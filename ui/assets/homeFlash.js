/**
 * Flash Home – mobile-first load pipeline (Patch H).
 * 1) Skeleton 2) localStorage 3) GET /api/home/fast 4) POST /api/home/wallet/refresh in background 5) Update UI on live.
 */
(function (root, factory) {
    if (typeof define === 'function' && define.amd) {
        define([], factory);
    } else if (typeof module === 'object' && module.exports) {
        module.exports = factory();
    } else {
        root.homeFlash = factory();
    }
})(typeof self !== 'undefined' ? self : this, function () {
    'use strict';

    var lastRefreshAttemptAt = 0;
    var REFRESH_DEBOUNCE_MS = 30000;
    var REFRESH_LOCK_TTL_MS = 20000;
    var REFRESH_LOCK_KEY_PREFIX = 'tt_wallet_refresh_lock:';
    var _walletFallbackAttempts = 0;
    var WALLET_FALLBACK_MAX_ATTEMPTS = 3;
    var WALLET_FALLBACK_DELAYS_MS = [600, 1500, 4000];

    function getAccountId() {
        if (typeof window !== 'undefined' && window.__ACTIVE_ACCOUNT_ID != null) return Number(window.__ACTIVE_ACCOUNT_ID);
        try {
            var u = typeof sessionStorage !== 'undefined' ? sessionStorage.getItem('user') : null;
            if (!u) u = typeof localStorage !== 'undefined' ? localStorage.getItem('user') : null;
            if (!u) return null;
            var user = JSON.parse(u);
            return user && (user.account_id != null) ? Number(user.account_id) : null;
        } catch (e) {
            return null;
        }
    }

    function isRefreshLocked(accountId) {
        try {
            var k = REFRESH_LOCK_KEY_PREFIX + accountId;
            var raw = localStorage.getItem(k);
            if (!raw) return false;
            var ts = parseInt(raw, 10);
            if (isNaN(ts)) return false;
            return (Date.now() - ts) < REFRESH_LOCK_TTL_MS;
        } catch (e) {
            return false;
        }
    }

    function setRefreshLock(accountId) {
        try {
            localStorage.setItem(REFRESH_LOCK_KEY_PREFIX + accountId, String(Date.now()));
        } catch (e) {}
    }

    function clearRefreshLock(accountId) {
        try {
            localStorage.removeItem(REFRESH_LOCK_KEY_PREFIX + accountId);
        } catch (e) {}
    }

    function init() {
        var accountId = getAccountId();
        if (!accountId) return Promise.resolve();

        var renderHome = window.renderHome;
        var storageCache = window.storageCache;
        if (!renderHome || !storageCache) return Promise.resolve();

        renderHome.renderSkeleton();

        var cached = storageCache.load(accountId);
        if (cached && cached.wallet_cached) {
            renderHome.walletCachedToAssetsState(cached.wallet_cached, cached.wallet_cached_at);
        }
        if (cached && cached.kpis && typeof window.updateKPIs === 'function') {
            window.updateKPIs({ account: cached.kpis, total_bots: cached.kpis.total_bots, active_bots: cached.kpis.active_bots, daily_bot_pnl_usd: cached.kpis.daily_bot_pnl_usd, total_pnl_usd: cached.kpis.total_pnl_usd });
        }
        renderHome.hideSkeleton();

        return loadFast(accountId).then(function () {
            triggerRefresh(accountId, false);
        });
    }

    function loadFast(accountId) {
        var apiClient = window.apiClient;
        var storageCache = window.storageCache;
        var renderHome = window.renderHome;
        if (!apiClient || !apiClient.get) return Promise.resolve();

        var url = '/api/home/fast?account_id=' + accountId;
        var opts = { timeout: 15000 };
        if (window.__DEBUG_NET__) console.log('[homeFlash] GET /api/home/fast');

        return apiClient.get(url, opts).then(function (res) {
            var ok = res && res.ok;
            var data = res && res.data;
            var meta = res && res.meta;
            if (!ok || !data) {
                if (res && res.error && res.error.message && typeof window.Toast !== 'undefined' && window.Toast.warning) {
                    try { window.Toast.warning(res.error.message); } catch (e) {}
                }
                return;
            }
            if (data.prices && Object.keys(data.prices).length) {
                renderHome.applyPricesToMarketStore(data.prices);
            }
            if (data.kpis && typeof window.updateKPIs === 'function') {
                var summaryShape = {
                    account: data.kpis,
                    total_bots: data.kpis.total_bots,
                    active_bots: data.kpis.active_bots,
                    daily_bot_pnl_usd: data.kpis.daily_bot_pnl_usd,
                    total_pnl_usd: data.kpis.total_pnl_usd
                };
                window.updateKPIs(summaryShape);
            }
            if (data.wallet_cached) {
                renderHome.walletCachedToAssetsState(data.wallet_cached, data.wallet_cached_at);
                _walletFallbackAttempts = 0;
            } else if (_walletFallbackAttempts < WALLET_FALLBACK_MAX_ATTEMPTS && typeof window.BinanceAssetsPanel !== 'undefined' && window.BinanceAssetsPanel.refresh) {
                var walletIdle = window.assetsState && window.assetsState.wallet && (window.assetsState.wallet.status === 'idle' || window.assetsState.wallet.status === 'loading');
                if (walletIdle) {
                    var delayMs = WALLET_FALLBACK_DELAYS_MS[Math.min(_walletFallbackAttempts, WALLET_FALLBACK_DELAYS_MS.length - 1)];
                    _walletFallbackAttempts++;
                    setTimeout(function () {
                        if (window.BinanceAssetsPanel && window.BinanceAssetsPanel.refresh) window.BinanceAssetsPanel.refresh();
                    }, delayMs);
                }
            }
            if (data.wallet_live_inflight) {
                renderHome.showUpdatingBadge(true);
            }
            storageCache.mergeSaved(accountId, {
                wallet_cached: data.wallet_cached,
                wallet_cached_at: data.wallet_cached_at,
                prices: data.prices,
                kpis: data.kpis
            });
            if (window.__DEBUG_NET__ && meta) {
                console.log('[homeFlash] fast server_ms=' + meta.server_ms + ' payload_bytes=' + meta.payload_bytes);
            }
        }).catch(function (err) {
            if (window.__DEBUG_NET__) console.warn('[homeFlash] fast error', err);
            if (typeof window.Toast !== 'undefined' && window.Toast.warning) {
                try { window.Toast.warning(err && err.message ? err.message : 'Veriler yüklenemedi'); } catch (e) {}
            }
        });
    }

    function triggerRefresh(accountId, force) {
        if (!accountId) return Promise.resolve();
        var active = typeof window !== 'undefined' ? window.__ACTIVE_ACCOUNT_ID : null;
        if (active != null && Number(accountId) !== Number(active)) {
            if (typeof window.pushWalletEvent === 'function') window.pushWalletEvent({ source: 'homeFlash', status: 'skipped', note: 'ACCOUNT_ID_MISMATCH req=' + accountId + ' active=' + active });
            return Promise.resolve();
        }
        var now = Date.now();
        if (!force && (now - lastRefreshAttemptAt < REFRESH_DEBOUNCE_MS)) return Promise.resolve();
        if (isRefreshLocked(accountId)) return Promise.resolve();

        var apiClient = window.apiClient;
        var renderHome = window.renderHome;
        var storageCache = window.storageCache;
        if (!apiClient || !apiClient.post) return Promise.resolve();

        lastRefreshAttemptAt = now;
        setRefreshLock(accountId);
        renderHome.showUpdatingBadge(true);

        var url = '/api/home/wallet/refresh?account_id=' + accountId + (force ? '&force=1' : '');
        var opts = { timeout: 20000 };

        return apiClient.post(url, null, opts).then(function (res) {
            clearRefreshLock(accountId);
            var ok = res && res.ok;
            var data = res && res.data;
            if (!ok || !data) {
                renderHome.showUpdatingBadge(false);
                return;
            }
            if (data.inflight) {
                renderHome.showUpdatingBadge(true);
                return;
            }
            renderHome.showUpdatingBadge(false);
            if (data.wallet_live) {
                renderHome.walletCachedToAssetsState(data.wallet_live, data.wallet_live_at, { live: true });
                storageCache.mergeSaved(accountId, {
                    wallet_cached: data.wallet_live,
                    wallet_cached_at: data.wallet_live_at
                });
            } else if (data.wallet_error || (data.error && data.error.error_code)) {
                if (typeof window.markWalletLiveFetchFailed === 'function') window.markWalletLiveFetchFailed();
                if (typeof window.updateKpiCuzdanLiveStatus === 'function') window.updateKpiCuzdanLiveStatus();
            }
        }).catch(function () {
            clearRefreshLock(accountId);
            renderHome.showUpdatingBadge(false);
            if (typeof window.markWalletLiveFetchFailed === 'function') window.markWalletLiveFetchFailed();
            if (typeof window.updateKpiCuzdanLiveStatus === 'function') window.updateKpiCuzdanLiveStatus();
        });
    }

    return {
        init: init,
        loadFast: loadFast,
        triggerRefresh: triggerRefresh,
        getAccountId: getAccountId
    };
});
