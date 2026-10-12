from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlite3 import Connection, Row

from backend.auth.tokens import GENERIC_AUTH_FAILURE, decode_access_token
from backend.config import ALLOWED_LOGIN_ROLES, BLOCKED_LOGIN_ROLES
from backend.db import get_connection

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    user_id: int
    username: str
    email: str | None
    role: str
    status: str
    organization_id: int
    organization_uid: str
    organization_name: str
    organization_type: str
    organization_status: str
    provisioning_state: str


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=GENERIC_AUTH_FAILURE,
        headers={"WWW-Authenticate": "Bearer"},
    )


def load_staff_user(conn: Connection, user_id: int) -> CurrentUser | None:
    row = conn.execute(
        """
        SELECT
            u.user_id,
            u.username,
            u.email,
            u.role,
            u.status AS user_status,
            u.password_reset_required,
            u.organization_id,
            o.organization_uid,
            o.organization_name,
            o.organization_type,
            o.status AS organization_status,
            o.provisioning_state
        FROM users u
        JOIN organizations o ON o.organization_id = u.organization_id
        WHERE u.user_id = ?
        """,
        (user_id,),
    ).fetchone()
    if row is None:
        return None
    if row["role"] in BLOCKED_LOGIN_ROLES or row["role"] not in ALLOWED_LOGIN_ROLES:
        return None
    if row["user_status"] != "ACTIVE" or row["password_reset_required"] != 0:
        return None
    if row["organization_status"] != "ACTIVE":
        return None
    return CurrentUser(
        user_id=row["user_id"],
        username=row["username"],
        email=row["email"] if "email" in row.keys() else None,
        role=row["role"],
        status=row["user_status"],
        organization_id=row["organization_id"],
        organization_uid=row["organization_uid"],
        organization_name=row["organization_name"],
        organization_type=row["organization_type"],
        organization_status=row["organization_status"],
        provisioning_state=row["provisioning_state"],
    )


def get_optional_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> CurrentUser | None:
    if credentials is None or credentials.scheme.lower() != "bearer":
        return None
    try:
        user_id = decode_access_token(credentials.credentials)
    except ValueError:
        return None
    with get_connection() as conn:
        user = load_staff_user(conn, user_id)
    if user is None or user.role != user.organization_type:
        return None
    return user


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> CurrentUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()
    try:
        user_id = decode_access_token(credentials.credentials)
    except ValueError:
        raise _unauthorized() from None
    with get_connection() as conn:
        user = load_staff_user(conn, user_id)
    if user is None:
        raise _unauthorized()
    if user.role != user.organization_type:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return user


def require_roles(*roles: str) -> Callable[..., CurrentUser]:
    allowed = frozenset(roles)

    def _guard(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
        if user.role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        return user

    return _guard


def require_resource_org(
    resource_org_id: int | None,
    actor: CurrentUser,
    *,
    not_found: bool = False,
) -> None:
    if resource_org_id is None or not_found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if resource_org_id != actor.organization_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


def load_owned_row(
    conn: Connection,
    sql: str,
    params: tuple,
    org_column: str,
    actor: CurrentUser,
) -> Row:
    row = conn.execute(sql, params).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    require_resource_org(row[org_column], actor)
    return row
