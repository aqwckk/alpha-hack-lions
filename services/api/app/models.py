"""Relational model (docs/architecture/data-model.md). Money is NUMERIC(18,2), instants are timestamptz (UTC)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .enums import (
    ERROR_CODES,
    ActorType,
    AnswerType,
    ConsentType,
    DocumentType,
    InfoRequestSource,
    JobKind,
    Outcome,
    Role,
    Source,
    Status,
    sql_in,
)

MONEY = Numeric(18, 2)
TS = DateTime(timezone=True)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSONB, list[Any]: JSONB}


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def created_at() -> Mapped[datetime]:
    return mapped_column(TS, nullable=False, server_default=func.now())


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint(f"role IN ({sql_in(Role)})", name="ck_users_role"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    login: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    representative_role: Mapped[str | None] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = created_at()


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (CheckConstraint("applicant_type IN ('LEGAL_ENTITY','INDIVIDUAL_ENTREPRENEUR')", name="ck_companies_type"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    inn: Mapped[str] = mapped_column(String(12), unique=True, nullable=False)
    applicant_type: Mapped[str] = mapped_column(String(32), nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = created_at()


class CompanyMembership(Base):
    __tablename__ = "company_memberships"
    __table_args__ = (UniqueConstraint("user_id", "company_id", name="uq_membership"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    representative_role: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = created_at()


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        CheckConstraint(f"status IN ({sql_in(Status)})", name="ck_app_status"),
        CheckConstraint(f"failed_stage IS NULL OR failed_stage IN ({sql_in(Status)})", name="ck_app_failed_stage"),
        CheckConstraint(f"last_error_code IS NULL OR last_error_code IN ({sql_in(ERROR_CODES)})", name="ck_app_error_code"),
        CheckConstraint("version >= 1", name="ck_app_version"),
        CheckConstraint("amount IS NULL OR amount > 0", name="ck_app_amount"),
        CheckConstraint("term_months IS NULL OR term_months BETWEEN 1 AND 120", name="ck_app_term"),
        CheckConstraint("cancel_reason IS NULL OR cancel_reason IN ('CL_WITHDRAWN','CL_DRAFT_EXPIRED','CL_INFO_TIMEOUT')", name="ck_app_cancel"),
        Index("ix_app_status_due", "status", "review_due_at"),
        Index("ix_app_client", "client_user_id", "updated_at"),
        Index("ix_app_retry", "next_retry_at", postgresql_where=text("status = 'EXTERNAL_SERVICE_UNAVAILABLE'")),
        Index(
            "uq_app_active_inn_product",
            "applicant_inn",
            "product_code",
            unique=True,
            postgresql_where=text(
                "is_history = false AND applicant_inn IS NOT NULL AND status NOT IN "
                "('DRAFT','ISSUED','DECLINED','OFFER_DECLINED','OFFER_EXPIRED','CANCELLED')"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    application_number: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    client_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    company_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("companies.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=Status.DRAFT)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_history: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    wizard_session_id: Mapped[str | None] = mapped_column(String(64))

    # client form (data-requirements.md, section 1)
    product_code: Mapped[str] = mapped_column(String(32), nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[Decimal | None] = mapped_column(MONEY)
    term_months: Mapped[int | None] = mapped_column(Integer)
    applicant_inn: Mapped[str | None] = mapped_column(String(12))
    applicant_type: Mapped[str | None] = mapped_column(String(32))
    representative_role: Mapped[str | None] = mapped_column(String(32))
    monthly_revenue_declared: Mapped[Decimal | None] = mapped_column(MONEY)
    existing_monthly_payments_declared: Mapped[Decimal | None] = mapped_column(MONEY)
    owner_guarantee_agreed: Mapped[bool | None] = mapped_column(Boolean)
    collateral_type: Mapped[str | None] = mapped_column(String(32))
    collateral_description: Mapped[str | None] = mapped_column(String(500))
    collateral_value: Mapped[Decimal | None] = mapped_column(MONEY)
    collateral_owner: Mapped[str | None] = mapped_column(String(32))
    investment_project_description: Mapped[str | None] = mapped_column(String(2000))
    own_contribution_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    client_comment: Mapped[str | None] = mapped_column(String(1000))

    # prefill by INN (section 3)
    inn_check_status: Mapped[str] = mapped_column(String(16), nullable=False, default="NOT_CHECKED")
    company_short_name: Mapped[str | None] = mapped_column(String(255))
    registry_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    prefilled_at: Mapped[datetime | None] = mapped_column(TS)
    early_warnings: Mapped[list[Any] | None] = mapped_column(JSONB)

    # state machine fields (application-states.md, section 2)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    failed_stage: Mapped[str | None] = mapped_column(String(32))
    last_error_code: Mapped[str | None] = mapped_column(String(32))
    enrichment_retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(TS)
    auto_info_request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    info_request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    review_queued_at: Mapped[datetime | None] = mapped_column(TS)
    review_due_at: Mapped[datetime | None] = mapped_column(TS)
    sla_breached: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    manual_review_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    manual_review_reasons: Mapped[list[Any] | None] = mapped_column(JSONB)
    cancel_reason: Mapped[str | None] = mapped_column(String(32))
    current_offer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    submitted_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status_changed_at: Mapped[datetime] = mapped_column(TS, nullable=False, server_default=func.now())

    final_product_code: Mapped[str | None] = mapped_column(String(32))
    final_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    final_term_months: Mapped[int | None] = mapped_column(Integer)
    final_rate_percent: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    final_monthly_payment: Mapped[Decimal | None] = mapped_column(MONEY)
    final_option_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = mapped_column(TS, nullable=False, server_default=func.now())
    submitted_at: Mapped[datetime | None] = mapped_column(TS)
    decided_at: Mapped[datetime | None] = mapped_column(TS)
    issued_at: Mapped[datetime | None] = mapped_column(TS)
    closed_at: Mapped[datetime | None] = mapped_column(TS)

    # denormalized for lists (source of truth: scoring_results, decisions)
    score: Mapped[int | None] = mapped_column(Integer)
    grade: Mapped[str | None] = mapped_column(String(1))


class FieldChange(Base):
    """History of client form changes after submission (answers to info requests)."""

    __tablename__ = "application_field_changes"

    id: Mapped[uuid.UUID] = uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id"), nullable=False, index=True)
    field_name: Mapped[str] = mapped_column(String(64), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    info_request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    changed_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    changed_at: Mapped[datetime] = created_at()


class Consent(Base):
    __tablename__ = "consents"
    __table_args__ = (CheckConstraint(f"consent_type IN ({sql_in(ConsentType)})", name="ck_consent_type"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    consent_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_inn: Mapped[str | None] = mapped_column(String(12))
    text_version: Mapped[str] = mapped_column(String(64), nullable=False)
    text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(TS)
    revoked_at: Mapped[datetime | None] = mapped_column(TS)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(f"document_type IN ({sql_in(DocumentType)})", name="ck_doc_type"),
        CheckConstraint("mime_type IN ('application/pdf','image/jpeg','image/png')", name="ck_doc_mime"),
        CheckConstraint("size_bytes > 0 AND size_bytes <= 10485760", name="ck_doc_size"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id"), nullable=False, index=True)
    document_type: Mapped[str] = mapped_column(String(32), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    uploaded_at: Mapped[datetime] = created_at()
    info_request_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    storage_key: Mapped[str] = mapped_column(String(64), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(TS)


class DocumentContent(Base):
    """File bodies kept apart from metadata (in production: object storage with encryption)."""

    __tablename__ = "document_contents"

    storage_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)


class SourceSnapshot(Base):
    __tablename__ = "source_snapshots"
    __table_args__ = (
        CheckConstraint(f"source IN ({sql_in(Source)})", name="ck_snapshot_source"),
        CheckConstraint("outcome IN ('SUCCESS','NO_DATA','FAILED')", name="ck_snapshot_outcome"),
        Index("ix_snapshot_lookup", "application_id", "source", "requested_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id"), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    inn: Mapped[str] = mapped_column(String(12), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(32))
    http_status: Mapped[int | None] = mapped_column(Integer)
    external_request_id: Mapped[str | None] = mapped_column(String(64))
    requested_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    responded_at: Mapped[datetime | None] = mapped_column(TS)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    valid_until: Mapped[datetime | None] = mapped_column(TS)


class ScoringResult(Base):
    __tablename__ = "scoring_results"

    id: Mapped[uuid.UUID] = uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id"), nullable=False, index=True)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    grade: Mapped[str] = mapped_column(String(1), nullable=False)
    pd: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    features: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    factor_contributions: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    scoring_input: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    scorecard_version: Mapped[str] = mapped_column(String(64), nullable=False)
    scorecard_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    calculated_at: Mapped[datetime] = created_at()


class Decision(Base):
    __tablename__ = "decisions"
    __table_args__ = (
        CheckConstraint(f"outcome IN ({sql_in(Outcome)})", name="ck_decision_outcome"),
        CheckConstraint("mode IN ('AUTO','MANUAL')", name="ck_decision_mode"),
        CheckConstraint("status IN ('PROPOSED','FINAL','REJECTED')", name="ck_decision_status"),
        CheckConstraint("confirmed_by IS NULL OR proposed_by IS NULL OR confirmed_by <> proposed_by", name="ck_decision_four_eyes"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id"), nullable=False, index=True)
    scoring_result_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("scoring_results.id"))
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="FINAL")
    reason_codes: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    reason_details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    rules_path: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    values: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    recommendation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    proposed_options: Mapped[list[Any] | None] = mapped_column(JSONB)
    override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    four_eyes_trigger: Mapped[str | None] = mapped_column(String(32))
    comment: Mapped[str | None] = mapped_column(Text)
    proposed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    scorecard_version: Mapped[str | None] = mapped_column(String(64))
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_sha256: Mapped[str | None] = mapped_column(String(64))
    grade: Mapped[str | None] = mapped_column(String(1))
    created_at: Mapped[datetime] = created_at()


class Offer(Base):
    __tablename__ = "offers"
    __table_args__ = (CheckConstraint("status IN ('ACTIVE','ACCEPTED','DECLINED','EXPIRED','CANCELLED')", name="ck_offer_status"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id"), nullable=False, index=True)
    decision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("decisions.id"), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    expires_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    selected_option_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    decline_reason_code: Mapped[str | None] = mapped_column(String(32))
    expiring_notified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = created_at()


class OfferOption(Base):
    __tablename__ = "offer_options"
    __table_args__ = (
        CheckConstraint(
            "option_type IN ('REQUESTED','AMOUNT_REDUCED','TERM_EXTENDED','PRODUCT_CHANGED','UNDERWRITER_TERMS')",
            name="ck_option_type",
        ),
        CheckConstraint("amount > 0 AND monthly_payment > 0", name="ck_option_money"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    offer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("offers.id"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    option_type: Mapped[str] = mapped_column(String(32), nullable=False)
    product_code: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    term_months: Mapped[int] = mapped_column(Integer, nullable=False)
    rate_percent: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    monthly_payment: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    total_payment: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    overpayment: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    requires_owner_guarantee: Mapped[bool] = mapped_column(Boolean, nullable=False)
    requires_collateral: Mapped[bool] = mapped_column(Boolean, nullable=False)
    tranche_max_term_months: Mapped[int | None] = mapped_column(Integer)
    recommended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class InfoRequest(Base):
    __tablename__ = "info_requests"
    __table_args__ = (
        CheckConstraint(f"source IN ({sql_in(InfoRequestSource)})", name="ck_ir_source"),
        CheckConstraint("status IN ('OPEN','ANSWERED','EXPIRED','CANCELLED')", name="ck_ir_status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id"), nullable=False, index=True)
    decision_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("decisions.id"))
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN")
    cycle_number: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()
    due_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    answered_at: Mapped[datetime | None] = mapped_column(TS)


class InfoRequestItem(Base):
    __tablename__ = "info_request_items"
    __table_args__ = (CheckConstraint(f"answer_type IN ({sql_in(AnswerType)})", name="ck_iri_answer_type"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    info_request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("info_requests.id"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    answer_type: Mapped[str] = mapped_column(String(16), nullable=False)
    field_name: Mapped[str | None] = mapped_column(String(64))
    document_type: Mapped[str | None] = mapped_column(String(32))
    client_text: Mapped[str] = mapped_column(Text, nullable=False)
    employee_text: Mapped[str | None] = mapped_column(Text)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    answer_text: Mapped[str | None] = mapped_column(Text)
    answer_value: Mapped[str | None] = mapped_column(String(255))
    document_ids: Mapped[list[Any] | None] = mapped_column(JSONB)


class DocumentPackage(Base):
    __tablename__ = "document_packages"

    id: Mapped[uuid.UUID] = uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id"), nullable=False, index=True)
    offer_option_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("offer_options.id"), nullable=False)
    external_package_id: Mapped[str] = mapped_column(String(64), nullable=False)
    edo_operation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    contract_number: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="READY_FOR_SIGNING")
    created_at: Mapped[datetime] = created_at()


class GeneratedDocument(Base):
    __tablename__ = "generated_documents"

    id: Mapped[uuid.UUID] = uuid_pk()
    package_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_packages.id"), nullable=False, index=True)
    document_type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class SigningCode(Base):
    __tablename__ = "signing_codes"

    id: Mapped[uuid.UUID] = uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id"), nullable=False, index=True)
    package_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_packages.id"), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    documents_sha256: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    used_at: Mapped[datetime | None] = mapped_column(TS)
    revoked_at: Mapped[datetime | None] = mapped_column(TS)
    notification_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class Signature(Base):
    __tablename__ = "signatures"

    id: Mapped[uuid.UUID] = uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id"), nullable=False, unique=True)
    signing_code_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("signing_codes.id"), nullable=False)
    package_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_packages.id"), nullable=False)
    external_signature_id: Mapped[str | None] = mapped_column(String(64))
    documents_sha256: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    signed_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))


class Loan(Base):
    __tablename__ = "loans"
    __table_args__ = (CheckConstraint("operation_type IN ('DISBURSEMENT','CREDIT_LINE_LIMIT')", name="ck_loan_operation"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id"), nullable=False, unique=True)
    contract_number: Mapped[str] = mapped_column(String(64), nullable=False)
    account_number_masked: Mapped[str] = mapped_column(String(32), nullable=False)
    product_code: Mapped[str] = mapped_column(String(32), nullable=False)
    operation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    rate_percent: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    term_months: Mapped[int] = mapped_column(Integer, nullable=False)
    monthly_payment: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    first_payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    abs_operation_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)


class Comment(Base):
    __tablename__ = "comments"
    __table_args__ = (CheckConstraint("kind IN ('INTERNAL','DECISION','RELEASE','RETURN')", name="ck_comment_kind"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id"), nullable=False, index=True)
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="INTERNAL")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = created_at()


class StatusHistory(Base):
    __tablename__ = "status_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id"), nullable=False, index=True)
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    transition_id: Mapped[str] = mapped_column(String(8), nullable=False)
    trigger: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(TS, nullable=False)


class Event(Base):
    """Domain event journal and transactional outbox (insert-only, see trigger in the migration)."""

    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint(f"actor_type IN ({sql_in(ActorType)})", name="ck_event_actor"),
        Index("ix_events_app_time", "application_id", "occurred_at"),
        Index("ix_events_type_time", "event_type", "occurred_at"),
        Index("ix_events_unpublished", "occurred_at", postgresql_where=text("published_at IS NULL")),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    application_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("applications.id"))
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    application_version: Mapped[int | None] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    published_at: Mapped[datetime | None] = mapped_column(TS)


class AuditLog(Base):
    """Who did what, when and from where (commands, reads of personal data, logins). Insert-only."""

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_time", "occurred_at"), Index("ix_audit_app", "application_id", "occurred_at"))

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(TS, nullable=False, server_default=func.now())
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor_login: Mapped[str | None] = mapped_column(String(64))
    actor_role: Mapped[str | None] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    object_type: Mapped[str | None] = mapped_column(String(32))
    object_id: Mapped[str | None] = mapped_column(String(64))
    application_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    request_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class Job(Base):
    """Work queue on PostgreSQL (SELECT ... FOR UPDATE SKIP LOCKED)."""

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(f"kind IN ({sql_in(JobKind)})", name="ck_job_kind"),
        CheckConstraint("status IN ('QUEUED','RUNNING','DONE','FAILED','CANCELLED')", name="ck_job_status"),
        Index("ix_jobs_ready", "run_at", postgresql_where=text("status = 'QUEUED'")),
        Index("ix_jobs_running", "locked_at", postgresql_where=text("status = 'RUNNING'")),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id"), nullable=False, index=True)
    expected_status: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="QUEUED")
    run_at: Mapped[datetime] = mapped_column(TS, nullable=False, server_default=func.now())
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    locked_by: Mapped[str | None] = mapped_column(String(128))
    locked_at: Mapped[datetime | None] = mapped_column(TS)
    last_error: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = created_at()
    finished_at: Mapped[datetime | None] = mapped_column(TS)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user", "user_id", "created_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    application_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("applications.id"))
    code: Mapped[str] = mapped_column(String(48), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = created_at()
    read_at: Mapped[datetime | None] = mapped_column(TS)
    expires_at: Mapped[datetime | None] = mapped_column(TS)


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_idempotency_user_key"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    scope: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at()


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = created_at()
    expires_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(TS)
    revoked_at: Mapped[datetime | None] = mapped_column(TS)


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    __table_args__ = (Index("ix_login_attempts_login", "login", "attempted_at"), Index("ix_login_attempts_ip", "ip_address", "attempted_at"))

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    login: Mapped[str] = mapped_column(String(64), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(TS, nullable=False, server_default=func.now())


class SystemSecret(Base):
    __tablename__ = "system_secrets"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = created_at()


class ConfigVersion(Base):
    __tablename__ = "config_versions"
    __table_args__ = (
        UniqueConstraint("config_type", "version", "sha256", name="uq_config_version"),
        CheckConstraint("config_type IN ('SCORECARD','POLICY')", name="ck_config_type"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    config_type: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    author: Mapped[str | None] = mapped_column(String(128))
    effective_from: Mapped[str | None] = mapped_column(String(32))
    description: Mapped[str | None] = mapped_column(Text)
    first_loaded_at: Mapped[datetime] = created_at()
    last_loaded_at: Mapped[datetime] = mapped_column(TS, nullable=False, server_default=func.now())
