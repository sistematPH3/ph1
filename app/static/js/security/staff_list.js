document.addEventListener('DOMContentLoaded', function() {
    // ---- LÓGICA DE BÚSQUEDA Y FILTRADO EN TIEMPO REAL ----
    const searchInput = document.getElementById('tableSearch');
    const statusFilter = document.getElementById('statusFilter');

    if (searchInput && statusFilter) {
        searchInput.addEventListener('input', executeTableFilter);
        statusFilter.addEventListener('change', executeTableFilter);
    }

    function executeTableFilter() {
        const query = searchInput.value.toLowerCase().trim();
        const selectedStatus = statusFilter.value; // 'all', 'active', 'inactive'
        const rows = document.querySelectorAll('#staffTable tbody tr');

        rows.forEach(row => {
            // Extraer el texto de las columnas de interés
            const nameText = row.querySelector('.user-name-text').textContent.toLowerCase();
            const emailText = row.querySelector('.user-email-text').textContent.toLowerCase();
            const rowStatus = row.getAttribute('data-status'); // 'active' o 'inactive'

            // Comprobar condiciones
            const matchesSearch = nameText.includes(query) || emailText.includes(query);
            const matchesStatus = (selectedStatus === 'all') || (rowStatus === selectedStatus);

            // Mostrar u ocultar la fila según corresponda
            if (matchesSearch && matchesStatus) {
                row.style.setProperty('display', '', 'important');
            } else {
                row.style.setProperty('display', 'none', 'important');
            }
        });
    }

    // ---- INTERACTIVIDAD DE LAS PÍLDORAS DE SEDES ----
    document.querySelectorAll('.ph-interactive-pill').forEach(pill => {
        pill.addEventListener('click', function() {
            const idSede = this.getAttribute('data-id');
            const hiddenSelect = document.getElementById('editLocations');
            if (!hiddenSelect) return;

            const option = hiddenSelect.querySelector(`option[value="${idSede}"]`);
            if (option) {
                // Alternar el estado de selección en el select oculto (true / false)
                option.selected = !option.selected;
                // Alternar la clase visual (activa el fondo rojo y la X)
                this.classList.toggle('selected', option.selected);
            }
        });
    });

    // Escuchar el cambio en el Rol para ocultar/mostrar sedes
    const editRole = document.getElementById('editRole');
    if (editRole) {
        editRole.addEventListener('change', checkRoleVisibility);
    }

    // Escuchar los botones de editar (Se añade el envío de las sedes vía dataset)
    document.querySelectorAll('.edit-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            openEditModal(
                this.dataset.id, 
                this.dataset.name, 
                this.dataset.email, 
                this.dataset.role, 
                this.dataset.locations
            );
        });
    });

    // Escuchar los switches de estado con INTERCEPCIÓN DE CONFIRMACIÓN
    document.querySelectorAll('.status-toggle').forEach(sw => {
        sw.addEventListener('change', function() {
            const userId = this.dataset.id;
            const isChecked = this.checked; // Destino deseado (true si intenta activar, false si intenta desactivar)

            // Definimos el mensaje personalizado según el estado del switch
            const message = isChecked 
                ? "¿Está seguro de activar a este usuario?" 
                : "¿Está seguro de desactivar a este usuario?";

            // Abrimos el modal de confirmación pasándole las acciones correspondientes
            showConfirmModal(
                "Confirmar Estado", 
                message, 
                function() {
                    // Acción si hace clic en SÍ: Ejecutar la petición al servidor
                    executeToggleStatus(userId, isChecked);
                }, 
                function() {
                    // Acción si hace clic en NO o cierra el modal: Revertir el switch en pantalla
                    const switchEl = document.querySelector(`.status-toggle[data-id="${userId}"]`);
                    if (switchEl) switchEl.checked = !isChecked;
                }
            );
        });
    });

    const saveBtn = document.getElementById('saveBtn');
    if (saveBtn) {
        saveBtn.addEventListener('click', saveChanges);
    }
});

// ---- FUNCIÓN GLOBAL: LANZAR ALERTA SIMPLE (OK) ----
function showAlertModal(title, message, callbackOnClose) {
    const modalEl = document.getElementById('alertModal');
    if (!modalEl) return;

    document.getElementById('alertModalTitle').textContent = title;
    document.getElementById('alertModalMessage').textContent = message;
    
    // Uso de getOrCreateInstance para evitar fugas de memoria y bloqueos de capas oscuras
    const modalInstance = bootstrap.Modal.getOrCreateInstance(modalEl);
    
    if (callbackOnClose) {
        modalEl.addEventListener('hidden.bs.modal', function handler() {
            callbackOnClose();
            modalEl.removeEventListener('hidden.bs.modal', handler); 
        });
    }
    
    modalInstance.show();
}

