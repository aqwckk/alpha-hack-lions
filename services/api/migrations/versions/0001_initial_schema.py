"""Initial schema of the credit pipeline (docs/architecture/data-model.md).

Tables, CHECK constraints for the dictionaries of the process model, partial indexes for the queue and
timers, the application number sequence and insert-only triggers for the event journal and audit.

Revision ID: 0001
Revises: 
Create Date: 2026-10-23 02:29:23.260946
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('audit_log',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('actor_id', sa.UUID(), nullable=True),
    sa.Column('actor_login', sa.String(length=64), nullable=True),
    sa.Column('actor_role', sa.String(length=32), nullable=True),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('result', sa.String(length=16), nullable=False),
    sa.Column('object_type', sa.String(length=32), nullable=True),
    sa.Column('object_id', sa.String(length=64), nullable=True),
    sa.Column('application_id', sa.UUID(), nullable=True),
    sa.Column('ip_address', sa.String(length=64), nullable=True),
    sa.Column('user_agent', sa.String(length=512), nullable=True),
    sa.Column('request_id', sa.String(length=64), nullable=True),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_audit_app', 'audit_log', ['application_id', 'occurred_at'], unique=False)
    op.create_index('ix_audit_time', 'audit_log', ['occurred_at'], unique=False)
    op.create_table('companies',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('inn', sa.String(length=12), nullable=False),
    sa.Column('applicant_type', sa.String(length=32), nullable=False),
    sa.Column('short_name', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("applicant_type IN ('LEGAL_ENTITY','INDIVIDUAL_ENTREPRENEUR')", name='ck_companies_type'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('inn')
    )
    op.create_table('config_versions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('config_type', sa.String(length=16), nullable=False),
    sa.Column('version', sa.String(length=64), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('author', sa.String(length=128), nullable=True),
    sa.Column('effective_from', sa.String(length=32), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('first_loaded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_loaded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("config_type IN ('SCORECARD','POLICY')", name='ck_config_type'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('config_type', 'version', 'sha256', name='uq_config_version')
    )
    op.create_table('document_contents',
    sa.Column('storage_key', sa.String(length=64), nullable=False),
    sa.Column('content', sa.LargeBinary(), nullable=False),
    sa.PrimaryKeyConstraint('storage_key')
    )
    op.create_table('login_attempts',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('login', sa.String(length=64), nullable=False),
    sa.Column('ip_address', sa.String(length=64), nullable=True),
    sa.Column('success', sa.Boolean(), nullable=False),
    sa.Column('attempted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_login_attempts_ip', 'login_attempts', ['ip_address', 'attempted_at'], unique=False)
    op.create_index('ix_login_attempts_login', 'login_attempts', ['login', 'attempted_at'], unique=False)
    op.create_table('system_secrets',
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('value', sa.String(length=256), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('name')
    )
    op.create_table('users',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('login', sa.String(length=64), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=True),
    sa.Column('role', sa.String(length=32), nullable=False),
    sa.Column('full_name', sa.String(length=255), nullable=False),
    sa.Column('representative_role', sa.String(length=32), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('is_demo', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("role IN ('CLIENT', 'UNDERWRITER', 'RISK_MANAGER')", name='ck_users_role'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('login')
    )
    op.create_table('applications',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('application_number', sa.String(length=16), nullable=False),
    sa.Column('client_user_id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('is_history', sa.Boolean(), nullable=False),
    sa.Column('wizard_session_id', sa.String(length=64), nullable=True),
    sa.Column('product_code', sa.String(length=32), nullable=False),
    sa.Column('purpose', sa.String(length=32), nullable=False),
    sa.Column('amount', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('term_months', sa.Integer(), nullable=True),
    sa.Column('applicant_inn', sa.String(length=12), nullable=True),
    sa.Column('applicant_type', sa.String(length=32), nullable=True),
    sa.Column('representative_role', sa.String(length=32), nullable=True),
    sa.Column('monthly_revenue_declared', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('existing_monthly_payments_declared', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('owner_guarantee_agreed', sa.Boolean(), nullable=True),
    sa.Column('collateral_type', sa.String(length=32), nullable=True),
    sa.Column('collateral_description', sa.String(length=500), nullable=True),
    sa.Column('collateral_value', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('collateral_owner', sa.String(length=32), nullable=True),
    sa.Column('investment_project_description', sa.String(length=2000), nullable=True),
    sa.Column('own_contribution_amount', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('client_comment', sa.String(length=1000), nullable=True),
    sa.Column('inn_check_status', sa.String(length=16), nullable=False),
    sa.Column('company_short_name', sa.String(length=255), nullable=True),
    sa.Column('registry_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('prefilled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('early_warnings', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('assignee_id', sa.UUID(), nullable=True),
    sa.Column('failed_stage', sa.String(length=32), nullable=True),
    sa.Column('last_error_code', sa.String(length=32), nullable=True),
    sa.Column('enrichment_retry_count', sa.Integer(), nullable=False),
    sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('auto_info_request_count', sa.Integer(), nullable=False),
    sa.Column('info_request_count', sa.Integer(), nullable=False),
    sa.Column('review_queued_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('review_due_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('sla_breached', sa.Boolean(), nullable=False),
    sa.Column('manual_review_required', sa.Boolean(), nullable=False),
    sa.Column('manual_review_reasons', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('cancel_reason', sa.String(length=32), nullable=True),
    sa.Column('current_offer_id', sa.UUID(), nullable=True),
    sa.Column('submitted_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('status_changed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('final_product_code', sa.String(length=32), nullable=True),
    sa.Column('final_amount', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('final_term_months', sa.Integer(), nullable=True),
    sa.Column('final_rate_percent', sa.Numeric(precision=6, scale=2), nullable=True),
    sa.Column('final_monthly_payment', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('final_option_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('issued_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('score', sa.Integer(), nullable=True),
    sa.Column('grade', sa.String(length=1), nullable=True),
    sa.CheckConstraint("cancel_reason IS NULL OR cancel_reason IN ('CL_WITHDRAWN','CL_DRAFT_EXPIRED','CL_INFO_TIMEOUT')", name='ck_app_cancel'),
    sa.CheckConstraint("failed_stage IS NULL OR failed_stage IN ('DRAFT', 'SUBMITTED', 'INFO_REQUESTED', 'ENRICHMENT', 'EXTERNAL_SERVICE_UNAVAILABLE', 'SCORING', 'DECISIONING', 'MANUAL_REVIEW', 'IN_REVIEW', 'PENDING_RISK_APPROVAL', 'OFFER_PENDING', 'OFFER_ACCEPTED', 'SIGNING', 'SIGNED', 'PROCESSING_ERROR', 'ISSUED', 'DECLINED', 'OFFER_DECLINED', 'OFFER_EXPIRED', 'CANCELLED')", name='ck_app_failed_stage'),
    sa.CheckConstraint("last_error_code IS NULL OR last_error_code IN ('SOURCE_TIMEOUT', 'SOURCE_HTTP_5XX', 'SOURCE_INVALID_RESPONSE', 'CONFIG_LOAD_FAILED', 'EDO_FAILED', 'ABS_FAILED', 'CONSENT_MISSING', 'UNEXPECTED')", name='ck_app_error_code'),
    sa.CheckConstraint("status IN ('DRAFT', 'SUBMITTED', 'INFO_REQUESTED', 'ENRICHMENT', 'EXTERNAL_SERVICE_UNAVAILABLE', 'SCORING', 'DECISIONING', 'MANUAL_REVIEW', 'IN_REVIEW', 'PENDING_RISK_APPROVAL', 'OFFER_PENDING', 'OFFER_ACCEPTED', 'SIGNING', 'SIGNED', 'PROCESSING_ERROR', 'ISSUED', 'DECLINED', 'OFFER_DECLINED', 'OFFER_EXPIRED', 'CANCELLED')", name='ck_app_status'),
    sa.CheckConstraint('amount IS NULL OR amount > 0', name='ck_app_amount'),
    sa.CheckConstraint('term_months IS NULL OR term_months BETWEEN 1 AND 120', name='ck_app_term'),
    sa.CheckConstraint('version >= 1', name='ck_app_version'),
    sa.ForeignKeyConstraint(['assignee_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['client_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('application_number')
    )
    op.create_index('ix_app_client', 'applications', ['client_user_id', 'updated_at'], unique=False)
    op.create_index('ix_app_retry', 'applications', ['next_retry_at'], unique=False, postgresql_where=sa.text("status = 'EXTERNAL_SERVICE_UNAVAILABLE'"))
    op.create_index('ix_app_status_due', 'applications', ['status', 'review_due_at'], unique=False)
    op.create_index(op.f('ix_applications_assignee_id'), 'applications', ['assignee_id'], unique=False)
    op.create_index(op.f('ix_applications_company_id'), 'applications', ['company_id'], unique=False)
    op.create_index('uq_app_active_inn_product', 'applications', ['applicant_inn', 'product_code'], unique=True, postgresql_where=sa.text("is_history = false AND applicant_inn IS NOT NULL AND status NOT IN ('DRAFT','ISSUED','DECLINED','OFFER_DECLINED','OFFER_EXPIRED','CANCELLED')"))
    op.create_table('company_memberships',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('representative_role', sa.String(length=32), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'company_id', name='uq_membership')
    )
    op.create_index(op.f('ix_company_memberships_company_id'), 'company_memberships', ['company_id'], unique=False)
    op.create_index(op.f('ix_company_memberships_user_id'), 'company_memberships', ['user_id'], unique=False)
    op.create_table('idempotency_keys',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('key', sa.String(length=128), nullable=False),
    sa.Column('scope', sa.String(length=128), nullable=False),
    sa.Column('request_hash', sa.String(length=64), nullable=False),
    sa.Column('response_status', sa.Integer(), nullable=True),
    sa.Column('response_body', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'key', name='uq_idempotency_user_key')
    )
    op.create_table('refresh_tokens',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('family_id', sa.UUID(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_index(op.f('ix_refresh_tokens_family_id'), 'refresh_tokens', ['family_id'], unique=False)
    op.create_index(op.f('ix_refresh_tokens_user_id'), 'refresh_tokens', ['user_id'], unique=False)
    op.create_table('application_field_changes',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('application_id', sa.UUID(), nullable=False),
    sa.Column('field_name', sa.String(length=64), nullable=False),
    sa.Column('old_value', sa.Text(), nullable=True),
    sa.Column('new_value', sa.Text(), nullable=True),
    sa.Column('info_request_id', sa.UUID(), nullable=True),
    sa.Column('changed_by', sa.UUID(), nullable=False),
    sa.Column('changed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ),
    sa.ForeignKeyConstraint(['changed_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_application_field_changes_application_id'), 'application_field_changes', ['application_id'], unique=False)
    op.create_table('comments',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('application_id', sa.UUID(), nullable=False),
    sa.Column('author_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('INTERNAL','DECISION','RELEASE','RETURN')", name='ck_comment_kind'),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ),
    sa.ForeignKeyConstraint(['author_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_comments_application_id'), 'comments', ['application_id'], unique=False)
    op.create_table('consents',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('application_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('consent_type', sa.String(length=32), nullable=False),
    sa.Column('subject_inn', sa.String(length=12), nullable=True),
    sa.Column('text_version', sa.String(length=64), nullable=False),
    sa.Column('text_sha256', sa.String(length=64), nullable=False),
    sa.Column('granted_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ip_address', sa.String(length=64), nullable=True),
    sa.Column('user_agent', sa.String(length=512), nullable=True),
    sa.CheckConstraint("consent_type IN ('CONSENT_PERSONAL_DATA', 'CONSENT_CREDIT_BUREAU', 'AUTHORITY_CONFIRMATION')", name='ck_consent_type'),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_consents_application_id'), 'consents', ['application_id'], unique=False)
    op.create_table('documents',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('application_id', sa.UUID(), nullable=False),
    sa.Column('document_type', sa.String(length=32), nullable=False),
    sa.Column('file_name', sa.String(length=255), nullable=False),
    sa.Column('mime_type', sa.String(length=64), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('uploaded_by', sa.UUID(), nullable=False),
    sa.Column('uploaded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('info_request_item_id', sa.UUID(), nullable=True),
    sa.Column('storage_key', sa.String(length=64), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("document_type IN ('COLLATERAL_DOCUMENTS', 'SUPPLIER_QUOTE', 'CONTRACT_COPY', 'BANK_STATEMENT', 'COLLATERAL_VALUATION', 'EXPLANATION_LETTER', 'OTHER')", name='ck_doc_type'),
    sa.CheckConstraint("mime_type IN ('application/pdf','image/jpeg','image/png')", name='ck_doc_mime'),
    sa.CheckConstraint('size_bytes > 0 AND size_bytes <= 10485760', name='ck_doc_size'),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_documents_application_id'), 'documents', ['application_id'], unique=False)
    op.create_table('events',
    sa.Column('event_id', sa.UUID(), nullable=False),
    sa.Column('seq', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('event_type', sa.String(length=48), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('application_id', sa.UUID(), nullable=True),
    sa.Column('actor_type', sa.String(length=16), nullable=False),
    sa.Column('actor_id', sa.UUID(), nullable=True),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('application_version', sa.Integer(), nullable=True),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("actor_type IN ('CLIENT', 'UNDERWRITER', 'RISK_MANAGER', 'SYSTEM', 'TIMER')", name='ck_event_actor'),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ),
    sa.PrimaryKeyConstraint('event_id'),
    sa.UniqueConstraint('seq')
    )
    op.create_index('ix_events_app_time', 'events', ['application_id', 'occurred_at'], unique=False)
    op.create_index('ix_events_type_time', 'events', ['event_type', 'occurred_at'], unique=False)
    op.create_index('ix_events_unpublished', 'events', ['occurred_at'], unique=False, postgresql_where=sa.text('published_at IS NULL'))
    op.create_table('jobs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('application_id', sa.UUID(), nullable=False),
    sa.Column('expected_status', sa.String(length=32), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('run_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('max_attempts', sa.Integer(), nullable=False),
    sa.Column('locked_by', sa.String(length=128), nullable=True),
    sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('idempotency_key', sa.String(length=128), nullable=True),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("kind IN ('COMPLETENESS_CHECK', 'ENRICH', 'SCORE', 'DECIDE', 'PREPARE_DOCUMENTS', 'ISSUE_LOAN')", name='ck_job_kind'),
    sa.CheckConstraint("status IN ('QUEUED','RUNNING','DONE','FAILED','CANCELLED')", name='ck_job_status'),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('idempotency_key')
    )
    op.create_index(op.f('ix_jobs_application_id'), 'jobs', ['application_id'], unique=False)
    op.create_index('ix_jobs_ready', 'jobs', ['run_at'], unique=False, postgresql_where=sa.text("status = 'QUEUED'"))
    op.create_index('ix_jobs_running', 'jobs', ['locked_at'], unique=False, postgresql_where=sa.text("status = 'RUNNING'"))
    op.create_table('loans',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('application_id', sa.UUID(), nullable=False),
    sa.Column('contract_number', sa.String(length=64), nullable=False),
    sa.Column('account_number_masked', sa.String(length=32), nullable=False),
    sa.Column('product_code', sa.String(length=32), nullable=False),
    sa.Column('operation_type', sa.String(length=32), nullable=False),
    sa.Column('amount', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('rate_percent', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('term_months', sa.Integer(), nullable=False),
    sa.Column('monthly_payment', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('issued_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('first_payment_date', sa.Date(), nullable=False),
    sa.Column('abs_operation_id', sa.String(length=64), nullable=False),
    sa.CheckConstraint("operation_type IN ('DISBURSEMENT','CREDIT_LINE_LIMIT')", name='ck_loan_operation'),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('abs_operation_id'),
    sa.UniqueConstraint('application_id')
    )
    op.create_table('notifications',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('application_id', sa.UUID(), nullable=True),
    sa.Column('code', sa.String(length=48), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_notifications_user', 'notifications', ['user_id', 'created_at'], unique=False)
    op.create_table('scoring_results',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('application_id', sa.UUID(), nullable=False),
    sa.Column('score', sa.Integer(), nullable=False),
    sa.Column('grade', sa.String(length=1), nullable=False),
    sa.Column('pd', sa.Numeric(precision=8, scale=4), nullable=False),
    sa.Column('features', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('factor_contributions', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('scoring_input', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('scorecard_version', sa.String(length=64), nullable=False),
    sa.Column('scorecard_sha256', sa.String(length=64), nullable=False),
    sa.Column('as_of_date', sa.Date(), nullable=False),
    sa.Column('calculated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_scoring_results_application_id'), 'scoring_results', ['application_id'], unique=False)
    op.create_table('source_snapshots',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('application_id', sa.UUID(), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('stage', sa.String(length=16), nullable=False),
    sa.Column('inn', sa.String(length=12), nullable=False),
    sa.Column('attempt', sa.Integer(), nullable=False),
    sa.Column('outcome', sa.String(length=16), nullable=False),
    sa.Column('error_code', sa.String(length=32), nullable=True),
    sa.Column('http_status', sa.Integer(), nullable=True),
    sa.Column('external_request_id', sa.String(length=64), nullable=True),
    sa.Column('requested_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.Column('response', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('valid_until', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("outcome IN ('SUCCESS','NO_DATA','FAILED')", name='ck_snapshot_outcome'),
    sa.CheckConstraint("source IN ('REGISTRY', 'FNS', 'FINANCIAL_STATEMENTS', 'CREDIT_BUREAU', 'BANK_TURNOVER')", name='ck_snapshot_source'),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_snapshot_lookup', 'source_snapshots', ['application_id', 'source', 'requested_at'], unique=False)
    op.create_table('status_history',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('application_id', sa.UUID(), nullable=False),
    sa.Column('from_status', sa.String(length=32), nullable=True),
    sa.Column('to_status', sa.String(length=32), nullable=False),
    sa.Column('transition_id', sa.String(length=8), nullable=False),
    sa.Column('trigger', sa.String(length=32), nullable=False),
    sa.Column('actor_type', sa.String(length=16), nullable=False),
    sa.Column('actor_id', sa.UUID(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_status_history_application_id'), 'status_history', ['application_id'], unique=False)
    op.create_table('decisions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('application_id', sa.UUID(), nullable=False),
    sa.Column('scoring_result_id', sa.UUID(), nullable=True),
    sa.Column('outcome', sa.String(length=32), nullable=False),
    sa.Column('mode', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('reason_codes', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('reason_details', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('rules_path', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('values', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('recommendation', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('proposed_options', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('override', sa.Boolean(), nullable=False),
    sa.Column('four_eyes_trigger', sa.String(length=32), nullable=True),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.Column('proposed_by', sa.UUID(), nullable=True),
    sa.Column('decided_by', sa.UUID(), nullable=True),
    sa.Column('confirmed_by', sa.UUID(), nullable=True),
    sa.Column('scorecard_version', sa.String(length=64), nullable=True),
    sa.Column('policy_version', sa.String(length=64), nullable=False),
    sa.Column('policy_sha256', sa.String(length=64), nullable=True),
    sa.Column('grade', sa.String(length=1), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("mode IN ('AUTO','MANUAL')", name='ck_decision_mode'),
    sa.CheckConstraint("outcome IN ('APPROVED', 'COUNTER_OFFER', 'NEEDS_INFO', 'MANUAL_REVIEW', 'DECLINED')", name='ck_decision_outcome'),
    sa.CheckConstraint("status IN ('PROPOSED','FINAL','REJECTED')", name='ck_decision_status'),
    sa.CheckConstraint('confirmed_by IS NULL OR proposed_by IS NULL OR confirmed_by <> proposed_by', name='ck_decision_four_eyes'),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ),
    sa.ForeignKeyConstraint(['confirmed_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['decided_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['proposed_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['scoring_result_id'], ['scoring_results.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_decisions_application_id'), 'decisions', ['application_id'], unique=False)
    op.create_table('info_requests',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('application_id', sa.UUID(), nullable=False),
    sa.Column('decision_id', sa.UUID(), nullable=True),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('cycle_number', sa.Integer(), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('due_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('answered_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("source IN ('COMPLETENESS_CHECK', 'POLICY', 'UNDERWRITER')", name='ck_ir_source'),
    sa.CheckConstraint("status IN ('OPEN','ANSWERED','EXPIRED','CANCELLED')", name='ck_ir_status'),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['decision_id'], ['decisions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_info_requests_application_id'), 'info_requests', ['application_id'], unique=False)
    op.create_table('offers',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('application_id', sa.UUID(), nullable=False),
    sa.Column('decision_id', sa.UUID(), nullable=False),
    sa.Column('outcome', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('selected_option_id', sa.UUID(), nullable=True),
    sa.Column('decline_reason_code', sa.String(length=32), nullable=True),
    sa.Column('expiring_notified', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('ACTIVE','ACCEPTED','DECLINED','EXPIRED','CANCELLED')", name='ck_offer_status'),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ),
    sa.ForeignKeyConstraint(['decision_id'], ['decisions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_offers_application_id'), 'offers', ['application_id'], unique=False)
    op.create_table('info_request_items',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('info_request_id', sa.UUID(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('reason_code', sa.String(length=64), nullable=False),
    sa.Column('answer_type', sa.String(length=16), nullable=False),
    sa.Column('field_name', sa.String(length=64), nullable=True),
    sa.Column('document_type', sa.String(length=32), nullable=True),
    sa.Column('client_text', sa.Text(), nullable=False),
    sa.Column('employee_text', sa.Text(), nullable=True),
    sa.Column('required', sa.Boolean(), nullable=False),
    sa.Column('answer_text', sa.Text(), nullable=True),
    sa.Column('answer_value', sa.String(length=255), nullable=True),
    sa.Column('document_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.CheckConstraint("answer_type IN ('DOCUMENT', 'FIELD', 'TEXT')", name='ck_iri_answer_type'),
    sa.ForeignKeyConstraint(['info_request_id'], ['info_requests.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_info_request_items_info_request_id'), 'info_request_items', ['info_request_id'], unique=False)
    op.create_table('offer_options',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('offer_id', sa.UUID(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('option_type', sa.String(length=32), nullable=False),
    sa.Column('product_code', sa.String(length=32), nullable=False),
    sa.Column('amount', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('term_months', sa.Integer(), nullable=False),
    sa.Column('rate_percent', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('monthly_payment', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('total_payment', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('overpayment', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('requires_owner_guarantee', sa.Boolean(), nullable=False),
    sa.Column('requires_collateral', sa.Boolean(), nullable=False),
    sa.Column('tranche_max_term_months', sa.Integer(), nullable=True),
    sa.Column('recommended', sa.Boolean(), nullable=False),
    sa.CheckConstraint("option_type IN ('REQUESTED','AMOUNT_REDUCED','TERM_EXTENDED','PRODUCT_CHANGED','UNDERWRITER_TERMS')", name='ck_option_type'),
    sa.CheckConstraint('amount > 0 AND monthly_payment > 0', name='ck_option_money'),
    sa.ForeignKeyConstraint(['offer_id'], ['offers.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_offer_options_offer_id'), 'offer_options', ['offer_id'], unique=False)
    op.create_table('document_packages',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('application_id', sa.UUID(), nullable=False),
    sa.Column('offer_option_id', sa.UUID(), nullable=False),
    sa.Column('external_package_id', sa.String(length=64), nullable=False),
    sa.Column('edo_operation_id', sa.String(length=64), nullable=False),
    sa.Column('contract_number', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ),
    sa.ForeignKeyConstraint(['offer_option_id'], ['offer_options.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_document_packages_application_id'), 'document_packages', ['application_id'], unique=False)
    op.create_table('generated_documents',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('package_id', sa.UUID(), nullable=False),
    sa.Column('document_type', sa.String(length=32), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('content_type', sa.String(length=64), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['package_id'], ['document_packages.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_generated_documents_package_id'), 'generated_documents', ['package_id'], unique=False)
    op.create_table('signing_codes',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('application_id', sa.UUID(), nullable=False),
    sa.Column('package_id', sa.UUID(), nullable=False),
    sa.Column('code_hash', sa.String(length=128), nullable=False),
    sa.Column('documents_sha256', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('issued_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('notification_id', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ),
    sa.ForeignKeyConstraint(['package_id'], ['document_packages.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_signing_codes_application_id'), 'signing_codes', ['application_id'], unique=False)
    op.create_table('signatures',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('application_id', sa.UUID(), nullable=False),
    sa.Column('signing_code_id', sa.UUID(), nullable=False),
    sa.Column('package_id', sa.UUID(), nullable=False),
    sa.Column('external_signature_id', sa.String(length=64), nullable=True),
    sa.Column('documents_sha256', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('signed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ip_address', sa.String(length=64), nullable=True),
    sa.Column('user_agent', sa.String(length=512), nullable=True),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ),
    sa.ForeignKeyConstraint(['package_id'], ['document_packages.id'], ),
    sa.ForeignKeyConstraint(['signing_code_id'], ['signing_codes.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('application_id')
    )


    op.execute("CREATE SEQUENCE application_number_seq START 1")
    op.execute(
        """
        CREATE FUNCTION forbid_change() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'table % is append-only', TG_TABLE_NAME;
        END $$;
        """
    )
    op.execute(
        """
        CREATE FUNCTION events_only_publish() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF (to_jsonb(NEW) - 'published_at') IS DISTINCT FROM (to_jsonb(OLD) - 'published_at') THEN
                RAISE EXCEPTION 'events are immutable';
            END IF;
            RETURN NEW;
        END $$;
        """
    )
    op.execute("CREATE TRIGGER events_no_delete BEFORE DELETE ON events FOR EACH ROW EXECUTE FUNCTION forbid_change()")
    op.execute("CREATE TRIGGER events_publish_only BEFORE UPDATE ON events FOR EACH ROW EXECUTE FUNCTION events_only_publish()")
    for table in ("audit_log", "status_history"):
        op.execute(f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION forbid_change()")

def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS events_no_delete ON events")
    op.execute("DROP TRIGGER IF EXISTS events_publish_only ON events")
    op.execute("DROP TRIGGER IF EXISTS audit_log_append_only ON audit_log")
    op.execute("DROP TRIGGER IF EXISTS status_history_append_only ON status_history")
    op.execute("DROP FUNCTION IF EXISTS events_only_publish()")
    op.execute("DROP FUNCTION IF EXISTS forbid_change()")
    op.execute("DROP SEQUENCE IF EXISTS application_number_seq")
    op.drop_table('signatures')
    op.drop_index(op.f('ix_signing_codes_application_id'), table_name='signing_codes')
    op.drop_table('signing_codes')
    op.drop_index(op.f('ix_generated_documents_package_id'), table_name='generated_documents')
    op.drop_table('generated_documents')
    op.drop_index(op.f('ix_document_packages_application_id'), table_name='document_packages')
    op.drop_table('document_packages')
    op.drop_index(op.f('ix_offer_options_offer_id'), table_name='offer_options')
    op.drop_table('offer_options')
    op.drop_index(op.f('ix_info_request_items_info_request_id'), table_name='info_request_items')
    op.drop_table('info_request_items')
    op.drop_index(op.f('ix_offers_application_id'), table_name='offers')
    op.drop_table('offers')
    op.drop_index(op.f('ix_info_requests_application_id'), table_name='info_requests')
    op.drop_table('info_requests')
    op.drop_index(op.f('ix_decisions_application_id'), table_name='decisions')
    op.drop_table('decisions')
    op.drop_index(op.f('ix_status_history_application_id'), table_name='status_history')
    op.drop_table('status_history')
    op.drop_index('ix_snapshot_lookup', table_name='source_snapshots')
    op.drop_table('source_snapshots')
    op.drop_index(op.f('ix_scoring_results_application_id'), table_name='scoring_results')
    op.drop_table('scoring_results')
    op.drop_index('ix_notifications_user', table_name='notifications')
    op.drop_table('notifications')
    op.drop_table('loans')
    op.drop_index('ix_jobs_running', table_name='jobs', postgresql_where=sa.text("status = 'RUNNING'"))
    op.drop_index('ix_jobs_ready', table_name='jobs', postgresql_where=sa.text("status = 'QUEUED'"))
    op.drop_index(op.f('ix_jobs_application_id'), table_name='jobs')
    op.drop_table('jobs')
    op.drop_index('ix_events_unpublished', table_name='events', postgresql_where=sa.text('published_at IS NULL'))
    op.drop_index('ix_events_type_time', table_name='events')
    op.drop_index('ix_events_app_time', table_name='events')
    op.drop_table('events')
    op.drop_index(op.f('ix_documents_application_id'), table_name='documents')
    op.drop_table('documents')
    op.drop_index(op.f('ix_consents_application_id'), table_name='consents')
    op.drop_table('consents')
    op.drop_index(op.f('ix_comments_application_id'), table_name='comments')
    op.drop_table('comments')
    op.drop_index(op.f('ix_application_field_changes_application_id'), table_name='application_field_changes')
    op.drop_table('application_field_changes')
    op.drop_index(op.f('ix_refresh_tokens_user_id'), table_name='refresh_tokens')
    op.drop_index(op.f('ix_refresh_tokens_family_id'), table_name='refresh_tokens')
    op.drop_table('refresh_tokens')
    op.drop_table('idempotency_keys')
    op.drop_index(op.f('ix_company_memberships_user_id'), table_name='company_memberships')
    op.drop_index(op.f('ix_company_memberships_company_id'), table_name='company_memberships')
    op.drop_table('company_memberships')
    op.drop_index('uq_app_active_inn_product', table_name='applications', postgresql_where=sa.text("is_history = false AND applicant_inn IS NOT NULL AND status NOT IN ('DRAFT','ISSUED','DECLINED','OFFER_DECLINED','OFFER_EXPIRED','CANCELLED')"))
    op.drop_index(op.f('ix_applications_company_id'), table_name='applications')
    op.drop_index(op.f('ix_applications_assignee_id'), table_name='applications')
    op.drop_index('ix_app_status_due', table_name='applications')
    op.drop_index('ix_app_retry', table_name='applications', postgresql_where=sa.text("status = 'EXTERNAL_SERVICE_UNAVAILABLE'"))
    op.drop_index('ix_app_client', table_name='applications')
    op.drop_table('applications')
    op.drop_table('users')
    op.drop_table('system_secrets')
    op.drop_index('ix_login_attempts_login', table_name='login_attempts')
    op.drop_index('ix_login_attempts_ip', table_name='login_attempts')
    op.drop_table('login_attempts')
    op.drop_table('document_contents')
    op.drop_table('config_versions')
    op.drop_table('companies')
    op.drop_index('ix_audit_time', table_name='audit_log')
    op.drop_index('ix_audit_app', table_name='audit_log')
    op.drop_table('audit_log')
