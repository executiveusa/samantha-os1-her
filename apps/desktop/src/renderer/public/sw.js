const CACHE_NAME = "os1-pwa-v1";
self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(caches.open(CACHE_NAME));
});
self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});
self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET" || event.request.url.includes("/os1/")) return;
  event.respondWith(fetch(event.request).catch(() => caches.match(event.request)));
});
