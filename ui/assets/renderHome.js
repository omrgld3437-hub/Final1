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

    /** Map wallet_cached / wallet_live to assetsState via normalizeAndApplyWallet.
     *  Backend enriches bot_locked (virtual_wallet + state fallback); do not strip those fields. */
    function walletCachedToAssetsState(walletCached, walletCachedAt, meta) {
        meta = meta || {};
        if (!walletCached || typeof walletCached !== 'object') return;
        var ts = walletCachedAt ? (typeof walletCachedAt === 'string' ? new Date(walletCachedAt).getTime() : walletCachedAt) : Date.now();
        if (typeof window !== 'undefined' && window.normalizeAndApplyWallet) {
            var p = Object.assign({}, walletCached, {
                ts: ts,
                keys_configured: walletCached.keys_configured !== false,
                data_status: meta.live ? 'fresh' : (walletCached.data_status || 'cached')
            });
            window.normalizeAndApplyWallet(p, {
                source: meta.live ? 'wallet_refresh' : 'home_fast_cached',
                skipped: meta.skipped === true,
                stale: meta.stale === true
            });
            return;
        }
        var assets = Array.isArray(walletCached.assets) ? walletCached.assets : [];
        var coerceNum = (typeof window !== 'undefined' && window.coerceNumber) ? window.coerceNumber : function(x) { return typeof x === 'number' && isFinite(x) ? x : null; };
        var totalUsd = coerceNum(walletCached.total_usd);
        var currentTotal = (typeof window !== 'undefined' && window.assetsState && window.assetsState.wallet && typeof window.assetsState.wallet.total_usd === 'number') ? window.assetsState.wallet.total_usd : null;
        if ((totalUsd == null || totalUsd === 0) && currentTotal != null && currentTotal > 0) totalUsd = currentTotal;
        var freeUsdTot = coerceNum(walletCached.free_usd);
        var lockedUsdTot = coerceNum(walletCached.locked_usd);
        var botLockedUsdTot = coerceNum(walletCached.bot_locked_usd);
        var availableUsdTot = coerceNum(walletCached.available_usd);
        var assetsForPanel = assets.map(function (a) {
            var free = coerceNum(a.free) || 0;
            var locked = coerceNum(a.locked) || 0;
            var total = free + locked;
            var uv = coerceNum(a.usdt_value) != null ? coerceNum(a.usdt_value) : coerceNum(a.total_usd);
            var botLocked = coerceNum(a.bot_locked) || 0;
            var botLockedUsd = coerceNum(a.bot_locked_usd);
            var freeUsd = coerceNum(a.free_usd);
            var lockedUsd = coerceNum(a.locked_usd);
            if (freeUsd == null && uv != null && total > 0) freeUsd = (free / total) * uv;
            if (lockedUsd == null && uv != null && total > 0) lockedUsd = (locked / total) * uv;
            if (botLockedUsd == null && botLocked > 0 && uv != null && total > 0) botLockedUsd = botLocked * (uv / total);
            var available = coerceNum(a.available);
            if (available == null) available = Math.max(0, free - botLocked);
            var availableUsd = coerceNum(a.available_usd);
            if (availableUsd == null && freeUsd != null) availableUsd = Math.max(0, freeUsd - (botLockedUsd || 0));
            return {
                asset: a.asset,
                free: free,
                locked: locked,
                total: total,
                value_usd: uv,
                total_usd: uv,
                free_usd: freeUsd,
                locked_usd: lockedUsd,
                bot_locked: botLocked,
                bot_locked_usd: botLockedUsd != null ? botLockedUsd : 0,
                available: available,
                available_usd: availableUsd
            };
        });
        if (botLockedUsdTot == null) {
            botLockedUsdTot = assetsForPanel.reduce(function (s, x) { return s + (Number(x.bot_locked_usd) || 0); }, 0);
        }
        if (availableUsdTot == null && freeUsdTot != null) {
            availableUsdTot = Math.max(0, freeUsdTot - (botLockedUsdTot || 0));
        }
        if (typeof window !== 'undefined' && window.assetsState && window.assetsState.wallet) {
            window.assetsState.wallet.status = 'ready';
            window.assetsState.wallet.ts = ts;
            window.assetsState.wallet.assets = assetsForPanel;
            window.assetsState.wallet.total_usd = totalUsd;
            window.assetsState.wallet.free_usd = freeUsdTot != null ? freeUsdTot : totalUsd;
            window.assetsState.wallet.locked_usd = lockedUsdTot || 0;
            window.assetsState.wallet.bot_locked_usd = botLockedUsdTot || 0;
            window.assetsState.wallet.available_usd = availableUsdTot != null ? availableUsdTot : totalUsd;
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
                var mini = { last: p || 0, open: p || 0, volume: d.volume24h || 0, quoteVolume: (d.volume24h || 0) * (p || 0), marketCap: 0 };
                if (d.change24h != null && Number.isFinite(Number(d.change24h))) mini.changePct = Number(d.change24h);
                miniData[sym] = mini;
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
        if (typeof window.setWalletPanelUpdating === 'function') {
            window.setWalletPanelUpdating(!!show);
            return;
        }
        var badge = document.getElementById('flashHomeUpdatingBadge');
        if (!badge) return;
        badge.hidden = !show;
        badge.setAttribute('aria-hidden', show ? 'false' : 'true');
        var staleEl = document.getElementById('bnAssetsStaleBadge');
        if (staleEl && show) staleEl.hidden = true;
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
