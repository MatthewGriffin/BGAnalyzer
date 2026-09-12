import json
import pytest
from bganalyzer.analytics.explanation import build_report_explanation
from bganalyzer.analytics.metrics import calculate_tir_metrics
from bganalyzer.analytics.report import ReportSnapshot
from bganalyzer.contracts.domain import GlucoseReading


def reading(remote, minute, value, valid=True):
    return GlucoseReading(
        source_id="source",
        remote_id=remote,
        revision_hash="r1",
        event_ms=minute * 60000,
        sgv_mgdl=value,
        valid=valid,
    )


def report(readings):
    snapshot = ReportSnapshot(1, "source", 0, 30 * 60000, readings=readings)
    snapshot.metrics = calculate_tir_metrics(readings, 0, 30 * 60000)
    return snapshot


def test_contributions_reproduce_duration_mean_and_exclude_conflicts():
    snapshot = report(
        [
            reading("carry", -2, 90),
            reading("low", 5, 54),
            reading("duplicate-a", 10, 180),
            reading("duplicate-b", 10, 180),
            reading("conflict-a", 20, 100),
            reading("conflict-b", 20, 120),
            reading("invalid", 25, 50, False),
        ]
    )
    explanation = build_report_explanation(snapshot, "Europe/London")
    rows = explanation["contributions"]
    minutes = sum(row["minutes"] for row in rows)
    assert minutes == 13
    assert minutes == snapshot.metrics.covered_minutes
    assert sum(row["glucose_mgdl"] * row["minutes"] for row in rows) / minutes == pytest.approx(
        snapshot.metrics.mean_mgdl
    )
    assert rows[0]["start_ms"] == 0
    assert rows[0]["reading_ms"] == -120000
    assert not any(
        row["record_id"].startswith("conflict") or row["record_id"] == "invalid" for row in rows
    )
    assert "Missing time: 17.00 minutes" in explanation["text"]
    assert "Source ID: low" in explanation["text"]
    json.dumps(explanation)  # Export-ready including exact contributions.


def test_no_coverage_does_not_invent_percentages():
    explanation = build_report_explanation(report([]), "UTC")
    assert explanation["contributions"] == []
    assert "range percentages and mean glucose are unavailable" in explanation["text"]


def test_evidence_fingerprint_is_stable_and_changes_with_source_revision():
    snapshot = report([reading("one", 0, 100)])
    first = build_report_explanation(snapshot, "UTC")
    assert first["evidence_hash"] == build_report_explanation(snapshot, "UTC")["evidence_hash"]
    snapshot.readings[0].revision_hash = "corrected"
    assert first["evidence_hash"] != build_report_explanation(snapshot, "UTC")["evidence_hash"]


def test_empty_status_does_not_hide_last_configuration(config, repo):
    import json
    from bganalyzer.contracts.domain import DeviceStatusRecord
    from bganalyzer.analytics.report import load_report
    for stamp, conf in [(100, {"apsConfiguration": {"use_dynamic_sensitivity": False}}), (200, {})]:
        repo.upsert_device_status(DeviceStatusRecord(source_id="synthetic", remote_id=str(stamp), revision_hash="r", event_ms=stamp, configuration_json=json.dumps(conf)))
    result = load_report(config, 1, 0, 300)
    assert result.configuration_at_ms == 100
    assert result.configuration["apsConfiguration"]["use_dynamic_sensitivity"] is False
