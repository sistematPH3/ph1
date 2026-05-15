const roleMap = {
    0: 'Invitado',
    1: 'Administrador',
    2: 'Gerente',
    3: 'Subgerente',
    4: 'Operaciones',
    5: 'Auditoría',
    6: 'Gerencia',
    7: 'Finanzas'
};

let sedeList = [];
let allUsers = [];

document.addEventListener('DOMContentLoaded', fetchSedes);

async function fetchSedes() {
    try {
        const response = await fetch('/users/sedes');
        if (!response.ok) throw new Error('Ruta no encontrada');
        const jsonResponse = await response.json();
        if (jsonResponse.status === 'success') {
            sedeList = jsonResponse.data;
        }
    } catch (error) {
        console.warn("Error cargando sedes:", error);
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
            const sedeName = sede ? sede.name : `Sede #${locId} (Inactiva)`;
            // Aquí está la etiqueta roja con la "X" para quitar al usuario de esa sede
            html += `<span class="location-badge">${sedeName} <i class="fas fa-times" style="cursor:pointer;" onclick="removeSede(${user.id}, ${locId})" title="Quitar sede"></i></span>`;
        });
        html += '</div>';
    }

    if (sedeList.length === 0) {
        html += `<select class="form-select sede-select form-select-sm text-muted" disabled>
                    <option>No hay sedes activas</option>
                 </select>`;
    } else {
        const unassignedSedes = sedeList.filter(s => !(user.location_ids || []).includes(s.id));

        if (unassignedSedes.length > 0) {
            html += `<select class="form-select sede-select form-select-sm" onchange="addSede(${user.id}, this.value)">
                        <option value="" selected disabled>+ Asignar nueva sede</option>`;
            unassignedSedes.forEach(sede => {
                html += `<option value="${sede.id}">${sede.name}</option>`;
            });
            html += `</select>`;
        } else if (user.location_ids && user.location_ids.length > 0) {
            html += `<span class="text-muted small">Todas las sedes disponibles asignadas</span>`;
        }
    }

    html += '</div>';
    return html;
}

async function addSede(userId, sedeId) {
    if (!sedeId) return;
    const user = allUsers.find(u => u.id === userId);
    const newLocationIds = [...(user.location_ids || []), parseInt(sedeId)];
    await executeUpdate(userId, newLocationIds);
}

async function removeSede(userId, sedeId) {
    const user = allUsers.find(u => u.id === userId);
    const newLocationIds = (user.location_ids || []).filter(id => id !== parseInt(sedeId));
    await executeUpdate(userId, newLocationIds);
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
                return s ? s.name.toLowerCase() : '';
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

document.getElementById('searchInput').addEventListener('input', filterAndRender);
document.getElementById('statusFilter').addEventListener('change', filterAndRender);