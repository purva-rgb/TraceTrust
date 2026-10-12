from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.auth.deps import CurrentUser, get_current_user
from backend.errors import api_error
from backend.fusion.service import decide_incident, full_assessment, get_incident, list_incidents

router = APIRouter(tags=["fusion"])


class IncidentDecision(BaseModel):
    decision: Literal["ignore", "freeze"]


@router.get("/products/{uid}/assessment")
def product_assessment(
    uid: str,
    _actor: Annotated[CurrentUser, Depends(get_current_user)],
) -> dict[str, Any]:
    body = full_assessment(uid)
    if body is None:
        raise api_error(404, "NOT_FOUND", "product not found")
    return body


@router.get("/incidents")
def incidents(_actor: Annotated[CurrentUser, Depends(get_current_user)]) -> list[dict[str, Any]]:
    return list_incidents()


@router.get("/incidents/{incident_id}")
def incident_detail(
    incident_id: int,
    _actor: Annotated[CurrentUser, Depends(get_current_user)],
) -> dict[str, Any]:
    body = get_incident(incident_id)
    if body is None:
        raise api_error(404, "NOT_FOUND", "incident not found")
    return body


@router.post("/incidents/{incident_id}/decision")
def incident_decision(
    incident_id: int,
    body: IncidentDecision,
    _actor: Annotated[CurrentUser, Depends(get_current_user)],
) -> dict[str, Any]:
    return decide_incident(incident_id, body.decision)
