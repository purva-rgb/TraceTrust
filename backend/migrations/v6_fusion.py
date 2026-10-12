"""Additive v6: rule_alerts and fusion incident revisions.

Already present and left unchanged: devices, scan_history (including legacy risk_score),
seal_inspections, transfers, verification_alerts, incidents, incident_alerts,
incident_revisions, investigator_decisions. Those incident tables are tied to
verification_alerts and human dispositions, so fusion episodes use fusion_incidents.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def _tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {row[0] for row in rows}


def apply_v6(db_path: Path) -> bool:
    db_path = Path(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        version_row = conn.execute("SELECT version FROM schema_migrations WHERE version=6").fetchone()
        present = _tables(conn)
        needed = {"rule_alerts", "fusion_incidents", "fusion_incident_alerts", "fusion_incident_revisions"}
        if version_row is not None and needed <= present:
            return False
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rule_alerts (
                id INTEGER PRIMARY KEY,
                rule_code TEXT NOT NULL,
                evidence_class TEXT NOT NULL,
                product_uid TEXT NOT NULL,
                evidence_ids_json TEXT NOT NULL,
                trust REAL NOT NULL,
                strength REAL NOT NULL,
                rule_version TEXT NOT NULL,
                reason TEXT NOT NULL,
                is_simulated INTEGER NOT NULL CHECK(is_simulated IN (0,1)),
                event_time_ms INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                dedupe_key TEXT NOT NULL UNIQUE,
                shipment_uid TEXT
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS rule_alerts_product_time ON rule_alerts(product_uid, event_time_ms)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fusion_incidents (
                id INTEGER PRIMARY KEY,
                product_uid TEXT NOT NULL,
                window_start_ms INTEGER NOT NULL,
                window_end_ms INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'OPEN'
                    CHECK(status IN ('OPEN','UNDER_REVIEW','CONFIRMED','DISMISSED','CLOSED')),
                revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>0),
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fusion_incident_alerts (
                incident_id INTEGER NOT NULL REFERENCES fusion_incidents(id),
                alert_id INTEGER NOT NULL REFERENCES rule_alerts(id),
                PRIMARY KEY (incident_id, alert_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fusion_incident_revisions (
                id INTEGER PRIMARY KEY,
                incident_id INTEGER NOT NULL REFERENCES fusion_incidents(id),
                revision INTEGER NOT NULL CHECK(revision>0),
                fusion_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (incident_id, revision)
            )
            """
        )
        applied_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        if version_row is None:
            conn.execute(
                """
                INSERT INTO schema_migrations(version, applied_at, source_sha256, migration_sha256, description)
                VALUES (6, ?, 'local', 'v6-fusion', 'rule_alerts and fusion incident revisions')
                """,
                (applied_at,),
            )
        conn.execute("INSERT OR REPLACE INTO app_metadata(key, value) VALUES('schema_version', '6')")
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
