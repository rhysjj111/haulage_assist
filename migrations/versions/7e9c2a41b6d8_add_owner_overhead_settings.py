"""Add separate owner overhead settings and weekly snapshots.

Revision ID: 7e9c2a41b6d8
Revises: 859d6ebe2110

No historical amounts are inferred and no payroll or expense rows are changed.
"""

from alembic import op
import sqlalchemy as sa

revision = "7e9c2a41b6d8"
down_revision = "859d6ebe2110"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "owner_overhead_setting",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("effective_week_start", sa.Date(), nullable=False),
        sa.Column("truck_count", sa.Integer(), nullable=False),
        sa.Column("allowance_per_truck", sa.Integer(), nullable=False),
        sa.CheckConstraint("truck_count >= 0", name="ck_owner_overhead_truck_count"),
        sa.CheckConstraint("allowance_per_truck >= 0", name="ck_owner_overhead_allowance"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("effective_week_start", name="uq_owner_overhead_effective_week"),
    )
    op.create_table(
        "owner_weekly_overhead",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("truck_count", sa.Integer(), nullable=False),
        sa.Column("allowance_per_truck", sa.Integer(), nullable=False),
        sa.Column("source_setting_id", sa.Integer(), nullable=False),
        sa.CheckConstraint("truck_count >= 0", name="ck_owner_weekly_truck_count"),
        sa.CheckConstraint("allowance_per_truck >= 0", name="ck_owner_weekly_allowance"),
        sa.ForeignKeyConstraint(["source_setting_id"], ["owner_overhead_setting.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("week_start", name="uq_owner_weekly_overhead_week"),
    )
    op.create_index("ix_owner_weekly_overhead_source_setting_id", "owner_weekly_overhead", ["source_setting_id"])


def downgrade():
    op.drop_index("ix_owner_weekly_overhead_source_setting_id", table_name="owner_weekly_overhead")
    op.drop_table("owner_weekly_overhead")
    op.drop_table("owner_overhead_setting")
