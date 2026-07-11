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