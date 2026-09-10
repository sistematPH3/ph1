from datetime import datetime
from decimal import Decimal

from app.extensions import db


class SnapshotMetric:
    """Métricas agregadas en statistics_snapshots (constantes compartidas)."""
    PURCHASES = 'PURCHASES'
    KITCHEN_CONSUMPTION = 'KITCHEN_CONSUMPTION'
    WASTE = 'WASTE'
    TRANSFERS = 'TRANSFERS'


class SnapshotPeriodType:
    """Tipos de período de los resúmenes (constantes compartidas)."""
    WEEKLY = 'WEEKLY'
    MONTHLY = 'MONTHLY'
    QUARTERLY = 'QUARTERLY'
    ANNUAL = 'ANNUAL'


class StatisticsSnapshot(db.Model):
    """Resumen ("foto") de los totales ya calculados por sede y período.

    Guarda cuánto se compró, consumió, mermó o trasladó en cada período, en las
    tres monedas, para que los reportes, gráficos y alarmas lean de aquí en vez
    de recalcular todo desde cero. Se refresca con un UPSERT idempotente.
    """
    __tablename__ = 'statistics_snapshots'
    __table_args__ = (
        db.UniqueConstraint(
            'location_id', 'metric', 'period_type', 'period_start',
            name='uq_statistics_snapshots_loc_metric_period',
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    location_id = db.Column(db.Integer, db.ForeignKey('locations.id'), nullable=False)
    metric = db.Column(db.String(30), nullable=False)        # SnapshotMetric
    period_type = db.Column(db.String(15), nullable=False)   # SnapshotPeriodType
    period_start = db.Column(db.Date, nullable=False)
    period_end = db.Column(db.Date)

    amount_bs = db.Column(db.Numeric(15, 2), nullable=False, default=Decimal('0.00'), server_default='0')
    amount_usd = db.Column(db.Numeric(15, 2), nullable=False, default=Decimal('0.00'), server_default='0')
    amount_eur = db.Column(db.Numeric(15, 2), nullable=False, default=Decimal('0.00'), server_default='0')
    quantity = db.Column(db.Numeric(14, 2), nullable=False, default=Decimal('0.00'), server_default='0')
    record_count = db.Column(db.Integer, nullable=False, default=0, server_default='0')

    calculated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    calculated_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    location = db.relationship('Location', backref=db.backref(
        'statistics_snapshots', lazy=True), lazy=True)
    calculated_by = db.relationship('User', backref=db.backref(
        'statistics_snapshots', lazy=True), lazy=True)