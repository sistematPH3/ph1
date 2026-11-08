"""foto_por_producto

Revision ID: d3e4f5a6b7c8
Revises: a7b8c9d0e1f2
Create Date: 2026-09-05

Evidencia fotográfica POR PRODUCTO: cada línea de waste_details puede llevar su
propia foto (evidence_url). La foto general de la cabecera (Waste.evidence_url)
se conserva para los registros anteriores.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd3e4f5a6b7c8'
down_revision = 'a7b8c9d0e1f2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'waste_details',
        sa.Column('evidence_url', sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_column('waste_details', 'evidence_url')