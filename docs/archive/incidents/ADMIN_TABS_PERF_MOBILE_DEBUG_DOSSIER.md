# ADMIN TABS PERFORMANCE & MOBILE DEBUG DOSSIER

**Target:** ChatGPT / LLM consumption. Diagnose and fix: (1) slow "Hesaplar" tab load and late tab content; (2) mobile "Sekmeler" button not showing tabs menu; (3) preload all tabs for instant switch while minimizing backend load.

**Stack:** Vanilla JS + CSS + HTML; backend FastAPI. Admin container with tabs header and panels.

---

## A) SYSTEM MAP (Admin Panel UI)

### A.1 DOM structure (canonical)

```
body.binance-theme.page-admin
  #breachAlertOverlay
  #topTicker
  .admin-appbar
  .container.admin-container
    .kpi-strip
    #tabsContainer.tabs-container
      #adminTabsHeader.tabs-header
        #adminTabsToggle.admin-tabs-toggle  [Sekmeler button - mobile]
        #adminTabsList.admin-tabs-list
          .tab-indicator
          .tab-btn.active[data-tab="accounts"]  (Hesaplar)
          .tab-btn[data-tab="suspended"]
          .tab-btn[data-tab="pending"]
          .tab-btn[data-tab="contact"]
          .tab-btn[data-tab="server"]
          .tab-btn[data-tab="popup"]
          .tab-btn[data-tab="settings"]
      #tabAccounts.tab-content.admin-tab-panel.active[data-tab-panel="accounts"]
        #tilesContainer.tile-grid
      #tabPending.tab-content.admin-tab-panel[data-tab-panel="pending"]
      #tabContact.tab-content.admin-tab-panel[data-tab-panel="contact"]
      #tabSuspended.tab-content.admin-tab-panel[data-tab-panel="suspended"]
      #tabServer.tab-content.admin-tab-panel[data-tab-panel="server"]
      #tabPopup.tab-content.admin-tab-panel[data-tab-panel="popup"]
      #tabSettings.tab-content.admin-tab-panel[data-tab-panel="settings"]
```

### A.2 CSS selectors and fallbacks

| Element | Primary selector | Fallback |
|--------|------------------|----------|
| Admin container | `.container.admin-container` | `body.page-admin .container` |
| Tabs container | `#tabsContainer` | `.tabs-container` |
| Tabs header | `#adminTabsHeader` | `.tabs-header` |
| Mobile "Sekmeler" button | `#adminTabsToggle` | `.admin-tabs-toggle` |
| Tabs list (desktop row / mobile dropdown) | `#adminTabsList` | `.admin-tabs-list` |
| Active tab button | `.tab-btn.active` | `.tab-btn[data-tab="accounts"]` |
| Tab button by key | `.tab-btn[data-tab="accounts"]` | `#adminTabsList .tab-btn:nth-child(2)` (1-based after indicator) |
| Tab indicator | `.admin-tabs-list .tab-indicator` | `#adminTabsList .tab-indicator` |
| Panel by key | `.admin-tab-panel[data-tab-panel="accounts"]` | `#tabAccounts` |
| Accounts tiles | `#tilesContainer` | `.tile-grid` |

### A.3 Known DOM paths (from user / codebase)

- `div.container.admin-container > div#tabsContainer > div#adminTabsHeader > div.admin-tabs-list > button.tab-btn`
- `div#tabsContainer > div#adminTabsHeader > button#adminTabsToggle` (Sekmeler)
- Panel: `div#tabsContainer > div#tabAccounts.admin-tab-panel`

### A.4 Event handlers

- `switchTab('accounts')` — global (window.switchTab). Invoked via inline `onclick="switchTab('accounts')"` on each `.tab-btn`.
- `toggleAdminTabs()` — global. Bound on DOMContentLoaded: `document.getElementById("adminTabsToggle").addEventListener("click", ...)` with stopPropagation/preventDefault.
- Click-outside-to-close: `document.addEventListener("click", ...)` checks `.admin-tabs-list.admin-tabs-list--open` and closes if click not on `#adminTabsToggle` or `.admin-tabs-list`.
- Resize: `window.addEventListener("resize", ...)` restores `.admin-tabs-list` into `#adminTabsHeader` when width > 768 and clears inline position styles.

### A.5 HTML generation source

- **Server-side:** `ui/admin.html` — full HTML; all tab panels and buttons present in initial markup. No server-side tab content injection.
- **Client-side:** Tab panel content filled by JS: `renderTiles()`, `loadPendingRegistrations()`, `loadContactMessages()`, `loadServerStats()`, `loadPopupsList()`, etc. Initial state: `#tilesContainer` contains `<div class="empty-state">Loading...</div>`; other panels have static placeholder or empty-state divs.
- **Script:** `ui/assets/admin.js` loaded at end of body (assumed; verify in admin.html). No template engine; string concatenation or innerHTML for lists.

---

## B) CURRENT BEHAVIOR TIMELINE (DESKTOP vs MOBILE)

### B.1 First admin load (desktop)

1. HTML parsed; head script runs: check sessionStorage token/user; if missing redirect to login.
2. Styles load (ticker, theme, ui, design, admin-login-theme).
3. Body renders: appbar, KPI strip, tabsContainer with header and all panels (panels with display:none except first or none).
4. admin.js loads.
5. DOMContentLoaded fires: whoami fetch (if no token), boot-id fetch, boot_id mismatch may trigger second whoami; document.documentElement.style.visibility = "".
6. initAdminTabsSlider(); restoreAccountsCacheFromStorage() (sessionStorage cache may render tiles immediately); switchTab(savedTab or "accounts") called.
7. switchTab("accounts"): state.currentTab = "accounts"; positionIndicatorToButton; buttons active class; animateAdminTabContentTransition("accounts", "accounts") — fromKey may be null so runLoadForTab("accounts") still runs; closeAdminTabsDropdown(); sessionStorage set admin_tab.
8. animateAdminTabContentTransition: toPanel gets .active, opacity/transform animation 220ms; after wait runLoadForTab("accounts") called.
9. runLoadForTab("accounts") → loadAccounts(). If cache hit and state.accounts.length > 0, renderTiles + renderKpis first; then state.inFlight check; fetch `/api/admin/accounts?cb=timestamp`; on response parse JSON, state.accounts = data.accounts, state.accountsTotals = data.totals, renderTiles, renderKpis, sessionStorage set cache, state.inFlight = false.
10. fetchBreachAlerts() called; setInterval 5s for loadAccounts (only when currentTab === 'accounts'); setInterval 15s for fetchBreachAlerts.
11. Expected network: GET /api/auth/whoami (optional), GET /api/boot-id, GET /api/admin/accounts?cb=..., GET /api/admin/breach-alerts.

**Failure modes:** whoami or boot-id slow/blocking; loadAccounts runs after animation so first paint of accounts panel is "Loading..." until fetch completes; no prefetch of other tabs so first click on "Bekleyen Onaylar" etc. triggers load on demand.

### B.2 Clicking "Hesaplar" (desktop)

1. User clicks .tab-btn[data-tab="accounts"]. onclick="switchTab('accounts')".
2. switchTab("accounts"): fromKey !== toKey check (if already accounts, return). __adminTabAnimating guard; state.currentTab = "accounts"; positionIndicatorToButton; toggle .active on buttons; animateAdminTabContentTransition(fromKey, "accounts"); closeAdminTabsDropdown.
3. animateAdminTabContentTransition: show toPanel, hide fromPanel, 220ms animation; then runLoadForTab("accounts").
4. runLoadForTab("accounts") → loadAccounts(). If inFlight and !force, skip. Else fetch /api/admin/accounts.
5. Expected network: GET /api/admin/accounts?cb=... (unless skipped by inFlight).
6. Expected state: state.currentTab = "accounts"; state.accounts updated on response; tiles re-rendered.

**Failure modes:** __adminTabAnimating stuck true (animation error); runLoadForTab called after animation with stale closure; loadAccounts inFlight true from polling so fetch skipped and UI not updated.

### B.3 Switching to another tab (e.g. "Bekleyen Onaylar")

1. switchTab("pending"): runLoadForTab("pending") only after animation ends → loadPendingRegistrations().
2. loadPendingRegistrations: fetch /api/admin/pending-registrations; then fetch /api/admin/password-reset-requests; render both lists.
3. No cache for pending; every switch triggers full fetch. Same for suspended, contact, server, popup, settings (each has its own load function).

**Failure modes:** Sequential awaits in loadPendingRegistrations (pending then password-reset) cause waterfall; no request coalescing so rapid tab switch can fire multiple overlapping fetches; runLoadForTab(toKey) called after animation so first paint of panel is empty/placeholder until fetch completes.

### B.4 Mobile: pressing "Sekmeler" button

1. User taps #adminTabsToggle (Sekmeler). Expected: click listener fires (added in DOMContentLoaded), stopPropagation + preventDefault, toggleAdminTabs().
2. toggleAdminTabs(): list = .admin-tabs-list, toggle = #adminTabsToggle, header = #adminTabsHeader. isOpen = list.classList.toggle("admin-tabs-list--open").
3. If isOpen && isMobile (innerWidth <= 768): if list.parentNode !== document.body and header, document.body.appendChild(list); then set list.style.position = "fixed", left/right/top (rect.bottom + 6), maxHeight "min(320px, 50vh)", zIndex 1000.
4. Expected DOM: .admin-tabs-list has class admin-tabs-list--open; list is now child of body; list is position:fixed below toggle.
5. CSS: .page-admin .admin-tabs-list { display: none !important } and .page-admin .admin-tabs-list.admin-tabs-list--open { display: flex !important } (design.css around 1200–1220).

