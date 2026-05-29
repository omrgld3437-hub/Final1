/**
 * FILE: admin.js
 * VERSION: v18
 * DATE: 2026-01-22
 * CHANGE: Fix account deletion error handling - reset button state on error, show proper error messages
 */

const state = {
    accounts: [],
    accountsTotals: null,
    suspendedAccounts: [],
    filteredAccounts: [],
    inFlight: false,
    timer: null,
    currentTab: 'accounts',  // 'accounts' | 'suspended' | 'pending' | 'contact' | 'server' | 'settings'
    deleteTargetId: null,
    settingsAccount: null,
    serverStatsTimer: null,
    errorLogsResetAfterId: null,  // Sıfırdan sonra sadece id > bu değer; ilk gelen hata #1
    switchToken: 0  // Monotonic counter to ignore stale tab load responses
};

/** Admin tab data store: cache + TTL + inflight coalescing + abort. */
const AdminStore = {
    cache: {
        accounts: { data: null, ts: 0, inflight: null, abort: null },
        pending: { data: null, ts: 0, inflight: null, abort: null },
        suspended: { data: null, ts: 0, inflight: null, abort: null },
        contact: { data: null, ts: 0, inflight: null, abort: null },
        server: { data: null, ts: 0, inflight: null, abort: null },
        popup: { data: null, ts: 0, inflight: null, abort: null },
        settings: { data: null, ts: 0, inflight: null, abort: null }
    },
    TTL: {
        accounts: 300000,
        pending: 30000,
        suspended: 30000,
        contact: 60000,
        server: 10000,
        popup: 60000,
        settings: 300000
    },
    get: function (tab, fetcher, opts) {
        opts = opts || {};
        var entry = this.cache[tab];
        if (!entry) return Promise.reject(new Error('Unknown tab: ' + tab));
        var ttl = this.TTL[tab] || 60000;
        var staleMaxMs = tab === 'accounts' ? ADMIN_ACCOUNTS_CACHE_MAX_AGE_MS : 0;
        var now = Date.now();
        if (entry.data !== null && (now - entry.ts) < ttl) {
            return Promise.resolve(entry.data);
        }
        if (entry.data !== null && staleMaxMs > 0 && (now - entry.ts) < staleMaxMs) {
            if (!entry.inflight) {
                var bgController = typeof AbortController !== 'undefined' ? new AbortController() : null;
                entry.abort = bgController;
                entry.inflight = fetcher(bgController ? bgController.signal : null)
                    .then(function (data) {
                        entry.data = data;
                        entry.ts = Date.now();
                        entry.inflight = null;
                        entry.abort = null;
                        if (typeof opts.onRefresh === 'function') opts.onRefresh(data);
                        return data;
                    })
                    .catch(function (err) {
                        entry.inflight = null;
                        entry.abort = null;
                        throw err;
                    });
            }
            return Promise.resolve(entry.data);
        }
        if (entry.inflight) return entry.inflight;
        var controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
        entry.abort = controller;
        var self = this;
        var p = fetcher(controller ? controller.signal : null)
            .then(function (data) {
                entry.data = data;
                entry.ts = Date.now();
                entry.inflight = null;
                entry.abort = null;
                return data;
            })
            .catch(function (err) {
                entry.inflight = null;
                entry.abort = null;
                throw err;
            });
        entry.inflight = p;
        return p;
    },
    abort: function (tab) {
        var entry = this.cache[tab];
        if (entry && entry.abort && entry.abort.abort) entry.abort.abort();
    },
    invalidate: function (tab) {
        var entry = this.cache[tab];
        if (entry) {
            entry.data = null;
            entry.ts = 0;
            entry.inflight = null;
            if (entry.abort && entry.abort.abort) entry.abort.abort();
            entry.abort = null;
        }
    }
};

function invalidateAccountsAndSuspendedCache() {
    AdminStore.invalidate('accounts');
    AdminStore.invalidate('suspended');
    adminClearAccountsCache();
}

/** Guard: same tap that opens menu must not close it (click-outside). */
var adminTabsJustOpenedAt = 0;
var adminTabsLastToggleRunAt = 0;

var ADMIN_ACCOUNTS_CACHE_KEY = 'admin_accounts_cache_v2';
var ADMIN_ACCOUNTS_CACHE_MAX_AGE_MS = 5 * 60 * 1000;

function adminReadAccountsCacheRaw() {
    try {
        return sessionStorage.getItem(ADMIN_ACCOUNTS_CACHE_KEY) || localStorage.getItem(ADMIN_ACCOUNTS_CACHE_KEY);
    } catch (e) {
        return null;
    }
}

function adminWriteAccountsCache(payload) {
    var raw = JSON.stringify(payload);
    try { sessionStorage.setItem(ADMIN_ACCOUNTS_CACHE_KEY, raw); } catch (e) {}
    try { localStorage.setItem(ADMIN_ACCOUNTS_CACHE_KEY, raw); } catch (e) {}
}

function adminClearAccountsCache() {
    try { sessionStorage.removeItem(ADMIN_ACCOUNTS_CACHE_KEY); } catch (e) {}
    try { localStorage.removeItem(ADMIN_ACCOUNTS_CACHE_KEY); } catch (e) {}
}

function restoreAccountsCacheFromStorage() {
    try {
        var raw = adminReadAccountsCacheRaw();
        if (!raw) return false;
        var c = JSON.parse(raw);
        if (Date.now() - (c.ts || 0) > ADMIN_ACCOUNTS_CACHE_MAX_AGE_MS) return false;
        if (!Array.isArray(c.accounts) || c.accounts.length === 0) return false;
        state.accounts = c.accounts;
        state.accountsTotals = c.totals || null;
        var container = document.getElementById('tilesContainer');
        if (container) renderTiles(state.accounts, container);
        if (state.accountsTotals) renderKpis(state.accountsTotals);
        AdminStore.cache.accounts.data = { accounts: state.accounts, totals: state.accountsTotals };
        AdminStore.cache.accounts.ts = c.ts || Date.now();
        return true;
    } catch (e) {
        return false;
    }
}

function adminAccountsHasDisplayCache() {
    if (state.accounts.length > 0) return true;
    var entry = AdminStore.cache.accounts;
    if (entry && entry.data && (Date.now() - entry.ts) < ADMIN_ACCOUNTS_CACHE_MAX_AGE_MS) return true;
    try {
        var raw = adminReadAccountsCacheRaw();
        if (!raw) return false;
        var c = JSON.parse(raw);
        return Array.isArray(c.accounts) && c.accounts.length > 0
            && (Date.now() - (c.ts || 0)) < ADMIN_ACCOUNTS_CACHE_MAX_AGE_MS;
    } catch (e) {
        return false;
    }
}

function adminAuthHeaders() {
    var tok = sessionStorage.getItem('token');
    var h = { 'Content-Type': 'application/json' };
    if (tok) h['Authorization'] = 'Bearer ' + tok;
    if (typeof document !== 'undefined' && document.cookie) {
        var csrfMatch = document.cookie.match(/\bcsrf_token=([^;]+)/);
        if (csrfMatch && csrfMatch[1]) h['X-CSRF-Token'] = csrfMatch[1].trim();
    }
    return h;
}

function adminFetchJSON(url, opts) {
    opts = opts || {};
    var tab = opts.tab || '';
    var signal = opts.signal || null;
    var requestId = typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : 'r' + Date.now();
    var headers = Object.assign({}, adminAuthHeaders());
    headers['X-Request-ID'] = requestId;
    var start = performance.now();
    return fetch(url, { cache: 'no-store', credentials: 'same-origin', signal: signal, headers: headers })
        .then(function (r) {
            var dur = Math.round(performance.now() - start);
            if (window.__ADMIN_DEBUG && console && console.debug) console.debug('[ADMIN_PERF] FETCH_END', { tab: tab, url: url, status: r.status, duration_ms: dur, request_id: requestId });
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
        });
}

function adminLogout() {
    if (!confirm("Çıkış yapmak istiyor musunuz?")) return;
    try {
        if (window.apiClient && window.apiClient.clearAuthAndBroadcast) window.apiClient.clearAuthAndBroadcast(); else { sessionStorage.removeItem("user"); sessionStorage.removeItem("token"); }
        localStorage.removeItem("boot_id");
        localStorage.removeItem("last_route");
    } catch (e) {}
    window.location.replace("/ui/login.html?logout=1");
}

function notifyServerDown() {
    if (typeof window.Toast !== "undefined" && window.Toast.warning) {
        try { window.Toast.warning("Sunucuya bağlanılamıyor. Sunucu gelene kadar bekleniyor."); } catch (e) {}
    }
}

/** Boot_id check — non-blocking; only logs out on confirmed 401 after server restart. */
async function adminBootIdCheck() {
    try {
        var r = await fetch("/api/boot-id", { cache: "no-store" });
        if (!r.ok) return;
        var b = await r.json();
        var serverBootId = b && b.boot_id ? String(b.boot_id) : "";
        var localBootId = localStorage.getItem("boot_id") || "";
        if (serverBootId && localBootId && serverBootId !== localBootId) {
            try { localStorage.setItem("boot_id", serverBootId); } catch (e) {}
            var who = await fetch(window.location.origin + "/api/auth/whoami", { method: "GET", credentials: "include", cache: "no-store" });
            if (!who.ok && who.status === 401) {
                var body = {};
                try { body = await who.json(); } catch (_) {}
                var detail = (body && body.detail && typeof body.detail === "object") ? body.detail : {};
                var errCode = detail.error_code || body.error_code || "UNAUTHORIZED";
                var isSessionInvalid = (errCode === "SESSION_NOT_FOUND");
                if (isSessionInvalid) {
                    if (window.apiClient && window.apiClient.redirectToLoginOnce) window.apiClient.redirectToLoginOnce(true);
                    else { try { sessionStorage.removeItem("user"); sessionStorage.removeItem("token"); localStorage.removeItem("user"); localStorage.removeItem("token"); localStorage.removeItem("boot_id"); localStorage.removeItem("last_route"); adminClearAccountsCache(); } catch (e) {} window.location.replace("/ui/login.html?session_expired=1"); }
                }
            }
        } else if (!localBootId && serverBootId) {
            try { localStorage.setItem("boot_id", serverBootId); } catch (e) {}
        }
    } catch (e) {}
}

// Initialize
document.addEventListener("DOMContentLoaded", async () => {
    var tok = sessionStorage.getItem("token");
    var usr = sessionStorage.getItem("user");
    // Token yoksa cookie ile whoami dene (login yaniti bazen token icermeyebilir; sunucu cookie gonderir)
    if (!usr || !tok) {
        try {
            var who = await fetch(window.location.origin + "/api/auth/whoami", { method: "GET", credentials: "include", cache: "no-store" });
            if (who.ok) {
                var whoBody = await who.json();
                var minimalUser = {
                    id: whoBody.user_id,
                    username: whoBody.username || "Admin",
                    name: whoBody.name || "",
                    surname: whoBody.surname || "",
                    is_admin: !!whoBody.is_admin,
                    account_id: whoBody.account_id || null,
                    account_code: whoBody.account_code || null
                };
                sessionStorage.setItem("user", JSON.stringify(minimalUser));
                try { localStorage.setItem("user", JSON.stringify(minimalUser)); } catch (e) {}
                usr = sessionStorage.getItem("user");
                if (!tok) tok = null; // Cookie ile giris; Bearer yok, sonraki istekler credentials: include ile cookie gonderir
            }
        } catch (e) {}
    }
    if (!usr) {
        try { localStorage.removeItem("last_route"); } catch (e) {}
        window.location.replace("/ui/login.html?session_expired=1");
        return;
    }
    restoreAccountsCacheFromStorage();
    var savedTab = sessionStorage.getItem("admin_tab");
    var validTabs = ["accounts", "suspended", "pending", "contact", "server", "popup", "settings"];
    if (savedTab && validTabs.indexOf(savedTab) !== -1) {
        switchTab(savedTab, { immediate: true, initial: true });
    } else {
        switchTab("accounts", { immediate: true, initial: true });
    }
    adminBootIdCheck();
    const userStr = sessionStorage.getItem("user");
    let user = null;
    if (userStr) {
        try {
            user = JSON.parse(userStr);
        } catch (e) {}
    }
    const nameEl = document.getElementById("adminAppbarUserName");
    if (nameEl) nameEl.textContent = "Admin";

    initAdminTabsSlider();
    fetchBreachAlerts();

    schedulePreloadAllTabs();

    var adminChatInp = document.getElementById("adminChatInput");
    if (adminChatInp) adminChatInp.addEventListener("input", onAdminChatInput);

    document.getElementById("createName").addEventListener("input", validateForm);
    const createPhoneEl = document.getElementById("createPhone");
    if (createPhoneEl) createPhoneEl.addEventListener("input", validateForm);
    
    document.getElementById("createForm").addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            e.preventDefault();
            createAccount(e);
        }
    });
    
    // Start polling (5s) only when on accounts tab and tab visible – avoid overload
    state.timer = setInterval(function () {
        if (state.currentTab !== 'accounts') return;
        if (document.visibilityState !== 'visible') return;
        loadAccounts(false);
    }, 5000);

    // Breach uyarıları periyodik kontrol (15s) – sadece sekme görünürken
    if (!state.breachAlertTimer) {
        state.breachAlertTimer = setInterval(function () {
            if (document.visibilityState === 'visible') fetchBreachAlerts();
        }, 15000);
    }

    window.addEventListener("beforeunload", () => {
        if (state.timer) clearInterval(state.timer);
        if (state.serverStatsTimer) clearInterval(state.serverStatsTimer);
        if (state.breachAlertTimer) clearInterval(state.breachAlertTimer);
    });

    // Sekmeler dropdown: click/touchend-outside kapat — aynı tap ile açıldıysa 250ms içinde kapatma (mobile bug fix)
    function maybeCloseTabsDropdown(e) {
        if (Date.now() - adminTabsJustOpenedAt < 250) return;
        var list = document.querySelector(".admin-tabs-list");
        if (!list || !list.classList.contains("admin-tabs-list--open")) return;
        var target = e.target;
        if (target && (target.closest("#adminTabsToggle") || target.closest(".admin-tabs-list"))) return;
        var header = document.getElementById("adminTabsHeader");
        if (header && target && header.contains(target)) return;
        closeAdminTabsDropdown();
    }
    document.addEventListener("click", maybeCloseTabsDropdown);
    document.addEventListener("touchend", maybeCloseTabsDropdown, { passive: true });

    // Toggle: tek dokunuşta touchend + pointerup + click hepsi tetiklenir; sadece ilkini işle (çift toggle = hemen kapanma bugı)
    function handleTabsToggle(e) {
        if (!e.target || !e.target.closest("#adminTabsToggle")) return;
        e.stopPropagation();
        e.preventDefault();
        var now = Date.now();
        if (now - adminTabsLastToggleRunAt < 400) return;
        adminTabsLastToggleRunAt = now;
        toggleAdminTabs();
    }
    document.addEventListener("touchend", handleTabsToggle, { passive: false });
    document.addEventListener("pointerup", handleTabsToggle);
    document.addEventListener("click", handleTabsToggle);

    document.addEventListener("keydown", function(e) {
        if (e.key === "Escape") closeAdminTabsDropdown();
    });

    window.addEventListener("resize", function() {
        if (window.innerWidth > 768) {
            var list = document.querySelector(".admin-tabs-list");
            var header = document.getElementById("adminTabsHeader");
            var portal = document.getElementById("adminTabsPortal");
            var parent = list && list.parentNode;
            if (list && header && (parent === document.body || (portal && parent === portal))) {
                list.classList.remove("admin-tabs-list--open");
                header.appendChild(list);
                list.style.position = list.style.top = list.style.left = list.style.right = list.style.width = list.style.maxHeight = list.style.zIndex = "";
            }
        }
    });
});

async function fetchBreachAlerts() {
    try {
        var res = await fetch("/api/admin/breach-alerts", { headers: adminAuthHeaders(), credentials: "same-origin" });
        if (!res.ok) return;
        var data = await res.json();
        var events = data.breach_events || [];
        if (events.length === 0) return;
        var content = document.getElementById("breachAlertContent");
        var overlay = document.getElementById("breachAlertOverlay");
        var headerEl = document.querySelector("#breachAlertOverlay .breach-modal-header");
        if (!content || !overlay) return;
        var hasSuspension = events.some(function (e) { return e.type === "account_accessed_unauthorized"; });
        if (headerEl) {
            headerEl.textContent = hasSuspension ? "⚠️ HESAP ASKIYA ALINDI · GÜVENLİK İHLALİ" : "⚠️ GÜVENLİK İHLALİ UYARISI";
            headerEl.className = "breach-modal-header" + (hasSuspension ? " breach-header-suspension" : "");
        }
        var html = "";
        if (hasSuspension) html += "<p class='breach-suspension-notice'>Bir kullanıcı hesabı yetkisiz erişim nedeniyle otomatik askıya alındı. Sadece admin panelinden tekrar aktif edebilirsiniz.</p>";
        html += "<p style='margin-bottom: 1rem; color: var(--ds-text-secondary);'>Aşağıdaki güvenlik ihlali(leri) tespit edildi. Lütfen inceleyin.</p>";
        events.forEach(function (e) {
            var typeLabel = e.type === "admin_accessed_without_auth" ? "Admin paneline yetkisiz erişim" : (e.type === "account_accessed_unauthorized" ? "Hesaba yetkisiz erişim (hesap askıya alındı)" : e.type);
            html += "<div class='breach-item'>";
            html += "<strong>" + typeLabel + "</strong><br>";
            html += (e.detail || "") + "<br>";
            html += "<span style='font-size: 0.85rem; color: var(--ds-text-muted);'>" + (e.path || "") + " · " + (e.method || "") + " · IP: " + (e.client_ip || "—") + " · " + (e.ts || "") + "</span>";
            if (e.session_user_id != null) html += "<br><span style='font-size: 0.85rem;'>Oturum user_id: " + e.session_user_id + (e.session_account_id != null ? ", account_id: " + e.session_account_id : "") + "</span>";
            if (e.requested_account_id != null) html += "<br><span style='font-size: 0.85rem;'>Erişilen hesap: " + e.requested_account_id + "</span>";
            html += "</div>";
        });
        content.innerHTML = html;
        overlay.style.display = "flex";
    } catch (e) {
        if (typeof console !== "undefined" && console.error) console.error("[admin] fetchBreachAlerts:", e);
    }
}

function loadAccounts(force) {
    if (force) {
        var entry = AdminStore.cache.accounts;
        entry.data = null;
        entry.ts = 0;
        entry.inflight = null;
        AdminStore.abort('accounts');
    }
    loadTab('accounts');
}

function renderKpis(totals) {
    document.getElementById("kpiAccounts").textContent = totals.total_accounts || 0;
    document.getElementById("kpiActiveBots").textContent = totals.total_active_bots || 0;
}

// P/L helper functions
function pnlClass(x) {
    if (x > 0) return "pos";
    if (x < 0) return "neg";
    return "zero";
}

function fmtSignedUsd(x) {
    const num = parseFloat(x) || 0;
    const formatted = num.toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return (num > 0 ? "+" : "") + formatted;
}

function fmtSignedPct(x) {
    const num = parseFloat(x) || 0;
    const formatted = num.toFixed(2);
    return (num > 0 ? "+" : "") + formatted;
}

function formatDateTime(isoString) {
    if (!isoString) return '';
    try {
        if (typeof window.trTime !== 'undefined' && window.trTime.trFormatDateTime)
            return window.trTime.trFormatDateTime(isoString);
        const date = new Date(isoString);
        return date.toLocaleString('tr-TR', {
            year: 'numeric', month: '2-digit', day: '2-digit',
            hour: '2-digit', minute: '2-digit', second: '2-digit',
            timeZone: 'Europe/Istanbul'
        });
    } catch (e) {
        return isoString;
    }
}

