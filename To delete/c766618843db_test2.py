"""test2

Revision ID: c766618843db
Revises: 4527f935ee68
Create Date: 2024-12-14 08:52:06.857953

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'c766618843db'
down_revision = '4527f935ee68'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('day', schema=None) as batch_op:
        batch_op.alter_column('timestamp',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False)
        batch_op.alter_column('fuel',
               existing_type=sa.BOOLEAN(),
               nullable=False)
        batch_op.drop_constraint('day_driver_id_fkey', type_='foreignkey')
        batch_op.drop_constraint('day_truck_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key(None, 'truck', ['truck_id'], ['id'], ondelete='RESTRICT')
        batch_op.create_foreign_key(None, 'driver', ['driver_id'], ['id'], ondelete='RESTRICT')

    with op.batch_alter_table('driver', schema=None) as batch_op:
        batch_op.alter_column('timestamp',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False)
        batch_op.create_index(batch_op.f('ix_driver_truck_id'), ['truck_id'], unique=False)

    with op.batch_alter_table('expense', schema=None) as batch_op:
        batch_op.alter_column('timestamp',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False)

    with op.batch_alter_table('expense_occurrence', schema=None) as batch_op:
        batch_op.alter_column('timestamp',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False)

    with op.batch_alter_table('fuel', schema=None) as batch_op:
        batch_op.alter_column('timestamp',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False)

    with op.batch_alter_table('job', schema=None) as batch_op:
        batch_op.alter_column('timestamp',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False)
        batch_op.alter_column('split',
               existing_type=sa.BOOLEAN(),
               nullable=False)

    with op.batch_alter_table('payslip', schema=None) as batch_op:
        batch_op.alter_column('timestamp',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False)

    with op.batch_alter_table('truck', schema=None) as batch_op:
        batch_op.alter_column('timestamp',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False)

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('truck', schema=None) as batch_op:
        batch_op.alter_column('timestamp',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True)

    with op.batch_alter_table('payslip', schema=None) as batch_op:
        batch_op.alter_column('timestamp',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True)

    with op.batch_alter_table('job', schema=None) as batch_op:
        batch_op.alter_column('split',
               existing_type=sa.BOOLEAN(),
               nullable=True)
        batch_op.alter_column('timestamp',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True)

    with op.batch_alter_table('fuel', schema=None) as batch_op:
        batch_op.alter_column('timestamp',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True)

    with op.batch_alter_table('expense_occurrence', schema=None) as batch_op:
        batch_op.alter_column('timestamp',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True)

    with op.batch_alter_table('expense', schema=None) as batch_op:
        batch_op.alter_column('timestamp',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True)

    with op.batch_alter_table('driver', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_driver_truck_id'))
        batch_op.alter_column('timestamp',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True)

    with op.batch_alter_table('day', schema=None) as batch_op:
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.create_foreign_key('day_truck_id_fkey', 'truck', ['truck_id'], ['id'], ondelete='CASCADE')
        batch_op.create_foreign_key('day_driver_id_fkey', 'driver', ['driver_id'], ['id'], ondelete='CASCADE')
        batch_op.alter_column('fuel',
               existing_type=sa.BOOLEAN(),
               nullable=True)
        batch_op.alter_column('timestamp',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True)

    # ### end Alembic commands ###