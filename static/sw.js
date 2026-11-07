// Service worker:
// - File tĩnh (CSS/JS/icon): dùng bản cache ngay, cập nhật ở nền.
// - Trang: luôn lấy mới từ máy chủ; mỗi trang mở thành công được lưu lại để khi
//   mất kết nối (máy chủ tắt / mất mạng) vẫn xem được bản gần nhất, kèm dải "Đang offline".
// - Đăng xuất: trang /login gửi lệnh xóa toàn bộ trang đã lưu (dữ liệu khách thuê).
const VERSION = "v7";
const STATIC_CACHE = `static-${VERSION}`;
const PAGE_CACHE = "pages-v1";
const MAX_PAGES = 40;
const PRECACHE = [
    "/offline",
    "/static/styles.css?v=11",
    "/static/app.js?v=2",
    "/static/icons/icon-192.png",
];
// Không lưu trang đăng nhập / trang lỗi
const NO_PAGE_CACHE = ["/login", "/logout", "/offline", "/sw.js"];

self.addEventListener("install", (event) => {
    event.waitUntil(caches.open(STATIC_CACHE).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys()
            .then((keys) => Promise.all(keys.filter((key) => key !== STATIC_CACHE && key !== PAGE_CACHE).map((key) => caches.delete(key))))
            .then(() => self.clients.claim())
    );
});

self.addEventListener("message", (event) => {
    if (event.data === "clear-pages") event.waitUntil(caches.delete(PAGE_CACHE));
});

const trimPages = async (cache) => {
    const keys = await cache.keys();
    await Promise.all(keys.slice(0, Math.max(0, keys.length - MAX_PAGES)).map((key) => cache.delete(key)));
};

const offlineBanner = (date) =>
    `<div class="offline-banner" role="status">Đang offline — đang xem bản lưu lúc ${date}. Số liệu có thể chưa mới nhất.</div>`;

const fromPageCache = async (request) => {
    const cache = await caches.open(PAGE_CACHE);
    const cached = await cache.match(request, { ignoreVary: true });
    if (!cached) return caches.match("/offline");
    const savedAt = new Date(Number(cached.headers.get("X-Saved-At")) || Date.now());
    const stamp = savedAt.toLocaleString("vi-VN", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" });
    const html = (await cached.text()).replace(/<body([^>]*)>/, (m) => m + offlineBanner(stamp));
    return new Response(html, { headers: { "Content-Type": "text/html; charset=utf-8" } });
};

const savePage = async (request, response) => {
    const type = response.headers.get("Content-Type") || "";
    if (!response.ok || response.redirected || !type.includes("text/html")) return;
    const headers = new Headers(response.headers);
    headers.set("X-Saved-At", String(Date.now()));
    const body = await response.blob();
    const cache = await caches.open(PAGE_CACHE);
    await cache.put(request, new Response(body, { status: 200, headers }));
    await trimPages(cache);
};

const isPortalAsset = (url) => /^\/k\/[^/]+\/hoa-don\/\d+\/(qr\.png|anh\.png)$/.test(url.pathname);

self.addEventListener("fetch", (event) => {
    const { request } = event;
    if (request.method !== "GET") return;
    const url = new URL(request.url);
    if (url.origin !== self.location.origin) return;

    if (request.mode === "navigate") {
        if (NO_PAGE_CACHE.includes(url.pathname)) {
            event.respondWith(fetch(request).catch(() => caches.match("/offline")));
            return;
        }
        event.respondWith(
            fetch(request)
                .then((response) => {
                    event.waitUntil(savePage(request, response.clone()));
                    return response;
                })
                .catch(() => fromPageCache(request))
        );
        return;
    }

    // QR / ảnh hóa đơn của khách: để khách vẫn quét QR chuyển khoản khi máy chủ tắt
    if (isPortalAsset(url)) {
        event.respondWith(
            fetch(request)
                .then((response) => {
                    if (response.ok) {
                        const copy = response.clone();
                        event.waitUntil(caches.open(PAGE_CACHE).then((cache) => cache.put(request, copy)));
                    }
                    return response;
                })
                .catch(() => caches.match(request, { ignoreVary: true }).then((hit) => hit || Response.error()))
        );
        return;
    }

    if (url.pathname.startsWith("/static/")) {
        event.respondWith(
            caches.open(STATIC_CACHE).then(async (cache) => {
                const cached = await cache.match(request);
                const network = fetch(request)
                    .then((response) => {
                        if (response.ok) cache.put(request, response.clone());
                        return response;
                    })
                    .catch(() => cached);
                return cached || network;
            })
        );
    }
});
