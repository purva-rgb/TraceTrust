from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from backend.chain.adapter import ChainClient, ChainUnavailable, ProductOnChain
from backend.chain.ids import sha256_to_bytes32, uid_to_bytes32
from backend.crypto.canonical import CanonicalError, build_canonical_event, canonical_dumps, parse_canonical_json
from backend.crypto.events import ZERO_PREVIOUS_HASH
from backend.crypto.keys import verify_event_signature
from backend.db import connect
from backend.geo import location_check

HEADLINE_VERIFIED = "Digital record verified"
HEADLINE_FAILED = "Digital record failed"
HEADLINE_PENDING = "Digital record pending"
HEADLINE_UNKNOWN = "Unknown product"
HEADLINE_UNVERIFIABLE = "Digital record unverifiable"

LAYERS = ("hash", "signature", "sequence", "anchor", "custody")


@dataclass
class IntegrityResult:
    status: str
    failing_layer: str | None = None
    reasons: list[str] = field(default_factory=list)


def token_lookup_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()[:32]


def parse_qr_payload(payload: str) -> tuple[str | None, str | None]:
    text = payload.strip()
    if text.startswith("tt:v1:"):
        parts = text.split(":")
        if len(parts) >= 4:
            return parts[2], parts[3]
    return None, None


def mask_serial(serial: str | None) -> str | None:
    if not serial:
        return None
    if len(serial) <= 4:
        return "*" * len(serial)
    return ("*" * (len(serial) - 4)) + serial[-4:]


def _gps_from_event(row, payload: dict[str, Any]) -> dict[str, Any]:
    gps = payload.get("gps") if isinstance(payload.get("gps"), dict) else {}
    return {
        "gps_accuracy_cm": gps.get("gps_accuracy_cm", row["gps_accuracy_cm"]),
        "gps_lat_e7": gps.get("gps_lat_e7", row["gps_lat_e7"]),
        "gps_lng_e7": gps.get("gps_lng_e7", row["gps_lng_e7"]),
        "gps_source": gps.get("gps_source") or row["gps_source"] or "CLIENT_REPORTED",
        "gps_status": gps.get("gps_status") or row["gps_status"] or "NOT_REQUESTED",
    }


def _warehouse_latlng(conn, warehouse_id: int | None) -> tuple[float | None, float | None]:
    if warehouse_id is None:
        return None, None
    row = conn.execute(
        """
        SELECT l.latitude, l.longitude
        FROM warehouses w LEFT JOIN locations l ON l.location_id = w.location_id
        WHERE w.warehouse_id=?
        """,
        (warehouse_id,),
    ).fetchone()
    if row is None:
        return None, None
    return row["latitude"], row["longitude"]


def _observer_location_mismatch(conn, warehouse_id: int | None, observer_gps: dict[str, Any] | None) -> bool:
    """True only when verify-time GPS is more than 50 km from the current warehouse."""
    lat, lng = _warehouse_latlng(conn, warehouse_id)
    return location_check(observer_gps, lat, lng) == "OUTSIDE_RADIUS"


def _fail(layer: str, reason: str) -> IntegrityResult:
    return IntegrityResult(status="FAILED", failing_layer=layer, reasons=[reason])


def _verify_events(events: list[Any]) -> IntegrityResult | None:
    if not events:
        return None
    previous = ZERO_PREVIOUS_HASH
    for index, row in enumerate(events):
        if int(row["seq"]) != index:
            return _fail("sequence", f"sequence gap at seq {row['seq']}")
        if str(row["previous_hash"]) != previous:
            return _fail("sequence", f"previous_hash mismatch at seq {row['seq']}")
        try:
            parsed = parse_canonical_json(row["canonical_payload"])
            rebuilt = canonical_dumps(build_canonical_event(parsed))
        except (CanonicalError, json.JSONDecodeError, TypeError, ValueError) as exc:
            return _fail("hash", f"canonical rebuild failed at seq {row['seq']}: {exc}")
        digest = hashlib.sha256(rebuilt).hexdigest()
        if digest != row["event_hash"]:
            return _fail("hash", f"event_hash mismatch at seq {row['seq']}")
        payload = parsed.get("payload") if isinstance(parsed, dict) else {}
        gps = payload.get("gps") if isinstance(payload, dict) else None
        if isinstance(gps, dict):
            if gps.get("gps_lat_e7") != row["gps_lat_e7"] or gps.get("gps_lng_e7") != row["gps_lng_e7"]:
                return _fail("hash", f"GPS coordinate mismatch at seq {row['seq']}")
        key = row["eth_address"]
        if not key:
            return _fail("signature", f"unknown signer_key_id at seq {row['seq']}")
        if int(row["key_organization_id"] or -1) != int(row["organization_id"]):
            return _fail("signature", f"signer organization mismatch at seq {row['seq']}")
        if not verify_event_signature(row["event_hash"], row["digital_signature"], key):
            return _fail("signature", f"signature mismatch at seq {row['seq']}")
        previous = row["event_hash"]
    return None


