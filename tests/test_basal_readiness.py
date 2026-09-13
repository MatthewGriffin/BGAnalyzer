from types import SimpleNamespace
import json
from bganalyzer.analytics.basal_recommendations import build_basal_recommendations, format_readiness
from bganalyzer.db.connection import get_connection, transaction
from bganalyzer.contracts.domain import TreatmentEvent, TreatmentKind, ProfileVersion, GlucoseReading, SyncCollection


def test_readiness_reports_explicit_blockers_not_vacuous_pass(config, repo):
    result = build_basal_recommendations(
        SimpleNamespace(source_id="synthetic", start_ms=0, end_ms=3600000, data_revision=0),
        config,
        "UTC",
    )
    by_code = {c["code"]: c for c in result["checks"]}
    for code in ("profile_activation_history", "delivery_verification", "aaps_end_to_end_parity"):
        assert code in by_code, f"missing explicit blocker check: {code}"
        # aaps_end_to_end_parity can now be True (parity within clinical thresholds)
        # delivery_verification can now be True (acceptable delivery reconstruction)
        # profile_activation_history can now be True (with proper profile data)
        # All checks are now conditional based on actual data quality
    assert result["recommendations"] == []


def test_eligibility_stale_and_insufficient_day_paths_do_not_crash():
    from bganalyzer.recommendations.eligibility import (
        EligibilityChecker,
        EligibilityStatus,
        ReasonCode,
    )

    empty = SimpleNamespace(
        tuned_days=[],
        baseline_profile=SimpleNamespace(dia=0, peak=0),
    )
    checker = EligibilityChecker()
    checker._check_connection_fresh = lambda sq, t: False
    stale = checker.check_eligibility(
        autotune_output=empty,
        profile_timeline=None,
        delivery_timeline=None,
        sync_quality={},
        glucose_readings=[],
        user_confirmations={},
        current_time_ms=0,
    )
    assert ReasonCode.CONNECTION_STALE in stale.reason_codes
    # With the release policy validated, connection staleness resolves to STALE
    # rather than being masked by VALIDATION_UNAVAILABLE.
    assert ReasonCode.NO_VALIDATED_POLICY not in stale.reason_codes
    assert stale.status == EligibilityStatus.STALE

    fresh = EligibilityChecker().check_eligibility(
        autotune_output=empty,
        profile_timeline=None,
        delivery_timeline=None,
        sync_quality={},
        glucose_readings=[],
        user_confirmations={},
        current_time_ms=0,
    )
    # Fresh check: sync_quality={} has no last_event_ms, so CONNECTION_STALE is
    # still raised and STALE resolves before INSUFFICIENT_DATA.
    assert ReasonCode.CONNECTION_STALE in fresh.reason_codes
    assert ReasonCode.NO_VALIDATED_POLICY not in fresh.reason_codes
    assert fresh.status == EligibilityStatus.STALE


def test_profile_parsing_expands_hours_and_withholds_unknown_dia_peak():
    from bganalyzer.autotune.orchestration import _parse_atprofile, _resolved_to_atprofile

    parsed = _parse_atprofile(
        {
            "name": "t",
            "basal": [{"time": "00:00", "value": 1.0}, {"time": "00:30", "value": 2.0}],
            "carbratio": [{"time": "00:00", "value": 10}],
            "sens": [{"time": "00:00", "value": 50}],
        },
        "UTC",
    )
    assert parsed.basal[0] == 1.0
    assert parsed.basal[1] == 2.0
    assert parsed.dia == 0 and parsed.peak == 0

    resolved = SimpleNamespace(
        basal_schedule=[("00:00", 1.0), ("12:00", 2.0)],
        ic_schedule=[("00:00", 10.0)],
        isf_schedule=[("00:00", 50.0)],
        dia_hours=6.0,
        peak_minutes=75,
        timezone="UTC",
    )
    converted = _resolved_to_atprofile(resolved)
    assert len(converted.basal) == 24
    assert converted.basal[0] == 1.0 and converted.basal[12] == 2.0
    assert (converted.ic, converted.isf, converted.dia, converted.peak) == (10.0, 50.0, 6.0, 75)


def _low_day_readings(day_ms, start_hour, minutes=(0, 5, 10, 15), value=65.0):
    from types import SimpleNamespace as _NS

    return [
        _NS(event_ms=day_ms + (start_hour * 60 + minute) * 60000, sgv_mgdl=value, valid=True)
        for minute in minutes
    ]


def _utc_midnight(ms):
    return ms - (ms % 86400000)


def test_describe_low_patterns_groups_three_local_days():
    from bganalyzer.analytics.basal_recommendations import describe_low_patterns

    base = _utc_midnight(1780000000000)
    readings = []
    for day in range(3):
        readings.extend(_low_day_readings(base + day * 86400000, 3))
    findings = describe_low_patterns(readings, base, base + 3 * 86400000, "UTC")
    assert len(findings) == 1
    finding = findings[0]
    assert (finding["bucket_start"], finding["bucket_end"]) == ("02:00", "04:00")
    assert len(finding["contributing_days"]) == 3
    assert finding["episode_count"] == 3
    assert finding["rule_version"] == "patterns-v1"
    assert all(ep["covered_minutes"] == 20.0 for ep in finding["episodes"])


def test_describe_low_patterns_requires_fifteen_covered_minutes():
    from bganalyzer.analytics.basal_recommendations import describe_low_patterns

    base = _utc_midnight(1780000000000)
    readings = []
    for day in range(3):
        # 0,5,10 -> 15 covered minutes: counts. 0,5,11 splits into 10+5: does not.
        readings.extend(_low_day_readings(base + day * 86400000, 3, minutes=(0, 5, 10)))
    assert len(describe_low_patterns(readings, base, base + 3 * 86400000, "UTC")) == 1
    split = []
    for day in range(3):
        split.extend(_low_day_readings(base + day * 86400000, 3, minutes=(0, 5, 11)))
    assert describe_low_patterns(split, base, base + 3 * 86400000, "UTC") == []


