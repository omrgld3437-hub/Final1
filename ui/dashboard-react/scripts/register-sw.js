const v2BaseUrl = new URL(import.meta.env.BASE_URL, window.location.origin);

function canRegisterServiceWorker() {
  if (!("serviceWorker" in navigator)) return false;
  if (window.isSecureContext) return true;
  return window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
}

async function registerV2ServiceWorker() {
  if (!canRegisterServiceWorker()) return;

  try {
    const registration = await navigator.serviceWorker.register(
      new URL("sw.js", v2BaseUrl),
      {
        scope: v2BaseUrl.pathname,
        updateViaCache: "none",
      },
    );
    await registration.update();

    registration.addEventListener("updatefound", () => {
      const worker = registration.installing;
      if (!worker) return;
      worker.addEventListener("statechange", () => {
        if (worker.state === "installed" && navigator.serviceWorker.controller) {
          window.dispatchEvent(new CustomEvent("ayserose:pwa-update-ready"));
        }
      });
    });
  } catch (error) {
    if (import.meta.env.DEV) {
      console.warn("[pwa] Service worker kaydı başarısız:", error);
    }
  }
}

window.addEventListener(
  "load",
  () => {
    void registerV2ServiceWorker();
  },
  { once: true },
);
