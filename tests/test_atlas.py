from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from bson import ObjectId
from pymongo.errors import OperationFailure

from bganalyzer.analytics.calendar import day_bounds
from bganalyzer.config import AtlasConfig
from bganalyzer.contracts.domain import SyncCollection
from bganalyzer.nightscout.atlas import (
    AtlasClient,
    AtlasCoordinator,
    midnight_ms,
    normalize,
    validate_atlas_uri,
)
from bganalyzer.nightscout.client import NightscoutError
from bganalyzer.nightscout.sync import SyncStats
from bganalyzer.secrets import AtlasCredentialProvider


URI = "mongodb+srv://reader:synthetic@cluster.example.mongodb.net/?retryWrites=true"


class Cursor:
    def __init__(self, rows, fail=False):
        self.rows = rows
        self.closed = False
        self.fail = fail

    def max_time_ms(self, ms):
        assert ms == 30000
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def __iter__(self):
        yield from self.rows
        if self.fail:
            raise OperationFailure("sensitive server text must not escape", code=13)


class Collection:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []
        self.cursor = None

    def find(self, query, batch_size):
        self.calls.append((query, batch_size))
        self.cursor = Cursor(self.rows)
        return self.cursor


class Database:
    def __init__(self, collections):
        self.collections = collections

    def list_collection_names(self):
        return list(self.collections)

    def __getitem__(self, name):
        return self.collections[name]


def fake_client(monkeypatch, collections):
    class Client:
        def __init__(self, uri, **options):
            assert options["tls"] is True
            assert options["socketTimeoutMS"] == 15000
            self.closed = False

        def __getitem__(self, name):
            assert name == "Cluster0"
            return Database(collections)

        def close(self):
            self.closed = True

    monkeypatch.setattr("bganalyzer.nightscout.atlas.MongoClient", Client)
    config = AtlasConfig(database="Cluster0")
    return AtlasClient(config, URI)


def test_cursor_batches_bypass_http_exclusion_limit(monkeypatch):
    rows = [{"_id": ObjectId(), "date": 100, "sgv": 108} for _ in range(2501)]
    collection = Collection(rows)
    client = fake_client(monkeypatch, {"entries": collection})
    pages = list(client.pages("entries", 0, 200))
    assert [len(p) for p in pages] == [1000, 1000, 501]
    assert collection.calls == [({"date": {"$gte": 0, "$lt": 200}}, 1000)]
    assert pages[0][0]["_id"] == str(rows[0]["_id"])
    assert collection.cursor.closed
    client.close()


def test_missing_collection_is_not_successful_empty_history(monkeypatch):
    client = fake_client(monkeypatch, {})
    with pytest.raises(NightscoutError) as error:
        list(client.pages("entries", 0, 200))
    assert error.value.error_code == "ATLAS_COLLECTION"
    client.close()


def test_date_query_accepts_iso_and_bson_dates(monkeypatch):
    collection = Collection([])
    client = fake_client(monkeypatch, {"treatments": collection})
    list(client.pages("treatments", 0, 1000))
    expression = collection.calls[0][0]["$expr"]["$let"]
    assert expression["vars"]["event"]["$convert"]["input"] == "$created_at"
    assert expression["in"]["$and"][1]["$lt"][1] == datetime(
        1970, 1, 1, 0, 0, 1, tzinfo=timezone.utc
    )
    client.close()


def test_cancel_closes_cursor(monkeypatch):
    collection = Collection([{"_id": ObjectId(), "date": 100}])
    client = fake_client(monkeypatch, {"entries": collection})
    checks = iter([False, True])
    client.cancelled = lambda: next(checks)
    with pytest.raises(NightscoutError) as error:
        list(client.pages("entries", 0, 200))
    assert error.value.error_code == "CANCELLED"
    assert collection.cursor.closed
    client.close()


@pytest.mark.parametrize(
    "suffix",
    [
        "&tls=false",
        "&tlsInsecure=true",
        "&tlsAllowInvalidCertificates=true",
        "&tlsAllowInvalidHostnames=true",
    ],
)
def test_uri_cannot_disable_tls(suffix):
    with pytest.raises(ValueError):
        validate_atlas_uri(URI + suffix)


