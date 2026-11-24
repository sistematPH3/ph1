"""Impide registrar insumos duplicados por nombre.

Antes de crear la restricción se verifica la base de datos: si ya existen
insumos con el mismo nombre la migración se detiene y lista los duplicados
para que se corrijan manualmente (renombrar o fusionar), en lugar de borrar
o renombrar datos automáticamente.

Revision ID: a4c9f2e61b7d
Revises: e7a1b3c95d02
"""

from alembic import op
import sqlalchemy as sa

revision = 'a4c9f2e61b7d'
down_revision = 'e7a1b3c95d02'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    duplicados = bind.execute(sa.text(
        """
        SELECT name, COUNT(*) AS total
        FROM products
        GROUP BY name
        HAVING COUNT(*) > 1
        ORDER BY name
        """
    )).fetchall()

    if duplicados:
        detalle = ', '.join(
            f"'{fila.name}' ({fila.total} registros)" for fila in duplicados
        )
        raise RuntimeError(
            'No se puede aplicar la unicidad de nombres de insumos: existen '
            f'duplicados en la tabla products: {detalle}. '
            'Renombra o fusiona esos registros y vuelve a ejecutar la migración.'
        )

    op.create_unique_constraint('uq_products_name', 'products', ['name'])


def downgrade():
    op.drop_constraint('uq_products_name', 'products', type_='unique')
