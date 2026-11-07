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

    // ----- Copy / chia sẻ link (link app của khách) -----
    const flashToast = (text) => {
        let box = document.getElementById("app-toast");
        if (!box) {
            box = document.createElement("div");
            box.id = "app-toast";
            box.className = "toast";
            box.setAttribute("role", "status");
            document.body.appendChild(box);
        }
        box.textContent = text;
        box.classList.add("show");
        clearTimeout(box._timer);
        box._timer = setTimeout(() => box.classList.remove("show"), 3500);
    };
    window.appToast = flashToast;
    if (navigator.share) document.querySelectorAll("[data-share-link]").forEach((b) => { b.hidden = false; });
    const isTouch = window.matchMedia("(pointer: coarse)").matches;
    document.addEventListener("click", async (event) => {
        const both = event.target.closest("[data-copy][data-share-link]");
        if (both && isTouch && navigator.share) {
            try {
                await navigator.share({ title: both.dataset.shareTitle, text: both.dataset.shareTitle, url: both.dataset.shareLink });
            } catch { /* người dùng đóng bảng chia sẻ */ }
            return;
        }
        const copyBtn = event.target.closest("[data-copy]");
        if (copyBtn) {
            try {
                await navigator.clipboard.writeText(copyBtn.dataset.copy);
                flashToast("Đã copy link. Dán vào Zalo để gửi cho khách.");
            } catch {
                const input = copyBtn.closest(".portal-link")?.querySelector("input");
                if (input) { input.focus(); input.select(); }
                flashToast("Hãy giữ vào ô link để copy.");
            }
            return;
        }
        const shareBtn = event.target.closest("[data-share-link]");
        if (shareBtn) {
            try {
                await navigator.share({ title: shareBtn.dataset.shareTitle, text: shareBtn.dataset.shareTitle, url: shareBtn.dataset.shareLink });
            } catch { /* người dùng đóng bảng chia sẻ */ }
        }
    });

    // ----- Đánh dấu đã thu / chưa thu không cần tải lại trang -----
    document.addEventListener("submit", async (event) => {
        const form = event.target.closest("form[data-paid-toggle]");
        if (!form || !window.fetch) return;
        event.preventDefault();
        const button = form.querySelector("button");
        button.disabled = true;
        try {
            const response = await fetch(form.action, { method: "POST", body: new FormData(form), headers: { "X-Requested-With": "fetch" } });
            if (!response.ok) throw new Error(String(response.status));
            const { paid } = await response.json();
            const scope = form.closest("[data-paid-scope]") || form;
            scope.classList.toggle("is-paid", paid);
            scope.querySelectorAll("form[data-paid-toggle] input[name=paid]").forEach((i) => { i.value = paid ? "0" : "1"; });
            flashToast(paid ? "Đã đánh dấu đã thu tiền." : "Đã chuyển về chưa thu.");
            document.dispatchEvent(new CustomEvent("paid-changed", { detail: { paid } }));
        } catch {
            form.submit();
        } finally {
            button.disabled = false;
        }
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
