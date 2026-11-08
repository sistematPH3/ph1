"""estadisticas_statistics_snapshots

Crea la tabla statistics_snapshots: resúmenes por sede y período
(compras, consumos, mermas, traslados) en las tres monedas, para que
los reportes, gráficos y alarmas del Módulo 8 lean de aquí.

Revision ID: a1b2c3d4e5f0
Revises: 4f0e1d2c3b4a
Create Date: 2026-09-10 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f0'
down_revision = '4f0e1d2c3b4a'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'statistics_snapshots',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('location_id', sa.Integer(), sa.ForeignKey('locations.id'), nullable=False),
        sa.Column('metric', sa.String(30), nullable=False),
        sa.Column('period_type', sa.String(15), nullable=False),
        sa.Column('period_start', sa.Date(), nullable=False),
        sa.Column('period_end', sa.Date(), nullable=True),
        sa.Column('amount_bs', sa.Numeric(15, 2), nullable=False, server_default='0'),
        sa.Column('amount_usd', sa.Numeric(15, 2), nullable=False, server_default='0'),
        sa.Column('amount_eur', sa.Numeric(15, 2), nullable=False, server_default='0'),
        sa.Column('quantity', sa.Numeric(14, 2), nullable=False, server_default='0'),
        sa.Column('record_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('calculated_at', sa.DateTime(), nullable=False),
        sa.Column('calculated_by_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.UniqueConstraint(
            'location_id', 'metric', 'period_type', 'period_start',
            name='uq_statistics_snapshots_loc_metric_period',
        ),
    )


def downgrade():
    op.drop_table('statistics_snapshots')