"""Register a few confirmed units that stay with the manufacturer."""
from __future__ import annotations

import os
from uuid import uuid4

from dotenv import load_dotenv
from fastapi.testclient import TestClient

from backend.config import ROOT, get_settings


def main() -> None:
    load_dotenv(ROOT / ".env")
    get_settings.cache_clear()
    from backend.main import create_app

    password = os.environ.get("DEMO_MANUFACTURER_PASSWORD", "")
    app = create_app()
    with TestClient(app) as client:
        login = client.post(
            "/auth/login",
            json={"username": "demo_manufacturer", "password": password},
        )
        if login.status_code != 200:
            raise SystemExit(f"login failed: {login.status_code} {login.text}")
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        batches = client.get("/batches", headers=headers).json()
        warehouses = client.get("/warehouses", headers=headers).json()
        existing = client.get("/inventory", headers=headers).json()
        needed = max(0, 3 - len(existing))
        for _ in range(needed):
            body = {
                "batch_id": batches[0]["batch_id"],
                "warehouse_id": warehouses[0]["warehouse_id"],
                "serial_number": f"MFR-KEEP-{uuid4().hex[:10].upper()}",
                "box_serial": f"BOX-KEEP-{uuid4().hex[:10].upper()}",
                "seal_id": f"SEAL-KEEP-{uuid4().hex[:10].upper()}",
            }
            created = client.post(
                "/products",
                json=body,
                headers={**headers, "Idempotency-Key": str(uuid4())},
            )
            print(created.status_code, created.json().get("chain_status"), created.json().get("product_uid"))
            if created.status_code != 202:
                raise SystemExit(created.text)
        inventory = client.get("/inventory", headers=headers).json()
        print("manufacturer_inventory", len(inventory))


if __name__ == "__main__":
    main()
