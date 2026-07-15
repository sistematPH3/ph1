document.addEventListener("DOMContentLoaded", function() {
    const searchInput = document.getElementById("auditSearchInput");
    const locationFilterSelect = document.getElementById("locationFilter");
    const dateFilterInput = document.getElementById("dateFilter");
    const hourFilterSelect = document.getElementById("hourFilter");
    const clearTimeBtn = document.getElementById("clearTimeBtn");
    
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

    function toggleClearButton() {
        if (hourFilterSelect && clearTimeBtn) {
            if (hourFilterSelect.value) {
                clearTimeBtn.style.display = "block";
            } else {
                clearTimeBtn.style.display = "none";
            }
        }
    }

    if (clearTimeBtn && hourFilterSelect) {
        clearTimeBtn.addEventListener("click", function() {
            hourFilterSelect.value = "";
            toggleClearButton();
            processTableFilters();
        });
    }

    function processTableFilters() {
        toggleClearButton();

        const searchKeyword = searchInput ? searchInput.value.toLowerCase() : "";
        const selectedLocation = locationFilterSelect ? locationFilterSelect.value : "";
        const selectedDate = dateFilterInput ? dateFilterInput.value : "";
        const selectedHour = hourFilterSelect ? hourFilterSelect.value : "";
        
        let visibleRowsCount = 0;
        let visibleCardsCount = 0;

        dataRows.forEach(row => {
            const rowFullText = row.textContent.toLowerCase();
            const locationCell = row.querySelector(".location-cell-data");
            const locationText = locationCell ? locationCell.textContent.trim() : "";
            const matchesLocation = !selectedLocation || locationText.includes(selectedLocation);
            const matchesSearch = rowFullText.includes(searchKeyword);
            const datetimeCell = row.querySelector(".datetime-column-cell");
            const rowTimestampFull = datetimeCell ? datetimeCell.getAttribute("data-timestamp") : "";
            
            let matchesDate = true;
            let matchesHour = true;

            if (rowTimestampFull) {
                const parts = rowTimestampFull.split('T');
                const rDate = parts[0];
                const rTime = parts[1] ? parts[1].substring(0, 5) : "";

                if (selectedDate) {
                    matchesDate = (selectedDate === rDate);
                }
                if (selectedHour) {
                    matchesHour = (selectedHour === rTime);
                }
            } else {
                if (selectedDate || selectedHour) {
                    matchesDate = false;
                    matchesHour = false;
                }
            }

            if (matchesLocation && matchesSearch && matchesDate && matchesHour) {
                row.style.setProperty("display", "", "important");
                visibleRowsCount++;
            } else {
                row.style.setProperty("display", "none", "important");
            }
        });

        mobileCards.forEach(card => {
            const cardFullText = card.textContent.toLowerCase();
            const cardLocation = card.getAttribute("data-location") || "";
            const matchesLocation = !selectedLocation || cardLocation.includes(selectedLocation);
            const matchesSearch = cardFullText.includes(searchKeyword);
            const cardTimestampFull = card.getAttribute("data-timestamp") || "";
            
            let matchesDate = true;
            let matchesHour = true;

            if (cardTimestampFull) {
                const parts = cardTimestampFull.split('T');
                const rDate = parts[0];
                const rTime = parts[1] ? parts[1].substring(0, 5) : "";

                if (selectedDate) {
                    matchesDate = (selectedDate === rDate);
                }
                if (selectedHour) {
                    matchesHour = (selectedHour === rTime);
                }
            } else {
                if (selectedDate || selectedHour) {
                    matchesDate = false;
                    matchesHour = false;
                }
            }

            if (matchesLocation && matchesSearch && matchesDate && matchesHour) {
                card.style.setProperty("display", "block", "important");
                visibleCardsCount++;
            } else {
                card.style.setProperty("display", "none", "important");
            }
        });

        if (noResultsRow) {
            const isMobile = window.innerWidth < 768;
            if (isMobile) {
                noResultsRow.style.setProperty("display", (visibleCardsCount === 0) ? "block" : "none", "important");
            } else {
                noResultsRow.style.setProperty("display", (visibleRowsCount === 0) ? "" : "none", "important");
            }
        }
    }

    if (searchInput) searchInput.addEventListener("input", processTableFilters);
    if (locationFilterSelect) locationFilterSelect.addEventListener("change", processTableFilters);
    if (dateFilterInput) dateFilterInput.addEventListener("input", processTableFilters);
    if (hourFilterSelect) hourFilterSelect.addEventListener("input", processTableFilters);
});