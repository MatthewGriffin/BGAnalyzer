from bganalyzer.autotune.models import ATProfile, BGDatum, PreppedGlucose
from bganalyzer.autotune.orchestration import AutotuneOutput
from bganalyzer.recommendations.eligibility import EligibilityChecker, ReasonCode


def _profile(basal_val=1.0, ic=10.0, isf=50.0):
    return ATProfile(
        basal=[basal_val] * 24,
        basalUnTuned=[0] * 24,
        ic=ic,
        isf=isf,
        dia=6.0,
        peak=60,
        isValid=True,
        from_=0,
        localInsulin=None,
        profileName="P",
        timezone="UTC",
    )


def test_sensitivity_stability_skips_when_insufficient_prepped_days():
    checker = EligibilityChecker()
    base = _profile()
    output = AutotuneOutput(
        tuned_days=[],
        final_profile=base,
        baseline_profile=base,
        eligibility={},
        prepped_days=[],
    )
    result = checker._check_sensitivity_stability(output)
    assert isinstance(result, dict)
    assert result["unstable"] is False
    assert result["n_reruns"] == 0
    assert result["basal_ranges"] == {}
    assert result["ic_range"] is None
    assert result["isf_range"] is None


def test_sensitivity_stability_passes_when_consistent():
    checker = EligibilityChecker()
    baseline = _profile(1.0)
    # 3 prepped days, each with positive deviations at hour 12
    # hour 12 in UTC is ms: 12 * 3600 * 1000 = 43200000
    prepped = []
    for day in range(3):
        ts = day * 86400000 + 43200000
        bg = [BGDatum(date=ts, value=150.0, deviation=30.0)]
        prepped.append(PreppedGlucose(startBG=150, crData=[], csfGlucoseData=[], isfGlucoseData=[], basalGlucoseData=bg))

    # Full run tuned profile with an increase in basal
    final = _profile(1.0)
    final.basal[10] = 1.05  # due to prior 3-hour adjustment

    output = AutotuneOutput(
        tuned_days=[],
        final_profile=final,
        baseline_profile=baseline,
        eligibility={},
        prepped_days=prepped,
        preferences={"autosens_max": 1.2, "autosens_min": 0.7},
        pump_profile=baseline,
    )
    # Consistent positive deviations across all days -> stable
    result = checker._check_sensitivity_stability(output)
    assert isinstance(result, dict)
    assert result["unstable"] is False
    assert result["n_reruns"] == 3
    # basal_ranges should have an entry for hour 10 (the changed hour)
    assert 10 in result["basal_ranges"]
    hr = result["basal_ranges"][10]
    assert "min" in hr and "max" in hr
    assert hr["min"] <= hr["max"]


def test_sensitivity_stability_flags_unstable_when_crossing_baseline():
    checker = EligibilityChecker()
    baseline = _profile(1.0)

    # Day 0 & 1 have positive deviations at hour 12, but Day 2 has a large negative deviation
    prepped = []
    for day in range(2):
        ts = day * 86400000 + 43200000
        bg = [BGDatum(date=ts, value=150.0, deviation=10.0)]
        prepped.append(PreppedGlucose(startBG=150, crData=[], csfGlucoseData=[], isfGlucoseData=[], basalGlucoseData=bg))
    
    # Day 2 has a massive negative deviation
    ts_neg = 2 * 86400000 + 43200000
    bg_neg = [BGDatum(date=ts_neg, value=60.0, deviation=-50.0)]
    prepped.append(PreppedGlucose(startBG=60, crData=[], csfGlucoseData=[], isfGlucoseData=[], basalGlucoseData=bg_neg))

    # Suppose full run claims an increase on hour 10:
    final = _profile(1.0)
    final.basal[10] = 1.05

    output = AutotuneOutput(
        tuned_days=[],
        final_profile=final,
        baseline_profile=baseline,
        eligibility={},
        prepped_days=prepped,
        preferences={"autosens_max": 1.2, "autosens_min": 0.7},
        pump_profile=baseline,
    )
    # When excluding Day 0 or 1, Day 2 will dominate and cause a decrease, crossing baseline!
    result = checker._check_sensitivity_stability(output)
    assert isinstance(result, dict)
    assert result["unstable"] is True
    assert result["n_reruns"] == 3



def test_stability_checks_every_day_and_counts_completed_runs(monkeypatch):
    baseline = _profile()
    final = _profile(1.05, ic=11, isf=55)
    days = [object() for _ in range(5)]
    calls = []
    def run(prepped, *args):
        calls.append(prepped)
        return [_profile(1.05, ic=11, isf=55)]
    monkeypatch.setattr("bganalyzer.autotune.core.run_autotune", run)
    output = AutotuneOutput(tuned_days=[], final_profile=final, baseline_profile=baseline,
                            eligibility={}, prepped_days=days, pump_profile=baseline)
    result = EligibilityChecker()._check_sensitivity_stability(output)
    assert len(calls) == result["n_reruns"] == 5
    assert all(days[i] not in calls[i] for i in range(5))
    assert result["isf_range"] == {"min": 55, "max": 55}
    assert result["unstable"] is False


def test_stability_rerun_failure_cannot_pass(monkeypatch):
    baseline = _profile()
    output = AutotuneOutput(tuned_days=[], final_profile=_profile(1.05), baseline_profile=baseline,
                            eligibility={}, prepped_days=[object()] * 3, pump_profile=baseline)
    def fail(*args):
        raise ValueError("synthetic failure")
    monkeypatch.setattr("bganalyzer.autotune.core.run_autotune", fail)
    result = EligibilityChecker()._check_sensitivity_stability(output)
    assert result["unstable"] is True
    assert result["n_reruns"] == 0
