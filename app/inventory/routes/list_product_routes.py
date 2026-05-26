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


@inventory_bp.route('/products/edit/<int:product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    """
    Controlador encargado de la edición de un producto.
    GET: Carga el formulario con los datos actuales.
    POST: Procesa la actualización del insumo.
    """
    if request.method == 'POST':
        form_data = request.form.to_dict()
        try:
            ProductService.update_existing_product(product_id, form_data)
            flash("Insumo actualizado exitosamente.", "success")
            return redirect(url_for('inventory.list_products'))
        except ValueError as e:
            # Si el SKU está duplicado o falta algo, atrapamos el error del servicio
            flash(str(e), "danger")
            return redirect(url_for('inventory.edit_product', product_id=product_id))

    # Método GET: Recuperamos el producto y las categorías para pintar la vista
    from app.inventory.repositories.products_repository import ProductRepository
    product = ProductRepository.find_by_id(product_id)
    if not product:
        flash("El insumo solicitado no existe.", "danger")
        return redirect(url_for('inventory.list_products'))
        
    categories = Category.query.all() # Para el select dinámico de categorías
    
    # Reutilizamos la plantilla de formulario mandándole el objeto 'product' existente
    return render_template('product_form.html', product=product, categories=categories)