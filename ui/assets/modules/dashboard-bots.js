/**
 * dashboard-bots.js
 * Bot listesi: activateBotsTab, renderBotsList, sort, bots tab cache.
 * dashboard.js'ten SONRA yüklenir.
 */

var _botsTabCache = { accountId: null, initialized: false };

function botsTabCacheSessionKey(accountId) {
    return 'dashboard_bots_tab_ready_v1_' + (accountId || '');
}

function clearBotsTabCache() {
    _botsTabCache.initialized = false;
    _botsTabCache.accountId = null;
    if (State.accountId) {
        try {
            sessionStorage.removeItem(botsTabCacheSessionKey(State.accountId));
            sessionStorage.removeItem(financeBotsDomCacheKey(State.accountId));
        } catch (e) {}
    }
}

function isBotsTabCacheReady() {
    if (!_botsTabCache.initialized || _botsTabCache.accountId !== State.accountId) return false;
    return _financeBotsPanelHasRows(document.getElementById('financeBotsListBots'));
}

function markBotsTabCacheReady() {
    if (!State.accountId) return;
    _botsTabCache.initialized = true;
    _botsTabCache.accountId = State.accountId;
    try { sessionStorage.setItem(botsTabCacheSessionKey(State.accountId), '1'); } catch (e) {}
    if (typeof persistFinanceBotsDomCache === 'function') persistFinanceBotsDomCache();
}

function financeBotsDomCacheKey(accountId) {
    return 'financeBotsDom_v1_' + (accountId || '');
}

/** Bot detaydan dönüşte tablo HTML — renderFinanceBots yerine enjekte. */
function persistFinanceBotsDomCache() {
    if (!State.accountId) return;
    var home = document.getElementById('financeBotsList');
    var tab = document.getElementById('financeBotsListBots');
    var src = (_financeBotsPanelHasRows(tab) && tab) ? tab : ((_financeBotsPanelHasRows(home) && home) ? home : null);
    if (!src || !src.innerHTML || src.innerHTML.indexOf('data-bot-id') < 0) return;
    try {
        sessionStorage.setItem(financeBotsDomCacheKey(State.accountId), JSON.stringify({
            ts: Date.now(),
            html: src.innerHTML,
            structureSig: _financeBotsStructureSignature,
            idsSig: _financeBotsIdsSignature,
            sortBy: normalizeFinanceBotsSortBy(typeof financeBotsSortBy !== 'undefined' ? financeBotsSortBy : 'best')
        }));
    } catch (e) { /* quota */ }
}

function restoreFinanceBotsDomFromSessionCache(accountId, bots) {
    if (!accountId) return false;
    try {
        var raw = sessionStorage.getItem(financeBotsDomCacheKey(accountId));
        if (!raw) return false;
        var data = JSON.parse(raw);
        if (!data || !data.html || data.html.indexOf('data-bot-id') < 0) return false;
        if (data.ts && Date.now() - data.ts > 86400000) return false;
        bots = Array.isArray(bots) ? bots : [];
        var sortBy = normalizeFinanceBotsSortBy(data.sortBy || (typeof financeBotsSortBy !== 'undefined' ? financeBotsSortBy : 'best'));
        var structureSig = bots.length ? financeBotsStructureSignature(bots, sortBy) : data.structureSig;
        var idsSig = bots.length
            ? bots.map(function (b) { return String(b.bot_id || b.id || ''); }).sort().join(',')
            : data.idsSig;
        if (data.idsSig && idsSig && data.idsSig !== idsSig) return false;
        if (data.structureSig && structureSig && data.structureSig !== structureSig) return false;
        var home = document.getElementById('financeBotsList');
        var tab = document.getElementById('financeBotsListBots');
        if (!home && !tab) return false;
        if (home) {
            home.innerHTML = data.html;
            bindFinanceBotsRowClicks(home);
        }
        if (tab) {
            tab.innerHTML = data.html;
            bindFinanceBotsRowClicks(tab);
        }
        _financeBotsStructureSignature = structureSig || data.structureSig;
        _financeBotsIdsSignature = idsSig || data.idsSig;
        if (data.sortBy) financeBotsSortBy = normalizeFinanceBotsSortBy(data.sortBy);
        markBotsTabCacheReady();
        return true;
    } catch (e) {
        return false;
    }
}

