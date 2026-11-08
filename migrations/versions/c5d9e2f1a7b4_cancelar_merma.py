"""cancelar_merma

Revision ID: c5d9e2f1a7b4
Revises: b4f1a2c9d8e7
Create Date: 2026-09-04

El autor retira una merma PENDIENTE antes de la respuesta del Administrador.
Guarda quién, cuándo y por qué se canceló (consta en la Auditoría de Inventario).
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c5d9e2f1a7b4'
down_revision = 'b4f1a2c9d8e7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('waste', sa.Column('cancelled_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True))
    op.add_column('waste', sa.Column('cancelled_at', sa.DateTime(), nullable=True))
    op.add_column('waste', sa.Column('cancel_reason', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('waste', 'cancel_reason')
    op.drop_column('waste', 'cancelled_at')
    op.drop_column('waste', 'cancelled_by_id')