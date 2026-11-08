from flask import render_template, request, redirect, url_for, flash
from app.inventory import inventory_bp
from app.inventory.services.products_service import ProductService
from app.models.inventory_model import Category
from app.inventory.requests.list_products_request import ListProductsRequest

# =========================================================================
# CONSULTAS, LISTADOS Y EDICIÓN (Responsable: Diego)
# =========================================================================

@inventory_bp.route('/products', methods=['GET'])
def list_products():
    form_request = ListProductsRequest(request.args)
    
    if not form_request.is_valid():
        flash("La búsqueda es demasiado larga. Máximo 50 caracteres.", "warning")
        return redirect(url_for('inventory.list_products'))
        
    # Cambias 'search_query' por 'search_term' aquí:
    products = ProductService.get_listed_products(form_request.search_query)
    
    # Y aquí también al mandarlo a la plantilla:
    return render_template(
        'list_products.html', 
        products=products, 
        search_query=form_request.search_query
    )
@inventory_bp.route('/products/<int:product_id>/toggle-status', methods=['POST'])
def toggle_product_status(product_id):
    try:
        # Buscamos el insumo directamente en el repositorio
        from app.inventory.repositories.products_repository import ProductRepository
        product = ProductRepository.find_by_id(product_id)
        
        if not product:
            return {"success": False, "error": "Producto no encontrado"}, 404
            
        # Invertimos su estado de activación de forma booleana
        product.is_active = not product.is_active
        ProductRepository.save(product)
        
        return {"success": True, "is_active": product.is_active}, 200
    except Exception as e:
        return {"success": False, "error": str(e)}, 500