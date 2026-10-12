from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from backend.chain.adapter import ChainClient, ReceiptInfo, SignedTx
from backend.crypto.events import insert_event_row
from backend.db import connect


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


SAFE_RELEASE_ON_REVERT = frozenset({"INITIATE_TRANSFER", "REGISTER_PRODUCT"})


@dataclass
class OperationSpec:
    operation_uid: str
    operation_type: str
    actor_user_id: int | None
    organization_id: int
    idempotency_scope: str
    idempotency_key: str
    request_hash: str
    canonical_intent: dict[str, Any]
    signed_payload: dict[str, Any]
    expected_heads: dict[str, Any]
    deployment_id: str
    chain_function: str
    chain_args: list[Any]
    sender_private_key: str
    sender_address: str
    reservations: list[dict[str, Any]] = field(default_factory=list)
    staging_sql: list[tuple[str, tuple]] = field(default_factory=list)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=_json_default)


def _json_default(value: Any) -> str:
    if isinstance(value, (bytes, bytearray)):
        return "0x" + bytes(value).hex()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def insert_operation_row(conn: sqlite3.Connection, spec: OperationSpec, stamp: str | None = None) -> None:
    stamp = stamp or _now()
    conn.execute(
        """
        INSERT INTO operations(
            operation_uid, operation_type, actor_user_id, organization_id,
            idempotency_scope, idempotency_key, request_hash, canonical_intent,
            signed_payload_json, expected_heads_json, deployment_id, status,
            created_at, updated_at, attempt_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, 0)
        """,
        (
            spec.operation_uid,
            spec.operation_type,
            spec.actor_user_id,
            spec.organization_id,
            spec.idempotency_scope,
            spec.idempotency_key,
            spec.request_hash,
            _json_dumps(spec.canonical_intent),
            _json_dumps(spec.signed_payload),
            _json_dumps(spec.expected_heads),
            spec.deployment_id,
            stamp,
            stamp,
        ),
    )


