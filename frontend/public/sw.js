/*
  «Цифровой механик»: сервис-воркер установленного приложения.
  Данные и ответы агента всегда идут из сети: система без сервера не работает и устаревшее показывать нельзя.
  В запасе лежат только оболочка (скрипты, стили, шрифты, значки) и экран «Нет связи».
*/
const VERSION = 'dm-v1';
const SHELL = ['/offline.html', '/icons/icon-192.png'];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(VERSION).then((cache) => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== VERSION).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

/** Файлы сборки с меткой в имени не меняются: берём из запаса, в сеть идём один раз. */
function isStatic(url) {
  return url.pathname.startsWith('/_next/static/') || url.pathname.startsWith('/icons/');
}

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  // Запросы к серверу агента и поток чата сервис-воркер не трогает
  if (url.pathname.startsWith('/api/')) return;

  if (request.mode === 'navigate') {
    // Страница всегда свежая. Нет сети — показываем экран «Нет связи»
    event.respondWith(fetch(request).catch(() => caches.match('/offline.html')));
    return;
  }

  if (isStatic(url)) {
    event.respondWith(
      caches.match(request).then(
        (hit) =>
          hit ||
          fetch(request).then((response) => {
            if (response.ok) {
              const copy = response.clone();
              caches.open(VERSION).then((cache) => cache.put(request, copy));
            }
            return response;
          }),
      ),
    );
  }
});
