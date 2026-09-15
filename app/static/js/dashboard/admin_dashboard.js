/* Dashboard del Admin (Módulo 8 - Rápido 1): tabs de métricas + gráfico. */
(function () {
    'use strict';

    const datos = window.PH_DATOS_GRAFICO || {periods: [], metrics: {}};
    const orden = ['PURCHASES', 'KITCHEN_CONSUMPTION', 'WASTE', 'TRANSFERS'];
    const config = {
        'PURCHASES': {label: 'Compras', color: '#ce1126'},
        'KITCHEN_CONSUMPTION': {label: 'Consumo Cocina', color: '#2563eb'},
        'WASTE': {label: 'Mermas', color: '#d97706'},
        'TRANSFERS': {label: 'Traslados', color: '#7c3aed'},
    };
    const SIMBOLO = {'USD': '$', 'EUR': '€', 'BS': 'Bs. '};
    const moneda = datos.moneda || 'USD';
    const simbolo = SIMBOLO[moneda] || '$';
    let grafico = null;
    let activa = 'PURCHASES';

    function totalDeTodas() {
        return orden.reduce(function (acc, m) {
            return acc + (datos.metrics[m] || []).reduce(function (a, v) { return a + (Number(v) || 0); }, 0);
        }, 0);
    }

    function construir() {
        const ctx = document.getElementById('globalChart');
        if (!ctx) return;
        const emptyEl = document.getElementById('dashEmpty');
        const cfg = config[activa];
        const valores = datos.metrics[activa] || [];
        const labels = (datos.periods || []).map(p => p.label);

        if (grafico) grafico.destroy();

        if (totalDeTodas() === 0) {
            ctx.style.display = 'none';
            if (emptyEl) emptyEl.style.display = 'block';
            return;
        }
        if (emptyEl) emptyEl.style.display = 'none';
        ctx.style.display = 'block';

        grafico = new Chart(ctx.getContext('2d'), {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: cfg.label + ' (' + moneda + ')',
                    data: valores,
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
                    pointHoverBorderColor: cfg.color,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {display: false},
                    tooltip: {
                        callbacks: {
                            label: function (item) {
                                return item.dataset.label + ': ' + simbolo + Number(item.parsed.y || 0).toFixed(2);
                            }
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        grid: {color: 'rgba(226, 232, 240, 0.6)'},
                        border: {display: false},
                        ticks: {color: '#64748b', callback: function (v) { return simbolo + v; }}
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

    function renderDot(tab, activo) {
        const dot = tab.querySelector('.dot');
        if (!dot) return;
        dot.style.background = activo ? '#ffffff' : (config[tab.dataset.metric] || {}).color || '#cbd5e1';
    }

    function initTabs() {
        const tabs = document.querySelectorAll('#metricTabs .metric-tab');
        tabs.forEach(function (tab) {
            tab.addEventListener('click', function () {
                tabs.forEach(function (t) {
                    t.classList.remove('active');
                    t.removeAttribute('style');
                    renderDot(t, false);
                });
                activa = tab.dataset.metric;
                tab.classList.add('active');
                const cfg = config[activa];
                tab.style.borderColor = cfg.color;
                tab.style.background = cfg.color;
                tab.style.color = '#ffffff';
                renderDot(tab, true);
                construir();
            });
        });
    }

    /* ------------------- Mermas por tipo ------------------- */
    const COLORES_TIPOS = ['#d97706', '#ce1126', '#7c3aed', '#2563eb', '#0f766e', '#be185d', '#b45309', '#0369a1'];

    function construirMermasTipo() {
        const ctx = document.getElementById('mermasTipoChart');
        const datos = window.PH_MERMAS_TIPO || {tipos: []};
        const panel = ctx ? ctx.closest('.dash-panel') : null;
        if (!ctx || !panel || !datos.tipos || !datos.tipos.length) return;

        const labels = datos.tipos.map(function (t) { return t.tipo; });
        const valores = datos.tipos.map(function (t) { return Number(t.monto_usd) || 0; });
        const colores = datos.tipos.map(function (_, i) { return COLORES_TIPOS[i % COLORES_TIPOS.length]; });

        new Chart(ctx.getContext('2d'), {
            type: 'bar',
            data: {labels: labels, datasets: [{label: 'Costo (USD)', data: valores, backgroundColor: colores, borderRadius: 6, barThickness: 22}]},
            options: {
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                plugins: {legend: {display: false}, tooltip: {callbacks: {label: function (item) { return '$' + Number(item.parsed.x || 0).toFixed(2); }}}},
                scales: {
                    x: {beginAtZero: true, grid: {color: 'rgba(226,232,240,.6)'}, border: {display: false}, ticks: {color: '#64748b', callback: function (v) { return '$' + v; }}},
                    y: {grid: {display: false}, border: {display: false}, ticks: {color: '#334155'}}
                }
            }
        });

        const leyenda = document.getElementById('mermasTiposLegend');
        if (leyenda) {
            leyenda.innerHTML = datos.tipos.map(function (t) {
                return '<span class="merma-tipo-chip"><strong>' + t.tipo + '</strong>: ' + Number(t.cantidad || 0) + ' und · $' + Number(t.monto_usd || 0).toFixed(2) + '</span>';
            }).join('');
        }
    }

    document.addEventListener('DOMContentLoaded', function () {
        initTabs();
        construir();
        construirMermasTipo();
    });
})();