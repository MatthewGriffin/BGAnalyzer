"""Limit tuning to the contiguous period with the current resolved settings."""


def settings_key(profile):
    if not hasattr(profile, 'basal_schedule'):
        return None
    return tuple(tuple(sorted(getattr(profile, name))) for name in (
        'basal_schedule', 'ic_schedule', 'isf_schedule',
        'target_low_schedule', 'target_high_schedule')) + (
            profile.dia_hours, profile.peak_minutes, profile.timezone)


def current_period_start(timeline, start_ms, end_ms, current):
    """Check every known transition, including temporary profile expiry.

    Equal settings in a new upload do not restart the period. Returning to
    previous settings after an intervening change starts a new period.
    """
    boundary = {start_ms, end_ms}
    for activation in timeline.activations:
        boundary.update(t for t in (activation.start_ms, activation.end_ms)
                        if t is not None and start_ms < t < end_ms)
    boundary.update(p.effective_from_ms for p in timeline.store_versions
                    if start_ms < p.effective_from_ms < end_ms)
    points = sorted(boundary)
    expected = settings_key(current)
    period_start = end_ms
    for lo, hi in reversed(list(zip(points, points[1:]))):
        if settings_key(timeline.resolve_profile(lo)) != expected:
            break
        period_start = lo
    return period_start


def no_analysis_days_message(evidence, timezone):
    """Explain zero retained days separately from the seven-day eligibility gate."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    prefix = "Basal changes withheld: no usable days remain for the current settings. "
    if not evidence.get('glucose_records'):
        return prefix + "No glucose records were available in the selected range. Sync that range first."
    if not evidence.get('candidate_days'):
        return prefix + "Glucose records exist, but no days had a resolvable historical profile."
    zone = ZoneInfo(timezone)
    since = datetime.fromtimestamp(evidence['current_period_start_ms'] / 1000, zone)
    cutoff = datetime.fromtimestamp(evidence['as_of_ms'] / 1000, zone)
    excluded = evidence.get('excluded_days', [])
    partial = sum(day['reason'] == 'Incomplete local day' for day in excluded)
    manual = sum(day['reason'] == 'User exclusion or affected insulin lookback' for day in excluded)
    insulin = sum(day['reason'].startswith('Historical insulin settings unresolved:') for day in excluded)
    changed = len(excluded) - partial - manual - insulin
    return (prefix + f"Matching current-profile history begins {since:%d %b %Y %H:%M %Z}; "
            f"analysis ends {cutoff:%d %b %Y %H:%M %Z}. "
            f"Of {evidence['candidate_days']} days with glucose and profile data, "
            f"{changed} crossed older/unknown settings or the {evidence['lookback_hours']:g}-hour "
            f"insulin lookback, {manual} were excluded by you or their affected insulin lookback, "
            f"{insulin} had unresolved historical insulin settings, and {partial} were incomplete days. "
            "This is an analysis-day filter, not the seven-day minimum. "
            "If that history start does not match your last settings change, profile evidence needs inspection.")
