document.addEventListener('DOMContentLoaded', function () {
    const searchInput = document.getElementById('searchDisputeInput');
    const statusSelect = document.getElementById('statusFilterSelect');
    const locationSelect = document.getElementById('locationFilterSelect');
    const tableRows = document.querySelectorAll('.ph-table tbody tr.dispute-row');
    const noResultsRow = document.getElementById('noResultsRow');

    function filterTable() {
        const query = searchInput ? searchInput.value.toLowerCase().trim() : '';
        const selectedStatus = statusSelect ? statusSelect.value.toLowerCase().trim() : '';
        
        let selectedLocationText = '';
        if (locationSelect && locationSelect.selectedIndex > 0) {
            selectedLocationText = locationSelect.options[locationSelect.selectedIndex].text.toLowerCase().trim();
        }
        
        let visibleCount = 0;

        tableRows.forEach(row => {
            const textContent = row.textContent.toLowerCase();
            const matchesSearch = textContent.includes(query);
            const matchesStatus = selectedStatus === "" || textContent.includes(selectedStatus);
            const matchesLocation = selectedLocationText === "" || textContent.includes(selectedLocationText);

            if (matchesSearch && matchesStatus && matchesLocation) {
                row.style.display = '';
                visibleCount++;
            } else {
                row.style.display = 'none';
                const nextRow = row.nextElementSibling;
                if (nextRow && nextRow.classList.contains('collapse')) {
                    nextRow.classList.remove('show');
                }
            }
        });

        if (noResultsRow) {
            if (visibleCount === 0 && tableRows.length > 0) {
                noResultsRow.style.display = '';
            } else {
                noResultsRow.style.display = 'none';
            }
        }
    }

    if (searchInput) searchInput.addEventListener('input', filterTable);
    if (statusSelect) statusSelect.addEventListener('change', filterTable);
    if (locationSelect) locationSelect.addEventListener('change', filterTable);

    // Al abandonar la resolución de una novedad (botón "Cancelar" o la "X" del
    // modal) sin emitir el veredicto, se avisa al backend para que cancele
    // cualquier despacho complementario de reposición que se haya generado
    // desde ese mismo registro. Así se evita que quede un traslado en tránsito
    // sin ninguna novedad que lo respalde (discrepancia de inventario).
    document.querySelectorAll('.dispute-modal-dismiss').forEach(btn => {
        btn.addEventListener('click', async () => {
            const movementId = btn.dataset.movementId;
            const modalEl = btn.closest('.modal');

            const previouslyDisabled = btn.disabled;
            btn.disabled = true;

            try {
                if (movementId) {
                    await fetch(`/logistics/movements/admin/disputes/${movementId}/cancel-replenishment`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' }
                    });
                }
            } catch (error) {
                // Si falla la llamada de red, igual dejamos cerrar el modal;
                // el traslado quedará visible para revisión manual del admin.
            } finally {
                btn.disabled = previouslyDisabled;
                if (modalEl) {
                    const modalInstance = bootstrap.Modal.getOrCreateInstance(modalEl);
                    modalInstance.hide();
                }
            }
        });
    });

    // Reapertura automática del registro de la disputa al volver del despacho complementario
    // (ya sea porque se canceló el traslado o porque se procesó exitosamente)
    const urlParams = new URLSearchParams(window.location.search);
    const openDisputeId = urlParams.get('open_dispute');
    if (openDisputeId) {
        // El formulario de resolución (donde vive el botón "Ir a Reposición") está
        // dentro del modal, no dentro de la fila colapsable de "Ver". Hay que reabrir
        // el modal para que el usuario retome la resolución donde la dejó.
        const resolveModalEl = document.getElementById(`resolveModal-${openDisputeId}`);
        if (resolveModalEl) {
            const modalInstance = bootstrap.Modal.getOrCreateInstance(resolveModalEl);
            modalInstance.show();
        }

        // Además, expandimos la fila de detalle como contexto adicional y
        // desplazamos la vista suavemente hacia el registro correspondiente.
        const detailRow = document.getElementById(`detalle-disputa-${openDisputeId}`);
        if (detailRow) {
            const bsCollapse = bootstrap.Collapse.getOrCreateInstance(detailRow, { toggle: false });
            bsCollapse.show();

            setTimeout(() => {
                detailRow.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }, 300);
        }
    }
});