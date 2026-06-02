(function () {
    'use strict';

    var FRESH_LIMIT_SEC = 900;

    function parseWalletTime(raw) {
        if (!raw) return null;
        if (raw instanceof Date) return isNaN(raw.getTime()) ? null : raw;
        var text = String(raw).trim();
        if (!text) return null;
        var normalized = text;
        if (/^\d{4}-\d{2}-\d{2}T/.test(normalized) && !/(Z|[+-]\d{2}:?\d{2})$/.test(normalized)) {
            normalized += 'Z';
        }
        var parsed = new Date(normalized);
        return isNaN(parsed.getTime()) ? null : parsed;
    }

    function ageFromTimestamp(raw) {
        var ts = parseWalletTime(raw);
        if (!ts) return null;
        return Math.max(0, Math.round((Date.now() - ts.getTime()) / 1000));
    }

    function applyFreshness(meta, payload) {
        if (!meta) return meta;
        var ts = meta.wallet_ts_iso || (payload && (payload.ts || payload.last_snapshot_at || payload.wallet_live_at));
        var age = ageFromTimestamp(ts);
        if (age == null) return meta;
        meta.wallet_age_sec = age;
        meta.stale = age >= FRESH_LIMIT_SEC;
        if (!meta.stale && meta.source === 'dashboard_snapshot') {
            meta.stale_code = null;
        }
        return meta;
    }

    function correctDebugMeta() {
        var dbg = window.__walletDebugMeta;
        if (!dbg) return;
        var age = ageFromTimestamp(dbg.wallet_ts_iso || dbg.last_refresh_at);
        if (age == null) return;
        dbg.wallet_age_sec = age;
        dbg.wallet_snapshot_stale = age >= FRESH_LIMIT_SEC;
    }

    function installWrapper() {
        if (typeof window.normalizeAndApplyWallet !== 'function' || window.normalizeAndApplyWallet.__walletStaleFix) {
            return false;
        }
        var original = window.normalizeAndApplyWallet;
        var wrapped = function (payload, meta) {
            return original.call(this, payload, applyFreshness(meta || {}, payload));
        };
        wrapped.__walletStaleFix = true;
        window.normalizeAndApplyWallet = wrapped;
        return true;
    }

    var attempts = 0;
    var timer = setInterval(function () {
        attempts += 1;
        correctDebugMeta();
        if (installWrapper() || attempts > 40) {
            clearInterval(timer);
        }
    }, 250);

    setInterval(correctDebugMeta, 1000);
}());
