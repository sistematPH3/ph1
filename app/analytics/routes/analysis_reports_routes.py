from datetime import date
from decimal import Decimal

from flask import (Blueprint, jsonify, render_template, request, url_for)
from flask_login import current_user, login_required

from app.decorators.roles import require_roles
from app.analytics.requests.analysis_reports_validators import validate_report_filters
from app.analytics.services import analysis_reports_service as report_svc

analysis_reports_bp = Blueprint('analysis_reports', __name__)

METRICAS_OPCIONES = [
    ('PURCHASES', 'Compras por sede / proveedor'),
    ('KITCHEN_CONSUMPTION', 'Gastos de cocina'),
    ('WASTE', 'Mermas'),
    ('TRANSFERS', 'Traslados'),
    ('CONSOLIDATED', 'Consolidado financiero'),
]
PERIODOS_OPCIONES = ('WEEKLY', 'MONTHLY', 'QUARTERLY', 'ANNUAL')
PERIODOS_ETIQUETAS = {
    'WEEKLY': 'Semanal',
    'MONTHLY': 'Mensual',
    'QUARTERLY': 'Trimestral',
    'ANNUAL': 'Anual',
}
MONEDAS = {
    'USD': 'Dólares (USD)',
    'BS': 'Bolívares (Bs)',
    'EUR': 'Euros (EUR)',
}
KPIS_ORDEN = ('compras', 'consumo_cocina', 'mermas', 'traslados', 'costo_operativo')


def _url_export(filtros, formato):
    query = dict(filtros)
    for campo in ('period_start', 'desde', 'hasta'):
        if hasattr(query.get(campo), 'isoformat'):
            query[campo] = query[campo].isoformat()
    query['formato'] = formato
    return url_for('exports.descargar', **query)


def _contexto_plantilla(filtros, metricas_opciones=None, kpis_orden=None):
    return {
        'metricas_opciones': metricas_opciones or METRICAS_OPCIONES,
        'periodos_opciones': PERIODOS_OPCIONES,
        'periodos_etiquetas': PERIODOS_ETIQUETAS,
        'monedas': MONEDAS,
        'kpis_orden': kpis_orden or KPIS_ORDEN,
        'export_url_pdf': _url_export(filtros, 'pdf'),
        'export_url_excel': _url_export(filtros, 'excel'),
        'filtros': filtros,
    }


def _metricas_y_orden_por_usuario(location_id=None):
    """Opciones de métrica y KPIs visibles según la Central: si el usuario no la
    gestiona, o filtra una sede que no es la Central (solo la Central compra),
    no ve compras (el reporte se mide por traslados)."""
    if report_svc.aplica_compras_por_filtro(current_user.id, location_id):
        return list(METRICAS_OPCIONES), list(KPIS_ORDEN)
    metricas = [m for m in METRICAS_OPCIONES if m[0] != 'PURCHASES']
    kpis = [k for k in KPIS_ORDEN if k != 'compras']
    return metricas, kpis


def _metric_efectiva(metric, location_id=None):
    """Métrica real del usuario: quien no gestiona la Central (o filtra otra
    sede que no es la Central) nunca usa compras, se sustituye por traslados."""
    if not report_svc.aplica_compras_por_filtro(current_user.id, location_id) \
            and (metric or 'PURCHASES') == 'PURCHASES':
        return 'TRANSFERS'
    return metric


