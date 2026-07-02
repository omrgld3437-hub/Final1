/**
 * dashboard-leaderboard.js
 * Global Leaderboard — dashboard.js'ten çıkarıldı.
 * dashboard.html'de dashboard.js'ten SONRA yüklenir
 * (State, assetsState gibi globallere runtime'da erişir).
 */

var LEADERBOARD_EMPTY_HTML = '<div style="text-align: center; color: var(--ds-text-secondary); font-size: 0.9rem; padding: 1rem;">Henüz listelenecek aktif bot yok. Bu sıralama yalnızca çalışan ve toplam K/Z\'si sıfır veya pozitif olan botları gösterir.</div>';
var LEADERBOARD_NO_PROFIT_HTML = '<div style="text-align: center; color: var(--ds-text-secondary); font-size: 0.9rem; padding: 1rem;">Karda olan bot bulunamadı. Liste yalnızca çalışan ve toplam K/Z\'si sıfır veya pozitif olan botları gösterir.</div>';
var LEADERBOARD_LOADING_HTML = '<div style="text-align: center; color: var(--ds-text-secondary); padding: 1rem;">Yükleniyor…</div>';
var LEADERBOARD_LOAD_TIMEOUT_MS = 10000;
var _leaderboardLoadTimeoutId = null;
var _leaderboardSyncDebounce = null;
var LEADERBOARD_RANK_SWAP_MIN_GAP_PCT = 0.15;
var LEADERBOARD_RANK_SWAP_STABLE_POLLS = 2;
var _leaderboardRankCandidate = null;

function leaderboardItemKey(item) {
    var sym = String((item && (item.symbol || (item.params && item.params.symbol))) || '').toUpperCase().replace(/\s/g, '');
    var sid = String((item && item.structure_id) || 'trailing_dca').toLowerCase();
    return sym + '|' + sid;
}

function sortLeaderboardItemsByProfit(items) {
    return (items || []).slice().sort(function (a, b) {
        var pa = a.profit_pct != null && Number.isFinite(Number(a.profit_pct)) ? Number(a.profit_pct) : -Infinity;
        var pb = b.profit_pct != null && Number.isFinite(Number(b.profit_pct)) ? Number(b.profit_pct) : -Infinity;
        if (pb !== pa) return pb - pa;
        return leaderboardItemKey(a).localeCompare(leaderboardItemKey(b));
    });
}

/** Küçük K/Z farklarında sıra zıplamasını önle — yeni set veya kalıcı fark olunca sırala. */
function stabilizeLeaderboardOrder(incoming) {
    incoming = sortLeaderboardItemsByProfit(incoming);
    if (!incoming.length) {
        State.leaderboardDisplayOrder = [];
        _leaderboardRankCandidate = null;
        return incoming;
    }
    var apiOrder = incoming.map(leaderboardItemKey);
    var prevOrder = State.leaderboardDisplayOrder || [];
    if (!prevOrder.length || State.leaderboardLastState !== 'items') {
        State.leaderboardDisplayOrder = apiOrder.slice();
        _leaderboardRankCandidate = null;
        return incoming;
    }
    var prevSet = prevOrder.slice().sort().join(',');
    var apiSet = apiOrder.slice().sort().join(',');
    if (prevSet !== apiSet) {
        State.leaderboardDisplayOrder = apiOrder.slice();
        _leaderboardRankCandidate = null;
        return incoming;
    }
    if (prevOrder.join('>') === apiOrder.join('>')) {
        _leaderboardRankCandidate = null;
        return incoming;
    }
    var orderSig = apiOrder.join('>');
    if (!_leaderboardRankCandidate || _leaderboardRankCandidate.sig !== orderSig) {
        _leaderboardRankCandidate = { sig: orderSig, count: 1 };
    } else {
        _leaderboardRankCandidate.count += 1;
    }
    var gapOk = true;
    for (var i = 0; i < incoming.length - 1; i++) {
        var a = Number(incoming[i].profit_pct != null ? incoming[i].profit_pct : 0);
        var b = Number(incoming[i + 1].profit_pct != null ? incoming[i + 1].profit_pct : 0);
        if (!Number.isFinite(a) || !Number.isFinite(b) || Math.abs(a - b) < LEADERBOARD_RANK_SWAP_MIN_GAP_PCT) {
            gapOk = false;
            break;
        }
    }
    if (_leaderboardRankCandidate.count >= LEADERBOARD_RANK_SWAP_STABLE_POLLS || gapOk) {
        State.leaderboardDisplayOrder = apiOrder.slice();
        _leaderboardRankCandidate = null;
        return incoming;
    }
    var byKey = {};
    incoming.forEach(function (item) { byKey[leaderboardItemKey(item)] = item; });
    return prevOrder.map(function (k) { return byKey[k]; }).filter(Boolean);
}

function buildGlobalLeaderboardOrderSignature(items) {
    if (!Array.isArray(items)) return '';
    return items.map(leaderboardItemKey).join('>');
}

function clearLeaderboardLoadTimeout() {
    if (_leaderboardLoadTimeoutId) {
        clearTimeout(_leaderboardLoadTimeoutId);
        _leaderboardLoadTimeoutId = null;
    }
}

function scheduleLeaderboardLoadTimeout() {
    clearLeaderboardLoadTimeout();
    _leaderboardLoadTimeoutId = setTimeout(function () {
        _leaderboardLoadTimeoutId = null;
        if (State.leaderboardLastState !== 'loading') return;
        var listEls = _globalLeaderboardListEls();
        if (!listEls.length) return;
        State.leaderboardLastState = 'empty';
        State.leaderboardItems = [];
        State.leaderboardStructureSig = null;
        State.leaderboardMetricsSig = null;
        State.leaderboardOrderSig = null;
        State.leaderboardDisplayOrder = [];
        _leaderboardRankCandidate = null;
        listEls.forEach(function (el) { el.innerHTML = LEADERBOARD_NO_PROFIT_HTML; });
        if (window.intervalRegistry) window.intervalRegistry.stop('dashboard.leaderboard');
    }, LEADERBOARD_LOAD_TIMEOUT_MS);
}

