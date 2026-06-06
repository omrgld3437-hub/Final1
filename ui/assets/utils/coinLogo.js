/**
 * Trust Wallet lokal coin logo – tek nokta helper.
 * Logolar: /ui/assets/coins/{SYMBOL}.png (flat). Fallback: initials.
 */
(function (global) {
    var COIN_LOGO_MAP = {
        XBT: "BTC",
        LUNA2: "LUNA",
        "1000SHIB": "SHIB"
    };

    /** Sadece "çift" ise quote sonekini kaldır (BTCUSDT→BTC). Tek başına stable/quote ise (USDT, FDUSD) olduğu gibi döndür. */
    var QUOTE_ONLY = ["USDT", "USDC", "FDUSD", "BUSD", "TUSD", "DAI", "USDP"];
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

    var missingKeys = typeof global !== 'undefined' && global.__logo404 ? global.__logo404 : (global.__logo404 = new Set());
    var NO_LOGO_KEYS = { MULTI: true };
    function getCoinLogoUrl(symbol) {
        var key = normalizeLogoSymbol(symbol);
        if (!key) return null;
        if (key === 'USD') return "/ui/assets/coins/USDT.png";
        if (NO_LOGO_KEYS[key] || missingKeys.has(key)) return null;
        return "/ui/assets/coins/" + key + ".png";
    }
    function registerLogo404(key) { if (key) missingKeys.add(String(key).toUpperCase()); }

    global.normalizeLogoSymbol = normalizeLogoSymbol;
    global.getCoinLogoUrl = getCoinLogoUrl;
    global.registerLogo404 = registerLogo404;
})(typeof window !== "undefined" ? window : this);
