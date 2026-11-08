"""fotos_multiple_por_producto

Revision ID: e5f6a7b8c9d0
Revises: d3e4f5a6b7c8
Create Date: 2026-09-05

Varias fotos POR PRODUCTO: tabla hija waste_detail_photos (1 N).
Cada fila = una foto (URL de ImgBB) de UNA línea de waste_details.

Se mantiene waste_details.evidence_url como "foto principal" (posición 1)
para no romper aprobación/auditoría/edición; backfill copia las evidencias
únicas existentes a la tabla nueva.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = 'e5f6a7b8c9d0'
down_revision = 'd3e4f5a6b7c8'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'waste_detail_photos',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('waste_detail_id', sa.Integer(), nullable=False),
        sa.Column('photo_url', sa.Text(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False, server_default=sa.text('1')),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['waste_detail_id'], ['waste_details.id'], ondelete='CASCADE'),
    )
    op.create_index('idx_waste_detail_photos_waste_detail_id', 'waste_detail_photos', ['waste_detail_id'])

    # Backfill: las evidencias únicas ya existentes pasan a ser la "foto principal"
    op.execute(text("""
        INSERT INTO waste_detail_photos (waste_detail_id, photo_url, position)
        SELECT id, evidence_url, 1
        FROM waste_details
        WHERE evidence_url IS NOT NULL
    """))


def downgrade():
    op.drop_index('idx_waste_detail_photos_waste_detail_id', table_name='waste_detail_photos')
    op.drop_table('waste_detail_photos')