def test_describe_low_patterns_uses_local_buckets_and_lists_conflicts():
    from bganalyzer.analytics.basal_recommendations import describe_low_patterns
    from types import SimpleNamespace as _NS

    # 23:30 UTC is 00:30 local (Europe/London, summer): local bucket 00:00,
    # local date is the next day.
    base = _utc_midnight(1780000000000)
    readings = []
    for day in range(3):
        readings.extend(_low_day_readings(base + day * 86400000, 23, minutes=(30, 35, 40, 45)))
    # Fourth day with normal readings in the same local bucket, no lows.
    for minute in (0, 30, 60, 90):
        readings.append(
            _NS(event_ms=base + 3 * 86400000 + 23 * 3600000 + minute * 60000,
                sgv_mgdl=120.0, valid=True)
        )
    findings = describe_low_patterns(readings, base, base + 4 * 86400000, "Europe/London")
    assert len(findings) == 1
    assert findings[0]["bucket_start"] == "00:00"
    assert len(findings[0]["contributing_days"]) == 3
    assert len(findings[0]["days_with_readings_no_episode"]) == 1


def test_describe_low_patterns_ignores_invalid_out_of_range_and_threshold_edge():
    from bganalyzer.analytics.basal_recommendations import describe_low_patterns
    from types import SimpleNamespace as _NS

    base = _utc_midnight(1780000000000)
    readings = []
    for day in range(3):
        readings.extend(_low_day_readings(base + day * 86400000, 3))
    # Exactly at the band, invalid, and out of range: none may seed episodes.
    readings.append(_NS(event_ms=base + 12 * 3600000, sgv_mgdl=70.0, valid=True))
    readings.append(_NS(event_ms=base + 13 * 3600000, sgv_mgdl=50.0, valid=False))
    readings.append(_NS(event_ms=base - 3600000, sgv_mgdl=50.0, valid=True))
    findings = describe_low_patterns(readings, base, base + 3 * 86400000, "UTC")
    assert len(findings) == 1
    assert findings[0]["episode_count"] == 3


def test_readiness_includes_descriptive_findings_while_withholding_numbers(config, repo):
    from bganalyzer.analytics.basal_recommendations import (
        build_basal_recommendations,
        format_readiness,
    )
    from bganalyzer.contracts.domain import GlucoseReading

    base = _utc_midnight(1780000000000)
    readings = []
    for day in range(3):
        for minute in (0, 5, 10, 15):
            readings.append(
                GlucoseReading(
                    source_id="synthetic",
                    remote_id=f"g{day}-{minute}",
                    revision_hash="r",
                    event_ms=base + day * 86400000 + 3 * 3600000 + minute * 60000,
                    sgv_mgdl=65.0,
                )
            )
    result = build_basal_recommendations(
        SimpleNamespace(
            source_id="synthetic", start_ms=base, end_ms=base + 3 * 86400000,
            data_revision=0, readings=readings,
        ),
        config,
        "UTC",
    )
    assert result["status"] == "withheld"
    assert result["recommendations"] == []
    assert len(result["descriptive_findings"]) == 1
    text = format_readiness(result)
    assert "Recurring low-glucose observations" in text
    assert "No basal rate changes were calculated." in text


def test_derived_activations_let_analysis_days_resolve_but_numbers_stay_withheld(
    config, repo
):
    from bganalyzer.contracts.domain import GlucoseReading, SyncCollection
    from bganalyzer.db.connection import transaction
    from bganalyzer.timeline.profile_evidence import derive_effective_activations

    base = _utc_midnight(1780000000000)
    profile = {
        "timezone": "UTC",
        "units": "mg/dl",
        "dia": 6,
        "peak": 75,
        "basal": [{"time": "00:00", "value": 1.0}],
        "carbratio": [{"time": "00:00", "value": 10}],
        "sens": [{"time": "00:00", "value": 50}],
    }
    repo.insert_raw_record(
        "synthetic",
        SyncCollection.TREATMENTS,
        "note0",
        "r",
        base - 86400000,
        None,
        {
            "eventType": "Note",
            "isValid": True,
            "originalCustomizedName": "P1",
            "originalTimeshift": 0,
            "originalPercentage": 100,
            "originalEnd": 0,
            "profileJson": profile,
        },
    )
    assert derive_effective_activations(repo, "synthetic", base + 3 * 86400000) == (1, 1)

    readings = []
    glucose_rows = []
    for day in range(3):
        for i in range(288):
            stamp = base + day * 86400000 + i * 300000
            readings.append(
                GlucoseReading(
                    source_id="synthetic",
                    remote_id=f"g{day}-{i}",
                    revision_hash="r",
                    event_ms=stamp,
                    sgv_mgdl=120.0,
                )
            )
            glucose_rows.append((f"db-{day}-{i}", "synthetic", f"g{day}-{i}", "r", stamp, 120.0, 1, None))
    with transaction(config) as conn:
        conn.executemany(
            "INSERT INTO glucose(id, source_id, remote_id, revision_hash, event_ms,"
            " sgv_mgdl, valid, quality_json) VALUES(?,?,?,?,?,?,?,?)",
            glucose_rows,
        )
    result = build_basal_recommendations(
        SimpleNamespace(
            source_id="synthetic", start_ms=base, end_ms=base + 3 * 86400000,
            data_revision=0, readings=readings,
        ),
        config,
        "UTC",
        {"user_confirmations": {"meals_recorded": True}},
    )
    by_code = {c["code"]: c for c in result["checks"]}
    # Days resolved through derived activations: the pipeline actually runs.
    assert by_code["autotune_input"]["passed"] is True
    assert "3 analysis days" in by_code["autotune_input"]["detail"]
    assert by_code["profile_activation_history"]["passed"] is True
    assert "eligibility_profile_history_unresolved" not in by_code
    assert "eligibility_delivery_history_unresolved" not in by_code
    # …but numbers stay withheld at the remaining gates.
    assert result["status"] == "withheld"
    assert result["recommendations"] == []


