from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.products.gps import GpsIn


class ProductCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batch_id: int
    warehouse_id: int
    serial_number: str = Field(min_length=1, max_length=128)
    box_serial: str = Field(min_length=1, max_length=128)
    seal_id: str = Field(min_length=1, max_length=128)
    gps: GpsIn | None = None

    @field_validator("serial_number", "box_serial", "seal_id")
    @classmethod
    def strip_nonempty(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must be nonempty")
        return text


class OperationAccepted(BaseModel):
    operation_uid: str
    chain_status: str
    status_url: str
    product_uid: str | None = None
    package_uid: str | None = None
    qr_payload: str | None = None


class BatchOut(BaseModel):
    batch_id: int
    batch_number: str
    brand: str
    model_name: str
    batch_status: str
    manufacturer_id: int


class WarehouseOut(BaseModel):
    warehouse_id: int
    warehouse_code: str
    warehouse_name: str
    organization_id: int
    status: str


class InventoryItem(BaseModel):
    product_id: int
    product_uid: str
    product_code: str
    serial_number: str
    custodian_organization_id: int
    warehouse_id: int | None


class OperationOut(BaseModel):
    operation_uid: str
    operation_type: str
    status: str
    chain_status: str
    error_code: str | None = None
    error_detail: str | None = None
    created_at: str
    confirmed_at: str | None = None
    product_uid: str | None = None


class QrLabelOut(BaseModel):
    product_uid: str
    qr_payload: str
    serial_number: str
    box_serial: str
    seal_id: str


class LabelOut(BaseModel):
    product_uid: str
    qr_payload: str | None = None
    serial_number: str
    box_serial: str
    seal_id: str
    custodian: str | None = None
    warehouse_id: int | None = None
