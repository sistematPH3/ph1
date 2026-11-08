/* =========================================================
   BANDEJA DE RESPUESTAS: ESTADO "LEÍDO" EN EL SERVIDOR
   -----------------------------------------------------------------
   Estado vive en la tabla notifications (type RESPUESTA_TRASLADO y
   tipos MERMA_APROBADA / MERMA_RECHAZADA). La bandeja se divide en
   dos pestañas: "No leídos" y "Leídos". Soporta respuestas de
   TRASLADOS y de MERMAS (aprobada/rechazada): cada fila tiene
   data-response-type para distinguirlas y usar su propio id.
   ========================================================= */

document.addEventListener('DOMContentLoaded', function () {
    const cardElement = document.querySelector('.ph-card[data-user-id]');
    if (!cardElement) return;

    const readUrl = cardElement.getAttribute('data-read-url');
    const readAllUrl = cardElement.getAttribute('data-read-all-url');
    const unreadCountSpan = document.getElementById('unread-count');
    let unreadCount = unreadCountSpan ? parseInt(unreadCountSpan.textContent, 10) || 0 : 0;

    const unreadTbody = document.getElementById('tbody-unread');
    const readTbody = document.getElementById('tbody-read');
    const countUnread = document.getElementById('count-unread');
    const countRead = document.getElementById('count-read');
    const unreadTab = document.getElementById('unread-tab');
    const unreadTabItem = unreadTab ? unreadTab.closest('li') : null;
    const readTab = document.getElementById('read-tab');
    const readAllBtn = document.getElementById('read-all-btn');

    // ---- Identificadores de fila / desplegable según el tipo de respuesta ----
    function rowSel(movId, type) {
        return '#' + (type === 'MERMA' ? 'row-waste-' : 'row-mov-') + movId;
    }
    function collapseSel(movId, type) {
        return '#' + (type === 'MERMA' ? 'respuesta-waste-' : 'respuesta-admin-') + movId;
    }

    // ---- Búsqueda / filtros / paginación ----
    const PER_PAGE = 8;
    const searchInput = document.getElementById('inbox-search');
    const filterTipo = document.getElementById('filter-tipo');
    const filterNovedad = document.getElementById('filter-novedad');
    const filterSede = document.getElementById('filter-sede');
    const searchState = { text: '', tipo: '', novedad: '', sede: '' };
    const pageRefs = { unread: 1, read: 1 };

    // Traslados cuyo detalle está abierto y, al cerrarse, deben pasar a
    // "Leídos" (evita duplicar la sincronización si se abre y cierra varias
    // veces la misma respuesta).
    const pendingRead = {};

    // Recalcula los contadores de las pestañas. Cuando "No leídos" se
    // vacía, oculta su pestaña y (si estaba activa) pasa a "Leídos".
    function refreshSectionCounts() {
        const unreadTotal = unreadTbody ? unreadTbody.querySelectorAll('tr.dispute-row').length : 0;
        const readTotal = readTbody ? readTbody.querySelectorAll('tr.dispute-row').length : 0;

        if (countUnread) countUnread.textContent = unreadTotal;
        if (countRead) countRead.textContent = readTotal;

        if (unreadTab) {
            const empty = unreadTotal === 0;
            if (unreadTabItem) unreadTabItem.classList.toggle('d-none', empty);
            if (empty && unreadTab.classList.contains('active') && readTab) {
                readTab.click();
            }
        }
    }

    // ---- Paginación y filtrado por pestaña ----

    // ¿La fila cumple el buscador + filtros activos?
    function rowMatches(row) {
        const hay = (row.getAttribute('data-search') || '').toLowerCase();
        const novedad = row.getAttribute('data-novedad') || '';
        const tipo = row.getAttribute('data-response-type') || '';
        const sedes = (row.getAttribute('data-sede') || '').trim().split(/\s+/).filter(Boolean);

        const q = searchState.text.toLowerCase().replace('#', '').trim();
        const tokens = q ? q.split(/\s+/) : [];
        if (tokens.some(function (t) { return hay.indexOf(t) === -1; })) return false;
        if (searchState.tipo && tipo !== searchState.tipo) return false;
        if (searchState.novedad && novedad !== searchState.novedad) return false;
        if (searchState.sede && sedes.indexOf(searchState.sede) === -1) return false;
        return true;
    }

    // Cierra cualquier detalle abierto (evita "huérfanos" al filtrar/paginar).
    function closeOpenCollapses() {
        document.querySelectorAll('.dispute-row + tr.collapse.show').forEach(function (c) {
            if (window.bootstrap && bootstrap.Collapse.getInstance(c)) {
                bootstrap.Collapse.getInstance(c).hide();
            } else {
                c.classList.remove('show');
                c.style.display = 'none';
            }
        });
    }

    // Oculta/muestra una fila y su desplegable (la fila va seguida de su <tr class="collapse">).
    function setRowVisible(row, on) {
        row.style.display = on ? '' : 'none';
        const coll = row.nextElementSibling;
        if (coll && coll.classList && coll.classList.contains('collapse')) {
            if (on) {
                if (coll.style.display === 'none') coll.style.display = '';
            } else {
                coll.style.display = 'none';
            }
        }
    }

    // Aplica búsqueda + filtros + paginación a una pestaña.
    function applyPane(kind) {
        const tbody = kind === 'unread' ? unreadTbody : readTbody;
        if (!tbody) return;

        const rows = Array.from(tbody.querySelectorAll('tr.dispute-row'));
        const total = rows.length;
        const filtered = rows.filter(rowMatches);
        const pages = Math.max(1, Math.ceil(filtered.length / PER_PAGE));
        if (pageRefs[kind] > pages) pageRefs[kind] = pages;

        const start = (pageRefs[kind] - 1) * PER_PAGE;
        const visible = filtered.slice(start, start + PER_PAGE);

        rows.forEach(function (r) { setRowVisible(r, false); });
        visible.forEach(function (r) { setRowVisible(r, true); });

        // Mensaje "sin resultados" solo cuando la pestaña tiene filas pero
        // ninguna pasa el filtro (una pestaña vacía no muestra el mensaje).
        const emptyRow = document.getElementById('no-results-' + kind);
        if (emptyRow) {
            emptyRow.classList.toggle('d-none', !(total > 0 && filtered.length === 0));
        }

        // Paginación.
        const wrap = document.getElementById('pagination-wrap-' + kind);
        const ul = document.getElementById('pagination-' + kind);
        if (wrap && ul) {
            ul.innerHTML = '';
            if (pages <= 1) {
                wrap.classList.add('d-none');
            } else {
                const first = start + 1;
                const last = Math.min(start + PER_PAGE, filtered.length);
                const info = document.createElement('li');
                info.className = 'page-item disabled';
                info.innerHTML = '<span class="page-link">' + first + '–' + last + ' de ' + filtered.length + '</span>';
                ul.appendChild(info);
                for (let i = 1; i <= pages; i++) {
                    const li = document.createElement('li');
                    li.className = 'page-item' + (i === pageRefs[kind] ? ' active' : '');
                    li.innerHTML = '<a class="page-link" href="#">' + i + '</a>';
                    li.addEventListener('click', (function (p) {
                        return function (e) {
                            e.preventDefault();
                            pageRefs[kind] = p;
                            closeOpenCollapses();
                            applyPane(kind);
                        };
                    })(i));
                    ul.appendChild(li);
                }
                wrap.classList.remove('d-none');
            }
        }
    }

    function renderAllPanes() {
        closeOpenCollapses();
        applyPane('unread');
        applyPane('read');
    }

    function resetFiltersAndRender() {
        pageRefs.unread = 1;
        pageRefs.read = 1;
        renderAllPanes();
    }

    // Mueve una fila (y su desplegable) de la pestaña "No leídos" a "Leídos".
    function moveRowToRead(movId, type) {
        const row = document.querySelector(rowSel(movId, type));
        if (!row || !readTbody || !unreadTbody) return;

        row.classList.remove('row-unread');
        row.classList.add('row-read');

        const collapse = document.querySelector(collapseSel(movId, type));
        row.remove();
        readTbody.appendChild(row);
        if (collapse) {
            collapse.remove();
            readTbody.appendChild(collapse);
        }
        refreshSectionCounts();
        renderAllPanes();
    }

    // Persiste "leído" en el servidor y baja el contador del encabezado.
    function syncReadServer(movId, type) {
        if (unreadCountSpan && unreadCount > 0) {
            unreadCount--;
            unreadCountSpan.textContent = unreadCount;
        }
        if (readUrl && movId) {
            const payload = type === 'MERMA'
                ? { waste_id: parseInt(movId, 10) }
                : { movement_id: parseInt(movId, 10) };
            fetch(readUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                },
                credentials: 'same-origin',
                body: JSON.stringify(payload)
            }).then(function (resp) {
                return resp.ok ? resp.json() : null;
            }).then(function (data) {
                // Sincronizar el contador con el que calcula el servidor.
                if (data && typeof data.unread_count === 'number' && unreadCountSpan) {
                    unreadCount = data.unread_count;
                    unreadCountSpan.textContent = unreadCount;
                }
            }).catch(function () {
                /* mejor esfuerzo: si falla, el próximo polling de la
                   campana volverá a marcarla como pendiente */
            });
        }
    }

    // Marca una única respuesta como leída: mueve la fila y sincroniza.
    function markSingleRead(movId, type) {
        const row = document.querySelector(rowSel(movId, type));
        if (!row || !row.classList.contains('row-unread')) return;
        moveRowToRead(movId, type);
        syncReadServer(movId, type);
    }

    // 1. "Leer Respuesta": al hacer clic se despliega el detalle EN EL LUGAR;
    //    la fila pasa a "Leídos" recién cuando se cierra el desplegable.
    const readButtons = document.querySelectorAll('.btn-read-response');
    readButtons.forEach(button => {
        const movId = button.getAttribute('data-mov-id');
        const type = button.getAttribute('data-response-type') || 'TRASLADO';

        button.addEventListener('click', function () {
            const row = document.querySelector(rowSel(movId, type));
            if (row && row.classList.contains('row-unread')) {
                pendingRead[movId + '-' + type] = true;
            }
        });

        const collapse = document.querySelector(collapseSel(movId, type));
        if (collapse) {
            collapse.addEventListener('hidden.bs.collapse', function () {
                if (pendingRead[movId + '-' + type]) {
                    pendingRead[movId + '-' + type] = false;
                    markSingleRead(movId, type);
                }
            });
        }
    });

    // 2. "Marcar todo como leído": mueve TODAS las no leídas a "Leídos"
    //    y persiste con un solo llamado al servidor.
    if (readAllBtn && readAllUrl) {
        readAllBtn.addEventListener('click', function () {
            readAllBtn.disabled = true;
            closeOpenCollapses();

            // Mover todas las filas de forma optimista.
            const rows = unreadTbody ? Array.from(unreadTbody.querySelectorAll('tr.dispute-row')) : [];
            rows.forEach(row => {
                const movId = row.getAttribute('data-mov-id');
                const type = row.getAttribute('data-response-type') || 'TRASLADO';
                if (pendingRead[movId + '-' + type]) pendingRead[movId + '-' + type] = false;
                moveRowToRead(movId, type);
            });

            if (unreadCountSpan) {
                unreadCount = 0;
                unreadCountSpan.textContent = 0;
            }
            // Ocultar el botón: ya no queda nada por leer.
            readAllBtn.classList.add('d-none');

            fetch(readAllUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                },
                credentials: 'same-origin'
            }).then(function (resp) {
                return resp.ok ? resp.json() : null;
            }).then(function (data) {
                if (data && typeof data.unread_count === 'number' && unreadCountSpan) {
                    unreadCount = data.unread_count;
                    unreadCountSpan.textContent = unreadCount;
                }
            }).catch(function () {
                readAllBtn.disabled = false;
                readAllBtn.classList.remove('d-none');
            });
        });
    }

    // 3. Búsqueda y filtros (globales, aplican a ambas pestañas).
    let debounceTimer = null;
    function onFiltersChange() {
        searchState.text = searchInput ? searchInput.value : '';
        searchState.tipo = filterTipo ? filterTipo.value : '';
        searchState.novedad = filterNovedad ? filterNovedad.value : '';
        searchState.sede = filterSede ? filterSede.value : '';
        resetFiltersAndRender();
    }
    if (searchInput) {
        searchInput.addEventListener('input', function () {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(onFiltersChange, 180);
        });
        searchInput.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') {
                clearTimeout(debounceTimer);
                onFiltersChange();
            }
        });
    }
    if (filterTipo) filterTipo.addEventListener('change', onFiltersChange);
    if (filterNovedad) filterNovedad.addEventListener('change', onFiltersChange);
    if (filterSede) filterSede.addEventListener('change', onFiltersChange);

    // Al cambiar de pestaña, re-normar la visibilidad de filas.
    document.querySelectorAll('#responseTabs button[data-bs-toggle="tab"]').forEach(function (btn) {
        btn.addEventListener('shown.bs.tab', renderAllPanes);
    });

    // Estado inicial: aplicar paginación (filas > PER_PAGE) y filtros.
    renderAllPanes();
});