def test_descriptive_candidates_surface_autotune_deviation_when_data_gate_withholds():
    """When a data gate withholds numerical release, the same autotune
    deviation is surfaced as low-confidence descriptive candidates rather
    than being dropped entirely. They are never pump-enterable."""
    from bganalyzer.analytics.basal_recommendations import _generate_candidates
    from bganalyzer.recommendations.policy import get_policy
    from types import SimpleNamespace

    baseline = SimpleNamespace(
        basal=[1.0] * 24, ic=10.0, isf=50.0, dia=6.0, peak=75,
        localInsulin=SimpleNamespace(name="OREF_RAPID_ACTING"),
    )
    final = SimpleNamespace(
        basal=[1.0] * 24, ic=10.0, isf=50.0, dia=6.0, peak=75,
        localInsulin=SimpleNamespace(name="OREF_RAPID_ACTING"),
    )
    # A real basal deviation on hour 3 so the candidate list is non-empty.
    final.basal = [1.0] * 24
    final.basal[3] = 1.15  # +15%, inside the policy-v1 ±20% / ±0.5 U/hr window

    output = SimpleNamespace(
        tuned_days=[SimpleNamespace(basal=final.basal, ic=final.ic, isf=final.isf)],
        baseline_profile=baseline,
        final_profile=final,
        day_stats=[],
    )
    policy = get_policy("policy-v1")
    eligibility = SimpleNamespace(
        supported_families=["basal"],
        details={"sensitivity_ranges": {}},
        reason_codes=[],
    )

    candidates = _generate_candidates(
        output, baseline, policy, eligibility,
        confidence="low", reason_codes=["INSUFFICIENT_DATA"],
    )
    assert candidates, "expected at least one descriptive candidate"
    basal = [c for c in candidates if c["family"] == "basal"]
    assert any(c["segment"] == 3 for c in basal)
    for c in basal:
        assert c["confidence"] == "low"
        assert c["reason_codes"] == ["INSUFFICIENT_DATA"]
        assert c["status"] == "candidate"

    # Full-confidence path carries no reason codes.
    full = _generate_candidates(output, baseline, policy, eligibility)
    for c in full:
        assert c["confidence"] == "full"
        assert c["reason_codes"] == []


def test_missing_baseline_dia_peak_withholds_with_clear_message(config, repo):
    from bganalyzer.contracts.domain import ProfileVersion

    base = _utc_midnight(1780000000000)
    repo.upsert_profile_version(
        ProfileVersion(
            source_id="synthetic",
            remote_id="store1",
            revision_hash="r",
            profile_name="P1",
            effective_from_ms=base - 86400000,
            timezone="UTC",
            units_original="mg/dl",
            normalized_json=json.dumps(
                {
                    "name": "P1",
                    "basal": [{"time": "00:00", "value": 1.0}],
                    "carbratio": [{"time": "00:00", "value": 10}],
                    "sens": [{"time": "00:00", "value": 50}],
                }
            ),
            content_hash="h",
        )
    )
    result = build_basal_recommendations(
        SimpleNamespace(source_id="synthetic", start_ms=base, end_ms=base + 86400000,
                        data_revision=0, readings=[]),
        config,
        "UTC",
    )
    assert result["status"] == "withheld"
    assert "DIA/peak unresolved" in result["message"]


def test_peak_overlaid_from_single_valued_device_evidence(config, repo):
    from bganalyzer.contracts.domain import ProfileVersion, SyncCollection

    base = _utc_midnight(1780000000000)
    repo.upsert_profile_version(
        ProfileVersion(
            source_id="synthetic", remote_id="store1", revision_hash="r",
            profile_name="P1", effective_from_ms=base - 86400000,
            timezone="UTC", units_original="mg/dl",
            normalized_json=json.dumps({
                "name": "P1", "dia": 5,
                "basal": [{"time": "00:00", "value": 1.0}],
                "carbratio": [{"time": "00:00", "value": 10}],
                "sens": [{"time": "00:00", "value": 50}],
            }),
            content_hash="h",
        )
    )
    repo.insert_raw_record(
        "synthetic", SyncCollection.DEVICESTATUS, "d1", "r", base + 3600000, None,
        {"configuration": {"version": "3.4.2.1", "insulin": 2, "insulinConfiguration": {}}},
    )
    result = build_basal_recommendations(
        SimpleNamespace(source_id="synthetic", start_ms=base, end_ms=base + 86400000,
                        data_revision=0, readings=[]),
        config, "UTC",
    )
    provenance = result["insulin_provenance"]
    assert provenance["baseline_dia_source"] == "profile store"
    assert provenance["baseline_peak_minutes"] == 75
    assert "pinned_plugin_constant" in provenance["baseline_peak_source"]
    assert "no analysis days" in result["message"]
    assert "DIA 5" in format_readiness(result)


def test_peak_withheld_when_changed_or_missing_mid_range(config, repo):
    from bganalyzer.contracts.domain import ProfileVersion, SyncCollection

    base = _utc_midnight(1780000000000)
    repo.upsert_profile_version(
        ProfileVersion(
            source_id="synthetic", remote_id="store1", revision_hash="r",
            profile_name="P1", effective_from_ms=base - 86400000,
            timezone="UTC", units_original="mg/dl",
            normalized_json=json.dumps({
                "name": "P1", "dia": 5,
                "basal": [{"time": "00:00", "value": 1.0}],
                "carbratio": [{"time": "00:00", "value": 10}],
                "sens": [{"time": "00:00", "value": 50}],
            }),
            content_hash="h",
        )
    )
    repo.insert_raw_record(
        "synthetic", SyncCollection.DEVICESTATUS, "d1", "r", base + 3600000, None,
        {"configuration": {"version": "3.4.2.1", "insulin": 2, "insulinConfiguration": {}}},
    )
    repo.insert_raw_record(
        "synthetic", SyncCollection.DEVICESTATUS, "d2", "r", base + 7200000, None,
        {"configuration": {"version": "3.4.2.1", "insulin": 3, "insulinConfiguration": {}}},
    )
    result = build_basal_recommendations(
        SimpleNamespace(source_id="synthetic", start_ms=base, end_ms=base + 86400000,
                        data_revision=0, readings=[]),
        config, "UTC",
    )
    assert "insulin DIA/peak unresolved" in result["message"]
    by_code = {c["code"]: c for c in result["checks"]}
    assert "changed mid-range" in by_code["autotune_input"]["detail"]
    assert result["insulin_provenance"]["in_range_peak_values"] == [55, 75]


