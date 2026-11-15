"""Retained deterministic evidence for inspecting individual tuning candidates."""

from datetime import datetime
from zoneinfo import ZoneInfo


def attach_basal_evidence(candidates, output, baseline, policy):
    zone = baseline.timezone or "UTC"
    samples = [[] for _ in range(24)]
    for day_index, prepped in enumerate(output.prepped_days, 1):
        for bg in prepped.basalGlucoseData:
            hour = datetime.fromtimestamp(bg.date / 1000, ZoneInfo(zone)).hour
            sample = dict(timestamp_ms=bg.date, glucose_mgdl=bg.value,
                          deviation=bg.deviation, day_index=day_index)
            for offset in (1, 2, 3):
                samples[(hour - offset) % 24].append(sample)
    for candidate in candidates:
        if candidate["family"] == "isf":
            from bganalyzer.autotune.core import _percentile
            days = []
            for index, day in enumerate(output.prepped_days):
                readings = getattr(day, "isfGlucoseData", [])
                ratios = sorted(1 + bg.deviation / bg.bgi for bg in readings if bg.bgi != 0)
                days.append({"reading_count": len(readings), "ratio_count": len(ratios),
                             "median_ratio": _percentile(ratios, 0.5) if ratios else None,
                             "tuned_isf": output.tuned_days[index].isf})
            usable = sum(d["reading_count"] >= 10 and d["ratio_count"] > 0 for d in days)
            candidate["isf_evidence"] = {"days": days, "usable_days": usable}
            candidate["confidence"] = "low"
            candidate["isf_limitation"] = "Calculated ISF remains visible; correction-episode validation is not established."
            if usable == 0 and candidate.get("status") in ("candidate", "unchanged"):
                candidate.update(status="insufficient_evidence", proposed_value=None, direction="unavailable")
        if candidate["family"] == "ic":
            candidate["meal_evidence"] = {
                "episode_count": sum(len(getattr(day, "crData", [])) for day in output.prepped_days),
                "tuned_day_ratios": [day.ic for day in output.tuned_days],
                "usable_episode_count": sum(
                    cr.crInsulinTotal > 0
                    for day in output.prepped_days for cr in getattr(day, "crData", [])
                ),
            }
            if (candidate["meal_evidence"]["usable_episode_count"] == 0
                    and candidate.get("status") in ("candidate", "unchanged")):
                candidate["status"] = "insufficient_evidence"
                candidate["proposed_value"] = None
                candidate["direction"] = "unavailable"
        if candidate["family"] != "basal":
            continue
        hour = int(candidate["segment"])
        from bganalyzer.analytics.hourly_support import hourly_support
        support = hourly_support(candidate, samples[hour], policy.min_eligible_days)
        candidate["hourly_support"] = support
        if not support['numerical_release_ready']:
            candidate['confidence'] = 'low'
        bounds = policy.basal_bounds
        candidate["decision_evidence"] = {
            "timezone": zone, "samples": samples[hour],
            "tuned_day_rates": [day.basal[hour] for day in output.tuned_days],
            "entry_increment": bounds.entry_increment,
            "max_percent_change": bounds.max_percent_change,
            "max_absolute_change": bounds.max_absolute_change,
            "min_value": bounds.min_value, "max_value": bounds.max_value,
        }


