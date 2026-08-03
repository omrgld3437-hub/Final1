/**
 * Grid trailing dip/tepe — oturum tabanı (yalnızca min/max, asla ters yönde güncellenmez).
 * sessionStorage ile sayfa yenilemesinde dip zemin / tepe tavan korunur.
 */
(function (global) {
    'use strict';

    var _env = {
        buy: {},
        sell: {},
        profitReentry: null,
        profitExit: null,
        _loadedKey: null
    };
    var MAX_TRUSTED_PRICE_FACTOR = 20;

    function storageKey(botId, cycleId) {
        return 'gridTrailFloor_' + String(botId || '') + '_' + String(cycleId != null ? cycleId : '0');
    }

    function loadFromStorage(botId, cycleId) {
        var key = storageKey(botId, cycleId);
        if (_env._loadedKey === String(botId) + ':' + String(cycleId)) return;
        _env.buy = {};
        _env.sell = {};
        _env.profitReentry = null;
        _env.profitExit = null;
        try {
            var raw = sessionStorage.getItem(key);
            if (raw) {
                var data = JSON.parse(raw);
                if (data && typeof data === 'object') {
                    _env.buy = data.buy && typeof data.buy === 'object' ? data.buy : {};
                    _env.sell = data.sell && typeof data.sell === 'object' ? data.sell : {};
                    _env.profitReentry = data.profitReentry != null ? Number(data.profitReentry) : null;
                    _env.profitExit = data.profitExit != null ? Number(data.profitExit) : null;
                }
            }
        } catch (e) { /* ignore */ }
        _env._loadedKey = String(botId) + ':' + String(cycleId);
    }

    function saveToStorage(botId, cycleId) {
        if (!botId) return;
        try {
            sessionStorage.setItem(storageKey(botId, cycleId), JSON.stringify({
                buy: _env.buy,
                sell: _env.sell,
                profitReentry: _env.profitReentry,
                profitExit: _env.profitExit
            }));
        } catch (e) { /* ignore */ }
    }

    function resetSession() {
        _env.buy = {};
        _env.sell = {};
        _env.profitReentry = null;
        _env.profitExit = null;
        _env._loadedKey = null;
    }

    function sanitizeStoredPrice(value, trustedValues) {
        var n = Number(value);
        if (!Number.isFinite(n) || n <= 0) return null;
        var trusted = null;
        (trustedValues || []).some(function (candidate) {
            var v = Number(candidate);
            if (!Number.isFinite(v) || v <= 0) return false;
            trusted = v;
            return true;
        });
        if (trusted == null) return n;
        var ratio = n / trusted;
        if (ratio > MAX_TRUSTED_PRICE_FACTOR || ratio < 1 / MAX_TRUSTED_PRICE_FACTOR) {
            return null;
        }
        return n;
    }

    function mergeBuyFloor(cur, base, livePrice, applyLive) {
        var v = (cur != null && !isNaN(Number(cur))) ? Number(cur) : null;
        if (base != null && !isNaN(Number(base)) && Number(base) > 0) {
            v = v == null ? Number(base) : Math.min(v, Number(base));
        }
        if (applyLive && livePrice != null && !isNaN(Number(livePrice)) && Number(livePrice) > 0) {
            v = v == null ? Number(livePrice) : Math.min(v, Number(livePrice));
        }
        return v;
    }

    function mergeSellCeiling(cur, base, livePrice, applyLive) {
        var v = (cur != null && !isNaN(Number(cur))) ? Number(cur) : null;
        if (base != null && !isNaN(Number(base)) && Number(base) > 0) {
            v = v == null ? Number(base) : Math.max(v, Number(base));
        }
        if (applyLive && livePrice != null && !isNaN(Number(livePrice)) && Number(livePrice) > 0) {
            v = v == null ? Number(livePrice) : Math.max(v, Number(livePrice));
        }
        return v;
    }

    function syncGridTrailEnvelope(botId, cycleId, sellPoints, buyPoints, livePrice, applyLive) {
        if (botId != null) loadFromStorage(botId, cycleId);
        (sellPoints || []).forEach(function (p) {
            if (p.fired || (p.anchor == null && p.trigger_hit_price == null)) return;
            var base = p.anchor != null && !isNaN(Number(p.anchor)) ? Number(p.anchor) : null;
            var stored = sanitizeStoredPrice(
                _env.sell[p.i],
                [base, p.trigger_hit_price, p.trigger_price]
            );
            var cur = mergeSellCeiling(stored, base, livePrice, applyLive);
            if (cur != null) _env.sell[p.i] = cur;
        });
        (buyPoints || []).forEach(function (p) {
            if (p.fired || (p.anchor == null && p.trigger_hit_price == null)) return;
            var base = p.anchor != null && !isNaN(Number(p.anchor)) ? Number(p.anchor) : null;
            var stored = sanitizeStoredPrice(
                _env.buy[p.i],
                [base, p.trigger_hit_price, p.trigger_price]
            );
            var cur = mergeBuyFloor(stored, base, livePrice, applyLive);
            if (cur != null) _env.buy[p.i] = cur;
        });
        if (botId != null) saveToStorage(botId, cycleId);
    }

    function syncProfitTrailEnvelope(botId, cycleId, pps, livePrice, applyLive) {
        if (botId != null) loadFromStorage(botId, cycleId);
        (pps || []).forEach(function (p) {
            if (!p.trigger_hit) return;
            if (p.type === 'reentry' && p.dip != null) {
                var base = Number(p.dip);
                _env.profitReentry = sanitizeStoredPrice(
                    _env.profitReentry,
                    [base, p.trigger_price]
                );
                _env.profitReentry = mergeBuyFloor(_env.profitReentry, base, livePrice, applyLive);
            } else if (p.type !== 'reentry' && p.tepe != null) {
                var baseT = Number(p.tepe);
                _env.profitExit = sanitizeStoredPrice(
                    _env.profitExit,
                    [baseT, p.trigger_price]
                );
                _env.profitExit = mergeSellCeiling(_env.profitExit, baseT, livePrice, applyLive);
            }
        });
        if (botId != null) saveToStorage(botId, cycleId);
    }

    function trailDisplayFromEnvelope(p, side, trailPct) {
        if (p.fired) return { anchor: p.anchor, exec: p.execution_price };
        if (p.anchor == null && p.trigger_hit_price == null) {
            return { anchor: p.anchor, exec: p.execution_price };
        }
        var store = side === 'buy' ? _env.buy : _env.sell;
        var stored = store[p.i] != null && !isNaN(Number(store[p.i])) ? Number(store[p.i]) : null;
        var server = p.anchor != null && !isNaN(Number(p.anchor)) ? Number(p.anchor) : null;
        var anchor = stored != null ? stored : server;
        if (stored != null && server != null) {
            anchor = side === 'buy' ? Math.min(stored, server) : Math.max(stored, server);
        }
        if (anchor == null) return { anchor: null, exec: p.execution_price };
        var exec = side === 'buy'
            ? anchor * (1 + (trailPct || 0.3) / 100)
            : anchor * (1 - (trailPct || 0.3) / 100);
        return { anchor: anchor, exec: exec };
    }

    function profitTrailDisplay(p, side, trailPct) {
        var stored = p.type === 'reentry' ? _env.profitReentry : _env.profitExit;
        var server = p.type === 'reentry'
            ? (p.dip != null && !isNaN(Number(p.dip)) ? Number(p.dip) : null)
            : (p.tepe != null && !isNaN(Number(p.tepe)) ? Number(p.tepe) : null);
        var anchor = stored != null && !isNaN(Number(stored)) ? Number(stored) : server;
        if (stored != null && server != null) {
            anchor = p.type === 'reentry' ? Math.min(Number(stored), server) : Math.max(Number(stored), server);
        }
        if (anchor == null) return { anchor: null, exec: p.execution_price };
        var exec = side === 'buy'
            ? anchor * (1 + (trailPct || 0.3) / 100)
            : anchor * (1 - (trailPct || 0.3) / 100);
        return { anchor: anchor, exec: exec };
    }

    global.GridTrailEnvelope = {
        syncGridTrailEnvelope: syncGridTrailEnvelope,
        syncProfitTrailEnvelope: syncProfitTrailEnvelope,
        trailDisplayFromEnvelope: trailDisplayFromEnvelope,
        profitTrailDisplay: profitTrailDisplay,
        resetSession: resetSession
    };
})(typeof window !== 'undefined' ? window : globalThis);
