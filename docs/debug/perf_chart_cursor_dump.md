# Performance chart debug dump — evidence for deterministic fix

**Purpose:** Investigate why the live line chart inside `#perfChartWrap` never appears / never updates. Values should come only from `#perfReportBakiyeDegisim` and `#perfReportPariteDegisim`. No fixes in this document — evidence only.

---

## 0) Summary

### What currently happens

- **On page load:** Bot detail page loads; `perfPanel` has `style="display: none"`. `#perfChartWrap` exists in DOM with initial content: title + `#perfChartSvgWrap` (placeholder text) + legend. `#perfReportBakiyeDegisim` and `#perfReportPariteDegisim` do **not** exist until `perfReport.innerHTML` is set (inside `renderBotDetail` when bot data is loaded and Performans tab content is rendered).
- **When user opens Performans tab / bot data loads:** `renderBotDetail` (or equivalent) runs: sets `perfReport.innerHTML` (creating the two spans), then calls `window.PerfChartRebuild.init()` (if defined), then sets `perfPanel.style.display = 'block'`. So **init runs while `perfPanel` may still be `display: none`** (block is set immediately after init). If `window.LightweightCharts` is undefined, `perf_chart_rebuild.js` returns early and **never defines `PerfChartRebuild`**; then `init` is never called, and the fallback click handler (`openPerfChartModal`) is bound instead.
- **When user clicks `#perfChartWrap`:** If `PerfChartRebuild.init` was run: `openModal()` runs (modal opens; modal chart built on first open). If `PerfChartRebuild` was never defined: `openPerfChartModal()` runs (legacy path using `window._lastPerfChartSeries` / `buildPerfChartSvg` — not the DOM spans; modal may open empty).

### What is expected vs actual

- **Expected:** A live line chart is rendered **inside** `#perfChartWrap` (inline mini chart), two lines from a single starting point, values read only from `#perfReportBakiyeDegisim` and `#perfReportPariteDegisim` (e.g. parse trailing `-0.25%` and `-0.47%`), and the chart updates continuously (e.g. every 5 s).
- **Actual:** The chart never appears in `#perfChartWrap`; the user sees the placeholder ("Parite % & Bot bakiyesi % ... Grafiği aç") or the same content after init replaces innerHTML with title + `#perfChartWrapMount` — but the mount may have 0 size or the chart is never drawn (e.g. script early return, or `buildMiniChart` runs when container has 0 width).

---

## 1) DOM anchors (confirm at runtime)

Run in browser console **after** opening a bot detail page and **after** the Performans panel is visible (bot data loaded, `perfPanel.style.display = 'block'`).

### Snippets to run

```javascript
// 1) perfChartWrap exists?
var wrap = document.getElementById('perfChartWrap');
console.log('perfChartWrap exists', !!wrap);
if (wrap) console.log('outerHTML (first 500 chars)', (wrap.outerHTML || '').substring(0, 500));
```

```javascript
// 2) Data spans exist?
var bakiye = document.getElementById('perfReportBakiyeDegisim');
var parite = document.getElementById('perfReportPariteDegisim');
console.log('perfReportBakiyeDegisim exists', !!bakiye, 'textContent', bakiye ? bakiye.textContent : 'N/A');
console.log('perfReportPariteDegisim exists', !!parite, 'textContent', parite ? parite.textContent : 'N/A');
```

```javascript
// 3) Is #perfChartWrap visible?
var wrap = document.getElementById('perfChartWrap');
if (wrap) {
  var r = wrap.getBoundingClientRect();
  var cs = window.getComputedStyle(wrap);
  console.log('getBoundingClientRect', { top: r.top, left: r.left, width: r.width, height: r.height });
  console.log('computed display', cs.display, 'visibility', cs.visibility, 'height', cs.height);
}
```

```javascript
// 4) Spans updated over time? (run, wait 5s, run again)
var b = document.getElementById('perfReportBakiyeDegisim');
var p = document.getElementById('perfReportPariteDegisim');
console.log('Bakiye now', b ? b.textContent : null, 'Parite now', p ? p.textContent : null);
// After 5 seconds, run same again and compare.
```