def summarize_candidate_decision(candidate, result):
    """Explain retained observations without inventing a clinical cause."""
    eligibility = result.get("eligibility", {})
    status = eligibility.get("status") if isinstance(eligibility, dict) else eligibility
    rejected = candidate.get("status") == "rejected"
    withheld = (result.get("status") == "withheld" or candidate.get("confidence") == "low"
                or status != "eligible")
    if candidate.get("status") == "insufficient_evidence":
        setting = "meal evidence for a carb-ratio change" if candidate.get("family") == "ic" else "current-profile evidence for an ISF change"
        opening = (f"Insufficient {setting}. "
                   "The baseline is shown for reference, not as a confirmed result.")
    elif candidate.get("status") == "unchanged":
        opening = "The calculation did not produce a representable change. This does not establish that the current setting is optimal."
    elif rejected:
        opening = "This change was rejected by the app's checks."
    elif withheld:
        opening = "This is an unvalidated calculation, not a cleared recommendation."
    else:
        opening = "This candidate passed the app's technical eligibility checks."
    lines = [opening]
    profile = result.get("baseline_evidence")
    if profile:
        cutoff = datetime.fromtimestamp(profile["as_of_ms"] / 1000, ZoneInfo("UTC"))
        effective = datetime.fromtimestamp(profile["effective_from_ms"] / 1000, ZoneInfo("UTC"))
        lines.append(f"Compared with the latest profile resolved at {cutoff:%Y-%m-%d %H:%M UTC}, "
                     f"effective from {effective:%Y-%m-%d %H:%M UTC}. "
                     f"Profile evidence: {profile['origin']} ({profile['certainty']}).")
    if profile and "retained_days" in profile:
        lines.append(f"This run uses {profile['retained_days']} complete days under the current settings. "
                     f"{len(profile['excluded_days'])} days were excluded because settings or insulin "
                     "lookback differed, you excluded the day or its insulin context, or the day was incomplete. Older settings are not reused "
                     "to push the new profile further.")
    if profile and profile.get("user_exclusions"):
        lines.append("Days you excluded (also excluded from insulin lookback): " + "; ".join(
            f"{item['local_date']} ({item['timezone']}): {item['reason']}"
            for item in profile['user_exclusions']))
    if candidate.get("family") == "basal":
        lines.append("The grid rounds rates to two decimals for display. Exact calculation values are shown below.")
    baseline, proposed = candidate.get("baseline_value"), candidate.get("proposed_value")
    if candidate.get("family") == "isf":
        if isinstance(proposed, (int, float)):
            lines.append(f"The calculated ISF is {proposed:g} mg/dL per unit, compared with "
                         f"{baseline:g} mg/dL per unit in the current profile.")
            if proposed != baseline:
                effect = "less" if proposed > baseline else "more"
                lines.append(f"This would mean {effect} correction insulin for the same glucose difference.")
        evidence = candidate.get("isf_evidence", {})
        days = evidence.get("days", [])
        usable = [d for d in days if d['reading_count'] >= 10 and d['median_ratio'] is not None]
        if usable:
            up = sum(d['median_ratio'] > 1 for d in usable)
            down = sum(d['median_ratio'] < 1 for d in usable)
            lines.append(f"Of {len(usable)} days with usable ISF inputs, {up} pointed toward "
                         f"a higher ISF, {down} toward a lower ISF, and {len(usable)-up-down} "
                         "toward no change. Opposing days mean the evidence is mixed.")
            lines.append("The engine compares observed glucose movement with the movement predicted "
                         "from insulin activity. It uses the middle adjustment ratio for each day, "
                         "limits that estimate, then blends 20% of it with 80% of the previous "
                         "estimate. Each run starts again from the uploaded current profile; "
                         "it does not use the last suggestion as its starting point.")
        else:
            lines.append("No days met the ISF calculation's usable-input requirement. "
                         "A retained baseline is not confirmation that it is appropriate.")
        if candidate.get('reason'):
            lines.append(candidate['reason'])
        lines.append("ISF is included in the calculation and shown here, but correction-episode "
                     "validation is not established. Treat this as an unvalidated estimate.")
        return "\n\n".join(lines)
    if candidate.get("family") == "ic":
        if isinstance(baseline, (int, float)) and isinstance(proposed, (int, float)):
            lines.append(f"The calculated insulin-to-carb ratio changes from {baseline:g} to "
                         f"{proposed:g} grams of carbohydrate per unit of insulin (g/U).")
            if proposed != baseline:
                effect = "more" if proposed < baseline else "less"
                lines.append(f"This means {effect} meal insulin for the same amount of carbohydrate.")
            else:
                lines.append("After rounding, this is unchanged from the baseline ratio.")
        evidence = candidate.get("meal_evidence")
        if evidence:
            lines.append(f"The analysis retained {evidence['episode_count']} meal episodes for "
                         f"carb-ratio calculations across {len(evidence['tuned_day_ratios'])} tuned days. "
                         "The engine compares recorded carbs with estimated insulin needed over "
                         "meal episodes, taking starting insulin on board and the glucose change "
                         "into account. Episodes with a non-positive estimated insulin total do "
                         "not contribute to the daily ratio.")
            if evidence.get("usable_episode_count") is not None:
                lines.append(f"Usable meal episodes: {evidence['usable_episode_count']}. "
                             "With none, the engine retains the previous ratio; this is not "
                             "evidence that the ratio is correct.")
            lines.append("Each day's update blends 20% of the bounded meal-derived ratio with "
                         "80% of the previous ratio, then applies bounds and rounding. "
                         "This is not simply a response to high glucose after one meal.")
        else:
            lines.append("The meal calculation details were not retained in this result. "
                         "Run the analysis again to obtain them.")
        lines.append("This is one overall ratio estimate, not separate breakfast, lunch and "
                     "dinner recommendations. The retained summary does not establish which "
                     "individual meals drove the change.")
        if candidate.get('reason'):
            lines.append("Why it was rejected: " + candidate['reason'])
        if candidate.get('supported') is False:
            lines.append("The required meal-episode support was not established for this candidate.")
        return "\n\n".join(lines)
    if candidate.get("family") != "basal":
        return opening + "\n\nAn hourly basal explanation does not apply to this setting. See calculation details."
    hour = int(candidate['segment'])
    if isinstance(baseline, (int, float)) and isinstance(proposed, (int, float)):
        direction = "increase" if proposed > baseline else "decrease" if proposed < baseline else "keep"
        lines.append(f"For {hour:02d}:00–{(hour + 1) % 24:02d}:00, the calculated change is to "
                     f"{direction} basal from {baseline:g} to {proposed:g} U/hr.")
    else:
        direction = "unknown"
    support = candidate.get('hourly_support')
    if support:
        lines.append(f"Hourly evidence: {support['strength']}. "
                     f"{support['supporting_days']} supporting days, {support['opposing_days']} opposing days, "
                     f"{support['neutral_days']} neutral days; {support['sample_count']} selected readings.")
        lines.append(f"Removing one day and recalculating: {support['leave_one_day_out']}. "
                     f"The hourly support check requires {support['minimum_supporting_days']} supporting days "
                     "and a leave-one-day-out range that stays on the same side of the baseline. "
                     "These are engineering checks, not a probability of benefit.")
    evidence = candidate.get('decision_evidence') or {}
    samples = evidence.get('samples', [])
    if not samples:
        lines.append("There are no retained direct glucose observations to explain this hour. "
                     "The engine can also change an hour when smoothing the daily profile; "
                     "we cannot claim a repeated high or low pattern here.")
    else:
        days = {}
        for sample in samples:
            days.setdefault(sample['day_index'], []).append(sample)
        positive = sum(sum(s['deviation'] for s in day) > 0 for day in days.values())
        negative = sum(sum(s['deviation'] for s in day) < 0 for day in days.values())
        neutral = len(days) - positive - negative
        lines.append(f"Why this hour? The engine uses selected readings between "
                     f"{(hour + 1) % 24:02d}:00 and {(hour + 4) % 24:02d}:00 "
                     f"({evidence['timezone']}) to adjust the preceding three basal hours. "
                     "That is why the glucose evidence is later than the setting being changed.")
        lines.append(f"Across {len(days)} days with relevant readings, glucose moved upward more "
                     f"than the insulin model expected on {positive} days, downward more on "
                     f"{negative} days, and had no net difference on {neutral} days. "
                     "These are selected analysis readings, not every reading in that time window.")
        supporting = positive if direction == "increase" else negative if direction == "decrease" else 0
        opposing = negative if direction == "increase" else positive if direction == "decrease" else 0
        if supporting >= 2 and opposing == 0 and supporting == len(days):
            lines.append(f"The direction repeats across all {supporting} observed days. "
                         f"That is consistent with the engine calculating a basal {direction}.")
        elif supporting > 0 and opposing > 0:
            lines.append("The evidence is mixed: some days point toward more basal and others "
                         "toward less. This is not a consistent daily pattern.")
        elif supporting == 0:
            lines.append("These direct observations do not support the direction of the calculated "
                         "change. Smoothing, bounds and earlier tuning steps can also affect it; "
                         "the retained evidence does not fully explain that difference.")
        else:
            lines.append("There is some evidence in the calculated direction, but it does not "
                         "establish a consistent pattern across multiple days.")
        lines.append("Moving above or below the model's expectation does not necessarily mean "
                     "glucose was high or low. This evidence alone does not establish that basal "
                     "was the cause; meals, activity and other factors may contribute.")
    if candidate.get('reason'):
        lines.append("Why it was rejected: " + candidate['reason'])
    return "\n\n".join(lines)


