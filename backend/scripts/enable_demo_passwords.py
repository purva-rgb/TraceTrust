"""Enable only manufacturer/distributor/retailer demo accounts from env passwords."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from backend.auth.passwords import hash_password
from backend.config import ROOT

STAFF_ENV = {
    "demo_manufacturer": "DEMO_MANUFACTURER_PASSWORD",
    "demo_distributor": "DEMO_DISTRIBUTOR_PASSWORD",
    "demo_retailer": "DEMO_RETAILER_PASSWORD",
}
BLOCKED_USERNAMES = frozenset(
    {"demo_admin", "demo_auditor", "demo_regulator", "demo_logistics"}
)


class PasswordSetupError(ValueError):
    pass


def enable_staff_passwords(db_path: Path, environ: dict[str, str] | None = None) -> list[str]:
    env = environ if environ is not None else os.environ
    enabled: list[str] = []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        conn.execute("BEGIN IMMEDIATE")
        for username, env_name in STAFF_ENV.items():
            password = env.get(env_name, "")
            if len(password) < 12:
                raise PasswordSetupError(f"{env_name} must be at least 12 characters")
            row = conn.execute(
                "SELECT user_id, role, organization_id FROM users WHERE username = ?",
                (username,),
            ).fetchone()
            if row is None:
                raise PasswordSetupError(f"unknown username {username}")
            if row["role"] not in {"MANUFACTURER", "DISTRIBUTOR", "RETAILER"}:
                raise PasswordSetupError(f"{username} is not a staff supply-chain role")
            stamp = (
                datetime.now(timezone.utc)
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z")
            )
            conn.execute(
                """
                UPDATE users
                SET password_hash = ?,
                    credential_scheme = 'scrypt',
                    password_reset_required = 0,
                    credentials_updated_at = ?,
                    status = 'ACTIVE'
                WHERE user_id = ?
                """,
                (hash_password(password), stamp, row["user_id"]),
            )
            conn.execute(
                """
                INSERT INTO audit_log(
                    actor_user_id, organization_id, action, entity_type, entity_id, details, details_json
                ) VALUES (NULL, ?, 'LOCAL_PASSWORD_SETUP', 'USER', ?, 'Password set by local operator; no secret logged', '{}')
                """,
                (row["organization_id"], str(row["user_id"])),
            )
            enabled.append(username)

        blocked = conn.execute(
            """
            SELECT username, role FROM users
            WHERE username IN ({})
            """.format(",".join("?" for _ in BLOCKED_USERNAMES)),
            tuple(BLOCKED_USERNAMES),
        ).fetchall()
        for row in blocked:
            conn.execute(
                """
                UPDATE users
                SET status = 'DISABLED', password_reset_required = 1
                WHERE username = ?
                """,
                (row["username"],),
            )
        conn.commit()
        return enabled
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    db = Path(os.environ.get("DATABASE_PATH", ROOT / "laptop_anti_counterfeit.db"))
    if not db.is_absolute():
        db = ROOT / db
    enabled = enable_staff_passwords(db)
    print("enabled:", ", ".join(enabled))
    print("blocked from API login: admin/regulator/auditor/logistics")


if __name__ == "__main__":
    main()
