"""Risk: a double click or a retry creates a second effect, a stale screen overwrites newer data, two people win one race."""

from __future__ import annotations

import threading
import uuid

from sqlalchemy import func, select

from app.db import session_scope
from app.models import Event


def count_events(application_id: str, event_type: str) -> int:
    with session_scope() as s:
        return s.execute(select(func.count()).select_from(Event).where(Event.application_id == uuid.UUID(application_id), Event.event_type == event_type)).scalar_one()


def test_double_submit_and_stale_version(draft_ready):
    client, view = draft_ready("S1")
    url = f"/api/v1/applications/{view['id']}/submit"
    key = uuid.uuid4().hex
    first = client.post(url, {"expected_version": view["version"]}, key=key)
    replay = client.post(url, {"expected_version": view["version"]}, key=key)
    assert replay.headers.get("idempotent-replayed") == "true" and replay.json() == first.json()
    assert count_events(view["id"], "APPLICATION_SUBMITTED") == 1
    reused = client.post(url, {"expected_version": view["version"] + 1}, key=key, expect=422)
    assert reused.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    other_key = client.post(url, {"expected_version": view["version"]}, expect=409)
    assert other_key.json()["error"]["code"] == "INVALID_TRANSITION"
    stale = client.post(f"/api/v1/applications/{view['id']}/withdraw", {"expected_version": view["version"]}, expect=409)
    assert stale.json()["error"]["code"] == "VERSION_CONFLICT" and stale.json()["error"]["details"]["current_version"] == first.json()["version"]


def test_take_race_has_one_winner(draft_ready, login, worker):
    client, view = draft_ready("S3")
    client.post(f"/api/v1/applications/{view['id']}/submit", {"expected_version": view["version"]})
    worker.drain()
    uw1, uw2 = login("uw.dmitry"), login("uw.anna")
    version = uw1.get(f"/api/v1/bank/applications/{view['id']}").json()["version"]
    barrier = threading.Barrier(2)
    results: dict[str, int] = {}

    def take(api):
        barrier.wait()
        results[api.login] = api.post(f"/api/v1/bank/applications/{view['id']}/take", {"expected_version": version}, expect=None).status_code

    threads = [threading.Thread(target=take, args=(u,)) for u in (uw1, uw2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results.values()) == [200, 409]
    assert count_events(view["id"], "REVIEW_TAKEN") == 1


def test_withdraw_wins_over_running_task(draft_ready, worker):
    """The client cancels while the worker enriches: the first committed change wins, the task does not resurrect the application."""
    client, view = draft_ready("S1")
    submitted = client.post(f"/api/v1/applications/{view['id']}/submit", {"expected_version": view["version"]}).json()
    job = worker.claim()  # COMPLETENESS_CHECK
    worker.run_job(job)
    job = worker.claim()  # ENRICH is claimed, the client withdraws before it runs
    current = client.get(f"/api/v1/applications/{view['id']}").json()
    client.post(f"/api/v1/applications/{view['id']}/withdraw", {"expected_version": current["version"]})
    worker.run_job(job)
    worker.drain()
    final = client.get(f"/api/v1/applications/{view['id']}").json()
    assert final["client_status"] == "WITHDRAWN" and submitted["version"] < final["version"]
    assert count_events(view["id"], "SCORING_COMPLETED") == 0
