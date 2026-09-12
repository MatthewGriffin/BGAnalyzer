"""Derived inferred activation evidence from effective-profile uploads."""

import json

from bganalyzer.contracts.domain import SyncCollection
from bganalyzer.db.connection import transaction
from bganalyzer.timeline.profile_evidence import derive_effective_activations

DAY = 86400000
START = 1780000000000 - (1780000000000 % DAY)


def profile(value=1.0, zone="UTC"):
    return {
        "timezone": zone,
        "units": "mg/dl",
        "dia": 6,
        "basal": [{"time": "00:00", "value": value}],
        "carbratio": [{"time": "00:00", "value": 10}],
        "sens": [{"time": "00:00", "value": 50}],
    }


def note(name, value=1.0, end=0, percent=100, ic=10, isf=50):
    payload = {
        "eventType": "Note",
        "isValid": True,
        "originalCustomizedName": name,
        "originalTimeshift": 0,
        "originalPercentage": percent,
        "originalEnd": end,
        "profileJson": profile(value),
    }
    payload["profileJson"]["carbratio"] = [{"time": "00:00", "value": ic}]
    payload["profileJson"]["sens"] = [{"time": "00:00", "value": isf}]
    return payload


def insert_note(repo, remote, stamp, payload):
    repo.insert_raw_record("synthetic", SyncCollection.TREATMENTS, remote, "r", stamp, None, payload)


def activation_rows(config):
    with transaction(config) as conn:
        return conn.execute(
            """SELECT a.start_ms,a.end_ms,a.certainty,a.origin,a.evidence_json,p.remote_id,p.normalized_json
            FROM profile_activations a JOIN profile_versions p ON p.id=a.profile_version_id
            WHERE p.source_id='synthetic' ORDER BY a.start_ms"""
        ).fetchall()


def test_two_notes_derive_versions_and_open_trailing_activation(config, repo):
    insert_note(repo, "n1", START, note("P1", value=1.0))
    insert_note(repo, "n2", START + DAY, note("P1", value=2.0))
    versions, activations = derive_effective_activations(repo, "synthetic", START + 2 * DAY)
    assert (versions, activations) == (2, 2)
    rows = activation_rows(config)
    assert [(r[0], r[1], r[2], r[3]) for r in rows] == [
        (START, START + DAY, "inferred", "effective_note"),
        (START + DAY, None, "inferred", "effective_note"),
    ]
    assert {r[5] for r in rows} == {"effective:n1", "effective:n2"}
    evidence = json.loads(rows[0][4])
    assert evidence["already_customized"] is True
    assert len(evidence["source_refs"]) == 1


def test_rerun_is_idempotent_and_revision_updates_content(config, repo):
    insert_note(repo, "n1", START, note("P1", value=1.0))
    derive_effective_activations(repo, "synthetic", START + DAY)
    before = activation_rows(config)
    versions, activations = derive_effective_activations(repo, "synthetic", START + DAY)
    assert (versions, activations) == (1, 1)
    assert activation_rows(config) == before
    # A corrected upload revises content without duplicating rows.
    repo.insert_raw_record(
        "synthetic", SyncCollection.TREATMENTS, "n1", "r2", START, None, note("P1", value=3.0)
    )
    assert derive_effective_activations(repo, "synthetic", START + DAY) == (1, 1)
    rows = activation_rows(config)
    assert len(rows) == 1
    assert json.loads(rows[0][6])["basal"][0]["value"] == 3.0


def test_conflicting_simultaneous_notes_leave_a_gap(config, repo):
    insert_note(repo, "a", START, note("P1", value=1.0))
    insert_note(repo, "b", START, note("P1", value=9.0))
    insert_note(repo, "c", START + DAY, note("P1", value=2.0))
    assert derive_effective_activations(repo, "synthetic", START + 2 * DAY) == (1, 1)
    rows = activation_rows(config)
    assert [(r[0], r[1]) for r in rows] == [(START + DAY, None)]


