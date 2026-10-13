"""Persist rule alerts and fusion episodes. Legacy incident rows are not updated."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from uuid import uuid4

from backend.db import connect
from backend.fusion.engine import analyze
from backend.fusion.incidents import cluster_alerts, primary_product
from backend.fusion.rules import evaluate
from backend.fusion.score import fuse

logger = logging.getLogger("tracetrust")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _to_ms(value) -> int:
    if value is None:
        return _now_ms()
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).replace("Z", "")[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
            return int(parsed.timestamp() * 1000)
        except ValueError:
            continue
    return _now_ms()


def _row_alert(row) -> dict:
    return {
        "id": row["id"],
        "rule_code": row["rule_code"],
        "evidence_class": row["evidence_class"],
        "product_uid": row["product_uid"],
        "evidence_ids": json.loads(row["evidence_ids_json"]),
        "trust": row["trust"],
        "strength": row["strength"],
        "rule_version": row["rule_version"],
        "reason": row["reason"],
        "is_simulated": row["is_simulated"],
        "event_time_ms": row["event_time_ms"],
        "dedupe_key": row["dedupe_key"],
        "shipment_uid": row["shipment_uid"],
    }


def upsert_alerts(conn, alerts: list[dict]) -> list[dict]:
    stored = []
    stamp = _now()
    for alert in sorted(alerts, key=lambda item: item["dedupe_key"]):
        existing = conn.execute(
            "SELECT id FROM rule_alerts WHERE dedupe_key=?",
            (alert["dedupe_key"],),
        ).fetchone()
        if existing is None:
            conn.execute(
                """
                INSERT INTO rule_alerts (
                    rule_code, evidence_class, product_uid, evidence_ids_json, trust, strength,
                    rule_version, reason, is_simulated, event_time_ms, created_at, dedupe_key, shipment_uid
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    alert["rule_code"],
                    alert["evidence_class"],
                    alert["product_uid"],
                    json.dumps(alert["evidence_ids"]),
                    alert["trust"],
                    alert["strength"],
                    alert["rule_version"],
                    alert["reason"],
                    int(alert["is_simulated"]),
                    int(alert["event_time_ms"]),
                    stamp,
                    alert["dedupe_key"],
                    alert.get("shipment_uid"),
                ),
            )
            alert_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        else:
            alert_id = int(existing["id"])
        stored.append({**alert, "id": alert_id})
    return stored


def _load_alert_rows(conn, product_uids: set[str], shipment_uids: set[str]) -> list[dict]:
    rows: list[dict] = []
    seen: set[int] = set()
    if product_uids:
        marks = ",".join("?" for _ in product_uids)
        for row in conn.execute(
            f"SELECT * FROM rule_alerts WHERE product_uid IN ({marks})",
            tuple(sorted(product_uids)),
        ):
            if row["id"] not in seen:
                seen.add(row["id"])
                rows.append(_row_alert(row))
    if shipment_uids:
        marks = ",".join("?" for _ in shipment_uids)
        for row in conn.execute(
            f"SELECT * FROM rule_alerts WHERE shipment_uid IN ({marks})",
            tuple(sorted(shipment_uids)),
        ):
            if row["id"] not in seen:
                seen.add(row["id"])
                rows.append(_row_alert(row))
    return rows


