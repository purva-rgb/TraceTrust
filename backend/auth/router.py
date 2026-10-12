from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.auth.deps import CurrentUser, get_current_user, load_staff_user
from backend.auth.passwords import verify_password
from backend.auth.signup import register_staff
from backend.auth.tokens import GENERIC_AUTH_FAILURE, issue_access_token
from backend.config import ALLOWED_LOGIN_ROLES, BLOCKED_LOGIN_ROLES
from backend.db import get_connection

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str | None = Field(default=None, max_length=128)
    username: str | None = Field(default=None, max_length=128)
    password: str = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def require_identity(self) -> "LoginRequest":
        if not (self.email or self.username):
            raise ValueError("email is required")
        return self


class SignupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=128)
    password: str = Field(min_length=8, max_length=256)
    role: str = Field(min_length=1, max_length=32)
    organization_name: str = Field(min_length=2, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeResponse(BaseModel):
    user_id: int
    username: str
    email: str | None = None
    role: str
    status: str
    organization_id: int
    organization_uid: str
    organization_name: str
    organization_type: str
    organization_status: str
    provisioning_state: str


def _reject() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=GENERIC_AUTH_FAILURE,
    )


@router.post("/register")
def signup(body: SignupRequest) -> dict:
    return register_staff(
        email=body.email,
        password=body.password,
        role=body.role,
        organization_name=body.organization_name,
    )


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest) -> TokenResponse:
    identity = (body.email or body.username or "").strip()
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT user_id, username, email, password_hash, role, status, password_reset_required,
                   credential_scheme, organization_id
            FROM users
            WHERE lower(username) = lower(?) OR (email IS NOT NULL AND lower(email) = lower(?))
            """,
            (identity, identity),
        ).fetchone()
        if row is None:
            raise _reject()
        if row["role"] in BLOCKED_LOGIN_ROLES or row["role"] not in ALLOWED_LOGIN_ROLES:
            raise _reject()
        if row["credential_scheme"] != "scrypt":
            raise _reject()
        if not verify_password(body.password, row["password_hash"]):
            raise _reject()
        staff = load_staff_user(conn, row["user_id"])
        if staff is None:
            raise _reject()
        if staff.role != staff.organization_type:
            raise _reject()
        token = issue_access_token(staff.user_id)
        return TokenResponse(access_token=token)


@router.get("/me", response_model=MeResponse)
def me(user: Annotated[CurrentUser, Depends(get_current_user)]) -> MeResponse:
    return MeResponse(
        user_id=user.user_id,
        username=user.username,
        email=user.email,
        role=user.role,
        status=user.status,
        organization_id=user.organization_id,
        organization_uid=user.organization_uid,
        organization_name=user.organization_name,
        organization_type=user.organization_type,
        organization_status=user.organization_status,
        provisioning_state=user.provisioning_state,
    )
