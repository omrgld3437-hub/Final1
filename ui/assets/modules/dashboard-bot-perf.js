/**
 * dashboard-bot-perf.js
 * Bot performans cache, renderBotPerformancePanel, loadBotPerformance,
 * leaderboard yardımcıları (applyTrailingDcaConfig vb.).
 * dashboard.js'ten SONRA yüklenir.
 */

var BOT_PERF_CACHE_PREFIX = 'dashboard_bot_perf_v1_';
var TX_HISTORY_CACHE_PREFIX = 'dashboard_tx_history_v1_';
var DASHBOARD_PANEL_CACHE_LOCAL_MAX_MS = 7 * 24 * 60 * 60 * 1000;
var _dashboardPanelsAccountId = null;
var _botPerformanceLoaded = false;
var _botPerformanceLastPeriod = null;
var _botPerformanceLastSig = '';

function _parseDashboardPanelCache(raw, maxAgeMs) {
    if (!raw) return null;
    try {
        var o = JSON.parse(raw);
        if (!o || o.ts == null) return null;
        if (maxAgeMs != null && Date.now() - Number(o.ts) > maxAgeMs) return null;
        return o;
    } catch (e) {
        return null;
    }
}

function _readBotPerfCache(accountId, period) {
    if (!accountId) return null;
    var suffix = (period || 'all').toLowerCase();
    var key = BOT_PERF_CACHE_PREFIX + accountId + '_' + suffix;
    return _parseDashboardPanelCache(sessionStorage.getItem(key), null)
        || _parseDashboardPanelCache(localStorage.getItem(key), DASHBOARD_PANEL_CACHE_LOCAL_MAX_MS);
}

function _persistBotPerfCache(accountId, period, data) {
    if (!accountId || !data) return;
    try {
        var suffix = (period || 'all').toLowerCase();
        var key = BOT_PERF_CACHE_PREFIX + accountId + '_' + suffix;
        var payload = { ts: Date.now(), period: suffix, data: data };
        sessionStorage.setItem(key, JSON.stringify(payload));
        localStorage.setItem(key, JSON.stringify(payload));
    } catch (e) { /* ignore */ }
}

function hydrateBotPerformanceFromCache(accountId, period) {
    period = (period || State.botPerformancePeriod || 'all').toLowerCase();
    var cached = _readBotPerfCache(accountId, period);
    if (!cached || !cached.data) return false;
    State.botPerformancePeriod = period;
    document.querySelectorAll('.bot-perf-btn').forEach(function (b) {
        b.classList.toggle('active', (b.getAttribute('data-period') || '').toLowerCase() === period);
    });
    renderBotPerformancePanel(cached.data, period);
    _botPerformanceLastPeriod = period;
    _botPerformanceLastSig = period + '|cache';
    _botPerformanceLoaded = true;
    return true;
}

function _readTxHistoryCache(accountId, period, typeFilter, page) {
    if (!accountId) return null;
    var key = TX_HISTORY_CACHE_PREFIX + accountId + '_' + (period || 'daily') + '_' + (typeFilter || 'buysell') + '_p' + (page || 1);
    return _parseDashboardPanelCache(sessionStorage.getItem(key), null)
        || _parseDashboardPanelCache(localStorage.getItem(key), DASHBOARD_PANEL_CACHE_LOCAL_MAX_MS);
}

function _persistTxHistoryCache(accountId, period, typeFilter, page, listHtml, paginationHtml, sig, revision) {
    if (!accountId || !listHtml) return;
    try {
        var key = TX_HISTORY_CACHE_PREFIX + accountId + '_' + period + '_' + typeFilter + '_p' + page;
        var payload = {
            ts: Date.now(),
            period: period,
            typeFilter: typeFilter,
            page: page,
            listHtml: listHtml,
            paginationHtml: paginationHtml || '',
            sig: sig || '',
            revision: revision || ''
        };
        sessionStorage.setItem(key, JSON.stringify(payload));
        localStorage.setItem(key, JSON.stringify(payload));
    } catch (e) { /* ignore */ }
}

