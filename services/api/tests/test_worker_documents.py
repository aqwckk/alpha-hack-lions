"""Regressions for durable document preparation and the signed loan terms."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import uuid

import pytest
from sqlalchemy import func, select

from app.db import session_scope
from app.enums import Status
from app.models import Application, DocumentPackage, IntegrationRequest, Loan
from app.services import integrations
from app.services.schedules import package_schedule
from app.worker import tasks


def test_lost_edo_response_and_next_day_retry_keep_signed_terms(draft_ready, worker, login, mock_app, monkeypatch):
    client, view = draft_ready("S1")
    app_id = uuid.UUID(view["id"])
    path = f"/api/v1/applications/{app_id}"
    client.post(path + "/submit", {"expected_version": view["version"]})
    worker.drain()
    view = client.get(path).json()
    client.post(path + "/offer/accept", {"expected_version": view["version"], "option_id": view["offer"]["options"][0]["id"]})
    job = worker.claim()
    assert job["kind"] == "PREPARE_DOCUMENTS"
    real_create = integrations.create_document_package
    requests = []

    def lose_response(body, **kwargs):
        # A separate connection must see the immutable intent before any external side effect.
        with session_scope() as session:
            intent = session.get(IntegrationRequest, kwargs["idempotency_key"])
            assert intent.request == body and intent.response is None
        requests.append((kwargs["idempotency_key"], deepcopy(body)))
        real_create(body, **kwargs)
        raise integrations.OperationError("TIMEOUT", "Response lost after EDO committed")

    monkeypatch.setattr(tasks, "msk_today", lambda: "2026-10-25")
    monkeypatch.setattr(integrations, "create_document_package", lose_response)
    worker.run_job(job)
    with session_scope() as session:
        assert session.get(Application, app_id).status == Status.PROCESSING_ERROR
        intent = session.get(IntegrationRequest, requests[0][0])
        frozen = deepcopy(intent.request)
        assert intent.response is None
    key = requests[0][0]
    package_id = mock_app.state.ledger.package_keys[key][0]
    hashes = [d["sha256"] for d in mock_app.state.ledger.packages[package_id]["documents"]]

    def recover(body, **kwargs):
        requests.append((kwargs["idempotency_key"], deepcopy(body)))
        return real_create(body, **kwargs)

    monkeypatch.setattr(tasks, "msk_today", lambda: "2026-10-26")
    import mockapp.main as mock_main

    class NextDay(datetime):
        @classmethod
        def now(cls, tz=None):
            value = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)

    monkeypatch.setattr(mock_main, "datetime", NextDay)
    monkeypatch.setattr(integrations, "create_document_package", recover)
    # Recovery by key must work even if EDO cannot create packages now.
    mock_app.state.behavior.outages["EDO"] = "HTTP_500"
    uw = login("uw.dmitry")
    card = uw.get(f"/api/v1/bank/applications/{app_id}").json()
    uw.post(f"/api/v1/bank/applications/{app_id}/retry", {"expected_version": card["version"]})
    worker.drain()
    view = client.get(path).json()
    assert view["signing"] is not None
    assert all(request == (key, frozen) for request in requests)
    with session_scope() as session:
        pkg = session.execute(select(DocumentPackage).where(DocumentPackage.application_id == app_id)).scalar_one()
        assert pkg.external_package_id == package_id
        assert session.get(IntegrationRequest, key).response["package_id"] == package_id
    assert [d["sha256"] for d in mock_app.state.ledger.packages[package_id]["documents"]] == hashes
    mock_app.state.behavior.reset()
    code = client.post(path + "/signing-code").json()["code"]
    client.post(path + "/sign", {"expected_version": view["version"], "code": code})
    worker.drain()
    op = mock_app.state.ledger.operations[str(app_id)][1]
    with session_scope() as session:
        loan = session.execute(select(Loan).where(Loan.application_id == app_id)).scalar_one()
        assert loan.issued_at.date().isoformat() == "2026-10-26"
        assert loan.contract_number == pkg.contract_number == op["contract_number"]
        assert loan.payment_schedule == op["schedule"] == frozen["schedule"]
        assert loan.first_payment_date.isoformat() == op["first_payment_date"] == frozen["schedule"][0]["date"]
        # Pre-migration packages have only the rendered signed schedule.
        with session.begin_nested() as legacy:
            session.delete(session.get(IntegrationRequest, key))
            loan.payment_schedule = None
            session.flush()
            assert package_schedule(session, pkg) == frozen["schedule"]
            legacy.rollback()
        assert session.get(IntegrationRequest, key) is not None
        assert loan.payment_schedule == frozen["schedule"]
        assert session.execute(select(func.count()).select_from(DocumentPackage).where(DocumentPackage.application_id == app_id)).scalar_one() == 1
        assert session.execute(select(func.count()).select_from(Loan).where(Loan.application_id == app_id)).scalar_one() == 1
    assert client.get(path).json()["loan"]["contract_number"] == pkg.contract_number
    with pytest.raises(tasks.StaleTask):
        tasks.issue_loan(job, tasks.Actor.system("repeat-issued"))