**Failure modes (mobile menu not visible):**
- Event not bound: DOMContentLoaded ran before script or adminTabsToggle not in DOM when listener attached.
- list is null: selector .admin-tabs-list or #adminTabsList returns null (e.g. ID typo or duplicate).
- display remains none: class admin-tabs-list--open not applied (toggle failed) or overridden by more specific rule.
- list not moved to body: appendChild not run (header null or list.parentNode === document.body already but list still inside a container with overflow:hidden).
- Stacking: another fixed element (e.g. appbar, breach overlay) has higher z-index than 1000.
- Position: top set to rect.bottom + 6 but rect is from getBoundingClientRect(); if toggle is off-screen or in a scroll container, rect may be wrong; or list is positioned but viewport scroll/address bar hides it.
- Overflow: parent of list (before move) had overflow:hidden so list was clipped; after move to body, list should be visible unless body/html overflow hidden.
- Touch: 300ms click delay on iOS so tap fires late; or touch event consumed by another handler so click never fires.
- Two menus: duplicate #adminTabsList in DOM; toggle updates one list, the visible one is the other.
- aria-expanded toggled but list visibility tied to a different state (e.g. data attribute) that is not updated.

---

## C) PERFORMANCE BOTTLENECK HYPOTHESES (UI + API)

1. **Symptom:** First "Hesaplar" content appears after long delay. **Cause:** loadAccounts() is called only after animateAdminTabContentTransition completes (runLoadForTab at end of animation). **Verify:** Performance mark before/after loadAccounts; check timing of first fetch. **Fix:** Call runLoadForTab(toKey) immediately on switch (or preload accounts on init) and optionally keep animation; or preload accounts in parallel with init.
2. **Symptom:** Tab switch feels slow. **Cause:** runLoadForTab runs only after 220ms animation. **Verify:** Measure time from click to runLoadForTab. **Fix:** Start fetch on tab click before or during animation; render when data arrives.
3. **Symptom:** Multiple /api/admin/accounts requests in short time. **Cause:** No request coalescing; rapid tab switch or double-click triggers multiple loadAccounts. **Verify:** Network tab filter by "accounts"; count requests within 2s. **Fix:** In-flight promise reuse; ignore or debounce duplicate switchTab for same tab.
4. **Symptom:** Large JSON for /api/admin/accounts. **Cause:** Backend returns all accounts with nested data (bots, balances). **Verify:** Network response size for /api/admin/accounts. **Fix:** Paginate; lightweight list endpoint; details on demand.
5. **Symptom:** No caching; every tab switch refetches. **Cause:** loadPendingRegistrations, loadSuspendedAccounts, loadContactMessages, etc. have no cache. **Verify:** Switch tab A → B → A; check network for duplicate fetches. **Fix:** In-memory cache per tab with TTL; return cached and optionally revalidate.
6. **Symptom:** DOM thrash on accounts render. **Cause:** renderTiles clears container and sets innerHTML with large string. **Verify:** Performance recording; long Layout/Recalc. **Fix:** DocumentFragment or incremental DOM; virtual list if many tiles.
7. **Symptom:** Requests serialized. **Cause:** loadPendingRegistrations awaits pending then password-reset sequentially. **Verify:** Network waterfall. **Fix:** Promise.all or parallel fetch with single combined endpoint.
8. **Symptom:** Polling (5s) and breach (15s) run even when tab not visible. **Cause:** setInterval only skips loadAccounts when currentTab !== 'accounts'; breach always runs. **Verify:** Switch to Server tab; check network for accounts requests (should stop). **Fix:** Already guarded for accounts; reduce breach frequency or pause when tab not active.
9. **Symptom:** Mobile tap on "Sekmeler" does nothing. **Cause:** Click listener not attached (script load order or element not found). **Verify:** In Safari remote debug, breakpoint in toggleAdminTabs; tap button; check if hit. **Fix:** Ensure script after DOM; use event delegation on container if needed.
10. **Symptom:** Menu flashes and disappears. **Cause:** Click-outside handler fires immediately (event bubbles from same tap). **Verify:** Log in click handler: target, list.classList. **Fix:** setTimeout 0 to close dropdown so same-tap doesn’t close; or check event phase.
11. **Symptom:** Menu not visible but DOM has --open. **Cause:** display:flex overridden by more specific rule or display:none on parent. **Verify:** Computed style for .admin-tabs-list (display, visibility). **Fix:** Increase specificity or use !important for --open state; ensure no parent display:none.
12. **Symptom:** Menu rendered off-screen. **Cause:** position:fixed top/left in scroll context; or getBoundingClientRect() before layout. **Verify:** getBoundingClientRect() of list after open. **Fix:** Position after requestAnimationFrame; use visualViewport for mobile.
13. **Symptom:** z-index: 1000 not on top. **Cause:** New stacking context from transform/opacity on ancestor. **Verify:** Stacking context chain (Chrome Layers). **Fix:** Move list to body (already done in code); ensure no body transform.
14. **Symptom:** Overflow hidden on .tabs-header or .tabs-container clips menu. **Cause:** Mobile menu is position:fixed but was measured when inside container; after appendChild to body it’s correct, but if appendChild not run list stays inside. **Verify:** list.parentNode after toggle. **Fix:** Always append to body when opening on mobile; confirm in code path.
15. **Symptom:** 300ms tap delay (iOS). **Cause:** Browser waits for possible double-tap. **Verify:** Fast tap vs slow tap. **Fix:** touch-action: manipulation; or touchstart handler with preventDefault and programmatic click (careful for a11y).
16. **Symptom:** Heavy main thread at load. **Cause:** initAdminTabsSlider, restoreAccountsCacheFromStorage, switchTab, fetchBreachAlerts all in DOMContentLoaded. **Verify:** Performance recording; long task. **Fix:** Defer non-critical (breach, prefetch) with requestIdleCallback or setTimeout(0).
17. **Symptom:** First Interactive / LCP slow. **Cause:** Multiple sync scripts or large CSS. **Verify:** Lighthouse. **Fix:** Defer admin.js; critical CSS inline or preload.
18. **Symptom:** Backend /api/admin/accounts slow. **Cause:** N+1 queries (accounts + bots + spot balance per account). **Verify:** Server logs; DB query count. **Fix:** Eager load; batch spot balance; cache.
19. **Symptom:** Spot balance fetch per account blocks. **Cause:** _get_spot_balance_for_account is async and may be called in loop. **Verify:** Backend timing per account. **Fix:** Concurrent limit (e.g. 2); or lazy load balance on expand.
20. **Symptom:** Long JSON parse. **Cause:** Large accounts array. **Verify:** Performance mark around JSON.parse. **Fix:** Stream or paginate; reduce payload.
21. **Symptom:** Reflow loop. **Cause:** Reading offsetHeight/ getBoundingClientRect then writing style in loop. **Verify:** Layout thrash in Performance. **Fix:** Batch reads then writes; or requestAnimationFrame.
22. **Symptom:** Animation jank. **Cause:** animateAdminTabContentTransition uses transform/opacity but layout triggered elsewhere. **Verify:** Frame rate during transition. **Fix:** will-change: transform on panels during transition; avoid reading layout in animation frame.
23. **Symptom:** Safari mobile viewport. **Cause:** 100vh includes address bar; fixed menu position wrong when bar shows/hides. **Verify:** innerHeight vs 50vh. **Fix:** Use visualViewport.height or CSS env(safe-area).
24. **Symptom:** Duplicate event binding. **Cause:** switchTab or toggle bound multiple times if script runs twice. **Verify:** getEventListeners(adminTabsToggle). **Fix:** Single attach; or removeEventListener before add.
25. **Symptom:** Stale closure in setInterval. **Cause:** Polling closure captures old state. **Verify:** Log state.currentTab in interval. **Fix:** Read state.currentTab inside interval (already done).
26. **Symptom:** runLoadForTab called with wrong tab after rapid switch. **Cause:** animateAdminTabContentTransition resolves after delay; toKey from closure may be stale if user switched again. **Verify:** Log toKey when runLoadForTab runs. **Fix:** Pass tab key at resolve time; or cancel previous animation and ignore stale runLoadForTab.
27. **Symptom:** sessionStorage cache prevents fresh data. **Cause:** restoreAccountsCacheFromStorage runs on init; loadAccounts may skip or show stale. **Verify:** Cache timestamp vs loadAccounts response. **Fix:** TTL check; or loadAccounts(true) on first tab show.
28. **Symptom:** No prefetch of other tabs. **Cause:** Only accounts (and optionally from cache) loaded on init. **Verify:** Network on load: only accounts and breach. **Fix:** Prefetch queue for pending, suspended, etc. with low priority.
29. **Symptom:** Backend 401 on mobile only. **Cause:** Cookie not sent (SameSite, secure, or CORS). **Verify:** Request headers in Safari. **Fix:** credentials: "include"; SameSite=Lax; CORS credentials.
30. **Symptom:** Tabs list not in DOM when toggle runs. **Cause:** Dynamic content or duplicate admin page. **Verify:** document.querySelectorAll('.admin-tabs-list').length. **Fix:** Ensure single list; attach listener after DOM ready.

---

## D) INSTRUMENTATION PLAN (MEASURABLE + REPRODUCIBLE)

