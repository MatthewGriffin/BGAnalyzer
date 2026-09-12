"""Database repository layer."""

import json
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from bganalyzer.config import AppConfig
from bganalyzer.contracts.analysis import (
    AnalysisRun,
    EvidenceRecord,
    RecommendationEvent,
    RecommendationRecord,
)
from bganalyzer.contracts.domain import (
    Annotation,
    DataRevision,
    DeviceStatusRecord,
    GlucoseReading,
    ProfileActivation,
    ProfileVersion,
    SourceRecord,
    SyncCollection,
    SyncStateRecord,
    TreatmentEvent,
)
from bganalyzer.db.connection import transaction
from bganalyzer.logging_config import get_logger

logger = get_logger(__name__)


class Repository:
    """Data access layer for BGAnalyzer."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    # Source management
    def upsert_source(self, source: SourceRecord) -> None:
        with transaction(self.config) as conn:
            conn.execute(
                """
                INSERT INTO sources (id, origin, api_mode, server_version, capabilities_json, created_ms)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(origin) DO UPDATE SET
                    api_mode = excluded.api_mode,
                    server_version = excluded.server_version,
                    capabilities_json = excluded.capabilities_json
            """,
                (
                    source.id,
                    source.origin,
                    source.api_mode,
                    source.server_version,
                    source.capabilities_json,
                    source.created_ms,
                ),
            )

    def get_source(self, origin: str) -> Optional[SourceRecord]:
        with transaction(self.config) as conn:
            row = conn.execute("SELECT * FROM sources WHERE origin = ?", (origin,)).fetchone()
            if row:
                return SourceRecord(**dict(row))
            return None

    # Sync state
    def upsert_sync_state(self, state: SyncStateRecord) -> None:
        with transaction(self.config) as conn:
            conn.execute(
                """
                INSERT INTO sync_state (source_id, collection, cursor_json, backfill_start_ms,
                                       backfill_end_ms, last_success_ms, last_error_code)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id, collection) DO UPDATE SET
                    cursor_json = excluded.cursor_json,
                    backfill_start_ms = excluded.backfill_start_ms,
                    backfill_end_ms = excluded.backfill_end_ms,
                    last_success_ms = excluded.last_success_ms,
                    last_error_code = excluded.last_error_code
            """,
                (
                    state.source_id,
                    state.collection.value,
                    state.cursor_json,
                    state.backfill_start_ms,
                    state.backfill_end_ms,
                    state.last_success_ms,
                    state.last_error_code,
                ),
            )

    def get_sync_state(
        self, source_id: str, collection: SyncCollection
    ) -> Optional[SyncStateRecord]:
        with transaction(self.config) as conn:
            row = conn.execute(
                "SELECT * FROM sync_state WHERE source_id = ? AND collection = ?",
                (source_id, collection.value),
            ).fetchone()
            if row:
                data = dict(row)
                data["collection"] = SyncCollection(data["collection"])
                return SyncStateRecord(**data)
            return None

    # Raw records
    def insert_raw_record(
        self,
        source_id: str,
        collection: SyncCollection,
        remote_id: str,
        revision_hash: str,
        event_ms: Optional[int],
        server_modified_ms: Optional[int],
        payload: dict,
    ) -> bool:
        with transaction(self.config) as conn:
            current = conn.execute(
                "SELECT revision_hash FROM raw_records WHERE source_id=? AND collection=? AND remote_id=? AND is_current=1",
                (source_id, collection.value, remote_id),
            ).fetchone()
            if current and current[0] == revision_hash:
                return False
            conn.execute(
                """
                UPDATE raw_records SET is_current = 0
                WHERE source_id = ? AND collection = ? AND remote_id = ?
            """,
                (source_id, collection.value, remote_id),
            )
            conn.execute(
                """
                INSERT INTO raw_records (source_id, collection, remote_id, revision_hash,
                    event_ms, server_modified_ms, first_seen_ms, payload_json, is_valid, is_current)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(source_id, collection, remote_id, revision_hash)
                DO UPDATE SET is_current=1, is_valid=excluded.is_valid
            """,
                (
                    source_id,
                    collection.value,
                    remote_id,
                    revision_hash,
                    event_ms,
                    server_modified_ms,
                    int(datetime.now().timestamp() * 1000),
                    json.dumps(payload, separators=(",", ":"), sort_keys=True),
                    int(payload.get("isValid", True) is not False),
                ),
            )
            return True

    def mark_raw_invalid(
        self, source_id: str, collection: SyncCollection, remote_id: str, revision_hash: str
    ) -> None:
        with transaction(self.config) as conn:
            conn.execute(
                """
                UPDATE raw_records SET is_valid = 0, is_current = 0
                WHERE source_id = ? AND collection = ? AND remote_id = ? AND revision_hash = ?
            """,
                (source_id, collection.value, remote_id, revision_hash),
            )

    # Glucose
    def upsert_glucose(self, reading: GlucoseReading) -> None:
        with transaction(self.config) as conn:
            conn.execute(
                """
                INSERT INTO glucose (id, source_id, remote_id, revision_hash, event_ms,
                                    sgv_mgdl, valid, quality_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id, remote_id) DO UPDATE SET
                    revision_hash = excluded.revision_hash,
                    event_ms = excluded.event_ms,
                    sgv_mgdl = excluded.sgv_mgdl,
                    valid = excluded.valid,
                    quality_json = excluded.quality_json
            """,
                (
                    str(reading.id),
                    reading.source_id,
                    reading.remote_id,
                    reading.revision_hash,
                    reading.event_ms,
                    reading.sgv_mgdl,
                    1 if reading.valid else 0,
                    reading.quality_json,
                ),
            )

    def get_glucose_range(self, source_id: str, start_ms: int, end_ms: int) -> list[GlucoseReading]:
        with transaction(self.config) as conn:
            rows = conn.execute(
                """
                SELECT * FROM glucose WHERE source_id = ? AND event_ms >= ? AND event_ms < ?
                AND NOT EXISTS (SELECT 1 FROM sync_disappearances d WHERE d.source_id=glucose.source_id
                    AND d.collection='entries' AND d.remote_id=glucose.remote_id AND d.resolved_ms IS NULL)
                ORDER BY event_ms
            """,
                (source_id, start_ms, end_ms),
            ).fetchall()
            return [GlucoseReading(**dict(row)) for row in rows]

    # Treatments
    def upsert_treatment(self, treatment: TreatmentEvent) -> None:
        with transaction(self.config) as conn:
            conn.execute(
                """
                INSERT INTO treatments (id, source_id, remote_id, revision_hash, event_ms, end_ms,
                                       kind, insulin_u, carbs_g, rate_u_h, percent,
                                       delivery_status, pump_event_key, valid, attributes_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id, remote_id) DO UPDATE SET
                    revision_hash = excluded.revision_hash,
                    event_ms = excluded.event_ms,
                    end_ms = excluded.end_ms,
                    kind = excluded.kind,
                    insulin_u = excluded.insulin_u,
                    carbs_g = excluded.carbs_g,
                    rate_u_h = excluded.rate_u_h,
                    percent = excluded.percent,
                    delivery_status = excluded.delivery_status,
                    pump_event_key = excluded.pump_event_key,
                    valid = excluded.valid,
                    attributes_json = excluded.attributes_json
            """,
                (
                    str(treatment.id),
                    treatment.source_id,
                    treatment.remote_id,
                    treatment.revision_hash,
                    treatment.event_ms,
                    treatment.end_ms,
                    treatment.kind.value,
                    str(treatment.insulin_u) if treatment.insulin_u is not None else None,
                    str(treatment.carbs_g) if treatment.carbs_g is not None else None,
                    str(treatment.rate_u_h) if treatment.rate_u_h is not None else None,
                    str(treatment.percent) if treatment.percent is not None else None,
                    treatment.delivery_status.value,
                    treatment.pump_event_key,
                    1 if treatment.valid else 0,
                    treatment.attributes_json,
                ),
            )

    def get_treatments_range(
        self, source_id: str, start_ms: int, end_ms: int
    ) -> list[TreatmentEvent]:
        with transaction(self.config) as conn:
            rows = conn.execute(
                """
                SELECT * FROM treatments WHERE source_id = ? AND event_ms >= ? AND event_ms < ?
                ORDER BY event_ms
            """,
                (source_id, start_ms, end_ms),
            ).fetchall()
            return [TreatmentEvent(**dict(row)) for row in rows]

    # Profile versions
    def upsert_profile_version(self, profile: ProfileVersion) -> None:
        with transaction(self.config) as conn:
            conn.execute(
                """
                INSERT INTO profile_versions (id, source_id, remote_id, revision_hash,
                                             profile_name, effective_from_ms, timezone,
                                             units_original, normalized_json, content_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id, remote_id) DO UPDATE SET
                    revision_hash = excluded.revision_hash,
                    profile_name = excluded.profile_name,
                    effective_from_ms = excluded.effective_from_ms,
                    timezone = excluded.timezone,
                    units_original = excluded.units_original,
                    normalized_json = excluded.normalized_json,
                    content_hash = excluded.content_hash
            """,
                (
                    str(profile.id),
                    profile.source_id,
                    profile.remote_id,
                    profile.revision_hash,
                    profile.profile_name,
                    profile.effective_from_ms,
                    profile.timezone,
                    profile.units_original,
                    profile.normalized_json,
                    profile.content_hash,
                ),
            )

    def get_profile_versions(self, source_id: str) -> list[ProfileVersion]:
        with transaction(self.config) as conn:
            rows = conn.execute(
                """
                SELECT * FROM profile_versions WHERE source_id = ?
                ORDER BY effective_from_ms
            """,
                (source_id,),
            ).fetchall()
            return [ProfileVersion(**dict(row)) for row in rows]

    # Profile activations
    def upsert_profile_activation(self, activation: ProfileActivation) -> None:
        with transaction(self.config) as conn:
            conn.execute(
                """
                INSERT INTO profile_activations (id, profile_version_id, start_ms, end_ms,
                                                percentage, time_shift_minutes, origin,
                                                evidence_json, certainty)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    profile_version_id = excluded.profile_version_id,
                    start_ms = excluded.start_ms,
                    end_ms = excluded.end_ms,
                    percentage = excluded.percentage,
                    time_shift_minutes = excluded.time_shift_minutes,
                    origin = excluded.origin,
                    evidence_json = excluded.evidence_json,
                    certainty = excluded.certainty
            """,
                (
                    str(activation.id),
                    str(activation.profile_version_id),
                    activation.start_ms,
                    activation.end_ms,
                    str(activation.percentage) if activation.percentage else None,
                    activation.time_shift_minutes,
                    activation.origin.value,
                    activation.evidence_json,
                    activation.certainty,
                ),
            )

    def get_active_profile_at(self, source_id: str, at_ms: int) -> Optional[ProfileActivation]:
        with transaction(self.config) as conn:
            row = conn.execute(
                """
                SELECT pa.* FROM profile_activations pa
                JOIN profile_versions pv ON pa.profile_version_id = pv.id
                WHERE pv.source_id = ? AND pa.start_ms <= ? AND (pa.end_ms IS NULL OR pa.end_ms > ?)
                ORDER BY pa.start_ms DESC LIMIT 1
            """,
                (source_id, at_ms, at_ms),
            ).fetchone()
            if row:
                return ProfileActivation(**dict(row))
            return None

    def delete_activations_by_origin(self, source_id: str, origin: str) -> int:
        """Delete activations of one origin for a source; returns rows removed."""
        with transaction(self.config) as conn:
            cursor = conn.execute(
                """
                DELETE FROM profile_activations WHERE id IN (
                    SELECT pa.id FROM profile_activations pa
                    JOIN profile_versions pv ON pa.profile_version_id = pv.id
                    WHERE pv.source_id = ? AND pa.origin = ?
                )
            """,
                (source_id, origin),
            )
            return cursor.rowcount

    def get_profile_version_id(self, source_id: str, remote_id: str) -> Optional[str]:
        """Primary key of a stored profile version, if present."""
        with transaction(self.config) as conn:
            row = conn.execute(
                "SELECT id FROM profile_versions WHERE source_id = ? AND remote_id = ?",
                (source_id, remote_id),
            ).fetchone()
            return row[0] if row else None

    def get_profile_note_records(self, source_id: str, end_ms: int) -> list[dict]:
        """Current profile-bearing treatment uploads below end_ms for evidence.

        Covers effective-profile Notes and Profile Switch records (including
        Nightscout-entered switches without a profile JSON, which still bound
        the preceding interval as barriers).
        """
        with transaction(self.config) as conn:
            rows = conn.execute(
                """SELECT remote_id,revision_hash,event_ms,payload_json,is_valid FROM raw_records
                WHERE source_id=? AND collection='treatments' AND is_current=1 AND event_ms<?
                AND (json_extract(payload_json,'$.profileJson') IS NOT NULL
                     OR json_extract(payload_json,'$.originalCustomizedName') IS NOT NULL
                     OR json_extract(payload_json,'$.eventType') = 'Profile Switch')""",
                (source_id, end_ms),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_unresolved_disappearances(self, source_id: str, collection: SyncCollection) -> list[str]:
        """Remote IDs missing locally without a resolution."""
        with transaction(self.config) as conn:
            rows = conn.execute(
                """SELECT remote_id FROM sync_disappearances
                WHERE source_id=? AND collection=? AND resolved_ms IS NULL""",
                (source_id, collection.value),
            ).fetchall()
            return [row[0] for row in rows]

    # Device status
    def upsert_device_status(self, status: DeviceStatusRecord) -> None:
        with transaction(self.config) as conn:
            conn.execute(
                """
                INSERT INTO device_status (id, source_id, remote_id, revision_hash,
                                          event_ms, configuration_json, loop_json, quality_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id, remote_id) DO UPDATE SET
                    revision_hash = excluded.revision_hash,
                    event_ms = excluded.event_ms,
                    configuration_json = excluded.configuration_json,
                    loop_json = excluded.loop_json,
                    quality_json = excluded.quality_json
            """,
                (
                    str(status.id),
                    status.source_id,
                    status.remote_id,
                    status.revision_hash,
                    status.event_ms,
                    status.configuration_json,
                    status.loop_json,
                    status.quality_json,
                ),
            )

    # Annotations
    def upsert_annotation(self, annotation: Annotation) -> None:
        with transaction(self.config) as conn:
            conn.execute(
                """
                INSERT INTO annotations (id, start_ms, end_ms, kind, text,
                                        attributes_json, created_ms, updated_ms, deleted_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    start_ms = excluded.start_ms,
                    end_ms = excluded.end_ms,
                    kind = excluded.kind,
                    text = excluded.text,
                    attributes_json = excluded.attributes_json,
                    updated_ms = excluded.updated_ms,
                    deleted_ms = excluded.deleted_ms
            """,
                (
                    str(annotation.id),
                    annotation.start_ms,
                    annotation.end_ms,
                    annotation.kind,
                    annotation.text,
                    annotation.attributes_json,
                    annotation.created_ms,
                    annotation.updated_ms,
                    annotation.deleted_ms,
                ),
            )

    def get_annotations_range(self, start_ms: int, end_ms: int) -> list[Annotation]:
        with transaction(self.config) as conn:
            rows = conn.execute(
                """
                SELECT * FROM annotations 
                WHERE start_ms < ? AND (end_ms IS NULL OR end_ms > ?) AND deleted_ms IS NULL
                ORDER BY start_ms
            """,
                (end_ms, start_ms),
            ).fetchall()
            return [Annotation(**dict(row)) for row in rows]

    # Data revisions
    def create_data_revision(self, revision: DataRevision) -> None:
        with transaction(self.config) as conn:
            conn.execute(
                """
                INSERT INTO data_revisions (revision, committed_ms, affected_start_ms,
                                           affected_end_ms, reason)
                VALUES (?, ?, ?, ?, ?)
            """,
                (
                    revision.revision,
                    revision.committed_ms,
                    revision.affected_start_ms,
                    revision.affected_end_ms,
                    revision.reason,
                ),
            )

    # Analysis runs
    def insert_analysis_run(self, run: AnalysisRun) -> None:
        with transaction(self.config) as conn:
            conn.execute(
                """
                INSERT INTO analysis_runs (id, data_revision, start_ms, end_ms, profile_hash,
                                          algorithm_version, policy_hash, input_hash, state,
                                          metrics_json, created_ms, error_code, source_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    str(run.id),
                    run.data_revision,
                    run.start_ms,
                    run.end_ms,
                    run.profile_hash,
                    run.algorithm_version,
                    run.policy_hash,
                    run.input_hash,
                    run.state,
                    run.metrics_json,
                    run.created_ms,
                    run.error_code,
                    run.source_id,
                ),
            )

    def update_analysis_run(self, run: AnalysisRun) -> None:
        with transaction(self.config) as conn:
            conn.execute(
                """
                UPDATE analysis_runs SET end_ms = ?, state = ?, metrics_json = ?, error_code = ?
                WHERE id = ?
            """,
                (run.end_ms, run.state, run.metrics_json, run.error_code, str(run.id)),
            )

    def get_latest_analysis_run(self) -> Optional[AnalysisRun]:
        with transaction(self.config) as conn:
            row = conn.execute("""
                SELECT * FROM analysis_runs ORDER BY created_ms DESC LIMIT 1
            """).fetchone()
            if row:
                return AnalysisRun(**dict(row))
            return None

    # Evidence
    def insert_evidence(self, evidence: EvidenceRecord) -> None:
        with transaction(self.config) as conn:
            conn.execute(
                """
                INSERT INTO evidence (id, run_id, kind, start_ms, end_ms,
                                     payload_json, source_refs_json, content_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    str(evidence.id),
                    str(evidence.run_id),
                    evidence.kind.value,
                    evidence.start_ms,
                    evidence.end_ms,
                    evidence.payload_json,
                    evidence.source_refs_json,
                    evidence.content_hash,
                ),
            )

    # Recommendations
    def insert_recommendation(self, rec: RecommendationRecord) -> None:
        with transaction(self.config) as conn:
            conn.execute(
                """
                INSERT INTO recommendations (id, run_id, family, state, baseline_profile_hash,
                                            candidate_json, evidence_ids_json, eligibility_json,
                                            created_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    str(rec.id),
                    str(rec.run_id),
                    rec.family.value,
                    rec.state.value,
                    rec.baseline_profile_hash,
                    rec.candidate_json,
                    rec.evidence_ids_json,
                    rec.eligibility_json,
                    rec.created_ms,
                ),
            )

    def update_recommendation_state(self, rec_id: UUID, state: str) -> None:
        with transaction(self.config) as conn:
            conn.execute(
                """
                UPDATE recommendations SET state = ? WHERE id = ?
            """,
                (state, str(rec_id)),
            )

    def add_recommendation_event(self, event: RecommendationEvent) -> None:
        with transaction(self.config) as conn:
            conn.execute(
                """
                INSERT INTO recommendation_events (id, recommendation_id, event_ms, event_type, payload_json)
                VALUES (?, ?, ?, ?, ?)
            """,
                (
                    str(event.id),
                    str(event.recommendation_id),
                    event.event_ms,
                    event.event_type,
                    event.payload_json,
                ),
            )

    # Explanations
    def insert_explanation(self, explanation: Any) -> None:
        with transaction(self.config) as conn:
            conn.execute(
                """
                INSERT INTO explanations (id, run_id, evidence_hash, model_hash,
                                         prompt_version, validated_json, status, created_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    str(explanation.id),
                    str(explanation.run_id),
                    explanation.evidence_hash,
                    explanation.model_hash,
                    explanation.prompt_version,
                    explanation.validated_json,
                    explanation.status,
                    explanation.created_ms,
                ),
            )
