/**
 * Dashboard bots tab — sync DOM boot from session/localStorage before module bundle loads.
 * Keeps bot list + logos stable on refresh; dashboard-bots.js patches metrics in place.
 */
(function (global) {
    'use strict';

    var DOM_KEY = 'financeBotsDom_v1_';
    var BOTS_DATA_KEY = 'financeBotsTable_';
    var KPI_KEY = 'kpi_cuzdan_snap_v1_';
    var HOME_KEY = 'tt_home_cache_v1:';
    var MAX_DOM_AGE_MS = 86400000;

    function qs() {
        try { return new URLSearchParams(global.location.search); } catch (e) { return new URLSearchParams(); }
    }

    function isBotsTabActiveEarly() {
        var q = qs();
        var tab = q.get('tab');
        if (tab === 'bots') return true;
        try {
            if (global.localStorage.getItem('dashboard_active_tab') === 'bots') return true;
        } catch (e) { /* ignore */ }
        return false;
    }

    function shouldShowKpiStripEarly() {
        var q = qs();
        var tab = q.get('tab');
        if (!tab) {
            try { tab = global.localStorage.getItem('dashboard_active_tab') || 'binance'; } catch (e2) { tab = 'binance'; }
        }
        return tab === 'binance' || tab === 'reports' || tab === 'trade' || tab === 'bots';
    }

    function earlyAccountId() {
        try {
            var q = qs();
            var idParam = q.get('account_id');
            if (idParam && !/^\d{5,7}$/.test(String(idParam).trim())) {
                var n = parseInt(idParam, 10);
                if (n > 0) return n;
            }
            var code = (q.get('account_code') || '').trim();
            if (code) {
                var storedCode = global.localStorage.getItem('selectedAccountCode');
                var storedId = global.localStorage.getItem('selectedAccountId');
                if (storedCode && storedId && String(storedCode).trim().toUpperCase() === code.toUpperCase()) {
                    var sid = parseInt(String(storedId).trim(), 10);
                    if (sid > 0) return sid;
                }
            }
            var fromAdmin = q.get('from_admin') === '1' || global.sessionStorage.getItem('dashboard_from_admin') === '1';
            if (fromAdmin) {
                var adminId = global.sessionStorage.getItem('dashboard_admin_account_id');
                if (adminId) {
                    var aid = parseInt(adminId, 10);
                    if (aid > 0) return aid;
                }
            }
            var storedId2 = global.localStorage.getItem('selectedAccountId');
            if (storedId2) {
                var sid2 = parseInt(String(storedId2).trim(), 10);
                if (sid2 > 0) return sid2;
            }
            var u = global.sessionStorage.getItem('user') || global.localStorage.getItem('user');
            if (u) {
                var user = JSON.parse(u);
                if (user && user.account_id > 0) return Number(user.account_id);
            }
        } catch (e3) { /* ignore */ }
        return null;
    }

    function readJsonStorage(key) {
        try {
            var raw = global.sessionStorage.getItem(key) || global.localStorage.getItem(key);
            if (!raw) return null;
            return JSON.parse(raw);
        } catch (e) {
            return null;
        }
    }

    function readDomCache(accountId) {
        if (!accountId) return null;
        var data = readJsonStorage(DOM_KEY + accountId);
        if (!data || !data.html || data.html.indexOf('data-bot-id') < 0) return null;
        if (data.ts && Date.now() - data.ts > MAX_DOM_AGE_MS) return null;
        return data;
    }

    function markLogosLoaded(root) {
        if (!root) return;
        root.querySelectorAll('img.mevcut-bot-logo').forEach(function (img) {
            if (img.complete && img.naturalWidth > 0) {
                img.classList.add('coin-logo-loaded');
            }
        });
    }

    function injectBotsHtml(html) {
        var tab = global.document.getElementById('financeBotsListBots');
        var home = global.document.getElementById('financeBotsList');
        if (!tab && !home) return false;
        if (tab) {
            tab.innerHTML = html;
            markLogosLoaded(tab);
        }
        if (home && !home.querySelector('[data-bot-id]')) {
            home.innerHTML = html;
            markLogosLoaded(home);
        }
        return !!(tab && tab.querySelector('[data-bot-id]'));
    }

    function bootBotsDom(accountId) {
        if (!accountId || !isBotsTabActiveEarly()) return false;
        var data = readDomCache(accountId);
        if (!data) return false;
        if (!injectBotsHtml(data.html)) return false;
        global.__DASH_BOTS_DOM_BOOT = {
            accountId: accountId,
            idsSig: data.idsSig || '',
            structureSig: data.structureSig || '',
            sortBy: data.sortBy || 'best',
            ts: data.ts || Date.now()
        };
        try {
            global.sessionStorage.setItem('dashboard_bots_tab_ready_v1_' + accountId, '1');
        } catch (e) { /* ignore */ }
        return true;
    }

    function fmtUsdEarly(v) {
        var n = Number(v);
        if (!isFinite(n)) return '$0.00';
        return '$' + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    function earlyAccountCode() {
        try {
            var q = qs();
            var code = q.get('account_code');
            if (code) return String(code).trim();
            var stored = global.localStorage.getItem('selectedAccountCode');
            if (stored) return String(stored).trim();
            var admin = global.sessionStorage.getItem('dashboard_admin_account_code');
            if (admin) return String(admin).trim();
        } catch (e) { /* ignore */ }
        return '';
    }

    function isTestAccountCodeEarly(code) {
        return /^TEST/i.test(String(code || '').trim());
    }

    function paintSpotStatusEarly(isTest) {
        if (!isTest) return;
        var el = global.document.getElementById('kpiCuzdanLive');
        if (!el) return;
        el.hidden = false;
        el.textContent = 'Test';
        el.title = 'Test paper hesabı — simüle cüzdan.';
        el.classList.add('kpi-spot-status--test');
        el.classList.remove('kpi-spot-status--live', 'kpi-spot-status--stale', 'kpi-spot-status--offline');
    }

    function paintKpiEarly(spot, pnl, pct) {
        var showStrip = shouldShowKpiStripEarly();
        var strip = global.document.getElementById('unifiedKpiStrip');
        if (strip && showStrip) strip.style.removeProperty('display');
        paintSpotStatusEarly(isTestAccountCodeEarly(earlyAccountCode()));
        if (spot > 0) {
            var w = global.document.getElementById('kpiCuzdan');
            if (w) w.textContent = fmtUsdEarly(spot);
        }
        if (pnl != null && isFinite(Number(pnl))) {
            var pnlEl = global.document.getElementById('kpiCuzdanPnl');
            var n = Number(pnl);
            if (pnlEl) {
                pnlEl.textContent = (n >= 0 ? '' : '-') + fmtUsdEarly(Math.abs(n));
                pnlEl.style.color = n >= 0 ? '#0ecb81' : '#f6465d';
            }
            if (pct != null && isFinite(Number(pct))) {
                var pe = global.document.getElementById('kpiCuzdanPnlPct');
                var p = Number(pct);
                if (pe) {
                    pe.textContent = (p >= 0 ? '+' : '') + p.toFixed(2) + '%';
                    pe.style.color = n >= 0 ? '#0ecb81' : '#f6465d';
                }
            }
        }
    }

    function bootKpi(accountId) {
        if (!accountId) return;
        var isTest = isTestAccountCodeEarly(earlyAccountCode());
        if (shouldShowKpiStripEarly()) {
            var stripEl = global.document.getElementById('unifiedKpiStrip');
            if (stripEl) stripEl.style.removeProperty('display');
        }
        paintSpotStatusEarly(isTest);
        var sess = readJsonStorage(KPI_KEY + accountId);
        if (sess && sess.spot > 0 && (!sess.ts || Date.now() - sess.ts < MAX_DOM_AGE_MS)) {
            paintKpiEarly(sess.spot, sess.pnl, sess.pct);
            return;
        }
        var home = readJsonStorage(HOME_KEY + accountId);
        if (!home || !home.kpis) return;
        if (home.stored_at && Date.now() - home.stored_at > 604800000) return;
        var k = home.kpis;
        var spot = k.spot_balance_usd != null ? Number(k.spot_balance_usd) : Number(k.spot_kpi_total_usd);
        if (spot > 0) paintKpiEarly(spot, k.daily_wallet_pnl_usd, k.daily_wallet_pnl_pct);
    }

    function bootFromUrl() {
        var aid = earlyAccountId();
        if (!aid) return { accountId: null, botsDom: false };
        var botsDom = bootBotsDom(aid);
        if (shouldShowKpiStripEarly()) bootKpi(aid);
        return { accountId: aid, botsDom: botsDom };
    }

    global.DashboardBotsShell = {
        bootFromUrl: bootFromUrl,
        bootBotsDom: bootBotsDom,
        bootKpi: bootKpi,
        earlyAccountId: earlyAccountId,
        isBotsTabActiveEarly: isBotsTabActiveEarly,
        shouldShowKpiStripEarly: shouldShowKpiStripEarly,
        DOM_KEY: DOM_KEY,
        BOTS_DATA_KEY: BOTS_DATA_KEY
    };
})(typeof window !== 'undefined' ? window : globalThis);
