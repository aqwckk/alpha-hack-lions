"""Integrations mock: simplified contracts of external systems used by the credit pipeline.

Sources (enrichment): REGISTRY (EGRUL/EGRIP), FNS ("Transparent business"), FINANCIAL_STATEMENTS
(GIR BO), CREDIT_BUREAU (requires a consent reference), BANK_TURNOVER (internal bank data).
Operations: EDO (document package, signature registration), ABS (loan disbursement or credit line
limit, idempotent by key). Every response carries a request id; errors use one JSON format.
"""

from __future__ import annotations

import asyncio
import calendar
import hashlib
import hmac
import json
import logging
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .data import SOURCES, ProfileStore, inn_is_valid
from .documents import render_package
from .settings import load_settings
from .state import BehaviorState, LedgerState

MSK = ZoneInfo("Europe/Moscow")
OPERATION_SOURCES = ("EDO", "ABS")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "service": "integrations-mock",
            "msg": record.getMessage(),
        }
        extra = getattr(record, "extra_fields", None)
        if extra:
            payload.update(extra)
        return json.dumps(payload, ensure_ascii=False)


def _configure_logging(level: str) -> logging.Logger:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("mock")
    logger.handlers = [handler]
    logger.setLevel(level)
    logger.propagate = False
    return logger


class ConsentRef(BaseModel):
    consent_id: str = Field(min_length=1, max_length=64)
    granted_at: datetime
    expires_at: datetime
    text_version: str = Field(min_length=1, max_length=64)


class CreditReportRequest(BaseModel):
    inn: str = Field(min_length=10, max_length=12)
    consent: ConsentRef | None = None
    purpose: str = Field(default="LOAN_APPLICATION", max_length=64)


class Applicant(BaseModel):
    inn: str
    name: str
    applicant_type: Literal["LEGAL_ENTITY", "INDIVIDUAL_ENTREPRENEUR"]
    guarantor_name: str | None = None


class Terms(BaseModel):
    product_code: str
    product_name: str
    amount: str
    term_months: int
    rate_percent: str
    monthly_payment: str
    total_payment: str | None = None
    overpayment: str | None = None
    tranche_max_term_months: int | None = None


class PackageRequest(BaseModel):
    application_id: str
    application_number: str
    applicant: Applicant
    terms: Terms
    documents: list[Literal["CREDIT_AGREEMENT", "PAYMENT_SCHEDULE", "GUARANTEE_AGREEMENT", "PLEDGE_AGREEMENT"]] = Field(min_length=1)
    schedule: list[dict[str, Any]] = Field(default_factory=list)
    collateral: dict[str, Any] | None = None


class SignatureRequest(BaseModel):
    documents_sha256: list[str] = Field(min_length=1)
    signing_code_id: str
    signer_ref: str
    signed_at: datetime


class LoanRequest(BaseModel):
    application_id: str
    operation_type: Literal["DISBURSEMENT", "CREDIT_LINE_LIMIT"]
    borrower_inn: str
    product_code: str
    amount: str
    term_months: int = Field(ge=1, le=120)
    rate_percent: str
    monthly_payment: str


class OutageRequest(BaseModel):
    source: Literal["REGISTRY", "FNS", "FINANCIAL_STATEMENTS", "CREDIT_BUREAU", "BANK_TURNOVER", "EDO", "ABS"]
    failure: Literal["TIMEOUT", "HTTP_500"] | None = None


class BehaviorRequest(BaseModel):
    source: Literal["REGISTRY", "FNS", "FINANCIAL_STATEMENTS", "CREDIT_BUREAU", "BANK_TURNOVER", "EDO", "ABS"]
    inn: str
    fail_first_n: int = Field(ge=0, le=100)
    failure: Literal["TIMEOUT", "HTTP_500"] = "HTTP_500"


def add_month(d: date) -> date:
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


