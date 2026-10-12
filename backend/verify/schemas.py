from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.products.gps import GpsIn


class VerifyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    qr_payload: str | None = Field(default=None, max_length=256)
    token: str | None = Field(default=None, max_length=128)
    product_uid: str | None = Field(default=None, max_length=64)
    gps: GpsIn | None = None

    @model_validator(mode="after")
    def require_one(self) -> "VerifyIn":
        if not any([self.qr_payload, self.token, self.product_uid]):
            raise ValueError("qr_payload, token, or product_uid is required")
        return self
