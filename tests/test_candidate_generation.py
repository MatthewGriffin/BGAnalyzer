"""Tests for _generate_candidates in basal_recommendations.py.

Verifies that:
- Candidate dicts contain contributing_days, supported, sensitivity_min/max
- Basal supported flag reflects eligibility.supported_families
- LOO sensitivity bounds from eligibility.details["sensitivity_ranges"] are attached
- ISF candidates are always marked supported=False
- Candidates without eligibility still work (backward compat)
"""

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Optional

from bganalyzer.autotune.models import ATProfile
from bganalyzer.autotune.orchestration import AutotuneOutput
from bganalyzer.autotune.core import TunedProfile
from bganalyzer.analytics.basal_recommendations import _generate_candidates
from bganalyzer.recommendations.policy import NumericalReleasePolicy, PolicyBounds
from bganalyzer.recommendations.eligibility import EligibilityResult, EligibilityStatus, ReasonCode


# ─── helpers ────────────────────────────────────────────────────────────────

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


def _tuned(basal_val=1.0, ic=10.0, isf=50.0):
    """Return a minimal TunedProfile."""
    return TunedProfile(
        basal=[basal_val] * 24,
        basal_un_tuned=[0.0] * 24,
        dia=6.0,
        peak=60,
        local_insulin=None,
        ic=ic,
        isf=isf,
    )


def _permissive_policy():
    """A very wide policy that accepts all reasonable changes."""
    return NumericalReleasePolicy(
        version="test-v0",
        description="Permissive test policy",
        created_ms=0,
        supported_contexts=["any"],
        basal_bounds=PolicyBounds(
            max_absolute_change=5.0,
            max_percent_change=1.0,
            min_value=0.0,
            max_value=20.0,
            entry_increment=0.025,
        ),
        ic_bounds=PolicyBounds(
            max_absolute_change=50.0,
            max_percent_change=1.0,
            min_value=1.0,
            max_value=200.0,
            entry_increment=0.1,
        ),
        isf_bounds=PolicyBounds(
            max_absolute_change=100.0,
            max_percent_change=1.0,
            min_value=1.0,
            max_value=500.0,
            entry_increment=1.0,
        ),
    )


def _autotune_output_with_tuned(tuned_profile):
    baseline = _profile(1.0, ic=10.0, isf=50.0)
    return AutotuneOutput(
        tuned_days=[tuned_profile],
        prepped_days=[SimpleNamespace(basalGlucoseData=[], isfGlucoseData=[SimpleNamespace(bgi=-1, deviation=-0.1)] * 10, crData=[SimpleNamespace(crInsulinTotal=3.0)])],
        final_profile=_profile(tuned_profile.basal[0], tuned_profile.ic, tuned_profile.isf),
        baseline_profile=baseline,
        eligibility={},
        day_stats=[{"date_ms": 0, "tuned": True, "n_basal_data": 6, "n_isf_data": 0, "n_cr_data": 3}],
    )


def _eligibility_with_support(supported_families, basal_ranges=None, ic_range=None, isf_range=None):
    """Build a mock EligibilityResult with support and LOO range data."""
    return EligibilityResult(
        status=EligibilityStatus.ELIGIBLE,
        reason_codes=[],
        evidence_ids=[],
        supported_families=list(supported_families),
        details={
            "sensitivity_ranges": {
                "unstable": False,
                "n_reruns": 7,
                "basal_ranges": basal_ranges or {},
                "ic_range": ic_range,
                "isf_range": isf_range,
            },
            "isf_limitation": "reference defines no correction episodes; numeric ISF withheld",
        },
    )


# ─── tests ──────────────────────────────────────────────────────────────────

def test_empty_candidates_when_no_tuned_days():
    baseline = _profile()
    output = AutotuneOutput(
        tuned_days=[],
        final_profile=baseline,
        baseline_profile=baseline,
        eligibility={},
    )
    result = _generate_candidates(output, baseline, _permissive_policy())
    assert result == []


def test_no_change_returns_informational_scalar_rows():
    baseline = _profile(1.0, ic=10.0, isf=50.0)
    tuned = _tuned(1.0, ic=10.0, isf=50.0)  # identical to baseline
    output = _autotune_output_with_tuned(tuned)
    result = _generate_candidates(output, baseline, _permissive_policy())
    assert {row["family"] for row in result} == {"ic", "isf"}
    assert result[0]["family"] == "ic"
    assert result[0]["status"] == "unchanged"


def test_basal_candidate_has_enriched_metadata():
    baseline = _profile(1.0)
    tuned = _tuned(1.1)  # every hour increases by 0.1
    output = _autotune_output_with_tuned(tuned)

    loo_ranges = {h: {"min": 1.05, "max": 1.12} for h in range(24)}
    eligibility = _eligibility_with_support(
        supported_families=["basal"],
        basal_ranges=loo_ranges,
    )

    candidates = _generate_candidates(output, baseline, _permissive_policy(), eligibility)
    basal_candidates = [c for c in candidates if c["family"] == "basal" and c["status"] == "candidate"]

    assert len(basal_candidates) == 24

    for c in basal_candidates:
        hour = c["segment"]
        assert c["contributing_days"] == 1, "should count tuned days from day_stats"
        assert c["supported"] is True, "basal is in supported_families"
        assert c["sensitivity_min"] == 1.05
        assert c["sensitivity_max"] == 1.12
        assert "time" in c
        assert c["direction"] == "increase"


