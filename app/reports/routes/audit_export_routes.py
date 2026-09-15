from io import BytesIO

from flask import Blueprint, jsonify, request, send_file
from flask_login import current_user, login_required

from app.decorators.roles import require_roles
from app.reports.requests.audit_export_validators import (
    validate_audit_export_params,
)
from app.reports.services.audit_export_generators import (
    generar_excel_auditoria,
    generar_pdf_auditoria,
)
from app.reports.services import audit_export_service

audit_exports_bp = Blueprint('audit_exports', __name__)

MIMETYPES = {
    'pdf': 'application/pdf',
    'excel': ('application/vnd.openxmlformats-officedocument.'
              'spreadsheetml.sheet'),
}


def _descargar(tipo, url_factory):
    """Crea el documento de la auditoría y lo envía como descarga directa.

    URL_factory(tipo) devuelve el nombre del archivo (siempre
    descarga-logo-<ext>, nunca una ruta renderizada) para que el navegador
    baje el PDF/Excel sin depender de gestores externos como IDM.
    """
    datos = validate_audit_export_params(request.args)

    if not datos['is_valid']:
        return jsonify({'success': False, 'message': 'Parámetros inválidos.'}), 400

    filtros = datos['data']  # {formato, sede, desde, hasta}

    documento = audit_export_service.construir_documento(tipo, current_user, filtros)

    if documento.get('error'):
        return jsonify({'success': False, 'message': documento['error']}), 403

    formato = filtros['formato']
    buffer = BytesIO()
    painter = generar_pdf_auditoria if formato == 'pdf' else generar_excel_auditoria
    archivo = painter(documento['header'], documento['detalle_tablas'])
    buffer.write(archivo.getvalue())
    buffer.seek(0)

    nombre = url_factory(tipo, formato)

    return send_file(
        buffer,
        # PDF en linea (vista en el visor del navegador): los gestores
        # externos como IDM no interceptan el contenido en linea, solo las
        # descargas attachment. El visor permite guardar el archivo.
        as_attachment=(formato != 'pdf'),
        download_name=nombre,
        mimetype=MIMETYPES[formato],
    )


def _nombre_descarga(tipo, formato):
    from datetime import datetime
    nombre_tipo = {
        'accesos': 'auditoria-accesos',
        'usuarios': 'auditoria-personal',
        'compras': 'auditoria-compras',
        'movimientos': 'auditoria-traslados',
        'mermas': 'auditoria-mermas',
        'inventario': 'auditoria-inventario',
    }.get(tipo, 'auditoria')
    marca = datetime.now().strftime('%Y%m%d_%H%M%S')
    ext = {'pdf': 'pdf', 'excel': 'xlsx'}.get(formato, 'xlsx')
    return f"{nombre_tipo}-{marca}.{ext}"


# =============================================================================
# 1) ACCESOS (Solo Administrator / Finance)
# =============================================================================
@audit_exports_bp.route('/auditoria/accesos/export', methods=['GET'])
@login_required
def descargar_accesos():
    user_role = current_user.role.name if hasattr(current_user, 'role') and current_user.role else ''
    if user_role not in ('Administrator', 'Finance'):
        return jsonify({'success': False, 'message': 'Permisos insuficientes.'}), 403
    return _descargar('accesos', _nombre_descarga)


# =============================================================================
# 2) PERSONAL / USUARIOS (admin, gestión o finanzas)
# =============================================================================
@audit_exports_bp.route('/auditoria/usuarios/export', methods=['GET'])
@login_required
def descargar_usuarios():
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Permisos insuficientes.'}), 403
    return _descargar('usuarios', _nombre_descarga)


# =============================================================================
# 3) COMPRAS (solo admin)
# =============================================================================
@audit_exports_bp.route('/auditoria/compras/export', methods=['GET'])
@login_required
@require_roles('admin')
def descargar_compras():
    return _descargar('compras', _nombre_descarga)


# =============================================================================
# 4) TRASLADOS / MOVIMIENTOS (admin / finance)
# =============================================================================
@audit_exports_bp.route('/logistics/movements/audit/export', methods=['GET'])
@login_required
@require_roles('admin', 'finance')
def descargar_movimientos():
    return _descargar('movimientos', _nombre_descarga)


# =============================================================================
# 5) MERMAS (admin / finance)
# =============================================================================
@audit_exports_bp.route('/waste/merma/audit/export', methods=['GET'])
@login_required
@require_roles('admin', 'finance')
def descargar_mermas():
    return _descargar('mermas', _nombre_descarga)


# =============================================================================
# 6) INVENTARIO (cualquier rol autenticado con acceso a inventario)
# =============================================================================
@audit_exports_bp.route('/waste/audit/export', methods=['GET'])
@login_required
def descargar_inventario():
    return _descargar('inventario', _nombre_descarga)