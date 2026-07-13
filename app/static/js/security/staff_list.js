document.addEventListener('DOMContentLoaded', function() {
    // ---- LÓGICA DE ACTIVACIÓN MASIVA POR SEDE ----
const locationFilterEl = document.getElementById('locationFilter');
const bulkActivateBtn = document.getElementById('bulkActivateBtn');

if (locationFilterEl && bulkActivateBtn) {
    // Mostrar/ocultar el botón según la sede seleccionada
    locationFilterEl.addEventListener('change', function() {
        if (this.value !== 'all') {
            bulkActivateBtn.classList.remove('d-none');
        } else {
            bulkActivateBtn.classList.add('d-none');
        }
    });

    // Acción al presionar el botón masivo
    bulkActivateBtn.addEventListener('click', function() {
        const locationId = locationFilterEl.value;
        const locationName = locationFilterEl.options[locationFilterEl.selectedIndex].text;

        showConfirmModal(
            "Activación Masiva",
            `¿Está seguro de que desea ACTIVAR a todos los usuarios pertenecientes a la sede "${locationName}"?`,
            function() {
                // Si dice SÍ, disparamos el fetch al backend
                fetch(`/staff/bulk-activate/${locationId}`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'}
                })
                .then(r => r.json())
                .then(d => {
                    if (d.success) {
                        location.reload(); // Recargamos para ver los cambios
                    } else {
                        showAlertModal("Error", d.message || "No se pudo realizar la activación masiva.");
                    }
                })
                .catch(err => {
                    showAlertModal("Error Crítico", "Problema de conexión con el servidor.");
                });
            },
            function() {
                console.log("Acción masiva cancelada.");
            }
        );
    });
}
    // ---- LÓGICA DE BÚSQUEDA Y FILTRADO MULTI-CRITERIO EN TIEMPO REAL ----
    const searchInput = document.getElementById('tableSearch');
    const statusFilter = document.getElementById('statusFilter');
    const roleFilter = document.getElementById('roleFilter');
    const locationFilter = document.getElementById('locationFilter');

    if (searchInput && statusFilter && roleFilter && locationFilter) {
        searchInput.addEventListener('input', executeTableFilter);
        statusFilter.addEventListener('change', executeTableFilter);
        roleFilter.addEventListener('change', executeTableFilter);
        locationFilter.addEventListener('change', executeTableFilter);
    }

    function executeTableFilter() {
        const query = searchInput.value.toLowerCase().trim();
        const selectedStatus = statusFilter.value;     // 'all', 'active', 'inactive'
        const selectedRole = roleFilter.value;         // 'all' o ID de rol
        const selectedLocation = locationFilter.value; // 'all' o ID de sede
        
        // AJUSTE: Excluimos la fila de "No resultados" para evitar errores de lectura de nodos
        const rows = document.querySelectorAll('#staffTable tbody tr:not(#noResultsRow)');
        let visibleRowsCount = 0;

        rows.forEach(row => {
            // Extraer textos y atributos de datos de la fila
            const nameText = row.querySelector('.user-name-text').textContent.toLowerCase();
            const emailText = row.querySelector('.user-email-text').textContent.toLowerCase();
            const rowStatus = row.getAttribute('data-status'); 
            const rowRole = row.getAttribute('data-role');
            
            // Convertimos la cadena de sedes "1,2,3," en un array limpio de JS
            const rowLocationsStr = row.getAttribute('data-locations') || '';
            const rowLocationsArr = rowLocationsStr.split(',').filter(Boolean);

            // Evaluar cumplimiento de los 4 criterios en cascada
            const matchesSearch = nameText.includes(query) || emailText.includes(query);
            const matchesStatus = (selectedStatus === 'all') || (rowStatus === selectedStatus);
            const matchesRole = (selectedRole === 'all') || (rowRole === selectedRole);
            const matchesLocation = (selectedLocation === 'all') || rowLocationsArr.includes(selectedLocation);

            // Mostrar u ocultar la fila (Todas las condiciones deben ser verdaderas)
            if (matchesSearch && matchesStatus && matchesRole && matchesLocation) {
                row.style.setProperty('display', '', 'important');
                visibleRowsCount++; // Incrementamos si la fila pasa los filtros
            } else {
                row.style.setProperty('display', 'none', 'important');
            }
        });

        // CONTROL DE VISIBILIDAD DE LA LUPA
        const noResultsRow = document.getElementById('noResultsRow');
        if (noResultsRow) {
            if (visibleRowsCount === 0) {
                noResultsRow.style.setProperty('display', '', 'important');
            } else {
                noResultsRow.style.setProperty('display', 'none', 'important');
            }
        }
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
            const isChecked = this.checked;

            const message = isChecked 
                ? "¿Está seguro de activar a este usuario?" 
                : "¿Está seguro de desactivar a este usuario?";

            showConfirmModal(
                "Confirmar Estado", 
                message, 
                function() {
                    executeToggleStatus(userId, isChecked);
                }, 
                function() {
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
    const newBtnYes = btnYes.cloneNode(true);
    btnYes.parentNode.replaceChild(newBtnYes, btnYes);
    
    const modalInstance = bootstrap.Modal.getOrCreateInstance(modalEl);
    let confirmed = false;
    
    newBtnYes.addEventListener('click', function() {
        confirmed = true;
        modalInstance.hide();
        if (onYes) onYes();
    });
    
    modalEl.addEventListener('hidden.bs.modal', function handler() {
        if (!confirmed && onNo) {
            onNo(); 
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

    if (isSeparatedFromLocations && selectedLocations.length === 0) {
        data.activo = false;
    }

    showConfirmModal(
        "Confirmar Guardado",
        "¿Está seguro de guardar los datos editados?",
        function() {
            const editModalEl = document.getElementById('editModal');
            bootstrap.Modal.getOrCreateInstance(editModalEl).hide();

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