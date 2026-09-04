/* =========================================================
   MIS MERMAS PENDIENTES
   -----------------------------------------------------------------
   1) Búsqueda instantánea sobre las filas de la tabla.
   2) Botón Cancelar: abre un modal de confirmación con motivo
      obligatorio y llama a POST /api/waste/merma/<id>/cancel.
   ========================================================= */

document.addEventListener("DOMContentLoaded", function () {
    const searchInput = document.getElementById("searchMermaList");

    // ---------- 1) Búsqueda sobre las filas ----------
    if (searchInput) {
        searchInput.addEventListener("input", function () {
            const q = (this.value || "").toLowerCase().trim();
            document.querySelectorAll("#mermaPendingTable .searchable-row").forEach(function (row) {
                const haystack = (row.textContent || "").toLowerCase();
                row.style.display = haystack.indexOf(q) !== -1 ? "" : "none";
            });
        });
    }

    // ---------- 2) Cancelación con confirmación ----------
    const cancelModalEl = document.getElementById("cancelMermaModal");
    if (!cancelModalEl) return;
    const cancelModal = new bootstrap.Modal(cancelModalEl);
    const wasteIdInput = document.getElementById("cancelWasteId");
    const wasteIdText = document.getElementById("cancelWasteIdText");
    const reasonInput = document.getElementById("cancelReason");
    const reasonError = document.getElementById("cancelReasonError");
    const btnConfirm = document.getElementById("btnConfirmCancelMerma");

    document.querySelectorAll(".btn-cancel-merma").forEach(function (btn) {
        btn.addEventListener("click", function () {
            const wasteId = btn.getAttribute("data-id");
            wasteIdInput.value = wasteId;
            wasteIdText.textContent = "#".concat(wasteId);
            reasonInput.value = "";
            reasonInput.classList.remove("is-invalid");
            reasonError.style.display = "none";
            cancelModal.show();
        });
    });

    btnConfirm.addEventListener("click", async function () {
        const wasteId = wasteIdInput.value;
        const reason = (reasonInput.value || "").trim();

        if (reason.length < 10) {
            reasonInput.classList.add("is-invalid");
            reasonError.style.display = "block";
            reasonError.textContent = "El motivo de cancelación debe tener al menos 10 caracteres.";
            return;
        }
        reasonInput.classList.remove("is-invalid");
        reasonError.style.display = "none";

        btnConfirm.disabled = true;
        btnConfirm.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Cancelando...';

        try {
            const res = await fetch("/api/waste/merma/" + wasteId + "/cancel", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ reason: reason })
            });
            const result = await res.json();

            if (result.success) {
                cancelModal.hide();
                removeRow(wasteId);
                showAlert(
                    "success",
                    '<i class="bi bi-check-circle-fill me-2"></i><strong>Merma #' + wasteId + ' cancelada.</strong>' +
                    ' Se registró en la Auditoría de Inventario. El stock no se descontó.',
                    true
                );
            } else {
                reasonInput.classList.add("is-invalid");
                reasonError.style.display = "block";
                reasonError.textContent = result.message || (
                    (result.errors && result.errors.reason) ?
                    result.errors.reason : "No se pudo cancelar la merma."
                );
            }
        } catch (err) {
            reasonInput.classList.add("is-invalid");
            reasonError.style.display = "block";
            reasonError.textContent = "No se pudo comunicar con el servidor. Intente de nuevo.";
        } finally {
            btnConfirm.disabled = false;
            btnConfirm.innerHTML = '<i class="bi bi-check2-circle me-1"></i>Sí, cancelar merma';
        }
    });

    function removeRow(wasteId) {
        const row = document.querySelector('.btn-cancel-merma[data-id="' + wasteId + '"]');
        const tr = row ? row.closest("tr") : null;
        if (tr) tr.remove();

        const rows = document.querySelectorAll("#mermaPendingTable .searchable-row").length;
        const badge = document.getElementById("pendingCountBadge");
        if (badge) {
            const next = Math.max(0, rows);
            badge.innerHTML = '<i class="bi bi-hourglass-split me-1"></i> Pendientes: ' + next;
        }

        if (rows === 0) {
            const tbody = document.querySelector("#mermaPendingTable tbody");
            if (tbody && !document.getElementById("emptyRow")) {
                tbody.innerHTML =
                    '<tr id="emptyRow"><td colspan="8" class="text-center text-muted py-5">' +
                    '<div class="waste-empty-state"><i class="bi bi-inbox"></i>' +
                    'No hay mermas pendientes de respuesta.</div></td></tr>';
            }
        }
    }

    function showAlert(type, html, autoHide) {
        const container = document.getElementById("cancelAlerts");
        if (!container) return;
        const alertEl = document.createElement("div");
        alertEl.className = "alert alert-" + type + " d-flex align-items-center border-0";
        alertEl.innerHTML = html;
        container.innerHTML = "";
        container.appendChild(alertEl);
        if (autoHide) {
            setTimeout(function () {
                alertEl.style.transition = "opacity .4s ease";
                alertEl.style.opacity = "0";
                setTimeout(function () { alertEl.remove(); }, 400);
            }, 5000);
        }
    }
});