def test_malformed_note_leaves_a_gap_but_valid_note_still_derives(config, repo):
    broken = note("P1")
    broken["profileJson"] = {"timezone": "UTC", "units": "mg/dl"}
    insert_note(repo, "bad", START, broken)
    insert_note(repo, "good", START + DAY, note("P1", value=2.0))
    assert derive_effective_activations(repo, "synthetic", START + 2 * DAY) == (1, 1)
    assert [(r[0], r[1]) for r in activation_rows(config)] == [(START + DAY, None)]


def test_positive_expiry_truncates_interval(config, repo):
    insert_note(repo, "n1", START, note("P1", value=1.0, end=START + 3600000))
    insert_note(repo, "n2", START + DAY, note("P1", value=2.0))
    assert derive_effective_activations(repo, "synthetic", START + 2 * DAY) == (2, 2)
    assert [(r[0], r[1]) for r in activation_rows(config)] == [
        (START, START + 3600000),
        (START + DAY, None),
    ]


def test_disappeared_note_leaves_a_gap_without_fallback(config, repo):
    insert_note(repo, "n1", START, note("P1", value=1.0))
    insert_note(repo, "n2", START + DAY, note("P1", value=2.0))
    with transaction(config) as conn:
        conn.execute(
            "INSERT INTO sync_disappearances(source_id,collection,remote_id,first_missing_ms)"
            " VALUES('synthetic','treatments','n1',?)",
            (START + 2 * DAY,),
        )
    assert derive_effective_activations(repo, "synthetic", START + 3 * DAY) == (1, 1)
    rows = activation_rows(config)
    assert [(r[0], r[1]) for r in rows] == [(START + DAY, None)]


def test_resolved_profile_uses_value_keys_without_double_scaling(config, repo):
    from bganalyzer.timeline.profiles import ProfileTimeline, build_profile_timeline

    insert_note(repo, "n1", START, note("P1", value=0.0, percent=150))
    derive_effective_activations(repo, "synthetic", START + DAY)
    with transaction(config) as conn:
        timeline = build_profile_timeline(conn, "synthetic", START + DAY)
    assert isinstance(timeline, ProfileTimeline)
    resolved = timeline.resolve_profile(START + 3600000)
    assert resolved.basal_schedule == [("00:00", 0.0)]
    assert resolved.percentage == 100.0
    assert resolved.is_customized is True


def test_missing_isvalid_counts_as_valid_like_aaps():
    from bganalyzer.timeline.profile_evidence import effective_profile

    payload = dict(note("P1"))
    del payload["isValid"]
    assert effective_profile(payload)["timezone"] == "UTC"
    payload["isValid"] = False
    assert effective_profile(payload) is None


def test_diagnose_switch_records_names_verdicts():
    import json

    from bganalyzer.timeline.profile_evidence import diagnose_switch_records

    def record(remote, stamp, payload, valid=True):
        return {
            "remote_id": remote,
            "revision_hash": "r",
            "event_ms": stamp,
            "payload_json": json.dumps(payload),
            "is_valid": valid,
        }

    records = [
        record("ok-note", START, note("P1")),
        record("no-keys", START + 1000, {"eventType": "Note", "profileJson": profile()}),
        record("no-json", START + 2000, switch_payload(with_json=False)),
        record("str-pct", START + 3000, dict(switch_payload(), percentage="150")),
        record("gone", START + 4000, note("P1"), valid=False),
        record("other", START + 5000, {"eventType": "Announcement", "profileJson": profile()}),
        {
            "remote_id": "broken", "revision_hash": "r", "event_ms": START + 6000,
            "payload_json": "{not json", "is_valid": True,
        },
    ]
    lines = diagnose_switch_records(records, START, START + DAY)
    text = "\n".join(lines)
    assert "ok-note" in text and "supports P1" in text
    assert "no-keys" in text and "not switch evidence" in text
    assert "no-json" in text and "no profileJson" in text
    assert "str-pct" in text and "not an integer" in text
    assert "gone" in text and "presence unconfirmed" in text
    assert "other" in text and "not switch evidence" in text
    assert "broken" in text and "malformed" in text


