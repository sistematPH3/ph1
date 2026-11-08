// app/static/js/dashboard/management_dashboard.js

document.addEventListener('DOMContentLoaded', function () {
    const btnToggleStock = document.getElementById('btn-toggle-stock-history');
    const stockHistoryDrawer = document.getElementById('stock-history-drawer');

    if (btnToggleStock && stockHistoryDrawer) {
        btnToggleStock.addEventListener('click', function (e) {
            e.preventDefault();
            e.stopPropagation(); // Evita que se dispare cualquier enlace externo
            
            const isHidden = stockHistoryDrawer.style.display === 'none' || stockHistoryDrawer.style.display === '';
            stockHistoryDrawer.style.display = isHidden ? 'block' : 'none';
        });

        // Detener la propagación de clics dentro del mismo desplegable
        stockHistoryDrawer.addEventListener('click', function (e) {
            e.stopPropagation();
        });
    }

    // Scroll suave a Alertas Críticas
    const linkAlertas = document.getElementById('link-alertas-criticas');
    if (linkAlertas) {
        linkAlertas.addEventListener('click', function (e) {
            const panelCriticos = document.getElementById('panel-criticos-seccion');
            if (panelCriticos) {
                e.preventDefault();
                panelCriticos.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        });
    }
});