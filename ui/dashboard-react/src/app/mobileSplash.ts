declare global {
  interface Window {
    __ayseroseSplashStartedAt?: number;
    __ayseroseSplashDismissRequested?: boolean;
    __ayseroseSplashShouldShow?: boolean;
  }
}

// 640 ms tam görünüm + 160 ms çıkış = her mobil girişte 0,8 saniye.
const SPLASH_HOLD_MS = 640;
const SPLASH_EXIT_MS = 160;

export function dismissMobileAppSplash(): void {
  const splash = document.getElementById("mobile-app-splash");
  if (!splash || window.__ayseroseSplashDismissRequested) return;
  window.__ayseroseSplashDismissRequested = true;

  if (
    !window.matchMedia("(max-width: 639px)").matches ||
    window.__ayseroseSplashShouldShow !== true
  ) {
    splash.remove();
    return;
  }

  const startedAt = Number(window.__ayseroseSplashStartedAt);
  const elapsed = Number.isFinite(startedAt)
    ? performance.now() - startedAt
    : SPLASH_HOLD_MS;
  window.setTimeout(() => {
    splash.classList.add("is-leaving");
    window.setTimeout(() => {
      splash.remove();
      document.documentElement.classList.remove("mobile-splash-pending");
    }, SPLASH_EXIT_MS);
  }, Math.max(0, SPLASH_HOLD_MS - elapsed));
}
