// Platine service worker (Workbox). The server serves this file on /sw.js, prefixed with
// `const PRECACHE = [...]`: every interface file with a fingerprint of its content, so the
// slightest change triggers an update of the installed app.
/* global PRECACHE, workbox */

importScripts("/vendor/workbox/workbox-sw.js");
workbox.setConfig({ modulePathPrefix: "/vendor/workbox/", debug: false });

const { cacheableResponse, core, expiration, precaching, routing, strategies } = workbox;
const SERVER_ONLY = /^\/(api|metrics|healthz)(\/|$)/;

core.setCacheNameDetails({ prefix: "platine" });
precaching.cleanupOutdatedCaches();
precaching.precacheAndRoute(PRECACHE);

// The API and the MP3 files always come from the server: nothing stale may be shown.
routing.registerRoute(
  ({ url }) => url.origin === self.location.origin && SERVER_ONLY.test(url.pathname),
  new strategies.NetworkOnly(),
);

// Every navigation, Android sharing included ("/?text=..."), opens the app, even offline.
routing.registerRoute(
  new routing.NavigationRoute(precaching.createHandlerBoundToURL("/"), { denylist: [SERVER_ONLY] }),
);

// Covers (YouTube, Spotify, SoundCloud...): kept for a month so the list still shows offline.
routing.registerRoute(
  ({ request, url }) => request.destination === "image" && url.origin !== self.location.origin,
  new strategies.CacheFirst({
    cacheName: "platine-covers",
    plugins: [
      new cacheableResponse.CacheableResponsePlugin({ statuses: [0, 200] }),
      new expiration.ExpirationPlugin({ maxEntries: 120, maxAgeSeconds: 30 * 24 * 3600, purgeOnQuotaError: true }),
    ],
  }),
);

// The page offers "Reload" when a new version is waiting, then sends this message.
self.addEventListener("message", (event) => {
  if (event.data?.type === "SKIP_WAITING") self.skipWaiting();
});
