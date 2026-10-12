from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import time
from typing import Any
from uuid import uuid4

from eth_account import Account

from backend.auth.deps import CurrentUser
from backend.chain.adapter import ChainClient
from backend.chain.ids import sha256_to_bytes32, uid_to_bytes32
from backend.chain.pipeline import (
    OperationSpec,
    execute_operation,
    insert_operation_row,
)
from backend.crypto.canonical import canonical_dumps
from backend.crypto.events import EVENT_INSERT_COLUMNS, ZERO_PREVIOUS_HASH, build_signed_event_row
from backend.crypto.keys import KeyError_, load_org_private_key
from backend.db import connect, get_connection
from backend.errors import api_error
from backend.products.gps import gps_to_canonical
from backend.products.labels_file import write_demo_labels
from backend.products.schemas import (
    BatchOut,
    InventoryItem,
    LabelOut,
    OperationAccepted,
    OperationOut,
    ProductCreate,
    QrLabelOut,
    WarehouseOut,
)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _idempotency_scope(org_id: int) -> str:
    return f"REGISTER_PRODUCT:{org_id}"


def _jsonable_event(event: dict[str, Any]) -> dict[str, Any]:
    return {name: event[name] for name in EVENT_INSERT_COLUMNS}


def list_batches(actor: CurrentUser) -> list[BatchOut]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT batch_id, batch_number, brand, model_name, batch_status, manufacturer_id
            FROM batches
            WHERE manufacturer_id=? AND batch_status='ACTIVE'
            ORDER BY batch_id
            """,
            (actor.organization_id,),
        ).fetchall()
    return [BatchOut(**dict(row)) for row in rows]


def list_warehouses(actor: CurrentUser) -> list[WarehouseOut]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT warehouse_id, warehouse_code, warehouse_name, organization_id, status
            FROM warehouses
            WHERE organization_id=? AND status='ACTIVE'
            ORDER BY warehouse_id
            """,
            (actor.organization_id,),
        ).fetchall()
    return [WarehouseOut(**dict(row)) for row in rows]


def list_labels(actor: CurrentUser) -> list[LabelOut]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT p.product_uid, p.serial_number, p.manufacturer_id,
                   p.current_owner_organization_id, i.warehouse_id,
                   pkg.package_serial_number AS box_serial, pkg.seal_id,
                   op.canonical_intent, org.organization_type AS custodian
            FROM products p
            JOIN packages pkg ON pkg.product_id = p.product_id AND pkg.status='ACTIVE'
            LEFT JOIN operational_inventory i ON i.product_id = p.product_id
            LEFT JOIN operations op ON op.operation_uid = p.registration_operation_uid
            LEFT JOIN organizations org ON org.organization_id = p.current_owner_organization_id
            WHERE p.data_origin='LIVE' AND p.registration_state='CONFIRMED'
              AND (p.manufacturer_id=? OR p.current_owner_organization_id=?)
            ORDER BY p.product_id
            """,
            (actor.organization_id, actor.organization_id),
        ).fetchall()
    labels = []
    for row in rows:
        intent = {}
        try:
            intent = json.loads(row["canonical_intent"] or "{}")
        except json.JSONDecodeError:
            intent = {}
        labels.append(
            LabelOut(
                product_uid=row["product_uid"],
                qr_payload=intent.get("qr_payload"),
                serial_number=row["serial_number"],
                box_serial=row["box_serial"],
                seal_id=row["seal_id"],
                custodian=row["custodian"],
                warehouse_id=row["warehouse_id"],
            )
        )
    return labels


def list_inventory(actor: CurrentUser) -> list[InventoryItem]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT product_id, product_uid, product_code, serial_number,
                   custodian_organization_id, warehouse_id
            FROM operational_inventory
            WHERE custodian_organization_id=?
            ORDER BY product_id
            """,
            (actor.organization_id,),
        ).fetchall()
    return [InventoryItem(**dict(row)) for row in rows]


