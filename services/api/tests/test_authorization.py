"""Risk: a client reaches someone else's application, runs an employee command or sees internal risk data."""

from __future__ import annotations

import json

import pytest

INTERNAL_KEYS = {"score", "grade", "pd", "factor_contributions", "rules_path", "recommendation", "assignee", "comments", "values", "reason_codes", "failed_stage"}


def keys_of(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in keys_of(v)}
    if isinstance(value, list):
        return {k for v in value for k in keys_of(v)}
    return set()


@pytest.fixture(scope="module")
def decided_s1(request):
    draft_ready = request.getfixturevalue("draft_ready")
    worker = request.getfixturevalue("worker")
    client, view = draft_ready("S1")
    client.post(f"/api/v1/applications/{view['id']}/submit", {"expected_version": view["version"]})
    worker.drain()
    return client, client.get(f"/api/v1/applications/{view['id']}").json()


@pytest.mark.parametrize("method, path", [("GET", ""), ("POST", "/withdraw"), ("POST", "/offer/decline"), ("GET", "/schedule")])
def test_foreign_client_gets_404(decided_s1, login, method, path):
    _, view = decided_s1
    other = login("client.andrey")
    if method == "GET":
        r = other.get(f"/api/v1/applications/{view['id']}{path}", expect=404)
    else:
        r = other.post(f"/api/v1/applications/{view['id']}{path}", {"expected_version": view["version"]}, expect=404)
    assert r.json()["error"]["code"] == "NOT_FOUND"
    assert view["id"] not in json.dumps(other.get("/api/v1/applications").json())


@pytest.mark.parametrize("command", ["take", "approve", "decline", "request-info", "retry"])
def test_client_cannot_run_employee_commands(decided_s1, command):
    client, view = decided_s1
    body = {"expected_version": view["version"], "comment": "x"}
    body |= {"decline": {"reason_codes": ["DCL_UNDERWRITER_RISK"]}, "request-info": {"items": [{"reason_code": "NI_OTHER", "answer_type": "TEXT", "client_text": "?"}]}}.get(command, {})
    if command in ("take", "retry"):
        body.pop("comment")
    r = client.post(f"/api/v1/bank/applications/{view['id']}/{command}", body, expect=403)
    assert r.json()["error"]["code"] == "ROLE_NOT_ALLOWED"


def test_client_view_has_no_internal_risk_data(decided_s1):
    _, view = decided_s1
    assert view["client_status"] == "DECISION_READY"
    assert "status" not in view and not keys_of(view) & INTERNAL_KEYS


def test_underwriter_does_not_see_drafts_and_non_assignee_cannot_decide(draft_ready, login, worker):
    client, view = draft_ready("S3")
    uw1, uw2 = login("uw.dmitry"), login("uw.anna")
    uw1.get(f"/api/v1/bank/applications/{view['id']}", expect=404)
    client.post(f"/api/v1/applications/{view['id']}/submit", {"expected_version": view["version"]})
    worker.drain()
    card = uw1.get(f"/api/v1/bank/applications/{view['id']}").json()
    card = uw1.post(f"/api/v1/bank/applications/{view['id']}/take", {"expected_version": card["version"]}).json()
    r = uw2.post(f"/api/v1/bank/applications/{view['id']}/decline", {"expected_version": card["version"], "comment": "x", "reason_codes": ["DCL_UNDERWRITER_RISK"]}, expect=None)
    assert r.status_code in (403, 404)
    assert uw1.http.patch(f"/api/v1/applications/{view['id']}", json={"expected_version": card["version"], "amount": "1"}).status_code == 403