def sync_incidents(conn, alerts: list[dict]) -> list[int]:
    if not alerts:
        return []
    product_uids = {alert["product_uid"] for alert in alerts if alert.get("product_uid")}
    shipment_uids = {alert["shipment_uid"] for alert in alerts if alert.get("shipment_uid")}
    grouped = cluster_alerts(_load_alert_rows(conn, product_uids, shipment_uids))
    incident_ids = []
    stamp = _now()
    for group in grouped:
        if not group:
            continue
        product_uid = primary_product(group)
        start = min(int(item["event_time_ms"]) for item in group)
        end = max(int(item["event_time_ms"]) for item in group)
        payload = json.dumps(
            fuse(group, missing_checks=[]),
            sort_keys=True,
            separators=(",", ":"),
        )
        wanted = {int(item["id"]) for item in group}
        row = conn.execute(
            """
            SELECT * FROM fusion_incidents
            WHERE product_uid=? AND window_start_ms<=? AND window_end_ms>=?
            ORDER BY id
            LIMIT 1
            """,
            (product_uid, end, start),
        ).fetchone()
        if row is None:
            conn.execute(
                """
                INSERT INTO fusion_incidents(product_uid, window_start_ms, window_end_ms, status, revision, created_at)
                VALUES (?,?,?,'OPEN',1,?)
                """,
                (product_uid, start, end, stamp),
            )
            incident_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
            conn.execute(
                """
                INSERT INTO fusion_incident_revisions(incident_id, revision, fusion_json, created_at)
                VALUES (?,?,?,?)
                """,
                (incident_id, 1, payload, stamp),
            )
            for alert_id in sorted(wanted):
                conn.execute(
                    "INSERT INTO fusion_incident_alerts(incident_id, alert_id) VALUES (?,?)",
                    (incident_id, alert_id),
                )
            incident_ids.append(incident_id)
            continue
        incident_id = int(row["id"])
        existing = {
            int(item["alert_id"])
            for item in conn.execute(
                "SELECT alert_id FROM fusion_incident_alerts WHERE incident_id=?",
                (incident_id,),
            )
        }
        if existing == wanted:
            incident_ids.append(incident_id)
            continue
        revision = int(row["revision"]) + 1
        conn.execute(
            """
            UPDATE fusion_incidents
            SET revision=?, window_start_ms=?, window_end_ms=?
            WHERE id=?
            """,
            (revision, min(start, int(row["window_start_ms"])), max(end, int(row["window_end_ms"])), incident_id),
        )
        conn.execute(
            """
            INSERT INTO fusion_incident_revisions(incident_id, revision, fusion_json, created_at)
            VALUES (?,?,?,?)
            """,
            (incident_id, revision, payload, stamp),
        )
        for alert_id in sorted(wanted - existing):
            conn.execute(
                "INSERT OR IGNORE INTO fusion_incident_alerts(incident_id, alert_id) VALUES (?,?)",
                (incident_id, alert_id),
            )
        incident_ids.append(incident_id)
    return incident_ids


def persist_alerts(conn, alerts: list[dict]) -> dict:
    stored = upsert_alerts(conn, alerts)
    sync_incidents(conn, stored)
    return fuse(stored)


def load_product_alerts(conn, product_uid: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM rule_alerts WHERE product_uid=? ORDER BY event_time_ms, dedupe_key",
        (product_uid,),
    ).fetchall()
    return [_row_alert(row) for row in rows]


def summary_for(product_uid: str, *, missing_checks: list[str] | None = None, db_path=None) -> dict:
    conn = connect(db_path)
    try:
        alerts = load_product_alerts(conn, product_uid)
    finally:
        conn.close()
    return fuse(alerts, missing_checks=missing_checks)


def _insert_public_scan(conn, product_uid: str, gps: dict | None, integrity: dict | None, actor=None) -> None:
    product = conn.execute(
        "SELECT product_id, is_simulated, qr_token FROM products WHERE product_uid=?",
        (product_uid,),
    ).fetchone()
    if product is None:
        return
    status = (integrity or {}).get("status")
    record_integrity = {"VERIFIED": "VALID", "FAILED": "INVALID", "UNVERIFIABLE": "UNVERIFIABLE"}.get(status, "PENDING")
    gps_status = (gps or {}).get("gps_status") or "NOT_REQUESTED"
    lat = lng = None
    accuracy_km = None
    if gps_status == "CAPTURED" and gps and gps.get("gps_lat_e7") is not None:
        lat = float(gps["gps_lat_e7"]) / 10_000_000
        lng = float(gps["gps_lng_e7"]) / 10_000_000
    if gps and gps.get("gps_accuracy_cm") is not None:
        accuracy_km = float(gps["gps_accuracy_cm"]) / 100_000
    payload = json.dumps(
        {"accuracy_km": accuracy_km, "gps_status": gps_status, "server_derived_trust": True},
        sort_keys=True,
    )
    stamp = _now().replace("Z", "").replace("T", " ")
    conn.execute(
        """
        INSERT INTO scan_history (
            observation_uid, occurred_at, received_at, source,
            identity_trust, location_trust, inspection_trust, is_simulated, rule_version,
            record_integrity, physical_checks_json, restriction_flags_json, data_origin,
            product_id, scanned_qr_token, scan_latitude, scan_longitude,
            scanner_user_id, scanner_organization_id,
            verification_method, verification_status, scanned_at, canonical_payload
        ) VALUES (?,?,?,?,0,0,0,?,?,?, '{}', '[]', 'LIVE', ?,?,?,?,?,?, 'QR','PENDING',?,?)
        """,
        (
            str(uuid4()),
            stamp,
            stamp,
            "STAFF" if actor is not None else "PUBLIC",
            int(product["is_simulated"] or 0),
            "rules-v1",
            record_integrity,
            product["product_id"],
            product_uid,
            lat,
            lng,
            actor.user_id if actor is not None else None,
            actor.organization_id if actor is not None else None,
            stamp,
            payload,
        ),
    )