### D.1 Performance marks and measures

Add at top of admin.js (or in a small inline script after admin.js):

```javascript
function adminPerfMark(name) {
  try { performance.mark(name); } catch (e) {}
}
function adminPerfMeasure(name, start, end) {
  try { performance.measure(name, start, end); } catch (e) {}
}
```

Instrumentation points:

- On DOMContentLoaded start: `adminPerfMark("admin_init_start")`.
- After whoami + boot-id + visibility: `adminPerfMark("admin_init_ready")`; then `adminPerfMeasure("admin_init", "admin_init_start", "admin_init_ready")`.
- Start of switchTab(tabName): `adminPerfMark("TAB_SWITCH_START_" + tabName)`.
- When runLoadForTab(tabName) is invoked: `adminPerfMark("TAB_LOAD_START_" + tabName)`.
- End of load function for that tab (e.g. after renderTiles in loadAccounts): `adminPerfMark("TAB_LOAD_END_" + tabName)`; `adminPerfMeasure("TAB_LOAD_" + tabName, "TAB_LOAD_START_" + tabName, "TAB_LOAD_END_" + tabName)`.
- After animation end in switchTab: `adminPerfMark("TAB_SWITCH_END_" + tabName)`; `adminPerfMeasure("TAB_SWITCH_" + tabName, "TAB_SWITCH_START_" + tabName, "TAB_SWITCH_END_" + tabName)`.
- Before fetch in loadAccounts: `adminPerfMark("FETCH_START_accounts")`.
- After fetch response: `adminPerfMark("FETCH_END_accounts")`; measure "FETCH_accounts".

### D.2 Central logger (console + optional server)

```javascript
var _adminLog = [];
function adminLog(event, data) {
  var entry = { event: event, ts: Date.now(), ...data };
  _adminLog.push(entry);
  if (typeof console !== "undefined" && console.debug) console.debug("[ADMIN_PERF]", event, data);
  // Optional: send to backend (batch on unload or every N events)
}
```

Events to log:

- TAB_SWITCH_START: tab_name, from_key.
- TAB_SWITCH_END: tab_name, duration_ms.
- FETCH_START: tab_name, url, request_id (crypto.randomUUID? or Date.now()).
- FETCH_END: tab_name, url, request_id, status, duration_ms, payload_size_bytes, cache_hit (if applicable).
- RENDER_START: tab_name.
- RENDER_END: tab_name, duration_ms, item_count (e.g. tiles length).

### D.3 Fetch wrapper (log + abort)

```javascript
var _adminInflight = {};
function adminFetch(url, opts, requestId) {
  requestId = requestId || "r" + Date.now();
  var start = performance.now();
  adminLog("FETCH_START", { url: url, request_id: requestId });
  var aborter = new AbortController();
  var combined = { ...opts, signal: aborter.signal };
  return fetch(url, combined).then(function (r) {
    var dur = performance.now() - start;
    var size = r.headers.get("content-length");
    adminLog("FETCH_END", { url: url, request_id: requestId, status: r.status, duration_ms: Math.round(dur), payload_bytes: size ? parseInt(size, 10) : null });
    return r;
  });
}
function cancelAdminFetch(requestId) {
  if (_adminInflight[requestId]) _adminInflight[requestId].abort();
}
```

Use: wrap fetch in loadAccounts, loadPendingRegistrations, etc.; store AbortController in _adminInflight by requestId; on tab switch cancel previous tab’s requestId so rapid switch doesn’t let old response overwrite.

### D.4 Network instrumentation summary

- Log url, method, ms, status, bytes (from content-length or response clone and blob), cache_hit (response from cache).
- Abort in-flight tab fetch when switching away (optional but recommended for correctness).

---

## E) LOAD STRATEGY: PRELOAD / PRIME ALL TABS WITHOUT BACKEND OVERLOAD

### E.1 Warm start (after admin page load)

- **Critical path:** Show UI and first tab (accounts) immediately; use sessionStorage cache for accounts if valid.
- **Deferred:** Within 2–3s after first paint, schedule prefetch for other tabs in a throttled queue: pending, suspended, contact, server (summary only), popup, settings (light).
- **Concurrency limit:** Max 2 in-flight prefetch requests.
- **Request coalescing:** If getTabData(tab) is called while a fetch for that tab is in flight, return the same Promise instead of starting a new request.
- **Cache TTL:** accounts 60s, pending/suspended 30s, contact 60s, server 10s, popup 60s, settings 300s (or until mutation).
- **Stale-while-revalidate:** On tab switch, show cached data immediately if available and age < TTL; in background trigger fetch and update when response arrives (if still on that tab).

### E.2 adminDataStore (unified)

- **Structure:** `{ accounts: { data, ts, inflightPromise }, pending: { ... }, suspended: { ... }, contact: { ... }, server: { ... }, popup: { ... }, settings: { ... } }`.
- **getTabData(tab):** If cache valid (now - ts < TTL), return Promise.resolve(cache.data). Else if inflightPromise exists, return it. Else create new fetch promise, store in inflight, on settle clear inflight and set data + ts; return promise.
- **invalidate(tab or "all"):** Clear data/ts/inflight for tab(s). After account create/delete/suspend, invalidate "accounts" and "suspended".
- **preloadAllTabs():** For each tab (except current), call getTabData(tab) and push to a queue that runs with concurrency 2 (e.g. p-limit style). Schedule after requestIdleCallback(_, { timeout: 2000 }) or setTimeout(..., 500).

### E.3 UI skeleton

- For each panel, define a skeleton HTML (e.g. 5 placeholder cards for accounts). On switch, show skeleton immediately; when getTabData resolves, replace with real render. This gives instant switch feel.

### E.4 Pseudo-code

```text
preloadAllTabs() {
  const tabs = ["pending", "suspended", "contact", "server", "popup", "settings"];
  const queue = tabs.filter(t => t !== state.currentTab);
  runQueue(queue, 2, (tab) => getTabData(tab).catch(() => {}));
}
getTabData(tab) {
  const entry = store[tab];
  if (entry && entry.ts && (Date.now() - entry.ts < TTL[tab])) return Promise.resolve(entry.data);
  if (entry && entry.inflight) return entry.inflight;
  const p = fetchForTab(tab).then(data => { entry.data = data; entry.ts = Date.now(); entry.inflight = null; return data; });
  entry.inflight = p;
  return p;
}
renderTab(tab, data) {
  const panel = document.querySelector('.admin-tab-panel[data-tab-panel="' + tab + '"]');
  if (!panel) return;
  const container = panel.querySelector('[data-tab-content]') || panel.firstElementChild;
  if (data === undefined) showSkeleton(container);
  else renderTabContent(tab, container, data);
}
schedule(fn) {
  if (typeof requestIdleCallback !== 'undefined') requestIdleCallback(fn, { timeout: 2000 });
  else setTimeout(fn, 100);
}
```

### E.5 Avoiding backend overload

- Concurrency limit 2 for prefetch.
- Lightweight endpoints: e.g. /api/admin/accounts?summary=1 (counts only) for KPI; full list on demand.
- Server cache: 5–10s TTL for GET /api/admin/accounts; ETag/If-None-Match to return 304.
- Paginate: /api/admin/accounts?limit=20&offset=0; load more on scroll.
- Incremental: account details (bots, balance) on expand or separate call.

---

## F) MOBILE "SEKMELER BUTTON DOES NOT SHOW" — ROOT CAUSE MATRIX

### F.1 Event binding (handler never attached on mobile breakpoint)

- **Check:** getEventListeners(document.getElementById("adminTabsToggle")) in console (Chrome). On Safari, add temporary log inside click handler and tap.
- **Fix:** Attach in DOMContentLoaded after DOM ready; or use event delegation: document.getElementById("adminTabsHeader").addEventListener("click", function(e) { if (e.target.closest("#adminTabsToggle")) toggleAdminTabs(); }).

### F.2 CSS breakpoint (menu hidden by media query)

- **Check:** At 768px or below, computed style of .admin-tabs-list: display. Expect "none" when closed and "flex" when --open.
- **Fix:** .admin-tabs-list.admin-tabs-list--open { display: flex !important; } with sufficient specificity; ensure no other rule sets display:none on --open.

### F.3 Stacking context (z-index / transform / position)

- **Check:** List’s computed z-index; ancestors with transform/filter/opacity create new stacking context. Chrome: Layers panel.
- **Fix:** List appended to body with z-index 1000; ensure body has no transform. If modal overlay exists, set its z-index below 1000 or move list above (e.g. 10001).

### F.4 Overlay intercept (element covers button or menu)

- **Check:** document.elementFromPoint(center of toggle) and center of list after open. Should be button and list (or child).
- **Fix:** Lower z-index of overlays; or ensure toggle has position:relative and z-index above siblings; list in body with high z-index.

### F.5 Scroll/overflow clipping (container overflow hidden hides menu)

- **Check:** Before open, list’s offsetParent and ancestors’ overflow. If list is inside #adminTabsHeader and header has overflow:hidden, list can be clipped even with position:fixed if not moved.
- **Fix:** When opening on mobile, append list to document.body so it’s not inside any overflow:hidden; current code does appendChild(list) to body—verify this path runs (isMobile true, list.parentNode !== document.body).

### F.6 iOS viewport (100vh, address bar)

