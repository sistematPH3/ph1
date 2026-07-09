document.addEventListener("DOMContentLoaded", function() {
    const searchInput = document.getElementById('autoSearch');
    const statusFilter = document.getElementById('statusFilter');
    const noResults = document.getElementById('noResults');
    const tableElement = document.getElementById('suppliersTable');
    const tableHeader = tableElement.querySelector('thead');

    const modalDeactivate = new bootstrap.Modal(document.getElementById('modalDeactivate'));
    const modalActivate = new bootstrap.Modal(document.getElementById('modalActivate'));
    const modalDetails = new bootstrap.Modal(document.getElementById('modalDetails'));

    let activeToggleTarget = null;

    function applyFilters() {
        const searchValue = searchInput.value.toLowerCase().trim();
        const selectedStatus = statusFilter.value;
        const rows = document.querySelectorAll('#suppliersTable tbody .supplier-row');
        let visibleCount = 0;

        rows.forEach(row => {
            const sName = (row.getAttribute('data-name') || '').toLowerCase().trim();
            const sTaxId = (row.getAttribute('data-taxid') || '').toLowerCase().trim();
            const rowStatus = row.getAttribute('data-status');

            const matchesSearch = sName.includes(searchValue) || sTaxId.includes(searchValue);
            const matchesStatus = (selectedStatus === "") || (rowStatus === selectedStatus);

            if (matchesSearch && matchesStatus) {
                row.style.display = "";
                visibleCount++;
            } else {
                row.style.display = "none";
            }
        });

        if (visibleCount === 0) {
            tableHeader.style.display = "none";
            noResults.classList.remove('d-none');
        } else {
            tableHeader.style.display = "";
            noResults.classList.add('d-none');
        }
    }

    searchInput.addEventListener('keyup', applyFilters);
    searchInput.addEventListener('input', applyFilters);
    statusFilter.addEventListener('change', applyFilters);

    const triggers = document.querySelectorAll('.clickable-trigger');
    triggers.forEach(cell => {
        cell.addEventListener('click', function() {
            const row = this.closest('.supplier-row');

            document.getElementById('detName').innerText = row.getAttribute('data-name');
            document.getElementById('detTaxId').innerText = row.getAttribute('data-taxid');
            document.getElementById('detContact').innerText = row.getAttribute('data-contact');
            document.getElementById('detPhone').innerText = row.getAttribute('data-phone');
            document.getElementById('detEmail').innerText = row.getAttribute('data-email');
            document.getElementById('detDate').innerText = row.getAttribute('data-date');

            modalDetails.show();
        });
    });

    const editButtons = document.querySelectorAll('.btn-action-edit');
    editButtons.forEach(btn => {
        btn.addEventListener('click', function(e) {
            const supplierId = this.getAttribute('data-id');
            window.location.href = `/logistics/suppliers/edit/${supplierId}`;
        });
    });

    const toggles = document.querySelectorAll('.status-toggle');
    toggles.forEach(toggle => {
        toggle.addEventListener('click', function(e) {
            e.preventDefault(); 
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

    applyFilters();
});