from __future__ import annotations

import copy

from eth_account import Account

from backend.crypto.canonical import canonical_dumps, event_hash
from backend.crypto.events import ZERO_PREVIOUS_HASH, build_canonical_event
from backend.crypto.keys import sign_event_hash, verify_event_signature


def _event(lat: int | None = 183520000) -> dict:
    return {
        "actor_user_id": 2,
        "event_type": "PRODUCT_REGISTERED",
        "event_uid": "11111111-1111-1111-1111-111111111111",
        "occurred_at": 1760284800000,
        "operation_uid": "22222222-2222-2222-2222-222222222222",
        "organization_uid": "5a628292-129d-54d0-b4ab-a678a1643172",
        "payload": {
            "box_serial": "BOX-1",
            "gps": {
                "gps_accuracy_cm": 150,
                "gps_lat_e7": lat,
                "gps_lng_e7": 738560000,
                "gps_source": "CLIENT_REPORTED",
                "gps_status": "CAPTURED",
            },
            "seal_id": "SEAL-1",
        },
        "previous_hash": ZERO_PREVIOUS_HASH,
        "product_uid": "48436666-3470-576c-8bd5-eee5adfd2b08",
        "schema_version": 1,
        "seq": 0,
        "signer_key_id": "mfr-key-1",
    }


def test_canonical_determinism() -> None:
    shuffled = {
        "schema_version": 1,
        "seq": 0,
        "signer_key_id": "mfr-key-1",
        "product_uid": "48436666-3470-576c-8bd5-eee5adfd2b08",
        "previous_hash": ZERO_PREVIOUS_HASH,
        "payload": {
            "seal_id": "SEAL-1",
            "gps": {
                "gps_status": "CAPTURED",
                "gps_lng_e7": 738560000,
                "gps_source": "CLIENT_REPORTED",
                "gps_lat_e7": 183520000,
                "gps_accuracy_cm": 150,
            },
            "box_serial": "BOX-1",
        },
        "organization_uid": "5a628292-129d-54d0-b4ab-a678a1643172",
        "operation_uid": "22222222-2222-2222-2222-222222222222",
        "occurred_at": 1760284800000,
        "event_uid": "11111111-1111-1111-1111-111111111111",
        "event_type": "PRODUCT_REGISTERED",
        "actor_user_id": 2,
    }
    first = canonical_dumps(build_canonical_event(_event()))
    second = canonical_dumps(build_canonical_event(shuffled))
    third = canonical_dumps(build_canonical_event(copy.deepcopy(_event())))
    assert first == second == third
    assert b" " not in first
    assert first.decode("utf-8").startswith("{")
    assert event_hash(_event()) == event_hash(shuffled)


def test_changing_latitude_breaks_hash_and_signature() -> None:
    key = Account.create()
    original = _event(183520000)
    tampered = _event(183520001)
    original_hash = event_hash(original)
    tampered_hash = event_hash(tampered)
    assert original_hash != tampered_hash
    signature = sign_event_hash(original_hash, key.key.hex())
    assert verify_event_signature(original_hash, signature, key.address)
    assert not verify_event_signature(tampered_hash, signature, key.address)
    assert ZERO_PREVIOUS_HASH == "0" * 64
    assert len(ZERO_PREVIOUS_HASH) == 64