def load_context(conn, product_uid: str) -> dict:
    product = conn.execute(
        """
        SELECT p.product_uid, p.lifecycle_state, c.custodian_organization_id
        FROM products p
        LEFT JOIN custody c ON c.product_id = p.product_id
        WHERE p.product_uid=?
        """,
        (product_uid,),
    ).fetchone()
    lifecycle = product["lifecycle_state"] if product else "IN_SUPPLY_CHAIN"
    custodian = product["custodian_organization_id"] if product else None
    recipient = conn.execute(
        """
        SELECT t.recipient_organization_id
        FROM transfers t
        JOIN transfer_items i ON i.transfer_id = t.transfer_id
        JOIN products p ON p.product_id = i.product_id
        WHERE p.product_uid=? AND t.transfer_status='INITIATED'
        ORDER BY t.transfer_id DESC
        LIMIT 1
        """,
        (product_uid,),
    ).fetchone()
    expected_recipient = recipient["recipient_organization_id"] if recipient else None
    scans = []
    for row in conn.execute(
        """
        SELECT s.*, d.status AS device_status
        FROM scan_history s
        LEFT JOIN devices d ON d.device_id = s.device_id
        WHERE s.product_id=(SELECT product_id FROM products WHERE product_uid=?)
        """,
        (product_uid,),
    ):
        payload = {}
        if row["canonical_payload"]:
            try:
                payload = json.loads(row["canonical_payload"])
            except json.JSONDecodeError:
                payload = {}
        gps_status = payload.get("gps_status")
        if gps_status is None and row["scan_latitude"] is not None:
            gps_status = "CAPTURED"
        signature_valid = payload.get("signature_valid")
        if row["source"] == "DEVICE":
            signature_valid = bool(row["digital_signature"]) if signature_valid is None else bool(signature_valid)
        device_id = row["device_id"]
        device_registered = row["device_status"] == "ACTIVE"
        if device_id is None and row["scanner_user_id"] is not None:
            device_id = f"user:{row['scanner_user_id']}"
            device_registered = True
        scans.append(
            {
                "evidence_id": row["observation_uid"],
                "product_uid": product_uid,
                "lat": row["scan_latitude"],
                "lng": row["scan_longitude"],
                "event_time_ms": _to_ms(row["received_at"] or row["scanned_at"]),
                "device_id": device_id,
                "device_registered": device_registered,
                "signature_valid": signature_valid,
                "authenticated": row["scanner_user_id"] is not None or row["source"] == "STAFF",
                "inspection_method": "STAFF" if row["source"] == "STAFF" else None,
                "gps_status": gps_status or "NOT_REQUESTED",
                "accuracy_km": payload.get("accuracy_km"),
                "is_simulated": bool(row["is_simulated"]),
                "scanner_org_id": row["scanner_organization_id"],
                "custodian_org_id": custodian,
                "expected_recipient_org_id": expected_recipient,
                "lifecycle_state": lifecycle,
            }
        )
    inspections = []
    transfers = []
    for row in conn.execute(
        """
        SELECT s.inspection_id, s.inspection_uid, s.observed_box_serial, s.observed_seal_id,
               s.observed_condition, s.laptop_serial_result, s.opening_authorized, s.inspection_mode,
               s.is_simulated, s.occurred_at, s.received_at, s.inspected_by_user_id,
               pkg.package_serial_number, pkg.seal_id, ti.item_outcome, t.transfer_uid
        FROM seal_inspections s
        JOIN packages pkg ON pkg.package_id = s.package_id
        JOIN products p ON p.product_id = pkg.product_id
        LEFT JOIN transfer_items ti ON ti.receipt_inspection_id = s.inspection_id
        LEFT JOIN transfers t ON t.transfer_id = ti.transfer_id
        WHERE p.product_uid=?
        """,
        (product_uid,),
    ):
        inspections.append(
            {
                "evidence_id": row["inspection_uid"] or f"inspection-{row['inspection_id']}",
                "product_uid": product_uid,
                "event_time_ms": _to_ms(row["occurred_at"] or row["received_at"]),
                "authenticated": row["inspected_by_user_id"] is not None,
                "inspection_method": row["inspection_mode"],
                "observed_box": row["observed_box_serial"],
                "expected_box": row["package_serial_number"],
                "observed_seal": row["observed_seal_id"],
                "expected_seal": row["seal_id"],
                "seal_condition": row["observed_condition"],
                "opening_authorized": bool(row["opening_authorized"]),
                "laptop_serial_result": row["laptop_serial_result"],
                "is_simulated": bool(row["is_simulated"]),
                "shipment_uid": row["transfer_uid"],
            }
        )
        if row["item_outcome"] in {"MISMATCH", "MISSING"}:
            transfers.append(
                {
                    "kind": "handover_mismatch",
                    "evidence_id": f"handover-{row['inspection_id']}",
                    "product_uid": product_uid,
                    "event_time_ms": _to_ms(row["occurred_at"] or row["received_at"]),
                    "authenticated": row["inspected_by_user_id"] is not None,
                    "inspection_method": row["inspection_mode"],
                    "is_simulated": bool(row["is_simulated"]),
                    "shipment_uid": row["transfer_uid"],
                }
            )
    records = _documentation_records(conn, product_uid)
    return {"scans": scans, "inspections": inspections, "transfers": transfers, "records": records}


