"""Database migrations."""

import sqlite3
from datetime import datetime
from typing import Callable

from bganalyzer.logging_config import get_logger

logger = get_logger(__name__)

MIGRATIONS: list[tuple[int, str, Callable[[sqlite3.Connection], None]]] = []


def migration(version: int, name: str):
    """Decorator to register a migration."""

    def decorator(
        func: Callable[[sqlite3.Connection], None],
    ) -> Callable[[sqlite3.Connection], None]:
        MIGRATIONS.append((version, name, func))
        return func

    return decorator


@migration(1, "initial_schema")
def migration_001_initial(conn: sqlite3.Connection) -> None:
    """Create initial schema."""
    conn.executescript("""
        BEGIN IMMEDIATE;
        CREATE TABLE schema_version (
            version INTEGER PRIMARY KEY,
            applied_ms INTEGER NOT NULL
        );

        CREATE TABLE sources (
            id TEXT PRIMARY KEY,
            origin TEXT UNIQUE NOT NULL,
            api_mode TEXT,
            server_version TEXT,
            capabilities_json TEXT NOT NULL,
            created_ms INTEGER
        );

        CREATE TABLE sync_state (
            source_id TEXT NOT NULL,
            collection TEXT NOT NULL,
            cursor_json TEXT,
            backfill_start_ms INTEGER,
            backfill_end_ms INTEGER,
            last_success_ms INTEGER,
            last_error_code TEXT,
            PRIMARY KEY (source_id, collection),
            FOREIGN KEY (source_id) REFERENCES sources(id)
        );

        CREATE TABLE raw_records (
            source_id TEXT NOT NULL,
            collection TEXT NOT NULL,
            remote_id TEXT NOT NULL,
            revision_hash TEXT NOT NULL,
            event_ms INTEGER,
            server_modified_ms INTEGER,
            first_seen_ms INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            is_valid INTEGER NOT NULL CHECK (is_valid IN (0,1)),
            is_current INTEGER NOT NULL CHECK (is_current IN (0,1)),
            PRIMARY KEY (source_id, collection, remote_id, revision_hash)
        );

        CREATE INDEX idx_raw_records_current ON raw_records(source_id, collection, remote_id) WHERE is_current = 1;
        CREATE INDEX idx_raw_records_event_ms ON raw_records(event_ms);

        CREATE TABLE glucose (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            remote_id TEXT NOT NULL,
            revision_hash TEXT NOT NULL,
            event_ms INTEGER NOT NULL,
            sgv_mgdl REAL,
            valid INTEGER NOT NULL CHECK (valid IN (0,1)),
            quality_json TEXT,
            FOREIGN KEY (source_id) REFERENCES sources(id),
            UNIQUE (source_id, remote_id)
        );

        CREATE INDEX idx_glucose_event_ms ON glucose(event_ms);
        CREATE INDEX idx_glucose_source_event ON glucose(source_id, event_ms);

        CREATE TABLE treatments (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            remote_id TEXT NOT NULL,
            revision_hash TEXT NOT NULL,
            event_ms INTEGER,
            end_ms INTEGER,
            kind TEXT NOT NULL,
            insulin_u TEXT,
            carbs_g TEXT,
            rate_u_h TEXT,
            percent TEXT,
            delivery_status TEXT,
            pump_event_key TEXT,
            valid INTEGER NOT NULL CHECK (valid IN (0,1)),
            attributes_json TEXT,
            FOREIGN KEY (source_id) REFERENCES sources(id),
            UNIQUE (source_id, remote_id)
        );

        CREATE INDEX idx_treatments_event_ms ON treatments(event_ms);
        CREATE INDEX idx_treatments_pump_key ON treatments(pump_event_key);

        CREATE TABLE profile_versions (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            remote_id TEXT NOT NULL,
            revision_hash TEXT NOT NULL,
            profile_name TEXT,
            effective_from_ms INTEGER,
            timezone TEXT,
            units_original TEXT,
            normalized_json TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            FOREIGN KEY (source_id) REFERENCES sources(id),
            UNIQUE (source_id, remote_id)
        );

        CREATE INDEX idx_profile_effective ON profile_versions(effective_from_ms);

        CREATE TABLE profile_activations (
            id TEXT PRIMARY KEY,
            profile_version_id TEXT NOT NULL,
            start_ms INTEGER,
            end_ms INTEGER,
            percentage TEXT,
            time_shift_minutes INTEGER,
            origin TEXT,
            evidence_json TEXT,
            certainty TEXT,
            FOREIGN KEY (profile_version_id) REFERENCES profile_versions(id)
        );

        CREATE INDEX idx_activation_period ON profile_activations(start_ms, end_ms);

        CREATE TABLE device_status (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            remote_id TEXT NOT NULL,
            revision_hash TEXT NOT NULL,
            event_ms INTEGER,
            configuration_json TEXT,
            loop_json TEXT,
            quality_json TEXT,
            FOREIGN KEY (source_id) REFERENCES sources(id),
            UNIQUE (source_id, remote_id)
        );

        CREATE INDEX idx_device_status_event ON device_status(event_ms);

        CREATE TABLE annotations (
            id TEXT PRIMARY KEY,
            start_ms INTEGER,
            end_ms INTEGER,
            kind TEXT,
            text TEXT,
            attributes_json TEXT,
            created_ms INTEGER,
            updated_ms INTEGER,
            deleted_ms INTEGER
        );

        CREATE INDEX idx_annotations_period ON annotations(start_ms, end_ms);

        CREATE TABLE data_revisions (
            revision INTEGER PRIMARY KEY,
            committed_ms INTEGER NOT NULL,
            affected_start_ms INTEGER NOT NULL,
            affected_end_ms INTEGER NOT NULL,
            reason TEXT
        );

        CREATE TABLE analysis_runs (
            id TEXT PRIMARY KEY,
            data_revision INTEGER NOT NULL,
            start_ms INTEGER NOT NULL,
            end_ms INTEGER,
            profile_hash TEXT NOT NULL,
            algorithm_version TEXT NOT NULL,
            policy_hash TEXT NOT NULL,
            input_hash TEXT NOT NULL,
            state TEXT NOT NULL,
            metrics_json TEXT,
            created_ms INTEGER NOT NULL,
            error_code TEXT,
            UNIQUE (input_hash, algorithm_version, policy_hash)
        );

        CREATE INDEX idx_analysis_run_revision ON analysis_runs(data_revision);

        CREATE TABLE evidence (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            start_ms INTEGER,
            end_ms INTEGER,
            payload_json TEXT NOT NULL,
            source_refs_json TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            FOREIGN KEY (run_id) REFERENCES analysis_runs(id)
        );

        CREATE INDEX idx_evidence_run ON evidence(run_id);

        CREATE TABLE recommendations (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            family TEXT NOT NULL,
            state TEXT NOT NULL,
            baseline_profile_hash TEXT NOT NULL,
            candidate_json TEXT NOT NULL,
            evidence_ids_json TEXT NOT NULL,
            eligibility_json TEXT NOT NULL,
            created_ms INTEGER NOT NULL,
            FOREIGN KEY (run_id) REFERENCES analysis_runs(id)
        );

        CREATE INDEX idx_recommendations_run ON recommendations(run_id);

        CREATE TABLE recommendation_events (
            id TEXT PRIMARY KEY,
            recommendation_id TEXT NOT NULL,
            event_ms INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT,
            FOREIGN KEY (recommendation_id) REFERENCES recommendations(id)
        );

        CREATE INDEX idx_recommendation_events_rec ON recommendation_events(recommendation_id);

        CREATE TABLE explanations (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            evidence_hash TEXT NOT NULL,
            model_hash TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            validated_json TEXT,
            status TEXT NOT NULL,
            created_ms INTEGER NOT NULL,
            FOREIGN KEY (run_id) REFERENCES analysis_runs(id)
        );

        CREATE INDEX idx_explanations_run ON explanations(run_id);
    """)


