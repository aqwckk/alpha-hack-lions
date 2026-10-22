"""FastAPI application: routers, request id, JSON logs, security headers, error format, Prometheus metrics."""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram
from sqlalchemy.dialects.postgresql import insert
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import auth, bank, catalog, client, misc, risk
from .config import get_settings
from .db import session_scope
from .domain.configs import ConfigError, get_registry
from .errors import ApiError
from .logging_setup import actor_var, configure_logging, request_id_var
from .models import ConfigVersion
from .services.core import Actor, audit, emit, utcnow

log = logging.getLogger("app.http")

HTTP_REQUESTS = Counter("credit_http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_LATENCY = Histogram("credit_http_request_seconds", "HTTP latency", ["method", "route"])

API_DESCRIPTION = """
API кредитного конвейера для малого и микробизнеса (прототип, синтетические данные).

* Аутентификация: `POST /api/v1/auth/login`, затем заголовок `Authorization: Bearer <access_token>`.
* Команды, меняющие статус заявки, принимают `expected_version` (оптимистичная блокировка) и заголовок `Idempotency-Key`.
* Ошибки в едином формате `{"error": {"code", "message", "request_id", "details", "fields"}}`.
* Клиентский API не отдает внутренний статус, балл, грейд и пороги политики: только `client_status` и тексты.
"""


def record_config_versions() -> None:
    """CONFIG_VERSION_LOADED with sha256 for audit of which versions decided what (H8)."""
    try:
        sc, pol = get_registry().require()
    except ConfigError as exc:
        log.error("configs failed to load", extra={"fields": {"error": str(exc)}})
        return
    with session_scope() as session:
        for c in (sc, pol):
            session.execute(
                insert(ConfigVersion)
                .values(id=uuid.uuid4(), config_type=c.config_type, version=c.version, sha256=c.sha256, author=c.author, effective_from=c.effective_from, description=c.content.get("description"))
                .on_conflict_do_update(constraint="uq_config_version", set_={"last_loaded_at": utcnow()})
            )
            emit(session, "CONFIG_VERSION_LOADED", Actor.system("startup"), payload={"config_type": c.config_type, "version": c.version, "sha256": c.sha256})


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        get_registry().load()
        record_config_versions()
    except Exception:  # noqa: BLE001 (readiness reports the problem; liveness stays up)
        log.exception("startup check failed")
    yield


def create_app() -> FastAPI:
    s = get_settings()
    configure_logging("api", s.log_level)
    app = FastAPI(
        title="Credit pipeline API",
        version="1.0.0",
        description=API_DESCRIPTION,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-Id"],
        expose_headers=["X-Request-Id", "Idempotent-Replayed", "Retry-After"],
        max_age=600,
    )

    @app.middleware("http")
    async def context(request: Request, call_next):
        rid = request.headers.get("x-request-id") or ""
        if not rid or len(rid) > 64 or not all(c.isalnum() or c in "-_." for c in rid):
            rid = uuid.uuid4().hex
        request.state.request_id = rid
        token = request_id_var.set(rid)
        actor_var.set(None)
        started = time.perf_counter()
        length = request.headers.get("content-length")
        limit = s.max_document_bytes + 1024 * 1024 if request.url.path.endswith("/documents") else s.max_json_body_bytes
        if length and length.isdigit() and int(length) > limit:
            response = JSONResponse(status_code=413, content=ApiError("Слишком большой запрос", code="PAYLOAD_TOO_LARGE", status=413).body(rid))
        else:
            try:
                response = await call_next(request)
            except Exception:  # noqa: BLE001
                log.exception("unhandled error")
                response = JSONResponse(status_code=500, content=ApiError("Внутренняя ошибка, попробуйте позже", code="INTERNAL_ERROR", status=500).body(rid))
        route = getattr(request.scope.get("route"), "path", "unmatched")
        elapsed = time.perf_counter() - started
        HTTP_REQUESTS.labels(request.method, route, str(response.status_code)).inc()
        HTTP_LATENCY.labels(request.method, route).observe(elapsed)
        response.headers["X-Request-Id"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.path.startswith("/api/docs"):
            response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; img-src 'self' data: https://fastapi.tiangolo.com; frame-ancestors 'none'"
        else:
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
            response.headers.setdefault("Cache-Control", "no-store")
        if s.refresh_cookie_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if route != "/metrics" and not route.startswith("/api/health"):
            actor = actor_var.get() or {}
            log.info("request", extra={"fields": {"method": request.method, "route": route, "status": response.status_code, "duration_ms": round(elapsed * 1000, 1), "user_id": actor.get("user_id")}})
        request_id_var.reset(token)
        return response

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError):
        if exc.status in (403,) or (exc.status == 404 and actor_var.get()):
            _audit_denied(request, exc)
        return JSONResponse(status_code=exc.status, content=exc.body(request.state.request_id), headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        fields = []
        for e in exc.errors():
            loc = [str(p) for p in e.get("loc", []) if p not in ("body", "query", "path", "header")]
            fields.append({"field": ".".join(loc) or "body", "code": "INVALID_FORMAT", "message": "Проверьте формат значения"})
        return JSONResponse(status_code=422, content=ApiError(code="VALIDATION_FAILED", status=422, fields=fields).body(request.state.request_id))

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        codes = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}
        return JSONResponse(status_code=exc.status_code, content=ApiError("Ресурс не найден" if exc.status_code == 404 else str(exc.detail), code=codes.get(exc.status_code, "HTTP_ERROR"), status=exc.status_code).body(request.state.request_id))

    for r in (auth.router, catalog.router, client.router, bank.router, risk.router, misc.notifications, misc.demo, misc.health):
        app.include_router(r)
    return app


def _audit_denied(request: Request, exc: ApiError) -> None:
    """Denied access attempts are part of the audit journal (separate transaction: the command rolled back)."""
    info = actor_var.get() or {}
    try:
        from .enums import ActorType

        actor = Actor(
            type=ActorType(info["role"]) if info.get("role") else ActorType.CLIENT,
            user_id=uuid.UUID(info["user_id"]) if info.get("user_id") else None,
            login=info.get("login"), role=info.get("role"), ip=info.get("ip"), user_agent=info.get("ua"),
            correlation_id=request.state.request_id,
        )
        with session_scope() as session:
            audit(session, actor, f"{request.method} {getattr(request.scope.get('route'), 'path', request.url.path)}", result="DENIED", details={"code": exc.code, "status": exc.status})
    except Exception:  # noqa: BLE001
        log.warning("audit of a denied request failed")


app = create_app()
