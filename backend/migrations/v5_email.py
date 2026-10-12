"""Additive v5: users.email for login and suspicious-event mail."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DEMO_EMAILS = {
    "demo_manufacturer": "manufacturer@tracetrust.demo",
    "demo_distributor": "distributor@tracetrust.demo",
    "demo_retailer": "retailer@tracetrust.demo",
}


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}


def apply_v5(db_path: Path) -> bool:
    db_path = Path(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        version_row = conn.execute(
            "SELECT version FROM schema_migrations WHERE version=5"
        ).fetchone()
        cols = _columns(conn, "users")
        if version_row is not None and "email" in cols:
            _backfill(conn)
            conn.commit()
            return False
        conn.execute("BEGIN IMMEDIATE")
        if "email" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN email TEXT")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS users_email_unique ON users(email) WHERE email IS NOT NULL"
        )
        _backfill(conn)
        applied_at = (
            datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        )
        if version_row is None:
            conn.execute(
                """
                INSERT INTO schema_migrations(version, applied_at, source_sha256, migration_sha256, description)
                VALUES (5, ?, 'local', 'v5-email', 'users.email for login and alerts')
                """,
                (applied_at,),
            )
        conn.execute("INSERT OR REPLACE INTO app_metadata(key, value) VALUES('schema_version', '5')")
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _backfill(conn: sqlite3.Connection) -> None:
    for username, email in DEMO_EMAILS.items():
        conn.execute(
            "UPDATE users SET email=? WHERE username=? AND (email IS NULL OR email='')",
            (email, username),
        )
