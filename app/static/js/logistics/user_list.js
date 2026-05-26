const roleMap = {
    0: 'Invitado',
    1: 'Administrador',
    2: 'Gerente',
    3: 'Subgerente',
    4: 'Operaciones',
    6: 'Gerencia',
    7: 'Finanzas'
};

let sedeList = [];
let allUsers = [];
let modalConfirmacion;
let modalTitulo;
let modalMensaje;
let modalIcono;
let btnConfirmar;
let pendingAction = null;
let pendingSelect = null;
let pendingPrevValue = null;

const iconoPeligro = `<svg width="90" height="90" viewBox="0 0 16 16" class="text-danger" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><path d="M8 15A7 7 0 1 1 8 1a7 7 0 0 1 0 14zm0 1A8 8 0 1 0 8 0a8 8 0 0 0 0 16z"/><path d="M7.002 11a1 1 0 1 1 2 0 1 1 0 0 1-2 0zM7.1 4.995a.905.905 0 1 1 1.8 0l-.35 3.507a.552.552 0 0 1-1.1 0L7.1 4.995z"/></svg>`;
const iconoExito = `<svg width="90" height="90" viewBox="0 0 16 16" class="text-success" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><path d="M16 8A8 8 0 1 1 0 8a8 8 0 0 1 16 0zm-3.97-3.03a.75.75 0 0 0-1.08.022L7.477 9.417 5.384 7.323a.75.75 0 0 0-1.06 1.06L6.97 11.03a.75.75 0 0 0 1.079-.02l3.992-4.99a.75.75 0 0 0-.01-1.05z"/></svg>`;

document.addEventListener('DOMContentLoaded', () => {
    fetchSedes();

    const modalElement = document.getElementById('modalConfirmacionSede');
    modalConfirmacion = new bootstrap.Modal(modalElement);
    modalTitulo = document.getElementById('modalTitulo');
    modalMensaje = document.getElementById('modalMensaje');
    modalIcono = document.getElementById('modalIcono');
    btnConfirmar = document.getElementById('btnConfirmar');

    btnConfirmar.addEventListener('click', async () => {
        modalConfirmacion.hide();
        if (pendingAction) {
            await pendingAction();
            pendingAction = null;
            pendingSelect = null;
        }
    });

    modalElement.addEventListener('hidden.bs.modal', () => {
        if (pendingSelect) {
            pendingSelect.value = pendingPrevValue;
            pendingSelect = null;
            pendingAction = null;
        }
    });

    document.getElementById('searchInput').addEventListener('input', filterAndRender);
    document.getElementById('statusFilter').addEventListener('change', filterAndRender);
});

async function fetchSedes() {
    try {
        const response = await fetch('/users/sedes');
        if (!response.ok) throw new Error('Ruta no encontrada');
        const jsonResponse = await response.json();
        if (jsonResponse.status === 'success') {
            sedeList = jsonResponse.data;
        }
    } catch (error) {
    } finally {
        fetchUsers();
    }
}

async function fetchUsers() {
    const errorContainer = document.getElementById('error-container');
    try {
        const response = await fetch('/users');
        if (!response.ok) throw new Error('Error de conexión');
        const jsonResponse = await response.json();
        if (jsonResponse.status === 'success') {
            allUsers = jsonResponse.data;
            filterAndRender();
        } else {
            throw new Error(jsonResponse.message);
        }
    } catch (error) {
        document.getElementById('users-tbody').innerHTML = '';
        errorContainer.style.display = 'block';
        errorContainer.textContent = error.message;
    }
}

