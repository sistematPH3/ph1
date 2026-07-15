document.addEventListener('DOMContentLoaded', function() {
    const searchInput = document.getElementById('genericSearchInput');
    
    if (searchInput) {
        searchInput.addEventListener('keyup', function() {
            const filterText = this.value.toLowerCase();
            const rows = document.querySelectorAll('tbody tr');
            
            rows.forEach(row => {
                if (row.classList.contains('no-records-row')) return;
                
                const rowText = row.textContent.toLowerCase();
                
                if (rowText.includes(filterText)) {
                    row.style.display = '';
                } else {
                    row.style.display = 'none';
                }
            });
        });
    }
});