def format_candidate_decision(candidate, result):
    family = candidate.get("family", "basal")
    unit = {"basal": "U/hr", "ic": "g/U", "isf": "mg/dL/U"}.get(family, "")
    label = candidate.get("time") or str(candidate.get("segment", ""))
    lines = [f"{family.upper()} — {label}",
             f"Analysis eligibility: {(result.get('eligibility') or {}).get('status', 'not recorded') if isinstance(result.get('eligibility'), dict) else result.get('eligibility', 'not recorded')}",
             f"Candidate status: {candidate.get('status', 'not recorded')}"]
    for key, title in (("baseline_value", "Baseline"), ("raw_value", "Unrounded engine result"),
                       ("proposed_value", "Candidate value")):
        value = candidate.get(key)
        lines.append(f"{title}: {value:g} {unit}" if isinstance(value, (float, int))
                     else f"{title}: not retained")
    for key, title in (("direction", "Direction"), ("confidence", "Confidence"),
                       ("contributing_days", "Contributing days"), ("supported", "Episode support"),
                       ("reason", "Rejection reason"), ("isf_limitation", "Limitation")):
        if candidate.get(key) is not None:
            lines.append(f"{title}: {candidate[key]}")
    lines.append(f"Leave-one-day-out range: {candidate.get('sensitivity_min')} to "
                 f"{candidate.get('sensitivity_max')} {unit} (None means unavailable)")
    if candidate.get("reason_codes"):
        lines.append("Withholding reasons: " + ", ".join(candidate["reason_codes"]))
    if candidate.get("isf_evidence"):
        lines += ["", "ISF calculation inputs by day:"]
        for index, day in enumerate(candidate["isf_evidence"]["days"], 1):
            lines.append(f"Day {index}: {day['reading_count']} classified readings; "
                         f"{day['ratio_count']} usable ratios; median ratio {day['median_ratio']}; "
                         f"tuned ISF {day['tuned_isf']:g} mg/dL/U.")
        return "\n".join(lines)
    evidence = candidate.get("decision_evidence")
    if not evidence:
        return "\n".join(lines + ["", "Detailed input evidence was not retained for this candidate."])
    lines += ["", f"Entry increment: {evidence['entry_increment']:g} {unit}",
              f"Policy change limits: {evidence['max_percent_change']:.0%} and "
              f"{evidence['max_absolute_change']:g} {unit}; allowed values "
              f"{evidence['min_value']:g}–{evidence['max_value']:g} {unit}.",
              "Chronological tuned-day rates: " + ", ".join(
                  f"day {i}: {rate:g}" for i, rate in enumerate(evidence['tuned_day_rates'], 1)),
              "", "How inputs affect this hour:",
              "The engine sums classified basal glucose deviations by local clock hour. "
              "It applies 20% of deviation / ISF to the preceding three basal hours: "
              "positive adjustments are split equally, negative adjustments proportionally. "
              "Bounds, smoothing, rounding and successive days also affect the final result.",
              "The samples below are direct deviation inputs for this hour, not a complete "
              "trace of smoothing or intermediate calculations. Raw source IDs are not retained "
              "in these prepared samples. Displayed glucose and deviation units are mg/dL.",
              f"Relevant prepared samples ({evidence['timezone']}):"]
    zone = ZoneInfo(evidence['timezone'])
    for sample in evidence['samples']:
        stamp = datetime.fromtimestamp(sample['timestamp_ms'] / 1000, zone)
        lines.append(f"{stamp:%Y-%m-%d %H:%M:%S %Z} · day {sample['day_index']} · "
                     f"BG {sample['glucose_mgdl']:g} · deviation {sample['deviation']:+g}")
    if not evidence['samples']:
        lines.append("No direct deviation samples; smoothing can still affect this hour.")
    return "\n".join(lines)