class MockError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def create_app() -> FastAPI:
    settings = load_settings()
    log = _configure_logging(settings.log_level)
    store = ProfileStore(settings.analytics_dir)
    behavior = BehaviorState()
    ledger = LedgerState()

    app = FastAPI(
        title="Integrations mock",
        version="1.0.0",
        description="Simulators of REGISTRY, FNS, FINANCIAL_STATEMENTS, CREDIT_BUREAU, BANK_TURNOVER, EDO and ABS.",
    )
    app.state.behavior = behavior
    app.state.ledger = ledger
    app.state.store = store
    app.state.settings = settings

    def today() -> date:
        if settings.as_of:
            return date.fromisoformat(settings.as_of)
        return datetime.now(MSK).date()

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("x-request-id") or str(uuid.uuid4())
        if len(rid) > 64 or not all(c.isalnum() or c in "-_." for c in rid):
            rid = str(uuid.uuid4())
        request.state.request_id = rid
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-Id"] = rid
        log.info(
            "request",
            extra={
                "extra_fields": {
                    "request_id": rid,
                    "method": request.method,
                    "path": getattr(request.scope.get("route"), "path", "unmatched"),
                    "status": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                }
            },
        )
        return response

    @app.exception_handler(MockError)
    async def mock_error_handler(request: Request, exc: MockError):
        return JSONResponse(
            status_code=exc.status,
            content={"error": {"code": exc.code, "message": exc.message, "request_id": request.state.request_id}},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_FAILED",
                    "message": "Invalid request",
                    "request_id": request.state.request_id,
                    "details": [{"loc": list(e.get("loc", [])), "msg": e.get("msg")} for e in exc.errors()],
                }
            },
        )

    def require_key(x_api_key: str | None = Header(default=None)) -> None:
        if settings.api_key and not hmac.compare_digest(x_api_key or "", settings.api_key):
            raise MockError(401, "UNAUTHORIZED", "Missing or invalid X-Api-Key")

    async def simulate(source: str, inn: str) -> None:
        """Latency and configured failures; raises MockError for a failed request."""
        failure = behavior.decide_failure(source, inn, store.mock_behavior(inn).get(source))
        if failure == "TIMEOUT":
            await asyncio.sleep(settings.timeout_sleep_seconds)
            raise MockError(504, "UPSTREAM_TIMEOUT", f"{source} did not respond in time")
        if failure == "HTTP_500":
            raise MockError(500, "INTERNAL_ERROR", f"{source} internal error")
        span = max(settings.delay_ms_max - settings.delay_ms_min, 0)
        if settings.delay_ms_max > 0:
            seed = int(hashlib.sha256(f"delay:{source}:{inn}".encode()).hexdigest()[:8], 16)
            await asyncio.sleep((settings.delay_ms_min + (seed % (span + 1))) / 1000)

    def checked_inn(inn: str) -> str:
        if not inn_is_valid(inn):
            raise MockError(400, "INVALID_INN", "INN has invalid length or checksum")
        return inn

    def envelope(request: Request, source: str, inn: str, as_of: date, data: Any) -> dict[str, Any]:
        return {
            "request_id": request.state.request_id,
            "source": source,
            "inn": inn,
            "as_of": as_of.isoformat(),
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "data": data,
        }

    async def source_response(request: Request, source: str, inn: str) -> dict[str, Any]:
        inn = checked_inn(inn)
        await simulate(source, inn)
        as_of = today()
        data = store.profile(inn, as_of).get(source)
        if data is None:
            code = "NOT_APPLICABLE" if source == "FINANCIAL_STATEMENTS" and len(inn) == 12 else "NOT_FOUND"
            raise MockError(404, code, f"{source} has no data for this subject")
        if source == "BANK_TURNOVER":
            data = {**data, "inflow_months": store.month_labels(as_of)}
        return envelope(request, source, inn, as_of, data)

    deps = [Depends(require_key)]

    @app.get("/health", tags=["service"])
    def health() -> dict[str, Any]:
        return {"status": "ok", "demo_data_version": store.version, "companies": len(store.companies)}

    @app.get("/registry/v1/subjects/{inn}", tags=["REGISTRY"], dependencies=deps)
    async def registry(inn: str, request: Request):
        """EGRUL (10 digits) or EGRIP (12 digits) extract. Unknown subject: 200 with found=false."""
        return await source_response(request, "REGISTRY", inn)

    @app.get("/fns/v1/subjects/{inn}", tags=["FNS"], dependencies=deps)
    async def fns(inn: str, request: Request):
        return await source_response(request, "FNS", inn)

    @app.get("/gir-bo/v1/statements/{inn}", tags=["FINANCIAL_STATEMENTS"], dependencies=deps)
    async def statements(inn: str, request: Request):
        """Accounting statements of legal entities only; 404 NOT_APPLICABLE for an individual entrepreneur."""
        return await source_response(request, "FINANCIAL_STATEMENTS", inn)

    @app.get("/bank/v1/turnover/{inn}", tags=["BANK_TURNOVER"], dependencies=deps)
    async def turnover(inn: str, request: Request):
        return await source_response(request, "BANK_TURNOVER", inn)

    @app.post("/bki/v1/credit-reports", tags=["CREDIT_BUREAU"], dependencies=deps)
    async def credit_report(body: CreditReportRequest, request: Request):
        """Credit report. The bureau refuses a request without a valid consent reference (403 CONSENT_REQUIRED)."""
        now = datetime.now(timezone.utc)
        if body.consent is None or body.consent.expires_at <= now or body.consent.granted_at > now + timedelta(minutes=5):
            raise MockError(403, "CONSENT_REQUIRED", "A valid consent of the subject is required")
        return await source_response(request, "CREDIT_BUREAU", body.inn)

    # ---- EDO ------------------------------------------------------------------------------

    def idem_key(value: str | None) -> str:
        if not value or len(value) > 128:
            raise MockError(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key header is required")
        return value

    @app.post("/edo/v1/packages", tags=["EDO"], dependencies=deps, status_code=201)
    async def create_package(body: PackageRequest, request: Request, idempotency_key: str | None = Header(default=None)):
        """Generate the document package for signing; repeated key returns the same package."""
        key = idem_key(idempotency_key)
        await simulate("EDO", body.applicant.inn)
        payload = body.model_dump(mode="json")
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        with ledger.lock:
            if key in ledger.package_keys:
                pkg_id, fp = ledger.package_keys[key]
                if fp != fingerprint:
                    raise MockError(409, "IDEMPOTENCY_CONFLICT", "The key was used with another request")
                return ledger.packages[pkg_id]
            pkg_id = str(uuid.uuid4())
            number = f"{body.application_number}-{len(ledger.packages) + 1:03d}"
            package = {
                "package_id": pkg_id,
                "edo_operation_id": f"EDO-{uuid.uuid4().hex[:12].upper()}",
                "contract_number": number,
                "status": "READY_FOR_SIGNING",
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                "documents": render_package(number, payload),
            }
            ledger.packages[pkg_id] = package
            ledger.package_keys[key] = (pkg_id, fingerprint)
            return package

    @app.post("/edo/v1/packages/{package_id}/signatures", tags=["EDO"], dependencies=deps, status_code=201)
    async def register_signature(package_id: str, body: SignatureRequest, request: Request, idempotency_key: str | None = Header(default=None)):
        """Register a simple electronic signature bound to the exact document hashes of the package."""
        key = idem_key(idempotency_key)
        with ledger.lock:
            package = ledger.packages.get(package_id)
        if package is None:
            raise MockError(404, "PACKAGE_NOT_FOUND", "Unknown package")
        await simulate("EDO", package_id)
        with ledger.lock:
            if key in ledger.signatures:
                return ledger.signatures[key]
            expected = sorted(d["sha256"] for d in package["documents"])
            if sorted(body.documents_sha256) != expected:
                raise MockError(409, "HASH_MISMATCH", "Signed hashes do not match the package documents")
            signature = {
                "signature_id": f"SIG-{uuid.uuid4().hex[:12].upper()}",
                "package_id": package_id,
                "status": "SIGNED",
                "signed_at": body.signed_at.isoformat(),
                "documents_sha256": expected,
            }
            ledger.signatures[key] = signature
            package["status"] = "SIGNED"
            return signature

    # ---- ABS ------------------------------------------------------------------------------

    @app.post("/abs/v1/loans", tags=["ABS"], dependencies=deps, status_code=201)
    async def issue_loan(body: LoanRequest, request: Request, idempotency_key: str | None = Header(default=None)):
        """Disbursement to the settlement account or credit line limit. Same key: same operation, never a second one."""
        key = idem_key(idempotency_key)
        await simulate("ABS", body.borrower_inn)
        payload = body.model_dump(mode="json")
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        with ledger.lock:
            if key in ledger.operations:
                fp, op = ledger.operations[key]
                if fp != fingerprint:
                    raise MockError(409, "IDEMPOTENCY_CONFLICT", "The key was used with another request")
                return JSONResponse(status_code=200, content=op, headers={"Idempotent-Replayed": "true"})
            ledger.contract_seq += 1
            issued = datetime.now(timezone.utc)
            local_day = issued.astimezone(MSK).date()
            first_payment = add_month(local_day)
            prefix = "40702810" if len(body.borrower_inn) == 10 else "40802810"
            tail = int(hashlib.sha256(f"acc:{body.borrower_inn}".encode()).hexdigest()[:8], 16) % 10000
            op = {
                "operation_id": f"ABS-{uuid.uuid4().hex[:12].upper()}",
                "operation_type": body.operation_type,
                "status": "COMPLETED",
                "contract_number": f"KD-{local_day.year}-{ledger.contract_seq:06d}",
                "account_number_masked": f"{prefix}{'*' * 8}{tail:04d}",
                "issued_at": issued.isoformat(timespec="seconds").replace("+00:00", "Z"),
                "first_payment_date": first_payment.isoformat(),
                "amount": body.amount,
            }
            ledger.operations[key] = (fingerprint, op)
            return op

    # ---- demo administration --------------------------------------------------------------

    @app.get("/admin/state", tags=["admin"], dependencies=deps)
    def admin_state() -> dict[str, Any]:
        return behavior.snapshot()

    @app.post("/admin/reset", tags=["admin"], dependencies=deps)
    def admin_reset() -> dict[str, Any]:
        """Reset failure counters, overrides and outages (demo: S5 can be shown again)."""
        behavior.reset()
        log.info("behavior reset")
        return {"status": "reset", **behavior.snapshot()}

    @app.put("/admin/outage", tags=["admin"], dependencies=deps)
    def admin_outage(body: OutageRequest) -> dict[str, Any]:
        """Global switch: every request to the source fails (failure=null switches it back on)."""
        with behavior.lock:
            if body.failure:
                behavior.outages[body.source] = body.failure
            else:
                behavior.outages.pop(body.source, None)
        log.info("outage changed", extra={"extra_fields": {"source": body.source, "failure": body.failure}})
        return behavior.snapshot()

    @app.put("/admin/behavior", tags=["admin"], dependencies=deps)
    def admin_behavior(body: BehaviorRequest) -> dict[str, Any]:
        """Per-INN failure on the first N requests (overrides the profile's mock_behavior)."""
        with behavior.lock:
            behavior.overrides[(body.source, body.inn)] = {"fail_first_n": body.fail_first_n, "failure": body.failure}
            behavior.counters.pop((body.source, body.inn), None)
        return behavior.snapshot()

    log.info("integrations mock started", extra={"extra_fields": {"companies": len(store.companies), "sources": list(SOURCES) + list(OPERATION_SOURCES)}})
    return app


app = create_app()