def _verify_anchors(events: list[Any]) -> IntegrityResult | None:
    for row in events:
        if row["anchored_hash"] is None:
            return _fail("anchor", f"missing chain anchor at seq {row['seq']}")
        if row["anchored_hash"] != row["event_hash"]:
            return _fail("anchor", f"anchored_hash mismatch at seq {row['seq']}")
        if row["anchor_status"] not in {"CONFIRMED"}:
            if row["anchor_status"] == "UNVERIFIABLE":
                return IntegrityResult(status="UNVERIFIABLE", reasons=["anchor marked UNVERIFIABLE"])
            return _fail("anchor", f"anchor not confirmed at seq {row['seq']}")
    return None


def _verify_chain(
    events: list[Any],
    onchain: ProductOnChain | None,
    custodian_address: str | None,
) -> IntegrityResult | None:
    if onchain is None:
        return IntegrityResult(status="UNVERIFIABLE", reasons=["chain product lookup failed"])
    if not events:
        if onchain.exists:
            return _fail("sequence", "chain has a product head but the local event tail is missing")
        return IntegrityResult(status="UNVERIFIABLE", reasons=["no signed events"])
    if not onchain.exists:
        return _fail("sequence", "local events exist but the contract has no product")
    if int(onchain.seq) + 1 != len(events):
        return _fail("sequence", "event count does not match contract sequence")
    terminal = events[-1]["event_hash"]
    try:
        head = sha256_to_bytes32(terminal)
    except ValueError:
        return _fail("hash", "terminal event_hash is not 32 bytes")
    if head != onchain.event_head:
        return _fail("anchor", "terminal event head does not match the contract")
    if custodian_address and onchain.custodian.lower() != custodian_address.lower():
        return _fail("custody", "database custodian does not match the contract")
    return None