function hydrateTransactionHistoryFromCache(accountId, period, typeFilter, page) {
    period = period || State.txHistoryPeriod || 'daily';
    typeFilter = typeFilter || State.txHistoryType || 'buysell';
    page = page || State.txHistoryPage || 1;
    var cached = _readTxHistoryCache(accountId, period, typeFilter, page);
    if (!cached || !cached.listHtml) return false;
    var listEl = document.getElementById('txHistoryList');
    var paginationEl = document.getElementById('txHistoryPagination');
    if (!listEl) return false;
    listEl.innerHTML = cached.listHtml;
    if (paginationEl) paginationEl.innerHTML = cached.paginationHtml || '';
    if (cached.sig) _txHistoryLastSig = cached.sig;
    if (cached.revision) _txHistoryRevision = cached.revision;
    _txHistoryLoaded = true;
    State.txHistoryPeriod = period;
    State.txHistoryType = typeFilter;
    State.txHistoryPage = page;
    document.querySelectorAll('.tx-period-btn').forEach(function (b) {
        b.classList.toggle('active', b.getAttribute('data-period') === period);
    });
    document.querySelectorAll('.tx-type-btn').forEach(function (b) {
        b.classList.toggle('active', b.getAttribute('data-type') === typeFilter);
    });
    listEl.querySelectorAll('.tx-history-item').forEach(function (el) {
        el.onclick = function () {
            try {
                var raw = el.getAttribute('data-tx');
                var tx = raw ? JSON.parse(decodeURIComponent(raw)) : null;
                if (tx && typeof openTxDetailModal === 'function') openTxDetailModal(tx);
            } catch (e) {}
        };
    });
    if (paginationEl) {
        paginationEl.querySelectorAll('.tx-pg-btn').forEach(function (btn) {
            btn.onclick = function () {
                var p = parseInt(btn.getAttribute('data-page'), 10);
                if (typeof loadTransactionHistory === 'function') {
                    loadTransactionHistory(State.txHistoryPeriod, State.txHistoryType, p, false, { force: true });
                }
            };
        });
    }
    return true;
}

function hydrateDashboardPanelsFromCache(accountId) {
    if (!accountId) return;
    var perfPeriod = State.botPerformancePeriod || 'all';
    try {
        var savedPerf = sessionStorage.getItem('dashboard_bot_perf_period_' + accountId);
        if (savedPerf) perfPeriod = savedPerf;
    } catch (e) {}
    hydrateBotPerformanceFromCache(accountId, perfPeriod);
    hydrateTransactionHistoryFromCache(
        accountId,
        State.txHistoryPeriod || 'daily',
        State.txHistoryType || 'buysell',
        State.txHistoryPage || 1
    );
}
window.hydrateDashboardPanelsFromCache = hydrateDashboardPanelsFromCache;

function renderBotPerformancePanel(data, forPeriod) {
    if (forPeriod !== State.botPerformancePeriod) return;
    var totals = (data && data.totals) || {};
    var totalPnl = totals.pnl_usd != null ? Number(totals.pnl_usd) : (data && data.pnl_usd != null ? Number(data.pnl_usd) : 0);
    var totalFees = totals.fees_usd != null ? Number(totals.fees_usd) : 0;
    var rangeTxt = _fmtBotPerfRange(data, forPeriod);
    var pnlLabelTxt = _perfPeriodPnlLabel(forPeriod);
    var feesLabelTxt = _perfPeriodFeesLabel(forPeriod);
    var pnlTxt = _fmtPerfUsdt(totalPnl);
    var feesTxt = _fmtPerfUsdtPlain(totalFees);
    var pnlCls = 'bot-perf-summary-value' + _perfColorClass(totalPnl);

    _botPerfDomSuffixes().forEach(function (suf) {
        var rangeEl = document.getElementById('botPerformanceRange' + suf);
        var pnlLabelEl = document.getElementById('botPerfPnlLabel' + suf);
        var feesLabelEl = document.getElementById('botPerfFeesLabel' + suf);
        var pnlEl = document.getElementById('botPerfTotalPnl' + suf);
        var feesEl = document.getElementById('botPerfTotalFees' + suf);
        if (rangeEl) rangeEl.textContent = rangeTxt;
        if (pnlLabelEl) pnlLabelEl.textContent = pnlLabelTxt;
        if (feesLabelEl) feesLabelEl.textContent = feesLabelTxt;
        if (pnlEl) {
            pnlEl.textContent = pnlTxt;
            pnlEl.className = pnlCls;
        }
        if (feesEl) {
            feesEl.textContent = feesTxt;
            feesEl.className = 'bot-perf-summary-value bot-perf-summary-value--muted';
        }
    });
    if (State.accountId) {
        _persistBotPerfCache(State.accountId, forPeriod, data);
        try { sessionStorage.setItem('dashboard_bot_perf_period_' + State.accountId, forPeriod); } catch (e) {}
    }
}

