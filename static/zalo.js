// Gửi hóa đơn qua Zalo.
// - Máy tính: copy ảnh hóa đơn vào clipboard rồi mở khung chat zalo.me/<số> → Ctrl+V, Enter.
// - Điện thoại: mở bảng Chia sẻ của hệ điều hành kèm ảnh → chọn Zalo → chọn khách.
(() => {
    const toast = (text, isError) => {
        let box = document.getElementById("zalo-toast");
        if (!box) {
            box = document.createElement("div");
            box.id = "zalo-toast";
            box.className = "toast";
            document.body.appendChild(box);
        }
        box.textContent = text;
        box.classList.toggle("is-error", !!isError);
        box.classList.add("show");
        clearTimeout(box._timer);
        box._timer = setTimeout(() => box.classList.remove("show"), 6000);
    };

    const copyImage = async (url) => {
        if (!navigator.clipboard || !window.ClipboardItem) throw new Error("no-clipboard");
        // Truyền Promise vào ClipboardItem để thao tác vẫn nằm trong lượt bấm của người dùng
        const blob = fetch(url, { cache: "no-store" }).then((r) => {
            if (!r.ok) throw new Error("image");
            return r.blob();
        });
        await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
    };

    const download = (url, filename) => {
        const a = document.createElement("a");
        a.href = url;
        a.download = filename || "hoa-don.png";
        document.body.appendChild(a);
        a.click();
        a.remove();
    };

    // ----- Điện thoại: Web Share API -----
    const isTouch = window.matchMedia("(pointer: coarse)").matches;
    const canShareFiles = isTouch && !!navigator.canShare &&
        navigator.canShare({ files: [new File([""], "x.png", { type: "image/png" })] });
    // iOS chỉ cho mở bảng chia sẻ ngay trong lượt chạm, nên phải tải sẵn ảnh trước khi bấm
    const files = new Map();
    const preload = (button) => {
        const { image, filename } = button.dataset;
        if (files.has(image)) return;
        files.set(image, fetch(image, { cache: "no-store" })
            .then((r) => (r.ok ? r.blob() : Promise.reject(new Error("image"))))
            .then((blob) => { const file = new File([blob], filename || "hoa-don.png", { type: "image/png" }); files.set(image, file); return file; })
            .catch(() => { files.delete(image); }));
    };
    if (canShareFiles) {
        const buttons = document.querySelectorAll("[data-zalo-send]");
        if ("IntersectionObserver" in window) {
            const observer = new IntersectionObserver((entries) => entries.forEach((entry) => {
                if (entry.isIntersecting) { preload(entry.target); observer.unobserve(entry.target); }
            }), { rootMargin: "300px" });
            buttons.forEach((b) => observer.observe(b));
        } else {
            buttons.forEach(preload);
        }
    }

    const markSent = (button, logUrl) => {
        if (logUrl) fetch(logUrl, { method: "POST" }).catch(() => {});
        const card = button.closest("[data-zalo-item]");
        if (card) {
            card.classList.add("is-sent");
            const next = card.parentElement.querySelector("[data-zalo-item]:not(.is-sent) [data-zalo-send]");
            if (next) next.closest("[data-zalo-item]").scrollIntoView({ behavior: "smooth", block: "center" });
        }
    };

    const shareOnPhone = async (button) => {
        const { image, logUrl, phone } = button.dataset;
        const file = files.get(image);
        if (!(file instanceof File)) {
            preload(button);
            toast("Đang chuẩn bị ảnh hóa đơn, bấm lại sau giây lát…");
            return;
        }
        try {
            await navigator.share({ files: [file] });
        } catch (error) {
            if (error && error.name === "AbortError") return; // người dùng đóng bảng chia sẻ
            toast("Không mở được bảng chia sẻ. Hãy mở ảnh, bấm giữ để lưu rồi gửi qua Zalo.", true);
            return;
        }
        markSent(button, logUrl);
        if (phone) toast(`Đã chia sẻ. Nhớ chọn đúng khách có số Zalo ${phone}.`);
    };

    document.addEventListener("click", async (event) => {
        const button = event.target.closest("[data-zalo-send]");
        if (!button) return;
        event.preventDefault();
        if (canShareFiles) {
            shareOnPhone(button);
            return;
        }
        const { image, link, logUrl, filename } = button.dataset;

        let copied = true;
        try {
            await copyImage(image);
        } catch {
            copied = false;
            download(image, filename);
        }
        window.open(link, "_blank", "noopener");

        toast(copied
            ? "Đã copy ảnh hóa đơn. Trong khung chat Zalo vừa mở: bấm Ctrl+V rồi Enter để gửi."
            : "Trình duyệt không cho copy ảnh — ảnh đã được tải về, hãy kéo thả ảnh vào khung chat Zalo.",
            !copied);

        markSent(button, logUrl);
    });
})();
