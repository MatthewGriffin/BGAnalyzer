import json

import pytest

from bganalyzer.timeline.insulin_evidence import (
    insulin_configuration_evidence,
    insulin_configuration_observation,
)


def record(stamp=100, plugin=2, version="3.4.2.1", settings=None, **extra):
    return {
        "event_ms": stamp,
        "remote_id": str(stamp),
        "revision_hash": "r",
        "payload_json": json.dumps(
            {
                "configuration": {
                    "version": version,
                    "insulin": plugin,
                    "insulinConfiguration": settings or {},
                }
            }
        ),
        **extra,
    }


@pytest.mark.parametrize("plugin,peak", [(2, 75), (3, 55)])
def test_pinned_plugin_constants_have_explicit_provenance(plugin, peak):
    o = insulin_configuration_observation(record(plugin=plugin))
    assert o["peak_minutes"] == peak
    assert o["peak_origin"] == "pinned_plugin_constant"
    assert not o["issues"]
    assert "dia_hours" not in o


def test_free_peak_requires_uploaded_setting_never_preference_default():
    o = insulin_configuration_observation(record(plugin=4))
    assert o["peak_minutes"] is None
    assert "missing_or_invalid_uploaded_peak" in o["issues"]
    o = insulin_configuration_observation(record(plugin=4, settings={"insulin_oref_peak": 65}))
    assert o["peak_minutes"] == 65
    assert o["peak_origin"].startswith("uploaded_")


@pytest.mark.parametrize("peak", [None, True, "75", 34, 121, 75.0])
def test_malformed_peak_withheld(peak):
    assert (
        insulin_configuration_observation(record(plugin=4, settings={"insulin_oref_peak": peak}))[
            "peak_minutes"
        ]
        is None
    )


@pytest.mark.parametrize("version", [None, "3.4.2.0", "3.4.2.1-custom"])
def test_unknown_version_does_not_borrow_pinned_constant(version):
    o = insulin_configuration_observation(record(version=version))
    assert o["peak_minutes"] is None
    assert "unsupported_aaps_version" in o["issues"]


def test_disappeared_or_invalid_upload_does_not_yield_settings():
    assert insulin_configuration_observation(record(presence_unknown=True))["peak_minutes"] is None
    r = record()
    payload = json.loads(r["payload_json"])
    payload["isValid"] = False
    r["payload_json"] = json.dumps(payload)
    assert insulin_configuration_observation(r)["issues"] == ["invalid_or_disappeared_upload"]


def test_only_nearest_preceding_nonempty_configuration_is_retained():
    empty = record(90)
    empty["payload_json"] = '{"configuration": {}}'
    result = insulin_configuration_evidence(
        [record(10), record(80), empty, record(150), record(200)], 100, 200
    )
    assert [o["event_ms"] for o in result["observations"]] == [80, 150]
    assert result["historical_activation_verified"] is False


def test_invalid_preceding_upload_never_falls_back_to_old_valid_settings():
    result = insulin_configuration_evidence(
        [record(10), record(80, presence_unknown=True)], 100, 200
    )
    assert len(result["observations"]) == 1
    assert result["resolved_peak_observations"] == 0


def test_simultaneous_conflicts_withheld_identical_uploads_keep_refs():
    a, b = record(), record()
    b["remote_id"] = "b"
    result = insulin_configuration_evidence([a, b], 0, 200)
    assert result["resolved_peak_observations"] == 2
    b = record(plugin=3)
    b["remote_id"] = "b"
    result = insulin_configuration_evidence([a, b], 0, 200)
    assert result["resolved_peak_observations"] == 0
    assert result["issue_counts"] == {"conflicting_simultaneous_configuration": 2}


def test_readiness_uses_current_raw_configuration_and_disappearance(config, repo):
    from types import SimpleNamespace
    from bganalyzer.analytics.basal_recommendations import (
        build_basal_recommendations,
        format_readiness,
    )
    from bganalyzer.contracts.domain import SyncCollection
    from bganalyzer.db.connection import transaction

    for stamp, plugin in [(10, 2), (80, 4), (150, 3)]:
        r = record(stamp, plugin=plugin, settings={"insulin_oref_peak": 65})
        repo.insert_raw_record(
            "synthetic",
            SyncCollection.DEVICESTATUS,
            r["remote_id"],
            "r",
            stamp,
            None,
            json.loads(r["payload_json"]),
        )
    with transaction(config) as conn:
        conn.execute(
            "INSERT INTO sync_disappearances(source_id,collection,remote_id,first_missing_ms) VALUES('synthetic','devicestatus','150',180)"
        )
    result = build_basal_recommendations(
        SimpleNamespace(source_id="synthetic", start_ms=100, end_ms=200, data_revision=0),
        config,
        "UTC",
    )
    evidence = result["insulin_configuration_evidence"]
    assert [o["event_ms"] for o in evidence["observations"]] == [80, 150]
    assert evidence["resolved_peak_observations"] == 1
    assert evidence["issue_counts"] == {"invalid_or_disappeared_upload": 1}
    assert "record 150" in format_readiness(result)
    assert result["recommendations"] == []
