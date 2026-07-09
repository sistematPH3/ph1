/**
 * Lógica para el panel administrativo (Listados y Aprobaciones)
 */

function filterTable() {
    let input = document.getElementById("userInput");
    let table = document.getElementById("userTable");
    if (!input || !table) return;

    let filter = input.value.toLowerCase();
    let tr = table.getElementsByTagName("tr");

    for (let i = 1; i < tr.length; i++) {
        let tdName = tr[i].getElementsByTagName("td")[0];
        let tdEmail = tr[i].getElementsByTagName("td")[1];
        if (tdName || tdEmail) {
            let txtValueName = tdName.textContent || tdName.innerText;
            let txtValueEmail = tdEmail.textContent || tdEmail.innerText;
            if (txtValueName.toLowerCase().indexOf(filter) > -1 || txtValueEmail.toLowerCase().indexOf(filter) > -1) {
                tr[i].style.display = "";
            } else {
                tr[i].style.display = "none";
            }
        }
    }
}

function toggleSort() {
    let currentUrl = new URL(window.location.href);
    let order = currentUrl.searchParams.get("sort") === "asc" ? "desc" : "asc";
    currentUrl.searchParams.set("sort", order);
    window.location.href = currentUrl.href;
}

function toggleSedesContainer(rolSelect) {
    const usuarioId = rolSelect.getAttribute('data-user-id');
    const locationContainer = document.getElementById('location_container_' + usuarioId);
    
    if (rolSelect.value === "1") { // ID 1 es 'Administrador'
        locationContainer.style.display = 'none';
        
        // Desmarcamos correctamente los Checkboxes/Pills por si acaso seleccionó alguno antes
        const checkboxes = locationContainer.querySelectorAll('input[name="location_ids"]');
        checkboxes.forEach(cb => cb.checked = false);
    } else {
        locationContainer.style.display = 'block';
    }
}

function validarFormularioAprobacion(formulario) {
    const usuarioId = formulario.getAttribute('data-id'); 
    const rolSelect = formulario.querySelector('#role_id_' + usuarioId);
    const errorMsgSedes = formulario.querySelector('#error_msg_sedes_' + usuarioId);
    const errorMsgGeneral = formulario.querySelector('#error_msg_general_' + usuarioId);
    
    // Captura los Checkboxes activos dentro del contenedor de píldoras
    const checkboxesMarcados = formulario.querySelectorAll('input[name="location_ids"]:checked');
    
    let esValido = true;

    if (rolSelect) rolSelect.classList.remove('is-invalid');
    if (errorMsgSedes) errorMsgSedes.classList.add('d-none');
    if (errorMsgGeneral) errorMsgGeneral.classList.add('d-none');

    // Validar el cargo/rol
    if (rolSelect && rolSelect.value === "") {
        rolSelect.classList.add('is-invalid');
        esValido = false;
    }

    // Validar sedes si NO es Administrador
    if (rolSelect && rolSelect.value !== "1") {
        if (checkboxesMarcados.length === 0) {
            if (errorMsgSedes) errorMsgSedes.classList.remove('d-none');
            esValido = false;
        }
    }

    if (!esValido) {
        if (errorMsgGeneral) errorMsgGeneral.classList.remove('d-none');
        return false; 
    }

    return true; 
}