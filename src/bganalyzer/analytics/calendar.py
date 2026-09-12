"""Calendar days are local-midnight intervals, including 23/25-hour DST days."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


def day_bounds(day, zone):
    tz = ZoneInfo(zone)
    return tuple(
        int(datetime.combine(d, time(), tz).timestamp() * 1000)
        for d in (day, day + timedelta(days=1))
    )
