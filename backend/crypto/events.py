from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4

from backend.crypto.canonical import (
    CanonicalError,
    build_canonical_event,
    canonical_dumps,
    event_hash,
    normalize_gps,
)
from backend.crypto.keys import load_org_private_key, sign_event_hash

ZERO_PREVIOUS_HASH = "0" * 64

EVENT_INSERT_COLUMNS = (
    "event_uid",
    "product_id",
    "product_uid",
    "seq",
    "event_type",
    "actor_user_id",
    "organization_id",
    "signer_key_id",
    "operation_uid",
    "canonical_payload",
    "event_details",
    "previous_hash",
    "event_hash",
    "digital_signature",
    "occurred_at",
    "schema_version",
    "gps_lat_e7",
    "gps_lng_e7",
    "gps_accuracy_cm",
    "gps_status",
    "gps_source",
)


def occurred_at_text(epoch_ms: int) -> str:
    return (
        datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def next_chain_link(conn: sqlite3.Connection, product_id: int) -> tuple[int, str]:
    row = conn.execute(
        """
        SELECT seq, event_hash
        FROM event_ledger
        WHERE product_id = ?
        ORDER BY seq DESC
        LIMIT 1
        """,
        (product_id,),
    ).fetchone()
    if row is None:
        return 0, ZERO_PREVIOUS_HASH
    return int(row["seq"]) + 1, str(row["event_hash"])


def _gps_columns(gps: Mapping[str, Any]) -> dict[str, Any]:
    block = normalize_gps(gps)
    return {
        "gps_lat_e7": block["gps_lat_e7"],
        "gps_lng_e7": block["gps_lng_e7"],
        "gps_accuracy_cm": block["gps_accuracy_cm"],
        "gps_status": block["gps_status"],
        "gps_source": block["gps_source"],
    }


def build_signed_event_row(
    conn: sqlite3.Connection,
    *,
    product_id: int,
    product_uid: str,
    organization_id: int,
    organization_uid: str,
    organization_type: str,
    signer_key_id: str,
    operation_uid: str,
    event_type: str,
    actor_user_id: int | None,
    payload: Mapping[str, Any],
    occurred_at_ms: int,
    event_uid: str | None = None,
    event_details: Mapping[str, Any] | None = None,
    private_key: str | None = None,
) -> dict[str, Any]:
    seq, previous_hash = next_chain_link(conn, product_id)
    if seq == 0 and previous_hash != ZERO_PREVIOUS_HASH:
        raise CanonicalError("genesis previous_hash must be 32 zero bytes")
    if seq == 0 and event_type != "PRODUCT_REGISTERED":
        raise CanonicalError("seq 0 must be PRODUCT_REGISTERED")
    if seq > 0 and event_type == "PRODUCT_REGISTERED":
        raise CanonicalError("PRODUCT_REGISTERED is only valid at seq 0")

    payload_in = dict(payload)
    gps = _gps_columns(payload_in.get("gps"))
    payload_in["gps"] = gps
    event = {
        "actor_user_id": actor_user_id,
        "event_type": event_type,
        "event_uid": event_uid or str(uuid4()),
        "occurred_at": occurred_at_ms,
        "operation_uid": operation_uid,
        "organization_uid": organization_uid,
        "payload": payload_in,
        "previous_hash": previous_hash,
        "product_uid": product_uid,
        "schema_version": 1,
        "seq": seq,
        "signer_key_id": signer_key_id,
    }
    canonical = build_canonical_event(event)
    canonical_bytes = canonical_dumps(canonical)
    digest = event_hash(canonical)
    key = private_key or load_org_private_key(organization_type, organization_id)
    signature = sign_event_hash(digest, key)

    details = {
        "gps_source": "CLIENT_REPORTED",
        **(dict(event_details) if event_details else {}),
    }
    values = {
        "event_uid": canonical["event_uid"],
        "product_id": product_id,
        "product_uid": product_uid,
        "seq": seq,
        "event_type": event_type,
        "actor_user_id": actor_user_id,
        "organization_id": organization_id,
        "signer_key_id": signer_key_id,
        "operation_uid": operation_uid,
        "canonical_payload": canonical_bytes.decode("utf-8"),
        "event_details": json.dumps(details, sort_keys=True, separators=(",", ":")),
        "previous_hash": previous_hash,
        "event_hash": digest,
        "digital_signature": signature,
        "occurred_at": occurred_at_text(occurred_at_ms),
        "schema_version": 1,
        **gps,
        "canonical_event": canonical,
    }
    return values


def jsonable_event_row(values: Mapping[str, Any]) -> dict[str, Any]:
    return {name: values[name] for name in EVENT_INSERT_COLUMNS}


def insert_event_row(conn: sqlite3.Connection, values: Mapping[str, Any]) -> int:
    placeholders = ", ".join("?" for _ in EVENT_INSERT_COLUMNS)
    columns = ", ".join(EVENT_INSERT_COLUMNS)
    conn.execute(
        f"INSERT INTO event_ledger ({columns}) VALUES ({placeholders})",
        [values[name] for name in EVENT_INSERT_COLUMNS],
    )
    return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


def append_event(
    conn: sqlite3.Connection,
    *,
    product_id: int,
    product_uid: str,
    organization_id: int,
    organization_uid: str,
    organization_type: str,
    signer_key_id: str,
    operation_uid: str,
    event_type: str,
    actor_user_id: int | None,
    payload: Mapping[str, Any],
    occurred_at_ms: int,
    event_uid: str | None = None,
    event_details: Mapping[str, Any] | None = None,
    private_key: str | None = None,
) -> dict[str, Any]:
    values = build_signed_event_row(
        conn,
        product_id=product_id,
        product_uid=product_uid,
        organization_id=organization_id,
        organization_uid=organization_uid,
        organization_type=organization_type,
        signer_key_id=signer_key_id,
        operation_uid=operation_uid,
        event_type=event_type,
        actor_user_id=actor_user_id,
        payload=payload,
        occurred_at_ms=occurred_at_ms,
        event_uid=event_uid,
        event_details=event_details,
        private_key=private_key,
    )
    values["event_id"] = insert_event_row(conn, values)
    return values
