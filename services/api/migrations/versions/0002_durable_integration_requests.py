"""Persist external operation requests and the issued payment schedule."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integration_requests",
        sa.Column("idempotency_key", sa.String(128), primary_key=True),
        sa.Column("application_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("system", sa.String(16), nullable=False),
        sa.Column("request", postgresql.JSONB(), nullable=False),
        sa.Column("response", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_integration_requests_application_id", "integration_requests", ["application_id"])
    op.add_column("loans", sa.Column("payment_schedule", postgresql.JSONB()))


def downgrade() -> None:
    op.drop_column("loans", "payment_schedule")
    op.drop_table("integration_requests")