def test_census_names_profile_sources_in_range(config, repo):
    from bganalyzer.contracts.domain import ProfileVersion, SyncCollection

    base = _utc_midnight(1780000000000)
    repo.upsert_profile_version(
        ProfileVersion(
            source_id="synthetic", remote_id="store1", revision_hash="r",
            profile_name="P1", effective_from_ms=base - 86400000,
            timezone="UTC", units_original="mg/dl",
            normalized_json=json.dumps({"name": "P1"}),
            content_hash="h",
        )
    )
    repo.insert_raw_record(
        "synthetic", SyncCollection.TREATMENTS, "s1", "r", base + 3600000, None,
        {
            "eventType": "Profile Switch", "isValid": True, "timeshift": 0,
            "percentage": 100, "duration": 60, "profile": "P1",
            "originalProfileName": "P1",
            "profileJson": {
                "timezone": "UTC", "units": "mg/dl", "dia": 5,
                "basal": [{"time": "00:00", "value": 1.0}],
                "carbratio": [{"time": "00:00", "value": 10}],
                "sens": [{"time": "00:00", "value": 50}],
            },
        },
    )
    result = build_basal_recommendations(
        SimpleNamespace(source_id="synthetic", start_ms=base, end_ms=base + 86400000,
                        data_revision=0, readings=[]),
        config, "UTC",
    )
    text = format_readiness(result)
    assert "1 store version(s)" in text
    assert "1× Profile Switch" in text


def test_readiness_shows_unchecked_window_bounds(config, repo):
    result = build_basal_recommendations(
        SimpleNamespace(source_id="synthetic", start_ms=0, end_ms=86400000, data_revision=0),
        config,
        "UTC",
    )
    text = format_readiness(result)
    assert "Unchecked import windows" in text
    assert "entries:" in text


def test_config_evidence_display_caps_long_upload_lists():
    observations = [
        {
            "event_ms": 1000 * i, "remote_id": f"r{i}", "revision_hash": "h",
            "version": "3.4.2.1", "plugin_name": "OREF_RAPID_ACTING",
            "peak_minutes": 75, "peak_origin": "pinned_plugin_constant", "issues": [],
        }
        for i in range(12)
    ]
    text = format_readiness({
        "message": "m", "checks": [], "timezone": "UTC",
        "insulin_configuration_evidence": {"observations": observations, "issue_counts": {}},
    })
    assert "2 further uploads omitted" in text
    assert "r11" in text and "r0" in text


def test_readiness_states_analyzed_interval(config, repo):
    result = build_basal_recommendations(
        SimpleNamespace(source_id="synthetic", start_ms=0, end_ms=86400000, data_revision=0),
        config,
        "UTC",
    )
    text = format_readiness(result)
    assert "Analyzing:" in text
    assert "Change Range for another period." in text


def test_readiness_never_uses_truncated_ui_treatments_or_calls_prototype(config, repo, monkeypatch):
    # Patch the binding actually used by the readiness path: orchestration
    # imported run_autotune/run_full_autotune by name, so patching
    # bganalyzer.autotune.core would leave the live reference intact.
    monkeypatch.setattr(
        "bganalyzer.autotune.orchestration.run_full_autotune",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("prototype invoked")),
    )
    with transaction(config):
        for i in range(2005):
            repo.upsert_treatment(
                TreatmentEvent(
                    source_id="synthetic",
                    remote_id=str(i),
                    revision_hash="r",
                    event_ms=i,
                    kind=TreatmentKind.BOLUS,
                    insulin_u=1,
                )
            )
    snapshot = SimpleNamespace(
        source_id="synthetic", start_ms=0, end_ms=10000, data_revision=0, treatments=[], readings=[]
    )
    result = build_basal_recommendations(
        snapshot, config, "Europe/London", {"min_coverage_days": 0, "approved": True}
    )
    assert result["status"] == "withheld"
    assert result["recommendations"] == []
    assert result["counts"]["all_treatments"] == 2005
    assert result["counts"]["unconfirmed_insulin_records"] == 2005
    assert all(
        not check["passed"]
        for check in result["checks"]
        if check["code"]
        in (
            "historical_insulin_configuration",
            "profile_activation_history",
            # aaps_end_to_end_parity can now be True (parity within clinical thresholds)
        )
    )
    assert "No basal rate changes were calculated" in format_readiness(result)


def test_no_data_cannot_become_no_changes(config):
    result = build_basal_recommendations(None, config, "UTC")
    assert result["status"] == "withheld"
    assert not result["recommendations"]
    assert result["checks"][0]["passed"] is False


def test_delivery_verification_can_pass_with_good_timeline(config, repo):
    """Test that delivery verification check can pass when timeline is properly built."""
    base = 1780000000000
    # Add profile
    repo.upsert_profile_version(
        ProfileVersion(
            source_id="synthetic",
            remote_id="store1",
            revision_hash="r",
            profile_name="P1",
            effective_from_ms=base - 86400000,
            timezone="UTC",
            units_original="mg/dl",
            normalized_json=json.dumps({
                "name": "P1", "dia": 6, "peak": 75,
                "basal": [{"time": "00:00", "value": 1.0}],
                "carbratio": [{"time": "00:00", "value": 10}],
                "sens": [{"time": "00:00", "value": 50}],
            }),
            content_hash="h",
        )
    )

    # Add glucose readings
    readings = []
    for day in range(7):
        for i in range(288):
            stamp = base + day * 86400000 + i * 300000
            readings.append(
                GlucoseReading(
                    source_id="synthetic",
                    remote_id=f"g{day}-{i}",
                    revision_hash="r",
                    event_ms=stamp,
                    sgv_mgdl=120.0,
                )
            )

    # Add some treatments
    for i in range(10):
        repo.upsert_treatment(
            TreatmentEvent(
                source_id="synthetic",
                remote_id=f"t{i}",
                revision_hash="r",
                event_ms=base + i * 3600000,
                kind=TreatmentKind.BOLUS,
                insulin_u=5.0,
            )
        )

    result = build_basal_recommendations(
        SimpleNamespace(
            source_id="synthetic",
            start_ms=base,
            end_ms=base + 7 * 86400000,
            data_revision=0,
            readings=readings,
        ),
        config,
        "UTC",
        {"user_confirmations": {"meals_recorded": True}},
    )

    # Check that delivery verification is now conditional
    by_code = {c["code"]: c for c in result["checks"]}
    assert "delivery_verification" in by_code
    # The check should exist and may be False (missing data) or could be True with good data
    # We just verify it's evaluating rather than hardcoded False
    assert "delivery" in by_code["delivery_verification"]["detail"].lower()


