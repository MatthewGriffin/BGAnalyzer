"""Episode detection and analysis."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from bganalyzer.contracts.analysis import MealEpisode
from bganalyzer.contracts.domain import GlucoseReading


@dataclass
class GlucoseEpisode:
    """Continuous glucose episode."""

    start_ms: int
    end_ms: int
    min_mgdl: float
    max_mgdl: float
    mean_mgdl: float
    duration_minutes: float
    readings: list[GlucoseReading]


def find_hypoglycemic_episodes(
    glucose: list[GlucoseReading], threshold_mgdl: float = 70, min_duration_minutes: int = 15
) -> list[GlucoseEpisode]:
    """Find hypoglycemic episodes below threshold."""
    valid = [g for g in glucose if g.valid]
    valid.sort(key=lambda g: g.event_ms)

    episodes = []
    current_episode: list[GlucoseReading] = []

    for reading in valid:
        if reading.sgv_mgdl < threshold_mgdl:
            current_episode.append(reading)
        else:
            if current_episode:
                episode = _create_episode(current_episode)
                if episode.duration_minutes >= min_duration_minutes:
                    episodes.append(episode)
                current_episode = []

    if current_episode:
        episode = _create_episode(current_episode)
        if episode.duration_minutes >= min_duration_minutes:
            episodes.append(episode)

    return episodes


def _create_episode(readings: list[GlucoseReading]) -> GlucoseEpisode:
    """Create episode from readings."""
    start_ms = readings[0].event_ms
    end_ms = readings[-1].event_ms + 5 * 60 * 1000
    values = [r.sgv_mgdl for r in readings]

    return GlucoseEpisode(
        start_ms=start_ms,
        end_ms=end_ms,
        min_mgdl=min(values),
        max_mgdl=max(values),
        mean_mgdl=sum(values) / len(values),
        duration_minutes=(end_ms - start_ms) / 60000,
        readings=readings,
    )


def find_postprandial_episodes(
    meal_episodes: list[MealEpisode], glucose: list[GlucoseReading], window_minutes: int = 180
) -> list[MealEpisode]:
    """Analyze postprandial glucose for meal episodes."""
    valid_glucose = [g for g in glucose if g.valid]
    valid_glucose.sort(key=lambda g: g.event_ms)

    for episode in meal_episodes:
        window_end = episode.start_ms + window_minutes * 60 * 1000
        postprandial = [g for g in valid_glucose if episode.start_ms <= g.event_ms < window_end]

        if not postprandial:
            continue

        episode.peak_mgdl = max(g.sgv_mgdl for g in postprandial)

        high_threshold = 180
        episode.time_above_range_minutes = sum(
            5 for g in postprandial if g.sgv_mgdl > high_threshold
        )

        glucose_2h = _find_glucose_at(valid_glucose, episode.start_ms + 2 * 60 * 60 * 1000)
        glucose_4h = _find_glucose_at(valid_glucose, episode.start_ms + 4 * 60 * 60 * 1000)
        episode.glucose_2h_mgdl = glucose_2h
        episode.glucose_4h_mgdl = glucose_4h

    return meal_episodes


def _find_glucose_at(
    glucose: list[GlucoseReading], target_ms: int, tolerance_ms: int = 5 * 60 * 1000
) -> Optional[float]:
    """Find glucose reading near target time."""
    candidates = [g for g in glucose if abs(g.event_ms - target_ms) <= tolerance_ms]
    if not candidates:
        return None
    return min(candidates, key=lambda g: abs(g.event_ms - target_ms)).sgv_mgdl


def group_episodes_by_time_bucket(
    episodes: list[GlucoseEpisode], bucket_hours: int = 2
) -> dict[int, list[GlucoseEpisode]]:
    """Group episodes by time-of-day bucket."""
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("UTC")
    buckets: dict[int, list[GlucoseEpisode]] = {}

    for episode in episodes:
        dt = datetime.fromtimestamp(episode.start_ms / 1000, tz)
        bucket = (dt.hour // bucket_hours) * bucket_hours
        if bucket not in buckets:
            buckets[bucket] = []
        buckets[bucket].append(episode)

    return buckets
