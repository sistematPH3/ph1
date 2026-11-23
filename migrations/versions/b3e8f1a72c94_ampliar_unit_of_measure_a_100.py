"""Amplía la unidad de medida de los insumos a 100 caracteres.

Revision ID: b3e8f1a72c94
Revises: 9f3a1c2d4e5b
"""

from alembic import op
import sqlalchemy as sa

revision = 'b3e8f1a72c94'
down_revision = '9f3a1c2d4e5b'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        'products',
        'unit_of_measure',
        existing_type=sa.String(length=20),
        type_=sa.String(length=100),
        existing_nullable=True,
    )


def downgrade():
    op.alter_column(
        'products',
        'unit_of_measure',
        existing_type=sa.String(length=100),
        type_=sa.String(length=20),
        existing_nullable=True,
    )
