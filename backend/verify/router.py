from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status

from backend.auth.deps import CurrentUser, get_optional_user
from backend.chain.adapter import ChainClient
from backend.chain.deps import get_chain_optional
from backend.errors import api_error
from backend.verify.engine import reduce_public, verify_product
from backend.verify.rate_limit import public_verify_limiter
from backend.verify.schemas import VerifyIn
from backend.verify.service import verify_request

router = APIRouter(tags=["verify"])


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


@router.post("/public/verify")
def public_verify(
    body: VerifyIn,
    request: Request,
    chain: Annotated[ChainClient | None, Depends(get_chain_optional)],
    actor: Annotated[CurrentUser | None, Depends(get_optional_user)] = None,
) -> dict[str, Any]:
    if not public_verify_limiter.allow(_client_ip(request)):
        raise api_error(status.HTTP_429_TOO_MANY_REQUESTS, "RATE_LIMITED", "too many verification requests")
    result = verify_request(body, chain, actor=actor)
    reduced = reduce_public(result)
    if "genuine" in reduced.get("headline", "").lower():
        reduced["headline"] = "Digital record verified"
    return reduced


@router.get("/products/{uid}/provenance")
def product_provenance(
    uid: str,
    chain: Annotated[ChainClient | None, Depends(get_chain_optional)],
    actor: Annotated[CurrentUser | None, Depends(get_optional_user)] = None,
) -> dict[str, Any]:
    result = verify_product(uid, chain)
    if result.get("final_status") == "UNKNOWN" and result.get("product_uid") is None:
        raise api_error(404, "NOT_FOUND", "product not found")
    try:
        from backend.fusion.service import summary_for

        result["assessment"] = summary_for(uid)
    except Exception:
        result["assessment"] = None
    if actor is None:
        return reduce_public(result)
    return result
