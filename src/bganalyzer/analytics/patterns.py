"""Pattern detection rules."""

from dataclasses import dataclass
from uuid import uuid4

from bganalyzer.analytics.episodes import find_hypoglycemic_episodes, group_episodes_by_time_bucket
from bganalyzer.contracts.analysis import MealEpisode, PatternFinding
from bganalyzer.contracts.domain import GlucoseReading, TreatmentEvent


@dataclass
class PatternRuleResult:
    """Result of a pattern rule evaluation."""

    findings: list[PatternFinding]
    excluded_days: list[int]
    contradictory_days: list[int]


def detect_repeated_low_episodes(
    glucose: list[GlucoseReading],
    low_threshold_mgdl: float = 70,
    min_days: int = 3,
    min_duration_minutes: int = 15,
) -> PatternRuleResult:
    """Detect repeated low glucose episodes in same time bucket."""
    episodes = find_hypoglycemic_episodes(glucose, low_threshold_mgdl, min_duration_minutes)
    buckets = group_episodes_by_time_bucket(episodes, bucket_hours=2)

    findings = []
    excluded_days = []
    contradictory_days = []

    for bucket_hour, bucket_episodes in buckets.items():
        days_with_episodes = set()
        for ep in bucket_episodes:
            from datetime import datetime
            from zoneinfo import ZoneInfo

            dt = datetime.fromtimestamp(ep.start_ms / 1000, ZoneInfo("UTC"))
            days_with_episodes.add(dt.date().toordinal())

        if len(days_with_episodes) >= min_days:
            finding = PatternFinding(
                id=uuid4(),
                rule_version="patterns-v1",
                rule_name="repeated_low_episodes",
                description=f"Repeated low glucose episodes in {bucket_hour:02d}:00-{bucket_hour+2:02d}:00 bucket on {len(days_with_episodes)} days",
                severity="high",
                contributing_days=sorted(days_with_episodes),
                conflicting_days=[],
                evidence_ids=[],  # Would be populated with actual evidence IDs
                exclusion_codes=[],
                metadata_json=f'{{"bucket_hour": {bucket_hour}, "episode_count": {len(bucket_episodes)}}}',
            )
            findings.append(finding)

    return PatternRuleResult(findings, excluded_days, contradictory_days)


