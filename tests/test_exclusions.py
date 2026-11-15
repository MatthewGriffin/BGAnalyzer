from datetime import date
import json

from bganalyzer.db.connection import get_connection, close_connection
from bganalyzer.db.exclusions import set_day_exclusion, active_exclusions, overlapping_exclusions


def test_exclusions_persist_restore_and_respect_dst(config, repo):
    day = date(2026, 3, 29)
    set_day_exclusion(config, 'synthetic', day, 'Europe/London', 'Pod failure')
    close_connection()
    conn = get_connection(config)
    items = active_exclusions(conn, 'synthetic')
    assert len(items) == 1
    assert items[0]['end_ms'] - items[0]['start_ms'] == 23*3600000
    assert active_exclusions(conn, 'another-source') == []
    assert overlapping_exclusions(items, items[0]['end_ms'], items[0]['end_ms']+1) == []
    set_day_exclusion(config, 'synthetic', day, 'Europe/London', '', active=False)
    assert active_exclusions(conn, 'synthetic') == []
    assert conn.execute('SELECT reason FROM analysis_exclusions').fetchone()[0] == 'Pod failure'


def test_exclusion_removes_day_and_following_insulin_context_not_raw_data(config, repo):
    from bganalyzer.contracts.domain import ProfileVersion, GlucoseReading
    from bganalyzer.analytics.calendar import day_bounds
    from bganalyzer.autotune.orchestration import build_analysis_snapshot
    start, _ = day_bounds(date(2026, 9, 10), 'UTC')
    day_ms = 86400000
    repo.upsert_profile_version(ProfileVersion(
        source_id='synthetic', remote_id='p', revision_hash='r', profile_name='P',
        effective_from_ms=start-10*day_ms, timezone='UTC', units_original='mg/dl', content_hash='p',
        normalized_json=json.dumps({'dia': 6, 'peak': 75, 'basal': [{'time': '00:00', 'value': 1}],
            'carbratio': [{'time': '00:00', 'value': 7}], 'sens': [{'time': '00:00', 'value': 50}]})))
    for offset in range(5):
        repo.upsert_glucose(GlucoseReading(source_id='synthetic', remote_id=str(offset), revision_hash='r',
                                          event_ms=start+offset*day_ms+3600000, sgv_mgdl=100))
    conn = get_connection(config)
    before = build_analysis_snapshot(conn, 'synthetic', start, start+5*day_ms, 'UTC')
    assert len(before.analysis_days) == 5
    set_day_exclusion(config, 'synthetic', date(2026,9,12), 'UTC', 'Pod leaked')
    after = build_analysis_snapshot(conn, 'synthetic', start, start+5*day_ms, 'UTC')
    assert [d.date_ms for d in after.analysis_days] == [start, start+day_ms, start+4*day_ms]
    assert len(after.baseline_evidence['excluded_days']) == 2
    assert after.baseline_evidence['user_exclusions'][0]['reason'] == 'Pod leaked'
    assert conn.execute('SELECT count(*) FROM glucose').fetchone()[0] == 5
    set_day_exclusion(config, 'synthetic', date(2026,9,12), 'UTC', '', active=False)
    restored = build_analysis_snapshot(conn, 'synthetic', start, start+5*day_ms, 'UTC')
    assert len(restored.analysis_days) == 5


def test_blank_reason_does_not_create_exclusion(config, repo):
    import pytest
    with pytest.raises(ValueError):
        set_day_exclusion(config, 'synthetic', date(2026, 9, 12), 'UTC', '  ')
    assert active_exclusions(get_connection(config), 'synthetic') == []