function setGlobalLeaderboardEmpty(html, stopPoll) {
    var listEls = _globalLeaderboardListEls();
    var msg = html || LEADERBOARD_EMPTY_HTML;
    State.leaderboardLastState = 'empty';
    State.leaderboardItems = [];
    State.leaderboardStructureSig = null;
    State.leaderboardMetricsSig = null;
    State.leaderboardOrderSig = null;
    State.leaderboardDisplayOrder = [];
    _leaderboardRankCandidate = null;
    listEls.forEach(function (el) {
        if (el.innerHTML !== msg) el.innerHTML = msg;
    });
    if (stopPoll !== false && window.intervalRegistry) window.intervalRegistry.stop('dashboard.leaderboard');
}

/** API + hesaptaki canlı K/Z: ekside kalan botları listeden çıkar. */
function filterLeaderboardItemsForDisplay(items) {
    if (!Array.isArray(items) || !items.length) return [];
    return items.filter(function (item) {
        var pct = item.profit_pct != null ? Number(item.profit_pct) : null;
        var pnl = item.total_pnl_usd != null ? Number(item.total_pnl_usd) : null;
        if (pnl != null && Number.isFinite(pnl) && pnl < 0) return false;
        if (pct != null && Number.isFinite(pct) && pct < 0) return false;
        var sym = (item.symbol || (item.params && item.params.symbol) || '').toUpperCase().replace(/\s/g, '');
        if (!sym || !State.bots || !State.bots.length) return true;
        for (var i = 0; i < State.bots.length; i++) {
            var b = State.bots[i];
            if ((b.symbol || '').toUpperCase() !== sym) continue;
            if (String(b.status || '').toLowerCase() !== 'running') continue;
            var kz = typeof resolveBotHeroKz === 'function' ? resolveBotHeroKz(b) : null;
            if (!kz) return true;
            if (kz.pct != null && Number.isFinite(kz.pct) && kz.pct < 0) return false;
            if (kz.usd != null && Number.isFinite(kz.usd) && kz.usd < 0) return false;
            break;
        }
        return true;
    });
}

function buildGlobalLeaderboardMetricsSignature(items) {
    if (!Array.isArray(items)) return '';
    return items.map(function (item) {
        return leaderboardItemKey(item) + ':' + (item.profit_pct != null ? item.profit_pct : '') + ':' + (item.total_pnl_usd != null ? item.total_pnl_usd : '') + ':' + (item.cycles_count != null ? item.cycles_count : '');
    }).join('|');
}

function formatLeaderboardCyclesLabel(item) {
    var n = item && item.cycles_count != null ? Number(item.cycles_count) : NaN;
    if (!Number.isFinite(n) || n < 0) return 'Tamamlanan tur: —';
    return 'Tamamlanan tur: ' + String(Math.floor(n));
}

/** Leaderboard coin logos — DOM yeniden kurulunca cache'den src; yoksa lazy observer. */
function buildLeaderboardSymbolLogoHtml(symbolStr) {
    var sym = (typeof symbolStr === 'string' ? symbolStr : '').trim() || '—';
    var logoUrl = (typeof getCoinLogoUrl === 'function' ? getCoinLogoUrl(sym) : null);
    var initials = (typeof getCoinLogoInitials === 'function' ? getCoinLogoInitials(sym) : (sym.length >= 1 ? sym.substring(0, 1).toUpperCase() : '—'));
    if (typeof escapeHtml === 'function') initials = escapeHtml(initials);
    if (!logoUrl) {
        return '<span class="global-leaderboard-symbol-initials">' + initials + '</span>';
    }
    var escUrl = (typeof escapeHtml === 'function' ? escapeHtml(logoUrl) : logoUrl);
    var escSym = (typeof escapeHtml === 'function' ? escapeHtml(sym) : sym);
    var onload = 'if(window.markCoinLogoLoaded)window.markCoinLogoLoaded(this)';
    var onerr = 'if(window.handleCoinLogoError)window.handleCoinLogoError(this)';
    var wrapStart = '<span class="global-leaderboard-symbol-logo-wrap" style="position:relative;display:inline-flex;align-items:center;justify-content:center;">';
    var initialsSpan = '<span class="global-leaderboard-symbol-initials" style="display:none;position:absolute;inset:0;align-items:center;justify-content:center;font-size:0.65rem;font-weight:600;background:var(--ds-bg-tertiary);color:var(--ds-text-secondary);border-radius:50%;">' + initials + '</span>';
    var eager = (typeof shouldEagerLoadLogo === 'function' && shouldEagerLoadLogo(sym)) ||
        (window.coinLogoCache && window.coinLogoCache.get(logoUrl));
    if (eager) {
        return wrapStart + '<img src="' + escUrl + '" alt="' + escSym + '" data-symbol="' + escSym + '" class="global-leaderboard-symbol-logo" decoding="async" onload="' + onload + '" onerror="' + onerr + '" />' + initialsSpan + '</span>';
    }
    return wrapStart + '<img class="global-leaderboard-symbol-logo lazy-coin-logo" data-src="' + escUrl + '" alt="' + escSym + '" data-symbol="' + escSym + '" decoding="async" onload="' + onload + '" onerror="' + onerr + '" />' + initialsSpan + '</span>';
}

function hydrateLeaderboardListLogos(listEl) {
    if (!listEl) return;
    ensureLazyLogoObserver();
    listEl.querySelectorAll('.global-leaderboard-symbol-logo').forEach(function (img) {
        var dataSrc = img.getAttribute('data-src');
        var sym = img.getAttribute('data-symbol') || img.getAttribute('alt') || '';
        if (!dataSrc) {
            if (img.src && window.coinLogoCache) window.coinLogoCache.set(img.src.split('?')[0], true);
            return;
        }
        if ((typeof shouldEagerLoadLogo === 'function' && shouldEagerLoadLogo(sym)) ||
            (window.coinLogoCache && window.coinLogoCache.get(dataSrc))) {
            img.src = dataSrc;
            img.removeAttribute('data-src');
            img.classList.remove('lazy-coin-logo');
            return;
        }
        if (window._lazyLogoObserver) window._lazyLogoObserver.observe(img);
    });
}