- **Check:** After open, list.getBoundingClientRect(); top should be visible (e.g. top >= 0 and top < innerHeight). If top is negative or below fold, adjust.
- **Fix:** Use visualViewport API: list.style.top = (toggleRect.bottom + visualViewport.offsetTop) + "px"; or use fixed px from top (e.g. 60px) instead of rect.bottom + 6 if rect is wrong.

### F.7 Touch/click (pointer events, preventDefault)

- **Check:** Toggle has pointer-events: auto; no overlay with pointer-events:none covering it. Tap: does click fire?
- **Fix:** -webkit-tap-highlight-color: transparent; touch-action: manipulation on toggle. Avoid preventDefault on click if it blocks focus/activation.

### F.8 DOM duplication (two menus; toggling wrong one)

- **Check:** document.querySelectorAll(".admin-tabs-list").length; document.querySelectorAll("#adminTabsList").length (IDs should be unique).
- **Fix:** Single element with id="adminTabsList"; remove any duplicate markup.

### F.9 Recommendation (fixed overlay appended to body)

- **Explicit:** On mobile, when opening tabs menu: (1) append .admin-tabs-list to document.body; (2) set position:fixed; left:0; right:0; top: [below appbar]; max-height: 70vh; z-index: 10001; (3) ensure no ancestor of body has transform/overflow that could affect fixed. This avoids any container clipping and stacking issues.

---

## G) TAB SWITCH UX: INSTANT SWITCH + SLIDE ANIMATION

### G.1 Active underline/slider

- **Current:** .tab-indicator is positioned by positionIndicatorToButton(list, indicator, activeBtn, noTransition). Width and transform: translate(left, -50%) from active button.
- **Improvement:** On tab click, update indicator position immediately (noTransition=false for animation). Use transition on .tab-indicator (e.g. transition: transform 0.2s, width 0.2s) so it slides. Ensure indicator is a direct child of .admin-tabs-list and has position:absolute; bottom:0; left:0; height:2px; so it doesn’t affect layout.

### G.2 Panel transitions (translateX, no heavy reflow)

- **Current:** animateAdminTabContentTransition uses opacity and transform: translateX; duration 220ms. After animation, runLoadForTab runs.
- **Improvement:** Keep panels in DOM; use visibility or pointer-events to hide inactive (avoid display:none during animation to prevent reflow). Use transform only (GPU). Avoid will-change on all panels; add will-change: transform only on active/entering panel for the duration, then remove.

### G.3 No-jank approach

- **CSS:** .admin-tab-panel { contain: layout paint; } to isolate reflow. Transition only transform and opacity.
- **JS:** RequestAnimationFrame before reading getBoundingClientRect; batch DOM writes; runLoadForTab (fetch) doesn’t block animation—fetch in parallel and render when ready.

### G.4 State machine (optional)

- States: IDLE, ANIMATING_OUT, ANIMATING_IN, LOADING, READY. On switch: IDLE → ANIMATING_OUT (fromPanel exit) → ANIMATING_IN (toPanel enter) → LOADING (runLoadForTab) → READY when data rendered. Cancel animation if switch again (ignore stale runLoadForTab using current tab key).

---

## H) BACKEND LOAD MINIMIZATION CHECKLIST (FastAPI)

### H.1 Endpoints used by admin tabs

- **accounts:** GET /api/admin/accounts (list + totals; may call spot balance per account).
- **suspended:** GET /api/admin/accounts?suspended=true.
- **pending:** GET /api/admin/pending-registrations, GET /api/admin/password-reset-requests.
- **contact:** GET /api/admin/chats; GET /api/admin/contact-messages (or similar).
- **server:** GET /api/admin/server/stats.
- **popup:** GET /api/admin/popups.
- **settings:** Minimal (no heavy list).
- **breach:** GET /api/admin/breach-alerts.

### H.2 Lightweight / batch proposals

- **GET /api/admin/bootstrap:** Returns { accounts_count, suspended_count, pending_count, contact_unread, server_summary, popup_count } in one call for initial KPI and badges. Reduces multiple round-trips on first load.
- **GET /api/admin/accounts?limit=20&offset=0&summary=0:** Paginate; summary=1 returns only counts and totals (no per-account spot balance).
- **Spot balance:** Lazy per account (e.g. GET /api/admin/accounts/:id/balance) or batch with concurrency limit server-side (already throttled per account in code).

### H.3 Caching

- Per-account or per-route cache with 5–10s TTL; ETag for GET /api/admin/accounts; If-None-Match returns 304.
- Avoid N+1: eager load User, Bot count; batch spot balance with asyncio.gather and semaphore (e.g. 2 concurrent).

### H.4 Pagination and timeouts

- Paginate accounts list (limit/offset); lazy load details. Async gather with timeout (e.g. 5s per spot balance) so one slow account doesn’t block whole response.

### H.5 Detect backend bottleneck

- Log request_id (middleware); log server_ms per endpoint. Client sends X-Request-ID; correlate with backend logs. If server_ms > 500ms for /api/admin/accounts, optimize DB and spot balance.

---

## I) DEBUG PLAYBOOK (COPY/PASTE STEPS)

### I.1 Chrome DevTools (desktop)

1. Open admin page; F12 → Network: disable cache; throttle "Fast 3G" or "Slow 3G".
2. Reload; note order and duration: whoami, boot-id, accounts, breach-alerts.
3. Performance: Record; click "Hesaplar"; stop after content visible. Find TAB_SWITCH and FETCH in timeline if instrumented; check Long Tasks.
4. Console: getEventListeners(document.getElementById("adminTabsToggle")); getEventListeners(document.querySelector(".admin-tabs-list")).
5. Elements: Inspect #adminTabsList; check computed display, visibility, z-index; check ancestors for overflow:hidden.

### I.2 Safari remote debug (iOS)

1. iPhone: Settings → Safari → Advanced → Web Inspector on. Connect USB; Mac Safari → Develop → [device] → admin page.
2. Console: add temporary console.log in toggleAdminTabs; tap "Sekmeler"; see if log appears.
3. Elements: Inspect .admin-tabs-list after tap; check class admin-tabs-list--open; computed display; parentNode (should be body when open on mobile).
4. Network: Reload admin; check which requests fire and timing.

### I.3 Network throttling

- Fast 3G: tab switch < 400ms uncached acceptable; first load < 3s.
- Slow 3G: reproduce slow "Hesaplar"; verify prefetch doesn’t block first tab.

### I.4 CPU throttling and performance recording

- Performance tab: CPU 4x slowdown; record; switch tabs; identify long tasks and layout thrash.

### I.5 HAR and console logs

- Network → right-click → Save all as HAR. Console: copy _adminLog or export performance.getEntriesByType("measure").

### I.6 Correlate with backend (request_id)

- Add header X-Request-ID: crypto.randomUUID() in fetch; backend logs request_id; match with FETCH_END request_id in client log.

### I.7 Thresholds (expected good vs bad)

- **Good:** First admin interactive < 2s desktop, < 3.5s mobile; tab switch < 100ms cached, < 400ms uncached; prefetch concurrency max 2; total requests first 10s < 10.
- **Bad:** First interactive > 4s; tab switch > 1s; > 5 concurrent fetches; duplicate fetches for same tab within 2s.

### I.8 Minimal repro (mocked endpoints)

- Replace fetch with mock: return Promise.resolve({ json: () => ({ accounts: [], totals: {...} }) }) with 100ms delay. Measure pure UI switch time. Then add real fetch and compare.

---

## J) KNOWN RACE CONDITIONS & BUG PATTERNS

