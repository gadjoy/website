/*
 * Gadjoy service worker (spec 013, FR-004..FR-009).
 *
 * Served from the root so its scope is the whole site. GitHub Pages cannot set
 * `Service-Worker-Allowed`, so scope widening is impossible — serving from root
 * is what makes that irrelevant rather than a problem.
 *
 * DESIGN NOTE, because a service worker is the one thing here that can break
 * the site for returning visitors even after a good deploy: this one is
 * deliberately small, its caches are versioned, and activation deletes every
 * cache that is not of the current version. A worker that cannot be retired is
 * the classic failure of this pattern, and clearing it needs devtools that a
 * repair-shop customer does not have.
 *
 * The build is 198 MB across 3,630 pages, so NOTHING resembling a full precache
 * is possible or attempted. What is precached is an app shell; everything else
 * is cached as it is visited.
 */

// Bump on any change to this file's behaviour. Activation deletes every cache
// whose name does not start with this exact version.
const VERSION = 'gadjoy-v1';

const SHELL_CACHE = `${VERSION}-shell`;
const PAGE_CACHE = `${VERSION}-pages`;
const ASSET_CACHE = `${VERSION}-assets`;

// Small and fixed. The offline page is the only one that MUST be here: it is
// what a visitor sees when they have never loaded the page they asked for.
const SHELL = [
  '/offline/',
  '/img/pwa/icon-192.png',
  '/img/pwa/icon-512.png',
];

const ASSET_PATTERN = /\.(?:css|js|woff2?|ttf|otf|png|jpe?g|webp|gif|svg|ico)$/i;

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(SHELL_CACHE);
    // addAll() rejects the whole install if any single entry 404s, which would
    // leave the site with no worker at all. Each entry is added individually so
    // one missing asset degrades rather than aborts.
    await Promise.all(SHELL.map(async (url) => {
      try {
        await cache.add(new Request(url, { cache: 'reload' }));
      } catch (err) {
        console.warn('[sw] could not precache', url, err);
      }
    }));
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(
      names
        .filter((n) => n.startsWith('gadjoy-') && !n.startsWith(VERSION))
        .map((n) => caches.delete(n)),
    );
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // --- never intercepted -----------------------------------------------
  // FR-008. A queued or replayed enquiry is WORSE than a failed one: the
  // customer believes it was sent and waits for a reply that is not coming.
  // Anything that is not a plain same-origin GET goes straight to the network.
  if (request.method !== 'GET') return;
  if (url.origin !== self.location.origin) return;
  // Range requests (video seeking) must not be served from a full-body cache.
  if (request.headers.has('range')) return;

  if (request.mode === 'navigate' || request.destination === 'document') {
    event.respondWith(htmlNetworkFirst(request));
    return;
  }

  if (ASSET_PATTERN.test(url.pathname)) {
    event.respondWith(assetCacheFirst(request));
  }
});

/*
 * Network-first for HTML (FR-006).
 *
 * The shop publishes repair posts and corrects claims on the site; a page
 * served stale from cache would show yesterday's content indefinitely. The
 * cache is the fallback, not the source.
 */
async function htmlNetworkFirst(request) {
  const cache = await caches.open(PAGE_CACHE);
  try {
    const fresh = await fetch(request);
    if (fresh && fresh.ok) {
      cache.put(request, fresh.clone());
    }
    return fresh;
  } catch (err) {
    const cached = await cache.match(request);
    if (cached) return cached;

    // Never visited, no network. Show Gadjoy's own offline page rather than
    // the browser's error, which looks to a customer like the shop's site is
    // broken (US3).
    const shell = await caches.open(SHELL_CACHE);
    const offline = await shell.match('/offline/');
    if (offline) return offline;

    return new Response('Offline', {
      status: 503,
      headers: { 'Content-Type': 'text/plain' },
    });
  }
}

/* Cache-first for assets (FR-006). Images and CSS here are effectively
 * immutable — a changed image gets a new path through the media pipeline. */
async function assetCacheFirst(request) {
  const cache = await caches.open(ASSET_CACHE);
  const cached = await cache.match(request);
  if (cached) return cached;
  try {
    const fresh = await fetch(request);
    if (fresh && fresh.ok) cache.put(request, fresh.clone());
    return fresh;
  } catch (err) {
    return cached || Response.error();
  }
}
