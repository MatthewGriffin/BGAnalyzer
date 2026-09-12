import json
from datetime import datetime

from bganalyzer.timeline.basal_delivery import reported_basal_segments, temporary_basal_record


def record(start=0, duration=600000, name="tb", **payload):
    return {
        "remote_id": name,
        "revision_hash": "r",
        "event_ms": start,
        "payload_json": json.dumps(
            {
                "eventType": "Temp Basal",
                "isValid": True,
                "durationInMilliseconds": duration,
                **payload,
            }
        ),
    }


def profile(start=0, end=3600000, zone="UTC", schedule=None):
    return {
        "start_ms": start,
        "end_ms": end,
        "source_refs": [{"remote_id": "p", "revision_hash": "r"}],
        "profile": {"timezone": zone, "basal": schedule or [{"time": "00:00", "value": 1}]},
    }


def test_zero_absolute_and_serialized_percentage_offset():
    assert temporary_basal_record(record(absolute=0))["rate"] == 0
    assert temporary_basal_record(record(percent=0))["rate"] == 100
    assert temporary_basal_record(record(percent=-100))["rate"] == 0
    assert temporary_basal_record(record(rate=1))["issues"] == ["missing_or_invalid_explicit_rate"]
    assert temporary_basal_record(record(absolute=0, percent=0))["issues"] == [
        "ambiguous_rate_fields"
    ]


def test_precise_duration_and_end_id_not_used_as_nightscout_id():
    a = temporary_basal_record(record(duration=60001, absolute=1, endId="different-record"))
    assert a["end_ms"] == 60001
    assert a["pump_end_id"] == "different-record"
    result = reported_basal_segments(
        [record(start=-300000, duration=900001, absolute=0)], [profile()], 0, 900000
    )
    assert result["reported_rate_ms"] == 600001
    assert result["segments"][0]["rate_u_h"] == 0
    assert result["segments"][-1]["reason"] == "no_reported_temp_basal"
    assert result["delivery_verified"] is False


def test_profile_gap_and_schedule_change_split_percentage_rates():
    p = profile(schedule=[{"time": "00:00", "value": 1}, {"time": "00:05", "value": 2}])
    result = reported_basal_segments([record(percent=50)], [p], 0, 600000)
    assert [(s["start_ms"], s["rate_u_h"]) for s in result["segments"]] == [(0, 1.5), (300000, 3.0)]
    result = reported_basal_segments([record(absolute=1)], [profile(start=100000)], 0, 600000)
    assert result["segments"][0]["rate_u_h"] is None
    assert result["segments"][1]["profile_refs"] == p["source_refs"]


def test_overlaps_and_missing_duration_withheld():
    records = [record(absolute=1), record(start=100000, duration=200000, name="b", absolute=2)]
    result = reported_basal_segments(records, [profile()], 0, 600000)
    assert [s["reason"] for s in result["segments"]] == [
        "reported_rate_only",
        "overlapping_temp_basals",
        "reported_rate_only",
    ]
    broken = record(start=200000, duration=None, name="broken", absolute=1)
    result = reported_basal_segments([record(absolute=1), broken], [profile()], 0, 900000)
    assert result["segments"][-1]["reason"] == "invalid_or_incomplete_temp_basal"


def test_dst_repeated_hour_resolves_wall_clock_schedule_twice():
    start = int(datetime.fromisoformat("2026-10-25T00:00:00+00:00").timestamp() * 1000)
    end = start + 7200000
    p = profile(
        start, end, "Europe/London", [{"time": "00:00", "value": 1}, {"time": "01:30", "value": 2}]
    )
    result = reported_basal_segments([record(start, 7200000, percent=0)], [p], start, end)
    assert [s["rate_u_h"] for s in result["segments"]] == [1, 2, 1, 2]
    assert sum(s["end_ms"] - s["start_ms"] for s in result["segments"]) == 7200000


def test_suspend_prevents_unqualified_continuation():
    result = reported_basal_segments(
        [record(absolute=1), record(start=200000, name="s", eventType="Suspend")],
        [profile()],
        0,
        600000,
    )
    assert result["segments"][-1]["rate_u_h"] is None
    assert "pump_transition_unresolved" in result["records"][-1]["issues"]


def test_disappeared_upload_and_bad_duration_remain_unknown():
    r = record(absolute=1)
    r["presence_unknown"] = True
    result = reported_basal_segments([r], [profile()], 0, 600000)
    assert result["reported_rate_ms"] == 0
    for duration in (-1, True, 1.5, "60000"):
        assert (
            "invalid_duration"
            in temporary_basal_record(record(duration=duration, absolute=1))["issues"]
        )


def test_spring_clock_change_does_not_invent_nonexistent_hour():
    start = int(datetime.fromisoformat("2026-03-29T00:00:00+00:00").timestamp() * 1000)
    end = start + 7200000
    p = profile(
        start,
        end,
        "Europe/London",
        [
            {"time": "00:00", "value": 1},
            {"time": "01:30", "value": 2},
            {"time": "02:00", "value": 3},
        ],
    )
    result = reported_basal_segments([record(start, 7200000, percent=0)], [p], start, end)
    assert [s["rate_u_h"] for s in result["segments"]] == [1, 3]
    assert [s["end_ms"] - s["start_ms"] for s in result["segments"]] == [3600000, 3600000]


def test_effective_profile_switch_preserves_both_source_chains():
    a, b = profile(end=300000), profile(start=300000)
    b["profile"]["basal"][0]["value"] = 2
    b["source_refs"] = [{"remote_id": "new", "revision_hash": "r2"}]
    result = reported_basal_segments([record(percent=0)], [a, b], 0, 600000)
    assert [s["rate_u_h"] for s in result["segments"]] == [1, 2]
    assert result["segments"][1]["profile_refs"] == b["source_refs"]
    assert all(
        s["source_refs"] == [{"remote_id": "tb", "revision_hash": "r"}] for s in result["segments"]
    )