1. **Multiple switchTab handlers:** If script loaded twice, inline onclick and addEventListener could both run. **Detect:** getEventListeners on button. **Fix:** Single attachment; avoid inline onclick or use only one.
2. **Async render of old tab overwrites new tab:** runLoadForTab(toKey) runs after delay; user switched to B then back to A; response for B arrives and overwrites A. **Detect:** Log tab key when rendering. **Fix:** Before render, check state.currentTab === tabKey; ignore response if not.
3. **Stale closure capturing wrong tabName:** setInterval or animation callback captures initial tabName. **Detect:** Log tabName in callback. **Fix:** Read state.currentTab inside callback.
4. **Global variable collisions:** __adminTabAnimating, __adminActiveTabKey could conflict with another script. **Detect:** Search for same names. **Fix:** Use a single admin namespace object.
5. **Promise.all without guard:** Prefetch all tabs in parallel; one 401 could reject whole batch. **Fix:** Per-tab catch; don’t reject store promise for whole preload.
6. **Missing await leading to empty DOM:** loadAccounts() not awaited so renderTiles runs before data. **Detect:** Check order of renderTiles and state.accounts assignment. **Fix:** await fetch then assign then render.
7. **Mutation observer causing loops:** If a MO updates DOM and triggers another update. **Fix:** Don’t use MO for tab content; or disconnect during batch update.
8. **setInterval refresh overlapping with tab fetch:** 5s polling loadAccounts and user-triggered loadAccounts overlap. **Detect:** inFlight check. **Fix:** Reuse in-flight promise (coalesce) instead of skipping.
9. **Auth refresh causing 401 on mobile only:** Cookie not sent. **Detect:** Compare request headers desktop vs mobile. **Fix:** credentials: "include"; CORS and SameSite.
10. **toggleAdminTabs runs but list is null:** Selector fails (e.g. typo adminTabsList vs adminTabsList). **Detect:** if (!list) return; add log. **Fix:** Use consistent ID; fallback querySelector(".admin-tabs-list").
11. **List moved to body but header still has placeholder:** If JS moves list to body, header might collapse or show empty. **Detect:** Inspect header children. **Fix:** Keep a spacer or min-height so layout doesn’t jump.
12. **resize handler moves list back too early:** On mobile, resize (e.g. orientation) fires; width > 768 restores list to header; user was on mobile menu. **Fix:** Only restore when width > 768 and list was in body; don’t restore if menu was open and we’re still in mobile breakpoint.
13. **Animation promise never resolves:** waitMs(220) rejects or animation throws. **Detect:** .catch in animateAdminTabContentTransition. **Fix:** finally { __adminTabAnimating = false; } so guard is always cleared.
14. **runLoadForTab called with undefined toKey:** fromKey/toKey from closure. **Detect:** Log toKey in runLoadForTab. **Fix:** Pass toKey explicitly at call site after animation.
15. **Cache restore overwrites fresh load:** restoreAccountsCacheFromStorage runs after loadAccounts response. **Detect:** Order of operations in DOMContentLoaded. **Fix:** Restore cache only once before first loadAccounts; or don’t restore if loadAccounts already in flight.
16. **Badge count not updated:** suspendedBadge, pendingBadge updated only when that tab loads. **Fix:** Bootstrap endpoint returns counts; update badges on init.
17. **Double toggle on double-tap:** Two quick taps open then close. **Fix:** Debounce toggle 300ms or ignore second tap within 200ms.
18. **Focus trap in modal blocks tab button:** If a modal has focus and focus trap, Tab key might not reach Sekmeler. **Fix:** Ensure modal doesn’t cover tab button; or close modal on outside click.
19. **Touch scroll triggers click:** Scroll on list triggers click on child. **Fix:** touch-action: pan-y on list; or distinguish scroll vs tap (deltaY).
20. **getBoundingClientRect in wrong frame:** rect for toggle taken before layout. **Fix:** requestAnimationFrame before reading rect when opening menu.
21. **position:fixed list inside transformed ancestor:** If body or html has transform, fixed is relative to that. **Fix:** Append list to body; ensure no transform on body.
22. **CORS preflight for admin fetch:** POST with custom headers triggers preflight; delay. **Fix:** Use simple headers where possible; backend Allow-Methods.
23. **Session expiry during long prefetch:** Token expires; subsequent requests 401. **Fix:** Check 401 in fetch wrapper; redirect to login; don’t prefetch if token near expiry.
24. **Memory leak from interval:** setInterval not cleared on page hide. **Fix:** beforeunload or visibilitychange clear intervals (already in code).
25. **Large state.accounts kept in memory:** Many accounts; no pagination. **Fix:** Paginate; or virtual list; release references when switching tab.
26. **innerHTML XSS risk:** renderTiles builds HTML from data. **Fix:** Escape account names; or use textContent / createElement.
27. **Race between restoreAccountsCacheFromStorage and switchTab:** Both run in DOMContentLoaded; switchTab triggers loadAccounts which may overwrite cache. **Fix:** Restore sync; then switchTab; loadAccounts will run and overwrite with fresh data (or use cache as initial and loadAccounts in background).
28. **Server stats interval keeps running on Server tab:** startServerStatsRefresh sets 5s interval; clear on tab switch (code clears state.serverStatsTimer in switchTab). **Verify:** Clear on switch away from server.
29. **Breach overlay blocks tab button:** If breach overlay is visible and has high z-index, tap goes to overlay. **Fix:** Ensure overlay doesn’t cover header; or close overlay when opening tabs.
30. **Tab key order wrong for a11y:** Focus order might skip menu. **Fix:** tabIndex and aria-expanded on toggle; focus trap in dropdown when open.

---

## K) ACCEPTANCE TESTS (DEFINITION OF DONE)

### K.1 Unit tests (store caching logic)

- getTabData("accounts") with fresh cache returns cached data and does not fetch.
- getTabData("accounts") with expired cache starts fetch and returns promise.
- getTabData("accounts") while fetch in flight returns same promise (coalescing).
- invalidate("accounts") clears cache; next getTabData fetches.
- TTL per tab enforced (mock Date.now).

### K.2 Integration (Playwright or manual)

- Open admin; wait for first tab visible; click "Bekleyen Onaylar"; pending content appears within 400ms (uncached) or 100ms (cached).
- Switch A → B → A; second view of A uses cache (no duplicate fetch for A within TTL).
- Network: first 10s after load, at most 10 requests; max 2 concurrent to same endpoint pattern.

### K.3 Mobile

- iOS Safari: Tap "Sekmeler"; menu opens (dropdown visible); tap "Hesaplar"; panel switches and menu closes.
- Android Chrome: Same.
- No console errors on tap; getBoundingClientRect of list visible (top/left within viewport).

### K.4 Regression

- Tab loads once; switching back within TTL does not refetch (check network).
- Stale price or slow Binance does not block admin tabs menu (menu is independent of wallet fetch).

### K.5 Metrics to log

- tab_init_ms (admin_init measure).
- tab_fetch_ms per tab (FETCH_END - FETCH_START).
- tab_render_ms (RENDER_END - RENDER_START).
- cache_hit_rate (cache_hit count / total getTabData calls).
- backend_request_count per session (increment on each fetch; log on beforeunload or periodically).

---

## L) PATCH PLAN TEMPLATE

### L.1 File paths (placeholders)

- `/ui/assets/admin.js` — tab switch, load functions, prefetch, store, instrumentation.
- `/ui/assets/core/apiClient.js` or new `/ui/assets/adminApiClient.js` — fetch wrapper with cache, inflight, abort.
- `/ui/assets/design.css` or `/ui/assets/admin-login-theme.css` — mobile menu, indicator, panel transitions.
- `/ui/admin.html` — optional: data attributes for tab content containers; ensure single #adminTabsList.
- Backend: `/app/api/admin.py` — optional bootstrap endpoint; pagination; cache headers.

### L.2 Minimal patch set (for ChatGPT to fill)

1. **apiClient fetch wrapper (admin):** Add adminApiClient.js or section in admin.js: fetch wrapper that logs (url, method, ms, status, bytes), caches by url+params with TTL, reuses in-flight promise by key, supports AbortController; cancel previous tab fetch on switch.
2. **Preload queue:** In admin.js after first paint: schedule preloadAllTabs() with requestIdleCallback or setTimeout; preloadAllTabs runs getTabData for each non-current tab with concurrency 2; getTabData uses cache or inflight or new fetch.
3. **Tab menu portal (mobile):** In toggleAdminTabs, ensure on mobile (innerWidth <= 768) when opening: appendChild(list, document.body); set position:fixed; z-index: 10001; top from getBoundingClientRect after requestAnimationFrame; ensure no ancestor of body has transform. Add fallback if list is null (querySelector).
4. **Animation slider:** Keep positionIndicatorToButton; add CSS transition on .tab-indicator for transform and width; call positionIndicatorToButton with transition enabled on tab click.
5. **Instrumentation:** Add performance marks (admin_init_start/ready, TAB_SWITCH_START/END, FETCH_START/END, RENDER_START/END); central adminLog(event, data); wrap fetch with adminFetch (log + optional abort). Log cache_hit and request_id.

### L.3 Backend (optional)

- Add GET /api/admin/bootstrap returning { accounts_count, suspended_count, pending_count, ... }.
- Add Cache-Control or ETag for GET /api/admin/accounts.
- Add ?limit=&offset= for accounts list; lazy spot balance or batch with limit.

---

## M) ADDITIONAL BOTTLENECK HYPOTHESES (31–45)

31. **Symptom:** LCP delayed. **Cause:** #tilesContainer shows "Loading..." until fetch; no skeleton. **Verify:** LCP element in Lighthouse. **Fix:** Skeleton tiles or cached HTML for LCP.
32. **Symptom:** Main thread blocked > 50ms. **Cause:** JSON.parse of large accounts array. **Verify:** Performance recording; Scripting time. **Fix:** Chunk parse; or stream; or smaller payload.
33. **Symptom:** FID high. **Cause:** Click handler does sync work (positionIndicatorToButton reads layout). **Verify:** FID in Lighthouse. **Fix:** requestAnimationFrame before layout read; or defer indicator update.
34. **Symptom:** Multiple boot-id requests. **Cause:** Redirect or retry. **Verify:** Network filter boot-id. **Fix:** Single boot-id; no redirect loop.
35. **Symptom:** renderTiles takes > 100ms. **Cause:** Large innerHTML; many DOM nodes. **Verify:** Performance mark around renderTiles. **Fix:** DocumentFragment; batch append; or virtual list.
36. **Symptom:** Reflow when showing panel. **Cause:** .tab-content.active display:block triggers layout. **Verify:** Layout boundaries in Performance. **Fix:** contain: layout; or visibility/opacity instead of display during transition.
37. **Symptom:** Font blocking. **Cause:** Google Fonts sync or render-blocking. **Verify:** Network priority of fonts. **Fix:** font-display: swap; preload; async.
38. **Symptom:** Script blocking parse. **Cause:** admin.js without defer/async. **Verify:** Script position and attributes in admin.html. **Fix:** defer on admin.js.
39. **Symptom:** Waterfall: accounts then breach. **Cause:** fetchBreachAlerts after DOMContentLoaded; not parallel with loadAccounts. **Verify:** Network timing. **Fix:** Start breach fetch in parallel with accounts (no await order).
40. **Symptom:** Polling refetches even when tab not visible (user switched tab/window). **Cause:** No visibility check. **Verify:** Switch browser tab; check network. **Fix:** if (document.visibilityState === "visible") loadAccounts().
41. **Symptom:** Session storage quota. **Cause:** Large accounts cache in sessionStorage. **Verify:** sessionStorage.length; size. **Fix:** Limit cache size; or skip cache if > N KB.
42. **Symptom:** Backend spot balance timeout. **Cause:** Binance API slow; no timeout on _get_spot_balance_for_account. **Verify:** Server logs per-account duration. **Fix:** asyncio.wait_for(..., 5.0).
43. **Symptom:** Duplicate runLoadForTab. **Cause:** animateAdminTabContentTransition and direct call both invoke runLoadForTab. **Verify:** Log runLoadForTab count per switch. **Fix:** Single call site after animation.
44. **Symptom:** Tab indicator jumps. **Cause:** positionIndicatorToButton called before panel visible; getBoundingClientRect wrong. **Verify:** Indicator left/width after switch. **Fix:** requestAnimationFrame before positionIndicatorToButton.
45. **Symptom:** Mobile menu closes on scroll. **Cause:** Scroll event or touchmove closes dropdown. **Verify:** Scroll while menu open. **Fix:** Don’t close on scroll; only on click outside or tab tap.