function adminAccountSpotDisplay(acc, balDisplayFn, pnlDisplayFn) {
    var isTest = !!acc.is_test_account
        || String(acc.user_username || "").trim().toLowerCase() === "test"
        || (acc.name && String(acc.name).indexOf("Test (Paper)") >= 0);
    var spotStatus = isTest ? "ok" : (acc.spot_balance_status || "ok");
    var spotNoKeys = !isTest && spotStatus === "no_keys";
    var spotError = !isTest && spotStatus === "error";
    var spotNoData = spotNoKeys || spotError;
    var spotLabel = isTest ? "SPOT BAKİYESİ" : "BİNANCE BAKİYESİ";
    var spotUsd = acc.spot_balance_usd;
    if (isTest && (spotUsd == null || spotUsd === "" || spotNoData)) {
        spotUsd = 10000;
        spotNoData = false;
    }
    var walPnl = pnlDisplayFn(acc.daily_wallet_pnl_usd, acc.daily_wallet_pnl_pct, !!acc.admin_isolated);
    var balanceText = spotNoData
        ? (spotNoKeys ? "Binance aktif edilmedi" : "Binance erişim hatası")
        : balDisplayFn(spotUsd);
    var pnlText = spotNoData
        ? (spotNoKeys ? "Binance aktif edilmedi" : "Binance erişim hatası")
        : walPnl.html;
    return { spotLabel: spotLabel, balanceText: balanceText, pnlText: pnlText, walPnl: walPnl };
}

function renderTiles(accounts, container = null) {
    if (!container) {
        container = document.getElementById("tilesContainer");
    }
    if (!container) return;
    
    if (accounts.length === 0) {
        container.innerHTML = `
            <div class="empty-state" style="grid-column: 1 / -1; text-align: center; padding: 3rem;">
                <p>Hesap bulunamadı</p>
                <button class="btn primary" onclick="openCreateModal()" style="margin-top: 1rem;">Yeni Hesap</button>
            </div>
        `;
        return;
    }
    
    container.innerHTML = accounts.map(acc => {
        const hasActiveBots = acc.active_bots > 0;
        const statusDotClass = hasActiveBots ? "status-dot-active" : "status-dot-inactive";
        
        // Ensure account_id is a valid number
        const accId = Number(acc.account_id) || 0;
        if (!accId || !Number.isInteger(accId) || accId <= 0) {
            console.error("[admin] renderTiles: Invalid account_id:", acc.account_id, "for account:", acc.name);
            return ''; // Skip invalid accounts
        }
        
        const accountCode = (acc.account_code && String(acc.account_code).trim()) || '';
        const isOnline = !!acc.user_is_online;
        const userFullName = [acc.user_name, acc.user_surname].filter(Boolean).map(function(s) { return String(s).trim(); }).join(' ').trim();
        const accName = (acc.name && String(acc.name).trim()) || '';
        const uu = (acc.user_username && String(acc.user_username).trim()) || '';
        const displayName = accName || userFullName || uu || accountCode || 'İsimsiz hesap';
        const navArg = /^\d{6}$/.test(accountCode) ? `'${accountCode.replace(/'/g, "\\'")}'` : String(accId);
        const safeName = displayName.replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        const isIsolated = !!acc.admin_isolated;
        const tileClass = "acct-tile" + (isIsolated ? " acct-tile-isolated" : "");
        const balDisplay = (v) => (v == null || v === undefined || v === "") ? "****" : Format.usd(v);
        const botPnlUsd = acc.daily_bot_pnl_usd;
        const botPnlPct = acc.daily_bot_pnl_pct;
        const walPnlUsd = acc.daily_wallet_pnl_usd;
        const walPnlPct = acc.daily_wallet_pnl_pct;
        const pnlDisplay = (usd, pct, isIsol) => {
            if (isIsol) return { html: "****", color: "var(--ds-text-secondary)" };
            if (usd == null && (pct == null || pct === undefined)) return { html: "—", color: "var(--ds-text-secondary)" };
            const u = parseFloat(usd) || 0;
            const p = pct != null && pct !== undefined ? parseFloat(pct) : null;
            const color = u >= 0 ? "#0ecb81" : "#f6465d";
            const usdStr = "$" + fmtSignedUsd(u);
            const pctStr = p != null ? (p >= 0 ? "+" : "") + p.toFixed(2) + "%" : "";
            const html = pctStr ? usdStr + " (" + pctStr + ")" : usdStr;
            return { html: html, color: color };
        };
        const botPnl = pnlDisplay(botPnlUsd, botPnlPct, isIsolated);
        const spotUi = adminAccountSpotDisplay(acc, balDisplay, pnlDisplay);
        return `
            <div class="${tileClass}" data-account-id="${accId}" onclick="handleAdminTileClick(event, ${navArg}, ${isIsolated})">
                <div class="acct-head">
                    <div>
                        <div class="acct-name">${safeName} ${accountCode ? `<span style="font-size: 12px; color: var(--ds-text-secondary); font-weight: normal;">[${accountCode}]</span>` : ''}${isIsolated ? ' <span class="pill small" style="background: rgba(246,70,93,0.2); color: var(--ds-text-error);">İzole</span>' : ''}</div>
                        <div class="acct-chips">
                            <span class="pill small">${acc.exchange}</span>
                        </div>
                    </div>
                    <div class="acct-head-right" style="display: flex; align-items: center; gap: 8px;" onclick="event.stopPropagation()">
                        ${isOnline ? '<span class="status-dot-online" title="Kullanıcı çevrimiçi"></span>' : ''}
                        <div class="status-dot ${statusDotClass}"></div>
                        <button type="button" class="icon-btn" title="Hesap ayarları" onclick="openAccountSettingsModalFromTile(${accId})">&#9881;</button>
                    </div>
                </div>
                
                <div class="acct-section">
                    <div class="acct-active">
                        <div class="label">AKTİF BOT</div>
                        <div class="value">${acc.active_bots}${acc.total_bots != null && acc.total_bots > acc.active_bots ? '<span style="font-size:0.75rem;color:var(--ds-text-secondary);font-weight:400;"> / ' + acc.total_bots + ' toplam</span>' : ''}</div>
                    </div>
                </div>
                
                <div class="acct-section">
                    <div class="bal-strip">
                        <div class="bal-item">
                            <div class="bal-label">${spotUi.spotLabel}</div>
                            <div class="bal-value">${spotUi.balanceText}</div>
                            <div class="bal-pnl" style="color: ${spotUi.walPnl.color};">Günlük Değişim ${spotUi.pnlText}</div>
                        </div>
                        <div class="bal-item">
                            <div class="bal-label">BOT BAKİYESİ</div>
                            <div class="bal-value">${balDisplay(acc.bots_balance_usd)}</div>
                            <div class="bal-pnl" style="color: ${botPnl.color};">Günlük PnL ${botPnl.html}</div>
                        </div>
                    </div>
                </div>
                
                <div class="acct-foot">
                    ${acc.user_last_login_at || acc.user_last_logout_at ? `
                        <div style="font-size: 0.75rem; color: var(--ds-text-secondary);">
                            ${acc.user_last_login_at ? `<div>Giriş: ${formatDateTime(acc.user_last_login_at)}</div>` : ''}
                            ${acc.user_last_logout_at ? `<div>Çıkış: ${formatDateTime(acc.user_last_logout_at)}</div>` : ''}
                        </div>
                    ` : ''}
                </div>
            </div>
        `;
    }).join("");
}

/** Dashboard KPI ile aynı değerleri tile bakiye şeridine yazar; tam re-render yapmadan canlı güncelleme. */
function updateAccountTileStrips(accounts) {
    if (!accounts || !accounts.length) return;
    const container = document.getElementById("tilesContainer");
    if (!container) return;
    const balDisplay = (v) => (v == null || v === undefined || v === "") ? "****" : Format.usd(v);
    const pnlDisplay = (usd, pct, isIsol) => {
        if (isIsol) return { html: "****", color: "var(--ds-text-secondary)" };
        if (usd == null && (pct == null || pct === undefined)) return { html: "—", color: "var(--ds-text-secondary)" };
        const u = parseFloat(usd) || 0;
        const p = pct != null && pct !== undefined ? parseFloat(pct) : null;
        const color = u >= 0 ? "#0ecb81" : "#f6465d";
        const usdStr = "$" + fmtSignedUsd(u);
        const pctStr = p != null ? (p >= 0 ? "+" : "") + p.toFixed(2) + "%" : "";
        const html = pctStr ? usdStr + " (" + pctStr + ")" : usdStr;
        return { html: html, color: color };
    };
    accounts.forEach((acc) => {
        const accId = Number(acc.account_id) || 0;
        if (!accId) return;
        const tile = container.querySelector(`.acct-tile[data-account-id="${accId}"]`);
        if (!tile) return;
        const spotUi = adminAccountSpotDisplay(acc, balDisplay, pnlDisplay);
        const botPnl = pnlDisplay(acc.daily_bot_pnl_usd, acc.daily_bot_pnl_pct, !!acc.admin_isolated);
        const item0 = tile.querySelector(".bal-strip .bal-item:nth-child(1)");
        const item1 = tile.querySelector(".bal-strip .bal-item:nth-child(2)");
        if (item0) {
            const labelEl = item0.querySelector(".bal-label");
            const valEl = item0.querySelector(".bal-value");
            const pnlEl = item0.querySelector(".bal-pnl");
            if (labelEl) labelEl.textContent = spotUi.spotLabel;
            if (valEl) valEl.textContent = spotUi.balanceText;
            if (pnlEl) {
                pnlEl.textContent = "Günlük Değişim " + spotUi.pnlText;
                pnlEl.style.color = spotUi.walPnl.color;
            }
        }
        if (item1) {
            const valEl = item1.querySelector(".bal-value");
            const pnlEl = item1.querySelector(".bal-pnl");
            if (valEl) valEl.textContent = balDisplay(acc.bots_balance_usd);
            if (pnlEl) {
                pnlEl.textContent = "Günlük PnL " + botPnl.html;
                pnlEl.style.color = botPnl.color;
            }
        }
    });
}

function handleAdminTileClick(event, accountIdOrCode, isIsolated) {
    if (isIsolated) {
        event.preventDefault();
        event.stopPropagation();
        if (typeof window.Toast !== "undefined" && window.Toast.warning) {
            window.Toast.warning("Bu hesap adminden izole; hesaba girilemez.");
        }
        return;
    }
    navigateToAccount(accountIdOrCode);
}

function navigateToAccount(accountIdOrCode) {
    const raw = String(accountIdOrCode == null ? "" : accountIdOrCode).trim();
    const fromAdmin = "from_admin=1";
    if (!raw) return;
    const id = Number(raw);
    const isNumericId = /^\d+$/.test(raw) && Number.isFinite(id) && id > 0 && !/^\d{5,7}$/.test(raw);
    try {
        sessionStorage.setItem("dashboard_from_admin", "1");
    } catch (e) {}
    if (isNumericId) {
        try {
            localStorage.setItem("selectedAccountId", String(id));
            sessionStorage.setItem("dashboard_admin_account_id", String(id));
            sessionStorage.removeItem("dashboard_admin_account_code");
        } catch (e) {}
        window.location.href = `/ui/dashboard.html?account_id=${id}&${fromAdmin}`;
        return;
    }
    try {
        localStorage.setItem("selectedAccountCode", raw);
        sessionStorage.setItem("dashboard_admin_account_code", raw);
        sessionStorage.removeItem("dashboard_admin_account_id");
    } catch (e) {}
    window.location.href = `/ui/dashboard.html?account_code=${encodeURIComponent(raw)}&${fromAdmin}`;
}

function openAccountSettingsModalFromTile(accountId) {
    const id = Number(accountId);
    let acc = (state.accounts || []).find(a => Number(a.account_id) === id);
    if (!acc) acc = (state.suspendedAccounts || []).find(a => Number(a.account_id) === id);
    if (acc) openAccountSettingsModal(acc);
}

function openAccountSettingsModal(acc) {
    state.settingsAccount = acc;
    const accId = Number(acc.account_id) || 0;
    const modal = document.getElementById("accountSettingsModal");
    const title = document.getElementById("accountSettingsTitle");
    const idEl = document.getElementById("accountSettingsId");
    const loginAtEl = document.getElementById("accountSettingsLoginAt");
    const loginIpEl = document.getElementById("accountSettingsLoginIp");
    const createdAtEl = document.getElementById("accountSettingsCreatedAt");
    const passwordEl = document.getElementById("accountSettingsPassword");
    const hintEl = document.getElementById("accountSettingsPasswordHint");
    const pwdRow = document.getElementById("accountSettingsPasswordRow");
    const genWrap = document.getElementById("accountSettingsGeneratedWrap");
    const genInput = document.getElementById("accountSettingsGeneratedPassword");
    const btnGenerate = document.getElementById("btnGenerateSetPassword");
    const btnCopy = document.getElementById("btnCopyGeneratedPassword");
    const suspendRow = document.getElementById("accountSettingsSuspendRow");
    const btnSuspend = document.getElementById("btnAccountSuspend");
    const btnKick = document.getElementById("btnAccountKick");
    const btnDelete = document.getElementById("btnAccountDelete");

    if (!modal) return;
    title && (title.textContent = "Hesap Ayarları – " + (acc.name || "Hesap"));
    idEl && (idEl.textContent = (acc.account_code && String(acc.account_code).trim()) ? ("ID: " + String(acc.account_code)) : "ID: —");
    loginAtEl && (loginAtEl.textContent = acc.user_last_login_at ? formatDateTime(acc.user_last_login_at) : "—");
    loginIpEl && (loginIpEl.textContent = (acc.user_last_login_ip && String(acc.user_last_login_ip).trim()) ? acc.user_last_login_ip : "—");
    var phoneDisplay = document.getElementById("accountSettingsPhoneDisplay");
    if (phoneDisplay) phoneDisplay.textContent = (acc.user_phone && String(acc.user_phone).trim()) ? acc.user_phone : "—";
    createdAtEl && (createdAtEl.textContent = acc.user_created_at ? formatDateTime(acc.user_created_at) : "—");

    if (passwordEl) {
        passwordEl.textContent = "••••••••";
        passwordEl.style.display = "inline";
        passwordEl.title = "Görüntülemek için tıklayın";
        passwordEl.onclick = function () {
            if (hintEl) {
                hintEl.textContent = "Güvenlik nedeniyle şifre görüntülenemez. Güncellemek için Oluştur ve Ayarla kullanın.";
                hintEl.style.display = "inline";
            }
        };
    }
    if (hintEl) { hintEl.style.display = "none"; hintEl.textContent = ""; }

    if (pwdRow) pwdRow.style.display = acc.user_id ? "block" : "none";
    if (genWrap) genWrap.style.display = "none";
    if (genInput) genInput.value = "";

    if (btnGenerate) {
        btnGenerate.style.display = acc.user_id ? "inline-block" : "none";
        btnGenerate.onclick = () => handleGenerateSetUserPassword();
    }
    if (btnCopy) btnCopy.onclick = () => {
        if (genInput && genInput.value) {
            navigator.clipboard.writeText(genInput.value).then(() => {
                if (window.Toast) window.Toast.success("Kopyalandı");
            }).catch(() => {});
        }
    };

    var isSuspended = acc.user_is_suspended === true ||
        (state.suspendedAccounts && state.suspendedAccounts.some(function (a) { return Number(a.account_id) === Number(acc.account_id); }));
    if (acc.user_id && suspendRow && btnSuspend) {
        suspendRow.style.display = "block";
        if (isSuspended) {
            btnSuspend.textContent = "Hesabı Askıdan Kaldır";
            btnSuspend.className = "btn btn-sm btn-success";
            btnSuspend.onclick = function () { handleSuspendUserFromModal(false); };
        } else {
            btnSuspend.textContent = "Hesabı Askıya Al";
            btnSuspend.className = "btn btn-sm btn-warning";
            btnSuspend.onclick = function () { handleSuspendUserFromModal(true); };
        }
    } else if (suspendRow) {
        suspendRow.style.display = "none";
    }

    if (btnKick) {
        btnKick.style.display = acc.user_id ? "inline-block" : "none";
        btnKick.onclick = () => handleKickUserFromModal();
    }
    if (btnDelete) btnDelete.onclick = () => {
        closeAccountSettingsModal();
        openDeleteModal(accId, acc.name);
    };

    var btnAudit = document.getElementById("btnAccountSettingsAudit");
    if (acc.user_id) {
        if (btnAudit) {
            if (acc.admin_isolated) {
                btnAudit.style.display = "none";
            } else {
                btnAudit.style.display = "block";
                btnAudit.onclick = function () { openAccountUserAuditModal(acc.user_id, acc.name || ("Hesap " + accId)); };
            }
        }
    } else {
        if (btnAudit) btnAudit.style.display = "none";
    }

    document.body.style.overflow = "hidden";
    modal.style.display = "flex";
    modal.style.alignItems = "center";
    modal.style.justifyContent = "center";
    modal.style.overflow = "hidden";
}

async function handleGenerateSetUserPassword() {
    const acc = state.settingsAccount;
    if (!acc || !acc.user_id) return;
    const genWrap = document.getElementById("accountSettingsGeneratedWrap");
    const genInput = document.getElementById("accountSettingsGeneratedPassword");
    const btn = document.getElementById("btnGenerateSetPassword");
    if (!genWrap || !genInput) return;
    if (btn) { btn.disabled = true; btn.textContent = "Oluşturuluyor…"; }
    try {
        const res = await fetch("/api/admin/generate-and-set-user-password", {
            method: "POST",
            headers: adminAuthHeaders(),
            body: JSON.stringify({ account_id: Number(acc.account_id) })
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || "Şifre oluşturulamadı");
        genInput.value = data.generated_password || "";
        genWrap.style.display = "block";
        if (window.Toast) window.Toast.success("Şifre oluşturuldu. Kopyalayıp kullanıcıya iletin.");
    } catch (e) {
        if (window.Toast) window.Toast.error(e.message || "Şifre oluşturulamadı");
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = "Oluştur ve Ayarla"; }
    }
}

function closeAccountSettingsModal() {
    state.settingsAccount = null;
    document.body.style.overflow = "";
    var m = document.getElementById("accountSettingsModal");
    if (m) m.style.display = "none";
}

function togglePasswordUpdateForm(show) {
    const form = document.getElementById("accountSettingsPasswordUpdate");
    const btn = document.getElementById("btnTogglePasswordUpdate");
    if (!form || !btn) return;
    form.style.display = show ? "block" : "none";
    btn.style.display = show ? "none" : "inline-block";
    if (show) {
        const inp = document.getElementById("accountSettingsNewPassword");
        if (inp) inp.focus();
    }
}

