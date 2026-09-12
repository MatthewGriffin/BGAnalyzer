from decimal import Decimal

import pytest

from bganalyzer.contracts.domain import SyncCollection, TreatmentEvent, TreatmentKind
from bganalyzer.db.connection import get_connection, transaction
from bganalyzer.nightscout.sync import SyncCoordinator


class NoNetwork:
    pass


def test_atomic_nested_transactions(config, repo):
    with pytest.raises(RuntimeError):
        with transaction(config):
            repo.insert_raw_record("synthetic", SyncCollection.ENTRIES, "x", "one", 0, None, {})
            raise RuntimeError("rollback")
    assert get_connection(config).execute("SELECT count(*) FROM raw_records").fetchone()[0] == 0


def test_raw_revision_idempotency(config, repo):
    for rev in ["one", "one", "two", "two"]:
        repo.insert_raw_record(
            "synthetic",
            SyncCollection.ENTRIES,
            "x",
            rev,
            0,
            None,
            {"sgv": 100 if rev == "one" else 101},
        )
    conn = get_connection(config)
    assert conn.execute("SELECT count(*) FROM raw_records").fetchone()[0] == 2
    assert (
        conn.execute("SELECT revision_hash FROM raw_records WHERE is_current=1").fetchone()[0]
        == "two"
    )


def test_zero_basal_survives_roundtrip(repo):
    repo.upsert_treatment(
        TreatmentEvent(
            source_id="synthetic",
            remote_id="zero",
            revision_hash="r",
            event_ms=1,
            kind=TreatmentKind.TEMP_BASAL,
            rate_u_h=Decimal(0),
            percent=Decimal(0),
        )
    )
    tx = repo.get_treatments_range("synthetic", 0, 2)[0]
    assert tx.rate_u_h == Decimal(0)
    assert tx.percent == Decimal(0)


def test_real_profile_store_shape(config, repo):
    class Client:
        def fetch_profiles(self):
            return [
                {
                    "_id": "profile",
                    "startDate": "2026-01-01T00:00:00Z",
                    "store": {
                        "Weekday": {"units": "mmol", "timezone": "Europe/London", "basal": []},
                        "Weekend": {"units": "mmol", "timezone": "Europe/London", "basal": []},
                    },
                }
            ]

    sync = SyncCoordinator(config, repo, Client())
    assert sync._sync_profiles("synthetic") == 2
    assert {p.profile_name for p in repo.get_profile_versions("synthetic")} == {
        "Weekday",
        "Weekend",
    }


def test_invalid_correction_and_smb(config, repo):
    sync = SyncCoordinator(config, repo, NoNetwork())
    sync._save("synthetic", SyncCollection.ENTRIES, {"_id": "g", "date": 1000, "sgv": 100})
    sync._save(
        "synthetic",
        SyncCollection.ENTRIES,
        {"_id": "g", "date": 1000, "sgv": 100, "isValid": False},
    )
    assert not repo.get_glucose_range("synthetic", 0, 2000)[0].valid
    sync._save(
        "synthetic",
        SyncCollection.TREATMENTS,
        {
            "_id": "t",
            "created_at": "2026-01-01T00:00:00Z",
            "eventType": "Meal Bolus",
            "isSMB": True,
            "insulin": 0.1,
            "pumpId": 123,
        },
    )
    tx = repo.get_treatments_range("synthetic", 0, 2_000_000_000_000)[0]
    assert tx.kind == TreatmentKind.SMB
    assert tx.delivery_status.value == "unknown"


def test_full_page_subdivides(config, repo):
    config.sync.page_size = 50
    sync = SyncCoordinator(config, repo, NoNetwork())
    records = [{"_id": str(i), "date": i} for i in range(100)]
    calls = []

    def fetch(start, end, count, excluded_ids=None):
        calls.append((start, end))
        return [
            r for r in records if start <= r["date"] < end and r["_id"] not in (excluded_ids or [])
        ][:count]

    result = [r for page in sync._pages(fetch, 0, 100) for r in page]
    assert result == records
    assert (0, 50) in calls and (50, 100) in calls


def test_malformed_window_rolls_back(config, repo):
    from bganalyzer.nightscout.sync import SyncStats

    class Client:
        fetch_treatments = fetch_devicestatus = lambda *args, **kwargs: []

        def fetch_entries(self, *args, **kwargs):
            return [{"_id": "g", "date": 1, "sgv": 100}, {"_id": "bad", "date": 2}]

    sync = SyncCoordinator(config, repo, Client())
    # Missing SGV is kept raw but excluded, while a missing ID aborts the window.
    Client.fetch_entries = lambda *args, **kwargs: [
        {"_id": "g", "date": 1, "sgv": 100},
        {"date": 2, "sgv": 100},
    ]
    with pytest.raises(KeyError):
        sync._window("synthetic", SyncCollection.ENTRIES, 0, 10, SyncStats())
    assert repo.get_glucose_range("synthetic", 0, 10) == []
    assert repo.get_sync_state("synthetic", SyncCollection.ENTRIES) is None


def test_config_does_not_persist_secret(config):
    from bganalyzer.secrets import CredentialProvider
    credentials = CredentialProvider(config)
    credentials.set_token("synthetic-secret", persistent=False)
    config.save()
    text = (config.config_dir / "config.json").read_text()
    assert "synthetic-secret" not in text
    assert (config.config_dir / "config.json").stat().st_mode & 0o777 == 0o600
