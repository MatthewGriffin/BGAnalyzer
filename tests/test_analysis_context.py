from datetime import date
from types import SimpleNamespace
import pytest
from bganalyzer.analytics.calendar import day_bounds
from bganalyzer.autotune.orchestration import _split_into_days
from bganalyzer.autotune.categorize import Treatment, TempBasal


def timeline(zone):
    resolved = SimpleNamespace(basal_schedule=[("00:00", 1)], ic_schedule=[("00:00", 10)],
                               isf_schedule=[("00:00", 50)], dia_hours=6, peak_minutes=75, timezone=zone)
    return SimpleNamespace(resolve_profile=lambda _: resolved)


@pytest.mark.parametrize("day,hours", [(date(2026,3,29),23), (date(2026,10,25),25)])
def test_local_days_follow_dst_without_duplicate_or_missing_glucose(day, hours):
    start, end = day_bounds(day, "Europe/London")
    glucose = [{"timestamp": t, "value": 120} for t in range(start, end, 300000)]
    days = _split_into_days(glucose, [], [], [], None, timeline("Europe/London"), None, start, end, "Europe/London")
    assert len(days) == 1
    assert len(days[0].glucose) == hours * 12
    assert days[0].date_ms == start


def test_pre_window_insulin_is_included_without_future_doses():
    start, end = day_bounds(date(2026,9,10), "UTC")
    context_start = start - 8 * 3600000
    doses = [Treatment(timestamp=t, amount=1) for t in (context_start-1, context_start, start-1, start, end)]
    temp = TempBasal(timestamp=context_start-1000, duration=2000, rate=1, is_absolute=True)
    result = _split_into_days([{"timestamp": start, "value": 120}], doses, [], [temp], None,
                              timeline("UTC"), None, start, end, "UTC")
    assert [t.timestamp for t in result[0].treatments] == [context_start, start-1, start]
    assert result[0].temp_basals == [temp]


def test_database_adapter_preserves_percent_and_pre_window_records(config, repo, monkeypatch):
    import json
    from bganalyzer.contracts.domain import ProfileVersion, TreatmentEvent, TreatmentKind
    from bganalyzer.db.connection import get_connection, transaction
    from bganalyzer.autotune.orchestration import build_analysis_snapshot
    start = 86400000
    repo.upsert_profile_version(ProfileVersion(source_id="synthetic", remote_id="p", revision_hash="r",
        profile_name="p", effective_from_ms=0, timezone="UTC", units_original="mg/dl", content_hash="h",
        normalized_json=json.dumps({"dia":6, "peak":75, "basal":[{"time":"00:00", "value":1}],
        "carbratio":[{"time":"00:00", "value":10}], "sens":[{"time":"00:00", "value":50}]})))
    for name, stamp, kind, end, percent in [
        ("bolus-before", start-60000, TreatmentKind.BOLUS, None, None),
        ("neutral", start, TreatmentKind.TEMP_BASAL, start+600000, 0),
        ("no-duration", start, TreatmentKind.TEMP_BASAL, None, None),
        ("gone", start+1, TreatmentKind.BOLUS, None, None),
    ]:
        repo.upsert_treatment(TreatmentEvent(source_id="synthetic", remote_id=name, revision_hash="r",
            event_ms=stamp, end_ms=end, kind=kind, insulin_u=1, rate_u_h=1, percent=percent))
    with transaction(config) as conn:
        conn.execute("INSERT INTO sync_disappearances(source_id,collection,remote_id,first_missing_ms) VALUES('synthetic','treatments','gone',100)")
    captured = {}
    def capture(glucose, treatments, carbs, temps, *args):
        captured.update(treatments=treatments, temps=temps)
        return []
    monkeypatch.setattr("bganalyzer.autotune.orchestration._split_into_days", capture)
    build_analysis_snapshot(get_connection(config), "synthetic", start, start+86400000, "UTC")
    assert [t.timestamp for t in captured["treatments"]] == [start-60000]
    assert len(captured["temps"]) == 1
    assert captured["temps"][0].rate == 100
    assert captured["temps"][0].is_absolute is False
