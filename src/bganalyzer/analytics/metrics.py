"""Duration-weighted CGM summaries; missing time is never filled beyond five minutes."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from math import isfinite, sqrt
from statistics import median
from zoneinfo import ZoneInfo

import numpy as np

from bganalyzer.contracts.analysis import DailyPercentileOverlay, TimeInRangeMetrics
from bganalyzer.contracts.domain import DeliveryStatus, GlucoseReading, TreatmentKind
from bganalyzer.normalize.glucose import classify_glucose_mgdl


@dataclass(frozen=True)
class ReportBands:
    very_low: float = 54
    low: float = 70
    high: float = 180
    very_high: float = 250

    def __post_init__(self):
        values = (self.very_low, self.low, self.high, self.very_high)
        if (
            not all(isfinite(v) for v in values)
            or not 0 < values[0] < values[1] < values[2] < values[3]
        ):
            raise ValueError("Report bands must be finite, positive and increasing")


DEFAULT_BANDS = ReportBands()


def _unique_readings(glucose):
    by_time = defaultdict(list)
    for reading in glucose:
        if reading.valid and isfinite(reading.sgv_mgdl):
            by_time[reading.event_ms].append(reading)
    # Conflicting concurrent sensor values are not averaged or arbitrarily selected.
    return [
        items[0]
        for _, items in sorted(by_time.items())
        if len({item.sgv_mgdl for item in items}) == 1
    ]


def metric_contributions(glucose, start_ms, end_ms):
    readings = [g for g in _unique_readings(glucose) if start_ms - 300_000 < g.event_ms < end_ms]
    for i, reading in enumerate(readings):
        end = min(
            end_ms,
            reading.event_ms + 300_000,
            readings[i + 1].event_ms if i + 1 < len(readings) else end_ms,
        )
        duration = max(0, end - max(start_ms, reading.event_ms)) / 60_000
        if duration > 0:
            yield reading, max(start_ms, reading.event_ms), end, duration


def calculate_tir_metrics(
    glucose: list[GlucoseReading], start_ms: int, end_ms: int, bands: ReportBands = DEFAULT_BANDS
) -> TimeInRangeMetrics:
    if end_ms <= start_ms:
        raise ValueError("Report end must follow start")
    intervals = []
    minutes = defaultdict(float)
    for reading, _, _, duration in metric_contributions(glucose, start_ms, end_ms):
        intervals.append((reading.sgv_mgdl, duration))
        band = classify_glucose_mgdl(
            reading.sgv_mgdl,
            low=bands.low,
            high=bands.high,
            very_low=bands.very_low,
            very_high=bands.very_high,
        )
        minutes[band] += duration
    covered = sum(weight for _, weight in intervals)
    total = (end_ms - start_ms) / 60_000
    mean = sum(value * weight for value, weight in intervals) / covered if covered else None
    sd = (
        sqrt(sum(weight * (value - mean) ** 2 for value, weight in intervals) / covered)
        if covered
        else None
    )
    return TimeInRangeMetrics(
        period_start_ms=start_ms,
        period_end_ms=end_ms,
        total_readings=len(intervals),
        covered_minutes=covered,
        total_minutes=total,
        coverage_percent=100 * covered / total,
        very_low_minutes=minutes["very_low"],
        low_minutes=minutes["low"],
        in_range_minutes=minutes["in_range"],
        high_minutes=minutes["high"],
        very_high_minutes=minutes["very_high"],
        mean_mgdl=mean,
        sd_mgdl=sd,
        cv_percent=100 * sd / mean if mean and sd is not None else None,
    )


def calculate_daily_percentiles(
    glucose: list[GlucoseReading], start_ms: int, end_ms: int, timezone_str: str, min_days: int = 5
) -> list[DailyPercentileOverlay]:
    if min_days < 1:
        raise ValueError("min_days must be positive")
    tz = ZoneInfo(timezone_str)
    bins = defaultdict(lambda: defaultdict(list))
    for reading in _unique_readings(glucose):
        if start_ms <= reading.event_ms < end_ms:
            dt = datetime.fromtimestamp(reading.event_ms / 1000, tz)
            bins[(dt.hour * 60 + dt.minute) // 30 * 30][dt.date()].append(reading.sgv_mgdl)
    result = []
    for start, days in sorted(bins.items()):
        if len(days) < min_days:
            continue
        values = [median(day) for day in days.values()]
        p5, p25, p50, p75, p95 = np.percentile(values, [5, 25, 50, 75, 95])
        result.append(
            DailyPercentileOverlay(
                bin_start_minutes=start,
                p5=p5,
                p25=p25,
                p50=p50,
                p75=p75,
                p95=p95,
                sample_count=len(values),
                days_contributing=len(days),
            )
        )
    return result


def calculate_daily_insulin_totals(treatments: list, start_ms: int, end_ms: int) -> dict:
    """Recorded confirmed bolus subtotals only; excludes calculators and basal estimates."""
    totals = defaultdict(Decimal)
    for tx in treatments:
        if (
            tx.valid
            and start_ms <= tx.event_ms < end_ms
            and tx.kind in (TreatmentKind.BOLUS, TreatmentKind.SMB)
            and tx.delivery_status == DeliveryStatus.DELIVERED
            and tx.insulin_u is not None
        ):
            day = datetime.fromtimestamp(tx.event_ms / 1000, ZoneInfo("UTC")).date().isoformat()
            totals[day] += tx.insulin_u
    return dict(totals)
