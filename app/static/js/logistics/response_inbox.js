document.addEventListener('DOMContentLoaded', function () {
    const cardElement = document.querySelector('.ph-card[data-user-id]');
    if (!cardElement) return;

    const userId = cardElement.getAttribute('data-user-id');
    const storageKey = `read_responses_user_${userId}`;

    // Obtener lista de IDs leídos por este usuario específico
    let readResponses = JSON.parse(localStorage.getItem(storageKey)) || [];

    const rows = document.querySelectorAll('.dispute-row');
    const unreadCountSpan = document.getElementById('unread-count');
    let unreadCount = 0;

    // 1. Evaluar el estado de cada fila al cargar la página
    rows.forEach(row => {
        const movId = row.id.replace('row-mov-', '');
        
        if (readResponses.includes(movId)) {
            row.classList.remove('row-unread');
            row.classList.add('row-read');
        } else {
            row.classList.remove('row-read');
            row.classList.add('row-unread');
            unreadCount++;
        }
    });

    // Actualizar el número del badge inicial
    if (unreadCountSpan) {
        unreadCountSpan.textContent = unreadCount;
    }

    // 2. Manejar clic en "Leer Respuesta"
    const readButtons = document.querySelectorAll('.btn-read-response');
    readButtons.forEach(button => {
        button.addEventListener('click', function () {
            const movId = this.getAttribute('data-mov-id');
            const row = document.getElementById(`row-mov-${movId}`);

            if (row && row.classList.contains('row-unread')) {
                // Cambiar estilo de la fila a blanco
                row.classList.remove('row-unread');
                row.classList.add('row-read');

                // Guardar ID en la lista de leídos
                if (!readResponses.includes(movId)) {
                    readResponses.push(movId);
                    localStorage.setItem(storageKey, JSON.stringify(readResponses));
                }

                // Decrementar contador en el badge
                if (unreadCountSpan && unreadCount > 0) {
                    unreadCount--;
                    unreadCountSpan.textContent = unreadCount;
                }
            }
        });
    });
});