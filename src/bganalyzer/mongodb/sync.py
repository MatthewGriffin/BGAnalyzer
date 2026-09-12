"""MongoDB sync coordinator - replaces Nightscout sync with direct database access."""

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo
from decimal import Decimal

from bganalyzer.contracts.domain import (
    DeliveryStatus,
    DeviceStatusRecord,
    GlucoseReading,
    ProfileVersion,
    SyncCollection,
    SyncStateRecord,
    TreatmentEvent,
    TreatmentKind,
)
from bganalyzer.db.connection import transaction
from bganalyzer.db.sync_journal import SyncJournal
from bganalyzer.nightscout.client import NightscoutError

DAY = 86_400_000
MAX_EXCLUDED_IDS = 20


@dataclass
class SyncStats:
    entries_fetched: int = 0
    treatments_fetched: int = 0
    devicestatus_fetched: int = 0
    profiles_fetched: int = 0
    errors: list[str] = field(default_factory=list)
    error_codes: list[str] = field(default_factory=list)
    windows_completed: int = 0
    windows_skipped: int = 0
    records_changed: int = 0
    cancelled: bool = False
    run_id: str | None = None


def timestamp(value):
    if isinstance(value, bool):
        raise ValueError("Invalid timestamp")
    if isinstance(value, (int, float)):
        return int(value)
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Timestamp timezone is unknown")
    return int(dt.timestamp() * 1000)


