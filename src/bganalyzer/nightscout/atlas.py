"""Read-only MongoDB cursor imports for current and historical data."""

from bisect import bisect_right
from dataclasses import asdict
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit, parse_qs
import time as systime

from bson import ObjectId, Decimal128
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from bganalyzer.contracts.domain import SyncCollection, SyncStateRecord
from bganalyzer.db.sync_journal import SyncJournal
from bganalyzer.nightscout.client import NightscoutError
from bganalyzer.nightscout.sync import DAY, SyncCoordinator, SyncStats, timestamp


def midnight_ms(zone, now=None):
    now = now or datetime.now(ZoneInfo(zone))
    return int(
        datetime.combine(now.astimezone(ZoneInfo(zone)).date(), time(), ZoneInfo(zone)).timestamp()
        * 1000
    )


def validate_atlas_uri(uri):
    try:
        parts = urlsplit(uri)
        options = {k.lower(): v for k, v in parse_qs(parts.query).items()}
        if (
            parts.scheme != "mongodb+srv"
            or not parts.hostname
            or not parts.hostname.endswith(".mongodb.net")
        ):
            raise ValueError()
        if not parts.username or not parts.password or parts.fragment:
            raise ValueError()
        for key in ("tlsinsecure", "tlsallowinvalidcertificates", "tlsallowinvalidhostnames"):
            if any(v.lower() != "false" for v in options.get(key, [])):
                raise ValueError()
        for key in ("tls", "ssl"):
            if any(v.lower() != "true" for v in options.get(key, [])):
                raise ValueError()
    except ValueError:
        raise ValueError(
            "Enter an Atlas mongodb+srv URI with credentials and verified TLS."
        ) from None
    return uri


def normalize(value):
    """Match Nightscout JSON representations so IDs/revisions share one local source."""
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return (
            value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        )
    if isinstance(value, Decimal128):
        return str(value.to_decimal())
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize(v) for v in value]
    return value


class AtlasClient:
    def __init__(self, config, uri, cancelled=lambda: False):
        if not uri:
            raise NightscoutError(
                "Enter the Atlas connection URI in Connection.", error_code="AUTH_REQUIRED"
            )
        self.client = None
        try:
            if not config.database:
                raise ValueError()
            validate_atlas_uri(uri)
            self.client = MongoClient(
                uri,
                tls=True,
                tz_aware=True,
                serverSelectionTimeoutMS=10000,
                connectTimeoutMS=10000,
                socketTimeoutMS=15000,
                timeoutMS=30000,
                maxPoolSize=2,
                appname="BGAnalyzer",
            )
            self.database = self.client[config.database]
        except (ValueError, PyMongoError):
            if self.client is not None:
                self.client.close()
            raise NightscoutError(
                "Check Atlas connection settings.", error_code="ATLAS_CONFIG"
            ) from None
        self.config = config
        self.cancelled = cancelled
        self._verified = set()

    def pages(self, collection, start=None, end=None, after_id=None):
        if self.cancelled():
            raise NightscoutError("Synchronization cancelled", error_code="CANCELLED")
        name = getattr(self.config, collection)
        try:
            # Missing/misspelled collections must not become successful empty windows.
            if name not in self._verified:
                if name not in self.database.list_collection_names():
                    raise NightscoutError(
                        "Configured Atlas collection does not exist.", error_code="ATLAS_COLLECTION"
                    )
                self._verified.add(name)
            field = "date" if collection == "entries" else "created_at"
            query = {}
            if start is not None:
                if field == "date":
                    query = {field: {"$gte": start, "$lt": end}}
                else:
                    lo = datetime.fromtimestamp(start / 1000, timezone.utc)
                    hi = datetime.fromtimestamp(end / 1000, timezone.utc)
                    # Compare instants, not ISO text: offsets and fractional-second
                    # spellings can otherwise silently exclude records at day boundaries.
                    query = {
                        "$expr": {
                            "$let": {
                                "vars": {
                                    "event": {
                                        "$convert": {
                                            "input": "$created_at",
                                            "to": "date",
                                            "onError": None,
                                            "onNull": None,
                                        }
                                    }
                                },
                                "in": {
                                    "$and": [{"$gte": ["$$event", lo]}, {"$lt": ["$$event", hi]}]
                                },
                            }
                        }
                    }
            if after_id is not None:
                # _id is indexed while the $expr conversion is not: bounding
                # recent polls to documents inserted after a known point turns
                # a full collection scan into an index range plus filter.
                id_bound = {"_id": {"$gt": after_id}}
                if "$expr" in query:
                    query = {"$and": [query, id_bound]}
                else:
                    query = {**query, **id_bound}
            with self.database[name].find(query, batch_size=1000).max_time_ms(30000) as cursor:
                page = []
                for record in cursor:
                    if self.cancelled():
                        raise NightscoutError("Synchronization cancelled", error_code="CANCELLED")
                    page.append(normalize(record))
                    if len(page) == 1000:
                        yield page
                        page = []
                if page:
                    yield page
        except PyMongoError as exc:
            code = "AUTH_FAILED" if getattr(exc, "code", None) in (13, 18) else "ATLAS_READ_FAILED"
            raise NightscoutError(
                "Atlas read failed; check database permissions and network access.", error_code=code
            ) from None

    def close(self):
        self.client.close()