def detect_repeated_postmeal_elevation(
    meal_episodes: list[MealEpisode],
    high_threshold_mgdl: float = 180,
    min_episodes: int = 5,
    min_days: int = 3,
    proportion_threshold: float = 0.5,
) -> PatternRuleResult:
    """Detect repeated post-meal glucose elevation."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    buckets: dict[int, list[MealEpisode]] = {}

    for episode in meal_episodes:
        if episode.time_above_range_minutes <= 0:
            continue
        dt = datetime.fromtimestamp(episode.start_ms / 1000, ZoneInfo("UTC"))
        bucket = (dt.hour // 4) * 4
        if bucket not in buckets:
            buckets[bucket] = []
        buckets[bucket].append(episode)

    findings = []
    excluded_days = []
    contradictory_days = []

    for bucket_hour, bucket_episodes in buckets.items():
        if len(bucket_episodes) < min_episodes:
            continue

        days = set()
        for ep in bucket_episodes:
            dt = datetime.fromtimestamp(ep.start_ms / 1000, ZoneInfo("UTC"))
            days.add(dt.date().toordinal())

        if len(days) < min_days:
            continue

        prop_above = sum(1 for ep in bucket_episodes if ep.time_above_range_minutes > 0) / len(
            bucket_episodes
        )

        if prop_above >= proportion_threshold:
            finding = PatternFinding(
                id=uuid4(),
                rule_version="patterns-v1",
                rule_name="repeated_postmeal_elevation",
                description=f"Repeated post-meal elevation in {bucket_hour:02d}:00-{bucket_hour+4:02d}:00 bucket ({prop_above:.0%} of episodes)",
                severity="medium",
                contributing_days=sorted(days),
                conflicting_days=[],
                evidence_ids=[],
                exclusion_codes=[],
                metadata_json=f'{{"bucket_hour": {bucket_hour}, "proportion_above": {prop_above}, "episode_count": {len(bucket_episodes)}}}',
            )
            findings.append(finding)

    return PatternRuleResult(findings, excluded_days, contradictory_days)


def detect_loop_compensation(
    treatments: list[TreatmentEvent], min_days: int = 5, consistency_threshold: float = 0.8
) -> PatternRuleResult:
    """Detect repeated loop compensation via temp basals."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    temp_basals = [t for t in treatments if t.kind.name == "TEMP_BASAL" and t.rate_u_h]

    buckets: dict[int, list[TreatmentEvent]] = {}

    for tx in temp_basals:
        dt = datetime.fromtimestamp(tx.event_ms / 1000, ZoneInfo("UTC"))
        bucket = (dt.hour // 2) * 2
        if bucket not in buckets:
            buckets[bucket] = []
        buckets[bucket].append(tx)

    findings = []
    excluded_days = []
    contradictory_days = []

    for bucket_hour, bucket_txs in buckets.items():
        days_data = {}
        for tx in bucket_txs:
            dt = datetime.fromtimestamp(tx.event_ms / 1000, ZoneInfo("UTC"))
            day = dt.date().toordinal()
            if day not in days_data:
                days_data[day] = {"positive": 0, "negative": 0}
            if tx.rate_u_h > 0:
                days_data[day]["positive"] += 1
            elif tx.rate_u_h < 0:
                days_data[day]["negative"] += 1

        consistent_days = 0
        for day_data in days_data.values():
            total = day_data["positive"] + day_data["negative"]
            if total > 0:
                max_dir = max(day_data["positive"], day_data["negative"])
                if max_dir / total >= consistency_threshold:
                    consistent_days += 1

        if consistent_days >= min_days:
            direction = "increase" if day_data["positive"] > day_data["negative"] else "decrease"
            finding = PatternFinding(
                id=uuid4(),
                rule_version="patterns-v1",
                rule_name="repeated_loop_compensation",
                description=f"Repeated loop compensation ({direction}) in {bucket_hour:02d}:00-{bucket_hour+2:02d}:00 bucket on {consistent_days} days",
                severity="medium",
                contributing_days=sorted(days_data.keys()),
                conflicting_days=[],
                evidence_ids=[],
                exclusion_codes=[],
                metadata_json=f'{{"bucket_hour": {bucket_hour}, "direction": "{direction}", "consistent_days": {consistent_days}}}',
            )
            findings.append(finding)

    return PatternRuleResult(findings, excluded_days, contradictory_days)


def detect_data_quality_issues(
    glucose: list[GlucoseReading],
    treatments: list[TreatmentEvent],
    profile_changes: list,
    annotations: list,
) -> PatternRuleResult:
    """Detect data quality issues that affect analysis."""
    findings = []
    excluded_days = []
    contradictory_days = []

    from bganalyzer.timeline.quality import assess_glucose_quality

    if glucose:
        quality = assess_glucose_quality(glucose, 0, 2**63 - 1)
        if quality.glucose_coverage_percent < 90:
            finding = PatternFinding(
                id=uuid4(),
                rule_version="patterns-v1",
                rule_name="low_glucose_coverage",
                description=f"Glucose coverage only {quality.glucose_coverage_percent:.1f}%",
                severity="high",
                contributing_days=[],
                conflicting_days=[],
                evidence_ids=[],
                exclusion_codes=["LOW_COVERAGE"],
                metadata_json=f'{{"coverage_percent": {quality.glucose_coverage_percent}}}',
            )
            findings.append(finding)

    return PatternRuleResult(findings, excluded_days, contradictory_days)


def run_all_pattern_rules(
    glucose: list[GlucoseReading],
    treatments: list[TreatmentEvent],
    meal_episodes: list[MealEpisode],
    profile_changes: list,
    annotations: list,
    low_threshold: float = 70,
    high_threshold: float = 180,
) -> list[PatternFinding]:
    """Run all pattern detection rules."""
    all_findings = []

    result1 = detect_repeated_low_episodes(glucose, low_threshold)
    all_findings.extend(result1.findings)

    result2 = detect_repeated_postmeal_elevation(meal_episodes, high_threshold)
    all_findings.extend(result2.findings)

    result3 = detect_loop_compensation(treatments)
    all_findings.extend(result3.findings)

    result4 = detect_data_quality_issues(glucose, treatments, profile_changes, annotations)
    all_findings.extend(result4.findings)

    # Sort by severity and evidence
    severity_order = {"high": 0, "medium": 1, "low": 2}
    all_findings.sort(key=lambda f: (severity_order.get(f.severity, 3), -len(f.contributing_days)))

    return all_findings
