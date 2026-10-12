"""Backup DB, apply v4, write .env if missing, enable the three staff accounts."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

from backend.config import ROOT
from backend.migrations.v4_gps import backup_and_migrate
from backend.scripts.enable_demo_passwords import STAFF_ENV, enable_staff_passwords


def _ensure_env_file() -> Path:
    path = ROOT / ".env"
    if path.exists():
        return path
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    jwt_secret = secrets.token_hex(32)
    lines = []
    for line in example.splitlines():
        if line.startswith("JWT_SECRET="):
            lines.append(f"JWT_SECRET={jwt_secret}")
        elif line.startswith("DEMO_MANUFACTURER_PASSWORD="):
            lines.append(f"DEMO_MANUFACTURER_PASSWORD={secrets.token_urlsafe(16)}")
        elif line.startswith("DEMO_DISTRIBUTOR_PASSWORD="):
            lines.append(f"DEMO_DISTRIBUTOR_PASSWORD={secrets.token_urlsafe(16)}")
        elif line.startswith("DEMO_RETAILER_PASSWORD="):
            lines.append(f"DEMO_RETAILER_PASSWORD={secrets.token_urlsafe(16)}")
        else:
            lines.append(line)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> None:
    db = ROOT / "laptop_anti_counterfeit.db"
    result = backup_and_migrate(db)
    print("backup:", result)
    env_path = _ensure_env_file()
    load_dotenv(env_path, override=True)
    missing = [name for name in STAFF_ENV.values() if len(os.environ.get(name, "")) < 12]
    if missing:
        raise SystemExit(f"missing env passwords: {missing}")
    enabled = enable_staff_passwords(db)
    print("enabled:", ", ".join(enabled))
    print("staff passwords are in .env (gitignored); admin/regulator/auditor cannot log in")


if __name__ == "__main__":
    main()
