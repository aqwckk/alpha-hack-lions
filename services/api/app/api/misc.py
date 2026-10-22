"""Notifications inside the product, demo controls of the integrations mock, health and metrics."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..domain.configs import get_registry
from ..errors import ApiError, Forbidden, NotFound, ServiceUnavailable
from ..models import Notification
from ..schemas import OutageRequest
from ..services import integrations
from ..services.core import Actor, audit, utcnow
from .deps import current_actor, staff_actor

notifications = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])
demo = APIRouter(prefix="/api/v1/demo", tags=["demo"])
health = APIRouter(tags=["service"])
meta = APIRouter(prefix="/api/v1/meta", tags=["service"])


@meta.get("")
def public_meta() -> dict[str, bool]:
    """Public UI flags before login: demo mode (test accounts hint, demo controls) and optional AI module."""
    s = get_settings()
    return {"demo_mode": s.demo_mode, "ai_enabled": bool(s.ollama_url)}


@notifications.get("")
def list_notifications(unread_only: bool = False, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), actor: Actor = Depends(current_actor), session: Session = Depends(get_db)) -> dict[str, Any]:
    """Bell and feed (CL-14): the only channel of notifications, no email or SMS."""
    stmt = select(Notification).where(Notification.user_id == actor.user_id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    total = session.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    unread = session.execute(select(func.count()).select_from(Notification).where(Notification.user_id == actor.user_id, Notification.read_at.is_(None))).scalar_one()
    rows = session.execute(stmt.order_by(Notification.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).scalars()
    return {
        "items": [
            {"id": str(n.id), "code": n.code, "title": n.title, "body": n.body, "application_id": str(n.application_id) if n.application_id else None, "created_at": n.created_at.isoformat(), "read": n.read_at is not None}
            for n in rows
        ],
        "unread": unread,
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@notifications.post("/{notification_id}/read", status_code=204)
def mark_read(notification_id: uuid.UUID, actor: Actor = Depends(current_actor), session: Session = Depends(get_db)) -> Response:
    result = session.execute(update(Notification).where(Notification.id == notification_id, Notification.user_id == actor.user_id, Notification.read_at.is_(None)).values(read_at=utcnow()))
    if result.rowcount == 0 and session.get(Notification, notification_id) is None:
        raise NotFound("Уведомление не найдено", code="NOTIFICATION_NOT_FOUND")
    session.commit()
    return Response(status_code=204)


@notifications.post("/read-all", status_code=204)
def mark_all_read(actor: Actor = Depends(current_actor), session: Session = Depends(get_db)) -> Response:
    session.execute(update(Notification).where(Notification.user_id == actor.user_id, Notification.read_at.is_(None)).values(read_at=utcnow()))
    session.commit()
    return Response(status_code=204)


def _demo_guard(actor: Actor) -> None:
    if not get_settings().demo_mode:
        raise Forbidden("Демо-управление выключено", code="DEMO_DISABLED")


def _mock(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        return integrations.admin_call(method, path, body)
    except Exception as exc:  # noqa: BLE001
        raise ServiceUnavailable("Симулятор внешних систем недоступен", code="MOCK_UNAVAILABLE") from exc


@demo.get("/integrations")
def mock_state(actor: Actor = Depends(staff_actor)) -> dict[str, Any]:
    """State of failure simulation in the integrations mock (counters, outages)."""
    _demo_guard(actor)
    return _mock("GET", "/admin/state")


@demo.post("/integrations/reset")
def mock_reset(actor: Actor = Depends(staff_actor), session: Session = Depends(get_db)) -> dict[str, Any]:
    """Reset failure counters and outages: scenario S5 (bureau timeouts on the first 4 requests) can be shown again."""
    _demo_guard(actor)
    result = _mock("POST", "/admin/reset")
    audit(session, actor, "DEMO_MOCK_RESET")
    session.commit()
    return result


@demo.put("/integrations/outage")
def mock_outage(body: OutageRequest, actor: Actor = Depends(staff_actor), session: Session = Depends(get_db)) -> dict[str, Any]:
    """Global switch of a source (S5b): failure=TIMEOUT or HTTP_500 turns it off, null turns it back on."""
    _demo_guard(actor)
    result = _mock("PUT", "/admin/outage", body.model_dump())
    audit(session, actor, "DEMO_MOCK_OUTAGE", details=body.model_dump())
    session.commit()
    return result


@health.get("/api/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@health.get("/api/health/ready")
def ready(session: Session = Depends(get_db)):
    checks: dict[str, str] = {}
    ok = True
    try:
        session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:  # noqa: BLE001
        checks["database"] = "unavailable"
        ok = False
    try:
        sc, pol = get_registry().require()
        checks["configs"] = f"{sc.version}; {pol.version}"
    except ApiError:
        raise
    except Exception:  # noqa: BLE001
        checks["configs"] = "not loaded"
        ok = False
    return JSONResponse(status_code=200 if ok else 503, content={"status": "ok" if ok else "unavailable", "checks": checks})


@health.get("/metrics", include_in_schema=False)
def prometheus_metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