async function confirmSetUserPassword() {
    const acc = state.settingsAccount;
    if (!acc) return;
    const newPassEl = document.getElementById("accountSettingsNewPassword");
    const confirmEl = document.getElementById("accountSettingsNewPasswordConfirm");
    if (!newPassEl || !confirmEl) return;
    const newPass = newPassEl.value;
    const confirmPass = confirmEl.value;
    if (!newPass || !confirmPass) {
        if (window.Toast) window.Toast.error("Yeni şifre ve tekrarını girin");
        return;
    }
    if (newPass !== confirmPass) {
        if (window.Toast) window.Toast.error("Şifreler eşleşmiyor");
        return;
    }
    try {
        const res = await fetch("/api/admin/set-user-password", {
            method: "POST",
            headers: adminAuthHeaders(),
            body: JSON.stringify({
                account_id: Number(acc.account_id),
                new_password: newPass,
                new_password_confirm: confirmPass
            })
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || "Şifre güncellenemedi");
        if (window.Toast) window.Toast.success("Şifre güncellendi");
        togglePasswordUpdateForm(false);
        newPassEl.value = "";
        confirmEl.value = "";
    } catch (e) {
        if (window.Toast) window.Toast.error(e.message || "Şifre güncellenemedi");
    }
}

function handleSuspendUserFromModal(suspend) {
    const acc = state.settingsAccount;
    if (!acc || !acc.user_id) return;
    const btn = document.getElementById("btnAccountSuspend");
    const orig = btn.textContent;
    btn.disabled = true;
    btn.textContent = suspend ? "Askıya alınıyor…" : "Askıdan kaldırılıyor…";
    fetch("/api/admin/suspend-user", {
        method: "POST",
        headers: adminAuthHeaders(),
        body: JSON.stringify({ user_id: acc.user_id, suspend })
    })
        .then(r => r.json().then(data => ({ ok: r.ok, data })))
        .then(({ ok, data }) => {
            if (!ok) throw new Error(data.detail || "İşlem başarısız");
            if (window.Toast) window.Toast.success(data.message || (suspend ? "Askıya alındı" : "Askıdan kaldırıldı"));
            closeAccountSettingsModal();
            invalidateAccountsAndSuspendedCache();
            loadAccounts(true);
            loadSuspendedAccounts();
        })
        .catch(err => {
            if (window.Toast) window.Toast.error(err.message || "İşlem başarısız");
            btn.disabled = false;
            btn.textContent = orig;
        });
}

async function handleKickUserFromModal() {
    const acc = state.settingsAccount;
    if (!acc || !acc.user_id) return;
    if (!confirm("Kullanıcıyı hesaptan çıkaracaksınız. Çıkış yapıp tekrar giriş yapabilir. Devam?")) return;
    try {
        const res = await fetch("/api/admin/kick-user", {
            method: "POST",
            headers: adminAuthHeaders(),
            body: JSON.stringify({ user_id: acc.user_id })
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || "İşlem başarısız");
        if (window.Toast) window.Toast.success("Kullanıcı hesaptan çıkarıldı");
        closeAccountSettingsModal();
        loadAccounts(true);
    } catch (e) {
        if (window.Toast) window.Toast.error(e.message || "İşlem başarısız");
    }
}

function openCreateModal() {
    document.getElementById("createModal").style.display = "block";
    document.getElementById("createForm").reset();
    const ne = document.getElementById("nameError");
    const pe = document.getElementById("phoneError");
    if (ne) ne.textContent = "";
    if (pe) pe.textContent = "";
    validateForm();
    setTimeout(() => document.getElementById("createName").focus(), 100);
}

function validateForm() {
    const name = document.getElementById("createName").value.trim();
    const phoneRaw = (document.getElementById("createPhone") || {}).value.trim();
    const phoneDigits = phoneRaw.replace(/\D/g, "");
    const nameOk = name && name.length >= 3;
    const phoneOk = phoneDigits.length >= 10;
    const ne = document.getElementById("nameError");
    const pe = document.getElementById("phoneError");
    if (ne) ne.textContent = nameOk ? "" : "En az 3 karakter gerekli";
    if (pe) pe.textContent = phoneOk ? "" : "Geçerli telefon (en az 10 rakam) gerekli";
    const btn = document.getElementById("btnSubmit");
    if (btn) btn.disabled = !(nameOk && phoneOk);
    return nameOk && phoneOk;
}

function closeCreateModal() {
    document.getElementById("createModal").style.display = "none";
}

async function createAccount(event) {
    event.preventDefault();
    if (!validateForm()) return;
    
    const name = document.getElementById("createName").value.trim();
    const phone = (document.getElementById("createPhone") || {}).value.trim();
    const payload = { name, phone, exchange: "BINANCE" };
    
    try {
        const response = await fetch("/api/admin/accounts", {
            method: "POST",
            headers: adminAuthHeaders(),
            body: JSON.stringify(payload)
        });
        
        const result = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(result.detail || `HTTP ${response.status}`);
        }
        
        closeCreateModal();
        loadAccounts(true);
        if (window.Toast) window.Toast.success("Hesap oluşturuldu");
        
        if (result.username && result.generated_password) {
            const msg = "KULLANICI OLUŞTURULDU\n\nKullanıcı adı: " + result.username + "\nŞifre (tek kullanımlık): " + result.generated_password + "\n\nBu bilgileri kullanıcıya iletin. İlk girişte şifre değiştirmesi zorunludur.";
            navigator.clipboard.writeText("Kullanıcı adı: " + result.username + "\nŞifre: " + result.generated_password).catch(() => {});
            alert(msg);
        }
    } catch (error) {
        console.error("Error creating account:", error);
        if (window.Toast) window.Toast.error(error.message || "Hesap oluşturulamadı");
    }
}

function openDeleteModal(accountId, accountName) {
    // Ensure accountId is a number
    const id = typeof accountId === 'number' 
        ? accountId 
        : parseInt(String(accountId), 10);
    
    if (!Number.isFinite(id) || id <= 0) {
        console.error("[admin] openDeleteModal: Invalid account ID:", accountId, "type:", typeof accountId);
        if (window.Toast) {
            window.Toast.error("Geçersiz hesap ID");
        }
        return;
    }
    
    console.log("[admin] openDeleteModal: accountId=", id, "name=", accountName);
    state.deleteTargetId = id; // Store as number
    const nameEl = document.getElementById("deleteAccountName");
    if (nameEl) {
        nameEl.textContent = accountName || "Bu hesap";
    }
    const modal = document.getElementById("deleteModal");
    if (modal) {
        modal.style.display = "block";
    }
}

function openDeleteModalFromButton(button) {
    const accountIdStr = button.getAttribute("data-account-id");
    const accountName = button.getAttribute("data-account-name") || "Bu hesap";
    
    if (!accountIdStr || accountIdStr === "0" || accountIdStr === "undefined" || accountIdStr === "null") {
        console.error("[admin] openDeleteModalFromButton: Missing or invalid account ID:", accountIdStr);
        if (window.Toast) {
            window.Toast.error("Geçersiz hesap ID");
        }
        return;
    }
    
    // Parse account ID as integer - strict validation
    const accountId = parseInt(String(accountIdStr).trim(), 10);
    if (isNaN(accountId) || !Number.isFinite(accountId) || accountId <= 0 || !Number.isInteger(accountId)) {
        console.error("[admin] openDeleteModalFromButton: Invalid account ID:", accountIdStr, "parsed:", accountId);
        if (window.Toast) {
            window.Toast.error("Geçersiz hesap ID formatı: " + accountIdStr);
        }
        return;
    }
    
    console.log("[admin] openDeleteModalFromButton: accountId=", accountId, "name=", accountName, "type:", typeof accountId);
    openDeleteModal(accountId, accountName);
}

function closeDeleteModal() {
    state.deleteTargetId = null;
    document.getElementById("deleteModal").style.display = "none";
}

async function confirmDelete() {
    if (!state.deleteTargetId) {
        console.warn("[admin] confirmDelete: No delete target ID");
        if (window.Toast) {
            window.Toast.error("Silinecek hesap seçilmedi");
        }
        return;
    }
    
    // Ensure accountId is a valid positive integer
    let accountId;
    if (typeof state.deleteTargetId === 'number') {
        accountId = state.deleteTargetId;
    } else {
        const parsed = parseInt(String(state.deleteTargetId).trim(), 10);
        if (isNaN(parsed)) {
            console.error("[admin] confirmDelete: Cannot parse account ID:", state.deleteTargetId);
            if (window.Toast) {
                window.Toast.error("Geçersiz hesap ID formatı");
            }
            return;
        }
        accountId = parsed;
    }
    
    if (!Number.isFinite(accountId) || accountId <= 0 || !Number.isInteger(accountId)) {
        console.error("[admin] confirmDelete: Invalid account ID:", state.deleteTargetId, "parsed:", accountId);
        if (window.Toast) {
            window.Toast.error("Geçersiz hesap ID: " + state.deleteTargetId);
        }
        return;
    }
    
    console.log("[admin] confirmDelete: Deleting account", accountId, "type:", typeof accountId);
    
    // Show loading state
    const deleteBtn = document.querySelector("#deleteModal .btn.danger");
    const originalBtnText = deleteBtn ? deleteBtn.textContent : "Sil";
    if (deleteBtn) {
        deleteBtn.disabled = true;
        deleteBtn.textContent = "Siliniyor...";
    }
    
    // Helper function to reset button state
    const resetButton = () => {
        if (deleteBtn) {
            deleteBtn.disabled = false;
            deleteBtn.textContent = originalBtnText;
        }
    };
    
    try {
        // Ensure URL uses clean integer value (no decimals, no special chars)
        // FastAPI expects integer in path, so we send it as a clean number string
        const cleanAccountId = Math.floor(accountId); // Ensure it's an integer
        // Admin panel: use admin endpoint so audit shows ADMIN_ACCOUNT_DELETED with actor_type=admin
        const url = `/api/admin/accounts/${cleanAccountId}`;
        console.log("[admin] confirmDelete: Calling DELETE", url, "accountId:", cleanAccountId);
        
        const response = await fetch(url, {
            method: "DELETE",
            headers: Object.assign({
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache"
            }, adminAuthHeaders()),
            cache: "no-store"
        });
        
        console.log("[admin] confirmDelete: Response status", response.status, response.statusText, "headers:", response.headers);
        
        if (!response.ok) {
            let errorData;
            try {
                errorData = await response.json();
            } catch (e) {
                errorData = { detail: `HTTP ${response.status}: ${response.statusText}` };
            }
            
            // Extract error message - handle both string and object formats
            let errorMsg = errorData.detail || errorData.error || errorData.message || `HTTP ${response.status}`;
            if (typeof errorMsg === 'object' && errorMsg.detail) {
                errorMsg = errorMsg.detail;
            }
            
            console.error("[admin] confirmDelete: Error response", errorData, "status:", response.status);
            
            // Reset button state before showing error
            resetButton();
            
            // Show error message to user
            if (window.Toast) {
                window.Toast.error(errorMsg || "Hesap silinemedi");
            } else {
                alert("Hata: " + errorMsg);
            }
            
            // Don't close modal on error - let user see the error
            return; // Exit function, don't proceed with success handling
        }
        
        const data = await response.json();
        console.log("[admin] confirmDelete: Success response", data);
        
        // Immediately remove from UI (optimistic update)
        console.log("[admin] confirmDelete: Removing account from UI immediately, accountId:", accountId);
        const beforeCount = state.accounts.length;
        state.accounts = state.accounts.filter(acc => {
            const accId = Number(acc.account_id) || 0;
            const shouldKeep = accId !== accountId;
            if (!shouldKeep) {
                console.log("[admin] confirmDelete: Filtering out account", accId, acc.name);
            }
            return shouldKeep;
        });
        const afterCount = state.accounts.length;
        console.log("[admin] confirmDelete: Account count:", beforeCount, "->", afterCount);
        
        // Force re-render
        renderTiles(state.accounts);
        
        // Recalculate KPIs
        const totals = {
            total_accounts: state.accounts.length,
            total_active_bots: state.accounts.reduce((sum, acc) => sum + (acc.active_bots || 0), 0)
        };
        renderKpis(totals);
        
        console.log("[admin] confirmDelete: UI updated, account should be removed");
        
        if (window.Toast) {
            window.Toast.success(data.message || "Hesap silindi");
        }
        
        closeDeleteModal();
        
        // Force refresh accounts list after deletion to ensure consistency
        // Wait a bit to ensure backend has processed the deletion
        setTimeout(() => {
            console.log("[admin] confirmDelete: Force refreshing accounts list from backend...");
            loadAccounts(true); // Force refresh - bypass inFlight check
        }, 1000);
    } catch (error) {
        console.error("[admin] confirmDelete: Exception", error);
        
        // Reset button state on error
        resetButton();
        
        const errorMsg = error.message || "Hesap silinemedi";
        if (window.Toast) {
            window.Toast.error(errorMsg);
        } else {
            alert("Hata: " + errorMsg);
        }
        
        // Don't close modal on error
        // Modal stays open so user can see the error or try again
    }
}

var __adminTabAnimating = false;
var __adminActiveTabKey = null;
var __adminTabOrder = ['accounts', 'suspended', 'pending', 'contact', 'server', 'popup', 'settings'];

function getTabIndex(key) {
    var idx = __adminTabOrder.indexOf(key);
    return idx >= 0 ? idx : 999;
}

function positionIndicatorToButton(list, indicator, btn, immediate) {
    var listRect = list.getBoundingClientRect();
    var btnRect = btn.getBoundingClientRect();
    var left = btnRect.left - listRect.left;
    var width = btnRect.width;
    if (immediate) {
        var prev = indicator.style.transition;
        indicator.style.transition = 'none';
        indicator.style.width = width + 'px';
        indicator.style.transform = 'translate(' + left + 'px, -50%)';
        indicator.offsetHeight;
        indicator.style.transition = prev || '';
    } else {
        indicator.style.width = width + 'px';
        indicator.style.transform = 'translate(' + left + 'px, -50%)';
    }
}

function initAdminTabsSlider() {
    var list = document.querySelector('#adminTabsHeader .admin-tabs-list') || document.getElementById('adminTabsList');
    if (!list) return;
    var indicator = list.querySelector('.tab-indicator');
    if (!indicator) {
        indicator = document.createElement('div');
        indicator.className = 'tab-indicator';
        indicator.setAttribute('aria-hidden', 'true');
        list.insertBefore(indicator, list.firstChild);
    }
    var activeBtn = list.querySelector('.tab-btn.active') || list.querySelector('.tab-btn[data-tab="accounts"]') || list.querySelector('.tab-btn');
    if (activeBtn) positionIndicatorToButton(list, indicator, activeBtn, true);
    window.addEventListener('resize', function () {
        var currentActive = list.querySelector('.tab-btn.active');
        if (currentActive) positionIndicatorToButton(list, indicator, currentActive, true);
    }, { passive: true });
}

function waitMs(ms) {
    return new Promise(function (r) { setTimeout(r, ms); });
}

function showAdminPanel(key) {
    var host = document.getElementById('tabsContainer');
    if (!host || !key) return;
    var p = host.querySelector('.admin-tab-panel[data-tab-panel="' + key + '"]');
    if (p) p.classList.add('active');
}
function hideAdminPanel(key) {
    var host = document.getElementById('tabsContainer');
    if (!host || !key) return;
    var p = host.querySelector('.admin-tab-panel[data-tab-panel="' + key + '"]');
    if (p) p.classList.remove('active');
}

function runLoadForTab(tabName) {
    loadTab(tabName);
}

var _preloadQueueRunning = false;
var _preloadTabsOrder = ['pending', 'suspended', 'contact', 'server', 'popup', 'settings'];

function schedulePreloadAllTabs() {
    function run() {
        if (_preloadQueueRunning) return;
        _preloadQueueRunning = true;
        var queue = _preloadTabsOrder.filter(function (t) { return t !== state.currentTab; });
        var concurrency = 2;
        var index = 0;
        function next() {
            while (concurrency > 0 && index < queue.length) {
                var tab = queue[index++];
                concurrency--;
                var fetcher = getAdminTabFetcher(tab);
                if (!fetcher) { concurrency++; next(); return; }
                AdminStore.get(tab, fetcher).catch(function () {}).then(function () {
                    concurrency++;
                    next();
                });
            }
        }
        next();
    }
    if (typeof requestIdleCallback !== 'undefined') {
        requestIdleCallback(run, { timeout: 2000 });
    } else {
        setTimeout(run, 800);
    }
}

/** Start loading tab data (store + TTL + guard). Called immediately on tab switch, not after animation. */
function loadTab(tabKey) {
    var token = state.switchToken;
    var fetcher = getAdminTabFetcher(tabKey);
    if (!fetcher) {
        if (tabKey === 'settings') loadAdminSettings();
        return;
    }
    AdminStore.get(tabKey, fetcher, {
        onRefresh: function (data) {
            if (state.currentTab !== tabKey || state.switchToken !== token) return;
            runRenderForTab(tabKey, data);
        }
    }).then(function (data) {
        if (state.currentTab !== tabKey || state.switchToken !== token) return;
        runRenderForTab(tabKey, data);
        if (tabKey === 'server') startServerStatsRefresh();
    }).catch(function (err) {
        if (state.currentTab !== tabKey) return;
        if (window.__ADMIN_DEBUG && console && console.error) console.error('[ADMIN] loadTab error', tabKey, err);
        if (tabKey === 'accounts' && window.Toast) window.Toast.error('Hesaplar yüklenemedi: ' + (err && err.message ? err.message : ''));
    });
}

function getAdminTabFetcher(tabKey) {
    if (tabKey === 'accounts') return function (signal) {
        return adminFetchJSON('/api/admin/accounts?cb=' + Date.now(), { tab: 'accounts', signal: signal }).then(function (r) {
            return { accounts: r.accounts || [], totals: r.totals || null };
        });
    };
    if (tabKey === 'pending') return function (signal) {
        return Promise.all([
            adminFetchJSON('/api/admin/pending-registrations', { tab: 'pending', signal: signal }),
            adminFetchJSON('/api/admin/password-reset-requests', { signal: signal })
        ]).then(function (arr) { return { pending: arr[0], reset: arr[1] }; });
    };
    if (tabKey === 'suspended') return function (signal) {
        return adminFetchJSON('/api/admin/accounts?suspended=true', { tab: 'suspended', signal: signal }).then(function (r) {
            return { accounts: r.accounts || [] };
        });
    };
    if (tabKey === 'contact') return function (signal) {
        return adminFetchJSON('/api/admin/chats', { tab: 'contact', signal: signal }).then(function (r) { return r; });
    };
    if (tabKey === 'server') return function (signal) {
        return adminFetchJSON('/api/admin/server/stats', { tab: 'server', signal: signal }).then(function (r) { return r; });
    };
    if (tabKey === 'popup') return function (signal) {
        return adminFetchJSON('/api/admin/popups', { tab: 'popup', signal: signal }).then(function (r) { return r; });
    };
    if (tabKey === 'settings') return null;
    return null;
}

function runRenderForTab(tabKey, data) {
    if (tabKey === 'accounts' && data) {
        state.accounts = data.accounts || [];
        state.accountsTotals = data.totals || null;
        if (state.accountsTotals) renderKpis(state.accountsTotals);
        var container = document.getElementById('tilesContainer');
        if (container) renderTiles(state.accounts, container);
        try {
            adminWriteAccountsCache({ accounts: state.accounts, totals: state.accountsTotals, ts: Date.now() });
        } catch (e) {}
        return;
    }
    if (tabKey === 'pending' && data) {
        renderPendingData(data.pending, data.reset);
        return;
    }
    if (tabKey === 'suspended' && data) {
        state.suspendedAccounts = data.accounts || [];
        var badge = document.getElementById('suspendedBadge');
        if (badge) {
            if (state.suspendedAccounts.length > 0) { badge.textContent = state.suspendedAccounts.length; badge.style.display = 'inline-block'; } else { badge.style.display = 'none'; }
        }
        var cont = document.getElementById('suspendedTilesContainer');
        if (cont) {
            if (state.suspendedAccounts.length === 0) cont.innerHTML = '<div class="empty-state" style="grid-column: 1 / -1; text-align: center; padding: 3rem;">Askıya alınmış hesap yok</div>';
            else renderTiles(state.suspendedAccounts, cont);
        }
        return;
    }
    if (tabKey === 'contact' && data) {
        renderContactData(data);
        return;
    }
    if (tabKey === 'server' && data) {
        renderServerStatsData(data);
        return;
    }
    if (tabKey === 'popup' && data) {
        renderPopupsListData(data);
        return;
    }
}

function renderPendingData(pendingData, resetData) {
    var container = document.getElementById('pendingContainer');
    var badge = document.getElementById('pendingBadge');
    var count = (pendingData && pendingData.count) != null ? pendingData.count : ((pendingData && pendingData.pending) ? pendingData.pending.length : 0);
    if (badge) {
        if (count > 0) { badge.textContent = count; badge.style.display = 'inline-block'; } else { badge.style.display = 'none'; }
    }
    var pending = (pendingData && pendingData.pending) ? pendingData.pending : [];
    if (!container) return;
    if (pending.length === 0) {
        container.innerHTML = '<div class="empty-state">Bekleyen onay yok</div>';
    } else {
        container.innerHTML = pending.map(function (reg) {
            return '<div class="pending-item"><div><strong>' + (reg.name || '') + ' ' + (reg.surname || '') + '</strong><div style="font-size: 12px; color: var(--ds-text-secondary); margin-top: 4px;">📞 ' + (reg.phone || 'Telefon yok') + ' • IP: ' + (reg.ip_address || '') + ' • ' + (formatDateTime(reg.created_at) || '—') + '</div></div><div style="display: flex; gap: 0.5rem;"><button class="btn primary" onclick="approveRegistration(' + reg.id + ', true)">Onayla</button><button class="btn danger" onclick="approveRegistration(' + reg.id + ', false)">Reddet</button></div></div>';
        }).join('');
    }
    var resetContainer = document.getElementById('passwordResetContainer');
    if (!resetContainer) return;
    var requests = (resetData && resetData.requests) ? resetData.requests : [];
    if (requests.length === 0) {
        resetContainer.innerHTML = '<div class="empty-state">Bekleyen talep yok</div>';
    } else {
        resetContainer.innerHTML = requests.map(function (req) {
            var displayName = (req.user_name || '') + ' ' + (req.user_surname || '');
            return '<div class="pending-item" style="position: relative;"><button type="button" class="icon-btn" style="position: absolute; top: 0.5rem; right: 0.5rem; padding: 0.25rem 0.5rem; font-size: 1rem; line-height: 1; color: var(--ds-text-secondary);" onclick="dismissPasswordResetRequest(' + req.id + ')" title="Kapat">×</button><div style="margin-right: 2rem;"><strong>' + displayName + '</strong><div style="font-size: 12px; color: var(--ds-text-secondary); margin-top: 4px;">📞 ' + (req.phone || '') + ' • Kullanıcı: ' + (req.username || '') + ' • ' + (formatDateTime(req.created_at) || '—') + '</div></div><div style="display: flex; gap: 0.5rem; align-items: center;"><span style="font-size: 12px; color: var(--ds-text-secondary);">Admin SMS ile yeni şifre atacak</span></div></div>';
        }).join('');
    }
}

function renderContactData(data) {
    var container = document.getElementById('adminChatListContainer');
    if (!container) return;
    var chats = (data && data.chats) ? data.chats : [];
    var totalUnread = chats.reduce(function (s, c) { return s + (c.unread_count || 0); }, 0);
    var badge = document.getElementById('contactBadge');
    if (badge) {
        if (totalUnread > 0) { badge.textContent = totalUnread; badge.style.display = 'inline-block'; } else { badge.style.display = 'none'; }
    }
    if (chats.length === 0) {
        container.innerHTML = '<div class="empty-state">Henüz sohbet yok</div>';
        return;
    }
    container.innerHTML = chats.map(function (c) {
        var name = [c.name, c.surname].filter(Boolean).join(' ').trim() || 'Kullanıcı';
        var sub = [c.phone, c.account_code].filter(Boolean).join(' · ') || '';
        var last = c.last_message_at ? (window.trTime && window.trTime.trFormatShort ? window.trTime.trFormatShort(c.last_message_at) : new Date(c.last_message_at).toLocaleString('tr-TR', { dateStyle: 'short', timeStyle: 'short', timeZone: 'Europe/Istanbul' })) : '';
        var avg = c.avg_rating != null ? Number(c.avg_rating) : (c.rating != null && c.rating >= 1 && c.rating <= 5 ? c.rating : null);
        var ratingStr = (avg != null && avg >= 1 && avg <= 5) ? ' ★ ' + (avg % 1 === 0 ? avg + '/5' : avg.toFixed(1) + '/5') : '';
        var unread = (c.unread_count || 0) > 0 ? '<span class="badge" style="font-size: 0.7rem;">' + c.unread_count + '</span>' : '';
        var locked = c.locked ? ' 🔒' : '';
        var online = c.online === true;
        var dotColor = online ? '#22c55e' : '#ef4444';
        var dotTitle = online ? 'Çevrimiçi' : 'Çevrimdışı';
        var statusDot = '<span class="admin-chat-status-dot" style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: ' + dotColor + '; margin-right: 6px; flex-shrink: 0; vertical-align: middle;" title="' + dotTitle + '" aria-hidden="true"></span>';
        var sel = adminChatSelected && adminChatSelected.user_id === c.user_id ? ' background: var(--ds-bg-tertiary); border-radius: 8px;' : '';
        var displayName = (name + locked).replace(/'/g, "\\'").replace(/"/g, '&quot;');
        return '<button type="button" class="admin-chat-user" data-user-id="' + c.user_id + '" data-thread-id="' + (c.thread_id || '') + '" style="text-align: left; padding: 0.6rem 0.75rem; border: none; background: transparent; color: var(--ds-text-primary); cursor: pointer; border-radius: 8px; display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; width: 100%;' + sel + '" onclick="selectAdminChat(' + c.user_id + ', ' + (c.thread_id || 'null') + ", '" + displayName + "')\"><div style=\"flex: 1; min-width: 0; display: flex; align-items: center;\">" + statusDot + "<div style=\"flex: 1; min-width: 0;\"><div style=\"font-weight: 600; font-size: 0.9rem;\">" + name + locked + "</div><div style=\"font-size: 0.75rem; color: var(--ds-text-secondary);\">" + sub + (last ? ' · ' + last : '') + ratingStr + "</div></div></div>" + unread + "</button>";
    }).join('');
}

function renderServerStatsData(data) {
    if (!data) return;
    var cwdEl = document.getElementById('serverCwd');
    if (cwdEl) cwdEl.textContent = (data.server_cwd && String(data.server_cwd).trim()) ? data.server_cwd : '—';
    var uptimeEl = document.getElementById('serverUptime');
    if (uptimeEl) uptimeEl.textContent = data.uptime_formatted || (data.uptime_seconds + ' sn') || 'Hata';
    var startedEl = document.getElementById('serverStartedAt');
    if (startedEl) startedEl.textContent = data.started_at_iso ? ('Başlangıç: ' + data.started_at_iso.replace('T', ' ').replace('+00:00', ' UTC').slice(0, 22)) : '—';
    var reqEl = document.getElementById('serverRequestCount');
    if (reqEl) reqEl.textContent = data.request_count != null ? String(data.request_count) : '—';
    var memEl = document.getElementById('serverMemoryMb');
    if (memEl) {
        if (data.memory_mb != null && data.memory_total_mb != null) memEl.textContent = data.memory_mb + ' / ' + data.memory_total_mb + ' MB';
        else if (data.memory_mb != null) memEl.textContent = data.memory_mb + ' MB';
        else memEl.textContent = '—';
    }
    var cpuEl = document.getElementById('serverCpuPercent');
    if (cpuEl) cpuEl.textContent = data.cpu_percent != null ? String(data.cpu_percent) : '—';
    var linkEl = document.getElementById('serverNetworkLink');
    if (linkEl) linkEl.textContent = data.network_link_mbps != null ? String(data.network_link_mbps) : '—';
    var ipEl = document.getElementById('serverIp');
    if (ipEl) ipEl.textContent = data.server_ip && String(data.server_ip).trim() ? String(data.server_ip).trim() : '—';
    var netDownEl = document.getElementById('serverNetworkDown');
    var netUpEl = document.getElementById('serverNetworkUp');
    if (netDownEl) netDownEl.textContent = data.network_mbps_down != null ? Number(data.network_mbps_down).toFixed(2) : '—';
    if (netUpEl) netUpEl.textContent = data.network_mbps_up != null ? Number(data.network_mbps_up).toFixed(2) : '—';
    var lockdown = !!data.lockdown;
    var lockEl = document.getElementById('serverLockdownStatus');
    if (lockEl) lockEl.textContent = lockdown ? 'Kapalı (sadece admin erişebilir)' : 'Açık';
    var btnLock = document.getElementById('btnServerLockdown');
    var btnUnlock = document.getElementById('btnServerUnlock');
    if (btnLock) btnLock.style.display = lockdown ? 'none' : '';
    if (btnUnlock) btnUnlock.style.display = lockdown ? '' : 'none';
    var noStats = data.psutil_available === false || (data.memory_mb == null && data.cpu_percent == null && data.network_mbps_down == null);
    var msgEl = document.getElementById('serverTabMessage');
    if (msgEl) msgEl.textContent = noStats ? 'Bellek, CPU ve ağ hızları için sunucuda psutil gerekir: pip install psutil' : '';
}

function renderPopupsListData(data) {
    var container = document.getElementById('popupAdminList');
    if (!container) return;
    var list = (data && data.popups) ? data.popups : [];
    if (list.length === 0) {
        container.innerHTML = '<p class="empty-state">Henüz pop-up yayınlanmamış.</p>';
        return;
    }
    container.innerHTML = list.map(function (p) {
        var active = p.is_active ? '<span class="badge" style="background: var(--ds-success); color: #fff;">Aktif</span>' : '<span class="badge" style="background: var(--ds-text-tertiary);">Süresi doldu</span>';
        var targetLabel = p.target === 'first_login' ? 'İlk giriş' : 'Normal kullanıcı';
        var titleLabels = { info: 'Bilgi', warning: 'Uyarı', success: 'Başarı', maintenance: 'Bakım', announcement: 'Duyuru' };
        var titleLabel = titleLabels[p.title_key] || p.title_key;
        var maxShows = p.max_shows_per_user != null ? p.max_shows_per_user : 1;
        var showCountText = maxShows === 1 ? 'Tek seferlik' : 'En fazla ' + maxShows + ' kere';
        return '<div class="popup-admin-item popup-admin-item-clickable" data-popup-id="' + p.id + '" onclick="openPopupDetail(' + p.id + ')" role="button" tabindex="0" title="Detay ve görüntüleyen kullanıcılar">' +
            '<div class="popup-admin-item-row">' +
            '<div class="popup-admin-item-content">' +
            '<div class="popup-admin-item-meta">' + active + ' <strong>' + targetLabel + '</strong> · ' + titleLabel + ' · ' + showCountText + ' · Geçerlilik: ' + (p.valid_until || '').slice(0, 16) + '</div>' +
            '<div class="popup-admin-item-msg">' + (p.message || '').slice(0, 120) + (p.message && p.message.length > 120 ? '…' : '') + '</div>' +
            '</div>' +
            '<button type="button" class="btn btn-sm popup-admin-item-remove" onclick="event.stopPropagation(); deletePopup(' + p.id + ')" title="Yayından kaldır">Kaldır</button>' +
            '</div></div>';
    }).join('');
}

function animateAdminTabContentTransition(fromKey, toKey) {
    var host = document.getElementById('tabsContainer');
    if (!host) {
        showAdminPanel(toKey);
        hideAdminPanel(fromKey);
        runLoadForTab(toKey);
        return Promise.resolve();
    }
    var fromPanel = fromKey ? host.querySelector('.admin-tab-panel[data-tab-panel="' + fromKey + '"]') : null;
    var toPanel = host.querySelector('.admin-tab-panel[data-tab-panel="' + toKey + '"]');
    if (!toPanel) {
        showAdminPanel(toKey);
        hideAdminPanel(fromKey);
        runLoadForTab(toKey);
        return Promise.resolve();
    }
    var dir = (getTabIndex(toKey) > getTabIndex(fromKey)) ? 1 : -1;
    var enterX = 22 * dir;
    var exitX = -22 * dir;
    toPanel.classList.add('active');
    toPanel.style.opacity = '0';
    toPanel.style.transform = 'translateX(' + enterX + 'px)';
    if (fromPanel) {
        fromPanel.style.opacity = '1';
        fromPanel.style.transform = 'translateX(0)';
    }
    toPanel.offsetHeight;
    var duration = 220;
    var easing = 'cubic-bezier(0.2, 0.8, 0.2, 1)';
    toPanel.style.transition = 'transform ' + duration + 'ms ' + easing + ', opacity ' + duration + 'ms ease';
    if (fromPanel) fromPanel.style.transition = 'transform ' + duration + 'ms ' + easing + ', opacity ' + duration + 'ms ease';
    toPanel.style.opacity = '1';
    toPanel.style.transform = 'translateX(0)';
    if (fromPanel) {
        fromPanel.style.opacity = '0';
        fromPanel.style.transform = 'translateX(' + exitX + 'px)';
    }
    return waitMs(duration).then(function () {
        toPanel.style.transition = '';
        toPanel.style.transform = '';
        toPanel.style.opacity = '';
        if (fromPanel) {
            fromPanel.classList.remove('active');
            fromPanel.style.transition = '';
            fromPanel.style.transform = '';
            fromPanel.style.opacity = '';
        }
        showAdminPanel(toKey);
        hideAdminPanel(fromKey);
        /* Load already started in switchTab; do not call runLoadForTab here */
    });
}

function showSkeletonForTab(tabKey) {
    var host = document.getElementById('tabsContainer');
    if (!host) return;
    var panel = host.querySelector('.admin-tab-panel[data-tab-panel="' + tabKey + '"]');
    if (!panel) return;
    if (tabKey === 'accounts') {
        var c = document.getElementById('tilesContainer');
        if (c && c.querySelector('.acct-tile')) return;
        if (c) c.innerHTML = '<div class="empty-state" data-skeleton>Yükleniyor...</div>';
    } else if (tabKey === 'pending') {
        var pc = document.getElementById('pendingContainer');
        if (pc) pc.innerHTML = '<div class="empty-state" data-skeleton>Yükleniyor...</div>';
    } else if (tabKey === 'suspended') {
        var sc = document.getElementById('suspendedTilesContainer');
        if (sc) sc.innerHTML = '<div class="empty-state" data-skeleton>Yükleniyor...</div>';
    } else if (tabKey === 'contact') {
        var cc = document.getElementById('adminChatListContainer');
        if (cc) cc.innerHTML = '<div class="empty-state" data-skeleton>Yükleniyor...</div>';
    } else if (tabKey === 'server') {
        var su = document.getElementById('serverUptime');
        if (su) su.textContent = '—';
    } else if (tabKey === 'popup') {
        var pop = document.getElementById('popupAdminList');
        if (pop) pop.innerHTML = '<p class="empty-state" data-skeleton>Yükleniyor...</p>';
    }
}

function switchTab(tabName, opts) {
    var tabKey = tabName || 'accounts';
    var immediate = opts && opts.immediate === true;
    var initial = opts && opts.initial === true;
    if (!immediate && __adminTabAnimating) return;
    var list = document.getElementById('adminTabsList') || document.querySelector('#adminTabsHeader .admin-tabs-list') || document.querySelector('.admin-tabs-list');
    var indicator = list ? list.querySelector('.tab-indicator') : null;
    var newBtn = list ? list.querySelector('.tab-btn[data-tab="' + tabKey + '"]') : null;
    var oldBtn = list ? list.querySelector('.tab-btn.active') : null;
    var fromKey = __adminActiveTabKey || (oldBtn ? oldBtn.getAttribute('data-tab') : null);
    var toKey = tabKey;
    if (fromKey === toKey && !initial) return;

    state.currentTab = toKey;
    state.switchToken++;
    if (state.serverStatsTimer) {
        clearInterval(state.serverStatsTimer);
        state.serverStatsTimer = null;
    }
    __adminTabAnimating = true;

    if (list && indicator && newBtn) {
        positionIndicatorToButton(list, indicator, newBtn, immediate);
    }
    document.querySelectorAll('.tab-btn').forEach(function (btn) { btn.classList.remove('active'); });
    if (newBtn) newBtn.classList.add('active');

    showAdminPanel(toKey);
    if (fromKey !== toKey) hideAdminPanel(fromKey);
    var entry = AdminStore.cache[toKey];
    var hasCache = entry && entry.data !== null && (Date.now() - entry.ts) < (AdminStore.TTL[toKey] || 60000);
    if (toKey === 'accounts' && adminAccountsHasDisplayCache()) hasCache = true;
    if (!hasCache) showSkeletonForTab(toKey);
    loadTab(toKey);

    if (immediate) {
        __adminActiveTabKey = toKey;
        __adminTabAnimating = false;
    } else {
        animateAdminTabContentTransition(fromKey, toKey).catch(function () {}).then(function () {
            __adminActiveTabKey = toKey;
            __adminTabAnimating = false;
        });
    }

    closeAdminTabsDropdown();
    if (toKey !== 'contact') stopAdminChatPoll();
    try {
        sessionStorage.setItem('admin_tab', state.currentTab);
    } catch (e) {}
}

// Make switchTab globally available
window.switchTab = switchTab;

function ensureAdminTabsPortal() {
    var portal = document.getElementById('adminTabsPortal');
    if (!portal) {
        portal = document.createElement('div');
        portal.id = 'adminTabsPortal';
        document.body.appendChild(portal);
    }
    return portal;
}

var _adminTabsScrollResizeHandlers = null;

function positionAdminTabsList() {
    var list = document.getElementById('adminTabsList') || document.querySelector('.admin-tabs-list');
    var toggle = document.getElementById('adminTabsToggle');
    if (!list || !toggle || !list.classList.contains('admin-tabs-list--open')) return;
    if (list.parentNode && list.parentNode.id !== 'adminTabsPortal') return;
    var rect = toggle.getBoundingClientRect();
    var top = rect.bottom + 6;
    list.style.top = top + 'px';
}

function removeAdminTabsScrollResizeListeners() {
    if (!_adminTabsScrollResizeHandlers) return;
    window.removeEventListener('scroll', _adminTabsScrollResizeHandlers.scroll, true);
    window.removeEventListener('resize', _adminTabsScrollResizeHandlers.resize);
    if (window.visualViewport) {
        window.visualViewport.removeEventListener('scroll', _adminTabsScrollResizeHandlers.scroll);
        window.visualViewport.removeEventListener('resize', _adminTabsScrollResizeHandlers.resize);
    }
    _adminTabsScrollResizeHandlers = null;
}

function addAdminTabsScrollResizeListeners() {
    removeAdminTabsScrollResizeListeners();
    var onScroll = function () {
        requestAnimationFrame(positionAdminTabsList);
    };
    var onResize = function () {
        requestAnimationFrame(positionAdminTabsList);
    };
    _adminTabsScrollResizeHandlers = { scroll: onScroll, resize: onResize };
    window.addEventListener('scroll', onScroll, true);
    window.addEventListener('resize', onResize);
    if (window.visualViewport) {
        window.visualViewport.addEventListener('scroll', onScroll);
        window.visualViewport.addEventListener('resize', onResize);
    }
}

function toggleAdminTabs() {
    var list = document.getElementById('adminTabsList') || document.querySelector('.admin-tabs-list');
    var toggle = document.getElementById('adminTabsToggle');
    var header = document.getElementById('adminTabsHeader');
    if (!list || !toggle) {
        if (window.__ADMIN_DEBUG && console && console.debug) console.debug('[ADMIN] toggleAdminTabs: list or toggle missing', { list: !!list, toggle: !!toggle });
        return;
    }
    var isOpen = list.classList.toggle('admin-tabs-list--open');
    toggle.setAttribute('aria-expanded', isOpen);
    if (isOpen) adminTabsJustOpenedAt = Date.now();
    var isMobile = window.innerWidth <= 768;
    if (window.__ADMIN_DEBUG && console && console.debug) console.debug('[ADMIN] toggleAdminTabs', { isOpen: isOpen, isMobile: isMobile, parentNode: list.parentNode ? list.parentNode.tagName : null });
    if (isOpen) {
        if (isMobile) {
            var portal = ensureAdminTabsPortal();
            if (list.parentNode !== portal && header) {
                portal.appendChild(list);
            }
            list.style.zIndex = '10002';
            list.style.pointerEvents = 'auto';
            list.style.position = 'fixed';
            list.style.left = '8px';
            list.style.right = '8px';
            list.style.width = 'auto';
            list.style.maxHeight = 'min(360px, 60vh)';
            requestAnimationFrame(function () {
                positionAdminTabsList();
                if (window.__ADMIN_DEBUG && console && console.debug) console.debug('[ADMIN] menu positioned');
                addAdminTabsScrollResizeListeners();
            });
        } else {
            removeAdminTabsScrollResizeListeners();
            restoreAdminTabsListToHeader(list, header);
            list.style.position = list.style.left = list.style.right = list.style.width = list.style.top = list.style.maxHeight = list.style.zIndex = '';
        }
    } else {
        removeAdminTabsScrollResizeListeners();
        restoreAdminTabsListToHeader(list, header);
        list.style.position = list.style.top = list.style.left = list.style.right = list.style.width = list.style.maxHeight = list.style.zIndex = '';
        if (isMobile) {
            var portal = document.getElementById('adminTabsPortal');
            if (portal && portal.parentNode) portal.parentNode.removeChild(portal);
        }
    }
}

function restoreAdminTabsListToHeader(list, header) {
    if (!list || !header) return;
    var parent = list.parentNode;
    var portal = document.getElementById('adminTabsPortal');
    if (parent === document.body || (portal && parent === portal)) {
        header.appendChild(list);
    }
}

function closeAdminTabsDropdown() {
    removeAdminTabsScrollResizeListeners();
    var list = document.getElementById('adminTabsList') || document.querySelector('.admin-tabs-list');
    var toggle = document.getElementById('adminTabsToggle');
    var header = document.getElementById('adminTabsHeader');
    if (list) {
        list.classList.remove('admin-tabs-list--open');
        var parent = list.parentNode;
        var portal = document.getElementById('adminTabsPortal');
        if (header && (parent === document.body || (portal && parent === portal))) {
            header.appendChild(list);
        }
        list.style.position = list.style.top = list.style.left = list.style.right = list.style.width = list.style.maxHeight = list.style.zIndex = '';
        if (portal && portal.parentNode && portal.children.length === 0) {
            portal.parentNode.removeChild(portal);
        }
    }
    if (toggle) toggle.setAttribute('aria-expanded', 'false');
}

window.toggleAdminTabs = toggleAdminTabs;

function openSettingsTab() {
    switchTab('settings');
}

function loadAdminSettings() {
    // IP onayı kaldırıldı; ayarlar sekmesinde sadece şifre değiştir + tüm admin oturumlarını sonlandır
}

var ADMIN_AUDIT_EVENT_LABELS = {
    'LOGIN_SUCCESS': 'Giriş başarılı', 'LOGIN_FAILED': 'Giriş başarısız', 'LOGOUT': 'Çıkış',
    'IP_APPROVAL_REQUIRED': 'IP onayı istendi', 'IP_APPROVED': 'IP onaylandı', 'IP_DENIED': 'IP reddedildi',
    'ALLOWED_IP_ADDED': 'IP eklendi', 'ALLOWED_IP_REMOVED': 'IP kaldırıldı',
    'USER_IP_APPROVED': 'IP onaylandı (admin)', 'USER_IP_DENIED': 'IP reddedildi (admin)', 'USER_ALLOWED_IP_ADDED': 'IP eklendi (admin)', 'USER_ALLOWED_IP_REMOVED': 'IP kaldırıldı (admin)',
    'SETTINGS_UPDATE': 'Ayar güncellendi', 'PASSWORD_CHANGE': 'Şifre değişti', 'PHONE_UPDATE': 'Telefon güncellendi',
    'SPOT_ORDER_CREATE': 'Spot emir oluşturuldu', 'SPOT_ORDER_CANCEL': 'Spot emir iptal',
    'BOT_CREATE': 'Bot oluşturuldu', 'BOT_DELETE': 'Bot silindi', 'BOT_START': 'Bot başlatıldı', 'BOT_STOP': 'Bot durduruldu', 'BOT_TRADE': 'Bot alım/satım',
    'CHAT_USER_MESSAGE': 'Sohbet mesajı (kullanıcı)', 'CHAT_ADMIN_MESSAGE': 'Sohbet mesajı (admin)',
    'ACCOUNT_DELETED': 'Hesap silindi',
    'ADMIN_USER_SUSPENDED': 'Hesap askıya alındı (admin)', 'ADMIN_USER_UNSUSPENDED': 'Hesap askıdan çıkarıldı (admin)',
    'ADMIN_ACCOUNT_CREATED': 'Hesap oluşturuldu (admin)', 'ADMIN_ACCOUNT_DELETED': 'Hesap silindi (admin)',
    'ADMIN_USER_PHONE_UPDATE': 'Telefon güncellendi (admin)', 'ADMIN_USER_PASSWORD_SET': 'Şifre ayarlandı (admin)', 'ADMIN_PASSWORD_CHANGE': 'Admin şifre değişti',
    'SERVER_START': 'Sunucu başlatıldı'
};
function adminAuditEventLabel(type) { return ADMIN_AUDIT_EVENT_LABELS[type] || type; }
function adminAuditEventDescription(e) {
    if (e.detail != null && e.detail !== '') return e.detail;
    var m = e.meta;
    if (!m) return '—';
    if (e.event_type === 'CHAT_USER_MESSAGE' || e.event_type === 'CHAT_ADMIN_MESSAGE') return (m.body_preview != null ? m.body_preview : '—');
    if (e.event_type === 'SPOT_ORDER_CREATE' && (m.symbol || m.side)) {
        var parts = [(m.side || ''), (m.symbol || '')].filter(Boolean);
        if (m.quantity != null) parts.push(m.quantity + ' adet');
        if (m.price != null) parts.push('fiyat ' + m.price);
        if (m.executed_value_usdt != null) parts.push('~' + Number(m.executed_value_usdt).toFixed(2) + ' USDT');
        return parts.join(' · ') || '—';
    }
    if (e.event_type === 'BOT_TRADE' && (m.symbol || m.side)) {
        var sideTr = (m.side === 'BUY' || m.side === 'DOWN_BUY') ? 'Alım' : 'Satım';
        return sideTr + ' ' + (m.symbol || '') + ' ' + (m.qty != null ? m.qty : '') + ' @ ' + (m.price != null ? m.price : '') + (m.reason ? ' (neden: ' + m.reason + ')' : '');
    }
    if (e.event_type === 'BOT_CREATE' && m.bot_id != null) return 'Bot #' + m.bot_id + ' ' + (m.symbol || '') + ' · ' + (m.mode || '') + (m.config_summary && m.config_summary.budget_usdt != null ? ' · ' + m.config_summary.budget_usdt + ' USDT' : '');
    if (e.event_type === 'BOT_DELETE' && m.bot_id != null) return 'Bot #' + m.bot_id + ' ' + (m.symbol || '') + ' silindi';
    if (m.updated_fields && m.updated_fields.length) return m.updated_fields.join(', ');
    if (m.symbol && m.side) return (m.side || '') + ' ' + m.symbol;
    if (m.reason) return m.reason;
    if (m.account_name) return 'Hesap: ' + m.account_name;
    if (m.name) return m.name;
    if (m.field) return 'Alan: ' + m.field;
    if (m.suspend !== undefined) return m.suspend ? 'Askıya alındı' : 'Askıdan çıkarıldı';
    if (m.order_id) return 'Emir #' + m.order_id;
    if (m.remark) return m.remark;
    return '—';
}
function openAdminAuditModal() {
    var backdrop = document.getElementById('adminAuditModalBackdrop');
    var modal = document.getElementById('adminAuditModal');
    if (!backdrop || !modal) return;
    backdrop.style.display = 'block';
    modal.style.display = 'flex';
    loadAdminAudit('month');
    var container = document.getElementById('adminAuditModal');
    if (container) {
        container.querySelectorAll('.admin-audit-range').forEach(function (btn) {
            if (btn && btn.getAttribute('data-range')) btn.onclick = function () { loadAdminAudit(btn.getAttribute('data-range')); };
        });
    }
    backdrop.onclick = function () { closeAdminAuditModal(); };
}
function closeAdminAuditModal() {
    var backdrop = document.getElementById('adminAuditModalBackdrop');
    var modal = document.getElementById('adminAuditModal');
    if (backdrop) backdrop.style.display = 'none';
    if (modal) modal.style.display = 'none';
}
window.openAdminAuditModal = openAdminAuditModal;
window.closeAdminAuditModal = closeAdminAuditModal;

// --- Hata logları: son 50 benzersiz hata. Sıfırla → tertemiz, ilk gelen #1. ---
var ERROR_LOGS_CAP = 50;

function _errorLogEsc(s) { return (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

function _errorLogSetEmpty() {
    var listEl = document.getElementById('errorLogsList');
    var totalEl = document.getElementById('errorLogsTotal');
    if (listEl) listEl.innerHTML = '<p style="color: var(--ds-text-secondary); padding: 1.5rem; text-align: center;">Kayıt yok.</p>';
    if (totalEl) totalEl.textContent = '';
}

function openErrorLogsModal() {
    var modal = document.getElementById('errorLogsModal');
    if (!modal) return;
    modal.style.display = 'flex';
    document.body.style.overflow = 'hidden';
    loadErrorLogs();
}
function closeErrorLogsModal() {
    var modal = document.getElementById('errorLogsModal');
    if (modal) { modal.style.display = 'none'; document.body.style.overflow = ''; }
}
window.openErrorLogsModal = openErrorLogsModal;
window.closeErrorLogsModal = closeErrorLogsModal;

async function loadErrorLogs() {
    var listEl = document.getElementById('errorLogsList');
    var totalEl = document.getElementById('errorLogsTotal');
    if (!listEl) return;
    listEl.innerHTML = '<span style="color: var(--ds-text-secondary);">Yükleniyor...</span>';
    if (totalEl) totalEl.textContent = '';
    var resetAfter = state.errorLogsResetAfterId;
    var url = '/api/admin/error-logs?grouped=true&max_unique=' + ERROR_LOGS_CAP;
    if (resetAfter != null && Number.isFinite(Number(resetAfter))) {
        url += '&after_id=' + encodeURIComponent(Number(resetAfter));
    }
    try {
        var res = await fetch(url, { headers: adminAuthHeaders() });
        var data = res.ok ? await res.json().catch(function () { return {}; }) : {};
        if (!res.ok) {
            var errMsg = (data.detail && data.detail.message) ? data.detail.message : (typeof data.detail === 'string' ? data.detail : '') || (data.message || 'HTTP ' + res.status);
            listEl.innerHTML = '<p style="color: var(--ds-danger);">Yüklenemedi: ' + _errorLogEsc(errMsg) + '</p>';
            return;
        }
        var errors = data.errors || [];
        if (resetAfter != null && Number.isFinite(Number(resetAfter))) {
            errors = errors.filter(function (r) { return (r.id != null) && (Number(r.id) > resetAfter); });
        }
        var n = errors.length;
        if (totalEl) totalEl.textContent = 'Toplam ' + n + ' hata';
        if (n === 0) {
            listEl.innerHTML = '<p style="color: var(--ds-text-secondary); padding: 1.5rem; text-align: center;">Kayıt yok.</p>';
            return;
        }
        var copyPayloads = [];
        var html = '';
        function esc(s) { return _errorLogEsc(s); }
        for (var i = 0; i < errors.length; i++) {
            var r = errors[i];
            var seq = i + 1;
            var count = r.occurrence_count != null ? r.occurrence_count : 1;
            var countText = count > 1000 ? '1000+ kez' : (count === 1 ? '' : count + ' kez');
            var ctx = r.context && typeof r.context === 'object' ? r.context : null;
            var ctxRaw = ctx ? JSON.stringify(ctx) : (r.context || '');
            var durumParts = [];
            if (ctx) {
                if (ctx.page) durumParts.push('Sayfa: ' + ctx.page);
                if (ctx.section) durumParts.push('Bölüm: ' + ctx.section);
                if (ctx.path && !ctx.page) durumParts.push('Path: ' + ctx.path);
            }
            var durumLine = durumParts.length ? ('Durum: ' + durumParts.join(' · ')) : (r.path ? ('Path: ' + r.path) : '');
            var detailShort = (r.detail || '').substring(0, 1500) + (r.detail && r.detail.length > 1500 ? '...' : '');
            var who = r.user_label
                ? ((String(r.user_label).indexOf('Denenen:') === 0) ? r.user_label : ('Kullanıcı: ' + r.user_label))
                : (r.is_admin ? 'Admin' : '—');
            var acc = r.account_label ? ('Hesap: ' + r.account_label) : '';
            var createdFmt = (window.trTime && window.trTime.trFormatDateTime) ? window.trTime.trFormatDateTime(r.created_at) : (r.created_at || '');
            var copyText = ['#' + seq + ' ' + (r.source || '') + ' · ' + createdFmt + (countText ? ' (' + countText + ')' : ''), (r.message || ''), r.path ? ('Path: ' + r.path) : '', r.detail || '', ctxRaw ? ('Context: ' + ctxRaw) : '', r.request_id ? ('Request ID: ' + r.request_id) : ''].filter(Boolean).join('\n\n');
            copyPayloads.push(copyText);
            var copyIdx = copyPayloads.length - 1;
            html += '<div class="error-log-item" data-copy-idx="' + copyIdx + '" style="border: 1px solid var(--ds-border); border-radius: 8px; padding: 0.75rem 1rem; margin-bottom: 0.75rem; background: var(--ds-bg-secondary);">';
            html += '<div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 0.5rem;">';
            html += '<span style="font-weight: 600; color: var(--ds-danger);">#' + seq + ' ' + esc(r.source || '') + ' · ' + createdFmt + (countText ? ' <span style="color: var(--ds-text-secondary); font-size: 0.8rem;">(' + countText + ')</span>' : '') + '</span>';
            html += '<span style="display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap;">';
            html += '<span style="font-size: 0.8rem; color: var(--ds-text-secondary);">' + esc(who) + (acc ? ' · ' + esc(acc) : '') + '</span>';
            html += '<button type="button" class="btn-error-kopyala" onclick="window.copyErrorLogAt(this)" style="padding: 0.25rem 0.5rem; font-size: 0.75rem; border-radius: 6px; border: 1px solid var(--ds-border); background: var(--ds-bg-tertiary); color: var(--ds-text-primary); cursor: pointer;">Kopyala</button>';
            html += '</span></div>';
            html += '<div style="margin-top: 0.5rem; word-break: break-word;">' + esc(r.message) + '</div>';
            if (durumLine) html += '<div style="font-size: 0.8rem; margin-top: 0.35rem; color: var(--ds-accent);">' + esc(durumLine) + '</div>';
            if (r.client_ip || r.user_agent) html += '<div style="font-size: 0.75rem; color: var(--ds-text-secondary); margin-top: 0.25rem;">' + (r.client_ip ? 'IP: ' + esc(r.client_ip) : '') + (r.client_ip && r.user_agent ? ' · ' : '') + (r.user_agent ? 'UA: ' + esc((r.user_agent || '').substring(0, 80)) + ((r.user_agent || '').length > 80 ? '…' : '') : '') + '</div>';
            if (detailShort) html += '<pre style="font-size: 0.75rem; white-space: pre-wrap; word-break: break-all; margin: 0.5rem 0 0; padding: 0.5rem; background: var(--ds-bg-tertiary); border-radius: 4px; max-height: 180px; overflow: auto;">' + esc(detailShort) + '</pre>';
            if (r.request_id) html += '<div style="font-size: 0.75rem; margin-top: 0.2rem;">Request ID: ' + esc(r.request_id) + '</div>';
            html += '</div>';
        }
        window._errorLogCopyPayloads = copyPayloads;
        listEl.innerHTML = html;
    } catch (e) {
        listEl.innerHTML = '<p style="color: var(--ds-danger);">Yüklenemedi: ' + _errorLogEsc(e.message || '') + '</p>';
    }
}
window.loadErrorLogs = loadErrorLogs;

function copyErrorLogAt(btn) {
    var row = btn && btn.closest && btn.closest('.error-log-item');
    var idx = row ? parseInt(row.getAttribute('data-copy-idx'), 10) : NaN;
    if (isNaN(idx)) return;
    var arr = window._errorLogCopyPayloads;
    if (!arr || !arr[idx]) return;
    var text = arr[idx];
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () {
            if (window.Toast && window.Toast.success) window.Toast.success('Panoya kopyalandı');
        }).catch(function () {
            var ta = document.createElement('textarea'); ta.value = text; ta.style.position = 'fixed'; ta.style.left = '-9999px';
            document.body.appendChild(ta); ta.select();
            try { document.execCommand('copy'); if (window.Toast && window.Toast.success) window.Toast.success('Panoya kopyalandı'); } catch (e2) {}
            document.body.removeChild(ta);
        });
    } else {
        var ta = document.createElement('textarea'); ta.value = text; ta.style.position = 'fixed'; ta.style.left = '-9999px';
        document.body.appendChild(ta); ta.select();
        try { document.execCommand('copy'); if (window.Toast && window.Toast.success) window.Toast.success('Panoya kopyalandı'); } catch (e2) {}
        document.body.removeChild(ta);
    }
}
window.copyErrorLogAt = copyErrorLogAt;

async function resetErrorLogs() {
    try {
        var res = await fetch('/api/admin/error-logs/clear', { method: 'POST', headers: adminAuthHeaders() });
        var data = res.ok ? await res.json().catch(function () { return {}; }) : {};
        if (!res.ok) {
            var msg = (data.detail && (typeof data.detail === 'object' ? data.detail.message : data.detail)) || data.message || 'Hatalar silinemedi.';
            if (window.Toast && window.Toast.error) window.Toast.error(msg);
            return;
        }
        state.errorLogsResetAfterId = null;
        _errorLogSetEmpty();
        if (window.Toast && window.Toast.success) window.Toast.success(data.message || 'Hatalar sıfırlandı.');
    } catch (e) {
        state.errorLogsResetAfterId = null;
        _errorLogSetEmpty();
        if (window.Toast && window.Toast.error) window.Toast.error(e.message || 'Hatalar sıfırlanamadı.');
    }
}
window.resetErrorLogs = resetErrorLogs;

async function createTestErrorLog() {
    try {
        var res = await fetch('/api/admin/error-logs/test', { method: 'POST', headers: adminAuthHeaders() });
        var data = await res.json().catch(function () { return {}; });
        if (!res.ok) {
            var msg = (data.detail && (typeof data.detail === 'object' ? data.detail.message : data.detail)) || data.message || 'Test hatası oluşturulamadı';
            throw new Error(msg);
        }
        if (window.Toast) window.Toast.success('Test hatası eklendi.');
        await loadErrorLogs();
    } catch (e) {
        if (window.Toast) window.Toast.error(e.message || 'Test hatası oluşturulamadı');
    }
}
window.createTestErrorLog = createTestErrorLog;

function refreshErrorLogs() {
    loadErrorLogs();
}
window.refreshErrorLogs = refreshErrorLogs;

function _auditEsc(s) {
    if (s == null || s === '') return '';
    var t = String(s);
    return t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

async function loadAdminAudit(range) {
    var el = document.getElementById('adminAuditList');
    if (!el) return;
    el.innerHTML = '<span class="admin-audit-loading">Yükleniyor...</span>';
    var rangeKey = range || 'month';
    var container = document.getElementById('adminAuditModal');
    if (container) {
        container.querySelectorAll('.admin-audit-range').forEach(function (btn) {
            btn.classList.toggle('active', btn.getAttribute('data-range') === rangeKey);
        });
    }
    try {
        var res = await fetch('/api/admin/audit/events?range=' + rangeKey + '&limit=200&offset=0&admin_only=true&own_only=true', { headers: adminAuthHeaders() });
        var data = res.ok ? await res.json().catch(function () { return {}; }) : { events: [] };
        if (!data.events || data.events.length === 0) {
            el.innerHTML = '<span class="admin-audit-loading">Bu dönemde kayıt yok.</span>';
            return;
        }
        var html = '<table class="admin-audit-table"><thead><tr>';
        html += '<th>Tarih-Saat</th><th>Kim yaptı</th><th>İşlem</th><th>Açıklama / Detay</th><th>Hedef (Kullanıcı)</th><th>IP</th><th>Cihaz</th></tr></thead><tbody>';
        data.events.forEach(function (e) {
            var time = e.created_at ? (window.trTime && window.trTime.trFormatDateTime ? window.trTime.trFormatDateTime(e.created_at) : new Date(e.created_at).toLocaleString('tr-TR', { timeZone: 'Europe/Istanbul' })) : '—';
            var actorTr = (e.actor_label != null && e.actor_label !== '') ? e.actor_label : (e.actor_type === 'admin' ? 'Admin' : (e.actor_type === 'system' ? 'Sistem' : 'Kullanıcı'));
            var label = adminAuditEventLabel(e.event_type);
            var desc = adminAuditEventDescription(e);
            var target = (e.target_user_label != null && String(e.target_user_label).trim() !== '') ? e.target_user_label : ((e.target_user_id != null ? 'K:' + e.target_user_id : '') + (e.target_account_id != null ? (e.target_user_id != null ? ' / H:' : 'H:') + e.target_account_id : '') || '—');
            var ipDisplay = e.ip_masked ? '(gizli)' : (e.ip || '—');
            var devDisplay = e.device_id ? (e.device_id.length > 12 ? e.device_id.slice(0, 12) + '…' : e.device_id) : '—';
            html += '<tr>';
            html += '<td class="audit-time" data-label="Tarih-Saat">' + _auditEsc(time) + '</td>';
            html += '<td class="audit-actor" data-label="Kim yaptı">' + _auditEsc(actorTr || '—') + '</td>';
            html += '<td class="audit-type" data-label="İşlem">' + _auditEsc(label) + '</td>';
            html += '<td class="audit-detail" data-label="Açıklama">' + _auditEsc(desc || '—') + '</td>';
            html += '<td class="audit-target" data-label="Hedef (Kullanıcı)">' + _auditEsc(target) + '</td>';
            html += '<td data-label="IP">' + _auditEsc(ipDisplay) + '</td>';
            html += '<td data-label="Cihaz">' + _auditEsc(devDisplay) + '</td>';
            html += '</tr>';
        });
        html += '</tbody></table>';
        el.innerHTML = html;
    } catch (err) {
        el.innerHTML = '<span style="color: var(--ds-danger);">Yüklenemedi.</span>';
    }
}
function openAccountUserAuditModal(userId, accountName) {
    state.accountUserAuditUserId = userId;
    state.accountUserAuditAccountName = accountName || '';
    var backdrop = document.getElementById('accountUserAuditBackdrop');
    var modal = document.getElementById('accountUserAuditModal');
    var title = document.getElementById('accountUserAuditTitle');
    if (title) title.textContent = 'İşlem geçmişi – ' + (accountName || 'Kullanıcı');
    if (backdrop) backdrop.style.display = 'block';
    if (modal) modal.style.display = 'flex';
    loadAccountUserAudit(userId, 'month');
    var container = document.getElementById('accountUserAuditModal');
    if (container) {
        container.querySelectorAll('.account-user-audit-range').forEach(function (btn) {
            if (btn && btn.getAttribute('data-range')) {
                btn.onclick = function () {
                    var uid = state.accountUserAuditUserId;
                    if (uid) loadAccountUserAudit(uid, btn.getAttribute('data-range'));
                };
            }
        });
    }
    if (backdrop) backdrop.onclick = function () { closeAccountUserAuditModal(); };
}
function closeAccountUserAuditModal() {
    state.accountUserAuditUserId = null;
    state.accountUserAuditAccountName = null;
    var backdrop = document.getElementById('accountUserAuditBackdrop');
    var modal = document.getElementById('accountUserAuditModal');
    if (backdrop) backdrop.style.display = 'none';
    if (modal) modal.style.display = 'none';
}
window.closeAccountUserAuditModal = closeAccountUserAuditModal;

async function loadAccountUserAudit(userId, range) {
    var el = document.getElementById('accountUserAuditList');
    if (!el) return;
    el.innerHTML = '<span style="color: var(--ds-text-secondary);">Yükleniyor...</span>';
    try {
        var res = await fetch('/api/admin/users/' + userId + '/audit?range=' + (range || 'month') + '&limit=200&offset=0', { headers: adminAuthHeaders() });
        var data = res.ok ? await res.json().catch(function () { return {}; }) : { events: [] };
        if (!data.events || data.events.length === 0) {
            el.innerHTML = '<span style="color: var(--ds-text-secondary);">Bu dönemde kayıt yok.</span>';
            return;
        }
        var html = '<table style="width: 100%; border-collapse: collapse; font-size: 0.85rem;"><thead><tr style="border-bottom: 1px solid var(--ds-border);">';
        html += '<th style="text-align: left; padding: 0.5rem;">Tarih-Saat</th><th style="text-align: left; padding: 0.5rem;">Kim yaptı</th><th style="text-align: left; padding: 0.5rem;">İşlem</th><th style="text-align: left; padding: 0.5rem;">Açıklama / Detay</th><th style="text-align: left; padding: 0.5rem;">Giriş IP</th><th style="text-align: left; padding: 0.5rem;">Cihaz</th></tr></thead><tbody>';
        data.events.forEach(function (e) {
            var time = e.created_at ? (window.trTime && window.trTime.trFormatDateTime ? window.trTime.trFormatDateTime(e.created_at) : new Date(e.created_at).toLocaleString('tr-TR', { timeZone: 'Europe/Istanbul' })) : '—';
            var actorTr = (e.actor_label != null && e.actor_label !== '') ? e.actor_label : (e.actor_type === 'admin' ? 'Admin' : (e.actor_type === 'system' ? 'Sistem' : 'Kullanıcı'));
            var label = adminAuditEventLabel(e.event_type);
            var desc = adminAuditEventDescription(e);
            var ipDisplay = e.ip_masked ? '(gizli)' : (e.ip || '—');
            var devDisplay = e.device_id ? (e.device_id.length > 12 ? e.device_id.slice(0, 12) + '…' : e.device_id) : '—';
            html += '<tr style="border-bottom: 1px solid var(--ds-border);"><td style="padding: 0.5rem; white-space: nowrap;">' + time + '</td><td style="padding: 0.5rem;">' + (actorTr || '—') + '</td><td style="padding: 0.5rem;">' + label + '</td><td style="padding: 0.5rem; max-width: 280px; word-break: break-word;">' + (desc || '—') + '</td><td style="padding: 0.5rem;">' + ipDisplay + '</td><td style="padding: 0.5rem;">' + devDisplay + '</td></tr>';
        });
        html += '</tbody></table>';
        el.innerHTML = html;
    } catch (err) {
        el.innerHTML = '<span style="color: var(--ds-danger);">Yüklenemedi.</span>';
    }
}

function adminDropAllAdminSessions() {
    if (!confirm('Tüm admin oturumları sonlandırılacak (tüm adminler çıkış olacak). Devam?')) return;
    fetch('/api/admin/sessions/drop-all-admin', { method: 'POST', headers: adminAuthHeaders() })
        .then(r => r.json().then(d => ({ ok: r.ok, data: d })))
        .then(({ ok }) => {
            if (ok) {
                try { if (window.apiClient && window.apiClient.clearAuthAndBroadcast) window.apiClient.clearAuthAndBroadcast(); else { sessionStorage.removeItem('user'); sessionStorage.removeItem('token'); } localStorage.removeItem('boot_id'); localStorage.removeItem('last_route'); } catch (e) {}
                window.location.replace('/ui/login.html?reason=all_admin_sessions_dropped');
            } else if (window.Toast && window.Toast.error) window.Toast.error('İşlem başarısız.');
        })
        .catch(() => { if (window.Toast && window.Toast.error) window.Toast.error('İşlem başarısız.'); });
}

async function loadServerStats() {
    var uptimeEl = document.getElementById('serverUptime');
    var msgEl = document.getElementById('serverTabMessage');
    try {
        const res = await fetch('/api/admin/server/stats', { headers: adminAuthHeaders(), cache: 'no-store' });
        if (!res.ok) {
            if (res.status === 502 || res.status === 503 || res.status === 504) notifyServerDown();
            if (uptimeEl) uptimeEl.textContent = 'Hata';
            if (msgEl) msgEl.textContent = (res.status === 401 || res.status === 403) ? 'Yetkisiz. Sunucu sekmesi için admin girişi gerekir.' : '';
            return;
        }
        const data = await res.json();
        var cwdEl = document.getElementById('serverCwd');
        if (cwdEl) cwdEl.textContent = (data.server_cwd && String(data.server_cwd).trim()) ? data.server_cwd : '—';
        if (uptimeEl) uptimeEl.textContent = data.uptime_formatted || (data.uptime_seconds != null ? (data.uptime_seconds + ' sn') : '') || 'Hata';
        var startedEl = document.getElementById('serverStartedAt');
        if (startedEl) startedEl.textContent = data.started_at_iso ? ('Başlangıç: ' + data.started_at_iso.replace('T', ' ').replace('+00:00', ' UTC').slice(0, 22)) : '—';
        var reqEl = document.getElementById('serverRequestCount');
        if (reqEl) reqEl.textContent = data.request_count != null ? String(data.request_count) : '—';
        var memEl = document.getElementById('serverMemoryMb');
        if (memEl) {
            if (data.memory_mb != null && data.memory_total_mb != null) memEl.textContent = data.memory_mb + ' / ' + data.memory_total_mb + ' MB';
            else if (data.memory_mb != null) memEl.textContent = data.memory_mb + ' MB';
            else memEl.textContent = '—';
        }
        var cpuEl = document.getElementById('serverCpuPercent');
        if (cpuEl) cpuEl.textContent = data.cpu_percent != null ? String(data.cpu_percent) : '—';
        var linkEl = document.getElementById('serverNetworkLink');
        if (linkEl) linkEl.textContent = data.network_link_mbps != null ? String(data.network_link_mbps) : '—';
        var ipEl = document.getElementById('serverIp');
        if (ipEl) ipEl.textContent = data.server_ip && String(data.server_ip).trim() ? String(data.server_ip).trim() : '—';
        var noStats = data.psutil_available === false || (data.memory_mb == null && data.cpu_percent == null);
        if (msgEl) msgEl.textContent = noStats ? 'Bellek, CPU için sunucuda psutil gerekir: pip install psutil' : '';
    } catch (e) {
        if (uptimeEl) uptimeEl.textContent = 'Hata';
        if (msgEl) msgEl.textContent = 'İstatistikler alınamadı: ' + ((e && e.message) ? e.message : '');
    }
}

function startServerStatsRefresh() {
    if (state.serverStatsTimer) clearInterval(state.serverStatsTimer);
    state.serverStatsTimer = setInterval(loadServerStats, 5000);
}

async function serverLockdown() {
    if (!confirm('Erişimi kapatmak istiyor musunuz? Sadece admin sayfası ve admin API erişilebilir olacak.')) return;
    try {
        const res = await fetch('/api/admin/server/lockdown', { method: 'POST', headers: adminAuthHeaders() });
        const data = await res.json().catch(function() { return {}; });
        if (res.ok && data.success) {
            if (window.Toast) window.Toast.success(data.message || 'Erişim kapatıldı.');
            loadServerStats();
        } else {
            if (window.Toast) window.Toast.error(data.detail || data.message || 'İşlem başarısız.');
        }
    } catch (e) {
        if (window.Toast) window.Toast.error('İstek hatası: ' + e.message);
    }
}

async function serverUnlock() {
    if (!confirm('Erişimi tekrar açmak istiyor musunuz?')) return;
    try {
        const res = await fetch('/api/admin/server/unlock', { method: 'POST', headers: adminAuthHeaders() });
        const data = await res.json().catch(function() { return {}; });
        if (res.ok && data.success) {
            if (window.Toast) window.Toast.success(data.message || 'Erişim açıldı.');
            loadServerStats();
        } else {
            if (window.Toast) window.Toast.error(data.detail || data.message || 'İşlem başarısız.');
        }
    } catch (e) {
        if (window.Toast) window.Toast.error('İstek hatası: ' + e.message);
    }
}

function openServerExitModal() {
    var m = document.getElementById('serverExitModal');
    var p = document.getElementById('serverExitPassword');
    var e = document.getElementById('serverExitError');
    if (m) m.style.display = 'block';
    if (p) { p.value = ''; p.focus(); }
    if (e) e.textContent = '';
}

function closeServerExitModal() {
    var m = document.getElementById('serverExitModal');
    var p = document.getElementById('serverExitPassword');
    var err = document.getElementById('serverExitError');
    if (m) m.style.display = 'none';
    if (p) p.value = '';
    if (err) err.textContent = '';
}

async function confirmServerExit() {
    var pEl = document.getElementById('serverExitPassword');
    var errEl = document.getElementById('serverExitError');
    var btn = document.getElementById('serverExitConfirmBtn');
    var password = (pEl && pEl.value) ? pEl.value.trim() : '';
    if (errEl) errEl.textContent = '';
    if (!password) {
        if (errEl) errEl.textContent = 'Şifre girin.';
        if (pEl) pEl.focus();
        return;
    }
    if (btn) { btn.disabled = true; btn.textContent = 'İşleniyor...'; }
    try {
        const res = await fetch('/api/admin/server/exit', {
            method: 'POST',
            headers: adminAuthHeaders(),
            body: JSON.stringify({ password: password })
        });
        const data = await res.json().catch(function() { return {}; });
        if (res.ok && data.success) {
            if (window.Toast) window.Toast.success(data.message || 'Sunucu kapatılıyor...');
            closeServerExitModal();
            document.getElementById('serverTabMessage').textContent = 'Sunucu kapatılıyor...';
        } else {
            var msg = (data.detail || data.message || 'İşlem başarısız.');
            if (typeof msg === 'object' && msg.detail) msg = msg.detail;
            if (errEl) errEl.textContent = msg;
            if (window.Toast) window.Toast.error(msg);
        }
    } catch (e) {
        if (errEl) errEl.textContent = 'İstek hatası: ' + e.message;
        if (window.Toast) window.Toast.error('İstek hatası: ' + e.message);
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = 'Sunucuyu Kapat'; }
    }
}

function serverExit() {
    openServerExitModal();
}

async function serverRestart() {
    if (!confirm('Sunucu yaklaşık 5 saniye sonra kapatılıp process yöneticisi ile yeniden başlatılacak. Kısa süre erişim kesilir. Devam edilsin mi?')) return;
    var msgEl = document.getElementById('serverTabMessage');
    if (msgEl) msgEl.textContent = 'Yeniden başlatılıyor...';
    try {
        const res = await fetch('/api/admin/server/restart', {
            method: 'POST',
            headers: adminAuthHeaders(),
            body: '{}'
        });
        const data = await res.json().catch(function() { return {}; });
        if (res.ok && data.success) {
            if (window.Toast) window.Toast.success(data.message || 'Sunucu 5 saniye içinde yeniden başlatılacak.');
            if (msgEl) msgEl.textContent = 'Sunucu 5 saniye içinde kapatılıp yeniden başlatılacak. Açılmazsa .run/restart_helper.log dosyasını kontrol edin.';
        } else {
            var msg = (data.detail || data.message || 'İşlem başarısız.');
            if (typeof msg === 'object' && msg.detail) msg = msg.detail;
            if (window.Toast) window.Toast.error(msg);
            if (msgEl) msgEl.textContent = '';
        }
    } catch (e) {
        if (window.Toast) window.Toast.error('İstek hatası: ' + e.message);
        if (msgEl) msgEl.textContent = '';
    }
}

async function loadPendingRegistrations() {
    try {
        const res = await fetch('/api/admin/pending-registrations', { headers: adminAuthHeaders() });
        const data = await res.json();
        
        const container = document.getElementById('pendingContainer');
        const badge = document.getElementById('pendingBadge');
        
        if (data.count > 0) {
            badge.textContent = data.count;
            badge.style.display = 'inline-block';
        } else {
            badge.style.display = 'none';
        }
        
        if (data.pending.length === 0) {
            container.innerHTML = '<div class="empty-state">Bekleyen onay yok</div>';
        } else {
            container.innerHTML = data.pending.map(reg => `
                <div class="pending-item">
                    <div>
                        <strong>${reg.name} ${reg.surname}</strong>
                        <div style="font-size: 12px; color: var(--ds-text-secondary); margin-top: 4px;">
                            📞 ${reg.phone || 'Telefon yok'} • IP: ${reg.ip_address} • ${formatDateTime(reg.created_at) || '—'}
                        </div>
                    </div>
                    <div style="display: flex; gap: 0.5rem;">
                        <button class="btn primary" onclick="approveRegistration(${reg.id}, true)">Onayla</button>
                        <button class="btn danger" onclick="approveRegistration(${reg.id}, false)">Reddet</button>
                    </div>
                </div>
            `).join('');
        }
        
        // Load password reset requests
        try {
            const resetRes = await fetch('/api/admin/password-reset-requests', { credentials: 'same-origin', headers: adminAuthHeaders() });
            const resetData = await resetRes.json();
            const resetContainer = document.getElementById('passwordResetContainer');
            
            if (resetData.count === 0) {
                resetContainer.innerHTML = '<div class="empty-state">Bekleyen talep yok</div>';
            } else {
                resetContainer.innerHTML = resetData.requests.map(req => `
                    <div class="pending-item" style="position: relative;">
                        <button type="button" class="icon-btn" style="position: absolute; top: 0.5rem; right: 0.5rem; padding: 0.25rem 0.5rem; font-size: 1rem; line-height: 1; color: var(--ds-text-secondary);" onclick="dismissPasswordResetRequest(${req.id})" title="Kapat">×</button>
                        <div style="margin-right: 2rem;">
                            <strong>${req.user_name || ''} ${req.user_surname || ''}</strong>
                            <div style="font-size: 12px; color: var(--ds-text-secondary); margin-top: 4px;">
                                📞 ${req.phone} • Kullanıcı: ${req.username} • ${formatDateTime(req.created_at) || '—'}
                            </div>
                        </div>
                        <div style="display: flex; gap: 0.5rem; align-items: center;">
                            <span style="font-size: 12px; color: var(--ds-text-secondary);">Admin SMS ile yeni şifre atacak</span>
                        </div>
                    </div>
                `).join('');
            }
        } catch (resetError) {
            console.error('Error loading password reset requests:', resetError);
        }
    } catch (error) {
        console.error('Error loading pending registrations:', error);
    }
}

async function dismissPasswordResetRequest(requestId) {
    try {
        const res = await fetch('/api/admin/dismiss-password-reset-request', {
            method: 'POST',
            headers: adminAuthHeaders(),
            body: JSON.stringify({ request_id: requestId }),
            credentials: 'same-origin'
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || 'Kapatılamadı');
        if (window.Toast) window.Toast.success(data.message || 'Talep kapatıldı');
        loadPendingRegistrations();
    } catch (e) {
        if (window.Toast) window.Toast.error(e.message || 'Talep kapatılamadı');
    }
}

window.dismissPasswordResetRequest = dismissPasswordResetRequest;

async function approveRegistration(regId, approve) {
    try {
        const res = await fetch('/api/admin/approve-registration', {
            method: 'POST',
            headers: adminAuthHeaders(),
            credentials: 'same-origin',
            body: JSON.stringify({registration_id: regId, approve})
        });
        const data = await res.json();
        
        if (!res.ok) {
            throw new Error(data.detail || 'İşlem başarısız');
        }
        
        if (approve && data.username && data.temp_password) {
            // Show credentials in a modal or alert - make it more visible
            const message = `✅ KULLANICI ONAYLANDI!\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\nKULLANICI ADI: ${data.username}\nŞİFRE: ${data.temp_password}\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n⚠️ ÖNEMLİ: Bu bilgileri kullanıcıya SMS ile iletin!\n\nŞifre panoya kopyalandı.`;
            alert(message);
            // Also copy to clipboard if possible
            if (navigator.clipboard) {
                navigator.clipboard.writeText(`Kullanıcı Adı: ${data.username}\nŞifre: ${data.temp_password}`).catch(() => {});
            }
        }
        
        if (window.Toast) {
            window.Toast.success(data.message || (approve ? 'Kullanıcı onaylandı' : 'Başvuru reddedildi'));
        }
        
        loadPendingRegistrations();
        if (approve) {
            loadAccounts(); // Refresh accounts list
        }
    } catch (error) {
        console.error('Error approving registration:', error);
        if (window.Toast) {
            window.Toast.error(error.message || 'İşlem başarısız');
        }
    }
}

async function changeAdminPassword() {
    const oldPassword = document.getElementById('oldPassword').value;
    const newPassword = document.getElementById('newPassword').value;
    const newPasswordConfirm = document.getElementById('newPasswordConfirm').value;
    const statusEl = document.getElementById('adminPasswordStatus');
    
    if (!oldPassword || !newPassword || !newPasswordConfirm) {
        if (statusEl) {
            statusEl.textContent = 'Lütfen tüm alanları doldurun';
            statusEl.style.color = 'var(--ds-text-error, #f6465d)';
        }
        if (window.Toast) window.Toast.error('Lütfen tüm alanları doldurun');
        return;
    }
    
    // Check if passwords match
    if (newPassword !== newPasswordConfirm) {
        if (statusEl) {
            statusEl.textContent = 'Yeni şifreler eşleşmiyor';
            statusEl.style.color = 'var(--ds-text-error, #f6465d)';
        }
        if (window.Toast) window.Toast.error('Yeni şifreler eşleşmiyor');
        return;
    }
    
    if (statusEl) {
        statusEl.textContent = 'Güncelleniyor...';
        statusEl.style.color = 'var(--ds-text-secondary)';
    }
    
    try {
        const res = await fetch('/api/admin/change-password', {
            method: 'POST',
            headers: adminAuthHeaders(),
            credentials: 'same-origin',
            body: JSON.stringify({
                old_password: oldPassword,
                new_password: newPassword,
                new_password_confirm: newPasswordConfirm
            })
        });
        
        let data;
        try {
            data = await res.json();
        } catch (e) {
            throw new Error('Yanıt alınamadı');
        }
        
        if (!res.ok) {
            throw new Error(data.detail || 'Şifre değiştirilemedi');
        }
        
        if (statusEl) {
            statusEl.textContent = 'Şifre değiştirildi';
            statusEl.style.color = '#0ecb81';
        }
        if (window.Toast) {
            window.Toast.success('Şifre değiştirildi');
        }
        
        document.getElementById('oldPassword').value = '';
        document.getElementById('newPassword').value = '';
        document.getElementById('newPasswordConfirm').value = '';
    } catch (error) {
        console.error('Error changing password:', error);
        if (statusEl) {
            statusEl.textContent = error.message || 'Şifre değiştirilemedi';
            statusEl.style.color = 'var(--ds-text-error, #f6465d)';
        }
        if (window.Toast) {
            window.Toast.error(error.message || 'Şifre değiştirilemedi');
        }
    }
}

async function changeAdminUsername() {
    const newUsername = document.getElementById('adminUsername').value.trim();
    const statusEl = document.getElementById('adminUsernameStatus');
    
    if (!newUsername) {
        if (statusEl) {
            statusEl.textContent = 'Kullanıcı adı girin';
            statusEl.style.color = 'var(--ds-text-error, #f6465d)';
        }
        if (window.Toast) window.Toast.error('Kullanıcı adı girin');
        return;
    }
    
    if (newUsername.length < 3) {
        if (statusEl) {
            statusEl.textContent = 'Kullanıcı adı en az 3 karakter olmalıdır';
            statusEl.style.color = 'var(--ds-text-error, #f6465d)';
        }
        if (window.Toast) window.Toast.error('Kullanıcı adı en az 3 karakter olmalıdır');
        return;
    }
    
    if (statusEl) {
        statusEl.textContent = 'Güncelleniyor...';
        statusEl.style.color = 'var(--ds-text-secondary)';
    }
    
    try {
        const res = await fetch('/api/admin/change-username', {
            method: 'POST',
            headers: adminAuthHeaders(),
            credentials: 'same-origin',
            body: JSON.stringify({new_username: newUsername})
        });
        
        let data;
        try {
            data = await res.json();
        } catch (e) {
            throw new Error('Yanıt alınamadı');
        }
        
        if (!res.ok) {
            throw new Error(data.detail || 'Kullanıcı adı değiştirilemedi');
        }
        
        if (statusEl) {
            statusEl.textContent = 'Kullanıcı adı değiştirildi';
            statusEl.style.color = '#0ecb81';
        }
        if (window.Toast) {
            window.Toast.success('Kullanıcı adı değiştirildi');
        }
        
        const newName = (data && data.username) ? data.username : newUsername;
        try {
            const u = JSON.parse(sessionStorage.getItem('user') || '{}');
            u.username = newName;
            sessionStorage.setItem('user', JSON.stringify(u));
        } catch (e) {}
        const appbarEl = document.getElementById('adminAppbarUserName');
        if (appbarEl) appbarEl.textContent = (newName && String(newName).trim()) || 'Admin';
        const currentEl = document.getElementById('adminCurrentUsername');
        if (currentEl) currentEl.textContent = newName;
        const inputEl = document.getElementById('adminUsername');
        if (inputEl) {
            inputEl.value = '';
            inputEl.placeholder = 'Yeni kullanıcı adı (mevcut: ' + newName + ')';
        }
    } catch (error) {
        console.error('Error changing username:', error);
        if (statusEl) {
            statusEl.textContent = error.message || 'Kullanıcı adı değiştirilemedi';
            statusEl.style.color = 'var(--ds-text-error, #f6465d)';
        }
        if (window.Toast) {
            window.Toast.error(error.message || 'Kullanıcı adı değiştirilemedi');
        }
    }
}

async function loadBannedIPs() {
    try {
        const res = await fetch('/api/admin/banned-ips', { headers: adminAuthHeaders(), credentials: 'same-origin' });
        const data = await res.json();
        
        const container = document.getElementById('bannedIpsContainer');
        
        if (!data.banned_ips || data.banned_ips.length === 0) {
            container.innerHTML = '<div class="empty-state">Engellenen IP yok</div>';
            return;
        }
        
        container.innerHTML = data.banned_ips.map(ban => `
            <div class="pending-item">
                <div>
                    <strong style="font-family: monospace; color: var(--ds-danger);">${ban.ip_address}</strong>
                    <div style="font-size: 12px; color: var(--ds-text-secondary); margin-top: 4px;">
                        ${ban.reason ? `Sebep: ${ban.reason} • ` : ''}Engellenme: ${formatDateTime(ban.banned_at) || '—'}
                    </div>
                </div>
                <div style="display: flex; gap: 0.5rem;">
                    <button class="btn primary" onclick="unbanIP('${ban.ip_address}')">Engeli Kaldır</button>
                </div>
            </div>
        `).join('');
    } catch (error) {
        console.error('Error loading banned IPs:', error);
        const container = document.getElementById('bannedIpsContainer');
        container.innerHTML = '<div class="empty-state">Hata: Engellenen IP\'ler yüklenemedi</div>';
    }
}

async function unbanIP(ipAddress) {
    if (!confirm(`Bu IP adresinin engelini kaldırmak istediğinize emin misiniz?\n\nIP: ${ipAddress}`)) {
        return;
    }
    
    try {
        const res = await fetch('/api/admin/unban-ip', {
            method: 'POST',
            headers: adminAuthHeaders(),
            credentials: 'same-origin',
            body: JSON.stringify({ip_address: ipAddress})
        });
        const data = await res.json();
        
        if (!res.ok) {
            throw new Error(data.detail || 'İşlem başarısız');
        }
        
        if (window.Toast) {
            window.Toast.success('IP engeli kaldırıldı');
        }
        
        loadBannedIPs(); // Refresh list
    } catch (error) {
        console.error('Error unbanning IP:', error);
        if (window.Toast) {
            window.Toast.error(error.message || 'IP engeli kaldırılamadı');
        }
    }
}

async function banContactIP(ipAddress, messageId) {
    if (!confirm(`Bu IP adresini (${ipAddress}) engellemek istediğinize emin misiniz?`)) {
        return;
    }
    
    try {
        // Ban the IP using contact-reply endpoint with empty reply
        const banRes = await fetch('/api/admin/contact-reply', {
            method: 'POST',
            headers: adminAuthHeaders(),
            credentials: 'same-origin',
            body: JSON.stringify({message_id: messageId, reply: '', ban_ip: true})
        });
        
        let banData;
        try {
            banData = await banRes.json();
        } catch (jsonError) {
            // If response is not JSON (e.g., Internal Server Error), get text
            const text = await banRes.text();
            throw new Error(text || 'Sunucu hatası');
        }
        
        if (banRes.ok && banData.success) {
            if (window.Toast) window.Toast.success('IP adresi engellendi');
            loadPendingRegistrations(); // Refresh
        } else {
            throw new Error(banData.detail || 'IP engellenemedi');
        }
    } catch (error) {
        console.error('Error banning IP:', error);
        if (window.Toast) window.Toast.error(error.message || 'IP engellenemedi');
    }
}

function pollPendingAndChats() {
    fetch('/api/admin/pending-registrations', { credentials: 'same-origin', headers: adminAuthHeaders() })
        .then(r => r.json())
        .then(data => {
            const badge = document.getElementById('pendingBadge');
            if (badge) {
                if (data.count > 0) {
                    badge.textContent = data.count;
                    badge.style.display = 'inline-block';
                } else {
                    badge.style.display = 'none';
                }
            }
        })
        .catch(() => {});

    fetch('/api/admin/chats', { credentials: 'same-origin', headers: adminAuthHeaders() })
        .then(r => r.json())
        .then(data => {
            const badge = document.getElementById('contactBadge');
            const chats = data.chats || [];
            const totalUnread = chats.reduce((s, c) => s + (c.unread_count || 0), 0);
            if (badge) {
                if (totalUnread > 0) {
                    badge.textContent = totalUnread;
                    badge.style.display = 'inline-block';
                } else {
                    badge.style.display = 'none';
                }
            }
            const prev = window._adminChatPrevUnread || {};
            const cur = {};
            const viewing = (typeof adminChatSelected !== 'undefined' && adminChatSelected && adminChatSelected.user_id) ? adminChatSelected.user_id : null;
            chats.forEach(c => {
                const u = c.unread_count || 0;
                cur[c.user_id] = u;
                if (c.user_id !== viewing && u > (prev[c.user_id] || 0)) {
                    const name = [c.name, c.surname].filter(Boolean).join(' ').trim() || 'Kullanıcı';
                    if (window.Toast) window.Toast.success('Yeni mesaj: ' + name);
                }
            });
            window._adminChatPrevUnread = cur;
        })
        .catch(() => {});
}
pollPendingAndChats();
setInterval(pollPendingAndChats, 15000);

// Make functions global
window.loadAccounts = loadAccounts;
window.handleAdminTileClick = handleAdminTileClick;
window.navigateToAccount = navigateToAccount;
window.openCreateModal = openCreateModal;
window.closeCreateModal = closeCreateModal;
window.createAccount = createAccount;
window.openDeleteModal = openDeleteModal;
window.openDeleteModalFromButton = openDeleteModalFromButton;
window.closeDeleteModal = closeDeleteModal;
window.confirmDelete = confirmDelete;
window.switchTab = switchTab;
window.openSettingsTab = openSettingsTab;
window.adminDropAllAdminSessions = adminDropAllAdminSessions;
window.approveRegistration = approveRegistration;
window.changeAdminPassword = changeAdminPassword;
window.changeAdminUsername = changeAdminUsername;
window.loadBannedIPs = loadBannedIPs;
window.unbanIP = unbanIP;
window.banContactIP = banContactIP;

async function deleteContactMessage(messageId) {
    if (!confirm('Bu mesajı silmek istediğinize emin misiniz?')) {
        return;
    }
    
    try {
        const res = await fetch(`/api/admin/contact-messages/${messageId}`, {
            method: 'DELETE'
        });
        
        let data;
        try {
            data = await res.json();
        } catch (jsonError) {
            const text = await res.text().catch(() => 'Mesaj silinemedi');
            if (window.Toast) window.Toast.error(text || 'Mesaj silinemedi');
            return;
        }
        
        if (!res.ok) {
            throw new Error(data.detail || data.message || 'Mesaj silinemedi');
        }
        
        if (window.Toast) window.Toast.success('Mesaj silindi');
        
        // Reload contact messages
        loadContactMessages();
    } catch (error) {
        console.error('Error deleting contact message:', error);
        if (window.Toast) window.Toast.error(error.message || 'Mesaj silinemedi');
    }
}

window.deleteContactMessage = deleteContactMessage;

// Reply modal functions
let currentReplyMessageId = null;

function openReplyModal(messageId, userName) {
    currentReplyMessageId = messageId;
    document.getElementById('replyModalUserName').textContent = userName || 'Kullanıcı';
    document.getElementById('replyModalText').value = '';
    document.getElementById('replyModal').style.display = 'block';
}

function closeReplyModal() {
    document.getElementById('replyModal').style.display = 'none';
    currentReplyMessageId = null;
    document.getElementById('replyModalText').value = '';
}

async function confirmReply() {
    const replyText = document.getElementById('replyModalText').value.trim();
    
    if (!replyText) {
        if (window.Toast) window.Toast.error('Lütfen yanıt yazın');
        return;
    }
    
    if (!currentReplyMessageId) {
        if (window.Toast) window.Toast.error('Mesaj bulunamadı');
        return;
    }
    
    try {
        const res = await fetch('/api/admin/contact-reply', {
            method: 'POST',
            headers: adminAuthHeaders(),
            credentials: 'same-origin',
            body: JSON.stringify({
                message_id: currentReplyMessageId,
                reply: replyText,
                ban_ip: false
            })
        });
        
        let data;
        try {
            data = await res.json();
        } catch (e) {
            throw new Error('Yanıt alınamadı');
        }
        
        if (!res.ok) {
            throw new Error(data.detail || 'Yanıt gönderilemedi');
        }
        
        if (window.Toast) {
            window.Toast.success('Yanıt gönderildi');
        }
        
        closeReplyModal();
        loadContactMessages(); // Reload to show updated status
    } catch (error) {
        console.error('Error replying to message:', error);
        if (window.Toast) {
            window.Toast.error(error.message || 'Yanıt gönderilemedi');
        }
    }
}

window.openReplyModal = openReplyModal;
window.closeReplyModal = closeReplyModal;
window.confirmReply = confirmReply;

// Suspend/unsuspend user account
async function handleSuspendUser(button, suspend) {
    const userId = button.getAttribute('data-user-id');
    const accountId = button.getAttribute('data-account-id');
    
    if (!userId) {
        console.error('[admin] handleSuspendUser: Missing user_id');
        if (window.Toast) window.Toast.error('Kullanıcı ID bulunamadı');
        return;
    }
    
    const originalText = button.textContent;
    
    // Disable button and show loading state
    button.disabled = true;
    button.textContent = suspend ? 'Askıya alınıyor...' : 'Askıdan kaldırılıyor...';
    
    try {
        const response = await fetch('/api/admin/suspend-user', {
            method: 'POST',
            headers: Object.assign({ 'Accept': 'application/json' }, adminAuthHeaders()),
            credentials: 'same-origin',
            body: JSON.stringify({
                user_id: parseInt(userId),
                suspend: suspend
            })
        });
        
        if (!response.ok) {
            let errorData;
            try {
                errorData = await response.json();
            } catch (e) {
                errorData = { detail: `HTTP ${response.status}: ${response.statusText}` };
            }
            const errorMsg = errorData.detail || errorData.error || errorData.message || `HTTP ${response.status}`;
            throw new Error(errorMsg);
        }
        
        const data = await response.json();
        
        if (window.Toast) {
            window.Toast.success(data.message || (suspend ? 'Hesap askıya alındı' : 'Hesap askıdan kaldırıldı'));
        }
        
        invalidateAccountsAndSuspendedCache();
        await loadAccounts(true);
        await loadSuspendedAccounts();
        
    } catch (error) {
        console.error('[admin] Error suspending/unsuspending user:', error);
        if (window.Toast) {
            window.Toast.error(error.message || (suspend ? 'Hesap askıya alınamadı' : 'Hesap askıdan kaldırılamadı'));
        }
        // Restore button state
        button.disabled = false;
        button.textContent = originalText;
    }
}

window.handleSuspendUser = handleSuspendUser;

// Load suspended accounts
async function loadSuspendedAccounts(force = false) {
    const container = document.getElementById('suspendedTilesContainer');
    if (!container) return;
    
    try {
        const response = await fetch('/api/admin/accounts?suspended=true', {
            method: 'GET',
            headers: Object.assign({
                'Accept': 'application/json',
                'Cache-Control': 'no-cache'
            }, adminAuthHeaders()),
            cache: 'no-store'
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        
        const data = await response.json();
        const accounts = data.accounts || [];
        state.suspendedAccounts = accounts;
        AdminStore.cache.suspended.data = { accounts: accounts };
        AdminStore.cache.suspended.ts = Date.now();
        
        // Update badge
        const badge = document.getElementById('suspendedBadge');
        if (badge) {
            if (accounts.length > 0) {
                badge.textContent = accounts.length;
                badge.style.display = 'inline-block';
            } else {
                badge.style.display = 'none';
            }
        }
        
        if (accounts.length === 0) {
            container.innerHTML = '<div class="empty-state" style="grid-column: 1 / -1; text-align: center; padding: 3rem;">Askıya alınmış hesap yok</div>';
            return;
        }
        
        // Use the same renderTiles function to display suspended accounts
        renderTiles(accounts, container);
        
    } catch (error) {
        console.error('[admin] Error loading suspended accounts:', error);
        container.innerHTML = '<div class="empty-state" style="grid-column: 1 / -1; text-align: center; padding: 3rem;">Hesaplar yüklenirken hata oluştu</div>';
    }
}

window.loadSuspendedAccounts = loadSuspendedAccounts;

// --- Admin chat (İletişim tab) ---
let adminChatSelected = null; // { user_id, thread_id, name, locked, ended }
var adminChatPollTimer = null;
var ADMIN_CHAT_POLL_MS = 2500;
var _adminTypingHeartbeat = null;
var _adminTypingStopTimer = null;
var ADMIN_TYPING_HEARTBEAT_MS = 1500;
var ADMIN_TYPING_IDLE_MS = 2000;

function startAdminChatPoll() {
    stopAdminChatPoll();
    if (!adminChatSelected || state.currentTab !== 'contact') return;
    adminChatPollTimer = setInterval(function () {
        if (!adminChatSelected || state.currentTab !== 'contact') {
            stopAdminChatPoll();
            return;
        }
        loadAdminChatMessages();
        loadAdminChats();
    }, ADMIN_CHAT_POLL_MS);
}

function stopAdminChatPoll() {
    if (adminChatPollTimer) {
        clearInterval(adminChatPollTimer);
        adminChatPollTimer = null;
    }
}

async function loadAdminChats() {
    const container = document.getElementById('adminChatListContainer');
    if (!container) return;
    try {
        const res = await fetch('/api/admin/chats', { headers: adminAuthHeaders() });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || 'Sohbetler yüklenemedi');
        const chats = data.chats || [];
        const totalUnread = chats.reduce((s, c) => s + (c.unread_count || 0), 0);
        const badge = document.getElementById('contactBadge');
        if (badge) {
            if (totalUnread > 0) {
                badge.textContent = totalUnread;
                badge.style.display = 'inline-block';
            } else {
                badge.style.display = 'none';
            }
        }
        if (chats.length === 0) {
            container.innerHTML = '<div class="empty-state">Henüz sohbet yok</div>';
            return;
        }
        container.innerHTML = chats.map(c => {
            const name = [c.name, c.surname].filter(Boolean).join(' ').trim() || 'Kullanıcı';
            const sub = [c.phone, c.account_code].filter(Boolean).join(' · ') || '';
            const last = c.last_message_at ? (window.trTime && window.trTime.trFormatShort ? window.trTime.trFormatShort(c.last_message_at) : new Date(c.last_message_at).toLocaleString('tr-TR', { dateStyle: 'short', timeStyle: 'short', timeZone: 'Europe/Istanbul' })) : '';
            const avg = c.avg_rating != null ? Number(c.avg_rating) : (c.rating != null && c.rating >= 1 && c.rating <= 5 ? c.rating : null);
            const ratingStr = (avg != null && avg >= 1 && avg <= 5) ? ' ★ ' + (avg % 1 === 0 ? avg + '/5' : avg.toFixed(1) + '/5') : '';
            const unread = (c.unread_count || 0) > 0 ? `<span class="badge" style="font-size: 0.7rem;">${c.unread_count}</span>` : '';
            const locked = c.locked ? ' 🔒' : '';
            const online = c.online === true;
            const dotColor = online ? '#22c55e' : '#ef4444';
            const dotTitle = online ? 'Çevrimiçi' : 'Çevrimdışı';
            const statusDot = `<span class="admin-chat-status-dot" style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: ${dotColor}; margin-right: 6px; flex-shrink: 0; vertical-align: middle;" title="${dotTitle}" aria-hidden="true"></span>`;
            const sel = adminChatSelected && adminChatSelected.user_id === c.user_id ? ' background: var(--ds-bg-tertiary); border-radius: 8px;' : '';
            const displayName = (name + locked).replace(/'/g, "\\'").replace(/"/g, '&quot;');
            return `<button type="button" class="admin-chat-user" data-user-id="${c.user_id}" data-thread-id="${c.thread_id || ''}" style="text-align: left; padding: 0.6rem 0.75rem; border: none; background: transparent; color: var(--ds-text-primary); cursor: pointer; border-radius: 8px; display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; width: 100%;${sel}" onclick="selectAdminChat(${c.user_id}, ${c.thread_id || 'null'}, '${displayName}')">
                <div style="flex: 1; min-width: 0; display: flex; align-items: center;">
                    ${statusDot}
                    <div style="flex: 1; min-width: 0;">
                        <div style="font-weight: 600; font-size: 0.9rem;">${name}${locked}</div>
                        <div style="font-size: 0.75rem; color: var(--ds-text-secondary);">${sub} ${last ? '· ' + last : ''}${ratingStr}</div>
                    </div>
                </div>
                ${unread}
            </button>`;
        }).join('');
    } catch (e) {
        console.error('loadAdminChats:', e);
        if (container) container.innerHTML = '<div class="empty-state">Sohbetler yüklenemedi</div>';
    }
}

function scrollAdminChatListIntoView() {
    var el = document.getElementById('adminChatListContainer');
    if (el && el.scrollIntoView) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function notifyAdminTyping() {
    if (!adminChatSelected || !adminChatSelected.user_id) return;
    fetch('/api/admin/chats/typing', {
        method: 'POST',
        headers: adminAuthHeaders(),
        body: JSON.stringify({ user_id: adminChatSelected.user_id })
    }).catch(function () {});
}

function stopAdminTypingHeartbeat() {
    if (_adminTypingHeartbeat) {
        clearInterval(_adminTypingHeartbeat);
        _adminTypingHeartbeat = null;
    }
    if (_adminTypingStopTimer) {
        clearTimeout(_adminTypingStopTimer);
        _adminTypingStopTimer = null;
    }
}

function onAdminChatInput() {
    if (!adminChatSelected) return;
    notifyAdminTyping();
    if (_adminTypingStopTimer) clearTimeout(_adminTypingStopTimer);
    if (!_adminTypingHeartbeat) {
        _adminTypingHeartbeat = setInterval(notifyAdminTyping, ADMIN_TYPING_HEARTBEAT_MS);
    }
    _adminTypingStopTimer = setTimeout(stopAdminTypingHeartbeat, ADMIN_TYPING_IDLE_MS);
}

function selectAdminChat(userId, threadId, name) {
    adminChatSelected = { user_id: userId, thread_id: threadId, name: name || 'Kullanıcı' };
    document.getElementById('adminChatNoSelection').style.display = 'none';
    const active = document.getElementById('adminChatActive');
    active.style.display = 'flex';
    document.getElementById('adminChatUserName').textContent = name || 'Kullanıcı';
    document.getElementById('adminChatInput').value = '';
    loadAdminChatMessages();
    loadAdminChats(); // refresh list selection highlight
    startAdminChatPoll();
}

async function loadAdminChatMessages() {
    if (!adminChatSelected) return;
    const container = document.getElementById('adminChatMessages');
    if (!container) return;
    try {
        const res = await fetch(`/api/admin/chats/${adminChatSelected.user_id}/messages`, { headers: adminAuthHeaders() });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || 'Mesajlar yüklenemedi');
        const locked = !!data.locked;
        const ended = !!data.ended;
        const rating = data.rating != null ? Number(data.rating) : null;
        adminChatSelected.locked = locked;
        adminChatSelected.ended = ended;
        adminChatSelected.rating = rating;
        adminChatSelected.thread_id = data.thread_id;
        const hasThread = !!data.thread_id;
        const actDiv = document.getElementById('adminChatActions');
        if (actDiv) actDiv.style.display = hasThread ? 'flex' : 'none';
        document.getElementById('adminChatLockedBanner').style.display = locked ? 'block' : 'none';
        const endedBanner = document.getElementById('adminChatEndedBanner');
        endedBanner.style.display = ended ? 'block' : 'none';
        let endedText = 'Sohbet sonlandırıldı.';
        if (ended && rating != null && rating >= 1 && rating <= 5) {
            const stars = '★'.repeat(rating) + '☆'.repeat(5 - rating);
            endedText += ' Kullanıcı puanı: ' + stars + ' (' + rating + '/5)';
        }
        endedBanner.textContent = endedText;
        document.getElementById('adminChatInputWrap').style.display = ended ? 'none' : 'block';
        /* Sohbet esnasında ve sonlandıktan sonra tüm butonlar görünsün; sadece duruma göre aktif/pasif */
        document.getElementById('adminChatBtnLock').style.display = (hasThread && !locked && !ended) ? 'inline-flex' : 'none';
        document.getElementById('adminChatBtnUnlock').style.display = (hasThread && locked && !ended) ? 'inline-flex' : 'none';
        const btnEnd = document.getElementById('adminChatBtnEnd');
        if (btnEnd) {
            btnEnd.style.display = hasThread ? 'inline-flex' : 'none';
            btnEnd.disabled = !!ended;
            btnEnd.title = ended ? 'Sohbet zaten sonlandı' : '';
        }
        const btnReopen = document.getElementById('adminChatBtnReopen');
        if (btnReopen) {
            btnReopen.style.display = (hasThread && ended) ? 'inline-flex' : 'none';
            btnReopen.disabled = false;
        }
        const btnClear = document.getElementById('adminChatBtnClear');
        if (btnClear) btnClear.style.display = hasThread ? 'inline-flex' : 'none';
        const msgs = data.messages || [];
        let html = '';
        if (msgs.length === 0) {
            html = '<div class="empty-state" style="padding: 1.5rem;">Henüz mesaj yok</div>';
        } else {
            html = msgs.map(m => {
                const isAdmin = m.sender_type === 'admin';
                const time = m.created_at ? (window.trTime && window.trTime.trFormatTime ? window.trTime.trFormatTime(m.created_at) : new Date(m.created_at).toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Istanbul' })) : '';
                const read = m.read_at ? ' ✓✓' : (isAdmin ? '' : ' ✓');
                const style = isAdmin ? 'align-self: flex-end; background: var(--ds-accent); color: #000; border-radius: 12px 12px 4px 12px;' : 'align-self: flex-start; background: var(--ds-bg-tertiary); color: var(--ds-text-primary); border-radius: 12px 12px 12px 4px;';
                const body = (m.body || '').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
                return `<div style="display: flex; flex-direction: column; align-items: ${isAdmin ? 'flex-end' : 'flex-start'};">
                    <div style="max-width: 75%; padding: 0.5rem 0.75rem; word-wrap: break-word; ${style}">
                        <div style="font-size: 0.7rem; opacity: 0.85;">${isAdmin ? 'Admin' : 'Kullanıcı'}</div>
                        <div style="font-size: 0.9rem;">${body}</div>
                        <div style="font-size: 0.65rem; margin-top: 0.2rem; opacity: 0.8;">${time}${read}</div>
                    </div>
                </div>`;
            }).join('');
        }
        if (ended && rating != null && rating >= 1 && rating <= 5) {
            const stars = '★'.repeat(rating) + '☆'.repeat(5 - rating);
            html += '<div style="display: flex; justify-content: center; padding: 0.5rem 0;"><span style="font-size: 0.85rem; color: var(--ds-text-secondary);">Kullanıcı puanı: ' + stars + ' (' + rating + '/5)</span></div>';
        }
        container.innerHTML = html;
        container.scrollTop = container.scrollHeight;
    } catch (e) {
        console.error('loadAdminChatMessages:', e);
        if (container) container.innerHTML = '<div class="empty-state" style="color: var(--ds-danger);">Mesajlar yüklenemedi</div>';
    }
}

async function adminChatSend(e) {
    e.preventDefault();
    if (!adminChatSelected) return;
    const input = document.getElementById('adminChatInput');
    const msg = (input && input.value) ? input.value.trim() : '';
    if (!msg) return;
    try {
        const res = await fetch('/api/admin/chats/send', {
            method: 'POST',
            headers: adminAuthHeaders(),
            body: JSON.stringify({ user_id: adminChatSelected.user_id, message: msg })
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || 'Gönderilemedi');
        input.value = '';
        stopAdminTypingHeartbeat();
        await loadAdminChatMessages();
        loadAdminChats();
    } catch (err) {
        if (window.Toast) window.Toast.error(err.message || 'Gönderilemedi');
    }
}

async function adminChatLock() {
    if (!adminChatSelected || !adminChatSelected.thread_id) return;
    try {
        const res = await fetch(`/api/admin/chats/${adminChatSelected.thread_id}/lock`, { method: 'POST', headers: adminAuthHeaders() });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || 'İşlem başarısız');
        if (window.Toast) window.Toast.success('Sohbet kilitlendi');
        adminChatSelected.locked = true;
        await loadAdminChatMessages();
        loadAdminChats();
    } catch (err) {
        if (window.Toast) window.Toast.error(err.message || 'İşlem başarısız');
    }
}

async function adminChatUnlock() {
    if (!adminChatSelected || !adminChatSelected.thread_id) return;
    try {
        const res = await fetch(`/api/admin/chats/${adminChatSelected.thread_id}/unlock`, { method: 'POST', headers: adminAuthHeaders() });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || 'İşlem başarısız');
        if (window.Toast) window.Toast.success('Kilidi açıldı');
        adminChatSelected.locked = false;
        await loadAdminChatMessages();
        loadAdminChats();
    } catch (err) {
        if (window.Toast) window.Toast.error(err.message || 'İşlem başarısız');
    }
}

async function adminChatEnd() {
    if (!adminChatSelected || !adminChatSelected.thread_id) return;
    if (!confirm('Bu sohbeti sonlandırmak istediğinize emin misiniz? Artık mesaj gönderilemez.')) return;
    try {
        const res = await fetch(`/api/admin/chats/${adminChatSelected.thread_id}/end`, { method: 'POST', headers: adminAuthHeaders() });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || 'İşlem başarısız');
        if (window.Toast) window.Toast.success('Sohbet sonlandırıldı');
        adminChatSelected.ended = true;
        await loadAdminChatMessages();
        loadAdminChats();
    } catch (err) {
        if (window.Toast) window.Toast.error(err.message || 'İşlem başarısız');
    }
}

async function adminChatReopen() {
    if (!adminChatSelected || !adminChatSelected.thread_id) return;
    try {
        const res = await fetch(`/api/admin/chats/${adminChatSelected.thread_id}/reopen`, { method: 'POST', headers: adminAuthHeaders() });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || 'İşlem başarısız');
        if (window.Toast) window.Toast.success('Sohbet tekrar açıldı');
        await loadAdminChatMessages();
        loadAdminChats();
    } catch (err) {
        if (window.Toast) window.Toast.error(err.message || 'İşlem başarısız');
    }
}

async function adminChatClear() {
    if (!adminChatSelected || !adminChatSelected.thread_id) return;
    if (!confirm('Tüm mesajlar silinecek. Bu işlem geri alınamaz. Devam edilsin mi?')) return;
    try {
        const res = await fetch(`/api/admin/chats/${adminChatSelected.thread_id}/clear`, { method: 'POST', headers: adminAuthHeaders() });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || 'İşlem başarısız');
        if (window.Toast) window.Toast.success('Sohbet temizlendi');
        await loadAdminChatMessages();
        loadAdminChats();
    } catch (err) {
        if (window.Toast) window.Toast.error(err.message || 'İşlem başarısız');
    }
}

