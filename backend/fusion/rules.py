"""Deterministic rule alerts. Scores are applied later and do not live here."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from backend.fusion.config import (
    BURST_MIN_DEVICES,
    BURST_WINDOW_MS,
    MIN_DISTANCE_KM,
    RECEIPT_CONFLICT_WINDOW_MS,
    RULE_VERSION,
    SPEED_KMH,
    TRUST,
)

CONSISTENCY_FIELDS = ("product_uid", "shipment_ref", "quantity", "event_time_ms", "signature")
CARRIER_ROLES = frozenset({"CARRIER", "LOGISTICS"})
from backend.fusion.trust import derive_trust
from backend.geo import haversine_km


def dedupe_key(rule_code: str, product_uid: str, evidence_ids: list[str]) -> str:
    raw = f"{RULE_VERSION}|{rule_code}|{product_uid}|{','.join(evidence_ids)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def make_alert(
    *,
    rule_code: str,
    evidence_class: str,
    product_uid: str,
    evidence_ids: list[str],
    trust: float,
    reason: str,
    is_simulated: bool,
    event_time_ms: int,
    shipment_uid: str | None = None,
    strength: float = 1.0,
) -> dict:
    ids = sorted(str(item) for item in evidence_ids)
    key = dedupe_key(rule_code, product_uid, ids)
    return {
        "id": key,
        "rule_code": rule_code,
        "evidence_class": evidence_class,
        "product_uid": product_uid,
        "evidence_ids": ids,
        "trust": round(float(trust), 10),
        "strength": 1.0 if strength else 0.0,
        "rule_version": RULE_VERSION,
        "reason": reason,
        "is_simulated": 1 if is_simulated else 0,
        "event_time_ms": int(event_time_ms),
        "dedupe_key": key,
        "shipment_uid": shipment_uid,
    }


@dataclass
class Evaluation:
    alerts: list[dict] = field(default_factory=list)
    missing_checks: list[str] = field(default_factory=list)
    authorized_opening: bool = False


def _simulated(items: list[dict]) -> bool:
    return any(bool(item.get("is_simulated")) for item in items)


def _trust_of(item: dict) -> dict:
    return derive_trust(
        authenticated=bool(item.get("authenticated")),
        device_registered=bool(item.get("device_registered")),
        signature_valid=item.get("signature_valid"),
        inspection_method=item.get("inspection_method"),
        accuracy_km=item.get("accuracy_km"),
        client_trust=item.get("client_trust"),
    )


def _gps_captured(item: dict) -> bool:
    return item.get("gps_status") == "CAPTURED" and item.get("lat") is not None and item.get("lng") is not None


def _movement(scans: list[dict], missing: set[str]) -> list[dict]:
    alerts = []
    usable = []
    for scan in scans:
        trust = _trust_of(scan)
        scan = {**scan, "_trust": trust}
        if scan.get("gps_status") != "CAPTURED":
            missing.add("gps")
            continue
        if trust["exclude_location"] or not _gps_captured(scan):
            continue
        usable.append(scan)
    usable.sort(key=lambda item: (int(item["event_time_ms"]), str(item["evidence_id"])))
    for index, left in enumerate(usable):
        for right in usable[index + 1 :]:
            distance = haversine_km(float(left["lat"]), float(left["lng"]), float(right["lat"]), float(right["lng"]))
            if distance <= MIN_DISTANCE_KM:
                continue
            elapsed_ms = abs(int(right["event_time_ms"]) - int(left["event_time_ms"]))
            elapsed_h = elapsed_ms / 3_600_000
            speed = float("inf") if elapsed_h == 0 else distance / elapsed_h
            if speed <= SPEED_KMH:
                continue
            trust = min(left["_trust"]["location_trust"], right["_trust"]["location_trust"])
            alerts.append(
                make_alert(
                    rule_code="IMPOSSIBLE_TRAVEL",
                    evidence_class="movement_conflict",
                    product_uid=left["product_uid"],
                    evidence_ids=[left["evidence_id"], right["evidence_id"]],
                    trust=trust,
                    reason=f"{distance:.0f} km between observations exceeds {SPEED_KMH:.0f} km/h",
                    is_simulated=_simulated([left, right]),
                    event_time_ms=max(int(left["event_time_ms"]), int(right["event_time_ms"])),
                )
            )
    return alerts


def _burst(scans: list[dict]) -> list[dict]:
    registered = []
    for scan in scans:
        if not scan.get("device_registered") or scan.get("signature_valid") is False or not scan.get("device_id"):
            continue
        registered.append({**scan, "_trust": _trust_of(scan)})
    registered.sort(key=lambda item: (int(item["event_time_ms"]), str(item["device_id"]), str(item["evidence_id"])))
    for start, origin in enumerate(registered):
        chosen: dict[str, dict] = {}
        for candidate in registered[start:]:
            if int(candidate["event_time_ms"]) - int(origin["event_time_ms"]) > BURST_WINDOW_MS:
                break
            chosen.setdefault(str(candidate["device_id"]), candidate)
        if len(chosen) < BURST_MIN_DEVICES:
            continue
        members = [chosen[key] for key in sorted(chosen)]
        trust = min(item["_trust"]["identity_trust"] for item in members)
        return [
            make_alert(
                rule_code="DUPLICATE_BURST",
                evidence_class="duplicate_burst",
                product_uid=origin["product_uid"],
                evidence_ids=[item["evidence_id"] for item in members],
                trust=trust,
                reason=f"{len(members)} distinct registered devices scanned this product within 5 seconds",
                is_simulated=_simulated(members),
                event_time_ms=max(int(item["event_time_ms"]) for item in members),
            )
        ]
    return []


def _concurrent(transfers: list[dict]) -> list[dict]:
    rows = []
    for item in transfers:
        if item.get("kind") != "concurrent_receipt":
            continue
        rows.append({**item, "_trust": _trust_of(item)})
    rows.sort(key=lambda item: (int(item["event_time_ms"]), str(item["evidence_id"])))
    for index, left in enumerate(rows):
        for right in rows[index + 1 :]:
            if abs(int(left["event_time_ms"]) - int(right["event_time_ms"])) > RECEIPT_CONFLICT_WINDOW_MS:
                continue
            if left.get("org_id") is None or left.get("org_id") == right.get("org_id"):
                continue
            if left.get("receipt_fingerprint") == right.get("receipt_fingerprint"):
                continue
            trust = min(left["_trust"]["inspection_trust"], right["_trust"]["inspection_trust"])
            return [
                make_alert(
                    rule_code="CONCURRENT_RECEIPT_CONFLICT",
                    evidence_class="concurrent_receipt",
                    product_uid=left["product_uid"],
                    evidence_ids=[left["evidence_id"], right["evidence_id"]],
                    trust=trust,
                    reason="Two receipts for this product disagree within 10 minutes",
                    is_simulated=_simulated([left, right]),
                    event_time_ms=max(int(left["event_time_ms"]), int(right["event_time_ms"])),
                    shipment_uid=left.get("shipment_uid") or right.get("shipment_uid"),
                )
            ]
    return []


def _identity(inspections: list[dict], *, authorized_opening: bool, missing: set[str]) -> list[dict]:
    alerts = []
    for item in inspections:
        trust = _trust_of(item)["inspection_trust"]
        product_uid = item["product_uid"]
        simulated = bool(item.get("is_simulated"))
        when = int(item.get("event_time_ms") or 0)
        shipment = item.get("shipment_uid")
        if item.get("observed_box") is not None and item.get("expected_box") is not None:
            if item["observed_box"] != item["expected_box"]:
                alerts.append(
                    make_alert(
                        rule_code="BOX_MISMATCH",
                        evidence_class="box_mismatch",
                        product_uid=product_uid,
                        evidence_ids=[item["evidence_id"]],
                        trust=trust,
                        reason="Observed box serial does not match the registered package",
                        is_simulated=simulated,
                        event_time_ms=when,
                        shipment_uid=shipment,
                    )
                )
        if item.get("observed_seal") is not None and item.get("expected_seal") is not None:
            if item["observed_seal"] != item["expected_seal"]:
                alerts.append(
                    make_alert(
                        rule_code="SEAL_ID_MISMATCH",
                        evidence_class="seal_id_mismatch",
                        product_uid=product_uid,
                        evidence_ids=[item["evidence_id"]],
                        trust=trust,
                        reason="Observed seal ID does not match the registered seal",
                        is_simulated=simulated,
                        event_time_ms=when,
                        shipment_uid=shipment,
                    )
                )
        serial = item.get("laptop_serial_result") or "NOT_CHECKED"
        if serial == "NOT_CHECKED":
            missing.add("laptop_serial")
        elif serial == "UNAVAILABLE":
            missing.add("laptop_serial")
        elif serial == "MISMATCH":
            alerts.append(
                make_alert(
                    rule_code="SERIAL_MISMATCH",
                    evidence_class="laptop_serial",
                    product_uid=product_uid,
                    evidence_ids=[item["evidence_id"]],
                    trust=trust,
                    reason="Observed laptop serial does not match the registered serial",
                    is_simulated=simulated,
                    event_time_ms=when,
                    shipment_uid=shipment,
                )
            )
        condition = item.get("seal_condition")
        if condition in {"BROKEN", "MISSING"} and not authorized_opening and not item.get("opening_authorized"):
            alerts.append(
                make_alert(
                    rule_code="UNEXPECTED_SEAL_BROKEN",
                    evidence_class="unexpected_seal_broken",
                    product_uid=product_uid,
                    evidence_ids=[item["evidence_id"]],
                    trust=trust,
                    reason="Seal is broken or missing without an authorized opening",
                    is_simulated=simulated,
                    event_time_ms=when,
                    shipment_uid=shipment,
                )
            )
    return alerts


def _custody(scans: list[dict]) -> list[dict]:
    alerts = []
    for scan in scans:
        scanner = scan.get("scanner_org_id")
        custodian = scan.get("custodian_org_id")
        if scanner is None or custodian is None or scanner == custodian:
            continue
        if scan.get("expected_recipient_org_id") is not None and scanner == scan.get("expected_recipient_org_id"):
            continue
        trust = _trust_of(scan)["identity_trust"]
        alerts.append(
            make_alert(
                rule_code="CUSTODY_MISMATCH",
                evidence_class="custody_mismatch",
                product_uid=scan["product_uid"],
                evidence_ids=[scan["evidence_id"]],
                trust=trust,
                reason="Scanner organization is not the custodian at event time and is not the named recipient",
                is_simulated=bool(scan.get("is_simulated")),
                event_time_ms=int(scan.get("event_time_ms") or 0),
                shipment_uid=scan.get("shipment_uid"),
            )
        )
    return alerts


def _transfer_flags(transfers: list[dict]) -> list[dict]:
    alerts = []
    mapping = {
        "handover_mismatch": ("HANDOVER_MISMATCH", "handover_mismatch", "Receipt does not match the signed manifest"),
        "prohibited_route": (
            "PROHIBITED_ROUTE",
            "prohibited_route_or_sold_reentry",
            "Transfer attempt used an edge outside manufacturer to distributor to retailer",
        ),
        "sold_reentry": (
            "SOLD_REENTRY",
            "prohibited_route_or_sold_reentry",
            "A sold product was submitted for another supply-chain transfer",
        ),
    }
    for item in transfers:
        spec = mapping.get(item.get("kind"))
        if spec is None:
            continue
        rule_code, evidence_class, reason = spec
        trust = _trust_of(item)["identity_trust"]
        alerts.append(
            make_alert(
                rule_code=rule_code,
                evidence_class=evidence_class,
                product_uid=item["product_uid"],
                evidence_ids=[item["evidence_id"]],
                trust=trust,
                reason=reason,
                is_simulated=bool(item.get("is_simulated")),
                event_time_ms=int(item.get("event_time_ms") or 0),
                shipment_uid=item.get("shipment_uid"),
            )
        )
    return alerts


def _documenting_org(records: list[dict]) -> int | None:
    for item in records:
        if item.get("kind") == "documentation_gap" and item.get("org_id") is not None:
            return item["org_id"]
    return None


def _collapse_orgs(records: list[dict]) -> list[dict]:
    collapsed: dict[object, dict] = {}
    leftovers = []
    for item in sorted(records, key=lambda row: str(row.get("evidence_id") or "")):
        org = item.get("org_id")
        if org is None:
            leftovers.append(item)
            continue
        collapsed.setdefault(org, item)
    return leftovers + [collapsed[key] for key in sorted(collapsed, key=str)]


def _is_independent(item: dict, documenting_org: int | None) -> bool:
    item.pop("independent", None)
    item.pop("client_trust", None)
    if item.get("role") in CARRIER_ROLES:
        return True
    org = item.get("org_id")
    return org is not None and documenting_org is not None and org != documenting_org


def _consistency_payload(item: dict) -> dict:
    shipment = item.get("shipment_ref") or item.get("shipment_uid")
    return {
        "product_uid": item.get("product_uid"),
        "shipment_ref": shipment,
        "quantity": item.get("quantity"),
        "event_time_ms": item.get("event_time_ms"),
        "signature": item.get("signature"),
    }


def _documentation(records: list[dict], missing: set[str]) -> list[dict]:
    alerts = []
    records = list(records or [])
    product_uids = sorted({item["product_uid"] for item in records if item.get("product_uid")})
    for product_uid in product_uids:
        group = [item for item in records if item.get("product_uid") == product_uid]
        gaps = [item for item in group if item.get("kind") == "documentation_gap"]
        if not gaps:
            continue
        gap = sorted(gaps, key=lambda item: str(item.get("evidence_id") or ""))[0]
        simulated = _simulated(group)
        when = max(int(item.get("event_time_ms") or 0) for item in group)
        shipment = gap.get("shipment_uid") or gap.get("shipment_ref")
        alerts.append(
            make_alert(
                rule_code="CUSTODY_DOCUMENTATION_GAP",
                evidence_class="documentation_gap",
                product_uid=product_uid,
                evidence_ids=[gap["evidence_id"]],
                trust=0.0,
                reason="Receipt or accept is recorded but the confirmed handover is missing",
                is_simulated=simulated,
                event_time_ms=when,
                shipment_uid=shipment,
                strength=0.0,
            )
        )
        interrupted = [
            item
            for item in group
            if item.get("kind") in {"interrupted_operation", "operation", "chain_submission"}
            or str(item.get("operation_status") or "").upper() in {"PENDING", "SUBMITTED"}
        ]
        if interrupted:
            chosen = sorted(interrupted, key=lambda item: str(item.get("evidence_id") or ""))[0]
            alerts.append(
                make_alert(
                    rule_code="INTERRUPTED_OPERATION",
                    evidence_class="interrupted_operation",
                    product_uid=product_uid,
                    evidence_ids=[chosen["evidence_id"]],
                    trust=TRUST["INTERRUPTED_OPERATION"],
                    reason="A PENDING or SUBMITTED operation or chain submission exists for this handover",
                    is_simulated=_simulated([gap, chosen]),
                    event_time_ms=int(chosen.get("event_time_ms") or when),
                    shipment_uid=shipment,
                )
            )
        documenting_org = _documenting_org(group)
        corroborations = [
            item
            for item in group
            if item.get("kind") == "corroboration"
        ]
        independent = [item for item in _collapse_orgs(corroborations) if _is_independent(item, documenting_org)]
        if independent:
            chosen = independent[0]
            alerts.append(
                make_alert(
                    rule_code="INDEPENDENT_CORROBORATION",
                    evidence_class="independent_corroboration",
                    product_uid=product_uid,
                    evidence_ids=[chosen["evidence_id"]],
                    trust=TRUST["INDEPENDENT_CORROBORATION"],
                    reason="A matching record from a different organization or carrier corroborates the incomplete handover",
                    is_simulated=_simulated([gap, chosen]),
                    event_time_ms=int(chosen.get("event_time_ms") or when),
                    shipment_uid=shipment,
                )
            )
            baseline = _consistency_payload(gap)
            other = _consistency_payload(chosen)
            missing_fields = [
                field for field in CONSISTENCY_FIELDS if baseline.get(field) in {None, ""} or other.get(field) in {None, ""}
            ]
            if missing_fields:
                missing.update(missing_fields)
            elif baseline == other:
                alerts.append(
                    make_alert(
                        rule_code="CONSISTENCY_CHECK",
                        evidence_class="consistency_check",
                        product_uid=product_uid,
                        evidence_ids=[gap["evidence_id"], chosen["evidence_id"]],
                        trust=TRUST["CONSISTENCY_CHECK"],
                        reason="Backend consistency check matched product IDs, shipment reference, quantity, dates and signatures",
                        is_simulated=_simulated([gap, chosen]),
                        event_time_ms=when,
                        shipment_uid=shipment,
                    )
                )
        elif corroborations:
            missing.add("independent_corroboration")
    return alerts


def _digital(items: list[dict], missing: set[str]) -> list[dict]:
    alerts = []
    rules = {
        "signature": ("SIGNATURE_INVALID", "event_integrity", "Event signature does not match the registered key"),
        "hash": ("HASH_INVALID", "event_integrity", "Event hash does not match its canonical payload"),
        "sequence": ("SEQUENCE_INVALID", "event_integrity", "Event sequence or previous hash is broken"),
    }
    for item in items:
        kind = item.get("kind")
        if kind in {"unverifiable", "chain_down", "reset"}:
            missing.add("chain")
            continue
        if kind == "anchor":
            if not item.get("confirmed"):
                missing.add("chain")
                continue
            alerts.append(
                make_alert(
                    rule_code="ANCHOR_MISMATCH",
                    evidence_class="anchor_mismatch",
                    product_uid=item["product_uid"],
                    evidence_ids=[item["evidence_id"]],
                    trust=TRUST["CRYPTO_FAILURE"],
                    reason="Confirmed chain commitment does not match the local event",
                    is_simulated=bool(item.get("is_simulated")),
                    event_time_ms=int(item.get("event_time_ms") or 0),
                )
            )
            continue
        spec = rules.get(kind)
        if spec is None:
            continue
        rule_code, evidence_class, reason = spec
        alerts.append(
            make_alert(
                rule_code=rule_code,
                evidence_class=evidence_class,
                product_uid=item["product_uid"],
                evidence_ids=[item["evidence_id"]],
                trust=TRUST["CRYPTO_FAILURE"],
                reason=reason,
                is_simulated=bool(item.get("is_simulated")),
                event_time_ms=int(item.get("event_time_ms") or 0),
            )
        )
    return alerts


def evaluate(
    *,
    scans: list[dict] | None = None,
    inspections: list[dict] | None = None,
    transfers: list[dict] | None = None,
    digital: list[dict] | None = None,
    records: list[dict] | None = None,
) -> Evaluation:
    scans = list(scans or [])
    inspections = list(inspections or [])
    transfers = list(transfers or [])
    digital = list(digital or [])
    records = list(records or [])
    authorized = any(bool(item.get("opening_authorized")) for item in inspections)
    missing: set[str] = set()
    alerts: list[dict] = []
    product_uids = {
        item["product_uid"]
        for item in [*scans, *inspections, *transfers, *digital, *records]
        if item.get("product_uid")
    }
    for product_uid in sorted(product_uids):
        product_scans = [item for item in scans if item.get("product_uid") == product_uid]
        product_inspections = [item for item in inspections if item.get("product_uid") == product_uid]
        product_transfers = [item for item in transfers if item.get("product_uid") == product_uid]
        product_digital = [item for item in digital if item.get("product_uid") == product_uid]
        product_records = [item for item in records if item.get("product_uid") == product_uid]
        product_authorized = authorized and any(item.get("product_uid") == product_uid and item.get("opening_authorized") for item in inspections)
        alerts.extend(_movement(product_scans, missing))
        alerts.extend(_burst(product_scans))
        alerts.extend(_concurrent(product_transfers))
        alerts.extend(_identity(product_inspections, authorized_opening=product_authorized, missing=missing))
        alerts.extend(_custody(product_scans))
        alerts.extend(_transfer_flags(product_transfers))
        alerts.extend(_digital(product_digital, missing))
        alerts.extend(_documentation(product_records, missing))
    alerts.sort(key=lambda item: (item["evidence_class"], item["rule_code"], item["dedupe_key"], item["event_time_ms"]))
    return Evaluation(
        alerts=alerts,
        missing_checks=sorted(missing),
        authorized_opening=authorized,
    )
