/**
 * Performance chart rebuild — DOM-driven, LightweightCharts, zero-fail.
 * Data from #perfReportBakiyeDegisim and #perfReportPariteDegisim (trailing % only).
 */
(function () {
    'use strict';

    if (typeof window.LightweightCharts === 'undefined') {
        console.error('[PerfChartRebuild] FATAL: window.LightweightCharts not found. Add script: https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js');
        return;
    }

    var RANGES = {
        LIVE: 3600,
        '1H': 3600,
        '4H': 14400,
        '1D': 86400,
        '1W': 604800
    };
    var DEFAULT_RANGE = '4H';
    var SAMPLE_INTERVAL_MS = 2000;
    var MINI_UPDATE_MS = 5000;

    function parseTrailingPercent(text) {
        if (text == null || typeof text !== 'string') return null;
        var s = text.trim();
        var m = s.match(/([+-]?\d+[.,]\d+)\s*%\s*$/);
        if (!m) return null;
        var val = m[1].replace(',', '.');
        var n = parseFloat(val);
        return isNaN(n) ? null : n;
    }

    var inited = false;
    var wrapEl, modalEl, wrapMount, modalMount;
    var miniChart, modalChart;
    var state = {
        startTsSec: 0,
        rangeSec: RANGES[DEFAULT_RANGE] || RANGES['4H'],
        rangeKey: DEFAULT_RANGE,
        points: [],
        initialBot: null,
        initialParite: null
    };
    var sampleTimer = null;
    var miniUpdateTimer = null;
    var debugEl = null;

    function getSpans() {
        return {
            bot: document.getElementById('perfReportBakiyeDegisim'),
            parite: document.getElementById('perfReportPariteDegisim')
        };
    }

    function resetBaseline() {
        var spans = getSpans();
        var botPct = parseTrailingPercent(spans.bot ? spans.bot.textContent : '');
        var paritePct = parseTrailingPercent(spans.parite ? spans.parite.textContent : '');
        state.initialBot = botPct != null ? botPct : 0;
        state.initialParite = paritePct != null ? paritePct : 0;
        state.startTsSec = Math.floor(Date.now() / 1000);
        state.points = [];
    }

    function pruneBuffer(nowSec) {
        var from = nowSec - state.rangeSec;
        state.points = state.points.filter(function (p) { return p.ts >= from; });
    }

    function sampleFromDom() {
        var spans = getSpans();
        var botPct = parseTrailingPercent(spans.bot ? spans.bot.textContent : '');
        var paritePct = parseTrailingPercent(spans.parite ? spans.parite.textContent : '');
        if (state.initialBot == null) state.initialBot = botPct != null ? botPct : 0;
        if (state.initialParite == null) state.initialParite = paritePct != null ? paritePct : 0;
        var nowSec = Math.floor(Date.now() / 1000);
        var last = state.points.length ? state.points[state.points.length - 1] : null;
        state.points.push({
            ts: nowSec,
            bot: botPct != null ? botPct : (last ? last.bot : state.initialBot),
            parite: paritePct != null ? paritePct : (last ? last.parite : state.initialParite)
        });
        pruneBuffer(nowSec);
    }

    function buildSeriesData(nowSec, rangeSec) {
        var fromSec = nowSec - rangeSec;
        var toSec = nowSec;
        var initialBot = state.initialBot != null ? state.initialBot : 0;
        var initialParite = state.initialParite != null ? state.initialParite : 0;
        var lastBot = initialBot;
        var lastParite = initialParite;
        if (state.points.length) {
            var last = state.points[state.points.length - 1];
            lastBot = last.bot;
            lastParite = last.parite;
        }
        var latestBotDelta = lastBot - initialBot;
        var latestPariteDelta = lastParite - initialParite;

        var botPoints = [{ time: fromSec, value: 0 }];
        var paritePoints = [{ time: fromSec, value: 0 }];
        var seen = {};
        state.points.forEach(function (p) {
            if (p.ts < fromSec || p.ts > toSec) return;
            var t = p.ts;
            if (seen[t]) return;
            seen[t] = true;
            var bVal = (p.bot != null ? p.bot : lastBot) - initialBot;
            var parVal = (p.parite != null ? p.parite : lastParite) - initialParite;
            botPoints.push({ time: t, value: Math.round(bVal * 100) / 100 });
            paritePoints.push({ time: t, value: Math.round(parVal * 100) / 100 });
        });
        botPoints.push({ time: toSec, value: Math.round(latestBotDelta * 100) / 100 });
        paritePoints.push({ time: toSec, value: Math.round(latestPariteDelta * 100) / 100 });

        return { bot: botPoints, parite: paritePoints, latestBot: latestBotDelta, latestParite: latestPariteDelta };
    }

    function applyColors(botBetter, botS, pariteS) {
        var botColor = botBetter ? '#0ECB81' : '#F6465D';
        var pariteColor = botBetter ? '#F6465D' : '#0ECB81';
        if (botS) botS.applyOptions({ color: botColor });
        if (pariteS) pariteS.applyOptions({ color: pariteColor });
    }

    function updateChart(chart, botS, pariteS, isModal) {
        if (!chart || !botS || !pariteS) return;
        var nowSec = Math.floor(Date.now() / 1000);
        var rangeSec = state.rangeSec;
        var data = buildSeriesData(nowSec, rangeSec);
        botS.setData(data.bot);
        pariteS.setData(data.parite);
        var botBetter = data.latestBot >= data.latestParite;
        applyColors(botBetter, botS, pariteS);
        var fromSec = nowSec - rangeSec;
        var toSec = nowSec;
        requestAnimationFrame(function () {
            try {
                chart.timeScale().setVisibleRange({ from: fromSec, to: toSec });
            } catch (e) {}
        });
        if (isModal && debugEl) {
            debugEl.textContent = 'range=' + state.rangeKey + ' now=' + nowSec + ' from=' + fromSec + ' to=' + toSec +
                ' points=' + state.points.length + ' botΔ=' + (data.latestBot != null ? data.latestBot.toFixed(2) : '—') + '% pariteΔ=' + (data.latestParite != null ? data.latestParite.toFixed(2) : '—') + '%';
        }
    }

    function createChartOptions(height) {
        return {
            layout: {
                background: { type: 'solid', color: '#1e2329' },
                textColor: 'rgba(255,255,255,0.6)'
            },
            grid: {
                vertLines: { color: 'rgba(255,255,255,0.06)' },
                horzLines: { color: 'rgba(255,255,255,0.06)' }
            },
            rightPriceScale: {
                borderVisible: false,
                scaleMargins: { top: 0.1, bottom: 0.1 }
            },
            timeScale: {
                timeVisible: true,
                secondsVisible: false
            },
            crosshair: { mode: 1 },
            handleScroll: { vertTouchDrag: false }
        };
    }

    function createChart(mountEl, height) {
        var w = mountEl && mountEl.offsetWidth ? mountEl.offsetWidth : 0;
        var opts = createChartOptions(height);
        opts.width = w > 0 ? w : undefined;
        opts.height = height;
        var chart = window.LightweightCharts.createChart(mountEl, opts);
        var botColor = '#0ECB81';
        var pariteColor = '#F6465D';
        var s1 = chart.addLineSeries({
            color: botColor,
            lineWidth: 2,
            priceLineVisible: false,
            lastValueVisible: true
        });
        var s2 = chart.addLineSeries({
            color: pariteColor,
            lineWidth: 2,
            priceLineVisible: false,
            lastValueVisible: true
        });
        chart.priceScale('right').applyOptions({
            tickMarkFormatter: function (v) { return v.toFixed(2) + '%'; }
        });
        return { chart: chart, botSeries: s1, pariteSeries: s2 };
    }

    function buildMiniChart() {
        if (!wrapMount || miniChart) return;
        var rect = wrapMount.getBoundingClientRect();
        var h = Math.max(rect.height || 260, 260);
        miniChart = createChart(wrapMount, h);
        var nowSec = Math.floor(Date.now() / 1000);
        var fromSec = nowSec - state.rangeSec;
        var toSec = nowSec;
        var data = buildSeriesData(nowSec, state.rangeSec);
        miniChart.botSeries.setData(data.bot);
        miniChart.pariteSeries.setData(data.parite);
        applyColors(data.latestBot >= data.latestParite, miniChart.botSeries, miniChart.pariteSeries);
        requestAnimationFrame(function () {
            try {
                miniChart.chart.timeScale().setVisibleRange({ from: fromSec, to: toSec });
            } catch (e) {}
        });
        miniChart.chart.timeScale().fitContent();
    }

    function buildModalChart() {
        if (!modalMount || modalChart) return;
        var rect = modalMount.getBoundingClientRect();
        var h = Math.max(rect.height || 520, 520);
        modalChart = createChart(modalMount, h);
        var nowSec = Math.floor(Date.now() / 1000);
        var fromSec = nowSec - state.rangeSec;
        var toSec = nowSec;
        var data = buildSeriesData(nowSec, state.rangeSec);
        modalChart.botSeries.setData(data.bot);
        modalChart.pariteSeries.setData(data.parite);
        applyColors(data.latestBot >= data.latestParite, modalChart.botSeries, modalChart.pariteSeries);
        requestAnimationFrame(function () {
            try {
                modalChart.chart.timeScale().setVisibleRange({ from: fromSec, to: toSec });
            } catch (e) {}
        });
        modalChart.chart.timeScale().fitContent();
    }

    function startSampling() {
        if (sampleTimer) return;
        sampleFromDom();
        sampleTimer = setInterval(sampleFromDom, SAMPLE_INTERVAL_MS);
    }

    function stopSampling() {
        if (sampleTimer) {
            clearInterval(sampleTimer);
            sampleTimer = null;
        }
    }

    function openModal() {
        modalEl.classList.add('is-open');
        resetBaseline();
        startSampling();
        requestAnimationFrame(function () {
            requestAnimationFrame(function () {
                if (!modalChart && modalMount) {
                    buildModalChart();
                }
                if (modalChart) {
                    state.rangeSec = RANGES[state.rangeKey] || RANGES['4H'];
                    updateChart(modalChart.chart, modalChart.botSeries, modalChart.pariteSeries, true);
                }
            });
        });
    }

    function closeModal() {
        modalEl.classList.remove('is-open');
        stopSampling();
    }

    function setRange(key) {
        state.rangeKey = key;
        state.rangeSec = RANGES[key] != null ? RANGES[key] : RANGES['4H'];
        resetBaseline();
        sampleFromDom();
        if (modalChart) updateChart(modalChart.chart, modalChart.botSeries, modalChart.pariteSeries, true);
        if (miniChart) updateChart(miniChart.chart, miniChart.botSeries, miniChart.pariteSeries, false);
    }

    function init() {
        if (inited) return;
        wrapEl = document.getElementById('perfChartWrap');
        modalEl = document.getElementById('perfChartModalOverlay');
        if (!wrapEl || !modalEl) {
            console.error('[PerfChartRebuild] Missing required elements: perfChartWrap=' + !!wrapEl + ' perfChartModalOverlay=' + !!modalEl);
            return;
        }
        resetBaseline();
        var spans = getSpans();
        if (!spans.bot || !spans.parite) {
            state.points.push({
                ts: Math.floor(Date.now() / 1000),
                bot: 0,
                parite: 0
            });
        }

        wrapEl.innerHTML = '<div class="perf-chart-title">Parite % &amp; Bot bakiyesi % (başlangıçtan itibaren) <span class="perf-chart-open-hint">Grafiği aç</span></div>' +
            '<div id="perfChartWrapMount" style="width:100%; min-height:260px; height:260px;"></div>';
        wrapMount = document.getElementById('perfChartWrapMount');

        var modalContent = modalEl.querySelector && modalEl.querySelector('.perf-chart-modal');
        if (modalContent) {
            var head = modalContent.querySelector('.perf-chart-modal-head');
            var body = modalContent.querySelector('.perf-chart-modal-body');
            if (body) {
                body.innerHTML = '<div id="perfChartModalDebug" class="perf-chart-rebuild-debug" style="font-size:0.7rem; color:rgba(255,255,255,0.5); margin-bottom:0.5rem;"></div>' +
                    '<div id="perfChartModalMount" style="width:100%; height:520px;"></div>';
                modalMount = document.getElementById('perfChartModalMount');
                debugEl = document.getElementById('perfChartModalDebug');
                if (head) {
                    var rangeHtml = '<div class="perf-chart-range-btns" style="display:flex; gap:0.5rem; margin-top:0.5rem; flex-wrap:wrap;">';
                    ['LIVE', '1H', '4H', '1D', '1W'].forEach(function (k) {
                        rangeHtml += '<button type="button" class="perf-chart-range-btn' + (k === DEFAULT_RANGE ? ' active' : '') + '" data-range="' + k + '">' + k + '</button>';
                    });
                    rangeHtml += '</div>';
                    head.insertAdjacentHTML('beforeend', rangeHtml);
                    head.querySelectorAll('.perf-chart-range-btn').forEach(function (btn) {
                        btn.addEventListener('click', function () {
                            head.querySelectorAll('.perf-chart-range-btn').forEach(function (b) { b.classList.remove('active'); });
                            btn.classList.add('active');
                            setRange(btn.getAttribute('data-range'));
                        });
                    });
                }
                var closeBtn = document.getElementById('perfChartModalClose');
                if (closeBtn) closeBtn.addEventListener('click', closeModal);
            }
        } else {
            modalEl.innerHTML = '<div class="perf-chart-modal" id="perfChartModal">' +
                '<div class="perf-chart-modal-head"><span class="perf-chart-modal-title">Parite % &amp; Bot bakiyesi %</span>' +
                '<button type="button" class="perf-chart-modal-close" id="perfChartModalClose" aria-label="Kapat">&times;</button>' +
                '<div class="perf-chart-range-btns" style="display:flex; gap:0.5rem; margin-top:0.5rem; flex-wrap:wrap;">' +
                ['LIVE', '1H', '4H', '1D', '1W'].map(function (k) {
                    return '<button type="button" class="perf-chart-range-btn' + (k === DEFAULT_RANGE ? ' active' : '') + '" data-range="' + k + '">' + k + '</button>';
                }).join('') + '</div></div>' +
                '<div class="perf-chart-modal-body">' +
                '<div id="perfChartModalDebug" class="perf-chart-rebuild-debug" style="font-size:0.7rem; color:rgba(255,255,255,0.5); margin-bottom:0.5rem;"></div>' +
                '<div id="perfChartModalMount" style="width:100%; height:520px;"></div></div></div>';
            modalMount = document.getElementById('perfChartModalMount');
            debugEl = document.getElementById('perfChartModalDebug');
            modalEl.querySelectorAll('.perf-chart-range-btn').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    modalEl.querySelectorAll('.perf-chart-range-btn').forEach(function (b) { b.classList.remove('active'); });
                    btn.classList.add('active');
                    setRange(btn.getAttribute('data-range'));
                });
            });
            var closeBtn = document.getElementById('perfChartModalClose');
            if (closeBtn) closeBtn.addEventListener('click', closeModal);
        }

        wrapEl.style.cursor = 'pointer';
        wrapEl.title = 'Grafiği büyütmek için tıklayın';
        wrapEl.addEventListener('click', openModal);

        resetBaseline();
        sampleFromDom();
        requestAnimationFrame(function () {
            buildMiniChart();
        });

        miniUpdateTimer = setInterval(function () {
            if (!wrapMount || !miniChart) return;
            sampleFromDom();
            updateChart(miniChart.chart, miniChart.botSeries, miniChart.pariteSeries, false);
        }, MINI_UPDATE_MS);

        if (modalEl) {
            modalEl.addEventListener('click', function (e) {
                if (e.target === modalEl) closeModal();
            });
            var modalPanel = modalEl.querySelector('.perf-chart-modal');
            if (modalPanel) modalPanel.addEventListener('click', function (e) { e.stopPropagation(); });
        }
        var existingClose = document.getElementById('perfChartModalClose');
        if (existingClose && !existingClose.hasAttribute('data-rebuild-bound')) {
            existingClose.setAttribute('data-rebuild-bound', '1');
            existingClose.addEventListener('click', closeModal);
        }

        inited = true;
    }

    window.PerfChartRebuild = { init: init, parseTrailingPercent: parseTrailingPercent };
})();
