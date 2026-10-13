// Service worker: giúp game chạy offline.
// Khi sửa index.html / question.json, hãy tăng số phiên bản CACHE để máy cập nhật bản mới.
const CACHE = 'snake-ai-v6';
const ASSETS = [
  './',
  './index.html',
  './question.json',
  './socket_io_min.js',
  './manifest.webmanifest',
  './icon-192.png',
  './icon-512.png'
];

const ASSET_PATHS = new Set(ASSETS.map((a) => new URL(a, self.location).pathname));

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => Promise.all(ASSETS.map((a) => c.add(a).catch(() => {})))).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// Ưu tiên bản đã lưu (mở nhanh, chạy offline), đồng thời tải bản mới ở nền cho lần mở sau.
self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  // Khi trang do main.py phục vụ (cùng địa chỉ với máy chủ game): KHÔNG được cache /socket.io, /health, /status...
  // Chỉ xử lý trang chính và các file trong ASSETS.
  if (req.mode !== 'navigate' && !ASSET_PATHS.has(url.pathname)) return;

  e.respondWith((async () => {
    const cache = await caches.open(CACHE);
    let cached = await cache.match(req, { ignoreSearch: true });
    if (!cached && req.mode === 'navigate') cached = await cache.match('./index.html');

    const network = fetch(req)
      .then((res) => {
        if (res && res.ok) cache.put(req, res.clone());
        return res;
      })
      .catch(() => null);

    if (cached) {
      e.waitUntil(network);
      return cached;
    }
    return (await network) || new Response('Đang offline và chưa có dữ liệu được lưu.', {
      status: 503,
      headers: { 'Content-Type': 'text/plain; charset=utf-8' }
    });
  })());
});
