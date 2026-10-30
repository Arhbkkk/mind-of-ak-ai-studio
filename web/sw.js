/* Network-only service worker: never cache authenticated studio content. */
self.addEventListener("install", event => { self.skipWaiting(); });
self.addEventListener("activate", event => { event.waitUntil(self.clients.claim()); });
self.addEventListener("fetch", event => {
  // Keep authentication enforced by the server; no caching of HTML, APIs, media or exports.
  event.respondWith(fetch(event.request));
});