function persistDashboardBeforeBotDetailNav() {
    try { localStorage.setItem('dashboard_active_tab', 'bots'); } catch (e) {}
    if (typeof persistFinanceBotsDomCache === 'function') persistFinanceBotsDomCache();
    if (State.accountId) {
        try { sessionStorage.setItem(botsTabCacheSessionKey(State.accountId), '1'); } catch (e) {}
    }
}

function tryRestoreBotsTabCacheFlag(accountId) {
    if (!accountId) return false;
    try {
        if (sessionStorage.getItem(botsTabCacheSessionKey(accountId)) !== '1') return false;
    } catch (e) { return false; }
    if (!_financeBotsPanelHasRows(document.getElementById('financeBotsListBots'))) return false;
    _botsTabCache.initialized = true;
    _botsTabCache.accountId = accountId;
    return true;
}

/** Tablo yeniden çizilmeden canlı fiyat, bakiye, K/Z, leaderboard, performans. */
function refreshBotsTabDataOnly() {
    if (State.bots && State.bots.length) {
        patchFinanceBotsMetrics(State.bots);
    } else {
        updateFinanceBotsLivePrices();
    }
    if (typeof ensureFinanceBotsLiveEquity === 'function') ensureFinanceBotsLiveEquity();
    if (typeof ensureFinanceBotsHealthPolling === 'function') ensureFinanceBotsHealthPolling();
    if (State.accountId && typeof loadBotPerformance === 'function') {
        loadBotPerformance(State.botPerformancePeriod || 'all');
    }
    if (typeof loadGlobalLeaderboard === 'function') loadGlobalLeaderboard(true);
}

/**
 * Botlar sekmesi açılışı — force:true hesap değişimi veya bot listesi yapısal değişiminde.
 */
function activateBotsTab(opts) {
    opts = opts || {};
    if (opts.force) clearBotsTabCache();
    if (!opts.force && tryRestoreBotsTabCacheFlag(State.accountId)) {
        refreshBotsTabDataOnly();
        if (typeof _bindFinanceBotsSortButtons === 'function') _bindFinanceBotsSortButtons();
        return;
    }
    if (!opts.force && isBotsTabCacheReady()) {
        refreshBotsTabDataOnly();
        if (typeof _bindFinanceBotsSortButtons === 'function') _bindFinanceBotsSortButtons();
        return;
    }

    if (typeof _bindFinanceBotsSortButtons === 'function') _bindFinanceBotsSortButtons();

    if (State.accountId && typeof restoreFinanceBotsFromSessionCache === 'function') {
        restoreFinanceBotsFromSessionCache(State.accountId);
    }

    var tabList = document.getElementById('financeBotsListBots');
    if (_financeBotsPanelHasRows(tabList)) {
        markBotsTabCacheReady();
        refreshBotsTabDataOnly();
        return;
    }

    if (typeof syncFinanceBotsTabFromHome === 'function') syncFinanceBotsTabFromHome();
    if (_financeBotsPanelHasRows(tabList)) {
        markBotsTabCacheReady();
        refreshBotsTabDataOnly();
        return;
    }

    if (State.bots && State.bots.length && typeof renderFinanceBots === 'function') {
        renderFinanceBots(State.bots, { forceFullRender: true });
    } else if (State.accountId) {
        if (typeof loadBotsListFast === 'function') loadBotsListFast(State.accountId);
        if (!State.bots || !State.bots.length) {
            if (typeof loadSummary === 'function') loadSummary(State.accountId);
        }
    }

    if (State.accountId && typeof loadBotPerformance === 'function') {
        loadBotPerformance(State.botPerformancePeriod || 'all');
    }
    if (typeof loadGlobalLeaderboard === 'function') loadGlobalLeaderboard(false);

    if (_financeBotsPanelHasRows(tabList)) markBotsTabCacheReady();
}
window.activateBotsTab = activateBotsTab;

