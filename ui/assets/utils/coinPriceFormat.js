/**
 * coinPriceFormat.js — sembol tick size + fiyat büyüklüğüne göre dinamik ondalık.
 * PEPE gibi düşük fiyatlı paritelerde 0.0000 yerine anlamlı basamak gösterir.
 */
(function (global) {
    'use strict';

    var _tickDecimalsBySymbol = {};

    function decimalPlacesFromTickSize(tickSize) {
        if (tickSize == null || tickSize === '') return null;
        var s = String(tickSize).trim();
        var t = Number(s);
        if (!Number.isFinite(t) || t <= 0) return null;
        if (t >= 1) return 0;
        if (/e/i.test(s)) {
            var em = s.match(/e-?(\d+)/i);
            if (em) return Math.min(8, parseInt(em[1], 10));
        }
        var parts = s.split('.');
        if (parts.length < 2) return 0;
        var frac = parts[1].replace(/0+$/, '');
        return Math.min(8, frac.length || parts[1].length);
    }

    function inferPriceDecimalsFromMagnitude(price) {
        var p = Number(price);
        if (!Number.isFinite(p) || p <= 0) return 8;
        if (p >= 1000) return 2;
        if (p >= 100) return 3;
        if (p >= 1) return 4;
        if (p >= 0.1) return 4;
        if (p >= 0.01) return 5;
        if (p >= 0.001) return 6;
        if (p >= 0.0001) return 7;
        return 8;
    }

    function decimalsNeededToDiffer(a, b, minDec) {
        minDec = minDec != null ? minDec : 2;
        var x = Number(a);
        var y = Number(b);
        if (!Number.isFinite(x) || !Number.isFinite(y)) return minDec;
        for (var d = minDec; d <= 8; d++) {
            if (x.toFixed(d) !== y.toFixed(d)) return d;
        }
        return 8;
    }

    function positiveHints(priceHints) {
        var out = [];
        (priceHints || []).forEach(function (h) {
            var v = Number(h);
            if (Number.isFinite(v) && v > 0) out.push(v);
        });
        return out;
    }

    function resolvePriceDecimals(symbol, priceHints) {
        symbol = String(symbol || '').toUpperCase();
        var hints = positiveHints(priceHints);
        var dec = null;

        if (symbol && _tickDecimalsBySymbol[symbol] != null) {
            dec = _tickDecimalsBySymbol[symbol];
        }

        hints.forEach(function (v) {
            var need = inferPriceDecimalsFromMagnitude(v);
            dec = dec != null ? Math.max(dec, need) : need;
        });

        if (hints.length >= 2) {
            for (var i = 1; i < hints.length; i++) {
                dec = Math.max(dec || 2, decimalsNeededToDiffer(hints[0], hints[i], dec || 2));
            }
        }

        if (dec == null) dec = 8;
        return Math.min(8, Math.max(2, dec));
    }

    function setSymbolTickDecimals(symbol, tickSize) {
        symbol = String(symbol || '').toUpperCase();
        if (!symbol) return;
        var d = decimalPlacesFromTickSize(tickSize);
        if (d != null) _tickDecimalsBySymbol[symbol] = Math.min(8, d);
    }

    function getSymbolTickDecimals(symbol) {
        symbol = String(symbol || '').toUpperCase();
        return _tickDecimalsBySymbol[symbol] != null ? _tickDecimalsBySymbol[symbol] : null;
    }

    function ensureSymbolTickDecimals(symbol, accountId, onLoaded) {
        symbol = String(symbol || '').toUpperCase();
        if (!symbol || !accountId || _tickDecimalsBySymbol[symbol] != null) {
            if (typeof onLoaded === 'function') onLoaded();
            return;
        }
        if (!global.apiClient || typeof global.apiClient.get !== 'function') {
            if (typeof onLoaded === 'function') onLoaded();
            return;
        }
        global.apiClient.get(
            '/api/spot/quick_data?account_id=' + encodeURIComponent(accountId) +
            '&symbol=' + encodeURIComponent(symbol)
        ).then(function (r) {
            if (r && r.filters) setSymbolTickDecimals(symbol, r.filters.tickSize);
            if (typeof onLoaded === 'function') onLoaded();
        }).catch(function () {
            if (typeof onLoaded === 'function') onLoaded();
        });
    }

    function fmtPriceValue(price, decimals) {
        if (price == null || price === '' || isNaN(price)) return '—';
        var n = Number(price);
        if (!Number.isFinite(n)) return '—';
        var dec = decimals != null ? decimals : 8;
        return n.toLocaleString('en-US', {
            minimumFractionDigits: dec,
            maximumFractionDigits: dec
        });
    }

    function fmtSymbolPrice(price, symbol, priceHints) {
        var hints = positiveHints([price].concat(priceHints || []));
        var dec = resolvePriceDecimals(symbol, hints);
        return fmtPriceValue(price, dec);
    }

    function fmtSymbolPriceFixed(price, symbol, priceHints) {
        if (price == null || price === '' || isNaN(price)) return '—';
        var n = Number(price);
        if (!Number.isFinite(n)) return '—';
        var hints = positiveHints([price].concat(priceHints || []));
        var dec = resolvePriceDecimals(symbol, hints);
        return n.toFixed(dec);
    }

    var CoinPriceFormat = {
        decimalPlacesFromTickSize: decimalPlacesFromTickSize,
        inferPriceDecimalsFromMagnitude: inferPriceDecimalsFromMagnitude,
        decimalsNeededToDiffer: decimalsNeededToDiffer,
        resolvePriceDecimals: resolvePriceDecimals,
        setSymbolTickDecimals: setSymbolTickDecimals,
        getSymbolTickDecimals: getSymbolTickDecimals,
        ensureSymbolTickDecimals: ensureSymbolTickDecimals,
        fmtPriceValue: fmtPriceValue,
        fmtSymbolPrice: fmtSymbolPrice,
        fmtSymbolPriceFixed: fmtSymbolPriceFixed
    };

    global.CoinPriceFormat = CoinPriceFormat;
})(typeof window !== 'undefined' ? window : global);
