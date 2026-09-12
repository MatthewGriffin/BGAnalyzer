"""Thread-owned SQLite connections and nestable atomic transactions."""

import sqlite3
import threading
from contextlib import contextmanager
from itertools import count

from bganalyzer.config import AppConfig

_thread_local = threading.local()
_savepoints = count()


def get_connection(config: AppConfig, read_only: bool = False) -> sqlite3.Connection:
    connections = getattr(_thread_local, "connections", None)
    if connections is None:
        connections = _thread_local.connections = {}
    key = (str(config.db_path.resolve()), read_only)
    if key not in connections:
        config.ensure_dirs()
        if not read_only and not config.db_path.exists():
            config.db_path.touch(mode=0o600)
        conn = sqlite3.connect(
            config.db_path.as_uri() + ("?mode=ro" if read_only else "?mode=rwc"), uri=True
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        if not read_only:
            conn.execute("PRAGMA journal_mode=WAL")
            config.db_path.chmod(0o600)
        connections[key] = conn
    return connections[key]


@contextmanager
def transaction(config: AppConfig):
    conn = get_connection(config)
    name = f"tx_{next(_savepoints)}"
    conn.execute(f"SAVEPOINT {name}")
    try:
        yield conn
        conn.execute(f"RELEASE SAVEPOINT {name}")
    except BaseException:
        conn.execute(f"ROLLBACK TO SAVEPOINT {name}")
        conn.execute(f"RELEASE SAVEPOINT {name}")
        raise


def close_connection() -> None:
    for conn in getattr(_thread_local, "connections", {}).values():
        conn.close()
    _thread_local.connections = {}


def initialize_database(config: AppConfig) -> None:
    from bganalyzer.db.migrations import (
        MIGRATIONS,
        backup_database,
        get_current_version,
        run_migrations,
    )

    conn = get_connection(config)
    current = get_current_version(conn)
    target = max(version for version, _, _ in MIGRATIONS)
    if 0 < current < target:
        from uuid import uuid4

        backup = config.data_dir / f"before-migration-{current}-{uuid4().hex}.db"
        backup_database(config, str(backup))
    run_migrations(conn)
