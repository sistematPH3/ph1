(function () {
    'use strict';

    var form = document.getElementById('reportFilters');
    var btnPdf = document.getElementById('btnExportPdf');
    var btnExcel = document.getElementById('btnExportExcel');
    var exportBase = '/analytics/reportes/export';

    function currentValues() {
        if (!form) return {};
        var data = {};
        ['metric', 'period_type', 'period_start', 'moneda', 'location_id',
         'desde', 'hasta']
            .forEach(function (name) {
                var el = form.querySelector('[name="' + name + '"]');
                data[name] = el ? el.value : '';
            });
        return data;
    }

    function buildExportUrl(formato) {
        var params = new URLSearchParams(currentValues());
        params.set('formato', formato);
        return exportBase + '?' + params.toString();
    }

    function refreshExportLinks() {
        if (btnPdf) btnPdf.href = buildExportUrl('pdf');
        if (btnExcel) btnExcel.href = buildExportUrl('excel');
    }

    function guardarSede(prefijo) {
        // Persiste la sede elegida entre pantallas de reportes.
        var sede = (currentValues().location_id || '');
        try {
            localStorage.setItem(prefijo + '_location_id', sede);
        } catch (e) { /* sin almacenamiento */ }
    }

    // Auto-aplicar al cambiar reporte, período, moneda, sede o rango de fechas.
    if (form) {
        form.addEventListener('change', function (e) {
            // El ancla del período se refleja al instante en los botones de
            // exportación sin recargar; el resto (incluido el rango desde/hasta)
            // recarga el reporte.
            if (e.target.name === 'period_start') {
                refreshExportLinks();
                return;
            }
            guardarSede('analysis_reports');
            form.submit();
        });
    }

    function prevenirDobleenvio(btn) {
        btn.addEventListener('click', function (e) {
            e.preventDefault();
            var esPdf = btn.id === 'btnExportPdf';
            if (esPdf) {
                // PDF inline: se abre en el visor (pestaña nueva) sin generar
                // evento de descarga que IDM pueda interceptar.
                window.open(btn.href, '_blank');
                return;
            }
            btn.classList.add('disabled');
            window.location.href = btn.href;
            setTimeout(function () { btn.classList.remove('disabled'); }, 4000);
        });
    }

    if (btnPdf) prevenirDobleenvio(btnPdf);
    if (btnExcel) prevenirDobleenvio(btnExcel);

    // Anclas: desvincularse de la selección específica si el ancla desaparece.
    var anclaSel = form && form.querySelector('[name="period_start"]');
    if (anclaSel) {
        var current = anclaSel.value;
        var existe = Array.prototype.some.call(anclaSel.options, function (o) {
            return o.value === current;
        });
        if (current && !existe) {
            anclaSel.value = '';
        }
    }

    refreshExportLinks();

    // -------------------------------------------------- gráficos Chart.js
    var g = window.RECORTES;

    var NOMBRE_METRICA = {
        PURCHASES: 'Compras',
        KITCHEN_CONSUMPTION: 'Gastos de cocina',
        WASTE: 'Mermas',
        TRANSFERS: 'Traslados',
        CONSOLIDATED: 'Costo operativo'
    };
    var PALETA = ['#C8102E', '#F5B301', '#1F3864', '#1A7F4B', '#8D4BB8',
                  '#2E75B6', '#C9803B', '#5A6B8C'];

    function destruirGrafico(id) {
        var el = document.getElementById(id);
        if (el && el.chart) {
            el.chart.destroy();
            el.chart = null;
        }
    }

    function crearGrafico(id, config) {
        var el = document.getElementById(id);
        if (!el) return;
        destruirGrafico(id);
        el.chart = new Chart(el, config);
    }

    function simboloMoneda(moneda) {
        if (moneda === 'BS') return 'Bs';
        if (moneda === 'EUR') return '\u20AC';
        return '$';
    }

    function textoMonto(v, moneda) {
        var num = Number(v);
        var esEntero = Math.abs(num - Math.round(num)) < 1e-9;
        var n = num.toLocaleString('es-VE', {
            minimumFractionDigits: esEntero ? 0 : 2,
            maximumFractionDigits: esEntero ? 0 : 2
        });
        if (moneda === 'mezcla') return n;
        return simboloMoneda(moneda) + ' ' + n;
    }

    function textoEje(v) {
        var n = Number(v);
        if (Math.abs(n) >= 1000) {
            return (n / 1000).toLocaleString('es-VE') + 'k';
        }
        return String(Math.round(n * 100) / 100);
    }

    function tooltipMonto(moneda, esConteo, sufijo) {
        return {
            callbacks: {
                label: function (ctx) {
                    var v = ctx.parsed.y || ctx.parsed || 0;
                    if (esConteo) return ' ' + Number(v).toLocaleString('es-VE') + ' movimientos';
                    if (ctx.dataset.type === 'doughnut' || ctx.chart.config.type === 'doughnut') {
                        return ' ' + textoMonto(ctx.parsed, moneda);
                    }
                    return ' ' + textoMonto(v, moneda);
                }
            }
        };
    }

    function renderizarGraficos() {
        if (!g || typeof Chart === 'undefined') return;

        var esConteo = g.metric === 'TRANSFERS';
        var nombreMet = NOMBRE_METRICA[g.metric] || 'Indicador';
        var moneda = g.moneda || 'USD';

        // 1) Evolución temporal (línea)
        if (g.evolucion && g.evolucion.length) {
            var evoLabels = g.evolucion.map(function (p) { return p.label; });
            var evoValues = g.evolucion.map(function (p) { return p.value; });
            var gradiente = document.createElement('canvas').getContext('2d');
            var relleno = gradiente.createLinearGradient(0, 0, 0, 320);
            relleno.addColorStop(0, 'rgba(200, 16, 46, 0.22)');
            relleno.addColorStop(1, 'rgba(200, 16, 46, 0.02)');

            crearGrafico('chartEvolucion', {
                type: 'line',
                data: {
                    labels: evoLabels,
                    datasets: [{
                        label: nombreMet,
                        data: evoValues,
                        borderColor: '#C8102E',
                        backgroundColor: relleno,
                        borderWidth: 2.5,
                        pointBackgroundColor: '#C8102E',
                        pointBorderColor: '#ffffff',
                        pointRadius: 4,
                        pointHoverRadius: 6,
                        fill: true,
                        tension: 0.35
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: function (ctx) {
                                    var v = ctx.parsed.y;
                                    if (esConteo) {
                                        return ' ' + Number(v).toLocaleString('es-VE') + ' movimientos';
                                    }
                                    return ' ' + textoMonto(v, moneda);
                                }
                            }
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            grid: { color: '#eef1f6' },
                            ticks: {
                                color: '#8a94a8',
                                callback: function (v) {
                                    if (esConteo) return textoEje(v);
                                    return textoMonto(v, moneda);
                                }
                            }
                        },
                        x: {
                            grid: { display: false },
                            ticks: { color: '#5a6b8c', maxRotation: 45, minRotation: 0 }
                        }
                    }
                }
            });
        }

        // 2) Desglose del reporte (barras o torta)
        if (g.detalle) {
            var d = g.detalle;
            var monedaDetalle = d.unidad === 'mezcla' ? 'mezcla' : moneda;
            var colores = d.labels.map(function (_, i) {
                return PALETA[i % PALETA.length];
            });
            var datasetDet = {
                label: nombreMet,
                data: d.values,
                backgroundColor: d.tipo === 'doughnut'
                    ? colores
                    : colores.map(function (c) { return c + 'CC'; }),
                borderColor: colores,
                borderWidth: 1
            };
            if (d.tipo === 'bar') {
                datasetDet.borderRadius = 6;
                datasetDet.maxBarThickness = 46;
            }
            crearGrafico('chartDetalle', {
                type: d.tipo === 'doughnut' ? 'doughnut' : 'bar',
                data: { labels: d.labels, datasets: [datasetDet] },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: d.tipo === 'doughnut'
                            ? { position: 'bottom', labels: { color: '#41537a', boxWidth: 12 } }
                            : { display: false },
                        tooltip: tooltipMonto(monedaDetalle, esConteo, null)
                    },
                    scales: d.tipo === 'doughnut'
                        ? {}
                        : {
                            y: {
                                beginAtZero: true,
                                grid: { color: '#eef1f6' },
                                ticks: {
                                    color: '#8a94a8',
                                    callback: function (v) {
                                        if (esConteo) return textoEje(v);
                                        return textoMonto(v, monedaDetalle);
                                    }
                                }
                            },
                            x: {
                                grid: { display: false },
                                ticks: { color: '#5a6b8c' }
                            }
                        }
                }
            });
        }

        // 4) Compras por categoría contable (barras apiladas por mes)
        if (g.gasto && g.gasto.series && g.gasto.series.length) {
            var gasto = g.gasto;
            var datasetsGasto = gasto.series.map(function (s, i) {
                return {
                    label: s.name,
                    data: s.values,
                    backgroundColor: PALETA[i % PALETA.length] + 'CC',
                    borderColor: PALETA[i % PALETA.length],
                    borderWidth: 1,
                    stack: 'gasto'
                };
            });
            crearGrafico('chartGasto', {
                type: 'bar',
                data: { labels: gasto.labels, datasets: datasetsGasto },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            position: 'bottom',
                            labels: { color: '#41537a', boxWidth: 12 }
                        },
                        tooltip: {
                            callbacks: {
                                label: function (ctx) {
                                    return ' ' + ctx.dataset.label + ': '
                                        + textoMonto(ctx.parsed.y, gasto.moneda);
                                },
                                footer: function (items) {
                                    var total = 0;
                                    items.forEach(function (it) { total += it.parsed.y; });
                                    return 'Total: ' + textoMonto(total, gasto.moneda);
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            stacked: true,
                            grid: { display: false },
                            ticks: { color: '#5a6b8c' }
                        },
                        y: {
                            stacked: true,
                            beginAtZero: true,
                            grid: { color: '#eef1f6' },
                            ticks: {
                                color: '#8a94a8',
                                callback: function (v) {
                                    return textoMonto(v, gasto.moneda);
                                }
                            }
                        }
                    }
                }
            });
        }

        // 5) Ranking entre sedes (barras horizontales)
        if (g.ranking && g.ranking.labels && g.ranking.labels.length > 1) {
            var r = g.ranking;
            var coloresRank = r.labels.map(function (_, i) {
                return PALETA[i % PALETA.length];
            });
            crearGrafico('chartRanking', {
                type: 'bar',
                data: {
                    labels: r.labels,
                    datasets: [{
                        label: 'Total del período',
                        data: r.values,
                        backgroundColor: coloresRank,
                        borderRadius: 6,
                        maxBarThickness: 26
                    }]
                },
                options: {
                    indexAxis: 'y',
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: function (ctx) {
                                    return ' ' + textoMonto(ctx.parsed.x, r.unidad || moneda);
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            beginAtZero: true,
                            grid: { color: '#eef1f6' },
                            ticks: {
                                color: '#8a94a8',
                                callback: function (v) {
                                    return textoMonto(v, r.unidad || moneda);
                                }
                            }
                        },
                        y: {
                            grid: { display: false },
                            ticks: { color: '#41537a' }
                        }
                    }
                }
            });
        }
    }

    renderizarGraficos();
})();