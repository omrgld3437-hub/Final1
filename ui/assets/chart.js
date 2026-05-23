/**
 * Detay grafik – TradingView Lightweight Charts.
 * Timeframe butonları = interval seçimi (1m/5m/15m/1h/4h/1d/1w); zoom değil.
 * X-axis tarih/saat formatı intervale göre; pan + lazy backfill korunuyor.
 */
(function () {
    var params = new URLSearchParams(window.location.search);
    var symbol = (params.get('symbol') || 'BTCUSDT').toUpperCase();
    var chartType = 'candle';
    var chart = null;
    var candleSeries = null;
    var lineSeries = null;
    var currentSeries = null;
    var lastKlines = [];
    var BACKEND_LIMIT_MAX = 500;

    /** Tek kaynak: buton = interval seçimi. Limit ve varsayılan görünür süre günlere orantılı. */
    var TIMEFRAMES = [
        { key: '1m',  interval: '1m',  limit: 1440, rangeDays: 1, label: '1m' },
        { key: '5m',  interval: '5m',  limit: 288, rangeDays: 1, label: '5m' },
        { key: '15m', interval: '15m', limit: 672, rangeDays: 7, label: '15m' },
        { key: '1h',  interval: '1h',  limit: 168, rangeDays: 7, label: '1h' },
        { key: '4h',  interval: '4h',  limit: 42, rangeDays: 7, label: '4h' },
        { key: '1d',  interval: '1d',  limit: 90, rangeDays: 90, label: '1d' },
        { key: '1w',  interval: '1w',  limit: 52, rangeDays: 365, label: '1w' }
    ];

    var currentTFKey = '4h';
    var currentInterval = '4h';
    var currentLimit = 42;
    var loadedFromTs = null;
    var backfillInFlight = false;
    var frontendCache = {}; // key = symbol:interval:endTime -> raw klines array
    var unsubBackfill = null;
    var BACKFILL_THRESHOLD_BARS = 80;
    /** Son mum canlı güncelleme: { time, open, high, low, close } (saniye + sayılar) */
    var liveLastBar = null;
    var priceTickIntervalId = null;
    var PRICE_TICK_MS = 1000;
    var lastChartPrice = null;
    var lastChartPct = null;
    var chartBlinkCooldownUntil = 0;
    var CHART_BLINK_COOLDOWN_MS = 400;

    function showLoading(show) {
        var el = document.getElementById('chartLoading');
        if (el) el.style.display = show ? 'block' : 'none';
    }
    function showError(msg) {
        var el = document.getElementById('chartError');
        if (el) {
            el.style.display = msg ? 'block' : 'none';
            el.textContent = msg || '';
        }
    }
    /** Türkçe format (2.633,19) veya İngilizce (2633.19) metnini sayıya çevirir. */
    function parsePriceFromDisplay(text) {
        if (text == null || text === '') return NaN;
        var s = String(text).trim().replace(/\s/g, '');
        if (s === '—' || s === '') return NaN;
        if (/^\d+[.,]\d+$/.test(s) && s.indexOf(',') !== -1) {
            s = s.replace(/\./g, '').replace(',', '.');
        } else if (/^\d{1,3}(\.\d{3})*,\d+$/.test(s)) {
            s = s.replace(/\./g, '').replace(',', '.');
        } else {
            s = s.replace(/[^\d.-]/g, '').replace(/\.(?=.*\.)/g, '');
        }
        return parseFloat(s) || NaN;
    }
    function triggerChartBlink(el, oldNum, newNum, isPct) {
        if (!el) return;
        var now = Date.now();
        if (now < chartBlinkCooldownUntil) return;
        if (!Number.isFinite(newNum)) return;
        var old = Number.isFinite(oldNum) ? oldNum : (isPct ? (parseFloat(String(el.textContent).replace(/[^0-9.-]/g, '')) || 0) : parsePriceFromDisplay(el.textContent) || 0);
        if (Math.abs(newNum - old) < (isPct ? 0.0001 : 0.0000001)) return;
        chartBlinkCooldownUntil = now + CHART_BLINK_COOLDOWN_MS;
        el.classList.remove('blink-positive', 'blink-negative');
        void el.offsetWidth;
        if (newNum > old) el.classList.add('blink-positive');
        else el.classList.add('blink-negative');
        setTimeout(function () { el.classList.remove('blink-positive', 'blink-negative'); }, 750);
    }
    function setHeader(sym, price, pct) {
        var base = sym.replace(/USDT$|BTC$|ETH$|BNB$|FDUSD$|BUSD$/i, '') || sym;
        var quote = sym.endsWith('USDT') ? 'USDT' : sym.endsWith('FDUSD') ? 'FDUSD' : sym.endsWith('BTC') ? 'BTC' : sym.endsWith('ETH') ? 'ETH' : sym.slice(-4) || '';
        var symbolEl = document.getElementById('chartSymbol');
        if (symbolEl) symbolEl.textContent = base + (quote ? ' / ' + quote : '');
        var priceEl = document.getElementById('chartPrice');
        var priceNum = price != null && Number.isFinite(typeof price === 'number' ? price : parseFloat(price)) ? (typeof price === 'number' ? price : parseFloat(price)) : null;
        if (priceEl) {
            if (priceNum != null && lastChartPrice != null && Math.abs(priceNum - lastChartPrice) > 1e-10) {
                triggerChartBlink(priceEl, lastChartPrice, priceNum, false);
            }
            priceEl.textContent = formatPrice(price);
            if (priceNum != null) {
                lastChartPrice = priceNum;
            } else {
                lastChartPrice = null;
            }
        }
        var pctEl = document.getElementById('chartPct');
        if (pctEl) {
            var pctNum = pct != null ? (typeof pct === 'number' ? pct : parseFloat(pct)) : NaN;
            if (Number.isFinite(pctNum) && lastChartPct != null && Number.isFinite(lastChartPct) && Math.abs(pctNum - lastChartPct) > 0.0001) {
                triggerChartBlink(pctEl, lastChartPct, pctNum, true);
            }
            pctEl.textContent = Number.isFinite(pctNum) ? (pctNum >= 0 ? '+' : '') + pctNum.toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + '%' : '—';
            pctEl.className = 'chart-pct ' + (pctNum >= 0 ? 'up' : 'down');
            lastChartPct = Number.isFinite(pctNum) ? pctNum : null;
        }
        var logoEl = document.getElementById('chartLogo');
        if (logoEl && typeof getCoinLogoUrl === 'function') {
            var url = getCoinLogoUrl(base);
            if (url) {
                logoEl.src = url;
                logoEl.alt = base;
                logoEl.style.display = '';
            } else {
                logoEl.style.display = 'none';
            }
        }
    }
    function formatPrice(v) {
        var n = typeof v === 'number' ? v : parseFloat(v);
        if (v == null || v === '' || !Number.isFinite(n) || n <= 0) return '—';
        if (n >= 1) return n.toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        if (n >= 0.01) return n.toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 4 });
        return n.toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 8 });
    }

    /** Backend k.t ms cinsinden; Lightweight Charts saniye istiyor. */
    function klinesToChartData(klines) {
        if (!Array.isArray(klines) || klines.length === 0) return [];
        return klines.map(function (c) {
            var tMs = Number(c.t) || 0;
            var t = tMs >= 10000000000 ? Math.floor(tMs / 1000) : tMs;
            return {
                time: t,
                open: Number(c.o) || 0,
                high: Number(c.h) || 0,
                low: Number(c.l) || 0,
                close: Number(c.c) || 0
            };
        });
    }

    function rawKlinesMergePrepend(existingRaw, olderRaw) {
        var seen = {};
        existingRaw.forEach(function (c) { seen[c.t] = true; });
        var prepend = (olderRaw || []).filter(function (c) { return !seen[c.t]; });
        return prepend.concat(existingRaw);
    }

    function getTimeFormatter() {
        var interval = currentInterval;
        var tr = typeof window !== 'undefined' && window.trTime ? window.trTime : null;
        return function (time) {
            var t = typeof time === 'number' ? time : (time && time instanceof Date ? time.getTime() / 1000 : 0);
            if (tr) {
                if (interval === '1m' || interval === '5m' || interval === '15m' || interval === '1h')
                    return tr.trFormatChartTime(t);
                if (interval === '4h') return tr.trFormatChartTimeDay(t);
                return tr.trFormatChartTimeDate(t);
            }
            var d = new Date(t * 1000);
            if (interval === '1m' || interval === '5m' || interval === '15m' || interval === '1h')
                return d.toLocaleString('tr-TR', { hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Istanbul' });
            if (interval === '4h')
                return d.toLocaleString('tr-TR', { day: '2-digit', month: 'short', hour: '2-digit', timeZone: 'Europe/Istanbul' });
            return d.toLocaleDateString('tr-TR', { day: '2-digit', month: 'short', year: '2-digit', timeZone: 'Europe/Istanbul' });
        };
    }

    function formatTooltipPrice(v) {
        var n = typeof v === 'number' ? v : parseFloat(v);
        if (v == null || v === '' || !Number.isFinite(n) || n <= 0) return '—';
        if (n >= 1) return n.toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        if (n >= 0.01) return n.toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 4 });
        return n.toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 8 });
    }

    function formatTooltipTime(time) {
        var t = typeof time === 'number' ? time : (time && time instanceof Date ? time.getTime() / 1000 : 0);
        if (typeof window !== 'undefined' && window.trTime && window.trTime.trFormatTooltipTime)
            return window.trTime.trFormatTooltipTime(t);
        var d = new Date(t * 1000);
        return d.toLocaleString('tr-TR', { dateStyle: 'short', timeStyle: 'medium', timeZone: 'Europe/Istanbul' });
    }

    var crosshairUnsub = null;

    function findBarAtTime(timeSec) {
        if (timeSec == null || !Array.isArray(lastKlines) || lastKlines.length === 0) return null;
        var t = typeof timeSec === 'number' ? timeSec : (timeSec && timeSec instanceof Date ? timeSec.getTime() / 1000 : null);
        if (t == null || !Number.isFinite(t)) return null;
        for (var i = 0; i < lastKlines.length; i++) {
            var bar = lastKlines[i];
            var barSec = Math.floor(Number(bar.t) / 1000);
            if (barSec === t) return bar;
        }
        var closest = null;
        var best = Infinity;
        for (var j = 0; j < lastKlines.length; j++) {
            var b = lastKlines[j];
            var bs = Math.floor(Number(b.t) / 1000);
            var diff = Math.abs(bs - t);
            if (diff < best) { best = diff; closest = b; }
        }
        return best <= 86400 ? closest : null;
    }

    function setupCandleTooltip() {
        var tooltipEl = document.getElementById('chartCandleTooltip');
        if (!tooltipEl || !chart) return;
        if (crosshairUnsub) {
            try { crosshairUnsub(); } catch (e) {}
            crosshairUnsub = null;
        }
        function clearTooltip() {
            tooltipEl.classList.remove('chart-tooltip-visible');
            tooltipEl.innerHTML = '<span class="tooltip-placeholder">Grafikte bir mumun üzerine gelin; detaylar burada görünecek.</span>';
        }

        crosshairUnsub = chart.subscribeCrosshairMove(function (param) {
            if (!param) {
                clearTooltip();
                return;
            }
            var container = document.getElementById('chartContainer');
            var inChart = container && param.point && param.point.x != null && param.point.y != null &&
                param.point.x >= 0 && param.point.y >= 0 &&
                param.point.x <= container.clientWidth && param.point.y <= container.clientHeight;

            if (!inChart) {
                clearTooltip();
                return;
            }

            var d = null;
            if (param.seriesData && candleSeries) d = param.seriesData.get(candleSeries);
            if (!d || d.open == null) {
                var bar = findBarAtTime(param.time);
                if (bar) {
                    d = {
                        time: Math.floor(Number(bar.t) / 1000),
                        open: Number(bar.o) || 0,
                        high: Number(bar.h) || 0,
                        low: Number(bar.l) || 0,
                        close: Number(bar.c) || 0
                    };
                }
            }

            if (!d || !Number.isFinite(d.open)) {
                clearTooltip();
                return;
            }

            var timeStr = formatTooltipTime(d.time);
            tooltipEl.classList.add('chart-tooltip-visible');
            tooltipEl.innerHTML =
                '<span class="tooltip-label">Açılış fiyatı</span> <span class="tooltip-value">' + formatTooltipPrice(d.open) + '</span> ' +
                '<span class="tooltip-label">Kapanış fiyatı</span> <span class="tooltip-value">' + formatTooltipPrice(d.close) + '</span> ' +
                '<span class="tooltip-label">En yüksek</span> <span class="tooltip-value">' + formatTooltipPrice(d.high) + '</span> ' +
                '<span class="tooltip-label">En düşük</span> <span class="tooltip-value">' + formatTooltipPrice(d.low) + '</span> ' +
                '<span class="tooltip-label">Tarih / Zaman</span> <span class="tooltip-value">' + timeStr + '</span>';
        });
    }

    function buildChart() {
        var container = document.getElementById('chartContainer');
        if (!container) return null;
        if (typeof LightweightCharts === 'undefined') {
            showError('Grafik kütüphanesi yüklenemedi. Sayfayı yenileyin veya daha sonra tekrar deneyin.');
            return null;
        }
        if (chart) {
            chart.remove();
            chart = null;
            candleSeries = null;
            lineSeries = null;
            currentSeries = null;
        }
        var isDark = document.documentElement.getAttribute('data-theme') === 'dark' ||
            (window.getComputedStyle && window.getComputedStyle(document.body).getPropertyValue('--ds-bg-primary').indexOf('1a') === 0);
        var gridSoft = isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.07)';
        var axisGray = isDark ? '#8a9199' : '#6b7280';
        var chartOptions = {
            layout: {
                background: { type: 'solid', color: 'transparent' },
                textColor: axisGray,
                fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
                fontSize: 12
            },
            grid: {
                vertLines: { color: gridSoft },
                horzLines: { color: gridSoft }
            },
            rightPriceScale: { borderVisible: true, borderColor: axisGray },
            timeScale: {
                borderVisible: true,
                timeVisible: true,
                borderColor: axisGray,
                rightOffset: 5,
                barSpacing: 12,
                minBarSpacing: 2,
                maxBarSpacing: 150,
                fixLeftEdge: false,
                fixRightEdge: false,
                lockVisibleTimeRangeOnResize: true
            },
            localization: {
                locale: 'tr-TR',
                timeFormatter: getTimeFormatter()
            },
            handleScroll: {
                mouseWheel: true,
                pressedMouseMove: true,
                horzTouchDrag: true,
                vertTouchDrag: false
            },
            handleScale: {
                axisPressedMouseMove: true,
                mouseWheel: true,
                pinch: true
            }
        };
        chart = LightweightCharts.createChart(container, chartOptions);
        var priceFormatTR = {
            type: 'custom',
            formatter: function (price) { return formatPrice(price); },
            minMove: 0.01
        };
        candleSeries = chart.addCandlestickSeries({
            upColor: '#00C076',
            downColor: '#F6465D',
            borderUpColor: '#00C076',
            borderDownColor: '#F6465D',
            wickUpColor: '#00C076',
            wickDownColor: '#F6465D',
            priceFormat: priceFormatTR
        });
        lineSeries = chart.addLineSeries({
            color: '#f0b90b',
            lineWidth: 2,
            priceFormat: priceFormatTR
        });
        currentSeries = candleSeries;
        lineSeries.setData([]);
        setupCandleTooltip();
        return chart;
    }

    function applyMergedData(mergedRaw) {
        lastKlines = mergedRaw || [];
        var data = klinesToChartData(lastKlines);
        if (data.length === 0) return;
        if (data.length >= 2 && typeof window.__DEBUG_CHART__ !== 'undefined' && window.__DEBUG_CHART__) {
            var dt = data[1].time - data[0].time;
            console.log('interval', currentInterval, 'dt (s)', dt);
        }
        candleSeries.setData(data);
        var lineData = data.map(function (d) { return { time: d.time, value: d.close }; });
        lineSeries.setData(lineData);
        if (chartType === 'candle') {
            candleSeries.applyOptions({ visible: true });
            lineSeries.applyOptions({ visible: false });
            currentSeries = candleSeries;
        } else {
            candleSeries.applyOptions({ visible: false });
            lineSeries.applyOptions({ visible: true });
            currentSeries = lineSeries;
        }
        if (lastKlines.length > 0) {
            loadedFromTs = Math.floor(lastKlines[0].t / 1000);
            var last = lastKlines[lastKlines.length - 1];
            var tSec = Math.floor(last.t / 1000);
            liveLastBar = {
                time: tSec,
                open: Number(last.o) || 0,
                high: Number(last.h) || 0,
                low: Number(last.l) || 0,
                close: Number(last.c) || 0
            };
            var priceEl = document.getElementById('chartPrice');
            if (priceEl && (priceEl.textContent === '—' || !priceEl.textContent.trim())) {
                setHeader(symbol, liveLastBar.close, null);
            }
        } else {
            loadedFromTs = null;
            liveLastBar = null;
        }
    }

    function fetchKlines(interval, limit, endTimeMs, cb) {
        var qs = 'symbol=' + encodeURIComponent(symbol) + '&interval=' + encodeURIComponent(interval) + '&limit=' + limit;
        if (endTimeMs != null) qs += '&end_time=' + endTimeMs;
        var url = window.location.origin + '/api/spot/klines?' + qs;
        var cacheKey = symbol + ':' + interval + ':' + (endTimeMs != null ? endTimeMs : 'latest');
        if (frontendCache[cacheKey]) {
            if (cb) cb(frontendCache[cacheKey]);
            return;
        }
        fetch(url)
            .then(function (r) {
                if (!r.ok) {
                    var err = new Error('HTTP ' + r.status);
                    err.status = r.status;
                    throw err;
                }
                return r.json();
            })
            .then(function (data) {
                if (!Array.isArray(data)) data = [];
                if (data.length) frontendCache[cacheKey] = data;
                if (cb) cb(data);
            })
            .catch(function (e) {
                var msg = 'Grafik verisi alınamadı.';
                if (e && (e.status === 418 || e.status === 429)) {
                    msg = 'Binance istek limiti aktif (IP geçici ban). Birkaç dakika bekleyip tekrar deneyin.';
                }
                showError(msg);
                if (cb) cb([]);
            });
    }

    /** Varsayılan görünür aralık: interval'a göre rangeDays (1=24h, 7=1 hafta, 90=3 ay, 365=1 yıl). */
    function setDefaultVisibleRange() {
        if (!chart || !lastKlines.length) return;
        try {
            var tf = null;
            for (var i = 0; i < TIMEFRAMES.length; i++) {
                if (TIMEFRAMES[i].key === currentTFKey) { tf = TIMEFRAMES[i]; break; }
            }
            var days = (tf && tf.rangeDays) ? tf.rangeDays : 7;
            var last = lastKlines[lastKlines.length - 1];
            var toSec = Math.floor(Number(last.t) / 1000);
            var rangeSec = days * 86400;
            var fromSec = toSec - rangeSec;
            chart.timeScale().setVisibleRange({ from: fromSec, to: toSec });
        } catch (e) {}
    }

    function setupBackfillSubscription() {
        if (!chart) return;
        if (unsubBackfill) {
            try { unsubBackfill(); } catch (e) {}
            unsubBackfill = null;
        }
        unsubBackfill = chart.timeScale().subscribeVisibleTimeRangeChange(function () {
            if (backfillInFlight || loadedFromTs == null) return;
            var range = chart.timeScale().getVisibleLogicalRange();
            if (!range || range.from > BACKFILL_THRESHOLD_BARS) return;
            var endTimeMs = loadedFromTs * 1000 - 1;
            backfillInFlight = true;
            fetchKlines(currentInterval, BACKEND_LIMIT_MAX, endTimeMs, function (olderRaw) {
                backfillInFlight = false;
                if (!Array.isArray(olderRaw) || olderRaw.length === 0) return;
                var merged = rawKlinesMergePrepend(lastKlines, olderRaw);
                if (merged.length === lastKlines.length) return;
                var prepended = merged.length - lastKlines.length;
                var prevRange = chart.timeScale().getVisibleLogicalRange();
                applyMergedData(merged);
                if (prevRange) {
                    chart.timeScale().setVisibleLogicalRange({
                        from: prevRange.from + prepended,
                        to: prevRange.to + prepended
                    });
                }
            });
        });
    }

    /** Interval + limit ile veri çek, çiz, fitContent, backfill kur. Zoom yok. */
    function loadAndRender(endTimeMs, cb) {
        showError('');
        showLoading(true);
        var interval = currentInterval;
        var limit = Math.min(currentLimit, BACKEND_LIMIT_MAX);
        if (!chart) buildChart();
        if (!chart) { showLoading(false); if (cb) cb(); return; }
        fetchKlines(interval, limit, endTimeMs || null, function (data) {
            showLoading(false);
            if (!Array.isArray(data) || data.length === 0) {
                if (!document.getElementById('chartError') || document.getElementById('chartError').textContent === '') {
                    showError('Mum verisi yok. Binance geçici limit uyguluyor olabilir; birkaç dakika sonra yenileyin.');
                }
                if (cb) cb();
                return;
            }
            applyMergedData(data);
            try { setDefaultVisibleRange(); } catch (e) {}
            setupBackfillSubscription();
            loadTicker();
            if (cb) cb();
        });
    }

    function onIntervalClick(tfKey) {
        var tf = null;
        for (var i = 0; i < TIMEFRAMES.length; i++) {
            if (TIMEFRAMES[i].key === tfKey) { tf = TIMEFRAMES[i]; break; }
        }
        if (!tf) return;
        if (unsubBackfill) {
            try { unsubBackfill(); } catch (e) {}
            unsubBackfill = null;
        }
        currentTFKey = tfKey;
        currentInterval = tf.interval;
        currentLimit = tf.limit;
        loadedFromTs = null;
        document.querySelectorAll('.chart-toolbar button[data-interval]').forEach(function (btn) {
            btn.classList.toggle('active', btn.getAttribute('data-interval') === tfKey);
        });
        buildChart();
        loadAndRender(null);
    }

    function switchChartType(type) {
        chartType = type;
        var candleBtn = document.getElementById('chartTypeCandle');
        var lineBtn = document.getElementById('chartTypeLine');
        if (candleBtn) candleBtn.classList.toggle('active', type === 'candle');
        if (lineBtn) lineBtn.classList.toggle('active', type === 'line');
        if (!chart || lastKlines.length === 0) return;
        if (type === 'candle') {
            candleSeries.applyOptions({ visible: true });
            lineSeries.applyOptions({ visible: false });
            currentSeries = candleSeries;
        } else {
            candleSeries.applyOptions({ visible: false });
            lineSeries.applyOptions({ visible: true });
            currentSeries = lineSeries;
        }
    }

    function intervalToSeconds(interval) {
        var m = { '1m': 60, '3m': 180, '5m': 300, '15m': 900, '30m': 1800, '1h': 3600, '2h': 7200, '4h': 14400, '1d': 86400, '1w': 604800 };
        return m[interval] || 300;
    }

    function updateLiveBar(price) {
        if (!candleSeries || !lineSeries || price == null || !Number.isFinite(price) || price <= 0) return;
        var nowSec = Math.floor(Date.now() / 1000);
        var intervalSec = intervalToSeconds(currentInterval);
        var currentCandleStart = Math.floor(nowSec / intervalSec) * intervalSec;
        if (!liveLastBar) {
            liveLastBar = {
                time: currentCandleStart,
                open: price,
                high: price,
                low: price,
                close: price
            };
            try {
                candleSeries.update(liveLastBar);
                lineSeries.update({ time: liveLastBar.time, value: price });
            } catch (e) {}
            return;
        }
        if (currentCandleStart > liveLastBar.time) {
            liveLastBar.close = price;
            try {
                candleSeries.update(liveLastBar);
                lineSeries.update({ time: liveLastBar.time, value: liveLastBar.close });
            } catch (e) {}
            liveLastBar = {
                time: currentCandleStart,
                open: price,
                high: price,
                low: price,
                close: price
            };
        } else {
            liveLastBar.close = price;
            if (price > liveLastBar.high) liveLastBar.high = price;
            if (price < liveLastBar.low) liveLastBar.low = price;
        }
        try {
            candleSeries.update(liveLastBar);
            lineSeries.update({ time: liveLastBar.time, value: price });
        } catch (e) {}
    }

    function loadYearHighLow() {
        var url = window.location.origin + '/api/spot/klines?symbol=' + encodeURIComponent(symbol) + '&interval=1d&limit=365';
        fetch(url)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (!Array.isArray(data) || data.length === 0) return;
                var high = -Infinity;
                var low = Infinity;
                for (var i = 0; i < data.length; i++) {
                    var h = parseFloat(data[i].h || data[i].high || 0);
                    var l = parseFloat(data[i].l || data[i].low || 0);
                    if (Number.isFinite(h) && h > high) high = h;
                    if (Number.isFinite(l) && l < low) low = l;
                }
                var highEl = document.getElementById('chartYearHigh');
                var lowEl = document.getElementById('chartYearLow');
                if (highEl) highEl.textContent = Number.isFinite(high) && high > 0 ? formatPrice(high) : '—';
                if (lowEl) lowEl.textContent = Number.isFinite(low) && low > 0 ? formatPrice(low) : '—';
            })
            .catch(function () {});
    }

    function loadTicker() {
        var url = window.location.origin + '/api/spot/ticker_24h?symbol=' + encodeURIComponent(symbol);
        fetch(url)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var price = parseFloat(data.lastPrice || data.weightedAvgPrice || 0);
                var pct = parseFloat(data.priceChangePercent || 0);
                setHeader(symbol, price, pct);
                updateLiveBar(price);
            })
            .catch(function () {
                if (liveLastBar && liveLastBar.close > 0) setHeader(symbol, liveLastBar.close, null);
            });
    }

    function startPriceTick() {
        if (priceTickIntervalId) return;
        priceTickIntervalId = setInterval(function () {
            loadTicker();
        }, PRICE_TICK_MS);
    }

    function stopPriceTick() {
        if (priceTickIntervalId) {
            clearInterval(priceTickIntervalId);
            priceTickIntervalId = null;
        }
    }

    function init() {
        var embed = params.get('embed') === '1';
        var initialInterval = params.get('interval') || '4h';
        for (var i = 0; i < TIMEFRAMES.length; i++) {
            if (TIMEFRAMES[i].key === initialInterval) {
                currentTFKey = initialInterval;
                currentInterval = TIMEFRAMES[i].interval;
                currentLimit = TIMEFRAMES[i].limit;
                break;
            }
        }
        setHeader(symbol, null, null);
        buildChart();
        if (!chart) return;
        loadAndRender(null);
        startPriceTick();
        loadYearHighLow();

        var backLink = document.getElementById('chartBackLink');
        if (backLink) {
            if (embed) {
                backLink.textContent = 'Kapat';
                backLink.href = '#';
                backLink.removeAttribute('aria-label');
                backLink.setAttribute('aria-label', 'Kapat');
                backLink.addEventListener('click', function (e) {
                    e.preventDefault();
                    try {
                        if (window.parent !== window) window.parent.postMessage('closeChartModal', '*');
                    } catch (err) {}
                });
            } else {
                var fromParam = params.get('from') || '';
                backLink.href = '/ui/dashboard.html';
                backLink.addEventListener('click', function (e) {
                    e.preventDefault();
                    try {
                        if (fromParam === 'botcreate') {
                            sessionStorage.setItem('openBotCreate', '1');
                            sessionStorage.setItem('openBotCreateSymbol', symbol || '');
                        } else {
                            sessionStorage.setItem('openSpotModal', symbol);
                        }
                    } catch (err) {}
                    window.location.href = '/ui/dashboard.html';
                });
            }
        }

        document.querySelectorAll('.chart-toolbar button[data-interval]').forEach(function (btn) {
            var ival = btn.getAttribute('data-interval');
            btn.classList.toggle('active', ival === currentTFKey);
            btn.addEventListener('click', function () {
                onIntervalClick(ival);
            });
        });

        var candleBtn = document.getElementById('chartTypeCandle');
        var lineBtn = document.getElementById('chartTypeLine');
        if (candleBtn) candleBtn.addEventListener('click', function () { switchChartType('candle'); });
        if (lineBtn) lineBtn.addEventListener('click', function () { switchChartType('line'); });

        window.addEventListener('resize', function () {
            if (chart && document.getElementById('chartContainer')) {
                chart.resize(document.getElementById('chartContainer').clientWidth, document.getElementById('chartContainer').clientHeight);
            }
        });

        var chartContainer = document.getElementById('chartContainer');
        if (chartContainer) {
            chartContainer.addEventListener('mouseleave', function () {
                var el = document.getElementById('chartCandleTooltip');
                if (el) {
                    el.classList.remove('chart-tooltip-visible');
                    el.innerHTML = '<span class="tooltip-placeholder">Grafikte bir mumun üzerine gelin; detaylar burada görünecek.</span>';
                }
            });
        }

        /* Mobile: try landscape lock on load; always show "Yan çevir" in portrait so user can open in landscape */
        if (!embed && typeof window !== 'undefined') {
            var landscapeBtn = document.getElementById('chartLandscapeBtn');
            var isMobileNarrow = window.innerWidth <= 768;
            var isPortrait = window.innerHeight > window.innerWidth;
            function tryLockLandscape() {
                if (screen.orientation && typeof screen.orientation.lock === 'function') {
                    return screen.orientation.lock('landscape').catch(function () {
                        if (landscapeBtn) landscapeBtn.classList.add('visible');
                    });
                }
                if (landscapeBtn && (isMobileNarrow || isPortrait)) landscapeBtn.classList.add('visible');
            }
            if (isMobileNarrow && isPortrait) {
                tryLockLandscape();
                if (landscapeBtn) landscapeBtn.classList.add('visible');
            }
            if (landscapeBtn) {
                landscapeBtn.addEventListener('click', function () {
                    var doc = document.documentElement;
                    if (!document.fullscreenElement && !document.webkitFullscreenElement) {
                        var req = doc.requestFullscreen || doc.webkitRequestFullscreen;
                        if (req) {
                            req.call(doc).then(function () {
                                if (screen.orientation && typeof screen.orientation.lock === 'function') {
                                    screen.orientation.lock('landscape').catch(function () {});
                                }
                            }).catch(function () {});
                        } else if (screen.orientation && typeof screen.orientation.lock === 'function') {
                            screen.orientation.lock('landscape').catch(function () {});
                        }
                    } else if (screen.orientation && typeof screen.orientation.lock === 'function') {
                        screen.orientation.lock('landscape').catch(function () {});
                    }
                });
            }
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