### Expected output notes

- **Before** perf report is rendered: `perfReportBakiyeDegisim` and `perfReportPariteDegisim` are **null** (spans do not exist yet).
- **After** perf report is rendered: spans exist; `textContent` examples: `"$-0.25 -0.25%"` and `"-0.4800 -0.47%"` (trailing % is what `parseTrailingPercent` uses).
- If `#perfChartWrap` is inside a panel with `display: none`, `getBoundingClientRect()` can be 0 or very small; `offsetWidth`/`offsetHeight` on the mount div may be 0 when `createChart` runs.

---

## 2) File map: Where chart code lives

### ripgrep results (paths + line numbers)

**perfChartWrap**

```
./ui/bot.html:267:            <div class="perf-chart-wrap" id="perfChartWrap" title="Grafiği büyütmek için tıklayın">
./ui/bot.html:410:        var perfChartWrap = document.getElementById('perfChartWrap');
./ui/bot.html:1143:        if (perfChartWrap && !(window.PerfChartRebuild && typeof window.PerfChartRebuild.init === 'function')) {
./ui/bot.html:1144:            perfChartWrap.addEventListener('click', openPerfChartModal);
./ui/assets/perf_chart_rebuild.js:285:        wrapEl = document.getElementById('perfChartWrap');
./ui/assets/perf_chart_rebuild.js:302:        wrapEl.innerHTML = '<div class="perf-chart-title">Parite % &amp; Bot bakiyesi % (başlangıçtan itibaren) <span class="perf-chart-open-hint">Grafiği aç</span></div>' +
./ui/assets/perf_chart_rebuild.js:303:            '<div id="perfChartWrapMount" style="width:100%; min-height:260px; height:260px;"></div>';
```

**perfReportBakiyeDegisim**

```
./ui/bot.html:885:                    '<p><strong>Bakiye Değişimi:</strong> <span id="perfReportBakiyeDegisim" style="color:' + totalKzCl + '">' + ...
./ui/bot.html:1123:                '<p><strong>Bakiye Değişimi:</strong> <span id="perfReportBakiyeDegisim" style="color:' + pnlColor + '">' + ...
./ui/bot.html:1397:                    var bakiyeDegisimEl = document.getElementById('perfReportBakiyeDegisim');
./ui/assets/perf_chart_rebuild.js:3: * Data from #perfReportBakiyeDegisim and #perfReportPariteDegisim (trailing % only).
./ui/assets/perf_chart_rebuild.js:51:            bot: document.getElementById('perfReportBakiyeDegisim'),
```

**perfReportPariteDegisim**

```
./ui/bot.html:888:                    '<p><strong>Parite Değişimi:</strong> <span id="perfReportPariteDegisim">' + ...
./ui/bot.html:1126:                (priceDiffUsd != null && pricePct != null ? '<p><strong>Parite Değişimi:</strong> <span id="perfReportPariteDegisim" ...
./ui/bot.html:1406:                    var pariteDegisimEl = document.getElementById('perfReportPariteDegisim');
./ui/assets/perf_chart_rebuild.js:52:            parite: document.getElementById('perfReportPariteDegisim')
./ui/assets/perf_chart_rebuild.js:65:        var botPct = parseTrailingPercent(spans.bot ? spans.bot.textContent : '');
```

**perfChartModalOverlay**

