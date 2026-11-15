// Service worker de L'Observatoire : il rend le site installable comme une application et, hors connexion, montre
// une page simple au lieu de l'erreur du navigateur. Rien d'autre n'est gardé en cache : chaque ouverture charge la
// dernière version du site, et les requêtes à /api ne passent jamais par ici.
const CACHE = 'observatoire-hors-ligne-1';
const HORS_LIGNE = '/hors-ligne.html';

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.add(new Request(HORS_LIGNE, {cache: 'reload'}))).then(() => self.skipWaiting()));
});

self.addEventListener('activate', event => {
  event.waitUntil(caches.keys()
    .then(noms => Promise.all(noms.filter(nom => nom !== CACHE).map(nom => caches.delete(nom))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', event => {
  if (event.request.mode !== 'navigate') return;
  event.respondWith(fetch(event.request).catch(() => caches.match(HORS_LIGNE)));
});
