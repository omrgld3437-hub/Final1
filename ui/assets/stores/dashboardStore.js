/**
 * Dashboard store — single source for boot data (prices, wallet, kpis).
 * Used by appBoot.js and dashboard. No tab/DOM gating.
 */
(function (root) {
    'use strict';

    var BOOT_V2_NAMESPACE = 'dashboardStore';

    var store = {
        prices: { status: 'loading', data: {}, error: null, request_id: null },
        wallet: { status: 'loading', data: null, error: null, request_id: null, wallet_status: null },
        kpis: { status: 'loading', data: {}, error: null, request_id: null },
        boot_request_id: null,
        boot_server_ms: null,
    };

    function setPrices(payload) {
        if (!payload || typeof payload !== 'object') return;
        store.prices.data = payload.prices || {};
        store.prices.status = Object.keys(store.prices.data).length ? 'ready' : (payload.prices_ready === false ? 'stale' : 'ready');
        store.prices.error = null;
        store.prices.request_id = payload.request_id || null;
    }

    function setWallet(payload) {
        if (!payload) return;
        var w = payload.wallet_cached;
        var err = payload.wallet_status && (payload.wallet_status.last_error_code || (!w && payload.wallet_status.keys_configured));
        store.wallet.data = w || null;
        store.wallet.wallet_status = payload.wallet_status || null;
        store.wallet.status = w ? 'ready' : (err ? 'error' : 'loading');
        store.wallet.error = !w && err ? { error_code: 'WALLET_NOT_READY', detail: 'No cached snapshot yet' } : null;
        store.wallet.request_id = payload.request_id || null;
    }

    function setKpis(payload) {
        if (!payload || typeof payload !== 'object') return;
        store.kpis.data = payload.kpis || {};
        store.kpis.status = 'ready';
        store.kpis.error = null;
        store.kpis.request_id = payload.request_id || null;
    }

    function setBootMeta(meta) {
        if (meta) {
            store.boot_request_id = meta.request_id || null;
            store.boot_server_ms = meta.server_ms != null ? meta.server_ms : null;
        }
    }

    function setError(section, error) {
        if (section === 'prices') {
            store.prices.status = 'error';
            store.prices.error = error || { error_code: 'PRICES_TIMEOUT' };
        } else if (section === 'wallet') {
            store.wallet.status = 'error';
            store.wallet.error = error || { error_code: 'WALLET_TIMEOUT' };
        } else if (section === 'kpis') {
            store.kpis.status = 'error';
            store.kpis.error = error || {};
        }
    }

    function getState() {
        return store;
    }

    function resetLoading() {
        store.prices.status = 'loading';
        store.prices.error = null;
        store.wallet.status = 'loading';
        store.wallet.error = null;
        store.kpis.status = 'loading';
        store.kpis.error = null;
    }

    root[BOOT_V2_NAMESPACE] = {
        getState: getState,
        setPrices: setPrices,
        setWallet: setWallet,
        setKpis: setKpis,
        setBootMeta: setBootMeta,
        setError: setError,
        resetLoading: resetLoading,
        store: store,
    };
})(typeof window !== 'undefined' ? window : {});
