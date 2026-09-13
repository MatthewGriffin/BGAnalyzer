import json
from bganalyzer.analytics.uploaded_iob import uploaded_iob_observations


def record(name, stamp, value, **extra):
    return {"remote_id": name, "revision_hash": "revision", "is_valid": True,
            "iob_json": json.dumps({"time": stamp, "iob": value}), **extra}


def test_signed_zero_duplicates_and_conflicts_are_preserved():
    result = uploaded_iob_observations([
        record("negative", 100, -0.5), record("zero", 200, 0),
        record("a", 300, 1), record("b", 300, 1),
        record("c", 400, 1), record("d", 400, 2),
    ], 0, 500)
    assert [o["iob_u"] for o in result] == [-0.5, 0.0, 1.0, None]
    assert len(result[2]["source_refs"]) == 2
    assert result[3]["status"] == "invalid_or_conflicting"


def test_invalid_disappeared_values_are_barriers_and_no_model_is_guessed():
    result = uploaded_iob_observations([
        record("invalid", 100, 1, is_valid=False),
        record("gone", 200, 1, presence_unknown=True),
        record("string", 300, "1"), record("bool", 400, True),
        record("nan", 500, float("nan")),
    ], 0, 600)
    assert len(result) == 5
    assert all(o["iob_u"] is None for o in result)
    assert uploaded_iob_observations([], 0, 600) == []


def test_sample_time_is_authoritative_and_requires_timezone():
    result = uploaded_iob_observations([
        record("inside", "1970-01-01T01:00:01+01:00", 1),
        record("end", "1970-01-01T00:00:02Z", 2),
        record("ambiguous", "1970-01-01T00:00:01", 3),
    ], 0, 2000)
    assert [o["sample_ms"] for o in result] == [1000]


def test_cache_reads_uploaded_iob_independently_of_treatment_display(config, repo):
    from bganalyzer.contracts.domain import SyncCollection
    from bganalyzer.analytics.report import load_report
    from bganalyzer.db.connection import transaction
    for name, stamp, value in [("a", 100, 1.2), ("b", 200, -0.3)]:
        repo.insert_raw_record("synthetic", SyncCollection.DEVICESTATUS, name, "r", 9999, None,
                               {"openaps": {"iob": {"time": stamp, "iob": value}}})
    report = load_report(config, 1, 0, 500)
    assert report.treatments == []
    assert report.iob_points == [(100, 1.2), (200, -0.3)]
    with transaction(config) as conn:
        conn.execute("INSERT INTO sync_disappearances(source_id,collection,remote_id,first_missing_ms) VALUES('synthetic','devicestatus','b',300)")
    assert load_report(config, 2, 0, 500).iob_points[-1] == (200, None)


def test_graph_worker_uses_selected_day_iob(qtbot, config, repo):
    from bganalyzer.contracts.domain import SyncCollection
    from bganalyzer.ui.workers import ReportWorker
    day = 86400000
    for stamp in (100, day + 100):
        repo.insert_raw_record("synthetic", SyncCollection.DEVICESTATUS, str(stamp), "r", stamp, None,
                               {"openaps": {"iob": {"time": stamp, "iob": 0}}})
    worker = ReportWorker(config, 1, 0, 2 * day, graph_bounds=(day, 2 * day))
    result = []
    worker.result.connect(result.append)
    with qtbot.waitSignal(worker.finished, timeout=10000):
        worker.start()
    assert result[0].iob_points == [(day + 100, 0.0)]
    worker.deleteLater()
