(() => {
    // ----- CSRF: gắn token vào mọi form POST và mọi fetch() gửi dữ liệu -----
    const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
    window.csrfToken = csrf;
    const addToken = (form) => {
        if ((form.method || "").toLowerCase() !== "post" || form.querySelector('input[name="csrf_token"]')) return;
        const input = document.createElement("input");
        input.type = "hidden";
        input.name = "csrf_token";
        input.value = csrf;
        form.appendChild(input);
    };
    document.querySelectorAll("form").forEach(addToken);
    // Form thêm vào sau khi trang đã tải
    document.addEventListener("submit", (event) => addToken(event.target), true);
    const nativeFetch = window.fetch.bind(window);
    window.fetch = (input, init = {}) => {
        const method = (init.method || "GET").toUpperCase();
        if (csrf && method !== "GET" && method !== "HEAD") {
            init.headers = new Headers(init.headers || {});
            init.headers.set("X-CSRF-Token", csrf);
        }
        return nativeFetch(input, init);
    };

    // ----- Service worker (PWA) -----
    if ("serviceWorker" in navigator && window.isSecureContext) {
        window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
    }

    // ----- Menu "Thêm" trên điện thoại -----
    const body = document.body;
    const setMenu = (open) => {
        body.classList.toggle("menu-open", open);
        document.querySelectorAll("[data-menu-toggle]").forEach((el) => el.setAttribute("aria-expanded", String(open)));
    };
    document.addEventListener("click", (event) => {
        if (event.target.closest("[data-menu-toggle]")) {
            event.preventDefault();
            setMenu(!body.classList.contains("menu-open"));
        } else if (event.target.closest("[data-menu-close]")) {
            setMenu(false);
        }
    });
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") setMenu(false);
    });

    // ----- Số tiền: hiện số đã định dạng dưới ô nhập (vd: 5000000 -> 5.000.000 VND) -----
    const parse = (raw) => {
        let v = (raw || "").replace(/\s/g, "");
        if (!v) return null;
        if (v.includes(",") && v.includes(".")) {
            v = v.lastIndexOf(",") > v.lastIndexOf(".") ? v.replace(/\./g, "").replace(",", ".") : v.replace(/,/g, "");
        } else if (/^\d{1,3}([.,]\d{3})+$/.test(v)) {
            v = v.replace(/[.,]/g, "");
        } else {
            v = v.replace(",", ".");
        }
        const n = Number(v);
        return Number.isFinite(n) ? n : null;
    };
    window.parseVnNumber = parse;
    window.formatVnd = (n) => Math.round(n).toLocaleString("vi-VN") + " VND";
    document.querySelectorAll("[data-money]").forEach((input) => {
        const hint = input.parentElement.querySelector("[data-money-hint]");
        if (!hint) return;
        const fallback = hint.textContent;
        const update = () => {
            const n = parse(input.value);
            hint.textContent = n === null ? fallback : "= " + window.formatVnd(n);
        };
        input.addEventListener("input", update);
        update();
    });
    document.querySelectorAll("form[data-confirm]").forEach((form) => {
        form.addEventListener("submit", (event) => {
            if (!confirm(form.dataset.confirm)) event.preventDefault();
        });
    });
})();
