document.addEventListener("DOMContentLoaded", function() {
    const backBtn = document.getElementById('btn-back-history');
    if (backBtn) {
        backBtn.addEventListener('click', function(e) {
            e.preventDefault();
            if (window.history.length > 1) {
                window.history.back();
            } else {
                window.location.href = '/logistics/purchases/history';
            }
        });
    }
});