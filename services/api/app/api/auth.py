"""Login with rate limiting, short-lived access JWT, rotating refresh token in an HttpOnly cookie."""

from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..enums import ActorType
from ..errors import TooManyRequests, Unauthorized
from ..models import Company, CompanyMembership, LoginAttempt, RefreshToken, User
from ..schemas import ErrorResponse, LoginRequest, TokenResponse, UserInfo
from ..security import (
    create_access_token,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)
from ..services.core import Actor, audit, emit, utcnow
from .deps import client_ip, current_actor

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
COOKIE = "refresh_token"
COOKIE_PATH = "/api/v1/auth"
IP_LIMIT_PER_MINUTE = 30


def _user_info(session: Session, user: User) -> UserInfo:
    inns = []
    if user.role == "CLIENT":
        inns = list(
            session.execute(
                select(Company.inn).join(CompanyMembership, CompanyMembership.company_id == Company.id).where(CompanyMembership.user_id == user.id).order_by(Company.inn)
            ).scalars()
        )
    return UserInfo(id=str(user.id), login=user.login, role=user.role, full_name=user.full_name, representative_role=user.representative_role, company_inns=inns)


def _issue(session: Session, response: Response, user: User, family: uuid.UUID | None = None) -> TokenResponse:
    s = get_settings()
    token, ttl = create_access_token(user.id, user.role, user.login)
    raw, digest = new_refresh_token()
    session.add(RefreshToken(id=uuid.uuid4(), user_id=user.id, family_id=family or uuid.uuid4(), token_hash=digest, expires_at=utcnow() + timedelta(seconds=s.refresh_token_ttl_seconds)))
    response.set_cookie(COOKIE, raw, max_age=s.refresh_token_ttl_seconds, httponly=True, secure=s.refresh_cookie_secure, samesite="strict", path=COOKIE_PATH)
    return TokenResponse(access_token=token, expires_in=ttl, user=_user_info(session, user))


@router.post("/login", response_model=TokenResponse, responses={401: {"model": ErrorResponse}, 429: {"model": ErrorResponse}})
def login(body: LoginRequest, request: Request, response: Response, session: Session = Depends(get_db)) -> TokenResponse:
    """Login and password of a test account. After 5 failures the login is paused for 1 minute."""
    s = get_settings()
    ip = client_ip(request)
    login_name = body.login.strip().lower()
    since = utcnow() - timedelta(seconds=s.login_lockout_seconds)
    failures = session.execute(select(func.count()).select_from(LoginAttempt).where(LoginAttempt.login == login_name, LoginAttempt.success.is_(False), LoginAttempt.attempted_at > since)).scalar_one()
    by_ip = session.execute(select(func.count()).select_from(LoginAttempt).where(LoginAttempt.ip_address == ip, LoginAttempt.success.is_(False), LoginAttempt.attempted_at > utcnow() - timedelta(minutes=1))).scalar_one()
    if failures >= s.login_max_failures or by_ip >= IP_LIMIT_PER_MINUTE:
        raise TooManyRequests("Слишком много попыток входа, попробуйте через минуту", code="LOGIN_RATE_LIMITED", headers={"Retry-After": str(s.login_lockout_seconds)})
    user = session.execute(select(User).where(func.lower(User.login) == login_name)).scalar_one_or_none()
    ok = verify_password(user.password_hash if user else None, body.password) and user is not None and user.is_active
    ua = request.headers.get("user-agent")
    if user is not None:
        actor = Actor.from_user(user, ip=ip, user_agent=ua, correlation_id=request.state.request_id)
    else:
        actor = Actor(type=ActorType.CLIENT, user_id=None, login=login_name[:64], ip=ip, user_agent=ua, correlation_id=request.state.request_id)
    session.add(LoginAttempt(login=login_name[:64], ip_address=ip, success=ok))
    if not ok:
        emit(session, "LOGIN_FAILED", actor, payload={"role": user.role if user else None, "reason": "BAD_CREDENTIALS"})
        audit(session, actor, "LOGIN", result="DENIED", details={"reason": "BAD_CREDENTIALS"})
        session.commit()
        raise Unauthorized("Неверный логин или пароль", code="INVALID_CREDENTIALS")
    emit(session, "USER_LOGGED_IN", actor, payload={"role": user.role})
    audit(session, actor, "LOGIN")
    result = _issue(session, response, user)
    session.commit()
    return result


@router.post("/refresh", response_model=TokenResponse, responses={401: {"model": ErrorResponse}})
def refresh(request: Request, response: Response, session: Session = Depends(get_db)) -> TokenResponse:
    """Rotate the refresh token (HttpOnly cookie). Reuse of a rotated token revokes the whole family."""
    raw = request.cookies.get(COOKIE)
    if not raw:
        raise Unauthorized(code="REFRESH_MISSING")
    row = session.execute(select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw)).with_for_update()).scalar_one_or_none()
    now = utcnow()
    if row is None or row.revoked_at is not None or row.expires_at <= now:
        raise Unauthorized("Сессия истекла, войдите снова", code="REFRESH_INVALID")
    if row.used_at is not None:
        session.execute(update(RefreshToken).where(RefreshToken.family_id == row.family_id).values(revoked_at=now))
        session.commit()
        raise Unauthorized("Сессия отозвана, войдите снова", code="REFRESH_REUSED")
    user = session.get(User, row.user_id)
    if user is None or not user.is_active:
        raise Unauthorized(code="REFRESH_INVALID")
    row.used_at = now
    result = _issue(session, response, user, family=row.family_id)
    session.commit()
    return result


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, session: Session = Depends(get_db)) -> Response:
    raw = request.cookies.get(COOKIE)
    if raw:
        row = session.execute(select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw))).scalar_one_or_none()
        if row is not None:
            session.execute(update(RefreshToken).where(RefreshToken.family_id == row.family_id).values(revoked_at=utcnow()))
            session.commit()
    response.delete_cookie(COOKIE, path=COOKIE_PATH)
    response.status_code = 204
    return response


@router.get("/me", response_model=UserInfo)
def me(actor: Actor = Depends(current_actor), session: Session = Depends(get_db)) -> UserInfo:
    return _user_info(session, session.get(User, actor.user_id))