```
./ui/bot.html:277:            <div class="perf-chart-modal-overlay" id="perfChartModalOverlay">
./ui/bot.html:411:        var perfChartModalOverlay = document.getElementById('perfChartModalOverlay');
./ui/bot.html:484:            if ((series.length >= 2 || (pairSeries && pairSeries.length >= 2)) && perfChartModalOverlay) {
./ui/bot.html:489:                perfChartModalOverlay.classList.add('is-open');
./ui/bot.html:1169:                if (perfChartModalOverlay) perfChartModalOverlay.classList.remove('is-open');
./ui/bot.html:1172:        if (perfChartModalOverlay) {
./ui/bot.html:1173:            perfChartModalOverlay.addEventListener('click', function(e) {
./ui/bot.html:1174:                if (e.target === perfChartModalOverlay) perfChartModalOverlay.classList.remove('is-open');
./ui/bot.html:1182:                else if (perfChartModalOverlay && perfChartModalOverlay.classList.contains('is-open')) perfChartModalOverlay.classList.remove('is-open');
./ui/assets/perf_chart_rebuild.js:286:        modalEl = document.getElementById('perfChartModalOverlay');
./ui/assets/perf_chart_rebuild.js:288:            console.error('[PerfChartRebuild] Missing required elements: perfChartWrap=' + !!wrapEl + ' perfChartModalOverlay=' + !!modalEl);
```

**LightweightCharts / createChart / addLineSeries / setData / setVisibleRange**

```
./ui/assets/perf_chart_rebuild.js:8:    if (typeof window.LightweightCharts === 'undefined') {
./ui/assets/perf_chart_rebuild.js:9:        console.error('[PerfChartRebuild] FATAL: window.LightweightCharts not found. Add script: https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js');
./ui/assets/perf_chart_rebuild.js:133:        botS.setData(data.bot);
./ui/assets/perf_chart_rebuild.js:134:        pariteS.setData(data.parite);
./ui/assets/perf_chart_rebuild.js:141:                chart.timeScale().setVisibleRange({ from: fromSec, to: toSec });
./ui/assets/perf_chart_rebuild.js:173:    function createChart(mountEl, height) {
./ui/assets/perf_chart_rebuild.js:178:        var chart = window.LightweightCharts.createChart(mountEl, opts);
./ui/assets/perf_chart_rebuild.js:181:        var s1 = chart.addLineSeries({
./ui/assets/perf_chart_rebuild.js:187:        var s2 = chart.addLineSeries({
./ui/assets/perf_chart_rebuild.js:203:        miniChart = createChart(wrapMount, h);
./ui/assets/perf_chart_rebuild.js:208:        miniChart.botSeries.setData(data.bot);
./ui/assets/perf_chart_rebuild.js:209:        miniChart.pariteSeries.setData(data.parite);
./ui/assets/perf_chart_rebuild.js:213:                miniChart.chart.timeScale().setVisibleRange({ from: fromSec, to: toSec });
./ui/assets/chart.js:273:        if (!container || typeof LightweightCharts === 'undefined') return null;
./ui/assets/chart.js:325:        chart = LightweightCharts.createChart(container, chartOptions);
./ui/assets/chart.js:340:        lineSeries = chart.addLineSeries({
./ui/assets/chart.js:346:        lineSeries.setData([]);
./ui/assets/chart.js:359:        candleSeries.setData(data);
./ui/assets/chart.js:361:        lineSeries.setData(lineData);
./ui/assets/chart.js:425:            chart.timeScale().setVisibleRange({ from: fromSec, to: toSec });
```

---

## 3) Script loading & order

### HTML file

- **File:** `ui/bot.html` (single-page bot detail).

### Exact &lt;script&gt; tag order (ui/bot.html, lines 362–365)

```html
<script src="/ui/assets/utils/coinLogo.js?v=1"></script>
<script src="/ui/assets/core/apiClient.js?v=refactor1"></script>
<script src="https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"></script>
<script src="/ui/assets/perf_chart_rebuild.js?v=1"></script>
<script>
(function() { ... })();  // inline: botId, loadDetail, renderBotDetail, etc.
</script>
```

### LightweightCharts on the page

- **Check in console (after full load):**  
  `typeof window.LightweightCharts`  
  - **If `"undefined"`:** The library did not load (network error, blocked, or wrong URL). Then `perf_chart_rebuild.js` runs lines 8–11 and **returns immediately**; `window.PerfChartRebuild` is never set.
