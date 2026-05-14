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
            renderTable(allUsers);
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
    let select = `<select class="form-select sede-select" onchange="assignSede(${user.id}, this.value)">`;
    select += `<option value="" ${!user.location_id ? 'selected' : ''}>Sin Asignar</option>`;
    
    if (sedeList.length > 0) {
        sedeList.forEach(sede => {
            const isSelected = user.location_id == sede.id ? 'selected' : '';
            select += `<option value="${sede.id}" ${isSelected}>${sede.name}</option>`;
        });
    }
    
    select += '</select>';
    return select;
}

async function assignSede(userId, sedeId) {
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
                location_id: sedeId ? parseInt(sedeId) : null
            })
        });
        
        const jsonResponse = await response.json();
        
        if (response.ok && jsonResponse.status === 'success') {
            const userIndex = allUsers.findIndex(u => u.id === userId);
            if (userIndex !== -1) {
                allUsers[userIndex].location_id = sedeId ? parseInt(sedeId) : null;
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

document.getElementById('searchInput').addEventListener('input', (e) => {
    const term = e.target.value.toLowerCase();
    
    const filteredUsers = allUsers.filter(user => {
        const roleName = (roleMap[user.role_id] || 'Desconocido').toLowerCase();
        
        let locationName = 'sin asignar';
        if (user.location_id) {
            const sede = sedeList.find(s => s.id == user.location_id);
            if (sede) locationName = sede.name.toLowerCase();
        }

        return user.name.toLowerCase().includes(term) ||
               user.email.toLowerCase().includes(term) ||
               roleName.includes(term) ||
               locationName.includes(term);
    });
    
    renderTable(filteredUsers);
});