def _documentation_records(conn, product_uid: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT t.transfer_uid, t.transfer_status, t.chain_status, t.sender_organization_id,
               t.recipient_organization_id, t.initiation_operation_uid, t.terminal_operation_uid,
               i.item_outcome, i.receipt_inspection_id, i.received_scanned,
               i.scanned_at, t.created_at
        FROM transfers t
        JOIN transfer_items i ON i.transfer_id = t.transfer_id
        JOIN products p ON p.product_id = i.product_id
        WHERE p.product_uid=?
        """,
        (product_uid,),
    ).fetchall()
    records = []
    for row in rows:
        receipted = bool(row["receipt_inspection_id"] or row["received_scanned"] or row["item_outcome"] in {"MATCHED", "MISMATCH"})
        confirmed = row["transfer_status"] == "ACCEPTED" and row["chain_status"] == "CONFIRMED"
        if not receipted or confirmed:
            continue
        when = _to_ms(row["scanned_at"] or row["created_at"])
        records.append(
            {
                "kind": "documentation_gap",
                "product_uid": product_uid,
                "org_id": row["recipient_organization_id"],
                "evidence_id": f"gap:{row['transfer_uid']}",
                "event_time_ms": when,
                "shipment_ref": row["transfer_uid"],
                "shipment_uid": row["transfer_uid"],
                "is_simulated": 0,
            }
        )
        op_uids = [uid for uid in (row["initiation_operation_uid"], row["terminal_operation_uid"]) if uid]
        interrupted = False
        if op_uids:
            marks = ",".join("?" for _ in op_uids)
            pending = conn.execute(
                f"SELECT operation_uid, status FROM operations WHERE operation_uid IN ({marks}) AND status IN ('PENDING','SUBMITTED')",
                tuple(op_uids),
            ).fetchone()
            submitted = conn.execute(
                f"SELECT submission_id FROM chain_submissions WHERE operation_uid IN ({marks}) LIMIT 1",
                tuple(op_uids),
            ).fetchone()
            interrupted = pending is not None or submitted is not None
        if interrupted:
            records.append(
                {
                    "kind": "interrupted_operation",
                    "product_uid": product_uid,
                    "evidence_id": f"op:{row['transfer_uid']}",
                    "event_time_ms": when,
                    "operation_status": "PENDING",
                    "is_simulated": 0,
                }
            )
    return records


def digital_from_integrity(product_uid: str, integrity: dict | None) -> list[dict]:
    status = (integrity or {}).get("status")
    layer = (integrity or {}).get("failing_layer")
    reasons = " ".join((integrity or {}).get("reasons") or []).lower()
    if status in {None, "UNVERIFIABLE", "VERIFIED"}:
        if status == "UNVERIFIABLE":
            return [
                {
                    "product_uid": product_uid,
                    "kind": "unverifiable",
                    "evidence_id": f"chain:{product_uid}",
                    "event_time_ms": 0,
                }
            ]
        return []
    if status != "FAILED":
        return []
    if layer == "anchor":
        confirmed = ("mismatch" in reasons or "does not match" in reasons) and "missing" not in reasons
        if "not confirmed" in reasons or "unverifiable" in reasons:
            confirmed = False
        if not confirmed:
            return [
                {
                    "product_uid": product_uid,
                    "kind": "unverifiable",
                    "evidence_id": f"chain:{product_uid}",
                    "event_time_ms": 0,
                }
            ]
        return [
            {
                "product_uid": product_uid,
                "kind": "anchor",
                "confirmed": True,
                "evidence_id": f"anchor:{product_uid}",
                "event_time_ms": 0,
            }
        ]
    kind = {"signature": "signature", "hash": "hash", "sequence": "sequence"}.get(layer or "")
    if kind is None:
        return []
    return [
        {
            "product_uid": product_uid,
            "kind": kind,
            "evidence_id": f"{kind}:{product_uid}",
            "event_time_ms": 0,
        }
    ]


def record_verification(product_uid: str, result: dict, observer_gps: dict | None, *, db_path=None, actor=None) -> dict:
    conn = connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        _insert_public_scan(conn, product_uid, observer_gps, result.get("record_integrity"), actor)
        context = load_context(conn, product_uid)
        context["digital"] = digital_from_integrity(product_uid, result.get("record_integrity"))
        evaluation = evaluate(**context)
        upsert_alerts(conn, evaluation.alerts)
        stored = load_product_alerts(conn, product_uid)
        sync_incidents(conn, stored)
        conn.commit()
        return fuse(
            stored,
            missing_checks=evaluation.missing_checks,
            authorized_opening=evaluation.authorized_opening,
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def refresh_product(product_uid: str, *, db_path=None) -> dict | None:
    conn = connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        context = load_context(conn, product_uid)
        evaluation = evaluate(**context)
        upsert_alerts(conn, evaluation.alerts)
        stored = load_product_alerts(conn, product_uid)
        sync_incidents(conn, stored)
        conn.commit()
        return fuse(stored, missing_checks=evaluation.missing_checks, authorized_opening=evaluation.authorized_opening)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def record_transfer_facts(facts: list[dict], *, db_path=None) -> None:
    if not facts:
        return
    evaluation = evaluate(transfers=facts)
    conn = connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        upsert_alerts(conn, evaluation.alerts)
        product_uids = {fact["product_uid"] for fact in facts}
        stored = []
        for product_uid in product_uids:
            stored.extend(load_product_alerts(conn, product_uid))
        sync_incidents(conn, stored)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def full_assessment(product_uid: str, *, db_path=None) -> dict | None:
    conn = connect(db_path)
    try:
        product = conn.execute("SELECT product_uid FROM products WHERE product_uid=?", (product_uid,)).fetchone()
        if product is None:
            return None
        alerts = load_product_alerts(conn, product_uid)
        incident = conn.execute(
            """
            SELECT id, product_uid, window_start_ms, window_end_ms, status, revision, created_at
            FROM fusion_incidents WHERE product_uid=?
            ORDER BY id DESC LIMIT 1
            """,
            (product_uid,),
        ).fetchone()
    finally:
        conn.close()
    body = fuse(alerts)
    body["product_uid"] = product_uid
    body["alerts"] = [
        {
            "id": alert["id"],
            "rule_code": alert["rule_code"],
            "evidence_class": alert["evidence_class"],
            "trust": alert["trust"],
            "strength": alert["strength"],
            "reason": alert["reason"],
            "is_simulated": bool(alert["is_simulated"]),
            "rule_version": alert["rule_version"],
            "event_time_ms": alert["event_time_ms"],
        }
        for alert in alerts
    ]
    body["incident"] = dict(incident) if incident else None
    return body


def list_incidents(*, db_path=None) -> list[dict]:
    conn = connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT i.id, i.product_uid, i.window_start_ms, i.window_end_ms, i.status, i.revision, i.created_at,
                   (
                     SELECT pkg.package_serial_number
                     FROM products p
                     JOIN packages pkg ON pkg.product_id = p.product_id AND pkg.status = 'ACTIVE'
                     WHERE p.product_uid = i.product_uid
                     LIMIT 1
                   ) AS box_serial
            FROM fusion_incidents i
            ORDER BY i.id DESC
            """
        ).fetchall()
        listed = []
        for row in rows:
            item = dict(row)
            alerts = conn.execute(
                """
                SELECT a.id, a.rule_code, a.reason, a.evidence_class
                FROM fusion_incident_alerts link
                JOIN rule_alerts a ON a.id = link.alert_id
                WHERE link.incident_id=?
                ORDER BY a.event_time_ms, a.id
                """,
                (row["id"],),
            ).fetchall()
            item["alerts"] = [dict(alert) for alert in alerts]
            listed.append(item)
        return listed
    finally:
        conn.close()


