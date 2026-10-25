"""Boundary regressions for source evidence, consent and terminal queue failures."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import uuid

import pytest
from sqlalchemy import delete, func, select, update

from app.db import session_scope
from app.enums import JobKind, Status
from app.models import Application, Consent, Decision, Event, Job, ScoringResult, SourceSnapshot
from app.services import integrations
from app.services.core import utcnow
from app.worker import runner, tasks


@pytest.fixture
def stage(draft_ready, worker):
    ids = []

    def create(kind):
        client, view = draft_ready("S1")
        app_id = uuid.UUID(view["id"])
        ids.append(app_id)
        client.post(f"/api/v1/applications/{app_id}/submit", {"expected_version": view["version"]})
        for _ in range(10):
            job = worker.claim()
            assert job is not None
            if job["application_id"] == app_id and job["kind"] == kind:
                return app_id, job
            worker.run_job(job)
        pytest.fail(f"Stage {kind} not reached")

    yield create
    with session_scope() as session:
        session.execute(update(Job).where(Job.application_id.in_(ids), Job.status.in_(["RUNNING", "QUEUED"])).values(status="CANCELLED"))


@pytest.mark.parametrize("evidence", ["expired", "missing", "no_data"])
def test_source_evidence_is_not_a_fabricated_negative(stage, worker, evidence):
    app_id, job = stage("SCORE")
    with session_scope() as session:
        query = (SourceSnapshot.application_id == app_id, SourceSnapshot.source == "REGISTRY")
        if evidence == "missing":
            session.execute(delete(SourceSnapshot).where(*query))
        elif evidence == "expired":
            session.execute(update(SourceSnapshot).where(*query).values(valid_until=utcnow() - timedelta(seconds=1)))
        else:
            session.execute(update(SourceSnapshot).where(*query).values(outcome="NO_DATA", response=None))
    worker.run_job(job)
    with session_scope() as session:
        app = session.get(Application, app_id)
        if evidence == "no_data":
            result = session.execute(select(ScoringResult).where(ScoringResult.application_id == app_id)).scalar_one()
            assert result.scoring_input["sources"]["REGISTRY"] == {"found": False}
            assert app.status == Status.DECISIONING
        else:
            assert app.status == Status.PROCESSING_ERROR and app.failed_stage == Status.SCORING
            assert not session.execute(select(Decision.id).where(Decision.application_id == app_id)).first()
            assert not session.execute(select(ScoringResult.id).where(ScoringResult.application_id == app_id)).first()


@pytest.mark.parametrize("kind, evidence", [("SCORE", "missing"), ("DECIDE", "expired")])
def test_staff_retry_refreshes_source_evidence_before_scoring(stage, worker, login, kind, evidence):
    app_id, job = stage(kind)
    with session_scope() as session:
        source = (SourceSnapshot.application_id == app_id, SourceSnapshot.source == "REGISTRY")
        if evidence == "missing":
            session.execute(delete(SourceSnapshot).where(*source))
        else:
            session.execute(update(SourceSnapshot).where(*source).values(valid_until=utcnow() - timedelta(seconds=1)))
    worker.run_job(job)
    uw = login("uw.dmitry")
    path = f"/api/v1/bank/applications/{app_id}"
    card = uw.get(path).json()
    assert card["status"] == "PROCESSING_ERROR"
    assert card["processing"]["failed_stage"] == ("SCORING" if kind == "SCORE" else "DECISIONING")
    assert card["processing"]["last_error_code"] == "SOURCE_INVALID_RESPONSE" and not card["decisions"]
    card = uw.post(path + "/retry", {"expected_version": card["version"]}).json()
    assert card["status"] == "ENRICHMENT"
    with session_scope() as session:
        pending = session.execute(select(Job).where(Job.application_id == app_id, Job.status == "QUEUED")).scalar_one()
        assert pending.kind == JobKind.ENRICH and pending.expected_status == Status.ENRICHMENT
        retry = session.execute(select(Event).where(Event.application_id == app_id, Event.event_type == "STATUS_CHANGED").order_by(Event.seq.desc()).limit(1)).scalar_one()
        assert retry.payload["transition_id"] == "T-44" and retry.payload["to_status"] == "ENRICHMENT"
    worker.drain()
    with session_scope() as session:
        app = session.get(Application, app_id)
        assert app.status == Status.OFFER_PENDING and app.failed_stage is None and app.last_error_code is None
        decision = session.execute(select(Decision).where(Decision.application_id == app_id)).scalar_one()
        assert decision.outcome == "APPROVED"
        scored = session.get(ScoringResult, decision.scoring_result_id)
        assert scored.scoring_input["sources"]["REGISTRY"]["found"] is True
        assert session.execute(select(SourceSnapshot.id).where(
            SourceSnapshot.application_id == app_id, SourceSnapshot.source == "REGISTRY",
            SourceSnapshot.valid_until > utcnow(), SourceSnapshot.outcome == "SUCCESS",
        )).first()


@pytest.mark.parametrize("invalid", ["subject", "revoked", "expired", "future", "regranted"])
def test_bureau_cache_requires_current_subject_consent(stage, worker, mock_app, invalid):
    app_id, job = stage("ENRICH")
    with session_scope() as session:
        app = session.get(Application, app_id)
        now = utcnow()
        session.add(SourceSnapshot(application_id=app_id, source="CREDIT_BUREAU", stage="ENRICH", inn=app.applicant_inn,
                                   attempt=1, outcome="SUCCESS", requested_at=now - timedelta(seconds=1), responded_at=now,
                                   valid_until=now + timedelta(days=1), response={"no_record": True}))
        consent = session.execute(select(Consent).where(Consent.application_id == app_id, Consent.consent_type == "CONSENT_CREDIT_BUREAU")).scalar_one()
        if invalid == "subject":
            consent.subject_inn = "0010005015"
        elif invalid == "revoked":
            consent.revoked_at = now
        elif invalid == "expired":
            consent.expires_at = now
        elif invalid == "future":
            consent.granted_at = now + timedelta(minutes=1)
        else:
            consent.granted_at = now
    before = mock_app.state.behavior.requests_total.get("CREDIT_BUREAU", 0)
    worker.run_job(job)
    after = mock_app.state.behavior.requests_total.get("CREDIT_BUREAU", 0)
    with session_scope() as session:
        app = session.get(Application, app_id)
        if invalid == "regranted":
            assert after == before + 1 and app.status == Status.SCORING
        else:
            assert after == before
            assert app.status == Status.PROCESSING_ERROR and app.last_error_code == "CONSENT_MISSING"


def test_bureau_mock_rejects_a_consent_for_another_subject():
    now = utcnow()
    body = {"inn": "002000010193", "consent": {
        "consent_id": "test-consent", "subject_inn": "0010005015", "granted_at": now.isoformat(),
        "expires_at": (now + timedelta(days=1)).isoformat(), "text_version": "v1",
    }}
    with integrations.client(1) as http:
        response = http.post("/bki/v1/credit-reports", json=body)
        assert response.status_code == 403 and response.json()["error"]["code"] == "CONSENT_REQUIRED"
        del body["consent"]["subject_inn"]
        assert http.post("/bki/v1/credit-reports", json=body).status_code == 422


def test_terminal_failure_rolls_back_together_then_recovers_legacy(stage, worker, monkeypatch):
    app_id, job = stage("COMPLETENESS_CHECK")
    job["max_attempts"] = job["attempts"]
    with session_scope() as session:
        session.get(Job, job["id"]).max_attempts = job["attempts"]
    original = tasks.fail_after_exhausted

    def crash(*args):
        original(*args)
        raise RuntimeError("Connection lost before commit")

    def broken_handler(*_):
        raise RuntimeError("Task exhausted")

    monkeypatch.setitem(tasks.HANDLERS, JobKind.COMPLETENESS_CHECK, broken_handler)
    monkeypatch.setattr(tasks, "fail_after_exhausted", crash)
    with pytest.raises(RuntimeError, match="before commit"):
        worker.run_job(job)
    with session_scope() as session:
        assert session.get(Job, job["id"]).status == "RUNNING"
        assert session.get(Application, app_id).status == Status.SUBMITTED
        assert session.execute(select(func.count()).select_from(Event).where(Event.application_id == app_id, Event.event_type == "PROCESSING_FAILED")).scalar_one() == 0
    monkeypatch.setattr(tasks, "fail_after_exhausted", original)
    worker.run_job(job)
    with session_scope() as session:
        row, app = session.get(Job, job["id"]), session.get(Application, app_id)
        assert row.status == "FAILED" and app.status == Status.PROCESSING_ERROR
        # Reproduce a terminal record from an older deployment, before atomic finalization.
        app.status, app.version = Status.SUBMITTED, 1
        app.status_changed_at = row.finished_at - timedelta(seconds=1)
        row.payload = {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: worker._recover_failed_jobs(), range(2)))
    with session_scope() as session:
        assert session.get(Application, app_id).status == Status.PROCESSING_ERROR
        assert session.execute(select(func.count()).select_from(Event).where(Event.application_id == app_id, Event.event_type == "PROCESSING_FAILED")).scalar_one() == 2


@pytest.mark.parametrize("race", ["cancelled", "newer", "lease"])
def test_failure_recovery_respects_cancellation_and_new_owner(stage, worker, race):
    app_id, job = stage("COMPLETENESS_CHECK")
    with session_scope() as session:
        row = session.get(Job, job["id"])
        row.max_attempts, row.finished_at = row.attempts, utcnow()
        if race == "lease":
            row.locked_at += timedelta(seconds=1)
        else:
            row.status = "CANCELLED" if race == "cancelled" else "FAILED"
        if race == "newer":
            session.add(Job(application_id=app_id, kind=row.kind, expected_status=row.expected_status,
                            status="QUEUED", correlation_id="newer-task", created_at=utcnow()))
    worker._fail_exhausted(job, tasks.Actor.system("stale-owner"), "Late failure")
    worker._recover_failed_jobs()
    with session_scope() as session:
        assert session.get(Application, app_id).status == Status.SUBMITTED
        assert session.get(Job, job["id"]).status == ("RUNNING" if race == "lease" else "CANCELLED" if race == "cancelled" else "FAILED")


def test_heartbeat_tracks_only_successful_ticks_and_is_removed(worker, monkeypatch, tmp_path):
    path = tmp_path / "heartbeat"
    monkeypatch.setattr(runner, "HEARTBEAT_PATH", path)
    monkeypatch.setattr(runner, "start_http_server", lambda *_: None)
    monkeypatch.setattr(runner.signal, "signal", lambda *_: None)
    monkeypatch.setattr(runner.time, "sleep", lambda *_: None)
    stamps = []
    real_heartbeat = worker._heartbeat

    def heartbeat():
        real_heartbeat()
        stamps.append(path.read_text())

    def tick():
        if len(stamps) == 1:
            stamps.append("failed")
            raise RuntimeError("Database unavailable")
        assert path.read_text() == stamps[0]
        worker.stopping = True
        return False

    monkeypatch.setattr(worker, "_heartbeat", heartbeat)
    monkeypatch.setattr(worker, "tick", tick)
    try:
        worker.run_forever()
    finally:
        worker.stopping = False
    assert len(stamps) == 3 and stamps[1] == "failed"
    assert not path.exists()