def verify_product(
    product_uid: str,
    chain: ChainClient | None,
    *,
    db_path=None,
    observer_gps: dict[str, Any] | None = None,
) -> dict[str, Any]:
    conn = connect(db_path)
    try:
        product = conn.execute(
            """
            SELECT p.*, c.custodian_organization_id, c.verification_state AS custody_state,
                   c.warehouse_id AS custody_warehouse_id,
                   o.current_key_id, k.eth_address AS custodian_address
            FROM products p
            LEFT JOIN custody c ON c.product_id = p.product_id
            LEFT JOIN organizations o ON o.organization_id = c.custodian_organization_id
            LEFT JOIN signing_keys k ON k.key_id = o.current_key_id
            WHERE p.product_uid=?
            """,
            (product_uid,),
        ).fetchone()
        if product is None:
            return unknown_result()
        events = conn.execute(
            """
            SELECT e.*, a.anchored_hash, a.chain_status AS anchor_status,
                   k.eth_address, k.organization_id AS key_organization_id
            FROM event_ledger e
            LEFT JOIN event_anchors a ON a.event_id = e.event_id
            LEFT JOIN signing_keys k ON k.key_id = e.signer_key_id
            WHERE e.product_uid=?
            ORDER BY e.seq
            """,
            (product_uid,),
        ).fetchall()
        inspections = conn.execute(
            """
            SELECT s.inspection_mode, s.observed_box_serial, s.observed_seal_id, s.observed_condition,
                   s.laptop_serial_result, pkg.package_serial_number, pkg.seal_id
            FROM packages pkg
            LEFT JOIN seal_inspections s ON s.package_id = pkg.package_id
            WHERE pkg.product_id=?
            ORDER BY s.inspection_id
            """,
            (product["product_id"],),
        ).fetchall()
        deployment = conn.execute(
            """
            SELECT status FROM chain_deployments
            ORDER BY CASE status WHEN 'ACTIVE' THEN 0 WHEN 'RESET' THEN 1 ELSE 2 END, created_at DESC
            LIMIT 1
            """
        ).fetchone()
        deployment_status = deployment["status"] if deployment is not None else None
        location_mismatch = _observer_location_mismatch(
            conn, product["custody_warehouse_id"], observer_gps
        )
    finally:
        conn.close()

    physical = _physical_checks(inspections)
    flags = {
        "authenticity_verdict": product["authenticity_verdict"],
        "hold_active": bool(product["hold_active"]),
        "identity_revoked": bool(product["identity_revoked"]),
        "location_mismatch": location_mismatch,
        "recall_active": bool(product["recall_active"]),
        "stolen_active": bool(product["stolen_active"]),
    }
    provenance_events = [_event_point(row) for row in events]

    if product["registration_state"] != "CONFIRMED" or product["data_origin"] != "LIVE":
        integrity = IntegrityResult(status="UNVERIFIABLE", reasons=["registration is not a confirmed live record"])
        return _pack(product, integrity, physical, flags, provenance_events, full=True)

    if deployment_status == "RESET":
        integrity = IntegrityResult(status="UNVERIFIABLE", reasons=["chain deployment was reset"])
        return _pack(product, integrity, physical, flags, provenance_events, full=True)

    integrity = _verify_events(events)
    if integrity is None:
        integrity = _verify_anchors(events)
    if integrity is None:
        onchain = None
        try:
            if chain is None:
                raise ChainUnavailable("no chain client")
            if chain.get_code(chain.contract_address) == b"":
                raise ChainUnavailable("contract code missing")
            onchain = chain.get_product(uid_to_bytes32(product_uid))
        except ChainUnavailable as exc:
            integrity = IntegrityResult(status="UNVERIFIABLE", reasons=[str(exc)])
        else:
            integrity = _verify_chain(events, onchain, product["custodian_address"])
    if integrity is None:
        integrity = IntegrityResult(status="VERIFIED")
    return _pack(product, integrity, physical, flags, provenance_events, full=True)


def _event_point(row) -> dict[str, Any]:
    try:
        parsed = json.loads(row["canonical_payload"])
    except json.JSONDecodeError:
        parsed = {}
    payload = parsed.get("payload") if isinstance(parsed, dict) else {}
    gps = _gps_from_event(row, payload if isinstance(payload, dict) else {})
    return {
        "actor_user_id": row["actor_user_id"],
        "digital_signature": row["digital_signature"],
        "event_hash": row["event_hash"],
        "event_type": row["event_type"],
        "event_uid": row["event_uid"],
        "gps": gps,
        "gps_status": gps["gps_status"],
        "occurred_at": row["occurred_at"],
        "operation_uid": row["operation_uid"],
        "previous_hash": row["previous_hash"],
        "seq": row["seq"],
        "signer_key_id": row["signer_key_id"],
    }


def _physical_checks(rows: list[Any]) -> dict[str, str]:
    checks = {
        "box_id": "NOT_CHECKED",
        "box_serial": None,
        "laptop_serial": "NOT_CHECKED",
        "seal_condition": "NOT_CHECKED",
        "seal_id": "NOT_CHECKED",
        "seal_serial": None,
    }
    inspected = False
    for row in rows:
        if row["package_serial_number"]:
            checks["box_serial"] = row["package_serial_number"]
        if row["seal_id"]:
            checks["seal_serial"] = row["seal_id"]
        if row["inspection_mode"] is None:
            continue
        inspected = True
        expected_box = row["package_serial_number"]
        expected_seal = row["seal_id"]
        if row["observed_box_serial"] is not None:
            checks["box_id"] = "MATCH" if row["observed_box_serial"] == expected_box else "MISMATCH"
        if row["observed_seal_id"] is not None:
            checks["seal_id"] = "MATCH" if row["observed_seal_id"] == expected_seal else "MISMATCH"
        if row["observed_condition"] in {"INTACT", "BROKEN", "MISSING", "UNKNOWN"}:
            checks["seal_condition"] = row["observed_condition"]
        if row["laptop_serial_result"] in {"MATCH", "MISMATCH", "NOT_CHECKED", "UNAVAILABLE"}:
            checks["laptop_serial"] = row["laptop_serial_result"]
    if not inspected:
        if checks["box_serial"]:
            checks["box_id"] = "MATCH"
        if checks["seal_serial"]:
            checks["seal_id"] = "MATCH"
        if checks["box_serial"] or checks["seal_serial"]:
            checks["seal_condition"] = "INTACT"
    return checks