def persist_pending(conn: sqlite3.Connection, spec: OperationSpec) -> None:
    conn.execute("BEGIN IMMEDIATE")
    stamp = _now()
    try:
        insert_operation_row(conn, spec, stamp)
        for sql, params in spec.staging_sql:
            conn.execute(sql, params)
        for reservation in spec.reservations:
            conn.execute(
                """
                INSERT INTO product_reservations(product_id, transfer_id, operation_uid, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    reservation["product_id"],
                    reservation.get("transfer_id"),
                    spec.operation_uid,
                    stamp,
                    reservation["expires_at"],
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def persist_submission(
    conn: sqlite3.Connection, spec: OperationSpec, signed: SignedTx, attempt_no: int = 1
) -> None:
    conn.execute("BEGIN IMMEDIATE")
    stamp = _now()
    try:
        conn.execute(
            """
            INSERT INTO chain_submissions(
                operation_uid, attempt_no, deployment_id, sender_address, account_nonce,
                raw_signed_transaction, tx_hash, status, confirmations, created_at, broadcast_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'BROADCAST', 0, ?, ?)
            """,
            (
                spec.operation_uid,
                attempt_no,
                spec.deployment_id,
                signed.sender_address,
                signed.account_nonce,
                signed.raw_signed_transaction,
                signed.tx_hash,
                stamp,
                stamp,
            ),
        )
        conn.execute(
            "UPDATE operations SET status='SUBMITTED', updated_at=?, attempt_count=attempt_count+1 WHERE operation_uid=?",
            (stamp, spec.operation_uid),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


class ChainUnverifiable(Exception):
    pass


def mark_failed(conn: sqlite3.Connection, spec: OperationSpec, receipt: ReceiptInfo | None, detail: str) -> None:
    conn.execute("BEGIN IMMEDIATE")
    stamp = _now()
    if receipt is not None:
        conn.execute(
            """
            UPDATE chain_submissions
            SET status='REVERTED', receipt_status=0, block_number=?, block_hash=?,
                receipt_json=?, confirmations=1
            WHERE operation_uid=? AND tx_hash=?
            """,
            (receipt.block_number, receipt.block_hash, receipt.raw_json, spec.operation_uid, receipt.tx_hash),
        )
    conn.execute(
        """
        UPDATE operations
        SET status='FAILED', updated_at=?, error_code='CHAIN_REVERT', error_detail=?
        WHERE operation_uid=? AND status IN ('PENDING','SUBMITTED','RECONCILIATION_REQUIRED')
        """,
        (stamp, detail, spec.operation_uid),
    )
    if spec.operation_type in SAFE_RELEASE_ON_REVERT:
        conn.execute("DELETE FROM product_reservations WHERE operation_uid=?", (spec.operation_uid,))
    projection = spec.signed_payload.get("projection") or {}
    transfer_id = spec.signed_payload.get("transfer_id") or projection.get("transfer_id")
    if spec.operation_type == "INITIATE_TRANSFER":
        conn.execute(
            """
            UPDATE transfers SET chain_status='FAILED'
            WHERE initiation_operation_uid=? AND chain_status IN ('PENDING','SUBMITTED')
            """,
            (spec.operation_uid,),
        )
    if spec.operation_type in {"ACCEPT_TRANSFER", "REJECT_TRANSFER", "CANCEL_TRANSFER"} and transfer_id is not None:
        conn.execute(
            """
            UPDATE transfers
            SET terminal_operation_uid=NULL
            WHERE transfer_id=? AND transfer_status='INITIATED' AND terminal_operation_uid=?
            """,
            (transfer_id, spec.operation_uid),
        )
    conn.commit()


def confirm_operation(conn: sqlite3.Connection, spec: OperationSpec, receipt: ReceiptInfo) -> None:
    conn.execute("BEGIN IMMEDIATE")
    stamp = _now()
    existing = conn.execute(
        "SELECT status FROM operations WHERE operation_uid=?", (spec.operation_uid,)
    ).fetchone()
    event_count = conn.execute(
        "SELECT COUNT(*) AS n FROM event_ledger WHERE operation_uid=?", (spec.operation_uid,)
    ).fetchone()["n"]

    submission = conn.execute(
        "SELECT submission_id, status FROM chain_submissions WHERE operation_uid=? ORDER BY attempt_no DESC LIMIT 1",
        (spec.operation_uid,),
    ).fetchone()
    if submission["status"] != "MINED":
        conn.execute(
            """
            UPDATE chain_submissions
            SET status='MINED', receipt_status=1, block_number=?, block_hash=?,
                receipt_json=?, confirmations=1
            WHERE submission_id=?
            """,
            (receipt.block_number, receipt.block_hash, receipt.raw_json, submission["submission_id"]),
        )
    if existing["status"] != "CONFIRMED":
        conn.execute(
            """
            UPDATE operations
            SET status='CONFIRMED', confirmed_at=?, updated_at=?
            WHERE operation_uid=?
            """,
            (stamp, stamp, spec.operation_uid),
        )

    event_ids: list[int] = []
    if event_count == 0:
        for event_row in spec.signed_payload.get("events", []):
            event_ids.append(insert_event_row(conn, event_row))
    else:
        event_ids = [
            row["event_id"]
            for row in conn.execute(
                "SELECT event_id FROM event_ledger WHERE operation_uid=? ORDER BY seq",
                (spec.operation_uid,),
            )
        ]

    for event_id, event_row in zip(event_ids, spec.signed_payload.get("events", [])):
        already = conn.execute(
            "SELECT 1 FROM event_anchors WHERE event_id=? AND deployment_id=?",
            (event_id, spec.deployment_id),
        ).fetchone()
        if already:
            continue
        conn.execute(
            """
            INSERT INTO event_anchors(event_id, deployment_id, submission_id, anchored_hash, chain_status, verified_at)
            VALUES (?, ?, ?, ?, 'CONFIRMED', ?)
            """,
            (event_id, spec.deployment_id, submission["submission_id"], event_row["event_hash"], stamp),
        )

    _apply_projection(conn, spec, event_ids, stamp)
    if spec.operation_type in {
        "ACCEPT_TRANSFER",
        "REJECT_TRANSFER",
        "CANCEL_TRANSFER",
        "EXPIRE_TRANSFER",
        "SELL_PRODUCT",
    }:
        conn.execute("DELETE FROM product_reservations WHERE operation_uid=?", (spec.operation_uid,))
        transfer_id = spec.signed_payload.get("transfer_id")
        if transfer_id is not None:
            conn.execute("DELETE FROM product_reservations WHERE transfer_id=?", (transfer_id,))
    conn.commit()


def _apply_projection(
    conn: sqlite3.Connection, spec: OperationSpec, event_ids: list[int], stamp: str
) -> None:
    projection = spec.signed_payload.get("projection") or {}
    kind = projection.get("type") or spec.operation_type
    if kind == "REGISTER_PRODUCT" and event_ids:
        product_id = projection["product_id"]
        conn.execute(
            """
            UPDATE products
            SET registration_state='CONFIRMED', registration_operation_uid=?, latest_event_id=?
            WHERE product_id=? AND registration_state='PENDING'
            """,
            (spec.operation_uid, event_ids[0], product_id),
        )
        already = conn.execute("SELECT 1 FROM custody WHERE product_id=?", (product_id,)).fetchone()
        if already:
            return
        conn.execute(
            """
            INSERT INTO custody(
                verification_state, last_event_id, last_operation_uid, data_origin,
                product_id, custodian_organization_id, warehouse_id, updated_at
            ) VALUES ('CONFIRMED', ?, ?, 'LIVE', ?, ?, ?, ?)
            """,
            (
                event_ids[0],
                spec.operation_uid,
                product_id,
                spec.organization_id,
                projection.get("warehouse_id"),
                stamp,
            ),
        )
    elif kind == "INITIATE_TRANSFER":
        conn.execute(
            """
            UPDATE transfers SET chain_status='CONFIRMED'
            WHERE initiation_operation_uid=? AND chain_status='PENDING'
            """,
            (spec.operation_uid,),
        )
    elif kind == "ACCEPT_TRANSFER":
        products = projection.get("products") or []
        for event_id, product in zip(event_ids, products):
            conn.execute(
                """
                UPDATE custody
                SET custodian_organization_id=?, warehouse_id=?, last_event_id=?,
                    last_operation_uid=?, last_transfer_id=?, updated_at=?
                WHERE product_id=?
                """,
                (
                    projection["recipient_organization_id"],
                    projection.get("destination_warehouse_id"),
                    event_id,
                    spec.operation_uid,
                    projection["transfer_id"],
                    stamp,
                    product["product_id"],
                ),
            )
            conn.execute(
                """
                UPDATE products SET lifecycle_state='IN_SUPPLY_CHAIN'
                WHERE product_id=? AND lifecycle_state='REGISTERED'
                """,
                (product["product_id"],),
            )
        conn.execute(
            """
            UPDATE transfers
            SET transfer_status='ACCEPTED', chain_status='CONFIRMED', accepted_at=?,
                accepted_by_user_id=?, recipient_signature=?, recipient_key_id=?,
                receipt_digest=?, terminal_operation_uid=?
            WHERE transfer_id=? AND transfer_status='INITIATED'
            """,
            (
                stamp,
                projection.get("accepted_by_user_id"),
                projection.get("recipient_signature"),
                projection.get("recipient_key_id"),
                projection.get("receipt_digest"),
                spec.operation_uid,
                projection["transfer_id"],
            ),
        )
    elif kind in {"REJECT_TRANSFER", "CANCEL_TRANSFER"}:
        status = "REJECTED" if kind == "REJECT_TRANSFER" else "CANCELLED"
        conn.execute(
            """
            UPDATE transfers
            SET transfer_status=?, chain_status='CONFIRMED', terminal_operation_uid=?
            WHERE transfer_id=? AND transfer_status='INITIATED'
            """,
            (status, spec.operation_uid, projection["transfer_id"]),
        )


def wait_and_finalize(
    conn_factory,
    spec: OperationSpec,
    chain: ChainClient,
    signed: SignedTx,
    timeout_seconds: float,
) -> str:
    receipt = _wait_receipt(chain, signed.tx_hash, timeout_seconds)
    if receipt is None:
        return "SUBMITTED"
    conn = conn_factory()
    try:
        if receipt.status != 1:
            mark_failed(conn, spec, receipt, "transaction reverted")
            return "FAILED"
        if receipt.contract_address and receipt.contract_address.lower() != chain.contract_address.lower():
            mark_unverifiable(conn, spec, "contract address mismatch")
            return "RECONCILIATION_REQUIRED"
        confirm_operation(conn, spec, receipt)
        return "CONFIRMED"
    finally:
        conn.close()


def mark_unverifiable(conn: sqlite3.Connection, spec: OperationSpec, detail: str) -> None:
    stamp = _now()
    conn.execute("BEGIN IMMEDIATE")
    conn.execute(
        """
        UPDATE operations
        SET status='RECONCILIATION_REQUIRED', updated_at=?, error_code='CHAIN_RESET', error_detail=?
        WHERE operation_uid=? AND status IN ('PENDING','SUBMITTED','CONFIRMED','RECONCILIATION_REQUIRED')
        """,
        (stamp, detail, spec.operation_uid),
    )
    conn.execute(
        "UPDATE event_anchors SET chain_status='UNVERIFIABLE' WHERE deployment_id=?",
        (spec.deployment_id,),
    )
    conn.execute(
        "UPDATE chain_deployments SET status='RESET' WHERE deployment_id=?",
        (spec.deployment_id,),
    )
    conn.commit()


def _wait_receipt(chain: ChainClient, tx_hash: str, timeout_seconds: float) -> ReceiptInfo | None:
    import time

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        receipt = chain.get_receipt(tx_hash)
        if receipt is not None:
            return receipt
        time.sleep(0.05)
    return None


def execute_operation(
    spec: OperationSpec,
    chain: ChainClient,
    *,
    db_path=None,
    wait: bool = True,
    timeout_seconds: float | None = None,
    persist: bool = True,
) -> str:
    from backend.config import get_settings

    if persist:
        conn = connect(db_path)
        try:
            persist_pending(conn, spec)
        finally:
            conn.close()

    signed = chain.sign_function_call(spec.chain_function, spec.chain_args, spec.sender_private_key)

    conn = connect(db_path)
    try:
        persist_submission(conn, spec, signed)
    finally:
        conn.close()

    chain.broadcast(signed)

    if not wait:
        return "SUBMITTED"
    timeout = timeout_seconds if timeout_seconds is not None else get_settings().receipt_timeout_seconds
    return wait_and_finalize(lambda: connect(db_path), spec, chain, signed, timeout)