@analysis_reports_bp.route('/analytics/reportes', methods=['GET'])
@login_required
@require_roles('admin', 'finance')
def reports_page():
    """Página de reportes de estadística (Admin ve todo, Finanzas sus sedes)."""
    datos = _filtros_desde_request()
    datos['metric'] = _metric_efectiva(datos['metric'], datos['location_id'])
    validado = validate_report_filters(datos)
    metricas_ctx, kpis_orden_ctx = _metricas_y_orden_por_usuario(
        datos['location_id'])

    if not validado['is_valid']:
        ctx = _contexto_plantilla(validado['data'], metricas_ctx, kpis_orden_ctx)
        ctx.update(reporte=None, kpis=None, ranking=None,
                   graficos=None, anclas=[], sedes=[], error=validado['errors'],
                   fechas_disponibles=[],
                   ver_compras=report_svc.aplica_compras_por_filtro(
                       current_user.id, datos['location_id']))
        return render_template('analytics/analysis_reports.html', **ctx)

    filtros = report_svc.ReportFilters(**validado['data'])
    reporte = report_svc.construir_reporte(filtros, current_user.id)

    if 'error' in reporte:
        ctx = _contexto_plantilla(validado['data'], metricas_ctx, kpis_orden_ctx)
        ctx.update(reporte=None, kpis=None, ranking=None,
                   graficos=None, anclas=[], sedes=[], error=reporte['error'],
                   fechas_disponibles=[],
                   ver_compras=report_svc.aplica_compras_por_filtro(
                       current_user.id, datos['location_id']))
        return render_template('analytics/analysis_reports.html', **ctx)

    sede_ids = reporte['filters']['location_ids']
    incluir_compras = report_svc.aplica_compras(current_user.id, sede_ids)
    moneda = validado['data']['moneda']
    kpis = report_svc.obtener_kpis(sede_ids, validado['data']['period_type'],
                                   validado['data']['period_start'],
                                   moneda, incluir_compras=incluir_compras,
                                   desde=validado['data']['desde'],
                                   hasta=validado['data']['hasta'])
    ranking = report_svc.obtener_ranking(sede_ids, validado['data']['metric'],
                                         validado['data']['period_start'],
                                         validado['data']['period_type'],
                                         moneda, incluir_compras=incluir_compras,
                                         desde=validado['data']['desde'],
                                         hasta=validado['data']['hasta'])
    anclas = report_svc.obtener_anclas_selector(sede_ids,
                                                validado['data']['metric'],
                                                validado['data']['period_type'])
    fechas_disponibles = report_svc.obtener_fechas_disponibles(
        sede_ids, validado['data']['metric'], validado['data']['period_type'])
    graficos = _a_json(report_svc.construir_graficos(
        reporte, ranking, moneda, incluir_compras=incluir_compras))
    from app.analytics.repositories.analysis_reports_repository import (
        obtener_sedes_opciones,
    )
    sedes = obtener_sedes_opciones(current_user.id)

    ctx = _contexto_plantilla(validado['data'], metricas_ctx, kpis_orden_ctx)
    ctx.update(reporte=reporte, kpis=kpis, ranking=ranking,
               graficos=graficos,
               anclas=anclas, sedes=sedes, error=None,
               fechas_disponibles=fechas_disponibles,
               ver_compras=incluir_compras)
    return render_template('analytics/analysis_reports.html', **ctx)


@analysis_reports_bp.route('/api/analytics/reportes', methods=['GET'])
@login_required
@require_roles('admin', 'finance')
def reports_api():
    datos = _filtros_desde_request()
    validado = validate_report_filters(datos)
    if not validado['is_valid']:
        return jsonify({'success': False, 'errors': validado['errors']}), 400

    filtros = report_svc.ReportFilters(**validado['data'])
    reporte = report_svc.construir_reporte(filtros, current_user.id)
    if 'error' in reporte:
        return jsonify({'success': False, 'message': reporte['error']}), 403
    return jsonify({'success': True, 'report': _a_json(reporte)}), 200


@analysis_reports_bp.route('/api/analytics/kpis', methods=['GET'])
@login_required
@require_roles('admin', 'finance')
def kpis_api():
    datos = _filtros_desde_request()
    datos['metric'] = _metric_efectiva(datos['metric'])
    validado = validate_report_filters(datos)
    if not validado['is_valid']:
        return jsonify({'success': False, 'errors': validado['errors']}), 400

    sede_ids, error = report_svc.queda_reporte_usuario_autorizado(
        current_user.id, validado['data']['location_id'])
    if error:
        return jsonify({'success': False, 'message': error}), 403

    kpis = report_svc.obtener_kpis(
        sede_ids, validado['data']['period_type'],
        validado['data']['period_start'], validado['data']['moneda'],
        incluir_compras=report_svc.aplica_compras(current_user.id, sede_ids),
        desde=validado['data']['desde'], hasta=validado['data']['hasta'])
    return jsonify({'success': True, 'kpis': _a_json(kpis)}), 200


@analysis_reports_bp.route('/api/analytics/ranking', methods=['GET'])
@login_required
@require_roles('admin', 'finance')
def ranking_api():
    datos = _filtros_desde_request()
    datos['metric'] = _metric_efectiva(datos['metric'])
    validado = validate_report_filters(datos)
    if not validado['is_valid']:
        return jsonify({'success': False, 'errors': validado['errors']}), 400

    sede_ids, error = report_svc.queda_reporte_usuario_autorizado(
        current_user.id, validado['data']['location_id'])
    if error:
        return jsonify({'success': False, 'message': error}), 403

    ranking = report_svc.obtener_ranking(
        sede_ids, validado['data']['metric'],
        validado['data']['period_start'], validado['data']['period_type'],
        validado['data']['moneda'],
        incluir_compras=report_svc.aplica_compras(current_user.id, sede_ids),
        desde=validado['data']['desde'], hasta=validado['data']['hasta'])
    return jsonify({'success': True, 'ranking': _a_json(ranking)}), 200


def _filtros_desde_request():
    return {
        'location_id': request.args.get('location_id'),
        'metric': request.args.get('metric', 'PURCHASES'),
        'period_type': request.args.get('period_type', 'MONTHLY'),
        'period_start': request.args.get('period_start'),
        'moneda': request.args.get('moneda', 'USD'),
        'desde': request.args.get('desde'),
        'hasta': request.args.get('hasta'),
    }


def _a_json(obj):
    if isinstance(obj, dict):
        return {k: _a_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_a_json(v) for v in obj]
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (date,)):
        return obj.isoformat()
    return obj