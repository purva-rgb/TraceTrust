"""Fixed inputs for the simulator and the evaluation tests."""
from __future__ import annotations

MUMBAI = (19.0760, 72.8777)
LONDON = (51.5074, -0.1278)
NEW_YORK = (40.7128, -74.0060)
PUNE = (18.5204, 73.8567)

_DEVICES = (
    ("dev-mumbai", MUMBAI),
    ("dev-london", LONDON),
    ("dev-newyork", NEW_YORK),
)


def scan(
    evidence_id: str,
    *,
    product_uid: str = "prod-eval",
    lat: float | None = None,
    lng: float | None = None,
    event_time_ms: int = 0,
    device_id: str | None = None,
    device_registered: bool = False,
    signature_valid: bool | None = None,
    authenticated: bool = False,
    inspection_method: str | None = None,
    gps_status: str = "CAPTURED",
    accuracy_km: float | None = 0.02,
    client_trust: float | None = None,
    is_simulated: bool = True,
    scanner_org_id: int | None = None,
    custodian_org_id: int | None = None,
    expected_recipient_org_id: int | None = None,
    lifecycle_state: str = "IN_SUPPLY_CHAIN",
) -> dict:
    return {
        "evidence_id": evidence_id,
        "product_uid": product_uid,
        "lat": lat,
        "lng": lng,
        "event_time_ms": event_time_ms,
        "device_id": device_id,
        "device_registered": device_registered,
        "signature_valid": signature_valid,
        "authenticated": authenticated,
        "inspection_method": inspection_method,
        "gps_status": gps_status,
        "accuracy_km": accuracy_km,
        "client_trust": client_trust,
        "is_simulated": is_simulated,
        "scanner_org_id": scanner_org_id,
        "custodian_org_id": custodian_org_id,
        "expected_recipient_org_id": expected_recipient_org_id,
        "lifecycle_state": lifecycle_state,
    }


def registered_clone(count: int = 3, *, product_uid: str = "prod-eval", client_trust: float | None = None) -> list[dict]:
    scans = []
    for index in range(count):
        device_id, (lat, lng) = _DEVICES[index]
        scans.append(
            scan(
                f"scan-{device_id}",
                product_uid=product_uid,
                lat=lat,
                lng=lng,
                event_time_ms=index * 1000,
                device_id=device_id,
                device_registered=True,
                signature_valid=True,
                client_trust=client_trust,
            )
        )
    return scans


def anonymous_clone(*, product_uid: str = "prod-eval", client_trust: float | None = 0.99) -> list[dict]:
    scans = []
    for index, (_device_id, (lat, lng)) in enumerate(_DEVICES):
        scans.append(
            scan(
                f"anon-{index}",
                product_uid=product_uid,
                lat=lat,
                lng=lng,
                event_time_ms=index * 3 * 60 * 1000,
                device_registered=False,
                signature_valid=None,
                client_trust=client_trust,
            )
        )
    return scans


def staff_inspection(
    *,
    product_uid: str = "prod-eval",
    box_ok: bool = False,
    seal_ok: bool = False,
    broken: bool = False,
    serial: str = "NOT_CHECKED",
    opening_authorized: bool = False,
    evidence_id: str = "insp-staff",
) -> dict:
    return {
        "evidence_id": evidence_id,
        "product_uid": product_uid,
        "event_time_ms": 0,
        "authenticated": True,
        "inspection_method": "SEALED",
        "device_registered": False,
        "signature_valid": None,
        "observed_box": "BOX-OK" if box_ok else "BOX-WRONG",
        "expected_box": "BOX-OK",
        "observed_seal": "SEAL-OK" if seal_ok else "SEAL-WRONG",
        "expected_seal": "SEAL-OK",
        "seal_condition": "BROKEN" if broken else "INTACT",
        "opening_authorized": opening_authorized,
        "laptop_serial_result": serial,
        "is_simulated": True,
        "client_trust": 1,
    }


def documentation_gap_record(
    *,
    product_uid: str = "prod-eval",
    org_id: int = 1,
    evidence_id: str = "gap-1",
    event_time_ms: int = 0,
    shipment_ref: str | None = None,
    quantity: int | None = None,
    signature: str | None = None,
    is_simulated: bool = True,
) -> dict:
    return {
        "kind": "documentation_gap",
        "product_uid": product_uid,
        "org_id": org_id,
        "evidence_id": evidence_id,
        "event_time_ms": event_time_ms,
        "shipment_ref": shipment_ref,
        "shipment_uid": shipment_ref,
        "quantity": quantity,
        "signature": signature,
        "is_simulated": is_simulated,
        "client_trust": 0.99,
        "independent": True,
    }


def interrupted_operation_record(
    *,
    product_uid: str = "prod-eval",
    evidence_id: str = "op-pending",
    event_time_ms: int = 0,
    operation_status: str = "PENDING",
    is_simulated: bool = True,
) -> dict:
    return {
        "kind": "interrupted_operation",
        "product_uid": product_uid,
        "evidence_id": evidence_id,
        "event_time_ms": event_time_ms,
        "operation_status": operation_status,
        "is_simulated": is_simulated,
    }


def corroboration_record(
    *,
    product_uid: str = "prod-eval",
    org_id: int = 2,
    evidence_id: str = "cor-1",
    event_time_ms: int = 0,
    role: str | None = None,
    shipment_ref: str | None = None,
    quantity: int | None = None,
    signature: str | None = None,
    independent: bool = True,
    client_trust: float | None = 1.0,
    is_simulated: bool = True,
) -> dict:
    return {
        "kind": "corroboration",
        "product_uid": product_uid,
        "org_id": org_id,
        "evidence_id": evidence_id,
        "event_time_ms": event_time_ms,
        "role": role,
        "shipment_ref": shipment_ref,
        "shipment_uid": shipment_ref,
        "quantity": quantity,
        "signature": signature,
        "independent": independent,
        "client_trust": client_trust,
        "is_simulated": is_simulated,
    }


def interrupted_dispatch(
    *,
    interrupted: bool = True,
    other_org: bool = True,
    consistent: bool = False,
    extra_same_org: bool = False,
    product_uid: str = "prod-eval",
) -> list[dict]:
    shipment = "ship-eval" if consistent else None
    quantity = 1 if consistent else None
    signature = "0xdispatch" if consistent else None
    records = [
        documentation_gap_record(
            product_uid=product_uid,
            shipment_ref=shipment,
            quantity=quantity,
            signature=signature,
        )
    ]
    if interrupted:
        records.append(interrupted_operation_record(product_uid=product_uid))
    if other_org:
        records.append(
            corroboration_record(
                product_uid=product_uid,
                org_id=2,
                shipment_ref=shipment,
                quantity=quantity,
                signature=signature,
            )
        )
    if extra_same_org:
        records.append(
            corroboration_record(
                product_uid=product_uid,
                org_id=1,
                evidence_id="cor-same-org",
                independent=True,
                client_trust=1,
                shipment_ref=shipment,
                quantity=quantity,
                signature=signature,
            )
        )
    return records
