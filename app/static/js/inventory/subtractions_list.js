// Función para abrir el modal y cargar los datos dinámicos
function abrirModalEdicion(idMovimiento, cantidadActual, nombreProducto) {
    // Configuramos el título y el valor actual en los inputs
    document.getElementById('modalTitulo').innerText = 'Editar Gasto - ' + nombreProducto;
    document.getElementById('inputNuevaCantidad').value = cantidadActual;
    
    // Configuramos la ruta hacia la cual apuntará el formulario al hacer submit
    document.getElementById('formEdicion').action = '/inventory/movements/subtractions/edit/' + idMovimiento;
    
    // Mostramos el modal
    document.getElementById('modalEdicion').style.display = 'block';
}

// Función para cerrar el modal
function cerrarModal() {
    document.getElementById('modalEdicion').style.display = 'none';
}