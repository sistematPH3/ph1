from flask import render_template, request, redirect, url_for, flash
from app.inventory import inventory_bp
from app.inventory.services.products_service import ProductService
from app.models.inventory_model import Category

# =========================================================================
# CONSULTAS, LISTADOS Y EDICIÓN (Responsable: Diego)
# =========================================================================

@inventory_bp.route('/products', methods=['GET'])
def list_products():
    """
    Controlador del listado general de insumos.
    Captura y valida parámetros de búsqueda en la URL (?q=).
    """
    search_query = request.args.get('q', '')
    
    # Validador específico de listado: Evitar términos de búsqueda exagerados
    if len(search_query) > 50:
        flash("La búsqueda es demasiado larga. Máximo 50 caracteres.", "warning")
        return redirect(url_for('inventory.list_products'))
        
    # Pedimos la lista filtrada o completa al servicio
    products = ProductService.get_listed_products(search_query)
    
    # Renderizamos tu plantilla de listado enviando los objetos
    return render_template('list_products.html', products=products, search_query=search_query)