// ---- FUNCIÓN GLOBAL: LANZAR CONFIRMACIÓN (SÍ / NO) ----
function showConfirmModal(title, message, onYes, onNo) {
    const modalEl = document.getElementById('confirmModal');
    if (!modalEl) return;

    document.getElementById('confirmModalTitle').textContent = title;
    document.getElementById('confirmModalMessage').textContent = message;
    
    const btnYes = document.getElementById('confirmBtnYes');
    
    // Clonamos el botón "Sí" para limpiar listeners viejos acumulados de otras acciones anteriores
    const newBtnYes = btnYes.cloneNode(true);
    btnYes.parentNode.replaceChild(newBtnYes, btnYes);
    
    const modalInstance = bootstrap.Modal.getOrCreateInstance(modalEl);
    let confirmed = false;
    
    // Evento al presionar Sí
    newBtnYes.addEventListener('click', function() {
        confirmed = true;
        modalInstance.hide();
        if (onYes) onYes();
    });
    
    // Evento al cerrar el modal por cualquier vía (Botón No, clic afuera o tecla ESC)
    modalEl.addEventListener('hidden.bs.modal', function handler() {
        if (!confirmed && onNo) {
            onNo(); // Revierte el switch o cancela la acción si no confirmó con un SÍ
        }
        modalEl.removeEventListener('hidden.bs.modal', handler);
    }, { once: true });
    
    modalInstance.show();
}

// Abre el modal de edición y sincroniza tanto los inputs como el estado visual de las sedes
function openEditModal(id, name, email, roleId, locationsStr) {
    document.getElementById('editUserId').value = id;
    document.getElementById('editEmail').value = email;
    document.getElementById('editRole').value = roleId;

    const hiddenSelect = document.getElementById('editLocations');
    if (hiddenSelect) {
        Array.from(hiddenSelect.options).forEach(opt => opt.selected = false);
        
        if (locationsStr) {
            const idsArray = locationsStr.split(',').filter(Boolean);
            idsArray.forEach(idSede => {
                const option = hiddenSelect.querySelector(`option[value="${idSede}"]`);
                if (option) option.selected = true;
            });
        }
        syncLocationPills();
    }

    checkRoleVisibility();
    bootstrap.Modal.getOrCreateInstance(document.getElementById('editModal')).show();
}

function syncLocationPills() {
    const hiddenSelect = document.getElementById('editLocations');
    if (!hiddenSelect) return;

    document.querySelectorAll('.ph-interactive-pill').forEach(pill => {
        const idSede = pill.getAttribute('data-id');
        const option = hiddenSelect.querySelector(`option[value="${idSede}"]`);
        
        if (option && option.selected) {
            pill.classList.add('selected'); 
        } else {
            pill.classList.remove('selected'); 
        }
    });
}

function checkRoleVisibility() {
    const roleSelect = document.getElementById('editRole');
    const locationsContainer = document.getElementById('locationsContainer');
    const selectedText = roleSelect.options[roleSelect.selectedIndex].text.toLowerCase();
    locationsContainer.style.display = selectedText.includes('admin') ? 'none' : 'block';
}

// Intercepta el guardado para pedir confirmación antes de disparar el Fetch
function saveChanges() {
    const userId = document.getElementById('editUserId').value;
    const roleSelect = document.getElementById('editRole');
    const selectedText = roleSelect.options[roleSelect.selectedIndex].text.toLowerCase();
    
    const isSeparatedFromLocations = !selectedText.includes('admin');
    const selectedLocations = isSeparatedFromLocations 
        ? Array.from(document.getElementById('editLocations').selectedOptions).map(o => o.value)
        : [];

    const data = {
        email: document.getElementById('editEmail').value,
        role_id: roleSelect.value,
        locations: selectedLocations
    };

    // REGLA DE NEGOCIO VISUAL: Si no es admin y quitó todas las sedes, mandamos el flag de desactivación automática
    if (isSeparatedFromLocations && selectedLocations.length === 0) {
        data.activo = false;
    }

    // Pedimos confirmación elegante al usuario usando el mismo modal estilizado
    showConfirmModal(
        "Confirmar Guardado",
        "¿Está seguro de guardar los datos editados?",
        function() {
            // Si hace clic en "Sí", cerramos primero el modal de edición para limpiar la pantalla de backdrops
            const editModalEl = document.getElementById('editModal');
            bootstrap.Modal.getOrCreateInstance(editModalEl).hide();

            // Se procesa el envío seguro al servidor
            fetch(`/staff/editar/${userId}`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(data)
            })
            .then(r => r.json())
            .then(d => {
                if (d.success) {
                    location.reload();
                } else {
                    showAlertModal("Error de Guardado", d.message || "No se pudieron aplicar los cambios.", function() {
                        // Si falla, volvemos a mostrar el modal de edición para que corrija
                        bootstrap.Modal.getOrCreateInstance(editModalEl).show();
                    });
                }
            })
            .catch(err => {
                showAlertModal("Error Crítico", "Ocurrió un problema de red al procesar la solicitud.");
            });
        }
    );
}

// Envío real al Backend una vez que el usuario confirma con "Sí" el switch de estado
function executeToggleStatus(userId, isChecked) {
    fetch(`/staff/toggle-status/${userId}`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ activo: isChecked })
    })
    .then(r => r.json())
    .then(d => {
        if (d.success) {
            location.reload();
        } else {
            // Si el backend lo rechaza (ej. intentar activar un usuario sin sedes asignadas)
            showAlertModal(
                "Sede Obligatoria", 
                d.message || "Recuerda que debes asignar al menos una sede operativa para este rol.",
                function() {
                    const switchEl = document.querySelector(`.status-toggle[data-id="${userId}"]`);
                    if (switchEl) switchEl.checked = !isChecked;
                }
            );
        }
    })
    .catch(err => {
        const switchEl = document.querySelector(`.status-toggle[data-id="${userId}"]`);
        if (switchEl) switchEl.checked = !isChecked;
        showAlertModal("Error", "No se pudo cambiar el estado debido a un problema con el servidor.");
    });
}