---

## N) MOBILE ROOT CAUSE MATRIX (10–25)

10. **Touch target too small:** Toggle height < 44px. **Check:** getBoundingClientRect().height of #adminTabsToggle. **Fix:** min-height: 44px; padding 12px (already in design.css).
11. **Button disabled or aria-disabled:** **Check:** toggle.disabled; getAttribute("aria-disabled"). **Fix:** Ensure not disabled.
12. **Another element capturing touch:** Overlay or invisible div. **Check:** elementFromPoint(centerX, centerY) when tapping toggle. **Fix:** Lower z-index of overlay; or pointer-events: none on overlay when menu closed.
13. **preventDefault on touchstart elsewhere:** Global handler calls preventDefault. **Check:** Search for touchstart in admin.js and other scripts. **Fix:** Remove or narrow preventDefault.
14. **List visibility: hidden:** **Check:** getComputedStyle(list).visibility. **Fix:** visibility: visible when --open.
15. **List opacity: 0:** **Check:** getComputedStyle(list).opacity. **Fix:** opacity: 1 when --open.
16. **List width or height 0:** **Check:** getBoundingClientRect().width/height. **Fix:** width: auto; min-height when open.
17. **Transform leaves list off-screen:** **Check:** getComputedStyle(list).transform. **Fix:** Don’t apply transform that moves list off-viewport when open.
18. **Clip-path or clip:** **Check:** getComputedStyle(list).clipPath, .clip. **Fix:** none when open.
19. **List in iframe:** **Check:** list.ownerDocument !== document. **Fix:** N/A if no iframe; ensure admin runs in top frame.
20. **Safe area insets:** Notch or home indicator covers list. **Check:** list.getBoundingClientRect().bottom vs visualViewport.height. **Fix:** padding-bottom: env(safe-area-inset-bottom); max-height: calc(70vh - env(safe-area-inset-bottom)).
21. **Orientation change during open:** List positioned for portrait; device rotates. **Check:** Resize handler restores list to header at >768; on mobile after rotate might be >768. **Fix:** On resize, if still mobile and menu open, reposition list (getBoundingClientRect again).
22. **Focus moved to body:** After appendChild(list), focus might move; keyboard user can’t tab to menu. **Fix:** list.setAttribute("tabIndex", -1); list.focus() when open for a11y.
23. **Scroll position:** Page scrolled; toggle.getBoundingClientRect() is viewport-relative; list.top = rect.bottom + 6 might be above viewport if page scrolled. **Check:** rect.bottom + 6 vs visualViewport.height. **Fix:** Use visualViewport.offsetTop + rect.bottom or ensure list.top within viewport.
24. **Pseudo-element covering list:** ::before/::after on parent with high z-index. **Check:** Computed styles of list’s previousElementSibling. **Fix:** Lower z-index of pseudo or list higher.
25. **Browser autofill or native overlay:** Safari address bar or autofill covers top. **Check:** visualViewport.height vs innerHeight. **Fix:** Position list with margin from top; or use fixed px from top (e.g. 56px) for menu.

---

## O) ADDITIONAL BUG PATTERNS (31–50)

31. **runLoadForTab not defined in scope:** If script split, runLoadForTab might be in closure. **Detect:** ReferenceError on switch. **Fix:** Expose on window or ensure same scope.
32. **state.currentTab out of sync:** Tab switched but state not updated (e.g. error before assignment). **Detect:** Log state.currentTab in runLoadForTab. **Fix:** Set state.currentTab at start of switchTab.
33. **Animation end fires after unmount:** Panel removed from DOM before animation end. **Detect:** toPanel.isConnected in waitMs callback. **Fix:** Check isConnected before runLoadForTab.
34. **Cache key collision:** sessionStorage key same for different users. **Detect:** Key includes user id. **Fix:** ADMIN_ACCOUNTS_CACHE_KEY + "_" + userId.
35. **Polling clears cache:** loadAccounts overwrites sessionStorage; another tab might have had newer data. **Fix:** Only write cache when response is for current tab and user.
36. **AbortController not supported:** Old browser. **Detect:** typeof AbortController. **Fix:** Polyfill or skip abort.
37. **requestIdleCallback not supported:** **Detect:** typeof requestIdleCallback. **Fix:** setTimeout(fn, 1).
38. **performance.mark not supported:** **Detect:** performance.mark. **Fix:** try/catch; no-op.
39. **getTabData called before store init:** **Detect:** store undefined. **Fix:** Init store before any getTabData; or lazy init.
40. **Concurrency limit race:** Two tabs start; limit 2; one finishes; third starts before first’s promise stored. **Fix:** Decrement inFlight in finally; check inFlight before starting.
41. **TTL timezone:** Date.now() vs server time. **Fix:** Use client Date.now() consistently.
42. **Stale closure in click-outside:** Handler captures list reference; list moved to body so list.parentNode changed. **Fix:** Query list inside handler (e.target.closest).
43. **toggleAdminTabs called without user gesture:** Programmatic open; some browsers block. **Fix:** Only open on click/touch.
44. **Multiple resize handlers:** Another script also listens resize; restores list to wrong place. **Detect:** getEventListeners(window) for resize. **Fix:** Single handler; or namespace.
45. **Panel data-tab-panel typo:** Mismatch with tab key (e.g. "account" vs "accounts"). **Detect:** querySelector returns null. **Fix:** Align keys with HTML.
46. **Fetch error not handled:** loadAccounts catch only logs; UI stays "Loading...". **Fix:** Show error state; retry button.
47. **inFlight never cleared on error:** state.inFlight = true; fetch throws; state.inFlight not set false. **Fix:** finally { state.inFlight = false; }.
48. **Badge update race:** loadPendingRegistrations and loadAccounts both update badges. **Fix:** Single source; bootstrap or dedicated badge endpoint.
49. **localStorage full:** sessionStorage setItem throws. **Fix:** try/catch; skip cache write on quota error.
50. **CSP blocks inline onclick:** Content-Security-Policy script-src 'self' blocks inline. **Detect:** Console CSP error. **Fix:** addEventListener instead of onclick; or CSP nonce.

---

## P) INSTRUMENTATION CODE SNIPPETS (DETAILED)

### P.1 Performance marks (full list)

```javascript
var ADMIN_PERF = {
  mark: function(n) { try { performance.mark(n); } catch (e) {} },
  measure: function(n, s, e) { try { performance.measure(n, s, e); } catch (err) {} },
  marks: ["admin_init_start", "admin_init_ready", "admin_first_paint", "TAB_SWITCH_START", "TAB_SWITCH_END", "TAB_LOAD_START", "TAB_LOAD_END", "FETCH_START", "FETCH_END", "RENDER_START", "RENDER_END"]
};
```

### P.2 Measure after DOMContentLoaded critical path

```javascript
document.addEventListener("DOMContentLoaded", function() {
  ADMIN_PERF.mark("admin_init_start");
  // ... whoami, boot-id, visibility ...
  ADMIN_PERF.mark("admin_init_ready");
  ADMIN_PERF.measure("admin_init_total", "admin_init_start", "admin_init_ready");
  if (window.performance && performance.getEntriesByType) {
    var m = performance.getEntriesByType("measure").pop();
    if (m) console.debug("[ADMIN_PERF] admin_init_total", m.duration);
  }
});
```

### P.3 Tab switch measure

```javascript
function switchTab(tabName) {
  var startMark = "TAB_SWITCH_START_" + tabName;
  var endMark = "TAB_SWITCH_END_" + tabName;
  ADMIN_PERF.mark(startMark);
  // ... existing switch logic ...
  animateAdminTabContentTransition(...).then(function() {
    ADMIN_PERF.mark(endMark);
    ADMIN_PERF.measure("TAB_SWITCH_" + tabName, startMark, endMark);
  });
}
```

### P.4 Fetch measure and log

```javascript
function measuredFetch(url, opts, tabName) {
  var id = "r" + Date.now();
  var start = performance.now();
  ADMIN_PERF.mark("FETCH_START_" + tabName);
  return fetch(url, opts).then(function(r) {
    var dur = performance.now() - start;
    ADMIN_PERF.mark("FETCH_END_" + tabName);
    ADMIN_PERF.measure("FETCH_" + tabName, "FETCH_START_" + tabName, "FETCH_END_" + tabName);
    adminLog("FETCH_END", { tab: tabName, url: url, status: r.status, duration_ms: Math.round(dur), request_id: id });
    return r;
  });
}
```

