"""Rellena el stock mínimo histórico antes de exigirlo como obligatorio.

Los insumos creados cuando el campo era opcional quedaron con min_stock NULL.
La aplicación ya no aplica el respaldo silencioso de 20.00, así que se asigna
una única vez el antiguo valor por defecto a esos registros para que compras,
recepciones y alertas sigan operando con un umbral válido.

Revision ID: 9f3a1c2d4e5b
Revises: 7c0cb8c45047
"""

from alembic import op

revision = '9f3a1c2d4e5b'
down_revision = '7c0cb8c45047'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE products SET min_stock = 20.00 WHERE min_stock IS NULL")


def downgrade():
    # No se revierte el relleno: volver a NULL reabriría el fallo de datos.
    pass