class AtlasCoordinator(SyncCoordinator):
    """MongoDB is the sole remote source for all requested intervals."""

    # One remote query per chunk instead of one per day: the treatments and
    # devicestatus filters convert stored timestamps server-side and cannot
    # use an index, so each query scans the whole collection. Fetching the
    # requested range in week-long chunks keeps the scan count (and memory)
    # bounded while journaling still checkpoints every day window.
    FETCH_CHUNK_MS = 7 * DAY

    def __init__(self, config, repository, client, **kwargs):
        super().__init__(config, repository, client, **kwargs)
        self._window_days = 1

    # Overlap kept when bounding incremental polls to inserted-document ids:
    # ObjectIds embed creation time, so _id tells insertion order, but a
    # document committed mid-scan can be missed and only its id proves it is
    # new. Refetching the last hour covers mid-scan commits and plausible
    # uploader clock skew; anything older was covered by the scan that stored
    # the cursor. A poll that itself runs longer than the overlap does not
    # advance the cursor.
    INCREMENTAL_OVERLAP_MS = 3600000

    def _check_connection(self):
        self._check_cancel()  # Collection reads verify connectivity and permissions.

    def _read_poll_cursor(self, source_id, collection_name):
        """Milliseconds of the last fully successful poll start, if any."""
        import json

        state = self.repository.get_sync_state(source_id, SyncCollection(collection_name))
        if state is None:
            return None
        try:
            value = json.loads(state.cursor_json or "{}").get("poll_ms")
        except (ValueError, TypeError):
            return None
        return value if isinstance(value, int) and value > 0 else None

    def _store_poll_cursor(self, source_id, collection, poll_ms, now_ms):
        """Record a fully successful poll start without touching backfill bounds."""
        import json

        state = self.repository.get_sync_state(source_id, collection)
        self.repository.upsert_sync_state(
            SyncStateRecord(
                source_id=source_id,
                collection=collection,
                cursor_json=json.dumps({"poll_ms": poll_ms}, sort_keys=True),
                backfill_start_ms=state.backfill_start_ms if state else None,
                backfill_end_ms=state.backfill_end_ms if state else None,
                last_success_ms=now_ms,
            )
        )

    def _incremental_after_id(self, source_id, collection_name, poll_start_ms):
        """Indexed lower bound for polls, or None for a full scan.

        Nightscout assigns ObjectIds at document creation, so ids increase
        with insertion order. Bounding to ids created after (last successful
        poll minus overlap) lets MongoDB use the always-present _id index
        instead of scanning the collection for the timestamp conversion.
        """
        last = self._read_poll_cursor(source_id, collection_name)
        if last is None:
            return None
        from datetime import datetime as _datetime

        return ObjectId.from_datetime(
            _datetime.fromtimestamp(max(0, last - self.INCREMENTAL_OVERLAP_MS) / 1000, timezone.utc)
        )

    def _fetch_profiles(self):
        self.progress("Reading profile stores: MongoDB…")
        return [record for page in self.client.pages("profile") for record in page]

    def _collection_pages(self, collection, start, end):
        name = collection.value
        scope = "today" if start >= midnight_ms(self.config.ui.timezone) else "history"
        self.progress(f"Reading {name}: MongoDB {scope}…")
        field = "date" if name == "entries" else "created_at"
        for page in self.client.pages(name, start, end):
            self._check_cancel()
            self._validate_page(page, start, end, field, set())
            yield page

    def initial_backfill(self, source_id, days=90, force=False, start_ms=None, incremental=False):
        """Same checkpoints as the base loop, fewer collection scans.

        The base implementation re-queries the remote collection once per day
        window; with server-side timestamp conversion every query scans the
        whole collection. This override fetches each requested span once (in
        week-long chunks) and then persists the identical per-day windows, so
        coverage journaling, reconciliation and resume points are unchanged.

        incremental marks the every-minute today poll: when a previous fully
        successful poll left a cursor, chunk queries are additionally bounded
        to documents inserted since (cursor minus overlap) so MongoDB can use
        the _id index instead of scanning. Manual and forced imports always
        scan fully, which also picks up in-place server edits of old records.
        """
        if not 1 <= days <= 365:
            raise ValueError("Backfill days must be between 1 and 365")
        now = int(systime.time() * 1000)
        start = now - days * DAY if start_ms is None else min(start_ms, now)
        stats = SyncStats(requested_end_ms=now)
        stats.run_id = self.journal.begin_run(source_id, start, now, now)
        try:
            self._check_cancel()
            self._check_connection()
            self._check_cancel()
            try:
                stats.profiles_fetched = self._sync_profiles(source_id)
            except (NightscoutError, ValueError, KeyError, TypeError) as exc:
                self._check_cancel()
                code = exc.error_code if isinstance(exc, NightscoutError) else "MALFORMED_RECORD"
                stats.errors.append(f"Profile history: {code}")
                stats.error_codes.append(code)
                if code in ("AUTH_FAILED", "AUTH_REQUIRED", "NETWORK_ERROR", "RATE_LIMITED") or (
                    isinstance(exc, NightscoutError)
                    and exc.status_code is not None
                    and exc.status_code >= 500
                ):
                    raise
            for collection in (
                SyncCollection.ENTRIES,
                SyncCollection.TREATMENTS,
                SyncCollection.DEVICESTATUS,
            ):
                self._check_cancel()
                clean = self._sync_collection_range(
                    source_id, collection, start, now, force, stats, incremental
                )
                if incremental and clean:
                    # Only fast, fully successful polls advance the cursor: the
                    # overlap argument covers mid-scan commits only when the
                    # poll itself ran for less than the overlap.
                    finished_ms = int(systime.time() * 1000)
                    if finished_ms - now < self.INCREMENTAL_OVERLAP_MS:
                        self._store_poll_cursor(source_id, collection, now, finished_ms)
            self._derive_activation_evidence(source_id, now, stats)
        except NightscoutError as exc:
            if exc.error_code == "CANCELLED":
                stats.cancelled = True
            elif exc.error_code not in stats.error_codes:
                stats.errors.append(
                    f"Connection: {exc.error_code}"
                    + (f" (HTTP {exc.status_code})" if exc.status_code else "")
                )
                stats.error_codes.append(exc.error_code)
        except Exception:
            stats.errors.append("Import stopped: unexpected local error")
            stats.error_codes.append("LOCAL_ERROR")
        finally:
            state = "cancelled" if stats.cancelled else "partial" if stats.errors else "complete"
            self.journal.finish_run(stats.run_id, state, asdict(stats), int(systime.time() * 1000))
        return stats

    def _day_intervals(self, source_id, collection_name, start, now, force):
        """Wanted fetch intervals, newest first, with skips counted.

        Replicates the base loop's day boundaries and its choice between a
        full day window (forced or recent) and recorded missing sub-intervals.
        Days needing no fetch are counted as skipped, exactly as the base.
        """
        wanted = []
        skipped = 0
        window_ms = self._window_days * DAY
        stop = now
        while stop > start:
            lo = max(start, ((stop - 1) // window_ms) * window_ms)
            self._check_cancel()
            if force or stop > now - 2 * DAY:
                wanted.append((lo, stop))
            else:
                missing = self.journal.missing(
                    source_id, collection_name, lo, stop, checked_since=now - 7 * DAY
                )
                if not missing:
                    skipped += 1
                # Newest sub-interval first, matching the base traversal order.
                wanted.extend(reversed(missing))
            stop = lo
        return wanted, skipped

    @staticmethod
    def _merge_spans(intervals):
        """Merge overlapping or adjacent half-open intervals (ascending out)."""
        merged = []
        for begin, end in sorted(intervals):
            if merged and begin <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([begin, end])
        return [(begin, end) for begin, end in merged]

    def _split_chunks(self, spans):
        """Split fetch spans into bounded chunks to cap memory per query."""
        chunks = []
        for begin, end in spans:
            cursor = begin
            while cursor < end:
                stop = min(end, cursor + self.FETCH_CHUNK_MS)
                chunks.append((cursor, stop))
                cursor = stop
        return chunks

    def _sync_collection_range(
        self, source_id, collection, start, now, force, stats, incremental=False
    ):
        name = collection.value
        wanted, skipped = self._day_intervals(source_id, name, start, now, force)
        stats.windows_skipped += skipped
        # Defensive dedupe; days and missing gaps are disjoint by construction.
        wanted = list(dict.fromkeys(wanted))
        if not wanted:
            return True
        after_id = (
            self._incremental_after_id(source_id, name, now) if incremental and not force else None
        )
        field = "date" if name == "entries" else "created_at"
        wanted_asc = sorted(wanted)
        starts = [begin for begin, _ in wanted_asc]

        def bucket_index(ts):
            i = bisect_right(starts, ts) - 1
            if 0 <= i < len(wanted_asc) and wanted_asc[i][0] <= ts < wanted_asc[i][1]:
                return i
            return None

        chunks = self._split_chunks(self._merge_spans(wanted))
        # A wanted interval is persisted once every chunk overlapping it has
        # been fetched; failed chunks mark their intervals failed instead.
        pending = {
            interval: sum(1 for (clo, chi) in chunks if clo < interval[1] and interval[0] < chi)
            for interval in wanted
        }
        buckets: dict[tuple[int, int], list] = {interval: [] for interval in wanted}
        failed: set[tuple[int, int]] = set()
        saw_failure = False

        for clo, chi in chunks:
            self._check_cancel()
            scope = "today" if clo >= midnight_ms(self.config.ui.timezone) else "history"
            self.progress(f"Reading {name}: MongoDB {scope}…")
            chunk_ok = True
            fetched = 0
            try:
                for page_number, page in enumerate(self.client.pages(name, clo, chi, after_id)):
                    self._check_cancel()
                    self._validate_page(page, clo, chi, field, set())
                    fetched += len(page)
                    if page_number % 5 == 4:
                        self.progress(f"Reading {name}: MongoDB {scope}… ({fetched} records)")
                    for record in page:
                        i = bucket_index(timestamp(record[field]))
                        if i is None:
                            raise NightscoutError(
                                "ID or date filters were not honored",
                                error_code="FILTER_IGNORED",
                            )
                        buckets[wanted_asc[i]].append(record)
            except (NightscoutError, ValueError, KeyError, TypeError) as exc:
                self._check_cancel()
                code = exc.error_code if isinstance(exc, NightscoutError) else "MALFORMED_RECORD"

                chunk_ok = False
                saw_failure = True
                for interval in wanted:  # newest first, like the base traversal
                    begin, end = interval
                    if end <= clo or begin >= chi or interval in failed:
                        continue
                    if pending[interval] <= 0:
                        continue
                    failed.add(interval)
                    pending[interval] = 0
                    self.journal.record_window(
                        source_id,
                        name,
                        begin,
                        end,
                        int(systime.time() * 1000),
                        state="failed",
                        error=code,
                    )
                    stats.errors.append(
                        f"{name}: {code}"
                        + (
                            f" (HTTP {exc.status_code})"
                            if isinstance(exc, NightscoutError) and exc.status_code
                            else ""
                        )
                        + f"; incomplete window {begin}–{end}"
                    )
                    stats.error_codes.append(code)
                if code in (
                    "AUTH_FAILED",
                    "AUTH_REQUIRED",
                    "NETWORK_ERROR",
                    "RATE_LIMITED",
                    "ATLAS_READ_FAILED",
                    "ATLAS_COLLECTION",
                ) or (
                    isinstance(exc, NightscoutError)
                    and exc.status_code is not None
                    and exc.status_code >= 500
                ):
                    raise
            if not chunk_ok:
                continue
            for interval in wanted:  # newest first, like the base traversal
                begin, end = interval
                if end <= clo or begin >= chi or interval in failed:
                    continue
                pending[interval] -= 1
                if pending[interval] <= 0:
                    self._save_window(
                        source_id,
                        collection,
                        buckets[interval],
                        begin,
                        end,
                        stats,
                        complete_scan=after_id is None,
                    )
        return not saw_failure