function renderTable(users) {
    const tbody = document.getElementById('users-tbody');
    tbody.innerHTML = '';
    if (users.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="text-center py-5 text-muted">No se encontraron resultados.</td></tr>';
        return;
    }
    users.forEach(user => {
        const roleName = roleMap[user.role_id] || 'Desconocido';
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><strong>${user.name}</strong></td>
            <td>${user.email}</td>
            <td><span class="badge bg-secondary">${roleName}</span></td>
            <td>${createSedeAssignmentCell(user)}</td>
        `;
        tbody.appendChild(tr);
    });
}

function createSedeAssignmentCell(user) {
    let html = '<div class="location-select-container">';
    if (user.location_ids && user.location_ids.length > 0) {
        html += '<div class="d-flex flex-wrap gap-2 mb-2">';
        user.location_ids.forEach(locId => {
            const sede = sedeList.find(s => s.id === locId);
            let displaySedeName = `Sede #${locId}`;
            if (sede) {
                displaySedeName = sede.state ? `${sede.state} - ${sede.name}` : sede.name;
            }
            
            const safeSedeName = displaySedeName.replace(/'/g, "\\'");
            const safeUserName = user.name.replace(/'/g, "\\'");
            html += `<span class="location-badge">${displaySedeName} <i class="fas fa-times" style="cursor:pointer;" onclick="promptRemoveSede(${user.id}, ${locId}, '${safeSedeName}', '${safeUserName}')" title="Quitar sede"></i></span>`;
        });
        html += '</div>';
    }
    if (sedeList.length === 0) {
        html += `<select class="form-select sede-select form-select-sm text-muted" disabled><option>No hay sedes activas</option></select>`;
    } else {
        const unassignedSedes = sedeList.filter(s => !(user.location_ids || []).includes(s.id));
        if (unassignedSedes.length > 0) {
            const safeUserName = user.name.replace(/'/g, "\\'");
            html += `<select class="form-select sede-select form-select-sm" onchange="promptAddSede(${user.id}, '${safeUserName}', this)"><option value="" selected disabled>+ Asignar nueva sede</option>`;
            unassignedSedes.forEach(sede => {
                let displayOption = sede.state ? `${sede.state} - ${sede.name}` : sede.name;
                html += `<option value="${sede.id}">${displayOption}</option>`;
            });
            html += `</select>`;
        } else if (user.location_ids && user.location_ids.length > 0) {
            html += `<span class="text-muted small">Todas las sedes disponibles asignadas</span>`;
        }
    }
    html += '</div>';
    return html;
}

function promptAddSede(userId, userName, selectElement) {
    const sedeId = selectElement.value;
    if (!sedeId) return;
    const sedeName = selectElement.options[selectElement.selectedIndex].text;
    pendingPrevValue = "";
    pendingSelect = selectElement;
    modalIcono.innerHTML = iconoExito;
    modalTitulo.textContent = '¿Asignar Sede?';
    modalMensaje.innerHTML = `Vas a asignar la sede <b>${sedeName}</b> a <b>${userName}</b>.`;
    btnConfirmar.textContent = 'Confirmar';
    btnConfirmar.className = 'btn btn-success btn-lg w-100 mb-3 fw-bold text-white shadow-sm';
    pendingAction = async () => {
        const user = allUsers.find(u => u.id === userId);
        const newLocationIds = [...(user.location_ids || []), parseInt(sedeId)];
        await executeUpdate(userId, newLocationIds);
    };
    modalConfirmacion.show();
    selectElement.blur();
}

function promptRemoveSede(userId, sedeId, sedeName, userName) {
    modalIcono.innerHTML = iconoPeligro;
    modalTitulo.textContent = '¿Desactivar Asignación?';
    modalMensaje.innerHTML = `Estás a punto de quitarle la sede asignada <b>${sedeName}</b> a <b>${userName}</b>.`;
    btnConfirmar.textContent = 'Confirmar';
    btnConfirmar.className = 'btn btn-danger btn-lg w-100 mb-3 fw-bold text-white shadow-sm';
    pendingAction = async () => {
        const user = allUsers.find(u => u.id === userId);
        const newLocationIds = (user.location_ids || []).filter(id => id !== parseInt(sedeId));
        await executeUpdate(userId, newLocationIds);
    };
    modalConfirmacion.show();
}

async function executeUpdate(userId, locationIds) {
    const errorContainer = document.getElementById('error-container');
    errorContainer.style.display = 'none';
    try {
        const response = await fetch('/users/assign-sede', {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                user_id: userId,
                location_ids: locationIds
            })
        });
        const jsonResponse = await response.json();
        if (response.ok && jsonResponse.status === 'success') {
            const userIndex = allUsers.findIndex(u => u.id === userId);
            if (userIndex !== -1) {
                allUsers[userIndex].location_ids = locationIds;
                filterAndRender();
            }
        } else {
            throw new Error(jsonResponse.message);
        }
    } catch (error) {
        errorContainer.style.display = 'block';
        errorContainer.textContent = error.message;
        fetchUsers(); 
    }
}

function filterAndRender() {
    const term = document.getElementById('searchInput').value.toLowerCase();
    const status = document.getElementById('statusFilter').value;
    const filteredUsers = allUsers.filter(user => {
        const roleName = (roleMap[user.role_id] || 'Desconocido').toLowerCase();
        let matchesText = user.name.toLowerCase().includes(term) ||
                          user.email.toLowerCase().includes(term) ||
                          roleName.includes(term);
        if (!matchesText && user.location_ids) {
            const assignedNames = user.location_ids.map(id => {
                const s = sedeList.find(sede => sede.id === id);
                if (s) {
                    let fullName = s.state ? `${s.state} - ${s.name}` : s.name;
                    return fullName.toLowerCase();
                }
                return '';
            });
            matchesText = assignedNames.some(name => name.includes(term));
        }
        let matchesStatus = true;
        const hasSedes = user.location_ids && user.location_ids.length > 0;
        if (status === 'asignada') {
            matchesStatus = hasSedes;
        } else if (status === 'sin_asignar') {
            matchesStatus = !hasSedes;
        }
        return matchesText && matchesStatus;
    });
    renderTable(filteredUsers);
}