function openPopupForm(target) {
    document.getElementById('popupTarget').value = target;
    document.getElementById('popupModalTitle').textContent = target === 'first_login' ? 'İlk giriş yapan kullanıcıya Pop-Up' : 'Normal kullanıcıya Pop-Up';
    document.getElementById('popupMessage').value = '';
    var now = new Date();
    now.setDate(now.getDate() + 7);
    document.getElementById('popupValidUntil').value = now.toISOString().slice(0, 16);
    var maxShowsEl = document.getElementById('popupMaxShows');
    if (maxShowsEl) maxShowsEl.value = '1';
    document.getElementById('popupFormStatus').textContent = '';
    document.getElementById('popupCreateModal').style.display = 'flex';
}

function closePopupForm() {
    document.getElementById('popupCreateModal').style.display = 'none';
}

async function publishPopup(e) {
    e.preventDefault();
    var target = document.getElementById('popupTarget').value;
    var titleKey = document.getElementById('popupTitleKey').value;
    var message = document.getElementById('popupMessage').value.trim();
    var validUntil = document.getElementById('popupValidUntil').value;
    var maxShowsEl = document.getElementById('popupMaxShows');
    var maxShows = 1;
    if (maxShowsEl) { var v = parseInt(maxShowsEl.value, 10); if (!isNaN(v) && v >= 1) maxShows = v; }
    var statusEl = document.getElementById('popupFormStatus');
    if (!message) { statusEl.textContent = 'Mesaj girin.'; statusEl.style.color = 'var(--ds-danger)'; return; }
    var validDate = new Date(validUntil);
    if (validDate <= new Date()) { statusEl.textContent = 'Geçerlilik süresi gelecekte bir tarih olmalı.'; statusEl.style.color = 'var(--ds-danger)'; return; }
    statusEl.textContent = 'Yayınlanıyor...';
    statusEl.style.color = '';
    try {
        var res = await fetch('/api/admin/popups', {
            method: 'POST',
            headers: adminAuthHeaders(),
            credentials: 'same-origin',
            body: JSON.stringify({ target: target, title_key: titleKey, message: message, valid_until: validDate.toISOString(), max_shows_per_user: maxShows })
        });
        var data = await res.json().catch(function() { return {}; });
        if (!res.ok) {
            statusEl.textContent = data.detail || (Array.isArray(data.detail) ? data.detail.map(function(d) { return d.msg || d.message; }).join(', ') : 'İşlem başarısız');
            statusEl.style.color = 'var(--ds-danger)';
            return;
        }
        statusEl.textContent = 'Pop-up yayınlandı.';
        statusEl.style.color = 'var(--ds-success, #22c55e)';
        if (typeof window.Toast !== 'undefined' && window.Toast.success) window.Toast.success('Pop-up yayınlandı');
        loadPopupsList();
        setTimeout(closePopupForm, 1200);
    } catch (err) {
        statusEl.textContent = err.message || 'Bağlantı hatası';
        statusEl.style.color = 'var(--ds-danger)';
    }
}

