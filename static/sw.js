// De CACHE-naam wordt bij Flask-opstart vervangen door een hash van
// static/sw.js + static/js/*.js (zie weekmenu/routes/main.py::sw_js). Elke
// uitrol met gewijzigde JS levert vanzelf een nieuwe cache-naam op; de oude
// wordt in de 'activate'-listener hieronder opgeruimd.
// De 'weekmenu-devel'-waarde hieronder is de vangnetwaarde als de dynamische
// route om welke reden dan ook faalt en de statische versie wordt geserveerd.
const CACHE = 'weekmenu-devel';
const SHELL = [
  '/',
  '/static/favicon.svg',
  '/static/icon-192.png',
  '/static/icon-512.png',
];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  // Network-first for navigatie (HTML pagina's)
  if (e.request.mode === 'navigate') {
    e.respondWith(
      fetch(e.request)
        .then(r => { cacheClone(e.request, r); return r; })
        .catch(() => caches.match(e.request))
    );
    return;
  }

  // Cache-first voor statische assets
  if (url.pathname.startsWith('/static/')) {
    e.respondWith(
      caches.match(e.request).then(cached =>
        cached || fetch(e.request).then(r => { cacheClone(e.request, r); return r; })
      )
    );
    return;
  }

  // Network-only voor API/overige requests
  e.respondWith(fetch(e.request));
});

function cacheClone(req, res) {
  if (res.ok) caches.open(CACHE).then(c => c.put(req, res.clone()));
}
