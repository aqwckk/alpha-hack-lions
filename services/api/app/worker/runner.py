"""Worker loop: PostgreSQL queue (FOR UPDATE SKIP LOCKED), exponential backoff, timers, outbox relay.

Several worker processes can run at once: a job is claimed by exactly one of them, timers run under a
transaction-level advisory lock, and every status change is a conditional update.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import time
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

from prometheus_client import Counter, Gauge, Histogram, start_http_server
from sqlalchemy import and_, delete, or_, select, text, update
from sqlalchemy.orm import Session, aliased

from ..config import get_settings
from ..db import session_scope
from ..domain.configs import ConfigError, get_registry
from ..domain.dictionaries import SIGNING_CODE_EXPIRED_TEXT, fmt_dt
from ..enums import JobKind, Status, Trigger
from ..errors import ApiError
from ..models import (
    Application,
    Event,
    IdempotencyKey,
    InfoRequest,
    Job,
    Notification,
    Offer,
    SigningCode,
)
from ..services.client_commands import cancel_pending_jobs, revoke_codes
from ..services.core import Actor, apply_transition, emit, enqueue, notify, utcnow
from ..services.params import process_params
from . import tasks

log = logging.getLogger("app.worker")

JOBS_TOTAL = Counter("credit_jobs_total", "Worker jobs by outcome", ["kind", "outcome"])
JOB_SECONDS = Histogram("credit_job_seconds", "Job duration", ["kind"])
QUEUE_DEPTH = Gauge("credit_queue_ready_jobs", "Jobs ready to run")
TIMER_LOCK_KEY = 72_026_001
HEARTBEAT_PATH = Path("/tmp/credit-worker-heartbeat")


class Worker:
    def __init__(self, name: str | None = None):
        self.name = name or f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self.stopping = False
        self._last_timer = 0.0

    # Queue

    def claim(self) -> dict[str, Any] | None:
        with session_scope() as session:
            row = session.execute(
                text(
                    """
                    UPDATE jobs SET status = 'RUNNING', locked_by = :worker, locked_at = now(), attempts = attempts + 1,
                        payload = CASE WHEN payload ? '_stage_version' THEN payload ELSE
                            payload || jsonb_build_object('_stage_version', (SELECT version FROM applications WHERE id = jobs.application_id)) END
                    WHERE id = (
                        SELECT id FROM jobs WHERE status = 'QUEUED' AND run_at <= now()
                        ORDER BY run_at LIMIT 1 FOR UPDATE SKIP LOCKED
                    )
                    RETURNING id, kind, application_id, expected_status, attempts, max_attempts, correlation_id, payload, locked_at
                    """
                ),
                {"worker": self.name},
            ).mappings().first()
            return dict(row) if row else None

    def _owned_job(self, session: Session, job: dict[str, Any]) -> Job | None:
        return session.execute(select(Job).where(
            Job.id == job["id"], Job.status == "RUNNING", Job.locked_by == self.name,
            Job.attempts == job["attempts"], Job.locked_at == job["locked_at"],
        ).with_for_update()).scalar_one_or_none()

    def _finish(self, job: dict[str, Any], status: str, error: str | None = None, run_at=None) -> None:
        with session_scope() as session:
            row = self._owned_job(session, job)
            if row is None:
                return
            row.status, row.last_error = status, error
            if status == "QUEUED":
                row.run_at, row.locked_by, row.locked_at = run_at, None, None
            else:
                row.finished_at = utcnow()

    def _fail_exhausted(self, job: dict[str, Any], actor: Actor, error: str) -> None:
        with session_scope() as session:
            # Commands lock the application before cancelling jobs; keep the same lock order.
            session.execute(select(Application).where(Application.id == job["application_id"]).with_for_update()).scalar_one_or_none()
            row = self._owned_job(session, job)
            if row is None:
                return
            tasks.fail_after_exhausted(session, job, actor)
            row.status, row.last_error, row.finished_at = "FAILED", error, utcnow()

    def run_job(self, job: dict[str, Any]) -> None:
        kind = JobKind(job["kind"])
        actor = Actor.system(job["correlation_id"])
        started = time.perf_counter()
        try:
            tasks.HANDLERS[kind](job, actor)
            self._finish(job, "DONE")
            JOBS_TOTAL.labels(kind, "done").inc()
        except tasks.StaleTask:
            self._finish(job, "DONE", "stale: application moved on")
            JOBS_TOTAL.labels(kind, "stale").inc()
        except ApiError as exc:
            # a conflicting concurrent change (client withdrew, version moved): nothing to do
            self._finish(job, "DONE", f"conflict: {exc.code}")
            JOBS_TOTAL.labels(kind, "conflict").inc()
        except Exception as exc:  # noqa: BLE001
            s = get_settings()
            log.exception("job failed", extra={"fields": {"job_id": str(job["id"]), "kind": kind.value, "attempt": job["attempts"]}})
            if job["attempts"] < job["max_attempts"]:
                delay = s.job_backoff_base_seconds * (2 ** (job["attempts"] - 1))
                self._finish(job, "QUEUED", f"{type(exc).__name__}: {exc}"[:1000], run_at=utcnow() + timedelta(seconds=delay))
                JOBS_TOTAL.labels(kind, "retry").inc()
            else:
                self._fail_exhausted(job, actor, f"{type(exc).__name__}: {exc}"[:1000])
                JOBS_TOTAL.labels(kind, "failed").inc()
        finally:
            JOB_SECONDS.labels(kind).observe(time.perf_counter() - started)

    # Timers

    def run_timers(self) -> None:
        with session_scope() as session:
            if not session.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": TIMER_LOCK_KEY}).scalar_one():
                return
            QUEUE_DEPTH.set(session.execute(text("SELECT count(*) FROM jobs WHERE status = 'QUEUED' AND run_at <= now()")).scalar_one())
            self._requeue_stale_jobs(session)
        failure = None
        for timer in (self._recover_failed_jobs, self._enrichment_retry, self._offer_expiry, self._offer_expiring, self._info_expiry, self._draft_expiry, self._review_sla, self._signing_codes, self._outbox):
            try:
                timer()
            except Exception as exc:  # noqa: BLE001
                log.exception("timer failed", extra={"fields": {"timer": timer.__name__}})
                failure = exc
        if failure is not None:
            raise failure

    def _recover_failed_jobs(self) -> None:
        """Repair terminal jobs left behind by an interrupted older worker."""
        other = aliased(Job)
        superseded = select(other.id).where(
            other.application_id == Job.application_id, other.id != Job.id,
            or_(other.created_at > Job.created_at, other.status.in_(["QUEUED", "RUNNING"])),
        ).exists()
        stage_version = Job.payload["_stage_version"].as_integer()
        with session_scope() as session:
            ids = list(session.execute(select(Job.id).join(Application, Application.id == Job.application_id).where(
                Job.status == "FAILED", Job.attempts >= Job.max_attempts,
                Application.status == Job.expected_status, Application.is_history.is_(False),
                Job.finished_at.is_not(None), Application.status_changed_at <= Job.finished_at,
                or_(stage_version.is_(None), Application.version == stage_version), ~superseded,
            ).order_by(Job.finished_at).limit(50)).scalars())
        for job_id in ids:
            with session_scope() as session:
                app = session.execute(select(Application).join(Job, Job.application_id == Application.id).where(
                    Job.id == job_id,
                ).with_for_update(skip_locked=True, of=Application)).scalar_one_or_none()
                if app is None:
                    continue
                row = session.execute(select(Job).where(Job.id == job_id, Job.status == "FAILED").with_for_update(skip_locked=True)).scalar_one_or_none()
                if row is None or app.status != row.expected_status or row.finished_at is None:
                    continue
                stage_version = row.payload.get("_stage_version")
                if stage_version is not None and app.version != stage_version:
                    continue
                if app.status_changed_at > row.finished_at:
                    continue
                newer = session.execute(select(Job.id).where(
                    Job.application_id == app.id, Job.id != row.id,
                    or_(Job.created_at > row.created_at, Job.status.in_(["QUEUED", "RUNNING"])),
                ).limit(1)).first()
                if newer is None:
                    tasks.fail_after_exhausted(session, {"application_id": app.id, "expected_status": row.expected_status, "payload": row.payload}, Actor.system(row.correlation_id))

    def _requeue_stale_jobs(self, session: Session) -> None:
        lease = timedelta(seconds=get_settings().job_lease_seconds)
        session.execute(update(Job).where(Job.status == "RUNNING", Job.locked_at < utcnow() - lease).values(status="QUEUED", locked_by=None, locked_at=None, run_at=utcnow()))

    def _each_app(self, condition, handler, limit: int = 50) -> None:
        """Process matching applications one per transaction; rows locked by others are skipped."""
        with session_scope() as session:
            ids = list(session.execute(select(Application.id).where(Application.is_history.is_(False), condition).limit(limit)).scalars())
        for app_id in ids:
            try:
                with session_scope() as session:
                    app = session.execute(select(Application).where(Application.id == app_id, condition).with_for_update(skip_locked=True)).scalar_one_or_none()
                    if app is not None:
                        handler(session, app, Actor.timer(f"timer-{uuid.uuid4().hex[:12]}"))
            except ApiError:
                continue

    def _enrichment_retry(self) -> None:
        def handle(session: Session, app: Application, actor: Actor) -> None:
            apply_transition(session, app, "T-15", actor, trigger=Trigger.ENRICHMENT_RETRY, expected_version=app.version, changes={"enrichment_retry_count": app.enrichment_retry_count + 1, "next_retry_at": None})
            enqueue(session, JobKind.ENRICH, app, correlation_id=actor.correlation_id)

        self._each_app(and_(Application.status == Status.EXTERNAL_SERVICE_UNAVAILABLE.value, Application.next_retry_at <= utcnow()), handle)

    def _offer_expiry(self) -> None:
        def handle(session: Session, app: Application, actor: Actor) -> None:
            offer = session.get(Offer, app.current_offer_id)
            if offer is None or offer.expires_at > utcnow():
                return
            stage = app.status
            apply_transition(session, app, "T-35" if stage == Status.OFFER_PENDING else "T-40", actor, trigger=Trigger.OFFER_EXPIRY, expected_version=app.version)
            offer.status = "EXPIRED"
            revoke_codes(session, app)
            cancel_pending_jobs(session, app)
            emit(session, "OFFER_EXPIRED", actor, application=app, payload={"offer_id": str(offer.id), "stage": stage})
            notify(session, app.client_user_id, "NTF_OFFER_EXPIRED", application=app)

        expired = select(Offer.id).where(Offer.id == Application.current_offer_id, Offer.expires_at <= utcnow()).exists()
        self._each_app(and_(Application.status.in_([Status.OFFER_PENDING.value, Status.SIGNING.value]), expired), handle)

    def _offer_expiring(self) -> None:
        notice = timedelta(seconds=get_settings().offer_expiring_notice_seconds)
        now = utcnow()
        with session_scope() as session:
            rows = session.execute(
                select(Offer, Application).join(Application, Application.id == Offer.application_id).where(
                    Offer.status == "ACTIVE", Offer.expiring_notified.is_(False), Offer.expires_at - notice <= now, Offer.expires_at > now,
                    Offer.expires_at - Offer.created_at > notice, Application.status.in_([Status.OFFER_PENDING.value, Status.SIGNING.value]),
                ).with_for_update(skip_locked=True, of=Offer)
            ).all()
            for offer, app in rows:
                offer.expiring_notified = True
                notify(session, app.client_user_id, "NTF_OFFER_EXPIRING", application=app, expires_at=fmt_dt(offer.expires_at))

    def _info_expiry(self) -> None:
        def handle(session: Session, app: Application, actor: Actor) -> None:
            ir = session.execute(select(InfoRequest).where(InfoRequest.application_id == app.id, InfoRequest.status == "OPEN").order_by(InfoRequest.created_at.desc()).limit(1)).scalar_one_or_none()
            if ir is None or ir.due_at > utcnow():
                return
            apply_transition(session, app, "T-12", actor, trigger=Trigger.INFO_REQUEST_EXPIRY, expected_version=app.version, changes={"cancel_reason": "CL_INFO_TIMEOUT"})
            ir.status = "EXPIRED"
            emit(session, "APPLICATION_CANCELLED", actor, application=app, payload={"cancel_reason": "CL_INFO_TIMEOUT", "from_status": Status.INFO_REQUESTED.value})
            notify(session, app.client_user_id, "NTF_APPLICATION_CLOSED", application=app, due_at=fmt_dt(ir.due_at))

        overdue = select(InfoRequest.id).where(InfoRequest.application_id == Application.id, InfoRequest.status == "OPEN", InfoRequest.due_at <= utcnow()).exists()
        self._each_app(and_(Application.status == Status.INFO_REQUESTED.value, overdue), handle)

    def _draft_expiry(self) -> None:
        try:
            ttl = process_params().draft_ttl_seconds
        except ConfigError:
            return

        def handle(session: Session, app: Application, actor: Actor) -> None:
            apply_transition(session, app, "T-05", actor, trigger=Trigger.DRAFT_EXPIRY, expected_version=app.version, changes={"cancel_reason": "CL_DRAFT_EXPIRED"})
            emit(session, "APPLICATION_CANCELLED", actor, application=app, payload={"cancel_reason": "CL_DRAFT_EXPIRED", "from_status": Status.DRAFT.value})

        self._each_app(and_(Application.status == Status.DRAFT.value, Application.updated_at < utcnow() - timedelta(seconds=ttl)), handle)

    def _review_sla(self) -> None:
        now = utcnow()
        with session_scope() as session:
            apps = session.execute(
                select(Application).where(
                    Application.is_history.is_(False), Application.status.in_([Status.MANUAL_REVIEW.value, Status.IN_REVIEW.value]),
                    Application.sla_breached.is_(False), Application.review_due_at <= now,
                ).with_for_update(skip_locked=True)
            ).scalars().all()
            for app in apps:
                app.sla_breached = True
                emit(session, "REVIEW_SLA_BREACHED", Actor.timer("timer-review-sla"), application=app, payload={"review_due_at": app.review_due_at.isoformat(), "assignee_id": str(app.assignee_id) if app.assignee_id else None})

    def _signing_codes(self) -> None:
        now = utcnow()
        with session_scope() as session:
            codes = session.execute(select(SigningCode).where(SigningCode.used_at.is_(None), SigningCode.revoked_at.is_(None), SigningCode.expires_at <= now).with_for_update(skip_locked=True)).scalars().all()
            for c in codes:
                c.revoked_at = now
                if c.notification_id:
                    session.execute(update(Notification).where(Notification.id == c.notification_id).values(body=SIGNING_CODE_EXPIRED_TEXT))

    def _outbox(self) -> None:
        """Relay of the transactional outbox: here the consumer is the log and the metrics (no broker in the prototype)."""
        with session_scope() as session:
            rows = session.execute(
                select(Event.event_id).where(Event.published_at.is_(None)).order_by(Event.seq).limit(500).with_for_update(skip_locked=True)
            ).scalars().all()
            if rows:
                session.execute(update(Event).where(Event.event_id.in_(rows)).values(published_at=utcnow()))
            # stored command results are kept for 24 hours (a retry after that is a new command)
            session.execute(delete(IdempotencyKey).where(IdempotencyKey.created_at < utcnow() - timedelta(hours=24)))

    # Loop

    def tick(self) -> bool:
        s = get_settings()
        now = time.monotonic()
        if now - self._last_timer >= s.timer_interval_seconds:
            self._last_timer = now
            self.run_timers()
        job = self.claim()
        if job is None:
            return False
        self.run_job(job)
        return True

    def run_forever(self) -> None:
        s = get_settings()
        signal.signal(signal.SIGTERM, self._stop)
        signal.signal(signal.SIGINT, self._stop)
        try:
            start_http_server(s.worker_metrics_port)
        except OSError:
            log.warning("metrics port is busy, worker metrics are not exported")
        configs_ready = False
        try:
            log.info("worker started", extra={"fields": {"worker": self.name}})
            while not self.stopping:
                try:
                    if not configs_ready:
                        get_registry().load()
                        configs_ready = True
                        self._heartbeat()
                    busy = self.tick()
                    self._heartbeat()
                except Exception:  # noqa: BLE001 (database restart and similar: back off and continue)
                    log.exception("worker tick failed")
                    busy = False
                    time.sleep(2)
                if not busy:
                    time.sleep(s.worker_poll_interval_seconds)
        finally:
            HEARTBEAT_PATH.unlink(missing_ok=True)
            log.info("worker stopped", extra={"fields": {"worker": self.name}})

    def _heartbeat(self) -> None:
        temporary = HEARTBEAT_PATH.with_name(f"{HEARTBEAT_PATH.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text(str(time.time()), encoding="ascii")
            temporary.replace(HEARTBEAT_PATH)
        finally:
            temporary.unlink(missing_ok=True)

    def _stop(self, *_args) -> None:
        self.stopping = True

    def run_until_idle(self, max_jobs: int = 200) -> int:
        """Test helper: run timers once and jobs until the queue has nothing ready."""
        self.run_timers()
        done = 0
        while done < max_jobs:
            job = self.claim()
            if job is None:
                break
            self.run_job(job)
            done += 1
        return done