def test_basal_candidate_unsupported_when_not_in_supported_families():
    baseline = _profile(1.0)
    tuned = _tuned(1.1)
    output = _autotune_output_with_tuned(tuned)
    # ic is supported but NOT basal
    eligibility = _eligibility_with_support(supported_families=["ic"])

    candidates = _generate_candidates(output, baseline, _permissive_policy(), eligibility)
    basal_candidates = [c for c in candidates if c["family"] == "basal" and c["status"] == "candidate"]
    assert all(c["supported"] is False for c in basal_candidates)


def test_basal_candidate_no_loo_bounds_when_ranges_absent():
    baseline = _profile(1.0)
    tuned = _tuned(1.1)
    output = _autotune_output_with_tuned(tuned)
    # eligibility with empty basal_ranges
    eligibility = _eligibility_with_support(supported_families=["basal"], basal_ranges={})

    candidates = _generate_candidates(output, baseline, _permissive_policy(), eligibility)
    basal_candidates = [c for c in candidates if c["family"] == "basal" and c["status"] == "candidate"]

    assert all(c["sensitivity_min"] is None for c in basal_candidates)
    assert all(c["sensitivity_max"] is None for c in basal_candidates)


def test_ic_candidate_has_enriched_metadata():
    baseline = _profile(1.0, ic=10.0)
    tuned = _tuned(1.0, ic=12.0)  # IC increases
    output = _autotune_output_with_tuned(tuned)

    ic_range = {"min": 11.5, "max": 12.3}
    eligibility = _eligibility_with_support(supported_families=["basal", "ic"], ic_range=ic_range)

    candidates = _generate_candidates(output, baseline, _permissive_policy(), eligibility)
    ic_candidates = [c for c in candidates if c["family"] == "ic" and c["status"] == "candidate"]

    assert len(ic_candidates) == 1
    c = ic_candidates[0]
    assert c["supported"] is True
    assert c["contributing_days"] == 1
    assert c["sensitivity_min"] == 11.5
    assert c["sensitivity_max"] == 12.3


def test_isf_candidate_always_unsupported():
    baseline = _profile(1.0, isf=50.0)
    tuned = _tuned(1.0, isf=55.0)
    output = _autotune_output_with_tuned(tuned)

    # Even if we put "isf" in supported_families, the candidate should still be False
    eligibility = _eligibility_with_support(
        supported_families=["basal", "ic", "isf"],
        isf_range={"min": 53.0, "max": 57.0},
    )

    candidates = _generate_candidates(output, baseline, _permissive_policy(), eligibility)
    isf_candidates = [c for c in candidates if c["family"] == "isf" and c["status"] == "candidate"]

    assert len(isf_candidates) == 1
    c = isf_candidates[0]
    assert c["supported"] is False
    assert "isf_limitation" in c
    assert c["sensitivity_min"] == 53.0
    assert c["sensitivity_max"] == 57.0
    assert c["contributing_days"] == 1


def test_backward_compat_without_eligibility():
    """_generate_candidates with eligibility=None (or omitted) still works."""
    baseline = _profile(1.0)
    tuned = _tuned(1.1)
    output = _autotune_output_with_tuned(tuned)

    candidates = _generate_candidates(output, baseline, _permissive_policy())
    basal_candidates = [c for c in candidates if c["family"] == "basal" and c["status"] == "candidate"]

    assert len(basal_candidates) == 24
    for c in basal_candidates:
        # Without eligibility, supported is False and no LOO bounds
        assert c["supported"] is False
        assert c["sensitivity_min"] is None
        assert c["sensitivity_max"] is None
        assert c["contributing_days"] == 1


def test_empty_candidate_rendering_does_not_invent_or_mutate_results():
    from copy import deepcopy
    from bganalyzer.analytics.basal_recommendations import format_readiness
    result = {"status": "eligible", "message": "Synthetic analysis complete", "recommendations": [], "checks": []}
    before = deepcopy(result)
    text = format_readiness(result)
    assert result == before
    assert "No numerical candidates were produced" in text
    assert "15 analysis days" not in text


def test_unchanged_carb_ratio_is_explicit():
    output = _autotune_output_with_tuned(_tuned(ic=10.0))
    rows = _generate_candidates(output, _profile(ic=10.0), _permissive_policy())
    ic = next(row for row in rows if row['family'] == 'ic')
    assert ic['status'] == 'unchanged'
    assert ic['direction'] == 'unchanged'
    assert ic['baseline_value'] == ic['proposed_value'] == 10.0


def test_no_usable_meals_does_not_present_baseline_as_result():
    output = _autotune_output_with_tuned(_tuned(ic=7.0))
    output.prepped_days[0].crData[0].crInsulinTotal = 0
    rows = _generate_candidates(output, _profile(ic=7.0), _permissive_policy())
    ic = next(row for row in rows if row['family'] == 'ic')
    assert ic['status'] == 'insufficient_evidence'
    assert ic['proposed_value'] is None
    assert ic['baseline_value'] == 7.0

    from bganalyzer.analytics.basal_recommendations import format_readiness
    text = format_readiness({"status": "withheld", "descriptive_candidates": rows})
    assert "Unavailable g/U" in text