function scheduleLeaderboardSyncFromBots() {
    clearTimeout(_leaderboardSyncDebounce);
    _leaderboardSyncDebounce = setTimeout(function () {
        _leaderboardSyncDebounce = null;
        if (State.leaderboardLastState !== 'items' || !State.leaderboardItems || !State.leaderboardItems.length) return;
        var filtered = filterLeaderboardItemsForDisplay(State.leaderboardItems);
        if (filtered.length < State.leaderboardItems.length && typeof loadGlobalLeaderboard === 'function') {
            loadGlobalLeaderboard(false);
            return;
        }
        State.leaderboardItems = enrichLeaderboardItemsDynamicMode(State.leaderboardItems);
        patchGlobalLeaderboardMetrics(State.leaderboardItems);
    }, 350);
}

var LEADERBOARD_PARAM_LABELS = {
    symbol: 'Sembol',
    trail_pct: 'Trail %',
    up_trail_pct: 'Yukarı trail %',
    down_trail_pct: 'Aşağı trail %',
    grid_count: 'Grid sayısı',
    base_alloc_pct: 'Base dağılım %',
    quote_alloc_pct: 'Quote dağılım %',
    structure_id: 'Yapı',
    strategy_id: 'Strateji'
};
var LEADERBOARD_PARAM_SKIP_KEYS = { budget_usd: 1, bot_budget_quote: 1, initial_capital_usdt: 1 };

function stripLeaderboardBudgetFromParams(params) {
    if (!params || typeof params !== 'object') return params;
    var p = Object.assign({}, params);
    delete p.initial_capital_usdt;
    delete p.budget_usd;
    delete p.bot_budget_quote;
    return p;
}

function formatLeaderboardParamsForDisplay(params) {
    if (!params || typeof params !== 'object') return '<p class="muted">Parametre yok.</p>';
    var parts = [];
    function row(label, val) {
        var valStr = val === null || val === undefined ? '—' : (Array.isArray(val) ? JSON.stringify(val) : (typeof val === 'number' ? (Number.isInteger(val) ? String(val) : val.toFixed(4)) : String(val)));
        if (typeof escapeHtml === 'function') valStr = escapeHtml(valStr);
        var lab = (typeof escapeHtml === 'function' ? escapeHtml(label) : label);
        return '<div class="leaderboard-param-row"><span class="leaderboard-param-label">' + lab + '</span><span class="leaderboard-param-value">' + valStr + '</span></div>';
    }
    function gridTable(grids, title) {
        if (!Array.isArray(grids) || !grids.length) return '';
        var rows = grids.map(function (g) {
            var tr = (g.trigger_pct != null ? g.trigger_pct + '%' : '—');
            var qty = (g.qty_pct != null ? g.qty_pct + '%' : '—');
            return '<tr><td>' + (typeof escapeHtml === 'function' ? escapeHtml(String(tr)) : tr) + '</td><td>' + (typeof escapeHtml === 'function' ? escapeHtml(String(qty)) : qty) + '</td></tr>';
        }).join('');
        return (title ? '<div class="leaderboard-param-section-title">' + (typeof escapeHtml === 'function' ? escapeHtml(title) : title) + '</div>' : '') + '<table class="leaderboard-param-grid-table"><thead><tr><th>Tetik %</th><th>Miktar %</th></tr></thead><tbody>' + rows + '</tbody></table>';
    }
    Object.keys(params).forEach(function (k) {
        if (LEADERBOARD_PARAM_SKIP_KEYS[k] || k === 'up' || k === 'down') return;
        var v = params[k];
        if (v !== null && v !== undefined && typeof v === 'object' && !Array.isArray(v) && v.constructor === Object) return;
        var label = LEADERBOARD_PARAM_LABELS[k] || k;
        parts.push(row(label, v));
    });
    if (params.up && typeof params.up === 'object') {
        parts.push('<div class="leaderboard-param-section"><div class="leaderboard-param-section-title">Yukarı (satış) grid</div>');
        if (params.up.trail_pct != null) parts.push(row('Trail %', params.up.trail_pct));
        parts.push(gridTable(params.up.grids || [], ''));
        parts.push('</div>');
    }
    if (params.down && typeof params.down === 'object') {
        parts.push('<div class="leaderboard-param-section"><div class="leaderboard-param-section-title">Aşağı (alım) grid</div>');
        if (params.down.trail_pct != null) parts.push(row('Trail %', params.down.trail_pct));
        parts.push(gridTable(params.down.grids || [], ''));
        parts.push('</div>');
    }
    return parts.length ? parts.join('') : '<p class="muted">Parametre yok.</p>';
}

function leaderboardParamsHasDetail(params) {
    if (!params || typeof params !== 'object') return false;
    if (Array.isArray(params.sell_grids) && params.sell_grids.length) return true;
    if (Array.isArray(params.buy_grids) && params.buy_grids.length) return true;
    var up = params.up && typeof params.up === 'object' ? params.up : {};
    var down = params.down && typeof params.down === 'object' ? params.down : {};
    return (Array.isArray(up.grids) && up.grids.length) || (Array.isArray(down.grids) && down.grids.length);
}

async function resolveLeaderboardItemForModal(itemIndex) {
    var idx = itemIndex != null && itemIndex !== '' ? parseInt(itemIndex, 10) : NaN;
    var item = Number.isFinite(idx) && State.leaderboardItems ? State.leaderboardItems[idx] : null;
    if (item && leaderboardParamsHasDetail(item.params || {})) return item;
    if (window.apiClient) {
        try {
            var res = await window.apiClient.get('/api/leaderboard/global/top?limit=5');
            var items = (res && Array.isArray(res.items)) ? res.items
                : (res && res.data && Array.isArray(res.data.items)) ? res.data.items
                : [];
            if (items.length) {
                State.leaderboardItems = items;
                if (Number.isFinite(idx) && items[idx]) return items[idx];
            }
        } catch (e) {}
    }
    return item;
}

function closeParametrelerModal() {
    var modal = document.getElementById('parametrelerModal');
    if (modal) modal.style.display = 'none';
    document.body.style.overflow = '';
    _leaderboardParamActiveTab = 'genel';
}

var _leaderboardParamGenelHtml = '';
var _leaderboardParamDynHtml = '';
var _leaderboardParamActiveTab = 'genel';

