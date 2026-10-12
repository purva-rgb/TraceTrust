from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.scripts.tamper_demo import delete_last_event, rewrite_hashes, tamper_coordinate, tamper_payload
from backend.verify.engine import verify_product
from backend.verify.rate_limit import public_verify_limiter
from tests.test_products import _body, _mfr


def _register(client: TestClient) -> dict:
    auth = _mfr(client)
    body = _body()
    response = client.post(
        "/products",
        json=body,
        headers={**auth, "Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 202, response.text
    assert response.json()["chain_status"] == "CONFIRMED"
    return {
        "auth": auth,
        "product_uid": response.json()["product_uid"],
        "qr_payload": response.json()["qr_payload"],
        "serial_number": body["serial_number"],
    }


def test_public_verify_unknown_token(live_client: TestClient) -> None:
    public_verify_limiter.reset()
    response = live_client.post("/public/verify", json={"token": "deadbeefdeadbeefdeadbeefdeadbeef"})
    assert response.status_code == 200
    body = response.json()
    assert body["final_status"] == "UNKNOWN"
    assert body["headline"] == "Unknown product"
    assert "genuine" not in str(body).lower()
    assert body["physical_checks"]["laptop_serial"] == "NOT_CHECKED"


def test_public_verify_clean_record(live_client: TestClient) -> None:
    public_verify_limiter.reset()
    created = _register(live_client)
    response = live_client.post("/public/verify", json={"qr_payload": created["qr_payload"]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["headline"] == "Digital record verified"
    assert "genuine" not in str(body).lower()
    assert body["record_integrity"]["status"] == "VERIFIED"
    assert body["record_integrity"]["failing_layer"] is None
    assert body["final_status"] == "VALID"
    assert body["serial_number_masked"].endswith(created["serial_number"][-4:])
    assert "serial_number" not in body or body.get("serial_number") is None
    assert body["physical_checks"]["box_id"] == "MATCH"
    assert body["physical_checks"]["seal_id"] == "MATCH"
    assert body["physical_checks"]["seal_condition"] == "INTACT"
    assert body["physical_checks"]["laptop_serial"] == "NOT_CHECKED"
    assert body["physical_checks"]["box_serial"]
    assert body["physical_checks"]["seal_serial"]
    assert body["events"]
    assert "gps_status" in body["events"][0]


def test_provenance_public_reduced_staff_full(live_client: TestClient) -> None:
    created = _register(live_client)
    public = live_client.get(f"/products/{created['product_uid']}/provenance")
    assert public.status_code == 200
    reduced = public.json()
    assert "digital_signature" not in str(reduced)
    assert reduced["headline"] == "Digital record verified"
    assert reduced["events"][0]["gps_status"]

    staff = live_client.get(
        f"/products/{created['product_uid']}/provenance",
        headers=created["auth"],
    )
    assert staff.status_code == 200
    full = staff.json()
    assert full["serial_number"] == created["serial_number"]
    assert full["events"][0]["digital_signature"].startswith("0x")
    assert full["events"][0]["event_hash"]
    assert full["events"][0]["gps"]["gps_status"]


def test_tamper_payload_fails_hash(live_client: TestClient, db_path) -> None:
    created = _register(live_client)
    tamper_payload(db_path, created["product_uid"])
    result = verify_product(created["product_uid"], live_client.app.state.chain, db_path=db_path)
    assert result["record_integrity"]["status"] == "FAILED"
    assert result["record_integrity"]["failing_layer"] == "hash"
    assert result["final_status"] == "INVALID"


def test_tamper_coordinate_fails_hash(live_client: TestClient, db_path) -> None:
    created = _register(live_client)
    tamper_coordinate(db_path, created["product_uid"])
    result = verify_product(created["product_uid"], live_client.app.state.chain, db_path=db_path)
    assert result["record_integrity"]["status"] == "FAILED"
    assert result["record_integrity"]["failing_layer"] == "hash"


def test_delete_last_event_fails_sequence(live_client: TestClient, db_path) -> None:
    created = _register(live_client)
    delete_last_event(db_path, created["product_uid"])
    result = verify_product(created["product_uid"], live_client.app.state.chain, db_path=db_path)
    assert result["record_integrity"]["status"] == "FAILED"
    assert result["record_integrity"]["failing_layer"] == "sequence"


def test_consistent_hash_rewrite_fails_anchor(live_client: TestClient, db_path, monkeypatch) -> None:
    created = _register(live_client)
    private_key = get_settings().org_private_key_manufacturer
    assert private_key
    rewrite_hashes(db_path, created["product_uid"], private_key)
    result = verify_product(created["product_uid"], live_client.app.state.chain, db_path=db_path)
    assert result["record_integrity"]["status"] == "FAILED"
    assert result["record_integrity"]["failing_layer"] == "anchor"
    assert result["final_status"] == "INVALID"


def test_verify_gps_mismatch_flags_suspicious(live_client: TestClient, monkeypatch, tmp_path) -> None:
    public_verify_limiter.reset()
    monkeypatch.setattr("backend.notify.mail.OUTBOX", tmp_path)
    created = _register(live_client)
    skipped = live_client.post("/public/verify", json={"qr_payload": created["qr_payload"]})
    assert skipped.status_code == 200, skipped.text
    assert skipped.json()["restriction_flags"]["location_mismatch"] is False
    assert skipped.json()["final_status"] == "VALID"

    far = live_client.post(
        "/public/verify",
        json={
            "qr_payload": created["qr_payload"],
            "gps": {"gps_status": "CAPTURED", "latitude": 28.6139, "longitude": 77.2090},
        },
    )
    assert far.status_code == 200, far.text
    body = far.json()
    assert body["restriction_flags"]["location_mismatch"] is True
    assert body["final_status"] == "SUSPICIOUS"
    assert body["headline"] == "Digital record verified"
    assert body["record_integrity"]["status"] == "VERIFIED"
    assert list(tmp_path.glob("*.txt"))
    assert body["mail_alert"]["queued"] is True
    assert body["mail_alert"]["to"]

    near = live_client.post(
        "/public/verify",
        json={
            "qr_payload": created["qr_payload"],
            "gps": {"gps_status": "CAPTURED", "latitude": 18.5204, "longitude": 73.8567},
        },
    )
    assert near.json()["restriction_flags"]["location_mismatch"] is False
    assert near.json()["final_status"] == "VALID"


def test_public_verify_rate_limit(live_client: TestClient, monkeypatch) -> None:
    public_verify_limiter.reset()
    public_verify_limiter.limit = 2
    try:
        live_client.post("/public/verify", json={"token": "aa"})
        live_client.post("/public/verify", json={"token": "bb"})
        third = live_client.post("/public/verify", json={"token": "cc"})
        assert third.status_code == 429
    finally:
        public_verify_limiter.limit = 30
        public_verify_limiter.reset()
