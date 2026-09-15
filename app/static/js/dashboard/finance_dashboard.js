(function () {
    'use strict';

    var sel = document.getElementById('finPeriodo');
    var sedeSel = document.getElementById('finSede');
    var pdf = document.getElementById('finExportPdf');
    var xls = document.getElementById('finExportExcel');

    function ancla() {
        return sel ? sel.value : '';
    }

    function sede() {
        return sedeSel ? sedeSel.value : '';
    }

    function buildUrl(formato) {
        var params = new URLSearchParams();
        params.set('metric', window.FIN_PANEL_METRIC || 'CONSOLIDATED');
        params.set('period_type', 'MONTHLY');
        params.set('period_start', ancla());
        params.set('moneda', 'USD');
        params.set('formato', formato);
        if (sede()) {
            params.set('location_id', sede());
        }
        return '/analytics/reportes/export?' + params.toString();
    }

    function refresh() {
        if (pdf) pdf.href = buildUrl('pdf');
        if (xls) xls.href = buildUrl('excel');
    }

    if (sel) {
        sel.addEventListener('change', refresh);
    }

    // PDF inline: se abre en el visor (pestaña nueva) sin generar evento de
    // descarga que IDM u otros gestores puedan interceptar.
    if (pdf) {
        pdf.addEventListener('click', function (e) {
            e.preventDefault();
            window.open(pdf.getAttribute('href'), '_blank');
        });
    }

    refresh();
})();