function getLeaderboardItemBotConfig(bot) {
    var cfg = (bot && bot.config) ? bot.config : {};
    if ((!cfg || !Object.keys(cfg).length) && bot && bot.config_json) {
        try {
            cfg = typeof bot.config_json === 'string' ? JSON.parse(bot.config_json) : (bot.config_json || {});
        } catch (e) {
            cfg = {};
        }
    }
    return cfg || {};
}

function findLocalBotForLeaderboardItem(item) {
    if (!item || !State.bots || !State.bots.length) return null;
    var sym = String(item.symbol || (item.params && item.params.symbol) || '').toUpperCase().replace(/\s/g, '');
    if (!sym) return null;
    var itemPct = item.profit_pct != null ? Number(item.profit_pct) : null;
    var matches = [];
    for (var i = 0; i < State.bots.length; i++) {
        var b = State.bots[i];
        if (String(b.symbol || '').toUpperCase().replace(/\s/g, '') !== sym) continue;
        if (String(b.status || '').toLowerCase() !== 'running') continue;
        matches.push({ bot: b, cfg: getLeaderboardItemBotConfig(b) });
    }
    if (!matches.length) return null;
    if (matches.length === 1) return matches[0];
    if (itemPct != null && Number.isFinite(itemPct) && typeof resolveBotHeroKz === 'function') {
        for (var j = 0; j < matches.length; j++) {
            var kz = resolveBotHeroKz(matches[j].bot);
            if (kz && kz.pct != null && Number.isFinite(Number(kz.pct)) && Math.abs(Number(kz.pct) - itemPct) < 0.2) {
                return matches[j];
            }
        }
    }
    return matches[0];
}

/** API dynamic_mode + hesaptaki eşleşen bot (Mevcut Botlar ile aynı mantık). */
function resolveLeaderboardItemDynamicMode(item) {
    var dyn = (item && item.dynamic_mode) ? Object.assign({}, item.dynamic_mode) : {};
    if (window.DynModeParamsView && window.DynModeParamsView.isLeaderboardDynamicBadgeVisible(dyn)) {
        var localEarly = findLocalBotForLeaderboardItem(item);
        if (localEarly && localEarly.bot && localEarly.bot.dynamic_mode && localEarly.bot.dynamic_mode.snapshot) {
            return Object.assign({}, localEarly.bot.dynamic_mode, dyn, {
                enabled: true,
                active: dyn.active !== false
            });
        }
        return dyn;
    }
    var local = findLocalBotForLeaderboardItem(item);
    if (!local) return dyn;
    var b = local.bot;
    var cfg = local.cfg;
    if (window.DynModeParamsView && window.DynModeParamsView.isDynamicModeActiveForList(b.dynamic_mode || {}, cfg, b.status)) {
        return Object.assign({}, b.dynamic_mode || {}, dyn, { enabled: true, active: dyn.active !== false });
    }
    if (cfg.dynamic_mode) {
        return Object.assign({}, dyn, { enabled: true, active: true });
    }
    return dyn;
}

function enrichLeaderboardItemsDynamicMode(items) {
    if (!Array.isArray(items)) return items;
    return items.map(function (item) {
        var resolved = resolveLeaderboardItemDynamicMode(item);
        if (!window.DynModeParamsView || !window.DynModeParamsView.isLeaderboardDynamicBadgeVisible(resolved)) {
            return item;
        }
        return Object.assign({}, item, { dynamic_mode: resolved });
    });
}

function patchLeaderboardRowDynamicUi(row, item) {
    if (!row || !item || !window.DynModeParamsView) return;
    var dyn = resolveLeaderboardItemDynamicMode(item);
    var params = stripLeaderboardBudgetFromParams(normalizeLeaderboardParamsToFormConfig(item.params || {}));
    var dynVisible = window.DynModeParamsView.isLeaderboardDynamicBadgeVisible(dyn);
    var dynTip = window.DynModeParamsView.dynamicModeLogoTipShort(dyn, params);
    var symWrap = row.querySelector('.global-leaderboard-symbol-wrap');
    if (symWrap) {
        var logoWrap = symWrap.querySelector('.dyn-mode-logo-wrap');
        var logoEl = symWrap.querySelector('.global-leaderboard-symbol-logo, .global-leaderboard-symbol-initials');
        if (dynVisible) {
            if (logoWrap) {
                logoWrap.setAttribute('data-dyn-tip', window.DynModeParamsView.attrEsc(dynTip));
            } else if (logoEl) {
                logoEl.outerHTML = window.DynModeParamsView.wrapLogoForDynamicMode(logoEl.outerHTML, true, dynTip);
            }
        } else if (logoWrap) {
            logoWrap.outerHTML = logoWrap.innerHTML;
        }
    }
    symWrap = row.querySelector('.global-leaderboard-symbol-wrap');
    if (symWrap) {
        var strayBadge = symWrap.querySelector('.dyn-mode-list-badge');
        if (strayBadge) strayBadge.remove();
    }
    var metaLeft = row.querySelector('.global-leaderboard-item-meta-left');
    var metaEl = row.querySelector('.global-leaderboard-item-meta');
    if (metaEl) {
        metaEl.querySelectorAll('.dyn-mode-list-badge').forEach(function (b) {
            if (!metaLeft || !metaLeft.contains(b)) b.remove();
        });
    }
    var badge = metaLeft ? metaLeft.querySelector('.dyn-mode-list-badge') : null;
    if (dynVisible) {
        var badgeHtml = window.DynModeParamsView.renderDynamicBadgeHtml(
            window.DynModeParamsView.dynamicModeHoverTitle(dyn, params)
        );
        if (badge) {
            if (badge.outerHTML !== badgeHtml) badge.outerHTML = badgeHtml;
        } else if (metaLeft) {
            var cyclesEl = metaLeft.querySelector('.global-leaderboard-item-cycles');
            if (cyclesEl) cyclesEl.insertAdjacentHTML('afterend', badgeHtml);
            else metaLeft.insertAdjacentHTML('beforeend', badgeHtml);
        }
    } else if (badge) {
        badge.remove();
    }
    row.setAttribute('data-dyn-visible', dynVisible ? '1' : '0');
}

function leaderboardItemDynamicVisible(item) {
    if (!item || !window.DynModeParamsView) return false;
    return window.DynModeParamsView.isLeaderboardDynamicBadgeVisible(resolveLeaderboardItemDynamicMode(item));
}

