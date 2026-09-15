/* Estadísticas (Módulo 8 - Rápido 1): gráfico de evolución + regenerar snapshots. */
(function () {
    'use strict';

    var METRICAS = {
        'PURCHASES': {label: 'Compras', color: '#ce1126'},
        'KITCHEN_CONSUMPTION': {label: 'Consumo Cocina', color: '#2563eb'},
        'WASTE': {label: 'Mermas', color: '#d97706'},
        'TRANSFERS': {label: 'Traslados', color: '#7c3aed'}
    };
    var ORDEN = ['PURCHASES', 'KITCHEN_CONSUMPTION', 'WASTE', 'TRANSFERS'];

    var datos = window.PH_DATOS_ESTADISTICAS || {periods: [], metrics: {}};
    var ctx = document.getElementById('statsChart');
    var emptyEl = document.getElementById('statsEmpty');
    var legendEl = document.getElementById('statsLegend');
    var graf = null;
    var SIMBOLO = {'USD': '$', 'EUR': '€', 'BS': 'Bs. '}[datos.moneda || 'USD'] || '$';

    function totalPorMetrica() {
        return ORDEN.reduce(function (acc, m) {
            return acc + (datos.metrics[m] || []).reduce(function (a, v) { return a + (Number(v) || 0); }, 0);
        }, 0);
    }

    function construirGrafico() {
        if (!ctx) return;
        var datasets = ORDEN.map(function (m) {
            var cfg = METRICAS[m];
            return {
                label: cfg.label,
                data: datos.metrics[m] || [],
                borderColor: cfg.color,
                backgroundColor: cfg.color + '22',
                fill: true,
                tension: 0.32,
                borderWidth: 2,
                pointRadius: 3,
                pointHoverRadius: 5,
                pointBackgroundColor: '#ffffff',
                pointBorderColor: cfg.color,
                pointHoverBackgroundColor: cfg.color,
                pointHoverBorderColor: cfg.color
            };
        });

        graf = new Chart(ctx.getContext('2d'), {
            type: 'line',
            data: {
                labels: (datos.periods || []).map(function (p) { return p.label; }),
                datasets: datasets
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {mode: 'index', intersect: false},
                plugins: {
                    legend: {display: false},
                    tooltip: {
                        callbacks: {
                            label: function (item) {
                                return item.dataset.label + ': ' + SIMBOLO + Number(item.parsed.y || 0).toFixed(2);
                            }
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        grid: {color: 'rgba(226, 232, 240, 0.6)'},
                        border: {display: false},
                        ticks: {
                            callback: function (v) { return SIMBOLO + v; },
                            color: '#64748b'
                        }
                    },
                    x: {
                        grid: {display: false},
                        border: {display: false},
                        ticks: {color: '#64748b'}
                    }
                }
            }
        });
    }

    function construirLeyenda() {
        if (!legendEl) return;
        ORDEN.forEach(function (m, idx) {
            var cfg = METRICAS[m];
            var chip = document.createElement('button');
            chip.type = 'button';
            chip.className = 'stats-legend-chip active';
            chip.innerHTML = '<span class="dot" style="background:' + cfg.color + '"></span>' + cfg.label;
            chip.addEventListener('click', function () {
                var dataset = graf && graf.data.datasets[idx];
                if (!dataset) return;
                dataset.hidden = !dataset.hidden;
                chip.classList.toggle('active', !dataset.hidden);
                chip.classList.toggle('off', dataset.hidden);
                graf.update();
            });
            legendEl.appendChild(chip);
        });
    }

    function mostrarVacio() {
        if (!emptyEl || !ctx) return;
        var sinDatos = totalPorMetrica() === 0;
        emptyEl.style.display = sinDatos ? 'block' : 'none';
        if (ctx) ctx.style.display = sinDatos ? 'none' : 'block';
    }

    function init() {
        construirGrafico();
        construirLeyenda();
        mostrarVacio();
        initRefresh();
    }

    /* ------------------- Regenerar snapshots ------------------- */
    function initRefresh() {
        var btn = document.getElementById('btn-refresh-snapshots');
        if (!btn) return;
        btn.addEventListener('click', async function () {
            var status = document.getElementById('refreshStatus');
            btn.disabled = true;
            status.className = 'stats-refresh-status show';
            status.innerHTML = '<span class="stats-spinner"></span> Regenerando snapshots…';
            try {
                var resp = await fetch(btn.dataset.url, {
                    method: 'POST',
                    headers: {'X-Requested-With': 'fetch'},
                    body: new URLSearchParams({period_type: btn.dataset.period})
                });
                var data = await resp.json();
                if (data.success) {
                    status.className = 'stats-refresh-status show ok';
                    var periodos = data['per\u00edodos'] != null ? data['per\u00edodos'] : data.periods;
                    status.innerHTML = '<i class="bi bi-check-circle-fill"></i> ' +
                        (data.message || 'Snapshots actualizados') + ' (' + periodos + ' períodos).';
                    setTimeout(function () { window.location.reload(); }, 1000);
                } else {
                    throw new Error(data.message || 'Error desconocido');
                }
            } catch (e) {
                status.className = 'stats-refresh-status show err';
                status.innerHTML = '<i class="bi bi-exclamation-circle-fill"></i> ' + (e.message || 'Error de red.');
            } finally {
                setTimeout(function () { btn.disabled = false; }, 1600);
            }
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();