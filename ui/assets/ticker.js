/**
 * FILE: ui/assets/ticker.js
 * VERSION: v12
 * DATE: 2026-01-25
 * CHANGE: Canlı fiyat GET /api/pricing/summary, apiClient + intervalRegistry, 0 gösterme
 */
(() => {
  if (window.__APP_PAGE__ !== 'dashboard') return;
  if (typeof window !== 'undefined' && window.innerWidth <= 1024) return;
  if (window.apiClient && typeof window.apiClient.hasToken === 'function' && !window.apiClient.hasToken()) return;
  const ORDER = ["USDTTRY","EURTRY","GBPTRY","BTCUSD","ETHUSD","GRAM_ALTIN_TRY","ONS_ALTIN_USD"];
  const LABELS = {
    USDTTRY: "USD, TRY",
    EURTRY: "EUR, TRY",
    GBPTRY: "GBP, TRY",
    BTCUSD: "BTC, USD",
    ETHUSD: "ETH, USD",
    GRAM_ALTIN_TRY: "Gram altın",
    ONS_ALTIN_USD: "Altın ons"
  };

  /** Backend /api/pricing/summary döner: usdtry, eurtry, gbptry, btcusd, ethusd, gram_altin_tl, ons_altin_usd */
  const API_KEY_MAP = {
    USDTTRY: "usdtry",
    EURTRY: "eurtry",
    GBPTRY: "gbptry",
    BTCUSD: "btcusd",
    ETHUSD: "ethusd",
    GRAM_ALTIN_TRY: "gram_altin_tl",
    ONS_ALTIN_USD: "ons_altin_usd"
  };

  const ONE_MINUTE_MS = 60 * 1000;

  const state = {
    inFlight: false,
    prev: {},
    els: {},
    started: false,
    root: null,
    lastSuccessAt: 0
  };

  function formatLastUpdate(ts) {
    const d = new Date(ts);
    return d.toLocaleString("tr-TR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Istanbul" });
  }

  function updateLiveLineText() {
    const liveLineEl = document.getElementById("tickerLiveLine");
    if (!liveLineEl) return;
    const now = Date.now();
    if (!state.lastSuccessAt) {
      liveLineEl.textContent = "Canlı yükleniyor...";
      return;
    }
    if (now - state.lastSuccessAt <= ONE_MINUTE_MS) {
      liveLineEl.textContent = "Canlı";
    } else {
      liveLineEl.textContent = "Son güncelleme " + formatLastUpdate(state.lastSuccessAt);
    }
  }

  function toNum(x) {
    if (x == null) return null;
    if (typeof x === "string") x = x.replace(",", ".");
    const v = Number(x);
    return Number.isFinite(v) ? v : null;
  }

  function fmt(key, v) {
    if (v === null || v === undefined || (typeof v === "number" && (v <= 0 || !Number.isFinite(v)))) return "—";
    /* Dövizler (USD/TRY, EUR/TRY, GBP/TRY): Türkçe biçim, virgülle ondalık (örn. 59,07 veya 59.070,50) */
    if (key === "USDTTRY" || key === "EURTRY" || key === "GBPTRY") return Number(v).toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    /* BTC, ETH, gram altın, ons altın: virgülsüz tam sayı (örn. 87809) */
    if (key === "BTCUSD" || key === "ETHUSD" || key === "GRAM_ALTIN_TRY" || key === "ONS_ALTIN_USD") return Math.floor(Number(v)).toLocaleString("tr-TR");
    return String(v);
  }

  function ensureDom() {
    const root = document.getElementById("topTicker");
    if (!root) return;
    if (root.classList.contains("ticker-initialized")) return;

    state.root = root;
    root.classList.add("ticker-initialized");

    const inner = document.createElement("div");
    inner.className = "top-ticker-inner";

    const row = document.createElement("div");
    row.className = "top-ticker-row";

    ORDER.forEach((k) => {
      const item = document.createElement("div");
      item.className = "tick";
      item.dataset.key = k;

      const lab = document.createElement("span");
      lab.className = "tick-label";
      lab.textContent = LABELS[k] || k;

      const val = document.createElement("span");
      val.className = "tick-val";
      val.textContent = "—";

      const pct = document.createElement("span");
      pct.className = "tick-pct";
      pct.textContent = "";
      pct.style.display = "none";

      item.appendChild(lab);
      item.appendChild(val);
      item.appendChild(pct);
      row.appendChild(item);

      state.els[k] = { item, val, pct };
    });

    const liveLine = document.createElement("div");
    liveLine.className = "ticker-live-line";
    liveLine.id = "tickerLiveLine";
    liveLine.setAttribute("aria-live", "polite");
    liveLine.textContent = "Canlı yükleniyor...";

    const topRow = document.createElement("div");
    topRow.className = "top-ticker-top-row";
    topRow.appendChild(row);
    inner.appendChild(topRow);
    inner.appendChild(liveLine);
    root.appendChild(inner);
  }

  async function refresh() {
    if (state.inFlight || !state.root) return;
    state.inFlight = true;

    const tickerEl = state.root;

    try {
      if (tickerEl) {
        tickerEl.classList.remove("pulse");
        void tickerEl.offsetWidth;
        tickerEl.classList.add("pulse");
        setTimeout(() => tickerEl.classList.remove("pulse"), 320);
      }

      let data;
      const apiClient = window.apiClient;
      if (apiClient && typeof apiClient.get === "function") {
        data = await apiClient.get("/api/pricing/summary", { timeout: 8000 });
      } else {
        const controller = new AbortController();
        const to = setTimeout(() => controller.abort(), 8000);
        const res = await fetch("/api/pricing/summary", { signal: controller.signal, cache: "no-store" });
        clearTimeout(to);
        if (!res.ok) throw new Error("pricing/summary " + res.status);
        data = await res.json();
      }

      for (const k of ORDER) {
        const el = state.els[k];
        if (!el || !el.val) continue;

        const apiKey = API_KEY_MAP[k];
        const raw = apiKey ? data[apiKey] : undefined;
        const v = toNum(raw);
        el.val.textContent = fmt(k, v);

        if (v !== null) {
          const prev = state.prev[k];
          el.item.classList.remove("up", "down");
          el.val.classList.remove("up", "down", "same");
          if (typeof prev === "number" && prev > 0 && Math.abs(v - prev) > 1e-12) {
            if (v > prev) {
              el.item.classList.add("up");
              el.val.classList.add("up");
            } else if (v < prev) {
              el.item.classList.add("down");
              el.val.classList.add("down");
            }
            el.item.classList.remove("tick-update");
            void el.item.offsetWidth;
            el.item.classList.add("tick-update");
            setTimeout(() => el.item.classList.remove("tick-update"), 650);
          } else {
            el.val.classList.add("same");
          }
          state.prev[k] = v;
        }
        if (k === "BTCUSD") el.item.classList.add("active");
        else el.item.classList.remove("active");
      }
      state.lastSuccessAt = Date.now();
      updateLiveLineText();
    } catch (e) {
      updateLiveLineText();
      const reqId = e && e.request_id;
      if (reqId != null) console.warn("[ticker] pricing/summary error request_id:", reqId, e);
      else console.warn("[ticker] pricing/summary error:", e);
      // Son değerleri koru; UI'da "—" yapma
    } finally {
      state.inFlight = false;
    }
  }

  function start() {
    if (state.started) return;
    if (window.apiClient && typeof window.apiClient.hasToken === 'function' && !window.apiClient.hasToken()) {
      setTimeout(start, 800);
      return;
    }
    state.started = true;

    ensureDom();
    if (!state.root) return;

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
