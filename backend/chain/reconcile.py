from __future__ import annotations

import json
import logging
from pathlib import Path

from backend.chain.adapter import ChainClient, SignedTx
from backend.chain.pipeline import (
    ChainUnverifiable,
    OperationSpec,
    confirm_operation,
    mark_failed,
    mark_unverifiable,
)
from backend.db import connect

logger = logging.getLogger("tracetrust.chain")


def _spec_from_db(conn, operation_uid: str) -> tuple[OperationSpec, SignedTx | None]:
    row = conn.execute("SELECT * FROM operations WHERE operation_uid=?", (operation_uid,)).fetchone()
    payload = json.loads(row["signed_payload_json"] or "{}")
    spec = OperationSpec(
        operation_uid=row["operation_uid"],
        operation_type=row["operation_type"],
        actor_user_id=row["actor_user_id"],
        organization_id=row["organization_id"],
        idempotency_scope=row["idempotency_scope"],
        idempotency_key=row["idempotency_key"],
        request_hash=row["request_hash"],
        canonical_intent=json.loads(row["canonical_intent"]),
        signed_payload=payload,
        expected_heads=json.loads(row["expected_heads_json"] or "{}"),
        deployment_id=row["deployment_id"],
        chain_function=payload.get("chain_function") or "registerProduct",
        chain_args=payload.get("chain_args") or [],
        sender_private_key="",
        sender_address=payload.get("sender_address") or "",
    )
    sub = conn.execute(
        """
        SELECT raw_signed_transaction, tx_hash, sender_address, account_nonce
        FROM chain_submissions
        WHERE operation_uid=?
        ORDER BY attempt_no DESC
        LIMIT 1
        """,
        (operation_uid,),
    ).fetchone()
    signed = None
    if sub is not None:
        signed = SignedTx(
            raw_signed_transaction=sub["raw_signed_transaction"],
            tx_hash=sub["tx_hash"],
            sender_address=sub["sender_address"],
            account_nonce=sub["account_nonce"],
        )
        spec.sender_address = sub["sender_address"]
    return spec, signed


def _deployment_contract(conn, deployment_id: str) -> tuple[str, int]:
    row = conn.execute(
        "SELECT contract_address, chain_id, status FROM chain_deployments WHERE deployment_id=?",
        (deployment_id,),
    ).fetchone()
    if row is None:
        raise ChainUnverifiable("missing deployment")
    return row["contract_address"], int(row["chain_id"])


def reconcile_pending(db_path: Path | None = None, chain: ChainClient | None = None) -> dict[str, str]:
    """Replay SUBMITTED/PENDING operations. Timeouts stay pending; only a revert is FAILED."""
    results: dict[str, str] = {}
    conn = connect(db_path)
    try:
        rows = conn.execute("SELECT operation_uid, status FROM pending_chain_operations").fetchall()
        pending = [dict(row) for row in rows]
    finally:
        conn.close()

    for item in pending:
        uid = item["operation_uid"]
        conn = connect(db_path)
        try:
            spec, signed = _spec_from_db(conn, uid)
            contract_address, expected_chain_id = _deployment_contract(conn, spec.deployment_id)
            if chain is None:
                from backend.chain.adapter import Web3Chain

                chain = Web3Chain(contract_address=contract_address)
            if chain.get_chain_id() != expected_chain_id or chain.get_code(contract_address) == b"":
                mark_unverifiable(conn, spec, "local chain reset or deployment missing")
                results[uid] = "UNVERIFIABLE"
                continue
            if signed is None:
                results[uid] = "PENDING"
                continue
            receipt = chain.get_receipt(signed.tx_hash)
            if receipt is None:
                try:
                    chain.broadcast(signed)
                except Exception as exc:
                    logger.warning("rebroadcast failed for %s: %s", uid, exc)
                results[uid] = "SUBMITTED"
                continue
            if receipt.status != 1:
                mark_failed(conn, spec, receipt, "transaction reverted")
                results[uid] = "FAILED"
                continue
            confirm_operation(conn, spec, receipt)
            results[uid] = "CONFIRMED"
        except ChainUnverifiable as exc:
            mark_unverifiable(conn, spec, str(exc))
            results[uid] = "UNVERIFIABLE"
        except Exception:
            logger.exception("reconcile failed for %s", uid)
            results[uid] = item["status"]
        finally:
            conn.close()
    return results
