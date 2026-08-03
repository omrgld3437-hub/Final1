const CACHE_PREFIX = "ayserose-v2-static-";
const CACHE_NAME = `${CACHE_PREFIX}2026-07-22-3`;
const V2_STATIC_PREFIX = "/ui/assets/v2/dashboard/";
const HASHED_ASSET_PATTERN = /\/assets\/[^/]+-[A-Za-z0-9_-]{8,}\.(?:css|js|woff2?|png|svg|webp|avif)$/;

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME)
            .map((key) => caches.delete(key)),
        ),
      ),
  );
});

function isImmutableV2Asset(request) {
  if (request.method !== "GET") return false;
  if (request.mode === "navigate" || request.destination === "document") return false;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return false;
  if (url.pathname.startsWith("/api/")) return false;
  if (!url.pathname.startsWith(V2_STATIC_PREFIX)) return false;
  return HASHED_ASSET_PATTERN.test(url.pathname);
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (!isImmutableV2Asset(request)) return;

  event.respondWith(
    caches.open(CACHE_NAME).then(async (cache) => {
      const cached = await cache.match(request);
      if (cached) return cached;

      const response = await fetch(request);
      if (response.ok && (response.type === "basic" || response.type === "cors")) {
        await cache.put(request, response.clone());
      }
      return response;
    }),
  );
});

const DASHBOARD_URL = "/ui/assets/v2/dashboard/index.html?source=pwa&tab=bots";

function notificationPayload(event) {
  if (!event.data) return {};
  try {
    return event.data.json();
  } catch (_error) {
    return { body: event.data.text() };
  }
}

function safeNotificationUrl(value) {
  try {
    const target = new URL(value || DASHBOARD_URL, self.location.origin);
    return target.origin === self.location.origin ? target.href : new URL(DASHBOARD_URL, self.location.origin).href;
  } catch (_error) {
    return new URL(DASHBOARD_URL, self.location.origin).href;
  }
}

self.addEventListener("push", (event) => {
  const payload = notificationPayload(event);
  const targetUrl = safeNotificationUrl(payload.url);
  const botId = Number(payload.bot_id);
  event.waitUntil(
    self.registration.showNotification(payload.title || "Ayserose bot işlemi", {
      body: payload.body || "Botunuzda yeni bir işlem gerçekleşti.",
      icon: payload.icon || "/ui/assets/pwa/ayserose-plain-v4-192.png",
      badge: payload.badge || "/ui/assets/pwa/favicon-32.png",
      tag: payload.tag || "ayserose-bot-transaction",
      renotify: true,
      data: {
        url: targetUrl,
        botId: Number.isInteger(botId) && botId > 0 ? botId : null,
      },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const notificationData = event.notification.data || {};
  const target = new URL(safeNotificationUrl(notificationData.url));
  const botId = Number(notificationData.botId);
  if (Number.isInteger(botId) && botId > 0) {
    target.searchParams.set("tab", "bots");
    target.searchParams.set("bot_id", String(botId));
  }
  const targetUrl = target.href;
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then(async (windowClients) => {
      const dashboardClient = windowClients.find((client) => {
        try {
          const clientUrl = new URL(client.url);
          return clientUrl.origin === self.location.origin && clientUrl.pathname.startsWith(V2_STATIC_PREFIX);
        } catch (_error) {
          return false;
        }
      });
      if (dashboardClient) {
        const navigatedClient = await dashboardClient.navigate(targetUrl);
        const activeClient = navigatedClient || dashboardClient;
        activeClient.postMessage({
          type: "AYSEROSE_OPEN_BOT_DETAIL",
          botId: Number.isInteger(botId) && botId > 0 ? botId : null,
        });
        return activeClient.focus();
      }
      return clients.openWindow(targetUrl);
    }),
  );
});
