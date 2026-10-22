"""Object-level access: a client sees only applications of their own companies, employees by role and tab."""

from __future__ import annotations

import uuid

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from ..enums import ActorType, Status
from ..errors import Forbidden, NotFound
from ..models import Application, CompanyMembership, Decision, StatusHistory
from .core import Actor


def client_scope(actor: Actor):
    member_companies = select(CompanyMembership.company_id).where(CompanyMembership.user_id == actor.user_id)
    return or_(Application.client_user_id == actor.user_id, Application.company_id.in_(member_companies))


def underwriter_scope(actor: Actor):
    touched = exists().where(StatusHistory.application_id == Application.id, StatusHistory.actor_id == actor.user_id)
    decided = exists().where(Decision.application_id == Application.id, or_(Decision.decided_by == actor.user_id, Decision.proposed_by == actor.user_id))
    return or_(
        Application.status.in_([Status.MANUAL_REVIEW.value, Status.PROCESSING_ERROR.value]),
        Application.assignee_id == actor.user_id,
        touched,
        decided,
    )


def load_for_client(session: Session, actor: Actor, application_id: uuid.UUID) -> Application:
    if actor.type != ActorType.CLIENT:
        raise Forbidden(code="ROLE_NOT_ALLOWED")
    app = session.execute(select(Application).where(Application.id == application_id, client_scope(actor))).scalar_one_or_none()
    if app is None:
        raise NotFound()
    return app


def load_for_staff(session: Session, actor: Actor, application_id: uuid.UUID) -> Application:
    if not actor.is_staff:
        raise Forbidden(code="ROLE_NOT_ALLOWED")
    stmt = select(Application).where(Application.id == application_id, Application.status != Status.DRAFT.value)
    if actor.type == ActorType.UNDERWRITER:
        stmt = stmt.where(underwriter_scope(actor))
    app = session.execute(stmt).scalar_one_or_none()
    if app is None:
        raise NotFound()
    return app
