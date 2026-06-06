/**
 * appBoot.js — single entrypoint for dashboard (desktop + mobile).
 * No tab/DOM gating. Uses GET /api/dashboard/bootstrap only for initial data.
 * BOOT_V2: same path for mobile and desktop; data visible or explicit error in <=10s.
 */
(function (root) {
    'use strict';

    if (typeof window === 'undefined') return;

    window.__BOOT_V2_START = true;
    if (typeof console !== 'undefined' && console.log) {
        console.log('BOOT_V2_START');
    }

    var BOOT_TIMEOUT_MS = 10000;
    var _bootGuardTimer = null;
    var _bootDone = false;

    function getAccountId() {
        if (window.__ACTIVE_ACCOUNT_ID != null && window.__ACTIVE_ACCOUNT_ID !== '') {
            return Number(window.__ACTIVE_ACCOUNT_ID);
        }
        try {
            var u = sessionStorage.getItem('user') || localStorage.getItem('user');
            if (!u) return null;
            var user = JSON.parse(u);
            return user && user.account_id != null ? Number(user.account_id) : null;
        } catch (e) {
            return null;
        }
    }

    function showBootErrorBanner(section, error, requestId) {
        var code = (error && error.error_code) ? error.error_code : (section === 'prices' ? 'PRICES_TIMEOUT' : 'WALLET_TIMEOUT');
        var msg = (error && error.message) ? error.message : (section === 'prices' ? 'Fiyatlar yüklenemedi.' : 'Cüzdan verisi yüklenemedi.');
        var el = document.getElementById('appBootErrorBanner');
        if (!el) {
            el = document.createElement('div');
            el.id = 'appBootErrorBanner';
            el.setAttribute('role', 'alert');
            el.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:100000;background:var(--ds-bg-error, #1a0a0a);color:var(--ds-text-error, #f6465d);padding:10px 16px;font-size:14px;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,0.3);';
            document.body.appendChild(el);
        }
        el.innerHTML = '<span>' + msg + '</span> <button type="button" class="btn btn-sm" style="margin-left:8px;" id="appBootRetryBtn">Yenile</button>' +
            (requestId ? '<span style="opacity:0.7;font-size:11px;display:block;margin-top:4px;">request_id: ' + requestId + '</span>' : '');
        el.style.display = 'block';
        var btn = document.getElementById('appBootRetryBtn');
        if (btn && !btn._bound) {
            btn._bound = true;
            btn.onclick = function () {
                el.style.display = 'none';
                if (window.appBootRetry) window.appBootRetry();
            };
        }
    }

    function clearBootGuard() {
        if (_bootGuardTimer) {
            clearTimeout(_bootGuardTimer);
            _bootGuardTimer = null;
        }
    }

    function runBootGuard() {
        clearBootGuard();
        _bootGuardTimer = setTimeout(function () {
            _bootGuardTimer = null;
            if (_bootDone) return;
            var store = window.dashboardStore && window.dashboardStore.store;
            if (store) {
                if (store.prices.status === 'loading') {
                    window.dashboardStore.setError('prices', { error_code: 'PRICES_TIMEOUT', message: 'Fiyatlar 10 saniyede yüklenemedi.' });
                    showBootErrorBanner('prices', store.prices.error, store.boot_request_id);
                }
                if (store.wallet.status === 'loading') {
                    window.dashboardStore.setError('wallet', { error_code: 'WALLET_TIMEOUT', message: 'Cüzdan verisi 10 saniyede yüklenemedi.' });
                    showBootErrorBanner('wallet', store.wallet.error, store.boot_request_id);
                }
            }
        }, BOOT_TIMEOUT_MS);
    }

    function applyBootstrapToGlobals(data, meta) {
        if (!data) return;
        if (window.marketStore && data.prices && typeof data.prices === 'object') {
            var priceMap = {};
            for (var sym in data.prices) {
                if (data.prices[sym] && data.prices[sym].price != null) {
                    priceMap[sym] = Number(data.prices[sym].price);
                }
            }
            if (Object.keys(priceMap).length && typeof window.marketStore.updatePrices === 'function') {
                window.marketStore.updatePrices(priceMap);
            }
        }
        if (window.assetsState && window.assetsState.wallet && data.wallet_cached && typeof data.wallet_cached === 'object') {
            var w = data.wallet_cached;
            w.ts = data.wallet_cached_at || new Date().toISOString();
            if (typeof window.normalizeAndApplyWallet === 'function') {
                window.normalizeAndApplyWallet(w, { source: 'appBoot_bootstrap', request_id: meta && meta.request_id });
            }
        } else if (window.assetsState && window.assetsState.wallet && !data.wallet_cached) {
            var ws = data.wallet_status || {};
            window.assetsState.wallet.status = 'error';
            window.assetsState.wallet.error = { error_code: 'WALLET_NOT_READY', detail: 'No cached snapshot yet', request_id: meta && meta.request_id };
            window.assetsState.wallet.keys_configured = ws.keys_configured;
        }
        if (data.kpis && typeof window.updateKPIs === 'function') {
            window.updateKPIs({ account: data.kpis, total_bots: data.kpis.total_bots, active_bots: data.kpis.active_bots, daily_bot_pnl_usd: data.kpis.daily_bot_pnl_usd, total_pnl_usd: data.kpis.total_pnl_usd });
        }
    }

    function boot() {
        var accountId = getAccountId();
        if (!accountId) {
            if (typeof console !== 'undefined' && console.warn) console.warn('BOOT_V2: no accountId, skip bootstrap');
            window.__BOOT_V2_DONE = true;
            return;
        }

        window.__ACTIVE_ACCOUNT_ID = accountId;

        var apiClient = window.apiClient;
        if (!apiClient || typeof apiClient.get !== 'function') {
            if (typeof console !== 'undefined' && console.error) console.error('BOOT_V2: apiClient missing — do not use fetch fallback');
            showBootErrorBanner('prices', { error_code: 'API_CLIENT_MISSING', message: 'API istemcisi yüklenemedi. Sayfayı yenileyin.' }, null);
            window.__BOOT_V2_DONE = true;
            return;
        }

        if (window.dashboardStore) {
            window.dashboardStore.resetLoading();
        }
        runBootGuard();

        var url = '/api/dashboard/bootstrap?account_id=' + accountId;
        apiClient.get(url, { timeout: 10000 })
            .then(function (res) {
                clearBootGuard();
                if (!res || !res.ok) {
                    if (window.dashboardStore) {
                        window.dashboardStore.setError('prices', { error_code: 'BOOTSTRAP_FAIL', message: (res && res.error && res.error.message) || 'Bootstrap failed' });
                    }
                    showBootErrorBanner('prices', { error_code: 'BOOTSTRAP_FAIL' }, (res && res.meta && res.meta.request_id));
                    _bootDone = true;
                    window.__BOOT_V2_DONE = true;
                    return;
                }
                var data = (res && res.data) ? res.data : {};
                var meta = (res && res.meta) ? res.meta : {};
                if (window.dashboardStore) {
                    window.dashboardStore.setPrices(Object.assign({}, data, { request_id: meta.request_id }));
                    window.dashboardStore.setWallet(Object.assign({}, data, { request_id: meta.request_id }));
                    window.dashboardStore.setKpis(Object.assign({}, data, { request_id: meta.request_id }));
                    window.dashboardStore.setBootMeta(meta);
                }
                applyBootstrapToGlobals(data, meta);
                if (typeof window.syncBootWalletToAssetsState === 'function') {
                    window.syncBootWalletToAssetsState();
                }
                _bootDone = true;
                window.__BOOT_V2_DONE = true;
                if (window.BinanceAssetsPanel && typeof window.BinanceAssetsPanel.render === 'function') {
                    window.BinanceAssetsPanel.render();
                }
                if (typeof window.renderVarliklarList === 'function') {
                    window.renderVarliklarList();
                }
            })
            .catch(function (err) {
                clearBootGuard();
                var code = (err && err.error_code) ? err.error_code : 'NETWORK_ERROR';
                var msg = (err && err.message) ? err.message : 'Veri yüklenemedi.';
                if (window.dashboardStore) {
                    window.dashboardStore.setError('prices', { error_code: code, message: msg });
                    window.dashboardStore.setError('wallet', { error_code: code, message: msg });
                }
                showBootErrorBanner('prices', { error_code: code, message: msg }, (err && err.request_id) || null);
                _bootDone = true;
                window.__BOOT_V2_DONE = true;
            });
    }

    function retry() {
        _bootDone = false;
        window.__BOOT_V2_DONE = false;
        var el = document.getElementById('appBootErrorBanner');
        if (el) el.style.display = 'none';
        boot();
    }

    window.appBootRetry = retry;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { boot(); });
    } else {
        boot();
    }
})(typeof window !== 'undefined' ? window : {});
