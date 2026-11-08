document.addEventListener("DOMContentLoaded", function() {
    const searchInput = document.getElementById("auditSearchInput");
    const locationFilterSelect = document.getElementById("locationFilter");
    const dateFilterInput = document.getElementById("dateFilter");
    const hourFilterSelect = document.getElementById("hourFilter");
    
    const dataRows = document.querySelectorAll(".audit-data-row");
    const mobileCards = document.querySelectorAll("#auditCardsContainer .mobile-audit-card");
    const noResultsRow = document.getElementById("noResultsRow");

    if (dataRows.length === 0 && noResultsRow) {
        noResultsRow.style.display = "";
    }

    const currentDateTime = new Date();
    const offset = currentDateTime.getTimezoneOffset() * 60000;
    const maxDateString = (new Date(currentDateTime - offset)).toISOString().split('T')[0];
    
    if (dateFilterInput) {
        dateFilterInput.max = maxDateString;
    }

    function processTableFilters() {
        const searchText = searchInput ? searchInput.value.toLowerCase() : "";
        const selectedLocation = locationFilterSelect ? locationFilterSelect.value : "all";
        const selectedDate = dateFilterInput ? dateFilterInput.value : "";
        const selectedHour = hourFilterSelect ? hourFilterSelect.value : "";

        let visibleRowsCount = 0;
        let visibleCardsCount = 0;

        function filterElement(el) {
            const rText = el.textContent.toLowerCase();
            const rLoc = el.getAttribute("data-location") || "";
            const rDate = el.getAttribute("data-date") || "";
            const rTime12 = el.getAttribute("data-time12") || "";

            let matchesSearch = searchText === "" || rText.includes(searchText);
            let matchesLocation = selectedLocation === "all" || rLoc === selectedLocation;
            let matchesDate = true;
            let matchesHour = true;

            if (rDate) {
                if (selectedDate) matchesDate = (selectedDate === rDate);
                if (selectedHour) matchesHour = (selectedHour === rTime12);
            } else {
                if (selectedDate || selectedHour) {
                    matchesDate = false;
                    matchesHour = false;
                }
            }

            return matchesLocation && matchesSearch && matchesDate && matchesHour;
        }

        dataRows.forEach(row => {
            if (filterElement(row)) {
                row.style.display = "";
                visibleRowsCount++;
            } else {
                row.style.display = "none";
            }
        });

        mobileCards.forEach(card => {
            if (filterElement(card)) {
                card.style.setProperty("display", "block", "important");
                visibleCardsCount++;
            } else {
                card.style.setProperty("display", "none", "important");
            }
        });

        if (noResultsRow) {
            const isMobile = window.innerWidth < 768;
            if (isMobile) {
                noResultsRow.style.setProperty("display", (visibleCardsCount === 0) ? "table-row" : "none", "important");
            } else {
                noResultsRow.style.setProperty("display", (visibleRowsCount === 0) ? "table-row" : "none", "important");
            }
        }
    }

    if (searchInput) searchInput.addEventListener("input", processTableFilters);
    if (locationFilterSelect) locationFilterSelect.addEventListener("change", processTableFilters);
    if (dateFilterInput) dateFilterInput.addEventListener("input", processTableFilters);
    if (hourFilterSelect) hourFilterSelect.addEventListener("change", processTableFilters);
});