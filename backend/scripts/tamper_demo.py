"""Dev-only: copy a TraceTrust DB and tamper it so verification can be demonstrated."""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from pathlib import Path

from backend.crypto.canonical import build_canonical_event, canonical_dumps, parse_canonical_json
from backend.crypto.keys import sign_event_hash


def copy_database(source: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)
    return dest


def disable_append_only(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type='trigger'
          AND (name LIKE '%event_ledger%' OR name LIKE '%event_anchor%')
        """
    ).fetchall()
    for row in rows:
        conn.execute(f'DROP TRIGGER IF EXISTS "{row[0]}"')


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=OFF")
    disable_append_only(conn)
    return conn


def _last_event(conn: sqlite3.Connection, product_uid: str) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT * FROM event_ledger
        WHERE product_uid=?
        ORDER BY seq DESC
        LIMIT 1
        """,
        (product_uid,),
    ).fetchone()
    if row is None:
        raise SystemExit(f"no events for {product_uid}")
    return row


def tamper_payload(db_path: Path, product_uid: str) -> None:
    conn = _connect(db_path)
    try:
        row = _last_event(conn, product_uid)
        parsed = json.loads(row["canonical_payload"])
        payload = parsed.setdefault("payload", {})
        payload["tampered"] = "payload-edit"
        conn.execute(
            "UPDATE event_ledger SET canonical_payload=? WHERE event_id=?",
            (json.dumps(parsed, sort_keys=True, separators=(",", ":")), row["event_id"]),
        )
        conn.commit()
    finally:
        conn.close()


def tamper_coordinate(db_path: Path, product_uid: str) -> None:
    conn = _connect(db_path)
    try:
        row = _last_event(conn, product_uid)
        parsed = json.loads(row["canonical_payload"])
        gps = parsed.setdefault("payload", {}).setdefault("gps", {})
        original = gps.get("gps_lat_e7") or 0
        gps["gps_lat_e7"] = int(original) + 1
        conn.execute(
            """
            UPDATE event_ledger
            SET canonical_payload=?, gps_lat_e7=?
            WHERE event_id=?
            """,
            (
                json.dumps(parsed, sort_keys=True, separators=(",", ":")),
                gps["gps_lat_e7"],
                row["event_id"],
            ),
        )
        conn.commit()
    finally:
        conn.close()


def delete_last_event(db_path: Path, product_uid: str) -> None:
    conn = _connect(db_path)
    try:
        row = _last_event(conn, product_uid)
        conn.execute("DELETE FROM event_anchors WHERE event_id=?", (row["event_id"],))
        conn.execute("DELETE FROM event_ledger WHERE event_id=?", (row["event_id"],))
        conn.commit()
    finally:
        conn.close()


def rewrite_hashes(db_path: Path, product_uid: str, private_key: str) -> None:
    conn = _connect(db_path)
    try:
        row = _last_event(conn, product_uid)
        parsed = parse_canonical_json(row["canonical_payload"])
        payload = parsed.setdefault("payload", {})
        payload["tampered"] = "consistent-rewrite"
        rebuilt = build_canonical_event(parsed)
        blob = canonical_dumps(rebuilt)
        digest = __import__("hashlib").sha256(blob).hexdigest()
        signature = sign_event_hash(digest, private_key)
        conn.execute(
            """
            UPDATE event_ledger
            SET canonical_payload=?, event_hash=?, digital_signature=?
            WHERE event_id=?
            """,
            (blob.decode("utf-8"), digest, signature, row["event_id"]),
        )
        conn.execute(
            "UPDATE event_anchors SET anchored_hash=? WHERE event_id=?",
            (digest, row["event_id"]),
        )
        conn.commit()
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Tamper a COPY of a TraceTrust database")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument(
        "--mode",
        required=True,
        choices=("payload", "coordinate", "delete-last", "rewrite-hashes"),
    )
    parser.add_argument("--product-uid", required=True)
    parser.add_argument("--private-key", default=None, help="required for rewrite-hashes")
    args = parser.parse_args()
    if args.out.resolve() == args.source.resolve():
        raise SystemExit("refusing to tamper the source database; pass a different --out")
    copy_database(args.source, args.out)
    if args.mode == "payload":
        tamper_payload(args.out, args.product_uid)
    elif args.mode == "coordinate":
        tamper_coordinate(args.out, args.product_uid)
    elif args.mode == "delete-last":
        delete_last_event(args.out, args.product_uid)
    else:
        if not args.private_key:
            raise SystemExit("rewrite-hashes requires --private-key")
        rewrite_hashes(args.out, args.product_uid, args.private_key)
    print(f"wrote {args.out} mode={args.mode}")


if __name__ == "__main__":
    main()