def get_operation(actor: CurrentUser, operation_uid: str) -> OperationOut:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM operations WHERE operation_uid=?",
            (operation_uid,),
        ).fetchone()
    if row is None or row["organization_id"] != actor.organization_id:
        raise api_error(404, "NOT_FOUND", "operation not found")
    intent = {}
    try:
        intent = json.loads(row["canonical_intent"] or "{}")
    except Exception:
        intent = {}
    return OperationOut(
        operation_uid=row["operation_uid"],
        operation_type=row["operation_type"],
        status=row["status"],
        chain_status=row["status"],
        error_code=row["error_code"],
        error_detail=row["error_detail"],
        created_at=row["created_at"],
        confirmed_at=row["confirmed_at"],
        product_uid=intent.get("product_uid"),
    )


def get_qr_label(actor: CurrentUser, product_uid: str) -> QrLabelOut:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT p.product_uid, p.serial_number, p.manufacturer_id,
                   p.registration_state, p.current_owner_organization_id,
                   p.registration_operation_uid,
                   pkg.package_serial_number, pkg.seal_id,
                   o.canonical_intent
            FROM products p
            JOIN packages pkg ON pkg.product_id = p.product_id AND pkg.status='ACTIVE'
            LEFT JOIN operations o ON o.operation_uid = p.registration_operation_uid
            WHERE p.product_uid=?
            """,
            (product_uid,),
        ).fetchone()
    if row is None:
        raise api_error(404, "NOT_FOUND", "product not found")
    allowed = {row["manufacturer_id"], row["current_owner_organization_id"]}
    if actor.organization_id not in allowed:
        raise api_error(404, "NOT_FOUND", "product not found")
    if row["registration_state"] != "CONFIRMED":
        raise api_error(409, "NOT_CONFIRMED", "QR labels are issued only after confirmation")
    intent = json.loads(row["canonical_intent"] or "{}") if row["canonical_intent"] else {}
    payload = intent.get("qr_payload")
    if not payload:
        raise api_error(409, "QR_UNAVAILABLE", "QR payload was returned at registration")
    return QrLabelOut(
        product_uid=row["product_uid"],
        qr_payload=payload,
        serial_number=row["serial_number"],
        box_serial=row["package_serial_number"],
        seal_id=row["seal_id"],
    )


def _qr_payload(product_uid: str, token_hex: str) -> str:
    return f"tt:v1:{product_uid}:{token_hex}"


def _binding_digest(product_uid: str, package_uid: str, box_serial: str, seal_id: str) -> str:
    blob = canonical_dumps(
        {
            "binding_version": 1,
            "box_serial": box_serial,
            "package_uid": package_uid,
            "product_uid": product_uid,
            "seal_id": seal_id,
        }
    )
    return _sha256_hex(blob)


def _load_deployment(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT deployment_id, contract_address, status
        FROM chain_deployments
        WHERE status='ACTIVE'
        ORDER BY created_at DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        raise api_error(503, "CHAIN_UNAVAILABLE", "no ACTIVE chain deployment")
    return dict(row)


def _accepted(row_or_spec, chain_status: str, *, product_uid: str | None, package_uid: str | None, qr_payload: str | None) -> OperationAccepted:
    uid = row_or_spec if isinstance(row_or_spec, str) else row_or_spec.operation_uid
    return OperationAccepted(
        operation_uid=uid,
        chain_status=chain_status,
        status_url=f"/operations/{uid}",
        product_uid=product_uid,
        package_uid=package_uid,
        qr_payload=qr_payload,
    )


def register_product(
    actor: CurrentUser,
    body: ProductCreate,
    idempotency_key: str,
    chain: ChainClient,
) -> OperationAccepted:
    gps = gps_to_canonical(body.gps)
    intent = {
        "batch_id": body.batch_id,
        "box_serial": body.box_serial,
        "gps": gps,
        "seal_id": body.seal_id,
        "serial_number": body.serial_number,
        "warehouse_id": body.warehouse_id,
    }
    request_hash = _sha256_hex(canonical_dumps(intent))
    scope = _idempotency_scope(actor.organization_id)

    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            """
            SELECT operation_uid, request_hash, status, canonical_intent
            FROM operations
            WHERE idempotency_scope=? AND idempotency_key=?
            """,
            (scope, idempotency_key),
        ).fetchone()
        if existing is not None:
            conn.rollback()
            if existing["request_hash"] != request_hash:
                raise api_error(409, "IDEMPOTENCY_CONFLICT", "Idempotency-Key reused with a different body")
            stored = json.loads(existing["canonical_intent"] or "{}")
            return _accepted(
                existing["operation_uid"],
                existing["status"],
                product_uid=stored.get("product_uid"),
                package_uid=stored.get("package_uid"),
                qr_payload=None,
            )

        batch = conn.execute(
            """
            SELECT batch_id, manufacturer_id, brand, model_name, batch_status
            FROM batches WHERE batch_id=?
            """,
            (body.batch_id,),
        ).fetchone()
        if batch is None or batch["manufacturer_id"] != actor.organization_id:
            conn.rollback()
            raise api_error(404, "NOT_FOUND", "batch not found")
        if batch["batch_status"] != "ACTIVE":
            conn.rollback()
            raise api_error(422, "BATCH_INACTIVE", "batch is not ACTIVE")

        warehouse = conn.execute(
            """
            SELECT warehouse_id, organization_id, status
            FROM warehouses WHERE warehouse_id=?
            """,
            (body.warehouse_id,),
        ).fetchone()
        if warehouse is None or warehouse["organization_id"] != actor.organization_id:
            conn.rollback()
            raise api_error(404, "NOT_FOUND", "warehouse not found")
        if warehouse["status"] != "ACTIVE":
            conn.rollback()
            raise api_error(422, "WAREHOUSE_INACTIVE", "warehouse is not ACTIVE")

        org = conn.execute(
            """
            SELECT current_key_id, provisioning_state, organization_uid
            FROM organizations WHERE organization_id=?
            """,
            (actor.organization_id,),
        ).fetchone()
        if org is None or org["current_key_id"] is None or org["provisioning_state"] != "CONFIRMED":
            conn.rollback()
            raise api_error(503, "ORG_UNPROVISIONED", "organization is not chain-provisioned")

        deployment = _load_deployment(conn)
        duplicate = conn.execute(
            "SELECT 1 FROM products WHERE serial_number=?",
            (body.serial_number,),
        ).fetchone()
        if duplicate is not None:
            conn.rollback()
            raise api_error(409, "DUPLICATE_SERIAL", "serial already registered")

        product_uid = str(uuid4())
        package_uid = str(uuid4())
        operation_uid = str(uuid4())
        qr_payload_token = secrets.token_hex(16)
        qr_stored = hashlib.sha256(qr_payload_token.encode("ascii")).hexdigest()[:32]
        product_code = f"LAP-{product_uid.replace('-', '')[:12].upper()}"
        binding = _binding_digest(product_uid, package_uid, body.box_serial, body.seal_id)
        try:
            private_key = load_org_private_key(actor.organization_type, actor.organization_id)
        except KeyError_ as exc:
            conn.rollback()
            raise api_error(503, "ORG_UNPROVISIONED", "organization signing key is not configured") from exc

        try:
            conn.execute(
                """
                INSERT INTO products(
                    product_uid, lifecycle_state, registration_state, is_simulated, data_origin,
                    product_code, serial_number, qr_token, batch_id, brand, model_name,
                    product_category, manufacturer_id, product_status
                ) VALUES (?, 'REGISTERED', 'PENDING', 0, 'LIVE', ?, ?, ?, ?, ?, ?, 'LAPTOP', ?, 'ACTIVE')
                """,
                (
                    product_uid,
                    product_code,
                    body.serial_number,
                    qr_stored,
                    body.batch_id,
                    batch["brand"],
                    batch["model_name"],
                    actor.organization_id,
                ),
            )
            product_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
            conn.execute(
                """
                INSERT INTO packages(
                    package_uid, binding_version, binding_digest, data_origin,
                    product_id, package_serial_number, seal_id, seal_type, status, applied_by_user_id
                ) VALUES (?, 1, ?, 'LIVE', ?, ?, ?, 'TAMPER_EVIDENT', 'ACTIVE', ?)
                """,
                (package_uid, binding, product_id, body.box_serial, body.seal_id, actor.user_id),
            )
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            text = str(exc)
            if "serial_number" in text:
                raise api_error(409, "DUPLICATE_SERIAL", "serial already registered") from exc
            if "package_serial_number" in text:
                raise api_error(409, "DUPLICATE_BOX", "box serial already registered") from exc
            if "seal_id" in text:
                raise api_error(409, "DUPLICATE_SEAL", "seal already registered") from exc
            raise api_error(409, "CONFLICT", "duplicate product identity") from exc

        event = build_signed_event_row(
            conn,
            product_id=product_id,
            product_uid=product_uid,
            organization_id=actor.organization_id,
            organization_uid=org["organization_uid"],
            organization_type=actor.organization_type,
            signer_key_id=org["current_key_id"],
            operation_uid=operation_uid,
            event_type="PRODUCT_REGISTERED",
            actor_user_id=actor.user_id,
            payload={
                "batch_id": body.batch_id,
                "box_serial": body.box_serial,
                "gps": gps,
                "package_uid": package_uid,
                "seal_id": body.seal_id,
                "serial_number": body.serial_number,
                "warehouse_id": body.warehouse_id,
            },
            occurred_at_ms=_now_ms(),
            private_key=private_key,
        )
        sender_address = Account.from_key(private_key).address
        chain_args = [
            uid_to_bytes32(product_uid),
            sha256_to_bytes32(event["event_hash"]),
            uid_to_bytes32(operation_uid),
        ]
        qr_payload = _qr_payload(product_uid, qr_payload_token)
        canonical_intent = {
            **intent,
            "operation_uid": operation_uid,
            "package_uid": package_uid,
            "product_uid": product_uid,
            "qr_payload": qr_payload,
        }
        spec = OperationSpec(
            operation_uid=operation_uid,
            operation_type="REGISTER_PRODUCT",
            actor_user_id=actor.user_id,
            organization_id=actor.organization_id,
            idempotency_scope=scope,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            canonical_intent=canonical_intent,
            signed_payload={
                "chain_args": ["0x" + item.hex() for item in chain_args],
                "chain_function": "registerProduct",
                "events": [_jsonable_event(event)],
                "projection": {
                    "product_id": product_id,
                    "type": "REGISTER_PRODUCT",
                    "warehouse_id": body.warehouse_id,
                },
                "sender_address": sender_address,
            },
            expected_heads={product_uid: ZERO_PREVIOUS_HASH},
            deployment_id=deployment["deployment_id"],
            chain_function="registerProduct",
            chain_args=chain_args,
            sender_private_key=private_key,
            sender_address=sender_address,
        )
        try:
            insert_operation_row(conn, spec)
            conn.execute(
                "UPDATE products SET registration_operation_uid=? WHERE product_id=?",
                (operation_uid, product_id),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            text = str(exc)
            if "idempotency" in text:
                raise api_error(409, "IDEMPOTENCY_CONFLICT", "Idempotency-Key reused with a different body") from exc
            raise api_error(409, "CONFLICT", "could not persist registration") from exc
    finally:
        conn.close()

    chain_status = execute_operation(spec, chain, persist=False)
    if chain_status == "CONFIRMED":
        try:
            write_demo_labels()
        except Exception:
            pass
    return _accepted(
        spec,
        chain_status,
        product_uid=product_uid,
        package_uid=package_uid,
        qr_payload=qr_payload,
    )
