"""Agrega columna request_id a la tabla waste.

Requisito: cualquier entorno donde la tabla waste no tenga esta columna.
Mezcla de creación manual (create_all) con modelos que incluyen request_id
provocó un esquema desincronizado.

Revision ID: add_request_id_waste
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_request_id_waste'
down_revision = 'f3b4c5d6e7f8'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE waste ADD COLUMN IF NOT EXISTS request_id VARCHAR(100)")


def downgrade():
    op.execute("ALTER TABLE waste DROP COLUMN IF EXISTS request_id")
