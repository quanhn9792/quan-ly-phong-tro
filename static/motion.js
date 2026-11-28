// Số tiền ở ô thống kê đếm tăng dần khi mở trang. Các chuyển động khác (chuyển trang mờ → rõ,
// khối hiện lần lượt, biểu đồ tự vẽ) làm bằng CSS. Máy bật "Giảm chuyển động" thì bỏ qua.
(() => {
    if (!window.matchMedia || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    // Hiệu ứng chuyển trang chỉ chiếm vùng giữa thanh trên và thanh tab (không đè lên hai thanh)
    const root = document.documentElement;
    const measureBars = () => {
        const top = document.querySelector(".appbar")?.getBoundingClientRect();
        const tab = document.querySelector(".tabbar")?.getBoundingClientRect();
        root.style.setProperty("--vt-top", `${top && top.height ? Math.max(0, top.bottom) : 0}px`);
        root.style.setProperty("--vt-bottom", `${tab && tab.height ? Math.max(0, window.innerHeight - tab.top) : 0}px`);
    };
    measureBars();
    window.addEventListener("pageswap", measureBars);

    // Số tiền / số đếm tăng dần từ 0 (chỉ ô thống kê, không động vào bảng)
    const formatLike = (n, grouped) => (grouped ? Math.round(n).toLocaleString("vi-VN") : String(Math.round(n)));
    const ease = (p) => 1 - Math.pow(1 - p, 3);
    document.querySelectorAll(".stat-value, .overdue-head > strong").forEach((el, index) => {
        const node = Array.from(el.childNodes).find((n) => n.nodeType === 3 && /\d/.test(n.nodeValue));
        if (!node) return;
        const original = node.nodeValue;
        const match = original.match(/\d{1,3}(?:\.\d{3})+|\d+/);
        const target = Number(match[0].replace(/\./g, ""));
        if (!target || !Number.isFinite(target)) return;
        const before = original.slice(0, match.index);
        const after = original.slice(match.index + match[0].length);
        const grouped = match[0].includes(".") || target >= 1000;
        const duration = 650 + Math.min(index, 4) * 60;
        el.setAttribute("aria-label", el.textContent.trim().replace(/\s+/g, " "));
        let start = null;
        const step = (now) => {
            if (start === null) start = now;
            const p = Math.min(1, (now - start) / duration);
            node.nodeValue = p < 1 ? before + formatLike(target * ease(p), grouped) + after : original;
            if (p < 1) requestAnimationFrame(step);
        };
        node.nodeValue = before + "0" + after;
        requestAnimationFrame(step);
    });
})();
