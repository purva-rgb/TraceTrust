"""Additive v4: client-reported GPS columns. Missing GPS never blocks a handover."""
from __future__ import annotations

import hashlib
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

GPS_COLUMNS = frozenset(
    {
        "gps_lat_e7",
        "gps_lng_e7",
        "gps_accuracy_cm",
        "gps_status",
        "gps_source",
    }
)

MIGRATION_SQL = """
ALTER TABLE event_ledger ADD COLUMN gps_lat_e7 INTEGER;
ALTER TABLE event_ledger ADD COLUMN gps_lng_e7 INTEGER;
ALTER TABLE event_ledger ADD COLUMN gps_accuracy_cm INTEGER;
ALTER TABLE event_ledger ADD COLUMN gps_status TEXT NOT NULL DEFAULT 'NOT_REQUESTED'
  CHECK(gps_status IN ('CAPTURED','DENIED','UNAVAILABLE','NOT_REQUESTED'));
ALTER TABLE event_ledger ADD COLUMN gps_source TEXT NOT NULL DEFAULT 'CLIENT_REPORTED';
ALTER TABLE seal_inspections ADD COLUMN gps_lat_e7 INTEGER;
ALTER TABLE seal_inspections ADD COLUMN gps_lng_e7 INTEGER;
ALTER TABLE seal_inspections ADD COLUMN gps_accuracy_cm INTEGER;
ALTER TABLE seal_inspections ADD COLUMN gps_status TEXT NOT NULL DEFAULT 'NOT_REQUESTED'
  CHECK(gps_status IN ('CAPTURED','DENIED','UNAVAILABLE','NOT_REQUESTED'));
ALTER TABLE seal_inspections ADD COLUMN gps_source TEXT NOT NULL DEFAULT 'CLIENT_REPORTED';
""".strip()

DESCRIPTION = (
    "Additive client-reported GPS columns on event_ledger and seal_inspections; "
    "missing GPS never blocks a handover"
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}


def backup_database(db_path: Path) -> tuple[Path, str]:
    db_path = db_path.resolve()
    backups = db_path.parent / "backups"
    backups.mkdir(exist_ok=True)
    digest = sha256_file(db_path)
    backup_path = backups / "laptop_anti_counterfeit.v3.pre-v4.db"
    if not backup_path.exists():
        shutil.copy2(db_path, backup_path)
    (backups / "laptop_anti_counterfeit.v3.pre-v4.sha256").write_text(
        digest + "\n", encoding="utf-8"
    )
    return backup_path, digest


def apply_v4(db_path: Path, source_sha256: str | None = None) -> bool:
    """Return True if this call applied v4, False if already present."""
    db_path = Path(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        version_row = conn.execute(
            "SELECT version FROM schema_migrations WHERE version=4"
        ).fetchone()
        event_cols = _columns(conn, "event_ledger")
        seal_cols = _columns(conn, "seal_inspections")
        already = (
            version_row is not None
            and GPS_COLUMNS <= event_cols
            and GPS_COLUMNS <= seal_cols
        )
        if already:
            return False

        source = source_sha256 or sha256_file(db_path)
        conn.execute("BEGIN IMMEDIATE")
        event_cols = _columns(conn, "event_ledger")
        seal_cols = _columns(conn, "seal_inspections")
        statements = [s.strip() for s in MIGRATION_SQL.split(";") if s.strip()]
        for statement in statements:
            table = "event_ledger" if "event_ledger" in statement else "seal_inspections"
            col = statement.split("ADD COLUMN", 1)[1].strip().split()[0]
            existing = event_cols if table == "event_ledger" else seal_cols
            if col in existing:
                continue
            conn.execute(statement)
            existing.add(col)

        applied_at = (
            datetime.now(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        if version_row is None:
            conn.execute(
                """
                INSERT INTO schema_migrations(version, applied_at, source_sha256, migration_sha256, description)
                VALUES (4, ?, ?, ?, ?)
                """,
                (applied_at, source, sha256_text(MIGRATION_SQL), DESCRIPTION),
            )
        conn.execute(
            "INSERT OR REPLACE INTO app_metadata(key, value) VALUES('schema_version', '4')"
        )
        conn.commit()
        conn.execute("PRAGMA foreign_keys=ON")
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(f"foreign_key_check failed after v4: {violations}")
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"integrity_check failed after v4: {integrity}")
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def backup_and_migrate(db_path: Path) -> dict:
    backup_path, digest = backup_database(db_path)
    applied = apply_v4(db_path, source_sha256=digest)
    return {
        "backup_path": str(backup_path),
        "source_sha256": digest,
        "applied": applied,
    }


if __name__ == "__main__":
    from backend.config import get_settings

    result = backup_and_migrate(get_settings().database_path)
    print(result)
