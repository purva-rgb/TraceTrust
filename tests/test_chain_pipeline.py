from __future__ import annotations

import hashlib
import time
from uuid import uuid4

from eth_account import Account

from backend.chain.adapter import MockChain, SignedTx
from backend.chain.ids import sha256_to_bytes32, uid_to_bytes32
from backend.chain.pipeline import OperationSpec, execute_operation
from backend.chain.reconcile import reconcile_pending
from backend.crypto.events import ZERO_PREVIOUS_HASH, build_signed_event_row
from backend.db import connect
from backend.migrations.v4_gps import apply_v4


def _pk(account) -> str:
    key = account.key
    if hasattr(key, "to_0x_hex"):
        return key.to_0x_hex()
    text = key.hex()
    return text if text.startswith("0x") else "0x" + text


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _seed_deployment(db_path, account) -> str:
    apply_v4(db_path)
    deployment_id = f"test-{uuid4()}"
    stamp = "2026-10-12 19:00:00"
    conn = connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO chain_deployments(
                deployment_id, chain_id, contract_address, deployment_salt, start_block, status, created_at
            ) VALUES (?, 31337, ?, ?, 0, 'ACTIVE', ?)
            """,
            (deployment_id, "0x" + "11" * 20, "0x" + uuid4().hex, stamp),
        )
        existing = conn.execute(
            """
            SELECT key_id, key_version, eth_address
            FROM signing_keys WHERE organization_id=1
            ORDER BY key_version DESC LIMIT 1
            """
        ).fetchone()
        if existing is not None and existing["eth_address"].lower() == account.address.lower():
            key_id = existing["key_id"]
        else:
            version = int(existing["key_version"]) + 1 if existing is not None else 1
            key_id = f"org-1-v{version}"
            conn.execute(
                """
                INSERT INTO signing_keys(
                    key_id, organization_id, device_id, key_version, eth_address, valid_from, valid_until, status
                ) VALUES (?, 1, NULL, ?, ?, ?, NULL, 'ACTIVE')
                """,
                (key_id, version, account.address, stamp),
            )
        conn.execute(
            """
            UPDATE organizations
            SET current_key_id=?, provisioning_state='CONFIRMED'
            WHERE organization_id=1
            """,
            (key_id,),
        )
        conn.commit()
    finally:
        conn.close()
    return deployment_id


def _insert_live_product(db_path) -> dict:
    product_uid = str(uuid4())
    token = uuid4().hex
    conn = connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO products(
                product_uid, lifecycle_state, registration_state, is_simulated, data_origin,
                product_code, serial_number, qr_token, batch_id, brand, model_name,
                product_category, manufacturer_id, product_status
            ) VALUES (?, 'REGISTERED', 'PENDING', 0, 'LIVE', ?, ?, ?, 1, 'Dell', 'Latitude Demo 14', 'LAPTOP', 1, 'ACTIVE')
            """,
            (product_uid, f"LAP-LIVE-{token[:12]}", f"LIVE-SERIAL-{token[:12]}", token),
        )
        product_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        org_uid = conn.execute(
            "SELECT organization_uid FROM organizations WHERE organization_id=1"
        ).fetchone()[0]
        conn.commit()
    finally:
        conn.close()
    return {"product_id": product_id, "product_uid": product_uid, "organization_uid": org_uid}


def _register_spec(db_path, account, deployment_id, product, operation_uid: str) -> OperationSpec:
    conn = connect(db_path)
    try:
        event = build_signed_event_row(
            conn,
            product_id=product["product_id"],
            product_uid=product["product_uid"],
            organization_id=1,
            organization_uid=product["organization_uid"],
            organization_type="MANUFACTURER",
            signer_key_id="org-1-v1",
            operation_uid=operation_uid,
            event_type="PRODUCT_REGISTERED",
            actor_user_id=2,
            payload={"gps": {"gps_status": "NOT_REQUESTED"}},
            occurred_at_ms=int(time.time() * 1000),
            private_key=_pk(account),
        )
    finally:
        conn.close()
    intent = {"product_uid": product["product_uid"], "operation_uid": operation_uid}
    payload = {
        "events": [event],
        "projection": {
            "type": "REGISTER_PRODUCT",
            "product_id": product["product_id"],
            "warehouse_id": 1,
        },
        "chain_function": "registerProduct",
        "sender_address": account.address,
    }
    return OperationSpec(
        operation_uid=operation_uid,
        operation_type="REGISTER_PRODUCT",
        actor_user_id=2,
        organization_id=1,
        idempotency_scope="register",
        idempotency_key=operation_uid,
        request_hash=_sha(operation_uid),
        canonical_intent=intent,
        signed_payload=payload,
        expected_heads={product["product_uid"]: ZERO_PREVIOUS_HASH},
        deployment_id=deployment_id,
        chain_function="registerProduct",
        chain_args=[
            uid_to_bytes32(product["product_uid"]),
            sha256_to_bytes32(event["event_hash"]),
            uid_to_bytes32(operation_uid),
        ],
        sender_private_key=_pk(account),
        sender_address=account.address,
        staging_sql=[
            (
                "UPDATE products SET registration_operation_uid=? WHERE product_id=?",
                (operation_uid, product["product_id"]),
            )
        ],
    )


