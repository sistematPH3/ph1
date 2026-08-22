document.addEventListener('DOMContentLoaded', function () {
    const searchInput = document.getElementById('searchDisputeInput');
    const statusSelect = document.getElementById('statusFilterSelect');
    const locationSelect = document.getElementById('locationFilterSelect');
    const tableRows = document.querySelectorAll('.ph-table tbody tr.dispute-row');
    const noResultsRow = document.getElementById('noResultsRow');

    function filterTable() {
        const query = searchInput ? searchInput.value.toLowerCase().trim() : '';
        const selectedStatus = statusSelect ? statusSelect.value.toLowerCase().trim() : '';
        
        // Obtenemos el texto visible de la sede seleccionada (ej. el nombre de la sede)
        let selectedLocationText = '';
        if (locationSelect && locationSelect.selectedIndex > 0) {
            selectedLocationText = locationSelect.options[locationSelect.selectedIndex].text.toLowerCase().trim();
        }
        
        let visibleCount = 0;

        tableRows.forEach(row => {
            const textContent = row.textContent.toLowerCase();
            
            // Evaluamos coincidencias generales de texto y estado
            const matchesSearch = textContent.includes(query);
            const matchesStatus = selectedStatus === "" || textContent.includes(selectedStatus);
            
            // Evaluamos si la fila contiene la sede seleccionada (ya sea como origen o destino)
            const matchesLocation = selectedLocationText === "" || textContent.includes(selectedLocationText);

            if (matchesSearch && matchesStatus && matchesLocation) {
                row.style.display = '';
                visibleCount++;
            } else {
                row.style.display = 'none';
                // Si la fila se oculta, cerramos su detalle desplegable si estuviera abierto
                const nextRow = row.nextElementSibling;
                if (nextRow && nextRow.classList.contains('collapse')) {
                    nextRow.classList.remove('show');
                }
            }
        });

        // Mostrar u ocultar el mensaje de "No se encontraron resultados"
        if (noResultsRow) {
            if (visibleCount === 0 && tableRows.length > 0) {
                noResultsRow.style.display = '';
            } else {
                noResultsRow.style.display = 'none';
            }
        }
    }

    // Escuchar eventos en los elementos de filtro
    if (searchInput) searchInput.addEventListener('input', filterTable);
    if (statusSelect) statusSelect.addEventListener('change', filterTable);
    if (locationSelect) locationSelect.addEventListener('change', filterTable);
});