async function loadBotPerformance(period) {
    if (!State.accountId || !window.apiClient) return;
    period = (period || 'all').toLowerCase();
    if (!['daily', 'weekly', 'monthly', 'all'].includes(period)) period = 'all';
    State.botPerformancePeriod = period;
    var requestedPeriod = period;
    if (requestedPeriod !== _botPerformanceLastPeriod) {
        _botPerformanceLastSig = '';
    }
    var hadCache = hydrateBotPerformanceFromCache(State.accountId, requestedPeriod);
    if (!hadCache && !_botPerformanceLoaded) {
        _botPerfDomSuffixes().forEach(function (suf) {
            var pnlEl = document.getElementById('botPerfTotalPnl' + suf);
            var feesEl = document.getElementById('botPerfTotalFees' + suf);
            if (pnlEl) pnlEl.textContent = '…';
            if (feesEl) feesEl.textContent = '…';
        });
    }
    try {
        var res = await window.apiClient.get('/api/accounts/' + State.accountId + '/bot-performance?period=' + encodeURIComponent(period));
        var d = (res && (res.data || res.pnl_usd != null)) ? (res.data || res) : null;
        if (!d) {
            renderBotPerformancePanel({ totals: {} }, requestedPeriod);
            return;
        }
        var sig = requestedPeriod + '|' + (d.pnl_usd != null ? d.pnl_usd : '') + '|' + (d.hourly_series ? d.hourly_series.length : 0) + '|' + (d.daily_series ? d.daily_series.length : 0);
        if (sig === _botPerformanceLastSig && requestedPeriod === _botPerformanceLastPeriod) return;
        _botPerformanceLastSig = sig;
        _botPerformanceLastPeriod = requestedPeriod;
        renderBotPerformancePanel(d, requestedPeriod);
    } catch (e) {
        if (window.errorReporter) window.errorReporter.report(e, { tab: 'dashboard', account_id: State.accountId, action: 'loadBotPerformance' });
        renderBotPerformancePanel({ totals: {} }, requestedPeriod);
    }
    _botPerformanceLoaded = true;
}
window.loadBotPerformance = loadBotPerformance;

function normalizeRunningSinceIso(iso) {
    if (!iso || typeof iso !== 'string') return '';
    var s = iso.trim();
    if (!s) return '';
    if (s.indexOf('T') < 0 && s.indexOf(' ') > 0) s = s.replace(' ', 'T');
    if (!/Z$/i.test(s) && !/[+-]\d{2}:?\d{2}$/.test(s.slice(-6))) s += 'Z';
    return s;
}

function leaderboardStartMonthDays(runningSinceIso) {
    var norm = normalizeRunningSinceIso(runningSinceIso);
    if (!norm) return 30;
    var d = new Date(norm);
    if (isNaN(d.getTime())) return 30;
    var yyyy = d.getFullYear();
    var mm = d.getMonth();
    var key = 'leaderboardDurationStartMonthDays:v1:' + yyyy + '-' + (mm + 1);
    try {
        var cached = Number(sessionStorage.getItem(key));
        if (cached >= 28 && cached <= 31) return cached;
    } catch (e) {}
    var days = new Date(yyyy, mm + 1, 0).getDate();
    try { sessionStorage.setItem(key, String(days)); } catch (e2) {}
    return days;
}

