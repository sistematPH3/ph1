document.addEventListener("DOMContentLoaded", function() {
    const searchInput = document.getElementById("auditSearchInput");
    const locationFilterSelect = document.getElementById("locationFilter");
    const dateFilterInput = document.getElementById("dateFilter");
    const hourFilterSelect = document.getElementById("hourFilter");
    const clearTimeBtn = document.getElementById("clearTimeBtn");
    
    const dataRows = document.querySelectorAll(".audit-data-row");
    const noResultsRow = document.getElementById("noResultsRow");
    const mobileCards = document.querySelectorAll("#auditCardsContainer .mobile-audit-card");
    const noSearchResults = document.getElementById("noSearchResults");

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
            const isVisible = checkMatch(row, searchKeyword, selectedLocation, selectedDate, selectedHour, "table");
            
            if (isVisible) {
                row.style.display = "";
                visibleRowsCount++;
            } else {
                row.style.display = "none";
            }
        });

        mobileCards.forEach(card => {
            const isVisible = checkMatch(card, searchKeyword, selectedLocation, selectedDate, selectedHour, "card");
            
            if (isVisible) {
                card.style.setProperty("display", "block", "important");
                visibleCardsCount++;
            } else {
                card.style.setProperty("display", "none", "important");
            }
        });

        const isMobile = window.innerWidth < 768;
        if (noSearchResults) {
            if (isMobile) {
                if (mobileCards.length > 0 && visibleCardsCount === 0) {
                    noSearchResults.classList.remove("d-none");
                } else {
                    noSearchResults.classList.add("d-none");
                }
            } else {
                if (dataRows.length > 0 && visibleRowsCount === 0) {
                    noSearchResults.classList.remove("d-none");
                } else {
                    noSearchResults.classList.add("d-none");
                }
            }
        }

        if (noResultsRow) {
            noResultsRow.style.display = "none";
        }
    }

    function checkMatch(element, searchKeyword, selectedLocation, selectedDate, selectedHour, type) {
        let fullText = element.textContent.toLowerCase();
        let locationText = "";
        let timestampFull = "";

        if (type === "table") {
            const locationCell = element.querySelector(".location-cell-data");
            locationText = locationCell ? locationCell.textContent.trim() : "";
            const datetimeCell = element.querySelector(".datetime-column-cell");
            timestampFull = datetimeCell ? datetimeCell.getAttribute("data-timestamp") : "";
        } else {
            locationText = element.getAttribute("data-location") || "";
            timestampFull = element.getAttribute("data-timestamp") || "";
        }

        if (searchKeyword && !fullText.includes(searchKeyword)) {
            return false;
        }

        if (selectedLocation && !locationText.includes(selectedLocation)) {
            return false;
        }

        if (timestampFull) {
            const parts = timestampFull.split('T');
            const rDate = parts[0];
            const rTime = parts[1] ? parts[1].substring(0, 5) : "";

            if (selectedDate && selectedDate !== rDate) {
                return false;
            }
            if (selectedHour && selectedHour !== rTime) {
                return false;
            }
        } else {
            if (selectedDate || selectedHour) {
                return false;
            }
        }

        return true;
    }

    if (searchInput) searchInput.addEventListener("input", processTableFilters);
    if (locationFilterSelect) locationFilterSelect.addEventListener("change", processTableFilters);
    if (dateFilterInput) dateFilterInput.addEventListener("input", processTableFilters);
    if (hourFilterSelect) hourFilterSelect.addEventListener("input", processTableFilters);
});