"""ajuste en el auditlogs se añadio el campo location_id

Revision ID: 8e8b77ad821b
Revises: 037aec724840
Create Date: 2026-08-02 12:43:27.452883

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '8e8b77ad821b'
down_revision = '037aec724840'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('audit_logs', sa.Column('location_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_audit_logs_location_id', 'audit_logs', 'locations', ['location_id'], ['id'])

def downgrade():
    op.drop_constraint('fk_audit_logs_location_id', 'audit_logs', type_='foreignkey')
    op.drop_column('audit_logs', 'location_id')