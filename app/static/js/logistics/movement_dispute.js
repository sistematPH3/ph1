function formatRegistrationDates() {
    document.querySelectorAll('.js-local-date').forEach(el => {
        const utcStr = el.getAttribute('data-utc');
        if (utcStr) {
            const date = new Date(utcStr);
            if (!isNaN(date)) {
                el.textContent = date.toLocaleDateString('es-ES', {
                    day: '2-digit',
                    month: '2-digit',
                    year: 'numeric'
                });
            }
        }
    });

    document.querySelectorAll('.js-local-time').forEach(el => {
        const utcStr = el.getAttribute('data-utc');
        if (utcStr) {
            const date = new Date(utcStr);
            if (!isNaN(date)) {
                el.textContent = date.toLocaleTimeString('es-ES', {
                    hour: '2-digit',
                    minute: '2-digit',
                    hour12: true
                });
            }
        }
    });

    document.querySelectorAll('.js-local-full').forEach(el => {
        const utcStr = el.getAttribute('data-utc');
        if (utcStr) {
            const date = new Date(utcStr);
            if (!isNaN(date)) {
                const dateStr = date.toLocaleDateString('es-ES', {
                    day: '2-digit',
                    month: '2-digit',
                    year: 'numeric'
                });
                const timeStr = date.toLocaleTimeString('es-ES', {
                    hour: '2-digit',
                    minute: '2-digit',
                    hour12: true
                });
                el.textContent = `${dateStr} ${timeStr}`;
            }
        }
    });
}

document.addEventListener("DOMContentLoaded", function () {
    formatRegistrationDates();

    const itemsPerPage = 10;
    let currentPage = 1;

    const searchInput = document.getElementById("searchDisputeInput");
    const statusSelect = document.getElementById("statusFilterSelect");
    const locationSelect = document.getElementById("locationFilterSelect");
    const noResultsRow = document.getElementById("noResultsRow");

    const btnPrev = document.getElementById("btnPrevPage");
    const btnNext = document.getElementById("btnNextPage");
    const pageText = document.getElementById("currentPageText");
    const pageInfo = document.getElementById("paginationInfo");

    function getFilteredIndices() {
        const desktopRows = Array.from(document.querySelectorAll(".dispute-row"));
        const searchTerm = searchInput ? searchInput.value.toLowerCase().trim() : "";
        const selectedStatus = statusSelect ? statusSelect.value.trim() : "";

        let selectedLocationText = "";
        if (locationSelect && locationSelect.selectedIndex > 0) {
            selectedLocationText = locationSelect.options[locationSelect.selectedIndex].text.toLowerCase().trim();
        }

        let matchingIndices = [];

        desktopRows.forEach((row, index) => {
            const mobileCard = document.querySelectorAll(".dispute-row-mobile")[index];
            const combinedText = (row.textContent + " " + (mobileCard ? mobileCard.textContent : "")).toLowerCase();

            const matchesSearch = searchTerm === "" || combinedText.includes(searchTerm);

            let matchesStatus = true;
            if (selectedStatus !== "") {
                const selectedStatusText = statusSelect.options[statusSelect.selectedIndex].text.toLowerCase();
                matchesStatus = combinedText.includes(selectedStatusText) || combinedText.includes(selectedStatus.toLowerCase());
            }

            const matchesLocation = selectedLocationText === "" || combinedText.includes(selectedLocationText);

            if (matchesSearch && matchesStatus && matchesLocation) {
                matchingIndices.push(index);
            }
        });

        return matchingIndices;
    }

    function renderPage() {
        const desktopRows = document.querySelectorAll(".dispute-row");
        const detailRows = document.querySelectorAll(".detail-collapse-row");
        const mobileCards = document.querySelectorAll(".dispute-row-mobile");

        desktopRows.forEach(r => r.style.setProperty("display", "none", "important"));
        detailRows.forEach(d => {
            d.style.setProperty("display", "none", "important");
            const collapseDiv = d.querySelector('.collapse');
            if (collapseDiv && collapseDiv.classList.contains('show')) {
                collapseDiv.classList.remove('show');
            }
        });
        mobileCards.forEach(m => m.style.setProperty("display", "none", "important"));

        const filteredIndices = getFilteredIndices();
        const totalItems = filteredIndices.length;
        const totalPages = Math.ceil(totalItems / itemsPerPage) || 1;

        if (currentPage > totalPages) currentPage = totalPages;
        if (currentPage < 1) currentPage = 1;

        const start = (currentPage - 1) * itemsPerPage;
        const end = start + itemsPerPage;
        const pageIndices = filteredIndices.slice(start, end);

        const isMobile = window.innerWidth < 768;

        pageIndices.forEach(index => {
            if (isMobile) {
                if (mobileCards[index]) {
                    mobileCards[index].style.setProperty("display", "block", "important");
                }
            } else {
                if (desktopRows[index]) {
                    desktopRows[index].style.setProperty("display", "table-row", "important");
                }
                if (detailRows[index]) {
                    detailRows[index].style.setProperty("display", "table-row", "important");
                }
            }
        });

        if (noResultsRow) {
            noResultsRow.style.display = totalItems === 0 ? "block" : "none";
        }

        if (pageText) pageText.textContent = `Página ${currentPage} de ${totalPages}`;
        const displayedStart = totalItems === 0 ? 0 : start + 1;
        const displayedEnd = Math.min(end, totalItems);
        if (pageInfo) pageInfo.textContent = `Mostrando ${displayedStart}-${displayedEnd} de ${totalItems} registros`;

        if (btnPrev) btnPrev.disabled = currentPage === 1;
        if (btnNext) btnNext.disabled = currentPage === totalPages || totalItems === 0;
    }

    if (btnPrev) {
        btnPrev.addEventListener("click", () => {
            if (currentPage > 1) {
                currentPage--;
                renderPage();
            }
        });
    }

    if (btnNext) {
        btnNext.addEventListener("click", () => {
            const filtered = getFilteredIndices();
            if (currentPage * itemsPerPage < filtered.length) {
                currentPage++;
                renderPage();
            }
        });
    }

    [searchInput, statusSelect, locationSelect].forEach(el => {
        if (el) {
            el.addEventListener("input", () => {
                currentPage = 1;
                renderPage();
            });
            el.addEventListener("change", () => {
                currentPage = 1;
                renderPage();
            });
        }
    });

    window.addEventListener("resize", () => {
        renderPage();
    });

    renderPage();
});