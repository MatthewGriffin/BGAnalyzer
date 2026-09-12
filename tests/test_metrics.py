from datetime import datetime, timezone

import pytest

from bganalyzer.analytics.metrics import (
    ReportBands,
    calculate_daily_percentiles,
    calculate_tir_metrics,
)
from bganalyzer.contracts.domain import GlucoseReading


def reading(ms, value, valid=True):
    return GlucoseReading(
        source_id="s",
        remote_id=str(ms),
        revision_hash="r",
        event_ms=ms,
        sgv_mgdl=value,
        valid=valid,
    )


def test_weighted_mean_and_end_clipping():
    result = calculate_tir_metrics([reading(0, 100), reading(60_000, 200)], 0, 180_000)
    assert result.covered_minutes == 3
    assert result.coverage_percent == 100
    assert result.mean_mgdl == pytest.approx(500 / 3)
    assert result.sd_mgdl == pytest.approx(47.140452)
    assert result.in_range_minutes == 1
    assert result.high_minutes == 2


def test_no_gap_filling_and_predecessor_clip():
    result = calculate_tir_metrics([reading(0, 100), reading(600_000, 200)], 60_000, 660_000)
    assert result.covered_minutes == 5
    assert result.coverage_percent == 50
    assert result.mean_mgdl == 120


def test_empty_has_null_metrics():
    result = calculate_tir_metrics([], 0, 300_000)
    assert result.mean_mgdl is None
    assert result.sd_mgdl is None
    assert result.covered_minutes == 0


def test_conflicting_sensor_values_do_not_choose_one():
    result = calculate_tir_metrics([reading(0, 100), reading(0, 200)], 0, 300_000)
    assert result.covered_minutes == 0


@pytest.mark.parametrize("end", [0, -1])
def test_invalid_window(end):
    with pytest.raises(ValueError):
        calculate_tir_metrics([], 0, end)


def test_bucket_boundaries():
    result = calculate_tir_metrics(
        [reading(i * 300_000, value) for i, value in enumerate([53, 54, 70, 180, 250, 251])],
        0,
        1_800_000,
    )
    assert [
        result.very_low_minutes,
        result.low_minutes,
        result.in_range_minutes,
        result.high_minutes,
        result.very_high_minutes,
    ] == [5, 5, 10, 5, 5]


def test_distinct_day_percentiles_not_reading_count():
    start = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    values = [reading(start + i * 60_000, 100) for i in range(10)]
    assert calculate_daily_percentiles(values, start, start + 86_400_000, "Europe/London") == []
    values += [reading(start + day * 86_400_000, 200) for day in range(1, 5)]
    result = calculate_daily_percentiles(values, start, start + 5 * 86_400_000, "Europe/London")
    assert result[0].days_contributing == 5
    assert result[0].p50 == 200


def test_invalid_bands():
    with pytest.raises(ValueError):
        ReportBands(low=200, high=180)
