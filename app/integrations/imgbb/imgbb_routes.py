from flask import Blueprint, request, render_template, flash, redirect, url_for
from app.integrations.imgbb.imgbb_services import upload_invoice_image

imgbb_bp = Blueprint('imgbb', __name__)

@imgbb_bp.route('/test-upload', methods=['GET'])
def show_upload_form():
    return render_template('test_imgbb.html')

@imgbb_bp.route('/test-upload', methods=['POST'])
def process_upload():
    if 'invoice_photo' not in request.files:
        flash("No se encontró ningún archivo.", "error")
        return redirect(url_for('imgbb.show_upload_form'))
    
    file = request.files['invoice_photo']
    
    if file.filename == '':
        flash("No se seleccionó ningún archivo.", "error")
        return redirect(url_for('imgbb.show_upload_form'))

    try:
        url_evidencia = upload_invoice_image(file)
        return f"<h1>¡Éxito!</h1><p>URL de ImgBB: <a href='{url_evidencia}' target='_blank'>{url_evidencia}</a></p><img src='{url_evidencia}' width='300'>"
    except Exception as e:
        flash(str(e), "error")
        return redirect(url_for('imgbb.show_upload_form'))