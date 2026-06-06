# Patch H: Flash Home (mobile-first)

## Goal
Homepage renders meaningful content in **< 300ms (warm)** and **< 1s (cold)** without waiting for Binance wallet. Binance wallet is refreshed in the background with TTL + dedup to avoid storms.

## Setup
- `FLASH_HOME_ENABLED=true` (default)
- Optional: `HOME_FAST_CACHE_TTL_SEC=2`, `WALLET_LIVE_TTL_SEC=5`, `WALLET_COOLDOWN_SEC=30`

## Endpoints
- **GET /api/home/config** – feature flag + refresh policy (no auth)
- **GET /api/home/fast?account_id=N** – cached only, NO Binance
- **POST /api/home/wallet/refresh?account_id=N&force=0|1** – may call Binance (dedup + TTL)
- **GET /api/home/wallet/status?account_id=N** – inflight, last_live_at, cooldown

## Manual test steps

### 1. Cold load
- Clear localStorage (or use incognito).
- Open dashboard. **Expected:** Skeleton or “Yükleniyor” then cached/fast data within ~1s. Wallet may show “Güncelleniyor…” then update when refresh completes.

### 2. Warm load
- Reload dashboard (same session). **Expected:** Cached wallet from localStorage or fast cache appears quickly (< 200ms for cached block).

### 3. Network throttling (Slow 3G)
- DevTools → Network → Slow 3G. Open dashboard. **Expected:** Cached data (if any) shows first; fast endpoint returns when network allows; no UI lock.

### 4. Refresh button
- Click “Yenile” on wallet panel. **Expected:** One POST to `/api/home/wallet/refresh?account_id=…&force=1`. If within TTL/cooldown, backend may return `skipped: true`; otherwise wallet updates.

### 5. No Binance on critical path
- In Network tab, open dashboard. **Expected:** First request is GET `/api/home/fast` (no Binance). Then 0–1 POST `/api/home/wallet/refresh`. No GET to Binance wallet as part of initial paint.

### 6. Repeated opens
- Open dashboard, wait 2s, reload, reload again within 5s. **Expected:** Second/third load should not trigger multiple wallet refresh calls (TTL/dedup).

## Rollback
- Set `FLASH_HOME_ENABLED=false`. UI will use legacy snapshot path (fetchSnapshot on load).
- Backend endpoints remain; they are simply not used when flag is false.

## Expected: Home usable in < 1s
- First meaningful paint (cached or fast payload): **< 1s** on slow network.
- With warm cache: **< 300ms**.