/** Bot detay stateHeroMetaDur ile aynı format ve UTC kaynak. */
function formatLeaderboardRunningDuration(runningSinceIso) {
    var norm = normalizeRunningSinceIso(runningSinceIso);
    if (!norm) return '—';
    try {
        var d = new Date(norm);
        if (isNaN(d.getTime())) return '—';
        var ms = Math.max(0, Date.now() - d.getTime());
        var totalMinutes = Math.floor(ms / 60000);
        var totalHours = Math.floor(ms / 3600000);
        var totalDays = Math.floor(ms / 86400000);
        var monthDays = leaderboardStartMonthDays(norm);
        if (totalDays >= monthDays) {
            return Math.floor(totalDays / monthDays) + ' ay ' + (totalDays % monthDays) + ' gün';
        }
        if (totalDays >= 1) {
            return totalDays + ' gün ' + Math.floor((ms % 86400000) / 3600000) + ' sa';
        }
        return totalHours + ' sa ' + Math.max(0, totalMinutes % 60) + ' dk';
    } catch (e) { return '—'; }
}

function formatLeaderboardTotalPnl(item) {
    var pct = item && item.profit_pct != null ? Number(item.profit_pct) : null;
    if (pct == null || !Number.isFinite(pct)) {
        var pnl = item && item.total_pnl_usd != null ? Number(item.total_pnl_usd) : null;
        pct = pnl != null && Number.isFinite(pnl) ? pnl : 0;
    }
    return {
        text: fmtSignedPct(pct),
        color: pct >= 0 ? '#0ecb81' : '#f6465d'
    };
}

function roundPct2(v) {
    if (v == null || v === '' || isNaN(Number(v))) return v;
    return Math.round(Number(v) * 100) / 100;
}

function fmtPctDisplay(v) {
    if (v == null || isNaN(Number(v))) return '—';
    return Number(v).toFixed(2);
}

function roundLeaderboardPctFields(p) {
    if (!p || typeof p !== 'object') return p;
    p = Object.assign({}, p);
    [
        'base_alloc_pct', 'quote_alloc_pct',
        'sell_trigger_trailing_pct', 'buy_trigger_trailing_pct',
        'profit_reentry_drop_pct', 'profit_reentry_rise_pct',
        'profit_exit_rise_pct', 'profit_exit_drop_pct'
    ].forEach(function (k) {
        if (p[k] != null) p[k] = roundPct2(p[k]);
    });
    if (Array.isArray(p.sell_grids)) {
        p.sell_grids = p.sell_grids.map(function (g) {
            return {
                sell_grid_pct: roundPct2(g.sell_grid_pct != null ? g.sell_grid_pct : g.trigger_pct),
                sell_qty_pct_of_base: roundPct2(g.sell_qty_pct_of_base != null ? g.sell_qty_pct_of_base : g.qty_pct)
            };
        });
    }
    if (Array.isArray(p.buy_grids)) {
        p.buy_grids = p.buy_grids.map(function (g) {
            return {
                buy_grid_pct: roundPct2(g.buy_grid_pct != null ? g.buy_grid_pct : g.trigger_pct),
                buy_qty_pct_of_quote: roundPct2(g.buy_qty_pct_of_quote != null ? g.buy_qty_pct_of_quote : g.qty_pct)
            };
        });
    }
    return p;
}

