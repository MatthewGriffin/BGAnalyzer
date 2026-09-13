from datetime import datetime, timezone
from types import SimpleNamespace as NS

from bganalyzer.analytics.candidate_details import attach_basal_evidence, format_candidate_decision
from bganalyzer.recommendations.policy import NumericalReleasePolicy


def test_basal_evidence_wraps_midnight_and_excludes_unrelated_samples():
    def sample(hour):
        return NS(date=int(datetime(2026, 9, 1, hour, tzinfo=timezone.utc).timestamp()*1000),
                  value=100, deviation=2)
    output = NS(prepped_days=[NS(basalGlucoseData=[sample(0), sample(2), sample(3)])],
                tuned_days=[NS(basal=[1.025]*24)])
    rows = [dict(family="basal", segment=23, time="23:00", baseline_value=1,
                 proposed_value=1.025, raw_value=1.027, status="candidate")]
    attach_basal_evidence(rows, output, NS(timezone="UTC"),
                          NumericalReleasePolicy(version="test", description="synthetic", created_ms=0))
    evidence = rows[0]['decision_evidence']
    assert [s['timestamp_ms'] for s in evidence['samples']] == [sample(0).date, sample(2).date]
    assert evidence['tuned_day_rates'] == [1.025]
    text = format_candidate_decision(rows[0], {})
    assert "2026-09-01 00:00:00 UTC" in text
    assert "not a complete trace" in text
    assert "Entry increment: 0.025 U/hr" in text


def test_plain_summary_distinguishes_repeated_mixed_and_opposing_evidence():
    from bganalyzer.analytics.candidate_details import summarize_candidate_decision
    candidate = dict(family="basal", segment=23, baseline_value=1, proposed_value=1.025,
                     confidence="low", decision_evidence=dict(timezone="UTC", samples=[
                         dict(day_index=1, deviation=2), dict(day_index=2, deviation=3)]))
    text = summarize_candidate_decision(candidate, {})
    assert "unvalidated" in text
    assert "repeats across all 2 observed days" in text
    assert "00:00 and 03:00" in text
    assert "does not necessarily mean glucose was high or low" in text
    candidate['decision_evidence']['samples'][1]['deviation'] = -3
    assert "evidence is mixed" in summarize_candidate_decision(candidate, {})
    candidate['decision_evidence']['samples'][0]['deviation'] = -2
    assert "do not support the direction" in summarize_candidate_decision(candidate, {})
    candidate['decision_evidence']['samples'] = []
    assert "cannot claim a repeated high or low" in summarize_candidate_decision(candidate, {})
