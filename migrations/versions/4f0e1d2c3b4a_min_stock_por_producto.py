"""min_stock_por_producto

Agrega el campo products.min_stock: mínimo de stock configurable al
registrar el insumo (en la unidad del producto). NULL = usar 20.00.

Revision ID: 4f0e1d2c3b4a
Revises: add_request_id_waste
Create Date: 2026-09-10 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '4f0e1d2c3b4a'
down_revision = 'add_request_id_waste'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('products', sa.Column('min_stock', sa.Numeric(precision=10, scale=2), nullable=True))


def downgrade():
    op.drop_column('products', 'min_stock')