@migration(2, "sync_journal_and_source_provenance")
def migration_002_sync_journal(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        BEGIN IMMEDIATE;
        CREATE TABLE sync_runs (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL REFERENCES sources(id),
            requested_start_ms INTEGER NOT NULL,
            requested_end_ms INTEGER NOT NULL,
            started_ms INTEGER NOT NULL,
            finished_ms INTEGER,
            state TEXT NOT NULL,
            stats_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX idx_sync_runs_source ON sync_runs(source_id, started_ms);
        CREATE TABLE sync_windows (
            source_id TEXT NOT NULL REFERENCES sources(id),
            collection TEXT NOT NULL,
            start_ms INTEGER NOT NULL,
            end_ms INTEGER NOT NULL CHECK(end_ms > start_ms),
            checked_ms INTEGER NOT NULL,
            state TEXT NOT NULL,
            record_count INTEGER NOT NULL DEFAULT 0,
            error_code TEXT,
            PRIMARY KEY(source_id, collection, start_ms, end_ms)
        );
        CREATE INDEX idx_sync_windows_range ON sync_windows(source_id, collection, start_ms, end_ms);
        CREATE TABLE sync_disappearances (
            source_id TEXT NOT NULL REFERENCES sources(id),
            collection TEXT NOT NULL,
            remote_id TEXT NOT NULL,
            first_missing_ms INTEGER NOT NULL,
            resolved_ms INTEGER,
            PRIMARY KEY(source_id, collection, remote_id)
        );
        ALTER TABLE data_revisions ADD COLUMN source_id TEXT REFERENCES sources(id);
        ALTER TABLE analysis_runs ADD COLUMN source_id TEXT REFERENCES sources(id);
        CREATE INDEX idx_analysis_source ON analysis_runs(source_id);
    """)


def get_current_version(conn: sqlite3.Connection) -> int:
    """Get current schema version."""
    try:
        cursor = conn.execute("SELECT MAX(version) FROM schema_version")
        row = cursor.fetchone()
        return row[0] if row and row[0] is not None else 0
    except sqlite3.OperationalError:
        return 0


def run_migrations(conn: sqlite3.Connection) -> None:
    """Run all pending migrations."""
    current_version = get_current_version(conn)
    logger.info("Current schema version", version=current_version)

    pending = [m for m in MIGRATIONS if m[0] > current_version]
    pending.sort(key=lambda x: x[0])

    for version, name, func in pending:
        logger.info("Applying migration", version=version, name=name)
        try:
            func(conn)
            conn.execute(
                "INSERT INTO schema_version (version, applied_ms) VALUES (?, ?)",
                (version, int(datetime.now().timestamp() * 1000)),
            )
            conn.commit()
            logger.info("Migration applied", version=version)
        except Exception:
            conn.rollback()
            logger.error("Migration failed", version=version)
            raise


def backup_database(config, backup_path: str) -> None:
    """Create a backup of the database."""
    import os

    from bganalyzer.db.connection import get_connection

    conn = get_connection(config)
    fd = os.open(backup_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    with sqlite3.connect(backup_path) as destination:
        conn.backup(destination)
    logger.info("Database backed up", path=backup_path)


@migration(3, "analysis_day_exclusions")
def migration_003_exclusions(conn: sqlite3.Connection) -> None:
    conn.execute("BEGIN IMMEDIATE")
    conn.execute("""CREATE TABLE analysis_exclusions (
        source_id TEXT NOT NULL REFERENCES sources(id),
        local_date TEXT NOT NULL, timezone TEXT NOT NULL,
        start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL,
        reason TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
        updated_ms INTEGER NOT NULL,
        PRIMARY KEY(source_id, local_date, timezone),
        CHECK(end_ms > start_ms), CHECK(active IN (0,1))
    )""")
