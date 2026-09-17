from datetime import datetime as datetime_cls

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.decorators.roles import (
    management_required,
    manager_required,
    assistant_manager_required,
    admin_required,
    finance_required,
    operations_required
)
from app.inventory.repositories.inventory_alert_repository import obtener_alarmas_para_dashboard
from app.analytics.requests.statistics_validators import (
    validate_period_type,
    validate_moneda,
)
from app.analytics.services.snapshots_service import (
    leer_configuracion,
    evaluar_alarmas,
    obtener_grafico_evolucion,
    obtener_comparativo,
    obtener_costo_operativo,
    obtener_mermas_por_tipo,
    obtener_pendientes,
    generar_snapshots,
    faltan_snapshots,
)
from app.models import Location
from app.dashboard.dashboard_service import (
    get_subgerente_context,
    get_finance_dashboard_context,
)

dashboard_bp = Blueprint('dashboard', __name__)

def _contexto_estadisticas(period_type, moneda='USD', location_ids=None):
    """Contexto del cajón sin tumbar el dashboard si algo falla (tabla vacía, etc.)."""
    try:
        alertas_estadisticas = evaluar_alarmas(period_type, location_ids=location_ids)
    except Exception:
        alertas_estadisticas = []
    try:
        datos_grafico = obtener_grafico_evolucion(period_type, moneda=moneda, location_ids=location_ids)
    except Exception:
        datos_grafico = {
            'period_type': period_type,
            'moneda': moneda,
            'periods': [],
            'metrics': {
                'PURCHASES': [], 'KITCHEN_CONSUMPTION': [],
                'WASTE': [], 'TRANSFERS': [],
            },
        }
    return alertas_estadisticas, datos_grafico

def _asegurar_snapshots(period_type, user_id=None):
    """Regeneración perezosa: si falta el snapshot del período vigente se
    calcula SOLO ese período antes de renderizar. Un fallo aquí no debe tumbar el panel."""
    try:
        if faltan_snapshots(period_type):
            from app.analytics.services.snapshots_service import (
                calcular_periodo, generar_snapshot_periodo,
            )
            inicio, fin = calcular_periodo(period_type)
            generar_snapshot_periodo(period_type, inicio, fin, user_id=user_id)
    except Exception:
        pass


@dashboard_bp.route('/')
@login_required
def index():
    if current_user.is_management:
        return redirect(url_for('dashboard.director_dashboard'))
    elif current_user.is_manager:
        return redirect(url_for('dashboard.manager_dashboard'))
    elif current_user.is_admin:
        return redirect(url_for('dashboard.admin_dashboard'))
    elif current_user.is_finance:
        return redirect(url_for('dashboard.finance_dashboard'))
    elif current_user.is_operations:
        return redirect(url_for('dashboard.operations_dashboard'))
    elif current_user.is_assistant_manager:
        return redirect(url_for('dashboard.assistant_manager_dashboard'))
        
    flash("No tienes un rol permitido para visualizar el panel de control.", "danger")
    return redirect(url_for('security.login'))

@dashboard_bp.route('/director')
@login_required
@management_required
def director_dashboard():
    alarmas = obtener_alarmas_para_dashboard()
    return render_template('dashboard/management_dashboard.html', alarmas=alarmas)

@dashboard_bp.route('/manager-dashboard')
@login_required
@manager_required
def manager_dashboard():
    alarmas = obtener_alarmas_para_dashboard()
    return render_template('dashboard/manager_dashboard.html', alarmas=alarmas)

@dashboard_bp.route('/assistant-manager')
@login_required
@assistant_manager_required
def assistant_manager_dashboard():
    return render_template(
        'dashboard/assistant_manager_dashboard.html',
        **get_subgerente_context(current_user)
    )

@dashboard_bp.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    alarmas = obtener_alarmas_para_dashboard()
    period_type = validate_period_type(request.args.get('period'))
    default_moneda = leer_configuracion().get('ESTADISTICAS_MONEDA', 'USD')
    moneda = validate_moneda(request.args.get('moneda'), default=default_moneda)
    sedes = Location.query.filter_by(is_active=True).order_by(Location.name).all()
    sede_id = request.args.get('sede', type=int)
    if sede_id is not None and not any(s.id == sede_id for s in sedes):
        sede_id = None
    location_ids = [sede_id] if sede_id is not None else None
    _asegurar_snapshots(period_type, user_id=current_user.id)
    alertas_estadisticas, datos_grafico = _contexto_estadisticas(
        period_type, moneda=moneda, location_ids=location_ids,
    )
    try:
        pendientes = obtener_pendientes()
    except Exception:
        pendientes = {'mermas_pendientes': 0, 'traslados_en_transito': 0, 'disputas_pendientes': 0}
    try:
        costo_operativo = obtener_costo_operativo(
            period_type, moneda=moneda, location_ids=location_ids,
        )
    except Exception:
        costo_operativo = {'total': '0.00', 'moneda': moneda}
    try:
        comparativo = obtener_comparativo(
            period_type, moneda=moneda, location_ids=location_ids,
        )
    except Exception:
        comparativo = {'metricas': {}}
    try:
        mermas_por_tipo = obtener_mermas_por_tipo(period_type, location_ids=location_ids)
    except Exception:
        mermas_por_tipo = {'tipos': []}
    return render_template(
        'dashboard/admin_dashboard.html',
        alarmas=alarmas,
        alertas_estadisticas=alertas_estadisticas,
        datos_grafico=datos_grafico,
        costo_operativo=costo_operativo,
        comparativo=comparativo,
        mermas_por_tipo=mermas_por_tipo,
        period_type=period_type,
        moneda=moneda,
        pendientes=pendientes,
        sedes=sedes,
        sede_seleccionada=sede_id,
    )

@dashboard_bp.route('/finance')
@login_required
@finance_required
def finance_dashboard():
    alarmas = obtener_alarmas_para_dashboard()
    sede_raw = request.args.get('sede', '')
    sede_id = int(sede_raw) if sede_raw.isdigit() else None
    periodo_raw = request.args.get('periodo', '')
    periodo = None
    if periodo_raw:
        try:
            periodo = datetime_cls.strptime(periodo_raw, '%Y-%m-%d').date()
        except ValueError:
            periodo = None
    return render_template('dashboard/finance_dashboard.html', alarmas=alarmas,
                           **get_finance_dashboard_context(
                               current_user, sede_id=sede_id,
                               period_start=periodo, alarmas=alarmas))

@dashboard_bp.route('/operations')
@login_required
@operations_required
def operations_dashboard():
    alarmas = obtener_alarmas_para_dashboard()
    return render_template('dashboard/operations_dashboard.html', alarmas=alarmas)