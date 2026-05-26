from flask import render_template, request, flash, redirect, url_for
from app.inventory import inventory_bp
@inventory_bp.route('/products/new', methods=['GET', 'POST'])
def create_product():
    return "¡Ruta de Leminyer (Formularios) funcionando correctamente!"