async function loadPopupsList() {
    var container = document.getElementById('popupAdminList');
    if (!container) return;
    try {
        var res = await fetch('/api/admin/popups', { credentials: 'same-origin', headers: adminAuthHeaders() });
        var data = await res.json().catch(function() { return { popups: [] }; });
        var list = (data && data.popups) ? data.popups : [];
        if (list.length === 0) {
            container.innerHTML = '<p class="empty-state">Henüz pop-up yayınlanmamış.</p>';
            return;
        }
        container.innerHTML = list.map(function(p) {
            var active = p.is_active ? '<span class="badge" style="background: var(--ds-success); color: #fff;">Aktif</span>' : '<span class="badge" style="background: var(--ds-text-tertiary);">Süresi doldu</span>';
            var targetLabel = p.target === 'first_login' ? 'İlk giriş' : 'Normal kullanıcı';
            var titleLabels = { info: 'Bilgi', warning: 'Uyarı', success: 'Başarı', maintenance: 'Bakım', announcement: 'Duyuru' };
            var titleLabel = titleLabels[p.title_key] || p.title_key;
            var maxShows = p.max_shows_per_user != null ? p.max_shows_per_user : 1;
            var showCountText = maxShows === 1 ? 'Tek seferlik' : 'En fazla ' + maxShows + ' kere';
            return '<div class="popup-admin-item popup-admin-item-clickable" data-popup-id="' + p.id + '" onclick="openPopupDetail(' + p.id + ')" role="button" tabindex="0" title="Detay ve görüntüleyen kullanıcılar">' +
                '<div class="popup-admin-item-row">' +
                '<div class="popup-admin-item-content">' +
                '<div class="popup-admin-item-meta">' + active + ' <strong>' + targetLabel + '</strong> · ' + titleLabel + ' · ' + showCountText + ' · Geçerlilik: ' + (p.valid_until || '').slice(0, 16) + '</div>' +
                '<div class="popup-admin-item-msg">' + (p.message || '').slice(0, 120) + (p.message && p.message.length > 120 ? '…' : '') + '</div>' +
                '</div>' +
                '<button type="button" class="btn btn-sm popup-admin-item-remove" onclick="event.stopPropagation(); deletePopup(' + p.id + ')" title="Yayından kaldır">Kaldır</button>' +
                '</div>' +
                '</div>';
        }).join('');
    } catch (err) {
        container.innerHTML = '<p class="empty-state">Yüklenemedi.</p>';
    }
}

