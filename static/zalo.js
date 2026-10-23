// Gửi hóa đơn qua Zalo: copy ảnh hóa đơn vào clipboard rồi mở khung chat zalo.me/<số>.
// Người dùng chỉ cần Ctrl+V và Enter trong Zalo.
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

    document.addEventListener("click", async (event) => {
        const button = event.target.closest("[data-zalo-send]");
        if (!button) return;
        event.preventDefault();
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

        if (logUrl) fetch(logUrl, { method: "POST" }).catch(() => {});
        const card = button.closest("[data-zalo-item]");
        if (card) {
            card.classList.add("is-sent");
            const next = card.parentElement.querySelector("[data-zalo-item]:not(.is-sent) [data-zalo-send]");
            if (next) next.closest("[data-zalo-item]").scrollIntoView({ behavior: "smooth", block: "center" });
        }
    });
})();
