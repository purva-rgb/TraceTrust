from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status

from backend.auth.deps import CurrentUser, get_current_user
from backend.chain.adapter import ChainClient
from backend.chain.deps import get_chain
from backend.errors import api_error
from backend.transfers import service
from backend.transfers.schemas import (
    AcceptIn,
    OrganizationOut,
    ReceiptsIn,
    ReceiptsOut,
    TransferCreate,
    TransferListOut,
    TransferOperationOut,
    TransferOut,
)

router = APIRouter(tags=["transfers"])


@router.get("/organizations", response_model=list[OrganizationOut])
def get_organizations(
    actor: Annotated[CurrentUser, Depends(get_current_user)],
    type: str | None = Query(default=None, alias="type"),
) -> list[OrganizationOut]:
    return service.list_organizations(actor, type)


@router.get("/transfers", response_model=list[TransferListOut])
def get_transfers(
    actor: Annotated[CurrentUser, Depends(get_current_user)],
) -> list[TransferListOut]:
    return service.list_transfers(actor)


@router.get("/transfers/{uid}", response_model=TransferOut)
def get_transfer(
    uid: str,
    actor: Annotated[CurrentUser, Depends(get_current_user)],
) -> TransferOut:
    return service.get_transfer(actor, uid)


@router.post(
    "/transfers",
    response_model=TransferOperationOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def post_transfer(
    body: TransferCreate,
    actor: Annotated[CurrentUser, Depends(get_current_user)],
    chain: Annotated[ChainClient, Depends(get_chain)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> TransferOperationOut:
    if idempotency_key is None or not idempotency_key.strip():
        raise api_error(422, "IDEMPOTENCY_REQUIRED", "Idempotency-Key header is required")
    return service.initiate_transfer(actor, body, idempotency_key.strip(), chain)


@router.post("/transfers/{uid}/receipts", response_model=ReceiptsOut)
def post_receipts(
    uid: str,
    body: ReceiptsIn,
    actor: Annotated[CurrentUser, Depends(get_current_user)],
) -> ReceiptsOut:
    return service.record_receipts(actor, uid, body)


@router.post(
    "/transfers/{uid}/accept",
    response_model=TransferOperationOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def post_accept(
    uid: str,
    actor: Annotated[CurrentUser, Depends(get_current_user)],
    chain: Annotated[ChainClient, Depends(get_chain)],
    body: AcceptIn | None = None,
) -> TransferOperationOut:
    return service.accept_transfer(actor, uid, body or AcceptIn(), chain)


@router.post(
    "/transfers/{uid}/reject",
    response_model=TransferOperationOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def post_reject(
    uid: str,
    actor: Annotated[CurrentUser, Depends(get_current_user)],
    chain: Annotated[ChainClient, Depends(get_chain)],
) -> TransferOperationOut:
    return service.reject_transfer(actor, uid, chain)


@router.post(
    "/transfers/{uid}/cancel",
    response_model=TransferOperationOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def post_cancel(
    uid: str,
    actor: Annotated[CurrentUser, Depends(get_current_user)],
    chain: Annotated[ChainClient, Depends(get_chain)],
) -> TransferOperationOut:
    return service.cancel_transfer(actor, uid, chain)
