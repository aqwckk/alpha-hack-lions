"""HTTP client to external systems (integrations-mock): timeouts, error classification, request ids."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from prometheus_client import Counter, Histogram

from ..config import get_settings

log = logging.getLogger("app.integrations")

EXTERNAL_CALLS = Counter("credit_external_calls_total", "Calls to external systems", ["system", "outcome"])
EXTERNAL_LATENCY = Histogram("credit_external_call_seconds", "Latency of external calls", ["system"])

SOURCE_PATHS = {
    "REGISTRY": ("GET", "/registry/v1/subjects/{inn}"),
    "FNS": ("GET", "/fns/v1/subjects/{inn}"),
    "FINANCIAL_STATEMENTS": ("GET", "/gir-bo/v1/statements/{inn}"),
    "BANK_TURNOVER": ("GET", "/bank/v1/turnover/{inn}"),
    "CREDIT_BUREAU": ("POST", "/bki/v1/credit-reports"),
}

REQUIRED_KEYS = {
    "REGISTRY": ("found",),
    "FNS": ("tax_arrears_amount", "unreliable_flags"),
    "FINANCIAL_STATEMENTS": ("found",),
    "CREDIT_BUREAU": ("no_record",),
    "BANK_TURNOVER": ("has_account", "months_available", "inflow_by_month", "avg_monthly_inflow_12m", "compliance_flag"),
}


@dataclass
class SourceResult:
    source: str
    outcome: str  # SUCCESS, NO_DATA, FAILED
    data: dict[str, Any] | None
    error_code: str | None
    http_status: int | None
    external_request_id: str | None
    requested_at: datetime
    responded_at: datetime
    duration_ms: int

    @property
    def ok(self) -> bool:
        return self.outcome in ("SUCCESS", "NO_DATA")


class OperationError(Exception):
    def __init__(self, code: str, message: str, http_status: int | None = None):
        super().__init__(message)
        self.code, self.http_status = code, http_status


def _headers(correlation_id: str, idempotency_key: str | None = None) -> dict[str, str]:
    s = get_settings()
    headers = {"X-Request-Id": correlation_id[:64]}
    if s.integrations_api_key:
        headers["X-Api-Key"] = s.integrations_api_key
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def client(timeout: float) -> httpx.Client:
    return httpx.Client(base_url=get_settings().integrations_base_url, timeout=httpx.Timeout(timeout, connect=min(timeout, 3.0)))


def fetch_source(source: str, inn: str, *, timeout: float, correlation_id: str, consent: dict[str, Any] | None = None) -> SourceResult:
    """One attempt; never raises. 404 NOT_FOUND / NOT_APPLICABLE is a successful "no data" answer."""
    method, path = SOURCE_PATHS[source]
    started = time.perf_counter()
    requested_at = datetime.now(timezone.utc)
    status_code = None
    ext_id = None
    try:
        with client(timeout) as http:
            if method == "GET":
                resp = http.get(path.format(inn=inn), headers=_headers(correlation_id))
            else:
                resp = http.post(path, json={"inn": inn, "consent": consent, "purpose": "LOAN_APPLICATION"}, headers=_headers(correlation_id))
        status_code = resp.status_code
        ext_id = resp.headers.get("x-request-id")
        if resp.status_code == 404 and resp.json().get("error", {}).get("code") in ("NOT_FOUND", "NOT_APPLICABLE"):
            outcome, data, error = "NO_DATA", None, None
        elif resp.status_code >= 500:
            outcome, data, error = "FAILED", None, "SOURCE_TIMEOUT" if resp.status_code == 504 else "SOURCE_HTTP_5XX"
        elif resp.status_code != 200:
            outcome, data, error = "FAILED", None, "SOURCE_INVALID_RESPONSE"
        else:
            data = resp.json().get("data")
            if not isinstance(data, dict) or any(k not in data for k in REQUIRED_KEYS[source]):
                outcome, data, error = "FAILED", None, "SOURCE_INVALID_RESPONSE"
            else:
                outcome, error = "SUCCESS", None
    except httpx.TimeoutException:
        outcome, data, error = "FAILED", None, "SOURCE_TIMEOUT"
    except (httpx.HTTPError, ValueError):
        outcome, data, error = "FAILED", None, "SOURCE_HTTP_5XX"
    elapsed = time.perf_counter() - started
    EXTERNAL_CALLS.labels(source, outcome).inc()
    EXTERNAL_LATENCY.labels(source).observe(elapsed)
    return SourceResult(source, outcome, data, error, status_code, ext_id, requested_at, datetime.now(timezone.utc), int(elapsed * 1000))


def _operation(system: str, path: str, body: dict[str, Any], *, idempotency_key: str, correlation_id: str) -> dict[str, Any]:
    s = get_settings()
    started = time.perf_counter()
    try:
        with client(s.operation_timeout_seconds) as http:
            resp = http.post(path, json=body, headers=_headers(correlation_id, idempotency_key))
    except httpx.TimeoutException as exc:
        EXTERNAL_CALLS.labels(system, "FAILED").inc()
        raise OperationError("TIMEOUT", f"{system} timeout") from exc
    except httpx.HTTPError as exc:
        EXTERNAL_CALLS.labels(system, "FAILED").inc()
        raise OperationError("UNAVAILABLE", f"{system} unavailable") from exc
    finally:
        EXTERNAL_LATENCY.labels(system).observe(time.perf_counter() - started)
    if resp.status_code not in (200, 201):
        EXTERNAL_CALLS.labels(system, "FAILED").inc()
        code = "UNKNOWN"
        try:
            code = resp.json().get("error", {}).get("code", code)
        except ValueError:
            pass
        raise OperationError(code, f"{system} answered {resp.status_code}", resp.status_code)
    EXTERNAL_CALLS.labels(system, "SUCCESS").inc()
    return resp.json()


def create_document_package(body: dict[str, Any], *, idempotency_key: str, correlation_id: str) -> dict[str, Any]:
    return _operation("EDO", "/edo/v1/packages", body, idempotency_key=idempotency_key, correlation_id=correlation_id)


def register_signature(package_id: str, body: dict[str, Any], *, idempotency_key: str, correlation_id: str) -> dict[str, Any]:
    return _operation("EDO", f"/edo/v1/packages/{package_id}/signatures", body, idempotency_key=idempotency_key, correlation_id=correlation_id)


def issue_loan(body: dict[str, Any], *, idempotency_key: str, correlation_id: str) -> dict[str, Any]:
    return _operation("ABS", "/abs/v1/loans", body, idempotency_key=idempotency_key, correlation_id=correlation_id)


def admin_call(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    with client(5.0) as http:
        resp = http.request(method, path, json=body, headers=_headers(f"admin-{uuid.uuid4().hex[:12]}"))
    resp.raise_for_status()
    return resp.json()
