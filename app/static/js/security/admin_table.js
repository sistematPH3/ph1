// Control Unificado de Búsqueda para Gestión de Permisos y Utilidades de Formularios

function filterTable() {
    const searchInput = document.getElementById("userInput");
    if (!searchInput) return;

    const query = searchInput.value.toLowerCase().trim();
    
    // 1. FILTRADO PARA ESCRITORIO (Filas de la tabla)
    const tableRows = document.querySelectorAll("#userTableBody tr");
    let visibleRowsCount = 0;

    tableRows.forEach(row => {
        // Obtenemos el texto del nombre y correo del colaborador
        const nameText = row.querySelector(".user-name-text") ? row.querySelector(".user-name-text").textContent.toLowerCase() : "";
        const emailText = row.querySelector(".user-email-text") ? row.querySelector(".user-email-text").textContent.toLowerCase() : "";
        
        if (nameText.includes(query) || emailText.includes(query)) {
            row.style.setProperty("display", "", "important");
            visibleRowsCount++;
        } else {
            row.style.setProperty("display", "none", "important");
        }
    });

    // 2. FILTRADO PARA MÓVIL (Tarjetas móviles)
    const mobileCards = document.querySelectorAll("#userCardsContainer .mobile-user-card");
    let visibleCardsCount = 0;

    mobileCards.forEach(card => {
        // Obtenemos el nombre y correo de la tarjeta móvil
        const nameText = card.querySelector(".target-name-mobile") ? card.querySelector(".target-name-mobile").textContent.toLowerCase() : "";
        const emailText = card.querySelector(".target-email-mobile") ? card.querySelector(".target-email-mobile").textContent.toLowerCase() : "";

        if (nameText.includes(query) || emailText.includes(query)) {
            card.style.setProperty("display", "block", "important");
            visibleCardsCount++;
        } else {
            card.style.setProperty("display", "none", "important");
        }
    });

    // 3. CONTROL DE MENSAJE "SIN RESULTADOS"
    const noSearchResults = document.getElementById("noSearchResults");
    if (noSearchResults) {
        const isMobile = window.innerWidth < 768;
        
        if (isMobile) {
            if (mobileCards.length > 0 && visibleCardsCount === 0) {
                noSearchResults.classList.remove("d-none");
            } else {
                noSearchResults.classList.add("d-none");
            }
        } else {
            if (tableRows.length > 0 && visibleRowsCount === 0) {
                noSearchResults.classList.remove("d-none");
            } else {
                noSearchResults.classList.add("d-none");
            }
        }
    }
}

// Aseguramos que si cambia el tamaño de pantalla se reevalúe el aviso de resultados
window.addEventListener("resize", filterTable);

function toggleSort() {
    let currentUrl = new URL(window.location.href);
    let order = currentUrl.searchParams.get("sort") === "asc" ? "desc" : "asc";
    currentUrl.searchParams.set("sort", order);
    window.location.href = currentUrl.href;
}

function toggleSedesContainer(rolSelect) {
    const formulario = rolSelect.closest('form');
    const locationContainer = formulario.querySelector('.location-container-box');
    
    if (rolSelect.value === "1") { 
        locationContainer.style.display = 'none';
        
        const checkboxes = locationContainer.querySelectorAll('input[name="location_ids"]');
        checkboxes.forEach(cb => cb.checked = false);
    } else {
        locationContainer.style.display = 'block';
    }
}

function confirmReject(userId) {
    Swal.fire({
        title: '¿Denegar acceso?',
        text: "El usuario será eliminado de la lista de forma permanente.",
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#e31937',
        cancelButtonColor: '#6c757d',
        confirmButtonText: 'Sí, rechazar',
        cancelButtonText: 'Cancelar',
        customClass: {
            popup: 'rounded-4'
        }
    }).then((result) => {
        if (result.isConfirmed) {
            document.getElementById('rejectForm_' + userId).submit();
        }
    });
}

function validarFormularioAprobacion(event, formulario) {
    event.preventDefault();
    
    const rolSelect = formulario.querySelector('select[name="role_id"]');
    const checkboxes = formulario.querySelectorAll('input[name="location_ids"]');
    
    let tieneSede = false;
    for (let i = 0; i < checkboxes.length; i++) {
        if (checkboxes[i].checked) {
            tieneSede = true;
            break;
        }
    }

    if (!rolSelect || rolSelect.value === "") {
        Swal.fire({
            icon: 'warning',
            title: 'Rol no seleccionado',
            text: 'Debes asignar un cargo o rol al usuario antes de confirmar.',
            confirmButtonColor: '#e31937',
            customClass: {
                popup: 'rounded-4'
            }
        });
        return;
    }

    if (rolSelect.value !== "1" && !tieneSede) {
        Swal.fire({
            icon: 'warning',
            title: 'Sede Obligatoria',
            text: 'Recuerda que debes asignar al menos una sede operativa para este rol.',
            confirmButtonColor: '#e31937',
            customClass: {
                popup: 'rounded-4'
            }
        });
        return;
    }

    formulario.submit();
}