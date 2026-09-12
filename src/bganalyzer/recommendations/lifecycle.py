"""Recommendation lifecycle management."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from bganalyzer.contracts.analysis import RecommendationEvent
from bganalyzer.contracts.domain import RecommendationState
from bganalyzer.db.repository import Repository


@dataclass
class LifecycleTransition:
    """Recommendation state transition."""

    from_state: RecommendationState
    to_state: RecommendationState
    trigger: str
    reason: str
    timestamp: int


VALID_TRANSITIONS = {
    RecommendationState.DRAFT: [RecommendationState.WITHHELD, RecommendationState.READY_FOR_REVIEW],
    RecommendationState.WITHHELD: [RecommendationState.DRAFT, RecommendationState.DISMISSED],
    RecommendationState.READY_FOR_REVIEW: [
        RecommendationState.DISCUSSED,
        RecommendationState.DISMISSED,
        RecommendationState.SUPERSEDED,
    ],
    RecommendationState.DISCUSSED: [
        RecommendationState.USER_REPORTS_APPLIED,
        RecommendationState.DISMISSED,
        RecommendationState.SUPERSEDED,
    ],
    RecommendationState.USER_REPORTS_APPLIED: [
        RecommendationState.OBSERVED_PROFILE_CHANGE,
        RecommendationState.SUPERSEDED,
    ],
    RecommendationState.OBSERVED_PROFILE_CHANGE: [RecommendationState.SUPERSEDED],
    RecommendationState.DISMISSED: [RecommendationState.SUPERSEDED],
    RecommendationState.SUPERSEDED: [],
    RecommendationState.STALE: [RecommendationState.SUPERSEDED],
}


def can_transition(from_state: RecommendationState, to_state: RecommendationState) -> bool:
    """Check if state transition is valid."""
    return to_state in VALID_TRANSITIONS.get(from_state, [])


def transition_recommendation(
    repo: Repository, rec_id: UUID, to_state: RecommendationState, trigger: str, reason: str
) -> bool:
    """Perform recommendation state transition."""
    # Get current state
    # In practice, would fetch from DB
    current_state = RecommendationState.DRAFT  # Placeholder

    if not can_transition(current_state, to_state):
        return False

    # Update state
    repo.update_recommendation_state(rec_id, to_state.value)

    # Record event
    event = RecommendationEvent(
        recommendation_id=rec_id,
        event_ms=int(datetime.now().timestamp() * 1000),
        event_type=trigger,
        payload_json=f'{{"from": "{current_state.value}", "reason": "{reason}"}}',
    )
    repo.add_recommendation_event(event)

    return True


def supersede_recommendations(repo: Repository, profile_hash: str, reason: str) -> int:
    """Supersede all ready recommendations for a profile."""
    # Would query and update all recommendations for profile
    count = 0
    return count


def record_user_change(
    repo: Repository, rec_id: UUID, applied_values: dict, timestamp: int
) -> None:
    """Record user-reported profile change."""
    event = RecommendationEvent(
        recommendation_id=rec_id,
        event_ms=timestamp,
        event_type="user_reports_applied",
        payload_json=f'{{"applied_values": {applied_values}}}',
    )
    repo.add_recommendation_event(event)
    repo.update_recommendation_state(rec_id, RecommendationState.USER_REPORTS_APPLIED.value)


def detect_profile_change(repo: Repository, old_profile_hash: str, new_profile_hash: str) -> bool:
    """Detect if uploaded profile matches recommended changes."""
    return old_profile_hash != new_profile_hash
