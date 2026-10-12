from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.conftest import STAFF_PASSWORDS


def _login(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _mfr(client: TestClient) -> dict[str, str]:
    return _login(client, "demo_manufacturer", STAFF_PASSWORDS["DEMO_MANUFACTURER_PASSWORD"])


def _dst(client: TestClient) -> dict[str, str]:
    return _login(client, "demo_distributor", STAFF_PASSWORDS["DEMO_DISTRIBUTOR_PASSWORD"])


def _body(**overrides) -> dict:
    payload = {
        "batch_id": 1,
        "warehouse_id": 1,
        "serial_number": f"LIVE-SERIAL-{uuid4().hex[:12]}",
        "box_serial": f"BOX-{uuid4().hex[:12]}",
        "seal_id": f"SEAL-{uuid4().hex[:12]}",
        "gps": {
            "gps_status": "CAPTURED",
            "latitude": 18.52,
            "longitude": 73.856,
            "gps_accuracy_cm": 150,
        },
    }
    payload.update(overrides)
    return payload


def test_wrong_role_cannot_register(live_client: TestClient) -> None:
    headers = _dst(live_client)
    headers["Idempotency-Key"] = str(uuid4())
    response = live_client.post("/products", json=_body(), headers=headers)
    assert response.status_code == 403

    batches = live_client.get("/batches", headers=_dst(live_client))
    assert batches.status_code == 403


def test_duplicate_serial_rejected(live_client: TestClient) -> None:
    auth = _mfr(live_client)
    body = _body()
    first = live_client.post(
        "/products",
        json=body,
        headers={**auth, "Idempotency-Key": str(uuid4())},
    )
    assert first.status_code == 202, first.text
    second = live_client.post(
        "/products",
        json={**body, "box_serial": f"BOX-{uuid4().hex[:12]}", "seal_id": f"SEAL-{uuid4().hex[:12]}"},
        headers={**auth, "Idempotency-Key": str(uuid4())},
    )
    assert second.status_code == 409


def test_idempotency_replay_returns_same_result(live_client: TestClient) -> None:
    auth = _mfr(live_client)
    body = _body()
    key = str(uuid4())
    first = live_client.post("/products", json=body, headers={**auth, "Idempotency-Key": key})
    second = live_client.post("/products", json=body, headers={**auth, "Idempotency-Key": key})
    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text
    assert first.json()["operation_uid"] == second.json()["operation_uid"]
    assert first.json()["status_url"] == second.json()["status_url"]
    assert first.json()["qr_payload"]
    assert second.json().get("qr_payload") in (None, first.json()["qr_payload"])


def test_idempotency_key_with_different_body_conflicts(live_client: TestClient) -> None:
    auth = _mfr(live_client)
    key = str(uuid4())
    first = live_client.post("/products", json=_body(), headers={**auth, "Idempotency-Key": key})
    assert first.status_code == 202, first.text
    second = live_client.post("/products", json=_body(), headers={**auth, "Idempotency-Key": key})
    assert second.status_code == 409


def test_invalid_latitude_longitude_rejected(live_client: TestClient) -> None:
    auth = _mfr(live_client)
    headers = {**auth, "Idempotency-Key": str(uuid4())}
    lat = live_client.post(
        "/products",
        json=_body(gps={"gps_status": "CAPTURED", "latitude": 91, "longitude": 73.8}),
        headers=headers,
    )
    assert lat.status_code == 422
    lng = live_client.post(
        "/products",
        json=_body(gps={"gps_status": "CAPTURED", "latitude": 18.5, "longitude": 200}),
        headers={**auth, "Idempotency-Key": str(uuid4())},
    )
    assert lng.status_code == 422


def test_register_inventory_operation_and_qr(live_client: TestClient) -> None:
    auth = _mfr(live_client)
    warehouses = live_client.get("/warehouses", headers=auth)
    assert warehouses.status_code == 200
    assert any(item["warehouse_id"] == 1 for item in warehouses.json())

    batches = live_client.get("/batches", headers=auth)
    assert batches.status_code == 200
    assert any(item["batch_id"] == 1 and item["batch_status"] == "ACTIVE" for item in batches.json())

    body = _body()
    created = live_client.post(
        "/products",
        json=body,
        headers={**auth, "Idempotency-Key": str(uuid4())},
    )
    assert created.status_code == 202, created.text
    payload = created.json()
    assert payload["operation_uid"]
    assert payload["chain_status"] in {"SUBMITTED", "CONFIRMED"}
    assert payload["status_url"] == f"/operations/{payload['operation_uid']}"
    assert payload["qr_payload"].startswith("tt:v1:")
    product_uid = payload["product_uid"]

    op = live_client.get(payload["status_url"], headers=auth)
    assert op.status_code == 200
    assert op.json()["status"] == "CONFIRMED"
    assert op.json()["chain_status"] == "CONFIRMED"

    inventory = live_client.get("/inventory", headers=auth)
    assert inventory.status_code == 200
    uids = [item["product_uid"] for item in inventory.json()]
    assert product_uid in uids
    assert all("qr_token" not in item and "qr_payload" not in item for item in inventory.json())

    label = live_client.get(f"/products/{product_uid}/qr", headers=auth)
    assert label.status_code == 200
    assert label.json()["qr_payload"] == payload["qr_payload"]
    assert label.json()["serial_number"] == body["serial_number"]
    assert label.json()["box_serial"] == body["box_serial"]
    assert label.json()["seal_id"] == body["seal_id"]

    labels = live_client.get("/labels", headers=auth)
    assert labels.status_code == 200
    match = next(item for item in labels.json() if item["product_uid"] == product_uid)
    assert match["qr_payload"] == payload["qr_payload"]
    assert match["custodian"] == "MANUFACTURER"


def test_qr_label_rejected_until_confirmed(live_client: TestClient) -> None:
    live_client.app.state.chain.hold_receipts = True
    from backend.config import get_settings

    settings = get_settings()
    previous = settings.receipt_timeout_seconds
    settings.receipt_timeout_seconds = 0.15
    try:
        auth = _mfr(live_client)
        created = live_client.post(
            "/products",
            json=_body(),
            headers={**auth, "Idempotency-Key": str(uuid4())},
        )
        assert created.status_code == 202, created.text
        assert created.json()["chain_status"] == "SUBMITTED"
        label = live_client.get(
            f"/products/{created.json()['product_uid']}/qr",
            headers=auth,
        )
        assert label.status_code == 409
    finally:
        settings.receipt_timeout_seconds = previous
