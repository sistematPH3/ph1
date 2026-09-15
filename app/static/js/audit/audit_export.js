document.addEventListener('DOMContentLoaded', function () {
    var toolbar = document.getElementById('auditExportToolbar');
    if (!toolbar) return;

    var baseUrl = toolbar.getAttribute('data-export-url');
    var botones = toolbar.querySelectorAll('[data-export-format]');
    var exportSinFechas = toolbar.dataset.exportSinFechas === 'true' ||
                          window.auditExportSinFechas === true;

    function valorToolbar(id) {
        var el = document.getElementById(id);
        return (el && el.value) ? el.value : '';
    }

    function valorPorIds(ids) {
        for (var i = 0; i < ids.length; i++) {
            var v = valorToolbar(ids[i]);
            if (v) return v;
        }
        return '';
    }

    function valorPorName(nombre) {
        var el = document.querySelector('[name="' + nombre + '"]');
        return (el && el.value) ? el.value : '';
    }

    function filtrosAplicados() {
        // 1) Si el toolbar muestra sus propios filtros (traslados, etc.), usar esos
        var desde = valorToolbar('exportDesde');
        var hasta = valorToolbar('exportHasta');
        var sede = valorToolbar('exportSede');

        // 2) Fallback: leer los filtros del cintillo que el usuario ya aplico
        if (!desde && !hasta) {
            desde = valorToolbar('start_date');
            hasta = valorToolbar('end_date');
        }
        // 2b) Accesos: cintillo con dateFilter (dia) y locationFilter (sede)
        if (!desde && !hasta) {
            var dia = valorToolbar('dateFilter');
            if (dia) { desde = dia; hasta = dia; }
        }
        // 2c) Sede por nombre o id del cintillo (global, id numerico o nombre)
        if (!sede) {
            var loc = valorToolbar('location_filter') || valorToolbar('locationFilter')
                      || valorToolbar('filter_location') || valorToolbar('location_id');
            if (loc && loc.toLowerCase() !== 'all' && loc.toLowerCase() !== 'todas las sedes') {
                sede = loc;
            }
        }
        // 2d) Hora exacta (solo en Auditoría de Accesos)
        var hora = valorToolbar('exportHora') || valorToolbar('hourFilter');
        // 2e) Severidad: por id o por name (inventario y traslados usan name="severity")
        var sev = valorPorIds(['auditSeveritySelect', 'severityFilter',
                               'severity', 'severity_filter'])
                  || valorPorName('severity');
        // 2f) Pestaña activa de inventario (ingresos/egresos)
        var pestaña = valorToolbar('exportTab') || valorPorName('tab');
        // 2g) Texto de búsqueda de cualquier apartado (incluye genericSearchInput
        //     de personal/compras y search_query de mermas)
        var q = valorPorIds(['auditSearchInput', 'searchInput',
                             'genericSearchInput', 'search_query']);
        return { desde: desde, hasta: hasta, sede: sede, sev: sev, q: q,
                 hora: hora, tab: pestaña };
    }

    botones.forEach(function (btn) {
        btn.addEventListener('click', function (e) {
            e.preventDefault();
            var formato = btn.getAttribute('data-export-format');
            var params = new URLSearchParams();
            params.set('formato', formato);

            var f = filtrosAplicados();
            if (f.desde) params.set('desde', f.desde);
            if (f.hasta) params.set('hasta', f.hasta);
            if (f.sede) params.set('sede', f.sede);
            if (f.sev) params.set('severity', f.sev);
            if (f.q) params.set('q', f.q);
            if (f.hora) params.set('hour', f.hora);
            if (f.tab) params.set('tab', f.tab);

            var url = baseUrl + '?' + params.toString();
            if (formato === 'pdf') {
                // El servidor sirve el PDF como inline (visor del navegador).
                // Abrirlo en pestaña nueva evita generar un evento de descarga
                // que IDM u otros gestores puedan interceptar.
                window.open(url, '_blank');
            } else {
                window.location.href = url;
            }
        });
    });
});