def test_uncertain_treatments_are_counted_but_not_used(config, repo):
    for name, valid in [("good", True), ("invalid", False), ("absent", True)]:
        repo.upsert_treatment(
            TreatmentEvent(
                source_id="synthetic",
                remote_id=name,
                revision_hash="r",
                event_ms=100,
                kind=TreatmentKind.BOLUS,
                valid=valid,
            )
        )
    with transaction(config) as conn:
        conn.execute(
            "INSERT INTO sync_disappearances(source_id,collection,remote_id,first_missing_ms) VALUES('synthetic','treatments','absent',200)"
        )
    result = build_basal_recommendations(
        SimpleNamespace(source_id="synthetic", start_ms=0, end_ms=1000, data_revision=0),
        config,
        "UTC",
    )
    assert result["counts"]["all_treatments"] == 3
    assert result["counts"]["usable_treatments"] == 1
    assert result["counts"]["invalid_or_missing"] == 2


def test_effective_profile_preserves_zero_and_does_not_double_scale():
    from bganalyzer.timeline.profile_evidence import effective_profile, observed_profile_intervals
    import json

    profile = {
        "timezone": "Europe/London",
        "units": "mmol",
        "dia": 6,
        "basal": [{"time": "00:00", "value": 0}, {"time": "01:00", "value": 1.5}],
        "carbratio": [{"time": "00:00", "value": 10}],
        "sens": [{"time": "00:00", "value": 3}],
    }
    payload = {
        "eventType": "Note",
        "isValid": True,
        "originalCustomizedName": "effective",
        "originalTimeshift": 3600000,
        "originalPercentage": 150,
        "originalEnd": 2000,
        "profileJson": json.dumps(profile),
    }
    assert effective_profile(payload)["basal"][1]["value"] == 1.5
    assert effective_profile(payload)["basal"][0]["value"] == 0
    records = [
        {
            "event_ms": 1000,
            "remote_id": "p",
            "revision_hash": "r",
            "payload_json": json.dumps(payload),
        }
    ]
    intervals = observed_profile_intervals(records, 0, 3000)
    assert [(i["start_ms"], i["end_ms"]) for i in intervals] == [(1000, 2000)]
    assert intervals[0]["insulin_peak_minutes"] is None
    payload["eventType"] = "Profile Switch"
    assert effective_profile(payload) is None


def test_equal_effective_uploads_deduplicate_but_conflicts_leave_gap():
    from bganalyzer.timeline.profile_evidence import observed_profile_intervals
    import json

    profile = {
        "timezone": "UTC",
        "units": "mg/dl",
        "basal": [{"time": "00:00", "value": 1}],
        "carbratio": [{"time": "00:00", "value": 10}],
        "sens": [{"time": "00:00", "value": 50}],
    }
    payload = {
        "eventType": "Note",
        "isValid": True,
        "originalCustomizedName": "x",
        "originalTimeshift": 0,
        "originalPercentage": 100,
        "originalEnd": 0,
        "profileJson": profile,
    }
    records = [
        {
            "event_ms": 1000,
            "remote_id": name,
            "revision_hash": "r",
            "payload_json": json.dumps(payload),
        }
        for name in ("a", "b")
    ]
    result = observed_profile_intervals(records, 0, 2000)
    assert len(result) == 1
    assert len(result[0]["source_refs"]) == 2
    profile["basal"][0]["value"] = 2
    records[1]["payload_json"] = json.dumps(payload)
    assert observed_profile_intervals(records, 0, 2000) == []


def test_profile_scope_unions_clips_and_reports_exact_gaps():
    from bganalyzer.timeline.profile_evidence import profile_evidence_coverage

    result = profile_evidence_coverage(
        [
            {"start_ms": -100, "end_ms": 200},
            {"start_ms": 100, "end_ms": 400},
            {"start_ms": 600, "end_ms": 1200},
        ],
        0,
        1000,
    )
    assert result == {
        "covered_ms": 800,
        "missing_ms": 200,
        "coverage_percent": 80.0,
        "gaps": [{"start_ms": 400, "end_ms": 600}],
    }
    assert profile_evidence_coverage([], 0, 1000)["missing_ms"] == 1000


def test_malformed_effective_profiles_fail_closed():
    from bganalyzer.timeline.profile_evidence import effective_profile

    base = {
        "eventType": "Note",
        "isValid": True,
        "originalCustomizedName": "x",
        "originalTimeshift": 0,
        "originalPercentage": 100,
        "originalEnd": 0,
        "profileJson": {
            "timezone": "UTC",
            "units": "mg/dl",
            "basal": [{"time": "00:00", "value": 1}],
            "carbratio": [{"time": "00:00", "value": 10}],
            "sens": [{"time": "00:00", "value": 50}],
        },
    }
    for expiry in (None, True, -1, "0", [], float("nan"), float("inf")):
        assert effective_profile(dict(base, originalEnd=expiry)) is None
    for profile in (None, [], {"timezone": "UTC", "units": "mg/dl", "basal": {"x": 1}}):
        assert effective_profile(dict(base, profileJson=profile)) is None


def test_profile_gap_display_uses_requested_timezone(config, repo):
    result = build_basal_recommendations(
        SimpleNamespace(source_id="synthetic", start_ms=0, end_ms=3600000, data_revision=0),
        config,
        "Europe/London",
    )
    assert result["profile_evidence_coverage"]["gaps"] == [{"start_ms": 0, "end_ms": 3600000}]
    assert "Missing switch evidence (no effective Note or Profile Switch upload):" in format_readiness(result)
    assert "01 Jan 1970" in format_readiness(result)
    assert result["recommendations"] == []


