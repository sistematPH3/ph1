"""Marca los renglones conformes acreditados durante una recepción mixta.

En un traslado con varios ítems, los renglones sin novedad se acreditan de
inmediato en el inventario de destino. Esta bandera permite que la bandeja de
disputas y la resolución solo procesen las líneas con discrepancia, sin volver
a acreditar las que ya ingresaron.

Revision ID: b7d2e4f8a1c3
Revises: a4c9f2e61b7d
"""

from alembic import op
import sqlalchemy as sa

revision = 'b7d2e4f8a1c3'
down_revision = 'a4c9f2e61b7d'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'movement_details',
        sa.Column('conforming_credited', sa.Boolean(), nullable=False,
                  server_default=sa.text('false')),
    )
    # Los registros históricos quedan en False: las disputas ya pendientes
    # conservan su comportamiento anterior (se resuelven completas).
    op.alter_column('movement_details', 'conforming_credited',
                    server_default=None)


def downgrade():
    op.drop_column('movement_details', 'conforming_credited')