/** Hızlı bot listesi: /api/bots-engine ile hemen listeyi doldurur; summary gelene kadar "Yükleniyor" kalmaz. */
function loadBotsListFast(accountId) {
    if (!accountId || !window.apiClient) return;
    window.apiClient.get('/api/bots-engine?account_id=' + accountId, { timeout: 8000 })
        .then(function(res) {
            // Summary zaten geldiyse (current_usd dahil) onu ezme; sadece henüz veri yoksa doldur
            if (State.summary && Array.isArray(State.summary.bots) && State.summary.bots.length > 0) return;
            if (_financeBotsTableHasRows() && isBotsTabCacheReady()) {
                var list = Array.isArray(res.bots) ? res.bots : [];
                if (!list.length) return;
                var mapped = list.map(function(r) {
                    var cfg = r.config || {};
                    var budget = Number(cfg.initial_capital_usdt || cfg.budget_usd || cfg.bot_budget_usdt) || 0;
                    var existing = (State.bots || []).find(function(b) { return (b.bot_id || b.id) === r.bot_id; });
                    var base = {
                        bot_id: r.bot_id, id: r.bot_id, symbol: r.symbol || 'N/A',
                        status: (r.status || 'stopped').toLowerCase(),
                        display_status: r.display_status || r.status || 'stopped',
                        initial_allocation_done: r.initial_allocation_done === true,
                        health_alert_level: r.health_alert_level || null,
                        health_alerts: Array.isArray(r.health_alerts) ? r.health_alerts : [],
                        account_id: r.account_id, config: cfg,
                        budget_usd: budget, initial_usd: budget,
                        total_pnl_usd: 0, total_pnl_pct: 0, daily_pnl_usd: 0,
                        last_trade_at: r.last_tick_at || r.created_at || null
                    };
                    if (!existing) return base;
                    return Object.assign({}, base, {
                        current_usd: existing.current_usd,
                        total_pnl_usd: existing.total_pnl_usd != null ? existing.total_pnl_usd : base.total_pnl_usd,
                        total_pnl_pct: existing.total_pnl_pct != null ? existing.total_pnl_pct : base.total_pnl_pct,
                        total_cycles_completed: existing.total_cycles_completed,
                        cycle_id: existing.cycle_id,
                        daily_pnl_usd: existing.daily_pnl_usd != null ? existing.daily_pnl_usd : base.daily_pnl_usd
                    });
                });
                var idsSig = mapped.map(function (b) { return String(b.bot_id || b.id || ''); }).sort().join(',');
                if (idsSig === _financeBotsIdsSignature) {
                    State.bots = hydrateBotsWithMetricsCache(mapped);
                    patchFinanceBotsMetrics(State.bots);
                    return;
                }
            }
            var list = Array.isArray(res.bots) ? res.bots : [];
            var mapped = list.map(function(r) {
                var cfg = r.config || {};
                var budget = Number(cfg.initial_capital_usdt || cfg.budget_usd || cfg.bot_budget_usdt) || 0;
                var existing = (State.bots || []).find(function(b) { return (b.bot_id || b.id) === r.bot_id; });
                var base = {
                    bot_id: r.bot_id,
                    id: r.bot_id,
                    symbol: r.symbol || 'N/A',
                    status: (r.status || 'stopped').toLowerCase(),
                    display_status: r.display_status || r.status || 'stopped',
                    initial_allocation_done: r.initial_allocation_done === true,
                    health_alert_level: r.health_alert_level || null,
                    health_alerts: Array.isArray(r.health_alerts) ? r.health_alerts : [],
                    account_id: r.account_id,
                    config: cfg,
                    budget_usd: budget,
                    initial_usd: budget,
                    total_pnl_usd: 0,
                    total_pnl_pct: 0,
                    daily_pnl_usd: 0,
                    last_trade_at: r.last_tick_at || r.created_at || null
                };
                if (!existing) return base;
                return Object.assign({}, base, {
                    current_usd: existing.current_usd,
                    total_pnl_usd: existing.total_pnl_usd != null ? existing.total_pnl_usd : base.total_pnl_usd,
                    total_pnl_pct: existing.total_pnl_pct != null ? existing.total_pnl_pct : base.total_pnl_pct,
                    total_cycles_completed: existing.total_cycles_completed,
                    cycle_id: existing.cycle_id,
                    daily_pnl_usd: existing.daily_pnl_usd != null ? existing.daily_pnl_usd : base.daily_pnl_usd
                });
            });
            State.bots = hydrateBotsWithMetricsCache(mapped);
            renderBotsList(State.bots);
            if (typeof maybeRefreshWalletOnBotsChange === 'function') {
                maybeRefreshWalletOnBotsChange(State.bots, State.summary && State.summary.account);
            }
        })
        .catch(function() {
            if (State.bots && State.bots.length) return;
            if (_financeBotsTableHasRows()) return;
            renderBotsList([]);
        });
}

