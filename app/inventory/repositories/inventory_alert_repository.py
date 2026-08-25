from app.extensions import db
from app.models import Inventory, Product
from app.models.logistics_model import Location
from flask_login import current_user

def obtener_alarmas_para_dashboard():
    query = db.session.query(
        Inventory,
        Product.name.label('product_name'),
        Product.unit_of_measure.label('unit_of_measure'),
        Location.name.label('location_name')
    ).join(
        Product, Inventory.product_id == Product.id
    ).join(
        Location, Inventory.location_id == Location.id
    ).filter(
        Product.is_active == True,
        Location.is_active == True,
        Inventory.current_quantity > 0,
        Inventory.current_quantity <= Inventory.min_stock
    )
    
    is_admin = getattr(current_user, 'is_admin', False) or (
        getattr(current_user, 'role', None) and 'admin' in current_user.role.name.lower()
    ) or (getattr(current_user, 'role_id', None) == 1)
    
    if not is_admin:
        sedes_permitidas = [loc.id for loc in getattr(current_user, 'locations', [])]
        if not sedes_permitidas:
            return []
        query = query.filter(Inventory.location_id.in_(sedes_permitidas))
        
    resultados = query.order_by(Inventory.current_quantity.asc()).all()
    
    alarmas = []
    for inv, prod_name, unit, loc_name in resultados:
        alarmas.append({
            'location_name': loc_name,
            'product_name': prod_name or 'Insumo sin nombre',
            'new_quantity': float(inv.current_quantity or 0.0),
            'min_stock': float(inv.min_stock or 20.0),
            'unit_of_measure': unit or ''
        })
        
    return alarmas