"""Write DEMO_LABELS.md so UIDs and QR payloads can be copied for verify."""
from __future__ import annotations

import json
from pathlib import Path

from backend.config import ROOT
from backend.db import get_connection

MARKDOWN_PATH = ROOT / "DEMO_LABELS.md"
JSON_PATH = ROOT / "frontend" / "public" / "labels.json"


def _rows() -> list[dict]:
    with get_connection() as conn:
        records = conn.execute(
            """
            SELECT p.product_uid, p.serial_number,
                   pkg.package_serial_number AS box_serial, pkg.seal_id,
                   op.canonical_intent, org.organization_type AS custodian
            FROM products p
            JOIN packages pkg ON pkg.product_id = p.product_id AND pkg.status='ACTIVE'
            LEFT JOIN operations op ON op.operation_uid = p.registration_operation_uid
            LEFT JOIN organizations org ON org.organization_id = p.current_owner_organization_id
            WHERE p.data_origin='LIVE' AND p.registration_state='CONFIRMED'
            ORDER BY p.product_id
            """
        ).fetchall()
    items = []
    for row in records:
        intent = {}
        try:
            intent = json.loads(row["canonical_intent"] or "{}")
        except json.JSONDecodeError:
            intent = {}
        items.append(
            {
                "custodian": row["custodian"] or "",
                "serial_number": row["serial_number"],
                "product_uid": row["product_uid"],
                "qr_payload": intent.get("qr_payload") or "",
                "box_serial": row["box_serial"],
                "seal_id": row["seal_id"],
            }
        )
    return items


def write_demo_labels() -> None:
    from backend.config import get_settings

    if get_settings().database_path.name != "laptop_anti_counterfeit.db":
        return
    items = _rows()
    lines = [
        "# Demo labels",
        "",
        "Copy a **product UID** or **QR payload** into Verify.",
        "",
    ]
    if not items:
        lines.append("No confirmed live units yet. Register from the Labels page.")
        lines.append("")
    else:
        lines.extend(
            [
                "| Custodian | Serial | Product UID | QR payload |",
                "| --- | --- | --- | --- |",
            ]
        )
        for item in items:
            lines.append(
                f"| {item['custodian']} | {item['serial_number']} | `{item['product_uid']}` | `{item['qr_payload']}` |"
            )
        lines.append("")
        for item in items:
            lines.extend(
                [
                    f"## {item['serial_number']} ({item['custodian'] or 'UNKNOWN'})",
                    "",
                    f"- UID: `{item['product_uid']}`",
                    f"- QR: `{item['qr_payload']}`",
                    f"- Box: `{item['box_serial']}`",
                    f"- Seal: `{item['seal_id']}`",
                    "",
                ]
            )
    MARKDOWN_PATH.write_text("\n".join(lines), encoding="utf-8")
    JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(json.dumps(items, indent=2) + "\n", encoding="utf-8")