async function deletePopup(popupId) {
    if (!confirm('Bu pop-up yayından kaldırılacak. Kullanıcılar bir daha görmeyecek. Devam?')) return;
    try {
        var res = await fetch('/api/admin/popups/' + popupId, { method: 'DELETE', credentials: 'same-origin', headers: adminAuthHeaders() });
        var data = await res.json().catch(function() { return {}; });
        if (!res.ok) {
            if (window.Toast && window.Toast.error) window.Toast.error(data.detail || 'Kaldırılamadı');
            return;
        }
        if (window.Toast && window.Toast.success) window.Toast.success('Pop-up kaldırıldı');
        loadPopupsList();
    } catch (err) {
        if (window.Toast && window.Toast.error) window.Toast.error(err.message || 'Bağlantı hatası');
    }
}

function formatPopupDismissedAt(isoStr, offsetHours) {
    if (!isoStr) return '—';
    var d = new Date(isoStr.replace('Z', '+00:00'));
    if (isNaN(d.getTime())) return (isoStr || '').slice(0, 19).replace('T', ' ');
    var t = d.getTime() + (offsetHours || 0) * 60 * 60 * 1000;
    var x = new Date(t);
    var y = x.getUTCFullYear();
    var m = String(x.getUTCMonth() + 1).padStart(2, '0');
    var day = String(x.getUTCDate()).padStart(2, '0');
    var h = String(x.getUTCHours()).padStart(2, '0');
    var min = String(x.getUTCMinutes()).padStart(2, '0');
    var s = String(x.getUTCSeconds()).padStart(2, '0');
    return y + '-' + m + '-' + day + ' ' + h + ':' + min + ':' + s;
}

