from flask import Blueprint, jsonify, request, send_file
from flask_login import current_user, login_required

from app.decorators.roles import require_roles
from app.analytics.requests.analysis_reports_validators import validate_report_filters
from app.analytics.services import analysis_reports_service as report_svc
from app.reports.requests.export_validators import validate_export_format
from app.reports.repositories.export_repository import construir_nombre_archivo
from app.reports.services import export_service
from app.reports.services.export_excel_generator import generar_excel
from app.reports.services.export_pdf_generator import generar_pdf

exports_bp = Blueprint('exports', __name__)

MIMETYPES = {
    'pdf': 'application/pdf',
    'excel': ('application/vnd.openxmlformats-officedocument.'
              'spreadsheetml.sheet'),
}


@exports_bp.route('/analytics/reportes/export', methods=['GET'])
@login_required
@require_roles('admin', 'finance')
def descargar():
    """Descarga del reporte activo en PDF o Excel con cabecera de auditoría."""
    datos = _filtros_desde_request()
    validado = validate_report_filters(datos)
    formato = validate_export_format(datos)

    errores = {**validado['errors'], **formato['errors']}
    if errores:
        return jsonify({'success': False, 'errors': errores}), 400

    filtros = report_svc.ReportFilters(
        location_id=validado['data']['location_id'],
        metric=validado['data']['metric'],
        period_type=validado['data']['period_type'],
        period_start=validado['data']['period_start'],
        moneda=validado['data']['moneda'],
        desde=validado['data']['desde'],
        hasta=validado['data']['hasta'],
    )
    datos_export = export_service.construir_exportacion(filtros, current_user.id)
    if 'error' in datos_export:
        return jsonify({'success': False, 'message': datos_export['error']}), 403

    if datos['formato'] == 'excel':
        buffer = generar_excel(datos_export)
        extension = 'xlsx'
    else:
        buffer = generar_pdf(datos_export)
        extension = 'pdf'

    nombre = construir_nombre_archivo(datos_export['header'], extension,
                                      current_user.id)
    # PDF en linea (visor del navegador) para evitar gestores externos como
    # IDM; el Excel sigue siendo descarga directa.
    return send_file(buffer, as_attachment=(datos['formato'] == 'excel'),
                     download_name=nombre, mimetype=MIMETYPES[datos['formato']])


def _filtros_desde_request():
    return {
        'location_id': request.args.get('location_id'),
        'metric': request.args.get('metric', 'PURCHASES'),
        'period_type': request.args.get('period_type', 'MONTHLY'),
        'period_start': request.args.get('period_start'),
        'moneda': request.args.get('moneda', 'USD'),
        'desde': request.args.get('desde'),
        'hasta': request.args.get('hasta'),
        'formato': request.args.get('formato', 'pdf'),
    }