function isSpotModalOpen() {
    const m = document.getElementById('bnSpotTradeModal');
    return !!(m && m.style.display !== 'none');
}

// Update UI (patch updates) – account name no longer in appbar (center = company)

// ============================================================
// BOT LİSTESİ - K/Z sıralama: en kârlı üstte veya en zararda üstte
// ============================================================

var botsSortBy = 'best'; // legacy alias
var financeBotsSortBy = 'best'; // 'best' | 'worst'

function normalizeFinanceBotsSortBy(sortBy) {
    return sortBy === 'worst' ? 'worst' : 'best';
}

function financeBotSortPnlUsd(bot) {
    if (typeof resolveBotHeroKz === 'function') {
        var kz = resolveBotHeroKz(bot);
        if (kz && kz.usd != null && Number.isFinite(Number(kz.usd))) return Number(kz.usd);
    }
    return Number(bot.total_pnl_usd ?? bot.total_pnl ?? bot.pnl_30d ?? 0) || 0;
}

function compareFinanceBotsForSort(a, b) {
    var pa = financeBotSortPnlUsd(a);
    var pb = financeBotSortPnlUsd(b);
    if (normalizeFinanceBotsSortBy(financeBotsSortBy) === 'worst') return pa - pb;
    return pb - pa;
}

function financeBotsIdsSignature(bots) {
    return (bots || []).map(function (b) { return String(b.bot_id || b.id || ''); }).sort().join(',');
}

function reorderFinanceBotsListDom(container, sortedBotIds) {
    if (!container || !sortedBotIds || !sortedBotIds.length) return false;
    var tbody = container.querySelector('table.mevcut-botlar-table tbody');
    if (!tbody) return false;
    var rowMap = {};
    tbody.querySelectorAll('tr[data-bot-id]').forEach(function (tr) {
        rowMap[String(tr.getAttribute('data-bot-id'))] = tr;
    });
    var rowIds = Object.keys(rowMap);
    if (rowIds.length !== sortedBotIds.length) return false;
    for (var i = 0; i < sortedBotIds.length; i++) {
        if (!rowMap[String(sortedBotIds[i])]) return false;
    }
    sortedBotIds.forEach(function (id) {
        var tr = rowMap[String(id)];
        if (tr) tbody.appendChild(tr);
    });
    var mobileWrap = container.querySelector('.mevcut-botlar-mobile');
    if (mobileWrap) {
        var cardMap = {};
        mobileWrap.querySelectorAll('.mevcut-botlar-mobile-card[data-bot-id]').forEach(function (card) {
            cardMap[String(card.getAttribute('data-bot-id'))] = card;
        });
        if (Object.keys(cardMap).length === sortedBotIds.length) {
            sortedBotIds.forEach(function (id) {
                var card = cardMap[String(id)];
                if (card) mobileWrap.appendChild(card);
            });
        }
    }
    return true;
}

