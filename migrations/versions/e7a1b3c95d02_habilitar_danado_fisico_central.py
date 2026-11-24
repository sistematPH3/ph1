"""Habilita el tipo de merma DANADO_FISICO en el almacén central.

No hay cambios de esquema: solo se actualiza la bandera applies_central del
registro existente. En bases nuevas el seeder ya lo crea habilitado; esta
migración cubre las bases ya desplegadas y es idempotente por naturaleza.

Revision ID: e7a1b3c95d02
Revises: b3e8f1a72c94
"""

from alembic import op

revision = 'e7a1b3c95d02'
down_revision = 'b3e8f1a72c94'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        UPDATE waste_types
        SET applies_central = TRUE
        WHERE code = 'DANADO_FISICO'
          AND (applies_central = FALSE OR applies_central IS NULL)
        """
    )


def downgrade():
    op.execute(
        """
        UPDATE waste_types
        SET applies_central = FALSE
        WHERE code = 'DANADO_FISICO'
        """
    )
