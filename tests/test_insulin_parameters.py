import pytest
from types import SimpleNamespace as NS
from bganalyzer.autotune.models import LocalInsulin
from bganalyzer.autotune.orchestration import resolve_daily_insulin


@pytest.mark.parametrize('peak,dia', [(0,6),(75,0),(180,6),(-1,6),(float('nan'),6),(75,float('inf'))])
def test_invalid_curve_is_rejected_before_division(peak, dia):
    with pytest.raises(ValueError):
        LocalInsulin(None, peak, dia).iobCalcForTreatment(1, 0, 60000)


def test_daily_peak_requires_evidence_covering_lookback():
    day_ms = 86400000
    def inputs():
        return NS(analysis_days=[NS(date_ms=day_ms, profile=NS(dia=6, peak=0, timezone='UTC'))], baseline_evidence={})
    data = inputs()
    excluded = resolve_daily_insulin(data, [dict(event_ms=day_ms, peak_minutes=75, issues=[])])
    assert len(excluded) == 1
    assert data.analysis_days == []
    data = inputs()
    assert resolve_daily_insulin(data, [dict(event_ms=0, peak_minutes=75, issues=[])]) == []
    assert data.analysis_days[0].local_insulin.peak == 75
    assert data.analysis_days[0].profile.peak == 75
    data = inputs()
    assert len(resolve_daily_insulin(data, [dict(event_ms=0, peak_minutes=75, issues=[]),
                                           dict(event_ms=day_ms+1, peak_minutes=55, issues=[])])) == 1


def test_singular_positive_parameters_are_rejected():
    from math import sqrt
    with pytest.raises(ValueError, match='singular'):
        LocalInsulin(None, 360*(1-1/sqrt(2)), 6).iobCalcForTreatment(1, 0, 60000)


def test_resolved_historical_curve_can_calculate_iob():
    from math import isfinite
    value = LocalInsulin(None, 75, 6).iobCalcForTreatment(1, 0, 3600000)
    assert isfinite(value.iob_contrib)
    assert isfinite(value.activity_contrib)
    assert 0 < value.iob_contrib < 1