- **Intended source:**  
  `https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js`  
  (external; requires network and no CSP blocking script from unpkg.)

---

## 4) Initialization lifecycle

### DOMContentLoaded

- There is **no** explicit `DOMContentLoaded` listener for the chart. The inline script in `bot.html` runs as soon as it is parsed; it defines `loadDetail`, `renderBotDetail`, and binds the click handler. No “on DOM ready” wrapper around chart init.

### Who binds click on `#perfChartWrap`

- **bot.html lines 1143–1145:**  
  `if (perfChartWrap && !(window.PerfChartRebuild && typeof window.PerfChartRebuild.init === 'function')) { perfChartWrap.addEventListener('click', openPerfChartModal); }`  
  So: if `PerfChartRebuild.init` is **not** a function (e.g. script returned early), the **fallback** `openPerfChartModal` is bound.
- **perf_chart_rebuild.js line 358:**  
  Inside `init()`, `wrapEl.addEventListener('click', openModal)` is called. So if `init()` runs, the **rebuild** code owns the click (open modal + rebuild chart). The fallback is only used when `PerfChartRebuild` was never defined.

### Who is supposed to mount the chart

- **perf_chart_rebuild.js `init()` (lines 283–386):**
  1. Gets `perfChartWrap` and `perfChartModalOverlay`; if either missing, logs error and **returns** (line 288).
  2. Replaces `wrapEl.innerHTML` with title + `<div id="perfChartWrapMount" style="width:100%; min-height:260px; height:260px;"></div>` (lines 301–303).
  3. Gets `wrapMount = document.getElementById('perfChartWrapMount')`.
  4. Sets up modal DOM and listeners.
  5. `resetBaseline()` then `sampleFromDom()`.
  6. **requestAnimationFrame** → `buildMiniChart()` (lines 364–366).
- **buildMiniChart() (lines 199–216):**  
  `if (!wrapMount || miniChart) return;` then `var rect = wrapMount.getBoundingClientRect(); var h = Math.max(rect.height || 260, 260);` then `miniChart = createChart(wrapMount, h);` and `setData` / `setVisibleRange`. So the **inline** mini chart is created only inside this rAF, and only if `wrapMount` exists and `miniChart` is still null.

### “Init once” guard

- **perf_chart_rebuild.js line 283:**  
  `if (inited) return;`  
  So `init()` runs only once per page. After that, re-calling `init()` does nothing.

### Chart created while container has 0 height / display:none?

- **Yes, possible.**  
  `init()` is invoked from **bot.html lines 905–906**, inside the same block that sets `perfReport.innerHTML` and **then** sets `perfPanel.style.display = 'block'` (line 909). So at the moment `init()` runs, `perfPanel` can still be `display: none`. Then:
  - `#perfChartWrap` is inside `#perfPanel` → when panel is hidden, `getBoundingClientRect()` on `#perfChartWrap` (or `#perfChartWrapMount`) can return width/height 0 or very small.
  - `createChart(mountEl, h)` (line 178) uses `mountEl.offsetWidth` for `opts.width`; if the mount has **offsetWidth 0**, the chart is created with width 0 and may not render visibly.
- **buildMiniChart** runs in **requestAnimationFrame** (line 364); by then `perfPanel` might already be `display: block`, but the first frame after a display change can still report 0 size in some browsers.

### Code excerpts

**bot.html ~879–910 (where init is called and panel shown):**

```javascript
if (perfReport) {
    // ... perfReport.innerHTML = '...' with id="perfReportBakiyeDegisim" and id="perfReportPariteDegisim"
    if (window.PerfChartRebuild && typeof window.PerfChartRebuild.init === 'function') {
        try { window.PerfChartRebuild.init(); } catch (err) { console.warn('PerfChartRebuild.init', err); }
    }
}
perfPanel.style.display = 'block';
```

**perf_chart_rebuild.js lines 8–12 (early return):**

