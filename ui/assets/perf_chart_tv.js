/**
 * Perf chart: TradingView Lightweight Charts. Data from #perfReportBakiyeDegisim, #perfReportPariteDegisim.
 * window.PerfChartTV = { init, start, stop, setRange, reset }
 */
(function() {
    'use strict';

    var STORAGE_KEY_PREFIX = 'perf_tv_samples_v1';
    var SAVE_EVERY_N = 5;
    var MAX_AGE_SEC = 7 * 24 * 3600;
    var READY_POLL_MS = 300;
    var MOUNT_MIN_WIDTH = 200;
    var MOUNT_MIN_HEIGHT = 150;
    var CHART_HEIGHT = 240;

    var RANGE_SEC = { '1m': 60, '5m': 300, '1h': 3600, '4h': 14400, '1d': 86400 };
    /** 5m: bot başlangıcından bu yana 5 dakikada bir nokta (daha detaylı grafik). 1m: son 24 saat dakikada bir. */
    var DISPLAY_WINDOW_SEC = { '1m': 24 * 3600, '5m': 7 * 24 * 3600, '1h': 24 * 3600, '4h': 7 * 24 * 3600, '1d': 30 * 24 * 3600 };

    function getSampleIntervalMs() {
        return (RANGE_SEC[selectedRange] || 14400) * 1000;
    }

    /** Seçili aralığın bir sonraki bucket bitiş zamanı (unix saniye). */
    function getNextBucketEndSec() {
        var bucketSec = RANGE_SEC[selectedRange] || 14400;
        return Math.ceil(nowSec() / bucketSec) * bucketSec;
    }

    /** Bir sonraki bucket sonunda sample() çalıştıracak zamanlayıcıyı ayarla. */
    function scheduleNextSample() {
        if (sampleTimer) return;
        var bucketSec = RANGE_SEC[selectedRange] || 14400;
        var nextEnd = getNextBucketEndSec();
        var delayMs = Math.max(100, (nextEnd - nowSec()) * 1000);
        sampleTimer = setTimeout(function() {
            sampleTimer = null;
            sample();
            scheduleNextSample();
        }, delayMs);
    }

    var inited = false;
    var readyTimer = null;
    var sampleTimer = null;
    var liveUpdateTimer = null;
    var lastLiveBotVal = null;
    var lastLivePariteVal = null;
    var LIVE_UPDATE_INTERVAL_MS = 5000;
    var wrapEl = null;
    var mountEl = null;
    var statusEl = null;
    var chart = null;
    var botSeries = null;
    var pariteSeries = null;
    var resizeObserver = null;
    var selectedRange = '4h';
    var baseline = null;
    var samples = [];
    var saveCounter = 0;
    var applyVisibleRange = true;
    var applyModalVisibleRange = false;
    var modalChart = null;
    var modalBotSeries = null;
    var modalPariteSeries = null;
    var zeroLineSeries = null;
    var startDotSeries = null;
    var modalZeroLineSeries = null;
    var modalStartDotSeries = null;
    var currentBotId = '';
    var currentAccountId = null;
    var currentAccountCode = null;
    var activeAbortController = null;

    function getStorageKey() {
        return STORAGE_KEY_PREFIX + '_b' + (currentBotId != null && currentBotId !== '' ? currentBotId : 'none');
    }

    /** USD/bakiye metninden sayı parse et (örn. "$100.00", "$1,234.56", "0.1234") */
    function parseUsdOrNumber(text) {
        if (text == null || typeof text !== 'string') return null;
        var s = (text || '').trim().replace(/\$/g, '');
        if (s === '—' || s === '' || s === '-' || s === '–') return null;
        var commaCount = (s.match(/,/g) || []).length;
        var dotCount = (s.match(/\./g) || []).length;
        if (commaCount > 0 || dotCount > 0) {
            if (dotCount === 1 && commaCount === 0) {
                s = s.replace(/,/g, '');
            } else if (commaCount === 1 && dotCount === 0) {
                s = s.replace(/,/g, '.');
            } else if (dotCount === 1 && commaCount > 0) {
                s = s.replace(/,/g, '');
            } else if (commaCount === 1 && dotCount === 1) {
                var lastComma = s.lastIndexOf(',');
                var lastDot = s.lastIndexOf('.');
                if (lastDot > lastComma) {
                    s = s.replace(/,/g, '');
                } else {
                    s = s.replace(/\./g, '').replace(',', '.');
                }
            } else {
                s = s.replace(/,/g, '');
            }
        }
        var n = parseFloat(s);
        return isNaN(n) ? null : n;
    }

    /** Metnin sonundaki yüzde değerini parse et (örn. "+1.23%", " -0.50%") */
    function parseTrailingPct(text) {
        if (text == null || typeof text !== 'string') return null;
        var m = (text.trim()).match(/([+-]?\d+(?:[.,]\d+)?)\s*%\s*$/);
        if (!m) return null;
        var s = m[1].replace(',', '.');
        var n = parseFloat(s);
        return isNaN(n) ? null : n;
    }

    /**
     * Grafik yüzdeleri: performans raporundaki başlangıç ve güncel değerlerden hesaplanır.
     * Bot % = (Güncel bakiye - Başlangıç bakiyesi) / Başlangıç bakiyesi * 100
     * Parite % = (Parite güncel fiyat - Referans fiyat) / Referans fiyat * 100
     * Hesaplanamazsa Bakiye Değişimi / Parite Değişimi span'larındaki yüzde metni yedek olarak kullanılır.
     */
    function getDataFromDom() {
        var startBakiyeEl = document.getElementById('perfReportStartBakiye');
        var guncelBakiyeEl = document.getElementById('perfReportGuncelBakiye');
        var refPriceEl = document.getElementById('perfReportRefPrice');
        var pariteGuncelEl = document.getElementById('perfReportPariteGuncel');
        var bakiyeDegisimEl = document.getElementById('perfReportBakiyeDegisim');
        var pariteDegisimEl = document.getElementById('perfReportPariteDegisim');

        var startBakiye = startBakiyeEl ? parseUsdOrNumber(startBakiyeEl.textContent) : null;
        var guncelBakiye = guncelBakiyeEl ? parseUsdOrNumber(guncelBakiyeEl.textContent) : null;
        var refPrice = refPriceEl ? parseUsdOrNumber(refPriceEl.textContent) : null;
        var pariteGuncel = pariteGuncelEl ? parseUsdOrNumber(pariteGuncelEl.textContent) : null;

        var botPct = null;
        if (startBakiye != null && startBakiye > 0 && guncelBakiye != null) {
            botPct = (guncelBakiye - startBakiye) / startBakiye * 100;
        }
        if (botPct == null && bakiyeDegisimEl) {
            botPct = parseTrailingPct(bakiyeDegisimEl.textContent);
        }

        var paritePct = null;
        if (refPrice != null && refPrice > 0 && pariteGuncel != null) {
            paritePct = (pariteGuncel - refPrice) / refPrice * 100;
        }
        if (paritePct == null && pariteDegisimEl) {
            paritePct = parseTrailingPct(pariteDegisimEl.textContent);
        }

        return { botPct: botPct, paritePct: paritePct };
    }

    /** Performans raporundaki Parite Başlangıç Fiyatı (referans) — tek değer, grafik boyunca aynı */
    function getRefPriceFromDom() {
        var el = document.getElementById('perfReportRefPrice');
        if (!el || !el.textContent) return null;
        var s = (el.textContent || '').trim().replace(',', '.');
        if (s === '—' || s === '' || s === '-') return null;
        var n = parseFloat(s);
        return isNaN(n) ? null : n;
    }

    function nowSec() { return Math.floor(Date.now() / 1000); }

    function findNearestSample(timeSec) {
        if (!samples.length) return null;
        var best = null;
        var bestDiff = Infinity;
        for (var i = 0; i < samples.length; i++) {
            var d = Math.abs(samples[i].ts - timeSec);
            if (d < bestDiff) { bestDiff = d; best = samples[i]; }
        }
        return best;
    }

    function buildCrosshairTooltipHtml(timeSec, sample) {
        var dateStr = timeSec != null ? new Date(timeSec * 1000).toLocaleString('tr-TR', { dateStyle: 'short', timeStyle: 'medium' }) : '—';
        var botPctStr = sample && sample.botPct != null ? (sample.botPct >= 0 ? '+' : '') + sample.botPct.toFixed(2) + '%' : '—';
        var paritePctStr = sample && sample.paritePct != null ? (sample.paritePct >= 0 ? '+' : '') + sample.paritePct.toFixed(2) + '%' : '—';
        return '<div class="pct-tooltip-row"><strong>Tarih</strong> ' + dateStr + '</div>' +
            '<div class="pct-tooltip-row"><strong>Bot %</strong> ' + botPctStr + '</div>' +
            '<div class="pct-tooltip-row"><strong>Parite %</strong> ' + paritePctStr + '</div>';
    }

    /** Yerel depodan grafik state yükle (sadece sunucu boş/hatalıysa yedek). */
    function loadStorage() {
        try {
            var raw = localStorage.getItem(getStorageKey());
            if (!raw) return;
            var data = JSON.parse(raw);
            if (data.baseline) baseline = data.baseline;
            if (Array.isArray(data.samples)) samples = data.samples;
            if (data.range && RANGE_SEC[data.range]) selectedRange = data.range;
        } catch (e) {}
    }

    function buildAccountQuery() {
        if (currentAccountId != null && currentAccountId !== '') return '?account_id=' + encodeURIComponent(currentAccountId);
        if (currentAccountCode != null && currentAccountCode !== '') return '?account_code=' + encodeURIComponent(currentAccountCode);
        return '';
    }

    /** Grafik state tek kaynak: backend. Önce sunucudan oku; sunucu boş/hatalıysa localStorage yedek. */
    function loadChartStateFromServer(cb) {
        if (!currentBotId || !window.apiClient) {
            loadStorage();
            if (cb) cb();
            return;
        }
        loadPerfFromApi(selectedRange).then(function() { if (cb) cb(); }).catch(function() {
            loadStorage();
            if (cb) cb();
        });
    }

    /** Fetch perf series from API; abort previous request. Never re-create chart; only setData. */
    function loadPerfFromApi(range, opts) {
        opts = opts || {};
        if (activeAbortController) {
            activeAbortController.abort();
            activeAbortController = null;
        }
        activeAbortController = new AbortController();
        var bucket = range === '1h' ? '1h' : (RANGE_SEC[range] ? range : '4h');
        var q = buildAccountQuery();
        var url = '/api/bots-engine/' + currentBotId + '/perf-chart-data?range=' + encodeURIComponent(range) + '&bucket=' + encodeURIComponent(bucket) + q.replace('?', '&');
        var signal = activeAbortController.signal;
        if (opts.disableRangeButtons && wrapEl) {
            wrapEl.querySelectorAll('.pct-btn[data-range]').forEach(function(b) { b.disabled = true; });
        }
        return new Promise(function(resolve, reject) {
            window.apiClient.get(url, { signal: signal })
                .then(function(res) {
                    if (activeAbortController && signal.aborted) return reject(new Error('aborted'));
                    if (res && Array.isArray(res.series)) {
                        applySeriesFromApi(res.series, res.meta || {}, range);
                    }
                    resolve();
                })
                .catch(function(err) {
                    if (err && err.name === 'AbortError') return reject(err);
                    reject(err);
                })
                .finally(function() {
                    if (opts.disableRangeButtons && wrapEl) {
                        wrapEl.querySelectorAll('.pct-btn[data-range]').forEach(function(b) { b.disabled = false; });
                    }
                    activeAbortController = null;
                });
        });
    }

    /** Apply API series to chart only (setData). No DOM parse. No chart re-create. */
    function applySeriesFromApi(series, meta, range) {
        if (!chart || !botSeries || !pariteSeries) return;
        var bot0 = (meta && (meta.baseline_bot0 != null || meta.baseline_equity != null)) ? (meta.baseline_bot0 != null ? meta.baseline_bot0 : meta.baseline_equity) : 0;
        var parite0 = (meta && meta.baseline_parite0 != null) ? meta.baseline_parite0 : 0;
        function safeVal(v) { return (v != null && v === v) ? Number(v) : 0; }
        var botData = [];
        var pariteData = [];
        for (var i = 0; i < series.length; i++) {
            var s = series[i];
            var t = s.ts != null ? s.ts : s.time;
            if (t == null) continue;
            var bp = s.bot_pct != null ? s.bot_pct : s.botPct;
            var pp = s.basket_pct != null ? s.basket_pct : s.paritePct;
            botData.push({ time: t, value: safeVal(bp) - safeVal(bot0) });
            pariteData.push({ time: t, value: safeVal(pp) - safeVal(parite0) });
        }
        if (range) selectedRange = range;
        var lastBot = botData.length ? botData[botData.length - 1].value : 0;
        var lastParite = pariteData.length ? pariteData[pariteData.length - 1].value : 0;
        var botGreen = lastBot >= lastParite;
        botSeries.setData(botData);
        pariteSeries.setData(pariteData);
        botSeries.applyOptions({ color: botGreen ? '#0ECB81' : '#F6465D' });
        pariteSeries.applyOptions({ color: botGreen ? '#F6465D' : '#0ECB81' });
        var zeroData = botData.length ? [{ time: botData[0].time, value: 0 }, { time: botData[botData.length - 1].time, value: 0 }] : [];
        if (zeroLineSeries) zeroLineSeries.setData(zeroData);
        if (startDotSeries && botData.length) {
            startDotSeries.setData([{ time: botData[0].time, value: 0 }]);
            if (startDotSeries.setMarkers) startDotSeries.setMarkers([{ time: botData[0].time, position: 'inBar', shape: 'circle', color: '#ffffff', size: 0.5 }]);
        }
        var legBot = document.getElementById('pctLegendBot');
        var legParite = document.getElementById('pctLegendParite');
        var botLabel = 'Bot bakiyesi %' + (lastBot != null ? ' ' + (lastBot >= 0 ? '+' : '') + lastBot.toFixed(2) + '%' : '');
        var pariteLabel = 'Parite %' + (lastParite != null ? ' ' + (lastParite >= 0 ? '+' : '') + lastParite.toFixed(2) + '%' : '');
        if (legBot) { legBot.textContent = botLabel; legBot.style.color = (botGreen ? '#0ECB81' : '#F6465D'); }
        if (legParite) { legParite.textContent = pariteLabel; legParite.style.color = (botGreen ? '#F6465D' : '#0ECB81'); }
        setStatus((meta && meta.points != null) ? ('Bot ' + lastBot.toFixed(2) + '% | Parite ' + lastParite.toFixed(2) + '% | ' + (selectedRange || range).toUpperCase() + ' | ' + meta.points + ' nokta') : '');
    }

    /** Sunucuya grafik state kaydet (tek kaynak backend; localStorage önbellek). */
    function saveChartStateToServer() {
        if (!currentBotId || !window.apiClient) return;
        var payload = { baseline: baseline, samples: samples, range: selectedRange };
        var q = buildAccountQuery();
        window.apiClient.put('/api/bots-engine/' + currentBotId + '/perf-chart-state' + q, payload).catch(function() {});
    }

    /** Sekme tekrar görünür olduğunda state'i backend'den al (tek kaynak; diğer cihaz/tarayıcı ile senkron). */
    function mergeChartStateFromServer() {
        if (!currentBotId || !window.apiClient) return;
        var q = buildAccountQuery();
        window.apiClient.get('/api/bots-engine/' + currentBotId + '/perf-chart-state' + q)
            .then(function(res) {
                if (!res) return;
                if (res.baseline != null) baseline = res.baseline;
                if (Array.isArray(res.samples)) samples = res.samples.slice();
                if (res.range && RANGE_SEC[res.range]) selectedRange = res.range;
                pruneSamples();
                try { localStorage.setItem(getStorageKey(), JSON.stringify({ baseline: baseline, samples: samples, range: selectedRange })); } catch (e) {}
                if (wrapEl) wrapEl.querySelectorAll('.pct-btn[data-range]').forEach(function(b) {
                    b.classList.toggle('pct-active', b.getAttribute('data-range') === selectedRange);
                });
                renderChart();
            })
            .catch(function() {});
    }

    function pruneSamples() {
        var now = nowSec();
        var cut = now - MAX_AGE_SEC;
        samples = samples.filter(function(s) { return s.ts >= cut; });
    }

    function saveStorage() {
        try {
            var payload = { baseline: baseline, samples: samples, range: selectedRange };
            localStorage.setItem(getStorageKey(), JSON.stringify(payload));
            saveChartStateToServer();
        } catch (e) {}
    }

    function setStatus(msg) {
        if (statusEl) statusEl.textContent = msg || '';
    }

    function mountIsVisible() {
        if (!mountEl || !wrapEl) return false;
        var wrapRect = wrapEl.getBoundingClientRect();
        var wrapStyle = window.getComputedStyle(wrapEl);
        if (wrapStyle.display === 'none' || wrapStyle.visibility === 'hidden') return false;
        if ((wrapRect.width || 0) < MOUNT_MIN_WIDTH || (wrapRect.height || 0) < MOUNT_MIN_HEIGHT) return false;
        return true;
    }

    function createChartIfReady() {
        if (chart || !mountEl) return;
        if (typeof window.LightweightCharts === 'undefined') {
            if (wrapEl) wrapEl.innerHTML = '<div class="pct-fatal">Chart lib missing: LightweightCharts</div>';
            return;
        }
        if (!mountIsVisible()) return;
        var w = Math.max(MOUNT_MIN_WIDTH, mountEl.clientWidth || mountEl.offsetWidth || 400);
        var h = Math.max(MOUNT_MIN_HEIGHT, CHART_HEIGHT);
        var L = window.LightweightCharts;
        chart = L.createChart(mountEl, {
            width: w,
            height: h,
            layout: { background: { type: 'solid', color: '#0b0f14' }, textColor: '#9aa4b2' },
            grid: {
                vertLines: { visible: true, color: 'rgba(255,255,255,0.06)' },
                horzLines: { visible: true, color: 'rgba(255,255,255,0.06)' }
            },
            rightPriceScale: {
                visible: true,
                borderVisible: false,
                scaleMargins: { top: 0.1, bottom: 0.1 },
                autoScale: true
            },
            timeScale: { timeVisible: true, secondsVisible: false, borderVisible: false },
            crosshair: { mode: L.CrosshairMode.Normal }
        });
        zeroLineSeries = chart.addLineSeries({ lineWidth: 1, color: 'rgba(255,255,255,0.22)', lineStyle: 2, priceLineVisible: false, lastValueVisible: false, priceFormat: { type: 'price', precision: 2, minMove: 0.01 } });
        startDotSeries = chart.addLineSeries({ lineWidth: 0, color: 'transparent', priceLineVisible: false, lastValueVisible: false, priceFormat: { type: 'price', precision: 2, minMove: 0.01 } });
        botSeries = chart.addLineSeries({ lineWidth: 1, priceLineVisible: false, lastValueVisible: true, priceFormat: { type: 'price', precision: 2, minMove: 0.01 } });
        pariteSeries = chart.addLineSeries({ lineWidth: 1, priceLineVisible: false, lastValueVisible: true, priceFormat: { type: 'price', precision: 2, minMove: 0.01 } });
        resizeObserver = new ResizeObserver(function() {
            if (!chart || !mountEl) return;
            var r = mountEl.getBoundingClientRect();
            var width = Math.max(MOUNT_MIN_WIDTH, r.width || mountEl.clientWidth);
            var height = Math.max(MOUNT_MIN_HEIGHT, r.height || CHART_HEIGHT);
            chart.applyOptions({ width: width, height: height });
            renderChart();
        });
        resizeObserver.observe(mountEl);
        var tooltipEl = document.getElementById('pctCrosshairTooltip');
        if (!tooltipEl && wrapEl) {
            tooltipEl = document.createElement('div');
            tooltipEl.id = 'pctCrosshairTooltip';
            tooltipEl.className = 'pct-crosshair-tooltip';
            wrapEl.appendChild(tooltipEl);
        }
        if (chart && tooltipEl) {
            chart.subscribeCrosshairMove(function(param) {
                if (param.point.x < 0 || param.point.y < 0) {
                    tooltipEl.style.display = 'none';
                    return;
                }
                var t = null;
                var tsApi = chart && chart.timeScale ? chart.timeScale() : null;
                if (tsApi && typeof tsApi.coordinateToTime === 'function') {
                    var coordTime = tsApi.coordinateToTime(param.point.x);
                    t = typeof coordTime === 'number' ? coordTime : (coordTime && typeof coordTime === 'object' && coordTime.timestamp != null ? coordTime.timestamp : null);
                }
                if (t == null) {
                    t = typeof param.time === 'number' ? param.time : (param.time && typeof param.time === 'object' && param.time.timestamp != null ? param.time.timestamp : null);
                }
                if (t == null) { tooltipEl.style.display = 'none'; return; }
                var bucketSec = RANGE_SEC[selectedRange] || 14400;
                var bucketStart = Math.floor(t / bucketSec) * bucketSec;
                var sample = getSampleForBucket(t) || findNearestSample(t);
                tooltipEl.innerHTML = buildCrosshairTooltipHtml(bucketStart, sample);
                tooltipEl.style.display = 'block';
                var ox = mountEl.offsetLeft || 0;
                var oy = mountEl.offsetTop || 0;
                var x = ox + param.point.x + 12;
                var y = oy + param.point.y + 12;
                if (param.point.x + 232 > mountEl.clientWidth) x = ox + param.point.x - 220;
                if (param.point.y + 140 > mountEl.clientHeight) y = oy + param.point.y - 120;
                tooltipEl.style.left = x + 'px';
                tooltipEl.style.top = y + 'px';
            });
            if (mountEl) {
                mountEl.addEventListener('mouseleave', function() {
                    if (tooltipEl) tooltipEl.style.display = 'none';
                });
            }
        }
        renderChart();
    }

    /** LightweightCharts null/NaN kabul etmez; her value sayı olmalı. */
    function safeValue(v) {
        if (v == null || v !== v) return 0;
        var n = Number(v);
        return (typeof n === 'number' && !isNaN(n)) ? n : 0;
    }

    /**
     * Bucket başlangıç zamanı kullanılır; zaman gridleri eşit aralıklı olur (03:00, 06:00, 09:00...).
     * Her bucket için tek nokta (son değer = close), nokta zamanı = bucketStart.
     */
    function aggregateSamplesByRange(visibleSamples, fromSec, toSec, bucketSec) {
        if (!visibleSamples.length || bucketSec <= 0) return visibleSamples;
        var buckets = {};
        visibleSamples.forEach(function(s) {
            var ts = s.ts;
            if (ts == null) return;
            var bucketStart = Math.floor(ts / bucketSec) * bucketSec;
            if (bucketStart < fromSec) return;
            if (!buckets[bucketStart] || ts >= (buckets[bucketStart].ts || 0)) {
                buckets[bucketStart] = { ts: ts, botPct: s.botPct, paritePct: s.paritePct };
            }
        });
        var keys = Object.keys(buckets).map(Number).sort(function(a, b) { return a - b; });
        return keys.map(function(k) {
            var b = buckets[k];
            return { time: k, botPct: b.botPct, paritePct: b.paritePct };
        });
    }

    /** Hover zamanına ait bucket’taki (close) örneği döndürür; tooltip doğru çubukla eşleşir. */
    function getSampleForBucket(timeSec) {
        if (!samples.length) return null;
        var bucketSec = RANGE_SEC[selectedRange] || 14400;
        var bucketStart = Math.floor(timeSec / bucketSec) * bucketSec;
        var bucketEnd = bucketStart + bucketSec;
        var best = null;
        for (var i = 0; i < samples.length; i++) {
            var s = samples[i];
            if (s.ts != null && s.ts >= bucketStart && s.ts < bucketEnd) {
                if (!best || s.ts >= best.ts) best = s;
            }
        }
        return best;
    }

    function renderChart() {
        var now = nowSec();
        var rangeSec = RANGE_SEC[selectedRange] || RANGE_SEC['4h'];
        var displayWindowSec = DISPLAY_WINDOW_SEC[selectedRange] != null ? DISPLAY_WINDOW_SEC[selectedRange] : rangeSec;
        var bucketSec = rangeSec;
        var fromSec = now - Math.min(displayWindowSec, MAX_AGE_SEC);
        fromSec = Math.floor(fromSec / bucketSec) * bucketSec;
        var toSec = now;

        var visible = samples.filter(function(s) { return s.ts >= fromSec; });
        var aggregated = aggregateSamplesByRange(visible, fromSec, toSec, bucketSec);
        if (aggregated.length === 0 && visible.length > 0) {
            var m = {};
            visible.forEach(function(s) {
                var t = Math.floor((s.ts || 0) / bucketSec) * bucketSec;
                if (t >= fromSec && (!m[t] || (s.ts >= (m[t].ts || 0)))) m[t] = { time: t, botPct: s.botPct, paritePct: s.paritePct, ts: s.ts };
            });
            aggregated = Object.keys(m).map(Number).sort(function(a, b) { return a - b; }).map(function(k) { return { time: k, botPct: m[k].botPct, paritePct: m[k].paritePct }; });
        }

        var latestBotVal = null;
        var latestPariteVal = null;
        if (baseline && visible.length > 0) {
            var last = visible[visible.length - 1];
            latestBotVal = last.botPct != null && baseline.bot0 != null ? (last.botPct - baseline.bot0) : null;
            latestPariteVal = last.paritePct != null && baseline.parite0 != null ? (last.paritePct - baseline.parite0) : null;
        }

        function toPoint(s) {
            var v = baseline && s.botPct != null && baseline.bot0 != null ? (s.botPct - baseline.bot0) : 0;
            return { time: s.time != null ? s.time : s.ts, value: safeValue(v) };
        }
        function toPointParite(s) {
            var v = baseline && s.paritePct != null && baseline.parite0 != null ? (s.paritePct - baseline.parite0) : 0;
            return { time: s.time != null ? s.time : s.ts, value: safeValue(v) };
        }

        var botData = [{ time: fromSec, value: 0 }];
        var pariteData = [{ time: fromSec, value: 0 }];
        aggregated.forEach(function(s) {
            botData.push(toPoint(s));
            pariteData.push(toPointParite(s));
        });
        var lastTime = visible.length > 0 ? visible[visible.length - 1].ts : fromSec;
        var chartEndSec = Math.ceil(now / bucketSec) * bucketSec;
        var needAnchor = lastTime < chartEndSec;
        if (needAnchor) {
            var anchorBot = safeValue(latestBotVal != null ? latestBotVal : (botData.length ? botData[botData.length - 1].value : 0));
            var anchorParite = safeValue(latestPariteVal != null ? latestPariteVal : (pariteData.length ? pariteData[pariteData.length - 1].value : 0));
            botData.push({ time: chartEndSec, value: anchorBot });
            pariteData.push({ time: chartEndSec, value: anchorParite });
        }

        var botGreen = latestBotVal != null && latestPariteVal != null && latestBotVal >= latestPariteVal;
        var zeroData = [{ time: fromSec, value: 0 }, { time: chartEndSec, value: 0 }];

        if (chart && botSeries && pariteSeries) {
            botSeries.setData(botData.map(function(p) { return { time: p.time, value: safeValue(p.value) }; }));
            pariteSeries.setData(pariteData.map(function(p) { return { time: p.time, value: safeValue(p.value) }; }));
            botSeries.applyOptions({ color: botGreen ? '#0ECB81' : '#F6465D' });
            pariteSeries.applyOptions({ color: botGreen ? '#F6465D' : '#0ECB81' });
            if (zeroLineSeries) zeroLineSeries.setData(zeroData);
            if (startDotSeries) {
                startDotSeries.setData([{ time: fromSec, value: 0 }]);
                if (startDotSeries.setMarkers) startDotSeries.setMarkers([{ time: fromSec, position: 'inBar', shape: 'circle', color: '#ffffff', size: 0.5 }]);
            }
            if (chart.timeScale()) {
                var ts = chart.timeScale();
                var showSeconds = selectedRange === '1m' || selectedRange === '5m';
                ts.applyOptions({ timeVisible: true, secondsVisible: showSeconds });
                if (applyVisibleRange) {
                    ts.setVisibleRange({ from: fromSec, to: chartEndSec });
                    applyVisibleRange = false;
                }
            }
        }

        if (modalChart && modalBotSeries && modalPariteSeries) {
            modalBotSeries.setData(botData.map(function(p) { return { time: p.time, value: safeValue(p.value) }; }));
            modalPariteSeries.setData(pariteData.map(function(p) { return { time: p.time, value: safeValue(p.value) }; }));
            modalBotSeries.applyOptions({ color: botGreen ? '#0ECB81' : '#F6465D' });
            modalPariteSeries.applyOptions({ color: botGreen ? '#F6465D' : '#0ECB81' });
            if (modalZeroLineSeries) modalZeroLineSeries.setData(zeroData);
            if (modalStartDotSeries) {
                modalStartDotSeries.setData([{ time: fromSec, value: 0 }]);
                if (modalStartDotSeries.setMarkers) modalStartDotSeries.setMarkers([{ time: fromSec, position: 'inBar', shape: 'circle', color: '#ffffff', size: 0.5 }]);
            }
            if (modalChart.timeScale()) {
                var mts = modalChart.timeScale();
                var mShowSeconds = selectedRange === '1m' || selectedRange === '5m';
                mts.applyOptions({ timeVisible: true, secondsVisible: mShowSeconds });
                if (applyModalVisibleRange) {
                    mts.setVisibleRange({ from: fromSec, to: chartEndSec });
                    applyModalVisibleRange = false;
                }
            }
        }

        var botColor = botGreen ? '#0ECB81' : '#F6465D';
        var pariteColor = botGreen ? '#F6465D' : '#0ECB81';
        var legBot = document.getElementById('pctLegendBot');
        var legParite = document.getElementById('pctLegendParite');
        var botLabel = 'Bot bakiyesi %' + (latestBotVal != null ? ' ' + (latestBotVal >= 0 ? '+' : '') + latestBotVal.toFixed(2) + '%' : '');
        var pariteLabel = 'Parite %' + (latestPariteVal != null ? ' ' + (latestPariteVal >= 0 ? '+' : '') + latestPariteVal.toFixed(2) + '%' : '');
        if (legBot) { legBot.textContent = botLabel; legBot.style.color = botColor; }
        if (legParite) { legParite.textContent = pariteLabel; legParite.style.color = pariteColor; }
        var modalLegBot = document.getElementById('perfModalLegBalance');
        var modalLegParite = document.getElementById('perfModalLegPair');
        if (modalLegBot) {
            var pBot = modalLegBot.closest ? modalLegBot.closest('span') : modalLegBot.parentElement;
            if (pBot) {
                pBot.innerHTML = '<i class="leg-dot balance" id="perfModalLegBalance"></i> ' + botLabel;
                pBot.style.color = botColor;
                pBot.title = 'Bot bakiyesi % (bu renk)';
            }
            modalLegBot = document.getElementById('perfModalLegBalance');
            if (modalLegBot) modalLegBot.style.backgroundColor = botColor;
        }
        if (modalLegParite) {
            var pParite = modalLegParite.closest ? modalLegParite.closest('span') : modalLegParite.parentElement;
            if (pParite) {
                pParite.innerHTML = '<i class="leg-dot pair" id="perfModalLegPair"></i> ' + pariteLabel;
                pParite.style.color = pariteColor;
                pParite.title = 'Parite % (bu renk)';
            }
            modalLegParite = document.getElementById('perfModalLegPair');
            if (modalLegParite) modalLegParite.style.backgroundColor = pariteColor;
        }

        var parts = [];
        if (latestBotVal != null) parts.push('Bot ' + latestBotVal.toFixed(2) + '%');
        if (latestPariteVal != null) parts.push('Parite ' + latestPariteVal.toFixed(2) + '%');
        parts.push(selectedRange.toUpperCase());
        if (baseline && baseline.ts0) parts.push('Başlangıç: ' + new Date(baseline.ts0 * 1000).toLocaleString('tr-TR'));
        setStatus(parts.join(' | '));
    }

    /** Sadece aralık sonunda (bucket boundary) çağrılır; bir nokta yazar, sonraki boundary’yi zamanlar. */
    function sample() {
        var data = getDataFromDom();
        var botPct = data.botPct;
        var paritePct = data.paritePct;

        if (botPct == null || paritePct == null) {
            setStatus('Veri bekleniyor…');
            if (chart) renderChart();
            scheduleNextSample();
            return;
        }

        if (baseline == null) {
            baseline = { bot0: botPct, parite0: paritePct, ts0: nowSec() };
        }

        var bucketSec = RANGE_SEC[selectedRange] || 14400;
        var bucketEndSec = Math.floor(nowSec() / bucketSec) * bucketSec;
        samples.push({ ts: bucketEndSec, botPct: botPct, paritePct: paritePct });
        pruneSamples();
        saveCounter++;
        if (saveCounter >= SAVE_EVERY_N) { saveCounter = 0; saveStorage(); }

        createChartIfReady();
        renderChart();
        if (chart && !liveUpdateTimer) {
            liveUpdateTimer = setInterval(liveUpdateLineEnds, LIVE_UPDATE_INTERVAL_MS);
        }
    }

    /** Çizgi uçlarındaki yüzde her aralıkta canlı güncellenir (DOM’dan). */
    /** Çizgi ucu her periyotta güncellenir (fiyat değiştikçe yukarı aşağı); yazı sadece değer değişince. */
    function buildChartDataWithLive(liveNow, liveBotVal, livePariteVal) {
        var now = nowSec();
        var rangeSec = RANGE_SEC[selectedRange] || RANGE_SEC['4h'];
        var displayWindowSec = DISPLAY_WINDOW_SEC[selectedRange] != null ? DISPLAY_WINDOW_SEC[selectedRange] : rangeSec;
        var bucketSec = rangeSec;
        var fromSec = now - Math.min(displayWindowSec, MAX_AGE_SEC);
        fromSec = Math.floor(fromSec / bucketSec) * bucketSec;
        var toSec = now;
        var visible = samples.filter(function(s) { return s.ts >= fromSec; });
        var aggregated = aggregateSamplesByRange(visible, fromSec, toSec, bucketSec);
        if (aggregated.length === 0 && visible.length > 0) {
            var m = {};
            visible.forEach(function(s) {
                var t = Math.floor((s.ts || 0) / bucketSec) * bucketSec;
                if (t >= fromSec && (!m[t] || (s.ts >= (m[t].ts || 0)))) m[t] = { time: t, botPct: s.botPct, paritePct: s.paritePct, ts: s.ts };
            });
            aggregated = Object.keys(m).map(Number).sort(function(a, b) { return a - b; }).map(function(k) { return { time: k, botPct: m[k].botPct, paritePct: m[k].paritePct }; });
        }
        function toP(s) {
            var v = baseline && s.botPct != null && baseline.bot0 != null ? (s.botPct - baseline.bot0) : 0;
            return { time: s.time != null ? s.time : s.ts, value: safeValue(v) };
        }
        function toPP(s) {
            var v = baseline && s.paritePct != null && baseline.parite0 != null ? (s.paritePct - baseline.parite0) : 0;
            return { time: s.time != null ? s.time : s.ts, value: safeValue(v) };
        }
        var botData = [{ time: fromSec, value: 0 }];
        var pariteData = [{ time: fromSec, value: 0 }];
        aggregated.forEach(function(s) {
            botData.push(toP(s));
            pariteData.push(toPP(s));
        });
        var chartEndSec = Math.ceil((liveNow != null ? liveNow : now) / bucketSec) * bucketSec;
        var endBot = liveBotVal != null ? safeValue(liveBotVal) : (botData.length ? botData[botData.length - 1].value : 0);
        var endParite = livePariteVal != null ? safeValue(livePariteVal) : (pariteData.length ? pariteData[pariteData.length - 1].value : 0);
        botData.push({ time: chartEndSec, value: endBot });
        pariteData.push({ time: chartEndSec, value: endParite });
        return { botData: botData, pariteData: pariteData };
    }

    function liveUpdateLineEnds() {
        if (!chart || !botSeries || !pariteSeries) return;
        var data = getDataFromDom();
        var botPct = data.botPct;
        var paritePct = data.paritePct;
        if (botPct == null || paritePct == null) return;
        if (baseline == null) {
            baseline = { bot0: botPct, parite0: paritePct, ts0: nowSec() };
        }
        var botVal = baseline.bot0 != null ? (botPct - baseline.bot0) : 0;
        var pariteVal = baseline.parite0 != null ? (paritePct - baseline.parite0) : 0;
        var now = nowSec();
        var built = buildChartDataWithLive(now, botVal, pariteVal);
        botSeries.setData(built.botData.map(function(p) { return { time: p.time, value: safeValue(p.value) }; }));
        pariteSeries.setData(built.pariteData.map(function(p) { return { time: p.time, value: safeValue(p.value) }; }));
        var botGreen = botVal >= pariteVal;
        botSeries.applyOptions({ color: botGreen ? '#0ECB81' : '#F6465D' });
        pariteSeries.applyOptions({ color: botGreen ? '#F6465D' : '#0ECB81' });
        if (modalChart && modalBotSeries && modalPariteSeries) {
            modalBotSeries.setData(built.botData.map(function(p) { return { time: p.time, value: safeValue(p.value) }; }));
            modalPariteSeries.setData(built.pariteData.map(function(p) { return { time: p.time, value: safeValue(p.value) }; }));
            modalBotSeries.applyOptions({ color: botGreen ? '#0ECB81' : '#F6465D' });
            modalPariteSeries.applyOptions({ color: botGreen ? '#F6465D' : '#0ECB81' });
        }
        var roundedBot = Math.round(botVal * 100) / 100;
        var roundedParite = Math.round(pariteVal * 100) / 100;
        if (lastLiveBotVal !== roundedBot || lastLivePariteVal !== roundedParite) {
            lastLiveBotVal = roundedBot;
            lastLivePariteVal = roundedParite;
            var legBot = document.getElementById('pctLegendBot');
            var legParite = document.getElementById('pctLegendParite');
            var botGreen = botVal >= pariteVal;
            var botColor = botGreen ? '#0ECB81' : '#F6465D';
            var pariteColor = botGreen ? '#F6465D' : '#0ECB81';
            var liveBotLabel = 'Bot bakiyesi % ' + (botVal >= 0 ? '+' : '') + botVal.toFixed(2) + '%';
            var livePariteLabel = 'Parite % ' + (pariteVal >= 0 ? '+' : '') + pariteVal.toFixed(2) + '%';
            if (legBot) { legBot.textContent = liveBotLabel; legBot.style.color = botColor; }
            if (legParite) { legParite.textContent = livePariteLabel; legParite.style.color = pariteColor; }
            var modalLegBot = document.getElementById('perfModalLegBalance');
            var modalLegParite = document.getElementById('perfModalLegPair');
            if (modalLegBot) {
                var pBot = modalLegBot.closest ? modalLegBot.closest('span') : modalLegBot.parentElement;
                if (pBot) { pBot.innerHTML = '<i class="leg-dot balance" id="perfModalLegBalance"></i> ' + liveBotLabel; pBot.style.color = botColor; }
                modalLegBot = document.getElementById('perfModalLegBalance');
                if (modalLegBot) modalLegBot.style.backgroundColor = botColor;
            }
            if (modalLegParite) {
                var pParite = modalLegParite.closest ? modalLegParite.closest('span') : modalLegParite.parentElement;
                if (pParite) { pParite.innerHTML = '<i class="leg-dot pair" id="perfModalLegPair"></i> ' + livePariteLabel; pParite.style.color = pariteColor; }
                modalLegParite = document.getElementById('perfModalLegPair');
                if (modalLegParite) modalLegParite.style.backgroundColor = pariteColor;
            }
            var parts = [];
            parts.push('Bot ' + (botVal >= 0 ? '+' : '') + botVal.toFixed(2) + '%');
            parts.push('Parite ' + (pariteVal >= 0 ? '+' : '') + pariteVal.toFixed(2) + '%');
            parts.push(selectedRange.toUpperCase());
            if (baseline.ts0) parts.push('Başlangıç: ' + new Date(baseline.ts0 * 1000).toLocaleString('tr-TR'));
            setStatus(parts.join(' | '));
        }
    }

    function startSampling() {
        if (sampleTimer) return;
        scheduleNextSample();
        if (!liveUpdateTimer && chart) {
            liveUpdateTimer = setInterval(liveUpdateLineEnds, LIVE_UPDATE_INTERVAL_MS);
        }
    }

    function stopSampling() {
        if (sampleTimer) { clearTimeout(sampleTimer); sampleTimer = null; }
        if (liveUpdateTimer) { clearInterval(liveUpdateTimer); liveUpdateTimer = null; }
        lastLiveBotVal = null;
        lastLivePariteVal = null;
    }

    function bindButtons() {
        if (!wrapEl) return;
        wrapEl.querySelectorAll('.pct-btn[data-range]').forEach(function(btn) {
            btn.addEventListener('click', function(e) {
                e.stopPropagation();
                var range = btn.getAttribute('data-range') || '4h';
                selectedRange = range;
                wrapEl.querySelectorAll('.pct-btn[data-range]').forEach(function(b) { b.classList.remove('pct-active'); });
                btn.classList.add('pct-active');
                saveStorage();
                applyVisibleRange = true;
                stopSampling();
                loadPerfFromApi(range, { disableRangeButtons: true }).then(function() {
                    startSampling();
                }).catch(function() {
                    if (chart) renderChart();
                }).finally(function() {
                    if (wrapEl) wrapEl.querySelectorAll('.pct-btn[data-range]').forEach(function(b) { b.disabled = false; });
                });
            });
        });
    }

    function createModalChart() {
        var modalMount = document.getElementById('perfChartModalSvgWrap');
        if (!modalMount || !window.LightweightCharts || modalChart) return;
        var w = Math.max(400, modalMount.clientWidth || 400);
        var h = Math.max(300, modalMount.clientHeight || 360);
        var L = window.LightweightCharts;
        modalChart = L.createChart(modalMount, {
            width: w,
            height: h,
            layout: { background: { type: 'solid', color: '#0b0f14' }, textColor: '#9aa4b2' },
            grid: {
                vertLines: { visible: true, color: 'rgba(255,255,255,0.06)' },
                horzLines: { visible: true, color: 'rgba(255,255,255,0.06)' }
            },
            rightPriceScale: {
                visible: true,
                borderVisible: false,
                scaleMargins: { top: 0.1, bottom: 0.1 },
                autoScale: true
            },
            timeScale: { timeVisible: true, secondsVisible: false, borderVisible: false },
            crosshair: { mode: L.CrosshairMode.Normal }
        });
        modalZeroLineSeries = modalChart.addLineSeries({ lineWidth: 1, color: 'rgba(255,255,255,0.22)', lineStyle: 2, priceLineVisible: false, lastValueVisible: false, priceFormat: { type: 'price', precision: 2, minMove: 0.01 } });
        modalStartDotSeries = modalChart.addLineSeries({ lineWidth: 0, color: 'transparent', priceLineVisible: false, lastValueVisible: false, priceFormat: { type: 'price', precision: 2, minMove: 0.01 } });
        modalBotSeries = modalChart.addLineSeries({ lineWidth: 1, priceLineVisible: false, lastValueVisible: true, priceFormat: { type: 'price', precision: 2, minMove: 0.01 } });
        modalPariteSeries = modalChart.addLineSeries({ lineWidth: 1, priceLineVisible: false, lastValueVisible: true, priceFormat: { type: 'price', precision: 2, minMove: 0.01 } });
        applyModalVisibleRange = true;
        var modalTooltip = document.getElementById('pctModalCrosshairTooltip');
        if (!modalTooltip && modalMount && modalMount.parentElement) {
            modalTooltip = document.createElement('div');
            modalTooltip.id = 'pctModalCrosshairTooltip';
            modalTooltip.className = 'pct-crosshair-tooltip';
            modalMount.parentElement.appendChild(modalTooltip);
        }
        if (modalChart && modalTooltip) {
            modalChart.subscribeCrosshairMove(function(param) {
                if (param.point.x < 0 || param.point.y < 0) {
                    modalTooltip.style.display = 'none';
                    return;
                }
                var t = null;
                var mTsApi = modalChart && modalChart.timeScale ? modalChart.timeScale() : null;
                if (mTsApi && typeof mTsApi.coordinateToTime === 'function') {
                    var mCoordTime = mTsApi.coordinateToTime(param.point.x);
                    t = typeof mCoordTime === 'number' ? mCoordTime : (mCoordTime && typeof mCoordTime === 'object' && mCoordTime.timestamp != null ? mCoordTime.timestamp : null);
                }
                if (t == null) {
                    t = typeof param.time === 'number' ? param.time : (param.time && typeof param.time === 'object' && param.time.timestamp != null ? param.time.timestamp : null);
                }
                if (t == null) { modalTooltip.style.display = 'none'; return; }
                var bucketSec = RANGE_SEC[selectedRange] || 14400;
                var bucketStart = Math.floor(t / bucketSec) * bucketSec;
                var sample = getSampleForBucket(t) || findNearestSample(t);
                modalTooltip.innerHTML = buildCrosshairTooltipHtml(bucketStart, sample);
                modalTooltip.style.display = 'block';
                var rect = modalMount.getBoundingClientRect();
                var x = param.point.x + 12;
                var y = param.point.y + 12;
                if (x + 220 > rect.width) x = param.point.x - 220;
                if (y + 140 > rect.height) y = param.point.y - 120;
                modalTooltip.style.left = (modalMount.offsetLeft || 0) + x + 'px';
                modalTooltip.style.top = (modalMount.offsetTop || 0) + y + 'px';
            });
            modalMount.addEventListener('mouseleave', function() {
                if (modalTooltip) modalTooltip.style.display = 'none';
            });
        }
        renderChart();
        var ro = new ResizeObserver(function() {
            if (!modalChart || !modalMount) return;
            var r = modalMount.getBoundingClientRect();
            modalChart.applyOptions({ width: Math.max(200, r.width), height: Math.max(200, r.height) });
        });
        ro.observe(modalMount);
        modalMount._modalResizeObserver = ro;
    }

    function destroyModalChart() {
        var modalMount = document.getElementById('perfChartModalSvgWrap');
        if (modalMount && modalMount._modalResizeObserver) {
            modalMount._modalResizeObserver.disconnect();
            modalMount._modalResizeObserver = null;
        }
        if (modalChart) {
            modalChart.remove();
            modalChart = null;
            modalBotSeries = null;
            modalPariteSeries = null;
            modalZeroLineSeries = null;
            modalStartDotSeries = null;
        }
        if (modalMount) modalMount.innerHTML = '';
        var modalTooltip = document.getElementById('pctModalCrosshairTooltip');
        if (modalTooltip) modalTooltip.style.display = 'none';
    }

    function openModal() {
        var overlay = document.getElementById('perfChartModalOverlay');
        if (!overlay) return;
        overlay.classList.add('is-open');
        createModalChart();
        var modalBtns = overlay.querySelectorAll('.perf-chart-range-btns-modal .perf-chart-range-btn');
        modalBtns.forEach(function(btn) {
            var r = btn.getAttribute('data-range');
            btn.classList.toggle('active', r === selectedRange);
            btn.onclick = function(e) {
                e.stopPropagation();
                if (RANGE_SEC[r] == null) return;
                selectedRange = r;
                saveStorage();
                applyVisibleRange = true;
                applyModalVisibleRange = true;
                modalBtns.forEach(function(b) { b.classList.toggle('active', b.getAttribute('data-range') === r); });
                if (wrapEl) wrapEl.querySelectorAll('.pct-btn[data-range]').forEach(function(b) { b.classList.toggle('pct-active', b.getAttribute('data-range') === r); });
                stopSampling();
                startSampling();
                renderChart();
            };
        });
    }

    function closeModal() {
        var overlay = document.getElementById('perfChartModalOverlay');
        if (overlay) overlay.classList.remove('is-open');
        destroyModalChart();
    }

    function _initOnce() {
        if (inited) return;
        inited = true;
        wrapEl = document.getElementById('perfChartWrap');
        if (!wrapEl) return;

        if (typeof window.LightweightCharts === 'undefined') {
            wrapEl.innerHTML = '<div class="pct-fatal">Chart lib missing: LightweightCharts</div>';
            return;
        }

        wrapEl.title = '';
        wrapEl.innerHTML = ''
            + '<div class="pct-chart-header">'
            + '<div class="pct-title">PARİTE ve BOT PERFORMANS GRAFİĞİ</div>'
            + '<div class="pct-controls">'
            + '<button type="button" data-range="1m" class="pct-btn">1m</button>'
            + '<button type="button" data-range="5m" class="pct-btn">5m</button>'
            + '<button type="button" data-range="1h" class="pct-btn">1h</button>'
            + '<button type="button" data-range="4h" class="pct-btn pct-active">4h</button>'
            + '<button type="button" data-range="1d" class="pct-btn">1d</button>'
            + '</div>'
            + '</div>'
            + '<div id="pctChartMount" style="width:100%; height:' + CHART_HEIGHT + 'px;"></div>'
            + '<div class="pct-legend">'
            + '<span id="pctLegendBot">Bot %</span>'
            + '<span id="pctLegendParite">Parite %</span>'
            + '<span id="pctStatus" class="pct-status"></span>'
            + '</div>';

        mountEl = document.getElementById('pctChartMount');
        statusEl = document.getElementById('pctStatus');
        if (!mountEl) return;

        bindButtons();
        wrapEl.querySelectorAll('.pct-btn[data-range]').forEach(function(b) {
            b.classList.toggle('pct-active', b.getAttribute('data-range') === selectedRange);
        });
        wrapEl.addEventListener('click', function(e) {
            if (e.target.closest && e.target.closest('.pct-controls')) return;
            if (e.target.closest && e.target.closest('.pct-btn')) return;
            openModal();
        });
        requestAnimationFrame(function() {
            createChartIfReady();
            startSampling();
        });
        if (!window._perfChartVisibilityBound) {
            window._perfChartVisibilityBound = true;
            window.addEventListener('visibilitychange', function() {
                if (!document.hidden && inited && currentBotId) mergeChartStateFromServer();
            });
        }
    }

    function readyCheck() {
        var wrap = document.getElementById('perfChartWrap');
        if (!wrap) return false;
        var rect = wrap.getBoundingClientRect();
        if ((rect.width || 0) < MOUNT_MIN_WIDTH) return false;
        var botSpan = document.getElementById('perfReportBakiyeDegisim');
        var pariteSpan = document.getElementById('perfReportPariteDegisim');
        return !!(botSpan && pariteSpan);
    }

    function init(botIdParam, accountIdParam, accountCodeParam) {
        var botId = botIdParam != null && botIdParam !== '' ? String(botIdParam) : '';
        if (botId === '' && typeof window.location !== 'undefined' && window.location.search) {
            var m = window.location.search.match(/[?&]bot_id=(\d+)/);
            if (m) botId = m[1];
        }
        currentAccountId = accountIdParam != null && accountIdParam !== '' ? String(accountIdParam) : null;
        currentAccountCode = accountCodeParam != null && accountCodeParam !== '' ? String(accountCodeParam) : null;
        if (inited && currentBotId !== botId) {
            stop();
            inited = false;
            baseline = null;
            samples = [];
            saveCounter = 0;
            applyVisibleRange = true;
            wrapEl = null;
            mountEl = null;
            statusEl = null;
        }
        currentBotId = botId;
        if (inited) return;
        if (readyTimer) return;
        function tryInit() {
            if (!readyCheck()) return;
            clearInterval(readyTimer);
            readyTimer = null;
            loadChartStateFromServer(function() {
                _initOnce();
            });
        }
        readyTimer = setInterval(tryInit, READY_POLL_MS);
        tryInit();
    }

    function stop() {
        stopSampling();
        if (activeAbortController) {
            activeAbortController.abort();
            activeAbortController = null;
        }
        if (readyTimer) { clearInterval(readyTimer); readyTimer = null; }
        if (resizeObserver && mountEl) { resizeObserver.disconnect(); resizeObserver = null; }
        if (chart && mountEl) { chart.remove(); chart = null; botSeries = null; pariteSeries = null; zeroLineSeries = null; startDotSeries = null; }
        if (modalChart) {
            modalChart.remove();
            modalChart = null;
            modalBotSeries = null;
            modalPariteSeries = null;
            modalZeroLineSeries = null;
            modalStartDotSeries = null;
        }
    }

    function updatePerfChart(series, meta) {
        applySeriesFromApi(series || [], meta || {}, selectedRange);
    }

    function setRange(range) {
        if (RANGE_SEC[range] == null) return;
        selectedRange = range;
        saveStorage();
        applyVisibleRange = true;
        if (wrapEl) {
            wrapEl.querySelectorAll('.pct-btn[data-range]').forEach(function(b) {
                b.classList.toggle('pct-active', b.getAttribute('data-range') === range);
            });
        }
        stopSampling();
        startSampling();
        renderChart();
    }

    function reset() {
        try { localStorage.removeItem(getStorageKey()); } catch (e) {}
        baseline = null;
        samples = [];
        saveCounter = 0;
        if (currentBotId && window.apiClient) {
            var q = buildAccountQuery();
            window.apiClient.delete('/api/bots-engine/' + currentBotId + '/perf-chart-state' + q).catch(function() {});
        }
        setStatus('Sıfırlandı.');
        renderChart();
    }

    /** Sunucudan grafik state alıp uygula (bot başlatıldıktan sonra backend seed + samples). */
    function refreshFromServer(botId, accountIdParam, accountCodeParam) {
        var id = botId != null && botId !== '' ? String(botId) : '';
        if (!id || id !== currentBotId || !window.apiClient) return;
        var q = (accountIdParam != null && accountIdParam !== '') ? ('?account_id=' + encodeURIComponent(accountIdParam)) : ((accountCodeParam != null && accountCodeParam !== '') ? ('?account_code=' + encodeURIComponent(accountCodeParam)) : buildAccountQuery());
        window.apiClient.get('/api/bots-engine/' + currentBotId + '/perf-chart-state' + q)
            .then(function(res) {
                if (!res) return;
                if (res.baseline != null) baseline = res.baseline;
                if (Array.isArray(res.samples)) samples = res.samples.slice();
                if (res.range && RANGE_SEC[res.range]) selectedRange = res.range;
                pruneSamples();
                try { localStorage.setItem(getStorageKey(), JSON.stringify({ baseline: baseline, samples: samples, range: selectedRange })); } catch (e) {}
                if (wrapEl) wrapEl.querySelectorAll('.pct-btn[data-range]').forEach(function(b) {
                    b.classList.toggle('pct-active', b.getAttribute('data-range') === selectedRange);
                });
                renderChart();
            })
            .catch(function() {});
    }

    /** O bota ait grafik geçmişini siler; grafik o bot başladığında sıfırdan başlar. */
    function clearForBot(botId, accountIdParam, accountCodeParam) {
        var id = botId != null && botId !== '' ? String(botId) : '';
        if (!id) return;
        var key = STORAGE_KEY_PREFIX + '_b' + id;
        try { localStorage.removeItem(key); } catch (e) {}
        if (window.apiClient) {
            var q = (accountIdParam != null && accountIdParam !== '') ? ('?account_id=' + encodeURIComponent(accountIdParam)) : ((accountCodeParam != null && accountCodeParam !== '') ? ('?account_code=' + encodeURIComponent(accountCodeParam)) : buildAccountQuery());
            window.apiClient.delete('/api/bots-engine/' + id + '/perf-chart-state' + q).catch(function() {});
        }
        if (currentBotId === id) {
            baseline = null;
            samples = [];
            saveCounter = 0;
            if (chart && botSeries && pariteSeries) {
                var now = nowSec();
                var r = RANGE_SEC[selectedRange] || 14400;
                botSeries.setData([{ time: now - r, value: 0 }, { time: now, value: 0 }]);
                pariteSeries.setData([{ time: now - r, value: 0 }, { time: now, value: 0 }]);
            }
            setStatus('Grafik bot başlangıcından itibaren sıfırlandı.');
        }
    }

    window.PerfChartTV = {
        init: init,
        initPerfChart: init,
        updatePerfChart: updatePerfChart,
        destroyPerfChart: stop,
        start: startSampling,
        stop: stop,
        setRange: setRange,
        reset: reset,
        clearForBot: clearForBot,
        refreshFromServer: refreshFromServer,
        openModal: openModal,
        closeModal: closeModal
    };

    /* Grafik sadece showDetail içinde doğru botId ile init edilir; DOMContentLoaded'da otomatik init yok. */

    /*
     * Manual test steps:
     * 1. Open bot detail -> Performans tab -> chart shows (title, 1H/4H/1D/1W, Sıfırla, mount, legend).
     * 2. Wait ~10s -> two lines from 0 (TradingView style).
     * 3. Refresh -> history remains (backend single source).
     * 4. Switch 1H/4H/1D/1W -> visible window changes; 1D shows full 24h span (no 10s collapse).
     * 5. Sıfırla -> confirm -> baseline resets, chart clears to anchors, next sample sets new baseline.
     */
})();
