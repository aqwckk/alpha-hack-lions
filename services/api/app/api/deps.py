"""Authentication dependency: Bearer JWT, role from the token only, user re-checked in the database."""

from __future__ import annotations

import uuid

import jwt
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..enums import ActorType
from ..errors import Forbidden, Unauthorized
from ..logging_setup import actor_var, request_id_var
from ..models import User
from ..security import decode_access_token
from ..services.core import Actor


def client_ip(request: Request) -> str | None:
    """Behind the trusted reverse proxy (nginx) the real address comes in X-Real-IP."""
    if get_settings().app_env != "test" and request.headers.get("x-real-ip"):
        return request.headers["x-real-ip"][:64]
    return request.client.host if request.client else None


def current_actor(request: Request, session: Session = Depends(get_db)) -> Actor:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise Unauthorized()
    try:
        claims = decode_access_token(token.strip())
        user_id = uuid.UUID(claims["sub"])
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise Unauthorized("Сессия истекла, войдите снова", code="TOKEN_INVALID") from exc
    user = session.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    if user is None or not user.is_active or user.role != claims.get("role"):
        raise Unauthorized("Сессия недействительна, войдите снова", code="TOKEN_INVALID")
    actor = Actor.from_user(user, ip=client_ip(request), user_agent=request.headers.get("user-agent"), correlation_id=request_id_var.get() or uuid.uuid4().hex)
    actor_var.set({"user_id": str(user.id), "role": user.role, "login": user.login, "ip": actor.ip, "ua": actor.user_agent})
    return actor


def require(*roles: ActorType):
    def dep(actor: Actor = Depends(current_actor)) -> Actor:
        if actor.type not in roles:
            raise Forbidden(code="ROLE_NOT_ALLOWED")
        return actor

    return dep


client_actor = require(ActorType.CLIENT)
staff_actor = require(ActorType.UNDERWRITER, ActorType.RISK_MANAGER)
underwriter_actor = require(ActorType.UNDERWRITER)
risk_actor = require(ActorType.RISK_MANAGER)
