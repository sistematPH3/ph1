document.addEventListener("DOMContentLoaded", function() {
    // 1. Auto-cierre de alertas flash
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(function(alert) {
        setTimeout(function() {
            if (window.bootstrap && bootstrap.Alert) {
                const bsAlert = new bootstrap.Alert(alert);
                bsAlert.close();
            } else {
                alert.style.transition = "opacity 0.5s ease";
                alert.style.opacity = "0";
                setTimeout(() => alert.remove(), 500);
            }
        }, 2000);
    });

    // 2. Buscador y Filtro Cruzado en Tiempo Real
    const searchInput = document.getElementById('categorySearchInput');
    const controlFilter = document.getElementById('controlTypeFilter');
    const noResultsRow = document.getElementById('noResultsRow');
    const rows = document.querySelectorAll('.category-row');

    function executeCombinedFilter() {
        const query = searchInput ? searchInput.value.toLowerCase().trim() : '';
        const selectedFilter = controlFilter ? controlFilter.value : 'all';
        let totalVisible = 0;

        rows.forEach(row => {
            // Evaluamos el texto de la columna Categoría
            const categoryName = row.cells[0].textContent.toLowerCase();
            // Evaluamos el atributo data-control-type que añadimos en el HTML
            const rowControlType = row.getAttribute('data-control-type');

            const matchesText = categoryName.includes(query);
            const matchesFilter = (selectedFilter === 'all' || rowControlType === selectedFilter);

            // La fila se muestra únicamente si cumple ambas condiciones
            if (matchesText && matchesFilter) {
                row.style.display = "";
                totalVisible++;
            } else {
                row.style.display = "none";
            }
        });

        // Control dinámico del mensaje "No se encontraron resultados"
        if (noResultsRow) {
            if (totalVisible === 0 && rows.length > 0) {
                noResultsRow.style.display = "";
            } else {
                noResultsRow.style.display = "none";
            }
        }
    }

    // Escuchamos eventos en ambos componentes
    if (searchInput) {
        searchInput.addEventListener('input', executeCombinedFilter);
    }
    if (controlFilter) {
        controlFilter.addEventListener('change', executeCombinedFilter);
    }
});