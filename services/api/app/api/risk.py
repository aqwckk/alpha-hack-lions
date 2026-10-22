"""Risk manager: funnel and operational metrics from events, config versions, audit journal."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..domain.configs import get_registry
from ..errors import NotFound
from ..models import AuditLog, ConfigVersion
from ..services import metrics as metrics_service
from ..services.core import Actor
from .deps import risk_actor, staff_actor

router = APIRouter(prefix="/api/v1/risk", tags=["risk manager"])


@router.get("/metrics")
def metrics(
    period_days: int | None = Query(30, ge=1, le=366),
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    product_code: str | None = None,
    actor: Actor = Depends(risk_actor),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """BK-06 metrics (docs/analytics/metrics.md) by cohort of APPLICATION_CREATED in the period, including the imported synthetic history."""
    start, end = metrics_service.period(period_days, date_from, date_to, datetime.now(timezone.utc))
    return metrics_service.compute(session, start, end, product_code)


@router.get("/configs")
def configs(actor: Actor = Depends(staff_actor), session: Session = Depends(get_db)) -> dict[str, Any]:
    """Active scorecard and policy (version, sha256, author, date) and all versions ever loaded."""
    sc, pol = get_registry().require()
    rows = session.execute(select(ConfigVersion).order_by(ConfigVersion.config_type, ConfigVersion.first_loaded_at.desc())).scalars()
    return {
        "active": [
            {"config_type": c.config_type, "version": c.version, "sha256": c.sha256, "author": c.author, "effective_from": c.effective_from, "description": c.content.get("description"), "file": c.path}
            for c in (sc, pol)
        ],
        "history": [
            {"config_type": r.config_type, "version": r.version, "sha256": r.sha256, "author": r.author, "effective_from": r.effective_from, "first_loaded_at": r.first_loaded_at.isoformat(), "last_loaded_at": r.last_loaded_at.isoformat()}
            for r in rows
        ],
    }


@router.get("/configs/{config_type}")
def config_content(config_type: Literal["SCORECARD", "POLICY"], actor: Actor = Depends(risk_actor)) -> dict[str, Any]:
    """Read-only parameters of the active version (products, thresholds, rate matrix, factors and bins)."""
    sc, pol = get_registry().require()
    c = sc if config_type == "SCORECARD" else pol
    return {"version": c.version, "sha256": c.sha256, "content": c.content}


@router.get("/audit")
def audit_log(
    action: str | None = None,
    actor_login: str | None = None,
    application_id: str | None = None,
    access_only: bool = Query(False, description="Only card views and document downloads"),
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    actor: Actor = Depends(risk_actor),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """BK-08: who did what, when and from where (commands, logins, views of personal data, downloads)."""
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if actor_login:
        stmt = stmt.where(AuditLog.actor_login == actor_login)
    if application_id:
        try:
            import uuid

            stmt = stmt.where(AuditLog.application_id == uuid.UUID(application_id))
        except ValueError as exc:
            raise NotFound() from exc
    if access_only:
        stmt = stmt.where(AuditLog.action.in_(["VIEW_APPLICATION", "DOWNLOAD_DOCUMENT"]))
    if date_from:
        stmt = stmt.where(AuditLog.occurred_at >= date_from)
    if date_to:
        stmt = stmt.where(AuditLog.occurred_at < date_to)
    total = session.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = session.execute(stmt.order_by(AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size)).scalars()
    return {
        "items": [
            {"id": r.id, "occurred_at": r.occurred_at.isoformat(), "actor_login": r.actor_login, "actor_role": r.actor_role, "action": r.action, "result": r.result,
             "object_type": r.object_type, "object_id": r.object_id, "application_id": str(r.application_id) if r.application_id else None,
             "ip_address": r.ip_address, "user_agent": r.user_agent, "request_id": r.request_id, "details": r.details}
            for r in rows
        ],
        "page": page,
        "page_size": page_size,
        "total": total,
    }
