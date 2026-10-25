"""Consent identity and monetary input boundaries that must fail before side effects."""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.db import session_scope
from app.errors import ValidationFailed
from app.models import Consent
from app.services.staff_commands import _manual_options


def test_company_change_revokes_consents_and_old_subject_cannot_authorize_submit(draft_ready):
    client, view = draft_ready("S1")
    path = f"/api/v1/applications/{view['id']}"
    original_inn = view["form"]["applicant_inn"]
    base = "009999990"
    other_inn = base + str(sum(int(d) * w for d, w in zip(base, (2, 4, 10, 3, 5, 9, 4, 6, 8))) % 11 % 10)
    view = client.patch(path, {"expected_version": view["version"], "applicant_inn": other_inn}).json()["application"]
    assert not any(c["given"] for c in view["consents"])
    with session_scope() as session:
        rows = session.scalars(select(Consent).where(Consent.application_id == uuid.UUID(view["id"]))).all()
        assert len(rows) == 3 and all(c.revoked_at is not None for c in rows)
    view = client.post(path + "/prefill", {"expected_version": view["version"], "inn": original_inn}, key=None).json()["application"]
    assert not any(c["given"] for c in view["consents"])
    # Existing records with a mismatched subject must also fail closed.
    with session_scope() as session:
        for row in session.scalars(select(Consent).where(Consent.application_id == uuid.UUID(view["id"]))):
            row.revoked_at = None
            row.subject_inn = other_inn
    assert not any(c["given"] for c in client.get(path).json()["consents"])
    response = client.post(path + "/submit", {"expected_version": view["version"]}, expect=422)
    assert sum(f["code"] == "CONSENT_REQUIRED" for f in response.json()["error"]["fields"]) == 3
    view = client.patch(path, {"expected_version": view["version"], "applicant_inn": None}).json()["application"]
    assert client.http.put(path + "/consents/CONSENT_CREDIT_BUREAU", json={"expected_version": view["version"]}).status_code == 422


@pytest.mark.parametrize("amount", ["0", "-1", "NaN", "Infinity", "abc"])
def test_invalid_amount_is_rejected_before_create_and_manual_pricing(login, amount):
    client = login("client.irina")
    response = client.post("/api/v1/applications", {"product_code": "EXPRESS", "purpose": "EQUIPMENT", "amount": amount, "term_months": 24}, expect=422)
    assert response.json()["error"]["fields"][0]["field"] == "amount"
    app = SimpleNamespace(product_code="WORKING_CAPITAL", amount=Decimal("1200000"), term_months=24, applicant_type="LEGAL_ENTITY")
    with pytest.raises(ValidationFailed):
        _manual_options(app, "A", [{"amount": amount, "term_months": 24}], None)


@pytest.mark.parametrize("rate", ["abc", "NaN", "Infinity", "-1200", "100.01"])
def test_calculator_rejects_invalid_rate(login, rate):
    response = login("client.irina").post("/api/v1/catalog/calculate", {"product_code": "EXPRESS", "amount": "1200000", "term_months": 24, "rate_percent": rate}, key=None, expect=422)
    assert response.json()["error"]["fields"][0]["field"] == "rate_percent"


def test_zero_rate_is_supported_and_draft_zero_does_not_reach_database(draft_ready):
    client, view = draft_ready("S1")
    result = client.post("/api/v1/catalog/calculate", {"product_code": "EXPRESS", "amount": "1200000", "term_months": 24, "rate_percent": "0"}, key=None).json()
    assert Decimal(result["overpayment"]) == 0 and Decimal(result["monthly_payment"]) == 50000
    result = client.patch(f"/api/v1/applications/{view['id']}", {"expected_version": view["version"], "amount": "0"}).json()
    assert result["field_errors"][0]["field"] == "amount"
    assert Decimal(result["application"]["form"]["amount"]) == 1200000


@pytest.mark.parametrize("failed", ["database", "configs"])
def test_readiness_fails_when_a_required_dependency_is_unavailable(monkeypatch, failed):
    from app.api import misc

    def unavailable():
        raise RuntimeError("unavailable")

    session = SimpleNamespace(execute=lambda _: unavailable() if failed == "database" else None)
    registry = SimpleNamespace(require=lambda: unavailable() if failed == "configs" else (SimpleNamespace(version="test"), SimpleNamespace(version="test")))
    monkeypatch.setattr(misc, "get_registry", lambda: registry)
    assert misc.ready(session).status_code == 503
    assert misc.live() == {"status": "ok"}
