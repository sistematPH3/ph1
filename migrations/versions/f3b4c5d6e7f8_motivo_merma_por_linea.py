"""motivo de merma por línea (waste_details.waste_type_id)

Revision ID: f3b4c5d6e7f8
Revises: e2f0a1b2c3d4
Create Date: 2026-09-06

Permite que cada producto dentro de un ticket de merma lleve SU PROPIO tipo
de merma (motivo): VENCIDO para un lote y DAÑADO para otro en el mismo ticket.
NULL (legacy) se resuelve al tipo de la cabecera Waste.waste_type_id.
"""
from alembic import op
import sqlalchemy as sa

revision = 'f3b4c5d6e7f8'
down_revision = 'e2f0a1b2c3d4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('waste_details', sa.Column('waste_type_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_waste_details_waste_type_id', 'waste_details', 'waste_types',
        ['waste_type_id'], ['id'],
    )


def downgrade():
    op.drop_constraint('fk_waste_details_waste_type_id', 'waste_details', type_='foreignkey')
    op.drop_column('waste_details', 'waste_type_id')