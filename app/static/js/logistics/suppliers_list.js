document.addEventListener("DOMContentLoaded", function() {
    const searchInput = document.getElementById('autoSearch');
    const statusFilter = document.getElementById('statusFilter');
    const noResults = document.getElementById('noResults');

    const modalDeactivate = new bootstrap.Modal(document.getElementById('modalDeactivate'));
    const modalActivate = new bootstrap.Modal(document.getElementById('modalActivate'));
    const modalDetails = new bootstrap.Modal(document.getElementById('modalDetails'));

    let activeToggleTarget = null;

    function applyFilters() {
        const searchValue = searchInput.value.toLowerCase().trim();
        const selectedStatus = statusFilter.value;
        
        // Obtenemos los dos grupos de filas/tarjetas de manera independiente
        const desktopRows = document.querySelectorAll('#suppliersTable tbody .supplier-row');
        const mobileCards = document.querySelectorAll('#mobileSuppliersContainer .mobile-supplier-card');
        
        let visibleDesktopCount = 0;
        let visibleMobileCount = 0;

        // 1. Filtrar filas de Escritorio
        desktopRows.forEach(row => {
            const sName = (row.getAttribute('data-name') || '').toLowerCase().trim();
            const sTaxId = (row.getAttribute('data-taxid') || '').toLowerCase().trim();
            const rowStatus = row.getAttribute('data-status');

            const matchesSearch = sName.includes(searchValue) || sTaxId.includes(searchValue);
            const matchesStatus = (selectedStatus === "") || (rowStatus === selectedStatus);

            if (matchesSearch && matchesStatus) {
                row.style.display = "";
                visibleDesktopCount++;
            } else {
                row.style.display = "none";
            }
        });

        // 2. Filtrar tarjetas de Teléfono
        mobileCards.forEach(card => {
            const sName = (card.getAttribute('data-name') || '').toLowerCase().trim();
            const sTaxId = (card.getAttribute('data-taxid') || '').toLowerCase().trim();
            const cardStatus = card.getAttribute('data-status');

            const matchesSearch = sName.includes(searchValue) || sTaxId.includes(searchValue);
            const matchesStatus = (selectedStatus === "") || (cardStatus === selectedStatus);

            if (matchesSearch && matchesStatus) {
                card.style.display = "block";
                visibleMobileCount++;
            } else {
                card.style.display = "none";
            }
        });

        // 3. Manejo del estado vacío (noResults)
        const isMobile = window.innerWidth < 768;
        const finalCount = isMobile ? visibleMobileCount : visibleDesktopCount;

        if (finalCount === 0) {
            noResults.classList.remove('d-none');
        } else {
            noResults.classList.add('d-none');
        }
    }

    searchInput.addEventListener('keyup', applyFilters);
    searchInput.addEventListener('input', applyFilters);
    statusFilter.addEventListener('change', applyFilters);

    // Asociación de Modales de Detalles (Ambos entornos: Computadora y Celular)
    function attachDetailsTrigger(selector) {
        document.querySelectorAll(selector).forEach(element => {
            element.addEventListener('click', function() {
                const row = this.closest('.supplier-row, .mobile-supplier-card');

                document.getElementById('detName').innerText = row.getAttribute('data-name');
                document.getElementById('detTaxId').innerText = row.getAttribute('data-taxid');
                document.getElementById('detContact').innerText = row.getAttribute('data-contact');
                document.getElementById('detPhone').innerText = row.getAttribute('data-phone');
                document.getElementById('detEmail').innerText = row.getAttribute('data-email');
                document.getElementById('detDate').innerText = row.getAttribute('data-date');

                modalDetails.show();
            });
        });
    }

    attachDetailsTrigger('.clickable-trigger');          // Escritorio
    attachDetailsTrigger('.clickable-trigger-mobile');   // Teléfono

    // Redirección de Edición (Ambos entornos)
    document.querySelectorAll('.btn-action-edit').forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.stopPropagation(); // Previene abrir el detalle en teléfono
            const supplierId = this.getAttribute('data-id');
            window.location.href = `/logistics/suppliers/edit/${supplierId}`;
        });
    });

    // Switches de estatus (Ambos entornos)
    document.querySelectorAll('.status-toggle').forEach(toggle => {
        toggle.addEventListener('click', function(e) {
            e.preventDefault(); 
            e.stopPropagation(); // Previene abrir el detalle en teléfono
            activeToggleTarget = this;
            const supplierName = this.getAttribute('data-name');

            if (!this.checked) {
                document.getElementById('deactivateSupplierName').innerText = supplierName;
                modalDeactivate.show();
            } else {
                document.getElementById('activateSupplierName').innerText = supplierName;
                modalActivate.show();
            }
        });
    });

    document.getElementById('btnConfirmDeactivate').addEventListener('click', function() {
        if (activeToggleTarget) executeToggleAjax(activeToggleTarget);
        modalDeactivate.hide();
    });

    document.getElementById('btnConfirmActivate').addEventListener('click', function() {
        if (activeToggleTarget) executeToggleAjax(activeToggleTarget);
        modalActivate.hide();
    });

    function executeToggleAjax(toggleElement) {
        const supplierId = toggleElement.getAttribute('data-id');
        fetch(`/logistics/suppliers/list/${supplierId}/toggle`, {
            method: 'POST',
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
                'Content-Type': 'application/json'
            }
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                window.location.reload(); 
            } else {
                alert("Error al procesar la solicitud.");
            }
        })
        .catch(err => console.error("Error:", err));
    }

    // Inicializar filtros
    applyFilters();
    
    // Si la pantalla rota o cambia de tamaño, recalculamos la vista de resultados
    window.addEventListener('resize', applyFilters);
});