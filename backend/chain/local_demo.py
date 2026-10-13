"""Provision a local demo chain so register/transfer work without Hardhat."""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from eth_account import Account

from backend.config import ROOT, get_settings
from backend.crypto.keys import address_from_private_key
from backend.db import connect

logger = logging.getLogger("tracetrust")


def _keystore_path() -> Path:
    if os.access(ROOT, os.W_OK):
        return ROOT / "keystore.json"
    return Path(tempfile.gettempdir()) / "tracetrust-keystore.json"


KEYSTORE_PATH = _keystore_path()
LOCAL_CONTRACT = "0x" + "11" * 20
ORG_IDS = ((1, "MANUFACTURER"), (2, "DISTRIBUTOR"), (3, "RETAILER"))
# Filled only when locations.latitude/longitude are NULL. Used by location_check (50 km).
DEMO_LOCATION_COORDS = {
    1: (18.5204, 73.8567),  # Pune factory
    2: (19.0760, 72.8777),  # Mumbai distribution
    3: (19.1197, 72.8464),  # Mumbai retail
}


def _key_hex(account) -> str:
    key = account.key
    if hasattr(key, "to_0x_hex"):
        return key.to_0x_hex()
    text = key.hex()
    return text if text.startswith("0x") else "0x" + text


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def ensure_keystore() -> dict[str, str]:
    if KEYSTORE_PATH.exists():
        data = json.loads(KEYSTORE_PATH.read_text(encoding="utf-8"))
        if all(role in data for _, role in ORG_IDS):
            return data
    data = {role: _key_hex(Account.create()) for _, role in ORG_IDS}
    data["GOVERNANCE"] = _key_hex(Account.create())
    KEYSTORE_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    get_settings.cache_clear()
    return data


def provision_demo_orgs(keys: dict[str, str]) -> None:
    conn = connect()
    stamp = _stamp()
    try:
        conn.execute("BEGIN IMMEDIATE")
        active = conn.execute(
            "SELECT 1 FROM chain_deployments WHERE status='ACTIVE' LIMIT 1"
        ).fetchone()
        if active is None:
            salt = "0x" + uuid4().hex + uuid4().hex
            conn.execute(
                """
                INSERT INTO chain_deployments(
                    deployment_id, chain_id, contract_address, deployment_salt,
                    start_block, status, created_at
                ) VALUES (?, 31337, ?, ?, 0, 'ACTIVE', ?)
                """,
                ("local-mock-v1", LOCAL_CONTRACT, salt, stamp),
            )
        for org_id, role in ORG_IDS:
            org = conn.execute(
                "SELECT current_key_id, provisioning_state FROM organizations WHERE organization_id=?",
                (org_id,),
            ).fetchone()
            if org is None:
                continue
            if org["current_key_id"] and org["provisioning_state"] == "CONFIRMED":
                continue
            private_key = keys.get(role)
            if not private_key:
                continue
            key_id = f"org-{org_id}-v1"
            existing = conn.execute("SELECT 1 FROM signing_keys WHERE key_id=?", (key_id,)).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO signing_keys(
                        key_id, organization_id, device_id, key_version, eth_address,
                        valid_from, valid_until, status
                    ) VALUES (?, ?, NULL, 1, ?, ?, NULL, 'ACTIVE')
                    """,
                    (key_id, org_id, address_from_private_key(private_key), stamp),
                )
            conn.execute(
                """
                UPDATE organizations
                SET current_key_id=?, provisioning_state='CONFIRMED'
                WHERE organization_id=?
                """,
                (key_id, org_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def provision_demo_warehouse_coords() -> None:
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        for location_id, (lat, lng) in DEMO_LOCATION_COORDS.items():
            conn.execute(
                """
                UPDATE locations
                SET latitude=?, longitude=?
                WHERE location_id=? AND (latitude IS NULL OR longitude IS NULL)
                """,
                (lat, lng, location_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def attach_chain(app) -> None:
    if getattr(app.state, "chain", None) is not None:
        return
    from backend.chain.adapter import MockChain, Web3Chain

    settings = get_settings()
    try:
        from web3 import Web3

        w3 = Web3(Web3.HTTPProvider(settings.rpc_url, request_kwargs={"timeout": 1}))
        if w3.is_connected() and settings.contract_address:
            app.state.chain = Web3Chain(
                rpc_url=settings.rpc_url,
                contract_address=settings.contract_address,
            )
            return
    except Exception:
        logger.info("Hardhat RPC not available; using in-process mock chain")
    chain = MockChain(contract_address=LOCAL_CONTRACT)
    hydrate_mock_chain(chain)
    app.state.chain = chain


def hydrate_mock_chain(chain) -> None:
    """Rebuild in-memory product heads from confirmed local events after a process restart."""
    from backend.chain.adapter import ProductOnChain
    from backend.chain.ids import sha256_to_bytes32, uid_to_bytes32

    lifecycle = {"REGISTERED": 1, "IN_SUPPLY_CHAIN": 2, "SOLD": 3}
    conn = connect()
    try:
        rows = conn.execute(
            """
            SELECT p.product_uid, p.lifecycle_state,
                   (SELECT COUNT(*) FROM event_ledger e WHERE e.product_id=p.product_id) AS n,
                   (SELECT event_hash FROM event_ledger e WHERE e.product_id=p.product_id ORDER BY seq DESC LIMIT 1) AS head,
                   k.eth_address AS custodian
            FROM products p
            LEFT JOIN custody c ON c.product_id = p.product_id
            LEFT JOIN organizations o ON o.organization_id = c.custodian_organization_id
            LEFT JOIN signing_keys k ON k.key_id = o.current_key_id
            WHERE p.data_origin='LIVE' AND p.registration_state='CONFIRMED'
            """
        ).fetchall()
    finally:
        conn.close()
    for row in rows:
        if not row["head"] or not row["n"]:
            continue
        try:
            head = sha256_to_bytes32(row["head"])
        except ValueError:
            continue
        chain._products[uid_to_bytes32(row["product_uid"])] = ProductOnChain(
            custodian=row["custodian"] or ("0x" + "00" * 20),
            lifecycle=lifecycle.get(row["lifecycle_state"], 1),
            seq=int(row["n"]) - 1,
            event_head=head,
            reserved_transfer_id=b"\x00" * 32,
            exists=True,
        )


def prepare_local_demo(app) -> None:
    settings = get_settings()
    if settings.database_path.name != "laptop_anti_counterfeit.db":
        return
    keys = ensure_keystore()
    provision_demo_orgs(keys)
    provision_demo_warehouse_coords()
    attach_chain(app)
