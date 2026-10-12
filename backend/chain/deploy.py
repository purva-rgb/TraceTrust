"""Deploy TraceTrust and record chain_deployments + signing_keys (public addresses only)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from eth_account import Account
from hexbytes import HexBytes

from backend.chain.adapter import load_artifact
from backend.chain.ids import to_0x, uid_to_bytes32
from backend.config import ROOT, get_settings
from backend.crypto.keys import address_from_private_key
from backend.db import connect

ROLE = {"MANUFACTURER": 1, "DISTRIBUTOR": 2, "RETAILER": 3}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def deploy_and_record(db_path: Path | None = None) -> dict[str, str]:
    from web3 import Web3

    settings = get_settings()
    if not settings.governance_private_key:
        raise RuntimeError("GOVERNANCE_PRIVATE_KEY is required to deploy")
    w3 = Web3(Web3.HTTPProvider(settings.rpc_url))
    artifact = load_artifact()
    governance = Account.from_key(settings.governance_private_key)
    salt = uid_to_bytes32(settings.deployment_id)
    contract = w3.eth.contract(abi=artifact["abi"], bytecode=artifact["bytecode"])
    nonce = w3.eth.get_transaction_count(governance.address)
    tx = contract.constructor(salt).build_transaction(
        {
            "from": governance.address,
            "nonce": nonce,
            "chainId": int(w3.eth.chain_id),
            "gas": 4_000_000,
            "gasPrice": w3.eth.gas_price,
        }
    )
    signed = governance.sign_transaction(tx)
    raw = signed.raw_transaction
    tx_hash = w3.eth.send_raw_transaction(HexBytes(raw))
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    address = receipt.contractAddress
    deployed = w3.eth.contract(address=address, abi=artifact["abi"])

    org_keys = {
        1: ("MANUFACTURER", settings.org_private_key_manufacturer),
        2: ("DISTRIBUTOR", settings.org_private_key_distributor),
        3: ("RETAILER", settings.org_private_key_retailer),
    }
    nonce = w3.eth.get_transaction_count(governance.address)
    for org_id, (role_name, key) in org_keys.items():
        if not key:
            raise RuntimeError(f"missing private key for {role_name}")
        org_address = address_from_private_key(key)
        fn = deployed.functions.registerOrganization(org_address, ROLE[role_name], True)
        tx = fn.build_transaction(
            {
                "from": governance.address,
                "nonce": nonce,
                "chainId": int(w3.eth.chain_id),
                "gas": 200_000,
                "gasPrice": w3.eth.gas_price,
            }
        )
        signed = governance.sign_transaction(tx)
        w3.eth.send_raw_transaction(HexBytes(signed.raw_transaction))
        w3.eth.wait_for_transaction_receipt(signed.hash)
        nonce += 1

    stamp = _now()
    conn = connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO chain_deployments(
                deployment_id, chain_id, contract_address, deployment_salt, start_block, status, created_at
            ) VALUES (?, ?, ?, ?, ?, 'ACTIVE', ?)
            """,
            (
                settings.deployment_id,
                int(w3.eth.chain_id),
                address,
                to_0x(salt),
                int(receipt.blockNumber),
                stamp,
            ),
        )
        for org_id, (role_name, key) in org_keys.items():
            eth_address = address_from_private_key(key)
            key_id = f"org-{org_id}-v1"
            conn.execute(
                """
                INSERT INTO signing_keys(
                    key_id, organization_id, device_id, key_version, eth_address, valid_from, valid_until, status
                ) VALUES (?, ?, NULL, 1, ?, ?, NULL, 'ACTIVE')
                """,
                (key_id, org_id, eth_address, stamp),
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
    return {"contract_address": address, "deployment_id": settings.deployment_id}


if __name__ == "__main__":
    print(json.dumps(deploy_and_record(), indent=2))