def test_normalization_matches_api_object_ids_and_dates():
    oid = ObjectId()
    assert normalize({"_id": oid, "nested": [datetime(2026, 1, 1, tzinfo=timezone.utc)]}) == {
        "_id": str(oid),
        "nested": ["2026-01-01T00:00:00.000Z"],
    }


def test_all_dates_use_atlas_and_are_idempotent(config, repo):
    calls = []

    class Atlas:
        def pages(self, collection, start, end, after_id=None):
            calls.append((start, end))
            yield [
                {"_id": "history", "date": 50, "sgv": 108},
                {"_id": "today", "date": 150, "sgv": 108},
            ]

    sync = AtlasCoordinator(config, repo, Atlas())
    for _ in range(2):
        sync._window("synthetic", SyncCollection.ENTRIES, 0, 200, SyncStats())
    assert len(repo.get_glucose_range("synthetic", 0, 200)) == 2
    assert calls == [(0, 200), (0, 200)]


def test_backfill_fetches_week_chunks_and_checkpoints_each_day(config, repo):
    import time

    from bganalyzer.nightscout.sync import DAY

    calls = []
    now = int(time.time() * 1000)
    start = now - 10 * DAY

    class Atlas:
        def pages(self, collection, start=None, end=None, after_id=None):
            calls.append((collection, start, end))
            if collection == "profile":
                return
                yield
            day = 86400000
            cursor = start
            while cursor < end:
                if collection == "entries":
                    yield [{"_id": f"e{cursor}", "date": cursor, "sgv": 108}]
                else:
                    iso = datetime.fromtimestamp(cursor / 1000, timezone.utc).isoformat()
                    yield [{"_id": f"c{cursor}", "created_at": iso}]
                cursor += day

    sync = AtlasCoordinator(config, repo, Atlas())
    stats = sync.initial_backfill("synthetic", days=10, force=True, start_ms=start)
    assert not stats.errors
    entries_calls = [c for c in calls if c[0] == "entries"]
    assert len(entries_calls) == 2  # 10 days in week-long chunks, not one scan per day
    assert len(repo.get_glucose_range("synthetic", start, now)) == 10
    assert sync.journal.missing("synthetic", "entries", start, now) == []

    # A repeat import skips completed days and rechecks only the recent span.
    calls.clear()
    rerun = sync.initial_backfill("synthetic", days=10, start_ms=start)
    assert not rerun.errors
    assert rerun.windows_skipped > 0
    assert len([c for c in calls if c[0] == "entries"]) == 1
    # Idempotent upserts: only the newly elapsed span adds records, nothing duplicates.
    assert len(repo.get_glucose_range("synthetic", start, now)) >= 10


def test_after_id_adds_indexed_bound_without_changing_plain_queries(monkeypatch):
    from datetime import timedelta

    rows = [{"_id": ObjectId(), "created_at": "2026-09-10T00:00:00.000Z"}]
    collection = Collection(rows)
    entries = Collection([])
    client = fake_client(monkeypatch, {"devicestatus": collection, "entries": entries})
    bound = ObjectId.from_datetime(datetime(2026, 9, 9, tzinfo=timezone.utc))
    list(client.pages("devicestatus", 0, 1000, bound))
    query = collection.calls[0][0]
    assert query["$and"][1] == {"_id": {"$gt": bound}}
    assert "$expr" in query["$and"][0]
    list(client.pages("entries", 0, 200, bound))
    assert entries.calls[0][0] == {"date": {"$gte": 0, "$lt": 200}, "_id": {"$gt": bound}}
    client.close()


