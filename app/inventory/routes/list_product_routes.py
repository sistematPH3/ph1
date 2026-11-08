from flask import render_template, request, redirect, url_for, flash
from app.inventory import inventory_bp
from app.inventory.services.products_service import ProductService
from app.models.inventory_model import Category
from app.inventory.requests.list_products_request import ListProductsRequest

# CAMBIO: Importamos el decorador dinámico
from app.decorators.roles import require_roles 

# =========================================================================
# CONSULTAS, LISTADOS Y EDICIÓN (Responsable: Diego)
# =========================================================================

@inventory_bp.route('/products', methods=['GET'])
@require_roles('admin', 'management', 'manager', 'assistant_manager', 'operations')
def list_products():
    form_request = ListProductsRequest(request.args)
    
    if not form_request.is_valid():
        flash("La búsqueda es demasiado larga. Máximo 50 caracteres.", "warning")
        return redirect(url_for('inventory.list_products'))
        
    products = ProductService.get_listed_products(form_request.search_query)
    
    return render_template(
        'list_products.html', 
        products=products, 
        search_query=form_request.search_query
    )


@inventory_bp.route('/products/<int:product_id>/toggle-status', methods=['POST'])
@require_roles('admin', 'management', 'manager', 'assistant_manager', 'operations')
def toggle_product_status(product_id):
    try:
        from app.inventory.repositories.products_repository import ProductRepository
        product = ProductRepository.find_by_id(product_id)
        
        if not product:
            return {"success": False, "error": "Producto no encontrado"}, 404
            
        product.is_active = not product.is_active
        ProductRepository.save(product)
        
        return {"success": True, "is_active": product.is_active}, 200
    except Exception as e:
        return {"success": False, "error": str(e)}, 500