from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from eth_account import Account
from fastapi.testclient import TestClient

from backend.chain.adapter import MockChain
from backend.config import ROOT, get_settings
from backend.db import connect
from backend.migrations.v4_gps import apply_v4
from backend.migrations.v5_email import apply_v5
from backend.migrations.v6_fusion import apply_v6
from backend.scripts.enable_demo_passwords import enable_staff_passwords

STAFF_PASSWORDS = {
    "DEMO_MANUFACTURER_PASSWORD": "manufacturer-pass-ok",
    "DEMO_DISTRIBUTOR_PASSWORD": "distributor-pass-ok",
    "DEMO_RETAILER_PASSWORD": "retailer-pass-12ok",
}


@pytest.fixture
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    dest = tmp_path / "test.db"
    shutil.copy2(ROOT / "laptop_anti_counterfeit.db", dest)
    monkeypatch.setenv("DATABASE_PATH", str(dest))
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-32-bytes-minimum-ok")
    monkeypatch.setenv("JWT_ISSUER", "tracetrust")
    monkeypatch.setenv("JWT_AUDIENCE", "tracetrust-api")
    for key, value in STAFF_PASSWORDS.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    apply_v4(dest)
    apply_v5(dest)
    apply_v6(dest)
    enable_staff_passwords(dest, environ={**STAFF_PASSWORDS})
    return dest


def account_private_key(account) -> str:
    key = account.key
    if hasattr(key, "to_0x_hex"):
        return key.to_0x_hex()
    text = key.hex()
    return text if text.startswith("0x") else "0x" + text


def seed_org_chain(db_path: Path, accounts: dict[int, object]) -> str:
    deployment_id = f"test-{uuid4()}"
    stamp = "2026-10-12 20:00:00"
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
        for org_id, account in accounts.items():
            existing = conn.execute(
                """
                SELECT key_id, key_version, eth_address
                FROM signing_keys
                WHERE organization_id=?
                ORDER BY key_version DESC LIMIT 1
                """,
                (org_id,),
            ).fetchone()
            if existing is not None and existing["eth_address"].lower() == account.address.lower():
                key_id = existing["key_id"]
            else:
                version = int(existing["key_version"]) + 1 if existing is not None else 1
                key_id = f"org-{org_id}-v{version}"
                conn.execute(
                    """
                    INSERT INTO signing_keys(
                        key_id, organization_id, device_id, key_version, eth_address, valid_from, valid_until, status
                    ) VALUES (?, ?, NULL, ?, ?, ?, NULL, 'ACTIVE')
                    """,
                    (key_id, org_id, version, account.address, stamp),
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
    finally:
        conn.close()
    return deployment_id


def seed_manufacturer_chain(db_path: Path, account) -> str:
    return seed_org_chain(db_path, {1: account})


@pytest.fixture
def client(db_path: Path) -> TestClient:
    get_settings.cache_clear()
    from backend.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client
    get_settings.cache_clear()


@pytest.fixture
def live_client(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    manufacturer = Account.create()
    distributor = Account.create()
    retailer = Account.create()
    monkeypatch.setenv("ORG_PRIVATE_KEY_MANUFACTURER", account_private_key(manufacturer))
    monkeypatch.setenv("ORG_PRIVATE_KEY_DISTRIBUTOR", account_private_key(distributor))
    monkeypatch.setenv("ORG_PRIVATE_KEY_RETAILER", account_private_key(retailer))
    get_settings.cache_clear()
    seed_org_chain(db_path, {1: manufacturer, 2: distributor, 3: retailer})
    from backend.main import create_app

    app = create_app()
    app.state.chain = MockChain(contract_address="0x" + "11" * 20)
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()