def test_incremental_poll_fetches_only_new_ids_and_stores_cursor(config, repo):
    import json
    import time
    from datetime import timedelta

    from bganalyzer.contracts.domain import SyncCollection

    started = datetime.now(timezone.utc) - timedelta(minutes=10)
    docs = {}

    def add_doc(minutes, sgv):
        moment = started + timedelta(minutes=minutes)
        oid = ObjectId.from_datetime(moment)
        docs[str(oid)] = (oid, int(moment.timestamp() * 1000), sgv)

    for i in range(3):
        add_doc(i, 100 + i)
    add_doc(-120, 99)  # Outside the incremental ObjectId overlap but still in the day.
    bounds = []

    class Atlas:
        def pages(self, collection, start=None, end=None, after_id=None):
            bounds.append(after_id)
            if collection == "profile":
                return
                yield
            out = []
            for key in sorted(docs, key=lambda k: docs[k][0]):
                oid, ts, sgv = docs[key]
                if after_id is not None and oid <= after_id:
                    continue
                if start is not None and not (start <= ts < end):
                    continue
                if collection == "entries":
                    out.append({"_id": key, "date": ts, "sgv": sgv})
                else:
                    iso = datetime.fromtimestamp(ts / 1000, timezone.utc).isoformat()
                    out.append({"_id": key, "created_at": iso})
            yield out

    sync = AtlasCoordinator(config, repo, Atlas())
    first = sync.initial_backfill("synthetic", days=1, force=True, incremental=True)
    assert not first.errors
    assert all(bound is None for bound in bounds)
    state = repo.get_sync_state("synthetic", SyncCollection.ENTRIES)
    assert json.loads(state.cursor_json)["poll_ms"] > 0
    assert len(repo.get_glucose_range("synthetic", 0, int(time.time() * 1000))) == 4

    add_doc(3, 140)
    add_doc(4, 141)
    bounds.clear()
    first_cursor = json.loads(repo.get_sync_state("synthetic", SyncCollection.ENTRIES).cursor_json)
    second = sync.initial_backfill("synthetic", days=1, incremental=True)
    assert not second.errors
    assert any(bound is not None for bound in bounds)
    # Overlap refetches the recent three plus the two new ones; upserts dedupe.
    assert second.entries_fetched == 5
    assert len(repo.get_glucose_range("synthetic", 0, int(time.time() * 1000))) == 6
    second_cursor = json.loads(repo.get_sync_state("synthetic", SyncCollection.ENTRIES).cursor_json)
    assert second_cursor["poll_ms"] >= first_cursor["poll_ms"]


    from bganalyzer.db.connection import get_connection
    assert get_connection(config).execute("SELECT COUNT(*) FROM sync_disappearances WHERE resolved_ms IS NULL").fetchone()[0] == 0

def test_failed_poll_does_not_advance_cursor(config, repo):
    import json

    from bganalyzer.contracts.domain import SyncCollection
    from bganalyzer.nightscout.client import NightscoutError

    class Atlas:
        def pages(self, collection, start=None, end=None, after_id=None):
            if collection == "profile":
                return
                yield
            if collection == "devicestatus":
                raise NightscoutError("read failed", error_code="ATLAS_READ_FAILED")
            yield []

    sync = AtlasCoordinator(config, repo, Atlas())
    stats = sync.initial_backfill("synthetic", days=1, force=True, incremental=True)
    assert stats.error_codes and "ATLAS_READ_FAILED" in stats.error_codes
    assert repo.get_sync_state("synthetic", SyncCollection.DEVICESTATUS) is None or (
        "poll_ms"
        not in (repo.get_sync_state("synthetic", SyncCollection.DEVICESTATUS).cursor_json or "")
    )


def test_backfill_derives_inferred_activations_from_effective_notes(config, repo):
    import time

    from bganalyzer.db.connection import transaction
    from bganalyzer.nightscout.sync import DAY

    now = int(time.time() * 1000)
    start = now - 3 * DAY
    note_ms = start + 3600000
    iso = datetime.fromtimestamp(note_ms / 1000, timezone.utc).isoformat()
    note = {
        "_id": "note1",
        "created_at": iso,
        "eventType": "Note",
        "isValid": True,
        "originalCustomizedName": "P1",
        "originalTimeshift": 0,
        "originalPercentage": 100,
        "originalEnd": 0,
        "profileJson": {
            "timezone": "UTC",
            "units": "mg/dl",
            "dia": 6,
            "basal": [{"time": "00:00", "value": 1.0}],
            "carbratio": [{"time": "00:00", "value": 10}],
            "sens": [{"time": "00:00", "value": 50}],
        },
    }

    class Atlas:
        def pages(self, collection, start=None, end=None, after_id=None):
            if collection == "profile":
                return
                yield
            if collection == "treatments" and start <= note_ms < (end or 0):
                yield [note]
            else:
                yield []

    sync = AtlasCoordinator(config, repo, Atlas())
    stats = sync.initial_backfill("synthetic", days=3, force=True, start_ms=start)
    assert not stats.errors
    with transaction(config) as conn:
        rows = conn.execute(
            """SELECT a.start_ms,a.end_ms,a.certainty,a.origin FROM profile_activations a
            JOIN profile_versions p ON p.id=a.profile_version_id
            WHERE p.source_id='synthetic'"""
        ).fetchall()
    assert [(r[0], r[1], r[2], r[3]) for r in rows] == [
        (note_ms, None, "inferred", "effective_note")
    ]