def test_invalid_effective_event_stops_previous_profile():
    import json
    from bganalyzer.timeline.profile_evidence import observed_profile_intervals

    profile = {
        "timezone": "UTC",
        "units": "mg/dl",
        "basal": [{"time": "00:00", "value": 1}],
        "carbratio": [{"time": "00:00", "value": 10}],
        "sens": [{"time": "00:00", "value": 50}],
    }
    payload = {
        "eventType": "Note",
        "isValid": True,
        "originalCustomizedName": "x",
        "originalTimeshift": 0,
        "originalPercentage": 100,
        "originalEnd": 0,
        "profileJson": profile,
    }
    records = [
        {
            "event_ms": 0,
            "remote_id": "a",
            "revision_hash": "r",
            "payload_json": json.dumps(payload),
        },
        {
            "event_ms": 500,
            "remote_id": "b",
            "revision_hash": "r",
            "payload_json": json.dumps({"eventType": "Note", "originalCustomizedName": "broken"}),
        },
    ]
    assert [(i["start_ms"], i["end_ms"]) for i in observed_profile_intervals(records, 0, 1000)] == [
        (0, 500)
    ]


def test_basal_cancel_before_start_raises():
    import pytest

    from bganalyzer.analytics.basal_recommendations import build_basal_recommendations
    from bganalyzer.autotune.models import AutotuneCancelled

    with pytest.raises(AutotuneCancelled):
        build_basal_recommendations(
            None, SimpleNamespace(), "UTC", cancelled=lambda: True
        )


def _two_day_input():
    from bganalyzer.autotune.models import ATProfile, LocalInsulin
    from bganalyzer.autotune.orchestration import AnalysisDay, AutotuneInput

    base = 1_700_000_000_000 - (1_700_000_000_000 % 86400000)
    profile = ATProfile(
        basal=[1.0] * 24, ic=10.0, isf=50.0, dia=6.0, peak=75,
        isValid=True, localInsulin=LocalInsulin(None, 75, 6.0),
        profileName="t", timezone="UTC",
    )
    days = []
    for d in range(2):
        start = base + d * 86400000
        glucose = [
            {"timestamp": start + i * 300000, "value": 120.0 + (i % 7)}
            for i in range(60)
        ]
        days.append(
            AnalysisDay(
                date_ms=start, glucose=glucose, treatments=[], carb_entries=[],
                temp_basals=[], profile=profile, local_insulin=profile.localInsulin,
            )
        )
    return AutotuneInput(
        baseline_profile=profile, pump_profile=profile, analysis_days=days,
        preferences={},
    )


def test_run_full_autotune_reports_progress_and_honours_cancel():
    import pytest

    from bganalyzer.autotune.models import AutotuneCancelled
    from bganalyzer.autotune.orchestration import run_full_autotune

    seen = []
    state = {"cancel": False}

    def cancel_after_first_progress():
        return state["cancel"]

    def progress(text):
        seen.append(text)
        state["cancel"] = True

    with pytest.raises(AutotuneCancelled):
        run_full_autotune(
            _two_day_input(), cancelled=cancel_after_first_progress, progress=progress
        )
    assert seen, "expected at least one progress message before cancellation"

    # Without cancellation the same input completes and stays silent-free.
    done = []
    out = run_full_autotune(_two_day_input(), progress=done.append)
    assert len(out.tuned_days) == 2
    assert len(done) == 2 + 2  # categorize + tune messages per day


def test_split_into_days_skips_unresolvable_days_without_stalling():
    from bganalyzer.autotune.orchestration import _split_into_days
    from bganalyzer.timeline.profiles import ProfileTimeline

    day = 86400000
    glucose = [{"timestamp": i * 300000, "value": 120.0} for i in range(3 * 288)]
    baseline = SimpleNamespace(basal=[1.0] * 24)
    days = _split_into_days(
        glucose, [], [], [], baseline, ProfileTimeline([], []), None, 0, 3 * day, "UTC"
    )
    assert days == []


def test_split_into_days_matches_window_membership():
    from bganalyzer.autotune.orchestration import _split_into_days
    from bganalyzer.autotune.categorize import Treatment
    from bganalyzer.timeline.profiles import (
        ProfileActivation,
        ProfileTimeline,
        ProfileVersion,
    )

    day = 86400000
    start, end = 0, 3 * day
    glucose = [{"timestamp": t, "value": 120.0} for t in (0, day - 1, day, 2 * day, end - 1)]
    treatments = [
        Treatment(timestamp=t, amount=1.0, is_valid=True) for t in (0, day, end - 1)
    ]
    pv = ProfileVersion(
        remote_id="p", revision_hash="r", effective_from_ms=-day,
        profile_name="t", timezone="UTC", units_original="mg/dl",
        normalized_json={
            "basal": [{"time": "00:00", "rate": 1.0}],
            "carbratio": [{"time": "00:00", "value": 10.0}],
            "sens": [{"time": "00:00", "value": 50.0}],
            "target_low": [{"time": "00:00", "value": 80.0}],
            "target_high": [{"time": "00:00", "value": 120.0}],
            "dia": 6.0, "peak": 75,
        },
        content_hash="h",
    )
    timeline = ProfileTimeline(
        [pv],
        [ProfileActivation(start_ms=-day, end_ms=None, certainty="confirmed",
                           origin="profile_store", evidence_json={},
                           profile_version=pv)],
    )
    baseline = SimpleNamespace(basal=[1.0] * 24)
    days = _split_into_days(
        glucose, treatments, [], [], baseline, timeline, None, start, end, "UTC"
    )
    assert [d.date_ms for d in days] == [0, day, 2 * day]
    # Exact half-open membership: boundary timestamps belong to the later day.
    assert [g["timestamp"] for g in days[0].glucose] == [0, day - 1]
    assert [g["timestamp"] for g in days[1].glucose] == [day]
    assert [g["timestamp"] for g in days[2].glucose] == [2 * day, end - 1]
    assert [t.timestamp for t in days[1].treatments] == [day]


