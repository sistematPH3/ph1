// admin_table_mobile.js - Control Unificado de Búsqueda para Gestión de Permisos

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