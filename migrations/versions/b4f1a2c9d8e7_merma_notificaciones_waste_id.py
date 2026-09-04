"""merma_notificaciones_waste_id

Revision ID: b4f1a2c9d8e7
Revises: e77641c0a3be
Create Date: 2026-09-04 10:00:00.000000

Permite enlazar las notificaciones de decisiones de mermas
(MERMA_APROBADA / MERMA_RECHAZADA) con la merma correspondiente, para que
aparezcan en la Bandeja de Respuestas de Administración.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b4f1a2c9d8e7'
down_revision = 'e77641c0a3be'
branch_labels = None
depends_on = None


def upgrade():
    # Columna que apunta a la merma de la decisión (nullable para no romper
    # notificaciones existentes ni el constraint uq_notif_user_movement_type,
    # que usa movement_id NULL y en Postgres permite varias filas).
    op.add_column('notifications', sa.Column('waste_id', sa.Integer(), nullable=True))
    op.create_index('idx_notif_waste_id', 'notifications', ['waste_id'])

    # Backfill: las notificaciones de mermas antiguas guardaban la merma solo
    # en el texto ("Tu merma #13 fue ..."): se extrae el id y se rellena.
    op.execute(
        """
        UPDATE notifications
        SET waste_id = NULLIF(substring(message from '#([0-9]+)'), '')::int
        WHERE type IN ('MERMA_APROBADA', 'MERMA_RECHAZADA')
          AND waste_id IS NULL
        """
    )


def downgrade():
    op.drop_index('idx_notif_waste_id', table_name='notifications')
    op.drop_column('notifications', 'waste_id')