"""Rutas del cajón de estadísticas (Rápido 1 - Módulo 8).

- POST /estadisticas/refresh       -> regenera snapshots (solo Admin).
- GET  /api/estadisticas/alarmas   -> alertas de irregularidad (Admin/Finance).
- GET/POST /config/estadisticas    -> configuración (factor y mínimo).
- GET  /estadisticas               -> pantalla del Admin (resumen del cajón).
"""
from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required

from app.decorators.roles import require_roles
from app.analytics.services import snapshots_service
from app.analytics.requests.statistics_validators import (
    validate_moneda,
    validate_period_type,
    validate_refresh_payload,
)
from app.models import Location

analytics_bp = Blueprint('analytics', __name__)


@analytics_bp.route('/estadisticas/refresh', methods=['POST'])
@login_required
@require_roles('admin')
def refresh_snapshots():
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    validacion = validate_refresh_payload(data)
    if not validacion['is_valid']:
        return jsonify({'success': False, 'errors': validacion['errors'], 'message': 'Tipo de período no válido.'}), 400
    resultado = snapshots_service.generar_snapshots(validacion['period_type'], user_id=current_user.id)
    return jsonify(resultado)


@analytics_bp.route('/api/estadisticas/alarmas', methods=['GET'])
@login_required
@require_roles('admin', 'finance')
def alarmas_api():
    period_type = validate_period_type(request.args.get('period_type'))
    location_ids = None
    if current_user.is_finance and not current_user.is_admin:
        location_ids = [loc.id for loc in current_user.locations]
    alertas = snapshots_service.evaluar_alarmas(period_type, location_ids=location_ids)
    return jsonify({'success': True, 'alertas': alertas})


@analytics_bp.route('/config/estadisticas', methods=['GET', 'POST'])
@login_required
@require_roles('admin')
def config_estadisticas():
    if request.method == 'GET':
        return render_template(
            'analytics/statistics_config.html',
            configs=snapshots_service.leer_configuracion(),
        )

    data = request.form.to_dict() if request.form else (request.get_json(silent=True) or {})
    errors = snapshots_service.actualizar_configuracion(data)
    if errors:
        mensaje = ' '.join(f'{campo}: {texto}' for campo, texto in errors.items())
        return jsonify({'success': False, 'errors': errors, 'message': mensaje}), 400
    return jsonify({'success': True, 'message': 'Parámetros de estadísticas actualizados correctamente.'})


# GET /estadisticas ELIMINADO (2026-09-14): la pantalla aparte statistics.html
# se borró por decisión de coordinación. La página de gráficos/estadísticas con
# filtros la rehace Mariuska; cuando ella suba su ruta, el CTA del banner Admin
# se repuntará a su endpoint (TODO: analytics.mariu... ). Su configuración sigue
# viviendo en /config/estadisticas (analytics.config_estadisticas).