function bindLeaderboardParamTabHandlers() {
    var host = document.getElementById('paramTabsHost');
    if (!host || host.dataset.bound === '1') return;
    host.dataset.bound = '1';
    host.addEventListener('click', function (e) {
        var btn = e.target.closest('[data-param-tab]');
        if (!btn || !host.contains(btn)) return;
        var tab = btn.getAttribute('data-param-tab') || 'genel';
        if (tab === _leaderboardParamActiveTab) return;
        _leaderboardParamActiveTab = tab;
        refreshLeaderboardParamModalView();
    });
}

function refreshLeaderboardParamModalView() {
    var host = document.getElementById('paramTabsHost');
    var bodyEl = document.getElementById('configGrid');
    var showDyn = _leaderboardParamDynHtml && window.DynModeParamsView;
    if (host) {
        host.innerHTML = showDyn
            ? window.DynModeParamsView.renderParamModalTabsHtml(_leaderboardParamActiveTab)
            : '';
    }
    if (!bodyEl) return;
    if (_leaderboardParamActiveTab === 'dinamik' && showDyn) {
        bodyEl.innerHTML = _leaderboardParamDynHtml;
    } else {
        _leaderboardParamActiveTab = 'genel';
        bodyEl.innerHTML = _leaderboardParamGenelHtml || '<p class="param-hint">Parametre yok.</p>';
    }
}

function closeLeaderboardApplyModal() {
    var modal = document.getElementById('leaderboardApplyModal');
    if (modal) modal.style.display = 'none';
    document.body.style.overflow = '';
    _leaderboardApplyCallback = null;
}

var _leaderboardApplyCallback = null;

function initLeaderboardApplyModalHandlers() {
    if (initLeaderboardApplyModalHandlers._done) return;
    initLeaderboardApplyModalHandlers._done = true;
    var modal = document.getElementById('leaderboardApplyModal');
    var closeBtn = document.getElementById('leaderboardApplyModalClose');
    var cancelBtn = document.getElementById('leaderboardApplyCancelBtn');
    var tplBtn = document.getElementById('leaderboardApplyTemplateBtn');
    var dynBtn = document.getElementById('leaderboardApplyDynamicBtn');
    if (closeBtn) closeBtn.onclick = closeLeaderboardApplyModal;
    if (cancelBtn) cancelBtn.onclick = closeLeaderboardApplyModal;
    if (modal) {
        modal.onclick = function (e) {
            if (e.target === modal) closeLeaderboardApplyModal();
        };
    }
    if (tplBtn) {
        tplBtn.onclick = function () {
            var cb = _leaderboardApplyCallback;
            closeLeaderboardApplyModal();
            if (cb) cb({ useDynamicApplied: false, enableDynamicMode: false });
        };
    }
    if (dynBtn) {
        dynBtn.onclick = function () {
            if (dynBtn.disabled) return;
            var cb = _leaderboardApplyCallback;
            closeLeaderboardApplyModal();
            if (cb) cb({ useDynamicApplied: true, enableDynamicMode: true });
        };
    }
}

function confirmLeaderboardApplyMode(itemIndex, onChoose) {
    initLeaderboardApplyModalHandlers();
    var idx = itemIndex != null && itemIndex !== '' ? parseInt(itemIndex, 10) : NaN;
    var item = Number.isFinite(idx) && State.leaderboardItems ? State.leaderboardItems[idx] : null;
    var dyn = item ? resolveLeaderboardItemDynamicMode(item) : null;
    if (!leaderboardItemDynamicVisible(item)) {
        if (typeof onChoose === 'function') onChoose({ useDynamicApplied: false, enableDynamicMode: false });
        return;
    }
    var hasApplied = !!(dyn && dyn.snapshot && dyn.snapshot.applied);
    var modal = document.getElementById('leaderboardApplyModal');
    var textEl = document.getElementById('leaderboardApplyModalText');
    var tplBtn = document.getElementById('leaderboardApplyTemplateBtn');
    var dynBtn = document.getElementById('leaderboardApplyDynamicBtn');
    var symLabel = item && item.symbol ? String(item.symbol) : 'Bu bot';
    if (textEl) {
        textEl.textContent = symLabel + ' dinamik modda. Başlangıç değerlerini mi referans almak istiyorsunuz, yoksa son güncel dinamik değerleri mi? Seçiminiz bot oluşturma formuna aktarılır.';
    }
    if (tplBtn) {
        tplBtn.textContent = 'Başlangıç değerleri';
        tplBtn.disabled = false;
    }
    if (dynBtn) {
        dynBtn.textContent = 'Son güncel dinamik değerler';
        dynBtn.disabled = !hasApplied;
        dynBtn.title = hasApplied ? '' : 'Bu bot için henüz dinamik tur snapshot\'ı yok';
    }
    _leaderboardApplyCallback = function (opts) {
        if (typeof onChoose === 'function') {
            onChoose({
                useDynamicApplied: !!(opts && opts.useDynamicApplied && hasApplied),
                enableDynamicMode: !!(opts && opts.enableDynamicMode)
            });
        }
    };
    if (modal) {
        modal.style.display = 'flex';
        document.body.style.overflow = 'hidden';
    }
}

function initParametrelerModalHandlers() {
    if (initParametrelerModalHandlers._done) return;
    initParametrelerModalHandlers._done = true;
    var modal = document.getElementById('parametrelerModal');
    var closeBtn = document.getElementById('parametrelerModalClose');
    var kapatBtn = document.getElementById('parametrelerModalKapat');
    if (closeBtn) closeBtn.onclick = closeParametrelerModal;
    if (kapatBtn) kapatBtn.onclick = closeParametrelerModal;
    if (modal) {
        modal.onclick = function (e) {
            if (e.target === modal) closeParametrelerModal();
        };
    }
}

