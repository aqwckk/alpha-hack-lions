"""Idempotency-Key for user commands: the same key and payload returns the stored result, never a second effect.

The key row is inserted in the same transaction as the command. A concurrent duplicate waits on the
unique index until the first transaction ends, then replays its stored response. A failed command
rolls the key back, so a corrected retry with the same key is possible.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..errors import ApiError, Conflict
from ..models import IdempotencyKey
from .core import Actor


def _fingerprint(scope: str, payload: Any) -> str:
    return hashlib.sha256(json.dumps({"scope": scope, "payload": payload}, sort_keys=True, default=str).encode()).hexdigest()


def run(session: Session, actor: Actor, key: str | None, scope: str, payload: Any, fn: Callable[[], tuple[int, dict[str, Any]]], *, required: bool = True) -> tuple[int, dict[str, Any], bool]:
    if not key:
        if required:
            raise ApiError("Передайте заголовок Idempotency-Key", code="IDEMPOTENCY_KEY_REQUIRED", status=400)
        status, body = fn()
        session.commit()
        return status, body, False
    if len(key) > 128 or not all(c.isalnum() or c in "-_:." for c in key):
        raise ApiError("Некорректный Idempotency-Key", code="IDEMPOTENCY_KEY_INVALID", status=400)
    digest = _fingerprint(scope, payload)
    inserted = session.execute(
        insert(IdempotencyKey)
        .values(id=uuid.uuid4(), user_id=actor.user_id, key=key, scope=scope, request_hash=digest)
        .on_conflict_do_nothing(constraint="uq_idempotency_user_key")
        .returning(IdempotencyKey.id)
    ).scalar_one_or_none()
    if inserted is None:
        row = session.execute(select(IdempotencyKey).where(IdempotencyKey.user_id == actor.user_id, IdempotencyKey.key == key)).scalar_one()
        if row.request_hash != digest:
            raise ApiError("Ключ идемпотентности уже использован с другим запросом", code="IDEMPOTENCY_KEY_REUSED", status=422)
        if row.response_status is None:
            raise Conflict("Запрос с этим ключом еще выполняется", code="IDEMPOTENCY_IN_PROGRESS")
        session.rollback()
        return row.response_status, row.response_body or {}, True
    status, body = fn()
    session.execute(update(IdempotencyKey).where(IdempotencyKey.id == inserted).values(response_status=status, response_body=json.loads(json.dumps(body, default=str))))
    session.commit()
    return status, body, False
