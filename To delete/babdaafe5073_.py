"""Added notification and feedback tables

Revision ID: babdaafe5073
Revises: 4527f935ee68
Create Date: 2024-11-18 16:45:41.341139

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'babdaafe5073'
down_revision = '4527f935ee68'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('notification',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('timestamp', sa.DateTime(), nullable=True),
    sa.Column('verification_data', sa.JSON(), nullable=True),
    sa.Column('timeframe', sa.Enum('DAILY', 'WEEKLY', name='timeframeenum'), nullable=True),
    sa.Column('error_type', sa.Enum('MISSING_DATA', 'INCORRECT_DATA', 'SUSPICIOUS_ACTIVITY', name='errortypeenum'), nullable=True),
    sa.Column('primary_fault_area', sa.Enum('DAY_FUEL', 'DAY_MILEAGE', 'DAY_EARNED', 'FUEL', 'PAYSLIP', 'JOB', name='faultareaenum'), nullable=True),
    sa.Column('secondary_fault_area', sa.Enum('DAY_FUEL', 'DAY_MILEAGE', 'DAY_EARNED', 'FUEL', 'PAYSLIP', 'JOB', name='faultareaenum'), nullable=True),
    sa.Column('answer', sa.String(length=200), nullable=False),
    sa.Column('is_read', sa.Boolean(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('verification_feedback',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('timestamp', sa.DateTime(), nullable=True),
    sa.Column('notification_id', sa.Integer(), nullable=True),
    sa.Column('acceptable_structure', sa.Boolean(), nullable=False),
    sa.Column('notification_effective', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['notification_id'], ['notification.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('verification_feedback')
    op.drop_table('notification')
    # ### end Alembic commands ###