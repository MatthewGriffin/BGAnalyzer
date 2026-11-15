"""Signed temporary-basal contributions for the production insulin calculation.

The numerical contract is checked by an executable pinned-AAPS harness. A
reported rate is not proof that a pump physically delivered that insulin.
"""
from math import ceil, isfinite
from datetime import datetime
from zoneinfo import ZoneInfo
from bganalyzer.autotune.models import Round


def segment_contributions(timestamp_ms, duration_ms, rate, is_absolute, historical_basal, comparison_basal):
    if type(timestamp_ms) is not int or type(duration_ms) is not int or duration_ms < 0:
        raise ValueError('Explicit timestamp and nonnegative duration required')
    if type(is_absolute) is not bool:
        raise ValueError('Explicit rate mode required')
    for value in (rate, historical_basal, comparison_basal):
        if type(value) not in (int, float) or not isfinite(value) or value < 0:
            raise ValueError('Finite nonnegative basal rates required')
    minutes = duration_ms // 60000
    if not minutes:
        return []
    actual = rate if is_absolute else historical_basal * rate / 100
    net = Round.round_to(actual - comparison_basal, 0.001)
    count = ceil(minutes / 5)
    spacing = minutes / count
    return [(int(timestamp_ms + i * spacing * 60000 + 0.5 * spacing * 60000),
             net * spacing / 60) for i in range(count)]


def split_temp_basal(temp, profile):
    """Split at local hours, rate changes and clock transitions, retaining zero rates."""
    start, end = temp.timestamp, temp.timestamp + temp.duration
    zone = ZoneInfo(profile.timezone)
    cursor = start
    previous = datetime.fromtimestamp(start/1000, zone)
    previous_rate = profile.getBasal(start)
    for stamp in range((start // 60000 + 1)*60000, end, 60000):
        local = datetime.fromtimestamp(stamp/1000, zone)
        rate = profile.getBasal(stamp)
        if local.hour != previous.hour or local.utcoffset() != previous.utcoffset() or rate != previous_rate:
            yield cursor, stamp - cursor, profile.getBasal(cursor)
            cursor = stamp
        previous, previous_rate = local, rate
    if end > cursor:
        yield cursor, end - cursor, profile.getBasal(cursor)


def temp_basal_treatments(temps, profile):
    from bganalyzer.autotune.categorize import Treatment
    result = []
    valid = sorted((temp for temp in temps if temp.is_valid), key=lambda t: t.timestamp)
    previous_end = None
    for temp in valid:
        if previous_end is not None and temp.timestamp < previous_end:
            raise ValueError('Overlapping temporary basals cannot be counted twice')
        previous_end = temp.timestamp + temp.duration
        for start, duration, scheduled in split_temp_basal(temp, profile):
            for stamp, amount in segment_contributions(start, duration, temp.rate, temp.is_absolute,
                                                       scheduled, scheduled):
                result.append(Treatment(timestamp=stamp, amount=amount, type='NET_BASAL',
                                        source_id=temp.source_id, revision_hash=temp.revision_hash))
    return result
