"""notificaciones_respuesta_movement_id

Revision ID: a3f8c2d9e1b4
Revises: 10cae3436d7c
Create Date: 2026-08-30 19:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a3f8c2d9e1b4'
down_revision = '10cae3436d7c'
branch_labels = None
depends_on = None


def upgrade():
    # Columna que apunta a la respuesta del Administrador (bandeja de
    # respuestas de traslados). Nullable para no romper notificaciones viejas.
    op.add_column('notifications', sa.Column('movement_id', sa.Integer(), nullable=True))
    # Unico por usuario + traslado + tipo: una respuesta se puede abrir en
    # varias sedes, pero para cada usuario existe una sola notificacion.
    op.create_unique_constraint('uq_notif_user_movement_type', 'notifications',
                                ['user_id', 'movement_id', 'type'])


def downgrade():
    op.drop_constraint('uq_notif_user_movement_type', 'notifications')
    op.drop_column('notifications', 'movement_id')