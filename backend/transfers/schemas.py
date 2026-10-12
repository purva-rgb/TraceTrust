from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.products.gps import GpsIn
from backend.products.schemas import WarehouseOut


class TransferCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recipient_organization_id: int
    destination_warehouse_id: int
    source_warehouse_id: int | None = None
    product_uids: list[str] = Field(min_length=1, max_length=20)
    gps: GpsIn | None = None

    @field_validator("product_uids")
    @classmethod
    def nonempty_uids(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned):
            raise ValueError("product_uids must be nonempty")
        return cleaned


class ReceiptItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_uid: str = Field(min_length=1, max_length=64)
    box_serial: str = Field(min_length=1, max_length=128)
    seal_id: str = Field(min_length=1, max_length=128)
    condition: Literal["INTACT", "BROKEN", "MISSING", "UNKNOWN"] = "INTACT"
    mode: Literal["SEALED"] = "SEALED"
    gps: GpsIn | None = None

    @field_validator("product_uid", "box_serial", "seal_id")
    @classmethod
    def strip_nonempty(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must be nonempty")
        return text


class ReceiptsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[ReceiptItemIn] = Field(min_length=1)
    gps: GpsIn | None = None


class AcceptIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gps: GpsIn | None = None


class OrganizationOut(BaseModel):
    organization_id: int
    organization_uid: str
    organization_name: str
    organization_type: str
    status: str
    username: str | None = None
    email: str | None = None
    warehouses: list[WarehouseOut] = []


class TransferItemOut(BaseModel):
    product_uid: str
    expected_box_serial: str | None = None
    expected_seal_id: str | None = None
    item_outcome: str
    laptop_internal_serial_check: str = "NOT_CHECKED"


class TransferOut(BaseModel):
    transfer_uid: str
    transfer_status: str
    chain_status: str
    sender_organization_id: int
    recipient_organization_id: int
    source_warehouse_id: int | None
    destination_warehouse_id: int | None
    expires_at: str | None
    expired: bool
    items: list[TransferItemOut]
    location_check: str | None = None


class TransferListOut(BaseModel):
    transfer_uid: str
    transfer_status: str
    chain_status: str
    sender_organization_id: int
    recipient_organization_id: int
    expires_at: str | None
    expired: bool
    item_count: int


class TransferOperationOut(BaseModel):
    operation_uid: str
    chain_status: str
    status_url: str
    transfer_uid: str


class ReceiptsOut(BaseModel):
    transfer_uid: str
    location_check: str
    laptop_internal_serial_check: str = "NOT_CHECKED"
    items: list[TransferItemOut]
