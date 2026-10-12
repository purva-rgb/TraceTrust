from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from eth_account import Account

from backend.auth.deps import CurrentUser
from backend.chain.adapter import ChainClient
from backend.chain.ids import sha256_to_bytes32, uid_to_bytes32
from backend.chain.pipeline import OperationSpec, execute_operation, insert_operation_row
from backend.crypto.canonical import canonical_dumps
from backend.crypto.events import build_signed_event_row, jsonable_event_row
from backend.crypto.keys import load_org_private_key, sign_event_hash
from backend.db import connect, get_connection
from backend.errors import api_error
from backend.geo import location_check
from backend.products.gps import gps_to_canonical
from backend.products.labels_file import write_demo_labels
from backend.transfers.schemas import (
    AcceptIn,
    OrganizationOut,
    ReceiptItemIn,
    ReceiptsIn,
    ReceiptsOut,
    TransferCreate,
    TransferItemOut,
    TransferListOut,
    TransferOperationOut,
    TransferOut,
)

LEGAL_EDGES = {("MANUFACTURER", "DISTRIBUTOR"), ("DISTRIBUTOR", "RETAILER")}


def _open_alert_uids(conn: sqlite3.Connection, product_uids: list[str]) -> list[str]:
    if not product_uids:
        return []
    placeholders = ",".join("?" for _ in product_uids)
    try:
        rows = conn.execute(
            f"""
            SELECT DISTINCT product_uid FROM fusion_incidents
            WHERE status = 'UNDER_REVIEW' AND product_uid IN ({placeholders})
            """,
            tuple(product_uids),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [row["product_uid"] for row in rows]


def _reject_if_frozen(conn: sqlite3.Connection, product_uids: list[str]) -> None:
    frozen = _open_alert_uids(conn, product_uids)
    if frozen:
        raise api_error(
            409,
            "STEPS_FROZEN",
            "Upcoming steps for this box are frozen.",
            product_uids=frozen,
        )
COUNTERPARTIES = {
    "MANUFACTURER": frozenset({"DISTRIBUTOR"}),
    "DISTRIBUTOR": frozenset({"MANUFACTURER", "RETAILER"}),
    "RETAILER": frozenset({"DISTRIBUTOR"}),
}
EXPIRY_HOURS = 24


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _sql_ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _parse_ts(text: str | None) -> datetime | None:
    if not text:
        return None
    cleaned = text.replace("T", " ").replace("Z", "")
    if "." in cleaned:
        cleaned = cleaned.split(".", 1)[0]
    return datetime.strptime(cleaned[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def _expired(expires_at: str | None) -> bool:
    parsed = _parse_ts(expires_at)
    if parsed is None:
        return False
    return _utcnow() > parsed


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_deployment(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT deployment_id, contract_address, status
        FROM chain_deployments WHERE status='ACTIVE' ORDER BY created_at DESC LIMIT 1
        """
    ).fetchone()
    if row is None:
        raise api_error(503, "CHAIN_UNAVAILABLE", "no ACTIVE chain deployment")
    return dict(row)


def _org_row(conn: sqlite3.Connection, organization_id: int) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT o.organization_id, o.organization_uid, o.organization_name, o.organization_type,
               o.status, o.provisioning_state, o.current_key_id, k.eth_address
        FROM organizations o
        LEFT JOIN signing_keys k ON k.key_id = o.current_key_id
        WHERE o.organization_id=?
        """,
        (organization_id,),
    ).fetchone()
    if row is None:
        raise api_error(404, "NOT_FOUND", "organization not found")
    return row


def list_organizations(actor: CurrentUser, type_filter: str | None) -> list[OrganizationOut]:
    allowed = COUNTERPARTIES.get(actor.organization_type, frozenset())
    if type_filter:
        type_filter = type_filter.upper()
        if type_filter not in {"MANUFACTURER", "DISTRIBUTOR", "RETAILER"}:
            raise api_error(422, "INVALID_TYPE", "type must be a staff organization type")
        if type_filter not in allowed:
            return []
        wanted = {type_filter}
    else:
        wanted = set(allowed)
    if not wanted:
        return []
    placeholders = ",".join("?" for _ in wanted)
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT o.organization_id, o.organization_uid, o.organization_name, o.organization_type, o.status,
                   (
                     SELECT u.username FROM users u
                     WHERE u.organization_id = o.organization_id AND u.role = o.organization_type
                     ORDER BY u.user_id LIMIT 1
                   ) AS username,
                   (
                     SELECT u.email FROM users u
                     WHERE u.organization_id = o.organization_id AND u.role = o.organization_type
                     ORDER BY u.user_id LIMIT 1
                   ) AS email
            FROM organizations o
            WHERE o.status='ACTIVE' AND o.organization_type IN ({placeholders})
              AND o.organization_id<>?
            ORDER BY o.organization_id
            """,
            (*wanted, actor.organization_id),
        ).fetchall()
        org_ids = [row["organization_id"] for row in rows]
        warehouses_by_org: dict[int, list] = {org_id: [] for org_id in org_ids}
        if org_ids:
            wh_placeholders = ",".join("?" for _ in org_ids)
            warehouse_rows = conn.execute(
                f"""
                SELECT warehouse_id, warehouse_code, warehouse_name, organization_id, status
                FROM warehouses
                WHERE status='ACTIVE' AND organization_id IN ({wh_placeholders})
                ORDER BY warehouse_id
                """,
                org_ids,
            ).fetchall()
            for warehouse in warehouse_rows:
                warehouses_by_org[warehouse["organization_id"]].append(dict(warehouse))
    return [
        OrganizationOut(**dict(row), warehouses=warehouses_by_org.get(row["organization_id"], []))
        for row in rows
    ]


def _transfer_query(conn: sqlite3.Connection, transfer_uid: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT t.*, s.organization_type AS sender_type, r.organization_type AS recipient_type
        FROM transfers t
        JOIN organizations s ON s.organization_id = t.sender_organization_id
        JOIN organizations r ON r.organization_id = t.recipient_organization_id
        WHERE t.transfer_uid=?
        """,
        (transfer_uid,),
    ).fetchone()


def _items_out(conn: sqlite3.Connection, transfer_id: int) -> list[TransferItemOut]:
    rows = conn.execute(
        """
        SELECT p.product_uid, i.expected_box_serial, i.expected_seal_id, i.item_outcome
        FROM transfer_items i
        JOIN products p ON p.product_id = i.product_id
        WHERE i.transfer_id=?
        ORDER BY p.product_uid
        """,
        (transfer_id,),
    ).fetchall()
    return [
        TransferItemOut(
            product_uid=row["product_uid"],
            expected_box_serial=row["expected_box_serial"],
            expected_seal_id=row["expected_seal_id"],
            item_outcome=row["item_outcome"],
            laptop_internal_serial_check="NOT_CHECKED",
        )
        for row in rows
    ]


def _visible_to(row: sqlite3.Row, actor: CurrentUser) -> bool:
    if row["sender_organization_id"] == actor.organization_id:
        return True
    if row["recipient_organization_id"] == actor.organization_id and row["chain_status"] == "CONFIRMED":
        return True
    return False


def list_transfers(actor: CurrentUser) -> list[TransferListOut]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT t.transfer_uid, t.transfer_status, t.chain_status, t.sender_organization_id,
                   t.recipient_organization_id, t.expires_at,
                   (SELECT COUNT(*) FROM transfer_items i WHERE i.transfer_id=t.transfer_id) AS item_count
            FROM transfers t
            WHERE t.sender_organization_id=?
               OR (t.recipient_organization_id=? AND t.chain_status='CONFIRMED')
            ORDER BY t.transfer_id DESC
            """,
            (actor.organization_id, actor.organization_id),
        ).fetchall()
    return [
        TransferListOut(
            transfer_uid=row["transfer_uid"],
            transfer_status=row["transfer_status"],
            chain_status=row["chain_status"],
            sender_organization_id=row["sender_organization_id"],
            recipient_organization_id=row["recipient_organization_id"],
            expires_at=row["expires_at"],
            expired=_expired(row["expires_at"]),
            item_count=row["item_count"],
        )
        for row in rows
    ]


def get_transfer(actor: CurrentUser, transfer_uid: str) -> TransferOut:
    with get_connection() as conn:
        row = _transfer_query(conn, transfer_uid)
        if row is None or not _visible_to(row, actor):
            raise api_error(404, "NOT_FOUND", "transfer not found")
        items = _items_out(conn, row["transfer_id"])
    return TransferOut(
        transfer_uid=row["transfer_uid"],
        transfer_status=row["transfer_status"],
        chain_status=row["chain_status"],
        sender_organization_id=row["sender_organization_id"],
        recipient_organization_id=row["recipient_organization_id"],
        source_warehouse_id=row["source_warehouse_id"],
        destination_warehouse_id=row["destination_warehouse_id"],
        expires_at=row["expires_at"],
        expired=_expired(row["expires_at"]),
        items=items,
    )


def _replay(conn: sqlite3.Connection, scope: str, key: str, request_hash: str) -> TransferOperationOut | None:
    existing = conn.execute(
        """
        SELECT operation_uid, request_hash, status, canonical_intent
        FROM operations WHERE idempotency_scope=? AND idempotency_key=?
        """,
        (scope, key),
    ).fetchone()
    if existing is None:
        return None
    if existing["request_hash"] != request_hash:
        raise api_error(409, "IDEMPOTENCY_CONFLICT", "Idempotency-Key reused with a different body")
    intent = json.loads(existing["canonical_intent"] or "{}")
    return TransferOperationOut(
        operation_uid=existing["operation_uid"],
        chain_status=existing["status"],
        status_url=f"/operations/{existing['operation_uid']}",
        transfer_uid=intent.get("transfer_uid") or "",
    )


def initiate_transfer(
    actor: CurrentUser, body: TransferCreate, idempotency_key: str, chain: ChainClient
) -> TransferOperationOut:
    gps = gps_to_canonical(body.gps)
    unique_uids = list(dict.fromkeys(body.product_uids))
    if len(unique_uids) != len(body.product_uids):
        raise api_error(422, "DUPLICATE_PRODUCT", "product_uids must be distinct")
    if not (1 <= len(unique_uids) <= 20):
        raise api_error(422, "MANIFEST_SIZE", "manifest must contain 1-20 products")
    intent = {
        "destination_warehouse_id": body.destination_warehouse_id,
        "gps": gps,
        "product_uids": sorted(unique_uids),
        "recipient_organization_id": body.recipient_organization_id,
        "source_warehouse_id": body.source_warehouse_id,
    }
    request_hash = _sha(canonical_dumps(intent))
    scope = f"INITIATE_TRANSFER:{actor.organization_id}"

    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        replay = _replay(conn, scope, idempotency_key, request_hash)
        if replay is not None:
            conn.rollback()
            return replay

        recipient = _org_row(conn, body.recipient_organization_id)
        if recipient["status"] != "ACTIVE" or recipient["provisioning_state"] != "CONFIRMED":
            conn.rollback()
            raise api_error(422, "INACTIVE_ORG", "recipient is not an active provisioned organization")
        edge = (actor.organization_type, recipient["organization_type"])
        if edge not in LEGAL_EDGES:
            conn.rollback()
            _fusion_transfer_facts(unique_uids, kind="prohibited_route")
            raise api_error(422, "ILLEGAL_EDGE", "only manufacturer→distributor and distributor→retailer are legal")

        dest = conn.execute(
            "SELECT warehouse_id, organization_id, status FROM warehouses WHERE warehouse_id=?",
            (body.destination_warehouse_id,),
        ).fetchone()
        if dest is None or dest["organization_id"] != recipient["organization_id"] or dest["status"] != "ACTIVE":
            conn.rollback()
            raise api_error(404, "NOT_FOUND", "destination warehouse not found")

        placeholders = ",".join("?" for _ in unique_uids)
        rows = conn.execute(
            f"""
            SELECT i.product_id, i.product_uid, i.warehouse_id, p.product_uid AS puid,
                   pkg.package_id, pkg.package_uid, pkg.binding_version,
                   pkg.package_serial_number, pkg.seal_id,
                   (SELECT event_hash FROM event_ledger e WHERE e.product_id=i.product_id ORDER BY seq DESC LIMIT 1) AS head
            FROM operational_inventory i
            JOIN products p ON p.product_id = i.product_id
            JOIN packages pkg ON pkg.product_id = i.product_id AND pkg.status='ACTIVE'
            WHERE i.product_uid IN ({placeholders}) AND i.custodian_organization_id=?
            """,
            (*unique_uids, actor.organization_id),
        ).fetchall()
        by_uid = {row["product_uid"]: row for row in rows}
        missing = [uid for uid in unique_uids if uid not in by_uid]
        if missing:
            conn.rollback()
            _fusion_sold_reentry(missing)
            raise api_error(409, "NOT_ELIGIBLE", "one or more products are not confirmed custodial inventory")
        source_id = body.source_warehouse_id or rows[0]["warehouse_id"]
        source = conn.execute(
            "SELECT warehouse_id, organization_id, status FROM warehouses WHERE warehouse_id=?",
            (source_id,),
        ).fetchone()
        if source is None or source["organization_id"] != actor.organization_id or source["status"] != "ACTIVE":
            conn.rollback()
            raise api_error(404, "NOT_FOUND", "source warehouse not found")
        if any(row["warehouse_id"] != source_id for row in by_uid.values()):
            conn.rollback()
            raise api_error(422, "WAREHOUSE_MISMATCH", "all products must share the source warehouse")
        frozen = _open_alert_uids(conn, unique_uids)
        if frozen:
            conn.rollback()
            raise api_error(
                409,
                "STEPS_FROZEN",
                "Upcoming steps for this box are frozen.",
                product_uids=frozen,
            )

        sender = _org_row(conn, actor.organization_id)
        if sender["current_key_id"] is None or sender["eth_address"] is None:
            conn.rollback()
            raise api_error(503, "ORG_UNPROVISIONED", "sender is not chain-provisioned")
        if recipient["eth_address"] is None:
            conn.rollback()
            raise api_error(503, "ORG_UNPROVISIONED", "recipient is not chain-provisioned")

        deployment = _load_deployment(conn)
        created = _utcnow()
        expires = created + timedelta(hours=EXPIRY_HOURS)
        created_sql = _sql_ts(created)
        expires_sql = _sql_ts(expires)
        transfer_uid = str(uuid4())
        operation_uid = str(uuid4())
        transfer_code = f"TRF-{transfer_uid.replace('-', '')[:12].upper()}"
        sorted_rows = [by_uid[uid] for uid in sorted(unique_uids)]
        manifest = [
            {
                "binding_version": int(row["binding_version"]),
                "box_serial": row["package_serial_number"],
                "package_uid": row["package_uid"],
                "product_uid": row["product_uid"],
                "seal_id": row["seal_id"],
            }
            for row in sorted_rows
        ]
        manifest_digest = _sha(canonical_dumps(manifest))
        request_payload = {
            "created_at": int(created.timestamp() * 1000),
            "deployment_id": deployment["deployment_id"],
            "destination_warehouse_id": body.destination_warehouse_id,
            "expires_at": int(expires.timestamp()),
            "manifest_digest": manifest_digest,
            "operation_uid": operation_uid,
            "product_uids": [row["product_uid"] for row in sorted_rows],
            "recipient_organization_uid": recipient["organization_uid"],
            "sender_organization_uid": sender["organization_uid"],
            "source_warehouse_id": source_id,
            "transfer_uid": transfer_uid,
        }
        request_digest = _sha(canonical_dumps(request_payload))
        private_key = load_org_private_key(actor.organization_type, actor.organization_id)
        sender_signature = sign_event_hash(request_digest, private_key)
        occurred_ms = int(created.timestamp() * 1000)

        events = []
        expected_heads: dict[str, str] = {}
        for row in sorted_rows:
            event = build_signed_event_row(
                conn,
                product_id=row["product_id"],
                product_uid=row["product_uid"],
                organization_id=actor.organization_id,
                organization_uid=sender["organization_uid"],
                organization_type=actor.organization_type,
                signer_key_id=sender["current_key_id"],
                operation_uid=operation_uid,
                event_type="TRANSFER_INITIATED",
                actor_user_id=actor.user_id,
                payload={
                    "gps": gps,
                    "manifest_digest": manifest_digest,
                    "recipient_organization_uid": recipient["organization_uid"],
                    "transfer_uid": transfer_uid,
                },
                occurred_at_ms=occurred_ms,
                private_key=private_key,
            )
            events.append(event)
            expected_heads[row["product_uid"]] = event["previous_hash"]

        chain_args = [
            uid_to_bytes32(transfer_uid),
            recipient["eth_address"],
            [uid_to_bytes32(row["product_uid"]) for row in sorted_rows],
            sha256_to_bytes32(manifest_digest),
            int(expires.timestamp()),
            [sha256_to_bytes32(event["previous_hash"]) for event in events],
            [sha256_to_bytes32(event["event_hash"]) for event in events],
            uid_to_bytes32(operation_uid),
        ]
        spec = OperationSpec(
            operation_uid=operation_uid,
            operation_type="INITIATE_TRANSFER",
            actor_user_id=actor.user_id,
            organization_id=actor.organization_id,
            idempotency_scope=scope,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            canonical_intent={**intent, "transfer_uid": transfer_uid, "operation_uid": operation_uid},
            signed_payload={
                "chain_function": "initiateTransfer",
                "events": [jsonable_event_row(event) for event in events],
                "projection": {"type": "INITIATE_TRANSFER"},
                "sender_address": Account.from_key(private_key).address,
            },
            expected_heads=expected_heads,
            deployment_id=deployment["deployment_id"],
            chain_function="initiateTransfer",
            chain_args=chain_args,
            sender_private_key=private_key,
            sender_address=Account.from_key(private_key).address,
        )
        insert_operation_row(conn, spec, created_sql)
        conn.execute(
            """
            INSERT INTO transfers(
                transfer_uid, expires_at, request_digest, manifest_digest, chain_status,
                initiation_operation_uid, deployment_id, sender_key_id, request_payload,
                data_origin, transfer_code, sender_organization_id, recipient_organization_id,
                source_warehouse_id, destination_warehouse_id, transfer_status,
                initiated_by_user_id, created_at, sender_signature
            ) VALUES (?, ?, ?, ?, 'PENDING', ?, ?, ?, ?, 'LIVE', ?, ?, ?, ?, ?, 'INITIATED', ?, ?, ?)
            """,
            (
                transfer_uid,
                expires_sql,
                request_digest,
                manifest_digest,
                operation_uid,
                deployment["deployment_id"],
                sender["current_key_id"],
                json.dumps(request_payload, sort_keys=True, separators=(",", ":")),
                transfer_code,
                actor.organization_id,
                recipient["organization_id"],
                source_id,
                body.destination_warehouse_id,
                actor.user_id,
                created_sql,
                sender_signature,
            ),
        )
        transfer_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        for row in sorted_rows:
            conn.execute(
                """
                INSERT INTO transfer_items(
                    expected_package_id, expected_binding_version, expected_box_serial, expected_seal_id,
                    item_outcome, data_origin, transfer_id, product_id
                ) VALUES (?, ?, ?, ?, 'PENDING', 'LIVE', ?, ?)
                """,
                (
                    row["package_id"],
                    int(row["binding_version"]),
                    row["package_serial_number"],
                    row["seal_id"],
                    transfer_id,
                    row["product_id"],
                ),
            )
        for row in sorted_rows:
            conn.execute(
                """
                INSERT INTO product_reservations(product_id, transfer_id, operation_uid, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (row["product_id"], transfer_id, operation_uid, created_sql, expires_sql),
            )
        spec.signed_payload["projection"]["transfer_id"] = transfer_id
        spec.signed_payload["transfer_id"] = transfer_id
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise api_error(409, "CONFLICT", str(exc)) from exc
    finally:
        conn.close()

    chain_status = execute_operation(spec, chain, persist=False)
    return TransferOperationOut(
        operation_uid=operation_uid,
        chain_status=chain_status,
        status_url=f"/operations/{operation_uid}",
        transfer_uid=transfer_uid,
    )


def _open_transfer(conn: sqlite3.Connection, transfer_uid: str, actor: CurrentUser, *, role: str) -> sqlite3.Row:
    row = _transfer_query(conn, transfer_uid)
    if row is None:
        raise api_error(404, "NOT_FOUND", "transfer not found")
    if role == "recipient" and row["recipient_organization_id"] != actor.organization_id:
        raise api_error(404, "NOT_FOUND", "transfer not found")
    if role == "sender" and row["sender_organization_id"] != actor.organization_id:
        raise api_error(404, "NOT_FOUND", "transfer not found")
    if row["chain_status"] != "CONFIRMED":
        raise api_error(409, "NOT_CONFIRMED", "transfer is not usable until initiation is confirmed")
    if row["transfer_status"] != "INITIATED":
        raise api_error(409, "TRANSFER_CLOSED", "transfer is no longer open")
    if _expired(row["expires_at"]):
        raise api_error(409, "TRANSFER_EXPIRED", "transfer has expired")
    if row["terminal_operation_uid"] is not None and role in {"recipient", "sender"}:
        pending = conn.execute(
            "SELECT status FROM operations WHERE operation_uid=?",
            (row["terminal_operation_uid"],),
        ).fetchone()
        if pending and pending["status"] in {"PENDING", "SUBMITTED"}:
            raise api_error(409, "ACCEPTANCE_PENDING", "a terminal operation is already in flight")
    return row


def _warehouse_coords(conn: sqlite3.Connection, warehouse_id: int | None) -> tuple[float | None, float | None]:
    if warehouse_id is None:
        return None, None
    row = conn.execute(
        """
        SELECT l.latitude, l.longitude
        FROM warehouses w LEFT JOIN locations l ON l.location_id = w.location_id
        WHERE w.warehouse_id=?
        """,
        (warehouse_id,),
    ).fetchone()
    if row is None:
        return None, None
    return row["latitude"], row["longitude"]


def _insert_inspection(
    conn: sqlite3.Connection,
    *,
    actor: CurrentUser,
    org: sqlite3.Row,
    package_id: int,
    item: ReceiptItemIn,
    gps: dict[str, Any],
    private_key: str,
) -> int:
    inspection_uid = str(uuid4())
    occurred = _utcnow()
    occurred_sql = _sql_ts(occurred)
    payload = {
        "gps": gps,
        "inspection_mode": item.mode,
        "inspection_uid": inspection_uid,
        "laptop_serial_result": "NOT_CHECKED",
        "observed_box_serial": item.box_serial,
        "observed_condition": item.condition,
        "observed_seal_id": item.seal_id,
        "occurred_at": int(occurred.timestamp() * 1000),
    }
    canonical = canonical_dumps(payload).decode("utf-8")
    digest = _sha(canonical.encode("utf-8"))
    signature = sign_event_hash(digest, private_key)
    conn.execute(
        """
        INSERT INTO seal_inspections(
            inspection_uid, inspection_mode, observed_box_serial, observed_laptop_serial,
            laptop_serial_result, occurred_at, signer_key_id, canonical_payload, payload_digest,
            digital_signature, opening_authorized, is_simulated, verification_state, data_origin,
            package_id, inspected_by_user_id, observed_seal_id, observed_condition, inspected_at,
            gps_lat_e7, gps_lng_e7, gps_accuracy_cm, gps_status, gps_source
        ) VALUES (?, ?, ?, NULL, 'NOT_CHECKED', ?, ?, ?, ?, ?, 0, 0, 'VERIFIED', 'LIVE',
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, 'CLIENT_REPORTED')
        """,
        (
            inspection_uid,
            item.mode,
            item.box_serial,
            occurred_sql,
            org["current_key_id"],
            canonical,
            digest,
            signature,
            package_id,
            actor.user_id,
            item.seal_id,
            item.condition,
            occurred_sql,
            gps.get("gps_lat_e7"),
            gps.get("gps_lng_e7"),
            gps.get("gps_accuracy_cm"),
            gps.get("gps_status") or "NOT_REQUESTED",
        ),
    )
    return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


def record_receipts(actor: CurrentUser, transfer_uid: str, body: ReceiptsIn) -> ReceiptsOut:
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = _open_transfer(conn, transfer_uid, actor, role="recipient")
        org = _org_row(conn, actor.organization_id)
        if org["current_key_id"] is None:
            conn.rollback()
            raise api_error(503, "ORG_UNPROVISIONED", "recipient is not chain-provisioned")
        private_key = load_org_private_key(actor.organization_type, actor.organization_id)
        manifest_rows = conn.execute(
            """
            SELECT i.transfer_item_id, i.product_id, i.expected_package_id, i.expected_box_serial,
                   i.expected_seal_id, p.product_uid
            FROM transfer_items i JOIN products p ON p.product_id = i.product_id
            WHERE i.transfer_id=?
            """,
            (row["transfer_id"],),
        ).fetchall()
        expected_uids = [item["product_uid"] for item in manifest_rows]
        frozen = _open_alert_uids(conn, expected_uids)
        if frozen:
            conn.rollback()
            raise api_error(
                409,
                "STEPS_FROZEN",
                "Upcoming steps for this box are frozen.",
                product_uids=frozen,
            )
        by_uid = {item["product_uid"]: item for item in manifest_rows}
        observed_uids = [item.product_uid for item in body.items]
        counts = Counter(observed_uids)
        duplicates = [uid for uid, n in counts.items() if n > 1]
        unexpected = [uid for uid in counts if uid not in by_uid]
        missing = [uid for uid in expected_uids if counts[uid] == 0]
        mismatched: list[dict[str, str]] = []
        for uid in duplicates:
            mismatched.append({"product_uid": uid, "reason": "DUPLICATE"})
        for item in body.items:
            if item.product_uid in duplicates or item.product_uid not in by_uid:
                continue
            expected = by_uid[item.product_uid]
            if item.mode != "SEALED":
                mismatched.append({"product_uid": item.product_uid, "reason": "WRONG_MODE"})
            elif item.condition != "INTACT":
                mismatched.append({"product_uid": item.product_uid, "reason": "BROKEN_SEAL"})
            elif item.box_serial != expected["expected_box_serial"]:
                mismatched.append({"product_uid": item.product_uid, "reason": "WRONG_BOX"})
            elif item.seal_id != expected["expected_seal_id"]:
                mismatched.append({"product_uid": item.product_uid, "reason": "WRONG_SEAL"})

        gps = gps_to_canonical(body.gps or (body.items[0].gps if body.items else None))
        lat, lng = _warehouse_coords(conn, row["destination_warehouse_id"])
        loc = location_check(gps, lat, lng)

        failed = bool(missing or unexpected or mismatched)
        for item in body.items:
            expected = by_uid.get(item.product_uid)
            package_id = expected["expected_package_id"] if expected else None
            if package_id is None:
                found = conn.execute(
                    """
                    SELECT package_id FROM packages pkg
                    JOIN products p ON p.product_id = pkg.product_id
                    WHERE p.product_uid=? AND pkg.status='ACTIVE'
                    """,
                    (item.product_uid,),
                ).fetchone()
                package_id = found["package_id"] if found else None
            if package_id is None:
                continue
            item_gps = gps_to_canonical(item.gps) if item.gps is not None else gps
            inspection_id = _insert_inspection(
                conn,
                actor=actor,
                org=org,
                package_id=package_id,
                item=item,
                gps=item_gps,
                private_key=private_key,
            )
            if expected is None:
                continue
            if failed:
                conn.execute(
                    """
                    UPDATE transfer_items
                    SET receipt_inspection_id=?, item_outcome=?, received_scanned=1, scanned_at=?
                    WHERE transfer_item_id=?
                    """,
                    (
                        inspection_id,
                        "MISMATCH" if item.product_uid not in missing else "MISSING",
                        _sql_ts(_utcnow()),
                        expected["transfer_item_id"],
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE transfer_items
                    SET receipt_inspection_id=?, item_outcome='MATCHED', received_scanned=1, scanned_at=?
                    WHERE transfer_item_id=?
                    """,
                    (inspection_id, _sql_ts(_utcnow()), expected["transfer_item_id"]),
                )
        for uid in missing:
            conn.execute(
                """
                UPDATE transfer_items SET item_outcome='MISSING'
                WHERE transfer_id=? AND product_id=(SELECT product_id FROM products WHERE product_uid=?)
                """,
                (row["transfer_id"], uid),
            )
        conn.commit()
        items = _items_out(conn, row["transfer_id"])
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise api_error(409, "CONFLICT", str(exc)) from exc
    finally:
        conn.close()

    if failed or loc == "OUTSIDE_RADIUS":
        from backend.notify.mail import notify_transfer_mismatch

        notify_transfer_mismatch(
            transfer_uid,
            reason="HANDOVER_MISMATCH" if failed else "LOCATION_OUTSIDE_RADIUS",
            location_check=loc,
        )
    if failed:
        for uid in sorted(set(expected_uids) | set(observed_uids)):
            _fusion_refresh(uid)
        raise api_error(
            422,
            "HANDOVER_MISMATCH",
            "receipt does not match the signed manifest",
            missing=missing,
            unexpected=unexpected,
            mismatched=mismatched,
            location_check=loc,
            laptop_internal_serial_check="NOT_CHECKED",
        )
    return ReceiptsOut(
        transfer_uid=transfer_uid,
        location_check=loc,
        laptop_internal_serial_check="NOT_CHECKED",
        items=items,
    )


def _submit_terminal(
    actor: CurrentUser,
    transfer_uid: str,
    chain: ChainClient,
    *,
    operation_type: str,
    event_type: str,
    chain_function: str,
    role: str,
    gps: dict[str, Any],
    extra_payload: dict[str, Any],
    extra_projection: dict[str, Any],
    chain_args_builder,
) -> TransferOperationOut:
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = _open_transfer(conn, transfer_uid, actor, role=role)
        if operation_type == "ACCEPT_TRANSFER":
            unmatched = conn.execute(
                "SELECT COUNT(*) AS n FROM transfer_items WHERE transfer_id=? AND item_outcome<>'MATCHED'",
                (row["transfer_id"],),
            ).fetchone()["n"]
            if unmatched:
                conn.rollback()
                raise api_error(422, "RECEIPT_INCOMPLETE", "all manifest items must be MATCHED before accept")
        org = _org_row(conn, actor.organization_id)
        if org["current_key_id"] is None:
            conn.rollback()
            raise api_error(503, "ORG_UNPROVISIONED", "organization is not chain-provisioned")
        deployment = _load_deployment(conn)
        private_key = load_org_private_key(actor.organization_type, actor.organization_id)
        operation_uid = str(uuid4())
        occurred_ms = int(_utcnow().timestamp() * 1000)
        items = conn.execute(
            """
            SELECT i.product_id, p.product_uid,
                   (SELECT event_hash FROM event_ledger e WHERE e.product_id=i.product_id ORDER BY seq DESC LIMIT 1) AS head
            FROM transfer_items i JOIN products p ON p.product_id=i.product_id
            WHERE i.transfer_id=?
            ORDER BY p.product_uid
            """,
            (row["transfer_id"],),
        ).fetchall()
        events = []
        expected_heads: dict[str, str] = {}
        for item in items:
            event = build_signed_event_row(
                conn,
                product_id=item["product_id"],
                product_uid=item["product_uid"],
                organization_id=actor.organization_id,
                organization_uid=org["organization_uid"],
                organization_type=actor.organization_type,
                signer_key_id=org["current_key_id"],
                operation_uid=operation_uid,
                event_type=event_type,
                actor_user_id=actor.user_id,
                payload={"gps": gps, "transfer_uid": transfer_uid, **extra_payload},
                occurred_at_ms=occurred_ms,
                private_key=private_key,
            )
            events.append(event)
            expected_heads[item["product_uid"]] = event["previous_hash"]
        chain_args = chain_args_builder(row, items, events, operation_uid)
        spec = OperationSpec(
            operation_uid=operation_uid,
            operation_type=operation_type,
            actor_user_id=actor.user_id,
            organization_id=actor.organization_id,
            idempotency_scope=f"{operation_type}:{transfer_uid}",
            idempotency_key=operation_uid,
            request_hash=_sha(operation_uid.encode()),
            canonical_intent={"operation_uid": operation_uid, "transfer_uid": transfer_uid},
            signed_payload={
                "chain_function": chain_function,
                "events": [jsonable_event_row(event) for event in events],
                "projection": {
                    "destination_warehouse_id": row["destination_warehouse_id"],
                    "products": [{"product_id": item["product_id"], "product_uid": item["product_uid"]} for item in items],
                    "recipient_organization_id": row["recipient_organization_id"],
                    "transfer_id": row["transfer_id"],
                    "type": operation_type,
                    **extra_projection,
                },
                "sender_address": Account.from_key(private_key).address,
                "transfer_id": row["transfer_id"],
            },
            expected_heads=expected_heads,
            deployment_id=deployment["deployment_id"],
            chain_function=chain_function,
            chain_args=chain_args,
            sender_private_key=private_key,
            sender_address=Account.from_key(private_key).address,
        )
        insert_operation_row(conn, spec)
        claimed = conn.execute(
            """
            UPDATE transfers
            SET terminal_operation_uid=?
            WHERE transfer_id=? AND transfer_status='INITIATED' AND terminal_operation_uid IS NULL
            """,
            (operation_uid, row["transfer_id"]),
        ).rowcount
        if claimed != 1:
            conn.rollback()
            raise api_error(409, "ACCEPTANCE_PENDING", "another terminal operation already exists")
        conn.commit()
    finally:
        conn.close()
    chain_status = execute_operation(spec, chain, persist=False)
    if operation_type == "ACCEPT_TRANSFER" and chain_status == "CONFIRMED":
        try:
            write_demo_labels()
        except Exception:
            pass
    return TransferOperationOut(
        operation_uid=operation_uid,
        chain_status=chain_status,
        status_url=f"/operations/{operation_uid}",
        transfer_uid=transfer_uid,
    )


def accept_transfer(actor: CurrentUser, transfer_uid: str, body: AcceptIn, chain: ChainClient) -> TransferOperationOut:
    gps = gps_to_canonical(body.gps)
    with get_connection() as conn:
        row = _transfer_query(conn, transfer_uid)
        if row is not None:
            _reject_if_frozen(conn, [item.product_uid for item in _items_out(conn, row["transfer_id"])])
        if row is None:
            raise api_error(404, "NOT_FOUND", "transfer not found")
        inspections = conn.execute(
            """
            SELECT s.payload_digest
            FROM transfer_items i
            JOIN seal_inspections s ON s.inspection_id = i.receipt_inspection_id
            WHERE i.transfer_id=?
            ORDER BY i.product_id
            """,
            (row["transfer_id"],),
        ).fetchall()
    receipt_digest = _sha(canonical_dumps({"payload_digests": [r["payload_digest"] for r in inspections]}))
    org_key = None

    def build_args(_transfer, items, events, operation_uid):
        return [
            uid_to_bytes32(transfer_uid),
            sha256_to_bytes32(receipt_digest),
            [sha256_to_bytes32(event["event_hash"]) for event in events],
            uid_to_bytes32(operation_uid),
        ]

    with get_connection() as conn:
        org = _org_row(conn, actor.organization_id)
        org_key = org["current_key_id"]
        private_key = load_org_private_key(actor.organization_type, actor.organization_id)
        recipient_signature = sign_event_hash(receipt_digest, private_key)

    return _submit_terminal(
        actor,
        transfer_uid,
        chain,
        operation_type="ACCEPT_TRANSFER",
        event_type="TRANSFER_ACCEPTED",
        chain_function="acceptTransfer",
        role="recipient",
        gps=gps,
        extra_payload={"receipt_digest": receipt_digest},
        extra_projection={
            "accepted_by_user_id": actor.user_id,
            "receipt_digest": receipt_digest,
            "recipient_key_id": org_key,
            "recipient_signature": recipient_signature,
        },
        chain_args_builder=build_args,
    )


def reject_transfer(actor: CurrentUser, transfer_uid: str, chain: ChainClient) -> TransferOperationOut:
    def build_args(_transfer, items, events, operation_uid):
        return [
            uid_to_bytes32(transfer_uid),
            [sha256_to_bytes32(event["previous_hash"]) for event in events],
            [sha256_to_bytes32(event["event_hash"]) for event in events],
            uid_to_bytes32(operation_uid),
        ]

    return _submit_terminal(
        actor,
        transfer_uid,
        chain,
        operation_type="REJECT_TRANSFER",
        event_type="TRANSFER_REJECTED",
        chain_function="rejectTransfer",
        role="recipient",
        gps=gps_to_canonical(None),
        extra_payload={},
        extra_projection={},
        chain_args_builder=build_args,
    )


def cancel_transfer(actor: CurrentUser, transfer_uid: str, chain: ChainClient) -> TransferOperationOut:
    def build_args(_transfer, items, events, operation_uid):
        return [
            uid_to_bytes32(transfer_uid),
            [sha256_to_bytes32(event["previous_hash"]) for event in events],
            [sha256_to_bytes32(event["event_hash"]) for event in events],
            uid_to_bytes32(operation_uid),
        ]

    return _submit_terminal(
        actor,
        transfer_uid,
        chain,
        operation_type="CANCEL_TRANSFER",
        event_type="TRANSFER_CANCELLED",
        chain_function="cancelTransfer",
        role="sender",
        gps=gps_to_canonical(None),
        extra_payload={},
        extra_projection={},
        chain_args_builder=build_args,
    )


def _fusion_transfer_facts(product_uids: list[str], *, kind: str) -> None:
    if not product_uids:
        return
    try:
        from backend.fusion.service import record_transfer_facts

        now = int(datetime.now(timezone.utc).timestamp() * 1000)
        record_transfer_facts(
            [
                {
                    "kind": kind,
                    "product_uid": uid,
                    "evidence_id": f"{kind}:{uid}",
                    "event_time_ms": now,
                    "authenticated": True,
                    "is_simulated": 0,
                }
                for uid in product_uids
            ]
        )
    except Exception:
        logging.getLogger("tracetrust").exception("fusion transfer fact skipped")


def _fusion_sold_reentry(product_uids: list[str]) -> None:
    if not product_uids:
        return
    try:
        conn = connect()
        try:
            marks = ",".join("?" for _ in product_uids)
            rows = conn.execute(
                f"SELECT product_uid FROM products WHERE lifecycle_state='SOLD' AND product_uid IN ({marks})",
                tuple(product_uids),
            ).fetchall()
        finally:
            conn.close()
        _fusion_transfer_facts([row["product_uid"] for row in rows], kind="sold_reentry")
    except Exception:
        logging.getLogger("tracetrust").exception("fusion sold reentry skipped")


def _fusion_refresh(product_uid: str) -> None:
    try:
        from backend.fusion.service import refresh_product

        refresh_product(product_uid)
    except Exception:
        logging.getLogger("tracetrust").exception("fusion receipt refresh skipped")
