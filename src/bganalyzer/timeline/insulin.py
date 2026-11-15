"""Conservative reported delivery reconstruction; physical delivery is unverified.

Implements resolve_delivery(start_ms, end_ms) -> list[DeliveryInterval]
as specified in IMPLEMENTATION_PLAN.md section 8.

Upstream commit: 1393357107a2b27ba153df31d64e745efd771ef2
Reference target: AAPS AutotuneIob.kt. This module has not passed parity.
Unknown intervals never become confirmed delivery. Numerical conversion is verified separately.
"""

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from bganalyzer.timeline.profiles import ProfileTimeline, ResolvedProfile


class DeliveryOrigin(str, Enum):
    """Origin of insulin delivery."""

    REPORTED_TEMP = "reported_temp"       # Confirmed temp basal from pump
    SCHEDULED_ASSUMED = "scheduled_assumed"  # Scheduled basal (no temp recorded)
    REPORTED_SUSPEND = "reported_suspend"    # Explicit suspend
    REPORTED_RESUME = "reported_resume"      # Explicit resume
    BOLUS = "bolus"                        # Normal bolus
    SMB = "smb"                            # Super micro bolus
    EXTENDED_BOLUS = "extended_bolus"      # Extended/combo bolus
    UNKNOWN = "unknown"                    # Unresolved/conflicting


@dataclass
class DeliveryInterval:
    """Insulin delivery interval with provenance."""

    start_ms: int
    end_ms: int
    rate_u_hr: float  # For basal: U/hr; for bolus: total U over interval
    origin: DeliveryOrigin
    source_ids: List[str]  # Treatment/event IDs
    quality: str  # "confirmed" | "assumed" | "uncertain" | "conflicted"
    profile_basal_at_start: float = 0.0  # Scheduled basal rate at interval start
    is_percentage: bool = False  # True if temp basal was percentage-based
    percent_value: float = 0.0  # Percentage value if is_percentage

    @property
    def duration_minutes(self) -> int:
        return (self.end_ms - self.start_ms) // 60000

    @property
    def insulin_units(self) -> float:
        """Total insulin delivered in this interval."""
        if self.origin in (DeliveryOrigin.BOLUS, DeliveryOrigin.SMB, DeliveryOrigin.EXTENDED_BOLUS):
            return self.rate_u_hr
        return self.rate_u_hr * (self.end_ms - self.start_ms) / 3600000.0


@dataclass
class BolusDelivery:
    """Discrete bolus delivery event."""

    event_ms: int
    amount_u: float
    origin: DeliveryOrigin
    source_id: str
    is_valid: bool = True
    delivery_status: str = "delivered"  # "delivered" | "cancelled" | "unknown"


