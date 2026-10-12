from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

from eth_account import Account

from backend.auth.passwords import hash_password
from backend.chain.local_demo import KEYSTORE_PATH, _key_hex, _stamp
from backend.config import ALLOWED_LOGIN_ROLES, get_settings
from backend.crypto.keys import address_from_private_key
from backend.db import connect
from backend.errors import api_error

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ROLE_COORDS = {
    "MANUFACTURER": (18.5204, 73.8567, "Pune"),
    "DISTRIBUTOR": (19.0760, 72.8777, "Mumbai"),
    "RETAILER": (19.1197, 72.8464, "Mumbai"),
}


def _store_org_key(org_id: int, private_key: str) -> None:
    data = {}
    if KEYSTORE_PATH.exists():
        data = json.loads(KEYSTORE_PATH.read_text(encoding="utf-8"))
    data[str(org_id)] = private_key
    KEYSTORE_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    get_settings.cache_clear()


def register_staff(
    *,
    email: str,
    password: str,
    role: str,
    organization_name: str,
) -> dict[str, str | int]:
    email = email.strip().lower()
    name = organization_name.strip()
    role = role.strip().upper()
    if not EMAIL_RE.match(email):
        raise api_error(422, "INVALID_EMAIL", "enter a valid email")
    if len(password) < 8:
        raise api_error(422, "WEAK_PASSWORD", "password must be at least 8 characters")
    if role not in ALLOWED_LOGIN_ROLES:
        raise api_error(422, "INVALID_ROLE", "role must be MANUFACTURER, DISTRIBUTOR, or RETAILER")
    if len(name) < 2:
        raise api_error(422, "INVALID_ORG", "organization name is required")

    lat, lng, city = ROLE_COORDS[role]
    stamp = _stamp()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    short = uuid4().hex[:8].upper()
    org_uid = str(uuid4())
    org_code = f"{role[:3]}-{short}"
    warehouse_code = f"WH-{short}"
    account = Account.create()
    private_key = _key_hex(account)
    password_hash = hash_password(password)

    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        taken = conn.execute(
            "SELECT 1 FROM users WHERE lower(email)=? OR lower(username)=?",
            (email, email),
        ).fetchone()
        if taken is not None:
            conn.rollback()
            raise api_error(409, "EMAIL_TAKEN", "that email is already registered")
        conn.execute(
            """
            INSERT INTO organizations(
                organization_uid, provisioning_state, data_origin, organization_code,
                organization_name, organization_type, status, created_at
            ) VALUES (?, 'CONFIRMED', 'LIVE', ?, ?, ?, 'ACTIVE', ?)
            """,
            (org_uid, org_code, name, role, stamp),
        )
        org_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        conn.execute(
            """
            INSERT INTO locations(location_name, address, city, state, country, latitude, longitude, created_at)
            VALUES (?, ?, ?, 'Maharashtra', 'India', ?, ?, ?)
            """,
            (f"{name} site", name, city, lat, lng, stamp),
        )
        location_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        conn.execute(
            """
            INSERT INTO warehouses(warehouse_code, warehouse_name, organization_id, location_id, status)
            VALUES (?, ?, ?, ?, 'ACTIVE')
            """,
            (warehouse_code, f"{name} warehouse", org_id, location_id),
        )
        if role == "MANUFACTURER":
            conn.execute(
                """
                INSERT INTO batches(
                    data_origin, batch_number, manufacturer_id, brand, model_name,
                    product_category, batch_status, created_at
                ) VALUES ('LIVE', ?, ?, ?, 'Laptop', 'LAPTOP', 'ACTIVE', ?)
                """,
                (f"BATCH-{short}", org_id, name, stamp),
            )
        key_id = f"org-{org_id}-v1"
        conn.execute(
            """
            INSERT INTO signing_keys(
                key_id, organization_id, device_id, key_version, eth_address,
                valid_from, valid_until, status
            ) VALUES (?, ?, NULL, 1, ?, ?, NULL, 'ACTIVE')
            """,
            (key_id, org_id, address_from_private_key(private_key), stamp),
        )
        conn.execute(
            "UPDATE organizations SET current_key_id=? WHERE organization_id=?",
            (key_id, org_id),
        )
        conn.execute(
            """
            INSERT INTO users(
                password_reset_required, credential_scheme, credentials_updated_at, data_origin,
                organization_id, username, password_hash, role, status, created_at, email
            ) VALUES (0, 'scrypt', ?, 'LIVE', ?, ?, ?, ?, 'ACTIVE', ?, ?)
            """,
            (now, org_id, email, password_hash, role, stamp, email),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise api_error(409, "EMAIL_TAKEN", "that email is already registered") from exc
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    _store_org_key(org_id, private_key)
    return {"email": email, "organization_id": org_id, "role": role, "organization_name": name}