function normalizeLeaderboardParamsToFormConfig(params) {
    if (!params || typeof params !== 'object') return {};
    var p = Object.assign({}, params);

    function mapSellGrids(grids) {
        return (grids || []).map(function (g) {
                return {
                    trigger_pct: roundPct2(g.sell_grid_pct != null ? g.sell_grid_pct : g.trigger_pct),
                    qty_pct: roundPct2(g.sell_qty_pct_of_base != null ? g.sell_qty_pct_of_base : g.qty_pct)
                };
        });
    }
    function mapBuyGrids(grids) {
        return (grids || []).map(function (g) {
                return {
                    trigger_pct: roundPct2(g.buy_grid_pct != null ? g.buy_grid_pct : g.trigger_pct),
                    qty_pct: roundPct2(g.buy_qty_pct_of_quote != null ? g.buy_qty_pct_of_quote : g.qty_pct)
                };
        });
    }

    // sell_grids / buy_grids authoritative (dynamic snapshot merge); stale up/down must not win.
    if (Array.isArray(p.sell_grids) && p.sell_grids.length) {
        p.up = {
            trail_pct: roundPct2(p.sell_trigger_trailing_pct != null ? p.sell_trigger_trailing_pct : (p.up && p.up.trail_pct)),
            grids: mapSellGrids(p.sell_grids)
        };
    } else if ((p.sell_grids || p.buy_grids) && !p.up) {
        p.up = {
            trail_pct: roundPct2(p.sell_trigger_trailing_pct),
            grids: mapSellGrids(p.sell_grids)
        };
    }
    if (Array.isArray(p.buy_grids) && p.buy_grids.length) {
        p.down = {
            trail_pct: roundPct2(p.buy_trigger_trailing_pct != null ? p.buy_trigger_trailing_pct : (p.down && p.down.trail_pct)),
            grids: mapBuyGrids(p.buy_grids)
        };
    } else if (p.buy_grids && !p.down) {
        p.down = {
            trail_pct: roundPct2(p.buy_trigger_trailing_pct),
            grids: mapBuyGrids(p.buy_grids)
        };
    }
    if (p.up && !p.sell_grids && p.up.grids) {
        p.sell_grids = p.up.grids.map(function (g) {
            return { sell_grid_pct: g.trigger_pct, sell_qty_pct_of_base: g.qty_pct };
        });
        if (p.up.trail_pct != null) p.sell_trigger_trailing_pct = p.up.trail_pct;
    }
    if (p.down && !p.buy_grids && p.down.grids) {
        p.buy_grids = p.down.grids.map(function (g) {
            return { buy_grid_pct: g.trigger_pct, buy_qty_pct_of_quote: g.qty_pct };
        });
        if (p.down.trail_pct != null) p.buy_trigger_trailing_pct = p.down.trail_pct;
    }
    if (p.profit_reentry_drop_pct != null || p.profit_reentry_rise_pct != null
        || p.profit_exit_rise_pct != null || p.profit_exit_drop_pct != null) {
        p.profit = {
            rebuy_trigger_pct: roundPct2(p.profit_reentry_drop_pct != null ? p.profit_reentry_drop_pct : (p.profit && p.profit.rebuy_trigger_pct)),
            rebuy_trail_pct: roundPct2(p.profit_reentry_rise_pct != null ? p.profit_reentry_rise_pct : (p.profit && p.profit.rebuy_trail_pct)),
            resell_trigger_pct: roundPct2(p.profit_exit_rise_pct != null ? p.profit_exit_rise_pct : (p.profit && p.profit.resell_trigger_pct)),
            resell_trail_pct: roundPct2(p.profit_exit_drop_pct != null ? p.profit_exit_drop_pct : (p.profit && p.profit.resell_trail_pct))
        };
    }
    if (p.base_alloc_pct != null || p.quote_alloc_pct != null) {
        p.allocation = {
            base_pct: roundPct2(p.base_alloc_pct != null ? p.base_alloc_pct : (p.allocation && p.allocation.base_pct)),
            quote_pct: roundPct2(p.quote_alloc_pct != null ? p.quote_alloc_pct : (p.allocation && p.allocation.quote_pct))
        };
    }
    return p;
}

function mergeLeaderboardParamsWithApplied(params, applied) {
    if (!applied || typeof applied !== 'object') {
        return normalizeLeaderboardParamsToFormConfig(params || {});
    }
    var base = normalizeLeaderboardParamsToFormConfig(params || {});
    var merged = Object.assign({}, base, {
        base_alloc_pct: applied.base_alloc_pct != null ? applied.base_alloc_pct : base.base_alloc_pct,
        quote_alloc_pct: applied.quote_alloc_pct != null ? applied.quote_alloc_pct : base.quote_alloc_pct,
        sell_trigger_trailing_pct: applied.sell_trigger_trailing_pct != null ? applied.sell_trigger_trailing_pct : base.sell_trigger_trailing_pct,
        buy_trigger_trailing_pct: applied.buy_trigger_trailing_pct != null ? applied.buy_trigger_trailing_pct : base.buy_trigger_trailing_pct,
        profit_reentry_drop_pct: applied.profit_reentry_drop_pct != null ? applied.profit_reentry_drop_pct : base.profit_reentry_drop_pct,
        profit_reentry_rise_pct: applied.profit_reentry_rise_pct != null ? applied.profit_reentry_rise_pct : base.profit_reentry_rise_pct,
        profit_exit_rise_pct: applied.profit_exit_rise_pct != null ? applied.profit_exit_rise_pct : base.profit_exit_rise_pct,
        profit_exit_drop_pct: applied.profit_exit_drop_pct != null ? applied.profit_exit_drop_pct : base.profit_exit_drop_pct,
        sell_grids: Array.isArray(applied.sell_grids) && applied.sell_grids.length ? applied.sell_grids : base.sell_grids,
        buy_grids: Array.isArray(applied.buy_grids) && applied.buy_grids.length ? applied.buy_grids : base.buy_grids
    });
    return normalizeLeaderboardParamsToFormConfig(roundLeaderboardPctFields(merged));
}