def content_hash(record):
    return hashlib.sha256(
        json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def number(record, key):
    value = record.get(key)
    if value is None:
        return None
    result = Decimal(str(value))
    if not result.is_finite() or result < 0:
        raise ValueError("Invalid nonnegative quantity")
    return result


class MongoDBSyncCoordinator:
    def __init__(
        self, config, repository, client, cancelled=lambda: False, progress=lambda text: None
    ):
        self.config = config
        self.repository = repository
        self.client = client
        if client is not None:
            client.cancelled = cancelled
        self.cancelled = cancelled
        self.progress = progress
        self.journal = SyncJournal(config)
        self._profile_changed = False
        self._page_size = config.sync.page_size
        self._window_days = config.sync.window_days
        self._request_delay = config.sync.request_delay_seconds
        self._last_request_time = 0.0

    def _check_cancel(self):
        if self.cancelled():
            raise NightscoutError("Synchronization cancelled", error_code="CANCELLED")

    def _rate_limit(self):
        from bganalyzer.nightscout.client import interruptible_wait

        elapsed = time.monotonic() - self._last_request_time
        interruptible_wait(max(0, self._request_delay - elapsed), self.cancelled)
        self._last_request_time = time.monotonic()

    def _pages(self, fetch, start, end, depth=0, event_field="date", excluded_ids=None):
        """Bound ID filters before sending them: long URLs fail at reverse proxies."""
        if depth == 0:
            zone = ZoneInfo(self.config.ui.timezone)
            now = datetime.now(zone)
            midnight = int(
                now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000
            )
            scope = "today" if start >= midnight else "history"
            name = getattr(fetch, "__name__", "records").removeprefix("fetch_")
            self.progress(f"Reading {name}: MongoDB {scope}…")
        excluded = set(excluded_ids or ())
        self._check_cancel()
        self._rate_limit()
        records = fetch(start, end, self._page_size, excluded_ids=sorted(excluded))
        ids = self._validate_page(records, start, end, event_field, excluded)
        combined = ids | excluded
        more = len(combined) > MAX_EXCLUDED_IDS
        if records and not more:
            self._check_cancel()
            self._rate_limit()
            probe = fetch(start, end, 1, excluded_ids=sorted(combined))
            self._validate_page(probe, start, end, event_field, combined)
            more = bool(probe)
        if not more:
            yield records
        elif end - start <= 1:
            if len(combined) > MAX_EXCLUDED_IDS:
                raise NightscoutError(
                    "Too many same-timestamp records for bounded pagination",
                    error_code="INCOMPLETE_PAGE_BOUNDARY",
                )
            yield records
            yield from self._pages_id_pagination(fetch, start, end, combined, event_field)
        elif depth >= 40:
            raise NightscoutError(
                "Cannot resolve complete pagination boundary", error_code="INCOMPLETE_PAGE_BOUNDARY"
            )
        else:
            middle = (start + end) // 2
            yield from self._pages(fetch, start, middle, depth + 1, event_field, excluded)
            yield from self._pages(fetch, middle, end, depth + 1, event_field, excluded)

    @staticmethod
    def _validate_page(records, start, end, event_field, excluded):
        ids = set()
        for record in records:
            remote = record["_id"]
            if not isinstance(remote, str) or not remote or remote in ids:
                raise NightscoutError(
                    "Invalid or repeated record ID", error_code="INVALID_RECORD_ID"
                )
            if remote in excluded or not start <= timestamp(record[event_field]) < end:
                raise NightscoutError(
                    "ID or date filters were not honored", error_code="FILTER_IGNORED"
                )
            ids.add(remote)
        return ids

    def _pages_id_pagination(self, fetch, start, end, excluded_ids, event_field="date"):
        excluded_ids = set(excluded_ids)
        while True:
            self._check_cancel()
            if len(excluded_ids) > MAX_EXCLUDED_IDS:
                raise NightscoutError(
                    "Too many same-timestamp records for bounded pagination",
                    error_code="INCOMPLETE_PAGE_BOUNDARY",
                )
            self._rate_limit()
            records = fetch(
                start,
                end,
                min(self._page_size, MAX_EXCLUDED_IDS + 1 - len(excluded_ids)),
                excluded_ids=sorted(excluded_ids),
            )
            ids = self._validate_page(records, start, end, event_field, excluded_ids)
            if not records:
                break
            yield records
            excluded_ids.update(ids)

    @staticmethod
    def _map_treatment_kind(event_type, is_smb):
        if is_smb is True:
            return TreatmentKind.SMB
        return {
            "Temp Basal": TreatmentKind.TEMP_BASAL,
            "Meal Bolus": TreatmentKind.BOLUS,
            "Correction Bolus": TreatmentKind.BOLUS,
            "Bolus Wizard": TreatmentKind.BOLUS_WIZARD,
            "Carb Correction": TreatmentKind.CARBS,
            "Suspend": TreatmentKind.SUSPEND,
            "Resume": TreatmentKind.RESUME,
            "Profile Switch": TreatmentKind.PROFILE_SWITCH,
            "Temporary Target": TreatmentKind.TEMP_TARGET,
            "Site Change": TreatmentKind.SITE_CHANGE,
            "Insulin Change": TreatmentKind.INSULIN_CHANGE,
            "Exercise": TreatmentKind.EXERCISE,
            "Announcement": TreatmentKind.ANNOUNCEMENT,
        }.get(event_type, TreatmentKind.UNKNOWN)

    def _save(self, source, collection, data):
        remote = str(data["_id"])
        digest = content_hash(data)
        event = timestamp(
            data["date"] if collection == SyncCollection.ENTRIES else data["created_at"]
        )
        changed = self.repository.insert_raw_record(
            source, collection, remote, digest, event, None, data
        )
        returned = self.journal.seen(source, collection.value, remote, int(time.time() * 1000))
        changed = changed or returned
        common = dict(source_id=source, remote_id=remote, revision_hash=digest, event_ms=event)
        valid = data.get("isValid", True) is not False
        if collection == SyncCollection.ENTRIES:
            sgv = data.get("sgv")
            if data.get("type", "sgv") != "sgv" or sgv is None:
                with transaction(self.config) as conn:
                    conn.execute(
                        "UPDATE glucose SET valid=0 WHERE source_id=? AND remote_id=?",
                        (source, remote),
                    )
                return changed
            self.repository.upsert_glucose(
                GlucoseReading(**common, sgv_mgdl=sgv, valid=valid and sgv > 0)
            )
        elif collection == SyncCollection.TREATMENTS:
            kind = self._map_treatment_kind(data.get("eventType"), data.get("isSMB"))
            duration = data.get("durationInMilliseconds")
            if duration is None and data.get("duration") is not None:
                duration = float(data["duration"]) * 60_000
            if duration is not None and duration < 0:
                raise ValueError("Invalid duration")
            rate = (
                number(data, "absolute")
                if data.get("absolute") is not None
                else number(data, "rate")
            )
            self.repository.upsert_treatment(
                TreatmentEvent(
                    **common,
                    end_ms=event + int(duration) if duration is not None else None,
                    kind=kind,
                    insulin_u=number(data, "insulin"),
                    carbs_g=number(data, "carbs"),
                    rate_u_h=rate,
                    percent=number(data, "percent"),
                    valid=valid,
                    delivery_status=DeliveryStatus.UNKNOWN,
                    pump_event_key=str(data["pumpId"]) if data.get("pumpId") is not None else None,
                    attributes_json=json.dumps(data),
                )
            )
        else:
            self.repository.upsert_device_status(
                DeviceStatusRecord(
                    **common,
                    configuration_json=json.dumps(data.get("configuration") or {}),
                    loop_json=json.dumps(data.get("openaps") or {}),
                    quality_json=json.dumps({"valid": valid}),
                )
            )

        return changed

    def _window(self, source, collection, start, end, stats):
        fetch = {
            SyncCollection.ENTRIES: self.client.pages,
            SyncCollection.TREATMENTS: self.client.pages,
            SyncCollection.DEVICESTATUS: self.client.pages,
        }[collection]
        event_field = "date" if collection == SyncCollection.ENTRIES else "created_at"
        collection_name = collection.value
        records = [
            item
            for page in self._pages(lambda s, e, c, ei: fetch(collection_name, s, e), start, end, event_field=event_field)
            for item in page
        ]
        self._check_cancel()
        now = int(time.time() * 1000)
        changed = 0
        with transaction(self.config):
            seen = set()
            for record in records:
                self._check_cancel()
                if record["_id"] in seen:
                    raise NightscoutError(
                        "Repeated record across windows", error_code="FILTER_IGNORED"
                    )
                seen.add(record["_id"])
                changed += int(self._save(source, collection, record))
            changed += self.journal.reconcile(source, collection.value, start, end, seen, now)
            old = self.repository.get_sync_state(source, collection)
            self.repository.upsert_sync_state(
                SyncStateRecord(
                    source_id=source,
                    collection=collection,
                    backfill_start_ms=min(start, old.backfill_start_ms)
                    if old and old.backfill_start_ms is not None
                    else start,
                    backfill_end_ms=max(end, old.backfill_end_ms)
                    if old and old.backfill_end_ms is not None
                    else end,
                    last_success_ms=now,
                )
            )
            self.journal.record_window(
                source, collection.value, start, end, now, count=len(records)
            )
            if changed:
                self.journal.invalidate(
                    source, start, end, now, "clinical_records_or_presence_changed"
                )
        attr = {
            SyncCollection.ENTRIES: "entries_fetched",
            SyncCollection.TREATMENTS: "treatments_fetched",
            SyncCollection.DEVICESTATUS: "devicestatus_fetched",
        }[collection]
        setattr(stats, attr, getattr(stats, attr) + len(records))
        stats.records_changed += changed
        stats.windows_completed += 1

    def _sync_profiles(self, source):
        self._check_cancel()
        self._profile_changed = False
        records = self.client.fetch_profiles()
        count = 0
        with transaction(self.config):
            for data in records:
                self._check_cancel()
                digest = content_hash(data)
                event = timestamp(data.get("startDate") or data.get("date") or data["created_at"])
                changed = self.repository.insert_raw_record(
                    source, SyncCollection.PROFILE, str(data["_id"]), digest, event, None, data
                )
                self._profile_changed = self._profile_changed or changed
                for name, store in data["store"].items():
                    self.repository.upsert_profile_version(
                        ProfileVersion(
                            source_id=source,
                            remote_id=f"{data['_id']}:{name}",
                            revision_hash=digest,
                            profile_name=name,
                            effective_from_ms=event,
                            timezone=store.get("timezone", "unknown"),
                            units_original=store.get("units", "unknown"),
                            normalized_json=json.dumps(store),
                            content_hash=content_hash(store),
                        )
                    )
                    count += 1
            if self._profile_changed:
                now = int(time.time() * 1000)
                self.journal.invalidate(source, 0, now, now, "profile_store_changed")
        return count

    def initial_backfill(self, source_id, days=90, force=False, start_ms=None):
        if not 1 <= days <= 365:
            raise ValueError("Backfill days must be between 1 and 365")
        now = int(time.time() * 1000)
        start = now - days * DAY if start_ms is None else min(start_ms, now)
        stats = SyncStats()
        stats.run_id = self.journal.begin_run(source_id, start, now, now)
        try:
            self._check_cancel()
            stats.profiles_fetched = self._sync_profiles(source_id)
            stop = now
            day = 0
            window_ms = self._window_days * DAY
            while stop > start:
                lo = max(start, ((stop - 1) // window_ms) * window_ms)
                day += 1
                for collection in (
                    SyncCollection.ENTRIES,
                    SyncCollection.TREATMENTS,
                    SyncCollection.DEVICESTATUS,
                ):
                    self._check_cancel()
                    intervals = (
                        [(lo, stop)]
                        if force or stop > now - 2 * DAY
                        else self.journal.missing(
                            source_id, collection.value, lo, stop, checked_since=now - 7 * DAY
                        )
                    )
                    if not intervals:
                        stats.windows_skipped += 1
                    for begin, end in reversed(intervals):
                        self._check_cancel()
                        try:
                            self._window(source_id, collection, begin, end, stats)
                        except (NightscoutError, ValueError, KeyError, TypeError) as exc:
                            self._check_cancel()
                            code = (
                                exc.error_code
                                if isinstance(exc, NightscoutError)
                                else "MALFORMED_RECORD"
                            )
                            self.journal.record_window(
                                source_id,
                                collection.value,
                                begin,
                                end,
                                int(time.time() * 1000),
                                state="failed",
                                error=code,
                            )
                            stats.errors.append(
                                f"{collection.value}: {code}"
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
                                "MONGODB_READ_FAILED",
                                "MONGODB_COLLECTION",
                            ) or (
                                isinstance(exc, NightscoutError)
                                and exc.status_code is not None
                                and exc.status_code >= 500
                            ):
                                raise
                stop = lo
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
            self.journal.finish_run(stats.run_id, state, asdict(stats), int(time.time() * 1000))
        return stats

    def incremental_sync(self, source_id):
        return self.initial_backfill(source_id, days=2)