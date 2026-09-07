"""reservar_mermas_pendientes

Revision ID: e2f0a1b2c3d4
Revises: e77641c0a3be
Create Date: 2026-09-06

Reserva de stock para mermas PENDIENTES de aprobación: nueva columna
reserved_quantity en inventory. El stock congelado no se resta de
current_quantity pero deja de estar disponible para cocina, traslados y
ediciones hasta que el Administrador decida la merma.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'e2f0a1b2c3d4'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'inventory',
        sa.Column('reserved_quantity', sa.Numeric(10, 2), nullable=False, server_default='0.00')
    )


def downgrade():
    op.drop_column('inventory', 'reserved_quantity')