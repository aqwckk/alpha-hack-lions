"""Risk: a failing external source loses the application or turns into a false credit decline."""

from __future__ import annotations

import pytest


def bank_card(login, app_id):
    return login("risk.elena").get(f"/api/v1/bank/applications/{app_id}").json()


@pytest.mark.parametrize("failure", ["transient", "outage"])
def test_source_failure_retries_and_recovers(draft_ready, login, worker, mock_app, failure):
    client, view = draft_ready("S5")  # profile S5: the bureau times out on the first 4 requests
    if failure == "outage":
        mock_app.state.behavior.outages["CREDIT_BUREAU"] = "HTTP_500"
    client.post(f"/api/v1/applications/{view['id']}/submit", {"expected_version": view["version"]})
    worker.run_until_idle()  # completeness and the first enrichment (3 quick attempts)
    card = bank_card(login, view["id"])
    assert card["status"] == "EXTERNAL_SERVICE_UNAVAILABLE" and card["processing"]["next_retry_at"]
    client_view = client.get(f"/api/v1/applications/{view['id']}").json()
    assert client_view["client_status"] == "CHECKING" and "задержкой" in client_view["client_status_text"]["what_is_happening"]

    worker.drain()
    card = bank_card(login, view["id"])
    if failure == "transient":
        attempts = next(s for s in card["sources"] if s["source"] == "CREDIT_BUREAU")["attempts"]
        assert [a["outcome"] for a in attempts] == ["FAILED"] * 4 + ["SUCCESS"]
        assert card["status"] == "OFFER_PENDING" and card["decisions"][-1]["outcome"] == "APPROVED"
        return

    # every scheduled retry failed: a technical status for people, not a decline
    assert card["status"] == "PROCESSING_ERROR" and card["processing"]["failed_stage"] == "ENRICHMENT"
    assert card["processing"]["last_error_code"] == "SOURCE_HTTP_5XX" and not card["decisions"]
    assert client.get(f"/api/v1/applications/{view['id']}").json()["client_status"] == "CHECKING"
    uw = login("uw.dmitry")
    errors = uw.get("/api/v1/bank/applications?tab=errors").json()["items"]
    assert any(i["id"] == view["id"] for i in errors)
    mock_app.state.behavior.reset()
    uw.post(f"/api/v1/bank/applications/{view['id']}/retry", {"expected_version": card["version"]})
    worker.drain()
    card = bank_card(login, view["id"])
    assert card["status"] == "OFFER_PENDING" and any(h["event_type"] == "PROCESSING_RETRIED" for h in card["history"])
