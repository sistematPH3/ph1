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
                alert('Debe justificar obligatoriamente el motivo de la acción.');
                return;
            }
            const type = actionType.value;
            if (type === 'EDITAR' && newQuantityInput.value === '') {
                alert('Debe ingresar la nueva variación para editar el registro.');
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
                        new_quantity: newQuantityInput.value ? parseFloat(newQuantityInput.value) : null
                    })
                });
                const result = await response.json();
                if (result.success) {
                    if (actionModal) actionModal.hide();
                    window.location.reload();
                } else {
                    alert('Error: ' + result.message);
                }
            } catch (error) {
                alert('Error en la comunicación con el servidor.');
            } finally {
                btnConfirm.disabled = false;
                btnConfirm.innerText = 'Procesar Acción';
            }
        });
    }
});