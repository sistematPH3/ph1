from flask import render_template, request, flash, redirect, url_for
from app.inventory import inventory_bp
@inventory_bp.route('/products', methods=['GET'])
def list_products():
    # Comentamos temporalmente la lógica real para probar el canal de comunicación
    # return render_template('product_list.html', ...)
    return "¡Ruta de Diego (Listados) funcionando correctamente!"