def get_incident(incident_id: int, *, db_path=None) -> dict | None:
    conn = connect(db_path)
    try:
        row = conn.execute("SELECT * FROM fusion_incidents WHERE id=?", (incident_id,)).fetchone()
        if row is None:
            return None
        revisions = conn.execute(
            """
            SELECT id, incident_id, revision, fusion_json, created_at
            FROM fusion_incident_revisions WHERE incident_id=? ORDER BY revision
            """,
            (incident_id,),
        ).fetchall()
        alerts = conn.execute(
            """
            SELECT a.*
            FROM fusion_incident_alerts link
            JOIN rule_alerts a ON a.id = link.alert_id
            WHERE link.incident_id=?
            ORDER BY a.event_time_ms, a.dedupe_key
            """,
            (incident_id,),
        ).fetchall()
    finally:
        conn.close()
    return {
        **dict(row),
        "revisions": [
            {
                "id": item["id"],
                "incident_id": item["incident_id"],
                "revision": item["revision"],
                "fusion": json.loads(item["fusion_json"]),
                "created_at": item["created_at"],
            }
            for item in revisions
        ],
        "alerts": [_row_alert(item) for item in alerts],
    }


def decide_incident(incident_id: int, decision: str, *, db_path=None) -> dict:
    status = {"ignore": "DISMISSED", "freeze": "UNDER_REVIEW"}.get(decision)
    if status is None:
        raise api_error(422, "INVALID_DECISION", "Choose ignore or freeze.")
    conn = connect(db_path)
    try:
        row = conn.execute("SELECT id, status FROM fusion_incidents WHERE id=?", (incident_id,)).fetchone()
        if row is None:
            raise api_error(404, "NOT_FOUND", "incident not found")
        if row["status"] not in {"OPEN", "UNDER_REVIEW", "DISMISSED"}:
            raise api_error(409, "DECISION_CLOSED", "This alert is already closed.")
        conn.execute("UPDATE fusion_incidents SET status=? WHERE id=?", (status, incident_id))
        conn.commit()
    finally:
        conn.close()
    body = get_incident(incident_id, db_path=db_path)
    if body is None:
        raise api_error(404, "NOT_FOUND", "incident not found")
    return body


def case_result(**kwargs) -> dict:
    _evaluation, result = analyze(**kwargs)
    return result
