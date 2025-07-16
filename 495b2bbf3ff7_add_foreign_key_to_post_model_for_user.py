"""Add foreign key to Post model for User

Revision ID: 495b2bbf3ff7
Revises: d7b1890394f2
Create Date: 2025-06-02 20:47:43.755507

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = '495b2bbf3ff7'
down_revision = 'd7b1890394f2'
branch_labels = None
depends_on = None


def upgrade():
        # Step 1: Add the day_id column as nullable
    op.add_column('fuel', sa.Column('day_id', sa.Integer(), nullable=True))
    
    # Step 2: Populate existing fuel entries with matching day_id
    connection = op.get_bind()
    
    update_query = text("""
        UPDATE fuel 
        SET day_id = day.id 
        FROM day 
        WHERE fuel.date = day.date 
        AND fuel.truck_id = day.truck_id
        AND fuel.day_id IS NULL
    """)
    
    result = connection.execute(update_query)
    print(f"Updated {result.rowcount} fuel entries with day_id")
    
    # Step 3: Add the foreign key constraint
    op.create_foreign_key(
        'fk_fuel_day_id',  # constraint name
        'fuel',            # source table
        'day',             # target table
        ['day_id'],        # source columns
        ['id'],            # target columns
        ondelete='SET NULL'
    )
    
    # Step 4: Add index for performance
    op.create_index('ix_fuel_day_id', 'fuel', ['day_id'])


def downgrade():
    # Remove the foreign key constraint, index, and column
    op.drop_index('ix_fuel_day_id', table_name='fuel')
    op.drop_constraint('fk_fuel_day_id', 'fuel', type_='foreignkey')
    op.drop_column('fuel', 'day_id')
