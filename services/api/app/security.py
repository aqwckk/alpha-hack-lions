"""Passwords (argon2id), JWT access tokens (HS256, fixed algorithm), refresh tokens and signing codes."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from .config import get_settings
from .db import session_scope
from .models import SystemSecret

_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
# verify against this hash for unknown logins so the response time does not reveal existing accounts
_DUMMY_HASH = _hasher.hash("timing-equalizer-not-a-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def ensure_secret(name: str, nbytes: int = 48) -> str:
    """Return a persisted random secret, creating it once (shared by all API replicas)."""
    with session_scope() as session:
        session.execute(
            insert(SystemSecret).values(name=name, value=secrets.token_urlsafe(nbytes)).on_conflict_do_nothing(index_elements=["name"])
        )
        return session.execute(select(SystemSecret.value).where(SystemSecret.name == name)).scalar_one()


@lru_cache
def jwt_key() -> str:
    configured = get_settings().jwt_secret
    if configured:
        if len(configured) < 32:
            raise RuntimeError("JWT_SECRET must be at least 32 characters")
        return configured
    return ensure_secret("jwt_signing_key")


@lru_cache
def code_pepper() -> bytes:
    return ensure_secret("signing_code_pepper").encode()


def create_access_token(user_id: uuid.UUID, role: str, login: str) -> tuple[str, int]:
    s = get_settings()
    now = datetime.now(timezone.utc)
    claims = {
        "sub": str(user_id),
        "role": role,
        "login": login,
        "iss": s.jwt_issuer,
        "aud": s.jwt_audience,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=s.access_token_ttl_seconds)).timestamp()),
        "jti": uuid.uuid4().hex,
        "typ": "access",
    }
    return jwt.encode(claims, jwt_key(), algorithm="HS256"), s.access_token_ttl_seconds


def decode_access_token(token: str) -> dict[str, Any]:
    s = get_settings()
    claims = jwt.decode(
        token,
        jwt_key(),
        algorithms=["HS256"],
        audience=s.jwt_audience,
        issuer=s.jwt_issuer,
        options={"require": ["exp", "iat", "sub", "iss", "aud", "jti"]},
        leeway=5,
    )
    if claims.get("typ") != "access":
        raise jwt.InvalidTokenError("wrong token type")
    return claims


def new_refresh_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(48)
    return raw, hashlib.sha256(raw.encode()).hexdigest()


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def new_signing_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_signing_code(code_id: uuid.UUID, code: str) -> str:
    return hmac.new(code_pepper(), f"{code_id}:{code}".encode(), hashlib.sha256).hexdigest()


def code_matches(code_id: uuid.UUID, code: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_signing_code(code_id, code), expected_hash)
