import os
import shutil
import tempfile
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent

JWT_ALGORITHM = "HS256"
ALLOWED_LOGIN_ROLES = frozenset({"MANUFACTURER", "DISTRIBUTOR", "RETAILER"})
BLOCKED_LOGIN_ROLES = frozenset({"ADMIN", "REGULATOR", "AUDITOR", "LOGISTICS"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_path: Path = Field(default=ROOT / "laptop_anti_counterfeit.db")
    jwt_secret: str = Field(default="dev-only-change-me-32-bytes-minimum")
    jwt_issuer: str = "tracetrust"
    jwt_audience: str = "tracetrust-api"
    jwt_ttl_seconds: int = 900
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    keystore_path: Path | None = None
    org_private_key_manufacturer: str | None = None
    org_private_key_distributor: str | None = None
    org_private_key_retailer: str | None = None
    rpc_url: str = "http://127.0.0.1:8545"
    chain_id: int = 31337
    governance_private_key: str | None = None
    contract_address: str | None = None
    deployment_id: str = "local-hardhat-v1"
    receipt_timeout_seconds: float = 30.0
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_starttls: bool = True

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


def _writable_copy(path: Path) -> Path:
    """Vercel can read the bundled database but cannot write next to the code."""
    parent_writable = os.access(path.parent, os.W_OK)
    file_writable = not path.exists() or os.access(path, os.W_OK)
    if parent_writable and file_writable:
        return path
    runtime = Path(tempfile.gettempdir()) / path.name
    if path.exists():
        shutil.copy2(path, runtime)
    return runtime


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if not settings.database_path.is_absolute():
        settings.database_path = (ROOT / settings.database_path).resolve()
    settings.database_path = _writable_copy(settings.database_path)
    if settings.keystore_path is None:
        candidate = ROOT / "keystore.json"
        if candidate.exists():
            settings.keystore_path = candidate
    elif not settings.keystore_path.is_absolute():
        settings.keystore_path = (ROOT / settings.keystore_path).resolve()
    return settings
