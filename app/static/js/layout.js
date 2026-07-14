document.addEventListener("DOMContentLoaded", function () {
    const sidebar = document.querySelector(".sidebar");
    const toggleBtn = document.getElementById("toggle-btn");
    const searchInput = document.querySelector(".search-input");
    const searchBox = document.querySelector(".search-box");
    const togglers = document.querySelectorAll(".sidebar-toggler");

    // =========================================================
    // 1. CONTROL DE COLAPSO Y ESTADO INICIAL (Ajustado a 1024px)
    // =========================================================
    if (window.innerWidth <= 1024) {
        sidebar.classList.add("collapsed");
    } else {
        const sidebarState = localStorage.getItem("sidebar-collapsed");
        if (sidebarState === "true") {
            sidebar.classList.add("collapsed");
        }
    }

    toggleBtn.addEventListener("click", function () {
        sidebar.classList.toggle("collapsed");
        if (window.innerWidth > 1024) {
            localStorage.setItem("sidebar-collapsed", sidebar.classList.contains("collapsed"));
        }
    });

    if (searchBox) {
        searchBox.addEventListener("click", function () {
            if (sidebar.classList.contains("collapsed")) {
                sidebar.classList.remove("collapsed");
                setTimeout(() => searchInput.focus(), 200);
            }
        });
    }

    // =========================================================
    // 2. COMPORTAMIENTO DE CLIC (SÓLO MÓVILES Y TABLETS HASTA 1024px)
    // =========================================================
    togglers.forEach(toggler => {
        toggler.addEventListener("click", function (e) {
            // Este clic tipo acordeón SOLO se ejecuta en pantallas pequeñas
            if (window.innerWidth <= 1024 && !sidebar.classList.contains("searching")) {
                const item = this.closest(".nav-item");
                const dropdown = item.querySelector(".menu-desplegable");

                if (dropdown) {
                    e.preventDefault(); 
                    const isOpen = dropdown.classList.contains("open");

                    // Cerrar los demás submenús
                    document.querySelectorAll(".menu-desplegable").forEach(d => {
                        d.classList.remove("open");
                    });
                    document.querySelectorAll(".sidebar-toggler").forEach(t => {
                        t.classList.remove("active");
                    });

                    // Abrir el seleccionado
                    if (!isOpen) {
                        dropdown.classList.add("open");
                        this.classList.add("active");
                    }
                }
            }
        });
    });

    // =========================================================
    // 3. MOTOR DE BÚSQUEDA INTERNO (Limpio de inline important)
    // =========================================================
    if (searchInput) {
        searchInput.addEventListener("input", function (e) {
            const query = e.target.value.toLowerCase().trim();
            const navItems = document.querySelectorAll(".sidebar-menu .nav-item");

            if (query === "") {
                sidebar.classList.remove("searching");
            } else {
                sidebar.classList.add("searching");
            }

            navItems.forEach(item => {
                const mainLink = item.querySelector(".sidebar-toggler");
                const mainText = mainLink ? mainLink.querySelector(".link-text").textContent.toLowerCase() : "";
                const subLinks = item.querySelectorAll(".sub-link");
                const dropdown = item.querySelector(".menu-desplegable");
                
                let matchesMain = mainText.includes(query);
                let matchesSub = false;

                subLinks.forEach(sub => {
                    const subText = sub.textContent.toLowerCase();
                    if (subText.includes(query)) {
                        matchesSub = true;
                        sub.style.display = "block";
                    } else {
                        if (query !== "") {
                            sub.style.display = "none";
                        } else {
                            sub.style.display = "";
                        }
                    }
                });

                if (query === "") {
                    item.style.display = "";
                    if (dropdown) {
                        dropdown.style.display = "";
                    }
                } else {
                    if (matchesMain || matchesSub) {
                        item.style.display = "block";
                        if (dropdown) {
                            if (matchesSub) {
                                dropdown.style.display = "block";
                            } else {
                                dropdown.style.display = "none";
                            }
                        }
                    } else {
                        item.style.display = "none";
                    }
                }
            });
        });
    }
});