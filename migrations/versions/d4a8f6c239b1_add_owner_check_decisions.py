"""Allow explained dismissals and outstanding fuel-invoice notes.

Revision ID: d4a8f6c239b1
Revises: b2e7a9c4106f

Only the verification decision CHECK changes. Downgrade retains every review
row, note, timestamp and fingerprint: dismissed becomes verified, and an
awaiting-invoice decision becomes a non-resolving note for the older app.
"""

from alembic import op
import sqlalchemy as sa


revision = "d4a8f6c239b1"
down_revision = "b2e7a9c4106f"
branch_labels = None
depends_on = None


def _replace_decision_constraint(expression):
    # PostgreSQL alters the constraint in place; SQLite recreates just this
    # independent review table, preserving its rows and remaining constraints.
    with op.batch_alter_table("owner_issue_verification") as batch:
        batch.drop_constraint("ck_owner_issue_decision", type_="check")
        batch.create_check_constraint("ck_owner_issue_decision", expression)


def upgrade():
    _replace_decision_constraint(
        "decision IN ('verified', 'confirmed_zero', 'note', 'dismissed', 'awaiting_invoice')"
    )


def downgrade():
    op.execute(sa.text("UPDATE owner_issue_verification SET decision = 'verified' WHERE decision = 'dismissed'"))
    op.execute(sa.text("UPDATE owner_issue_verification SET decision = 'note' WHERE decision = 'awaiting_invoice'"))
    _replace_decision_constraint("decision IN ('verified', 'confirmed_zero', 'note')")
