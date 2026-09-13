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
        if candidate["family"] != "basal":
            continue
        hour = int(candidate["segment"])
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
    if rejected:
        opening = "This change was rejected by the app's checks."
    elif withheld:
        opening = "This is an unvalidated calculation, not a cleared recommendation."
    else:
        opening = "This candidate passed the app's technical eligibility checks."
    lines = [opening]
    baseline, proposed = candidate.get("baseline_value"), candidate.get("proposed_value")
    if candidate.get("family") != "basal":
        return opening + "\n\nAn hourly basal explanation does not apply to this setting. See calculation details."
    hour = int(candidate['segment'])
    if isinstance(baseline, (int, float)) and isinstance(proposed, (int, float)):
        direction = "increase" if proposed > baseline else "decrease" if proposed < baseline else "keep"
        lines.append(f"For {hour:02d}:00–{(hour + 1) % 24:02d}:00, the calculated change is to "
                     f"{direction} basal from {baseline:g} to {proposed:g} U/hr.")
    else:
        direction = "unknown"
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
