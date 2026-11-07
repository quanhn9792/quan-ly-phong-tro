// Service worker: chỉ cache giao diện tĩnh (CSS/JS/icon) để mở app nhanh.
// KHÔNG cache trang có dữ liệu (hóa đơn, khách thuê) — luôn lấy mới từ máy chủ.
const VERSION = "v1";
const STATIC_CACHE = `static-${VERSION}`;
const PRECACHE = [
    "/offline",
    "/static/styles.css?v=5",
    "/static/app.js?v=1",
    "/static/icons/icon-192.png",
];

self.addEventListener("install", (event) => {
    event.waitUntil(caches.open(STATIC_CACHE).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys()
            .then((keys) => Promise.all(keys.filter((key) => key !== STATIC_CACHE).map((key) => caches.delete(key))))
            .then(() => self.clients.claim())
    );
});

self.addEventListener("fetch", (event) => {
    const { request } = event;
    if (request.method !== "GET") return;
    const url = new URL(request.url);
    if (url.origin !== self.location.origin) return;

    // Mở trang: luôn lấy từ mạng; mất kết nối (máy chủ tắt / mất mạng) thì hiện trang báo offline
    if (request.mode === "navigate") {
        event.respondWith(fetch(request).catch(() => caches.match("/offline")));
        return;
    }

    // File tĩnh: dùng bản cache ngay, đồng thời tải bản mới ở nền
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
