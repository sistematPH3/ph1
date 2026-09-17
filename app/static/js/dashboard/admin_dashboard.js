/* Dashboard del Admin (Módulo 8 - Rápido 1): tabs de métricas + gráfico. */
(function () {
    'use strict';

    const root = document.querySelector('.dash-content') || document.body;
    const datos = JSON.parse(root.dataset.datosGrafico || '{"periods":[],"metrics":{}}');
    const mermasTipoData = JSON.parse(root.dataset.mermasTipo || '{"tipos":[]}');
    const orden = ['PURCHASES', 'KITCHEN_CONSUMPTION', 'WASTE', 'TRANSFERS'];
    const config = {
        'PURCHASES': {label: 'Compras', color: '#ce1126'},
        'KITCHEN_CONSUMPTION': {label: 'Consumo Cocina', color: '#2563eb'},
        'WASTE': {label: 'Mermas', color: '#d97706'},
        'TRANSFERS': {label: 'Traslados', color: '#7c3aed'},
    };
    const ALL_CLR = '#334155';
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

    function datasetsPara(esTodo) {
        return orden.map(function (m) {
            const cfg = config[m];
            return {
                label: cfg.label + ' (' + moneda + ')',
                data: datos.metrics[m] || [],
                borderColor: cfg.color,
                backgroundColor: cfg.color + '22',
                fill: !esTodo,
                tension: 0.32,
                borderWidth: esTodo ? 1.6 : 2,
                pointRadius: esTodo ? 2 : 3,
                pointHoverRadius: 5,
                pointBackgroundColor: '#ffffff',
                pointBorderColor: cfg.color,
                pointHoverBackgroundColor: cfg.color,
                pointHoverBorderColor: cfg.color,
            };
        });
    }

    function construir() {
        const ctx = document.getElementById('globalChart');
        if (!ctx) return;
        const emptyEl = document.getElementById('dashEmpty');
        const esTodo = activa === 'ALL';
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
                datasets: datasetsPara(esTodo),
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: esTodo ? {
                        display: true,
                        position: 'bottom',
                        labels: {
                            color: '#5e6a7e',
                            usePointStyle: true,
                            pointStyle: 'circle',
                            boxWidth: 8,
                            padding: 18,
                            font: {size: 11, weight: 600}
                        }
                    } : {display: false},
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
        dot.style.background = activo ? '#ffffff' : (config[tab.dataset.metric] || {}).color || ALL_CLR;
    }

    function initTabs() {
        const tabs = document.querySelectorAll('#metricTabs .metric-tab');
        tabs.forEach(function (tab) {
            tab.setAttribute('role', 'tab');
            tab.setAttribute('aria-pressed', tab.classList.contains('active') ? 'true' : 'false');
            tab.addEventListener('click', function () {
                tabs.forEach(function (t) {
                    t.classList.remove('active');
                    t.removeAttribute('style');
                    t.setAttribute('aria-pressed', 'false');
                    renderDot(t, false);
                });
                activa = tab.dataset.metric;
                tab.classList.add('active');
                tab.setAttribute('aria-pressed', 'true');
                const cfg = config[activa] || {};
                const clr = cfg.color || ALL_CLR;
                tab.style.borderColor = clr;
                tab.style.background = clr;
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
        const datos = mermasTipoData;
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

    /* ------------------- Regenerar snapshots ------------------- */
    function initRefresh() {
        const btn = document.getElementById('btn-refresh-snapshots');
        if (!btn) return;
        const original = btn.innerHTML;
        btn.addEventListener('click', async function () {
            btn.disabled = true;
            btn.innerHTML = 'Actualizando datos…';
            try {
                const resp = await fetch(btn.dataset.url, {
                    method: 'POST',
                    headers: {'X-Requested-With': 'fetch'},
                    body: new URLSearchParams({period_type: btn.dataset.period})
                });
                const data = await resp.json();
                if (!data || !data.success) {
                    throw new Error((data && data.message) || 'No se pudieron regenerar los snapshots.');
                }
                setTimeout(function () { window.location.reload(); }, 900);
            } catch (e) {
                btn.innerHTML = original;
                btn.disabled = false;
                window.alert('Error: ' + (e.message || 'No se pudieron regenerar los snapshots.'));
            }
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        initTabs();
        construir();
        construirMermasTipo();
        initRefresh();
    });
})();