def _final_status(integrity: IntegrityResult, flags: dict[str, Any], product: Any) -> str:
    if integrity.status == "FAILED":
        return "INVALID"
    if integrity.status == "UNVERIFIABLE":
        return "PENDING"
    restricted = (
        flags["hold_active"]
        or flags["recall_active"]
        or flags["stolen_active"]
        or flags["identity_revoked"]
        or flags["authenticity_verdict"] == "COUNTERFEIT"
        or flags.get("location_mismatch")
    )
    if restricted:
        return "SUSPICIOUS"
    if product["registration_state"] != "CONFIRMED":
        return "PENDING"
    return "VALID"


def _headline(final_status: str, integrity: IntegrityResult) -> str:
    if final_status == "UNKNOWN":
        return HEADLINE_UNKNOWN
    if integrity.status == "VERIFIED" and final_status in {"VALID", "SUSPICIOUS"}:
        return HEADLINE_VERIFIED
    if integrity.status == "FAILED":
        return HEADLINE_FAILED
    if integrity.status == "UNVERIFIABLE":
        return HEADLINE_UNVERIFIABLE
    return HEADLINE_PENDING


def unknown_result() -> dict[str, Any]:
    integrity = IntegrityResult(status="UNVERIFIABLE", reasons=["unknown token"])
    physical = {
        "box_id": "NOT_CHECKED",
        "box_serial": None,
        "laptop_serial": "NOT_CHECKED",
        "seal_condition": "NOT_CHECKED",
        "seal_id": "NOT_CHECKED",
        "seal_serial": None,
    }
    flags = {
        "authenticity_verdict": "UNDETERMINED",
        "hold_active": False,
        "location_mismatch": False,
        "identity_revoked": False,
        "recall_active": False,
        "stolen_active": False,
    }
    return {
        "brand": None,
        "events": [],
        "final_status": "UNKNOWN",
        "headline": HEADLINE_UNKNOWN,
        "model_name": None,
        "physical_checks": physical,
        "product_uid": None,
        "record_integrity": {"failing_layer": None, "reasons": integrity.reasons, "status": "UNVERIFIABLE"},
        "restriction_flags": flags,
        "serial_number": None,
        "serial_number_masked": None,
    }


def _pack(product, integrity: IntegrityResult, physical, flags, events, *, full: bool) -> dict[str, Any]:
    final_status = _final_status(integrity, flags, product)
    body = {
        "brand": product["brand"],
        "events": events,
        "final_status": final_status,
        "headline": _headline(final_status, integrity),
        "model_name": product["model_name"],
        "physical_checks": physical,
        "product_uid": product["product_uid"],
        "record_integrity": {
            "failing_layer": integrity.failing_layer,
            "reasons": integrity.reasons,
            "status": integrity.status,
        },
        "restriction_flags": flags,
        "serial_number": product["serial_number"],
        "serial_number_masked": mask_serial(product["serial_number"]),
    }
    return body


def reduce_public(result: dict[str, Any]) -> dict[str, Any]:
    events = [
        {
            "event_type": event["event_type"],
            "gps": {
                "gps_lat_e7": event["gps"]["gps_lat_e7"],
                "gps_lng_e7": event["gps"]["gps_lng_e7"],
                "gps_status": event["gps"]["gps_status"],
                "gps_source": event["gps"]["gps_source"],
            },
            "gps_status": event["gps_status"],
            "seq": event["seq"],
        }
        for event in result.get("events") or []
    ]
    return {
        "brand": result.get("brand"),
        "events": events,
        "final_status": result["final_status"],
        "headline": result["headline"],
        "model_name": result.get("model_name"),
        "physical_checks": result["physical_checks"],
        "product_uid": result.get("product_uid"),
        "record_integrity": result["record_integrity"],
        "restriction_flags": result["restriction_flags"],
        "serial_number_masked": result.get("serial_number_masked"),
        "mail_alert": result.get("mail_alert"),
        "assessment": result.get("assessment"),
    }
