"""Risk: the stages do not connect into one process. One API path through every stage up to ISSUED
(manual review, structured info request, return to the pinned underwriter, four eyes, signing, disbursement)."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.db import session_scope
from app.models import Loan


def test_investment_loan_from_draft_to_issued(draft_ready, login, worker, mock_app):
    client, view = draft_ready("S3")
    app_id = view["id"]
    uw, risk = login("uw.dmitry"), login("risk.elena")
    client.post(f"/api/v1/applications/{app_id}/submit", {"expected_version": view["version"]})
    worker.drain()
    assert client.get(f"/api/v1/applications/{app_id}").json()["client_status"] == "SPECIALIST_REVIEW"

    card = uw.get(f"/api/v1/bank/applications/{app_id}").json()
    assert [r["code"] for r in card["manual_review_reasons"]] == ["MR_PRODUCT_MANUAL_ONLY", "MR_DATA_MISMATCH"]
    card = uw.post(f"/api/v1/bank/applications/{app_id}/take", {"expected_version": card["version"]}).json()
    card = uw.post(f"/api/v1/bank/applications/{app_id}/request-info", {
        "expected_version": card["version"], "comment": "Нужно пояснение",
        "items": [{"reason_code": "NI_DATA_MISMATCH_EXPLANATION", "answer_type": "FIELD", "field_name": "monthly_revenue_declared"}],
    }).json()

    view = client.get(f"/api/v1/applications/{app_id}").json()
    item = view["info_request"]["items"][0]
    view = client.post(f"/api/v1/applications/{app_id}/info-response", {"expected_version": view["version"], "answers": [{"item_id": item["id"], "answer_value": "6500000"}]}).json()
    worker.drain()
    card = uw.get(f"/api/v1/bank/applications/{app_id}").json()
    assert card["status"] == "IN_REVIEW" and "MR_RETURNED_AFTER_INFO" in [r["code"] for r in card["manual_review_reasons"]]
    assert card["field_changes"][0]["new_value"] == "6500000.00"

    card = uw.post(f"/api/v1/bank/applications/{app_id}/approve", {"expected_version": card["version"], "comment": "Пояснение принято"}).json()
    assert card["status"] == "PENDING_RISK_APPROVAL"
    card = risk.post(f"/api/v1/bank/applications/{app_id}/confirm", {"expected_version": card["version"]}).json()
    assert card["status"] == "OFFER_PENDING"

    view = client.get(f"/api/v1/applications/{app_id}").json()
    option = view["offer"]["options"][0]
    client.post(f"/api/v1/applications/{app_id}/offer/accept", {"expected_version": view["version"], "option_id": option["id"]})
    worker.drain()
    view = client.get(f"/api/v1/applications/{app_id}").json()
    assert view["client_status"] == "DOCUMENTS" and len(view["signing"]["documents"]) == 4
    code = client.post(f"/api/v1/applications/{app_id}/signing-code").json()["code"]
    key = uuid.uuid4().hex
    for _ in range(2):  # repeated SIGN with the same key: one signature, one disbursement
        client.post(f"/api/v1/applications/{app_id}/sign", {"expected_version": view["version"], "code": code}, key=key)
    worker.drain()

    view = client.get(f"/api/v1/applications/{app_id}").json()
    assert view["client_status"] == "COMPLETED" and view["loan"]["amount"] == "40000000.00"
    with session_scope() as s:
        assert s.execute(select(func.count()).select_from(Loan).where(Loan.application_id == uuid.UUID(app_id))).scalar_one() == 1
    assert len(mock_app.state.ledger.operations) >= 1 and str(app_id) in mock_app.state.ledger.operations
    history = [h["payload"]["transition_id"] for h in risk.get(f"/api/v1/bank/applications/{app_id}").json()["history"] if h["event_type"] == "STATUS_CHANGED"]
    assert history == ["T-01", "T-03", "T-06", "T-13", "T-17", "T-22", "T-25", "T-29", "T-10", "T-06", "T-13", "T-17", "T-23", "T-28", "T-31", "T-33", "T-36", "T-39", "T-42"]