### P.5 Export measures for HAR/correlation

```javascript
window.getAdminPerfMeasures = function() {
  return performance.getEntriesByType("measure").filter(function(m) { return m.name.indexOf("TAB_") === 0 || m.name.indexOf("FETCH_") === 0 || m.name === "admin_init_total"; });
};
```

---

## Q) BACKEND ENDPOINT CHECKLIST (DETAILED)

- GET /api/auth/whoami — called on init if no token; keep lightweight; cache 0.
- GET /api/boot-id — called on init; return static or low-cost; cache 0.
- GET /api/admin/accounts — main bottleneck; add ?limit=&offset=; add ?summary=1 for KPI only; Cache-Control: private, max-age=10; consider ETag from accounts hash.
- GET /api/admin/accounts?suspended=true — same as above; cache 10s.
- GET /api/admin/pending-registrations — cache 15s; paginate if large.
- GET /api/admin/password-reset-requests — combine with pending in one response or same cache window.
- GET /api/admin/chats — list only; cache 30s; messages on demand.
- GET /api/admin/server/stats — cache 5s; lightweight.
- GET /api/admin/popups — cache 60s.
- GET /api/admin/breach-alerts — cache 0 (security); keep fast.
- POST endpoints — no cache; ensure idempotency where applicable.
- N+1: get_admin_accounts joins User; ensure no per-account query in loop; batch spot balance with asyncio.gather and semaphore(2).
- Timeout: apply asyncio.wait_for(..., 5.0) to each spot balance call.
- Logging: middleware to log request_id, path, method, status, duration_ms; correlate with client FETCH_END.

---

## R) DEBUG PLAYBOOK (MOBILE SPECIFIC)

- Safari iOS: Develop → [device] → [page]; Console and Elements.
- Reproduce: Tap "Sekmeler". If nothing happens: Add at top of toggleAdminTabs: console.log("toggleAdminTabs"); alert("toggle"); (remove alert after). If no log, click handler not firing.
- Check list: In Console run document.querySelector(".admin-tabs-list").getBoundingClientRect() before tap. After tap run again; check top, left, width, height. If width/height 0, display or size issue.
- Check class: After tap run document.querySelector(".admin-tabs-list").classList.contains("admin-tabs-list--open"). Must be true.
- Check parent: After tap run document.querySelector(".admin-tabs-list").parentNode.tagName. Expect "BODY".
- Check z-index: getComputedStyle(document.querySelector(".admin-tabs-list")).zIndex. Expect "1000" or "10001".
- Check overlay: document.elementFromPoint(innerWidth/2, 100). Should be list or child when menu open.
- Throttling: Network tab → Slow 3G; reload; tap Sekmeler; menu should still open (no network dependency).
- Orientation: Rotate device with menu open; menu should reposition or close (per product choice).

---

## S) ACCEPTANCE TEST STEPS (MANUAL CHECKLIST)

- [ ] Desktop: Open admin; within 2s see accounts or loading skeleton; within 4s see accounts data.
- [ ] Desktop: Click "Bekleyen Onaylar"; within 500ms see pending list or loading.
- [ ] Desktop: Click "Hesaplar" again; within 100ms see accounts (cached).
- [ ] Desktop: Network: No duplicate /api/admin/accounts within 2s of first load.
- [ ] Mobile (375px): Tap "Sekmeler"; within 300ms dropdown visible with all tab labels.
- [ ] Mobile: Tap "Hesaplar" in dropdown; panel switches to accounts; dropdown closes.
- [ ] Mobile: Tap outside dropdown; dropdown closes.
- [ ] Mobile: No console errors on any tap.
- [ ] Regression: After prefetch, switch to Server then back to Accounts; accounts from cache (no new fetch if TTL not expired).
- [ ] Regression: Stale price or slow /api/admin/accounts does not prevent "Sekmeler" tap from opening menu.

---

## T) CSS COMPUTED STYLE CHECKS (MOBILE MENU)

Run in console when menu should be open (after tap):

- getComputedStyle(document.querySelector(".admin-tabs-list")).display === "flex"
- getComputedStyle(document.querySelector(".admin-tabs-list")).visibility !== "hidden"
- getComputedStyle(document.querySelector(".admin-tabs-list")).opacity !== "0"
- getComputedStyle(document.querySelector(".admin-tabs-list")).position === "fixed"
- getComputedStyle(document.querySelector(".admin-tabs-list")).zIndex (numeric) >= 1000
- document.querySelector(".admin-tabs-list").parentNode === document.body
- document.querySelector(".admin-tabs-list").getBoundingClientRect().height > 0
- document.querySelector(".admin-tabs-list").getBoundingClientRect().top >= 0
- document.querySelector(".admin-tabs-list").getBoundingClientRect().bottom <= window.innerHeight (or visualViewport.height)

If any fails, fix the corresponding rule or JS.

---

## U) REQUEST COALESCING PSEUDO-CODE

```javascript
var inflightByTab = {};
function getTabData(tab) {
  if (inflightByTab[tab]) return inflightByTab[tab];
  var p = fetchTab(tab).then(function(data) {
    inflightByTab[tab] = null;
    return data;
  }).catch(function(e) {
    inflightByTab[tab] = null;
    throw e;
  });
  inflightByTab[tab] = p;
  return p;
}
```

---

## V) CONCURRENCY LIMIT PSEUDO-CODE

```javascript
var queue = [];
var inFlight = 0;
var limit = 2;
function runQueue() {
  while (inFlight < limit && queue.length) {
    var tab = queue.shift();
    inFlight++;
    getTabData(tab).finally(function() { inFlight--; runQueue(); });
  }
}
function preloadAllTabs() {
  ["pending", "suspended", "contact", "server", "popup", "settings"].forEach(function(t) {
    if (t !== state.currentTab) queue.push(t);
  });
  runQueue();
}
```

---

## W) EXACT DOM QUERIES FOR DIAGNOSIS (COPY-PASTE IN CONSOLE)

- document.getElementById("adminTabsToggle") — must not be null.
- document.getElementById("adminTabsList") — must not be null; single element.
- document.querySelectorAll(".admin-tabs-list").length — must be 1.
- document.querySelector("#adminTabsHeader .admin-tabs-list") === document.getElementById("adminTabsList") — true.
- document.querySelector(".admin-tabs-list").parentNode.id — "adminTabsHeader" when closed on desktop; when open on mobile after toggle, parentNode.tagName === "BODY".
- document.querySelector(".tab-btn.active").getAttribute("data-tab") — current tab key.
- document.querySelectorAll(".admin-tab-panel.active").length — must be 1.
- document.querySelector('.admin-tab-panel[data-tab-panel="accounts"]').classList.contains("active") — true when on accounts.
- document.getElementById("tilesContainer").innerHTML.length — size of tiles HTML; if very large, render cost high.
- getEventListeners(document.getElementById("adminTabsToggle")) — click handler count; expect 1.
- getEventListeners(document.querySelector(".admin-tabs-list")) — if any, note which events.
- window.switchTab — must be function.
- window.toggleAdminTabs — must be function.
- typeof __adminTabAnimating — "boolean" when script loaded.
- state.currentTab (if state exposed) — string matching active tab.

---

## X) NETWORK TAB INTERPRETATION

- Filter: "admin" or "api". Order: whoami → boot-id → accounts → breach-alerts on first load.
- If accounts request is "stalled" or "pending" long: server or browser connection limit; check whether 6 connections per origin exhausted.
- If accounts response is large (> 100 KB): consider payload size; backend pagination.
- If multiple accounts requests with same cb= or no cb: duplicate calls; add coalescing.
- If 401 on whoami or accounts: token/cookie issue; check Authorization header and credentials.
- If 304 on accounts: cache working; verify Cache-Control and If-None-Match.
- Timing: Time to first byte (TTFB) for accounts; if > 1s, backend or network.
- Waterfall: pending and password-reset sequential; can run in parallel (Promise.all).

---

## Y) PERFORMANCE RECORDING STEPS (CHROME)

- Open Performance tab; enable "Screenshots" and "Web Vitals".
- Click Record; switch to admin page (or reload); wait for accounts to appear; click "Bekleyen Onaylar"; wait for content; stop recording.
- Look for: Long Task (red triangle); Layout (purple); Recalc Style (purple); Scripting (yellow) > 50ms.
- Identify: Which function in Scripting? Expand Main; find loadAccounts or renderTiles.
- Check: LCP marker; FCP marker; when they occur relative to fetch end.
- Compare: With and without cache (clear cache, reload, record again).
- Mobile simulation: Device toolbar 375x667; throttle CPU 4x; record same steps.

---

## Z) SKELETON UI SPEC (INSTANT SWITCH)

- For accounts: 6–8 placeholder cards (same structure as tile, but gray block); container has data-skeleton attribute.
- On switchTab(tab): Immediately show panel and render skeleton for that tab (if no cached data); then getTabData(tab).then(data => renderTab(tab, data)); when data arrives, replace skeleton with real content; remove data-skeleton.
- Skeleton HTML: e.g. <div class="tile-skeleton" data-skeleton><div class="tile-skeleton-line"></div><div class="tile-skeleton-line short"></div></div> repeated.
- CSS: .tile-skeleton { animation: skeleton-pulse 1.5s ease-in-out infinite; } to avoid layout shift when replacing with real tiles.
- Ensures: Tab switch is instant (no wait for fetch); user sees structure immediately.

