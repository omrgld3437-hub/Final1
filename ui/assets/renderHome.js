/**
 * Flash Home – pure render helpers for wallet, prices, KPIs (Patch H).
 * Updates same state as dashboard applySnapshotToUI so BinanceAssetsPanel etc. stay in sync.
 */
(function (root, factory) {
    if (typeof define === 'function' && define.amd) {
        define([], factory);
    } else if (typeof module === 'object' && module.exports) {
        module.exports = factory();
    } else {
        root.renderHome = factory();
    }
})(typeof self !== 'undefined' ? self : this, function () {
    'use strict';

    function relativeTime(ts) {
        if (!ts) return '—';
        var date = new Date(ts);
        var now = Date.now();
        var diffMs = now - date.getTime();
        var diffSecs = Math.floor(diffMs / 1000);
        var diffMins = Math.floor(diffSecs / 60);
        var diffHours = Math.floor(diffMins / 60);
        if (diffSecs < 10) return 'just now';
        if (diffSecs < 60) return diffSecs + 's ago';
        if (diffMins < 60) return diffMins + 'm ago';
        if (diffHours < 24) return diffHours + 'h ago';
        return date.toLocaleDateString();
    }

    /** Map wallet_cached (minimal) to assetsState.wallet shape expected by BinanceAssetsPanel.
     *  Uses normalizeAndApplyWallet when available (coerceNumber for string totals). */
    function walletCachedToAssetsState(walletCached, walletCachedAt) {
        if (!walletCached || typeof walletCached !== 'object') return;
        if (typeof window !== 'undefined' && window.normalizeAndApplyWallet) {
            var coerceNum = window.coerceNumber || function(x) { return typeof x === 'number' && isFinite(x) ? x : null; };
            var rawAssets = Array.isArray(walletCached.assets) ? walletCached.assets : [];
            var assetsForPanel = rawAssets.map(function (a) {
                var uv = coerceNum(a.usdt_value);
                var free = coerceNum(a.free) || 0;
                var locked = coerceNum(a.locked) || 0;
                var total = free + locked;
                return {
                    asset: a.asset, free: free, locked: locked, total: total,
                    value_usd: uv, total_usd: uv,
                    free_usd: uv != null && total > 0 ? (free / total) * uv : (uv != null ? uv : null),
                    locked_usd: uv != null && total > 0 ? (locked / total) * uv : (uv != null ? 0 : null),
                    bot_locked: 0, bot_locked_usd: 0,
                    available: free, available_usd: uv
                };
            });
            var ts = walletCachedAt ? (typeof walletCachedAt === 'string' ? new Date(walletCachedAt).getTime() : walletCachedAt) : Date.now();
            var p = { total_usd: coerceNum(walletCached.total_usd), free_usd: coerceNum(walletCached.total_usd), locked_usd: 0, assets: assetsForPanel, keys_configured: true, data_status: 'cached', ts: ts };
            window.normalizeAndApplyWallet(p, { source: 'home_fast_cached' });
            return;
        }
        var assets = Array.isArray(walletCached.assets) ? walletCached.assets : [];
        var coerceNum = (typeof window !== 'undefined' && window.coerceNumber) ? window.coerceNumber : function(x) { return typeof x === 'number' && isFinite(x) ? x : null; };
        var ts = walletCachedAt ? (typeof walletCachedAt === 'string' ? new Date(walletCachedAt).getTime() : walletCachedAt) : Date.now();
        var totalUsd = coerceNum(walletCached.total_usd);
        var currentTotal = (typeof window !== 'undefined' && window.assetsState && window.assetsState.wallet && typeof window.assetsState.wallet.total_usd === 'number') ? window.assetsState.wallet.total_usd : null;
        if ((totalUsd == null || totalUsd === 0) && currentTotal != null && currentTotal > 0) totalUsd = currentTotal;
        var assetsForPanel = assets.map(function (a) {
            return {
                asset: a.asset,
                free: a.free,
                locked: a.locked,
                total: (a.free || 0) + (a.locked || 0),
                value_usd: a.usdt_value,
                total_usd: a.usdt_value,
                free_usd: a.usdt_value != null ? (a.free || 0) * (a.usdt_value / ((a.free || 0) + (a.locked || 0) || 1)) : null,
                locked_usd: a.usdt_value != null ? (a.locked || 0) * (a.usdt_value / ((a.free || 0) + (a.locked || 0) || 1)) : null,
                bot_locked: 0,
                bot_locked_usd: 0,
                available: a.free || 0,
                available_usd: a.usdt_value
            };
        });
        if (typeof window !== 'undefined' && window.assetsState && window.assetsState.wallet) {
            window.assetsState.wallet.status = 'ready';
            window.assetsState.wallet.ts = ts;
            window.assetsState.wallet.assets = assetsForPanel;
            window.assetsState.wallet.total_usd = totalUsd;
            window.assetsState.wallet.free_usd = totalUsd;
            window.assetsState.wallet.locked_usd = 0;
            window.assetsState.wallet.bot_locked_usd = 0;
            window.assetsState.wallet.available_usd = totalUsd;
            window.assetsState.wallet.error = null;
            window.assetsState.wallet.data_status = 'cached';
        }
        if (typeof window !== 'undefined' && window.BinanceAssetsPanel && window.BinanceAssetsPanel.render) {
            window.BinanceAssetsPanel.render();
        }
        if (typeof window !== 'undefined' && typeof window.renderVarliklarList === 'function') {
            window.renderVarliklarList();
        }
    }

    function applyPricesToMarketStore(prices) {
        if (!prices || typeof prices !== 'object') return;
        var priceMap = {};
        var miniData = {};
        for (var sym in prices) {
            if (!Object.prototype.hasOwnProperty.call(prices, sym)) continue;
            var d = prices[sym];
            if (d && typeof d === 'object') {
                var p = d.price;
                if (p != null && Number.isFinite(p)) priceMap[sym] = p;
                miniData[sym] = { last: p || 0, open: p || 0, changePct: d.change24h || 0, volume: d.volume24h || 0, quoteVolume: (d.volume24h || 0) * (p || 0), marketCap: 0 };
            }
        }
        if (Object.keys(priceMap).length === 0) return;
        if (window.marketStore && Object.keys(priceMap).length) {
            window.marketStore.updatePrices(priceMap);
            for (var s in miniData) {
                if (Object.prototype.hasOwnProperty.call(miniData, s)) window.marketStore.updateMini(s, miniData[s]);
            }
        }
    }

    function renderSkeleton() {
        var walletEl = document.getElementById('flashHomeWalletSkeleton');
        if (walletEl) walletEl.style.display = 'block';
        var walletContent = document.getElementById('flashHomeWalletContent');
        if (walletContent) walletContent.style.display = 'none';
    }

    function hideSkeleton() {
        var walletEl = document.getElementById('flashHomeWalletSkeleton');
        if (walletEl) walletEl.style.display = 'none';
        var walletContent = document.getElementById('flashHomeWalletContent');
        if (walletContent) walletContent.style.display = '';
    }

    function showUpdatingBadge(show) {
        var badge = document.getElementById('flashHomeUpdatingBadge');
        if (badge) badge.style.display = show ? 'inline' : 'none';
    }

    return {
        relativeTime: relativeTime,
        walletCachedToAssetsState: walletCachedToAssetsState,
        applyPricesToMarketStore: applyPricesToMarketStore,
        renderSkeleton: renderSkeleton,
        hideSkeleton: hideSkeleton,
        showUpdatingBadge: showUpdatingBadge
    };
});