function closePopupDetail() {
    var modal = document.getElementById('popupDetailModal');
    if (modal) modal.style.display = 'none';
}

async function openPopupDetail(popupId) {
    var modal = document.getElementById('popupDetailModal');
    var metaEl = document.getElementById('popupDetailMeta');
    var msgEl = document.getElementById('popupDetailMessage');
    var dismissalsEl = document.getElementById('popupDetailDismissals');
    if (!modal || !metaEl || !msgEl || !dismissalsEl) return;
    dismissalsEl.innerHTML = '<p style="margin: 0; padding: 0.5rem 0;">Yükleniyor…</p>';
    modal.style.display = 'flex';
    try {
        var res = await fetch('/api/admin/popups/' + popupId, { credentials: 'same-origin', headers: adminAuthHeaders() });
        var data = await res.json().catch(function() { return {}; });
        if (!res.ok) {
            dismissalsEl.innerHTML = '<p style="margin: 0; color: var(--ds-danger);">Yüklenemedi.</p>';
            return;
        }
        var p = data.popup || {};
        var targetLabel = p.target === 'first_login' ? 'İlk giriş' : 'Normal kullanıcı';
        var titleLabels = { info: 'Bilgi', warning: 'Uyarı', success: 'Başarı', maintenance: 'Bakım', announcement: 'Duyuru' };
        var titleLabel = titleLabels[p.title_key] || p.title_key;
        var maxShows = p.max_shows_per_user != null ? p.max_shows_per_user : 1;
        var showCountText = maxShows === 1 ? 'Tek seferlik' : 'En fazla ' + maxShows + ' kere';
        var active = p.is_active ? 'Aktif' : 'Süresi doldu';
        metaEl.textContent = active + ' · ' + targetLabel + ' · ' + titleLabel + ' · ' + showCountText + ' · Geçerlilik: ' + (p.valid_until || '').slice(0, 16);
        msgEl.textContent = p.message || '';
        var list = data.dismissals || [];
        if (list.length === 0) {
            dismissalsEl.innerHTML = '<p style="margin: 0; padding: 0.5rem 0; color: var(--ds-text-tertiary);">Henüz görüntüleyen kullanıcı yok.</p>';
        } else {
            var utcOffsetHours = 3;
            dismissalsEl.innerHTML = '<ul style="margin: 0; padding-left: 1.25rem;">' + list.map(function(d) {
                var at = formatPopupDismissedAt(d.dismissed_at, utcOffsetHours);
                return '<li>' + (d.user_name || 'Kullanıcı #' + d.user_id).trim() + ' <span style="color: var(--ds-text-tertiary); font-size: 0.85em;">(' + at + ')</span></li>';
            }).join('') + '</ul>';
        }
    } catch (err) {
        dismissalsEl.innerHTML = '<p style="margin: 0; color: var(--ds-danger);">' + (err.message || 'Bağlantı hatası') + '</p>';
    }
}

