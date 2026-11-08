"""modulo_mermas

Revision ID: e77641c0a3be
Revises: a3f8c2d9e1b4
Create Date: 2026-09-01 13:14:32.976681

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'e77641c0a3be'
down_revision = 'a3f8c2d9e1b4'
branch_labels = None
depends_on = None


def upgrade():
    # ------------------------------------------------------------------
    # 1) app_parameters: pizarra de reglas (solo las 2 de TIEMPO).
    #    NOTA: el limite de merma vive en products.waste_limit (no aqui).
    # ------------------------------------------------------------------
    op.create_table(
        'app_parameters',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('key', sa.String(length=50), nullable=False, unique=True),
        sa.Column('value', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
    )
    op.bulk_insert(
        sa.table(
            'app_parameters',
            sa.column('key', sa.String(50)),
            sa.column('value', sa.Text),
            sa.column('description', sa.Text),
        ),
        [
            {'key': 'WASTE_TIME_TOLERANCE', 'value': '1.5',
             'description': 'Factor de margen de la regla de tiempo'},
            {'key': 'WASTE_BASE_PERIOD_DAYS', 'value': '7',
             'description': 'Peri\xf3do base si no hay merma previa'},
        ],
    )

    # ------------------------------------------------------------------
    # 2) waste_details: lineas de merma (Maestro-Detalle, multi-lote).
    #    Sin ON DELETE CASCADE (anti-borrado).
    # ------------------------------------------------------------------
    op.create_table(
        'waste_details',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('waste_id', sa.Integer(), sa.ForeignKey('waste.id'), nullable=False),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=False),
        sa.Column('lot_number', sa.String(length=50), nullable=False),
        sa.Column('expiration_date', sa.Date(), nullable=True),
        sa.Column('quantity', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('unit_cost', sa.Numeric(precision=15, scale=4), nullable=False),
        sa.Column('subtotal_cost', sa.Numeric(precision=15, scale=2), nullable=False),
    )

    # ------------------------------------------------------------------
    # 3) products.waste_limit: limite de merma en la unidad del producto.
    # ------------------------------------------------------------------
    op.add_column('products', sa.Column('waste_limit', sa.Numeric(precision=10, scale=2), nullable=True))

    # ------------------------------------------------------------------
    # 4) waste_types: catalogos de tipos (codigo, gravedad, reglas).
    # ------------------------------------------------------------------
    op.add_column('waste_types', sa.Column('code', sa.String(length=40), nullable=True))
    op.add_column('waste_types', sa.Column('description', sa.Text(), nullable=True))
    op.add_column('waste_types', sa.Column('severity', sa.String(length=15), nullable=False, server_default='MEDIA'))
    op.add_column('waste_types', sa.Column('requires_approval', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('waste_types', sa.Column('applies_central', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('waste_types', sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_unique_constraint('uq_waste_types_code', 'waste_types', ['code'])

    # ------------------------------------------------------------------
    # 5) waste: cabecera (estado, aprobacion, reversion, costos ocultos).
    #    Se ELIMINAN las columnas legacy product_id / quantity (Maestro-
    #    Detalle: el producto ya vive en waste_details). Tabla vacia -> sin
    #    riesgo. Se usa batch_alter_table porque borrar una columna con FK
    #    en Postgres requiere recrear la tabla.
    # ------------------------------------------------------------------
    op.add_column('waste', sa.Column('status', sa.String(length=20), nullable=False, server_default='APROBADO'))
    op.add_column('waste', sa.Column('total_quantity', sa.Numeric(precision=10, scale=2), nullable=False, server_default='0'))
    op.add_column('waste', sa.Column('total_cost', sa.Numeric(precision=15, scale=2), nullable=False, server_default='0'))
    op.add_column('waste', sa.Column('currency', sa.String(length=5), nullable=False, server_default='USD'))
    op.add_column('waste', sa.Column('approved_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True))
    op.add_column('waste', sa.Column('approved_at', sa.DateTime(), nullable=True))
    op.add_column('waste', sa.Column('reverted_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True))
    op.add_column('waste', sa.Column('reverted_at', sa.DateTime(), nullable=True))
    op.add_column('waste', sa.Column('reversal_reason', sa.Text(), nullable=True))

    with op.batch_alter_table('waste', schema=None) as batch_op:
        batch_op.drop_constraint('waste_product_id_fkey', type_='foreignkey')
        batch_op.drop_column('product_id')
        batch_op.drop_column('quantity')

    # ------------------------------------------------------------------
    # 6) Indices de rendimiento.
    # ------------------------------------------------------------------
    op.create_index('idx_waste_location_date', 'waste', ['location_id', sa.text('date DESC')])
    op.create_index('idx_waste_status', 'waste', ['status'])
    op.create_index('idx_waste_details_waste_id', 'waste_details', ['waste_id'])
    op.create_index('idx_waste_details_product_lot', 'waste_details', ['product_id', 'lot_number'])


def downgrade():
    # ------------------------------------------------------------------
    # 6) Indices (en orden inverso).
    # ------------------------------------------------------------------
    op.drop_index('idx_waste_details_product_lot', table_name='waste_details')
    op.drop_index('idx_waste_details_waste_id', table_name='waste_details')
    op.drop_index('idx_waste_status', table_name='waste')
    op.drop_index('idx_waste_location_date', table_name='waste')

    # ------------------------------------------------------------------
    # 5) waste: revertir columnas nuevas.
    # ------------------------------------------------------------------
    op.drop_column('waste', 'reversal_reason')
    op.drop_column('waste', 'reverted_at')
    op.drop_column('waste', 'reverted_by_id')
    op.drop_column('waste', 'approved_at')
    op.drop_column('waste', 'approved_by_id')
    op.drop_column('waste', 'currency')
    op.drop_column('waste', 'total_cost')
    op.drop_column('waste', 'total_quantity')
    op.drop_column('waste', 'status')

    # Recrear las columnas legacy (Maestro un solo producto) que se borraron.
    with op.batch_alter_table('waste', schema=None) as batch_op:
        batch_op.add_column(sa.Column('product_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('quantity', sa.Numeric(precision=10, scale=2), nullable=False, server_default='0'))
        batch_op.create_foreign_key('waste_product_id_fkey', 'products', ['product_id'], ['id'])

    # ------------------------------------------------------------------
    # 4) waste_types.
    # ------------------------------------------------------------------
    op.drop_constraint('uq_waste_types_code', 'waste_types', type_='unique')
    op.drop_column('waste_types', 'is_active')
    op.drop_column('waste_types', 'applies_central')
    op.drop_column('waste_types', 'requires_approval')
    op.drop_column('waste_types', 'severity')
    op.drop_column('waste_types', 'description')
    op.drop_column('waste_types', 'code')

    # ------------------------------------------------------------------
    # 3) products.waste_limit.
    # ------------------------------------------------------------------
    op.drop_column('products', 'waste_limit')

    # ------------------------------------------------------------------
    # 2) waste_details.
    # ------------------------------------------------------------------
    op.drop_table('waste_details')

    # ------------------------------------------------------------------
    # 1) app_parameters (borra tablas y registros de seed).
    # ------------------------------------------------------------------
    op.drop_table('app_parameters')