async function openLeaderboardParamsModal(rank, structureName, params, createdAtIso, referencePrice, itemIndex, opts) {
    initParametrelerModalHandlers();
    bindLeaderboardParamTabHandlers();
    opts = opts || {};
    var modal = document.getElementById('parametrelerModal');
    var bodyEl = document.getElementById('configGrid');
    if (!modal || !bodyEl) return;
    bodyEl.innerHTML = '<p class="param-hint">Yükleniyor…</p>';
    var tabsHost = document.getElementById('paramTabsHost');
    if (tabsHost) tabsHost.innerHTML = '';
    modal.style.display = 'flex';
    document.body.style.overflow = 'hidden';

    var item = await resolveLeaderboardItemForModal(itemIndex);
    var resolved = stripLeaderboardBudgetFromParams(item
        ? normalizeLeaderboardParamsToFormConfig(item.params || {})
        : normalizeLeaderboardParamsToFormConfig(resolveLeaderboardItemParams(params, itemIndex)));
    if (item && item.symbol && !resolved.symbol) resolved.symbol = item.symbol;
    var symbol = (item && item.symbol) || resolved.symbol || (params && params.symbol) || '';
    var ref = referencePrice != null && !isNaN(referencePrice) ? referencePrice
        : (item && item.reference_price != null && !isNaN(Number(item.reference_price)) ? Number(item.reference_price) : null);
    if (ref == null && resolved.reference_price != null && !isNaN(Number(resolved.reference_price))) {
        ref = Number(resolved.reference_price);
    }

    _leaderboardParamGenelHtml = renderBotParamsConfig(resolved, symbol, ref, true);
    _leaderboardParamDynHtml = '';
    if (window.DynModeParamsView && item && leaderboardItemDynamicVisible(item)) {
        _leaderboardParamDynHtml = window.DynModeParamsView.renderBotDetailDynamicTab(
            resolveLeaderboardItemDynamicMode(item),
            {},
            symbol,
            resolved,
            { showBalances: false, hideBudget: true, referencePrice: ref }
        );
    }
    _leaderboardParamActiveTab = 'genel';
    refreshLeaderboardParamModalView();
}

window.openLeaderboardParamsModal = openLeaderboardParamsModal;
window.closeParametrelerModal = closeParametrelerModal;

function buildGlobalLeaderboardStructureSignature(items) {
    if (!Array.isArray(items)) return '';
    return items.map(function (item) {
        var params = normalizeLeaderboardParamsToFormConfig(item.params || {});
        return leaderboardItemKey(item) + ':' + JSON.stringify(params);
    }).slice().sort().join('|');
}