window.openPopupForm = openPopupForm;
window.closePopupForm = closePopupForm;
window.publishPopup = publishPopup;
window.loadPopupsList = loadPopupsList;
window.deletePopup = deletePopup;
window.openPopupDetail = openPopupDetail;
window.closePopupDetail = closePopupDetail;

window.loadAdminChats = loadAdminChats;
window.selectAdminChat = selectAdminChat;
window.adminChatSend = adminChatSend;
window.adminChatLock = adminChatLock;
window.adminChatUnlock = adminChatUnlock;
window.adminChatEnd = adminChatEnd;
window.adminChatReopen = adminChatReopen;
window.adminChatClear = adminChatClear;
window.loadContactMessages = loadAdminChats;

window.__ADMIN_DEBUG = false;
window.__adminDump = function () {
    var list = document.querySelector('.admin-tabs-list');
    return {
        currentTab: state.currentTab,
        switchToken: state.switchToken,
        menuOpen: list ? list.classList.contains('admin-tabs-list--open') : false,
        listParent: list && list.parentNode ? (list.parentNode.id || list.parentNode.tagName) : null,
        cacheTs: Object.keys(AdminStore.cache).reduce(function (acc, k) {
            acc[k] = AdminStore.cache[k].ts;
            return acc;
        }, {})
    };
};

/*
MANUAL ACCEPTANCE (admin tabs perf + mobile):
1. Mobile width 375: tap Sekmeler => menu visible, __adminDump().listParent === 'adminTabsPortal', display flex.
2. Tap outside => menu closes.
3. Tap a tab => panel switches and menu closes.
4. Desktop: switch tabs rapidly => no stale render; network shows <=1 request per tab within TTL.
5. First load: accounts skeleton immediately, data arrives, preload runs max 2 concurrent.
6. Set window.__ADMIN_DEBUG = true for console.debug toggle/position/cache logs.
*/
