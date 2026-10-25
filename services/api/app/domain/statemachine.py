"""Declarative transition table T-01...T-46 (docs/process/application-states.md, section 5).

One structure drives both the check of a command and the list of available_actions in API responses.
Guards listed here are the cheap object-level ones (ownership, assignee, four eyes, failed stage,
offer expiry); data guards (required fields, consents, product bounds) live in the command handlers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ..enums import ActorType, Command, Status, Trigger

S = Status
A = ActorType
C = Command
T = Trigger

CLIENT = frozenset({A.CLIENT})
UW = frozenset({A.UNDERWRITER})
RM = frozenset({A.RISK_MANAGER})
STAFF = frozenset({A.UNDERWRITER, A.RISK_MANAGER})
SYSTEM = frozenset({A.SYSTEM})
TIMER = frozenset({A.TIMER})


@dataclass(frozen=True)
class Transition:
    id: str
    sources: tuple[Status, ...]
    target: Status | None  # None: resolve the retry target from the failure (T-44).
    trigger: str
    actors: frozenset[ActorType]
    guards: tuple[str, ...] = field(default_factory=tuple)


TRANSITIONS: tuple[Transition, ...] = (
    Transition("T-01", (), S.DRAFT, C.CREATE_APPLICATION, CLIENT),
    Transition("T-03", (S.DRAFT,), S.SUBMITTED, C.SUBMIT, CLIENT, ("owner",)),
    Transition("T-04", (S.DRAFT,), S.CANCELLED, C.WITHDRAW, CLIENT, ("owner",)),
    Transition("T-05", (S.DRAFT,), S.CANCELLED, T.DRAFT_EXPIRY, TIMER),
    Transition("T-06", (S.SUBMITTED,), S.ENRICHMENT, T.COMPLETENESS_PASSED, SYSTEM),
    Transition("T-07", (S.SUBMITTED,), S.INFO_REQUESTED, T.COMPLETENESS_FAILED, SYSTEM, ("auto_info_cycles_left",)),
    Transition("T-08", (S.SUBMITTED,), S.MANUAL_REVIEW, T.COMPLETENESS_FAILED, SYSTEM, ("auto_info_cycles_exhausted",)),
    Transition("T-09", (S.SUBMITTED,), S.PROCESSING_ERROR, T.TASK_FAILED, SYSTEM),
    Transition("T-10", (S.INFO_REQUESTED,), S.SUBMITTED, C.RESPOND_INFO, CLIENT, ("owner",)),
    Transition("T-11", (S.INFO_REQUESTED,), S.CANCELLED, C.WITHDRAW, CLIENT, ("owner",)),
    Transition("T-12", (S.INFO_REQUESTED,), S.CANCELLED, T.INFO_REQUEST_EXPIRY, TIMER),
    Transition("T-13", (S.ENRICHMENT,), S.SCORING, T.ENRICHMENT_COMPLETED, SYSTEM),
    Transition("T-14", (S.ENRICHMENT,), S.EXTERNAL_SERVICE_UNAVAILABLE, T.SOURCES_UNAVAILABLE, SYSTEM, ("enrichment_retries_left",)),
    Transition("T-15", (S.EXTERNAL_SERVICE_UNAVAILABLE,), S.ENRICHMENT, T.ENRICHMENT_RETRY, TIMER),
    Transition("T-16", (S.ENRICHMENT,), S.PROCESSING_ERROR, T.ENRICHMENT_FAILED, SYSTEM),
    Transition("T-17", (S.SCORING,), S.DECISIONING, T.SCORING_COMPLETED, SYSTEM),
    Transition("T-18", (S.SCORING,), S.PROCESSING_ERROR, T.TASK_FAILED, SYSTEM),
    Transition("T-19", (S.DECISIONING,), S.OFFER_PENDING, T.POLICY_OFFER, SYSTEM, ("not_manual_review_required",)),
    Transition("T-20", (S.DECISIONING,), S.DECLINED, T.POLICY_DECLINED, SYSTEM),
    Transition("T-21", (S.DECISIONING,), S.INFO_REQUESTED, T.POLICY_NEEDS_INFO, SYSTEM, ("auto_info_cycles_left",)),
    Transition("T-22", (S.DECISIONING,), S.MANUAL_REVIEW, T.POLICY_MANUAL_REVIEW, SYSTEM),
    Transition("T-23", (S.DECISIONING,), S.IN_REVIEW, T.POLICY_MANUAL_REVIEW, SYSTEM, ("has_assignee",)),
    Transition("T-24", (S.DECISIONING,), S.PROCESSING_ERROR, T.TASK_FAILED, SYSTEM),
    Transition("T-25", (S.MANUAL_REVIEW,), S.IN_REVIEW, C.TAKE, UW),
    Transition("T-26", (S.IN_REVIEW,), S.MANUAL_REVIEW, C.RELEASE, UW, ("assignee",)),
    Transition("T-27", (S.IN_REVIEW,), S.OFFER_PENDING, C.APPROVE, UW, ("assignee", "has_scoring")),
    Transition("T-27", (S.IN_REVIEW,), S.OFFER_PENDING, C.MAKE_COUNTER_OFFER, UW, ("assignee", "has_scoring")),
    Transition("T-28", (S.IN_REVIEW,), S.PENDING_RISK_APPROVAL, C.APPROVE, UW, ("assignee", "has_scoring")),
    Transition("T-28", (S.IN_REVIEW,), S.PENDING_RISK_APPROVAL, C.MAKE_COUNTER_OFFER, UW, ("assignee", "has_scoring")),
    Transition("T-29", (S.IN_REVIEW,), S.INFO_REQUESTED, C.REQUEST_INFO, UW, ("assignee",)),
    Transition("T-30", (S.IN_REVIEW,), S.DECLINED, C.DECLINE, UW, ("assignee",)),
    Transition("T-31", (S.PENDING_RISK_APPROVAL,), S.OFFER_PENDING, C.CONFIRM_DECISION, RM, ("not_proposer",)),
    Transition("T-32", (S.PENDING_RISK_APPROVAL,), S.IN_REVIEW, C.RETURN_DECISION, RM),
    Transition("T-33", (S.OFFER_PENDING,), S.OFFER_ACCEPTED, C.ACCEPT_OFFER, CLIENT, ("owner", "offer_not_expired")),
    Transition("T-34", (S.OFFER_PENDING,), S.OFFER_DECLINED, C.DECLINE_OFFER, CLIENT, ("owner",)),
    Transition("T-35", (S.OFFER_PENDING,), S.OFFER_EXPIRED, T.OFFER_EXPIRY, TIMER),
    Transition("T-36", (S.OFFER_ACCEPTED,), S.SIGNING, T.DOCUMENTS_PREPARED, SYSTEM),
    Transition("T-37", (S.OFFER_ACCEPTED,), S.PROCESSING_ERROR, T.TASK_FAILED, SYSTEM),
    Transition("T-38", (S.OFFER_ACCEPTED, S.SIGNING), S.OFFER_DECLINED, C.DECLINE_OFFER, CLIENT, ("owner",)),
    Transition("T-39", (S.SIGNING,), S.SIGNED, C.SIGN, CLIENT, ("owner", "offer_not_expired")),
    Transition("T-40", (S.SIGNING,), S.OFFER_EXPIRED, T.OFFER_EXPIRY, TIMER),
    Transition(
        "T-41",
        (S.SUBMITTED, S.ENRICHMENT, S.EXTERNAL_SERVICE_UNAVAILABLE, S.SCORING, S.DECISIONING, S.MANUAL_REVIEW, S.IN_REVIEW, S.PENDING_RISK_APPROVAL),
        S.CANCELLED,
        C.WITHDRAW,
        CLIENT,
        ("owner",),
    ),
    Transition("T-42", (S.SIGNED,), S.ISSUED, T.LOAN_ISSUED, SYSTEM),
    Transition("T-43", (S.SIGNED,), S.PROCESSING_ERROR, T.TASK_FAILED, SYSTEM),
    Transition("T-44", (S.PROCESSING_ERROR,), None, C.RETRY_PROCESSING, STAFF, ("failed_stage_set",)),
    Transition("T-45", (S.PROCESSING_ERROR,), S.CANCELLED, C.WITHDRAW, CLIENT, ("owner", "failed_before_decision")),
    Transition("T-46", (S.PROCESSING_ERROR,), S.OFFER_DECLINED, C.DECLINE_OFFER, CLIENT, ("owner", "failed_at_documents")),
)

BY_ID: dict[str, list[Transition]] = {}
for _t in TRANSITIONS:
    BY_ID.setdefault(_t.id, []).append(_t)

# commands without a status change (section 5.1): status -> roles
STATIC_COMMANDS: tuple[tuple[str, frozenset[Status] | None, frozenset[ActorType]], ...] = (
    (C.UPDATE_DRAFT, frozenset({S.DRAFT}), CLIENT),
    (C.PREFILL_BY_INN, frozenset({S.DRAFT}), CLIENT),
    (C.GIVE_CONSENT, frozenset({S.DRAFT}), CLIENT),
    (C.REVOKE_CONSENT, frozenset({S.DRAFT}), CLIENT),
    (C.UPLOAD_DOCUMENT, frozenset({S.DRAFT, S.INFO_REQUESTED}), CLIENT),
    (C.DELETE_DOCUMENT, frozenset({S.DRAFT}), CLIENT),
    (C.REQUEST_SIGNING_CODE, frozenset({S.SIGNING}), CLIENT),
    (C.ADD_COMMENT, None, STAFF),  # any status except DRAFT
)

PRE_DECISION_STAGES = frozenset({S.SUBMITTED, S.ENRICHMENT, S.SCORING, S.DECISIONING})


def processing_retry_target(failed_stage: str | None, error_code: str | None) -> str | None:
    """Refresh missing source evidence before repeating scoring and decisioning."""
    if error_code == "SOURCE_INVALID_RESPONSE" and failed_stage in (S.SCORING, S.DECISIONING):
        return S.ENRICHMENT
    return failed_stage


@dataclass
class GuardContext:
    """Facts needed by the guards; filled by the caller from the database."""

    actor_type: ActorType
    actor_id: object | None
    owner_id: object | None = None
    assignee_id: object | None = None
    proposer_id: object | None = None
    failed_stage: str | None = None
    offer_expires_at: datetime | None = None
    now: datetime | None = None
    has_scoring: bool = False
    manual_review_required: bool = False
    auto_info_request_count: int = 0
    max_auto_info_cycles: int = 3
    enrichment_retry_count: int = 0
    max_enrichment_retries: int = 5


def guard_failure(guard: str, ctx: GuardContext) -> str | None:
    """None if the guard passes, otherwise an error code."""
    if guard == "owner":
        return None if ctx.actor_id is not None and ctx.actor_id == ctx.owner_id else "NOT_FOUND"
    if guard == "assignee":
        return None if ctx.actor_id is not None and ctx.actor_id == ctx.assignee_id else "NOT_ASSIGNEE"
    if guard == "has_assignee":
        return None if ctx.assignee_id is not None else "NO_ASSIGNEE"
    if guard == "not_proposer":
        return None if ctx.proposer_id is None or ctx.proposer_id != ctx.actor_id else "FOUR_EYES_SAME_USER"
    if guard == "failed_stage_set":
        return None if ctx.failed_stage else "FAILED_STAGE_MISSING"
    if guard == "failed_before_decision":
        return None if ctx.failed_stage in PRE_DECISION_STAGES else "INVALID_TRANSITION"
    if guard == "failed_at_documents":
        return None if ctx.failed_stage == S.OFFER_ACCEPTED else "INVALID_TRANSITION"
    if guard == "offer_not_expired":
        if ctx.offer_expires_at is None or ctx.now is None:
            return "OFFER_EXPIRED"
        return None if ctx.now < ctx.offer_expires_at else "OFFER_EXPIRED"
    if guard == "has_scoring":
        return None if ctx.has_scoring else "SCORING_REQUIRED"
    if guard == "not_manual_review_required":
        return None if not ctx.manual_review_required else "MANUAL_REVIEW_REQUIRED"
    if guard == "auto_info_cycles_left":
        return None if ctx.auto_info_request_count < ctx.max_auto_info_cycles else "INFO_CYCLES_EXCEEDED"
    if guard == "auto_info_cycles_exhausted":
        return None if ctx.auto_info_request_count >= ctx.max_auto_info_cycles else "INFO_CYCLES_LEFT"
    if guard == "enrichment_retries_left":
        return None if ctx.enrichment_retry_count < ctx.max_enrichment_retries else "RETRIES_EXHAUSTED"
    raise KeyError(guard)


def candidates(status: str, trigger: str) -> list[Transition]:
    return [t for t in TRANSITIONS if t.trigger == trigger and status in t.sources]


def resolve(transition_id: str, status: str, trigger: str | None = None) -> Transition | None:
    for t in BY_ID.get(transition_id, []):
        if status in t.sources and (trigger is None or t.trigger == trigger):
            return t
    return None


def available_actions(status: str, ctx: GuardContext, is_history: bool = False) -> list[str]:
    """Commands the actor may run now; the frontend renders buttons only from this list."""
    if is_history:
        return []
    actions: list[str] = []
    for t in TRANSITIONS:
        if t.trigger not in Command.__members__ or status not in t.sources or ctx.actor_type not in t.actors:
            continue
        if t.id == "T-28":
            continue  # same commands as T-27; the handler chooses the target
        if any(guard_failure(g, ctx) for g in t.guards):
            continue
        if t.trigger not in actions:
            actions.append(t.trigger)
    for command, statuses, actors in STATIC_COMMANDS:
        if ctx.actor_type not in actors:
            continue
        if statuses is None:
            if status == S.DRAFT:
                continue
        elif status not in statuses:
            continue
        if ctx.actor_type == ActorType.CLIENT and guard_failure("owner", ctx):
            continue
        if command not in actions:
            actions.append(command)
    return actions
