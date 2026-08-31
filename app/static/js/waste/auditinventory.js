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

    const actionLogId = document.getElementById('actionLogId');
    const actionType = document.getElementById('actionType');
    const newQuantityInput = document.getElementById('newQuantityInput');
    const actionNotes = document.getElementById('actionNotes');
    const editQuantityContainer = document.getElementById('editQuantityContainer');
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
            const editLotInput = document.getElementById('editLotInput');
            if (editLotInput) editLotInput.value = '';
            document.getElementById('actionAuditModalLabel').innerText = 'Confirmar Acción: ' + type;
            editQuantityContainer.style.display = type === 'EDITAR' ? 'block' : 'none';
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
                    text: 'Debe ingresar la nueva variación para editar el registro.',
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
                const response = await fetch('/api/waste/audit/action', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        log_id: actionLogId.value,
                        action_type: type,
                        notes: notes,
                        new_quantity: newQuantityInput.value ? parseFloat(newQuantityInput.value) : null,
                        lot_number: document.getElementById('editLotInput') ? document.getElementById('editLotInput').value.trim() || null : null
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