```javascript
if (typeof window.LightweightCharts === 'undefined') {
    console.error('[PerfChartRebuild] FATAL: window.LightweightCharts not found. ...');
    return;
}
```

**perf_chart_rebuild.js lines 283–303 (init guard + innerHTML replace):**

```javascript
function init() {
    if (inited) return;
    wrapEl = document.getElementById('perfChartWrap');
    modalEl = document.getElementById('perfChartModalOverlay');
    if (!wrapEl || !modalEl) {
        console.error('[PerfChartRebuild] Missing required elements: ...');
        return;
    }
    // ...
    wrapEl.innerHTML = '<div class="perf-chart-title">...<span class="perf-chart-open-hint">Grafiği aç</span></div>' +
        '<div id="perfChartWrapMount" style="width:100%; min-height:260px; height:260px;"></div>';
    wrapMount = document.getElementById('perfChartWrapMount');
```

**perf_chart_rebuild.js lines 199–204 (buildMiniChart):**

```javascript
function buildMiniChart() {
    if (!wrapMount || miniChart) return;
    var rect = wrapMount.getBoundingClientRect();
    var h = Math.max(rect.height || 260, 260);
    miniChart = createChart(wrapMount, h);
```

**perf_chart_rebuild.js createChart (lines 173–176):**

```javascript
function createChart(mountEl, height) {
    var w = mountEl && mountEl.offsetWidth ? mountEl.offsetWidth : 0;
    var opts = createChartOptions(height);
    opts.width = w > 0 ? w : undefined;
```

---

## 5) CSS / Layout blockers

### Computed CSS for `#perfChartWrap` (from ui/bot.html styles)

- **.perf-chart-wrap** (lines 108–111):  
  `min-height: 220px;`  
  `background: var(--ds-bg-tertiary);`  
  `border-radius: 12px;`  
  `padding: 1rem 1.25rem;`  
  `margin: 1rem 0;`  
  `border: 1px solid var(--ds-border);`  
  `cursor: pointer;`  
  No `display: none` or `visibility: hidden` on the wrap itself. **Parent** `#perfPanel` has `style="display: none"` until line 909 runs.

### Who overwrites innerHTML / replaces the node

- **perf_chart_rebuild.js lines 301–302:**  
  `wrapEl.innerHTML = '...'` replaces the entire contents of `#perfChartWrap` (removes `#perfChartSvgWrap`, `#perfChartPlaceholder`, legend) and inserts `#perfChartWrapMount`. So after init, the only child content of `#perfChartWrap` is the title div and the mount div.
- **bot.html** does not set `perfChartWrap.innerHTML` elsewhere; it only sets `perfReport.innerHTML` (which contains the two data spans).

### Modal z-index and pointer events

- **.perf-chart-modal-overlay** (line 84):  
  `position: fixed; inset: 0; background: rgba(0,0,0,0.65); z-index: 9999;`  
  Modal overlay has high z-index; no pointer-events rule that would block the inline chart. The inline chart is in `#perfChartWrap`, not in the overlay.

---

## 6) Console errors & network clues

### What to capture

- On **bot detail page load:** Check console for `[PerfChartRebuild] FATAL: window.LightweightCharts not found` (if script returned early).
- After **opening Performans** (bot data loaded): Check for `[PerfChartRebuild] Missing required elements: perfChartWrap=... perfChartModalOverlay=...`.
- Any **ReferenceError / TypeError** in `perf_chart_rebuild.js` (e.g. `createChart`, `setData`, `timeScale`) or in `buildMiniChart` / `updateChart`.
- **Network tab:** Whether `https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js` returns 200 or fails (CSP, network, adblock).

### No backend for chart

- The chart is DOM-driven; it does **not** call backend endpoints for the two series. Only the two spans are read. So no “failing endpoints” for the chart itself.

---

## 7) Minimal reproduction snippet

Use this **only for diagnosis** in the console (e.g. after opening Performans and ensuring `#perfChartWrap` and the data spans exist). Do not commit.

