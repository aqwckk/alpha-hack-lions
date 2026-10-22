"""Idempotent seed: demo users (password hashes only), companies and memberships, synthetic history for metrics.

The history (analytics/artifacts/synthetic_applications.json) is shifted by (now - reference_now) so that
it ends at the current moment; it is imported once and marked is_history (read-only, no timers).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, insert, select, text
from sqlalchemy.orm import Session

from .config import get_settings
from .db import session_scope
from .models import (
    Application,
    Company,
    CompanyMembership,
    Decision,
    Event,
    Offer,
    OfferOption,
    StatusHistory,
    User,
)
from .security import hash_password

log = logging.getLogger("app.seed")


def _load(name: str) -> dict[str, Any]:
    return json.loads((get_settings().analytics_artifacts_dir / name).read_text(encoding="utf-8"))


def _ts(value: str | None, shift) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")) + shift


def seed_users(session: Session) -> dict[str, uuid.UUID]:
    users = _load("demo_users.json")["users"]
    companies = {c["inn"]: c for c in _load("demo_companies.json")["companies"]}
    ids: dict[str, uuid.UUID] = {}
    for u in users:
        existing = session.execute(select(User).where(User.login == u["login"])).scalar_one_or_none()
        if existing is None:
            existing = User(
                id=uuid.uuid4(), login=u["login"], password_hash=hash_password(u["password"]), role=u["role"], full_name=u["full_name"],
                representative_role=u.get("representative_role"), is_active=True, is_demo=bool(u.get("is_demo")),
            )
            session.add(existing)
            session.flush()
            log.info("demo user created", extra={"fields": {"login": u["login"], "role": u["role"]}})
        ids[u["login"]] = existing.id
        for inn in u.get("company_inns") or []:
            company = session.execute(select(Company).where(Company.inn == inn)).scalar_one_or_none()
            if company is None:
                reg = (companies.get(inn) or {}).get("sources", {}).get("REGISTRY") or {}
                company = Company(id=uuid.uuid4(), inn=inn, applicant_type="LEGAL_ENTITY" if len(inn) == 10 else "INDIVIDUAL_ENTREPRENEUR", short_name=reg.get("company_short_name"))
                session.add(company)
                session.flush()
            member = session.execute(select(CompanyMembership).where(CompanyMembership.user_id == existing.id, CompanyMembership.company_id == company.id)).scalar_one_or_none()
            if member is None:
                session.add(CompanyMembership(id=uuid.uuid4(), user_id=existing.id, company_id=company.id, representative_role=u.get("representative_role")))
    return ids


def seed_history(session: Session) -> int:
    if session.execute(select(func.count()).select_from(Application).where(Application.is_history.is_(True))).scalar_one() > 0:
        return 0
    data = _load("synthetic_applications.json")
    reference = datetime.fromisoformat(data["reference_now"].replace("Z", "+00:00"))
    shift = datetime.now(timezone.utc) - reference
    users = {u.login: u.id for u in session.execute(select(User)).scalars()}
    for login in sorted({a["client_login"] for a in data["applications"]} | {e["actor_login"] for e in data["events"] if e["actor_login"]}):
        if login not in users:
            uid = uuid.uuid4()
            session.add(User(id=uid, login=login, password_hash=None, role="CLIENT", full_name=f"Синтетический клиент {login.rsplit('.', 1)[-1]}", is_active=False, is_demo=True))
            users[login] = uid
    session.flush()
    companies = {c.inn: c.id for c in session.execute(select(Company)).scalars()}
    app_rows, decision_rows, offer_rows, option_rows, history_rows = [], [], [], [], []
    for a in data["applications"]:
        if a["applicant_inn"] not in companies:
            cid = uuid.uuid4()
            session.add(Company(id=cid, inn=a["applicant_inn"], applicant_type=a["applicant_type"], short_name=a["company_short_name"]))
            companies[a["applicant_inn"]] = cid
        app_id = uuid.UUID(a["id"])
        created = _ts(a["created_at"], shift)
        current_offer = None
        last_decision_id = None
        decisions = a.get("decisions") or []
        for d in decisions:
            last_decision_id = uuid.UUID(d["decision_id"])
            decision_rows.append({
                "id": last_decision_id, "application_id": app_id, "outcome": d["outcome"], "mode": d["mode"], "status": "FINAL", "reason_codes": d["reason_codes"],
                "reason_details": {}, "rules_path": [], "override": d["override"], "decided_by": users.get(d["decided_by"]) if d.get("decided_by") else None,
                "policy_version": a.get("policy_version") or data["policy_version"], "scorecard_version": a.get("scorecard_version"), "grade": a.get("grade"),
                "created_at": _ts(d["created_at"], shift),
            })
        for o in a.get("offers") or []:
            offer_id = uuid.UUID(o["offer_id"])
            current_offer = offer_id
            status = {"OFFER_PENDING": "ACTIVE", "OFFER_DECLINED": "DECLINED", "OFFER_EXPIRED": "EXPIRED"}.get(a["status"], "ACCEPTED" if a.get("final_amount") else "EXPIRED")
            offer_rows.append({"id": offer_id, "application_id": app_id, "decision_id": last_decision_id, "outcome": o["outcome"], "status": status, "expires_at": _ts(o["expires_at"], shift), "created_at": _ts(decisions[-1]["created_at"], shift) if decisions else created, "expiring_notified": True})
            for i, opt in enumerate(o["options"]):
                option_rows.append({
                    "id": uuid.uuid5(offer_id, str(i)), "offer_id": offer_id, "position": i, "option_type": opt["option_type"], "product_code": opt["product_code"],
                    "amount": Decimal(opt["amount"]), "term_months": opt["term_months"], "rate_percent": Decimal(opt["rate_percent"]), "monthly_payment": Decimal(opt["monthly_payment"]),
                    "total_payment": Decimal(opt["total_payment"]), "overpayment": Decimal(opt["overpayment"]), "requires_owner_guarantee": opt["requires_owner_guarantee"],
                    "requires_collateral": opt["requires_collateral"], "tranche_max_term_months": opt.get("tranche_max_term_months"), "recommended": opt["recommended"],
                })
        app_rows.append({
            "id": app_id, "application_number": a["application_number"], "client_user_id": users[a["client_login"]], "company_id": companies[a["applicant_inn"]],
            "status": a["status"], "version": a["version"], "is_history": True, "product_code": a["product_code"], "purpose": a["purpose"],
            "amount": Decimal(a["amount"]), "term_months": a["term_months"], "applicant_inn": a["applicant_inn"], "applicant_type": a["applicant_type"],
            "monthly_revenue_declared": Decimal(a["monthly_revenue_declared"]), "existing_monthly_payments_declared": Decimal(a["existing_monthly_payments_declared"]),
            "collateral_type": a.get("collateral_type"), "collateral_value": Decimal(a["collateral_value"]) if a.get("collateral_value") else None,
            "inn_check_status": "FOUND", "company_short_name": a["company_short_name"], "assignee_id": users.get(a["assignee"]) if a.get("assignee") else None,
            "auto_info_request_count": a["auto_info_request_count"], "info_request_count": a["info_request_count"], "manual_review_required": a["manual_review_required"],
            "sla_breached": a["sla_breached"], "cancel_reason": a.get("cancel_reason"), "current_offer_id": current_offer,
            "final_product_code": a.get("final_product_code"), "final_amount": Decimal(a["final_amount"]) if a.get("final_amount") else None,
            "final_term_months": a.get("final_term_months"), "final_rate_percent": Decimal(a["final_rate_percent"]) if a.get("final_rate_percent") else None,
            "final_monthly_payment": Decimal(a["final_monthly_payment"]) if a.get("final_monthly_payment") else None,
            "created_at": created, "updated_at": _ts(a.get("closed_at") or a.get("issued_at") or a.get("decided_at") or a.get("submitted_at") or a["created_at"], shift),
            "status_changed_at": _ts(a.get("closed_at") or a.get("issued_at") or a.get("decided_at") or a.get("submitted_at") or a["created_at"], shift),
            "submitted_at": _ts(a.get("submitted_at"), shift), "decided_at": _ts(a.get("decided_at"), shift), "issued_at": _ts(a.get("issued_at"), shift),
            "closed_at": _ts(a.get("closed_at"), shift), "score": a.get("score"), "grade": a.get("grade"),
        })
    session.flush()
    session.execute(insert(Application), app_rows)
    if decision_rows:
        session.execute(insert(Decision), decision_rows)
    if offer_rows:
        session.execute(insert(Offer), offer_rows)
    if option_rows:
        session.execute(insert(OfferOption), option_rows)
    event_rows = []
    for e in data["events"]:
        occurred = _ts(e["occurred_at"], shift)
        event_rows.append({
            "event_id": uuid.UUID(e["event_id"]), "event_type": e["event_type"], "occurred_at": occurred,
            "application_id": uuid.UUID(e["application_id"]) if e["application_id"] else None, "actor_type": e["actor_type"],
            "actor_id": users.get(e["actor_login"]) if e["actor_login"] else None, "correlation_id": e["correlation_id"],
            "application_version": e["application_version"], "payload": e["payload"], "published_at": occurred,
        })
        if e["event_type"] == "STATUS_CHANGED":
            p = e["payload"]
            history_rows.append({
                "application_id": uuid.UUID(e["application_id"]), "from_status": p.get("from_status"), "to_status": p["to_status"], "transition_id": p.get("transition_id") or "T-00",
                "trigger": p.get("command") or p.get("trigger") or "HISTORY", "actor_type": e["actor_type"], "actor_id": users.get(e["actor_login"]) if e["actor_login"] else None,
                "version": e["application_version"] or 1, "occurred_at": occurred,
            })
    for i in range(0, len(event_rows), 2000):
        session.execute(insert(Event), event_rows[i : i + 2000])
    if history_rows:
        session.execute(insert(StatusHistory), history_rows)
    return len(app_rows)


def run() -> None:
    with session_scope() as session:
        session.execute(text("SELECT pg_advisory_xact_lock(72026002)"))
        users = seed_users(session)
        imported = seed_history(session) if get_settings().seed_history else 0
        max_number = session.execute(text("SELECT coalesce(max(substring(application_number from 3)::bigint), 0) FROM applications")).scalar_one()
        current = session.execute(text("SELECT last_value FROM application_number_seq")).scalar_one()
        if max_number >= current:
            session.execute(text("SELECT setval('application_number_seq', :v)"), {"v": max_number})
    log.info("seed finished", extra={"fields": {"demo_users": len(users), "history_applications": imported}})
