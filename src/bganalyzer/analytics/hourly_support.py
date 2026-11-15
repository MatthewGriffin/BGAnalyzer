"""Descriptive per-hour support, separate from clinical confidence or causation."""
from collections import defaultdict


def hourly_support(candidate, samples, minimum_days):
    days = defaultdict(list)
    for sample in samples:
        days[sample['day_index']].append(sample['deviation'])
    totals = {day: sum(values) for day, values in days.items()}
    direction = 1 if candidate.get('direction') == 'increase' else -1 if candidate.get('direction') == 'decrease' else 0
    supporting = sum(value*direction > 0 for value in totals.values())
    opposing = sum(value*direction < 0 for value in totals.values())
    neutral = len(days) - supporting - opposing
    baseline = candidate['baseline_value']
    lower, upper = candidate.get('sensitivity_min'), candidate.get('sensitivity_max')
    if lower is None or upper is None:
        stability = 'unavailable'
    elif lower > baseline and direction == 1 or upper < baseline and direction == -1:
        stability = 'direction retained'
    else:
        stability = 'direction not retained'
    if not days:
        strength = 'No direct hourly evidence'
    elif supporting == 0:
        strength = 'Direct evidence does not support change'
    elif opposing:
        strength = 'Mixed daily evidence'
    elif supporting < minimum_days:
        strength = 'Limited daily evidence'
    else:
        strength = 'Repeated daily support'
    return dict(observed_days=len(days), supporting_days=supporting, opposing_days=opposing,
                neutral_days=neutral, sample_count=len(samples), minimum_supporting_days=minimum_days,
                meets_day_support=supporting >= minimum_days, leave_one_day_out=stability,
                strength=strength, daily_deviation_totals=totals,
                numerical_release_ready=supporting >= minimum_days and stability == 'direction retained')
