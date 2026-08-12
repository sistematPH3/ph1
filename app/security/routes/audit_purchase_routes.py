from flask import Blueprint, render_template
from flask_login import current_user
from app.extensions import db
from app.models import PurchaseAuditLog, User, Role, Purchase, Location
from app.models.inventory_model import Product
from app.decorators.roles import require_roles
from datetime import timedelta
from sqlalchemy.orm import aliased

audit_purchase_bp = Blueprint('audit_purchase', __name__)

@audit_purchase_bp.route('/auditoria/compras', methods=['GET'])
@require_roles('admin', 'finance')
def list_purchase_audits():
    # Alias para distinguir al usuario Creador de la Compra del usuario Auditor
    PurchaseCreator = aliased(User)

    query = db.session.query(PurchaseAuditLog, User, Role)\
        .outerjoin(User, PurchaseAuditLog.user_id == User.id)\
        .outerjoin(Role, User.role_id == Role.id)\
        .outerjoin(Purchase, PurchaseAuditLog.purchase_id == Purchase.id)\
        .outerjoin(PurchaseCreator, Purchase.user_id == PurchaseCreator.id)

    # 1. Obtener y normalizar el rol del usuario actual
    user_role_name = current_user.role.name.lower().strip() if (hasattr(current_user, 'role') and current_user.role) else ''

    # 2. Obtener lista de IDs de las sedes asignadas al usuario actual (relación muchos a muchos)
    user_location_ids = [loc.id for loc in current_user.locations] if hasattr(current_user, 'locations') else []
    print(f"ROL: {user_role_name}, SEDES ASIGNADAS: {user_location_ids}")

    # 3. Filtrar si el rol es Finanzas
    if user_role_name in ['finance', 'finanzas']:
        if user_location_ids:
            # Filtra compras creadas por usuarios cuya lista de sedes contenga alguna de las sedes de Finanzas
            query = query.filter(PurchaseCreator.locations.any(Location.id.in_(user_location_ids)))
        else:
            # Si el usuario de Finanzas no tiene sedes asociadas, no retorna registros
            query = query.filter(db.false())

    # 4. Consulta ordenada por fecha descendente
    results = query.order_by(PurchaseAuditLog.timestamp.desc()).all()
    
    audits_list = []
    
    for audit, user, role in results:
        changed_data = {}
        
        if audit.action_type == 'CREATE':
            if audit.new_data:
                changed_data['Costo Total de la Factura'] = {
                    'old': '', 
                    'new': f"{audit.new_data.get('total_amount', 0)} {audit.new_data.get('currency', '')}"
                }
        elif audit.action_type == 'ANNULLED':
            changed_data['Estado de Factura'] = {
                'old': 'COMPLETED',
                'new': 'ANULADA (Stock Revertido)'
            }
        elif audit.action_type == 'EDIT':
            prev = audit.previous_data or {}
            curr = audit.new_data or {}
            
            changed_data['Motivo de Edición'] = {
                'old': '', 
                'new': curr.get('edit_reason', 'No especificado')
            }

            if str(float(prev.get('total_amount', 0))) != str(float(curr.get('total_amount', 0))):
                changed_data['Costo Total de la Factura'] = {'old': prev.get('total_amount'), 'new': curr.get('total_amount')}
            if str(float(prev.get('exchange_rate', 0))) != str(float(curr.get('exchange_rate', 0))):
                changed_data['Tasa de Cambio Aplicada'] = {'old': prev.get('exchange_rate'), 'new': curr.get('exchange_rate')}
            
            prev_details = {str(d.get('id', d.get('product_id'))): d for d in prev.get('details', [])}
            curr_details = {str(d.get('id', d.get('product_id'))): d for d in curr.get('details', [])}
            all_keys = set(list(prev_details.keys()) + list(curr_details.keys()))
            
            for key in all_keys:
                p_item = prev_details.get(key)
                c_item = curr_details.get(key)
                prod_id = p_item['product_id'] if p_item else c_item['product_id']
                
                product_obj = db.session.query(Product).get(prod_id)
                prod_name = product_obj.name if product_obj else f"Insumo ID {prod_id}"
                
                if not p_item and c_item:
                    changed_data[f'Insumo Añadido: {prod_name}'] = {'old': '-', 'new': f"Cant. Comprada: {c_item.get('quantity')} | Precio Unitario: {c_item.get('foreign_price')}"}
                elif p_item and not c_item:
                    changed_data[f'Insumo Eliminado: {prod_name}'] = {'old': f"Cant. Comprada: {p_item.get('quantity')} | Precio Unitario: {p_item.get('foreign_price')}", 'new': '-'}
                else:
                    if str(float(p_item.get('quantity', 0))) != str(float(c_item.get('quantity', 0))):
                        changed_data[f'Cantidad Comprada de {prod_name}'] = {'old': p_item.get('quantity'), 'new': c_item.get('quantity')}
                    if str(float(p_item.get('foreign_price', 0))) != str(float(c_item.get('foreign_price', 0))):
                        changed_data[f'Precio Unitario de {prod_name} (Cant. Comprada: {c_item.get("quantity")})'] = {'old': p_item.get('foreign_price'), 'new': c_item.get('foreign_price')}
                    p_date = str(p_item.get('expiration_date')) if p_item.get('expiration_date') else 'N/A'
                    c_date = str(c_item.get('expiration_date')) if c_item.get('expiration_date') else 'N/A'
                    if p_date != c_date:
                        changed_data[f'Fecha de Vencimiento de {prod_name}'] = {'old': p_date, 'new': c_date}

        local_time = audit.timestamp - timedelta(hours=4) if audit.timestamp else None

        audits_list.append({
            'id': audit.id,
            'purchase_id': audit.purchase_id,
            'action_type': audit.action_type,
            'timestamp': local_time,
            'changed_data': changed_data,
            'user_name': user.name if user else 'Sistema',
            'role_name': role.name if role else 'Administrador',
            'user_initial': user.name[:1].upper() if user else 'S'
        })

    return render_template('security/audit_purchase.html', audits=audits_list)