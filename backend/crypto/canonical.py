"""Canonical JSON for TraceTrust events (architecture §8)."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping

EVENT_FIELDS = (
    "event_uid",
    "product_uid",
    "operation_uid",
    "event_type",
    "seq",
    "previous_hash",
    "occurred_at",
    "actor_user_id",
    "signer_key_id",
    "organization_uid",
    "payload",
    "schema_version",
)
EVENT_FIELD_SET = frozenset(EVENT_FIELDS)
GPS_FIELDS = (
    "gps_lat_e7",
    "gps_lng_e7",
    "gps_accuracy_cm",
    "gps_status",
    "gps_source",
)
GPS_FIELD_SET = frozenset(GPS_FIELDS)
GPS_STATUSES = frozenset({"CAPTURED", "DENIED", "UNAVAILABLE", "NOT_REQUESTED"})
EXCLUDED_FROM_HASH = frozenset(
    {
        "digital_signature",
        "event_hash",
        "transaction_hash",
        "tx_hash",
        "block_number",
        "block_hash",
        "block_metadata",
        "chain_status",
        "operation_status",
        "status",
    }
)


class CanonicalError(ValueError):
    pass


def _reject_nan(value: Any) -> Any:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise CanonicalError("NaN and Infinity are not allowed")
    return value


def object_pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: set[str] = set()
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise CanonicalError("duplicate keys are not allowed")
        seen.add(key)
        out[key] = _reject_nan(value)
    return out


def parse_canonical_json(text: str | bytes) -> Any:
    if isinstance(text, bytes):
        text = text.decode("utf-8")
    return json.loads(
        text,
        object_pairs_hook=object_pairs_hook,
        parse_constant=lambda _v: (_ for _ in ()).throw(CanonicalError("NaN/Infinity not allowed")),
    )


def _normalize(value: Any, *, path: str) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        raise CanonicalError(f"floating-point values are not allowed at {path}")
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return [_normalize(item, path=f"{path}[{i}]") for i, item in enumerate(value)]
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, nested in value.items():
            if not isinstance(key, str):
                raise CanonicalError(f"non-string key at {path}")
            if key in EXCLUDED_FROM_HASH and path == "$":
                continue
            out[key] = _normalize(nested, path=f"{path}.{key}")
        return out
    raise CanonicalError(f"unsupported type at {path}: {type(value).__name__}")


def _require_int_or_null(value: Any, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise CanonicalError(f"{name} must be an integer or null")
    return value


def normalize_gps(gps: Mapping[str, Any] | None) -> dict[str, Any]:
    if gps is None:
        gps = {}
    extra = set(gps) - GPS_FIELD_SET
    if extra:
        raise CanonicalError(f"unknown gps fields: {sorted(extra)}")
    status = gps.get("gps_status", "NOT_REQUESTED")
    if status not in GPS_STATUSES:
        raise CanonicalError("invalid gps_status")
    source = gps.get("gps_source", "CLIENT_REPORTED")
    if source != "CLIENT_REPORTED":
        raise CanonicalError("gps_source must be CLIENT_REPORTED")
    block = {
        "gps_accuracy_cm": _require_int_or_null(gps.get("gps_accuracy_cm"), "gps_accuracy_cm"),
        "gps_lat_e7": _require_int_or_null(gps.get("gps_lat_e7"), "gps_lat_e7"),
        "gps_lng_e7": _require_int_or_null(gps.get("gps_lng_e7"), "gps_lng_e7"),
        "gps_source": source,
        "gps_status": status,
    }
    return block


def canonical_dumps(value: Any) -> bytes:
    normalized = _normalize(value, path="$")
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def build_canonical_event(event: Mapping[str, Any]) -> dict[str, Any]:
    present = set(event)
    unknown = present - EVENT_FIELD_SET - EXCLUDED_FROM_HASH
    if unknown:
        raise CanonicalError(f"unknown event fields: {sorted(unknown)}")
    missing = EVENT_FIELD_SET - present
    if missing:
        raise CanonicalError(f"missing event fields: {sorted(missing)}")
    payload = event["payload"]
    if not isinstance(payload, Mapping):
        raise CanonicalError("payload must be an object")
    payload_out = dict(payload)
    payload_out["gps"] = normalize_gps(payload.get("gps"))
    seq = event["seq"]
    occurred_at = event["occurred_at"]
    schema_version = event["schema_version"]
    if isinstance(seq, bool) or not isinstance(seq, int) or seq < 0:
        raise CanonicalError("seq must be a non-negative integer")
    if isinstance(occurred_at, bool) or not isinstance(occurred_at, int):
        raise CanonicalError("occurred_at must be integer epoch milliseconds")
    if schema_version != 1:
        raise CanonicalError("schema_version must be 1")
    built = {
        "actor_user_id": event["actor_user_id"],
        "event_type": event["event_type"],
        "event_uid": event["event_uid"],
        "occurred_at": occurred_at,
        "operation_uid": event["operation_uid"],
        "organization_uid": event["organization_uid"],
        "payload": payload_out,
        "previous_hash": event["previous_hash"],
        "product_uid": event["product_uid"],
        "schema_version": 1,
        "seq": seq,
        "signer_key_id": event["signer_key_id"],
    }
    return json.loads(canonical_dumps(built).decode("utf-8"))


def event_hash(event: Mapping[str, Any]) -> str:
    canonical = build_canonical_event(event)
    return hashlib.sha256(canonical_dumps(canonical)).hexdigest()
