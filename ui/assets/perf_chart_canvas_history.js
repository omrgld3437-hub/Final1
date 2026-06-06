/**
 * Perf chart: pure Canvas + localStorage. No external libs.
 * Data from #perfReportBakiyeDegisim and #perfReportPariteDegisim.
 * window.PerfChart = { init, start, stop, setRange, clearHistory }
 */
(function() {
    'use strict';

    var STORAGE_KEY = 'perf_chart_samples_v1';
    var SAMPLE_INTERVAL_MS = 2000;
    var SAVE_EVERY_N_SAMPLES = 5;
    var MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000; // 7 days
    var MAX_SAMPLES = 30000;
    var READY_POLL_MS = 300;
    var CHART_HEIGHT = 260;

    var RANGE_MS = {
        '1h': 3600000,
        '4h': 14400000,
        '1d': 86400000,
        '1w': 604800000
    };

    var inited = false;
    var readyCheckTimer = null;
    var sampleTimer = null;
    var wrapEl = null;
    var canvasEl = null;
    var statusEl = null;
    var selectedRange = '4h';

    var baseline = null; // { bot0, parite0, ts0 }
    var samples = [];     // { ts, botPct, paritePct }
    var saveCounter = 0;

    function parseTrailingPercent(text) {
        if (text == null || typeof text !== 'string') return null;
        var s = text.trim();
        // Find last number before % (allow comma as decimal)
        var match = s.match(/(-?\d+[.,]?\d*)\s*%\s*$/);
        if (!match) return null;
        var numStr = match[1].replace(',', '.');
        var n = parseFloat(numStr);
        return isNaN(n) ? null : n;
    }

    function getDataFromDom() {
        var botSpan = document.getElementById('perfReportBakiyeDegisim');
        var pariteSpan = document.getElementById('perfReportPariteDegisim');
        var botPct = botSpan ? parseTrailingPercent(botSpan.textContent) : null;
        var paritePct = pariteSpan ? parseTrailingPercent(pariteSpan.textContent) : null;
        return { botPct: botPct, paritePct: paritePct };
    }

    function loadFromStorage() {
        try {
            var raw = localStorage.getItem(STORAGE_KEY);
            if (!raw) return;
            var data = JSON.parse(raw);
            if (data.baseline) baseline = data.baseline;
            if (Array.isArray(data.samples)) samples = data.samples;
        } catch (e) {}
    }

    function pruneSamples() {
        var now = Date.now();
        var cut = now - MAX_AGE_MS;
        samples = samples.filter(function(s) { return s.ts >= cut; });
        if (samples.length > MAX_SAMPLES) {
            samples = samples.slice(-MAX_SAMPLES);
        }
    }

    function saveToStorage() {
        try {
            var payload = {
                baseline: baseline,
                samples: samples,
                lastSavedTs: Date.now()
            };
            localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
        } catch (e) {}
    }

    function setStatus(msg) {
        if (statusEl) statusEl.textContent = msg || '';
    }

    function drawGrid(ctx, w, h, midY) {
        ctx.strokeStyle = 'rgba(255,255,255,0.06)';
        ctx.lineWidth = 1;
        for (var i = 1; i <= 4; i++) {
            var y = midY - (h * 0.45 * i / 4);
            if (y >= 0 && y <= h) {
                ctx.beginPath();
                ctx.moveTo(0, y);
                ctx.lineTo(w, y);
                ctx.stroke();
            }
            y = midY + (h * 0.45 * i / 4);
            if (y >= 0 && y <= h) {
                ctx.beginPath();
                ctx.moveTo(0, y);
                ctx.lineTo(w, y);
                ctx.stroke();
            }
        }
    }

    function render() {
        if (!canvasEl || !wrapEl) return;
        var ctx = canvasEl.getContext('2d');
        if (!ctx) return;

        var dpr = window.devicePixelRatio || 1;
        var rect = canvasEl.getBoundingClientRect();
        var w = Math.max(100, (rect.width || 900) * dpr);
        var h = Math.max(100, CHART_HEIGHT * dpr);
        if (canvasEl.width !== w || canvasEl.height !== h) {
            canvasEl.width = w;
            canvasEl.height = h;
            canvasEl.style.width = (rect.width || 900) + 'px';
            canvasEl.style.height = CHART_HEIGHT + 'px';
        }
        var cw = canvasEl.width;
        var ch = canvasEl.height;
        var midY = ch / 2;

        ctx.fillStyle = '#1e2329';
        ctx.fillRect(0, 0, cw, ch);

        var now = Date.now();
        var rangeMs = RANGE_MS[selectedRange] || RANGE_MS['4h'];
        var from = now - rangeMs;

        var visible = samples.filter(function(s) { return s.ts >= from; });
        if (visible.length === 0) {
            visible = samples.slice();
        }

        var latestBotVal = null;
        var latestPariteVal = null;
        if (baseline && visible.length > 0) {
            var last = visible[visible.length - 1];
            latestBotVal = last.botPct - baseline.bot0;
            latestPariteVal = last.paritePct - baseline.parite0;
        }

        var maxAbs = 1;
        for (var i = 0; i < visible.length; i++) {
            var b = baseline ? (visible[i].botPct - baseline.bot0) : 0;
            var p = baseline ? (visible[i].paritePct - baseline.parite0) : 0;
            var m = Math.max(Math.abs(b), Math.abs(p));
            if (m > maxAbs) maxAbs = m;
        }
        maxAbs *= 1.2;
        if (maxAbs < 1e-6) maxAbs = 1;

        var toTs = Math.max(now, visible.length ? visible[visible.length - 1].ts : from);
        var rangeTs = toTs - from;
        if (rangeTs < 1) rangeTs = 1;

        drawGrid(ctx, cw, ch, midY);

        var botGreen = true;
        if (latestBotVal != null && latestPariteVal != null) {
            botGreen = latestBotVal >= latestPariteVal;
        }
        var botColor = botGreen ? '#0ecb81' : '#f6465d';
        var pariteColor = botGreen ? '#f6465d' : '#0ecb81';

        function xFor(ts) {
            return ((ts - from) / rangeTs) * cw;
        }
        function yFor(val) {
            return midY - (val / maxAbs) * (ch * 0.45);
        }

        if (visible.length >= 1 && baseline) {
            ctx.lineWidth = 2;
            ctx.lineJoin = 'round';
            ctx.lineCap = 'round';

            ctx.strokeStyle = botColor;
            ctx.beginPath();
            for (var j = 0; j < visible.length; j++) {
                var v = visible[j];
                var bx = xFor(v.ts);
                var by = yFor(v.botPct - baseline.bot0);
                if (j === 0) ctx.moveTo(bx, by);
                else ctx.lineTo(bx, by);
            }
            ctx.stroke();

            ctx.strokeStyle = pariteColor;
            ctx.beginPath();
            for (var k = 0; k < visible.length; k++) {
                var v2 = visible[k];
                var px = xFor(v2.ts);
                var py = yFor(v2.paritePct - baseline.parite0);
                if (k === 0) ctx.moveTo(px, py);
                else ctx.lineTo(px, py);
            }
            ctx.stroke();
        }

        var statusParts = [];
        if (latestBotVal != null) statusParts.push('Bot ' + latestBotVal.toFixed(2) + '%');
        if (latestPariteVal != null) statusParts.push('Parite ' + latestPariteVal.toFixed(2) + '%');
        statusParts.push('Aralık: ' + selectedRange.toUpperCase());
        if (baseline && baseline.ts0) {
            var d = new Date(baseline.ts0);
            statusParts.push('Başlangıç: ' + d.toLocaleString('tr-TR'));
        }
        setStatus(statusParts.join(' | '));
    }

    function sample() {
        var data = getDataFromDom();
        var botPct = data.botPct;
        var paritePct = data.paritePct;

        if (botPct == null || paritePct == null) {
            setStatus('Veri bekleniyor…');
            render();
            return;
        }

        if (baseline == null) {
            baseline = { bot0: botPct, parite0: paritePct, ts0: Date.now() };
        }

        samples.push({ ts: Date.now(), botPct: botPct, paritePct: paritePct });
        pruneSamples();
        saveCounter++;
        if (saveCounter >= SAVE_EVERY_N_SAMPLES) {
            saveCounter = 0;
            saveToStorage();
        }
        render();
    }

    function startSampling() {
        if (sampleTimer) return;
        sampleTimer = setInterval(sample, SAMPLE_INTERVAL_MS);
        sample();
    }

    function stopSampling() {
        if (sampleTimer) {
            clearInterval(sampleTimer);
            sampleTimer = null;
        }
    }

    function bindButtons() {
        if (!wrapEl) return;
        wrapEl.querySelectorAll('.pc-btn[data-range]').forEach(function(btn) {
            btn.addEventListener('click', function() {
                selectedRange = btn.getAttribute('data-range') || '4h';
                wrapEl.querySelectorAll('.pc-btn[data-range]').forEach(function(b) { b.classList.remove('pc-active'); });
                btn.classList.add('pc-active');
                render();
            });
        });
        var clearBtn = wrapEl.querySelector('.pc-btn[data-action="clear"]');
        if (clearBtn) {
            clearBtn.addEventListener('click', function() {
                if (!confirm('Grafik geçmişi silinsin mi? Başlangıç sıfırlanacak.')) return;
                try { localStorage.removeItem(STORAGE_KEY); } catch (e) {}
                baseline = null;
                samples = [];
                saveCounter = 0;
                setStatus('Sıfırlandı. Yeni veri gelince başlangıç alınacak.');
                render();
                startSampling();
            });
        }
    }

    function resizeAndRender() {
        if (canvasEl && wrapEl) {
            var rect = wrapEl.getBoundingClientRect();
            var w = rect.width || 900;
            canvasEl.style.width = w + 'px';
            canvasEl.style.height = CHART_HEIGHT + 'px';
            render();
        }
    }

    function _initOnce() {
        if (inited) return;
        inited = true;
        wrapEl = document.getElementById('perfChartWrap');
        if (!wrapEl) return;

        wrapEl.title = '';
        wrapEl.innerHTML = ''
            + '<div class="perf-chart-head">'
            + '<div class="perf-chart-title">PARİTE % & BOT BAKİYESİ % (BAŞLANGIÇTAN İTİBAREN)</div>'
            + '<div class="perf-chart-controls">'
            + '<button type="button" data-range="1h" class="pc-btn">1H</button>'
            + '<button type="button" data-range="4h" class="pc-btn pc-active">4H</button>'
            + '<button type="button" data-range="1d" class="pc-btn">1D</button>'
            + '<button type="button" data-range="1w" class="pc-btn">1W</button>'
            + '<button type="button" data-action="clear" class="pc-btn pc-danger">Sıfırla</button>'
            + '</div>'
            + '</div>'
            + '<canvas id="perfChartCanvas" width="900" height="' + CHART_HEIGHT + '"></canvas>'
            + '<div class="perf-chart-legend">'
            + '<span class="pc-legend-bot">Bot %</span>'
            + '<span class="pc-legend-parite">Parite %</span>'
            + '<span id="perfChartStatus" class="pc-status"></span>'
            + '</div>';

        canvasEl = document.getElementById('perfChartCanvas');
        statusEl = document.getElementById('perfChartStatus');
        if (!canvasEl) return;

        loadFromStorage();
        bindButtons();
        window.addEventListener('resize', resizeAndRender);
        render();
        startSampling();
    }

    function readyCheck() {
        var wrap = document.getElementById('perfChartWrap');
        if (!wrap) return false;
        var rect = wrap.getBoundingClientRect();
        if ((rect.width || 0) <= 100) return false;
        var botSpan = document.getElementById('perfReportBakiyeDegisim');
        var pariteSpan = document.getElementById('perfReportPariteDegisim');
        return !!(botSpan && pariteSpan);
    }

    function init() {
        if (inited) return;
        if (readyCheckTimer) return;
        readyCheckTimer = setInterval(function() {
            if (!readyCheck()) return;
            clearInterval(readyCheckTimer);
            readyCheckTimer = null;
            _initOnce();
        }, READY_POLL_MS);
        if (readyCheck()) {
            clearInterval(readyCheckTimer);
            readyCheckTimer = null;
            _initOnce();
        }
    }

    function stop() {
        stopSampling();
        if (readyCheckTimer) {
            clearInterval(readyCheckTimer);
            readyCheckTimer = null;
        }
    }

    function setRange(range) {
        if (RANGE_MS[range] != null) {
            selectedRange = range;
            if (wrapEl) {
                wrapEl.querySelectorAll('.pc-btn[data-range]').forEach(function(b) {
                    b.classList.toggle('pc-active', b.getAttribute('data-range') === range);
                });
            }
            render();
        }
    }

    function clearHistory() {
        try { localStorage.removeItem(STORAGE_KEY); } catch (e) {}
        baseline = null;
        samples = [];
        saveCounter = 0;
        setStatus('Geçmiş silindi.');
        if (statusEl) statusEl.textContent = 'Geçmiş silindi.';
        render();
    }

    window.PerfChart = {
        init: init,
        start: startSampling,
        stop: stop,
        setRange: setRange,
        clearHistory: clearHistory
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() {
            if (document.getElementById('perfChartWrap')) window.PerfChart.init();
        });
    } else {
        if (document.getElementById('perfChartWrap')) window.PerfChart.init();
    }

    /*
     * Manual test steps:
     * 1. Open bot detail page, go to Performans tab -> chart area should render (title, 1H/4H/1D/1W, Sıfırla, canvas, legend).
     * 2. If spans have data: status shows "Bot X% | Parite Y% | Aralık: 4H | Başlangıç: ...". Wait ~10s: two lines draw from 0.
     * 3. Refresh page, open Performans again -> history still visible (localStorage).
     * 4. Switch 1H / 4H / 1D / 1W -> window changes (last X of data).
     * 5. Click Sıfırla -> confirm -> chart clears, next sample sets new baseline, lines restart from 0.
     */
})();
