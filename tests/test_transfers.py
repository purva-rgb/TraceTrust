from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from tests.conftest import STAFF_PASSWORDS
from tests.test_products import _body, _dst, _login, _mfr


def _rtl(client: TestClient) -> dict[str, str]:
    return _login(client, "demo_retailer", STAFF_PASSWORDS["DEMO_RETAILER_PASSWORD"])


def _register(client: TestClient, auth: dict[str, str], **overrides) -> dict:
    body = _body(**overrides)
    response = client.post(
        "/products",
        json=body,
        headers={**auth, "Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 202, response.text
    assert response.json()["chain_status"] == "CONFIRMED"
    return {
        "product_uid": response.json()["product_uid"],
        "box_serial": body["box_serial"],
        "seal_id": body["seal_id"],
        "serial_number": body["serial_number"],
    }


def _initiate(client: TestClient, auth: dict[str, str], product_uids: list[str], recipient_id: int = 2, warehouse_id: int = 2) -> dict:
    response = client.post(
        "/transfers",
        json={
            "recipient_organization_id": recipient_id,
            "destination_warehouse_id": warehouse_id,
            "source_warehouse_id": 1,
            "product_uids": product_uids,
        },
        headers={**auth, "Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 202, response.text
    assert response.json()["chain_status"] == "CONFIRMED"
    return response.json()


def _match_items(products: list[dict]) -> dict:
    return {
        "items": [
            {
                "product_uid": item["product_uid"],
                "box_serial": item["box_serial"],
                "seal_id": item["seal_id"],
                "condition": "INTACT",
                "mode": "SEALED",
            }
            for item in products
        ]
    }


def test_manufacturer_to_retailer_rejected(live_client: TestClient) -> None:
    mfr = _mfr(live_client)
    product = _register(live_client, mfr)
    orgs = live_client.get("/organizations?type=RETAILER", headers=mfr)
    assert orgs.status_code == 200
    assert orgs.json() == []
    dst = live_client.get("/organizations?type=DISTRIBUTOR", headers=mfr)
    assert dst.status_code == 200
    assert any(item["organization_id"] == 2 for item in dst.json())
    distributor = next(item for item in dst.json() if item["organization_id"] == 2)
    assert distributor["username"] == "demo_distributor"
    assert distributor["warehouses"]
    assert all("warehouse_id" in warehouse for warehouse in distributor["warehouses"])

    response = live_client.post(
        "/transfers",
        json={
            "recipient_organization_id": 3,
            "destination_warehouse_id": 3,
            "product_uids": [product["product_uid"]],
        },
        headers={**mfr, "Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "ILLEGAL_EDGE"


def test_wrong_box_seal_and_broken_seal(live_client: TestClient) -> None:
    mfr = _mfr(live_client)
    dst = _dst(live_client)
    product = _register(live_client, mfr)
    created = _initiate(live_client, mfr, [product["product_uid"]])
    uid = created["transfer_uid"]

    wrong_box = live_client.post(
        f"/transfers/{uid}/receipts",
        json={"items": [{**_match_items([product])["items"][0], "box_serial": "WRONG-BOX"}]},
        headers=dst,
    )
    assert wrong_box.status_code == 422
    assert wrong_box.json()["detail"]["code"] == "HANDOVER_MISMATCH"
    assert any(item["reason"] == "WRONG_BOX" for item in wrong_box.json()["detail"]["mismatched"])

    wrong_seal = live_client.post(
        f"/transfers/{uid}/receipts",
        json={"items": [{**_match_items([product])["items"][0], "seal_id": "WRONG-SEAL"}]},
        headers=dst,
    )
    assert wrong_seal.status_code == 422
    assert any(item["reason"] == "WRONG_SEAL" for item in wrong_seal.json()["detail"]["mismatched"])

    broken = live_client.post(
        f"/transfers/{uid}/receipts",
        json={"items": [{**_match_items([product])["items"][0], "condition": "BROKEN"}]},
        headers=dst,
    )
    assert broken.status_code == 422
    assert any(item["reason"] == "BROKEN_SEAL" for item in broken.json()["detail"]["mismatched"])

    missing_field = live_client.post(
        f"/transfers/{uid}/receipts",
        json={"items": [{"product_uid": product["product_uid"], "seal_id": product["seal_id"], "condition": "INTACT", "mode": "SEALED"}]},
        headers=dst,
    )
    assert missing_field.status_code == 422

    inventory = live_client.get("/inventory", headers=mfr)
    assert product["product_uid"] not in [item["product_uid"] for item in inventory.json()]


def test_missing_extra_duplicate_item(live_client: TestClient) -> None:
    mfr = _mfr(live_client)
    dst = _dst(live_client)
    first = _register(live_client, mfr)
    second = _register(live_client, mfr)
    created = _initiate(live_client, mfr, [first["product_uid"], second["product_uid"]])
    uid = created["transfer_uid"]

    missing = live_client.post(
        f"/transfers/{uid}/receipts",
        json=_match_items([first]),
        headers=dst,
    )
    assert missing.status_code == 422
    assert second["product_uid"] in missing.json()["detail"]["missing"]

    extra = live_client.post(
        f"/transfers/{uid}/receipts",
        json=_match_items([first, second, {**first, "product_uid": str(uuid4())}]),
        headers=dst,
    )
    assert extra.status_code == 422
    assert extra.json()["detail"]["unexpected"]

    duplicate = live_client.post(
        f"/transfers/{uid}/receipts",
        json=_match_items([first, second, first]),
        headers=dst,
    )
    assert duplicate.status_code == 422
    assert any(item["reason"] == "DUPLICATE" for item in duplicate.json()["detail"]["mismatched"])


def test_concurrent_double_accept(live_client: TestClient) -> None:
    mfr = _mfr(live_client)
    dst = _dst(live_client)
    product = _register(live_client, mfr)
    created = _initiate(live_client, mfr, [product["product_uid"]])
    uid = created["transfer_uid"]
    receipts = live_client.post(f"/transfers/{uid}/receipts", json=_match_items([product]), headers=dst)
    assert receipts.status_code == 200, receipts.text
    assert receipts.json()["laptop_internal_serial_check"] == "NOT_CHECKED"
    assert receipts.json()["location_check"] in {"WITHIN_RADIUS", "OUTSIDE_RADIUS", "UNAVAILABLE"}

    live_client.app.state.chain.hold_receipts = True
    from backend.config import get_settings

    settings = get_settings()
    previous = settings.receipt_timeout_seconds
    settings.receipt_timeout_seconds = 0.15
    try:
        first = live_client.post(f"/transfers/{uid}/accept", json={}, headers=dst)
        assert first.status_code == 202, first.text
        assert first.json()["chain_status"] == "SUBMITTED"
        second = live_client.post(f"/transfers/{uid}/accept", json={}, headers=dst)
        assert second.status_code == 409
    finally:
        settings.receipt_timeout_seconds = previous
        live_client.app.state.chain.hold_receipts = False

    from backend.chain.adapter import SignedTx
    from backend.db import connect as db_connect
    from backend.config import get_settings as _settings

    conn = db_connect(_settings().database_path)
    sub = conn.execute(
        "SELECT tx_hash, raw_signed_transaction, sender_address, account_nonce FROM chain_submissions WHERE operation_uid=?",
        (first.json()["operation_uid"],),
    ).fetchone()
    conn.close()
    live_client.app.state.chain.release_receipt(
        SignedTx(
            raw_signed_transaction=sub["raw_signed_transaction"],
            tx_hash=sub["tx_hash"],
            sender_address=sub["sender_address"],
            account_nonce=sub["account_nonce"],
        )
    )
    from backend.chain.reconcile import reconcile_pending

    reconcile_pending(chain=live_client.app.state.chain)
    first_confirmed = live_client.get(first.json()["status_url"], headers=dst)
    assert first_confirmed.json()["status"] == "CONFIRMED"

    inventory = live_client.get("/inventory", headers=dst)
    assert product["product_uid"] in [item["product_uid"] for item in inventory.json()]


def test_accept_after_expiry(live_client: TestClient, monkeypatch) -> None:
    from backend.transfers import service as transfer_service

    clock = {"now": transfer_service._utcnow()}

    def fake_now():
        return clock["now"]

    monkeypatch.setattr(transfer_service, "_utcnow", fake_now)
    mfr = _mfr(live_client)
    dst = _dst(live_client)
    product = _register(live_client, mfr)
    created = _initiate(live_client, mfr, [product["product_uid"]])
    uid = created["transfer_uid"]
    receipts = live_client.post(f"/transfers/{uid}/receipts", json=_match_items([product]), headers=dst)
    assert receipts.status_code == 200, receipts.text
    clock["now"] = clock["now"] + timedelta(hours=25)
    shown = live_client.get(f"/transfers/{uid}", headers=dst)
    assert shown.status_code == 200
    assert shown.json()["expired"] is True
    accept = live_client.post(f"/transfers/{uid}/accept", json={}, headers=dst)
    assert accept.status_code == 409
    assert accept.json()["detail"]["code"] == "TRANSFER_EXPIRED"


def test_cancel_releases_reservations(live_client: TestClient) -> None:
    mfr = _mfr(live_client)
    product = _register(live_client, mfr)
    created = _initiate(live_client, mfr, [product["product_uid"]])
    uid = created["transfer_uid"]
    listed = live_client.get("/transfers", headers=mfr)
    assert listed.status_code == 200
    assert any(item["transfer_uid"] == uid for item in listed.json())

    cancel = live_client.post(f"/transfers/{uid}/cancel", headers=mfr)
    assert cancel.status_code == 202, cancel.text
    assert cancel.json()["chain_status"] == "CONFIRMED"

    inventory = live_client.get("/inventory", headers=mfr)
    assert product["product_uid"] in [item["product_uid"] for item in inventory.json()]
    detail = live_client.get(f"/transfers/{uid}", headers=mfr)
    assert detail.json()["transfer_status"] == "CANCELLED"


def test_handover_mismatch_mails_sender_and_recipient(live_client: TestClient, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("backend.notify.mail.OUTBOX", tmp_path)
    mfr = _mfr(live_client)
    dst = _dst(live_client)
    product = _register(live_client, mfr)
    created = _initiate(live_client, mfr, [product["product_uid"]])
    uid = created["transfer_uid"]
    wrong = live_client.post(
        f"/transfers/{uid}/receipts",
        json={"items": [{**_match_items([product])["items"][0], "box_serial": "WRONG-BOX"}]},
        headers=dst,
    )
    assert wrong.status_code == 422
    files = list(tmp_path.glob("*.txt"))
    assert files
    text = files[-1].read_text(encoding="utf-8")
    assert "manufacturer@tracetrust.demo" in text
    assert "distributor@tracetrust.demo" in text
    assert "transferring party and the receiving party" in text