---

## AA) INVALIDATION RULES (CACHE)

- After createAccount(): invalidate("accounts"); optionally invalidate bootstrap.
- After suspendUser(): invalidate("accounts"); invalidate("suspended").
- After approveRegistration(): invalidate("pending"); invalidate("accounts").
- After contact reply: invalidate("contact").
- After popup create/delete: invalidate("popup").
- On 401 from any admin endpoint: clear all caches; redirect to login.
- TTL expiry: getTabData checks (Date.now() - entry.ts) < TTL[tab]; else fetch.

---

## AB) MOBILE MENU FIX CHECKLIST (ORDERED)

1. Verify #adminTabsToggle exists and has click listener (event delegation fallback if direct attach fails).
2. In toggleAdminTabs, first line: if (!list || !toggle) return; add else log to confirm list and toggle found.
3. When isOpen && isMobile: ensure list.parentNode !== document.body then document.body.appendChild(list); then set position, left, right, top, maxHeight, zIndex; use requestAnimationFrame before getBoundingClientRect if layout might be stale.
4. CSS: .admin-tabs-list.admin-tabs-list--open { display: flex !important; } with .page-admin prefix; ensure no other rule sets display:none for --open.
5. Ensure no parent of body has transform (would make fixed relative to that parent).
6. z-index 10001 so above appbar (e.g. 1000) and breach overlay.
7. Test: Tap Sekmeler; in console list.parentNode.tagName; list.getBoundingClientRect(); list.classList.contains("admin-tabs-list--open").
8. If menu still not visible: try position list in a dedicated overlay div (id="adminTabsOverlay") that is direct child of body, position:fixed, inset:0, z-index:10000, pointer-events:none; list inside with pointer-events:auto; so overlay doesn’t block but contains list.
9. Touch: Add touch-action: manipulation to #adminTabsToggle and .admin-tabs-list to reduce 300ms delay.
10. Fallback: If appendChild to body causes layout issues, create a portal container: <div id="adminTabsPortal"></div> at end of body in HTML; append list to adminTabsPortal; portal has position:fixed; inset:0; z-index:10001; pointer-events:none; list pointer-events:auto.

---

## AC) PREFETCH PRIORITY ORDER

- High (first): accounts (already loaded on init; skip in preload).
- High: pending (user often checks); suspended (admin workflow).
- Medium: contact (chats); server (stats).
- Low: popup; settings.
- Order in queue: ["pending", "suspended", "contact", "server", "popup", "settings"]; filter out state.currentTab; run with concurrency 2.

---

## AD) THRESHOLDS (NUMERIC)

- admin_init_total: good < 1500ms; bad > 3000ms.
- TAB_SWITCH_* (animation only): good < 250ms; bad > 500ms.
- FETCH_accounts: good < 800ms; bad > 2000ms.
- FETCH_pending: good < 500ms; bad > 1500ms.
- tab_render_ms (renderTiles): good < 100ms; bad > 300ms.
- First Contentful Paint: good < 1.5s; bad > 3s.
- Time to Interactive (TTI): good < 2.5s desktop, < 4s mobile; bad > 5s.
- Cache hit rate: good > 0.5 after 3 tab switches; bad 0.
- Concurrent fetches: good max 2; bad > 3 simultaneous to same host.

---

## AE) FILE PATH REFERENCE (PROJECT)

- Admin HTML: ui/admin.html
- Admin script: ui/assets/admin.js
- Admin styles: ui/assets/design.css (lines ~924–965 tabs; ~1180–1243 mobile), ui/assets/admin-login-theme.css
- Backend admin routes: app/api/admin.py
- Optional API client: ui/assets/core/apiClient.js (if shared); or inline in admin.js

---

## AF) RACE CONDITION: ANIMATION VS SWITCH

- Scenario: User clicks A → B; animateAdminTabContentTransition(fromKey=A, toKey=B) starts; before 220ms user clicks C; animation for B completes and runLoadForTab(B) runs; then user is on C but B’s data loads.
- Detection: Log in runLoadForTab: "runLoadForTab", tabName, "state.currentTab", state.currentTab; if tabName !== state.currentTab, ignore.
- Fix: At start of runLoadForTab(toKey), check if (state.currentTab !== toKey) return; before any fetch or render. Optionally abort in-flight fetch for toKey if state.currentTab changed.

---

## AG) LOGGING PAYLOAD (MINIMAL)

- TAB_SWITCH_START: { tab: string, from: string, ts: number }
- TAB_SWITCH_END: { tab: string, duration_ms: number, ts: number }
- FETCH_START: { tab: string, url: string, request_id: string, ts: number }
- FETCH_END: { tab: string, url: string, request_id: string, status: number, duration_ms: number, size_bytes: number | null, cache_hit: boolean, ts: number }
- RENDER_END: { tab: string, duration_ms: number, item_count: number, ts: number }
- Store last 100 entries; expose window.getAdminPerfLog() for export.

---

## AH) BACKEND BOOTSTRAP RESPONSE SHAPE

- GET /api/admin/bootstrap → { accounts_count: number, suspended_count: number, pending_registrations_count: number, password_reset_count: number, contact_unread_count: number, server_ok: boolean, popups_count: number }
- Client: On init, call bootstrap; update KPI strip and badges; then prefetch full tab data in background. Reduces first-paint dependency on full accounts list.

---

## AI) WILL-CHANGE USAGE

- Do not set will-change on all panels permanently (memory cost).
- During animateAdminTabContentTransition: toPanel.style.willChange = "transform, opacity"; after transition end: toPanel.style.willChange = ""; same for fromPanel.
- .tab-indicator: can use will-change: transform; if indicator animates often; remove when idle.

---

## AJ) DEFINITION OF DONE (SUMMARY)

- Desktop: First admin interactive < 2s; tab switch to cached tab < 100ms; to uncached < 400ms.
- Mobile: "Sekmeler" tap opens menu in < 300ms; menu visible and tappable; no console errors.
- Preload: Within 10s of load, all tab data requested with max 2 concurrent; cache used on revisit.
- No duplicate fetches for same tab within TTL.
- Instrumentation: Marks and measures in place; adminLog or equivalent; request_id correlation possible.
- Backend: Optional bootstrap; accounts paginated or cached; spot balance batched or lazy.
- Dossier used to verify each hypothesis and apply fixes from sections E, F, L, and AB.

---

## AK) QUICK REFERENCE: KEY SELECTORS AND FUNCTIONS

- Toggle button: #adminTabsToggle or .admin-tabs-toggle
- Tabs list: #adminTabsList or .admin-tabs-list
- Open state class: .admin-tabs-list--open
- Tab buttons: .tab-btn, .tab-btn.active, .tab-btn[data-tab="accounts"]
- Panels: .admin-tab-panel[data-tab-panel="accounts"], #tabAccounts
- Global functions: window.switchTab(tabName), window.toggleAdminTabs()
- State: state.currentTab, state.accounts, state.inFlight
- Load functions: loadAccounts(force), loadSuspendedAccounts(force), loadPendingRegistrations(), loadContactMessages(), loadServerStats(), loadPopupsList(), loadAdminSettings()
- runLoadForTab(tabName) dispatches to load*; called at end of animateAdminTabContentTransition
- initAdminTabsSlider() positions .tab-indicator; called once on DOMContentLoaded
- closeAdminTabsDropdown() removes --open, restores list to header, clears inline styles
- Breakpoint: 768px (design.css .page-admin media max-width: 768px)
- Cache key: ADMIN_ACCOUNTS_CACHE_KEY in sessionStorage; TTL ADMIN_ACCOUNTS_CACHE_MAX_AGE_MS (5 min)
- Polling: 5s for loadAccounts when currentTab === 'accounts'; 15s for fetchBreachAlerts
- Animation duration: 220ms in animateAdminTabContentTransition; easing cubic-bezier(0.2, 0.8, 0.2, 1)

---

## AL) HAR EXPORT AND CORRELATION

- Chrome Network tab → Right-click → Save all as HAR with content.
- In HAR: Find entries for /api/admin/*; note request.requestId or response.headers X-Request-ID; note time (startedDateTime), duration (response.bodySize).
- Client: Ensure adminLog("FETCH_END", { request_id: id }) uses same id as X-Request-ID header if sent; correlate with HAR entry by URL and timestamp.
- Backend: Log request_id in middleware; on slow request (> 1s) log request_id, path, duration; match with client FETCH_END for same request_id to confirm server-side slowness.

---

## AM) CONTENT SECURITY POLICY (CSP) AND INLINE HANDLERS

- If CSP blocks inline onclick: switchTab and other handlers must be bound via addEventListener. In admin.js after DOM ready: document.querySelectorAll(".tab-btn").forEach(function(btn) { var tab = btn.getAttribute("data-tab"); if (tab) btn.addEventListener("click", function() { switchTab(tab); }); }); then remove onclick from HTML or keep for no-JS fallback (no-op if addEventListener used).
- Same for #adminTabsToggle: current code uses addEventListener in DOMContentLoaded; if HTML had onclick="toggleAdminTabs()" and CSP blocks it, addEventListener is the only way; ensure no duplicate binding.

---

*End of dossier. Use this document to diagnose slow "Hesaplar" load, late tab content, and mobile "Sekmeler" menu not showing; then implement preload, cache, and mobile menu fix per sections E, F, and L.*