def test_failed_history_cursor_does_not_commit_partial_window(config, repo):
    class HTTP:
        def fetch_entries(self, *args, **kwargs):
            pytest.fail("History must not request HTTP")

        fetch_treatments = fetch_devicestatus = fetch_entries

    class Atlas:
        def pages(self, *args):
            yield [{"_id": "history", "date": 50, "sgv": 108}]
            raise NightscoutError("read failed", error_code="ATLAS_READ_FAILED")

    sync = AtlasCoordinator(config, repo, Atlas())
    with pytest.raises(NightscoutError):
        sync._window("synthetic", SyncCollection.ENTRIES, 0, 100, SyncStats())
    assert not repo.get_glucose_range("synthetic", 0, 100)
    assert sync.journal.missing("synthetic", "entries", 0, 100) == [(0, 100)]


def test_atlas_secret_stays_out_of_config_and_is_source_bound(config, monkeypatch):
    monkeypatch.setattr("keyring.get_password", lambda *args: None)
    credentials = AtlasCredentialProvider(config)
    credentials.set_token(URI, persistent=False)
    config.save()
    assert URI not in (config.config_dir / "config.json").read_text()
    assert credentials.get_token() == URI
    config.atlas.database = "different"
    assert credentials.get_token() is None


@pytest.mark.parametrize(
    "day,hours", [(date(2026, 3, 29), 23), (date(2026, 10, 25), 25), (date(2026, 9, 10), 24)]
)
def test_local_day_boundaries(day, hours):
    lo, hi = day_bounds(day, "Europe/London")
    assert hi - lo == hours * 3600000
    now = datetime.fromtimestamp((lo + 3600000) / 1000, timezone.utc)
    assert midnight_ms("Europe/London", now) == lo


def test_database_errors_redact_server_text_and_close_cursor(monkeypatch):
    collection = Collection([])
    original_find = collection.find

    def failing_find(*args, **kwargs):
        cursor = original_find(*args, **kwargs)
        cursor.fail = True
        return cursor

    collection.find = failing_find
    client = fake_client(monkeypatch, {"entries": collection})
    with pytest.raises(NightscoutError) as error:
        list(client.pages("entries", 0, 200))
    assert error.value.error_code == "AUTH_FAILED"
    assert "sensitive" not in str(error.value)
    assert collection.cursor.closed
    client.close()


def test_delta_poll_does_not_mark_older_records_missing_or_certify_scope(config, repo):
    from bganalyzer.contracts.domain import SyncCollection
    from bganalyzer.nightscout.sync import SyncStats
    from bganalyzer.db.connection import get_connection
    from bganalyzer.db.sync_journal import SyncJournal
    coordinator = AtlasCoordinator(config, repo, None)
    old = {"_id": "older", "date": 100, "sgv": 100}
    new = {"_id": "newer", "date": 1200, "sgv": 120}
    coordinator._save_window("synthetic", SyncCollection.ENTRIES, [old], 0, 1000, SyncStats())
    stats = SyncStats()
    coordinator._save_window("synthetic", SyncCollection.ENTRIES, [new], 0, 2000, stats, complete_scan=False)
    conn = get_connection(config)
    assert conn.execute("SELECT COUNT(*) FROM sync_disappearances WHERE resolved_ms IS NULL").fetchone()[0] == 0
    assert stats.windows_completed == 0
    assert SyncJournal(config).missing("synthetic", "entries", 1000, 2000)
    # A genuine full scan still detects removal; later re-observation repairs it.
    coordinator._save_window("synthetic", SyncCollection.ENTRIES, [new], 0, 2000, SyncStats())
    assert conn.execute("SELECT COUNT(*) FROM sync_disappearances WHERE resolved_ms IS NULL").fetchone()[0] == 1
    coordinator._save_window("synthetic", SyncCollection.ENTRIES, [old, new], 0, 2000, SyncStats())
    assert conn.execute("SELECT COUNT(*) FROM sync_disappearances WHERE resolved_ms IS NULL").fetchone()[0] == 0