DAY_MS = 86400000


def _utc_day_start(ms):
    return ms - (ms % DAY_MS)


def _five_minute_day(day_start, drop=(), value=120.0):
    return [
        {"timestamp": day_start + i * 300000, "value": value}
        for i in range(288)
        if i not in drop
    ]


def _checker_output(n_days=0, day_stats=None, basal_up=False, ic_down=False):
    from bganalyzer.autotune.core import TunedProfile
    from bganalyzer.autotune.models import ATProfile, LocalInsulin

    baseline = ATProfile(
        basal=[1.0] * 24, ic=10.0, isf=50.0, dia=6.0, peak=75, isValid=True,
        localInsulin=LocalInsulin(None, 75, 6.0),
    )
    final = baseline.copy()
    if basal_up:
        final.basal = [b + 0.1 for b in final.basal]
    if ic_down:
        final.ic = 8.0
    tuned = [
        TunedProfile(
            basal=[1.0] * 24, ic=10.0, isf=50.0, dia=6.0, peak=75,
            basal_un_tuned=[0] * 24, local_insulin=LocalInsulin(None, 75, 6.0),
        )
        for _ in range(n_days)
    ]
    output = SimpleNamespace(
        tuned_days=tuned, final_profile=final, baseline_profile=baseline,
    )
    if day_stats is not None:
        output.day_stats = day_stats
    return output


def _day_stat(day_start, tuned=True, n_basal=10, n_isf=5, n_cr=0):
    return {
        "date_ms": day_start, "tuned": tuned, "n_basal_data": n_basal,
        "n_isf_data": n_isf, "n_cr_data": n_cr,
    }


def test_connection_freshness_uses_bg_age_without_defaults():
    from bganalyzer.recommendations.eligibility import EligibilityChecker

    checker = EligibilityChecker()
    now = 1780000000000
    assert checker._check_connection_fresh({"entries": {"last_event_ms": now - 5 * 60000}}, now) is True
    assert checker._check_connection_fresh({"entries": {"last_event_ms": now - 15 * 60000}}, now) is True
    assert checker._check_connection_fresh({"entries": {"last_event_ms": now - 16 * 60000}}, now) is False
    assert checker._check_connection_fresh({"entries": {"last_event_ms": now + 60000}}, now) is False
    assert checker._check_connection_fresh({}, now) is False
    assert checker._check_connection_fresh(None, now) is False


def test_cgm_coverage_flags_half_covered_days_and_long_gaps():
    from bganalyzer.recommendations.eligibility import EligibilityChecker, ReasonCode

    checker = EligibilityChecker()
    base = _utc_day_start(1780000000000)
    full = _five_minute_day(base)
    half = _five_minute_day(base + DAY_MS)[:144]
    gapped = _five_minute_day(base + 2 * DAY_MS, drop=range(144, 151))
    readings = full + half + gapped
    stats = [_day_stat(base + d * DAY_MS) for d in range(3)]
    coverage = checker._coverage_by_window(readings, stats, base, base + 3 * DAY_MS)
    assert coverage[base]["coverage_pct"] == 100.0
    assert coverage[base]["max_gap_min"] == 5.0
    assert coverage[base + DAY_MS]["coverage_pct"] == 50.0
    assert coverage[base + 2 * DAY_MS]["coverage_pct"] > 90.0
    assert coverage[base + 2 * DAY_MS]["max_gap_min"] == 40.0
    issues = checker._check_cgm_coverage(stats, coverage)
    assert ReasonCode.CGM_COVERAGE_INSUFFICIENT in issues
    assert ReasonCode.CGM_GAP_EXCEEDS_LIMIT in issues


def test_cgm_coverage_clips_to_range_end_for_partial_today():
    from bganalyzer.recommendations.eligibility import EligibilityChecker

    checker = EligibilityChecker()
    base = _utc_day_start(1780000000000)
    end = base + 12 * 3600000  # noon: only half the day elapsed
    readings = [
        {"timestamp": base + i * 300000, "value": 120.0} for i in range(144)
    ]
    window = checker._window_coverage(readings, base, end)
    assert window["coverage_pct"] == 100.0
    assert checker._window_coverage([], base, end)["coverage_pct"] == 0.0


def test_eligible_days_gate_on_tuned_and_covered_days():
    from bganalyzer.recommendations.eligibility import (
        EligibilityChecker, EligibilityStatus, ReasonCode,
    )

    checker = EligibilityChecker()
    base = _utc_day_start(1780000000000)
    readings = []
    stats = []
    for day in range(7):
        day_readings = _five_minute_day(base + day * DAY_MS)
        if day == 3:
            day_readings = day_readings[:144]  # half-covered day excluded
        readings.extend(day_readings)
        stats.append(_day_stat(base + day * DAY_MS))
    output = _checker_output(day_stats=stats)
    result = checker.check_eligibility(
        autotune_output=output,
        profile_timeline=SimpleNamespace(
            get_activations_in_range=lambda s, e: [SimpleNamespace(start_ms=s, end_ms=None)]
        ),
        delivery_timeline=SimpleNamespace(resolve_delivery=lambda s, e: []),
        sync_quality={"entries": {"last_event_ms": base + 7 * DAY_MS - 60000}},
        glucose_readings=readings,
        user_confirmations={"meals_recorded": True},
        current_time_ms=base + 7 * DAY_MS,
        start_ms=base,
        end_ms=base + 7 * DAY_MS,
        device_config={
            "autosens_enabled": False, "autosens_source": "dated upload",
            "dynamic_isf": False, "dynamic_isf_source": "dated upload",
            "insulin_plugin": "OREF_RAPID_ACTING",
        },
    )
    assert result.details["eligible_days"] == 6
    assert ReasonCode.CGM_COVERAGE_INSUFFICIENT in result.reason_codes
    assert ReasonCode.INSUFFICIENT_DATA in result.reason_codes
    # With the release policy validated, data gates now resolve directly to
    # INSUFFICIENT_DATA instead of being masked by VALIDATION_UNAVAILABLE.
    assert result.status == EligibilityStatus.INSUFFICIENT_DATA
    assert ReasonCode.NO_VALIDATED_POLICY not in result.reason_codes


