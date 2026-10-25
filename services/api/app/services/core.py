"""Single point of status change and the side effects that share its transaction.

apply_transition(): checks the transition table, role, guards and expected_version, performs a
conditional UPDATE (WHERE id AND status AND version), writes status history, STATUS_CHANGED,
audit and returns the refreshed application. Domain events, notifications and jobs are added by the
caller in the same session, so everything commits or rolls back together (transactional outbox).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from prometheus_client import Counter
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..domain.dictionaries import NOTIFICATIONS, render
from ..domain.statemachine import GuardContext, guard_failure, processing_retry_target, resolve
from ..enums import ActorType, Role, Status
from ..errors import (
    ApiError,
    Conflict,
    Forbidden,
    NotFound,
    invalid_transition,
    version_conflict,
)
from ..models import (
    Application,
    AuditLog,
    Decision,
    Event,
    Job,
    Notification,
    Offer,
    ScoringResult,
    StatusHistory,
    User,
)

log = logging.getLogger("app.core")

TRANSITIONS_TOTAL = Counter("credit_transitions_total", "Application status transitions", ["transition", "to_status"])
EVENTS_TOTAL = Counter("credit_events_total", "Domain events written", ["event_type"])


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Actor:
    type: ActorType
    user_id: uuid.UUID | None
    login: str | None = None
    role: str | None = None
    ip: str | None = None
    user_agent: str | None = None
    correlation_id: str = "system"
    full_name: str | None = None

    @property
    def is_client(self) -> bool:
        return self.type == ActorType.CLIENT

    @property
    def is_staff(self) -> bool:
        return self.type in (ActorType.UNDERWRITER, ActorType.RISK_MANAGER)

    @classmethod
    def system(cls, correlation_id: str) -> Actor:
        return cls(ActorType.SYSTEM, None, login="system", correlation_id=correlation_id)

    @classmethod
    def timer(cls, correlation_id: str) -> Actor:
        return cls(ActorType.TIMER, None, login="timer", correlation_id=correlation_id)

    @classmethod
    def from_user(cls, user: User, *, ip: str | None, user_agent: str | None, correlation_id: str) -> Actor:
        return cls(ActorType(user.role), user.id, user.login, user.role, ip, user_agent, correlation_id, user.full_name)


def emit(session: Session, event_type: str, actor: Actor, *, application: Application | None = None, application_id=None, payload: dict[str, Any] | None = None, occurred_at: datetime | None = None) -> Event:
    """Append a domain event (no personal data in the payload)."""
    ev = Event(
        event_id=uuid.uuid4(),
        event_type=event_type,
        occurred_at=occurred_at or utcnow(),
        application_id=application.id if application is not None else application_id,
        actor_type=actor.type.value,
        actor_id=actor.user_id,
        correlation_id=actor.correlation_id[:64],
        application_version=application.version if application is not None else None,
        payload=payload or {},
    )
    session.add(ev)
    EVENTS_TOTAL.labels(event_type).inc()
    return ev


def audit(session: Session, actor: Actor, action: str, *, result: str = "SUCCESS", application_id=None, object_type: str | None = None, object_id: str | None = None, details: dict[str, Any] | None = None) -> None:
    session.add(
        AuditLog(
            occurred_at=utcnow(),
            actor_id=actor.user_id,
            actor_login=actor.login,
            actor_role=actor.role or actor.type.value,
            action=action,
            result=result,
            object_type=object_type,
            object_id=object_id,
            application_id=application_id,
            ip_address=actor.ip,
            user_agent=(actor.user_agent or "")[:512] or None,
            request_id=actor.correlation_id[:64],
            details=details or {},
        )
    )


def notify(session: Session, user_id: uuid.UUID, ntf_code: str, *, application: Application | None = None, notification_expires_at: datetime | None = None, **values: Any) -> Notification:
    title, body = NOTIFICATIONS[ntf_code]
    if application is not None:
        values.setdefault("application_number", application.application_number)
    n = Notification(
        id=uuid.uuid4(),
        user_id=user_id,
        application_id=application.id if application is not None else None,
        code=ntf_code,
        title=title,
        body=render(body, values) or "",
        created_at=utcnow(),
        expires_at=notification_expires_at,
    )
    session.add(n)
    return n


def notify_role(session: Session, role: Role, ntf_code: str, *, application: Application, **values: Any) -> None:
    for uid in session.execute(select(User.id).where(User.role == role.value, User.is_active.is_(True), User.password_hash.is_not(None))).scalars():
        notify(session, uid, ntf_code, application=application, **values)


def enqueue(session: Session, kind: str, application: Application, *, correlation_id: str, run_at: datetime | None = None, idempotency_key: str | None = None, payload: dict[str, Any] | None = None, max_attempts: int | None = None) -> None:
    from ..config import get_settings

    values = dict(
        id=uuid.uuid4(),
        kind=kind,
        application_id=application.id,
        expected_status=application.status,
        payload=payload or {},
        status="QUEUED",
        run_at=run_at or utcnow(),
        attempts=0,
        max_attempts=max_attempts or get_settings().job_max_attempts,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id[:64],
    )
    stmt = insert(Job).values(**values)
    if idempotency_key:
        stmt = stmt.on_conflict_do_nothing(index_elements=["idempotency_key"])
    session.execute(stmt)


def guard_context(session: Session, app: Application, actor: Actor, *, now: datetime | None = None) -> GuardContext:
    from ..domain.configs import get_registry

    proposer = None
    if app.status == Status.PENDING_RISK_APPROVAL:
        proposer = session.execute(
            select(Decision.proposed_by).where(Decision.application_id == app.id, Decision.status == "PROPOSED").order_by(Decision.created_at.desc()).limit(1)
        ).scalar_one_or_none()
    offer_expires = None
    if app.current_offer_id is not None:
        offer_expires = session.execute(select(Offer.expires_at).where(Offer.id == app.current_offer_id)).scalar_one_or_none()
    has_scoring = session.execute(select(ScoringResult.id).where(ScoringResult.application_id == app.id).limit(1)).first() is not None
    try:
        max_cycles = get_registry().policy_content()["process"]["max_auto_info_cycles"]
    except Exception:  # noqa: BLE001 (configs unavailable: the default from the spec)
        max_cycles = 3
    from ..config import get_settings

    return GuardContext(
        actor_type=actor.type,
        actor_id=actor.user_id,
        owner_id=app.client_user_id,
        assignee_id=app.assignee_id,
        proposer_id=proposer,
        failed_stage=app.failed_stage,
        offer_expires_at=offer_expires,
        now=now or utcnow(),
        has_scoring=has_scoring,
        manual_review_required=app.manual_review_required,
        auto_info_request_count=app.auto_info_request_count,
        max_auto_info_cycles=max_cycles,
        enrichment_retry_count=app.enrichment_retry_count,
        max_enrichment_retries=len(get_settings().retry_schedule),
    )


GUARD_ERRORS: dict[str, type[ApiError] | tuple[int, str]] = {
    "NOT_FOUND": NotFound,
    "NOT_ASSIGNEE": (403, "Решение может принять только исполнитель заявки"),
    "FOUR_EYES_SAME_USER": (403, "Автор проекта решения не может его подтвердить"),
    "OFFER_EXPIRED": (409, "Срок предложения истек"),
    "SCORING_REQUIRED": (409, "Нельзя одобрить заявку без результата скоринга"),
}


def raise_guard(code: str, app: Application, actor: Actor) -> None:
    mapped = GUARD_ERRORS.get(code)
    if mapped is NotFound:
        raise NotFound()
    if isinstance(mapped, tuple):
        status, message = mapped
        raise ApiError(message, code=code, status=status)
    raise invalid_transition(app.status, None, internal=not actor.is_client) if code == "INVALID_TRANSITION" else Conflict(code=code, details={"guard": code})


def apply_transition(
    session: Session,
    app: Application,
    transition_id: str,
    actor: Actor,
    *,
    trigger: str,
    expected_version: int | None,
    changes: dict[str, Any] | None = None,
    ctx: GuardContext | None = None,
    client_status: str | None = None,
) -> Application:
    t = resolve(transition_id, app.status, trigger)
    if t is None:
        raise invalid_transition(app.status, client_status, internal=not actor.is_client)
    if actor.type not in t.actors:
        raise Forbidden(code="ROLE_NOT_ALLOWED")
    if t.guards:
        ctx = ctx or guard_context(session, app, actor)
        for g in t.guards:
            failure = guard_failure(g, ctx)
            if failure:
                raise_guard(failure, app, actor)
    if expected_version is not None and expected_version != app.version:
        raise version_conflict(app.version)

    target = t.target or processing_retry_target(app.failed_stage, app.last_error_code)
    if target is None:
        raise Conflict(code="FAILED_STAGE_MISSING")
    now = utcnow()
    from_status, from_version = app.status, app.version
    values: dict[str, Any] = dict(changes or {})
    values.update(status=target, version=from_version + 1, updated_at=now, status_changed_at=now)
    if target in (Status.ISSUED, Status.DECLINED, Status.OFFER_DECLINED, Status.OFFER_EXPIRED, Status.CANCELLED):
        values.setdefault("closed_at", now)
    result = session.execute(
        update(Application)
        .where(Application.id == app.id, Application.status == from_status, Application.version == from_version)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        session.expire(app)
        session.refresh(app)
        if app.status != from_status:
            raise invalid_transition(app.status, client_status, internal=not actor.is_client)
        raise version_conflict(app.version)
    session.refresh(app)
    session.add(
        StatusHistory(
            application_id=app.id,
            from_status=from_status,
            to_status=target,
            transition_id=t.id,
            trigger=trigger,
            actor_type=actor.type.value,
            actor_id=actor.user_id,
            version=app.version,
            occurred_at=now,
        )
    )
    key = "command" if actor.type not in (ActorType.SYSTEM, ActorType.TIMER) else "trigger"
    emit(session, "STATUS_CHANGED", actor, application=app, occurred_at=now, payload={"from_status": from_status, "to_status": target, "transition_id": t.id, key: trigger})
    if actor.user_id is not None:
        audit(session, actor, trigger, application_id=app.id, object_type="application", object_id=str(app.id), details={"transition_id": t.id, "from_status": from_status, "to_status": target})
    TRANSITIONS_TOTAL.labels(t.id, target).inc()
    log.info("transition", extra={"fields": {"application_id": str(app.id), "transition_id": t.id, "from": from_status, "to": target}})
    return app


def bump_version(session: Session, app: Application, actor: Actor, *, expected_version: int | None, changes: dict[str, Any], allowed_statuses: tuple[str, ...]) -> Application:
    """Change application data without a status change (UPDATE_DRAFT, consents, documents, answers)."""
    if app.status not in allowed_statuses:
        raise invalid_transition(app.status, None, internal=not actor.is_client)
    if expected_version is not None and expected_version != app.version:
        raise version_conflict(app.version)
    now = utcnow()
    result = session.execute(
        update(Application)
        .where(Application.id == app.id, Application.version == app.version, Application.status == app.status)
        .values(**changes, version=app.version + 1, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        session.expire(app)
        session.refresh(app)
        raise version_conflict(app.version)
    session.refresh(app)
    return app


def due(seconds: float) -> datetime:
    return utcnow() + timedelta(seconds=seconds)