def test_reconcile_after_submitted_kill_confirms_once(db_path) -> None:
    account = Account.create()
    deployment_id = _seed_deployment(db_path, account)
    product = _insert_live_product(db_path)
    spec = _register_spec(db_path, account, deployment_id, product, str(uuid4()))
    chain = MockChain()
    chain.hold_receipts = True
    status = execute_operation(spec, chain, db_path=db_path, wait=False)
    assert status == "SUBMITTED"

    conn = connect(db_path)
    assert conn.execute("SELECT status FROM operations WHERE operation_uid=?", (spec.operation_uid,)).fetchone()[0] == "SUBMITTED"
    assert conn.execute("SELECT COUNT(*) FROM event_ledger WHERE operation_uid=?", (spec.operation_uid,)).fetchone()[0] == 0
    sub = conn.execute("SELECT tx_hash, raw_signed_transaction FROM chain_submissions WHERE operation_uid=?", (spec.operation_uid,)).fetchone()
    conn.close()

    held = SignedTx(
        raw_signed_transaction=sub["raw_signed_transaction"],
        tx_hash=sub["tx_hash"],
        sender_address=account.address,
        account_nonce=0,
    )
    chain.release_receipt(held)
    first = reconcile_pending(db_path, chain=chain)
    assert first[spec.operation_uid] == "CONFIRMED"
    second = reconcile_pending(db_path, chain=chain)
    assert spec.operation_uid not in second

    conn = connect(db_path)
    assert conn.execute(
        "SELECT COUNT(*) FROM event_ledger WHERE operation_uid=? AND product_id=?",
        (spec.operation_uid, product["product_id"]),
    ).fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM event_anchors WHERE event_id IN (SELECT event_id FROM event_ledger WHERE product_id=?)",
        (product["product_id"],),
    ).fetchone()[0] == 1
    assert conn.execute("SELECT status FROM operations WHERE operation_uid=?", (spec.operation_uid,)).fetchone()[0] == "CONFIRMED"
    assert conn.execute("SELECT registration_state FROM products WHERE product_id=?", (product["product_id"],)).fetchone()[0] == "CONFIRMED"
    assert conn.execute("SELECT COUNT(*) FROM custody WHERE product_id=?", (product["product_id"],)).fetchone()[0] == 1
    conn.close()


def test_revert_marks_failed_and_releases_only_safe_reservations(db_path) -> None:
    account = Account.create()
    deployment_id = _seed_deployment(db_path, account)
    product = _insert_live_product(db_path)
    register = _register_spec(db_path, account, deployment_id, product, str(uuid4()))
    chain = MockChain()
    assert execute_operation(register, chain, db_path=db_path, wait=True) == "CONFIRMED"

    conn = connect(db_path)
    event = build_signed_event_row(
        conn,
        product_id=product["product_id"],
        product_uid=product["product_uid"],
        organization_id=1,
        organization_uid=product["organization_uid"],
        organization_type="MANUFACTURER",
        signer_key_id="org-1-v1",
        operation_uid=str(uuid4()),
        event_type="TRANSFER_INITIATED",
        actor_user_id=2,
        payload={"gps": {"gps_status": "NOT_REQUESTED"}},
        occurred_at_ms=int(time.time() * 1000),
        private_key=register.sender_private_key,
    )
    conn.close()
    op_uid = event["operation_uid"]
    initiate = OperationSpec(
        operation_uid=op_uid,
        operation_type="INITIATE_TRANSFER",
        actor_user_id=2,
        organization_id=1,
        idempotency_scope="transfer",
        idempotency_key=op_uid,
        request_hash=_sha(op_uid),
        canonical_intent={"transfer": op_uid},
        signed_payload={
            "events": [event],
            "projection": {"type": "INITIATE_TRANSFER"},
            "chain_function": "initiateTransfer",
            "sender_address": account.address,
        },
        expected_heads={product["product_uid"]: event["previous_hash"]},
        deployment_id=deployment_id,
        chain_function="initiateTransfer",
        chain_args=[],
        sender_private_key=register.sender_private_key,
        sender_address=account.address,
        reservations=[
            {
                "product_id": product["product_id"],
                "transfer_id": None,
                "expires_at": "2099-01-01 00:00:00",
            }
        ],
    )
    chain.revert_next = True
    status = execute_operation(initiate, chain, db_path=db_path, wait=True)
    assert status == "FAILED"

    conn = connect(db_path)
    assert conn.execute("SELECT status FROM operations WHERE operation_uid=?", (op_uid,)).fetchone()[0] == "FAILED"
    assert conn.execute("SELECT COUNT(*) FROM product_reservations WHERE product_id=?", (product["product_id"],)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM event_ledger WHERE operation_uid=?", (op_uid,)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM event_ledger WHERE product_id=?", (product["product_id"],)).fetchone()[0] == 1
    conn.close()


def test_chain_reset_is_unverifiable(db_path) -> None:
    account = Account.create()
    deployment_id = _seed_deployment(db_path, account)
    product = _insert_live_product(db_path)
    spec = _register_spec(db_path, account, deployment_id, product, str(uuid4()))
    chain = MockChain()
    chain.hold_receipts = True
    execute_operation(spec, chain, db_path=db_path, wait=False)
    chain.simulate_reset()
    result = reconcile_pending(db_path, chain=chain)
    assert result[spec.operation_uid] == "UNVERIFIABLE"
    conn = connect(db_path)
    row = conn.execute("SELECT status, error_code FROM operations WHERE operation_uid=?", (spec.operation_uid,)).fetchone()
    assert row["status"] == "RECONCILIATION_REQUIRED"
    assert row["error_code"] == "CHAIN_RESET"
    assert conn.execute("SELECT status FROM chain_deployments WHERE deployment_id=?", (deployment_id,)).fetchone()[0] == "RESET"
    conn.close()
