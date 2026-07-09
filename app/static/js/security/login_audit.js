document.addEventListener("DOMContentLoaded", function() {
    const searchInput = document.getElementById("auditSearchInput");
    const locationFilterSelect = document.getElementById("locationFilter");
    const dateFilterInput = document.getElementById("dateFilter");
    const hourFilterSelect = document.getElementById("hourFilter");
    const dataRows = document.querySelectorAll(".audit-data-row");
    const noResultsRow = document.getElementById("noResultsRow");

    if (dataRows.length === 0) {
        noResultsRow.style.display = "";
    }

    const currentDateTime = new Date();
    const offset = currentDateTime.getTimezoneOffset() * 60000;
    const maxDateString = (new Date(currentDateTime - offset)).toISOString().split('T')[0];
    dateFilterInput.max = maxDateString;

    function processTableFilters() {
        const searchKeyword = searchInput.value.toLowerCase();
        const selectedLocation = locationFilterSelect.value;
        const selectedDate = dateFilterInput.value;
        const selectedHour = hourFilterSelect.value;
        
        let visibleCount = 0;

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
                const rHour = parts[1] ? parts[1].substring(0, 2) : "";

                if (selectedDate) {
                    matchesDate = (selectedDate === rDate);
                }
                if (selectedHour) {
                    matchesHour = (selectedHour === rHour);
                }
            } else {
                if (selectedDate || selectedHour) {
                    matchesDate = false;
                    matchesHour = false;
                }
            }

            if (matchesLocation && matchesSearch && matchesDate && matchesHour) {
                row.style.display = "";
                visibleCount++;
            } else {
                row.style.display = "none";
            }
        });

        noResultsRow.style.display = (visibleCount === 0) ? "" : "none";
    }

    searchInput.addEventListener("input", processTableFilters);
    locationFilterSelect.addEventListener("change", processTableFilters);
    dateFilterInput.addEventListener("input", processTableFilters);
    hourFilterSelect.addEventListener("change", processTableFilters);
});