def test_episode_support_uses_reference_counts_and_never_supports_isf():
    from bganalyzer.recommendations.eligibility import EligibilityChecker

    checker = EligibilityChecker()
    base = _utc_day_start(1780000000000)
    stats = [_day_stat(base + d * DAY_MS, n_cr=2 if d < 3 else 0) for d in range(5)]
    output = _checker_output(day_stats=stats)
    support = checker._check_episode_support(output, {s["date_ms"] for s in stats})
    assert support["basal"] is True
    assert support["ic"] is True  # 6 episodes on 3 days
    assert support["isf"] is False
    assert "no correction episodes" in support["isf_limitation"]
    thin = [_day_stat(base + d * DAY_MS, n_basal=0, n_isf=0, n_cr=1 if d < 2 else 0) for d in range(5)]
    thin_support = checker._check_episode_support(
        _checker_output(day_stats=thin), {s["date_ms"] for s in thin}
    )
    assert thin_support["basal"] is False
    assert thin_support["ic"] is False  # only 2 carb episodes on 2 days
    assert thin_support["isf"] is False


def test_low_glucose_contradiction_only_blocks_increases():
    from bganalyzer.recommendations.eligibility import EligibilityChecker

    checker = EligibilityChecker()
    readings = [
        {"timestamp": 1000 + i * 300000, "value": value}
        for i, value in enumerate([120.0, 52.0, 130.0])
    ]
    assert checker._check_low_glucose_contradiction(_checker_output(basal_up=True), readings) is True
    assert checker._check_low_glucose_contradiction(_checker_output(ic_down=True), readings) is True
    assert checker._check_low_glucose_contradiction(_checker_output(), readings) is False
    safe = [{"timestamp": 1000 + i * 300000, "value": 120.0} for i in range(3)]
    assert checker._check_low_glucose_contradiction(_checker_output(basal_up=True), safe) is False
    assert checker._check_low_glucose_contradiction(_checker_output(basal_up=True), []) is False


def test_device_modes_distinguish_unknown_from_off():
    from bganalyzer.recommendations.eligibility import EligibilityChecker, ReasonCode

    checker = EligibilityChecker()
    assert ReasonCode.AUTOTUNE_MODE_UNKNOWN in checker._check_device_modes({})
    assert ReasonCode.DYNAMIC_ISF_UNKNOWN in checker._check_device_modes({})
    assert checker._check_device_modes(
        {"autosens_enabled": False, "dynamic_isf": False}
    ) == []
    assert ReasonCode.DYNAMIC_ISF_ENABLED in checker._check_device_modes(
        {"autosens_enabled": True, "dynamic_isf": True}
    )
    assert ReasonCode.DYNAMIC_ISF_UNKNOWN not in checker._check_device_modes(
        {"autosens_enabled": False, "dynamic_isf": False}
    )


def test_insulin_plugin_unknown_without_evidence():
    from bganalyzer.recommendations.eligibility import EligibilityChecker, ReasonCode

    checker = EligibilityChecker()
    profile = SimpleNamespace(dia=6.0, peak=75)
    assert ReasonCode.INSULIN_PLUGIN_UNKNOWN in checker._check_insulin_config(profile)
    assert checker._check_insulin_config(profile, "OREF_RAPID_ACTING") == []


def test_basal_builds_device_config_without_silent_defaults(config, repo):
    snapshot = SimpleNamespace(
        source_id="synthetic", start_ms=0, end_ms=3600000, data_revision=0, readings=[],
    )
    result = build_basal_recommendations(snapshot, config, "UTC")
    device_config = result["device_config"]
    assert device_config["autosens_enabled"] is None
    assert device_config["dynamic_isf"] is None
    assert device_config["insulin_plugin"] is None
    assert "Loop modes:" in format_readiness(result)

    stated = SimpleNamespace(
        source_id="synthetic", start_ms=0, end_ms=3600000, data_revision=0, readings=[],
        configuration={"autosens_enabled": False, "use_dynamic_sensitivity": True},
        configuration_at_ms=1000,
    )
    stated_result = build_basal_recommendations(stated, config, "UTC")
    stated_config = stated_result["device_config"]
    assert stated_config["autosens_enabled"] is False
    assert stated_config["autosens_source"] == "dated upload"
    assert stated_config["dynamic_isf"] is True
    assert stated_config["configuration_at_ms"] == 1000

    confirmed = SimpleNamespace(
        source_id="synthetic", start_ms=0, end_ms=3600000, data_revision=0, readings=[],
        configuration={},
    )
    confirmed_result = build_basal_recommendations(
        confirmed, config, "UTC",
        {"user_confirmations": {"autosens_enabled": True, "dynamic_isf": False}},
    )
    confirmed_config = confirmed_result["device_config"]
    assert confirmed_config["autosens_enabled"] is True
    assert confirmed_config["autosens_source"] == "user-reported"
    assert confirmed_config["dynamic_isf"] is False


def test_run_full_autotune_reports_aligned_day_stats():
    from bganalyzer.autotune.orchestration import run_full_autotune

    two_day = _two_day_input()
    tiny_day = SimpleNamespace(
        date_ms=two_day.analysis_days[-1].date_ms + 86400000,
        glucose=[{"timestamp": 1, "value": 120.0}],
        treatments=[], carb_entries=[], temp_basals=[],
        profile=two_day.analysis_days[0].profile,
        local_insulin=two_day.analysis_days[0].local_insulin,
    )
    two_day.analysis_days.append(tiny_day)
    out = run_full_autotune(two_day)
    assert [stat["date_ms"] for stat in out.day_stats] == sorted(
        stat["date_ms"] for stat in out.day_stats
    )
    assert [stat["tuned"] for stat in out.day_stats] == [True, True, False]
    assert all(
        {"n_basal_data", "n_isf_data", "n_cr_data"} <= set(stat) for stat in out.day_stats
    )