function buildGlobalLeaderboardItemHtml(item, index) {
    var structureId = (item.structure_id || 'trailing_dca').toLowerCase();
    var structure = typeof BOT_STRUCTURES !== 'undefined' ? BOT_STRUCTURES.find(function (s) { return s.id === structureId; }) : null;
    var structureName = structure ? structure.name : structureId;
    var pnlMeta = formatLeaderboardTotalPnl(item);
    var params = stripLeaderboardBudgetFromParams(normalizeLeaderboardParamsToFormConfig(item.params || {}));
    if (item.reference_price != null && params.reference_price == null) {
        params.reference_price = item.reference_price;
    }
    var symbolRaw = item.symbol || params.symbol || '';
    var symbolStr = (typeof symbolRaw === 'string' ? symbolRaw : '').trim() || '—';
    var symbolLogoHtml = buildLeaderboardSymbolLogoHtml(symbolStr);
    var dyn = resolveLeaderboardItemDynamicMode(item);
    var dynVisible = window.DynModeParamsView && window.DynModeParamsView.isLeaderboardDynamicBadgeVisible(dyn);
    var dynTip = window.DynModeParamsView ? window.DynModeParamsView.dynamicModeLogoTipShort(dyn, params) : 'Dinamik mod aktif';
    if (window.DynModeParamsView && dynVisible) {
        symbolLogoHtml = window.DynModeParamsView.wrapLogoForDynamicMode(symbolLogoHtml, true, dynTip);
    }
    var dynBadgeHtml = (window.DynModeParamsView && dynVisible)
        ? window.DynModeParamsView.renderDynamicBadgeHtml(
            window.DynModeParamsView.dynamicModeHoverTitle(dyn, params)
        )
        : '';
    var runningSinceNorm = normalizeRunningSinceIso(item.running_since_iso || '');
    var runningStr = formatLeaderboardRunningDuration(runningSinceNorm);
    var paramsJsonAttr = JSON.stringify(params).replace(/"/g, '&quot;');
    var refPrice = item.reference_price != null ? String(item.reference_price) : '';
    var structureNameAttr = (typeof escapeHtml === 'function' ? escapeHtml(structureName) : structureName).replace(/"/g, '&quot;');
    var itemKey = leaderboardItemKey(item);
    var itemKeyAttr = (typeof escapeHtml === 'function' ? escapeHtml(itemKey) : itemKey).replace(/"/g, '&quot;');
    var cyclesLabel = formatLeaderboardCyclesLabel(item);
    var applyBtnHtml = structure ? '<button type="button" class="btn btn-sm global-leaderboard-apply-btn" data-structure-id="' + (typeof escapeHtml === 'function' ? escapeHtml(structureId) : structureId) + '" data-params="' + paramsJsonAttr + '">Uygula</button>' : '';
    var viewParamsBtnHtml = '<button type="button" class="btn btn-sm global-leaderboard-view-params-btn" data-params="' + paramsJsonAttr + '" data-structure-name="' + structureNameAttr + '" data-rank="' + (index + 1) + '" data-reference-price="' + refPrice.replace(/"/g, '&quot;') + '">Parametreleri görüntüle</button>';
    return '<div class="global-leaderboard-item" data-item-key="' + itemKeyAttr + '" data-item-index="' + index + '" data-running-since="' + runningSinceNorm.replace(/"/g, '&quot;') + '">' +
        '<div class="global-leaderboard-item-main">' +
        '<div class="global-leaderboard-item-head">' +
        '<div class="global-leaderboard-symbol-wrap">' + symbolLogoHtml + '<span class="global-leaderboard-symbol-name">' + (typeof escapeHtml === 'function' ? escapeHtml(symbolStr) : symbolStr) + '</span></div>' +
        '<span class="global-leaderboard-rank-name">' + (index + 1) + '. ' + (typeof escapeHtml === 'function' ? escapeHtml(structureName) : structureName) + '</span>' +
        '<span class="global-leaderboard-pct" style="color:' + pnlMeta.color + '">' + pnlMeta.text + '</span>' +
        '</div>' +
        '<div class="global-leaderboard-item-meta">' +
        '<div class="global-leaderboard-item-meta-left">' +
        '<span class="global-leaderboard-item-duration">Çalışma süresi: ' + runningStr + '</span>' +
        '<span class="global-leaderboard-item-sep" aria-hidden="true">·</span>' +
        '<span class="global-leaderboard-item-cycles">' + cyclesLabel + '</span>' +
        dynBadgeHtml +
        '</div>' +
        '</div>' +
        '</div>' +
        '<div class="global-leaderboard-item-actions">' + viewParamsBtnHtml + applyBtnHtml + '</div>' +
        '</div>';
}

function parseLeaderboardParamsFromAttr(raw) {
    if (!raw) return null;
    try {
        return JSON.parse(raw);
    } catch (e1) {
        try {
            return JSON.parse(raw.replace(/&quot;/g, '"').replace(/&amp;/g, '&').replace(/&lt;/g, '<'));
        } catch (e2) {
            return null;
        }
    }
}

function bindGlobalLeaderboardItemActions(listEl) {
    if (!listEl || listEl.dataset.leaderboardActionsBound === '1') return;
    listEl.dataset.leaderboardActionsBound = '1';
    listEl.addEventListener('click', function (e) {
        var applyBtn = e.target.closest('.global-leaderboard-apply-btn');
        if (applyBtn && listEl.contains(applyBtn)) {
            e.preventDefault();
            var sid = applyBtn.getAttribute('data-structure-id');
            var paramsJson = applyBtn.getAttribute('data-params');
            if (!sid) return;
            var itemRow = applyBtn.closest('.global-leaderboard-item');
            var itemIdx = itemRow ? itemRow.getAttribute('data-item-index') : null;
            var params = null;
            if (itemIdx != null && itemIdx !== '' && State.leaderboardItems) {
                var lbIdx = parseInt(itemIdx, 10);
                if (Number.isFinite(lbIdx) && State.leaderboardItems[lbIdx]) {
                    params = stripLeaderboardBudgetFromParams(
                        normalizeLeaderboardParamsToFormConfig(State.leaderboardItems[lbIdx].params || {})
                    );
                }
            }
            if (!params && paramsJson) params = parseLeaderboardParamsFromAttr(paramsJson);
            if (!params) return;
            var structure = typeof BOT_STRUCTURES !== 'undefined' ? BOT_STRUCTURES.find(function (s) { return s.id === sid; }) : null;
            if (structure && typeof applyLeaderboardParams === 'function') {
                confirmLeaderboardApplyMode(itemIdx, function (applyOpts) {
                    applyLeaderboardParams(structure, params, itemIdx, applyOpts);
                });
            }
            return;
        }
        var viewBtn = e.target.closest('.global-leaderboard-view-params-btn');
        if (!viewBtn || !listEl.contains(viewBtn)) return;
        e.preventDefault();
        var paramsJson = viewBtn.getAttribute('data-params');
        var structureName = viewBtn.getAttribute('data-structure-name') || 'Bot';
        var rank = viewBtn.getAttribute('data-rank') || '';
        var refRaw = viewBtn.getAttribute('data-reference-price');
        var refPrice = refRaw !== '' && refRaw != null ? Number(refRaw) : null;
        var itemRow = viewBtn.closest('.global-leaderboard-item');
        var itemIdx = itemRow ? itemRow.getAttribute('data-item-index') : null;
        var params = null;
        if (itemIdx != null && itemIdx !== '' && State.leaderboardItems) {
            var viewIdx = parseInt(itemIdx, 10);
            if (Number.isFinite(viewIdx) && State.leaderboardItems[viewIdx]) {
                params = stripLeaderboardBudgetFromParams(
                    normalizeLeaderboardParamsToFormConfig(State.leaderboardItems[viewIdx].params || {})
                );
            }
        }
        if (!params && paramsJson) params = parseLeaderboardParamsFromAttr(paramsJson);
        if (!params) return;
        params = resolveLeaderboardItemParams(params, itemIdx);
        var lbItem = (itemIdx != null && itemIdx !== '' && State.leaderboardItems)
            ? State.leaderboardItems[parseInt(itemIdx, 10)]
            : null;
        if (refPrice == null && lbItem && lbItem.reference_price != null) refPrice = Number(lbItem.reference_price);
        if (refPrice == null && params.reference_price != null) refPrice = Number(params.reference_price);
        if (typeof openLeaderboardParamsModal === 'function') {
            openLeaderboardParamsModal(rank, structureName, params, null, refPrice, itemIdx, {});
        }
    });
}

function _globalLeaderboardListEls() {
    return ['globalLeaderboardList', 'globalLeaderboardListBots']
        .map(function (id) { return document.getElementById(id); })
        .filter(Boolean);
}

function _globalLeaderboardPanelEls() {
    return ['globalLeaderboardPanel', 'globalLeaderboardPanelBots']
        .map(function (id) { return document.getElementById(id); })
        .filter(Boolean);
}

function patchGlobalLeaderboardMetrics(items) {
    var lists = _globalLeaderboardListEls();
    if (!lists.length || !Array.isArray(items) || !items.length) return;
    State.leaderboardItems = items;
    lists.forEach(function (listEl) {
    items.forEach(function (item, index) {
        var itemKey = leaderboardItemKey(item);
        var row = listEl.querySelector('.global-leaderboard-item[data-item-key="' + itemKey + '"]');
        if (!row) return;
        var structureId = (item.structure_id || 'trailing_dca').toLowerCase();
        var structure = typeof BOT_STRUCTURES !== 'undefined' ? BOT_STRUCTURES.find(function (s) { return s.id === structureId; }) : null;
        var structureName = structure ? structure.name : structureId;
        var rankNameEl = row.querySelector('.global-leaderboard-rank-name');
        var rankText = (index + 1) + '. ' + structureName;
        if (rankNameEl && rankNameEl.textContent !== rankText) rankNameEl.textContent = rankText;
        row.setAttribute('data-item-index', String(index));
        var pnlEl = row.querySelector('.global-leaderboard-pct');
        var durEl = row.querySelector('.global-leaderboard-item-duration');
        var cyclesEl = row.querySelector('.global-leaderboard-item-cycles');
        var pnlMeta = formatLeaderboardTotalPnl(item);
        if (pnlEl) {
            if (pnlEl.textContent !== pnlMeta.text) pnlEl.textContent = pnlMeta.text;
            if (pnlEl.style.color !== pnlMeta.color) pnlEl.style.color = pnlMeta.color;
        }
        if (durEl) {
            var isoNorm = normalizeRunningSinceIso(item.running_since_iso || row.getAttribute('data-running-since'));
            var durText = 'Çalışma süresi: ' + formatLeaderboardRunningDuration(isoNorm);
            if (durEl.textContent !== durText) durEl.textContent = durText;
        }
        if (cyclesEl) {
            var cyclesText = formatLeaderboardCyclesLabel(item);
            if (cyclesEl.textContent !== cyclesText) cyclesEl.textContent = cyclesText;
        }
        if (item.running_since_iso) row.setAttribute('data-running-since', normalizeRunningSinceIso(item.running_since_iso));
        var params = stripLeaderboardBudgetFromParams(normalizeLeaderboardParamsToFormConfig(item.params || {}));
        if (item.symbol && !params.symbol) params.symbol = item.symbol;
        var paramsJson = JSON.stringify(params);
        row.querySelectorAll('.global-leaderboard-apply-btn, .global-leaderboard-view-params-btn').forEach(function (btn) {
            btn.setAttribute('data-params', paramsJson);
        });
        patchLeaderboardRowDynamicUi(row, item);
    });
    });
}

function startGlobalLeaderboardPoll() {
    if (!window.intervalRegistry) return;
    window.intervalRegistry.stop('dashboard.leaderboard');
    window.intervalRegistry.stop('dashboard.leaderboard.duration');
    window.intervalRegistry.start('dashboard.leaderboard', function () {
        if (State.accountId && typeof loadGlobalLeaderboard === 'function') loadGlobalLeaderboard(true);
    }, 5000, 'dashboard');
    window.intervalRegistry.start('dashboard.leaderboard.duration', function () {
        if (State.leaderboardLastState !== 'items') return;
        _globalLeaderboardListEls().forEach(function (listEl) {
            listEl.querySelectorAll('.global-leaderboard-item').forEach(function (row) {
                var durEl = row.querySelector('.global-leaderboard-item-duration');
                var iso = normalizeRunningSinceIso(row.getAttribute('data-running-since'));
                if (durEl && iso) durEl.textContent = 'Çalışma süresi: ' + formatLeaderboardRunningDuration(iso);
            });
        });
    }, 1000, 'dashboard');
}

async function loadGlobalLeaderboard(patchOnly) {
    var listEls = _globalLeaderboardListEls();
    var primaryList = listEls[0];
    if (!primaryList || !window.apiClient) return;
    listEls.forEach(function (el) { bindGlobalLeaderboardItemActions(el); });
    _globalLeaderboardPanelEls().forEach(function (panel) { panel.style.display = 'block'; });
    var lastState = State.leaderboardLastState || 'idle';
    if (lastState !== 'empty' && lastState !== 'error' && lastState !== 'items') {
        listEls.forEach(function (el) { el.innerHTML = LEADERBOARD_LOADING_HTML; });
        State.leaderboardLastState = 'loading';
        scheduleLeaderboardLoadTimeout();
    }
    try {
        var res = await window.apiClient.get('/api/leaderboard/global/top?limit=5');
        clearLeaderboardLoadTimeout();
        var items = (res && Array.isArray(res.items)) ? res.items
            : (res && res.data && Array.isArray(res.data.items)) ? res.data.items
            : [];
        items = filterLeaderboardItemsForDisplay(items);
        items = enrichLeaderboardItemsDynamicMode(items);
        if (!items.length) {
            setGlobalLeaderboardEmpty(
                State.leaderboardLastState === 'loading' ? LEADERBOARD_NO_PROFIT_HTML : LEADERBOARD_EMPTY_HTML,
                true
            );
            return;
        }
        items = stabilizeLeaderboardOrder(items);
        State.leaderboardItems = items;
        var orderSig = buildGlobalLeaderboardOrderSignature(items);
        var structureSig = buildGlobalLeaderboardStructureSignature(items);
        var metricsSig = buildGlobalLeaderboardMetricsSignature(items);
        var domCount = primaryList.querySelectorAll('.global-leaderboard-item').length;
        if (patchOnly && State.leaderboardLastState === 'items') {
            if (State.leaderboardOrderSig === orderSig && domCount === items.length) {
                patchGlobalLeaderboardMetrics(items);
                State.leaderboardMetricsSig = metricsSig;
                State.leaderboardStructureSig = structureSig;
                startGlobalLeaderboardPoll();
                return;
            }
        }
        var orderUnchanged = State.leaderboardOrderSig === orderSig
            && domCount === items.length
            && State.leaderboardLastState === 'items';
        if (orderUnchanged) {
            patchGlobalLeaderboardMetrics(items);
            State.leaderboardMetricsSig = metricsSig;
            State.leaderboardStructureSig = structureSig;
            startGlobalLeaderboardPoll();
            return;
        }
        var html = '';
        items.forEach(function (item, index) {
            html += buildGlobalLeaderboardItemHtml(item, index);
        });
        State.leaderboardLastState = 'items';
        State.leaderboardOrderSig = orderSig;
        State.leaderboardStructureSig = structureSig;
        State.leaderboardMetricsSig = metricsSig;
        listEls.forEach(function (el) {
            el.innerHTML = html;
            bindGlobalLeaderboardItemActions(el);
            hydrateLeaderboardListLogos(el);
        });
        startGlobalLeaderboardPoll();
    } catch (e) {
        clearLeaderboardLoadTimeout();
        if (window.errorReporter) window.errorReporter.report(e, { tab: 'dashboard', action: 'loadGlobalLeaderboard' });
        setGlobalLeaderboardEmpty(LEADERBOARD_NO_PROFIT_HTML, true);
    }
}
window.loadGlobalLeaderboard = loadGlobalLeaderboard;
initLeaderboardApplyModalHandlers();
window.resolveLeaderboardItemDynamicMode = resolveLeaderboardItemDynamicMode;
