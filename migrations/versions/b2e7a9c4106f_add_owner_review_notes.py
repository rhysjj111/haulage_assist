"""Add independent owner verification notes and whole-week reviews.

Revision ID: b2e7a9c4106f
Revises: 7e9c2a41b6d8

Append-only records have no foreign keys to deletable source rows/anomalies.
Existing entries and overhead snapshots are untouched.
"""

from alembic import op
import sqlalchemy as sa

revision = "b2e7a9c4106f"
down_revision = "7e9c2a41b6d8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "owner_issue_verification",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("scope_key", sa.String(255), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("decision IN ('verified', 'confirmed_zero', 'note')", name="ck_owner_issue_decision"),
        sa.CheckConstraint("length(trim(note)) > 0", name="ck_owner_issue_note_required"),
        sa.CheckConstraint("length(source_fingerprint) = 64", name="ck_owner_issue_fingerprint_length"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_owner_issue_verification_week_scope", "owner_issue_verification", ["week_start", "scope_key"])
    op.create_table(
        "owner_week_review",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("length(source_fingerprint) = 64", name="ck_owner_week_review_fingerprint_length"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_owner_week_review_week_start", "owner_week_review", ["week_start"])


def downgrade():
    op.drop_index("ix_owner_week_review_week_start", table_name="owner_week_review")
    op.drop_table("owner_week_review")
    op.drop_index("ix_owner_issue_verification_week_scope", table_name="owner_issue_verification")
    op.drop_table("owner_issue_verification")