def test_switch_issue_names_the_failing_check():
    from bganalyzer.timeline.profile_evidence import _switch_issue, requested_switch

    variants = [
        dict(switch_payload(), isValid=False),
        dict(switch_payload(with_json=False)),
        dict(switch_payload(), profileJson={"timezone": "UTC"}),
        dict(switch_payload(), percentage="150"),
        dict(switch_payload(), percentage=0),
        dict(switch_payload(), timeshift=1800000),
        dict(switch_payload(), duration=-5),
        dict(switch_payload(), originalDuration=-1),
        dict(switch_payload(), originalProfileName="", profile=""),
    ]
    for payload in variants:
        assert requested_switch(payload) is None
        issue = _switch_issue(payload)
        assert "unspecified" not in issue, payload


def test_diagnose_limits_to_range_and_sorts():
    from bganalyzer.timeline.profile_evidence import diagnose_switch_records

    assert diagnose_switch_records([], 0, 1000) == []


def test_parse_schedule_accepts_value_and_rate_spellings():
    from bganalyzer.timeline.profiles import ProfileTimeline

    timeline = ProfileTimeline([], [])
    assert timeline._parse_schedule([{"time": "00:00", "value": 1.5}], "rate") == [("00:00", 1.5)]
    assert timeline._parse_schedule([{"time": "00:00", "rate": 2.0}], "rate") == [("00:00", 2.0)]
    assert timeline._parse_schedule([{"time": "00:00"}], "rate") == [("00:00", 0.0)]


def switch_payload(name="P1", value=1.0, percent=150, shift_ms=3600000,
                   duration_min=180, original_duration=None, valid=True,
                   with_json=True):
    payload = {
        "eventType": "Profile Switch",
        "isValid": valid,
        "timeshift": shift_ms,
        "percentage": percent,
        "duration": duration_min,
        "profile": f"{name} {percent}%",
        "originalProfileName": name,
    }
    if with_json:
        payload["profileJson"] = profile(value)
    if original_duration is not None:
        payload["originalDuration"] = original_duration
    return payload


def insert_switch(repo, remote, stamp, **kwargs):
    repo.insert_raw_record(
        "synthetic", SyncCollection.TREATMENTS, remote, "r", stamp, None,
        switch_payload(**kwargs),
    )


def test_requested_switch_validation():
    from bganalyzer.timeline.profile_evidence import requested_switch

    assert requested_switch(switch_payload())["percentage"] == 150
    assert requested_switch(switch_payload(percent=0)) is None
    assert requested_switch(switch_payload(percent=1001)) is None
    assert requested_switch(switch_payload(percent="150")) is None
    assert requested_switch(switch_payload(percent=True)) is None
    assert requested_switch(switch_payload(shift_ms=1800000)) is None
    assert requested_switch(switch_payload(shift_ms="3600000")) is None
    assert requested_switch(switch_payload(duration_min=-5)) is None
    assert requested_switch(switch_payload(with_json=False)) is None
    assert requested_switch(switch_payload(valid=False)) is None
    assert requested_switch(dict(switch_payload(), eventType="Note")) is None
    assert requested_switch(switch_payload(original_duration=7200000))["duration_ms"] == 7200000


def test_switch_derives_base_version_with_requested_customization(config, repo):
    from decimal import Decimal

    insert_switch(repo, "s1", START)
    assert derive_effective_activations(repo, "synthetic", START + DAY) == (1, 1)
    rows = activation_rows(config)
    assert [(r[0], r[1], r[2], r[3]) for r in rows] == [(START, START + 3 * 3600000, "inferred", "profile_switch")]
    assert {r[5] for r in rows} == {"switch:s1"}
    # Stored content is the uncustomized base; scaling applies at resolve time.
    assert json.loads(rows[0][6])["basal"][0]["value"] == 1.0
    with transaction(config) as conn:
        row = conn.execute(
            "SELECT percentage,time_shift_minutes,evidence_json FROM profile_activations"
        ).fetchone()
    assert Decimal(row[0]) == Decimal(150) and row[1] == 60
    assert json.loads(row[2])["already_customized"] is False


