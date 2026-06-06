/**
 * Flash Home – localStorage cache for last-known wallet/prices (Patch H).
 * Key: tt_home_cache_v1:{accountId}
 * Schema: { schema_version, wallet_cached, wallet_cached_at, prices, kpis, stored_at }
 */
(function (root, factory) {
    if (typeof define === 'function' && define.amd) {
        define([], factory);
    } else if (typeof module === 'object' && module.exports) {
        module.exports = factory();
    } else {
        root.storageCache = factory();
    }
})(typeof self !== 'undefined' ? self : this, function () {
    'use strict';

    var SCHEMA_VERSION = 1;
    var MAX_AGE_MS = 30 * 60 * 1000; // 30 minutes – render instantly if within this

    function key(accountId) {
        return 'tt_home_cache_v1:' + (accountId || '');
    }

    function load(accountId) {
        try {
            var k = key(accountId);
            var raw = typeof localStorage !== 'undefined' ? localStorage.getItem(k) : null;
            if (!raw) return null;
            var data = JSON.parse(raw);
            if (!data || data.schema_version !== SCHEMA_VERSION) return null;
            var storedAt = data.stored_at;
            if (typeof storedAt !== 'number' || isNaN(storedAt)) return null;
            if (Date.now() - storedAt > MAX_AGE_MS) return null;
            return data;
        } catch (e) {
            return null;
        }
    }

    function save(accountId, payload) {
        try {
            if (typeof localStorage === 'undefined') return;
            var data = {
                schema_version: SCHEMA_VERSION,
                wallet_cached: payload.wallet_cached || null,
                wallet_cached_at: payload.wallet_cached_at || null,
                prices: payload.prices || null,
                kpis: payload.kpis || null,
                stored_at: Date.now()
            };
            localStorage.setItem(key(accountId), JSON.stringify(data));
        } catch (e) {}
    }

    function mergeSaved(accountId, update) {
        try {
            var cur = load(accountId) || {};
            var data = {
                schema_version: SCHEMA_VERSION,
                wallet_cached: update.wallet_cached !== undefined ? update.wallet_cached : cur.wallet_cached,
                wallet_cached_at: update.wallet_cached_at !== undefined ? update.wallet_cached_at : cur.wallet_cached_at,
                prices: update.prices !== undefined ? update.prices : cur.prices,
                kpis: update.kpis !== undefined ? update.kpis : cur.kpis,
                stored_at: Date.now()
            };
            localStorage.setItem(key(accountId), JSON.stringify(data));
        } catch (e) {}
    }

    return {
        load: load,
        save: save,
        mergeSaved: mergeSaved,
        SCHEMA_VERSION: SCHEMA_VERSION,
        MAX_AGE_MS: MAX_AGE_MS
    };
});
