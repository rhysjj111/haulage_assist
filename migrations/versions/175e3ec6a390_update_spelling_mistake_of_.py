"""Update spelling mistake of ExpenseOccurrence model name. Change attribute date_start to start_date and the same for date_end.

Revision ID: 175e3ec6a390
Revises: 8b522e11b6a4
Create Date: 2024-10-25 06:16:26.910188

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '175e3ec6a390'
down_revision = '8b522e11b6a4'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('expense_occurrence',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('expense_id', sa.Integer(), nullable=False),
    sa.Column('timestamp', sa.DateTime(), nullable=True),
    sa.Column('start_date', sa.Date(), nullable=False),
    sa.Column('end_date', sa.Date(), nullable=True),
    sa.Column('cost', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['expense_id'], ['expense.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('expense_occurrence', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_expense_occurrence_end_date'), ['end_date'], unique=False)
        batch_op.create_index(batch_op.f('ix_expense_occurrence_expense_id'), ['expense_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_expense_occurrence_start_date'), ['start_date'], unique=False)

    with op.batch_alter_table('expense_occurance', schema=None) as batch_op:
        batch_op.drop_index('ix_expense_occurance_date_end')
        batch_op.drop_index('ix_expense_occurance_date_start')
        batch_op.drop_index('ix_expense_occurance_expense_id')

    op.drop_table('expense_occurance')
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('expense_occurance',
    sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
    sa.Column('expense_id', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('timestamp', postgresql.TIMESTAMP(), autoincrement=False, nullable=True),
    sa.Column('date_start', sa.DATE(), autoincrement=False, nullable=False),
    sa.Column('date_end', sa.DATE(), autoincrement=False, nullable=True),
    sa.Column('cost', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['expense_id'], ['expense.id'], name='expense_occurance_expense_id_fkey'),
    sa.PrimaryKeyConstraint('id', name='expense_occurance_pkey')
    )
    with op.batch_alter_table('expense_occurance', schema=None) as batch_op:
        batch_op.create_index('ix_expense_occurance_expense_id', ['expense_id'], unique=False)
        batch_op.create_index('ix_expense_occurance_date_start', ['date_start'], unique=False)
        batch_op.create_index('ix_expense_occurance_date_end', ['date_end'], unique=False)

    with op.batch_alter_table('expense_occurrence', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_expense_occurrence_start_date'))
        batch_op.drop_index(batch_op.f('ix_expense_occurrence_expense_id'))
        batch_op.drop_index(batch_op.f('ix_expense_occurrence_end_date'))

    op.drop_table('expense_occurrence')
    # ### end Alembic commands ###