def test_switch_resolution_matches_verified_aaps_math(config, repo):
    from bganalyzer.timeline.profiles import build_profile_timeline

    insert_switch(repo, "s1", START)
    derive_effective_activations(repo, "synthetic", START + DAY)
    with transaction(config) as conn:
        timeline = build_profile_timeline(conn, "synthetic", START + DAY)
    resolved = timeline.resolve_profile(START + 3600000)
    assert resolved.is_customized is False
    assert resolved.percentage == 150.0
    # Basal scales up, IC/ISF scale inversely, schedule shifts one hour.
    assert resolved.basal_schedule == [("01:00", 1.5)]
    assert resolved.ic_schedule == [("01:00", 10 * 100.0 / 150)]
    assert resolved.isf_schedule == [("01:00", 50 * 100.0 / 150)]
    assert resolved.target_low_schedule == [] and resolved.target_high_schedule == []


def test_matching_switch_and_effective_note_coalesce(config, repo):
    insert_switch(repo, "s1", START, value=1.0, percent=150)
    insert_note(
        repo, "n1", START,
        note("P1", value=1.5, ic=10 * 100.0 / 150, isf=50 * 100.0 / 150, percent=150),
    )
    assert derive_effective_activations(repo, "synthetic", START + DAY) == (1, 1)
    rows = activation_rows(config)
    assert [(r[0], r[1], r[3]) for r in rows] == [(START, None, "effective_note")]
    assert len(json.loads(rows[0][4])["source_refs"]) == 2


def test_conflicting_switch_and_note_leave_a_gap(config, repo):
    insert_switch(repo, "s1", START, value=1.0, percent=150)
    insert_note(repo, "n1", START, note("P1", value=2.0))
    assert derive_effective_activations(repo, "synthetic", START + DAY) == (0, 0)
    assert activation_rows(config) == []


def test_identical_restatements_coalesce_into_one_row(config, repo):
    insert_note(repo, "n1", START, note("P1", value=1.0))
    insert_note(repo, "n2", START + DAY, note("P1", value=1.0))
    assert derive_effective_activations(repo, "synthetic", START + 2 * DAY) == (1, 1)
    rows = activation_rows(config)
    assert [(r[0], r[1]) for r in rows] == [(START, None)]
    assert len(json.loads(rows[0][4])["source_refs"]) == 2


def test_zero_duration_switch_is_permanent(config, repo):
    insert_note(repo, "n1", START, note("P1", value=1.0))
    insert_switch(repo, "s1", START + DAY, duration_min=0)
    assert derive_effective_activations(repo, "synthetic", START + 2 * DAY) == (2, 2)
    assert [(r[0], r[1]) for r in activation_rows(config)] == [(START, START + DAY), (START + DAY, None)]


def test_original_duration_wins_over_minute_duration(config, repo):
    insert_switch(repo, "s1", START, duration_min=60, original_duration=7200000)
    derive_effective_activations(repo, "synthetic", START + DAY)
    assert [(r[0], r[1]) for r in activation_rows(config)] == [(START, START + 7200000)]


def test_ns_entered_switch_without_json_barriers(config, repo):
    insert_note(repo, "n1", START, note("P1", value=1.0))
    insert_switch(repo, "s1", START + DAY, with_json=False)
    assert derive_effective_activations(repo, "synthetic", START + 2 * DAY) == (1, 1)
    assert [(r[0], r[1]) for r in activation_rows(config)] == [(START, START + DAY)]


def test_permanent_effective_upload_ignores_old_original_end():
    from bganalyzer.timeline.profile_evidence import observed_profile_intervals
    payload = note("P1", value=1.0)
    payload.update(originalDuration=0, originalEnd=START - 5000)
    records = [{"remote_id": "eps", "revision_hash": "r", "event_ms": START,
                "payload_json": json.dumps(payload)}]
    result = observed_profile_intervals(records, START, START + DAY)
    assert [(r["start_ms"], r["end_ms"]) for r in result] == [(START, START + DAY)]
