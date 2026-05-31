/**
 * FILE: ui/assets/ticker.js
 * VERSION: v17
 * DATE: 2026-05-31
 * CHANGE: 24s % — API pricing/summary chg_pct alanları (poll-to-poll değil)
 */
(() => {
  if (window.__APP_PAGE__ !== "dashboard") return;
  if (typeof window !== "undefined" && window.innerWidth <= 1024) return;

  const CACHE_KEY = "tt_ticker_snap_v2";
  const CACHE_TTL_MS = 3600000;

  const ORDER = ["USDTTRY", "EURTRY", "GBPTRY", "GRAM_ALTIN_TRY", "ONS_ALTIN_USD"];
  const LABELS = {
    USDTTRY: "USD/TRY",
    EURTRY: "EUR/TRY",
    GBPTRY: "GBP/TRY",
    GRAM_ALTIN_TRY: "Gram Altın",
    ONS_ALTIN_USD: "Altın Ons",
  };

  const API_KEY_MAP = {
    USDTTRY: "usdtry",
    EURTRY: "eurtry",
    GBPTRY: "gbptry",
    GRAM_ALTIN_TRY: "gram_altin_tl",
    ONS_ALTIN_USD: "ons_altin_usd",
  };

  const CHG_API_KEY_MAP = {
    USDTTRY: "usdtry_chg_pct",
    EURTRY: "eurtry_chg_pct",
    GBPTRY: "gbptry_chg_pct",
    GRAM_ALTIN_TRY: "gram_altin_tl_chg_pct",
    ONS_ALTIN_USD: "ons_altin_usd_chg_pct",
  };

  const FX_KEYS = new Set(["USDTTRY", "EURTRY", "GBPTRY"]);
  const INT_KEYS = new Set(["GRAM_ALTIN_TRY", "ONS_ALTIN_USD"]);

  const state = {
    inFlight: false,
    prev: {},
    chgText: {},
    started: false,
    root: null,
    track: null,
    layoutSynced: false,
  };

  function loadCache() {
    try {
      const raw = sessionStorage.getItem(CACHE_KEY);
      if (!raw) return null;
      const o = JSON.parse(raw);
      if (!o || !o.values || !o.ts || Date.now() - o.ts > CACHE_TTL_MS) return null;
      return o;
    } catch (e) {
      return null;
    }
  }

  function saveCache() {
    try {
      const values = {};
      const chgs = {};
      for (const k of ORDER) {
        if (typeof state.prev[k] === "number") values[k] = state.prev[k];
        if (state.chgText[k]) chgs[k] = state.chgText[k];
      }
      if (!Object.keys(values).length) return;
      sessionStorage.setItem(CACHE_KEY, JSON.stringify({ ts: Date.now(), values, chgs }));
    } catch (e) {}
  }

  function hydrateFromCache() {
    const cached = loadCache();
    if (!cached) return false;
    let painted = false;
    for (const k of ORDER) {
      const v = toNum(cached.values[k]);
      if (v === null) continue;
      state.prev[k] = v;
      if (cached.chgs && cached.chgs[k]) state.chgText[k] = cached.chgs[k];
      updateItem(k, v, { fromCache: true });
      painted = true;
    }
    return painted;
  }

  function toNum(x) {
    if (x == null) return null;
    if (typeof x === "string") x = x.replace(",", ".");
    const v = Number(x);
    return Number.isFinite(v) ? v : null;
  }

  function fmtPrice(key, v) {
    if (v === null || v === undefined || (typeof v === "number" && (v <= 0 || !Number.isFinite(v)))) return "—";
    if (FX_KEYS.has(key)) {
      return Number(v).toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }
    if (INT_KEYS.has(key)) {
      return Math.floor(Number(v)).toLocaleString("tr-TR");
    }
    return String(v);
  }

  function fmtChgFromPct(pct) {
    if (pct == null || !Number.isFinite(Number(pct))) return { text: "—", dir: "" };
    const p = Number(pct);
    if (Math.abs(p) < 1e-9) return { text: "0.00%", dir: "up" };
    const sign = p >= 0 ? "+" : "";
    return { text: sign + p.toFixed(2) + "%", dir: p >= 0 ? "up" : "down" };
  }

  function fmtChg(prev, v) {
    if (prev == null || v == null || !(prev > 0)) return { text: "—", dir: "" };
    const pct = ((v - prev) / prev) * 100;
    if (!Number.isFinite(pct) || Math.abs(pct) < 1e-9) return { text: "0.00%", dir: "up" };
    const sign = pct >= 0 ? "+" : "";
    return { text: sign + pct.toFixed(2) + "%", dir: pct >= 0 ? "up" : "down" };
  }

  function ensureDom() {
    const root = document.getElementById("topTicker");
    if (!root || root.classList.contains("ticker-initialized")) return;

    state.root = root;
    root.classList.add("ticker-initialized");

    root.innerHTML =
      '<div class="zip-ticker-wrap zip-ticker-wrap--static">' +
      '<div class="zip-ticker-track" id="dashboardZipTicker" aria-live="polite"></div>' +
      "</div>";

    state.track = document.getElementById("dashboardZipTicker");
    if (!state.track) return;

    ORDER.forEach((k) => {
      const item = document.createElement("span");
      item.className = "zip-ticker-item";
      item.dataset.key = k;

      const sym = document.createElement("span");
      sym.className = "zip-ticker-item__sym";
      sym.textContent = LABELS[k] || k;

      const price = document.createElement("span");
      price.className = "zip-ticker-item__price";
      price.textContent = "—";

      const chg = document.createElement("span");
      chg.className = "zip-ticker-item__chg";
      chg.textContent = "—";

      item.appendChild(sym);
      item.appendChild(price);
      item.appendChild(chg);
      state.track.appendChild(item);
    });

    syncStickyOffset();
  }

  function mapTickerFallback(data) {
    if (!data || typeof data !== "object") return {};
    return {
      usdtry: data.USDTTRY ?? data.usdtry,
      eurtry: data.EURTRY ?? data.eurtry,
      gbptry: data.GBPTRY ?? data.gbptry,
      gram_altin_tl: data.GRAM_ALTIN_TRY ?? data.gram_altin_tl,
      ons_altin_usd: data.ONS_ALTIN_USD ?? data.ons_altin_usd,
    };
  }

  function applySummary(data) {
    let hasValue = false;
    let changed = false;
    for (const k of ORDER) {
      const apiKey = API_KEY_MAP[k];
      const raw = apiKey ? data[apiKey] : undefined;
      const v = toNum(raw);
      if (v !== null) hasValue = true;
      const chgKey = CHG_API_KEY_MAP[k];
      const chgPct = chgKey ? toNum(data[chgKey]) : null;
      if (updateItem(k, v, { chgPct: chgPct })) changed = true;
    }
    if (changed) saveCache();
    return hasValue;
  }

  function updateItem(key, v, opts) {
    opts = opts || {};
    const track = state.track;
    if (!track) return false;

    const prev = state.prev[key];
    if (v === null) return false;

    const priceText = fmtPrice(key, v);
    let chg;
    if (opts.chgPct != null && Number.isFinite(Number(opts.chgPct))) {
      chg = fmtChgFromPct(opts.chgPct);
    } else if (opts.fromCache && state.chgText[key]) {
      chg = { text: state.chgText[key], dir: String(state.chgText[key]).startsWith("-") ? "down" : "up" };
    } else {
      chg = fmtChg(typeof prev === "number" ? prev : null, v);
    }
    const chgClass = "zip-ticker-item__chg" + (chg.dir ? " " + chg.dir : "");
    let changed = false;

    track.querySelectorAll('.zip-ticker-item[data-key="' + key + '"]').forEach((item) => {
      const priceEl = item.querySelector(".zip-ticker-item__price");
      const chgEl = item.querySelector(".zip-ticker-item__chg");
      if (priceEl && priceEl.textContent !== priceText) {
        priceEl.textContent = priceText;
        changed = true;
      }
      if (chgEl && chg.text !== "—") {
        if (chgEl.textContent !== chg.text) {
          chgEl.textContent = chg.text;
          changed = true;
        }
        if (chgEl.className !== chgClass) chgEl.className = chgClass;
      }

      if (opts.fromCache) return;

      item.classList.remove("tick-up", "tick-down");
      if (typeof prev === "number" && v !== null && Math.abs(v - prev) > 1e-12) {
        changed = true;
        const tickClass = v > prev ? "tick-up" : "tick-down";
        item.classList.add(tickClass);
        item.addEventListener(
          "animationend",
          () => {
            item.classList.remove("tick-up", "tick-down");
          },
          { once: true }
        );
      }
    });

    if (v !== null) state.prev[key] = v;
    if (chg.text && chg.text !== "—") state.chgText[key] = chg.text;
    return changed;
  }

  function syncStickyOffset(force) {
    const root = state.root;
    if (!root) return;
    if (state.layoutSynced && !force) return;
    const h = Math.ceil(root.getBoundingClientRect().height || root.offsetHeight || 41);
    if (h >= 28) {
      document.documentElement.style.setProperty("--dashboard-ticker-height", h + "px");
      state.layoutSynced = true;
    }
  }

  async function refresh() {
    if (state.inFlight || !state.root) return;
    state.inFlight = true;

    try {
      let data = null;
      const apiClient = window.apiClient;
      try {
        if (apiClient && typeof apiClient.get === "function") {
          data = await apiClient.get("/api/pricing/summary", { timeout: 8000, suppressRateLimitToast: true });
        } else {
          const controller = new AbortController();
          const to = setTimeout(() => controller.abort(), 8000);
          const res = await fetch("/api/pricing/summary", { signal: controller.signal, cache: "no-store", credentials: "include" });
          clearTimeout(to);
          if (!res.ok) throw new Error("pricing/summary " + res.status);
          data = await res.json();
        }
      } catch (primaryErr) {
        console.warn("[ticker] pricing/summary failed, trying /api/ticker", primaryErr);
        const controller = new AbortController();
        const to = setTimeout(() => controller.abort(), 8000);
        const res = await fetch("/api/ticker", { signal: controller.signal, cache: "no-store", credentials: "include" });
        clearTimeout(to);
        if (!res.ok) throw primaryErr;
        data = mapTickerFallback(await res.json());
      }

      if (applySummary(data || {})) {
        syncStickyOffset(!state.layoutSynced);
      }
    } catch (e) {
      const reqId = e && e.request_id;
      if (reqId != null) console.warn("[ticker] pricing/summary error request_id:", reqId, e);
      else console.warn("[ticker] pricing/summary error:", e);
    } finally {
      state.inFlight = false;
    }
  }

  function start() {
    if (state.started) return;
    if (window.apiClient && typeof window.apiClient.hasToken === "function" && !window.apiClient.hasToken()) {
      setTimeout(start, 800);
      return;
    }
    state.started = true;

    ensureDom();
    if (!state.root) return;

    hydrateFromCache();
    syncStickyOffset(true);

    if (window.intervalRegistry && typeof window.intervalRegistry.stopByOwner === "function") {
      window.intervalRegistry.stopByOwner("header");
    }
    refresh();
    if (window.intervalRegistry && typeof window.intervalRegistry.start === "function") {
      window.intervalRegistry.start("pricing:summary", refresh, 5000, "header");
    } else {
      setInterval(refresh, 5000);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
})();
