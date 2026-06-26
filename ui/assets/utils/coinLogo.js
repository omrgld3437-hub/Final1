/**
 * Coin logo helper — lokal PNG + on-demand fetch + baş harf fallback.
 * Logolar: /ui/assets/coins/{SYMBOL}.png
 */
(function (global) {
    var COIN_LOGO_MAP = {
        XBT: "BTC",
        LUNA2: "LUNA",
        "1000SHIB": "SHIB"
    };

    var QUOTE_ONLY = ["USDT", "USDC", "FDUSD", "BUSD", "TUSD", "DAI", "USDP"];
    var LS_OK = "tt_coin_logos_ok_v2";
    var LS_VER = "tt_coin_logos_schema";
    var LS_SCHEMA = "3";
    var sessionMissing = typeof global !== 'undefined' && global.__logo404 ? global.__logo404 : (global.__logo404 = new Set());
    var pendingFetch = typeof global !== 'undefined' && global.__logoFetch ? global.__logoFetch : (global.__logoFetch = new Set());
    var NO_LOGO_KEYS = { MULTI: true };

    try {
        if (localStorage.getItem(LS_VER) !== LS_SCHEMA) {
            localStorage.removeItem("tt_coin_logos_ok");
            localStorage.removeItem("tt_coin_logos_missing");
            localStorage.removeItem("tt_coin_logos_ok_v2");
            localStorage.setItem(LS_VER, LS_SCHEMA);
        }
    } catch (e) { /* private mode */ }

    function _loadOkSet() {
        try {
            var raw = localStorage.getItem(LS_OK);
            if (!raw) return new Set();
            var arr = JSON.parse(raw);
            return new Set(Array.isArray(arr) ? arr : []);
        } catch (e) {
            return new Set();
        }
    }

    function _saveOkSet(set) {
        try {
            localStorage.setItem(LS_OK, JSON.stringify(Array.from(set)));
        } catch (e) { /* ignore */ }
    }

    var confirmedKeys = _loadOkSet();

    function normalizeLogoSymbol(symbol) {
        if (!symbol) return null;
        var s = String(symbol).toUpperCase().trim();
        if (QUOTE_ONLY.indexOf(s) >= 0) return s;
        if (s.endsWith("USDT")) s = s.replace(/USDT$/i, "");
        else if (s.endsWith("USDC")) s = s.replace(/USDC$/i, "");
        else if (s.endsWith("FDUSD")) s = s.replace(/FDUSD$/i, "");
        else if (s.endsWith("BUSD")) s = s.replace(/BUSD$/i, "");
        else if (s.endsWith("TUSD")) s = s.replace(/TUSD$/i, "");
        else if (s.endsWith("DAI")) s = s.replace(/DAI$/i, "");
        return (COIN_LOGO_MAP[s] || s || null);
    }

    function getCoinLogoInitials(symbol) {
        var key = normalizeLogoSymbol(symbol);
        if (!key) return "?";
        return key.substring(0, 1).toUpperCase();
    }

    function isLogoConfirmed(symbol) {
        var key = normalizeLogoSymbol(symbol);
        return !!(key && confirmedKeys.has(key));
    }

    function markLogoConfirmed(symbol) {
        var key = normalizeLogoSymbol(symbol);
        if (!key) return;
        confirmedKeys.add(key);
        sessionMissing.delete(key);
        _saveOkSet(confirmedKeys);
        var url = getCoinLogoUrl(key);
        if (url && global.coinLogoCache) global.coinLogoCache.set(url, true);
    }

    /** Her zaman PNG yolunu döndür — missing listesi URL'i gizlemez. */
    function getCoinLogoUrl(symbol) {
        var key = normalizeLogoSymbol(symbol);
        if (!key) return null;
        if (key === "USD") return "/ui/assets/coins/USDT.png";
        if (NO_LOGO_KEYS[key]) return null;
        return "/ui/assets/coins/" + key + ".png";
    }

    function shouldEagerLoadLogo(symbol) {
        var key = normalizeLogoSymbol(symbol);
        if (!key) return false;
        if (isLogoConfirmed(key)) return true;
        var url = getCoinLogoUrl(key);
        return !!(url && global.coinLogoCache && global.coinLogoCache.get(url));
    }

    /** Sadece bu oturumda img onerror sonrası — localStorage'a yazılmaz. */
    function registerLogo404(key) {
        if (!key) return;
        sessionMissing.add(String(key).toUpperCase());
    }

    function markCoinLogoLoaded(img) {
        if (!img) return;
        var key = img.getAttribute("data-symbol") || img.getAttribute("alt") || "";
        markLogoConfirmed(key);
        var src = (img.currentSrc || img.src || "").split("?")[0];
        if (src && global.coinLogoCache) global.coinLogoCache.set(src, true);
    }

    function ensureCoinLogo(symbol, cb) {
        var key = normalizeLogoSymbol(symbol);
        if (!key || NO_LOGO_KEYS[key] || pendingFetch.has(key) || sessionMissing.has(key)) return;
        pendingFetch.add(key);
        fetch("/api/coins/logo/ensure?symbol=" + encodeURIComponent(key), { credentials: "same-origin" })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (data) {
                pendingFetch.delete(key);
                if (data && data.ok && data.url) {
                    markLogoConfirmed(key);
                    if (typeof cb === "function") cb(data.url, key);
                } else {
                    registerLogo404(key);
                }
            })
            .catch(function () {
                pendingFetch.delete(key);
                registerLogo404(key);
            });
    }

    function showCoinLogoInitials(img) {
        if (!img) return;
        img.style.display = "none";
        var initials = img.nextElementSibling;
        if (initials && initials.classList) {
            if (initials.classList.contains("varlik-logo-initials") ||
                initials.classList.contains("mevcut-bot-logo-initials") ||
                initials.classList.contains("global-leaderboard-symbol-initials") ||
                initials.classList.contains("bot-logo-initials")) {
                initials.style.display = initials.classList.contains("mevcut-bot-logo-initials") ? "inline-flex" : "flex";
                return;
            }
        }
        var wrap = img.parentElement;
        if (wrap && !initials) {
            var span = document.createElement("span");
            span.className = "varlik-logo-initials coin-logo-initials-fallback";
            span.textContent = getCoinLogoInitials(img.getAttribute("alt") || img.getAttribute("data-symbol") || "");
            span.style.display = "flex";
            wrap.appendChild(span);
        }
    }

    function handleCoinLogoError(img) {
        if (!img) return;
        var key = img.getAttribute("alt") || img.getAttribute("data-symbol") || "";
        var norm = normalizeLogoSymbol(key) || key;

        if (img.dataset.logoRetried !== "1" && norm) {
            img.dataset.logoRetried = "1";
            img.style.display = "";
            img.src = "/ui/assets/coins/" + norm + ".png";
            return;
        }

        if (img.dataset.logoFailed === "1") return;
        img.dataset.logoFailed = "1";
        registerLogo404(norm);
        showCoinLogoInitials(img);
    }

    function buildCoinLogoHtml(symbol, opts) {
        opts = opts || {};
        var initials = getCoinLogoInitials(symbol);
        var url = getCoinLogoUrl(symbol);
        var wrapCls = opts.wrapClass || "";
        var style = opts.style || "";
        if (!url) {
            return '<span class="varlik-logo-initials' + (wrapCls ? " " + wrapCls : "") + '" style="display:flex;' + style + '">' + initials + "</span>";
        }
        var onload = "if(window.markCoinLogoLoaded)window.markCoinLogoLoaded(this)";
        var onerr = "if(window.handleCoinLogoError)window.handleCoinLogoError(this)";
        var lazy = !(opts.eager === true || shouldEagerLoadLogo(symbol));
        return '<span class="coin-logo-wrap' + (wrapCls ? " " + wrapCls : "") + '" style="position:relative;display:inline-flex;align-items:center;justify-content:center;' + style + '">' +
            '<img src="' + url + '" alt="' + (normalizeLogoSymbol(symbol) || "") + '" data-symbol="' + (normalizeLogoSymbol(symbol) || "") + '" decoding="async" onload="' + onload + '" onerror="' + onerr + '"' + (lazy ? ' loading="lazy"' : "") + ' style="width:100%;height:100%;object-fit:cover;" />' +
            '<span class="varlik-logo-initials" style="display:none;position:absolute;inset:0;align-items:center;justify-content:center;font-weight:600;background:var(--ds-bg-tertiary,#2a2a2e);color:var(--ds-text-secondary,#aaa);border-radius:50%;">' + initials + "</span></span>";
    }

    global.normalizeLogoSymbol = normalizeLogoSymbol;
    global.getCoinLogoUrl = getCoinLogoUrl;
    global.getCoinLogoInitials = getCoinLogoInitials;
    global.isLogoConfirmed = isLogoConfirmed;
    global.shouldEagerLoadLogo = shouldEagerLoadLogo;
    global.markLogoConfirmed = markLogoConfirmed;
    global.markCoinLogoLoaded = markCoinLogoLoaded;
    global.registerLogo404 = registerLogo404;
    global.ensureCoinLogo = ensureCoinLogo;
    global.handleCoinLogoError = handleCoinLogoError;
    global.buildCoinLogoHtml = buildCoinLogoHtml;
})(typeof window !== "undefined" ? window : this);