/** Sıralama değişince tabloyu yeniden çizmeden satırları taşır — coin logoları yeniden yüklenmez. */
function applyFinanceBotsSortReorder(bots) {
    bots = hydrateBotsWithMetricsCache(Array.isArray(bots) ? bots : []);
    if (!bots.length) return false;
    var idsSig = financeBotsIdsSignature(bots);
    if (idsSig !== _financeBotsIdsSignature) return false;
    var sorted = bots.slice().sort(compareFinanceBotsForSort);
    var sortedIds = sorted.map(function (b) { return String(b.bot_id || b.id || ''); });
    var containers = [document.getElementById('financeBotsList'), document.getElementById('financeBotsListBots')].filter(function (el) {
        return el && _financeBotsPanelHasRows(el);
    });
    if (!containers.length) return false;
    var ok = containers.every(function (c) { return reorderFinanceBotsListDom(c, sortedIds); });
    if (!ok) return false;
    State.bots = sorted;
    var sortBy = normalizeFinanceBotsSortBy(financeBotsSortBy);
    _financeBotsStructureSignature = financeBotsStructureSignature(bots, sortBy);
    _financeBotsIdsSignature = idsSig;
    if (typeof persistFinanceBotsDomCache === 'function') persistFinanceBotsDomCache();
    if (typeof markBotsTabCacheReady === 'function') markBotsTabCacheReady();
    return true;
}

function setBotsSortBy(sortBy) {
    setFinanceBotsSortBy(normalizeFinanceBotsSortBy(sortBy));
}

function setFinanceBotsSortBy(sortBy) {
    financeBotsSortBy = normalizeFinanceBotsSortBy(sortBy);
    updateFinanceBotsSortButtonUi(financeBotsSortBy);
    if (State.bots && State.bots.length) {
        if (!applyFinanceBotsSortReorder(State.bots)) {
            renderFinanceBots(State.bots, { forceFullRender: true });
        }
    } else {
        loadFinanceBotsList();
    }
}

function updateFinanceBotsSortButtonUi(sortBy) {
    sortBy = normalizeFinanceBotsSortBy(sortBy);
    var isWorst = sortBy === 'worst';
    var title = isWorst
        ? 'En zararda olan üstte. Tıkla: en kârlıya göre sırala'
        : 'En kârlı üstte. Tıkla: en zararda olana göre sırala';
    var icon = isWorst ? '↓' : '↑';
    ['btnSortBotsBy', 'btnSortBotsByBotsTab'].forEach(function (id) {
        var btn = document.getElementById(id);
        if (!btn) return;
        btn.title = title;
        btn.setAttribute('aria-label', title);
        btn.classList.toggle('profit-sort-worst', isWorst);
        btn.classList.toggle('profit-sort-best', !isWorst);
    });
    ['btnSortBotsByIcon', 'btnSortBotsByBotsTabIcon'].forEach(function (id) {
        var el = document.getElementById(id);
        if (el) el.textContent = icon;
    });
}

// Botlar sekmesi + Anasayfa aynı tablo: renderFinanceBots hem financeBotsList hem financeBotsListBots günceller
function renderBotsList(bots, opts) {
    if (typeof window.__DEBUG_DASH__ !== 'undefined' && window.__DEBUG_DASH__) console.count('renderBotsList');
    bots = Array.isArray(bots) ? bots : [];
    if (!(opts && opts.forceFullRender) && isBotsTabActive() && isBotsTabCacheReady()) {
        var idsSig = bots.map(function (b) { return String(b.bot_id || b.id || ''); }).sort().join(',');
        if (idsSig === _financeBotsIdsSignature) {
            State.bots = hydrateBotsWithMetricsCache(bots);
            refreshBotsTabDataOnly();
            return;
        }
        clearBotsTabCache();
    }
    renderFinanceBots(bots, opts);
}

// Compatibility
function renderBotsNow(bots) { renderBotsList(bots); }
function renderBotsListDirect(bots) { renderBotsList(bots); }
function updateBotsList(bots) { renderBotsList(bots); }
