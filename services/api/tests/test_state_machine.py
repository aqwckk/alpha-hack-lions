"""Risk: a status changes along a path that the process model forbids, or a role gets someone else's action.

The table is checked directly (cheap level); one API call proves that the table is what guards real commands.
"""

from __future__ import annotations

import uuid

import pytest

from app.domain.statemachine import (
    TRANSITIONS,
    GuardContext,
    available_actions,
    resolve,
)
from app.enums import TERMINAL_STATUSES, ActorType, Command, Status, Trigger

C, T, S, A = Command, Trigger, Status, ActorType
UW1, UW2, OWNER = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

ALLOWED = [
    ("T-03", S.DRAFT, C.SUBMIT, A.CLIENT, S.SUBMITTED),
    ("T-06", S.SUBMITTED, T.COMPLETENESS_PASSED, A.SYSTEM, S.ENRICHMENT),
    ("T-10", S.INFO_REQUESTED, C.RESPOND_INFO, A.CLIENT, S.SUBMITTED),
    ("T-14", S.ENRICHMENT, T.SOURCES_UNAVAILABLE, A.SYSTEM, S.EXTERNAL_SERVICE_UNAVAILABLE),
    ("T-15", S.EXTERNAL_SERVICE_UNAVAILABLE, T.ENRICHMENT_RETRY, A.TIMER, S.ENRICHMENT),
    ("T-19", S.DECISIONING, T.POLICY_OFFER, A.SYSTEM, S.OFFER_PENDING),
    ("T-23", S.DECISIONING, T.POLICY_MANUAL_REVIEW, A.SYSTEM, S.IN_REVIEW),
    ("T-25", S.MANUAL_REVIEW, C.TAKE, A.UNDERWRITER, S.IN_REVIEW),
    ("T-28", S.IN_REVIEW, C.APPROVE, A.UNDERWRITER, S.PENDING_RISK_APPROVAL),
    ("T-31", S.PENDING_RISK_APPROVAL, C.CONFIRM_DECISION, A.RISK_MANAGER, S.OFFER_PENDING),
    ("T-38", S.SIGNING, C.DECLINE_OFFER, A.CLIENT, S.OFFER_DECLINED),
    ("T-39", S.SIGNING, C.SIGN, A.CLIENT, S.SIGNED),
    ("T-40", S.SIGNING, T.OFFER_EXPIRY, A.TIMER, S.OFFER_EXPIRED),
    ("T-41", S.SCORING, C.WITHDRAW, A.CLIENT, S.CANCELLED),
    ("T-42", S.SIGNED, T.LOAN_ISSUED, A.SYSTEM, S.ISSUED),
    ("T-44", S.PROCESSING_ERROR, C.RETRY_PROCESSING, A.RISK_MANAGER, None),
]

# application-states.md, section 8: transitions that break the meaning of the process
FORBIDDEN = [
    (S.DRAFT, T.COMPLETENESS_PASSED),
    (S.DRAFT, C.ACCEPT_OFFER),
    (S.SUBMITTED, T.POLICY_OFFER),
    (S.INFO_REQUESTED, T.SCORING_COMPLETED),
    (S.INFO_REQUESTED, T.POLICY_MANUAL_REVIEW),
    (S.ENRICHMENT, T.POLICY_OFFER),
    (S.SCORING, T.POLICY_DECLINED),
    (S.OFFER_PENDING, C.SIGN),
    (S.OFFER_PENDING, T.DOCUMENTS_PREPARED),
    (S.SIGNED, C.WITHDRAW),
    (S.SIGNED, C.DECLINE_OFFER),
    (S.OFFER_EXPIRED, C.ACCEPT_OFFER),
] + [(st, None) for st in sorted(TERMINAL_STATUSES)]  # None: no transition at all from a terminal status


@pytest.mark.parametrize("tid, source, trigger, actor, target", ALLOWED, ids=[a[0] for a in ALLOWED])
def test_allowed_transitions(tid, source, trigger, actor, target):
    t = resolve(tid, source, trigger)
    assert t is not None and actor in t.actors and t.target == target


@pytest.mark.parametrize("source, trigger", FORBIDDEN, ids=[f"{s}-{t}" for s, t in FORBIDDEN])
def test_forbidden_transitions(source, trigger):
    assert not [t for t in TRANSITIONS if source in t.sources and trigger in (None, t.trigger)]


def ctx(actor_type, actor_id, **kw):
    return GuardContext(actor_type=actor_type, actor_id=actor_id, owner_id=OWNER, has_scoring=True, **kw)


@pytest.mark.parametrize(
    "status, context, expected",
    [
        (S.IN_REVIEW, ctx(A.UNDERWRITER, UW1, assignee_id=UW1), {C.RELEASE, C.APPROVE, C.MAKE_COUNTER_OFFER, C.REQUEST_INFO, C.DECLINE, C.ADD_COMMENT}),
        (S.IN_REVIEW, ctx(A.UNDERWRITER, UW2, assignee_id=UW1), {C.ADD_COMMENT}),
        (S.IN_REVIEW, ctx(A.CLIENT, OWNER, assignee_id=UW1), {C.WITHDRAW}),
        (S.IN_REVIEW, ctx(A.CLIENT, uuid.uuid4(), assignee_id=UW1), set()),
        (S.PENDING_RISK_APPROVAL, ctx(A.RISK_MANAGER, UW2, proposer_id=UW1), {C.CONFIRM_DECISION, C.RETURN_DECISION, C.ADD_COMMENT}),
        (S.PENDING_RISK_APPROVAL, ctx(A.RISK_MANAGER, UW1, proposer_id=UW1), {C.RETURN_DECISION, C.ADD_COMMENT}),
        (S.MANUAL_REVIEW, ctx(A.CLIENT, OWNER), {C.WITHDRAW}),
        (S.PROCESSING_ERROR, ctx(A.CLIENT, OWNER, failed_stage=S.SIGNED), set()),
        (S.PROCESSING_ERROR, ctx(A.UNDERWRITER, UW1, failed_stage=S.SIGNED), {C.RETRY_PROCESSING, C.ADD_COMMENT}),
        (S.SIGNED, ctx(A.CLIENT, OWNER), set()),
    ],
    ids=["assignee", "other-underwriter", "client-owner", "foreign-client", "risk-manager", "risk-manager-is-author", "client-in-queue", "client-after-signing", "retry-after-abs-failure", "signed"],
)
def test_available_actions_by_role(status, context, expected):
    assert set(available_actions(status, context)) == expected


def test_api_rejects_transition_outside_table(draft_ready, worker):
    client, view = draft_ready("S1")
    client.post(f"/api/v1/applications/{view['id']}/submit", {"expected_version": view["version"]})
    worker.drain()
    view = client.get(f"/api/v1/applications/{view['id']}").json()
    r = client.post(f"/api/v1/applications/{view['id']}/sign", {"expected_version": view["version"], "code": "123456"}, expect=409)
    assert r.json()["error"]["code"] == "INVALID_TRANSITION" and "current_status" not in r.json()["error"]["details"]
