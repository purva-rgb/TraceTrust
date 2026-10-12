from __future__ import annotations

import sqlite3
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.auth.passwords import hash_password
from backend.auth.tokens import GENERIC_AUTH_FAILURE
from tests.conftest import STAFF_PASSWORDS


def test_login_wrong_password(client: TestClient) -> None:
    response = client.post(
        "/auth/login",
        json={"username": "demo_manufacturer", "password": "definitely-wrong"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == GENERIC_AUTH_FAILURE


def test_login_unknown_user(client: TestClient) -> None:
    response = client.post(
        "/auth/login",
        json={"username": "nobody", "password": "manufacturer-pass-ok"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == GENERIC_AUTH_FAILURE


def test_login_success_and_me_reloads_db(client: TestClient) -> None:
    response = client.post(
        "/auth/login",
        json={
            "username": "demo_manufacturer",
            "password": STAFF_PASSWORDS["DEMO_MANUFACTURER_PASSWORD"],
        },
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    body = me.json()
    assert body["username"] == "demo_manufacturer"
    assert body["role"] == "MANUFACTURER"
    assert body["organization_type"] == "MANUFACTURER"
    assert "password_hash" not in body


def test_disabled_roles_cannot_login_even_if_enabled_in_db(
    client: TestClient, db_path
) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=ON")
    stamp_hash = hash_password("admin-should-never-work")
    conn.execute(
        """
        UPDATE users
        SET password_hash = ?, password_reset_required = 0, status = 'ACTIVE',
            credential_scheme = 'scrypt'
        WHERE username = 'demo_admin'
        """,
        (stamp_hash,),
    )
    conn.execute(
        """
        UPDATE users
        SET password_hash = ?, password_reset_required = 0, status = 'ACTIVE',
            credential_scheme = 'scrypt'
        WHERE username = 'demo_regulator'
        """,
        (hash_password("regulator-should-fail"),),
    )
    conn.execute(
        """
        UPDATE users
        SET password_hash = ?, password_reset_required = 0, status = 'ACTIVE',
            credential_scheme = 'scrypt'
        WHERE username = 'demo_auditor'
        """,
        (hash_password("auditor-should-fail-x"),),
    )
    conn.commit()
    conn.close()

    for username, password in (
        ("demo_admin", "admin-should-never-work"),
        ("demo_regulator", "regulator-should-fail"),
        ("demo_auditor", "auditor-should-fail-x"),
    ):
        response = client.post(
            "/auth/login", json={"username": username, "password": password}
        )
        assert response.status_code == 401, username
        assert response.json()["detail"] == GENERIC_AUTH_FAILURE


def test_login_with_demo_email(client: TestClient) -> None:
    response = client.post(
        "/auth/login",
        json={
            "email": "manufacturer@tracetrust.demo",
            "password": STAFF_PASSWORDS["DEMO_MANUFACTURER_PASSWORD"],
        },
    )
    assert response.status_code == 200, response.text
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {response.json()['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == "manufacturer@tracetrust.demo"


def test_first_time_register_then_login(live_client: TestClient) -> None:
    email = f"mfr-{uuid4().hex[:8]}@example.com"
    created = live_client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "signup-pass-ok",
            "role": "MANUFACTURER",
            "organization_name": "New Factory Co",
        },
    )
    assert created.status_code == 200, created.text
    assert created.json()["email"] == email
    login = live_client.post("/auth/login", json={"email": email, "password": "signup-pass-ok"})
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    me = live_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["role"] == "MANUFACTURER"
    assert me.json()["email"] == email
    batches = live_client.get("/batches", headers={"Authorization": f"Bearer {token}"})
    assert batches.status_code == 200
    assert batches.json()
