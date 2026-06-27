/**
 * Bot detail shell — shared layout cache + skeleton for bot.html / bot_multi.html.
 * Structure renders instantly; API patches data in place.
 */
(function (global) {
    'use strict';

    var CACHE_V3 = 'bot_detail_shell_v3_';
    var CACHE_V2 = 'bot_detail_ui_v2_';
    var CACHE_V1 = 'bot_detail_ui_v1_';
    var MAX_AGE_MS = 604800000;

    function readBotIdFromUrl() {
        try {
            var q = new URLSearchParams(global.location.search);
            return q.get('bot_id') || q.get('id') || '';
        } catch (e) {
            return '';
        }
    }

    function readCache(botId) {
        if (!botId) return null;
        var keys = [CACHE_V3, CACHE_V2, CACHE_V1];
        for (var i = 0; i < keys.length; i++) {
            try {
                var raw = global.sessionStorage.getItem(keys[i] + botId)
                    || global.localStorage.getItem(keys[i] + botId);
                if (!raw) continue;
                var o = JSON.parse(raw);
                if (!o || !o.ts) continue;
                if (Date.now() - o.ts > MAX_AGE_MS && i === 0) continue;
                return o;
            } catch (e2) { /* next key */ }
        }
        return null;
    }

    function writeCache(botId, payload) {
        if (!botId || !payload) return;
        try {
            payload.ts = Date.now();
            payload.shellVersion = 3;
            var raw = JSON.stringify(payload);
            global.sessionStorage.setItem(CACHE_V3 + botId, raw);
            global.localStorage.setItem(CACHE_V3 + botId, raw);
            global.sessionStorage.setItem(CACHE_V2 + botId, raw);
            global.localStorage.setItem(CACHE_V2 + botId, raw);
        } catch (e) { /* quota */ }
    }

    function clearCache(botId) {
        if (!botId) return;
        [CACHE_V3, CACHE_V2, CACHE_V1].forEach(function (prefix) {
            try {
                global.sessionStorage.removeItem(prefix + botId);
                global.localStorage.removeItem(prefix + botId);
            } catch (e) { /* ignore */ }
        });
    }

    function collectElements() {
        return {
            statePanel: document.getElementById('statePanel'),
            stateGrid: document.getElementById('stateGrid'),
            stateHeroTitle: document.getElementById('stateHeroTitle'),
            stateHeroMeta: document.getElementById('stateHeroMeta'),
            botTopStrip: document.getElementById('botTopStrip'),
            botTypeHeader: document.getElementById('botTypeHeader'),
            botTypeHeaderName: document.getElementById('botTypeHeaderName'),
            botSymbolEl: document.getElementById('botSymbolEl'),
            botPriceEl: document.getElementById('botPriceEl'),
            bot24hEl: document.getElementById('bot24hEl'),
            statusBadge: document.getElementById('statusBadge'),
            gridPointsPanel: document.getElementById('gridPointsPanel'),
            profitPointsPanel: document.getElementById('profitPointsPanel'),
            tradesPanel: document.getElementById('tradesPanel'),
            perfPanel: document.getElementById('perfPanel'),
            engineLogPanel: document.getElementById('engineLogPanel'),
            gridSellBody: document.getElementById('gridSellBody'),
            gridBuyBody: document.getElementById('gridBuyBody'),
            profitPointsBody: document.getElementById('profitPointsBody'),
            perfMetrics: document.getElementById('perfMetrics'),
            cycleTradesList: document.getElementById('cycleTradesList'),
            cycleTurBtns: document.getElementById('cycleTradesTurButtons'),
            cycleReport: document.getElementById('cycleReport'),
            engineLogList: document.getElementById('engineLogList'),
            gridRef: document.getElementById('gridPointsRefPrice'),
            loadingEl: document.getElementById('loadingEl')
        };
    }

    function markShellPanels(el) {
        ['gridPointsPanel', 'profitPointsPanel', 'tradesPanel', 'perfPanel', 'engineLogPanel'].forEach(function (k) {
            if (el[k]) el[k].classList.add('bot-detail-shell-panel');
        });
    }

    function skeletonGridRows(side, count) {
        var n = count || 3;
        var rows = '';
        for (var i = 0; i < n; i++) {
            rows += '<tr class="bot-detail-skel-row"><td><span class="bot-detail-skel"></span></td>'
                + '<td><span class="bot-detail-skel bot-detail-skel--wide"></span></td>'
                + '<td><span class="bot-detail-skel"></span></td>'
                + '<td><span class="bot-detail-skel"></span></td>'
                + '<td><span class="bot-detail-skel"></span></td>'
                + (side === 'sell' ? '<td><span class="bot-detail-skel"></span></td>' : '<td><span class="bot-detail-skel"></span></td>')
                + '</tr>';
        }
        return rows;
    }

    function stateSkeletonHtml() {
        var items = '';
        for (var i = 0; i < 6; i++) {
            items += '<div class="state-hero-item bot-detail-skel-card">'
                + '<div class="bot-detail-skel bot-detail-skel--block"></div>'
                + '<div class="bot-detail-skel bot-detail-skel--block" style="margin-top:0.35rem;width:60%;"></div>'
                + '</div>';
        }
        return items;
    }

    function perfSkeletonHtml() {
        var cards = '';
        for (var i = 0; i < 4; i++) {
            cards += '<div class="perf-metric-card"><div class="bot-detail-skel bot-detail-skel--block" style="height:0.65rem;width:55%;"></div>'
                + '<div class="bot-detail-skel bot-detail-skel--block" style="height:1.1rem;width:70%;margin-top:0.5rem;"></div></div>';
        }
        return cards;
    }

    function tradesPlaceholder(msg) {
        return '<div class="muted" style="padding:1rem;text-align:center;">' + (msg || 'Güncelleniyor…') + '</div>';
    }

    function setBootRefreshing(on) {
        document.body.classList.toggle('bot-detail-refreshing', !!on);
    }

    function finishShellBoot(refreshing) {
        document.body.classList.add('bot-detail-shell-active');
        var el = collectElements();
        if (el.loadingEl) el.loadingEl.style.display = 'none';
        setBootRefreshing(!!refreshing);
    }

    function ensureSkeletonShell() {
        var el = collectElements();
        markShellPanels(el);
        if (el.statePanel) {
            el.statePanel.style.display = 'block';
            if (el.stateHeroTitle && (!el.stateHeroTitle.textContent || el.stateHeroTitle.textContent === 'Durum')) {
                el.stateHeroTitle.textContent = 'Durum';
            }
            if (el.stateGrid && !el.stateGrid.querySelector('.state-hero-item')) {
                el.stateGrid.innerHTML = stateSkeletonHtml();
            }
        }
        if (el.botTopStrip) el.botTopStrip.style.display = '';
        if (el.botTypeHeader) el.botTypeHeader.style.display = 'block';
        if (el.gridPointsPanel) el.gridPointsPanel.style.display = 'block';
        if (el.profitPointsPanel) el.profitPointsPanel.style.display = 'block';
        if (el.tradesPanel) el.tradesPanel.style.display = 'block';
        if (el.perfPanel) el.perfPanel.style.display = 'block';
        if (el.gridSellBody && !el.gridSellBody.rows.length) {
            el.gridSellBody.innerHTML = skeletonGridRows('sell', 3);
        }
        if (el.gridBuyBody && !el.gridBuyBody.rows.length) {
            el.gridBuyBody.innerHTML = skeletonGridRows('buy', 3);
        }
        if (el.profitPointsBody && !el.profitPointsBody.rows.length) {
            el.profitPointsBody.innerHTML = skeletonGridRows('sell', 2);
        }
        if (el.perfMetrics && !el.perfMetrics.children.length) {
            el.perfMetrics.innerHTML = perfSkeletonHtml();
        }
        if (el.cycleTradesList && !el.cycleTradesList.querySelector('.cycle-trade-row')) {
            el.cycleTradesList.innerHTML = tradesPlaceholder('Güncelleniyor…');
        }
        if (el.engineLogList && !el.engineLogList.querySelector('table.engine-log-table')) {
            el.engineLogList.innerHTML = '<div class="muted engine-log-loading" style="padding:0.75rem;">Güncelleniyor…</div>';
        }
        finishShellBoot(true);
    }

    function applyStatusBadgeHtml(badgeEl, html) {
        if (!badgeEl || !html) return;
        try {
            var wrap = document.createElement('div');
            wrap.innerHTML = html;
            var fresh = wrap.firstElementChild;
            if (fresh) badgeEl.replaceWith(fresh);
        } catch (e) {
            /* keep existing */
        }
    }

    function applyPanelsFromSnapshot(o) {
        var el = collectElements();
        markShellPanels(el);
        if (el.gridPointsPanel && o.gridPanelDisplay) el.gridPointsPanel.style.display = o.gridPanelDisplay;
        if (el.profitPointsPanel && o.profitPanelDisplay) el.profitPointsPanel.style.display = o.profitPanelDisplay;
        if (el.tradesPanel && o.tradesPanelDisplay) el.tradesPanel.style.display = o.tradesPanelDisplay;
        if (el.perfPanel && o.perfPanelDisplay) el.perfPanel.style.display = o.perfPanelDisplay;
        if (el.engineLogPanel && o.engineLogPanelDisplay) el.engineLogPanel.style.display = o.engineLogPanelDisplay;
        if (el.gridSellBody && o.gridSellHtml != null) el.gridSellBody.innerHTML = o.gridSellHtml;
        if (el.gridBuyBody && o.gridBuyHtml != null) el.gridBuyBody.innerHTML = o.gridBuyHtml;
        if (el.profitPointsBody && o.profitHtml != null) el.profitPointsBody.innerHTML = o.profitHtml;
        if (el.perfMetrics && o.perfMetricsHtml) el.perfMetrics.innerHTML = o.perfMetricsHtml;
        if (el.cycleReport) {
            if (o.cycleReportHtml) {
                el.cycleReport.innerHTML = o.cycleReportHtml;
                el.cycleReport.style.display = o.cycleReportDisplay || 'block';
            } else {
                el.cycleReport.style.display = 'none';
            }
        }
        if (el.cycleTurBtns) {
            el.cycleTurBtns.innerHTML = o.cycleTurBtnsHtml || '';
        }
        if (el.cycleTradesList) {
            if (o.cycleTradesHtml && o.cycleTradesHtml.indexOf('cycle-trade-row') >= 0) {
                el.cycleTradesList.innerHTML = o.cycleTradesHtml;
            } else if (!el.cycleTradesList.querySelector('.cycle-trade-row')) {
                el.cycleTradesList.innerHTML = tradesPlaceholder('Güncelleniyor…');
            }
        }
        if (el.engineLogList && o.engineLogHtml) el.engineLogList.innerHTML = o.engineLogHtml;
        if (el.gridRef && o.gridRefText) el.gridRef.textContent = o.gridRefText;
        return !!o.panelsReady;
    }

    function applySnapshotSync(o, opts) {
        if (!o) return false;
        opts = opts || {};
        var el = collectElements();
        var urlSym = (opts.urlSymbol || '').trim().toUpperCase();

        if (el.statePanel && o.statePanelDisplay) el.statePanel.style.display = o.statePanelDisplay;
        if (el.stateHeroTitle && o.stateHeroTitle) el.stateHeroTitle.textContent = o.stateHeroTitle;
        if (el.stateHeroMeta && o.stateHeroMetaHtml) el.stateHeroMeta.innerHTML = o.stateHeroMetaHtml;
        if (el.stateGrid && o.stateGridHtml) el.stateGrid.innerHTML = o.stateGridHtml;
        if (el.botTopStrip && o.botTopStripDisplay) {
            el.botTopStrip.style.display = o.botTopStripDisplay === 'none' ? 'none' : o.botTopStripDisplay;
        }
        if (el.botTypeHeader && o.botTypeHeaderDisplay) el.botTypeHeader.style.display = o.botTypeHeaderDisplay;
        if (el.botTypeHeaderName && o.botTypeHeaderName) el.botTypeHeaderName.textContent = o.botTypeHeaderName;

        var symShow = urlSym || (o.botSymbol ? String(o.botSymbol).toUpperCase() : '');
        if (el.botSymbolEl && symShow && symShow !== '—' && symShow !== '?') {
            el.botSymbolEl.textContent = symShow;
        }
        if (el.botPriceEl && o.botPrice) el.botPriceEl.textContent = o.botPrice;
        if (el.bot24hEl && o.bot24h) {
            el.bot24hEl.textContent = o.bot24h;
            if (o.bot24hClass) el.bot24hEl.className = o.bot24hClass;
        }
        if (el.statusBadge && o.statusBadgeHtml) applyStatusBadgeHtml(el.statusBadge, o.statusBadgeHtml);

        var panelsOk = applyPanelsFromSnapshot(o);
        finishShellBoot(false);
        return panelsOk || !!(o.stateGridHtml && o.stateGridHtml.indexOf('state-hero-item') !== -1);
    }

    function syncBootFromUrl(opts) {
        opts = opts || {};
        var botId = readBotIdFromUrl();
        if (!botId) return null;
        var urlSymbol = '';
        try {
            urlSymbol = (new URLSearchParams(global.location.search).get('symbol') || '').trim();
        } catch (e) { /* ignore */ }
        var cached = readCache(botId);
        if (cached) {
            applySnapshotSync(cached, { urlSymbol: urlSymbol });
            return cached;
        }
        ensureSkeletonShell();
        return null;
    }

    global.BotDetailShell = {
        CACHE_V3: CACHE_V3,
        CACHE_V2: CACHE_V2,
        MAX_AGE_MS: MAX_AGE_MS,
        readBotIdFromUrl: readBotIdFromUrl,
        readCache: readCache,
        writeCache: writeCache,
        clearCache: clearCache,
        collectElements: collectElements,
        ensureSkeletonShell: ensureSkeletonShell,
        applySnapshotSync: applySnapshotSync,
        applyPanelsFromSnapshot: applyPanelsFromSnapshot,
        syncBootFromUrl: syncBootFromUrl,
        setBootRefreshing: setBootRefreshing,
        finishShellBoot: finishShellBoot,
        tradesPlaceholder: tradesPlaceholder,
        skeletonGridRows: skeletonGridRows,
        stateSkeletonHtml: stateSkeletonHtml,
        perfSkeletonHtml: perfSkeletonHtml
    };
})(window);