class DeliveryTimeline:
    """Reported interval evidence; gaps and ambiguous transitions remain unknown."""

    def __init__(self, treatments, profile_timeline, default_timezone="UTC"):
        self.treatments = treatments
        self.profile_timeline = profile_timeline
        self.default_timezone = default_timezone
        self._cache = {}

    def _records(self, start_ms, end_ms):
        import json
        records = []
        for treatment in self.treatments:
            if treatment['event_ms'] >= end_ms:
                continue
            if treatment.get('end_ms') is not None and treatment['end_ms'] <= start_ms:
                continue
            if treatment.get('end_ms') is None and treatment['event_ms'] < start_ms:
                continue
            # Withdrawn revisions are not delivered events. Disappeared records
            # retain an uncertainty barrier instead of silently disappearing.
            if not treatment.get('valid', True) and not treatment.get('presence_unknown'):
                continue
            payload = treatment.get('payload_json')
            if payload is None:
                kind = treatment.get('kind')
                event = {'temp_basal': 'Temp Basal', 'suspend': 'Suspend', 'resume': 'Resume',
                         'site_change': 'Site Change', 'insulin_change': 'Insulin Change'}.get(kind)
                if not event:
                    continue
                data = {'eventType': event, 'isValid': bool(treatment.get('valid', True))}
                if kind == 'temp_basal':
                    if treatment.get('end_ms') is not None:
                        data['durationInMilliseconds'] = treatment['end_ms'] - treatment['event_ms']
                    if treatment.get('percent') is not None:
                        data['percent'] = treatment['percent']
                    elif treatment.get('rate_u_h') is not None:
                        data['absolute'] = treatment['rate_u_h']
                payload = json.dumps(data)
            records.append(dict(remote_id=treatment['remote_id'], revision_hash=treatment.get('revision_hash', ''),
                                event_ms=treatment['event_ms'], payload_json=payload,
                                is_valid=bool(treatment.get('valid', True)),
                                presence_unknown=treatment.get('presence_unknown', False)))
        return records

    def reported_segments(self, start_ms, end_ms):
        from bganalyzer.timeline.basal_delivery import reported_basal_segments
        key = (start_ms, end_ms)
        if key in self._cache:
            return self._cache[key]
        boundaries = {start_ms, end_ms}
        for act in self.profile_timeline.activations:
            boundaries.update(t for t in (act.start_ms, act.end_ms) if t is not None and start_ms < t < end_ms)
        boundaries.update(p.effective_from_ms for p in self.profile_timeline.store_versions
                          if start_ms < p.effective_from_ms < end_ms)
        times = sorted(boundaries)
        profiles = []
        for lo, hi in zip(times, times[1:]):
            profile = self.profile_timeline.resolve_profile(lo)
            if not isinstance(profile, ResolvedProfile):
                continue
            profiles.append({'start_ms': lo, 'end_ms': hi,
                             'source_refs': [{'remote_id': profile.source_profile_id,
                                              'revision_hash': profile.activation_evidence.profile_version.revision_hash}],
                             'profile': {'timezone': profile.timezone,
                                         'basal': [{'time': time, 'value': rate} for time, rate in profile.basal_schedule]}})
        result = reported_basal_segments(self._records(start_ms, end_ms), profiles, start_ms, end_ms)
        self._cache[key] = result
        return result

    def issues_in_range(self, start_ms, end_ms):
        # Ordinary gaps are recorded as unverified coverage, separately from
        # explicit ambiguous/conflicting events that invalidate a tuning day.
        return [s for s in self.reported_segments(start_ms, end_ms)['segments']
                if s['reason'] not in ('reported_rate_only', 'no_reported_temp_basal')]

    def resolve_delivery(self, start_ms, end_ms):
        result = []
        for segment in self.reported_segments(start_ms, end_ms)['segments']:
            known = segment['rate_u_h'] is not None
            result.append(DeliveryInterval(
                start_ms=segment['start_ms'], end_ms=segment['end_ms'],
                rate_u_hr=segment['rate_u_h'] if known else 0.0,
                origin=DeliveryOrigin.REPORTED_TEMP if known else DeliveryOrigin.UNKNOWN,
                source_ids=[r['remote_id'] for r in segment['source_refs']],
                quality='reported' if known else 'uncertain'))
        return result

    def get_bolus_deliveries(self, start_ms, end_ms):
        import math
        return [BolusDelivery(t['event_ms'], t['insulin_u'],
                              DeliveryOrigin.SMB if t['kind'] == 'smb' else DeliveryOrigin.BOLUS,
                              t['remote_id'], delivery_status=t.get('delivery_status', 'unknown'))
                for t in self.treatments if t.get('kind') in ('bolus', 'smb')
                and t.get('valid', True) and not t.get('presence_unknown')
                and t.get('delivery_status') != 'cancelled' and start_ms <= t['event_ms'] < end_ms
                and type(t.get('insulin_u')) in (int, float) and math.isfinite(t['insulin_u']) and t['insulin_u'] > 0]


def build_delivery_timeline(conn, source_id, start_ms, end_ms, profile_timeline):
    rows = conn.execute("""
        SELECT t.remote_id,t.revision_hash,t.event_ms,t.end_ms,t.kind,t.insulin_u,t.carbs_g,
               t.rate_u_h,t.percent,t.delivery_status,t.valid,r.payload_json,
               EXISTS(SELECT 1 FROM sync_disappearances d WHERE d.source_id=t.source_id
                   AND d.collection='treatments' AND d.remote_id=t.remote_id AND d.resolved_ms IS NULL) AS presence_unknown
        FROM treatments t LEFT JOIN raw_records r ON r.source_id=t.source_id
            AND r.collection='treatments' AND r.remote_id=t.remote_id
            AND r.revision_hash=t.revision_hash AND r.is_current=1
        WHERE t.source_id=? AND t.event_ms<?
        ORDER BY t.event_ms
    """, (source_id, end_ms)).fetchall()
    return DeliveryTimeline([dict(row) for row in rows], profile_timeline)
