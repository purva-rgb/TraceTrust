from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, status

from backend.auth.deps import CurrentUser, get_current_user, require_roles
from backend.chain.adapter import ChainClient
from backend.chain.deps import get_chain
from backend.errors import api_error
from backend.products import service
from backend.products.schemas import (
    BatchOut,
    InventoryItem,
    LabelOut,
    OperationAccepted,
    OperationOut,
    ProductCreate,
    QrLabelOut,
    WarehouseOut,
)

router = APIRouter(tags=["catalog"])


@router.get("/batches", response_model=list[BatchOut])
def get_batches(
    actor: Annotated[CurrentUser, Depends(require_roles("MANUFACTURER"))],
) -> list[BatchOut]:
    return service.list_batches(actor)


@router.get("/warehouses", response_model=list[WarehouseOut])
def get_warehouses(
    actor: Annotated[CurrentUser, Depends(get_current_user)],
) -> list[WarehouseOut]:
    return service.list_warehouses(actor)


@router.get("/inventory", response_model=list[InventoryItem])
def get_inventory(
    actor: Annotated[CurrentUser, Depends(get_current_user)],
) -> list[InventoryItem]:
    return service.list_inventory(actor)


@router.get("/labels", response_model=list[LabelOut])
def get_labels(
    actor: Annotated[CurrentUser, Depends(get_current_user)],
) -> list[LabelOut]:
    return service.list_labels(actor)


@router.post(
    "/products",
    response_model=OperationAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def post_product(
    body: ProductCreate,
    actor: Annotated[CurrentUser, Depends(require_roles("MANUFACTURER"))],
    chain: Annotated[ChainClient, Depends(get_chain)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> OperationAccepted:
    if idempotency_key is None or not idempotency_key.strip():
        raise api_error(422, "IDEMPOTENCY_REQUIRED", "Idempotency-Key header is required")
    return service.register_product(actor, body, idempotency_key.strip(), chain)


@router.get("/operations/{uid}", response_model=OperationOut)
def get_operation(
    uid: str,
    actor: Annotated[CurrentUser, Depends(get_current_user)],
) -> OperationOut:
    return service.get_operation(actor, uid)


@router.get("/products/{uid}/qr", response_model=QrLabelOut)
def get_qr_label(
    uid: str,
    actor: Annotated[CurrentUser, Depends(get_current_user)],
) -> QrLabelOut:
    return service.get_qr_label(actor, uid)
