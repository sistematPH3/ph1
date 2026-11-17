document.addEventListener('DOMContentLoaded', function () {
    const searchInput = document.getElementById('auditSearchInput');
    if (searchInput) {
        searchInput.addEventListener('input', function () {
            const q = this.value.toLowerCase();
            document.querySelectorAll('.ph-audit-card').forEach(function (card) {
                const haystack = card.getAttribute('data-search') || '';
                card.style.display = haystack.toLowerCase().indexOf(q) !== -1 ? '' : 'none';
            });
        });
    }

    // Cada pestaña se renderiza en el servidor con SU propio conjunto de datos
    // (gastos originales o movimientos compensatorios). Al cambiar de pestaña
    // se recarga la vista con ?tab=... para no mostrar registros del otro
    // apartado dentro del panel equivocado.
    document.querySelectorAll('#kitchenExpenseTabs [data-bs-toggle="tab"]').forEach(function (tabBtn) {
        tabBtn.addEventListener('click', function (event) {
            const target = (tabBtn.getAttribute('data-bs-target') || '').replace('#', '');
            if (!target) return;
            event.preventDefault();
            const url = new URL(window.location.href);
            url.searchParams.set('tab', target);
            window.location.assign(url.toString());
        });
    });

    const actionLogId = document.getElementById('actionLogId');
    const actionType = document.getElementById('actionType');
    const newQuantityInput = document.getElementById('newQuantityInput');
    const actionNotes = document.getElementById('actionNotes');
    const editQuantityContainer = document.getElementById('editQuantityContainer');
    const returnLotContainer = document.getElementById('returnLotContainer');
    const returnLotInput = document.getElementById('returnLotInput');
    const actionModalEl = document.getElementById('actionAuditModal');
    let actionModal = null;
    if (actionModalEl) {
        actionModal = new bootstrap.Modal(actionModalEl);
    }

    document.querySelectorAll('.btn-action-log').forEach(function (btn) {
        btn.addEventListener('click', function () {
            const type = btn.getAttribute('data-action');
            actionLogId.value = btn.getAttribute('data-id');
            actionType.value = type;
            actionNotes.value = '';
            newQuantityInput.value = '';
            // El lote viene precargado del botón y se bloquea como solo lectura;
            // el backend lo recibe tal cual sin permitir que el usuario lo edite.
            const raw_lot = btn.getAttribute('data-lot') || '';
            returnLotInput.value = raw_lot;
            returnLotInput.disabled = true;
            returnLotInput.setAttribute('readonly', '');
            document.getElementById('actionAuditModalLabel').innerText = 'Confirmar Acción: ' + type;
            editQuantityContainer.style.display = type === 'EDITAR' ? 'block' : 'none';
            // Editar y anular pueden devolver stock: el lote original se muestra
            // de solo lectura; el usuario no puede modificarlo ni escribirlo a mano.
            returnLotContainer.style.display = (type === 'EDITAR' || type === 'ANULAR') ? 'block' : 'none';
            if (actionModal) actionModal.show();
        });
    });

    const btnConfirm = document.getElementById('btnConfirmAction');
    if (btnConfirm) {
        btnConfirm.addEventListener('click', async function () {
            const notes = actionNotes.value.trim();
            if (!notes) {
                Swal.fire({
                    icon: 'warning',
                    title: 'Motivo Obligatorio',
                    text: 'Debe justificar obligatoriamente el motivo de la acción.',
                    confirmButtonColor: '#B31F24',
                    confirmButtonText: 'Cerrar'
                });
                return;
            }
            const type = actionType.value;
            if (type === 'EDITAR' && newQuantityInput.value === '') {
                Swal.fire({
                    icon: 'warning',
                    title: 'Cantidad Requerida',
                    text: 'Debe ingresar la cantidad real gastada para editar el registro.',
                    confirmButtonColor: '#B31F24',
                    confirmButtonText: 'Cerrar'
                });
                return;
            }
            if ((type === 'EDITAR' || type === 'ANULAR') && !returnLotInput.value.trim()) {
                Swal.fire({
                    icon: 'warning',
                    title: 'Lote Obligatorio',
                    text: 'El registro original no tiene lote de origen cargado. Contacte al Administrador para poder devolver stock.',
                    confirmButtonColor: '#B31F24',
                    confirmButtonText: 'Cerrar'
                });
                return;
            }
            if (type === 'EDITAR' && newQuantityInput.value !== '' && parseFloat(newQuantityInput.value) > 999999.99) {
                Swal.fire({
                    icon: 'warning',
                    title: 'Cantidad Excesiva',
                    text: 'La cantidad ingresada es excesiva (máx. 999999.99).',
                    confirmButtonColor: '#B31F24',
                    confirmButtonText: 'Cerrar'
                });
                return;
            }

            btnConfirm.disabled = true;
            btnConfirm.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Procesando...';

            try {
                const response = await fetch('/inventory/api/expenses/audit/action', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        log_id: actionLogId.value,
                        action_type: type,
                        notes: notes,
                        new_quantity: newQuantityInput.value ? parseFloat(newQuantityInput.value) : null,
                        lot_number: returnLotInput.value.trim() || null, // precargado y bloqueado (solo lectura)
                    })
                });
                const result = await response.json();
                if (result.success) {
                    if (actionModal) actionModal.hide();
                    window.location.reload();
                } else {
                    Swal.fire({
                        icon: 'error',
                        title: 'No se pudo procesar',
                        html: result.message || 'Ocurrió un error al procesar la acción.',
                        confirmButtonColor: '#B31F24',
                        confirmButtonText: 'Cerrar'
                    });
                }
            } catch (error) {
                Swal.fire({
                    icon: 'error',
                    title: 'Error de Conexión',
                    text: 'No se pudo comunicar con el servidor.',
                    confirmButtonColor: '#B31F24',
                    confirmButtonText: 'Cerrar'
                });
            } finally {
                btnConfirm.disabled = false;
                btnConfirm.innerText = 'Procesar Acción';
            }
        });
    }
});