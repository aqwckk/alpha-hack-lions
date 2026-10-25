"""Request and response contracts (OpenAPI). Client responses are strict allowlists: no score, grade, internal status."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Money = str  # decimal as string with two digits, e.g. "1200000.00"
MoneyIn = str | int


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Open(BaseModel):
    model_config = ConfigDict(extra="allow")


# Errors and pages


class ErrorField(BaseModel):
    field: str
    code: str
    message: str | None = None


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str | None = None
    details: dict[str, Any] | None = None
    fields: list[ErrorField] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


# Auth


class LoginRequest(Strict):
    login: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class UserInfo(BaseModel):
    id: str
    login: str
    role: Literal["CLIENT", "UNDERWRITER", "RISK_MANAGER"]
    full_name: str
    representative_role: str | None = None
    company_inns: list[str] = []


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int
    user: UserInfo


# Catalog


class MatchRequest(Strict):
    purpose: str
    amount: MoneyIn
    term_months: int = Field(ge=1, le=120)
    applicant_type: Literal["LEGAL_ENTITY", "INDIVIDUAL_ENTREPRENEUR"] | None = None
    inn: str | None = Field(default=None, max_length=12)


class ProductCard(BaseModel):
    product_code: str
    name: str
    description: str
    decision_speed: str
    review_mode: str
    rate_from_percent: str
    term_months: int
    term_note: str | None
    monthly_payment_from: Money
    total_payment_from: Money
    overpayment_from: Money
    amount_min: Money
    amount_max: Money
    amount_step: Money
    term_min_months: int
    term_max_months: int
    requirements: list[str]
    required_documents: list[str]
    available: bool
    unavailable_reason: str | None
    eligible_date: str | None
    recommended: bool
    rank: int


class MatchResponse(BaseModel):
    cards: list[ProductCard]
    hints: list[str]
    empty_text: str | None
    disclaimer: str
    early_check: dict[str, Any] | None = None


class CalculateRequest(Strict):
    product_code: str
    amount: MoneyIn
    term_months: int = Field(ge=1, le=120)
    rate_percent: str | None = None
    with_schedule: bool = False


class AnalyticsEventRequest(Strict):
    event_type: Literal["PRODUCT_WIZARD_STARTED", "PRODUCT_SELECTED"]
    wizard_session_id: str = Field(min_length=8, max_length=64)
    product_code: str | None = None
    purpose: str | None = None
    amount: MoneyIn | None = None
    term_months: int | None = None
    rank: int | None = None
    was_recommended: bool | None = None


# Client commands


class CreateApplicationRequest(Strict):
    product_code: str
    purpose: str
    amount: MoneyIn
    term_months: int
    wizard_session_id: str | None = Field(default=None, max_length=64)


class DraftUpdateRequest(Strict):
    expected_version: int
    purpose: str | None = None
    amount: MoneyIn | None = None
    term_months: int | None = None
    applicant_inn: str | None = None
    representative_role: str | None = None
    monthly_revenue_declared: MoneyIn | None = None
    existing_monthly_payments_declared: MoneyIn | None = None
    owner_guarantee_agreed: bool | None = None
    collateral_type: str | None = None
    collateral_description: str | None = None
    collateral_value: MoneyIn | None = None
    collateral_owner: str | None = None
    investment_project_description: str | None = None
    own_contribution_amount: MoneyIn | None = None
    client_comment: str | None = None


class PrefillRequest(Strict):
    expected_version: int | None = None
    inn: str | None = None


class VersionOnly(Strict):
    expected_version: int


class OptionalVersion(Strict):
    expected_version: int | None = None


class InfoAnswer(Strict):
    item_id: uuid.UUID
    answer_text: str | None = Field(default=None, max_length=2000)
    answer_value: MoneyIn | None = None
    document_ids: list[uuid.UUID] | None = None


class RespondInfoRequest(Strict):
    expected_version: int
    answers: list[InfoAnswer] = Field(max_length=10)


class AcceptOfferRequest(Strict):
    expected_version: int
    option_id: uuid.UUID


class DeclineOfferRequest(Strict):
    expected_version: int
    reason_code: str | None = None


class SignRequest(Strict):
    expected_version: int
    code: str = Field(min_length=1, max_length=12)


# Staff commands


class CommentCommand(Strict):
    expected_version: int
    comment: str | None = Field(default=None, max_length=4000)


class OptionInput(Strict):
    product_code: str | None = None
    amount: MoneyIn
    term_months: int


class CounterOfferRequest(Strict):
    expected_version: int
    comment: str | None = Field(default=None, max_length=4000)
    options: list[OptionInput] = Field(min_length=1, max_length=3)


class InfoItemInput(Strict):
    reason_code: str
    answer_type: Literal["DOCUMENT", "FIELD", "TEXT"]
    field_name: str | None = None
    document_type: str | None = None
    client_text: str | None = Field(default=None, max_length=1000)
    required: bool = True


class RequestInfoRequest(Strict):
    expected_version: int
    comment: str | None = Field(default=None, max_length=4000)
    items: list[InfoItemInput] = Field(min_length=1, max_length=10)


class DeclineRequest(Strict):
    expected_version: int
    comment: str | None = Field(default=None, max_length=4000)
    reason_codes: list[str] = Field(min_length=1, max_length=12)


class AddCommentRequest(Strict):
    body: str = Field(min_length=1, max_length=4000)


class OutageRequest(Strict):
    source: Literal["REGISTRY", "FNS", "FINANCIAL_STATEMENTS", "CREDIT_BUREAU", "BANK_TURNOVER", "EDO", "ABS"]
    failure: Literal["TIMEOUT", "HTTP_500"] | None = None


# Client view (strict allowlist)


class StatusText(Strict):
    title: str | None
    what_is_happening: str | None
    what_next: str | None
    deadline_text: str | None
    deadline_at: str | None
    notes: list[str]


class ProgressStep(Strict):
    step: int
    title: str
    state: Literal["DONE", "CURRENT", "ACTION_REQUIRED", "PENDING", "SKIPPED", "STOPPED"]
    note: str | None


class ConsentState(Strict):
    consent_type: str
    given: bool
    granted_at: str | None
    expires_at: str | None
    text_version: str


class DocumentInfo(Strict):
    id: str
    document_type: str
    document_title: str
    file_name: str
    mime_type: str
    size_bytes: int
    sha256: str
    uploaded_at: str | None
    info_request_item_id: str | None


class RequiredDocument(Strict):
    document_type: str
    title: str
    purpose: str
    uploaded: bool


class InfoItemView(Strict):
    id: str
    answer_type: str
    field_name: str | None
    field_label: str | None
    current_value: str | None
    document_type: str | None
    document_title: str | None
    client_text: str
    required: bool
    answer_text: str | None
    answer_value: str | None
    document_ids: list[str]


class InfoRequestView(Strict):
    id: str
    status: str
    due_at: str | None
    due_text: str
    created_at: str | None
    answered_at: str | None
    items: list[InfoItemView]


class ReasonText(Strict):
    text: str | None
    next_step: str | None


class CreditLineView(Strict):
    monthly_interest_full_use: Money
    payment_full_limit_12m: Money


class OptionView(Strict):
    id: str
    option_type: str
    product_code: str
    product_name: str
    amount: Money
    term_months: int
    rate_percent: str
    monthly_payment: Money
    total_payment: Money
    overpayment: Money
    requires_owner_guarantee: bool
    requires_collateral: bool
    tranche_max_term_months: int | None
    recommended: bool
    difference_text: str | None
    credit_line: CreditLineView | None = None


class RequestedTerms(Strict):
    amount: Money | None
    term_months: int | None
    monthly_payment: Money | None


class OfferView(Strict):
    id: str
    outcome: Literal["APPROVED", "COUNTER_OFFER"]
    status: str
    expires_at: str | None
    expires_text: str
    selected_option_id: str | None
    requested: RequestedTerms
    reasons: list[ReasonText]
    options: list[OptionView]


class DecisionClientView(Strict):
    outcome: Literal["DECLINED"]
    reasons: list[ReasonText]


class SigningDoc(Strict):
    id: str
    document_type: str
    title: str
    sha256: str


class ActiveCode(Strict):
    expires_at: str | None
    attempts_left: int


class SigningView(Strict):
    package_id: str
    contract_number: str
    status: str
    documents: list[SigningDoc]
    active_code: ActiveCode | None
    note: str


class LoanView(Strict):
    contract_number: str
    account_number_masked: str
    operation_type: str
    product_code: str
    amount: Money
    rate_percent: str
    term_months: int
    monthly_payment: Money
    issued_at: str | None
    first_payment_date: str


class TimelineItem(Strict):
    client_status: str
    title: str
    at: str | None


class NotificationView(Strict):
    id: str
    code: str
    title: str
    body: str
    created_at: str | None
    read: bool


class FinalTerms(Strict):
    product_code: str | None
    amount: Money
    term_months: int | None
    rate_percent: str
    monthly_payment: Money
    option_id: str | None = None


class EarlyWarning(Strict):
    reason_code: str
    text: str
    next_step: str | None


class FieldWarning(Strict):
    field: str
    code: str
    message: str | None


class ClientApplication(Strict):
    id: str
    application_number: str
    version: int
    product_code: str
    product_name: str
    purpose: str
    purpose_title: str
    form: dict[str, Any]
    applicant_type: str | None
    inn_check_status: Literal["NOT_CHECKED", "FOUND", "NOT_FOUND", "UNAVAILABLE"]
    company: dict[str, Any] | None
    early_warnings: list[EarlyWarning]
    client_status: Literal["FILLING", "SENT", "CHECKING", "ACTION_REQUIRED", "SPECIALIST_REVIEW", "DECISION_READY", "DOCUMENTS", "PAYOUT", "COMPLETED", "REJECTED", "WITHDRAWN", "EXPIRED"]
    client_status_text: StatusText
    progress_step: int
    progress: list[ProgressStep]
    action_required: bool
    available_actions: list[str]
    consents: list[ConsentState]
    documents: list[DocumentInfo]
    required_documents: list[RequiredDocument]
    warnings: list[FieldWarning]
    info_request: InfoRequestView | None
    decision: DecisionClientView | None
    offer: OfferView | None
    final_terms: FinalTerms | None
    signing: SigningView | None
    loan: LoanView | None
    timeline: list[TimelineItem]
    notifications: list[NotificationView]
    created_at: str | None
    updated_at: str | None
    submitted_at: str | None


class ClientApplicationListItem(Strict):
    id: str
    application_number: str
    product_code: str
    product_name: str
    amount: Money | None
    term_months: int | None
    company_short_name: str | None
    client_status: str
    client_status_title: str
    progress_step: int
    next_action_label: str
    updated_at: str | None
    version: int


class ClientApplicationPage(BaseModel):
    items: list[ClientApplicationListItem]
    page: int
    page_size: int
    total: int


class PrefillResult(BaseModel):
    status: Literal["FOUND", "NOT_FOUND", "SOURCE_UNAVAILABLE"]
    message: str | None


class PrefillResponse(BaseModel):
    prefill: PrefillResult
    application: ClientApplication


class DraftResponse(BaseModel):
    application: ClientApplication
    field_errors: list[ErrorField] = []


class SigningCodeResponse(BaseModel):
    signing_code_id: str
    expires_at: str
    ttl_seconds: int
    attempts_left: int
    code: str | None = Field(default=None, description="Only in demo mode (DEMO_MODE=true): the prototype has no SMS or email")
    demo_note: str | None = None


class ExplanationResponse(BaseModel):
    text: str
    label: str | None
    fallback_used: bool


class ScheduleRow(BaseModel):
    n: int
    date: str
    payment: Money
    interest: Money
    principal: Money
    balance: Money


class ScheduleResponse(BaseModel):
    product_code: str
    amount: Money
    term_months: int
    rate_percent: str
    monthly_payment: Money
    total_payment: Money
    overpayment: Money
    first_payment_date: str
    rows: list[ScheduleRow]


# Staff views (internal data allowed)


class StaffListItem(Open):
    id: str
    application_number: str
    status: str
    product_code: str
    amount: Money | None
    version: int


class StaffPage(BaseModel):
    items: list[StaffListItem]
    page: int
    page_size: int
    total: int
    counters: dict[str, int] = {}


class StaffCard(Open):
    id: str
    application_number: str
    version: int
    status: str
    client_status: str
    available_actions: list[str]


class AiSummaryResponse(BaseModel):
    blocks: dict[str, list[str]]
    label: str
    model_name: str | None
    fallback_used: bool
    latency_ms: int


class NotificationsPage(BaseModel):
    items: list[NotificationView | dict[str, Any]]
    unread: int
    page: int
    page_size: int
    total: int