function resolveLeaderboardItemParams(params, itemIndex) {
    var idx = itemIndex != null && itemIndex !== '' ? parseInt(itemIndex, 10) : NaN;
    if (Number.isFinite(idx) && State.leaderboardItems && State.leaderboardItems[idx]) {
        var item = State.leaderboardItems[idx];
        var itemParams = normalizeLeaderboardParamsToFormConfig(item.params || {});
        if (item.symbol && !itemParams.symbol) itemParams.symbol = item.symbol;
        if (Object.keys(itemParams).length) return itemParams;
    }
    return normalizeLeaderboardParamsToFormConfig(params || {});
}

function renderBotParamsConfig(cfg, symbol, referencePrice, hideBudget) {
    cfg = cfg || {};
    var alloc = cfg.allocation || {};
    var up = cfg.up || {};
    var down = cfg.down || {};
    var sellGrids = cfg.sell_grids || up.grids || [];
    var buyGrids = cfg.buy_grids || down.grids || [];
    var budget = hideBudget ? null : (cfg.initial_capital_usdt != null ? cfg.initial_capital_usdt : (cfg.budget_usd != null ? cfg.budget_usd : null));
    var basePct = cfg.base_alloc_pct != null ? cfg.base_alloc_pct : (alloc.base_pct != null ? alloc.base_pct : null);
    var quotePct = cfg.quote_alloc_pct != null ? cfg.quote_alloc_pct : (alloc.quote_pct != null ? alloc.quote_pct : null);
    var sellTrail = cfg.sell_trigger_trailing_pct != null ? cfg.sell_trigger_trailing_pct : (up.trail_pct != null ? up.trail_pct : null);
    var buyTrail = cfg.buy_trigger_trailing_pct != null ? cfg.buy_trigger_trailing_pct : (down.trail_pct != null ? down.trail_pct : null);
    var refPriceVal = referencePrice != null && !isNaN(referencePrice)
        ? referencePrice
        : (cfg.reference_price != null && !isNaN(cfg.reference_price) ? Number(cfg.reference_price) : null);
    refPriceVal = refPriceVal != null && !isNaN(refPriceVal) ? fmtNum(refPriceVal, 4) : '—';
    var pr = cfg.profit || {};
    var reTr = cfg.profit_reentry_drop_pct != null ? cfg.profit_reentry_drop_pct : pr.rebuy_trigger_pct;
    var reTrl = cfg.profit_reentry_rise_pct != null ? cfg.profit_reentry_rise_pct : pr.rebuy_trail_pct;
    var exTr = cfg.profit_exit_rise_pct != null ? cfg.profit_exit_rise_pct : pr.resell_trigger_pct;
    var exTrl = cfg.profit_exit_drop_pct != null ? cfg.profit_exit_drop_pct : pr.resell_trail_pct;
    function row(l, v, cls) {
        var val = v !== undefined && v !== '' ? v : '—';
        if (typeof escapeHtml === 'function') val = escapeHtml(String(val));
        var lab = typeof escapeHtml === 'function' ? escapeHtml(l) : l;
        return '<div class="param-row' + (cls ? ' ' + cls : '') + '"><span class="param-label">' + lab + '</span><span class="param-value">' + val + '</span></div>';
    }
    var html = '';
    html += '<div class="param-block"><div class="param-block-title">Genel</div>';
    html += row('Sembol', symbol || cfg.symbol || '—');
    if (!hideBudget) html += row('Bütçe (USDT)', fmtUsd(budget));
    html += row('Başlangıç fiyatı (referans)', refPriceVal);
    html += row('Base dağılım (%)', basePct != null ? fmtPctDisplay(basePct) + '%' : '—');
    html += row('Quote dağılım (%)', quotePct != null ? fmtPctDisplay(quotePct) + '%' : '—');
    html += '</div>';
    html += '<div class="param-block"><div class="param-block-title">Satış gridleri</div>';
    html += row('Grid sayısı', sellGrids.length || cfg.sell_grids_count || 0, 'param-sell');
    html += row('Trailing % (tetik sonrası gerçekleşme)', sellTrail != null ? fmtPctDisplay(sellTrail) + '%' : '—', 'param-sell');
    if (sellGrids.length) {
        html += '<table class="param-table"><thead><tr><th>Seviye</th><th class="num">Tetik %</th><th class="num">Miktar (base %)</th></tr></thead><tbody>';
        sellGrids.forEach(function (g, i) {
            var pct = g.sell_grid_pct != null ? g.sell_grid_pct : g.trigger_pct;
            var qty = g.sell_qty_pct_of_base != null ? g.sell_qty_pct_of_base : g.qty_pct;
            html += '<tr><td>#' + (i + 1) + '</td><td class="num">+' + fmtPctDisplay(pct) + '%</td><td class="num">' + fmtPctDisplay(qty) + '%</td></tr>';
        });
        html += '</tbody></table>';
    } else {
        html += '<p class="param-hint">Tanımlı değil.</p>';
    }
    html += '</div>';
    html += '<div class="param-block"><div class="param-block-title">Alım gridleri</div>';
    html += row('Grid sayısı', buyGrids.length || cfg.buy_grids_count || 0, 'param-buy');
    html += row('Trailing % (tetik sonrası gerçekleşme)', buyTrail != null ? fmtPctDisplay(buyTrail) + '%' : '—', 'param-buy');
    if (buyGrids.length) {
        html += '<table class="param-table"><thead><tr><th>Seviye</th><th class="num">Tetik %</th><th class="num">Miktar (quote %)</th></tr></thead><tbody>';
        buyGrids.forEach(function (g, i) {
            var pct = g.buy_grid_pct != null ? g.buy_grid_pct : g.trigger_pct;
            var qty = g.buy_qty_pct_of_quote != null ? g.buy_qty_pct_of_quote : g.qty_pct;
            html += '<tr><td>#' + (i + 1) + '</td><td class="num">-' + fmtPctDisplay(pct) + '%</td><td class="num">' + fmtPctDisplay(qty) + '%</td></tr>';
        });
        html += '</tbody></table>';
    } else {
        html += '<p class="param-hint">Tanımlı değil.</p>';
    }
    html += '</div>';
    html += '<div class="param-block"><div class="param-block-title">Kar alım / kar satış</div>';
    html += row('Kar alım tetik %', reTr != null ? fmtPctDisplay(reTr) + '%' : '—');
    html += row('Kar alım trailing %', reTrl != null ? fmtPctDisplay(reTrl) + '%' : '—');
    html += row('Kar satış tetik %', exTr != null ? fmtPctDisplay(exTr) + '%' : '—');
    html += row('Kar satış trailing %', exTrl != null ? fmtPctDisplay(exTrl) + '%' : '—');
    html += '<p class="param-hint">Kar alım: fiyat düşünce tekrar alım. Kar satış: fiyat yükselince kar realizasyonu satışı.</p>';
    html += '</div>';
    return html;
}

