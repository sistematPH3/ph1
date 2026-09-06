"""decision_por_producto

Revision ID: a7b8c9d0e1f2
Revises: c5d9e2f1a7b4
Create Date: 2026-09-05

Decisión de la merma POR PRODUCTO: cada línea de waste_details lleva su propio
estado (PENDIENTE/APROBADO/RECHAZADO), quién la resolvió, cuándo y el motivo
(si fue rechazada). La cabecera sigue reflejando la suma final.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a7b8c9d0e1f2'
down_revision = 'c5d9e2f1a7b4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'waste_details',
        sa.Column('status', sa.String(20), nullable=False, server_default='PENDIENTE'),
    )
    op.add_column(
        'waste_details',
        sa.Column('resolved_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
    )
    op.add_column(
        'waste_details',
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
    )
    op.add_column(
        'waste_details',
        sa.Column('resolution_reason', sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_column('waste_details', 'resolution_reason')
    op.drop_column('waste_details', 'resolved_at')
    op.drop_column('waste_details', 'resolved_by_id')
    op.drop_column('waste_details', 'status')