```javascript
(function() {
  var wrap = document.getElementById('perfChartWrap');
  if (!wrap) { console.error('perfChartWrap missing'); return; }
  var mount = document.createElement('div');
  mount.id = 'perfChartDebugMount';
  mount.style.cssText = 'width:100%; height:260px; background:#1e2329;';
  wrap.appendChild(mount);
  var rect = mount.getBoundingClientRect();
  console.log('Mount size', rect.width, 'x', rect.height);
  if (typeof window.LightweightCharts === 'undefined') {
    console.error('LightweightCharts not loaded');
    return;
  }
  var chart = window.LightweightCharts.createChart(mount, { width: mount.offsetWidth || 400, height: 260, layout: { background: { type: 'solid', color: '#1e2329' }, textColor: '#ccc' }, rightPriceScale: { borderVisible: false }, timeScale: { timeVisible: true } });
  var s1 = chart.addLineSeries({ color: '#0ECB81' });
  var s2 = chart.addLineSeries({ color: '#F6465D' });
  var t = Math.floor(Date.now() / 1000);
  s1.setData([{ time: t - 60, value: 0 }, { time: t, value: -0.25 }]);
  s2.setData([{ time: t - 60, value: 0 }, { time: t, value: -0.47 }]);
  chart.timeScale().fitContent();
  console.log('Chart created and setData done');
})();
```

- If **Mount size** is 0 x something: container was hidden or had no width when measured.
- If **LightweightCharts not loaded**: script loading / network / CSP issue.
- If chart appears after this snippet: init timing or container size is the issue; if it still does not: library or API usage issue.

---

## 8) Root-cause shortlist (no fixes)

Based on the evidence above, the **top 3 likely blockers**:

1. **LightweightCharts script missing or blocked**  
   - **Evidence:** `perf_chart_rebuild.js` lines 8–11: if `typeof window.LightweightCharts === 'undefined'`, the IIFE `return`s and never defines `window.PerfChartRebuild`. Then `init` is never called, and the fallback `openPerfChartModal` (which uses `_lastPerfChartSeries` / SVG, not the two DOM spans) is bound.  
   - **Check:** In console after load, `typeof window.LightweightCharts`. If `"undefined"`, the chart module never runs (network/CSP/adblock for unpkg).

2. **Init runs while container has zero width (display:none parent)**  
   - **Evidence:** `init()` is called from `bot.html` lines 905–906 **before** `perfPanel.style.display = 'block'` (line 909). So when `buildMiniChart()` runs in requestAnimationFrame, `#perfChartWrap` / `#perfChartWrapMount` may still be inside a `display: none` tree → `getBoundingClientRect()` and `offsetWidth` can be 0. `createChart(mountEl, h)` sets `opts.width = w > 0 ? w : undefined` (line 176); with width 0 the chart may not render visibly.  
   - **Check:** In console after opening Performans, run: `document.getElementById('perfChartWrapMount') && document.getElementById('perfChartWrapMount').getBoundingClientRect()` and `offsetWidth`. If init ran before panel was shown, mount might have been 0 at creation time.

3. **Init never called (guard or missing call path)**  
   - **Evidence:** `init()` is only invoked from one place: inside the `if (perfReport)` block that sets `perfReport.innerHTML` (lines 879–907). If that block is not run (e.g. different code path for this bot, or perf report not rendered), `PerfChartRebuild.init()` is never executed. Also `if (inited) return` ensures it runs at most once; if the first run happened in a state where wrap/modal or spans were missing, later corrections (e.g. spans added) are not retried.  
   - **Check:** Add a temporary `console.log('PerfChartRebuild.init called')` at the very start of `init()` and see if it appears when Performans is shown. If it never appears, either `PerfChartRebuild` is undefined (see 1) or the call path to `init()` is not reached.

---

**End of evidence dump.** Use this document to apply deterministic fixes (e.g. ensure LightweightCharts loads, call init only after panel is visible and mount has size, or re-resolve mount dimensions in buildMiniChart).