function applyTrailingDcaConfigToForm(p, opts) {
    opts = opts || {};
    if (!p || typeof p !== 'object') return;
    p = normalizeLeaderboardParamsToFormConfig(p);
    var symEl = document.getElementById('fSymbol');
    var budgetEl = document.getElementById('fBudget');
    var basePctEl = document.getElementById('fBasePct');
    var quotePctEl = document.getElementById('fQuotePct');
    if (symEl && p.symbol) {
        symEl.value = p.symbol;
        symEl.readOnly = !!opts.symbolReadOnly;
    }
    if (budgetEl) budgetEl.value = opts.clearBudget ? '' : (p.budget_usd != null ? p.budget_usd : (p.initial_capital_usdt != null ? p.initial_capital_usdt : budgetEl.value));
    var alloc = p.allocation || {};
    if (basePctEl) {
        var basePct = p.base_alloc_pct != null ? p.base_alloc_pct : alloc.base_pct;
        if (basePct != null || basePct === 0) basePctEl.value = roundPct2(basePct);
    }
    if (quotePctEl) {
        var quotePct = p.quote_alloc_pct != null ? p.quote_alloc_pct : alloc.quote_pct;
        if (quotePct != null || quotePct === 0) quotePctEl.value = roundPct2(quotePct);
    }
    var up = p.up || {};
    var down = p.down || {};
    var profit = p.profit || {};
    var upGrids = up.grids || [];
    var downGrids = down.grids || [];
    var upCountEl = document.getElementById('fUpCount');
    var downCountEl = document.getElementById('fDownCount');
    if (upCountEl && upGrids.length > 0) { upCountEl.value = upGrids.length; buildGridRows('upGridRows', upGrids.length, 'up'); }
    if (downCountEl && downGrids.length > 0) { downCountEl.value = downGrids.length; buildGridRows('downGridRows', downGrids.length, 'down'); }
    var upTrailEl = document.getElementById('fUpTrail');
    var downTrailEl = document.getElementById('fDownTrail');
    if (upTrailEl && (up.trail_pct != null || up.trail_pct === 0)) upTrailEl.value = roundPct2(up.trail_pct);
    if (downTrailEl && (down.trail_pct != null || down.trail_pct === 0)) downTrailEl.value = roundPct2(down.trail_pct);
    for (var i = 0; i < upGrids.length; i++) {
        var tEl = document.getElementById('upGrid_' + i + '_trigger');
        var qEl = document.getElementById('upGrid_' + i + '_qty');
        if (tEl && upGrids[i].trigger_pct != null) tEl.value = roundPct2(upGrids[i].trigger_pct);
        if (qEl && upGrids[i].qty_pct != null) qEl.value = roundPct2(upGrids[i].qty_pct);
    }
    for (var j = 0; j < downGrids.length; j++) {
        var t2 = document.getElementById('downGrid_' + j + '_trigger');
        var q2 = document.getElementById('downGrid_' + j + '_qty');
        if (t2 && downGrids[j].trigger_pct != null) t2.value = roundPct2(downGrids[j].trigger_pct);
        if (q2 && downGrids[j].qty_pct != null) q2.value = roundPct2(downGrids[j].qty_pct);
    }
    var rebuyT = document.getElementById('fRebuyTrigger');
    var rebuyTrail = document.getElementById('fRebuyTrail');
    var resellT = document.getElementById('fResellTrigger');
    var resellTrail = document.getElementById('fResellTrail');
    if (rebuyT && (profit.rebuy_trigger_pct != null || profit.rebuy_trigger_pct === 0)) rebuyT.value = roundPct2(profit.rebuy_trigger_pct);
    if (rebuyTrail && profit.rebuy_trail_pct != null) rebuyTrail.value = roundPct2(profit.rebuy_trail_pct);
    if (resellT && (profit.resell_trigger_pct != null || profit.resell_trigger_pct === 0)) resellT.value = roundPct2(profit.resell_trigger_pct);
    if (resellTrail && profit.resell_trail_pct != null) resellTrail.value = roundPct2(profit.resell_trail_pct);
    if (p.symbol && typeof updateCreateBotModalPairStrip === 'function') updateCreateBotModalPairStrip(p.symbol);
}

/** En İyi 5 Bot: tek kaynak state – flicker yok. Sadece içerik gerçekten değişince DOM güncellenir. */

State.txHistoryPeriod = State.txHistoryPeriod || 'daily';
State.txHistoryType = State.txHistoryType || 'buysell';
State.txHistoryPage = State.txHistoryPage || 1;
var _txHistoryRevision = '';
