from types import SimpleNamespace as NS
from bganalyzer.autotune.profile_period import current_period_start


def profile(rate=1, ic=7):
    return NS(basal_schedule=[('00:00', rate)], ic_schedule=[('00:00', ic)],
              isf_schedule=[('00:00', 50)], target_low_schedule=[], target_high_schedule=[],
              dia_hours=6, peak_minutes=75, timezone='UTC')


def timeline(changes):
    return NS(activations=[NS(start_ms=t, end_ms=None) for t, p in changes], store_versions=[],
              resolve_profile=lambda t: next(p for stamp, p in reversed(changes) if stamp <= t))


def test_equal_uploads_do_not_restart_period():
    current = profile()
    assert current_period_start(timeline([(0, current), (50, profile())]), 0, 100, current) == 0


def test_return_to_old_settings_does_not_reuse_old_period():
    current = profile()
    assert current_period_start(timeline([(0, current), (30, profile(ic=8)), (60, current)]),
                                0, 100, current) == 60


def test_unknown_interval_breaks_current_period():
    current = profile()
    assert current_period_start(timeline([(0, current), (30, NS()), (60, current)]),
                                0, 100, current) == 60


def test_repeated_analysis_preserves_meals_and_baseline():
    from copy import deepcopy
    from dataclasses import asdict
    from bganalyzer.autotune.models import ATProfile, LocalInsulin
    from bganalyzer.autotune.categorize import CarbEntry
    from bganalyzer.autotune.orchestration import AnalysisDay, AutotuneInput, run_full_autotune
    baseline = ATProfile(basal=[1.0]*24, ic=7, isf=50, dia=6, peak=75,
                         timezone='Europe/London', localInsulin=LocalInsulin(None, 75, 6))
    start = 1789340400000
    meals = [CarbEntry(timestamp=start+1800000, amount=30),
             CarbEntry(timestamp=start+3600000, amount=20)]
    day = AnalysisDay(date_ms=start,
                      glucose=[{'timestamp': start+i*300000, 'value': 110+i%10} for i in range(144)],
                      treatments=[], carb_entries=meals, temp_basals=[], profile=baseline,
                      local_insulin=baseline.localInsulin)
    inputs = AutotuneInput(baseline_profile=baseline, pump_profile=deepcopy(baseline),
                          analysis_days=[day], preferences={})
    original = deepcopy(inputs)
    first = run_full_autotune(inputs)
    second = run_full_autotune(inputs)
    assert [asdict(m) for m in inputs.analysis_days[0].carb_entries] == [asdict(m) for m in original.analysis_days[0].carb_entries]
    assert inputs.analysis_days[0].glucose == original.analysis_days[0].glucose
    assert inputs.baseline_profile.basal == original.baseline_profile.basal
    assert inputs.baseline_profile.ic == original.baseline_profile.ic
    assert inputs.baseline_profile.isf == original.baseline_profile.isf
    assert [(d.basal, d.ic, d.isf) for d in first.tuned_days] == [(d.basal, d.ic, d.isf) for d in second.tuned_days]
    assert [asdict(d) for d in first.prepped_days] == [asdict(d) for d in second.prepped_days]


def test_no_usable_insulin_effect_keeps_isf_unchanged():
    from bganalyzer.autotune.core import run_autotune
    from bganalyzer.autotune.models import ATProfile, BGDatum, PreppedGlucose
    baseline = ATProfile(basal=[1]*24, ic=7, isf=50, dia=6, peak=75, timezone='Europe/London')
    day = PreppedGlucose(startBG=0, crData=[], basalGlucoseData=[], csfGlucoseData=[],
                        isfGlucoseData=[BGDatum(date=i*300000, value=100, bgi=0, deviation=2) for i in range(10)])
    result = run_autotune([day, day], baseline, baseline.copy(), {})
    assert [d.isf for d in result] == [50, 50]


def test_no_days_message_explains_exclusions_instead_of_generic_invalid_data():
    from bganalyzer.autotune.profile_period import no_analysis_days_message
    evidence = dict(glucose_records=100, candidate_days=2, current_period_start_ms=0,
                    as_of_ms=86400000, lookback_hours=8,
                    excluded_days=[{'reason': 'Previous settings'}, {'reason': 'Incomplete local day'}])
    message = no_analysis_days_message(evidence, 'UTC')
    assert '1 crossed older/unknown settings' in message
    assert '1 were incomplete days' in message
    assert 'not the seven-day minimum' in message
    evidence['glucose_records'] = 0
    assert 'Sync that range first' in no_analysis_days_message(evidence, 'UTC')


def test_mmol_profile_isf_and_targets_resolve_in_mgdl():
    """AAPS uploads sens/targets in profile units; glucose maths here is mg/dL."""
    from bganalyzer.timeline.profiles import ProfileTimeline, ProfileVersion

    def resolve(units, sens, low, high):
        version = ProfileVersion(
            remote_id="p", revision_hash="r", effective_from_ms=0, profile_name="p",
            timezone="UTC", units_original=units, content_hash="h",
            normalized_json={
                "units": units, "dia": 6, "peak": 75,
                "basal": [{"time": "00:00", "value": 1.0}],
                "carbratio": [{"time": "00:00", "value": 10}],
                "sens": [{"time": "00:00", "value": sens}],
                "target_low": [{"time": "00:00", "value": low}],
                "target_high": [{"time": "00:00", "value": high}],
            },
        )
        return ProfileTimeline([version], [])._resolve_from_version(version, 1000, activation=None)

    mmol = resolve("mmol", 2.5, 5, 8)
    assert mmol.isf_schedule == [("00:00", 45.0)]
    assert mmol.target_low_schedule == [("00:00", 90.0)]
    assert mmol.target_high_schedule == [("00:00", 144.0)]
    assert mmol.ic_schedule == [("00:00", 10.0)]
    assert mmol.basal_schedule == [("00:00", 1.0)]

    mgdl = resolve("mg/dl", 45, 90, 144)
    assert mgdl.isf_schedule == mmol.isf_schedule
    assert mgdl.target_low_schedule == mmol.target_low_schedule
