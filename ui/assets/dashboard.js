/**
 * FILE: dashboard.js
 * VERSION: vREBUILD1
 * DATE: 2026-01-22
 * CHANGE: Bot listesi komple sıfırdan yazıldı - backend API'ye direkt bağlan, basit render
 */

// Global State
const State = {
    accountId: null,
    accountCode: null,
    accountMeta: null,
    summary: null,
    bots: [],
    botLiveEquity: {},
    loading: false,
    inFlight: false,
    lastSummaryHash: "",
    timers: { summary: null, bots: null }
};

/** Mobil görünüm (≤768px) – tek kaynak, resize'ta güncellenir */
// ============================================================
// DataHub REMOVED – Use marketStore only (single source of truth)
// UI reads from marketStore; marketDataService populates it via /api/data/hub
// ============================================================
const DataHub = {
    prices: new Map(),
    updateTimer: null,
    getPrice: () => null,
    getAllPrices: () => ({}),
    getCoinList: () => [],
    getAccountBalance: () => null,
    update: () => {},
    start: () => { console.warn("[DataHub] DEPRECATED: use marketDataService + marketStore"); },
    stop: () => {}
};
window.DataHub = DataHub;

// Price cache for instant updates (JET HIZLI)
let priceCache = {};
let priceCacheTime = {};

// ============================================================
// PERFORMANCE HOTFIX: SpotCache - Global Warm Cache Layer
// ============================================================
const SPOT_CACHE_MAX_PRICES = 400;
const SPOT_CACHE_MAX_FILTERS = 200;

const SpotCache = {
    prices: new Map(),      // symbol -> {price, ts}
    balances: new Map(),    // accountId -> {freeUSDT, freeBase, assetsMap, ts}
    filters: new Map(),      // symbol -> {tickSize, stepSize, minNotional, ts}
    
    // TTL constants
    PRICE_TTL: 2000,        // 2s
    BALANCE_TTL: 3000,      // 3s
    FILTER_TTL: 6 * 60 * 60 * 1000, // 6 hours

    _trimMap(map, maxKeys) {
        while (map.size > maxKeys) {
            const first = map.keys().next().value;
            if (first === undefined) break;
            map.delete(first);
        }
    },
    
    // Get cached price
    getPrice(symbol) {
        const entry = this.prices.get(symbol);
        if (!entry) return null;
        const age = Date.now() - entry.ts;
        if (age > this.PRICE_TTL) {
            this.prices.delete(symbol);
            return null;
        }
        return entry.price;
    },
    
    // Set cached price
    setPrice(symbol, price) {
        this.prices.set(symbol, { price, ts: Date.now() });
        this._trimMap(this.prices, SPOT_CACHE_MAX_PRICES);
    },
    
    // Get cached balance (accountId -> { ...balanceData, ts })
    getBalance(accountId) {
        if (!accountId) return null;
        const entry = this.balances.get(accountId);
        if (!entry || !entry.ts) return null;
        const age = Date.now() - entry.ts;
        if (age > this.BALANCE_TTL) {
            this.balances.delete(accountId);
            return null;
        }
        return entry;
    },
    
    // Set cached balance
    setBalance(accountId, balanceData) {
        if (!accountId) return;
        this.balances.set(accountId, { ...balanceData, ts: Date.now() });
    },
    
    // Get cached filters
    getFilters(symbol) {
        const entry = this.filters.get(symbol);
        if (!entry) return null;
        const age = Date.now() - entry.ts;
        if (age > this.FILTER_TTL) {
            this.filters.delete(symbol);
            return null;
        }
        return entry;
    },
    
    // Set cached filters
    setFilters(symbol, filterData) {
        this.filters.set(symbol, { ...filterData, ts: Date.now() });
        this._trimMap(this.filters, SPOT_CACHE_MAX_FILTERS);
    }
};

// AbortController registry for modal cleanup
let modalAbortController = null;
// Modal logo flicker önleme: sadece base değişince logo DOM güncellenir
let lastModalLogoBase = null;

// Lazy coin logos: cache loaded URLs; IntersectionObserver sets src when in viewport
window.coinLogoCache = window.coinLogoCache || new Map();
function ensureLazyLogoObserver() {
    if (window._lazyLogoObserver) return;
    window._lazyLogoObserver = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
            if (!entry.isIntersecting) return;
            var img = entry.target;
            var dataSrc = img.getAttribute('data-src');
            if (!dataSrc) return;
            if (window.coinLogoCache.get(dataSrc)) { img.src = dataSrc; img.removeAttribute('data-src'); return; }
            img.src = dataSrc;
            img.removeAttribute('data-src');
            window.coinLogoCache.set(dataSrc, true);
        });
    }, { rootMargin: '50px', threshold: 0.01 });
}
function observeLazyLogos(container) {
    if (!container) return;
    ensureLazyLogoObserver();
    container.querySelectorAll('img.lazy-coin-logo[data-src]').forEach(function (el) { window._lazyLogoObserver.observe(el); });
}

// Format helpers
/** Nokta ve virgül geçerli ondalık parse (0,5 veya 0.5) */
// Error banner
// Binance API Error Banner Management
let binanceApiErrorState = {
    isError: false,
    lastErrorTime: null,
    errorType: null, // 'rate_limit', 'ip_banned', 'bad_gateway', etc.
    retryAfter: null, // Timestamp when API will be available again
    retryAfterSeconds: null // Seconds until retry
};

function showBinanceApiBanner(errorType = 'rate_limit', error = null) {
    const banner = document.getElementById("binanceApiBanner");
    const messageEl = document.getElementById("binanceApiBannerMessage");
    
    if (!banner || !messageEl) return;
    
    // Extract retry/ban information from error
    let retryAfter = null;
    let retryAfterSeconds = null;
    let banUntil = null;
    
    if (error) {
        // Check error.detail first (APIError format)
        const errorDetail = error.detail || (typeof error === 'object' && error.detail ? error.detail : null);
        
        // Try to get ban_until from error object (priority - this is the real time from Binance)
        if (errorDetail && typeof errorDetail === 'object') {
            if (errorDetail.ban_until !== undefined) {
                banUntil = parseInt(errorDetail.ban_until);
                retryAfter = banUntil;
                retryAfterSeconds = Math.max(0, Math.floor((banUntil - Date.now()) / 1000));
            } else if (errorDetail.banUntil !== undefined) {
                banUntil = parseInt(errorDetail.banUntil);
                retryAfter = banUntil;
                retryAfterSeconds = Math.max(0, Math.floor((banUntil - Date.now()) / 1000));
            }
            
            // Try to get retry_after from error object (fallback if no ban_until)
            if (!banUntil && errorDetail.retry_after !== undefined) {
                retryAfterSeconds = parseInt(errorDetail.retry_after);
                retryAfter = Date.now() + (retryAfterSeconds * 1000);
            } else if (!banUntil && errorDetail.retryAfter !== undefined) {
                retryAfterSeconds = parseInt(errorDetail.retryAfter);
                retryAfter = Date.now() + (retryAfterSeconds * 1000);
            }
        }
        
        // Fallback: Try direct properties on error object
        if (!banUntil && !retryAfter) {
            if (error.ban_until !== undefined) {
                banUntil = parseInt(error.ban_until);
                retryAfter = banUntil;
                retryAfterSeconds = Math.max(0, Math.floor((banUntil - Date.now()) / 1000));
            } else if (error.banUntil !== undefined) {
                banUntil = parseInt(error.banUntil);
                retryAfter = banUntil;
                retryAfterSeconds = Math.max(0, Math.floor((banUntil - Date.now()) / 1000));
            } else if (error.retry_after !== undefined) {
                retryAfterSeconds = parseInt(error.retry_after);
                retryAfter = Date.now() + (retryAfterSeconds * 1000);
            } else if (error.retryAfter !== undefined) {
                retryAfterSeconds = parseInt(error.retryAfter);
                retryAfter = Date.now() + (retryAfterSeconds * 1000);
            }
        }
        
        // Try to extract from error message
        if (!retryAfter && !banUntil) {
            const errorMessage = error.message || '';
            const errorDetail = error.detail || (typeof error.message === 'object' ? error.message : null);
            
            // Check for "banned until" timestamp
            const banMatch = errorMessage.match(/banned until (\d+)/i) || 
                            (errorDetail && typeof errorDetail === 'string' ? errorDetail.match(/banned until (\d+)/i) : null) ||
                            (errorDetail && typeof errorDetail === 'object' && errorDetail.detail ? String(errorDetail.detail).match(/banned until (\d+)/i) : null);
            
            if (banMatch) {
                banUntil = parseInt(banMatch[1]);
                retryAfter = banUntil;
                retryAfterSeconds = Math.max(0, Math.floor((banUntil - Date.now()) / 1000));
            }
            
            // Check for "retry after" seconds
            const retryMatch = errorMessage.match(/retry after (\d+)/i) || 
                             (errorDetail && typeof errorDetail === 'string' ? errorDetail.match(/retry after (\d+)/i) : null);
            
            if (retryMatch && !retryAfter) {
                retryAfterSeconds = parseInt(retryMatch[1]);
                retryAfter = Date.now() + (retryAfterSeconds * 1000);
            }
        }
    }
    
    // Store retry information - only use default if we have NO information from Binance
    // If we have ban_until or retry_after from Binance, use that instead
    if (!retryAfter && !banUntil) {
        // No information from Binance, don't show fake time
        // Just show error without time estimate
        const message = "Binance API geçici olarak kilitli. Veriler güncellenemiyor. Lütfen birkaç dakika bekleyip tekrar deneyin.";
        messageEl.textContent = message;
        binanceApiErrorState.retryAfter = null;
        binanceApiErrorState.retryAfterSeconds = null;
        return;
    }
    
    // If we have ban_until, use it (it's in milliseconds from Binance)
    if (banUntil) {
        retryAfter = banUntil;
        retryAfterSeconds = Math.max(0, Math.floor((banUntil - Date.now()) / 1000));
    } else if (retryAfterSeconds != null && retryAfterSeconds > 0) {
        // If we have retry_after in seconds, calculate retryAfter timestamp
        retryAfter = Date.now() + (retryAfterSeconds * 1000);
    } else {
        // No valid information, don't show time
        const message = "Binance API geçici olarak kilitli. Veriler güncellenemiyor. Lütfen birkaç dakika bekleyip tekrar deneyin.";
        messageEl.textContent = message;
        binanceApiErrorState.retryAfter = null;
        binanceApiErrorState.retryAfterSeconds = null;
        return;
    }
    binanceApiErrorState.retryAfter = retryAfter;
    binanceApiErrorState.retryAfterSeconds = retryAfterSeconds;
    
    // Determine message based on error type
    let message = "Binance API geçici olarak kilitli. Veriler güncellenemiyor.";
    if (errorType === 'ip_banned' || errorType === '418') {
        message = "Binance API IP engeli tespit edildi. Veriler güncellenemiyor.";
    } else if (errorType === 'bad_gateway' || errorType === '502') {
        message = "Binance API bağlantı hatası. Veriler güncellenemiyor.";
    } else if (errorType === 'rate_limit' || errorType === '429') {
        message = "Binance API rate limit aşıldı. Veriler güncellenemiyor.";
    }
    
    // Always show exact time (saat kaçta açılacak)
    const retryDate = new Date(retryAfter);
    const timeStr = retryDate.toLocaleString('tr-TR', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
    });
    let countdown = '';
    if (retryAfterSeconds < 60) {
        countdown = `${retryAfterSeconds} saniye`;
    } else if (retryAfterSeconds < 3600) {
        countdown = `${Math.ceil(retryAfterSeconds / 60)} dakika`;
    } else {
        const h = Math.floor(retryAfterSeconds / 3600);
        const m = Math.floor((retryAfterSeconds % 3600) / 60);
        countdown = m > 0 ? `${h} saat ${m} dakika` : `${h} saat`;
    }
    message += ` API yaklaşık ${countdown} sonra tekrar açılacak. Açılma saati: ${timeStr}.`;
    
    messageEl.textContent = message;
    
    // Only show banner on "Anasayfa" (reports) or "Binance" tabs
    const activeTab = document.querySelector('.dm-tab.is-active');
    if (activeTab) {
        const tabName = activeTab.getAttribute('data-tab');
        if (tabName === 'reports' || tabName === 'binance') {
            banner.style.display = 'flex';
            binanceApiErrorState.isError = true;
            binanceApiErrorState.lastErrorTime = Date.now();
            binanceApiErrorState.errorType = errorType;
            
            // Use intervalRegistry so interval is cleaned on unload / tab switch
            if (window.intervalRegistry) {
                window.intervalRegistry.stop("binanceApiBanner.time");
                window.intervalRegistry.start("binanceApiBanner.time", updateBinanceApiBannerTime, 10000, "dashboard");
            } else {
                if (window.binanceApiBannerUpdateInterval) clearInterval(window.binanceApiBannerUpdateInterval);
                window.binanceApiBannerUpdateInterval = setInterval(updateBinanceApiBannerTime, 10000);
            }
        }
    }
}

function hideBinanceApiBanner() {
    const banner = document.getElementById("binanceApiBanner");
    if (banner) {
        banner.style.display = 'none';
        binanceApiErrorState.isError = false;
        binanceApiErrorState.errorType = null;
        binanceApiErrorState.retryAfter = null;
        binanceApiErrorState.retryAfterSeconds = null;
    }
    if (window.intervalRegistry) {
        window.intervalRegistry.stop("binanceApiBanner.time");
    }
    if (window.binanceApiBannerUpdateInterval) {
        clearInterval(window.binanceApiBannerUpdateInterval);
        window.binanceApiBannerUpdateInterval = null;
    }
}

// Update banner message with remaining time
function updateBinanceApiBannerTime() {
    if (!binanceApiErrorState.isError || !binanceApiErrorState.retryAfter) {
        return;
    }
    
    const now = Date.now();
    const remainingSeconds = Math.max(0, Math.floor((binanceApiErrorState.retryAfter - now) / 1000));
    
    if (remainingSeconds <= 0) {
        // Time expired, hide banner
        hideBinanceApiBanner();
        return;
    }
    
    const messageEl = document.getElementById("binanceApiBannerMessage");
    if (!messageEl) return;
    
    // Get base message (without time part)
    const baseMessages = {
        'rate_limit': 'Binance API rate limit aşıldı. Veriler güncellenemiyor.',
        'ip_banned': 'Binance API IP engeli tespit edildi. Veriler güncellenemiyor.',
        'bad_gateway': 'Binance API bağlantı hatası. Veriler güncellenemiyor.',
        '418': 'Binance API IP engeli tespit edildi. Veriler güncellenemiyor.',
        '429': 'Binance API rate limit aşıldı. Veriler güncellenemiyor.',
        '502': 'Binance API bağlantı hatası. Veriler güncellenemiyor.'
    };
    
    const baseMessage = baseMessages[binanceApiErrorState.errorType] || 'Binance API geçici olarak kilitli. Veriler güncellenemiyor.';
    
    const retryDate = new Date(binanceApiErrorState.retryAfter);
    const timeStr = retryDate.toLocaleString('tr-TR', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
    });
    let countdown = '';
    if (remainingSeconds < 60) {
        countdown = `${remainingSeconds} saniye`;
    } else if (remainingSeconds < 3600) {
        countdown = `${Math.ceil(remainingSeconds / 60)} dakika`;
    } else {
        const h = Math.floor(remainingSeconds / 3600);
        const m = Math.floor((remainingSeconds % 3600) / 60);
        countdown = m > 0 ? `${h} saat ${m} dakika` : `${h} saat`;
    }
    const fullMessage = `${baseMessage} API yaklaşık ${countdown} sonra tekrar açılacak. Açılma saati: ${timeStr}.`;
    messageEl.textContent = fullMessage;
}

// Helper function to check current rate limit status (for console debugging)
window.checkBinanceRateLimit = function() {
    const state = binanceApiErrorState;
    if (!state.isError) {
        console.log('✅ Binance API rate limit yok - Sistem normal çalışıyor');
        console.log('ℹ️ Yeni sistem WebSocket kullanıyor, rate limit riski çok düşük');
        return null;
    }
    
    const now = Date.now();
    const remainingSeconds = state.retryAfter ? Math.max(0, Math.floor((state.retryAfter - now) / 1000)) : null;
    
    if (remainingSeconds === null || remainingSeconds <= 0) {
        console.log('✅ Rate limit süresi dolmuş - Sistem normal çalışıyor');
        return null;
    }
    
    const retryDate = new Date(state.retryAfter);
    const info = {
        errorType: state.errorType,
        remainingSeconds: remainingSeconds,
        remainingMinutes: Math.ceil(remainingSeconds / 60),
        retryAfter: retryDate.toLocaleString('tr-TR', {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        }),
        timestamp: retryDate.getTime()
    };
    
    console.log('⚠️ Binance API Rate Limit Aktif:');
    console.log(`   Tip: ${info.errorType}`);
    console.log(`   Kalan Süre: ${info.remainingMinutes} dakika (${info.remainingSeconds} saniye)`);
    console.log(`   Açılma Zamanı: ${info.retryAfter}`);
    console.log(`   Timestamp: ${info.timestamp}`);
    
    return info;
};

// Check if we should show banner based on active tab
function updateBinanceApiBannerVisibility() {
    const activeTab = document.querySelector('.dm-tab.is-active');
    if (!activeTab) return;
    
    const tabName = activeTab.getAttribute('data-tab');
    const banner = document.getElementById("binanceApiBanner");
    
    if (banner && binanceApiErrorState.isError) {
        // Show only on reports, binance, or trade tabs
        if (tabName === 'reports' || tabName === 'binance' || tabName === 'trade') {
            banner.style.display = 'flex';
        } else {
            banner.style.display = 'none';
        }
    }
}

/** API bağlantı uyarısı: en üstte; sadece Anasayfa, Binance, Botlar’da (Finansal Hesap, İletişim, Ayarlar’da gösterilmez). API key girilmemişse gösterilir. */
async function updateBinanceConnectionNotice() {
    const notice = document.getElementById('binanceConnectionNotice');
    if (!notice || !State.accountId) return;
    if (assetsState.wallet.keys_configured === true) {
        notice.style.display = 'none';
        notice.classList.add('binance-connection-notice--hidden');
        return;
    }
    try {
        const data = await window.apiClient.get(`/api/accounts/${State.accountId}/settings`);
        if (data.has_binance_keys) {
            assetsState.wallet.keys_configured = true;
            notice.style.display = 'none';
            notice.classList.add('binance-connection-notice--hidden');
        } else {
            assetsState.wallet.keys_configured = false;
            notice.classList.remove('binance-connection-notice--hidden');
            notice.style.display = 'block';
        }
        var kpiLive = document.getElementById('kpiCuzdanLive');
        var kpiBotPct = document.getElementById('kpiBotBakiyePct');
        applyWalletStaleWarningEl(kpiLive);
        applyWalletStaleWarningEl(kpiBotPct);
    } catch (_) {
        if (assetsState.wallet.keys_configured === true || (typeof isWalletDataLive === 'function' && isWalletDataLive())) {
            notice.style.display = 'none';
            notice.classList.add('binance-connection-notice--hidden');
            return;
        }
        assetsState.wallet.keys_configured = false;
        notice.classList.remove('binance-connection-notice--hidden');
        notice.style.display = 'block';
        var fallbackLabel = (typeof State !== 'undefined' && State.isTestAccount) ? 'Test' : 'Bağlı değil';
        patchText('kpiCuzdanLive', '');
        patchText('kpiBotBakiyePct', '');
        applyWalletStaleWarningEl(document.getElementById('kpiCuzdanLive'));
        applyWalletStaleWarningEl(document.getElementById('kpiBotBakiyePct'));
    }
}

function hideBinanceConnectionNoticeIfWalletReady() {
    if (!assetsState || !assetsState.wallet) return;
    if (assetsState.wallet.keys_configured !== true && !(typeof isWalletDataLive === 'function' && isWalletDataLive())) return;
    var notice = document.getElementById('binanceConnectionNotice');
    if (!notice) return;
    notice.style.display = 'none';
    notice.classList.add('binance-connection-notice--hidden');
}

/** Yenileme / sekme değişimi / istemci kopması — kalıcı hata banner'ı gösterme. */
function isBenignDashboardFetchError(error) {
    if (!error) return false;
    if (error.name === 'AbortError') return true;
    var status = Number(error.status) || 0;
    if (status === 499) return true;
    var code = String(error.error_code || '').toUpperCase();
    if (code === 'CLIENT_DISCONNECT' || code === 'TIMEOUT') return true;
    var msg = String(error.message || '').toLowerCase();
    return msg.indexOf('client_disconnect') >= 0 || msg.indexOf('aborted') >= 0;
}
window.isBenignDashboardFetchError = isBenignDashboardFetchError;

function showError(message) {
    const banner = document.getElementById("errorBanner");
    const msg = document.getElementById("errorMessage");
    if (banner && msg) {
        const translatedMsg = translateErrorToTurkish(message);
        msg.textContent = translatedMsg;
        banner.style.display = "flex";
        // Artık otomatik gizleme yok: hata, başarılı yükleme (hideError) veya kullanıcı ✕ ile kapatana kadar kalır
    }
    console.error("[dashboard]", message);
}

function hideError() {
    const banner = document.getElementById("errorBanner");
    if (banner) banner.style.display = "none";
}

/** 5–7 haneli rakam: DB account_id değil, account_code. */
function looksLikeNumericAccountCode(value) {
    const s = String(value == null ? "" : value).trim();
    return /^\d{5,7}$/.test(s);
}

function isDashboardAdminContext() {
    const qs = new URLSearchParams(location.search);
    if (qs.get("from_admin") === "1") return true;
    try { return sessionStorage.getItem("dashboard_from_admin") === "1"; } catch (e) { return false; }
}

function persistSelectedAccount(accountId, accountCode) {
    try {
        if (accountCode) localStorage.setItem("selectedAccountCode", String(accountCode).trim());
        if (accountId != null && accountId !== "") localStorage.setItem("selectedAccountId", String(accountId));
    } catch (e) {}
}

async function resolveAccountByCode(code) {
    const c = String(code || "").trim();
    if (!c) return null;
    const data = await window.apiClient.get("/api/accounts/by-code/" + encodeURIComponent(c));
    return { accountId: data.id, accountCode: data.account_code || c };
}

async function resolveAccountById(idParam) {
    const raw = String(idParam == null ? "" : idParam).trim();
    if (!raw) return null;
    if (looksLikeNumericAccountCode(raw)) {
        return await resolveAccountByCode(raw);
    }
    const n = parseInt(raw, 10);
    if (!Number.isFinite(n) || n <= 0) return null;
    const data = await window.apiClient.get("/api/accounts/" + n);
    return { accountId: n, accountCode: data.account_code || null };
}

async function resolveSessionUserAccount() {
    try {
        var userStr = sessionStorage.getItem("user") || localStorage.getItem("user");
        if (!userStr) return null;
        var user = JSON.parse(userStr);
        if (user && user.is_admin) return null;
        var sessionCode = user && (user.account_code || "").trim();
        var sessionId = user && (user.account_id != null ? parseInt(user.account_id, 10) : NaN);
        if (sessionCode) {
            const resolved = await resolveAccountByCode(sessionCode);
            persistSelectedAccount(resolved.accountId, resolved.accountCode);
            return resolved;
        }
        if (Number.isFinite(sessionId) && sessionId > 0) {
            const resolved = await resolveAccountById(String(sessionId));
            if (resolved) persistSelectedAccount(resolved.accountId, resolved.accountCode);
            return resolved;
        }
    } catch (e) {
        if (typeof window.__DEBUG_DASH__ !== "undefined" && window.__DEBUG_DASH__) {
            console.warn("[dashboard] resolve from session user failed:", e);
        }
    }
    return null;
}

/** Resolve account from URL (account_code or account_id), admin session, localStorage, or session user. */
async function resolveAccountFromUrl() {
    const qs = new URLSearchParams(location.search);
    const code = qs.get("account_code");
    const idParam = qs.get("account_id");
    const fromAdmin = isDashboardAdminContext();
    const storedCode = localStorage.getItem("selectedAccountCode");
    const storedId = localStorage.getItem("selectedAccountId");

    if (code && String(code).trim()) {
        const resolved = await resolveAccountByCode(code);
        persistSelectedAccount(resolved.accountId, resolved.accountCode);
        if (fromAdmin) {
            try {
                sessionStorage.setItem("dashboard_admin_account_id", String(resolved.accountId));
                sessionStorage.setItem("dashboard_admin_account_code", resolved.accountCode || "");
            } catch (e) {}
        }
        return resolved;
    }
    if (idParam) {
        const resolved = await resolveAccountById(idParam);
        if (resolved) {
            persistSelectedAccount(resolved.accountId, resolved.accountCode);
            if (fromAdmin) {
                try {
                    sessionStorage.setItem("dashboard_admin_account_id", String(resolved.accountId));
                    sessionStorage.setItem("dashboard_admin_account_code", resolved.accountCode || "");
                } catch (e) {}
            }
            return resolved;
        }
    }
    if (!fromAdmin) {
        const sessionResolved = await resolveSessionUserAccount();
        if (sessionResolved) {
            if (storedCode && String(storedCode).trim().toUpperCase() !== String(sessionResolved.accountCode || "").trim().toUpperCase()) {
                try {
                    localStorage.removeItem("selectedAccountCode");
                    localStorage.removeItem("selectedAccountId");
                } catch (e) {}
            }
            persistSelectedAccount(sessionResolved.accountId, sessionResolved.accountCode);
            return sessionResolved;
        }
    }
    if (fromAdmin) {
        try {
            var adminCode = sessionStorage.getItem("dashboard_admin_account_code");
            if (adminCode && String(adminCode).trim()) {
                const resolved = await resolveAccountByCode(adminCode);
                persistSelectedAccount(resolved.accountId, resolved.accountCode);
                return resolved;
            }
            var adminId = sessionStorage.getItem("dashboard_admin_account_id");
            if (adminId) {
                const resolved = await resolveAccountById(adminId);
                if (resolved) {
                    persistSelectedAccount(resolved.accountId, resolved.accountCode);
                    return resolved;
                }
            }
        } catch (e) {}
        if (storedCode && String(storedCode).trim()) {
            try {
                const resolved = await resolveAccountByCode(storedCode);
                persistSelectedAccount(resolved.accountId, resolved.accountCode);
                return resolved;
            } catch (e) {
                if (typeof window.__DEBUG_DASH__ !== "undefined" && window.__DEBUG_DASH__) {
                    console.warn("[dashboard] stored account_code resolve failed:", storedCode, e);
                }
            }
        }
        if (storedId) {
            try {
                const resolved = await resolveAccountById(storedId);
                if (resolved) {
                    persistSelectedAccount(resolved.accountId, resolved.accountCode);
                    return resolved;
                }
            } catch (e) {
                if (typeof window.__DEBUG_DASH__ !== "undefined" && window.__DEBUG_DASH__) {
                    console.warn("[dashboard] stored account_id resolve failed:", storedId, e);
                }
            }
        }
        throw new Error("account_id veya account_code gerekli");
    }
    throw new Error("account_id veya account_code gerekli");
}

function getAccountId() {
    return State.accountId;
}

// Load account meta (timeout 15s – can be slow under load)
async function loadAccountMeta(accountId) {
    try {
        const data = await window.apiClient.get(`/api/accounts/${accountId}`, { timeout: 15000 });
        State.accountMeta = data;
        updateAccountName(data.name || "Hesap Dashboard");
    } catch (error) {
        console.error("[dashboard] loadAccountMeta error:", error);
    }
}

// Load summary (legacy) - stable URL, used as fallback or one-shot
async function loadSummary(accountId) {
    if (State.inFlight) return;
    State.inFlight = true;
    try {
        const url = `/api/dashboard/summary?account_id=${accountId}`;
        const data = await window.apiClient.get(url, { timeout: 15000 });
        const hash = computeHash(data);
        State.summary = data;
        State.bots = hydrateBotsWithMetricsCache(Array.isArray(data.bots) ? data.bots : []);
        State.isTestAccount = !!(data.is_test_account);
        renderBotsList(State.bots);
        if (hash === State.lastSummaryHash && State.summary) {
            updateKPIs(data);
            State.inFlight = false;
            return;
        }
        State.lastSummaryHash = hash;
        updateKPIs(data);
        updateAccountName(data.account?.name ?? data.account_name ?? "Hesap Dashboard");
        setAppbarAccountHolderName(data);
        hideError();
    } catch (error) {
        if (isBenignDashboardFetchError(error)) {
            console.warn('[dashboard] loadSummary skipped benign error:', error.message || error);
        } else {
            const errorMsg = error instanceof window.APIError ? `Dashboard yüklenemedi: ${error.message}` : `Dashboard yüklenemedi: ${error.message || 'Bilinmeyen hata'}`;
            showError(errorMsg, error);
        }
    } finally {
        State.inFlight = false;
    }
}

// Snapshot: single aggregated endpoint - prices, wallet, pnl, bots in one request
const SNAPSHOT_POLL_MS = 5000;
var _dashboardEventSource = null;
var _dashboardSseActive = false;

function _applySnapshotResponse(res) {
    const data = (res && res.ok && res.data)
        ? { ...res.data, account: res.data.kpis?.account || res.data.account, pnl: res.data.kpis?.pnl || res.data.pnl }
        : res;
    applySnapshotToUI(data);
}

function stopDashboardSSE() {
    if (_dashboardEventSource) {
        try { _dashboardEventSource.close(); } catch (e) { /* ignore */ }
        _dashboardEventSource = null;
    }
    _dashboardSseActive = false;
}

function startDashboardSSE() {
    if (_dashboardSseActive || !State.accountId || typeof EventSource === 'undefined') return false;
    if (window.__DASHBOARD_SSE_ENABLED === false) return false;
    if (window.apiClient && typeof window.apiClient.hasToken === 'function' && window.apiClient.hasToken()) return false;
    stopDashboardSSE();
    var fields = getSnapshotFields();
    var url = '/api/dashboard/stream?account_id=' + encodeURIComponent(State.accountId)
        + (fields ? '&fields=' + encodeURIComponent(fields) : '');
    try {
        var es = new EventSource(url);
        es.onmessage = function (ev) {
            if (!ev.data) return;
            try {
                var res = JSON.parse(ev.data);
                if (State.inFlight) return;
                State.inFlight = true;
                try { _applySnapshotResponse(res); } finally { State.inFlight = false; }
            } catch (parseErr) {
                console.warn('[dashboard] SSE parse error:', parseErr);
            }
        };
        es.onerror = function () {
            stopDashboardSSE();
            if (window.intervalRegistry && typeof window.intervalRegistry.start === 'function') {
                window.intervalRegistry.start('dashboard_snapshot', dashboardDataRefresh, SNAPSHOT_POLL_MS, 'dashboard');
            }
        };
        _dashboardEventSource = es;
        _dashboardSseActive = true;
        return true;
    } catch (e) {
        return false;
    }
}

function startDashboardSnapshotTransport() {
    stopDashboardSSE();
    window.intervalRegistry.stop('dashboard_snapshot');
    if (startDashboardSSE()) return;
    window.intervalRegistry.start('dashboard_snapshot', dashboardDataRefresh, SNAPSHOT_POLL_MS, 'dashboard');
}

// BOOT_V2: no tab/wallet-idle gating. Always request wallet so cache-only snapshot serves it (mobile + desktop).
function getSnapshotFields() {
    if (typeof isSpotModalOpen === 'function' && isSpotModalOpen()) return 'wallet,prices';
    return 'wallet,prices,bots,kpis';
}

async function fetchSnapshot() {
    if (!State.accountId || State.inFlight || (typeof isSpotModalOpen === 'function' && isSpotModalOpen())) return;
    State.inFlight = true;
    try {
        var fields = getSnapshotFields();
        var url = '/api/dashboard/snapshot?account_id=' + State.accountId + (fields ? '&fields=' + encodeURIComponent(fields) : '');
        const res = await window.apiClient.get(url, { timeout: 12000 });
        _applySnapshotResponse(res);
    } catch (error) {
        if (window.errorReporter) window.errorReporter.report(error, { tab: 'dashboard', account_id: State.accountId, action: 'fetchSnapshot' });
        console.warn('[dashboard] Snapshot fetch error:', error?.message || error);
    } finally {
        State.inFlight = false;
    }
}

var _dashboardStaleWalletRefreshLastAt = 0;
var DASHBOARD_STALE_WALLET_REFRESH_GAP_MS = 15000;

function maybeRefreshStaleWalletFromDashboard() {
    if (!State.accountId || (typeof State !== 'undefined' && State.isTestAccount)) return;
    if (typeof triggerWalletRefreshForVarliklar !== 'function') return;
    if (typeof isWalletPanelUpdating === 'function' && isWalletPanelUpdating()) return;
    var stale = false;
    if (window.__walletDebugMeta && window.__walletDebugMeta.wallet_age_sec != null) {
        stale = Number(window.__walletDebugMeta.wallet_age_sec) >= 900;
    }
    if (!stale && assetsState && assetsState.wallet) {
        stale = assetsState.wallet.data_status === 'stale' || (typeof isWalletDataLive === 'function' && !isWalletDataLive());
    }
    if (!stale) return;
    var now = Date.now();
    if (now - _dashboardStaleWalletRefreshLastAt < DASHBOARD_STALE_WALLET_REFRESH_GAP_MS) return;
    _dashboardStaleWalletRefreshLastAt = now;
    triggerWalletRefreshForVarliklar(State.accountId, { force: true });
    if (typeof pollWalletRefreshUntilDone === 'function') {
        pollWalletRefreshUntilDone(State.accountId);
    }
}

function dashboardDataRefresh() {
    if (!State.accountId || State.inFlight || (typeof isSpotModalOpen === 'function' && isSpotModalOpen())) return;
    var activeTab = document.querySelector('.dm-tab.is-active');
    var tabName = (activeTab && activeTab.getAttribute('data-tab')) || 'binance';
    if (window.FLASH_HOME_ENABLED && (tabName === 'binance' || tabName === 'varliklar' || tabName === '')) {
        var walletIdle = assetsState && assetsState.wallet && (assetsState.wallet.status === 'idle' || assetsState.wallet.status === 'loading');
        if (walletIdle) {
            _binanceWalletIdleCycles++;
            if (_binanceWalletIdleCycles >= 2) {
                _binanceWalletIdleCycles = 0;
                fetchSnapshot();
                return;
            }
        } else {
            _binanceWalletIdleCycles = 0;
        }
        if (window.homeFlash && typeof window.homeFlash.loadFast === 'function') {
            window.homeFlash.loadFast(State.accountId);
        }
        if (typeof loadBotsListFast === 'function') loadBotsListFast(State.accountId);
        maybeRefreshStaleWalletFromDashboard();
    }
    _binanceWalletIdleCycles = 0;
    _dashboardWalletForceTick = 0;
    fetchSnapshot();
}

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

function normalizeLeaderboardParamsToFormConfig(params) {
    if (!params || typeof params !== 'object') return {};
    var p = Object.assign({}, params);
    if ((p.sell_grids || p.buy_grids) && !p.up) {
        p.up = {
            trail_pct: p.sell_trigger_trailing_pct,
            grids: (p.sell_grids || []).map(function (g) {
                return {
                    trigger_pct: g.sell_grid_pct != null ? g.sell_grid_pct : g.trigger_pct,
                    qty_pct: g.sell_qty_pct_of_base != null ? g.sell_qty_pct_of_base : g.qty_pct
                };
            })
        };
    }
    if (p.buy_grids && !p.down) {
        p.down = {
            trail_pct: p.buy_trigger_trailing_pct,
            grids: (p.buy_grids || []).map(function (g) {
                return {
                    trigger_pct: g.buy_grid_pct != null ? g.buy_grid_pct : g.trigger_pct,
                    qty_pct: g.buy_qty_pct_of_quote != null ? g.buy_qty_pct_of_quote : g.qty_pct
                };
            })
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
    if ((p.profit_reentry_drop_pct != null || p.profit_exit_rise_pct != null) && !p.profit) {
        p.profit = {
            rebuy_trigger_pct: p.profit_reentry_drop_pct,
            rebuy_trail_pct: p.profit_reentry_rise_pct,
            resell_trigger_pct: p.profit_exit_rise_pct,
            resell_trail_pct: p.profit_exit_drop_pct
        };
    }
    if (p.base_alloc_pct != null && !p.allocation) {
        p.allocation = { base_pct: p.base_alloc_pct, quote_pct: p.quote_alloc_pct };
    }
    return p;
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
    html += row('Base dağılım (%)', basePct != null ? basePct + '%' : '—');
    html += row('Quote dağılım (%)', quotePct != null ? quotePct + '%' : '—');
    html += '</div>';
    html += '<div class="param-block"><div class="param-block-title">Satış gridleri</div>';
    html += row('Grid sayısı', sellGrids.length || cfg.sell_grids_count || 0, 'param-sell');
    html += row('Trailing % (tetik sonrası gerçekleşme)', sellTrail != null ? sellTrail + '%' : '—', 'param-sell');
    if (sellGrids.length) {
        html += '<table class="param-table"><thead><tr><th>Seviye</th><th class="num">Tetik %</th><th class="num">Miktar (base %)</th></tr></thead><tbody>';
        sellGrids.forEach(function (g, i) {
            var pct = g.sell_grid_pct != null ? g.sell_grid_pct : g.trigger_pct;
            var qty = g.sell_qty_pct_of_base != null ? g.sell_qty_pct_of_base : g.qty_pct;
            html += '<tr><td>#' + (i + 1) + '</td><td class="num">+' + (pct != null ? pct : '—') + '%</td><td class="num">' + (qty != null ? qty : '—') + '%</td></tr>';
        });
        html += '</tbody></table>';
    } else {
        html += '<p class="param-hint">Tanımlı değil.</p>';
    }
    html += '</div>';
    html += '<div class="param-block"><div class="param-block-title">Alım gridleri</div>';
    html += row('Grid sayısı', buyGrids.length || cfg.buy_grids_count || 0, 'param-buy');
    html += row('Trailing % (tetik sonrası gerçekleşme)', buyTrail != null ? buyTrail + '%' : '—', 'param-buy');
    if (buyGrids.length) {
        html += '<table class="param-table"><thead><tr><th>Seviye</th><th class="num">Tetik %</th><th class="num">Miktar (quote %)</th></tr></thead><tbody>';
        buyGrids.forEach(function (g, i) {
            var pct = g.buy_grid_pct != null ? g.buy_grid_pct : g.trigger_pct;
            var qty = g.buy_qty_pct_of_quote != null ? g.buy_qty_pct_of_quote : g.qty_pct;
            html += '<tr><td>#' + (i + 1) + '</td><td class="num">-' + (pct != null ? pct : '—') + '%</td><td class="num">' + (qty != null ? qty : '—') + '%</td></tr>';
        });
        html += '</tbody></table>';
    } else {
        html += '<p class="param-hint">Tanımlı değil.</p>';
    }
    html += '</div>';
    html += '<div class="param-block"><div class="param-block-title">Kar alım / kar satış</div>';
    html += row('Kar alım tetik %', reTr != null ? reTr + '%' : '—');
    html += row('Kar alım trailing %', reTrl != null ? reTrl + '%' : '—');
    html += row('Kar satış tetik %', exTr != null ? exTr + '%' : '—');
    html += row('Kar satış trailing %', exTrl != null ? exTrl + '%' : '—');
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
    if (basePctEl && (alloc.base_pct != null || alloc.base_pct === 0)) basePctEl.value = alloc.base_pct;
    if (quotePctEl && (alloc.quote_pct != null || alloc.quote_pct === 0)) quotePctEl.value = alloc.quote_pct;
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
    if (upTrailEl && (up.trail_pct != null || up.trail_pct === 0)) upTrailEl.value = up.trail_pct;
    if (downTrailEl && (down.trail_pct != null || down.trail_pct === 0)) downTrailEl.value = down.trail_pct;
    for (var i = 0; i < upGrids.length; i++) {
        var tEl = document.getElementById('upGrid_' + i + '_trigger');
        var qEl = document.getElementById('upGrid_' + i + '_qty');
        if (tEl && upGrids[i].trigger_pct != null) tEl.value = upGrids[i].trigger_pct;
        if (qEl && upGrids[i].qty_pct != null) qEl.value = upGrids[i].qty_pct;
    }
    for (var j = 0; j < downGrids.length; j++) {
        var t2 = document.getElementById('downGrid_' + j + '_trigger');
        var q2 = document.getElementById('downGrid_' + j + '_qty');
        if (t2 && downGrids[j].trigger_pct != null) t2.value = downGrids[j].trigger_pct;
        if (q2 && downGrids[j].qty_pct != null) q2.value = downGrids[j].qty_pct;
    }
    var rebuyT = document.getElementById('fRebuyTrigger');
    var rebuyTrail = document.getElementById('fRebuyTrail');
    var resellT = document.getElementById('fResellTrigger');
    var resellTrail = document.getElementById('fResellTrail');
    if (rebuyT && (profit.rebuy_trigger_pct != null || profit.rebuy_trigger_pct === 0)) rebuyT.value = profit.rebuy_trigger_pct;
    if (rebuyTrail && profit.rebuy_trail_pct != null) rebuyTrail.value = profit.rebuy_trail_pct;
    if (resellT && (profit.resell_trigger_pct != null || profit.resell_trigger_pct === 0)) resellT.value = profit.resell_trigger_pct;
    if (resellTrail && profit.resell_trail_pct != null) resellTrail.value = profit.resell_trail_pct;
    if (p.symbol && typeof updateCreateBotModalPairStrip === 'function') updateCreateBotModalPairStrip(p.symbol);
}

/** En İyi 5 Bot: tek kaynak state – flicker yok. Sadece içerik gerçekten değişince DOM güncellenir. */

State.txHistoryPeriod = State.txHistoryPeriod || 'daily';
State.txHistoryType = State.txHistoryType || 'buysell';
State.txHistoryPage = State.txHistoryPage || 1;
var _txHistoryRevision = '';
var _txHistoryLastSig = '';
var _txHistoryPollInFlight = false;
var _txHistoryLoaded = false;
const TX_HISTORY_POLL_MS = 3500;
var _txHistoryRateLimitUntil = 0;

var _txHistoryInitialSyncDone = false;
var _txHistoryLoadSeq = 0;
var _txHistoryInflight = null;
var _txHistoryInflightKey = '';
var _spotTxHistoryPending = {};

function _txHistoryListHasContent() {
    var listEl = document.getElementById('txHistoryList');
    if (!listEl) return false;
    return !!listEl.querySelector('.tx-history-item');
}

function resetTxHistoryClientState() {
    _txHistoryRevision = '';
    _txHistoryLastSig = '';
    _txHistoryLoaded = false;
    _txHistoryInitialSyncDone = false;
    _txHistoryLoadSeq += 1;
    _txHistoryInflight = null;
    _txHistoryInflightKey = '';
    _spotTxHistoryPending = {};
}
window.resetTxHistoryClientState = resetTxHistoryClientState;

function _txHistoryPayload(res) {
    if (!res) return null;
    if (Array.isArray(res.items)) return res;
    if (res.data && Array.isArray(res.data.items)) return res.data;
    if (res.data && typeof res.data === 'object') return res.data;
    return res;
}

function _txEncodeAttr(tx) {
    try {
        return encodeURIComponent(JSON.stringify(tx));
    } catch (e) {
        return '';
    }
}
function _txIsPaperSpotTx(tx) {
    if (!tx) return false;
    if (tx.paper === true) return true;
    var oid = String(tx.order_id || tx.trade_id || '');
    return oid.indexOf('test_paper_') === 0;
}
function _txPlatformLabel(tx) {
    if (!tx) return 'Binance';
    if (tx.bot_id || tx.source === 'bot') return 'TraderTrailing';
    if (_txIsPaperSpotTx(tx)) return 'TraderTrailing';
    var p = tx.platform && String(tx.platform);
    if (p) return p === 'TradeTrailing' ? 'TraderTrailing' : p;
    return 'Binance';
}

function isTransactionHistoryPanelVisible() {
    var panel = document.getElementById('transactionHistoryPanel');
    if (!panel || panel.style.display === 'none') return false;
    var tab = document.querySelector('.dm-tab.is-active');
    var tabName = tab && tab.getAttribute('data-tab');
    return tabName === 'binance' || tabName === 'varliklar' || !tabName;
}

function _txHistoryItemsSig(d) {
    if (!d || !Array.isArray(d.items)) return '';
    return String(d.revision || '') + '|' + (d.total || 0) + '|' + d.items.map(function (tx) {
        return (tx.id || '') + ':' + (tx.time || '') + ':' + (tx.qty || '');
    }).join(';');
}

function clearTxHistoryUiCache(accountId) {
    if (!accountId) return;
    try {
        var prefix = TX_HISTORY_CACHE_PREFIX + accountId;
        [sessionStorage, localStorage].forEach(function (store) {
            for (var i = store.length - 1; i >= 0; i--) {
                var k = store.key(i);
                if (k && k.indexOf(prefix) === 0) store.removeItem(k);
            }
        });
    } catch (e) { /* ignore */ }
}

function _fmtTxQtyShort(n) {
    if (n == null || !Number.isFinite(n)) return '—';
    var s = Number(n).toFixed(8).replace(/\.?0+$/, '');
    return s || '0';
}

function _renderTxHistoryItemHtml(tx) {
    var timeStr = tx.time ? new Date(tx.time).toLocaleString('tr-TR', { dateStyle: 'short', timeStyle: 'short' }) : '—';
    var typeLabel = tx.type_label || (tx.type === 'buy' ? 'Alım' : tx.type === 'sell' ? 'Satım' : tx.type === 'deposit' ? 'Yatırım' : tx.type === 'withdraw' ? 'Çekim' : '—');
    var typeClass = tx.type === 'buy' ? 'tx-type-buy' : tx.type === 'sell' ? 'tx-type-sell' : tx.type === 'deposit' ? 'tx-type-deposit' : tx.type === 'withdraw' ? 'tx-type-withdraw' : '';
    var amtRow = _txDisplayAmounts(tx);
    var qtyStr = _fmtTxQtyShort(amtRow.qty);
    var priceStr = amtRow.price > 0 ? (typeof fmtCoinPrice === 'function' ? fmtCoinPrice(amtRow.price) : '$' + Number(amtRow.price).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 8 })) : '—';
    var totalVal = (tx.type === 'deposit' || tx.type === 'withdraw')
        ? (qtyStr + ' ' + (tx.symbol || ''))
        : (amtRow.notional > 0 ? (typeof fmtUsd === 'function' ? fmtUsd(amtRow.notional) : '$' + amtRow.notional) : '—');
    var sourceLabel = tx.source_label || (tx.source === 'bot' ? 'Bot' : tx.source === 'spot' ? 'Spot' : '—');
    var platformLabel = _txPlatformLabel(tx);
    var metaRight = (tx.type === 'buy' || tx.type === 'sell') ? ('Miktar ' + qtyStr + ' · Fiyat ' + priceStr) : (qtyStr + (tx.symbol ? ' ' + tx.symbol : ''));
    return '<div class="tx-history-item" data-tx="' + _txEncodeAttr(tx) + '" role="button" tabindex="0">' +
        '<div class="tx-history-item-left">' +
        '<div class="tx-history-item-title"><span class="' + typeClass + '">' + typeLabel + '</span> ' + (tx.symbol || '') + '</div>' +
        '<div class="tx-history-item-meta">' + timeStr + ' · ' + sourceLabel + ' · ' + platformLabel + (tx.bot_name ? ' · ' + tx.bot_name : '') + '</div>' +
        '</div>' +
        '<div class="tx-history-item-right">' +
        '<div class="tx-history-item-total">' + totalVal + '</div>' +
        '<div class="tx-history-item-meta">' + metaRight + '</div>' +
        '</div></div>';
}

function _bindTxHistoryItemClicks(rootEl) {
    var listEl = rootEl || document.getElementById('txHistoryList');
    if (!listEl) return;
    listEl.querySelectorAll('.tx-history-item').forEach(function (el) {
        el.onclick = function () {
            try {
                var raw = el.getAttribute('data-tx');
                var tx = raw ? JSON.parse(decodeURIComponent(raw)) : null;
                if (tx && typeof openTxDetailModal === 'function') openTxDetailModal(tx);
            } catch (e) {}
        };
    });
}

function spotOrderResultToTxItem(result, symbol, side) {
    var r = result || {};
    var executedQty = parseFloat(r.executedQty != null ? r.executedQty : r.executed_qty);
    var cumQuote = parseFloat(r.cummulativeQuoteQty != null ? r.cummulativeQuoteQty : (r.cumulativeQuoteQty != null ? r.cumulativeQuoteQty : r.executed_value_usdt));
    var price = parseFloat(r.price || 0);
    if (!Number.isFinite(executedQty)) executedQty = 0;
    if (!Number.isFinite(cumQuote)) cumQuote = 0;
    if (!Number.isFinite(price)) price = 0;
    if (executedQty > 0 && cumQuote > 0) price = cumQuote / executedQty;
    var sideU = (side || r.side || '').toUpperCase();
    var isBuy = sideU === 'BUY';
    var sym = (symbol || r.symbol || '').toUpperCase();
    var orderId = String(r.orderId || r.order_id || ('spot_' + Date.now()));
    return {
        id: 'o_' + orderId,
        trade_id: orderId,
        order_id: orderId,
        time: new Date().toISOString(),
        type: isBuy ? 'buy' : 'sell',
        type_label: isBuy ? 'Alım' : 'Satım',
        symbol: sym,
        side: sideU,
        qty: executedQty,
        price: price,
        quote_qty: cumQuote,
        commission: 0,
        commission_asset: 'USDT',
        source: 'spot',
        source_label: 'Spot',
        platform: r.paper ? 'TraderTrailing' : 'Binance',
        fills_count: 1
    };
}

function spotTradeMatchesTxHistoryFilters(side) {
    var typeFilter = (State.txHistoryType || 'buysell').toLowerCase();
    var sideU = (side || '').toUpperCase();
    if (typeFilter === 'buy' && sideU !== 'BUY') return false;
    if (typeFilter === 'sell' && sideU !== 'SELL') return false;
    if (typeFilter === 'deposit' || typeFilter === 'withdraw' || typeFilter === 'depositwithdraw') return false;
    return true;
}

function spotTxPendingMatchesPeriod(tx, period) {
    if (!tx || !tx.time) return true;
    var p = (period || 'daily').toLowerCase();
    if (p === 'all') return true;
    var d = new Date(tx.time);
    if (isNaN(d.getTime())) return true;
    var fmt = function (dt) { return dt.toLocaleDateString('en-CA', { timeZone: 'Europe/Istanbul' }); };
    var txDay = fmt(d);
    var today = fmt(new Date());
    if (p === 'daily') return txDay === today;
    var diffDays = Math.floor((new Date(today).getTime() - new Date(txDay).getTime()) / 86400000);
    if (p === 'weekly') return diffDays >= 0 && diffDays <= 6;
    if (p === 'monthly') return diffDays >= 0 && diffDays <= 29;
    return true;
}

function registerPendingSpotTxHistory(result, symbol, side) {
    if (!spotTradeMatchesTxHistoryFilters(side)) return null;
    var tx = spotOrderResultToTxItem(result, symbol, side);
    if (!(tx.qty > 0) && !(tx.quote_qty > 0)) return null;
    var oid = String(tx.order_id || tx.trade_id || '');
    if (oid) _spotTxHistoryPending[oid] = tx;
    return tx;
}

function clearPendingSpotTxFromServerItems(items) {
    (items || []).forEach(function (tx) {
        var oid = String(tx.order_id || tx.trade_id || '');
        if (oid && _spotTxHistoryPending[oid]) delete _spotTxHistoryPending[oid];
    });
}

function mergePendingSpotTxHistoryItems(serverItems, period) {
    var items = Array.isArray(serverItems) ? serverItems.slice() : [];
    var serverIds = {};
    items.forEach(function (tx) {
        var oid = String(tx.order_id || tx.trade_id || '');
        if (oid) serverIds[oid] = true;
    });
    var pending = [];
    Object.keys(_spotTxHistoryPending).forEach(function (k) {
        var tx = _spotTxHistoryPending[k];
        if (!tx) return;
        var oid = String(tx.order_id || tx.trade_id || '');
        if (serverIds[oid]) return;
        if (!spotTradeMatchesTxHistoryFilters(tx.side)) return;
        if (!spotTxPendingMatchesPeriod(tx, period)) return;
        pending.push(tx);
    });
    pending.sort(function (a, b) {
        return String(b.time || '').localeCompare(String(a.time || ''));
    });
    return pending.concat(items);
}

function _paintTxHistoryList(items, page, total, perPage, totalPages, period, typeFilter) {
    var listEl = document.getElementById('txHistoryList');
    var paginationEl = document.getElementById('txHistoryPagination');
    if (!listEl) return;
    if (!items || items.length === 0) {
        listEl.innerHTML = '<div class="tx-history-empty" style="text-align:center;padding:2rem;color:var(--ds-text-secondary);">Bu filtrede işlem bulunamadı.</div>';
    } else {
        var html = items.map(function (tx) { return _renderTxHistoryItemHtml(tx); }).join('');
        listEl.innerHTML = '<div class="tx-history-items">' + html + '</div>';
        _bindTxHistoryItemClicks(listEl);
    }
    if (paginationEl) {
        if (totalPages > 1) {
            var pg = '';
            if (page > 1) pg += '<button type="button" class="btn btn-sm tx-pg-btn" data-page="' + (page - 1) + '">← Önceki</button>';
            pg += '<span style="margin:0 0.5rem;font-size:0.9rem;color:var(--ds-text-secondary);">Sayfa ' + page + ' / ' + totalPages + '</span>';
            if (page < totalPages) pg += '<button type="button" class="btn btn-sm tx-pg-btn" data-page="' + (page + 1) + '">Sonraki →</button>';
            paginationEl.innerHTML = pg;
            paginationEl.querySelectorAll('.tx-pg-btn').forEach(function (btn) {
                btn.onclick = function () {
                    var p = parseInt(btn.getAttribute('data-page'), 10);
                    if (typeof loadTransactionHistory === 'function') loadTransactionHistory(State.txHistoryPeriod, State.txHistoryType, p, false, { force: true });
                };
            });
        } else {
            paginationEl.innerHTML = '';
        }
    }
    document.querySelectorAll('.tx-period-btn').forEach(function (b) { b.classList.toggle('active', b.getAttribute('data-period') === period); });
    document.querySelectorAll('.tx-type-btn').forEach(function (b) { b.classList.toggle('active', b.getAttribute('data-type') === typeFilter); });
}

function scheduleTxHistoryRefreshAfterTrade(result, symbol, side) {
    if (!State.accountId || typeof loadTransactionHistory !== 'function') return;
    registerPendingSpotTxHistory(result, symbol, side);
    if (typeof prependSpotTradeToTxHistoryPanel === 'function') {
        prependSpotTradeToTxHistoryPanel(result, symbol, side);
    }
    var period = State.txHistoryPeriod || 'daily';
    var typeFilter = State.txHistoryType || 'buysell';
    [0, 400, 1000, 2500].forEach(function (delayMs) {
        setTimeout(function () {
            if (!State.accountId) return;
            loadTransactionHistory(period, typeFilter, 1, false, { force: true, afterTrade: true });
        }, delayMs);
    });
}

function prependSpotTradeToTxHistoryPanel(result, symbol, side) {
    var tx = registerPendingSpotTxHistory(result, symbol, side);
    if (!tx) return null;
    var listEl = document.getElementById('txHistoryList');
    if (!listEl) return tx;
    var container = listEl.querySelector('.tx-history-items');
    var html = _renderTxHistoryItemHtml(tx);
    var dup = false;
    if (container) {
        container.querySelectorAll('.tx-history-item').forEach(function (el) {
            try {
                var raw = el.getAttribute('data-tx');
                var existing = raw ? JSON.parse(decodeURIComponent(raw)) : null;
                if (existing && (String(existing.order_id) === String(tx.order_id) || String(existing.trade_id) === String(tx.trade_id))) dup = true;
            } catch (e) {}
        });
    }
    if (!dup) {
        if (!container) {
            listEl.innerHTML = '<div class="tx-history-items">' + html + '</div>';
        } else {
            container.insertAdjacentHTML('afterbegin', html);
        }
        _bindTxHistoryItemClicks(listEl);
    }
    return tx;
}

function formatSpotTradeFillToast(result, side, orderType, symbol) {
    var tx = spotOrderResultToTxItem(result, symbol, side);
    var typeLabel = (orderType || 'MARKET').toUpperCase() === 'LIMIT' ? 'Limit' : 'Market';
    var sideLabel = tx.type_label || ((side || '').toUpperCase() === 'BUY' ? 'Alış' : 'Satış');
    var sym = (symbol || tx.symbol || '').toUpperCase();
    var base = sym.endsWith('USDT') ? sym.slice(0, -4) : sym;
    var qtyStr = _fmtTxQtyShort(tx.qty);
    var quoteStr = tx.quote_qty > 0
        ? (typeof fmtUsd === 'function' ? fmtUsd(tx.quote_qty) : ('$' + Number(tx.quote_qty).toFixed(2)))
        : '—';
    if (!(tx.qty > 0) && !(tx.quote_qty > 0)) {
        return typeLabel + ' ' + sideLabel + ' emri gönderildi';
    }
    return typeLabel + ' ' + sideLabel + ' gerçekleşti: ' + qtyStr + ' ' + base + ' · ' + quoteStr;
}

async function pollTransactionHistoryRevision() {
    if (!State.accountId || !window.apiClient || _txHistoryPollInFlight) return;
    if (!isTransactionHistoryPanelVisible()) return;
    if (Date.now() < _txHistoryRateLimitUntil) return;
    _txHistoryPollInFlight = true;
    try {
        var res = await window.apiClient.get(
            '/api/accounts/' + State.accountId + '/transaction-history/revision',
            { timeout: 6000, suppressRateLimitToast: true }
        );
        var body = res && (res.data || res);
        var rev = body && body.revision != null ? String(body.revision) : '';
        if (!rev) return;
        if (!_txHistoryLoaded || rev !== _txHistoryRevision) {
            _txHistoryRevision = rev;
            await loadTransactionHistory(
                State.txHistoryPeriod || 'daily',
                State.txHistoryType || 'buysell',
                State.txHistoryPage || 1,
                false,
                { silent: _txHistoryLoaded }
            );
        }
    } catch (e) {
        if (e && e.status === 429) {
            var ra = (e.retry_after != null) ? Number(e.retry_after) : 60;
            _txHistoryRateLimitUntil = Date.now() + Math.min(120000, Math.max(15000, ra * 1000));
        }
    } finally {
        _txHistoryPollInFlight = false;
    }
}

async function loadTransactionHistory(period, typeFilter, page, sync, opts) {
    opts = opts || {};
    var force = !!opts.force;
    var afterTrade = !!opts.afterTrade;
    var silent = !!opts.silent && !force;
    if (!State.accountId || !window.apiClient) return;
    var listEl = document.getElementById('txHistoryList');
    var paginationEl = document.getElementById('txHistoryPagination');
    if (!listEl) return;
    var hadCache = false;
    if (force) {
        if (!afterTrade) _txHistoryRevision = '';
        _txHistoryLastSig = '';
        silent = false;
        clearTxHistoryUiCache(State.accountId);
    } else {
        hadCache = hydrateTransactionHistoryFromCache(State.accountId, period, typeFilter, page);
        if (hadCache) silent = true;
    }
    var hasContent = _txHistoryListHasContent();
    if (hasContent && !force) silent = true;
    if (!silent) _txHistoryLastSig = '';
    var doSync = !!sync || (!_txHistoryInitialSyncDone && (typeFilter || 'buysell') === 'buysell' && !hadCache && !force);
    if (doSync) _txHistoryInitialSyncDone = true;
    if (!force && Date.now() < _txHistoryRateLimitUntil) return;
    var reqKey = String(State.accountId) + '|' + period + '|' + typeFilter + '|' + page + '|' + (doSync ? '1' : '0');
    if (afterTrade) {
        _txHistoryInflight = null;
        _txHistoryInflightKey = '';
        reqKey += '|at' + Date.now();
    } else if (_txHistoryInflight && _txHistoryInflightKey === reqKey) {
        return _txHistoryInflight;
    }
    var mySeq = ++_txHistoryLoadSeq;
    var txHistoryRequestDone = false;
    var loadingTimer = null;
    if (!silent && !hadCache && !hasContent) {
        loadingTimer = setTimeout(function () {
            if (txHistoryRequestDone || mySeq !== _txHistoryLoadSeq) return;
            listEl.innerHTML = '<div class="tx-history-loading" style="text-align:center;padding:2rem;color:var(--ds-text-secondary);">Yükleniyor...</div>';
        }, 200);
        if (paginationEl) paginationEl.innerHTML = '';
    }
    State.txHistoryPeriod = period;
    State.txHistoryType = typeFilter;
    State.txHistoryPage = page;
    var q = '/api/accounts/' + State.accountId + '/transaction-history?period=' + encodeURIComponent(period) + '&type_filter=' + encodeURIComponent(typeFilter) + '&page=' + page + (doSync ? '&sync=1' : '');
    if (!doSync && !force && _txHistoryRevision) {
        q += '&revision=' + encodeURIComponent(_txHistoryRevision);
    }
    if (afterTrade) q += '&_nc=' + Date.now();
    _txHistoryInflightKey = reqKey;
    _txHistoryInflight = (async function () {
    try {
        var res = await window.apiClient.get(q, { suppressRateLimitToast: !!silent });
        if (mySeq !== _txHistoryLoadSeq) return;
        txHistoryRequestDone = true;
        if (loadingTimer) clearTimeout(loadingTimer);
        var d = _txHistoryPayload(res);
        if (d && d.revision != null) _txHistoryRevision = String(d.revision);
        var rawItems = (d && Array.isArray(d.items)) ? d.items : null;
        if (rawItems) clearPendingSpotTxFromServerItems(rawItems);
        var items = rawItems ? mergePendingSpotTxHistoryItems(rawItems, period) : mergePendingSpotTxHistoryItems([], period);
        var sigPayload = d ? Object.assign({}, d, { items: items }) : { items: items };
        var sig = _txHistoryItemsSig(sigPayload);
        if (silent && !force && sig && sig === _txHistoryLastSig) return;
        _txHistoryLastSig = sig;
        _txHistoryLoaded = true;
        if (!rawItems && items.length === 0) {
            if (!hasContent && !_txHistoryListHasContent()) {
                listEl.innerHTML = '<div class="tx-history-empty" style="text-align:center;padding:2rem;color:var(--ds-text-secondary);">İşlem bulunamadı.</div>';
            }
            return;
        }
        var total = Number(d && d.total) || 0;
        var perPage = Number(d && d.per_page) || 20;
        var totalPages = Number(d && d.total_pages) || 0;
        if (page === 1 && items.length > total) total = items.length;
        if (!totalPages && total > 0) totalPages = Math.ceil(total / perPage);
        if (total > 0 && total <= perPage) totalPages = 1;
        if (totalPages < 1 && total > 0) totalPages = 1;
        _paintTxHistoryList(items, page, total, perPage, totalPages, period, typeFilter);
        _persistTxHistoryCache(
            State.accountId,
            period,
            typeFilter,
            page,
            listEl.innerHTML,
            paginationEl ? paginationEl.innerHTML : '',
            sig,
            _txHistoryRevision
        );
        try {
            sessionStorage.setItem('dashboard_tx_period_' + State.accountId, period);
            sessionStorage.setItem('dashboard_tx_type_' + State.accountId, typeFilter);
            sessionStorage.setItem('dashboard_tx_page_' + State.accountId, String(page));
        } catch (eSave) {}
    } catch (e) {
        if (mySeq !== _txHistoryLoadSeq) return;
        txHistoryRequestDone = true;
        if (loadingTimer) clearTimeout(loadingTimer);
        if (e && e.status === 429) {
            var raTx = (e.retry_after != null) ? Number(e.retry_after) : 60;
            _txHistoryRateLimitUntil = Date.now() + Math.min(120000, Math.max(15000, raTx * 1000));
        }
        if (!silent && !_txHistoryListHasContent()) {
            if (window.errorReporter) window.errorReporter.report(e, { account_id: State.accountId, action: 'loadTransactionHistory' });
            listEl.innerHTML = '<div class="tx-history-error" style="text-align:center;padding:2rem;color:var(--ds-loss,#f6465d);">Yüklenemedi.</div>';
        }
    } finally {
        if (_txHistoryInflightKey === reqKey) {
            _txHistoryInflight = null;
            _txHistoryInflightKey = '';
        }
    }
    })();
    return _txHistoryInflight;
}
window.loadTransactionHistory = loadTransactionHistory;
window.pollTransactionHistoryRevision = pollTransactionHistoryRevision;

function _txDisplayAmounts(tx) {
    if (!tx) return { qty: 0, price: 0, notional: 0 };
    var qty = Number(tx.qty) || 0;
    var quote = Number(tx.quote_qty) || 0;
    var price = Number(tx.price) || 0;
    if (tx.type === 'buy' || tx.type === 'sell') {
        if (quote > 0 && qty > 0) {
            return { qty: qty, price: quote / qty, notional: quote };
        }
        if (qty > 0 && price > 0) {
            return { qty: qty, price: price, notional: qty * price };
        }
    }
    return { qty: qty, price: price, notional: quote };
}

function _txCommissionLabel(tx) {
    if (!tx || tx.commission == null || Number(tx.commission) <= 0) return '0';
    var raw = Number(tx.commission);
    if (!Number.isFinite(raw)) return '0';
    var asset = String(tx.commission_asset || 'USDT').toUpperCase();
    var usdt = (tx.commission_usdt != null && Number.isFinite(Number(tx.commission_usdt)))
        ? Number(tx.commission_usdt)
        : ((asset === 'USDT' || asset === 'BUSD' || asset === 'FDUSD' || asset === 'USDC') ? raw : null);
    var rawStr = typeof fmtNum === 'function' ? fmtNum(raw, 8) : String(raw);
    if (usdt != null && asset !== 'USDT') {
        var usdtStr = typeof fmtUsd === 'function' ? fmtUsd(usdt) : ('$' + usdt.toFixed(2));
        return rawStr + ' ' + asset + ' (≈ ' + usdtStr + ')';
    }
    return rawStr + ' ' + asset;
}

function openTxDetailModal(tx) {
    var modal = document.getElementById('txDetailModal');
    if (!modal) return;
    var timeStr = tx.time ? new Date(tx.time).toLocaleString('tr-TR', { dateStyle: 'medium', timeStyle: 'medium' }) : '—';
    var typeLabel = tx.type_label || (tx.type === 'buy' ? 'Alım' : tx.type === 'sell' ? 'Satım' : tx.type === 'deposit' ? 'Yatırım' : tx.type === 'withdraw' ? 'Çekim' : '—');
    var amt = _txDisplayAmounts(tx);
    var qty = amt.qty > 0 ? (typeof fmtNum === 'function' ? fmtNum(amt.qty, 8) : Number(amt.qty).toFixed(4)) : '—';
    var price = amt.price > 0 ? (typeof fmtCoinPrice === 'function' ? fmtCoinPrice(amt.price) : '$' + amt.price) : '—';
    var totalVal = (tx.type === 'deposit' || tx.type === 'withdraw')
        ? (qty + ' ' + (tx.symbol || ''))
        : (amt.notional > 0 ? (typeof fmtUsd === 'function' ? fmtUsd(amt.notional) : '$' + amt.notional) : '—');
    var comm = _txCommissionLabel(tx);
    patchText('txDetailTime', timeStr);
    patchText('txDetailType', typeLabel);
    patchText('txDetailSymbol', tx.symbol || '—');
    patchText('txDetailQty', qty);
    patchText('txDetailPrice', price !== '—' ? price : '—');
    patchText('txDetailTotal', totalVal);
    patchText('txDetailCommission', comm);
    patchText('txDetailSource', tx.source_label || (tx.source === 'bot' ? 'Bot' : tx.source === 'spot' ? 'Spot' : '—'));
    patchText('txDetailPlatform', _txPlatformLabel(tx));
    modal.style.display = 'flex';
    modal.setAttribute('aria-hidden', 'false');
}
window.openTxDetailModal = openTxDetailModal;

function closeTxDetailModal() {
    var modal = document.getElementById('txDetailModal');
    if (modal) { modal.style.display = 'none'; modal.setAttribute('aria-hidden', 'true'); }
}
window.closeTxDetailModal = closeTxDetailModal;

function applySnapshotToUI(data) {
    if (!data || typeof data !== 'object') return;
    // Progressive render: apply each section as it arrives
    if (data.prices && typeof data.prices === 'object' && !data.prices._error) {
        const priceMap = {};
        const miniData = {};
        for (const [sym, d] of Object.entries(data.prices)) {
            if (d && typeof d === 'object') {
                const p = d.price;
                if (p != null && Number.isFinite(p)) priceMap[sym] = p;
                const mini = { last: p || 0, open: p || 0, volume: d.volume24h || 0, quoteVolume: (d.volume24h || 0) * (p || 0), marketCap: 0 };
                if (d.change24h != null && Number.isFinite(Number(d.change24h))) mini.changePct = Number(d.change24h);
                miniData[sym] = mini;
            }
        }
        if (window.marketStore && Object.keys(priceMap).length) {
            window.marketStore.updatePrices(priceMap);
            for (const [sym, m] of Object.entries(miniData)) window.marketStore.updateMini(sym, m);
            // Favori Coinler paneli hemen güncellensin (tick 2sn beklemeyelim)
            if (document.getElementById('tabBinance')?.classList.contains('is-active') && typeof tickBinanceCoinListPrices === 'function') {
                tickBinanceCoinListPrices();
            }
        }
    }
    if (data.wallet && typeof data.wallet === 'object' && assetsState && assetsState.wallet) {
        var w = data.wallet;
        var meta = data.meta || {};
        var walletTsIso = meta.wallet_ts_iso || w.ts || null;
        var walletAgeSec = meta.wallet_age_sec;
        var walletTime = parseDashboardWalletTime(walletTsIso);
        if (walletTime) {
            walletAgeSec = Math.max(0, Math.round((Date.now() - walletTime.getTime()) / 1000));
        }
        var walletStale = walletAgeSec != null ? Number(walletAgeSec) >= 900 : !!meta.stale;
        normalizeAndApplyWallet(w, {
            source: 'dashboard_snapshot',
            request_id: meta.request_id || w._request_id,
            wallet_age_sec: walletAgeSec,
            stale: walletStale
        });
        if (window.__walletDebugMeta === undefined) window.__walletDebugMeta = {};
        window.__walletDebugMeta.wallet_source = meta.wallet_source;
        window.__walletDebugMeta.wallet_age_sec = walletAgeSec;
        window.__walletDebugMeta.wallet_ts_iso = walletTsIso;
        window.__walletDebugMeta.request_id = meta.request_id;
        maybeRefreshStaleWalletFromDashboard();
    }
    if (data.pnl && typeof data.pnl === 'object' && !data.pnl._error) {
        var spotUsd = (data.wallet && typeof data.wallet.total_usd === 'number' && data.wallet.total_usd >= 0) ? data.wallet.total_usd : (State.summary && State.summary.account && typeof State.summary.account.spot_balance_usd === 'number' ? State.summary.account.spot_balance_usd : (typeof (assetsState && assetsState.wallet && assetsState.wallet.total_usd) === 'number' ? assetsState.wallet.total_usd : 0));
        if (data.bots && Array.isArray(data.bots) && data.bots.length > 0) {
            State.bots = hydrateBotsWithMetricsCache(data.bots);
            resetFinanceBotsLiveCache(State.bots);
        }
        const merged = { ...data.pnl, binance_balance_usd: spotUsd, spot_balance_usd: spotUsd, free_usd: data.wallet?.free_usd ?? 0, locked_usd: data.wallet?.locked_usd ?? 0, available_usd: data.wallet?.available_usd ?? 0, bot_locked_usd: data.wallet?.bot_locked_usd ?? 0, account: data.account || {}, bots: (data.bots && data.bots.length > 0) ? data.bots : (State.bots || []), bot_summary: data.pnl.bot_summary || [] };
        if (typeof updateFinanceKPIs === 'function') updateFinanceKPIs(merged);
    }
    if (data.bots && Array.isArray(data.bots) && data.account) {
        var incomingBots = data.bots;
        if (!(incomingBots.length === 0 && State.bots && State.bots.length > 0)) {
            State.bots = hydrateBotsWithMetricsCache(incomingBots);
            resetFinanceBotsLiveCache(State.bots);
            State.isTestAccount = !!(data.account.is_test_account);
            const summaryShape = {
                account: data.account,
                bots: State.bots,
                account_name: data.account.name,
                user_name: data.account.user_name,
                user_surname: data.account.user_surname,
                total_bots: data.account.total_bots,
                active_bots: data.account.active_bots,
                daily_bot_pnl_usd: data.account.daily_bot_pnl_usd,
                daily_wallet_pnl_usd: data.account.daily_wallet_pnl_usd,
                total_pnl_usd: data.account.total_pnl_usd,
                is_test_account: State.isTestAccount
            };
            State.summary = summaryShape;
            State.lastSummaryHash = computeHash(summaryShape);
            if (typeof renderBotsList === 'function') {
                if (isBotsTabActive() && isBotsTabCacheReady()) {
                    var snapIds = State.bots.map(function (b) { return String(b.bot_id || b.id || ''); }).sort().join(',');
                    if (snapIds === _financeBotsIdsSignature) {
                        patchFinanceBotsMetrics(State.bots);
                    } else {
                        renderBotsList(State.bots);
                    }
                } else {
                    renderBotsList(State.bots);
                }
            }
            if (typeof updateKPIs === 'function') updateKPIs(summaryShape);
            if (typeof maybeRefreshWalletOnBotsChange === 'function') maybeRefreshWalletOnBotsChange(State.bots, data.account);
            if (typeof updateAccountName === 'function') updateAccountName(data.account.name || "Hesap Dashboard");
            if (typeof setAppbarAccountHolderName === 'function') setAppbarAccountHolderName(summaryShape);
            hideError();
        }
    }
    if (State.accountId && typeof loadBotPerformance === 'function') {
        loadBotPerformance(State.botPerformancePeriod || 'all');
    }
    if (State.accountId && typeof loadGlobalLeaderboard === 'function') {
        loadGlobalLeaderboard(isBotsTabActive() && isBotsTabCacheReady());
    }
    if (State.accountId && typeof loadTransactionHistory === 'function') {
        loadTransactionHistory(
            State.txHistoryPeriod || 'daily',
            State.txHistoryType || 'buysell',
            State.txHistoryPage || 1,
            false,
            { silent: _txHistoryLoaded }
        );
    }
}

function computeHash(data) {
    if (!data) return "";
    const account = data.account || {};
    const bots = data.bots || [];
    const botsHash = bots.map(b => `${b.bot_id ?? b.id}:${b.status}:${b.current_usd ?? ''}:${b.last_trade_at || ''}`).join('|');
    const walletKey = String(account.spot_balance_usd ?? data.spot_balance_usd ?? '');
    return `${walletKey}:${account.bots_balance_usd ?? ''}:${bots.length}:${botsHash}`;
}

function isBinanceTabActive() {
    const t = document.getElementById('tabBinance');
    return !!(t && t.classList.contains('is-active'));
}

function isBotsTabActive() {
    const t = document.getElementById('tabBots');
    return !!(t && t.classList.contains('is-active'));
}

/** Botlar sekmesi: ilk açılışta tam DOM; sonraki geçişlerde yalnızca metrik/fiyat güncellemesi. */
var _botsTabCache = { accountId: null, initialized: false };

function botsTabCacheSessionKey(accountId) {
    return 'dashboard_bots_tab_ready_v1_' + (accountId || '');
}

function clearBotsTabCache() {
    _botsTabCache.initialized = false;
    _botsTabCache.accountId = null;
    if (State.accountId) {
        try {
            sessionStorage.removeItem(botsTabCacheSessionKey(State.accountId));
            sessionStorage.removeItem(financeBotsDomCacheKey(State.accountId));
        } catch (e) {}
    }
}

function isBotsTabCacheReady() {
    if (!_botsTabCache.initialized || _botsTabCache.accountId !== State.accountId) return false;
    return _financeBotsPanelHasRows(document.getElementById('financeBotsListBots'));
}

function markBotsTabCacheReady() {
    if (!State.accountId) return;
    _botsTabCache.initialized = true;
    _botsTabCache.accountId = State.accountId;
    try { sessionStorage.setItem(botsTabCacheSessionKey(State.accountId), '1'); } catch (e) {}
    if (typeof persistFinanceBotsDomCache === 'function') persistFinanceBotsDomCache();
}

function financeBotsDomCacheKey(accountId) {
    return 'financeBotsDom_v1_' + (accountId || '');
}

/** Bot detaydan dönüşte tablo HTML — renderFinanceBots yerine enjekte. */
function persistFinanceBotsDomCache() {
    if (!State.accountId) return;
    var home = document.getElementById('financeBotsList');
    var tab = document.getElementById('financeBotsListBots');
    var src = (_financeBotsPanelHasRows(tab) && tab) ? tab : ((_financeBotsPanelHasRows(home) && home) ? home : null);
    if (!src || !src.innerHTML || src.innerHTML.indexOf('data-bot-id') < 0) return;
    try {
        sessionStorage.setItem(financeBotsDomCacheKey(State.accountId), JSON.stringify({
            ts: Date.now(),
            html: src.innerHTML,
            structureSig: _financeBotsStructureSignature,
            idsSig: _financeBotsIdsSignature,
            sortBy: normalizeFinanceBotsSortBy(typeof financeBotsSortBy !== 'undefined' ? financeBotsSortBy : 'best')
        }));
    } catch (e) { /* quota */ }
}

function restoreFinanceBotsDomFromSessionCache(accountId, bots) {
    if (!accountId) return false;
    try {
        var raw = sessionStorage.getItem(financeBotsDomCacheKey(accountId));
        if (!raw) return false;
        var data = JSON.parse(raw);
        if (!data || !data.html || data.html.indexOf('data-bot-id') < 0) return false;
        if (data.ts && Date.now() - data.ts > 86400000) return false;
        bots = Array.isArray(bots) ? bots : [];
        var sortBy = normalizeFinanceBotsSortBy(data.sortBy || (typeof financeBotsSortBy !== 'undefined' ? financeBotsSortBy : 'best'));
        var structureSig = bots.length ? financeBotsStructureSignature(bots, sortBy) : data.structureSig;
        var idsSig = bots.length
            ? bots.map(function (b) { return String(b.bot_id || b.id || ''); }).sort().join(',')
            : data.idsSig;
        if (data.idsSig && idsSig && data.idsSig !== idsSig) return false;
        if (data.structureSig && structureSig && data.structureSig !== structureSig) return false;
        var home = document.getElementById('financeBotsList');
        var tab = document.getElementById('financeBotsListBots');
        if (!home && !tab) return false;
        if (home) {
            home.innerHTML = data.html;
            bindFinanceBotsRowClicks(home);
        }
        if (tab) {
            tab.innerHTML = data.html;
            bindFinanceBotsRowClicks(tab);
        }
        _financeBotsStructureSignature = structureSig || data.structureSig;
        _financeBotsIdsSignature = idsSig || data.idsSig;
        if (data.sortBy) financeBotsSortBy = normalizeFinanceBotsSortBy(data.sortBy);
        markBotsTabCacheReady();
        return true;
    } catch (e) {
        return false;
    }
}

function persistDashboardBeforeBotDetailNav() {
    try { localStorage.setItem('dashboard_active_tab', 'bots'); } catch (e) {}
    if (typeof persistFinanceBotsDomCache === 'function') persistFinanceBotsDomCache();
    if (State.accountId) {
        try { sessionStorage.setItem(botsTabCacheSessionKey(State.accountId), '1'); } catch (e) {}
    }
}

function tryRestoreBotsTabCacheFlag(accountId) {
    if (!accountId) return false;
    try {
        if (sessionStorage.getItem(botsTabCacheSessionKey(accountId)) !== '1') return false;
    } catch (e) { return false; }
    if (!_financeBotsPanelHasRows(document.getElementById('financeBotsListBots'))) return false;
    _botsTabCache.initialized = true;
    _botsTabCache.accountId = accountId;
    return true;
}

/** Tablo yeniden çizilmeden canlı fiyat, bakiye, K/Z, leaderboard, performans. */
function refreshBotsTabDataOnly() {
    if (State.bots && State.bots.length) {
        patchFinanceBotsMetrics(State.bots);
    } else {
        updateFinanceBotsLivePrices();
    }
    if (typeof ensureFinanceBotsLiveEquity === 'function') ensureFinanceBotsLiveEquity();
    if (typeof ensureFinanceBotsHealthPolling === 'function') ensureFinanceBotsHealthPolling();
    if (State.accountId && typeof loadBotPerformance === 'function') {
        loadBotPerformance(State.botPerformancePeriod || 'all');
    }
    if (typeof loadGlobalLeaderboard === 'function') loadGlobalLeaderboard(true);
}

/**
 * Botlar sekmesi açılışı — force:true hesap değişimi veya bot listesi yapısal değişiminde.
 */
function activateBotsTab(opts) {
    opts = opts || {};
    if (opts.force) clearBotsTabCache();
    if (!opts.force && tryRestoreBotsTabCacheFlag(State.accountId)) {
        refreshBotsTabDataOnly();
        if (typeof _bindFinanceBotsSortButtons === 'function') _bindFinanceBotsSortButtons();
        return;
    }
    if (!opts.force && isBotsTabCacheReady()) {
        refreshBotsTabDataOnly();
        if (typeof _bindFinanceBotsSortButtons === 'function') _bindFinanceBotsSortButtons();
        return;
    }

    if (typeof _bindFinanceBotsSortButtons === 'function') _bindFinanceBotsSortButtons();

    if (State.accountId && typeof restoreFinanceBotsFromSessionCache === 'function') {
        restoreFinanceBotsFromSessionCache(State.accountId);
    }

    var tabList = document.getElementById('financeBotsListBots');
    if (_financeBotsPanelHasRows(tabList)) {
        markBotsTabCacheReady();
        refreshBotsTabDataOnly();
        return;
    }

    if (typeof syncFinanceBotsTabFromHome === 'function') syncFinanceBotsTabFromHome();
    if (_financeBotsPanelHasRows(tabList)) {
        markBotsTabCacheReady();
        refreshBotsTabDataOnly();
        return;
    }

    if (State.bots && State.bots.length && typeof renderFinanceBots === 'function') {
        renderFinanceBots(State.bots, { forceFullRender: true });
    } else if (State.accountId) {
        if (typeof loadBotsListFast === 'function') loadBotsListFast(State.accountId);
        if (!State.bots || !State.bots.length) {
            if (typeof loadSummary === 'function') loadSummary(State.accountId);
        }
    }

    if (State.accountId && typeof loadBotPerformance === 'function') {
        loadBotPerformance(State.botPerformancePeriod || 'all');
    }
    if (typeof loadGlobalLeaderboard === 'function') loadGlobalLeaderboard(false);

    if (_financeBotsPanelHasRows(tabList)) markBotsTabCacheReady();
}
window.activateBotsTab = activateBotsTab;

/** Hızlı bot listesi: /api/bots-engine ile hemen listeyi doldurur; summary gelene kadar "Yükleniyor" kalmaz. */
function loadBotsListFast(accountId) {
    if (!accountId || !window.apiClient) return;
    window.apiClient.get('/api/bots-engine?account_id=' + accountId, { timeout: 8000 })
        .then(function(res) {
            // Summary zaten geldiyse (current_usd dahil) onu ezme; sadece henüz veri yoksa doldur
            if (State.summary && Array.isArray(State.summary.bots) && State.summary.bots.length > 0) return;
            if (_financeBotsTableHasRows() && isBotsTabCacheReady()) {
                var list = Array.isArray(res.bots) ? res.bots : [];
                if (!list.length) return;
                var mapped = list.map(function(r) {
                    var cfg = r.config || {};
                    var budget = Number(cfg.initial_capital_usdt || cfg.budget_usd || cfg.bot_budget_usdt) || 0;
                    var existing = (State.bots || []).find(function(b) { return (b.bot_id || b.id) === r.bot_id; });
                    var base = {
                        bot_id: r.bot_id, id: r.bot_id, symbol: r.symbol || 'N/A',
                        status: (r.status || 'stopped').toLowerCase(),
                        display_status: r.display_status || r.status || 'stopped',
                        initial_allocation_done: r.initial_allocation_done === true,
                        health_alert_level: r.health_alert_level || null,
                        health_alerts: Array.isArray(r.health_alerts) ? r.health_alerts : [],
                        account_id: r.account_id, config: cfg,
                        budget_usd: budget, initial_usd: budget,
                        total_pnl_usd: 0, total_pnl_pct: 0, daily_pnl_usd: 0,
                        last_trade_at: r.last_tick_at || r.created_at || null
                    };
                    if (!existing) return base;
                    return Object.assign({}, base, {
                        current_usd: existing.current_usd,
                        total_pnl_usd: existing.total_pnl_usd != null ? existing.total_pnl_usd : base.total_pnl_usd,
                        total_pnl_pct: existing.total_pnl_pct != null ? existing.total_pnl_pct : base.total_pnl_pct,
                        total_cycles_completed: existing.total_cycles_completed,
                        cycle_id: existing.cycle_id,
                        daily_pnl_usd: existing.daily_pnl_usd != null ? existing.daily_pnl_usd : base.daily_pnl_usd
                    });
                });
                var idsSig = mapped.map(function (b) { return String(b.bot_id || b.id || ''); }).sort().join(',');
                if (idsSig === _financeBotsIdsSignature) {
                    State.bots = hydrateBotsWithMetricsCache(mapped);
                    patchFinanceBotsMetrics(State.bots);
                    return;
                }
            }
            var list = Array.isArray(res.bots) ? res.bots : [];
            var mapped = list.map(function(r) {
                var cfg = r.config || {};
                var budget = Number(cfg.initial_capital_usdt || cfg.budget_usd || cfg.bot_budget_usdt) || 0;
                var existing = (State.bots || []).find(function(b) { return (b.bot_id || b.id) === r.bot_id; });
                var base = {
                    bot_id: r.bot_id,
                    id: r.bot_id,
                    symbol: r.symbol || 'N/A',
                    status: (r.status || 'stopped').toLowerCase(),
                    display_status: r.display_status || r.status || 'stopped',
                    initial_allocation_done: r.initial_allocation_done === true,
                    health_alert_level: r.health_alert_level || null,
                    health_alerts: Array.isArray(r.health_alerts) ? r.health_alerts : [],
                    account_id: r.account_id,
                    config: cfg,
                    budget_usd: budget,
                    initial_usd: budget,
                    total_pnl_usd: 0,
                    total_pnl_pct: 0,
                    daily_pnl_usd: 0,
                    last_trade_at: r.last_tick_at || r.created_at || null
                };
                if (!existing) return base;
                return Object.assign({}, base, {
                    current_usd: existing.current_usd,
                    total_pnl_usd: existing.total_pnl_usd != null ? existing.total_pnl_usd : base.total_pnl_usd,
                    total_pnl_pct: existing.total_pnl_pct != null ? existing.total_pnl_pct : base.total_pnl_pct,
                    total_cycles_completed: existing.total_cycles_completed,
                    cycle_id: existing.cycle_id,
                    daily_pnl_usd: existing.daily_pnl_usd != null ? existing.daily_pnl_usd : base.daily_pnl_usd
                });
            });
            State.bots = hydrateBotsWithMetricsCache(mapped);
            renderBotsList(State.bots);
            if (typeof maybeRefreshWalletOnBotsChange === 'function') {
                maybeRefreshWalletOnBotsChange(State.bots, State.summary && State.summary.account);
            }
        })
        .catch(function() {
            if (State.bots && State.bots.length) return;
            if (_financeBotsTableHasRows()) return;
            renderBotsList([]);
        });
}

function isSpotModalOpen() {
    const m = document.getElementById('bnSpotTradeModal');
    return !!(m && m.style.display !== 'none');
}

// Update UI (patch updates) – account name no longer in appbar (center = company)

// ============================================================
// BOT LİSTESİ - K/Z sıralama: en kârlı üstte veya en zararda üstte
// ============================================================

var botsSortBy = 'best'; // legacy alias
var financeBotsSortBy = 'best'; // 'best' | 'worst'

function normalizeFinanceBotsSortBy(sortBy) {
    return sortBy === 'worst' ? 'worst' : 'best';
}

function financeBotSortPnlUsd(bot) {
    if (typeof resolveBotHeroKz === 'function') {
        var kz = resolveBotHeroKz(bot);
        if (kz && kz.usd != null && Number.isFinite(Number(kz.usd))) return Number(kz.usd);
    }
    return Number(bot.total_pnl_usd ?? bot.total_pnl ?? bot.pnl_30d ?? 0) || 0;
}

function compareFinanceBotsForSort(a, b) {
    var pa = financeBotSortPnlUsd(a);
    var pb = financeBotSortPnlUsd(b);
    if (normalizeFinanceBotsSortBy(financeBotsSortBy) === 'worst') return pa - pb;
    return pb - pa;
}

function financeBotsIdsSignature(bots) {
    return (bots || []).map(function (b) { return String(b.bot_id || b.id || ''); }).sort().join(',');
}

function reorderFinanceBotsListDom(container, sortedBotIds) {
    if (!container || !sortedBotIds || !sortedBotIds.length) return false;
    var tbody = container.querySelector('table.mevcut-botlar-table tbody');
    if (!tbody) return false;
    var rowMap = {};
    tbody.querySelectorAll('tr[data-bot-id]').forEach(function (tr) {
        rowMap[String(tr.getAttribute('data-bot-id'))] = tr;
    });
    var rowIds = Object.keys(rowMap);
    if (rowIds.length !== sortedBotIds.length) return false;
    for (var i = 0; i < sortedBotIds.length; i++) {
        if (!rowMap[String(sortedBotIds[i])]) return false;
    }
    sortedBotIds.forEach(function (id) {
        var tr = rowMap[String(id)];
        if (tr) tbody.appendChild(tr);
    });
    var mobileWrap = container.querySelector('.mevcut-botlar-mobile');
    if (mobileWrap) {
        var cardMap = {};
        mobileWrap.querySelectorAll('.mevcut-botlar-mobile-card[data-bot-id]').forEach(function (card) {
            cardMap[String(card.getAttribute('data-bot-id'))] = card;
        });
        if (Object.keys(cardMap).length === sortedBotIds.length) {
            sortedBotIds.forEach(function (id) {
                var card = cardMap[String(id)];
                if (card) mobileWrap.appendChild(card);
            });
        }
    }
    return true;
}

/** Sıralama değişince tabloyu yeniden çizmeden satırları taşır — coin logoları yeniden yüklenmez. */
function applyFinanceBotsSortReorder(bots) {
    bots = hydrateBotsWithMetricsCache(Array.isArray(bots) ? bots : []);
    if (!bots.length) return false;
    var idsSig = financeBotsIdsSignature(bots);
    if (idsSig !== _financeBotsIdsSignature) return false;
    var sorted = bots.slice().sort(compareFinanceBotsForSort);
    var sortedIds = sorted.map(function (b) { return String(b.bot_id || b.id || ''); });
    var containers = [document.getElementById('financeBotsList'), document.getElementById('financeBotsListBots')].filter(function (el) {
        return el && _financeBotsPanelHasRows(el);
    });
    if (!containers.length) return false;
    var ok = containers.every(function (c) { return reorderFinanceBotsListDom(c, sortedIds); });
    if (!ok) return false;
    State.bots = sorted;
    var sortBy = normalizeFinanceBotsSortBy(financeBotsSortBy);
    _financeBotsStructureSignature = financeBotsStructureSignature(bots, sortBy);
    _financeBotsIdsSignature = idsSig;
    if (typeof persistFinanceBotsDomCache === 'function') persistFinanceBotsDomCache();
    if (typeof markBotsTabCacheReady === 'function') markBotsTabCacheReady();
    return true;
}

function setBotsSortBy(sortBy) {
    setFinanceBotsSortBy(normalizeFinanceBotsSortBy(sortBy));
}

function setFinanceBotsSortBy(sortBy) {
    financeBotsSortBy = normalizeFinanceBotsSortBy(sortBy);
    updateFinanceBotsSortButtonUi(financeBotsSortBy);
    if (State.bots && State.bots.length) {
        if (!applyFinanceBotsSortReorder(State.bots)) {
            renderFinanceBots(State.bots, { forceFullRender: true });
        }
    } else {
        loadFinanceBotsList();
    }
}

function updateFinanceBotsSortButtonUi(sortBy) {
    sortBy = normalizeFinanceBotsSortBy(sortBy);
    var isWorst = sortBy === 'worst';
    var title = isWorst
        ? 'En zararda olan üstte. Tıkla: en kârlıya göre sırala'
        : 'En kârlı üstte. Tıkla: en zararda olana göre sırala';
    var icon = isWorst ? '↓' : '↑';
    ['btnSortBotsBy', 'btnSortBotsByBotsTab'].forEach(function (id) {
        var btn = document.getElementById(id);
        if (!btn) return;
        btn.title = title;
        btn.setAttribute('aria-label', title);
        btn.classList.toggle('profit-sort-worst', isWorst);
        btn.classList.toggle('profit-sort-best', !isWorst);
    });
    ['btnSortBotsByIcon', 'btnSortBotsByBotsTabIcon'].forEach(function (id) {
        var el = document.getElementById(id);
        if (el) el.textContent = icon;
    });
}

// Botlar sekmesi + Anasayfa aynı tablo: renderFinanceBots hem financeBotsList hem financeBotsListBots günceller
function renderBotsList(bots, opts) {
    if (typeof window.__DEBUG_DASH__ !== 'undefined' && window.__DEBUG_DASH__) console.count('renderBotsList');
    bots = Array.isArray(bots) ? bots : [];
    if (!(opts && opts.forceFullRender) && isBotsTabActive() && isBotsTabCacheReady()) {
        var idsSig = bots.map(function (b) { return String(b.bot_id || b.id || ''); }).sort().join(',');
        if (idsSig === _financeBotsIdsSignature) {
            State.bots = hydrateBotsWithMetricsCache(bots);
            refreshBotsTabDataOnly();
            return;
        }
        clearBotsTabCache();
    }
    renderFinanceBots(bots, opts);
}

// Compatibility
function renderBotsNow(bots) { renderBotsList(bots); }
function renderBotsListDirect(bots) { renderBotsList(bots); }
function updateBotsList(bots) { renderBotsList(bots); }

// ============================================================
// CREATE TAB: Bot Structures System
// ============================================================

/**
 * Bot Structures - Available bot types
 */
const BOT_STRUCTURES = [
    {
        id: 'trailing_dca',
        name: 'Trailing DCA Bot',
        description: 'Trailing stop-loss mekanizması ile çalışan DCA (Dollar Cost Averaging) botu. Fiyat hareketlerini takip ederek otomatik alım-satım işlemleri gerçekleştirir.',
        defaultConfig: {
            budget_usd: undefined,
            allocation: { base_pct: 50, quote_pct: 50 },
            up: { trail_pct: 0.30, grids: [] },
            down: { trail_pct: 0.30, grids: [] },
            profit: {
                rebuy_trigger_pct: 1.0,
                rebuy_trail_pct: 0.5,
                resell_trigger_pct: 2.0,
                resell_trail_pct: 1.0
            }
        }
    }];

/**
 * Open bot structure selection modal
 */
function openBotStructureModal() {
    const modal = document.getElementById("botStructureModal");
    const backdrop = document.getElementById("botStructureBackdrop");
    if (!modal || !backdrop) {
        console.warn("[dashboard] Bot structure modal elements not found");
        return;
    }
    
    modal.setAttribute("aria-hidden", "false");
    backdrop.setAttribute("aria-hidden", "false");
    modal.style.display = "flex";
    backdrop.style.display = "block";
    document.body.style.overflow = "hidden";
    
    // Render bot structures
    renderBotStructures();
}

/**
 * Close bot structure selection modal
 */
function closeBotStructureModal() {
    const modal = document.getElementById("botStructureModal");
    const backdrop = document.getElementById("botStructureBackdrop");
    if (!modal || !backdrop) return;
    
    modal.setAttribute("aria-hidden", "true");
    backdrop.setAttribute("aria-hidden", "true");
    modal.style.display = "none";
    backdrop.style.display = "none";
    document.body.style.overflow = "";
}

function escapeHtml(s) {
    if (s == null) return '';
    var div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
}

function applyLeaderboardParams(structure, params, itemIndex) {
    closeBotStructureModal();
    if (!structure) return;
    var normalized = normalizeLeaderboardParamsToFormConfig(resolveLeaderboardItemParams(params, itemIndex));
    var synthetic = { id: structure.id, name: structure.name || structure.id, defaultConfig: normalized, fromLeaderboardApply: true };
    currentSelectedTemplate = structure;
    fillModalWithTemplate(synthetic);
    openCreateBotModal(null, null, true, 'fBudget');
    setTimeout(function () {
        applyTrailingDcaConfigToForm(normalized, { clearBudget: true, symbolReadOnly: false });
        var focusEl = document.getElementById('fBudget');
        if (focusEl) focusEl.focus();
    }, 130);
}

/**
 * Render bot structures in modal - Clean, professional design
 */
function renderBotStructures() {
    const container = document.getElementById("botStructuresList");
    if (!container) {
        console.warn("[dashboard] botStructuresList container not found");
        return;
    }
    
    container.innerHTML = "";
    
    BOT_STRUCTURES.forEach(structure => {
        if (!structure || structure.id === 'trdca_pro') return;
        const card = document.createElement("div");
        card.style.cssText = `
            background: var(--ds-bg-secondary, #1e2329);
            border: 1px solid var(--ds-border, #2b3139);
            border-radius: 8px;
            padding: 20px 24px;
            cursor: pointer;
            transition: all 0.2s ease;
            width: 100%;
            
        `;
        card.dataset.structureId = structure.id;
        card.className = "bot-structure-card";
        const btnLabel = 'Devam Et →';
        const btnDisabled = '';
        card.innerHTML = `
            <div class="bot-structure-card__inner">
                <div class="bot-structure-card__text">
<h3 style="margin: 0 0 6px 0; font-size: 1.1rem; font-weight: 600; color: var(--ds-text-primary);">${structure.name}</h3>
                    <p style="margin: 0; font-size: 0.9rem; color: var(--ds-text-secondary); line-height: 1.4;">${structure.description}</p>
                </div>
                <div style="display: flex; flex-wrap: wrap; gap: 8px; align-items: center;">
                    <button class="btn btn-primary-gold bot-structure-card__btn" style="padding: 10px 24px; font-weight: 600; white-space: nowrap;" data-action="select" data-structure-id="${structure.id}"${btnDisabled}>
                        ${btnLabel}
                    </button>
                </div>
            </div>
        `;
        
        card.onmouseenter = () => {
            card.style.borderColor = 'var(--ds-accent, #f0b90b)';
            card.style.backgroundColor = 'var(--ds-bg-hover, rgba(240, 185, 11, 0.05))';
        };
        card.onmouseleave = () => {
            card.style.borderColor = 'var(--ds-border, #2b3139)';
            card.style.backgroundColor = 'var(--ds-bg-secondary, #1e2329)';
        };

        // Select button
        const selectBtn = card.querySelector('[data-action="select"]');
        if (selectBtn) {
            selectBtn.onclick = (e) => {
                e.stopPropagation();
                selectBotStructure(structure);
            };
        }
        // Card click
        card.onclick = (e) => {
            if (!e.target.closest('button')) {
                selectBotStructure(structure);
            }
        };
        
        container.appendChild(card);
    });
}

/**
 * Select bot structure and open parameter modal
 */
function selectBotStructure(structure) {
    console.log("[dashboard] Selected bot structure:", structure.id);
    
    // Store selected structure
    currentSelectedTemplate = structure;
    
    // Close bot structure selection modal
    closeBotStructureModal();
    
    // Fill modal with structure defaults
    fillModalWithTemplate(structure);
    
    // Open parameter modal (it will use currentSelectedTemplate to set button)
    openCreateBotModal();
}

/**
 * Show DCA or Multi wizard body in create bot modal
 */
function setCreateBotModalWizard(templateId) {
    const dca = document.getElementById("dmWizardDca");
    const multi = document.getElementById("dmWizardMulti");
    const pairStrip = document.getElementById("dmSelectedPairStrip");
    const tahminStrip = document.getElementById("dmTahminStrip");
    if (dmModalMultiPreviewIntervalId) {
        clearInterval(dmModalMultiPreviewIntervalId);
        dmModalMultiPreviewIntervalId = null;
    }
    if (dca) dca.style.display = "block";
    if (multi) multi.style.display = "none";
    hideMultiSymbolSearchDropdown();
    if (pairStrip) pairStrip.style.display = "none";
    if (tahminStrip) tahminStrip.style.display = "none";
}

/**
 * Build multi-asset rows (symbol + target_pct)
 */
function buildMultiAssetRows(count) {
    count = Math.min(10, Math.max(2, parseInt(count, 10) || 2));
    const container = document.getElementById("multiAssetRows");
    if (!container) return;
    hideMultiSymbolSearchDropdown();
    container.innerHTML = "";
    for (let i = 0; i < count; i++) {
        const row = document.createElement("div");
        row.className = "multi-asset-row";
        row.setAttribute("data-idx", String(i));
        row.style.marginBottom = "12px";
        row.innerHTML = `
            <div class="grid-2" style="gap: 8px;">
                <div class="form-group" style="position: relative;">
                    <label>Coin ${i + 1}</label>
                    <input type="text" class="form-input multi-asset-symbol" data-idx="${i}" placeholder="Sembol" maxlength="10" style="text-transform: uppercase; width: 100%; padding: 0.6rem 1rem;" autocomplete="off" />
                </div>
                <div class="form-group">
                    <label>Hedef %</label>
                    <input type="number" class="form-input multi-asset-pct" data-idx="${i}" min="0" max="100" step="1" placeholder="" style="width: 100%; padding: 0.6rem 1rem;" />
                </div>
            </div>
            <div class="multi-asset-preview multi-asset-preview-empty" data-idx="${i}" style="margin-top: 6px; padding: 8px 12px; font-size: 0.85rem; background: var(--ds-bg-tertiary); border-radius: 8px; border: 1px solid var(--ds-border); min-height: 24px;">—</div>
        `;
        container.appendChild(row);
    }
    updateMultiPctTotal();
}

function updateMultiBudgetPlaceholder() {
    var modal = document.getElementById("dmModal");
    var wizardMulti = document.getElementById("dmWizardMulti");
    if (!modal || modal.style.display === "none" || !wizardMulti || wizardMulti.style.display !== "block") return;
    var fMultiBudget = document.getElementById("fMultiBudget");
    if (!fMultiBudget) return;
    fMultiBudget.placeholder = formatAvailableQuotePlaceholder("USDT", getAvailableQuoteInWallet("USDT"));
}

function updateMultiRebalanceModeVisibility() {
    var mode = (document.getElementById("fMultiRebalanceMode") && document.getElementById("fMultiRebalanceMode").value) || "threshold";
    var thresholdPctGroup = document.getElementById("multiThresholdPctGroup");
    var row = document.getElementById("multiIntervalCooldownRow");
    var secGroup = document.getElementById("multiIntervalSecGroup");
    var cooldownGroup = document.getElementById("multiCooldownGroup");
    var hoursGroup = document.getElementById("multiIntervalHoursGroup");
    var fMultiIntervalSec = document.getElementById("fMultiIntervalSec");
    var fMultiIntervalHours = document.getElementById("fMultiIntervalHours");
    if (thresholdPctGroup) thresholdPctGroup.style.display = mode === "interval" ? "none" : "block";
    if (!row) return;
    if (mode === "threshold") {
        row.style.display = "none";
        return;
    }
    row.style.display = "grid";
    if (secGroup) secGroup.style.display = "none";
    if (cooldownGroup) cooldownGroup.style.display = "none";
    if (hoursGroup) hoursGroup.style.display = "block";
    if (fMultiIntervalSec && fMultiIntervalHours) fMultiIntervalHours.value = Math.round(parseInt(fMultiIntervalSec.value, 10) / 3600) || 1;
}

function updateMultiPctTotal() {
    var total = 0;
    document.querySelectorAll("#multiAssetRows .multi-asset-pct").forEach(function (el) {
        total += parseFloat(el.value) || 0;
    });
    var el = document.getElementById("multiPctTotal");
    if (el) {
        el.textContent = total.toFixed(1);
        el.style.color = Math.abs(total - 100) < 0.01 ? "var(--ds-success, #0ecb81)" : "var(--ds-text-secondary)";
    }
}

/**
 * Fill modal with template default values
 */
function fillModalWithTemplate(template) {
    const config = template.defaultConfig || {};
    const fromLeaderboard = !!template.fromLeaderboardApply;
    setCreateBotModalWizard(template.id);

    if (fromLeaderboard) {
        applyTrailingDcaConfigToForm(normalizeLeaderboardParamsToFormConfig(config), { clearBudget: true, symbolReadOnly: false });
        return;
    }

    // Budget: normal şablon açılışı
    const budgetEl = document.getElementById("fBudget");
    if (budgetEl) budgetEl.value = (config.budget_usd !== undefined && config.budget_usd !== null && config.budget_usd !== '') ? config.budget_usd : '';
    
    // Allocation
    const basePctEl = document.getElementById("fBasePct");
    if (basePctEl) basePctEl.value = config.allocation?.base_pct || 50;
    
    const quotePctEl = document.getElementById("fQuotePct");
    if (quotePctEl) quotePctEl.value = config.allocation?.quote_pct || 50;
    
    // Up grid (varsayılan 0.5)
    const upTrailEl = document.getElementById("fUpTrail");
    if (upTrailEl) upTrailEl.value = config.up?.trail_pct ?? 0.5;
    
    // Down grid (varsayılan 0.5)
    const downTrailEl = document.getElementById("fDownTrail");
    if (downTrailEl) downTrailEl.value = config.down?.trail_pct ?? 0.5;
    
    // Profit config (varsayılan tetik 1.5, trail 0.5)
    const rebuyTriggerEl = document.getElementById("fRebuyTrigger");
    if (rebuyTriggerEl) rebuyTriggerEl.value = config.profit?.rebuy_trigger_pct ?? 1.5;
    
    const rebuyTrailEl = document.getElementById("fRebuyTrail");
    if (rebuyTrailEl) rebuyTrailEl.value = config.profit?.rebuy_trail_pct ?? 0.30;
    
    const resellTriggerEl = document.getElementById("fResellTrigger");
    if (resellTriggerEl) resellTriggerEl.value = config.profit?.resell_trigger_pct ?? 1.5;
    
    const resellTrailEl = document.getElementById("fResellTrail");
    if (resellTrailEl) resellTrailEl.value = config.profit?.resell_trail_pct ?? 0.5;
    
    // Reset grid counts
    const upCountEl = document.getElementById("fUpCount");
    if (upCountEl) upCountEl.value = 0;
    
    const downCountEl = document.getElementById("fDownCount");
    if (downCountEl) downCountEl.value = 0;
    
    // Clear grid rows
    const upGridRows = document.getElementById("upGridRows");
    if (upGridRows) upGridRows.innerHTML = "";
    const downGridRows = document.getElementById("downGridRows");
    if (downGridRows) downGridRows.innerHTML = "";
    
    // Clear symbol (user must enter)
    const symbolEl = document.getElementById("fSymbol");
    if (symbolEl) {
        symbolEl.value = "";
        symbolEl.readOnly = false;
    }
}

/**
 * Create bot and start it immediately
 */
async function createAndStartBot(template) {
    if (!State.accountId) {
        showError("Hesap ID bulunamadı");
        return;
    }
    
    const errorEl = document.getElementById("createBotError");
    if (errorEl) errorEl.style.display = "none";
    
    // Collect form data
    const payload = collectForm();
    const error = validateForm(payload);
    
    if (error) {
        showCreateBotFormError(errorEl, error);
        return;
    }

    const displayName = payload.symbol || "Bot";

    var requestedBudget = 0;
    var quoteAsset = "USDT";
    requestedBudget = Number(payload.budget_usd) || 0;
    try {
        var pq = parseBaseQuote(payload.symbol || "");
        quoteAsset = (pq && pq.quote) ? pq.quote : "USDT";
    } catch (e) { quoteAsset = "USDT"; }
    if (requestedBudget > 0) {
        var availableQuote = getAvailableQuoteInWallet(quoteAsset);
        if (availableQuote == null || availableQuote === undefined) {
            if (errorEl) {
                errorEl.textContent = "Bakiye bilgisi yüklenemedi. Lütfen sayfayı yenileyin veya kısa süre sonra tekrar deneyin.";
                errorEl.style.display = "block";
            }
            return;
        }
        if (!Number.isFinite(availableQuote)) availableQuote = 0;
        if (requestedBudget > availableQuote) {
            var fmt = (quoteAsset === "USDT" || quoteAsset === "BUSD" || quoteAsset === "FDUSD") && typeof fmtNum === "function" ? fmtNum(availableQuote, 2) : (availableQuote.toFixed(2));
            if (errorEl) {
                errorEl.textContent = "Bakiye yetersiz. Bot bütçesi: " + requestedBudget + " " + quoteAsset + ", kullanılabilir: " + fmt + " " + quoteAsset + ". Bütçeyi düşürün veya cüzdana bakiye ekleyin.";
                errorEl.style.display = "block";
            }
            return;
        }
    }

    try {
        // Create bot
        const body = {
            account_id: payload.account_id,
            config_json: JSON.stringify(payload)
        };
        
        const createData = await window.apiClient.post("/api/bots/create", body);
        const botId = createData.bot_id || createData.id;
        
        if (!botId) {
            throw new Error("Bot oluşturuldu ancak bot ID alınamadı");
        }
        
        var createLabel = displayName;
        if (window.Toast) {
            window.Toast.success('Bot ' + createLabel + ' oluşturuldu');
        }
        try { localStorage.setItem(DASHBOARD_LAST_CREATE_BOT_PARAMS, JSON.stringify(payload)); } catch (e) {}
        
        // Start bot immediately (bots-engine inserts command for worker)
        try {
            const startResp = await window.apiClient.post(`/api/bots-engine/${botId}/start?account_id=${State.accountId}`);
            
            var startLabel = createLabel;
            if (window.Toast) {
                if (startResp && startResp.worker_alive === false) {
                    window.Toast.warning('Bot oluşturuldu ancak Engine worker çalışmıyor. Proje kökünden ./start.command çalıştırın.');
                } else {
                    window.Toast.success('Bot ' + startLabel + ' başlatıldı; ilk alım worker tarafından işlenecek.');
                }
            }
        } catch (startError) {
            console.error("[dashboard] Error starting bot:", startError);
            if (window.errorReporter) {
                window.errorReporter.report(startError, { tab: 'create', bot_id: botId, account_id: State.accountId, action: 'startBot' });
            }
            if (window.Toast) {
                window.Toast.warning(`Bot oluşturuldu ancak başlatılamadı: ${startError.message}`);
            }
        }
        
        // Close modal
        closeCreateBotModal();
        
        // Refresh bot list in Bots tab
        await loadSummary(State.accountId);
        
        // Yeni bot detayına git (eski bot ekranı / bfcache karışıklığını önler)
        var navQ = State.accountCode ? 'account_code=' + encodeURIComponent(State.accountCode) : 'account_id=' + (State.accountId || '');
        var detailPage = (payload.strategy_id === 'multi_asset_rebalance') ? '/ui/bot_multi.html' : '/ui/bot.html';
        window.location.assign(detailPage + '?bot_id=' + botId + '&' + navQ);
        return;
        
    } catch (error) {
        console.error("[dashboard] Error creating bot:", error);
        if (window.errorReporter) {
            window.errorReporter.report(error, { tab: 'create', account_id: State.accountId, action: 'createBot' });
            window.errorReporter.show(error, { tab: 'create', account_id: State.accountId });
        } else {
            const msg = error.message || "Bilinmeyen hata";
            showCreateBotFormError(errorEl, "Bot oluşturulamadı: " + msg);
        }
    }
}

/**
 * Render bot list in Create tab - Clean, professional design
 */
function renderCreateTabBotsList() {
    const container = document.getElementById("createTabBotsList");
    const emptyEl = document.getElementById("createTabBotsEmpty");
    
    if (!container) {
        console.warn("[dashboard] createTabBotsList container not found");
        return;
    }
    
    // Use State.bots if available, otherwise load
    const bots = State.bots || [];
    
    if (bots.length === 0) {
        container.style.display = "none";
        if (emptyEl) emptyEl.style.display = "block";
        return;
    }
    
    if (emptyEl) emptyEl.style.display = "none";
    container.style.display = "grid";
    container.innerHTML = "";
    
    bots.forEach(bot => {
        const botId = bot.bot_id ?? bot.id ?? 0;
        const symbol = bot.symbol || 'N/A';
        const status = (bot.status || 'stopped').toLowerCase();
        const accountId = bot.account_id || State.accountId || 0;
        
        // Status colors
        let statusColor = '#6c757d';
        let statusBg = 'rgba(108, 117, 125, 0.1)';
        if (status === 'running') {
            statusColor = '#0ecb81';
            statusBg = 'rgba(14, 203, 129, 0.1)';
        } else if (status === 'paused') {
            statusColor = '#f0b90b';
            statusBg = 'rgba(240, 185, 11, 0.1)';
        } else if (status === 'error') {
            statusColor = '#f6465d';
            statusBg = 'rgba(246, 70, 93, 0.1)';
        }
        
        // PnL
        const totalPnl = Number(bot.total_pnl_usd ?? 0);
        const pnlColor = totalPnl > 0 ? '#0ecb81' : totalPnl < 0 ? '#f6465d' : 'var(--ds-text-secondary)';
        // Card title: MULTI botlarda bot_code (#456789) göster, diğerlerinde symbol
        const cardTitle = (symbol === 'MULTI' && (bot.bot_code || botId)) ? ('#' + (bot.bot_code || botId)) : symbol;
        
        // Card - Clean, minimal design
        const card = document.createElement("div");
        card.style.cssText = `
            background: var(--ds-bg-secondary, #1e2329);
            border: 1px solid var(--ds-border, #2b3139);
            border-radius: 8px;
            padding: 20px;
            transition: all 0.2s ease;
        `;
        card.dataset.botId = botId;
        card.dataset.accountId = accountId;
        
        card.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px;">
                <div>
                    <div style="font-size: 1.25rem; font-weight: 600; color: var(--ds-text-primary); margin-bottom: 4px;">${cardTitle}</div>
                    <div style="font-size: 0.85rem; color: var(--ds-text-secondary);">Bot ID: ${botId}</div>
                </div>
                <span style="display: inline-block; padding: 4px 10px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; color: ${statusColor}; background: ${statusBg};">
                    ${(bot.status || 'STOPPED').toUpperCase()}
                </span>
            </div>
            
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; padding: 12px; background: var(--ds-bg-tertiary, #2b3139); border-radius: 6px;">
                <div>
                    <div style="font-size: 0.75rem; color: var(--ds-text-secondary); margin-bottom: 4px;">Bütçe</div>
                    <div style="font-size: 1rem; font-weight: 600; color: var(--ds-text-primary);">${fmtUsd(bot.budget_usd || bot.initial_usd || 0)}</div>
                </div>
                <div>
                    <div style="font-size: 0.75rem; color: var(--ds-text-secondary); margin-bottom: 4px;">Kazanç/Zarar</div>
                    <div style="font-size: 1rem; font-weight: 600; color: ${pnlColor};">${fmtSignedUsd(totalPnl)}</div>
                </div>
            </div>
            
            <div style="display: flex; gap: 8px; align-items: center;">
                <span style="flex: 1; font-size: 0.875rem; font-weight: 600; color: ${status === 'running' ? 'var(--ds-success, #0ecb81)' : 'var(--ds-text-secondary)'};">
                    ${status === 'running' ? '✓ Aktif' : 'Durduruldu'}
                </span>
                ${status !== 'running' ? `<a href="#" data-action="start" data-bot-id="${botId}" data-account-id="${accountId}" style="font-size: 0.8rem; color: var(--ds-accent, #f0b90b);">Yeniden başlat</a>` : ''}
                <button class="btn btn-sm" style="flex: 1; background: var(--ds-bg-tertiary, #2b3139); color: var(--ds-text-primary); font-weight: 500; padding: 8px;" data-action="edit" data-bot-id="${botId}" data-account-id="${accountId}">
                    Parametreler
                </button>
            </div>
        `;
        
        // Hover effect
        card.onmouseenter = () => {
            card.style.borderColor = 'var(--ds-accent, #f0b90b)';
            card.style.transform = 'translateY(-2px)';
        };
        card.onmouseleave = () => {
            card.style.borderColor = 'var(--ds-border, #2b3139)';
            card.style.transform = 'translateY(0)';
        };
        
        // Yeniden başlat linki (sadece durdurulmuş botlarda görünür)
        const startLink = card.querySelector('[data-action="start"]');
        if (startLink) {
            startLink.onclick = async (e) => {
                e.preventDefault();
                e.stopPropagation();
                if (status === 'running') {
                    if (window.Toast) window.Toast.info("Bot zaten çalışıyor");
                    return;
                }
                var cfg = bot.config || {};
                var dn = (bot.bot_code ? '#' + bot.bot_code : null) || (symbol === 'MULTI' ? ('#' + botId) : symbol);
                await startBotFromCreateTab(botId, accountId, symbol, dn);
            };
        }
        
        // Edit button - opens parameter modal
        const editBtn = card.querySelector('[data-action="edit"]');
        if (editBtn) {
            editBtn.onclick = async (e) => {
                e.stopPropagation();
                await openBotParameterModal(botId, accountId);
            };
        }
        
        // Card click - opens parameter modal
        card.onclick = (e) => {
            if (!e.target.closest('button')) {
                openBotParameterModal(botId, accountId);
            }
        };
        
        container.appendChild(card);
    });
}

/**
 * Start bot from Create tab
 */
async function startBotFromCreateTab(botId, accountId, symbol, displayName) {
    if (!State.accountId) {
        showError("Hesap ID bulunamadı");
        return;
    }
    var botLabel = displayName || (symbol === 'MULTI' ? ('#' + botId) : symbol) || ('#' + botId);
    try {
        // bots-engine inserts command so worker picks up the bot
        const data = await window.apiClient.post(`/api/bots-engine/${botId}/start?account_id=${accountId}`);
        
        if (window.Toast) {
            window.Toast.success('Bot ' + botLabel + ' başlatıldı');
        }
        
        // Refresh bot list
        await loadSummary(State.accountId);
        renderCreateTabBotsList();
    } catch (error) {
        console.error("[dashboard] Start bot error:", error);
        if (window.errorReporter) {
            window.errorReporter.report(error, { tab: 'create', bot_id: botId, account_id: accountId, action: 'startBot' });
            window.errorReporter.show(error, { tab: 'create', bot_id: botId, account_id: accountId });
        } else {
            const msg = error.message || "Bilinmeyen hata";
            showError(`Bot başlatılamadı: ${msg}`);
        }
    }
}

/**
 * Open bot parameter modal (loads bot config and shows in create modal)
 */
async function openBotParameterModal(botId, accountId) {
    try {
        // REFACTOR: Use apiClient to get bot detail
        // Use /bots/{bot_id}/detail endpoint which returns full bot config
        const botDetail = await window.apiClient.get(`/api/bots/${botId}/detail?account_id=${accountId}`);
        
        // Parse config from botDetail response
        // The /bots/{bot_id}/detail endpoint returns config in various formats
        let config = {};
        try {
            // Try direct config_json field
            if (botDetail.config_json) {
                config = typeof botDetail.config_json === 'string' 
                    ? JSON.parse(botDetail.config_json) 
                    : botDetail.config_json;
            } 
            // Try config field
            else if (botDetail.config) {
                config = typeof botDetail.config === 'string'
                    ? JSON.parse(botDetail.config)
                    : botDetail.config;
            }
            // Try extracting from botDetail structure (dashboard_bot_detail format)
            else if (botDetail.bot && botDetail.bot.config_json) {
                const botConfigJson = botDetail.bot.config_json;
                config = typeof botConfigJson === 'string' 
                    ? JSON.parse(botConfigJson) 
                    : botConfigJson;
            }
            // Try to reconstruct from detail fields
            else {
                // Extract from detail structure
                config = {
                    budget_usd: botDetail.budget_usd || botDetail.initial_usd || 0,
                    allocation: {
                        base_pct: botDetail.base_pct || 50,
                        quote_pct: botDetail.quote_pct || 50
                    },
                    up: {
                        trail_pct: botDetail.up_trail_pct || 0.30,
                        grids: botDetail.up_grids || []
                    },
                    down: {
                        trail_pct: botDetail.down_trail_pct || 0.30,
                        grids: botDetail.down_grids || []
                    },
                    profit: {
                        rebuy_trigger_pct: botDetail.rebuy_trigger_pct || 0,
                        rebuy_trail_pct: botDetail.rebuy_trail_pct || 0,
                        resell_trigger_pct: botDetail.resell_trigger_pct || 0,
                        resell_trail_pct: botDetail.resell_trail_pct || 0
                    }
                };
            }
        } catch (e) {
            console.warn("[dashboard] Failed to parse bot config:", e);
            // Fallback: use botDetail fields directly
            config = {
                budget_usd: botDetail.budget_usd || botDetail.initial_usd || 0,
                allocation: { base_pct: 50, quote_pct: 50 },
                up: { trail_pct: 0.30, grids: [] },
                down: { trail_pct: 0.30, grids: [] },
                profit: {}
            };
        }
        
        // Fill form with bot config
        fillCreateModalWithBotConfig(botId, accountId, botDetail, config);
        
        // Set edit mode
        createModalEditMode = { botId, accountId, isEdit: true };
        
        // Open modal
        openCreateBotModal(botId, accountId);
        
        // Show start button instead of create
        const submitBtn = document.getElementById("dmSubmitBtn");
        if (submitBtn) {
            const status = (botDetail.status || 'stopped').toLowerCase();
            if (status === 'running') {
                submitBtn.textContent = "✓ Çalışıyor";
                submitBtn.disabled = true;
                submitBtn.style.opacity = "0.6";
            } else {
                submitBtn.textContent = "Botu Başlat";
                submitBtn.disabled = false;
                submitBtn.style.opacity = "1";
                submitBtn.onclick = async () => {
                    var dn = (botDetail.bot_code ? '#' + botDetail.bot_code : null) || (botDetail.symbol === 'MULTI' ? ('#' + botId) : (botDetail.symbol || ''));
                    await startBotFromCreateTab(botId, accountId, botDetail.symbol || '', dn);
                    closeCreateBotModal();
                };
            }
        }
    } catch (error) {
        console.error("[dashboard] Load bot detail error:", error);
        if (window.errorReporter) {
            window.errorReporter.report(error, { tab: 'create', bot_id: botId, account_id: accountId, action: 'openBotParameterModal' });
            window.errorReporter.show(error, { tab: 'create', bot_id: botId, account_id: accountId });
        } else {
            showError(`Bot bilgileri yüklenemedi: ${error.message}`);
        }
    }
}

/**
 * Fill create modal with existing bot config
 */
function fillCreateModalWithBotConfig(botId, accountId, botDetail, config) {
    // Symbol
    const symbolEl = document.getElementById("fSymbol");
    if (symbolEl) {
        symbolEl.value = botDetail.symbol || '';
        symbolEl.readOnly = true; // Prevent editing symbol when viewing existing bot
    }
    
    // Budget
    const budgetEl = document.getElementById("fBudget");
    if (budgetEl) {
        const budget = config.budget_usd || botDetail.budget_usd || botDetail.initial_usd || 0;
        budgetEl.value = budget;
        budgetEl.readOnly = true; // Prevent editing budget when viewing existing bot
    }
    
    // Allocation
    const allocation = config.allocation || {};
    const basePctEl = document.getElementById("fBasePct");
    if (basePctEl) {
        basePctEl.value = allocation.base_pct || 50;
        basePctEl.readOnly = true; // Prevent editing allocation when viewing existing bot
    }
    
    const quotePctEl = document.getElementById("fQuotePct");
    if (quotePctEl) {
        quotePctEl.value = allocation.quote_pct || 50;
        quotePctEl.readOnly = true; // Prevent editing allocation when viewing existing bot
    }
    
    // Up grid
    const upCfg = config.up || {};
    const upCountEl = document.getElementById("fUpCount");
    if (upCountEl) {
        const upGrids = upCfg.grids || botDetail.up_grids || [];
        upCountEl.value = upGrids.length;
        upCountEl.readOnly = true; // Prevent editing grids when viewing existing bot
    }
    
    const upTrailEl = document.getElementById("fUpTrail");
    if (upTrailEl) {
        upTrailEl.value = upCfg.trail_pct ?? botDetail.up_trail_pct ?? 0.5;
        upTrailEl.readOnly = true;
    }
    
    // Down grid
    const downCfg = config.down || {};
    const downCountEl = document.getElementById("fDownCount");
    if (downCountEl) {
        const downGrids = downCfg.grids || botDetail.down_grids || [];
        downCountEl.value = downGrids.length;
        downCountEl.readOnly = true;
    }
    
    const downTrailEl = document.getElementById("fDownTrail");
    if (downTrailEl) {
        downTrailEl.value = downCfg.trail_pct ?? botDetail.down_trail_pct ?? 0.5;
        downTrailEl.readOnly = true;
    }
    
    // Profit config
    const profitCfg = config.profit || {};
    const rebuyTriggerEl = document.getElementById("fRebuyTrigger");
    if (rebuyTriggerEl) {
        rebuyTriggerEl.value = profitCfg.rebuy_trigger_pct ?? botDetail.rebuy_trigger_pct ?? 1.5;
        rebuyTriggerEl.readOnly = true;
    }
    
    const rebuyTrailEl = document.getElementById("fRebuyTrail");
    if (rebuyTrailEl) {
        rebuyTrailEl.value = profitCfg.rebuy_trail_pct ?? botDetail.rebuy_trail_pct ?? 0.30;
        rebuyTrailEl.readOnly = true;
    }
    
    const resellTriggerEl = document.getElementById("fResellTrigger");
    if (resellTriggerEl) {
        resellTriggerEl.value = profitCfg.resell_trigger_pct ?? botDetail.resell_trigger_pct ?? 1.5;
        resellTriggerEl.readOnly = true;
    }
    
    const resellTrailEl = document.getElementById("fResellTrail");
    if (resellTrailEl) {
        resellTrailEl.value = profitCfg.resell_trail_pct ?? botDetail.resell_trail_pct ?? 0.5;
        resellTrailEl.readOnly = true;
    }
    
    // Update modal title
    const titleEl = document.querySelector(".dm-modal__title");
    if (titleEl) {
        titleEl.textContent = `Bot Parametreleri - ${botDetail.symbol || 'N/A'}`;
    }
    
    // Strip + tahmin: parite bilgisini göster
    if (botDetail.symbol) updateCreateBotModalPairStrip(botDetail.symbol);
    
    // Show info message that this is view-only
    const errorEl = document.getElementById("createBotError");
    if (errorEl) {
        errorEl.style.display = "block";
        errorEl.style.color = "var(--ds-text-secondary)";
        errorEl.textContent = "Bu botun parametrelerini görüntülüyorsunuz. Parametreleri değiştirmek için botu durdurup yeni bot oluşturmanız gerekir.";
    }
}

// Shared password validation (settings form + must-change-password modal)
function dashboardValidatePassword(password, name, surname) {
    if (password.length < 10) return { valid: false, msg: 'Şifre en az 10 karakter olmalıdır' };
    if (!/[A-Z]/.test(password)) return { valid: false, msg: 'Şifre en az 1 büyük harf içermelidir' };
    if (!/[a-z]/.test(password)) return { valid: false, msg: 'Şifre en az 1 küçük harf içermelidir' };
    if (!/[0-9]/.test(password)) return { valid: false, msg: 'Şifre en az 1 rakam içermelidir' };
    if (!/[.,!?;:]/.test(password)) return { valid: false, msg: 'Şifre en az 1 noktalama işareti (.,!?;:) içermelidir' };
    const passLower = password.toLowerCase();
    if (name && name.toLowerCase().length >= 3 && passLower.includes(name.toLowerCase())) return { valid: false, msg: 'Şifre isminizi içeremez' };
    if (surname && surname.toLowerCase().length >= 3 && passLower.includes(surname.toLowerCase())) return { valid: false, msg: 'Şifre soyadınızı içeremez' };
    const weak = ['password', '123456', 'qwerty', 'abc123', 'password123', 'admin', 'welcome'];
    if (weak.includes(passLower)) return { valid: false, msg: 'Bu şifre çok zayıf, lütfen daha güçlü bir şifre seçin' };
    const obvious = ['12345', '23456', '34567', '45678', '56789', '67890', 'abcdef', 'qwerty', 'asdfgh', 'zxcvbn'];
    if (obvious.some(seq => passLower.includes(seq))) return { valid: false, msg: 'Şifre çok belirgin sıralı karakterler içeremez' };
    return { valid: true, msg: '✓ Şifre güçlü görünüyor' };
}

// Desktop tab -> mobil alt sekme: yenilemede aynı yerde kalsın
function desktopTabToMobileTab(desktopTab) {
    if (!desktopTab) return "home";
    var map = { binance: "home", reports: "home", finance: "portfoy", trade: "trade", bots: "bots", settings: "ayarlar", contact: "portfoy" };
    return map[desktopTab] || "home";
}

// Mobil sekme değişince desktop tab + localStorage senkronize (yenilemede doğru sekme kalsın)
function mobileTabToDesktopTab(mobileTab) {
    if (!mobileTab) return "binance";
    var map = { home: "binance", portfoy: "finance", trade: "trade", bots: "bots", ayarlar: "settings" };
    return map[mobileTab] || "binance";
}
function setDesktopTabActiveWithoutClick(desktopTabName) {
    var btn = document.querySelector('.dm-tab[data-tab="' + desktopTabName + '"]');
    if (!btn) return;
    document.querySelectorAll('.dm-tab').forEach(function (t) { t.classList.remove('is-active'); });
    btn.classList.add('is-active');
    try { localStorage.setItem('dashboard_active_tab', desktopTabName); } catch (_) {}
    if (history.replaceState) {
        var q = new URLSearchParams(window.location.search);
        q.set('tab', desktopTabName);
        history.replaceState(null, '', window.location.pathname + '?' + q.toString() + (window.location.hash || ''));
    }
}

// Mobil alt çubuk: Home | Markets | Trade | Botlar | Ayarlar
function initMobileBottomNav(currentDesktopTab) {
    const nav = document.getElementById("mobileBottomNav");
    if (!nav) return;
    const items = nav.querySelectorAll(".mobile-nav-item");
    const body = document.body;
    const TAB_CLASSES = ["mobile-tab-home", "mobile-tab-portfoy", "mobile-tab-trade", "mobile-tab-bots", "mobile-tab-ayarlar"];

    var _mobileTabInProgress = false;
    function setMobileTab(tab) {
        if (!tab) return;
        if (body.classList.contains("mobile-tab-" + tab)) return; // Zaten bu sekmede, tekrar işlem yapma (donma önlemi)
        if (_mobileTabInProgress) return;
        _mobileTabInProgress = true;
        requestAnimationFrame(function () {
            try {
                setMobileTabInner(tab);
            } finally {
                _mobileTabInProgress = false;
            }
        });
    }
    function setMobileTabInner(tab) {
        // Mobilde sekme geçişinde biriken interval'ları durdur (donma önlemi)
        if (window.intervalRegistry) {
            window.intervalRegistry.stopByOwner("binanceTab");
            window.intervalRegistry.stopByOwner("tab.varliklar");
            window.intervalRegistry.stopByOwner("tab.coinlist");
            window.intervalRegistry.stopByOwner("tab.list");
            window.intervalRegistry.stopByOwner("tab.reports");
            window.intervalRegistry.stopByOwner("tab.finance");
            window.intervalRegistry.stopByOwner("tab.bots");
            window.intervalRegistry.stopByOwner("tab.settings");
        }

        items.forEach(i => {
            i.classList.toggle("is-active", i.getAttribute("data-mobile-tab") === tab);
        });
        TAB_CLASSES.forEach(c => body.classList.remove(c));
        body.classList.add("mobile-tab-" + tab);

        const unifiedStrip = document.getElementById("unifiedKpiStrip");
        if (unifiedStrip) {
            const showStrip = tab === "home" || tab === "portfoy" || tab === "trade";
            unifiedStrip.classList.toggle("kpi-strip-hidden", !showStrip);
            if (showStrip) unifiedStrip.style.removeProperty("display");
            else unifiedStrip.style.display = "none";
            unifiedStrip.classList.remove("unified-kpi-bots-only");
        }
        updateBinanceConnectionNotice();

        document.body.classList.remove("tab-finance-active", "tab-contact-active", "tab-settings-active", "tab-trade-active", "tab-bots-active");
        if (tab === "home") {
            setDesktopTabActiveWithoutClick("binance");
            document.querySelectorAll(".dm-tab-content").forEach(c => { c.classList.remove("is-active"); c.style.display = "none"; });
            const tabBinance = document.getElementById("tabBinance");
            if (tabBinance) { tabBinance.classList.add("is-active"); tabBinance.style.display = "block"; }
            var txPanel = document.getElementById("transactionHistoryPanel");
            if (txPanel) txPanel.style.display = "block";
            if (typeof window.syncBootWalletToAssetsState === "function") window.syncBootWalletToAssetsState();
            if (window.BinanceAssetsPanel && typeof window.BinanceAssetsPanel.render === "function") window.BinanceAssetsPanel.render();
            if (typeof renderVarliklarList === "function") renderVarliklarList();
        } else if (tab === "portfoy") {
            setDesktopTabActiveWithoutClick("finance");
            document.body.classList.add("tab-finance-active");
            document.querySelectorAll(".dm-tab-content").forEach(c => { c.classList.remove("is-active"); c.style.display = "none"; });
            const tabFinance = document.getElementById("tabFinance");
            if (tabFinance) { tabFinance.classList.add("is-active"); tabFinance.style.display = "block"; }
            if (typeof initFinanceTab === "function") initFinanceTab();
        } else if (tab === "trade") {
            setDesktopTabActiveWithoutClick("trade");
            document.body.classList.add("tab-trade-active");
            document.querySelectorAll(".dm-tab-content").forEach(c => { c.classList.remove("is-active"); c.style.display = "none"; });
            var mobileTradeEl = document.getElementById("mobileTradeView");
            if (mobileTradeEl) { mobileTradeEl.classList.add("is-active"); mobileTradeEl.style.display = "block"; }
            initMobileTradeSearch();
            if (typeof getFavoritesStorageKey === "function" && getFavoritesStorageKey() && typeof loadSpotFavoritesFromStorage === "function") {
                loadSpotFavoritesFromStorage().then(function () { if (typeof renderMobileTradeFavorites === "function") renderMobileTradeFavorites(); }).catch(function () { if (typeof renderMobileTradeFavorites === "function") renderMobileTradeFavorites(); });
            } else {
                if (typeof renderMobileTradeFavorites === "function") renderMobileTradeFavorites();
            }
            if (typeof startMobileTradeFavPriceUpdates === "function") startMobileTradeFavPriceUpdates();
        } else if (tab === "bots") {
            document.body.classList.add("tab-bots-active");
            document.querySelectorAll(".dm-tab-content").forEach(function (c) { c.classList.remove("is-active"); c.style.display = "none"; });
            var tabBotsEl = document.getElementById("tabBots");
            if (tabBotsEl) { tabBotsEl.classList.add("is-active"); tabBotsEl.style.display = "block"; }
            setDesktopTabActiveWithoutClick("bots");
            if (typeof activateBotsTab === "function") activateBotsTab();
        } else if (tab === "ayarlar") {
            setDesktopTabActiveWithoutClick("settings");
            document.body.classList.add("tab-settings-active");
            document.querySelectorAll(".dm-tab-content").forEach(c => { c.classList.remove("is-active"); c.style.display = "none"; });
            const tabSettings = document.getElementById("tabSettings");
            if (tabSettings) { tabSettings.classList.add("is-active"); tabSettings.style.display = "block"; }
            if (typeof initSettingsTab === "function") initSettingsTab();
        }
    }

    items.forEach(btn => {
        btn.onclick = function () {
            const tab = this.getAttribute("data-mobile-tab");
            if (!tab) return;
            setMobileTab(tab);
        };
    });

    function syncFromDesktop() {
        if (window.innerWidth > 768) {
            TAB_CLASSES.forEach(c => body.classList.remove(c));
            return;
        }
        var mobileTab = desktopTabToMobileTab(currentDesktopTab);
        setMobileTab(mobileTab);
    }

    var resizeThrottled = throttle(function () {
        if (window.innerWidth > 768) TAB_CLASSES.forEach(c => body.classList.remove(c));
    }, 150);
    window.addEventListener("resize", resizeThrottled, { passive: true });
    syncFromDesktop();
}

// Mobil Trade sekmesi: coin ara, seçince alım satım modalı aç
var _mobileTradeSearchBound = false;
var _mobileTradeSearchPriceGen = 0;
function initMobileTradeSearch() {
    var input = document.getElementById("mobileTradeSearchInput");
    var dropdown = document.getElementById("mobileTradeSearchDropdown");
    var wrap = input ? input.closest(".coin-list-search-wrap") : null;
    if (!input || !dropdown) return;

    function fillDropdown() {
        var q = (input.value || "").trim().toUpperCase();
        if (!q) {
            dropdown.style.display = "none";
            return;
        }
        var list = (typeof filterCoinListForSearch === "function")
            ? filterCoinListForSearch(input.value, 50)
            : [];
        dropdown.innerHTML = list.map(function (item) {
            return renderCoinSearchDropdownItemHtml(item, "mobile-trade-search-item");
        }).join("");
        dropdown.style.display = list.length ? "block" : "none";
        if (list.length > 0 && typeof queueCoinSearchPriceFetch === "function") {
            var gen = ++_mobileTradeSearchPriceGen;
            queueCoinSearchPriceFetch(list.map(function (it) { return it.symbol; }), function () {
                if (gen !== _mobileTradeSearchPriceGen) return;
                if (!(input.value || "").trim()) return;
                fillDropdown();
            });
        }
    }

    if (!_mobileTradeSearchBound) {
        _mobileTradeSearchBound = true;
        input.oninput = fillDropdown;
        input.onclick = function () {
            input.focus();
            ensureCoinListSearchSymbolsLoaded("all").then(function () {
                buildCoinListSearchSymbols();
                if ((input.value || "").trim()) fillDropdown();
            });
        };
        if (wrap) {
            wrap.addEventListener("click", function (e) {
                if (e.target === dropdown || e.target.closest(".mobile-trade-search-item")) return;
                input.focus();
            });
        }
        input.onfocus = function () {
            ensureCoinListSearchSymbolsLoaded("all").then(function () { buildCoinListSearchSymbols(); if ((input.value || "").trim()) fillDropdown(); });
        };
        input.onkeydown = function (e) {
            if (e.key === "Escape") {
                dropdown.style.display = "none";
                return;
            }
            if (e.key === "Enter") {
                var first = dropdown.querySelector(".mobile-trade-search-item");
                if (first) {
                    e.preventDefault();
                    var sym = first.getAttribute("data-symbol");
                    if (sym && typeof openSpotTradeModal === "function") {
                        openSpotTradeModal(sym);
                        input.value = "";
                        dropdown.style.display = "none";
                    }
                }
            }
        };
        input.onblur = function () { setTimeout(function () { dropdown.style.display = "none"; }, 180); };
        dropdown.onmousedown = function (e) { e.preventDefault(); };
        dropdown.addEventListener("click", function (e) {
            var item = e.target.closest(".mobile-trade-search-item");
            if (!item) return;
            var symbol = item.getAttribute("data-symbol");
            if (symbol && typeof openSpotTradeModal === "function") {
                openSpotTradeModal(symbol);
                input.value = "";
                dropdown.style.display = "none";
            }
        });
    }

    ensureCoinListSearchSymbolsLoaded("all").then(function () { buildCoinListSearchSymbols(); fillDropdown(); });
}

var MOBILE_TRADE_FAV_TICKER_CACHE_KEY = "mobileTradeFavTicker_v1";
var _mobileTradeFavBatchInflight = null;
var _mobileTradeFavStoreSub = null;

function _readMobileTradeFavTickerCache() {
    try {
        var raw = sessionStorage.getItem(MOBILE_TRADE_FAV_TICKER_CACHE_KEY);
        return raw ? JSON.parse(raw) : {};
    } catch (e) {
        return {};
    }
}

function _writeMobileTradeFavTickerCache(symbol, price, changePct) {
    try {
        var sym = (symbol || "").toUpperCase();
        if (!sym || price == null || !Number.isFinite(price)) return;
        var cache = _readMobileTradeFavTickerCache();
        cache[sym] = { price: price, changePct: changePct, ts: Date.now() };
        sessionStorage.setItem(MOBILE_TRADE_FAV_TICKER_CACHE_KEY, JSON.stringify(cache));
    } catch (e) {}
}

function _fmtMobileTradeFavPriceDisplay(price, symbol) {
    return formatCoinSearchItemPrice(symbol, price);
}

function _applyMobileTradeFavItemQuote(symbol, price, changePct) {
    if (price == null || !Number.isFinite(price) || price <= 0) return;
    var sym = (symbol || "").toUpperCase();
    var item = document.querySelector('#mobileTradeFavoritesList .mobile-trade-fav-item[data-symbol="' + sym + '"]');
    if (!item) return;
    var priceRow = item.querySelector(".mobile-trade-fav-price-row");
    var changeSpan = item.querySelector(".mobile-trade-fav-change");
    if (!priceRow || !changeSpan) return;
    var oldPrice = parseFloat(priceRow.getAttribute("data-price") || "") || 0;
    var priceDisplay = _fmtMobileTradeFavPriceDisplay(price, sym);
    var changeStr = changePct != null && Number.isFinite(changePct)
        ? (changePct >= 0 ? "+" : "") + Number(changePct).toFixed(2) + "%"
        : "—";
    var changeColor = changePct != null && Number.isFinite(changePct)
        ? (changePct >= 0 ? "#0ecb81" : "#f6465d")
        : "var(--ds-text-secondary)";
    priceRow.setAttribute("data-price", price);
    priceRow.setAttribute("data-change-pct", changePct != null && Number.isFinite(changePct) ? changePct : "");
    var priceVal = priceRow.querySelector(".mobile-trade-fav-price-val");
    if (priceVal) priceVal.textContent = priceDisplay;
    changeSpan.textContent = changeStr;
    changeSpan.style.color = changeColor;
    _writeMobileTradeFavTickerCache(sym, price, changePct);
    if (Number.isFinite(oldPrice) && oldPrice > 0 && Math.abs(oldPrice - price) > 0.0001) {
        priceRow.classList.remove("mobile-trade-fav-price-blink-up", "mobile-trade-fav-price-blink-down");
        priceRow.classList.add(price > oldPrice ? "mobile-trade-fav-price-blink-up" : "mobile-trade-fav-price-blink-down");
        setTimeout(function () {
            priceRow.classList.remove("mobile-trade-fav-price-blink-up", "mobile-trade-fav-price-blink-down");
        }, 700);
    }
}

function _parseDataPricesPayload(res) {
    if (!res || typeof res !== "object") return {};
    if (res.prices && typeof res.prices === "object") return res.prices;
    if (res.data && typeof res.data === "object") {
        if (res.data.prices && typeof res.data.prices === "object") return res.data.prices;
        return res.data;
    }
    return res;
}

function _updateCoinSearchSymbolQuote(symbol, price, changePct) {
    var sym = (symbol || "").toUpperCase();
    if (!sym || price == null || !Number.isFinite(price) || price <= 0) return;
    if (window.marketStore && window.marketStore.updateMini) {
        window.marketStore.updateMini(sym, { last: price, changePct: changePct });
    }
    if (typeof coinListSearchAllSymbols !== "undefined" && Array.isArray(coinListSearchAllSymbols)) {
        for (var i = 0; i < coinListSearchAllSymbols.length; i++) {
            if ((coinListSearchAllSymbols[i].symbol || "").toUpperCase() === sym) {
                coinListSearchAllSymbols[i].last = price;
                if (changePct != null && Number.isFinite(changePct)) {
                    coinListSearchAllSymbols[i].changePct = changePct;
                }
                return;
            }
        }
        coinListSearchAllSymbols.push({ symbol: sym, last: price, changePct: changePct });
    }
}

function _getSymbolSearchQuote(symbol) {
    var sym = (symbol || "").toUpperCase();
    var mini = window.marketStore && window.marketStore.getMini && window.marketStore.getMini(sym);
    if (mini && mini.last != null && Number.isFinite(mini.last) && mini.last > 0) {
        return { price: mini.last, changePct: Number.isFinite(mini.changePct) ? mini.changePct : null };
    }
    var storePrice = window.marketStore && window.marketStore.getPrice && window.marketStore.getPrice(sym);
    if (storePrice != null && Number.isFinite(storePrice) && storePrice > 0) {
        return { price: storePrice, changePct: null };
    }
    if (typeof coinListSearchAllSymbols !== "undefined" && Array.isArray(coinListSearchAllSymbols)) {
        for (var i = 0; i < coinListSearchAllSymbols.length; i++) {
            var row = coinListSearchAllSymbols[i];
            if ((row.symbol || "").toUpperCase() === sym && row.last != null && Number.isFinite(row.last) && row.last > 0) {
                return {
                    price: row.last,
                    changePct: row.changePct != null && Number.isFinite(row.changePct) ? row.changePct : null
                };
            }
        }
    }
    var cached = _readMobileTradeFavTickerCache()[sym];
    if (cached && cached.price != null && Number.isFinite(cached.price) && cached.price > 0) {
        return {
            price: cached.price,
            changePct: cached.changePct != null && Number.isFinite(cached.changePct) ? cached.changePct : null
        };
    }
    return { price: null, changePct: null };
}

function formatCoinSearchItemPrice(symbol, price) {
    if (price == null || !Number.isFinite(Number(price)) || Number(price) <= 0) return "—";
    if (typeof formatModalPriceForSymbol === "function") {
        return formatModalPriceForSymbol(Number(price), symbol);
    }
    var pq = typeof parseTradingPairSymbol === "function" ? parseTradingPairSymbol(symbol) : null;
    if (pq && pq.valid && pq.quote) {
        var q = pq.quote;
        if (q === "USDT" || q === "FDUSD" || q === "BUSD" || q === "USDC") {
            return typeof fmtCoinPrice === "function" ? fmtCoinPrice(Number(price)) : ("$" + price);
        }
        if (q === "BTC") return fmtNum(price, 8) + " BTC";
        if (q === "ETH") return fmtNum(price, 6) + " ETH";
        if (q === "BNB") return fmtNum(price, 4) + " BNB";
        return fmtNum(price, 8) + " " + q;
    }
    return typeof fmtCoinPrice === "function" ? fmtCoinPrice(Number(price)) : ("$" + price);
}

function renderCoinSearchDropdownItemHtml(item, itemClass) {
    var sym = item.symbol || "";
    var label = typeof formatTradingPairDisplay === "function" ? formatTradingPairDisplay(sym) : sym;
    var pct = item.changePct != null && Number.isFinite(item.changePct) ? item.changePct : null;
    var pctStr = pct != null ? (pct >= 0 ? "+" : "") + pct.toFixed(2) + "%" : "—";
    var pctColor = pct != null ? (pct >= 0 ? "#0ecb81" : "#f6465d") : "var(--ds-text-secondary)";
    var priceStr = formatCoinSearchItemPrice(sym, item.last);
    var cls = "coin-list-search-item" + (itemClass ? " " + itemClass : "");
    return "<div class=\"" + cls + "\" data-symbol=\"" + sym + "\" style=\"padding: 0.6rem 1rem; cursor: pointer; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--ds-border);\"><span style=\"font-weight: 600;\">" + label + "</span><span style=\"display: flex; gap: 0.5rem; align-items: center;\"><span style=\"color: var(--ds-text-secondary);\">" + priceStr + "</span><span style=\"color: " + pctColor + "\">" + pctStr + "</span></span></div>";
}

var _coinSearchPriceFetchInflight = null;
var _coinSearchPricePending = [];
var _coinSearchPriceTimer = null;

function _fetchCoinSearchTickerFallback(symbol) {
    return fetch(window.location.origin + "/api/spot/ticker_24h?symbol=" + encodeURIComponent(symbol))
        .then(function (r) { return r.json(); })
        .then(function (data) {
            var price = parseFloat(data.lastPrice || data.weightedAvgPrice || 0);
            var changePct = parseFloat(data.priceChangePercent || 0);
            if (price > 0 && Number.isFinite(price)) {
                var pct = Number.isFinite(changePct) ? changePct : null;
                _updateCoinSearchSymbolQuote(symbol, price, pct);
                _writeMobileTradeFavTickerCache(symbol, price, pct);
                return { symbol: symbol, price: price, changePct: pct };
            }
            return null;
        })
        .catch(function () { return null; });
}

function fetchCoinSearchPricesBatch(symbols, opts) {
    opts = opts || {};
    var seen = {};
    symbols = (symbols || []).map(function (s) { return (s || "").toUpperCase(); }).filter(function (s) {
        if (!s || seen[s]) return false;
        seen[s] = true;
        return true;
    });
    if (!symbols.length) return Promise.resolve();
    var missing = [];
    symbols.forEach(function (sym) {
        var q = _getSymbolSearchQuote(sym);
        if (q.price != null && q.price > 0) {
            _updateCoinSearchSymbolQuote(sym, q.price, q.changePct);
            if (opts.onEach) opts.onEach(sym, q.price, q.changePct);
        } else {
            missing.push(sym);
        }
    });
    if (!missing.length) {
        if (opts.onUpdated) opts.onUpdated();
        return Promise.resolve();
    }
    if (!window.apiClient || typeof window.apiClient.get !== "function") {
        return Promise.all(missing.map(_fetchCoinSearchTickerFallback)).then(function () {
            if (opts.onUpdated) opts.onUpdated();
        });
    }
    var run = function () {
        return window.apiClient
            .get("/api/data/prices?slim=1&symbols=" + encodeURIComponent(missing.join(",")))
            .then(function (res) {
                var prices = _parseDataPricesPayload(res);
                var stillMissing = [];
                missing.forEach(function (sym) {
                    var row = prices[sym];
                    var price = row && row.price != null ? Number(row.price) : NaN;
                    var changePct = row && row.change24h != null ? Number(row.change24h) : null;
                    if (price > 0 && Number.isFinite(price)) {
                        var pct = Number.isFinite(changePct) ? changePct : null;
                        _updateCoinSearchSymbolQuote(sym, price, pct);
                        _writeMobileTradeFavTickerCache(sym, price, pct);
                        if (opts.onEach) opts.onEach(sym, price, pct);
                    } else {
                        stillMissing.push(sym);
                    }
                });
                return Promise.all(stillMissing.map(_fetchCoinSearchTickerFallback));
            })
            .catch(function () {
                return Promise.all(missing.map(_fetchCoinSearchTickerFallback));
            })
            .then(function () {
                if (opts.onUpdated) opts.onUpdated();
            });
    };
    if (_coinSearchPriceFetchInflight) {
        return _coinSearchPriceFetchInflight.then(run);
    }
    _coinSearchPriceFetchInflight = run().finally(function () {
        _coinSearchPriceFetchInflight = null;
    });
    return _coinSearchPriceFetchInflight;
}

function queueCoinSearchPriceFetch(symbols, onUpdated) {
    (symbols || []).forEach(function (s) {
        var u = (s || "").toUpperCase();
        if (u && _coinSearchPricePending.indexOf(u) === -1) _coinSearchPricePending.push(u);
    });
    if (_coinSearchPriceTimer) clearTimeout(_coinSearchPriceTimer);
    _coinSearchPriceTimer = setTimeout(function () {
        _coinSearchPriceTimer = null;
        var batch = _coinSearchPricePending.slice();
        _coinSearchPricePending = [];
        fetchCoinSearchPricesBatch(batch, { onUpdated: onUpdated });
    }, 150);
}

function _getMobileTradeFavQuote(symbol) {
    return _getSymbolSearchQuote(symbol);
}

function _fetchMobileTradeFavTickerFallback(symbol) {
    return _fetchCoinSearchTickerFallback(symbol).then(function (row) {
        if (row && row.price > 0) {
            _applyMobileTradeFavItemQuote(symbol, row.price, row.changePct);
        }
    });
}

function fetchMobileTradeFavPricesBatch(symbols) {
    return fetchCoinSearchPricesBatch(symbols, {
        onEach: function (sym, price, changePct) {
            _applyMobileTradeFavItemQuote(sym, price, changePct);
        }
    });
}

function prefetchMobileTradeFavTickerCache() {
    var favs = (typeof spotFavorites !== "undefined" && Array.isArray(spotFavorites)) ? spotFavorites.slice() : [];
    if (!favs.length) return;
    fetchMobileTradeFavPricesBatch(favs);
}

function refreshMobileTradeFavPricesFromStore() {
    var items = document.querySelectorAll("#mobileTradeFavoritesList .mobile-trade-fav-item");
    if (!items.length) return;
    items.forEach(function (item) {
        var sym = item.getAttribute("data-symbol");
        if (!sym) return;
        var q = _getMobileTradeFavQuote(sym);
        if (q.price != null) _applyMobileTradeFavItemQuote(sym, q.price, q.changePct);
    });
}

function ensureMobileTradeFavMarketStoreHook() {
    if (_mobileTradeFavStoreSub || !window.marketStore || typeof window.marketStore.subscribe !== "function") return;
    _mobileTradeFavStoreSub = window.marketStore.subscribe(function () {
        var view = document.getElementById("mobileTradeView");
        if (!view || !view.classList.contains("is-active")) return;
        refreshMobileTradeFavPricesFromStore();
    });
}

function startMobileTradeFavPriceUpdates() {
    ensureMobileTradeFavMarketStoreHook();
    if (window.intervalRegistry) {
        window.intervalRegistry.stopByOwner("tab.trade");
        tickMobileTradeFavoritesPrices();
        window.intervalRegistry.start("tab.trade.prices", tickMobileTradeFavoritesPrices, 2000, "tab.trade");
    }
}

// Mobil Trade: Favori coinler listesini doldur; tıklayınca alım satım modalı açılır
function renderMobileTradeFavorites() {
    var listEl = document.getElementById("mobileTradeFavoritesList");
    if (!listEl) return;
    try {
    var favs = (typeof spotFavorites !== "undefined" && Array.isArray(spotFavorites)) ? spotFavorites.slice() : [];
    if (favs.length === 0) {
        listEl.innerHTML = '<div style="padding: 1.5rem; text-align: center; color: var(--ds-text-secondary); font-size: 0.9rem;">Favori yok. Yukarıdaki arama çubuğunda coin arayıp seçin, alım satım ekranında yıldıza tıklayarak favorilere ekleyin.</div>';
        return;
    }
    var baseFromSymbol = function (sym) {
        var pq = parseTradingPairSymbol(sym);
        return pq.valid ? pq.base : sym;
    };
    var symbolDisplay = function (sym) {
        return formatTradingPairDisplay(sym);
    };
    var getLogoHtml = function (base) {
        if (!base || typeof getCoinLogoUrl !== "function") return '<span class="varlik-logo-initials" style="width:32px;height:32px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-size:0.7rem;font-weight:600;background:var(--ds-bg-tertiary);color:var(--ds-text-secondary);">' + (base || "").substring(0, 2).toUpperCase() + "</span>";
        var url = getCoinLogoUrl(base);
        var initials = (base || " ").substring(0, 2).toUpperCase();
        return url
            ? '<img src="' + url + '" alt="' + base + '" class="mobile-trade-fav-logo" style="width:32px;height:32px;border-radius:50%;object-fit:cover;" onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'flex\'" /><span class="varlik-logo-initials" style="display:none;width:32px;height:32px;border-radius:50%;align-items:center;justify-content:center;font-size:0.7rem;font-weight:600;background:var(--ds-bg-tertiary);color:var(--ds-text-secondary);">' + initials + "</span>"
            : '<span class="varlik-logo-initials" style="width:32px;height:32px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-size:0.7rem;font-weight:600;background:var(--ds-bg-tertiary);color:var(--ds-text-secondary);">' + initials + "</span>";
    };
    var html = favs.map(function (symbol) {
        var quote = _getMobileTradeFavQuote(symbol);
        var price = quote.price;
        var changePct = quote.changePct;
        var priceDisplay = _fmtMobileTradeFavPriceDisplay(price, symbol);
        var changeStr = changePct != null ? (changePct >= 0 ? "+" : "") + Number(changePct).toFixed(2) + "%" : "—";
        var changeColor = changePct != null ? (changePct >= 0 ? "#0ecb81" : "#f6465d") : "var(--ds-text-secondary)";
        var base = baseFromSymbol(symbol);
        var symbolLabel = symbolDisplay(symbol);
        return '<div class="mobile-trade-fav-item" data-symbol="' + symbol + '" role="button" tabindex="0">' +
            '<div class="mobile-trade-fav-logo-symbol">' +
            getLogoHtml(base) +
            '<span class="mobile-trade-fav-symbol" title="' + symbol + '">' + symbolLabel + '</span>' +
            '</div>' +
            '<div class="mobile-trade-fav-price-wrap">' +
            '<span class="mobile-trade-fav-price-row" data-price="' + (price != null && Number.isFinite(price) ? price : '') + '" data-change-pct="' + (changePct != null ? changePct : '') + '">' +
            '<span class="mobile-trade-fav-price-val">' + priceDisplay + '</span>' +
            '<span class="mobile-trade-fav-change" style="color:' + changeColor + '">' + changeStr + '</span>' +
            '</span></div>' +
            '<span class="mobile-trade-fav-spacer"></span>' +
            '<span class="mobile-trade-fav-action">Al / Sat</span>' +
            '</div>';
    }).join("");
    listEl.innerHTML = html;
    listEl.querySelectorAll(".mobile-trade-fav-item").forEach(function (el) {
        el.onclick = function () {
            var sym = el.getAttribute("data-symbol");
            if (sym && typeof openSpotTradeModal === "function") openSpotTradeModal(sym);
        };
        el.onkeydown = function (e) {
            if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                el.click();
            }
        };
    });
    var view = document.getElementById("mobileTradeView");
    if (view && view.classList.contains("is-active")) {
        fetchMobileTradeFavPricesBatch(favs);
    }
    } catch (err) {
        console.error("[dashboard] renderMobileTradeFavorites:", err);
        listEl.innerHTML = '<div style="padding: 1rem; color: var(--ds-danger); font-size: 0.9rem;">Favori listesi yüklenemedi. Sayfayı yenileyin.</div>';
    }
}

function tickMobileTradeFavoritesPrices() {
    var view = document.getElementById("mobileTradeView");
    if (!view || !view.classList.contains("is-active")) return;
    var items = document.querySelectorAll("#mobileTradeFavoritesList .mobile-trade-fav-item");
    if (items.length === 0) return;
    var symbols = [];
    items.forEach(function (item) {
        var sym = item.getAttribute("data-symbol");
        if (sym) symbols.push(sym);
    });
    fetchMobileTradeFavPricesBatch(symbols);
}

// Tabs
function bindTabs() {
    const tabs = document.querySelectorAll(".dm-tab");
    const contents = document.querySelectorAll(".dm-tab-content");
    
    console.log("[dashboard] bindTabs: Found", tabs.length, "tabs and", contents.length, "contents");
    
    if (tabs.length === 0) {
        console.error("[dashboard] bindTabs: No tabs found!");
        return;
    }
    
    tabs.forEach(tab => {
        // Remove any existing onclick handlers
        tab.onclick = null;
        
        // Use onclick instead of addEventListener for better compatibility
        tab.onclick = function(e) {
            try {
                e.preventDefault();
                e.stopPropagation();
                
                const targetTab = this.getAttribute("data-tab");
                console.log("[dashboard] Tab clicked:", targetTab, "Element:", this);
                
                if (!targetTab) {
                    console.error("[dashboard] Tab has no data-tab attribute:", this);
                    return;
                }
                
                // Re-query tabs and contents to ensure we have fresh references
                const allTabs = document.querySelectorAll(".dm-tab");
                const allContents = document.querySelectorAll(".dm-tab-content");
                
                // Update active states for all tabs
                allTabs.forEach(t => t.classList.remove("is-active"));
                allContents.forEach(c => { c.classList.remove("is-active"); c.style.display = "none"; });
                
                // Activate clicked tab
                this.classList.add("is-active");
                
                // Save active tab to localStorage ve URL – yenilemede aynı sekme kalsın
                localStorage.setItem('dashboard_active_tab', targetTab);
                if (history.replaceState) {
                    var q = new URLSearchParams(window.location.search);
                    q.set('tab', targetTab);
                    var newSearch = '?' + q.toString();
                    history.replaceState(null, '', window.location.pathname + newSearch + (window.location.hash || ''));
                }
                
                // Update Binance API banner visibility based on active tab
                updateBinanceApiBannerVisibility();
                // API bağlantı uyarısı: Anasayfa, Binance, Botlar sekmesinde göster (en üstte, tek blok)
                updateBinanceConnectionNotice();
                // Ortak KPI şeridi: Anasayfa, Trade; Botlar/Portföy/İletişim/Ayarlar’da gizle
                const unifiedStrip = document.getElementById('unifiedKpiStrip');
                if (unifiedStrip) {
                    const showStrip = (targetTab === 'reports' || targetTab === 'binance' || targetTab === 'trade');
                    unifiedStrip.classList.toggle('kpi-strip-hidden', !showStrip);
                    if (showStrip) unifiedStrip.style.removeProperty('display');
                    else unifiedStrip.style.display = 'none';
                    unifiedStrip.classList.remove('unified-kpi-bots-only');
                }
                
                // REFACTOR: Stop intervals from ALL tabs before switching (prevent leaks)
                window.intervalRegistry.stopByOwner('binanceTab');
                window.intervalRegistry.stopByOwner('tab.varliklar');
                window.intervalRegistry.stopByOwner('tab.varliklar.wallet_refresh');
                window.intervalRegistry.stopByOwner('tab.coinlist');
                window.intervalRegistry.stopByOwner('tab.trade');
                window.intervalRegistry.stopByOwner('tab.list');
                window.intervalRegistry.stopByOwner('tab.reports');
                window.intervalRegistry.stopByOwner('tab.finance');
                window.intervalRegistry.stopByOwner('tab.bots');
                window.intervalRegistry.stopByOwner('tab.settings');
                
                if (targetTab !== 'binance') {
                    if (window.BinanceUI && typeof window.BinanceUI.unmount === 'function') window.BinanceUI.unmount();
                }
                
                // Show corresponding content
                // Special handling for "finance" -> "Finance", "reports" -> "Reports", "trade" -> "mobileTradeView"
                let targetContentId;
                if (targetTab === "finance") {
                    targetContentId = "tabFinance";
                } else if (targetTab === "reports") {
                    targetContentId = "tabBinance";
                } else if (targetTab === "trade") {
                    targetContentId = "mobileTradeView";
                } else {
                    targetContentId = `tab${targetTab.charAt(0).toUpperCase() + targetTab.slice(1)}`;
                }
                const targetContent = document.getElementById(targetContentId);
                console.log("[dashboard] Looking for content:", targetContentId, "Found:", !!targetContent);
                
                if (targetContent) {
                    targetContent.classList.add("is-active");
                    targetContent.style.display = "block";
                    console.log("[dashboard] Tab switched successfully to:", targetTab);
                } else {
                    console.error("[dashboard] Tab content not found:", targetContentId, "Available IDs:", Array.from(allContents).map(c => c.id));
                }

                // Aktif Emirler paneli sadece Anasayfa'da göster; diğer sekmelerde gizle
                if (targetTab !== "binance" && typeof hideActiveOrdersPanel === "function") {
                    hideActiveOrdersPanel();
                }

                // Finansal Hesap, İletişim, Ayarlar, Trade sekmelerinde Mevcut Botlar, Bot Performansı ve İşlem Geçmişi gizlensin
                document.body.classList.toggle("tab-finance-active", targetTab === "finance");
                document.body.classList.toggle("tab-contact-active", targetTab === "contact");
                document.body.classList.toggle("tab-settings-active", targetTab === "settings");
                document.body.classList.toggle("tab-trade-active", targetTab === "trade");
                document.body.classList.toggle("tab-bots-active", targetTab === "bots");

                // İşlem Geçmişi paneli: Anasayfa/Binance sekmesinde her zaman görünsün ve veri yüklensin
                var txPanel = document.getElementById("transactionHistoryPanel");
                if (targetTab === "binance" && txPanel) {
                    txPanel.style.display = "block";
                    if (State.accountId && typeof loadTransactionHistory === "function") {
                        loadTransactionHistory(
                            State.txHistoryPeriod || "daily",
                            State.txHistoryType || "buysell",
                            State.txHistoryPage || 1,
                            false,
                            { silent: _txHistoryLoaded }
                        );
                    }
                }

                // Special handling for binance tab (varlıklar + coin listesi + wallet 2sn poll)
                if (targetTab === "binance") {
                    updateBinanceConnectionNotice();
                    initVarliklarTab();
                    if (typeof initBinanceCoinList === 'function') initBinanceCoinList();
                    if (typeof updateActiveOrdersPanelPosition === 'function') updateActiveOrdersPanelPosition();
                    if (typeof startBinanceTabPolling === 'function') startBinanceTabPolling();
                    // Bot alımı / dönüş sonrası cüzdan tablosu hemen güncellensin
                    if (State.accountId) {
                        triggerWalletRefreshForVarliklar(State.accountId, { force: true });
                    }
                    startVarliklarPeriodicRefresh();
                    // İşlemler paneli Binance sekmesinde; veri sadece Reports açıldığında yükleniyordu – Binance açıldığında da yükle
                    if (State.accountId && typeof loadFinanceTrades === 'function') loadFinanceTrades();
                    if (window.__DEBUG_BINANCE__) console.log("[dashboard] Binance tab: BinanceUI.mount");
                    if (State.accountId && window.BinanceUI && typeof window.BinanceUI.mount === 'function') {
                        window.BinanceUI.mount({ accountId: State.accountId });
                        // loadActiveOrders startBinanceTabPolling içinde (orders:poll + 1.5s ilk çekim) tetikleniyor; burada tekrar çağırma
                    } else if (!State.accountId) {
                        const b = document.getElementById("varliklarTableBody");
                        if (b) b.innerHTML = '<tr><td colspan="10" style="text-align: center; padding: 2rem; color: var(--ds-text-secondary);">Hesap seçin.</td></tr>';
                    }
                } else if (targetTab === "finance") {
                    // Special handling for Finansal Hesap tab
                    console.log("[dashboard] Finance tab activated");
                    initFinanceTab();
                } else if (targetTab === "reports") {
                    console.log("[dashboard] Reports tab activated");
                    initReportsTab();
                } else if (targetTab === "settings") {
                    initSettingsTab();
                } else if (targetTab === "contact") {
                    // İletişim sekmesine girince: chat API open=1 ile çağrılır → backend boş sohbete otomatik hoş geldin mesajı ekler
                    if (State.accountId && window.apiClient) {
                        window.apiClient.get('/api/auth/chat?account_id=' + State.accountId + '&open=1').catch(function () {});
                    }
                    if (typeof window.startChatNotify === 'function') window.startChatNotify();
                } else if (targetTab === "trade") {
                    initMobileTradeSearch();
                    if (typeof getFavoritesStorageKey === "function" && getFavoritesStorageKey() && typeof loadSpotFavoritesFromStorage === "function") {
                        loadSpotFavoritesFromStorage().then(function () { if (typeof renderMobileTradeFavorites === "function") renderMobileTradeFavorites(); }).catch(function () { if (typeof renderMobileTradeFavorites === "function") renderMobileTradeFavorites(); });
                    } else {
                        if (typeof renderMobileTradeFavorites === "function") renderMobileTradeFavorites();
                    }
                    if (typeof startMobileTradeFavPriceUpdates === "function") startMobileTradeFavPriceUpdates();
                } else if (targetTab === "bots") {
                    if (typeof activateBotsTab === "function") activateBotsTab();
                } else {
                    stopCoinListUpdates();
                }
            } catch (error) {
                console.error("[dashboard] Tab switch error:", error);
                if (window.errorReporter) {
                    window.errorReporter.report(error, { action: 'switchTab', tab: targetTab });
                }
            }
        };
    });
    
    initMobileTradeSearch();
    console.log("[dashboard] bindTabs: All tabs bound");
}

// Must-change-password modal: always bind (modal shows before any tab switch)
function bindMustChangePasswordModal() {
    const btn = document.getElementById('mustChangePasswordBtn');
    const newInput = document.getElementById('mustChangePasswordNew');
    const confirmInput = document.getElementById('mustChangePasswordConfirm');
    const statusEl = document.getElementById('mustChangePasswordStatus');
    const strengthEl = document.getElementById('mustChangePasswordStrength');
    const matchEl = document.getElementById('mustChangePasswordMatch');
    if (!btn || !newInput || !confirmInput) return;

    function updateStrength() {
        const user = JSON.parse(localStorage.getItem('user') || '{}');
        const check = dashboardValidatePassword(newInput.value, user.name || '', user.surname || '');
        if (strengthEl) {
            strengthEl.textContent = newInput.value ? check.msg : '';
            strengthEl.style.color = check.valid ? '#0ecb81' : 'var(--ds-danger)';
        }
    }
    function updateMatch() {
        const match = confirmInput.value === newInput.value;
        if (matchEl) {
            matchEl.textContent = !confirmInput.value ? '' : match ? '✓ Şifreler eşleşiyor' : '✗ Şifreler eşleşmiyor';
            matchEl.style.color = match ? '#0ecb81' : 'var(--ds-danger)';
        }
    }

    newInput.addEventListener('input', updateStrength);
    newInput.addEventListener('blur', updateStrength);
    confirmInput.addEventListener('input', updateMatch);
    confirmInput.addEventListener('blur', updateMatch);

    btn.onclick = null;
    btn.onclick = async function () {
        const newPassword = newInput.value.trim();
        const newPasswordConfirm = confirmInput.value.trim();

        if (!newPassword || !newPasswordConfirm) {
            if (statusEl) {
                statusEl.textContent = 'Lütfen her iki alanı da doldurun.';
                statusEl.style.color = 'var(--ds-danger)';
            }
            return;
        }
        if (newPassword !== newPasswordConfirm) {
            if (statusEl) {
                statusEl.textContent = 'Şifreler eşleşmiyor.';
                statusEl.style.color = 'var(--ds-danger)';
            }
            return;
        }
        const user = JSON.parse(localStorage.getItem('user') || '{}');
        const check = dashboardValidatePassword(newPassword, user.name || '', user.surname || '');
        if (!check.valid) {
            if (statusEl) {
                statusEl.textContent = check.msg;
                statusEl.style.color = 'var(--ds-danger)';
            }
            return;
        }

        btn.disabled = true;
        if (statusEl) {
            statusEl.textContent = 'Güncelleniyor…';
            statusEl.style.color = 'var(--ds-text-secondary)';
        }
        try {
            await window.apiClient.post('/api/auth/change-password', {
                account_id: State.accountId,
                new_password: newPassword,
                new_password_confirm: newPasswordConfirm
            });

            const u = JSON.parse(localStorage.getItem('user') || '{}');
            u.must_change_password = false;
            localStorage.setItem('user', JSON.stringify(u));

            const modal = document.getElementById('mustChangePasswordModal');
            if (modal) modal.style.display = 'none';
            const container = document.querySelector('.container');
            if (container) {
                container.style.pointerEvents = '';
                container.style.opacity = '';
                container.style.filter = '';
            }
            document.querySelectorAll('.dm-tab').forEach(t => {
                t.style.pointerEvents = '';
                t.style.opacity = '';
            });
            if (window.Toast) window.Toast.success('Şifre başarıyla değiştirildi. Artık platformu kullanabilirsiniz.');

            newInput.value = '';
            confirmInput.value = '';
            if (statusEl) statusEl.textContent = '';
            if (strengthEl) strengthEl.textContent = '';
            if (matchEl) matchEl.textContent = '';
        } catch (e) {
            const msg = e.message || 'Şifre değiştirilemedi';
            if (statusEl) {
                statusEl.textContent = msg;
                statusEl.style.color = 'var(--ds-danger)';
            }
            if (window.Toast) window.Toast.error(msg);
        } finally {
            btn.disabled = false;
        }
    };
}

// Modal (dm-modal)
// Track if modal is in "edit mode" (showing existing bot)
let createModalEditMode = {
    botId: null,
    accountId: null,
    isEdit: false
};

// Track current selected template
let currentSelectedTemplate = null;

// Create modal: canlı fiyat güncellemesi
var dmModalLivePriceIntervalId = null;
var dmModalMultiPreviewIntervalId = null;
var dmModalLastPrice = null;
var dmModalLastPct = null;
var dmModalLastLogoBase = null;
var dmModalOpenTs = 0;
var dmModalLastChartSymbol = null;  // Grafik sadece sembol değişince yeniden yüklensin (flicker önleme)
var dmModalLastTahminSymbol = null;
var _dmSymbolSearchPriceGen = 0;
var _dmSymbolSearchOutsideBound = false;
var _dmSymbolSearchPicking = false;
var _dmModalStripSymbol = null;
var dmModalTahminFetchTs = 0;
var dmModalTahminHigh = null;
var dmModalTahminLow = null;
var _dmModalTickerInflightKey = '';
var _dmModalTickerInflight = null;
var _dmModalLastTickerFetchSymbol = null;
var _dmModalTickerFetchTs = 0;
var DM_MODAL_LIVE_PRICE_MS = 1500;
var DM_MODAL_TAHMIN_MIN_MS = 30000;  // Tahmin (high/low) en fazla 30s'de bir yenilensin

function resolveDmModalChangePct(mini) {
    var raw = (mini && mini.changePct != null) ? Number(mini.changePct) : null;
    if (raw != null && Number.isFinite(raw)) {
        var bogusZero = raw === 0 && dmModalLastPct != null && Number.isFinite(dmModalLastPct) && Math.abs(dmModalLastPct) >= 0.005;
        if (!bogusZero) return raw;
    }
    if (dmModalLastPct != null && Number.isFinite(dmModalLastPct)) return dmModalLastPct;
    return (raw != null && Number.isFinite(raw)) ? raw : null;
}

function applyDmModalPctEl(el, pct) {
    if (!el) return;
    if (pct != null && Number.isFinite(pct)) {
        var newPctStr = (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%';
        var newColor = pct >= 0 ? '#0ecb81' : '#f6465d';
        if (el.textContent !== newPctStr || el.style.color !== newColor) {
            dmModalLastPct = pct;
            el.textContent = newPctStr;
            el.style.color = newColor;
        }
        return;
    }
    if (dmModalLastPct != null && Number.isFinite(dmModalLastPct)) {
        var holdStr = (dmModalLastPct >= 0 ? '+' : '') + dmModalLastPct.toFixed(2) + '%';
        var holdColor = dmModalLastPct >= 0 ? '#0ecb81' : '#f6465d';
        if (el.textContent !== holdStr || el.style.color !== holdColor) {
            el.textContent = holdStr;
            el.style.color = holdColor;
        }
        return;
    }
    if (el.textContent !== '—') {
        el.textContent = '—';
        el.style.color = '';
    }
}
var DASHBOARD_LAST_CREATE_BOT_PARAMS = "dashboard_last_create_bot_params";

/** Son oluşturulan bot parametrelerini forma uygula (yeni bot açılırken önceki değerler girili olsun) */
function applyLastCreateParamsToForm() {
    try {
        var raw = localStorage.getItem(DASHBOARD_LAST_CREATE_BOT_PARAMS);
        if (!raw) return;
        var p = JSON.parse(raw);
        if (!p || typeof p !== "object") return;
        var strategy = (p.strategy_id || "").trim().toLowerCase();
        var currentId = (currentSelectedTemplate && currentSelectedTemplate.id) ? currentSelectedTemplate.id : "trailing_dca";
        var symEl = document.getElementById("fSymbol");
        var budgetEl = document.getElementById("fBudget");
        var basePctEl = document.getElementById("fBasePct");
        var quotePctEl = document.getElementById("fQuotePct");
        if (symEl && p.symbol) { symEl.value = p.symbol; symEl.readOnly = false; }
        if (budgetEl && (p.budget_usd != null || p.initial_capital_usdt != null)) budgetEl.value = p.budget_usd != null ? p.budget_usd : p.initial_capital_usdt;
        var alloc = p.allocation || {};
        if (basePctEl && (alloc.base_pct != null || alloc.base_pct === 0)) basePctEl.value = alloc.base_pct;
        if (quotePctEl && (alloc.quote_pct != null || alloc.quote_pct === 0)) quotePctEl.value = alloc.quote_pct;
        var up = p.up || {};
        var down = p.down || {};
        var profit = p.profit || {};
        var upCountEl = document.getElementById("fUpCount");
        var downCountEl = document.getElementById("fDownCount");
        var upGrids = up.grids || [];
        var downGrids = down.grids || [];
        if (upCountEl && upGrids.length > 0) { upCountEl.value = upGrids.length; buildGridRows("upGridRows", upGrids.length, "up"); }
        if (downCountEl && downGrids.length > 0) { downCountEl.value = downGrids.length; buildGridRows("downGridRows", downGrids.length, "down"); }
        var upTrailEl = document.getElementById("fUpTrail");
        var downTrailEl = document.getElementById("fDownTrail");
        if (upTrailEl && (up.trail_pct != null || up.trail_pct === 0)) upTrailEl.value = up.trail_pct;
        if (downTrailEl && (down.trail_pct != null || down.trail_pct === 0)) downTrailEl.value = down.trail_pct;
        for (var i = 0; i < upGrids.length; i++) {
            var tEl = document.getElementById("upGrid_" + i + "_trigger");
            var qEl = document.getElementById("upGrid_" + i + "_qty");
            if (tEl && upGrids[i].trigger_pct != null) tEl.value = upGrids[i].trigger_pct;
            if (qEl && upGrids[i].qty_pct != null) qEl.value = upGrids[i].qty_pct;
        }
        for (var j = 0; j < downGrids.length; j++) {
            var t2 = document.getElementById("downGrid_" + j + "_trigger");
            var q2 = document.getElementById("downGrid_" + j + "_qty");
            if (t2 && downGrids[j].trigger_pct != null) t2.value = downGrids[j].trigger_pct;
            if (q2 && downGrids[j].qty_pct != null) q2.value = downGrids[j].qty_pct;
        }
        var rebuyT = document.getElementById("fRebuyTrigger");
        var rebuyTrail = document.getElementById("fRebuyTrail");
        var resellT = document.getElementById("fResellTrigger");
        var resellTrail = document.getElementById("fResellTrail");
        if (rebuyT && (profit.rebuy_trigger_pct != null || profit.rebuy_trigger_pct === 0)) rebuyT.value = profit.rebuy_trigger_pct;
        if (rebuyTrail && profit.rebuy_trail_pct != null) rebuyTrail.value = profit.rebuy_trail_pct;
        if (resellT && (profit.resell_trigger_pct != null || profit.resell_trigger_pct === 0)) resellT.value = profit.resell_trigger_pct;
        if (resellTrail && profit.resell_trail_pct != null) resellTrail.value = profit.resell_trail_pct;
        if (p.symbol && typeof updateCreateBotModalPairStrip === "function") updateCreateBotModalPairStrip(p.symbol);
    } catch (e) { console.debug("applyLastCreateParamsToForm", e); }
}

function openCreateBotModal(botId = null, accountId = null, skipLastCreateParams = false, focusFieldId = null) {
    const modal = document.getElementById("dmModal");
    const backdrop = document.getElementById("dmBackdrop");
    if (!modal || !backdrop) return;
    try {
        var templateId = (currentSelectedTemplate && currentSelectedTemplate.id) ? currentSelectedTemplate.id : "trailing_dca";
        sessionStorage.setItem("createBotParamScreen", templateId);
    } catch (e) {}
    // Strip ve tahmin: sembol seçilene kadar gizli (leaderboard Uygula ile sembol doluysa göster)
    const strip = document.getElementById("dmSelectedPairStrip");
    const tahminStrip = document.getElementById("dmTahminStrip");
    var prefillSymbol = (document.getElementById("fSymbol") || {}).value || "";
    if (skipLastCreateParams && prefillSymbol.trim() && typeof updateCreateBotModalPairStrip === "function") {
        updateCreateBotModalPairStrip(prefillSymbol.trim());
    } else {
        if (strip) strip.style.display = "none";
        if (tahminStrip) tahminStrip.style.display = "none";
    }
    hideCreateModalSymbolDropdown();
    ensureCoinListSearchSymbolsLoaded("all").then(function () { buildCoinListSearchSymbols(); });
    var fBudgetReset = document.getElementById("fBudget");
    if (fBudgetReset) fBudgetReset.placeholder = "Kullanılabilir: —";
    if (State.accountId && typeof pollWallet === "function" && (!assetsState.wallet.assets || !assetsState.wallet.assets.length)) pollWallet(true);
    
    // Reset edit mode if opening for new bot
    if (!botId) {
        createModalEditMode = { botId: null, accountId: null, isEdit: false };
    }
    setCreateBotModalWizard(currentSelectedTemplate ? currentSelectedTemplate.id : "trailing_dca");
    
    modal.setAttribute("aria-hidden", "false");
    backdrop.setAttribute("aria-hidden", "false");
    modal.style.display = "flex";
    backdrop.style.display = "block";
    document.body.style.overflow = "hidden";

    dmModalLastPrice = null;
    dmModalLastPct = null;
    dmModalOpenTs = Date.now();
    var priceEl = document.getElementById("dmPairPrice");
    var changeEl = document.getElementById("dmPairChangePct");
    if (priceEl) priceEl.classList.remove("blink-positive", "blink-negative");
    if (changeEl) changeEl.classList.remove("blink-positive", "blink-negative");

    // Oluştur = her zaman oluştur + anında başlat (parametreleri girip Oluştur dediğiniz an bot çalışır)
    const submitBtn = document.getElementById("dmSubmitBtn");
    if (submitBtn) {
        submitBtn.textContent = "Oluştur";
        submitBtn.onclick = async () => {
            await createAndStartBot(currentSelectedTemplate || null);
        };
    }
    
    // Reset modal title
    const titleEl = document.querySelector(".dm-modal__title");
    if (titleEl && !botId) {
        titleEl.textContent = currentSelectedTemplate ? `Bot Oluştur - ${currentSelectedTemplate.name}` : "Bot Oluştur";
    }
    
    if (focusFieldId) {
        setTimeout(function () {
            var focusEl = document.getElementById(focusFieldId);
            if (focusEl) focusEl.focus();
        }, 120);
    } else {
        const firstInput = modal.querySelector("input, select, textarea");
        if (firstInput) setTimeout(() => firstInput.focus(), 100);
    }
    if (!botId && !skipLastCreateParams && typeof applyLastCreateParamsToForm === "function") setTimeout(applyLastCreateParamsToForm, 80);
}

function closeCreateBotModal() {
    const modal = document.getElementById("dmModal");
    const backdrop = document.getElementById("dmBackdrop");
    if (!modal || !backdrop) return;
    hideMultiSymbolSearchDropdown();
    modal.setAttribute("aria-hidden", "true");
    backdrop.setAttribute("aria-hidden", "true");
    modal.style.display = "none";
    backdrop.style.display = "none";
    document.body.style.overflow = "";
    
    // Reset edit mode
    createModalEditMode = { botId: null, accountId: null, isEdit: false };
    currentSelectedTemplate = null; // Reset template selection
    try { sessionStorage.removeItem("createBotParamScreen"); } catch (e) {}
    // Reset submit button (Oluştur = her zaman oluştur + başlat)
    const submitBtn = document.getElementById("dmSubmitBtn");
    if (submitBtn) {
        submitBtn.textContent = "Oluştur";
        submitBtn.disabled = false;
        submitBtn.style.opacity = "1";
        submitBtn.onclick = async () => { await createAndStartBot(currentSelectedTemplate || null); };
    }
    
    // Reset modal title
    const titleEl = document.querySelector(".dm-modal__title");
    if (titleEl) {
        titleEl.textContent = "Bot Oluştur";
    }
    
    // Clear form and reset readonly states (varsayılan: trail 0.5, tetik 1.5)
    modal.querySelectorAll("input").forEach(input => {
        input.readOnly = false; // Reset readonly state
        if (input.id === "fBasePct") input.value = "50";
        else if (input.id === "fQuotePct") input.value = "50";
        else if (input.id === "fUpCount" || input.id === "fDownCount") input.value = "0";
        else if (input.id === "fUpTrail" || input.id === "fDownTrail" || input.id === "fResellTrail") input.value = "0.5";
        else if (input.id === "fRebuyTrigger" || input.id === "fResellTrigger") input.value = "1.5";
        else if (input.id === "fRebuyTrail") input.value = "0.30";
        else input.value = "";
    });
    
    // Clear error message
    const errorEl = document.getElementById("createBotError");
    if (errorEl) {
        errorEl.style.display = "none";
        errorEl.textContent = "";
    }
    
    // Clear grid rows
    const upGridRows = document.getElementById("upGridRows");
    if (upGridRows) upGridRows.innerHTML = "";
    const downGridRows = document.getElementById("downGridRows");
    if (downGridRows) downGridRows.innerHTML = "";
    
    const strip = document.getElementById("dmSelectedPairStrip");
    const tahminStrip = document.getElementById("dmTahminStrip");
    if (strip) strip.style.display = "none";
    if (tahminStrip) tahminStrip.style.display = "none";
    hideCreateModalSymbolDropdown();
    _dmModalStripSymbol = null;
    dmModalLastChartSymbol = null;
    dmModalLastTahminSymbol = null;
    dmModalTahminHigh = null;
    dmModalTahminLow = null;
    _dmModalTickerInflightKey = '';
    _dmModalTickerInflight = null;
    _dmModalLastTickerFetchSymbol = null;
    _dmModalTickerFetchTs = 0;
    if (dmModalLivePriceIntervalId) {
        clearInterval(dmModalLivePriceIntervalId);
        dmModalLivePriceIntervalId = null;
    }
    if (dmModalMultiPreviewIntervalId) {
        clearInterval(dmModalMultiPreviewIntervalId);
        dmModalMultiPreviewIntervalId = null;
    }
    dmModalLastPrice = null;
    dmModalLastPct = null;
    dmModalLastLogoBase = null;
}

function bindCreateBotModal() {
    // Open triggers - "Bot Oluştur" buttons should open bot structure selection modal first
    document.querySelectorAll('[onclick*="openCreateBotModal"]').forEach(btn => {
        btn.onclick = () => openBotStructureModal();
    });
    
    // Close triggers for parameter modal
    document.getElementById("dmCloseBtn")?.addEventListener("click", closeCreateBotModal);
    document.getElementById("dmCancelBtn")?.addEventListener("click", closeCreateBotModal);
    document.getElementById("dmBackdrop")?.addEventListener("click", (e) => {
        if (e.target.id === "dmBackdrop") closeCreateBotModal();
    });
    
    // Close triggers for bot structure modal
    document.getElementById("botStructureCloseBtn")?.addEventListener("click", closeBotStructureModal);
    document.getElementById("botStructureBackdrop")?.addEventListener("click", (e) => {
        if (e.target.id === "botStructureBackdrop") closeBotStructureModal();
    });
    
    // Ondalık alanlarda virgülü noktaya çevir (0,5 → 0.5) type="number" uyumu için
    ["fUpTrail", "fDownTrail", "fRebuyTrigger", "fRebuyTrail", "fResellTrigger", "fResellTrail"].forEach(function (id) {
        var el = document.getElementById(id);
        if (el) el.addEventListener("input", function () {
            var v = this.value;
            if (v && v.indexOf(",") !== -1) this.value = v.replace(",", ".");
        });
    });

    // ESC key - close active modal
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
            const structureModal = document.getElementById("botStructureModal");
            const paramModal = document.getElementById("dmModal");
            if (structureModal && structureModal.getAttribute("aria-hidden") === "false") {
                closeBotStructureModal();
            } else if (paramModal && paramModal.getAttribute("aria-hidden") === "false") {
                closeCreateBotModal();
            }
        }
    });
    
    // Parite strip: grafik alanına tıklanınca detay grafik sayfası
    const dmPairChartWrap = document.getElementById("dmPairChartWrap");
    if (dmPairChartWrap) {
        dmPairChartWrap.addEventListener("click", function () {
            const sym = normalizeSymbol(document.getElementById("fSymbol").value);
            if (sym) window.location.href = "/ui/chart.html?symbol=" + encodeURIComponent(sym) + "&from=botcreate";
        });
    }
    
    // fSymbol: yazarken arama dropdown, seçince strip + tahmin güncelle
    bindDmSymbolSearchOutsideClose();
    const fSymbol = document.getElementById("fSymbol");
    const dmSymbolSearchDropdown = document.getElementById("dmSymbolSearchDropdown");
    if (fSymbol) {
        let dmSymbolInputDebounce = null;
        var symWrap = fSymbol.closest(".coin-list-search-wrap");
        if (symWrap) {
            symWrap.addEventListener("pointerdown", function (e) {
                if (e.target.closest("#dmSymbolSearchDropdown")) return;
                if (document.activeElement !== fSymbol) {
                    fSymbol.focus({ preventScroll: true });
                }
            });
        }
        fSymbol.addEventListener("focus", function () {
            var v = (fSymbol.value || "").trim();
            if (coinListSearchAllSymbols.length > 0) {
                if (v.length >= 2) showCreateModalSymbolDropdown(v);
                else showCreateModalSymbolDropdownSuggestions();
            }
            ensureCoinListSearchSymbolsLoaded("all").then(function () {
                buildCoinListSearchSymbols();
                if (document.activeElement !== fSymbol) return;
                var v2 = (fSymbol.value || "").trim();
                if (v2.length >= 2) showCreateModalSymbolDropdown(v2);
                else showCreateModalSymbolDropdownSuggestions();
            });
        });
        fSymbol.addEventListener("input", function () {
            const v = (fSymbol.value || "").trim();
            clearTimeout(dmSymbolInputDebounce);
            if (v.length >= 2) {
                if (coinListSearchAllSymbols.length > 0) showCreateModalSymbolDropdown(v);
                dmSymbolInputDebounce = setTimeout(function () {
                    ensureCoinListSearchSymbolsLoaded("all").then(function () {
                        buildCoinListSearchSymbols();
                        if (document.activeElement !== fSymbol) return;
                        showCreateModalSymbolDropdown((fSymbol.value || "").trim());
                    });
                }, 100);
            } else if (v.length === 1) {
                if (coinListSearchAllSymbols.length > 0) showCreateModalSymbolDropdown(v, 1);
                dmSymbolInputDebounce = setTimeout(function () {
                    ensureCoinListSearchSymbolsLoaded("all").then(function () {
                        buildCoinListSearchSymbols();
                        if (document.activeElement !== fSymbol) return;
                        showCreateModalSymbolDropdown((fSymbol.value || "").trim(), 1);
                    });
                }, 80);
            } else {
                hideCreateModalSymbolDropdown();
                if (v.length === 0) {
                    const strip = document.getElementById("dmSelectedPairStrip");
                    const tahminStrip = document.getElementById("dmTahminStrip");
                    if (strip) strip.style.display = "none";
                    if (tahminStrip) tahminStrip.style.display = "none";
                    _dmModalStripSymbol = null;
                }
            }
        });
        fSymbol.addEventListener("blur", function () {
            setTimeout(function () {
                if (_dmSymbolSearchPicking) {
                    _dmSymbolSearchPicking = false;
                    return;
                }
                hideCreateModalSymbolDropdown();
            }, 160);
        });
        // Enter: parite onayla → strip ve tahmin göster (dropdown açıksa ilk sonucu seç, yoksa yazılanı normalize et)
        fSymbol.addEventListener("keydown", function (e) {
            if (e.key === "Escape") {
                hideCreateModalSymbolDropdown();
                return;
            }
            if (e.key !== "Enter") return;
            const dropdown = document.getElementById("dmSymbolSearchDropdown");
            const firstItem = dropdown && dropdown.querySelector(".dm-symbol-search-item, .coin-list-search-item");
            if (firstItem && dropdown.style.display !== "none") {
                const symbol = firstItem.getAttribute("data-symbol");
                if (symbol) {
                    fSymbol.value = symbol;
                    hideCreateModalSymbolDropdown();
                    updateCreateBotModalPairStrip(symbol);
                    e.preventDefault();
                }
            } else {
                const v = (fSymbol.value || "").trim();
                if (v.length >= 2) {
                    const norm = normalizeModalSymbol(v);
                    if (!norm.invalid && norm.normalized) {
                        updateCreateBotModalPairStrip(norm.normalized);
                        e.preventDefault();
                    }
                }
            }
        });
    }
    if (dmSymbolSearchDropdown) {
        dmSymbolSearchDropdown.addEventListener("mousedown", function (e) {
            var item = e.target.closest(".dm-symbol-search-item, .coin-list-search-item");
            if (!item) return;
            e.preventDefault();
            _dmSymbolSearchPicking = true;
            var symbol = item.getAttribute("data-symbol");
            if (symbol) fetchCreateBotModalTicker24h(symbol, { force: true });
            if (symbol && fSymbol) {
                fSymbol.value = symbol;
                hideCreateModalSymbolDropdown();
                updateCreateBotModalPairStrip(symbol);
            }
        });
    }
    
    // Base/Quote sync
    const fBasePct = document.getElementById("fBasePct");
    const fQuotePct = document.getElementById("fQuotePct");
    if (fBasePct && fQuotePct) {
        fBasePct.addEventListener("input", () => {
            const baseVal = parseFloat(fBasePct.value) || 0;
            fQuotePct.value = (100 - baseVal).toFixed(1);
        });
    }
    
    // Grid rows builders
    document.getElementById("fUpCount")?.addEventListener("input", (e) => {
        buildGridRows("upGridRows", parseInt(e.target.value) || 0, "up");
    });
    document.getElementById("fDownCount")?.addEventListener("input", (e) => {
        buildGridRows("downGridRows", parseInt(e.target.value) || 0, "down");
    });
    document.getElementById("fMultiCoinCount")?.addEventListener("input", (e) => {
        buildMultiAssetRows(parseInt(e.target.value, 10) || 2);
    });
    document.getElementById("fMultiRebalanceMode")?.addEventListener("change", updateMultiRebalanceModeVisibility);
    var dmMultiSymbolInputDebounce = null;
    var multiAssetRowsEl = document.getElementById("multiAssetRows");
    if (multiAssetRowsEl) {
        multiAssetRowsEl.addEventListener("focusin", function (e) {
            var input = e.target.closest(".multi-asset-symbol");
            if (!input) return;
            if (currentSelectedTemplate && currentSelectedTemplate.id === "multi_rebalance") {
                ensureCoinListSearchSymbolsLoaded("all").then(function () { buildCoinListSearchSymbols(); });
            }
        });
        multiAssetRowsEl.addEventListener("input", function (e) {
            var pctInput = e.target.closest(".multi-asset-pct");
            if (pctInput) {
                updateMultiPctTotal();
                return;
            }
            var input = e.target.closest(".multi-asset-symbol");
            if (!input) return;
            var v = (input.value || "").trim();
            clearTimeout(dmMultiSymbolInputDebounce);
            if (v.length >= 2) {
                dmMultiSymbolInputDebounce = setTimeout(function () {
                    ensureCoinListSearchSymbolsLoaded("all").then(function () {
                        buildCoinListSearchSymbols();
                        showMultiSymbolSearchDropdown(v, input);
                    });
                }, 200);
            } else {
                hideMultiSymbolSearchDropdown();
                if (v.length === 0) {
                    var idx = input.getAttribute("data-idx");
                    if (idx != null) updateMultiAssetPreview(idx, "");
                }
            }
        });
        multiAssetRowsEl.addEventListener("focusout", function (e) {
            if (e.relatedTarget && e.relatedTarget.closest && e.relatedTarget.closest("#dmMultiSymbolSearchDropdown")) return;
            setTimeout(function () {
                hideMultiSymbolSearchDropdown();
                var input = e.target;
                if (input && input.classList && input.classList.contains("multi-asset-symbol")) {
                    var v = (input.value || "").trim();
                    if (v.length >= 2) {
                        var sym = v.toUpperCase().replace(/\s/g, "");
                        if (!sym.endsWith("USDT")) sym = sym + "USDT";
                        var norm = normalizeModalSymbol(sym);
                        if (!norm.invalid && norm.normalized) updateMultiAssetPreview(input.getAttribute("data-idx"), norm.normalized);
                    }
                }
            }, 180);
        });
        multiAssetRowsEl.addEventListener("keydown", function (e) {
            var input = e.target.closest(".multi-asset-symbol");
            if (!input || e.key !== "Enter") return;
            var dropdown = document.getElementById("dmMultiSymbolSearchDropdown");
            var firstItem = dropdown && dropdown.querySelector(".dm-multi-symbol-item, .coin-list-search-item");
            if (firstItem && dropdown.style.display !== "none") {
                var symbol = firstItem.getAttribute("data-symbol");
                if (symbol) {
                    var base = symbol.replace(/USDT$/, "").replace(/FDUSD$/, "");
                    input.value = base;
                    hideMultiSymbolSearchDropdown();
                    var idx = input.getAttribute("data-idx");
                    if (idx != null) updateMultiAssetPreview(idx, symbol);
                    e.preventDefault();
                }
            } else {
                var v = (input.value || "").trim();
                if (v.length >= 2) {
                    var sym = v.toUpperCase().replace(/\s/g, "");
                    if (!sym.endsWith("USDT")) sym = sym + "USDT";
                    var norm = normalizeModalSymbol(sym);
                    if (!norm.invalid && norm.normalized) {
                        input.value = (norm.normalized || "").replace(/USDT$/, "");
                        var idx = input.getAttribute("data-idx");
                        if (idx != null) updateMultiAssetPreview(idx, norm.normalized);
                        e.preventDefault();
                    }
                }
            }
        });
    }
    var dmMultiSymbolSearchDropdownEl = document.getElementById("dmMultiSymbolSearchDropdown");
    if (dmMultiSymbolSearchDropdownEl) {
        dmMultiSymbolSearchDropdownEl.addEventListener("mousedown", function (e) { e.preventDefault(); });
        dmMultiSymbolSearchDropdownEl.addEventListener("click", function (e) {
            var item = e.target.closest(".dm-multi-symbol-item, .coin-list-search-item");
            if (!item) return;
            var symbol = item.getAttribute("data-symbol");
            if (!symbol || !_dmMultiSearchTargetInput) return;
            var base = symbol.replace(/USDT$/, "").replace(/FDUSD$/, "");
            _dmMultiSearchTargetInput.value = base;
            hideMultiSymbolSearchDropdown();
            var idx = _dmMultiSearchTargetIdx;
            if (idx != null) updateMultiAssetPreview(idx, symbol);
        });
    }
    
    // Submit: openCreateBotModal sets dmSubmitBtn.onclick → createAndStartBot (do not add createBot listener — it skips engine start)
}

function buildGridRows(containerId, count, mode) {
    const container = document.getElementById(containerId);
    if (!container) return;
    
    let html = '';
    for (let i = 0; i < count; i++) {
        const triggerLabel = mode === 'up' ? 'Tetik Fiyatı % (yukarı)' : 'Tetik Fiyatı % (aşağı)';
        const triggerTooltip = mode === 'up' 
            ? 'Referans fiyatından yukarı yönde %X kadar artışta bu grid tetiklenir. Örn: 0.5% = fiyat %0.5 yükselirse satış yapılır.'
            : 'Referans fiyatından aşağı yönde %X kadar düşüşte bu grid tetiklenir. Örn: 0.5% = fiyat %0.5 düşerse alış yapılır.';
        const qtyTooltip = mode === 'up'
            ? 'Bu grid tetiklendiğinde mevcut coin miktarının %X\'i satılacak. Örn: 10% = coin miktarının %10\'u satılır.'
            : 'Bu grid tetiklendiğinde mevcut USDT miktarının %X\'i ile alış yapılacak. Örn: 10% = USDT\'nin %10\'u ile coin alınır.';
        
        html += `
            <div class="grid-row">
                <div class="form-group">
                    <label class="label-with-tooltip">
                        ${triggerLabel}
                        <span class="tooltip-icon">ℹ</span>
                        <span class="tooltip-text">${triggerTooltip}</span>
                    </label>
                    <input type="number" id="${mode}Grid_${i}_trigger" class="form-input" step="0.01" placeholder="${(i + 1) * 0.5}" />
                </div>
                <div class="form-group">
                    <label class="label-with-tooltip">
                        Miktar %
                        <span class="tooltip-icon">ℹ</span>
                        <span class="tooltip-text">${qtyTooltip}</span>
                    </label>
                    <input type="number" id="${mode}Grid_${i}_qty" class="form-input" step="0.1" min="0" max="100" placeholder="10" />
                </div>
            </div>
        `;
    }
    container.innerHTML = html;
}

function normalizeSymbol(symbol) {
    return symbol.toUpperCase().replace(/\s+/g, '').replace(/\//g, '');
}

/** Parite sembolünden base/quote çıkar (BTCUSDT → { base: 'BTC', quote: 'USDT' }) */
function parseBaseQuote(symbol) {
    var pq = parseTradingPairSymbol(symbol);
    if (pq.valid) return { base: pq.base, quote: pq.quote };
    return { base: (symbol || '').toUpperCase().replace(/[\s\/\-]/g, ''), quote: 'USDT' };
}

/** Create bot modal: ticker_24h yanıtını strip + tahmin alanına uygula (klines'den hızlı). */
function applyCreateBotModalTickerData(sym, quote, data) {
    if (!sym || !data) return;
    var price = parseFloat(data.lastPrice || data.weightedAvgPrice || 0);
    var pct = parseFloat(data.priceChangePercent);
    var high = parseFloat(data.highPrice || 0);
    var low = parseFloat(data.lowPrice || 0);
    if (!(price > 0 && Number.isFinite(price))) return;
    var pctVal = Number.isFinite(pct) ? pct : null;
    _updateCoinSearchSymbolQuote(sym, price, pctVal);
    if (window.marketStore && window.marketStore.updateMini) {
        var miniPatch = { last: price, changePct: pctVal };
        if (high > 0 && Number.isFinite(high)) miniPatch.high = high;
        if (low > 0 && Number.isFinite(low)) miniPatch.low = low;
        window.marketStore.updateMini(sym, miniPatch);
    }
    var priceEl = document.getElementById('dmPairPrice');
    var changeEl = document.getElementById('dmPairChangePct');
    var changeTahmin = document.getElementById('dmTahminChange');
    var highEl = document.getElementById('dmTahminHigh');
    var lowEl = document.getElementById('dmTahminLow');
    var formatPrice = function (v) {
        return (v != null && Number.isFinite(v) && v > 0)
            ? ((quote === 'USDT' || quote === 'FDUSD') ? fmtUsd(v) : fmtNum(v, 8))
            : '—';
    };
    if (priceEl) {
        var newText = (quote === 'USDT' || quote === 'FDUSD' ? fmtUsd(price) : fmtNum(price, 8) + ' ' + quote);
        if (priceEl.textContent !== newText) {
            var blinkGrace = (typeof dmModalOpenTs === 'number' && (Date.now() - dmModalOpenTs) < 600);
            if (!blinkGrace && dmModalLastPrice != null && Number.isFinite(dmModalLastPrice) && Math.abs(price - dmModalLastPrice) > 1e-10 && typeof triggerValueBlink === 'function') {
                triggerValueBlink(priceEl, price);
            }
            dmModalLastPrice = price;
            priceEl.textContent = newText;
        }
    }
    if (pctVal != null) {
        applyDmModalPctEl(changeEl, pctVal);
        applyDmModalPctEl(changeTahmin, pctVal);
    }
    if (high > 0 && Number.isFinite(high)) {
        dmModalTahminHigh = high;
        if (highEl) highEl.textContent = formatPrice(high);
    }
    if (low > 0 && Number.isFinite(low)) {
        dmModalTahminLow = low;
        if (lowEl) lowEl.textContent = formatPrice(low);
    }
}

/** Create bot modal: /api/spot/ticker_24h — fiyat, 24s %, yüksek/düşük (klines yerine). */
function fetchCreateBotModalTicker24h(symbol, opts) {
    opts = opts || {};
    var sym = (symbol || '').toUpperCase();
    if (!sym) return Promise.resolve(null);
    var now = Date.now();
    var symbolChanged = sym !== _dmModalLastTickerFetchSymbol;
    var stale = (now - _dmModalTickerFetchTs) >= DM_MODAL_TAHMIN_MIN_MS;
    if (!opts.force && !symbolChanged && !stale) {
        if (_dmModalTickerInflightKey === sym && _dmModalTickerInflight) return _dmModalTickerInflight;
        return Promise.resolve(null);
    }
    if (_dmModalTickerInflightKey === sym && _dmModalTickerInflight) return _dmModalTickerInflight;
    var quote = parseBaseQuote(sym).quote;
    _dmModalTickerInflightKey = sym;
    var fetchFn = window.apiClient && typeof window.apiClient.get === 'function'
        ? window.apiClient.get('/api/spot/ticker_24h?symbol=' + encodeURIComponent(sym), { suppressRateLimitToast: true, timeout: 8000 })
        : fetch(window.location.origin + '/api/spot/ticker_24h?symbol=' + encodeURIComponent(sym)).then(function (r) { return r.json(); });
    _dmModalTickerInflight = Promise.resolve(fetchFn).then(function (data) {
        if (_dmModalTickerInflightKey !== sym) return data;
        _dmModalLastTickerFetchSymbol = sym;
        _dmModalTickerFetchTs = Date.now();
        dmModalTahminFetchTs = _dmModalTickerFetchTs;
        applyCreateBotModalTickerData(sym, quote, data);
        return data;
    }).catch(function () {
        return null;
    }).finally(function () {
        if (_dmModalTickerInflightKey === sym) {
            _dmModalTickerInflight = null;
        }
    });
    return _dmModalTickerInflight;
}

/** Create bot modal: seçilen parite strip'ini (logo, fiyat, 24h %, grafik) ve tahmin alanını güncelle */
function updateCreateBotModalPairStrip(symbol, opts) {
    opts = opts || {};
    const strip = document.getElementById('dmSelectedPairStrip');
    const tahminStrip = document.getElementById('dmTahminStrip');
    const logoEl = document.getElementById('dmPairLogo');
    const baseEl = document.getElementById('dmPairBaseSymbol');
    const pairEl = document.getElementById('dmPairSymbol');
    const priceEl = document.getElementById('dmPairPrice');
    const changeEl = document.getElementById('dmPairChangePct');
    const norm = normalizeModalSymbol(symbol || '');
    if (!strip || !tahminStrip) return;
    if (norm.invalid || !norm.normalized) {
        strip.style.display = 'none';
        tahminStrip.style.display = 'none';
        var qEl = document.getElementById('dmQuoteAssetName');
        if (qEl) qEl.textContent = 'USDT';
        var fb = document.getElementById('fBudget');
        if (fb) fb.placeholder = 'Kullanılabilir: —';
        return;
    }
    const sym = norm.normalized;
    if (!opts.preserveDropdown && sym && sym !== _dmModalStripSymbol) {
        hideCreateModalSymbolDropdown();
        _dmModalStripSymbol = sym;
    }
    const { base, quote } = parseBaseQuote(sym);
    strip.style.display = 'flex';
    tahminStrip.style.display = 'block';
    var quoteNameEl = document.getElementById('dmQuoteAssetName');
    if (quoteNameEl) quoteNameEl.textContent = quote || 'USDT';
    var fBudget = document.getElementById('fBudget');
    if (fBudget) {
        fBudget.placeholder = formatAvailableQuotePlaceholder(quote || 'USDT', getAvailableQuoteInWallet(quote || 'USDT'));
    }
    if (baseEl) baseEl.textContent = base || '—';
    if (pairEl) pairEl.textContent = sym;
    if (logoEl && typeof getCoinLogoUrl === 'function') {
        if (base !== dmModalLastLogoBase) {
            dmModalLastLogoBase = base;
            const url = getCoinLogoUrl(base);
            const initials = (base || ' ').substring(0, 2).toUpperCase();
            logoEl.innerHTML = url
                ? '<img src="' + url + '" alt="' + base + '" loading="lazy" onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'flex\';" /><span class="varlik-logo-initials" style="display:none">' + initials + '</span>'
                : '<span class="varlik-logo-initials">' + initials + '</span>';
            logoEl.title = base;
        }
    }
    const mini = window.marketStore && window.marketStore.getMini(sym);
    const price = (mini && mini.last != null) ? mini.last : (window.marketStore && window.marketStore.getPrice(sym));
    const pct = resolveDmModalChangePct(mini);
    if (priceEl) {
        if (price != null && Number.isFinite(price)) {
            const newText = (quote === 'USDT' || quote === 'FDUSD' ? fmtUsd(price) : fmtNum(price, 8) + ' ' + quote);
            if (priceEl.textContent !== newText) {
                var blinkGrace = (typeof dmModalOpenTs === 'number' && (Date.now() - dmModalOpenTs) < 600);
                if (!blinkGrace && dmModalLastPrice != null && Number.isFinite(dmModalLastPrice) && Math.abs(price - dmModalLastPrice) > 1e-10 && typeof triggerValueBlink === 'function') {
                    triggerValueBlink(priceEl, price);
                }
                dmModalLastPrice = price;
                priceEl.textContent = newText;
            }
        } else {
            if (priceEl.textContent !== '—') {
                priceEl.textContent = '—';
                dmModalLastPrice = null;
            }
        }
    }
    if (changeEl) applyDmModalPctEl(changeEl, pct);
    // Grafik sadece sembol değiştiğinde yeniden yüklensin (her tick'te yüklemek flicker yapıyor)
    if (sym !== dmModalLastChartSymbol) {
        dmModalLastChartSymbol = sym;
        loadCreateBotModalChart(sym);
    }
    updateCreateBotModalTahmin(sym, mini, quote);
    var needTicker = sym !== _dmModalLastTickerFetchSymbol || !(price != null && Number.isFinite(price)) || (Date.now() - _dmModalTickerFetchTs) >= DM_MODAL_TAHMIN_MIN_MS;
    if (needTicker) fetchCreateBotModalTicker24h(sym, { force: sym !== _dmModalLastTickerFetchSymbol });
    // Canlı fiyat: modal açık ve sembol seçiliyse periyodik güncelleme başlat
    if (!dmModalLivePriceIntervalId && document.getElementById('dmModal') && document.getElementById('dmModal').style.display !== 'none') {
        dmModalLivePriceIntervalId = setInterval(function () {
            var modal = document.getElementById('dmModal');
            var fSym = document.getElementById('fSymbol');
            if (!modal || modal.style.display === 'none' || !fSym || !fSym.value.trim()) return;
            if (document.activeElement === fSym || isCreateModalSymbolDropdownOpen()) return;
            var currentSym = normalizeModalSymbol(fSym.value.trim());
            if (currentSym.normalized) updateCreateBotModalPairStrip(currentSym.normalized, { preserveDropdown: true });
        }, DM_MODAL_LIVE_PRICE_MS);
    }
}

/** Create bot modal: Tahmin alanını (24s değişim, yüksek/düşük) önbellekten doldur; veri ticker_24h ile gelir. */
function updateCreateBotModalTahmin(symbol, mini, quoteAsset) {
    const changeEl = document.getElementById('dmTahminChange');
    const highEl = document.getElementById('dmTahminHigh');
    const lowEl = document.getElementById('dmTahminLow');
    const formatPrice = (v) => (v != null && Number.isFinite(v) && v > 0) ? (quoteAsset === 'USDT' || quoteAsset === 'FDUSD' ? fmtUsd(v) : fmtNum(v, 8)) : '—';
    if (changeEl) applyDmModalPctEl(changeEl, resolveDmModalChangePct(mini));
    if (!symbol) return;
    if (symbol !== dmModalLastTahminSymbol) {
        dmModalLastTahminSymbol = symbol;
        dmModalTahminHigh = null;
        dmModalTahminLow = null;
        if (highEl) highEl.textContent = '—';
        if (lowEl) lowEl.textContent = '—';
    }
    var miniHigh = mini && mini.high != null ? Number(mini.high) : null;
    var miniLow = mini && mini.low != null ? Number(mini.low) : null;
    if (miniHigh != null && Number.isFinite(miniHigh) && miniHigh > 0) {
        dmModalTahminHigh = miniHigh;
        if (highEl) highEl.textContent = formatPrice(miniHigh);
    } else if (dmModalTahminHigh != null && highEl) {
        highEl.textContent = formatPrice(dmModalTahminHigh);
    }
    if (miniLow != null && Number.isFinite(miniLow) && miniLow > 0) {
        dmModalTahminLow = miniLow;
        if (lowEl) lowEl.textContent = formatPrice(miniLow);
    } else if (dmModalTahminLow != null && lowEl) {
        lowEl.textContent = formatPrice(dmModalTahminLow);
    }
}

/** Create bot modal: mini grafik yükle (dmPairChart) */
async function loadCreateBotModalChart(symbol) {
    const container = document.getElementById('dmPairChart');
    if (!container) return;
    const norm = normalizeModalSymbol(symbol || '');
    if (norm.invalid || !norm.normalized) {
        container.innerHTML = '';
        return;
    }
    const chartSymbol = norm.normalized;
    const invalidChartSymbols = ['USDTUSDT', 'USDCUSDT', 'FDUSDUSDT', 'BUSDUSDT', 'TUSDUSDT', 'DAIUSDT'];
    if (invalidChartSymbols.includes(chartSymbol)) {
        container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--ds-text-tertiary);font-size:0.75rem;">—</div>';
        return;
    }
    var hadContent = container.querySelector('svg');
    if (!hadContent) container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--ds-text-secondary);font-size:0.8rem;">Yükleniyor...</div>';
    try {
        const data = await window.apiClient.get('/api/spot/klines?symbol=' + encodeURIComponent(chartSymbol) + '&interval=5m&limit=288');
        if (!Array.isArray(data) || data.length < 2) {
            container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--ds-text-secondary);font-size:0.75rem;">Veri yok</div>';
            return;
        }
        const points = data.map(k => ({ t: Number(k.t), o: Number(k.o), h: Number(k.h), l: Number(k.l), c: Number(k.c) }));
        const dataMin = Math.min(...points.map(p => p.l));
        const dataMax = Math.max(...points.map(p => p.h));
        const range = dataMax - dataMin || 1;
        const w = 260;
        const h = 100;
        const pad = 12;
        const linePoints = points.map((p, i) => {
            const x = pad + (i / (points.length - 1 || 1)) * (w - 2 * pad);
            const y = pad + (1 - (p.c - dataMin) / range) * (h - 2 * pad);
            return { x, y };
        });
        const pathD = linePoints.map((p, i) => (i === 0 ? 'M' : 'L') + ' ' + p.x + ' ' + p.y).join(' ');
        const first = points[0].c;
        const last = points[points.length - 1].c;
        const isUp = last >= first;
        const stroke = isUp ? '#00C076' : '#F6465D';
        container.innerHTML = '<svg width="100%" height="100%" viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none"><defs><linearGradient id="dmChartGrad" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="' + stroke + '" stop-opacity="0.25"/><stop offset="1" stop-color="' + stroke + '" stop-opacity="0"/></linearGradient></defs><path d="' + pathD + ' L ' + linePoints[linePoints.length - 1].x + ' ' + (h - pad) + ' L ' + pad + ' ' + (h - pad) + ' Z" fill="url(#dmChartGrad)" stroke="' + stroke + '" stroke-width="1.5" fill-opacity="1"/></svg>';
    } catch (e) {
        if (typeof window.__DEBUG_DASH__ !== 'undefined' && window.__DEBUG_DASH__) console.warn('[dashboard] loadCreateBotModalChart error:', e);
        container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--ds-text-tertiary);font-size:0.75rem;">—</div>';
    }
}

var SYMBOL_SEARCH_STOP_WORDS = { COIN: 1, TOKEN: 1, PARITE: 1, PAIR: 1, CRYPTO: 1, KRIPTO: 1, PARITY: 1 };
/** Binance quote varlıkları (uzun sonek önce denenir) — USDT + çapraz (ETH/BTC/BNB/…) */
var SYMBOL_SEARCH_QUOTE_SUFFIXES = [
    'USDT', 'FDUSD', 'USDC', 'BUSD', 'TUSD', 'DAI', 'USDD',
    'BTC', 'ETH', 'BNB', 'SOL', 'XRP', 'DOGE', 'TRX', 'TRY', 'EUR', 'GBP', 'BRL', 'AUD', 'RUB', 'IDR', 'UAH'
];
var INVALID_TRADING_PAIR_SYMBOLS = new Set(['USDTUSDT', 'USDCUSDT', 'FDUSDUSDT', 'BUSDUSDT', 'TUSDUSDT', 'DAIUSDT']);
/** scope=all coin-list sembolleri — geçerli parite doğrulama */
var binanceTradingSymbolsSet = null;

function tradingPairQuotesByLength() {
    return SYMBOL_SEARCH_QUOTE_SUFFIXES.slice().sort(function (a, b) { return b.length - a.length; });
}

/** Binance paritesi: quote sonekleri uzundan kısaya; tabanda ikinci quote yok (BNBFDUSD+USDT engeli). */
function parseTradingPairSymbol(symbol) {
    var s = (symbol || '').toUpperCase().replace(/[\s\/\-]/g, '');
    if (!s) return { base: '', quote: '', normalized: '', valid: false };
    if (s === 'USDTUSD') return { base: 'USDT', quote: 'USD', normalized: 'USDTUSD', valid: true };
    if (INVALID_TRADING_PAIR_SYMBOLS.has(s)) return { base: '', quote: '', normalized: s, valid: false };
    var quotes = tradingPairQuotesByLength();
    for (var i = 0; i < quotes.length; i++) {
        var q = quotes[i];
        if (!s.endsWith(q) || s.length <= q.length) continue;
        var base = s.slice(0, -q.length);
        if (!base || base === q) continue;
        var nested = false;
        for (var j = 0; j < quotes.length; j++) {
            var q2 = quotes[j];
            if (base.endsWith(q2) && base.length > q2.length) {
                nested = true;
                break;
            }
        }
        if (!nested) {
            return { base: base, quote: q, normalized: base + q, valid: true };
        }
    }
    return { base: s, quote: '', normalized: s, valid: false };
}

function rebuildBinanceTradingSymbolSet() {
    var syms = coinListAllScopeSymbols.length > 0
        ? coinListAllScopeSymbols
        : (coinListAllBinanceSymbols.length > 0 ? coinListAllBinanceSymbols : []);
    binanceTradingSymbolsSet = syms.length > 0 ? new Set(syms) : null;
}

function isValidTradingPairSymbol(symbol) {
    var s = (symbol || '').toUpperCase().replace(/[\s\/\-]/g, '');
    if (!s || INVALID_TRADING_PAIR_SYMBOLS.has(s)) return false;
    if (binanceTradingSymbolsSet && binanceTradingSymbolsSet.size > 0) {
        return binanceTradingSymbolsSet.has(s);
    }
    return parseTradingPairSymbol(s).valid;
}

function formatTradingPairDisplay(symbol) {
    var pq = parseTradingPairSymbol(symbol);
    if (!pq.valid) return (symbol || '').toUpperCase() || '—';
    if (pq.normalized === 'USDTUSD') return 'USDT/USD';
    return pq.base + '/' + pq.quote;
}

function normalizeSymbolSearchQuery(raw) {
    var s = (raw || '').trim().toUpperCase();
    if (!s) return { compact: '', tokens: [], primary: '' };
    var tokens = s.split(/[\s,\/\-]+/).filter(Boolean).filter(function (t) { return !SYMBOL_SEARCH_STOP_WORDS[t]; });
    var compact = (tokens.length ? tokens.join('') : s.replace(/[\s,\/\-]+/g, ''));
    var primary = tokens[0] || compact;
    return { compact: compact, tokens: tokens, primary: primary };
}

function parseBaseQuoteForSearch(symbol) {
    var pq = parseTradingPairSymbol(symbol);
    return { base: pq.base || '', quote: pq.quote || '' };
}

function coinListSearchQuoteOrder(sym) {
    if ((sym || '').endsWith('USDT')) return 0;
    if ((sym || '').endsWith('FDUSD')) return 1;
    if ((sym || '').endsWith('USDC')) return 2;
    if ((sym || '').endsWith('BTC')) return 3;
    if ((sym || '').endsWith('ETH')) return 4;
    if ((sym || '').endsWith('BNB')) return 5;
    return 6;
}

/** "xrp eth", "XRP/ETH" → XRPETH vb. aday semboller */
function resolveSearchSymbolCandidates(qn) {
    var out = [];
    var seen = {};
    function add(sym) {
        var s = (sym || '').toUpperCase();
        if (!s || seen[s] || !isValidTradingPairSymbol(s)) return;
        seen[s] = true;
        out.push(s);
    }
    var tokens = (qn && qn.tokens) ? qn.tokens : [];
    if (tokens.length >= 2) {
        add(tokens[0] + tokens[1]);
        add(tokens[1] + tokens[0]);
    }
    var needle = (qn && (qn.primary || qn.compact)) || '';
    if (needle && /^[A-Z0-9]{2,12}$/.test(needle)) {
        for (var i = 0; i < SYMBOL_SEARCH_QUOTE_SUFFIXES.length; i++) {
            add(needle + SYMBOL_SEARCH_QUOTE_SUFFIXES[i]);
        }
    }
    return out;
}

function symbolSearchMatchScore(symbol, qn) {
    var sym = (symbol || '').toUpperCase();
    if (!sym || !qn) return -1;
    var compact = qn.compact || '';
    var primary = qn.primary || compact;
    if (!primary && !compact) return -1;
    var pq = parseBaseQuoteForSearch(sym);
    var base = pq.base || '';
    var quote = pq.quote || '';
    if (qn.tokens.length >= 2) {
        var t0 = qn.tokens[0];
        var t1 = qn.tokens[1];
        if (base === t0 && quote === t1) return 99;
        if (sym === t0 + t1 || sym === t1 + t0) return 92;
    }
    if (compact && sym.indexOf(compact) !== -1) return 100;
    if (qn.tokens.length) {
        if (base === primary) return 95;
        if (base.indexOf(primary) === 0) return 88;
        if (primary.length >= 2 && base.indexOf(primary) !== -1) return 82;
        var allInSym = qn.tokens.every(function (t) { return sym.indexOf(t) !== -1; });
        if (allInSym) return 75;
        return -1;
    }
    if (base === primary) return 95;
    if (primary.length >= 2 && base.indexOf(primary) === 0) return 88;
    if (primary.length >= 2 && base.indexOf(primary) !== -1) return 82;
    if (compact && sym.indexOf(compact) !== -1) return 70;
    return -1;
}

function getCoinListSearchRows() {
    if (coinListSearchAllSymbols.length > 0) return coinListSearchAllSymbols;
    var fromScope = (coinListAllScopeSymbols || []).map(function (symbol) {
        var mini = window.marketStore && window.marketStore.getMini && window.marketStore.getMini(symbol);
        return { symbol: symbol, last: mini && mini.last, changePct: mini && mini.changePct };
    });
    if (fromScope.length > 0) return fromScope;
    if (window.marketStore && window.marketStore.getAllMini) {
        return (window.marketStore.getAllMini() || []).map(function (m) {
            return { symbol: (m.symbol || '').toUpperCase(), last: m.last, changePct: m.changePct };
        }).filter(function (x) { return x.symbol; });
    }
    return [];
}

function filterCoinListForSearch(query, maxResults, minLen) {
    maxResults = maxResults || 60;
    minLen = minLen != null ? minLen : 2;
    var qn = normalizeSymbolSearchQuery(query);
    var needle = qn.primary || qn.compact || '';
    if (needle.length < minLen) return [];
    var rows = getCoinListSearchRows();
    var scored = [];
    for (var i = 0; i < rows.length; i++) {
        var row = rows[i];
        var score = symbolSearchMatchScore(row.symbol, qn);
        if (score < 0 || !isValidTradingPairSymbol(row.symbol)) continue;
        scored.push({ row: row, score: score });
    }
    scored.sort(function (a, b) {
        if (b.score !== a.score) return b.score - a.score;
        var qA = coinListSearchQuoteOrder(a.row.symbol);
        var qB = coinListSearchQuoteOrder(b.row.symbol);
        if (qA !== qB) return qA - qB;
        return (a.row.symbol || '').localeCompare(b.row.symbol || '');
    });
    var list = scored.slice(0, maxResults).map(function (x) { return x.row; });
    if (list.length === 0) {
        list = resolveSearchSymbolCandidates(qn).map(function (sym) {
            var mini = window.marketStore && window.marketStore.getMini && window.marketStore.getMini(sym);
            return { symbol: sym, last: mini && mini.last, changePct: mini && mini.changePct };
        });
    }
    return list.slice(0, maxResults);
}

if (typeof window !== 'undefined') {
    window.parseTradingPairSymbol = parseTradingPairSymbol;
    window.isValidTradingPairSymbol = isValidTradingPairSymbol;
    window.formatTradingPairDisplay = formatTradingPairDisplay;
}

function isCreateModalSymbolDropdownOpen() {
    const dropdown = document.getElementById('dmSymbolSearchDropdown');
    return !!(dropdown && dropdown.style.display === 'block');
}

function paintCreateModalSymbolDropdown(list, emptyHtml) {
    const dropdown = document.getElementById('dmSymbolSearchDropdown');
    if (!dropdown) return;
    if (!list || !list.length) {
        dropdown.innerHTML = emptyHtml || '<div style="padding: 1rem; color: var(--ds-text-secondary); font-size: 0.9rem;">Sonuç yok. Pariteyi elle yazın (örn. BTCUSDT, XRPETH).</div>';
    } else {
        dropdown.innerHTML = list.map(function (item) {
            return renderCoinSearchDropdownItemHtml(item, 'dm-symbol-search-item');
        }).join('');
    }
    dropdown.style.display = 'block';
    dropdown.style.pointerEvents = 'auto';
}

function showCreateModalSymbolDropdownSuggestions() {
    const fSym = document.getElementById('fSymbol');
    var rows = getCoinListSearchRows();
    if (!rows.length) {
        paintCreateModalSymbolDropdown(null, '<div style="padding: 1rem; color: var(--ds-text-secondary); font-size: 0.9rem;">Sembol listesi yükleniyor…</div>');
        ensureCoinListSearchSymbolsLoaded('all').then(function () {
            buildCoinListSearchSymbols();
            if (fSym && document.activeElement === fSym) showCreateModalSymbolDropdownSuggestions();
        });
        return;
    }
    var list = rows.slice(0, 50);
    paintCreateModalSymbolDropdown(list);
    var priceGen = _dmSymbolSearchPriceGen;
    queueCoinSearchPriceFetch(list.map(function (it) { return it.symbol; }), function () {
        if (priceGen !== _dmSymbolSearchPriceGen) return;
        if (!fSym || document.activeElement !== fSym) return;
        if (!isCreateModalSymbolDropdownOpen()) return;
        showCreateModalSymbolDropdownSuggestions();
    });
}

/** Create modal: sembol arama dropdown göster (fSymbol için) */
function showCreateModalSymbolDropdown(query, minLen) {
    const fSym = document.getElementById('fSymbol');
    const dropdown = document.getElementById('dmSymbolSearchDropdown');
    if (!dropdown) return;
    minLen = minLen != null ? minLen : 2;
    const qn = normalizeSymbolSearchQuery(query);
    const needle = qn.primary || qn.compact || '';
    if (!needle || needle.length < minLen) {
        if (minLen <= 1 && needle.length === 0) showCreateModalSymbolDropdownSuggestions();
        else hideCreateModalSymbolDropdown();
        return;
    }
    let list = filterCoinListForSearch(query, 60, minLen);
    if (list.length === 0) {
        paintCreateModalSymbolDropdown(null);
        return;
    }
    paintCreateModalSymbolDropdown(list);
    var priceGen = _dmSymbolSearchPriceGen;
    queueCoinSearchPriceFetch(list.map(function (it) { return it.symbol; }), function () {
        if (priceGen !== _dmSymbolSearchPriceGen) return;
        if (!fSym || document.activeElement !== fSym) return;
        if (!isCreateModalSymbolDropdownOpen()) return;
        var v = (fSym.value || '').trim();
        if (v.length < minLen) return;
        showCreateModalSymbolDropdown(v, minLen);
    });
}

function hideCreateModalSymbolDropdown() {
    _dmSymbolSearchPriceGen++;
    _dmSymbolSearchPicking = false;
    const dropdown = document.getElementById('dmSymbolSearchDropdown');
    if (dropdown) {
        dropdown.style.display = 'none';
        dropdown.style.pointerEvents = 'none';
    }
}

function bindDmSymbolSearchOutsideClose() {
    if (_dmSymbolSearchOutsideBound) return;
    _dmSymbolSearchOutsideBound = true;
    document.addEventListener('mousedown', function (e) {
        var modal = document.getElementById('dmModal');
        if (!modal || modal.style.display === 'none') return;
        if (!isCreateModalSymbolDropdownOpen()) return;
        var fSym = document.getElementById('fSymbol');
        var wrap = fSym && fSym.closest('.coin-list-search-wrap');
        if (wrap && wrap.contains(e.target)) return;
        hideCreateModalSymbolDropdown();
    });
}

var _dmMultiSearchTargetInput = null;
var _dmMultiSearchTargetIdx = null;

function showMultiSymbolSearchDropdown(query, anchorInputEl) {
    const dropdown = document.getElementById('dmMultiSymbolSearchDropdown');
    if (!dropdown || !anchorInputEl) return;
    const qn = normalizeSymbolSearchQuery(query);
    const needle = qn.primary || qn.compact || '';
    if (!needle || needle.length < 2) {
        dropdown.style.display = 'none';
        return;
    }
    _dmMultiSearchTargetInput = anchorInputEl;
    _dmMultiSearchTargetIdx = anchorInputEl.getAttribute('data-idx');
    var list = filterCoinListForSearch(query, 60);
    if (list.length === 0) {
        dropdown.innerHTML = '<div style="padding: 1rem; color: var(--ds-text-secondary); font-size: 0.9rem;">Sonuç yok. Sembolü elle yazın (örn. BTC).</div>';
        dropdown.style.display = 'block';
    } else {
        dropdown.innerHTML = list.map(function (item) {
            return renderCoinSearchDropdownItemHtml(item, 'dm-multi-symbol-item');
        }).join('');
        dropdown.style.display = 'block';
        queueCoinSearchPriceFetch(list.map(function (it) { return it.symbol; }), function () {
            if (_dmMultiSearchTargetInput && (anchorInputEl.value || '').trim()) {
                showMultiSymbolSearchDropdown(anchorInputEl.value, anchorInputEl);
            }
        });
    }
    var rect = anchorInputEl.getBoundingClientRect();
    dropdown.style.left = rect.left + 'px';
    dropdown.style.top = (rect.bottom + 4) + 'px';
    dropdown.style.width = Math.max(rect.width, 320) + 'px';
}

function hideMultiSymbolSearchDropdown() {
    var dropdown = document.getElementById('dmMultiSymbolSearchDropdown');
    if (dropdown) dropdown.style.display = 'none';
    _dmMultiSearchTargetInput = null;
    _dmMultiSearchTargetIdx = null;
}

function updateMultiAssetPreview(idx, symbol, liveOnly) {
    var sym = (symbol || '').trim().toUpperCase().replace(/\s/g, '');
    if (!sym) sym = '';
    if (sym && !sym.endsWith('USDT')) sym = sym + 'USDT';
    var previewEl = document.querySelector('#multiAssetRows .multi-asset-row[data-idx="' + idx + '"] .multi-asset-preview');
    if (!previewEl) return;
    if (!sym || sym === 'USDT') {
        previewEl.innerHTML = '—';
        previewEl.classList.add('multi-asset-preview-empty');
        previewEl.style.display = 'block';
        return;
    }
    previewEl.classList.remove('multi-asset-preview-empty');
    var mini = window.marketStore && window.marketStore.getMini(sym);
    var price = (mini && mini.last != null) ? mini.last : (window.marketStore && window.marketStore.getPrice && window.marketStore.getPrice(sym));
    var pct = mini && mini.changePct != null ? mini.changePct : null;
    var priceStr = price != null && Number.isFinite(price) ? fmtUsd(price) : '—';
    var pctStr = pct != null && Number.isFinite(pct) ? (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%' : '—';
    var pctColor = pct != null ? (pct >= 0 ? '#0ecb81' : '#f6465d') : 'var(--ds-text-secondary)';
    var highStr = '—';
    var lowStr = '—';
    if (liveOnly) {
        var highVal = previewEl.querySelector('.multi-preview-high-val');
        var lowVal = previewEl.querySelector('.multi-preview-low-val');
        if (highVal) highStr = highVal.textContent || '—';
        if (lowVal) lowStr = lowVal.textContent || '—';
    }
    previewEl.innerHTML = '<div style="display: flex; flex-wrap: wrap; gap: 12px 16px; align-items: center;"><span><strong>Fiyat:</strong> ' + priceStr + '</span><span style="color: ' + pctColor + '"><strong>24s:</strong> ' + pctStr + '</span><span class="multi-preview-high"><strong>24s yüksek:</strong> <span class="multi-preview-high-val">' + highStr + '</span></span><span class="multi-preview-low"><strong>24s düşük:</strong> <span class="multi-preview-low-val">' + lowStr + '</span></span></div>';
    previewEl.style.display = 'block';
    if (liveOnly) return;
    window.apiClient.get('/api/spot/klines?symbol=' + encodeURIComponent(sym) + '&interval=5m&limit=288').then(function (data) {
        if (Array.isArray(data) && data.length > 0) {
            var low = Math.min.apply(null, data.map(function (k) { return Number(k.l); }));
            var high = Math.max.apply(null, data.map(function (k) { return Number(k.h); }));
            var highVal = previewEl.querySelector('.multi-preview-high-val');
            var lowVal = previewEl.querySelector('.multi-preview-low-val');
            if (highVal) highVal.textContent = fmtUsd(high);
            if (lowVal) lowVal.textContent = fmtUsd(low);
        }
    }).catch(function () {});
}

function collectForm() {
    const symbol = normalizeSymbol(document.getElementById("fSymbol").value);
    const budget = parseFloat(document.getElementById("fBudget").value);
    const basePct = parseFloat(document.getElementById("fBasePct").value);
    const quotePct = parseFloat(document.getElementById("fQuotePct").value);
    
    const upCount = parseInt(document.getElementById("fUpCount").value) || 0;
    const upTrail = parseDecimal(document.getElementById("fUpTrail")?.value, 0.5);
    const upGrids = [];
    for (let i = 0; i < upCount; i++) {
        const trigger = parseFloat(document.getElementById(`upGrid_${i}_trigger`)?.value);
        const qty = parseFloat(document.getElementById(`upGrid_${i}_qty`)?.value);
        if (Number.isFinite(trigger) && Number.isFinite(qty)) {
            upGrids.push({ trigger_pct: trigger, qty_pct: qty });
        }
    }

    const downCount = parseInt(document.getElementById("fDownCount").value) || 0;
    const downTrail = parseDecimal(document.getElementById("fDownTrail")?.value, 0.5);
    const downGrids = [];
    for (let i = 0; i < downCount; i++) {
        const trigger = parseFloat(document.getElementById(`downGrid_${i}_trigger`)?.value);
        const qty = parseFloat(document.getElementById(`downGrid_${i}_qty`)?.value);
        if (Number.isFinite(trigger) && Number.isFinite(qty)) {
            downGrids.push({ trigger_pct: trigger, qty_pct: qty });
        }
    }
    
    const rebuyTrigger = parseDecimal(document.getElementById("fRebuyTrigger")?.value, 1.5);
    const rebuyTrail = parseDecimal(document.getElementById("fRebuyTrail")?.value, 0.3);
    const resellTrigger = parseDecimal(document.getElementById("fResellTrigger")?.value, 1.5);
    const resellTrail = parseDecimal(document.getElementById("fResellTrail")?.value, 0.5);
    
    return {
        account_id: State.accountId,
        symbol: symbol,
        strategy_id: "dca_grid_trailing",
        budget_usd: budget,
        initial_capital_usdt: budget,
        allocation: { base_pct: basePct, quote_pct: quotePct },
        up: { trail_pct: upTrail, grids: upGrids },
        down: { trail_pct: downTrail, grids: downGrids },
        profit: {
            rebuy_trigger_pct: rebuyTrigger,
            rebuy_trail_pct: rebuyTrail,
            resell_trigger_pct: resellTrigger,
            resell_trail_pct: resellTrail
        }
    };
}

/** Cüzdan satırında bot/emir kilidi düşülmüş kullanılabilir miktar (varlıklar tablosu ile aynı). */
function getWalletAssetAvailableQty(assetRow) {
    if (!assetRow || typeof assetRow !== 'object') return null;
    var free = parseFloat(assetRow.free);
    if (!Number.isFinite(free)) return null;
    if (assetRow.available != null && Number.isFinite(Number(assetRow.available))) {
        return Number(assetRow.available);
    }
    var botLocked = Number(assetRow.bot_locked) || 0;
    return Math.max(0, free - botLocked);
}

/** Modal için cüzdandaki kullanılabilir quote (USDT vb.) miktarı. Veri yoksa null. */
function getAvailableQuoteInWallet(quoteAsset) {
    var quote = (quoteAsset || "USDT").toString().trim().toUpperCase();
    if (!quote) return null;
    var assets = (typeof assetsState !== "undefined" && assetsState.wallet && assetsState.wallet.assets) ? assetsState.wallet.assets : [];
    for (var i = 0; i < assets.length; i++) {
        if ((assets[i].asset || "").toUpperCase() === quote) {
            return getWalletAssetAvailableQty(assets[i]);
        }
    }
    return null;
}

function formatAvailableQuotePlaceholder(quoteAsset, availableQty) {
    var quote = (quoteAsset || "USDT").toString().trim().toUpperCase() || "USDT";
    if (availableQty == null || !Number.isFinite(availableQty)) return "Kullanılabilir: —";
    var dec = (quote === "USDT" || quote === "BUSD" || quote === "FDUSD") ? 2 : 8;
    return "Kullanılabilir: " + fmtNum(availableQty, dec) + " " + quote;
}

function updateDcaBudgetPlaceholder() {
    var modal = document.getElementById("dmModal");
    var wizard = document.getElementById("dmWizardDca");
    if (!modal || modal.style.display === "none" || !wizard || wizard.style.display === "none") return;
    var fBudget = document.getElementById("fBudget");
    if (!fBudget) return;
    var sym = ((document.getElementById("fSymbol") || {}).value || "").trim();
    var quote = "USDT";
    if (sym) {
        try { quote = parseBaseQuote(normalizeSymbol(sym)).quote || "USDT"; } catch (e) {}
    } else {
        var qEl = document.getElementById("dmQuoteAssetName");
        if (qEl && qEl.textContent) quote = qEl.textContent.trim() || "USDT";
    }
    fBudget.placeholder = formatAvailableQuotePlaceholder(quote, getAvailableQuoteInWallet(quote));
}

function validateForm(payload) {
    if (!payload.symbol || !/^[A-Z0-9]+$/.test(payload.symbol)) {
        return "Geçersiz parite formatı";
    }
    if (!payload.budget_usd || payload.budget_usd < 10) {
        return "Bütçe en az 10 USD olmalı";
    }
    if (payload.allocation.base_pct + payload.allocation.quote_pct !== 100) {
        return "Base ve Quote toplamı 100 olmalı";
    }
    var gridErr = validateDcaGridNotionals(payload);
    if (gridErr) return gridErr;
    return null;
}

function showCreateBotFormError(errorEl, message) {
    if (!errorEl) return;
    errorEl.textContent = message || "";
    errorEl.style.display = message ? "block" : "none";
    if (message) {
        try { errorEl.scrollIntoView({ behavior: "smooth", block: "nearest" }); } catch (e) {}
    }
}

/** Tahmini grid emir tutarı (USDT) — backend config_validate ile uyumlu */
function validateDcaGridNotionals(payload) {
    var MIN = 10;
    var buffer = 0.995;
    var budget = Number(payload.budget_usd || payload.initial_capital_usdt) || 0;
    if (budget <= 0) return null;
    var basePct = Number(payload.allocation && payload.allocation.base_pct) || 50;
    var quotePct = Number(payload.allocation && payload.allocation.quote_pct) || 50;
    var baseUsd = budget * basePct / 100 * buffer;
    var quoteUsd = budget * quotePct / 100 * buffer;
    var bad = [];
    var minBudgetCandidates = [];
    var upGrids = (payload.up && payload.up.grids) || [];
    var downGrids = (payload.down && payload.down.grids) || [];

    function legMinBudget(sidePct, qtyPct) {
        var denom = (sidePct / 100) * (qtyPct / 100) * buffer;
        if (denom <= 0) return null;
        return Math.ceil((MIN + 0.001) / denom * 100) / 100;
    }

    upGrids.forEach(function (g, i) {
        var qtyPct = Number(g.qty_pct);
        if (!Number.isFinite(qtyPct) || qtyPct <= 0) return;
        var n = baseUsd * qtyPct / 100;
        var legMin = legMinBudget(basePct, qtyPct);
        if (legMin != null) minBudgetCandidates.push(legMin);
        if (n <= MIN) bad.push({ side: "Satış", idx: i + 1, n: n, pct: qtyPct });
    });
    downGrids.forEach(function (g, i) {
        var qtyPct = Number(g.qty_pct);
        if (!Number.isFinite(qtyPct) || qtyPct <= 0) return;
        var n = quoteUsd * qtyPct / 100;
        var legMin = legMinBudget(quotePct, qtyPct);
        if (legMin != null) minBudgetCandidates.push(legMin);
        if (n <= MIN) bad.push({ side: "Alım", idx: i + 1, n: n, pct: qtyPct });
    });
    if (!bad.length) return null;
    var minBudget = minBudgetCandidates.length ? Math.max.apply(null, minBudgetCandidates) : null;
    var parts = ["Bot oluşturulamaz: en az bir grid emri 10 USDT altında kalıyor (Binance limiti)."];
    bad.forEach(function (b) {
        parts.push(b.side + " grid #" + b.idx + ": tahmini " + b.n.toFixed(2) + " USDT (grid başına en az " + MIN + " USDT gerekir, miktar %" + b.pct + ").");
    });
    if (minBudget != null && minBudget > 0) {
        parts.push("Bu parametrelerle bot için minimum bütçe: " + minBudget.toFixed(2) + " USDT (girdiğiniz: " + budget.toFixed(2) + " USDT).");
    } else {
        parts.push("Bütçeyi artırın, grid sayısını azaltın veya grid miktar yüzdelerini yükseltin.");
    }
    return parts.join(" ");
}

async function createBot() {
    const errorEl = document.getElementById("createBotError");
    if (errorEl) errorEl.style.display = "none";
    
    const payload = collectForm();
    const error = validateForm(payload);
    
    if (error) {
        showCreateBotFormError(errorEl, error);
        return;
    }

    var requestedBudget = 0;
    var quoteAsset = "USDT";
    requestedBudget = Number(payload.budget_usd) || 0;
    try {
        var pq = parseBaseQuote(payload.symbol || "");
        quoteAsset = (pq && pq.quote) ? pq.quote : "USDT";
    } catch (e) { quoteAsset = "USDT"; }
    if (requestedBudget > 0) {
        var availableQuote = getAvailableQuoteInWallet(quoteAsset);
        if (availableQuote == null || availableQuote === undefined) {
            if (errorEl) {
                errorEl.textContent = "Bakiye bilgisi yüklenemedi. Lütfen sayfayı yenileyin veya kısa süre sonra tekrar deneyin.";
                errorEl.style.display = "block";
            }
            return;
        }
        if (!Number.isFinite(availableQuote)) availableQuote = 0;
        if (requestedBudget > availableQuote) {
            var fmt = (quoteAsset === "USDT" || quoteAsset === "BUSD" || quoteAsset === "FDUSD") && typeof fmtNum === "function" ? fmtNum(availableQuote, 2) : (availableQuote.toFixed(2));
            if (errorEl) {
                errorEl.textContent = "Bakiye yetersiz. Bot bütçesi: " + requestedBudget + " " + quoteAsset + ", kullanılabilir: " + fmt + " " + quoteAsset + ". Bütçeyi düşürün veya cüzdana bakiye ekleyin.";
                errorEl.style.display = "block";
            }
            return;
        }
    }
    
    try {
        const body = {
            account_id: payload.account_id,
            config_json: JSON.stringify(payload)
        };
        // REFACTOR: Use apiClient instead of fetch
        const data = await window.apiClient.post("/api/bots/create", body);
        const botId = data.bot_id || data.id;
        
        if (window.Toast) {
            window.Toast.success("Bot oluşturuldu");
        }
        try { localStorage.setItem(DASHBOARD_LAST_CREATE_BOT_PARAMS, JSON.stringify(payload)); } catch (e) {}
        
        closeCreateBotModal();
        
        // Refresh bots list
        await loadSummary(State.accountId);
        
    } catch (error) {
        console.error("[dashboard] createBot error:", error);
        if (errorEl) {
            const msg = (error && error.message) || (typeof error === "string" ? error : "Bilinmeyen hata");
            errorEl.textContent = "Hata: " + msg;
            errorEl.style.display = "block";
        }
    }
}

// Refresh button - removed
function bindRefresh() {
    // Refresh button removed from UI
    // No-op function since button was removed
}

// SIMPLIFIED: Filter and sort (disabled for now - always show all bots)
let botsSortOrder = 'default';
let botsFilter = 'all';

function bindBotsActions() {
    // Filter and sort buttons removed - no longer needed
}

// ========== Binance Modal ==========

// ========== Binance Tab Functions ==========

// ---------- BinanceAssetsPanel (rebuilt): wallet + marketStore separation, fast price tick, leak-free ----------
const PRICE_UI_TICK_MS = 1000;
const WALLET_POLL_MS = 15000; // 15sn; backend TTL 15s + in-flight dedupe, flicker azaltma
const QUOTE = 'USDT';
const WALLET_BACKOFF_MIN = 5000;
const WALLET_BACKOFF_MAX = 60000;
var walletPollBackoffUntil = 0; // 429 sonrası bir süre poll atlanır (Date.now() + ms)
const LOADING_HTML = '<tr><td colspan="7" style="text-align: center; padding: 2rem; color: var(--ds-text-secondary);">Yükleniyor...</td></tr>';
const LOADING_HTML_VARLIKLAR = '<tr><td colspan="10" style="text-align: center; padding: 2rem; color: var(--ds-text-secondary);">Yükleniyor...</td></tr>';
let binanceRateLimited = false;

function normalizeAssetToSymbol(asset, quote = QUOTE) {
    if (!asset || typeof asset !== 'string') return '';
    const a = String(asset).replace(/[\s\/\-]/g, '').toUpperCase();
    if (!a) return '';
    if (a === 'USDT') return 'USDTUSD';
    if (a === 'USDC' || a === 'FDUSD' || a === 'BUSD' || a === 'TUSD' || a === 'DAI') return quote + quote;
    if (a === 'USDTUSD' || a === 'USDT/USD') return 'USDTUSD';
    if (/^[A-Z0-9]+USDT$/i.test(a) || /^[A-Z0-9]+(BTC|ETH|BNB|FDUSD|BUSD)$/i.test(a)) return a;
    return a + quote;
}

/** Modal için sembol normalize; USDT/USD → USDTUSD; çapraz parite XRPETH vb. */
function normalizeModalSymbol(symbol) {
    if (!symbol || typeof symbol !== 'string') return { normalized: '', invalid: true };
    const s = String(symbol).replace(/[\s\/\-]/g, '').toUpperCase();
    if (!s) return { normalized: '', invalid: true };
    if (binanceTradingSymbolsSet && binanceTradingSymbolsSet.size > 0 && !binanceTradingSymbolsSet.has(s)) {
        return { normalized: s, invalid: true };
    }
    const pq = parseTradingPairSymbol(s);
    if (!pq.valid || pq.base === 'USDT' || !pq.base) {
        if (binanceTradingSymbolsSet && binanceTradingSymbolsSet.has(s)) {
            return { normalized: s, invalid: false };
        }
        return { normalized: s, invalid: true };
    }
    return { normalized: pq.normalized, invalid: false };
}

function normalizeUiSymbolToStoreKey(uiSymbol) {
    return normalizeAssetToSymbol(uiSymbol, QUOTE);
}

const assetsState = {
    wallet: { status: 'idle', ts: 0, assets: [], error: null, source: null },
    prices: { ts: 0, data_status: 'empty' },
    ui: { filterText: '', hideSmall: false, sortKey: 'value', sortDir: 'desc' }
};

/** coerceNumber: string "10500.50" -> 10500.50; prevents typeof-check drops */
function coerceNumber(x) {
    if (typeof x === 'number' && isFinite(x)) return x;
    if (typeof x === 'string' && x.trim() !== '' && isFinite(Number(x))) return Number(x);
    return null;
}

/** Wallet event ring buffer (last 50) for debug_wallet=1 */
window.__walletEvents = window.__walletEvents || [];
function pushWalletEvent(ev) {
    var arr = window.__walletEvents;
    arr.push({ t: Date.now(), ...ev });
    if (arr.length > 50) arr.shift();
}

/** Single reducer: normalize payload and apply to assetsState.wallet */
function normalizeAndApplyWallet(payload, meta) {
    meta = meta || {};
    var source = meta.source || 'unknown';
    if (!payload || typeof payload !== 'object') {
        pushWalletEvent({ source: source, status: 'skipped', note: 'payload null or non-object' });
        return;
    }
    var err = payload._error;
    if (err && typeof err === 'string') {
        err = { message: err, error_code: payload._error_code || payload.code || null, request_id: payload._request_id || null };
    } else if (err && typeof err === 'object') {
        err.error_code = err.error_code || err.code || payload.code || payload._error_code || null;
    }
    var status = err ? 'error' : 'ready';
    // Snapshot returns cache-only wallet; do not overwrite ready wallet with WALLET_NOT_READY (prevents flicker)
    var isNotReady = err && (err.error_code === 'WALLET_NOT_READY' || (err.detail && err.detail.indexOf('No cached snapshot') !== -1));
    var currentReady = assetsState.wallet && assetsState.wallet.status === 'ready' && (assetsState.wallet.assets && assetsState.wallet.assets.length);
    if (isNotReady && currentReady) {
        pushWalletEvent({ source: source, status: 'skipped', note: 'WALLET_NOT_READY from snapshot; keep ready wallet' });
        return;
    }
    // Boş payload ile hazır cüzdanı sıfırlama (flicker önleme)
    var payloadAssets = Array.isArray(payload.assets) ? payload.assets : [];
    var payloadEmpty = payloadAssets.length === 0 && (coerceNumber(payload.total_usd) == null || coerceNumber(payload.total_usd) === 0);
    if (currentReady && payloadEmpty && !err) {
        pushWalletEvent({ source: source, status: 'skipped', note: 'empty payload; keep ready wallet' });
        return;
    }
    // Test hesabı: snapshot/wallet poll arasında küçük fiyat oynaklığı strip flicker yapmasın
    if (typeof State !== 'undefined' && State.isTestAccount && currentReady && !err && payloadAssets.length > 0) {
        payloadAssets = repairTestWalletAssets(payloadAssets);
        var curBrokenQty = (assetsState.wallet.assets || []).some(function (a) {
            return typeof testWalletAssetQtyBroken === 'function' && testWalletAssetQtyBroken(a);
        });
        var curAv = coerceNumber(assetsState.wallet.available_usd);
        var curBl = coerceNumber(assetsState.wallet.bot_locked_usd);
        var nextAv = coerceNumber(payload.available_usd);
        var nextBl = coerceNumber(payload.bot_locked_usd);
        var curUsdt = (assetsState.wallet.assets || []).find(function (a) { return a && (a.asset || '').toUpperCase() === 'USDT'; });
        var nextUsdt = payloadAssets.find(function (a) { return a && (a.asset || '').toUpperCase() === 'USDT'; });
        var curUsdtTotal = curUsdt && curUsdt.total != null ? Number(curUsdt.total) : null;
        var nextUsdtTotal = nextUsdt && nextUsdt.total != null ? Number(nextUsdt.total) : null;
        var usdtTotalStable = curUsdtTotal != null && nextUsdtTotal != null
            && Math.abs(curUsdtTotal - nextUsdtTotal) < 0.00000001;
        if (!curBrokenQty && curAv != null && nextAv != null && curBl != null && nextBl != null
            && Math.abs(curAv - nextAv) < 0.02 && Math.abs(curBl - nextBl) < 0.02
            && usdtTotalStable
            && payloadAssets.length === (assetsState.wallet.assets || []).length) {
            pushWalletEvent({ source: source, status: 'skipped', note: 'test strip within noise band' });
            return;
        }
    }
    var totalUsd = coerceNumber(payload.total_usd);
    var freeUsd = coerceNumber(payload.free_usd);
    var lockedUsd = coerceNumber(payload.locked_usd);
    var botLockedUsd = coerceNumber(payload.bot_locked_usd);
    var availableUsd = coerceNumber(payload.available_usd);
    var keysConfigured = payload.keys_configured !== false;
    var assets = Array.isArray(payload.assets) ? payload.assets : [];
    if (typeof State !== 'undefined' && State.isTestAccount) {
        assets = repairTestWalletAssets(assets);
    }
    // Bootstrap/minimal wallet uses usdt_value per asset; UI expects total_usd (so list and filter work)
    assets = assets.map(function (a) {
        if (!a || typeof a !== 'object') return a;
        var out = Object.assign({}, a);
        if (out.total_usd == null && out.usdt_value != null) out.total_usd = Number(out.usdt_value);
        return out;
    });
    var ts = payload.ts != null ? (typeof payload.ts === 'number' ? payload.ts : (typeof payload.ts === 'string' ? new Date(payload.ts).getTime() : null)) : null;
    if (ts == null) ts = assetsState.wallet.ts || 0;
    var currentTotal = (assetsState.wallet && typeof assetsState.wallet.total_usd === 'number') ? assetsState.wallet.total_usd : null;
    if ((totalUsd == null || totalUsd === 0) && currentTotal != null && currentTotal > 0) totalUsd = currentTotal;
    if (totalUsd == null && assets.length && freeUsd != null) totalUsd = freeUsd;
    if (!err && totalUsd == null && assets.length === 0 && keysConfigured) {
        status = 'error';
        err = { error_code: 'WALLET_EMPTY_UNEXPECTED', message: 'Cüzdan boş' };
    }
    assetsState.wallet.status = status;
    assetsState.wallet.source = source;
    assetsState.wallet.ts = ts;
    assetsState.wallet.total_usd = totalUsd;
    assetsState.wallet.free_usd = freeUsd;
    assetsState.wallet.locked_usd = lockedUsd;
    assetsState.wallet.bot_locked_usd = botLockedUsd;
    assetsState.wallet.available_usd = availableUsd;
    assetsState.wallet.keys_configured = keysConfigured;
    assetsState.wallet.assets = assets;
    assetsState.wallet.error = err || null;
    var explicitStatus = payload.data_status;
    var inferredLive = _isLiveWalletSource(source) && !meta.skipped && !meta.stale;
    var snapshotFresh = source === 'dashboard_snapshot'
        && meta.wallet_age_sec != null
        && Number(meta.wallet_age_sec) < 900
        && !meta.stale;
    var newDataStatus = explicitStatus || (err ? 'error' : ((inferredLive || snapshotFresh) ? 'fresh' : 'cached'));
    if (!err && explicitStatus !== 'stale' && explicitStatus !== 'error'
        && _walletLiveOkAt && (Date.now() - _walletLiveOkAt) <= WALLET_LIVE_OK_TTL_MS
        && !_walletLiveFailedAfterOk()) {
        newDataStatus = 'fresh';
    }
    assetsState.wallet.data_status = newDataStatus;
    assetsState.wallet.keysMessage = payload.message || null;
    assetsState.wallet.unpriced_assets = Array.isArray(payload.unpriced_assets) ? payload.unpriced_assets : [];
    if (err && _isLiveWalletSource(source)) {
        markWalletLiveFetchFailed(err.error_code || err.code);
    } else if ((_isLiveWalletSource(source) || snapshotFresh) && keysConfigured && !err) {
        if (explicitStatus === 'stale' || meta.stale) {
            if (meta.skipped || totalUsd != null || assets.length > 0) {
                assetsState.wallet.data_status = 'cached';
                assetsState.wallet.status = 'ready';
                assetsState.wallet.error = null;
                markWalletCachedLiveFetchStale(meta.stale_code || payload.last_error_code || payload._error_code || 'BINANCE_UNREACHABLE');
                scheduleSilentWalletRecovery();
            } else {
                markWalletLiveFetchFailed(meta.stale_code || 'BINANCE_UNREACHABLE');
            }
        } else if (meta.skipped && (totalUsd != null || assets.length > 0) && !meta.stale) {
            markWalletLiveFetchOk();
        } else if (!meta.skipped && (totalUsd != null || assets.length > 0)) {
            markWalletLiveFetchOk();
        }
    }
    pushWalletEvent({ source: source, status: status, total_usd: totalUsd, asset_count: assets.length, request_id: meta.request_id, note: meta.note });
    if (!err && assets.length) _persistWalletStorageCache();
    hideBinanceConnectionNoticeIfWalletReady();
    if (typeof updateKpiCuzdanLiveStatus === 'function') updateKpiCuzdanLiveStatus();
    if (window.BinanceAssetsPanel?.render) {
        window.BinanceAssetsPanel.render();
    } else if (typeof renderVarliklarList === 'function') {
        renderVarliklarList();
    }
    if (typeof updateDcaBudgetPlaceholder === 'function') updateDcaBudgetPlaceholder();
    if (typeof updateMultiBudgetPlaceholder === 'function') updateMultiBudgetPlaceholder();
    if (typeof updateTrdcaBalancePlaceholder === 'function') updateTrdcaBalancePlaceholder();
    if (typeof window.renderWalletDebugOverlay === 'function') window.renderWalletDebugOverlay();
}
window.coerceNumber = coerceNumber;
window.pushWalletEvent = pushWalletEvent;
window.normalizeAndApplyWallet = normalizeAndApplyWallet;

/** Sync boot wallet from dashboardStore into assetsState (fix: appBoot runs before dashboard.js so bootstrap wallet was never applied on first paint; mobile + desktop). */
function syncBootWalletToAssetsState() {
    if (typeof window === 'undefined' || !window.dashboardStore) return;
    var state = window.dashboardStore.getState();
    if (!state || !state.wallet) return;
    var w = state.wallet.data;
    if (w && typeof w === 'object') {
        normalizeAndApplyWallet(w, { source: 'appBoot_bootstrap_from_store', request_id: state.wallet.request_id });
    } else if (state.wallet.status === 'error' && state.wallet.error) {
        assetsState.wallet.status = 'error';
        assetsState.wallet.error = state.wallet.error;
        assetsState.wallet.keys_configured = (state.wallet.wallet_status && state.wallet.wallet_status.keys_configured);
        if (window.BinanceAssetsPanel && typeof window.BinanceAssetsPanel.render === 'function') window.BinanceAssetsPanel.render();
        if (typeof window.renderVarliklarList === 'function') window.renderVarliklarList();
    }
}
window.syncBootWalletToAssetsState = syncBootWalletToAssetsState;
// Apply boot wallet if bootstrap already completed (e.g. dashboard.js loaded after appBoot then())
syncBootWalletToAssetsState();

/** Debug overlay: ?debug_wallet=1 shows wallet state (accountId, status, source, totals, last 5 events) */
function renderWalletDebugOverlay() {
    if (typeof window === 'undefined') return;
    try {
        var q = new URLSearchParams(window.location.search);
        if (q.get('debug_wallet') !== '1') return;
    } catch (e) { return; }
    var w = (window.assetsState && window.assetsState.wallet) ? window.assetsState.wallet : {};
    var dbg = window.__walletDebugMeta || {};
    var acc = window.__ACTIVE_ACCOUNT_ID ?? State?.accountId ?? '—';
    var ev = (window.__walletEvents || []).slice(-5).reverse();
    var evStr = ev.map(function (e) {
        return [e.source, e.status, e.total_usd, e.asset_count, e.note].filter(Boolean).join(' | ');
    }).join('\n') || '(none)';
    var totalUsd = w.total_usd;
    var totalType = typeof totalUsd;
    var html = '<div id="wallet-debug-overlay" style="position:fixed;bottom:8px;right:8px;z-index:99999;max-width:360px;max-height:280px;overflow:auto;background:rgba(0,0,0,0.9);color:#0f0;font:11px monospace;padding:8px;border-radius:6px;box-shadow:0 2px 8px rgba(0,0,0,0.4);">' +
        '<div><b>wallet debug</b> [?debug_wallet=1]</div>' +
        '<div>accountId: ' + String(acc) + '</div>' +
        '<div>status: ' + (w.status || '—') + ' | source: ' + (w.source || '—') + '</div>' +
        '<div>wallet_source: ' + (dbg.wallet_source || '—') + ' | wallet_age_sec: ' + (dbg.wallet_age_sec != null ? dbg.wallet_age_sec : '—') + '</div>' +
        '<div>last_refresh_at: ' + (dbg.last_refresh_at || '—') + '</div>' +
        '<div>last_error_code: ' + (dbg.last_error_code || '—') + ' | cooldown_until: ' + (dbg.cooldown_until || '—') + '</div>' +
        '<div>request_id: ' + (dbg.request_id || w.error?.request_id || '—') + '</div>' +
        '<div>ts: ' + (w.ts ? new Date(w.ts).toISOString().slice(11, 19) : '—') + '</div>' +
        '<div>keys_configured: ' + String(w.keys_configured) + '</div>' +
        '<div>total_usd: ' + String(totalUsd) + ' (typeof: ' + totalType + ')</div>' +
        '<div>free_usd: ' + String(w.free_usd) + ' | locked_usd: ' + String(w.locked_usd) + '</div>' +
        '<div>assets: ' + (Array.isArray(w.assets) ? w.assets.length : 0) + '</div>' +
        (w.error ? '<div style="color:#f80">error: ' + (w.error.error_code || w.error.message || JSON.stringify(w.error)) + '</div>' : '') +
        '<div style="margin-top:6px;border-top:1px solid #333;padding-top:4px;"><b>Last 5 events:</b><pre style="margin:0;font-size:10px;white-space:pre-wrap;">' + evStr + '</pre></div>' +
        '</div>';
    var el = document.getElementById('wallet-debug-overlay');
    if (el) el.outerHTML = html; else document.body.insertAdjacentHTML('beforeend', html);
}
window.renderWalletDebugOverlay = renderWalletDebugOverlay;

/** UI health for diag: Binance price render count (sessiz UI kopması teşhisi) */
const uiHealth = { render_count: 0, last_render_ok_ts: null };

/** marketStore subscription – Binance tab açıkken abone, kapanınca unsubscribe (memory leak yok) */
let binanceUnsubscribePrices = null;

let walletPollInflight = false;
let walletBackoffMs = WALLET_BACKOFF_MIN;
let lastWalletHash = null;
let assetsPanelRenderCount = 0;
var _varliklarHasRenderedRows = false;
var BINANCE_WALLET_CACHE_PREFIX = 'binance_wallet_v1_';
var BINANCE_WALLET_CACHE_LOCAL_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;
var BINANCE_WALLET_TBODY_HTML_MAX = 120000;
var _walletBinanceCacheHydrated = false;

function _parseBinanceWalletCacheRaw(raw, maxAgeMs) {
    if (!raw) return null;
    try {
        var o = JSON.parse(raw);
        if (!o || !o.ts) return null;
        if (maxAgeMs != null && Date.now() - Number(o.ts) > maxAgeMs) return null;
        return o;
    } catch (e) {
        return null;
    }
}

function _readBinanceWalletCache(accountId) {
    if (!accountId) return null;
    var id = String(accountId);
    var sess = _parseBinanceWalletCacheRaw(sessionStorage.getItem(BINANCE_WALLET_CACHE_PREFIX + id), null);
    if (sess && ((sess.wallet_cached && sess.wallet_cached.assets && sess.wallet_cached.assets.length) || sess.tbodyHtml)) return sess;
    var local = _parseBinanceWalletCacheRaw(localStorage.getItem(BINANCE_WALLET_CACHE_PREFIX + id), BINANCE_WALLET_CACHE_LOCAL_MAX_AGE_MS);
    if (local && ((local.wallet_cached && local.wallet_cached.assets && local.wallet_cached.assets.length) || local.tbodyHtml)) return local;
    if (window.storageCache) {
        var sc = window.storageCache.load(accountId);
        if (sc && sc.wallet_cached && Array.isArray(sc.wallet_cached.assets) && sc.wallet_cached.assets.length) {
            return { ts: sc.stored_at || Date.now(), wallet_cached: sc.wallet_cached, wallet_cached_at: sc.wallet_cached_at, strip: null, tbodyHtml: '' };
        }
    }
    return null;
}

function applyBinanceStripSnapshot(availableUsd, botLockedUsd, lockedUsd) {
    var stripAvailable = document.getElementById('binanceAvailableAssets');
    var stripBotLocked = document.getElementById('binanceBotLockedAssets');
    var stripLocked = document.getElementById('binanceLockedAssets');
    var isTest = typeof State !== 'undefined' && State.isTestAccount;
    function paint(el, val) {
        if (!el || val == null || !Number.isFinite(Number(val))) return;
        el.classList.remove('binance-assets-strip-value--loading');
        var n = Number(val);
        el.setAttribute('data-value', n);
        var txt = typeof fmtUsd === 'function' ? fmtUsd(n) : ('$' + n.toFixed(2));
        if (isTest && typeof updateTestAccountStripCell === 'function') updateTestAccountStripCell(el, n);
        else if (typeof setTextIfChanged === 'function') setTextIfChanged(el, txt);
        else el.textContent = txt;
    }
    paint(stripAvailable, availableUsd);
    paint(stripBotLocked, botLockedUsd);
    paint(stripLocked, lockedUsd);
}

function _applyBinanceVarliklarTableHtml(html) {
    var tbody = document.getElementById('varliklarTableBody');
    if (!tbody || !html || html.indexOf('data-asset') === -1) return false;
    tbody.innerHTML = html;
    _varliklarHasRenderedRows = true;
    return true;
}

function _persistBinanceWalletCache(accountId) {
    if (!accountId) return;
    try {
        var tbody = document.getElementById('varliklarTableBody');
        var tbodyHtml = '';
        if (tbody && tbody.querySelector('tr[data-asset]')) {
            tbodyHtml = tbody.innerHTML;
            if (tbodyHtml.length > BINANCE_WALLET_TBODY_HTML_MAX) tbodyHtml = '';
        }
        var strip = {
            available: testAccountReadStripUsdValue(document.getElementById('binanceAvailableAssets')),
            botLocked: testAccountReadStripUsdValue(document.getElementById('binanceBotLockedAssets')),
            locked: testAccountReadStripUsdValue(document.getElementById('binanceLockedAssets'))
        };
        var walletSnap = null;
        if (assetsState.wallet.assets && assetsState.wallet.assets.length) {
            walletSnap = {
                assets: assetsState.wallet.assets,
                total_usd: assetsState.wallet.total_usd,
                free_usd: assetsState.wallet.free_usd,
                locked_usd: assetsState.wallet.locked_usd,
                bot_locked_usd: assetsState.wallet.bot_locked_usd,
                available_usd: assetsState.wallet.available_usd,
                keys_configured: assetsState.wallet.keys_configured !== false
            };
        }
        if (!walletSnap && !tbodyHtml && !(strip.available > 0 || strip.botLocked > 0)) return;
        var payload = {
            ts: Date.now(),
            strip: strip,
            wallet_cached: walletSnap,
            wallet_cached_at: assetsState.wallet.ts ? new Date(assetsState.wallet.ts).toISOString() : new Date().toISOString(),
            tbodyHtml: tbodyHtml
        };
        sessionStorage.setItem(BINANCE_WALLET_CACHE_PREFIX + accountId, JSON.stringify(payload));
        localStorage.setItem(BINANCE_WALLET_CACHE_PREFIX + accountId, JSON.stringify(payload));
    } catch (e) { /* ignore */ }
}

function hydrateWalletFromStorageCache(accountId) {
    if (!accountId) return false;
    if (assetsState.wallet.assets && assetsState.wallet.assets.length && _varliklarTableHasRows()) return false;
    var cached = _readBinanceWalletCache(accountId);
    if (!cached) return false;
    var restored = false;
    if (cached.strip) {
        applyBinanceStripSnapshot(cached.strip.available, cached.strip.botLocked, cached.strip.locked);
        restored = true;
    }
    if (cached.tbodyHtml && _applyBinanceVarliklarTableHtml(cached.tbodyHtml)) {
        restored = true;
        _walletBinanceCacheHydrated = true;
    }
    if (cached.wallet_cached && Array.isArray(cached.wallet_cached.assets) && cached.wallet_cached.assets.length) {
        if (window.renderHome && typeof window.renderHome.walletCachedToAssetsState === 'function') {
            window.renderHome.walletCachedToAssetsState(cached.wallet_cached, cached.wallet_cached_at);
        } else if (typeof normalizeAndApplyWallet === 'function') {
            normalizeAndApplyWallet(Object.assign({}, cached.wallet_cached, {
                ts: cached.wallet_cached_at ? new Date(cached.wallet_cached_at).getTime() : Date.now(),
                data_status: 'cached'
            }), { source: 'storage_cache_hydrate' });
        }
        assetsState.wallet.status = 'ready';
        if (!_varliklarTableHasRows() && typeof renderVarliklarList === 'function') renderVarliklarList();
        restored = true;
        _walletBinanceCacheHydrated = true;
    }
    if (restored) {
        if (window.renderHome && typeof window.renderHome.hideSkeleton === 'function') window.renderHome.hideSkeleton();
        if (typeof State !== 'undefined' && State.isTestAccount && typeof updateTestAccountKpiCuzdanFromStrip === 'function') {
            updateTestAccountKpiCuzdanFromStrip();
        }
    }
    return restored;
}
window.hydrateWalletFromStorageCache = hydrateWalletFromStorageCache;
window.applyBinanceStripSnapshot = applyBinanceStripSnapshot;
window.restoreBinanceWalletEarlyFromStorage = hydrateWalletFromStorageCache;

function _persistWalletStorageCache() {
    if (!State.accountId || !window.storageCache || !assetsState.wallet.assets || !assetsState.wallet.assets.length) return;
    try {
        window.storageCache.mergeSaved(State.accountId, {
            wallet_cached: {
                assets: assetsState.wallet.assets,
                total_usd: assetsState.wallet.total_usd,
                free_usd: assetsState.wallet.free_usd,
                locked_usd: assetsState.wallet.locked_usd,
                bot_locked_usd: assetsState.wallet.bot_locked_usd,
                available_usd: assetsState.wallet.available_usd,
                keys_configured: assetsState.wallet.keys_configured !== false
            },
            wallet_cached_at: assetsState.wallet.ts ? new Date(assetsState.wallet.ts).toISOString() : new Date().toISOString()
        });
    } catch (e) { /* ignore */ }
    _persistBinanceWalletCache(State.accountId);
}

function _varliklarTableHasRows() {
    var body = document.getElementById('varliklarTableBody');
    return !!(body && body.querySelector('tr[data-asset]'));
}

function _walletHasDisplayableAssets() {
    return !!(assetsState.wallet.assets && assetsState.wallet.assets.length) || _varliklarTableHasRows();
}
window._walletHasDisplayableAssets = _walletHasDisplayableAssets;

function hashWalletAssets(assets) {
    if (!Array.isArray(assets)) return '';
    var roundQty = function (v) {
        if (v == null || !Number.isFinite(Number(v))) return 0;
        var n = Number(v);
        if (n >= 1000) return Math.round(n * 100) / 100;
        if (n >= 1) return Math.round(n * 10000) / 10000;
        return Math.round(n * 1e8) / 1e8;
    };
    var rows = assets.map(function (a) {
        return [a.asset, roundQty(a.free), roundQty(a.locked), roundQty(a.bot_locked)];
    }).sort(function (a, b) { return (a[0] || '').localeCompare(b[0] || ''); });
    return JSON.stringify(rows);
}

/** Cüzdan tablosu sırası: tam USD değil, kaba kova + sembol (fiyat oynayınca satır sırası zıplamasın). */
function sortVarliklarListForDisplay(list) {
    if (!Array.isArray(list) || !list.length) return list;
    return list.slice().sort(function (a, b) {
        var va = Number(a._valueUsd) || 0;
        var vb = Number(b._valueUsd) || 0;
        var ba = va >= 1000 ? Math.round(va) : Math.round(va * 10) / 10;
        var bb = vb >= 1000 ? Math.round(vb) : Math.round(vb * 10) / 10;
        if (bb !== ba) return bb - ba;
        return (a.asset || '').localeCompare(b.asset || '');
    });
}

function varlikRowActionsHtml(d) {
    return '<div class="btn-al-sat-wrap">' +
        '<button type="button" class="btn-al"' + d.buyDisabled + ' onclick="event.stopPropagation(); ' + (d.canBuy ? "openSpotTradeModal('" + d.symbol + "', 'BUY')" : '') + '" title="' + d.buyTitle + '">Alış</button>' +
        '<button type="button" class="btn-sat"' + d.sellDisabled + ' onclick="event.stopPropagation(); ' + (d.canSell ? "openSpotTradeModal('" + d.symbol + "', 'SELL')" : '') + '" title="' + d.sellTitle + '">Satış</button></div>';
}

function _bnAssetsErrorRow(msg, showRetry = true) {
    const btn = showRetry
        ? ' <button type="button" class="btn btn-sm" onclick="typeof binanceRefresh===\'function\'?binanceRefresh():BinanceAssetsPanel.refresh()" style="margin-left:0.5rem;">Yenile</button>'
        : '';
    return `<tr><td colspan="7" style="text-align: center; padding: 2rem; color: var(--ds-text-secondary);">${msg}${btn}</td></tr>`;
}

function binanceRefresh() {
    if (!State.accountId) return;
    if (window.FLASH_HOME_ENABLED && window.homeFlash && typeof window.homeFlash.triggerRefresh === 'function') {
        window.homeFlash.triggerRefresh(State.accountId, true);
        return;
    }
    if (window.BinanceUI && typeof window.BinanceUI.refresh === 'function') {
        window.BinanceUI.refresh({ accountId: State.accountId });
    } else if (window.BinanceAssetsPanel && window.BinanceAssetsPanel.refresh) {
        BinanceAssetsPanel.refresh();
    }
}
window.binanceRefresh = binanceRefresh;

/** TEK KAYNAK: marketStore prices map (mini ile senkron). */
function resolveMarketLivePrice(sym) {
    if (!sym) return null;
    var s = String(sym).toUpperCase();
    var store = window.marketStore;
    if (!store) return null;
    var p = store.getPrice(s);
    if (p == null || !Number.isFinite(p) || p <= 0) {
        var mini = store.getMini(s);
        p = mini && mini.last;
    }
    return (p != null && Number.isFinite(p) && p > 0) ? p : null;
}

/** TEK KAYNAK: marketStore. dataHub kullanılmaz. */
function getAssetPrice(asset) {
    const symbol = normalizeAssetToSymbol(asset, QUOTE);
    if (asset === 'USDT' || asset === 'USDC' || asset === 'FDUSD' || asset === 'BUSD' || asset === 'TUSD' || asset === 'DAI') return 1;
    return resolveMarketLivePrice(symbol);
}

async function pollWallet(isManualRefresh = false) {
    if (!State.accountId) return;
    if (walletPollInflight && !isManualRefresh) return;
    if (!isManualRefresh && Date.now() < walletPollBackoffUntil) return; // 429 backoff
    walletPollInflight = true;

    const body = document.getElementById("varliklarTableBody");
    const empty = document.getElementById("varliklarEmpty");
    let didUpdateBody = false;
    const hasExisting = _walletHasDisplayableAssets();
    const isFirst = (assetsState.wallet.status === 'idle' || isManualRefresh) && !hasExisting && !_walletBinanceCacheHydrated;
    if (body && isFirst) { body.innerHTML = LOADING_HTML_VARLIKLAR; didUpdateBody = true; }
    if (empty) empty.style.display = 'none';
    if (isFirst && !hasExisting) assetsState.wallet.status = 'loading';
    if (typeof window.__DEBUG_BINANCE__ !== 'undefined' && window.__DEBUG_BINANCE__) console.count('walletFetch');

    const loadingGuard = setTimeout(() => {
        if (body && !didUpdateBody && body.innerHTML && body.innerHTML.includes('Yükleniyor')) {
            body.innerHTML = '<tr><td colspan="10" style="text-align: center; padding: 2rem; color: var(--ds-text-secondary);">Cüzdan yanıt vermiyor. Yenile\'yi deneyin.</td></tr>';
            didUpdateBody = true;
        }
    }, WALLET_POLL_MS + 3000);

    try {
        const url = `/api/binance/wallet?account_id=${State.accountId}`;
        if (!window.apiClient || typeof window.apiClient.get !== 'function') throw new Error('apiClient required');
        const data = await window.apiClient.get(url);
        normalizeAndApplyWallet(data, { source: 'binance_wallet', request_id: data.request_id });
        walletBackoffMs = WALLET_BACKOFF_MIN;
        walletPollBackoffUntil = 0;
        didUpdateBody = true;
        if (data.keys_configured !== false) {
            const notice = document.getElementById('binanceConnectionNotice');
            if (notice) {
                notice.style.display = 'none';
                notice.classList.add('binance-connection-notice--hidden');
            }
        }
        if (window.binanceFeeRates == null) {
            window.binanceFeeRates = { taker: 0.001, maker: 0.001, taker_pct: 0.1, maker_pct: 0.1 };
        }
        if (typeof updateMultiBudgetPlaceholder === 'function') updateMultiBudgetPlaceholder();
        if (typeof updateTrdcaBalancePlaceholder === 'function') updateTrdcaBalancePlaceholder();
        if (typeof updateDcaBudgetPlaceholder === 'function') updateDcaBudgetPlaceholder();
    } catch (error) {
        pushWalletEvent({ source: 'binance_wallet', status: 'error', note: 'pollWallet catch', request_id: error?.request_id });
        if (window.errorReporter) window.errorReporter.report(error, { tab: 'binance', account_id: State.accountId, action: 'pollWallet' });
        var is429 = error && (error.status === 429 || (error.error_code && String(error.error_code).indexOf('429') !== -1));
        assetsState.wallet.error = { message: error?.message || 'Bilinmeyen hata', error_code: error?.error_code || null, error_id: error?.error_id || null, request_id: error?.request_id || null };
        markWalletLiveFetchFailed();
        walletBackoffMs = Math.min(WALLET_BACKOFF_MAX, Math.max(WALLET_BACKOFF_MIN, (walletBackoffMs || WALLET_BACKOFF_MIN) * 2));
        if (is429) {
            var retrySec = (error.retry_after != null) ? Number(error.retry_after) : 10;
            var retryMs = Math.min(60000, Math.max(1000, retrySec * 1000));
            walletPollBackoffUntil = Date.now() + retryMs;
            assetsState.wallet.status = 'ready';
            assetsState.wallet.data_status = 'stale';
            assetsState.wallet.retry_after = retrySec;
            if (window.intervalRegistry && window.intervalRegistry.stop) {
                window.intervalRegistry.stop('wallet:poll');
                window.intervalRegistry.timeout && window.intervalRegistry.timeout.cancel && window.intervalRegistry.timeout.cancel('wallet:resume');
                // wallet from dashboard_snapshot; no wallet:poll resume
            }
            if (body && assetsState.wallet.assets && assetsState.wallet.assets.length) {
                if (window.BinanceAssetsPanel?.render) window.BinanceAssetsPanel.render();
                didUpdateBody = false;
            } else if (body) {
                body.innerHTML = '<tr><td colspan="10" style="text-align: center; padding: 2rem; color: var(--ds-text-secondary);">Limit aşıldı; ' + retrySec + ' sn sonra tekrar denenecek.</td></tr>';
                didUpdateBody = true;
            }
        } else {
            assetsState.wallet.status = 'error';
            if (body) {
                const msg = (window.errorReporter && typeof window.errorReporter.toUserMessage === 'function')
                    ? window.errorReporter.toUserMessage(error) : (error.message || 'Bilinmeyen hata');
                var lastErrorMsg = body.getAttribute('data-last-error');
                if (lastErrorMsg === msg && !isManualRefresh) {
                    didUpdateBody = false;
                } else {
                    body.setAttribute('data-last-error', msg);
                    if (window.errorReporter?.renderBox) {
                        body.innerHTML = '<tr><td colspan="10"></td></tr>';
                        const cell = body.querySelector('td');
                        if (cell) window.errorReporter.renderBox(cell, error);
                    } else {
                        body.innerHTML = '<tr><td colspan="10" style="text-align: center; padding: 2rem; color: var(--ds-text-secondary);">Cüzdan verisi alınamadı: ' + (msg || '').replace(/</g, '&lt;') + '</td></tr>';
                    }
                    didUpdateBody = true;
                }
            }
            if (assetsState.wallet.assets && assetsState.wallet.assets.length) {
                if (window.BinanceAssetsPanel?.render) window.BinanceAssetsPanel.render();
            }
        }
    } finally {
        clearTimeout(loadingGuard);
        walletPollInflight = false;
        if (body && !didUpdateBody && body.innerHTML && body.innerHTML.includes('Yükleniyor')) {
            body.innerHTML = '<tr><td colspan="10" style="text-align: center; padding: 2rem; color: var(--ds-text-secondary);">Bir hata oluştu. Yenile\'yi deneyin.</td></tr>';
        }
    }
}

function tickPricesUI() {
    const tab = document.getElementById("tabBinance");
    if (!tab?.classList.contains("is-active")) return;
    
    const store = window.marketStore;
    if (!store) {
        if (window.__DEBUG_BINANCE__) console.warn("[BINANCE][tickPricesUI] marketStore not available");
        return;
    }
    
    assetsState.prices.ts = store?.lastUpdateTs ?? 0;
    assetsState.prices.data_status = store?.isStale(10000) ? 'stale' : (store?.lastUpdateTs ? 'fresh' : 'empty');
    
    uiHealth.render_count = (uiHealth.render_count || 0) + 1;
    uiHealth.last_render_ok_ts = Date.now();
    
    if (window.__DEBUG_BINANCE__) {
        const priceCount = (store.prices && typeof store.prices.size === 'number') ? store.prices.size : 0;
        console.log("[BINANCE][RENDER]", priceCount, "items", new Date().toLocaleTimeString('tr-TR'));
    }
    
    if (document.getElementById("tabBinance")?.classList.contains("is-active")) {
        if (typeof tickVarliklarPrices === 'function') tickVarliklarPrices({ skipThrottle: true });
    }
    if (!window.BinanceUI || !document.getElementById("tabBinance")?.classList.contains("is-active")) {
        BinanceAssetsPanel.tickPrices();
        updateCoinListPricesFromMarketStore();
    }
}

function renderAssetsSummary() {
    const totalEl = document.getElementById("bnTotalValue");
    const freeEl = document.getElementById("bnFreeValue");
    const lockedEl = document.getElementById("bnLockedValue");
    const lastEl = document.getElementById("bnAssetsLastUpdate");
    const staleEl = document.getElementById("bnAssetsStaleBadge");
    const stripAvailable = document.getElementById('binanceAvailableAssets');
    const stripBotLocked = document.getElementById('binanceBotLockedAssets');
    const stripLocked = document.getElementById('binanceLockedAssets');
    const walletLoading = (assetsState.wallet.status === 'idle' || assetsState.wallet.status === 'loading')
        && !_walletHasDisplayableAssets() && !_walletBinanceCacheHydrated;
    if (walletLoading) {
        const loadingText = 'Yükleniyor…';
        if (totalEl) totalEl.textContent = loadingText;
        if (freeEl) freeEl.textContent = loadingText;
        if (lockedEl) lockedEl.textContent = loadingText;
        if (stripAvailable) { stripAvailable.textContent = loadingText; stripAvailable.classList.add('binance-assets-strip-value--loading'); }
        if (stripBotLocked) { stripBotLocked.textContent = loadingText; stripBotLocked.classList.add('binance-assets-strip-value--loading'); }
        if (stripLocked) { stripLocked.textContent = loadingText; stripLocked.classList.add('binance-assets-strip-value--loading'); }
        if (lastEl) lastEl.textContent = '—';
        if (typeof syncWalletPanelStatusBadges === 'function') syncWalletPanelStatusBadges();
        else if (staleEl) staleEl.hidden = true;
        return;
    }
    const totalUsd = typeof assetsState.wallet.total_usd === 'number' ? assetsState.wallet.total_usd : (() => {
        let sum = 0;
        (assetsState.wallet.assets || []).forEach(a => {
            const v = a.total_usd != null ? Number(a.total_usd) : 0;
            if (Number.isFinite(v)) sum += v;
        });
        return sum;
    })();
    let freeUsd = typeof assetsState.wallet.free_usd === 'number' ? assetsState.wallet.free_usd : null;
    let lockedUsd = typeof assetsState.wallet.locked_usd === 'number' ? assetsState.wallet.locked_usd : null;
    if (freeUsd == null || lockedUsd == null) {
        let f = 0, l = 0;
        (assetsState.wallet.assets || []).forEach(a => {
            if (a.free_usd != null && Number.isFinite(Number(a.free_usd))) f += Number(a.free_usd);
            if (a.locked_usd != null && Number.isFinite(Number(a.locked_usd))) l += Number(a.locked_usd);
        });
        if (freeUsd == null) freeUsd = f;
        if (lockedUsd == null) lockedUsd = l;
    }
    if (totalEl) totalEl.textContent = fmtUsd(totalUsd);
    if (freeEl) freeEl.textContent = fmtUsd(freeUsd);
    if (lockedEl) lockedEl.textContent = fmtUsd(lockedUsd);
    var availableUsd = typeof assetsState.wallet.available_usd === 'number' ? assetsState.wallet.available_usd : null;
    var botLockedUsd = typeof assetsState.wallet.bot_locked_usd === 'number' ? assetsState.wallet.bot_locked_usd : null;
    var testStripFromTable = false;
    if (typeof State !== 'undefined' && State.isTestAccount) {
        var testTbody = document.getElementById('varliklarTableBody');
        if (testTbody && testTbody.querySelector('tr[data-asset]')) {
            testStripFromTable = true;
            if (typeof updateTestAccountStripFromTable === 'function') {
                updateTestAccountStripFromTable(testTbody);
            }
        } else {
            availableUsd = testAccountVarlikAvailableTotalFromAssets(assetsState.wallet.assets || []);
            botLockedUsd = testAccountVarlikBotLockedTotalFromAssets(assetsState.wallet.assets || []);
        }
    } else if (availableUsd == null && (assetsState.wallet.assets || []).length) {
        var av = 0;
        (assetsState.wallet.assets || []).forEach(function (a) {
            if (a.available_usd != null && Number.isFinite(Number(a.available_usd))) av += Number(a.available_usd);
        });
        availableUsd = av;
    }
    if (botLockedUsd == null && (assetsState.wallet.assets || []).length) {
        var bl = 0;
        (assetsState.wallet.assets || []).forEach(function (a) {
            if (a.bot_locked_usd != null && Number.isFinite(Number(a.bot_locked_usd))) bl += Number(a.bot_locked_usd);
        });
        botLockedUsd = bl;
    }
    if (!testStripFromTable) {
    var stripAvailableVal = availableUsd != null ? availableUsd : freeUsd;
    var botLockedVal = botLockedUsd != null ? botLockedUsd : 0;
    if (typeof State !== 'undefined' && State.isTestAccount && typeof updateTestAccountStripCell === 'function') {
        updateTestAccountStripCell(stripAvailable, stripAvailableVal);
        updateTestAccountStripCell(stripBotLocked, botLockedVal);
    } else {
    if (stripAvailable) {
        stripAvailable.classList.remove('binance-assets-strip-value--loading');
        stripAvailable.setAttribute('data-value', stripAvailableVal);
        stripAvailable.textContent = fmtUsd(stripAvailableVal);
        triggerValueBlink(stripAvailable, stripAvailableVal);
    }
    if (stripBotLocked) {
        stripBotLocked.classList.remove('binance-assets-strip-value--loading');
        stripBotLocked.setAttribute('data-value', botLockedVal);
        stripBotLocked.textContent = fmtUsd(botLockedVal);
        triggerValueBlink(stripBotLocked, botLockedVal);
    }
    }
    }
    var lockedVal = lockedUsd != null ? lockedUsd : 0;
    if (stripLocked && !testStripFromTable) {
        stripLocked.classList.remove('binance-assets-strip-value--loading');
        stripLocked.setAttribute('data-value', lockedVal);
        if (typeof State !== 'undefined' && State.isTestAccount && typeof updateTestAccountStripCell === 'function') {
            updateTestAccountStripCell(stripLocked, lockedVal);
        } else {
            stripLocked.textContent = fmtUsd(lockedVal);
            triggerValueBlink(stripLocked, lockedVal);
        }
    }
    if (typeof State !== 'undefined' && State.isTestAccount && typeof updateTestAccountKpiCuzdanFromStrip === 'function') {
        updateTestAccountKpiCuzdanFromStrip();
    }
    if (lastEl) lastEl.textContent = assetsState.wallet.ts ? new Date(assetsState.wallet.ts).toLocaleTimeString('tr-TR', { timeZone: 'Europe/Istanbul', hour: '2-digit', minute: '2-digit' }) : '—';
    if (typeof syncWalletPanelStatusBadges === 'function') syncWalletPanelStatusBadges();
}

// Wallet tablosu tek kaynak: backend /api/binance/wallet assets[]. Coin list / FX ticker asla satır üretmez.
// FX guard: TRY/EUR/GBP için total_usd > quantity imkansız (1 birim < 1 USD); böyle satırları gösterme.
var WALLET_FX_ASSETS = ['TRY', 'EUR', 'GBP'];
function isWalletAssetSuspiciousFx(a) {
    if (!a || !WALLET_FX_ASSETS.includes((a.asset || '').toUpperCase())) return false;
    var totalQty = (a.free || 0) + (a.locked || 0);
    var totalUsd = a.total_usd != null ? Number(a.total_usd) : null;
    if (totalQty <= 0 || totalUsd == null) return false;
    if (totalUsd > totalQty) return true; // 1 TRY < 1 USD, bu veri hatalı (FX kur bakiye gibi)
    return false;
}

function renderAssetsList() {
    const body = document.getElementById("bnAssetsBody");
    const empty = document.getElementById("bnEmpty");
    if (!body) return;
    const assets = assetsState.wallet.assets || [];
    const filterText = (assetsState.ui.filterText || '').trim().toUpperCase();
    const hideSmall = !!assetsState.ui.hideSmall;
    let list = assets.filter(a => {
        if (isWalletAssetSuspiciousFx(a)) return false;
        const sym = (a.asset || '').toUpperCase();
        if (filterText && !sym.includes(filterText)) return false;
        return true;
    }).map(a => {
        const total = (a.free || 0) + (a.locked || 0);
        const valueUsd = a.total_usd != null && Number.isFinite(Number(a.total_usd)) ? Number(a.total_usd) : null;
        const price = getAssetPrice(a.asset);
        return { ...a, _price: price, _valueUsd: valueUsd != null ? valueUsd : 0, _valueUsdRaw: valueUsd, _total: total };
    });
    if (hideSmall) list = list.filter(x => (x._valueUsdRaw != null ? x._valueUsdRaw : x._valueUsd) >= 1);
    list.sort((a, b) => (b._valueUsdRaw != null ? b._valueUsdRaw : b._valueUsd || 0) - (a._valueUsdRaw != null ? a._valueUsdRaw : a._valueUsd || 0));

    if (list.length === 0) {
        body.innerHTML = '';
        if (empty) {
            empty.style.display = 'block';
            const p = empty.querySelector('p');
            if (p) {
                if (assetsState.wallet.keys_configured === false && assetsState.wallet.keysMessage) {
                    p.textContent = assetsState.wallet.keysMessage;
                } else {
                    p.textContent = assets.length ? 'Filtreye uygun varlık yok' : 'Varlık bulunamadı';
                }
            }
        }
        return;
    }
    if (empty) empty.style.display = 'none';

    const quote = QUOTE;
    body.innerHTML = list.map(a => {
        const asset = a.asset || 'N/A';
        const symbol = normalizeAssetToSymbol(asset, quote);
        const free = a.free || 0;
        const locked = a.locked || 0;
        const total = a._total || 0;
        const price = a._price;
        const value = a._valueUsdRaw != null ? a._valueUsdRaw : (a._valueUsd || 0);
        const priceDisplay = price != null && Number.isFinite(price) ? fmtCoinPrice(price) : '…';
        const valueDisplay = (a._valueUsdRaw != null && Number.isFinite(a._valueUsdRaw)) ? fmtUsd(a._valueUsdRaw) : '—';
        return `<tr data-asset="${asset}" data-symbol="${symbol}" data-free="${free}" data-locked="${locked}">
            <td><strong class="asset-symbol">${asset}</strong></td>
            <td class="text-right">${fmtNum(free, 8)}</td>
            <td class="text-right">${fmtNum(locked, 8)}</td>
            <td class="text-right">${fmtNum(total, 8)}</td>
            <td class="text-right price-cell" data-price="${price != null ? price : ''}">${priceDisplay}</td>
            <td class="text-right value-cell" data-value="${value}">${valueDisplay}</td>
            <td class="text-center">
                <div class="btn-al-sat-wrap">
                    <button type="button" class="btn-al" onclick="event.stopPropagation(); openSpotTradeModal('${symbol}', 'BUY')" title="Alış">Alış</button>
                    <button type="button" class="btn-sat" onclick="event.stopPropagation(); openSpotTradeModal('${symbol}', 'SELL')" title="Satış">Satış</button>
                </div>
            </td>
        </tr>`;
    }).join('');
    if (typeof window.__DEBUG_BINANCE__ !== 'undefined' && window.__DEBUG_BINANCE__) { assetsPanelRenderCount++; console.count('renderBinanceAssets'); }
}

function tickAssetsPrices() {
    var tabActive = document.getElementById("tabBinance")?.classList.contains("is-active");
    if (tabActive && typeof tickVarliklarPrices === 'function') tickVarliklarPrices({ skipThrottle: true });
    if (window.BinanceUI && tabActive) return;
    renderAssetsSummary();
}

const BinanceAssetsPanel = {
    render() {
        renderAssetsSummary();
        var hasAssets = !!(assetsState.wallet.assets && assetsState.wallet.assets.length);
        if ((assetsState.wallet.status === 'loading' || assetsState.wallet.status === 'idle') && !hasAssets && !_varliklarTableHasRows()) return;
        if (assetsState.wallet.status === 'error' && !hasAssets && !_varliklarTableHasRows()) {
            if (typeof renderVarliklarList === 'function') renderVarliklarList();
            return;
        }
        const h = hashWalletAssets(assetsState.wallet.assets);
        if (h !== lastWalletHash) {
            lastWalletHash = h;
            if (typeof renderVarliklarList === 'function') renderVarliklarList();
        } else if (hasAssets && !_varliklarTableHasRows() && typeof renderVarliklarList === 'function') {
            renderVarliklarList();
        }
    },
    tickPrices() { tickAssetsPrices(); },
    refresh() {
        walletBackoffMs = WALLET_BACKOFF_MIN;
        if (State.accountId && typeof triggerWalletRefreshForVarliklar === 'function') {
            triggerWalletRefreshForVarliklar(State.accountId, { force: true });
        } else {
            pollWallet(true);
        }
    },
    pollWallet,
    tickPricesUI
};

window.BinanceAssetsPanel = BinanceAssetsPanel;
window.normalizeAssetToSymbol = normalizeAssetToSymbol;
window.normalizeUiSymbolToStoreKey = normalizeUiSymbolToStoreKey;

// --- Varlıklar sekmesi: Cüzdan varlıkları tablosu (1 USD üstü), ortak Al/Sat modal ---
const VARLIKLAR_MIN_USD = 1;
/** Binance sekmesi – Coin Listesi: sabit gösterilecek USDT çiftleri (FDUSD en başta) */
const BINANCE_COIN_LIST_SYMBOLS = ['FDUSDUSDT', 'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'AVAXUSDT', 'ADAUSDT', 'LINKUSDT', 'DOTUSDT', 'BNBUSDT', 'LTCUSDT'];
const assetNameMap = { BTC: 'Bitcoin', ETH: 'Ethereum', BNB: 'BNB', USDT: 'Tether', XRP: 'Ripple', ADA: 'Cardano', SOL: 'Solana', DOGE: 'Dogecoin', TRY: 'Türk Lirası', BUSD: 'Binance USD', FDUSD: 'First Digital USD', AVAX: 'Avalanche', LINK: 'Chainlink', DOT: 'Polkadot', LTC: 'Litecoin' };

// --- Favori coin çiftleri (⭐) — tek kaynak: sunucu (GET/PUT spot-favorites). Yedek: localStorage ---
const FAVORITES_STORAGE_PREFIX = 'spot_favorites_';
var spotFavorites = []; // string[] (symbols: BTCUSDT, ETHBTC, ...)

function getFavoritesStorageKey() {
    return State.accountId ? (FAVORITES_STORAGE_PREFIX + State.accountId) : null;
}

function loadSpotFavoritesFromLocalStorage() {
    var key = getFavoritesStorageKey();
    if (!key) return;
    try {
        var raw = typeof localStorage !== 'undefined' ? localStorage.getItem(key) : null;
        if (raw == null || raw === '') return;
        var arr = JSON.parse(raw);
        var from = Array.isArray(arr) ? arr.filter(function (s) { return typeof s === 'string' && s.trim(); }).map(function (s) { return normalizePairSymbol(s); }) : [];
        spotFavorites = from;
    } catch (e) {
        try { localStorage.removeItem(key); } catch (e2) {}
    }
}

async function loadSpotFavoritesFromStorage() {
    spotFavorites = [];
    if (!State.accountId) return;
    try {
        var data = await window.apiClient.get('/api/accounts/' + State.accountId + '/spot-favorites?_=' + Date.now());
        var list = data && Array.isArray(data.symbols) ? data.symbols : [];
        spotFavorites = list.map(function (s) { return normalizePairSymbol(s); }).filter(Boolean);
        if (spotFavorites.length === 0) {
            loadSpotFavoritesFromLocalStorage();
            if (spotFavorites.length > 0) {
                window.apiClient.put('/api/accounts/' + State.accountId + '/spot-favorites', { symbols: spotFavorites.slice() }).catch(function () {});
            }
        }
        try { localStorage.setItem(getFavoritesStorageKey(), JSON.stringify(spotFavorites)); } catch (e) {}
    } catch (e) {
        loadSpotFavoritesFromLocalStorage();
        if (spotFavorites.length === 0) {
            throw e;
        }
    }
}

function saveSpotFavoritesToStorage() {
    if (!State.accountId) return Promise.resolve();
    var payload = { symbols: spotFavorites.slice() };
    return window.apiClient.put('/api/accounts/' + State.accountId + '/spot-favorites', payload).then(function () {
        try { localStorage.setItem(getFavoritesStorageKey(), JSON.stringify(spotFavorites)); } catch (e) {}
    }).catch(function (err) {
        if (typeof console !== 'undefined' && console.error) console.error('[spot-favorites] Kaydetme hatası:', err);
        throw err;
    });
}

function normalizePairSymbol(sym) {
    return (sym || '').toUpperCase().replace(/\s+/g, '').replace('/', '');
}

function isSpotFavorite(sym) {
    var n = normalizePairSymbol(sym);
    return n && spotFavorites.indexOf(n) !== -1;
}

function addSpotFavorite(sym) {
    var n = normalizePairSymbol(sym);
    if (!n || spotFavorites.indexOf(n) !== -1) return Promise.resolve();
    spotFavorites.push(n);
    return saveSpotFavoritesToStorage();
}

function removeSpotFavorite(sym) {
    var n = normalizePairSymbol(sym);
    var i = spotFavorites.indexOf(n);
    if (i === -1) return Promise.resolve();
    spotFavorites.splice(i, 1);
    return saveSpotFavoritesToStorage();
}

function toggleSpotFavorite(sym) {
    var n = normalizePairSymbol(sym);
    if (!n) return Promise.resolve(false);
    var prev = spotFavorites.slice();
    if (isSpotFavorite(n)) {
        var p = removeSpotFavorite(n);
        return (p && p.then ? p.then(function () { return false; }) : Promise.resolve(false)).catch(function () {
            spotFavorites = prev;
            return Promise.reject(false);
        });
    }
    var p = addSpotFavorite(n);
    return (p && p.then ? p.then(function () { return true; }) : Promise.resolve(true)).catch(function () {
        spotFavorites = prev;
        return Promise.reject(true);
    });
}

function syncFavoriteButtonUI() {
    var btn = document.getElementById('bnTradeFavoriteBtn');
    if (!btn) return;
    var sym = spotTradeState.symbol;
    var fav = sym ? isSpotFavorite(sym) : false;
    btn.classList.toggle('is-favorite', !!fav);
    btn.textContent = fav ? '\u2605' : '\u2606';
    btn.title = fav ? 'Favorilerden \u00e7\u0131kar' : 'Favorilere ekle';
    btn.disabled = !State.accountId;
}

function rememberVarlikDisplayChange(asset, pct) {
    var sym = (asset || '').toUpperCase();
    if (!sym || pct == null || !Number.isFinite(Number(pct))) return;
    _varlikDisplayChangeCache[sym] = Number(pct);
}

function getAssetChangePct(asset) {
    const symbol = normalizeAssetToSymbol(asset, QUOTE);
    const mini = window.marketStore?.getMini(symbol);
    if (mini && Number.isFinite(mini.changePct)) {
        rememberVarlikDisplayChange(asset, mini.changePct);
        return mini.changePct;
    }
    if (mini && Number.isFinite(mini.open) && mini.open > 0 && Number.isFinite(mini.last) && mini.last > 0) {
        var derived = ((mini.last - mini.open) / mini.open) * 100;
        rememberVarlikDisplayChange(asset, derived);
        return derived;
    }
    var sym = (asset || '').toUpperCase();
    if (sym && _varlikDisplayChangeCache[sym] != null && Number.isFinite(_varlikDisplayChangeCache[sym])) {
        return _varlikDisplayChangeCache[sym];
    }
    return null;
}

function formatVarlikChangePctDisplay(asset, changePct) {
    var pct = changePct;
    if (pct == null || !Number.isFinite(pct)) pct = getAssetChangePct(asset);
    if (pct != null && Number.isFinite(pct)) {
        return { text: (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%', color: pct >= 0 ? '#0ecb81' : '#f6465d' };
    }
    return { text: '—', color: 'var(--ds-text-secondary)' };
}

function pushVarlikMarketMini(symbol, price, changePct) {
    if (!window.marketStore || !symbol || !(price > 0)) return;
    var sym = String(symbol).toUpperCase();
    var mini = { last: price, open: price };
    if (changePct != null && Number.isFinite(changePct)) mini.changePct = Number(changePct);
    window.marketStore.updateMini(sym, mini);
    var base = sym.replace(/USDT|FDUSD|BUSD|USDC$/i, '') || sym;
    rememberVarlikDisplayPrice(base, price);
    if (mini.changePct != null) rememberVarlikDisplayChange(base, mini.changePct);
}

var _varliklarWalletMarketInflight = null;
var _varliklarWalletMarketLastFetch = 0;
var VARLIKLAR_WALLET_MARKET_FETCH_MS = 6000;

function refreshVarliklarWalletMarketData(force) {
    var tbody = document.getElementById('varliklarTableBody');
    if (!tbody || !window.apiClient) return Promise.resolve();
    var symbols = [];
    tbody.querySelectorAll('tr[data-symbol]').forEach(function (row) {
        var s = (row.getAttribute('data-symbol') || '').toUpperCase();
        if (s) symbols.push(s);
    });
    if (!symbols.length && assetsState.wallet && Array.isArray(assetsState.wallet.assets)) {
        assetsState.wallet.assets.forEach(function (a) {
            if (a && a.asset) symbols.push(normalizeAssetToSymbol(a.asset, QUOTE));
        });
    }
    var seen = {};
    symbols = symbols.filter(function (s) { if (seen[s]) return false; seen[s] = true; return true; });
    if (!symbols.length) return Promise.resolve();
    var now = Date.now();
    if (!force && (now - _varliklarWalletMarketLastFetch < VARLIKLAR_WALLET_MARKET_FETCH_MS)) return Promise.resolve();
    if (_varliklarWalletMarketInflight) return _varliklarWalletMarketInflight;
    _varliklarWalletMarketLastFetch = now;
    _varliklarWalletMarketInflight = window.apiClient
        .get('/api/data/prices?slim=1&symbols=' + encodeURIComponent(symbols.join(',')))
        .then(function (res) {
            var prices = _parseDataPricesPayload(res);
            symbols.forEach(function (sym) {
                var row = prices[sym];
                if (!row || row.price == null) return;
                var price = Number(row.price);
                if (!(price > 0) || !Number.isFinite(price)) return;
                var pct = row.change24h != null && Number.isFinite(Number(row.change24h)) ? Number(row.change24h) : null;
                pushVarlikMarketMini(sym, price, pct);
            });
            if (typeof tickVarliklarPrices === 'function') tickVarliklarPrices({ skipThrottle: true });
        })
        .catch(function () {})
        .finally(function () { _varliklarWalletMarketInflight = null; });
    return _varliklarWalletMarketInflight;
}

/** Varlıklar tablosu: marketStore anlık boşalsa son bilinen fiyat/% (… flicker önleme). */
var _varlikDisplayPriceCache = Object.create(null);
var _varlikDisplayChangeCache = Object.create(null);

function rememberVarlikDisplayPrice(asset, price) {
    var sym = (asset || '').toUpperCase();
    if (!sym) return;
    var p = Number(price);
    if (Number.isFinite(p) && p > 0) _varlikDisplayPriceCache[sym] = p;
}

function getVarlikDisplayPrice(asset, rowEl) {
    var sym = (asset || '').toUpperCase();
    if (!sym) return null;
    if (typeof isTestWalletStableAsset === 'function' && isTestWalletStableAsset(sym)) {
        rememberVarlikDisplayPrice(sym, 1);
        return 1;
    }
    var symbol = normalizeAssetToSymbol(asset, QUOTE);
    var live = resolveMarketLivePrice(symbol);
    if (live == null || !(live > 0)) live = getAssetPrice(asset);
    if (live != null && Number.isFinite(live) && live > 0) {
        rememberVarlikDisplayPrice(sym, live);
        return live;
    }
    if (rowEl) {
        var priceCell = rowEl.querySelector('.price-cell');
        if (priceCell) {
            var fromAttr = parseFloat(priceCell.getAttribute('data-price') || '');
            if (Number.isFinite(fromAttr) && fromAttr > 0) {
                rememberVarlikDisplayPrice(sym, fromAttr);
                return fromAttr;
            }
        }
    }
    var cached = _varlikDisplayPriceCache[sym];
    if (cached != null && Number.isFinite(cached) && cached > 0) return cached;
    return null;
}

function getVarlikDisplayChangePct(asset, rowEl) {
    var sym = (asset || '').toUpperCase();
    var live = getAssetChangePct(asset);
    if (live != null && Number.isFinite(live)) {
        if (sym) _varlikDisplayChangeCache[sym] = live;
        return live;
    }
    if (rowEl) {
        var changeCell = rowEl.querySelector('.change-pct');
        if (changeCell) {
            var fromAttr = parseFloat(changeCell.getAttribute('data-change-pct') || '');
            if (Number.isFinite(fromAttr)) return fromAttr;
        }
    }
    if (sym && _varlikDisplayChangeCache[sym] != null && Number.isFinite(_varlikDisplayChangeCache[sym])) {
        return _varlikDisplayChangeCache[sym];
    }
    return null;
}

function formatVarlikPriceDisplay(asset, price) {
    if (price != null && Number.isFinite(price) && price > 0) return fmtCoinPrice(price);
    var cached = _varlikDisplayPriceCache[(asset || '').toUpperCase()];
    if (cached != null && Number.isFinite(cached) && cached > 0) return fmtCoinPrice(cached);
    return '…';
}

function walletAssetTotalQty(a) {
    if (!a) return 0;
    var free = Number(a.free) || 0;
    var locked = Number(a.locked) || 0;
    var botLocked = Number(a.bot_locked) || 0;
    var isTest = typeof State !== 'undefined' && State.isTestAccount;
    var derived = isTest ? (free + locked + botLocked) : (free + locked);
    var explicit = (a.total != null && Number.isFinite(Number(a.total))) ? Number(a.total) : null;
    if (derived > 0) return derived;
    if (explicit != null && explicit > 0) return explicit;
    return derived;
}

function testWalletAssetQtyBroken(a) {
    if (!a || typeof isTestWalletStableAsset === 'function' && isTestWalletStableAsset(a.asset)) return false;
    var bl = Number(a.bot_locked) || 0;
    var total = Number(a.total);
    var derived = (Number(a.free) || 0) + (Number(a.locked) || 0) + bl;
    if (derived <= 0) return false;
    if (!Number.isFinite(total) || total <= 0) return true;
    return bl > 0 && Math.abs(total - derived) > 1e-8;
}

function repairTestWalletAssets(assets) {
    if (!Array.isArray(assets)) return assets;
    return assets.map(function (a) {
        if (!a || typeof a !== 'object') return a;
        var out = Object.assign({}, a);
        var bl = Number(out.bot_locked) || 0;
        var free = Number(out.free) || 0;
        var locked = Number(out.locked) || 0;
        var total = Number(out.total);
        var derived = free + locked + bl;
        if (derived > 0 && (!Number.isFinite(total) || total <= 0 || (bl > 0 && Math.abs(total - derived) > 1e-8))) {
            out.total = derived;
        }
        return out;
    });
}

var TEST_WALLET_STABLE_ASSETS = ['USDT', 'USDC', 'FDUSD', 'BUSD', 'TUSD', 'DAI'];

function isTestWalletStableAsset(asset) {
    return TEST_WALLET_STABLE_ASSETS.indexOf((asset || '').toUpperCase()) >= 0;
}

/** Test paper: stable Toplam/Değer = kullanılabilir + kilitli + bot kilitli (quote bot bakiyesi dahil). */
function testAccountVarlikStableRowTotalQty(a) {
    if (!a) return 0;
    return testAccountVarlikAvailableQty(a) + (Number(a.locked) || 0) + (Number(a.bot_locked) || 0);
}

/** Test paper: Değer = Toplam qty × canlı fiyat (stable satırlarda qty ≈ USD). */
function testAccountVarlikLiveValueUsd(asset, totalQty, price) {
    var qty = Number(totalQty) || 0;
    if (qty <= 0) return 0;
    if (isTestWalletStableAsset(asset)) return qty;
    var px = (price != null && Number.isFinite(Number(price)) && Number(price) > 0)
        ? Number(price)
        : (typeof getAssetPrice === 'function' ? getAssetPrice(asset) : null);
    if (px == null || !Number.isFinite(px) || px <= 0) return null;
    return qty * px;
}

/** Test paper: satır Değer — stable tam satır; base = kullanılabilir + kilitli + bot (satır gösterimi). */
function testAccountVarlikRowValueUsd(a, price) {
    if (!a) return 0;
    var asset = (a.asset || '').toUpperCase();
    var av = testAccountVarlikAvailableQty(a);
    var locked = Number(a.locked) || 0;
    var bot = Number(a.bot_locked) || 0;
    if (isTestWalletStableAsset(asset)) {
        return testAccountVarlikLiveValueUsd(asset, av + locked + bot, price) || 0;
    }
    var avUsd = testAccountVarlikLiveValueUsd(asset, av, price);
    var lockedUsd = testAccountVarlikLiveValueUsd(asset, locked, price);
    var botUsd = 0;
    if (bot > 0) {
        if (a.bot_locked_usd != null && Number.isFinite(Number(a.bot_locked_usd)) && Number(a.bot_locked_usd) > 0) {
            botUsd = Number(a.bot_locked_usd);
        } else {
            botUsd = testAccountVarlikLiveValueUsd(asset, bot, price) || 0;
        }
    }
    return (avUsd != null && Number.isFinite(avUsd) ? avUsd : 0)
        + (lockedUsd != null && Number.isFinite(lockedUsd) ? lockedUsd : 0)
        + botUsd;
}

/** Test paper: dağılım % payı — stable yalnızca kullanılabilir+kilitli; base bot dahil (çift sayım yok). */
function testAccountVarlikRowShareUsd(a, price) {
    if (!a) return 0;
    var asset = (a.asset || '').toUpperCase();
    var av = testAccountVarlikAvailableQty(a);
    var locked = Number(a.locked) || 0;
    var bot = Number(a.bot_locked) || 0;
    if (isTestWalletStableAsset(asset)) {
        return testAccountVarlikLiveValueUsd(asset, av + locked, price) || 0;
    }
    return testAccountVarlikRowValueUsd(a, price);
}

function testAccountVarlikRowLiveValueFromDom(row, price) {
    if (!row) return 0;
    var asset = row.getAttribute('data-asset') || '';
    if (isTestWalletStableAsset(asset)) {
        return parseFloat(row.getAttribute('data-total') || '') || 0;
    }
    var avQty = parseFloat(row.getAttribute('data-available') || '') || 0;
    var lockedQty = parseFloat(row.getAttribute('data-locked') || '') || 0;
    var botLockedQty = parseFloat(row.getAttribute('data-bot-locked') || '') || 0;
    var botLockedUsdHint = parseFloat(row.getAttribute('data-bot-locked-usd') || '');
    var avUsd = testAccountVarlikLiveValueUsd(asset, avQty, price) || 0;
    var lockedUsd = testAccountVarlikLiveValueUsd(asset, lockedQty, price) || 0;
    var botUsd = 0;
    if (botLockedQty > 0) {
        if (Number.isFinite(botLockedUsdHint) && botLockedUsdHint > 0) {
            botUsd = botLockedUsdHint;
        } else {
            botUsd = testAccountVarlikBotLockedUsd(asset, botLockedQty, price) || 0;
        }
    }
    return avUsd + lockedUsd + botUsd;
}

function testAccountVarlikRowShareUsdFromDom(row, price) {
    if (!row) return 0;
    var asset = row.getAttribute('data-asset') || '';
    if (isTestWalletStableAsset(asset)) {
        var avQty = parseFloat(row.getAttribute('data-available') || '') || 0;
        var lockedQty = parseFloat(row.getAttribute('data-locked') || '') || 0;
        return testAccountVarlikLiveValueUsd(asset, avQty + lockedQty, price) || 0;
    }
    return testAccountVarlikRowLiveValueFromDom(row, price);
}

function testAccountUsdtAvailableFromTable(tbody) {
    var root = tbody || document.getElementById('varliklarTableBody');
    if (!root) return 0;
    var row = root.querySelector('tr[data-asset="USDT"]');
    if (!row) return 0;
    var avQty = parseFloat(row.getAttribute('data-available') || '') || 0;
    return avQty > 0 ? avQty : 0;
}

function testAccountRunningBotsEquityUsd() {
    if (typeof State === 'undefined') return 0;
    var bots = (State.summary && Array.isArray(State.summary.bots) && State.summary.bots.length)
        ? State.summary.bots
        : (Array.isArray(State.bots) ? State.bots : []);
    var sum = 0;
    bots.forEach(function (b) {
        if (!b) return;
        var st = String(b.status || '').toLowerCase();
        if (st !== 'running' && st !== 'active') return;
        if (typeof resolveBotCurrentUsd === 'function') {
            var live = resolveBotCurrentUsd(b);
            if (live != null && Number.isFinite(live)) {
                sum += live;
                return;
            }
        }
        var cu = b.current_usd;
        if (cu != null && Number.isFinite(Number(cu))) {
            sum += Number(cu);
            return;
        }
        var budget = Number(b.budget_usd || b.initial_capital_usdt || b.initial_usd || 0);
        var pnl = Number(b.total_pnl_usd || b.pnl_usd || b.total_pnl || 0);
        if (budget > 0 || pnl !== 0) sum += budget + pnl;
    });
    return sum;
}

/** Test paper: TOPLAM SPOT = USDT kullanılabilir + çalışan bot equity + kilitli. */
function testAccountKpiTotalUsd(tbody) {
    var avail = testAccountUsdtAvailableFromTable(tbody);
    if (!(avail > 0) && assetsState && assetsState.wallet) {
        if (typeof assetsState.wallet.available_usd === 'number') avail = assetsState.wallet.available_usd;
        else avail = testAccountUsdtAvailablePool(assetsState.wallet.assets || []);
    }
    var botEq = testAccountRunningBotsEquityUsd();
    if (!(botEq > 0) && assetsState && assetsState.wallet && typeof assetsState.wallet.bot_locked_usd === 'number') {
        botEq = assetsState.wallet.bot_locked_usd;
    }
    var locked = testAccountReadStripUsdValue(document.getElementById('binanceLockedAssets'));
    return avail + botEq + locked;
}

function testAccountVarlikPortfolioTotal(list) {
    if (!list || !list.length) return 0;
    return list.reduce(function (sum, x) { return sum + (Number(x._valueUsd) || 0); }, 0);
}

function testAccountVarlikBotLockedDisplay(asset, botLocked, price) {
    var qty = Number(botLocked) || 0;
    if (qty <= 0) return '0';
    if (isTestWalletStableAsset(asset)) {
        var usd = testAccountVarlikBotLockedUsd(asset, qty, price);
        return (usd != null && Number.isFinite(usd)) ? fmtUsd(usd) : fmtVarlikQty(qty, asset);
    }
    return fmtVarlikQty(qty, asset);
}

function testAccountVarlikAvailableQty(a) {
    if (!a) return 0;
    var free = Number(a.free) || 0;
    var botLocked = Number(a.bot_locked) || 0;
    if (a.available != null && Number.isFinite(Number(a.available))) return Number(a.available);
    return Math.max(0, free - botLocked);
}

/** Test paper: Kullanılabilir qty × canlı fiyat (USDT strip ile tablo uyumlu). */
function testAccountVarlikAvailableUsd(asset, availableQty, price) {
    return testAccountVarlikLiveValueUsd(asset, availableQty, price);
}

function testAccountVarlikAvailableTotalFromAssets(assets) {
    if (!Array.isArray(assets)) return 0;
    var sum = 0;
    assets.forEach(function (a) {
        if (!a || (typeof isWalletAssetSuspiciousFx === 'function' && isWalletAssetSuspiciousFx(a))) return;
        var qty = testAccountVarlikAvailableQty(a);
        if (qty <= 0) return;
        var price = typeof getAssetPrice === 'function' ? getAssetPrice(a.asset) : null;
        var usd = testAccountVarlikAvailableUsd(a.asset, qty, price);
        if (usd != null && Number.isFinite(usd)) sum += usd;
    });
    return sum;
}

function testAccountVarlikBotLockedQty(a) {
    if (!a) return 0;
    return Number(a.bot_locked) || 0;
}

function testAccountVarlikBotLockedUsd(asset, botLockedQty, price) {
    return testAccountVarlikLiveValueUsd(asset, botLockedQty, price);
}

function testAccountVarlikBotLockedTotalFromAssets(assets) {
    if (!Array.isArray(assets)) return 0;
    var sum = 0;
    assets.forEach(function (a) {
        if (!a || (typeof isWalletAssetSuspiciousFx === 'function' && isWalletAssetSuspiciousFx(a))) return;
        var qty = testAccountVarlikBotLockedQty(a);
        if (qty <= 0) return;
        var price = typeof getAssetPrice === 'function' ? getAssetPrice(a.asset) : null;
        var usd = testAccountVarlikBotLockedUsd(a.asset, qty, price);
        if (usd != null && Number.isFinite(usd)) sum += usd;
    });
    return sum;
}

function testAccountUsdtAvailablePool(assets) {
    if (!Array.isArray(assets)) return 0;
    var sum = 0;
    assets.forEach(function (a) {
        if (!a || !isTestWalletStableAsset(a.asset)) return;
        sum += testAccountVarlikAvailableQty(a);
    });
    return sum;
}

/** Cüzdan satırı Al/Sat — her zaman aktif; yetersiz bakiye spot modal / emirde doğrulanır. */
function varlikRowTradeState(a, assets) {
    assets = assets || [];
    var asset = (a && a.asset) || '';
    var sym = asset.toUpperCase();
    var isQuote = (typeof isTestWalletStableAsset === 'function' && isTestWalletStableAsset(asset))
        || sym === 'USDT' || sym === 'BUSD' || sym === 'FDUSD';
    var isTest = typeof State !== 'undefined' && State.isTestAccount;
    var available = isTest
        ? testAccountVarlikAvailableQty(a)
        : ((a.available != null && Number.isFinite(Number(a.available)))
            ? Number(a.available)
            : Math.max(0, (Number(a.free) || 0) - (Number(a.bot_locked) || 0)));
    var total = typeof walletAssetTotalQty === 'function' ? walletAssetTotalQty(a) : ((Number(a.free) || 0) + (Number(a.locked) || 0));
    var usdtPool = isTest && typeof testAccountUsdtAvailablePool === 'function'
        ? testAccountUsdtAvailablePool(assets)
        : null;
    if (usdtPool == null && Array.isArray(assets)) {
        var usdtRow = assets.find(function (x) { return x && (x.asset || '').toUpperCase() === 'USDT'; });
        if (usdtRow) {
            usdtPool = (usdtRow.available != null && Number.isFinite(Number(usdtRow.available)))
                ? Number(usdtRow.available)
                : Math.max(0, (Number(usdtRow.free) || 0) - (Number(usdtRow.bot_locked) || 0));
        }
    }
    var sellHint = available > 0
        ? ('kullanılabilir: ' + fmtNum(available, 8))
        : (total > 0 ? 'miktar emir ekranında' : 'bakiye yok');
    var buyHint = isQuote
        ? 'quote bakiyesi'
        : (usdtPool > 0 ? ('USDT: ' + fmtNum(usdtPool, 2)) : 'USDT ile alış');
    var prefix = isTest ? 'test paper — ' : '';
    return {
        canBuy: true,
        canSell: true,
        sellTitle: 'Satış (' + prefix + sellHint + ')',
        buyTitle: 'Alış (' + prefix + buyHint + ')',
        sellDisabled: '',
        buyDisabled: '',
    };
}

function testAccountVarlikRowTradeState(a, assets) {
    return varlikRowTradeState(a, assets);
}

function updateTestAccountStripCell(stripEl, sum) {
    if (!stripEl) return;
    var next = Number(sum);
    if (!Number.isFinite(next)) next = 0;
    var prev = parseFloat(stripEl.getAttribute('data-value') || '');
    if (Number.isFinite(prev) && !kpiUsdDisplayChanged(prev, next)) return;
    stripEl.classList.remove('binance-assets-strip-value--loading', 'blink-positive', 'blink-negative');
    stripEl.setAttribute('data-value', String(next));
    var txt = typeof fmtUsd === 'function' ? fmtUsd(next) : String(next);
    if (typeof setTextIfChanged === 'function') setTextIfChanged(stripEl, txt);
    else stripEl.textContent = txt;
}

var _testKpiRefreshTimer = null;
var TEST_KPI_REFRESH_MS = 450;

function scheduleTestAccountKpiCuzdanRefresh() {
    if (_testKpiRefreshTimer) return;
    _testKpiRefreshTimer = setTimeout(function () {
        _testKpiRefreshTimer = null;
        if (typeof updateTestAccountKpiCuzdanFromStrip === 'function') updateTestAccountKpiCuzdanFromStrip();
    }, TEST_KPI_REFRESH_MS);
}

function testAccountReadStripUsdValue(el) {
    if (!el) return 0;
    var fromAttr = parseFloat(el.getAttribute('data-value') || '');
    if (Number.isFinite(fromAttr)) return fromAttr;
    return parseFloat(String(el.textContent || '').replace(/[^0-9.-]/g, '')) || 0;
}

/** Test paper: TOPLAM SPOT BAKİYESİ = strip (Kullanılabilir + Bot kilitli + Kilitli). */
function testAccountStripTotalUsd() {
    return testAccountReadStripUsdValue(document.getElementById('binanceAvailableAssets'))
        + testAccountReadStripUsdValue(document.getElementById('binanceBotLockedAssets'))
        + testAccountReadStripUsdValue(document.getElementById('binanceLockedAssets'));
}

function updateTestAccountKpiCuzdanFromStrip() {
    if (typeof State === 'undefined' || !State.isTestAccount) return;
    var tbody = document.getElementById('varliklarTableBody');
    var total = testAccountKpiTotalUsd(tbody);
    if (!(total > 0) && assetsState && assetsState.wallet && Array.isArray(assetsState.wallet.assets)) {
        var avail = testAccountUsdtAvailablePool(assetsState.wallet.assets);
        var botEq = testAccountRunningBotsEquityUsd();
        if (!(botEq > 0) && typeof assetsState.wallet.bot_locked_usd === 'number') {
            botEq = assetsState.wallet.bot_locked_usd;
        }
        var locked = typeof assetsState.wallet.locked_usd === 'number' ? assetsState.wallet.locked_usd : 0;
        total = avail + botEq + locked;
    }
    if (!(total > 0) && _kpiCuzdanLastSpot > 0) total = _kpiCuzdanLastSpot;
    if (!(total > 0) && State.accountId) {
        var snap = _loadPersistedKpiCuzdanFields(State.accountId);
        if (snap && snap.spot > 0) total = snap.spot;
    }
    if (!(total > 0)) return;
    _kpiCuzdanLastSpot = total;
    var el = document.getElementById('kpiCuzdan');
    if (typeof updateKpiCuzdanBalance === 'function') updateKpiCuzdanBalance(el, total);
    if (typeof updateTestAccountCuzdanDailyPnlLive === 'function') updateTestAccountCuzdanDailyPnlLive(total);
}

/** TR takvim günü (Europe/Istanbul) — YYYY-MM-DD */
function testAccountTrDateKey() {
    try {
        return new Intl.DateTimeFormat('en-CA', {
            timeZone: 'Europe/Istanbul',
            year: 'numeric',
            month: '2-digit',
            day: '2-digit'
        }).format(new Date());
    } catch (e) {
        return new Date().toISOString().slice(0, 10);
    }
}

function testAccountDailySpotRefStorageKey(accountId) {
    return 'test_daily_spot_ref_v1_' + accountId;
}

/** Gün başı (TR 00:00 sonrası ilk değer) spot strip toplamı referans; gün değişince yenilenir. */
function testAccountEnsureDailySpotRef(accountId, currentTotal) {
    if (!accountId) return null;
    var total = Number(currentTotal);
    if (!Number.isFinite(total) || total <= 0) return null;
    var today = testAccountTrDateKey();
    var key = testAccountDailySpotRefStorageKey(accountId);
    var stored = null;
    try {
        var raw = localStorage.getItem(key);
        if (raw) stored = JSON.parse(raw);
    } catch (e) {}
    if (!stored || stored.date !== today || !Number.isFinite(Number(stored.refUsd)) || Number(stored.refUsd) <= 0) {
        stored = { date: today, refUsd: total, setAt: Date.now() };
        try { localStorage.setItem(key, JSON.stringify(stored)); } catch (e2) {}
    }
    if (window.apiClient && accountId) {
        window.apiClient.post('/api/binance/test-daily-spot-ref', {
            account_id: accountId,
            ref_usd: Number(stored.refUsd),
            date: today
        }).catch(function () {});
    }
    return Number(stored.refUsd);
}

/** Test paper: Günlük Değişim = canlı strip toplamı − gün açılış referansı (TR 00:00). */
function updateTestAccountCuzdanDailyPnlLive(currentTotal) {
    if (typeof State === 'undefined' || !State.isTestAccount || !State.accountId) return;
    var total = Number(currentTotal);
    if (!Number.isFinite(total) || total <= 0) return;
    var ref = testAccountEnsureDailySpotRef(State.accountId, total);
    if (ref == null || !(ref > 0)) return;
    var pnlUsd = total - ref;
    var pnlPct = (pnlUsd / ref) * 100;
    _kpiCuzdanPnlDisplay.pnlUsd = pnlUsd;
    _kpiCuzdanPnlDisplay.pnlPct = pnlPct.toFixed(2);
    var cuzdanPnlEl = document.getElementById('kpiCuzdanPnl');
    if (cuzdanPnlEl) {
        setKpiUsdTextIfChanged(cuzdanPnlEl, pnlUsd);
        var pnlColor = pnlUsd >= 0 ? '#0ecb81' : '#f6465d';
        if (cuzdanPnlEl.style.color !== pnlColor) cuzdanPnlEl.style.color = pnlColor;
        cuzdanPnlEl.classList.remove('blink-positive', 'blink-negative');
    }
    var pe = document.getElementById('kpiCuzdanPnlPct');
    if (pe) {
        setKpiPctTextIfChanged(pe, pnlPct);
        var pctColor = pnlUsd >= 0 ? '#0ecb81' : '#f6465d';
        if (pe.style.color !== pctColor) pe.style.color = pctColor;
        pe.classList.remove('blink-positive', 'blink-negative');
    }
    _persistKpiCuzdanSessionCache(State.accountId, total, pnlUsd, pnlPct);
}

/** Test paper: strip = tablo satırlarından canlı (Kullanılabilir qty×fiyat, Bot kilitli qty×fiyat). */
function updateTestAccountStripFromTable(tbody, opts) {
    opts = opts || {};
    if (typeof State === 'undefined' || !State.isTestAccount) return;
    var stripAvailable = document.getElementById('binanceAvailableAssets');
    var stripBotLocked = document.getElementById('binanceBotLockedAssets');
    var root = tbody || document.getElementById('varliklarTableBody');
    if (!root) return;
    var walletAssets = (assetsState && assetsState.wallet && assetsState.wallet.assets) || [];
    var availSum = 0;
    var botSum = testAccountRunningBotsEquityUsd();
    var lockedSum = 0;
    if (walletAssets.length && typeof testAccountUsdtAvailablePool === 'function') {
        availSum = testAccountUsdtAvailablePool(walletAssets);
    }
    if (!(availSum > 0)) {
        root.querySelectorAll('tr[data-asset]').forEach(function (row) {
            var asset = row.getAttribute('data-asset') || '';
            if (isTestWalletStableAsset(asset)) {
                var avQty = parseFloat(row.getAttribute('data-available') || '') || 0;
                if (avQty > 0) availSum += avQty;
            }
        });
    }
    root.querySelectorAll('tr[data-asset]').forEach(function (row) {
        var asset = row.getAttribute('data-asset') || '';
        var lockedQty = parseFloat(row.getAttribute('data-locked') || '') || 0;
        if (lockedQty > 0) {
            var priceCell = row.querySelector('.price-cell');
            var price = priceCell ? parseFloat(priceCell.getAttribute('data-price') || '') : NaN;
            if (!Number.isFinite(price) || price <= 0) {
                price = typeof getAssetPrice === 'function' ? getAssetPrice(asset) : null;
            }
            var lockedUsd = testAccountVarlikLiveValueUsd(asset, lockedQty, price);
            if (lockedUsd != null && Number.isFinite(lockedUsd)) lockedSum += lockedUsd;
        }
    });
    if (!(botSum > 0)) {
        root.querySelectorAll('tr[data-asset]').forEach(function (row) {
            var asset = row.getAttribute('data-asset') || '';
            var priceCell = row.querySelector('.price-cell');
            var price = priceCell ? parseFloat(priceCell.getAttribute('data-price') || '') : NaN;
            if (!Number.isFinite(price) || price <= 0) {
                price = typeof getAssetPrice === 'function' ? getAssetPrice(asset) : null;
            }
            var blQty = parseFloat(row.getAttribute('data-bot-locked') || '') || 0;
            if (blQty > 0) {
                var blUsd = testAccountVarlikBotLockedUsd(asset, blQty, price);
                if (blUsd != null && Number.isFinite(blUsd)) botSum += blUsd;
            }
        });
    }
    if (!(availSum > 0) && assetsState && assetsState.wallet && typeof assetsState.wallet.available_usd === 'number') {
        availSum = assetsState.wallet.available_usd;
    }
    if (!(botSum > 0) && assetsState && assetsState.wallet && typeof assetsState.wallet.bot_locked_usd === 'number') {
        botSum = assetsState.wallet.bot_locked_usd;
    }
    updateTestAccountStripCell(stripAvailable, availSum);
    updateTestAccountStripCell(stripBotLocked, botSum);
    var stripLocked = document.getElementById('binanceLockedAssets');
    if (stripLocked) updateTestAccountStripCell(stripLocked, lockedSum);
    if (opts.immediateKpi) {
        if (_testKpiRefreshTimer) {
            clearTimeout(_testKpiRefreshTimer);
            _testKpiRefreshTimer = null;
        }
        if (typeof updateTestAccountKpiCuzdanFromStrip === 'function') updateTestAccountKpiCuzdanFromStrip();
    } else if (typeof scheduleTestAccountKpiCuzdanRefresh === 'function') {
        scheduleTestAccountKpiCuzdanRefresh();
    }
    if (State.accountId) _persistBinanceWalletCache(State.accountId);
}

function updateTestAccountAvailableStripFromTable(tbody) {
    updateTestAccountStripFromTable(tbody);
}

function updateTestVarlikRowLiveMetrics(row, tbody) {
    if (!row || typeof State === 'undefined' || !State.isTestAccount) return;
    var asset = row.getAttribute('data-asset') || '';
    if (isTestWalletStableAsset(asset)) return;
    var priceCell = row.querySelector('.price-cell');
    var valueCell = row.querySelector('.value-cell');
    if (!priceCell || !valueCell) return;
    var price = parseFloat(priceCell.getAttribute('data-price') || '');
    if (!Number.isFinite(price) || price <= 0) {
        price = typeof getAssetPrice === 'function' ? getAssetPrice(asset) : null;
    }
    var botLockedQty = parseFloat(row.getAttribute('data-bot-locked') || '') || 0;
    var liveVal = testAccountVarlikRowLiveValueFromDom(row, price);
    if (liveVal != null && Number.isFinite(liveVal)) {
        var oldVal = parseFloat(valueCell.getAttribute('data-value') || '') || 0;
        if (Math.abs(oldVal - liveVal) < 0.01) {
            return;
        }
        valueCell.setAttribute('data-value', liveVal);
        var valTxt = typeof fmtUsd === 'function' ? fmtUsd(liveVal) : String(liveVal);
        if (typeof setTextIfChanged === 'function') setTextIfChanged(valueCell, valTxt);
        else valueCell.textContent = valTxt;
    }
    var tds = row.querySelectorAll('td');
    if (tds[3] && botLockedQty > 0) {
        var botLockedUsd = parseFloat(row.getAttribute('data-bot-locked-usd') || '');
        if (!(botLockedUsd > 0)) {
            botLockedUsd = testAccountVarlikBotLockedUsd(asset, botLockedQty, price);
        }
        if (botLockedUsd != null && Number.isFinite(botLockedUsd)) {
            tds[3].setAttribute('data-value', botLockedUsd);
            var blTxt = testAccountVarlikBotLockedDisplay(asset, botLockedQty, price);
            if (typeof setTextIfChanged === 'function') setTextIfChanged(tds[3], blTxt);
            else tds[3].textContent = blTxt;
        }
    }
}

function renderVarliklarList() {
    const tbody = document.getElementById('varliklarTableBody');
    const emptyEl = document.getElementById('varliklarEmpty');
    if (!tbody) return;
    const assets = assetsState.wallet.assets || [];
    let list = assets.filter(a => !isWalletAssetSuspiciousFx(a)).map(a => {
        const price = getVarlikDisplayPrice(a.asset);
        const isTestStable = typeof State !== 'undefined' && State.isTestAccount && isTestWalletStableAsset(a.asset);
        const total = isTestStable ? testAccountVarlikStableRowTotalQty(a) : walletAssetTotalQty(a);
        let valueUsd = (a.total_usd != null && Number.isFinite(Number(a.total_usd))) ? Number(a.total_usd) : null;
        if (typeof State !== 'undefined' && State.isTestAccount) {
            valueUsd = testAccountVarlikRowValueUsd(a, price);
        }
        if (valueUsd == null) valueUsd = 0;
        return { ...a, _price: price, _valueUsd: valueUsd, _total: total };
    });
    const filterUsd = function (x) {
        if (typeof State !== 'undefined' && State.isTestAccount) {
            if ((Number(x.bot_locked) || 0) > 0) return true;
            return (Number(x._valueUsd) || 0) >= VARLIKLAR_MIN_USD;
        }
        return (x.total_usd != null ? Number(x.total_usd) : 0) >= VARLIKLAR_MIN_USD;
    };
    list = list.filter(filterUsd);
    list = sortVarliklarListForDisplay(list);
    const totalPortfolio = (typeof State !== 'undefined' && State.isTestAccount)
        ? testAccountKpiTotalUsd(document.getElementById('varliklarTableBody'))
        : (typeof assetsState.wallet.total_usd === 'number' ? assetsState.wallet.total_usd : list.reduce((sum, x) => sum + (x._valueUsd || 0), 0));

    if (list.length === 0) {
        var hasRenderedRows = _varliklarTableHasRows();
        var walletPending = assetsState.wallet.status === 'loading' || assetsState.wallet.status === 'idle'
            || _varliklarWalletRefreshInflight;
        if (hasRenderedRows && walletPending) return;
        var msg;
        if (assetsState.wallet.status === 'error' && assetsState.wallet.error) {
            var e = assetsState.wallet.error;
            if (e.error_code === 'WALLET_NOT_READY' || (e.detail && String(e.detail).indexOf('No cached snapshot') !== -1)) {
                msg = 'Cüzdan hazırlanıyor. ';
                msg += '<button type="button" class="btn btn-sm" onclick="typeof binanceRefresh===\'function\'?binanceRefresh():BinanceAssetsPanel.refresh()" style="margin:0 0.25rem;">Yenile</button>';
            } else {
                var errMsg = (e.message || 'Bilinmeyen hata') + (e.retry_after ? ' (Retry after ' + e.retry_after + ' sn)' : '');
                msg = 'Binance cüzdanı alınamadı: ' + errMsg + ' — ';
                msg += '<button type="button" class="btn btn-sm" onclick="typeof binanceRefresh===\'function\'?binanceRefresh():BinanceAssetsPanel.refresh()" style="margin:0 0.25rem;">Yenile</button>';
                msg += '<a href="/ui/dashboard.html" onclick="try{localStorage.setItem(\'dashboard_active_tab\',\'settings\')}catch(e){}" class="btn btn-sm" style="margin-left:0.25rem;">Ayarlara git</a>';
            }
        } else if (assetsState.wallet.keys_configured === false && assetsState.wallet.keysMessage) {
            msg = assetsState.wallet.keysMessage;
        } else {
            msg = 'Varlık bulunamadı veya 1 USDT altı varlıklar gizlidir.';
        }
        tbody.innerHTML = '<tr><td colspan="10" style="padding: 2rem; text-align: center; color: var(--ds-text-secondary);">' + msg + '</td></tr>';
        if (emptyEl) emptyEl.style.display = 'none';
        var unpricedEl0 = document.getElementById('varliklarUnpricedNotice');
        if (unpricedEl0) unpricedEl0.style.display = 'none';
        return;
    }
    if (emptyEl) emptyEl.style.display = 'none';

    const logoInitials = (a) => (a.asset || ' ').substring(0, 2).toUpperCase();

    function rowData(a, rowEl) {
        const asset = a.asset || 'N/A';
        const symbol = normalizeAssetToSymbol(asset, QUOTE);
        const free = a.free || 0;
        const locked = a.locked || 0;
        var isTest = typeof State !== 'undefined' && State.isTestAccount;
        const isQuote = (asset || '').toUpperCase() === 'USDT' || (asset || '').toUpperCase() === 'BUSD' || (asset || '').toUpperCase() === 'FDUSD';
        const botLocked = Number(a.bot_locked) || 0;
        const available = (a.available != null && Number.isFinite(Number(a.available))) ? Number(a.available) : Math.max(0, free - botLocked);
        const total = isTest && isQuote ? (available + locked + botLocked) : (a._total || 0);
        const price = getVarlikDisplayPrice(asset, rowEl) ?? a._price;
        const valueUsd = a._valueUsd != null ? a._valueUsd : 0;
        const valueDisplay = Number.isFinite(valueUsd) ? fmtUsd(valueUsd) : '—';
        const pctPortfolio = totalPortfolio > 0
            ? (testAccountVarlikRowShareUsd(a, price) / totalPortfolio * 100).toFixed(2)
            : '0.00';
        const priceDisplay = formatVarlikPriceDisplay(asset, price);
        const changePct = getVarlikDisplayChangePct(asset, rowEl);
        const chFmt = formatVarlikChangePctDisplay(asset, changePct);
        const changeStr = chFmt.text;
        const changeColor = chFmt.color;
        const name = assetNameMap[asset] || asset;
        const initials = logoInitials(a);
        const logoUrl = (typeof getCoinLogoUrl === 'function' && getCoinLogoUrl(a.asset)) || null;
        var trade = varlikRowTradeState(a, assetsState.wallet.assets || []);
        const canSell = trade.canSell;
        const canBuy = trade.canBuy;
        const sellTitle = trade.sellTitle;
        const buyTitle = trade.buyTitle;
        const sellDisabled = trade.sellDisabled;
        const buyDisabled = trade.buyDisabled;
        var botLockedUsdLive = isTest && botLocked > 0 ? testAccountVarlikBotLockedUsd(asset, botLocked, price) : null;
        var botLockedDisplay = isTest
            ? testAccountVarlikBotLockedDisplay(asset, botLocked, price)
            : fmtVarlikQty(botLocked, asset);
        var botLockedUsdStored = (a.bot_locked_usd != null && Number.isFinite(Number(a.bot_locked_usd)))
            ? Number(a.bot_locked_usd)
            : ((botLockedUsdLive != null && Number.isFinite(botLockedUsdLive)) ? botLockedUsdLive : null);
        return { asset, symbol, free, locked, botLocked, available, total, price, valueUsd, valueDisplay, pctPortfolio, priceDisplay, changePct, changeStr, changeColor, name, initials, logoUrl, canSell, canBuy, sellTitle, buyTitle, sellDisabled, buyDisabled, botLockedDisplay, botLockedUsdLive, botLockedUsdStored };
    }

    var currentOrder = Array.from(tbody.querySelectorAll('tr[data-asset]')).map(function(tr) { return tr.getAttribute('data-asset'); });
    var newOrder = list.map(function(a) { return a.asset || 'N/A'; });
    var sameOrder = currentOrder.length === newOrder.length && currentOrder.every(function(asset, i) { return asset === newOrder[i]; });

    if (sameOrder && currentOrder.length > 0) {
        function patchTd(el, txt) {
            if (!el) return;
            if (typeof setTextIfChanged === 'function') setTextIfChanged(el, txt);
            else el.textContent = txt;
        }
        list.forEach(function(a, i) {
            var row = tbody.querySelector('tr[data-asset="' + (a.asset || 'N/A') + '"]');
            if (!row) return;
            var d = rowData(a, row);
            row.setAttribute('data-symbol', d.symbol);
            row.setAttribute('data-free', d.free);
            row.setAttribute('data-locked', d.locked);
            row.setAttribute('data-total', d.total);
            row.setAttribute('data-available', d.available);
            row.setAttribute('data-bot-locked', d.botLocked);
            if (d.botLockedUsdStored != null && Number.isFinite(d.botLockedUsdStored)) {
                row.setAttribute('data-bot-locked-usd', d.botLockedUsdStored);
            } else {
                row.removeAttribute('data-bot-locked-usd');
            }
            var symbolCell = row.querySelector('.varlik-symbol');
            if (symbolCell) patchTd(symbolCell, d.asset);
            var nameCell = row.querySelector('.varlik-name');
            if (nameCell) patchTd(nameCell, d.name);
            var priceCell = row.querySelector('.price-cell');
            if (priceCell && d.price != null && Number.isFinite(d.price)) {
                var oldPricePatch = parseFloat(priceCell.getAttribute('data-price') || '') || 0;
                if (Math.abs(oldPricePatch - d.price) >= 1e-10) {
                    applyVarlikPriceBlink(priceCell, d.price, oldPricePatch, d.asset);
                    priceCell.setAttribute('data-price', d.price);
                }
                patchTd(priceCell, d.priceDisplay);
            }
            var changeCell = row.querySelector('.change-pct');
            if (changeCell) {
                if (d.changePct != null) changeCell.setAttribute('data-change-pct', d.changePct);
                if (changeCell.style.color !== d.changeColor) changeCell.style.color = d.changeColor;
                patchTd(changeCell, d.changeStr);
            }
            var tds = row.querySelectorAll('td');
            if (tds[2]) patchTd(tds[2], fmtVarlikQty(d.total, d.asset));
            if (tds[3]) {
                patchTd(tds[3], d.botLockedDisplay);
                if (d.botLocked > 0 && d.botLockedUsdLive != null && Number.isFinite(d.botLockedUsdLive)) {
                    tds[3].setAttribute('data-value', d.botLockedUsdLive);
                } else {
                    tds[3].setAttribute('data-value', '0');
                }
            }
            if (tds[4]) patchTd(tds[4], fmtVarlikQty(d.locked, d.asset));
            if (tds[5]) patchTd(tds[5], fmtVarlikQty(d.available, d.asset));
            var valueCell = row.querySelector('.value-cell');
            if (valueCell) {
                valueCell.setAttribute('data-value', d.valueUsd);
                patchTd(valueCell, d.valueDisplay);
            }
            var actionsCell = row.querySelector('.varlik-card-actions');
            if (actionsCell) {
                var actionsHtml = varlikRowActionsHtml(d);
                var prevActions = row.getAttribute('data-actions-sig') || '';
                var nextSig = (d.canBuy ? '1' : '0') + (d.canSell ? '1' : '0') + d.symbol;
                if (prevActions !== nextSig || !actionsCell.querySelector('.btn-al-sat-wrap')
                    || actionsCell.querySelector('button:disabled')) {
                    actionsCell.innerHTML = actionsHtml;
                    row.setAttribute('data-actions-sig', nextSig);
                }
            }
        });
        lastWalletHash = hashWalletAssets(assetsState.wallet.assets);
        _varliklarHasRenderedRows = true;
    } else {
        tbody.innerHTML = list.map(function(a) {
            var d = rowData(a);
            var actionsSig = (d.canBuy ? '1' : '0') + (d.canSell ? '1' : '0') + d.symbol;
            return '<tr class="varlik-row" data-asset="' + d.asset + '" data-symbol="' + d.symbol + '" data-free="' + d.free + '" data-locked="' + d.locked + '" data-total="' + d.total + '" data-available="' + d.available + '" data-bot-locked="' + d.botLocked + '" data-actions-sig="' + actionsSig + '"' + (d.botLockedUsdStored != null && Number.isFinite(d.botLockedUsdStored) ? ' data-bot-locked-usd="' + d.botLockedUsdStored + '"' : '') + '>' +
                varlikAssetCellHtml(d) +
                varlikFiyatCellHtml(d) +
                '<td class="varlik-num-cell col-center" data-label="Toplam">' + fmtVarlikQty(d.total, d.asset) + '</td>' +
                '<td class="varlik-num-cell col-center" data-label="Bot kilitli"' + (d.botLockedUsdLive != null && Number.isFinite(d.botLockedUsdLive) ? ' data-value="' + d.botLockedUsdLive + '"' : '') + '>' + d.botLockedDisplay + '</td>' +
                '<td class="varlik-num-cell col-center" data-label="Kilitli">' + fmtVarlikQty(d.locked, d.asset) + '</td>' +
                '<td class="varlik-num-cell col-center" data-label="Kullanılabilir">' + fmtVarlikQty(d.available, d.asset) + '</td>' +
                '<td class="varlik-num-cell value-cell col-center" data-value="' + d.valueUsd + '" data-label="Değer">' + d.valueDisplay + '</td>' +
                '<td class="varlik-card-actions col-action col-center" data-label="İşlem">' + varlikRowActionsHtml(d) + '</td></tr>';
        }).join('');
    }
    _varliklarHasRenderedRows = list.length > 0;
    lastWalletHash = hashWalletAssets(assetsState.wallet.assets);
    var unpricedEl = document.getElementById('varliklarUnpricedNotice');
    if (unpricedEl) unpricedEl.style.display = 'none';
    if (typeof State !== 'undefined' && State.isTestAccount) {
        if (typeof updateTestAccountStripFromTable === 'function') {
            updateTestAccountStripFromTable(tbody, { immediateKpi: true });
        } else if (typeof renderAssetsSummary === 'function') {
            renderAssetsSummary();
        }
    }
    if (State.accountId && list.length > 0) _persistBinanceWalletCache(State.accountId);
    if (list.length > 0 && typeof refreshVarliklarWalletMarketData === 'function') {
        refreshVarliklarWalletMarketData(true);
    }
}

var _varlikPriceBlinkUntil = {};

/** Cüzdan tablosu fiyat blink — Mevcut Botlar ile aynı efekt (mevcutBotPriceFlashUp/Down). */
function applyVarlikPriceBlink(priceCell, newPrice, oldPrice, asset) {
    if (!priceCell || !Number.isFinite(newPrice) || !Number.isFinite(oldPrice)) return;
    if (Math.abs(newPrice - oldPrice) < 1e-10) return;
    if (typeof isTestWalletStableAsset === 'function' && asset && isTestWalletStableAsset(asset)) return;
    var key = (asset || '') + '|' + (priceCell.closest('tr') && priceCell.closest('tr').getAttribute('data-asset') || '');
    var now = Date.now();
    var cooldownMs = (typeof FINANCE_BOT_PRICE_BLINK_COOLDOWN_MS === 'number') ? FINANCE_BOT_PRICE_BLINK_COOLDOWN_MS : 350;
    if (_varlikPriceBlinkUntil[key] && now < _varlikPriceBlinkUntil[key]) return;
    _varlikPriceBlinkUntil[key] = now + cooldownMs;
    var tone = newPrice > oldPrice ? 'up' : 'down';
    if (typeof applyFinanceBotPriceBlink === 'function') {
        applyFinanceBotPriceBlink(priceCell, newPrice, oldPrice, tone);
        return;
    }
    priceCell.classList.remove('mevcut-bot-blink-up', 'mevcut-bot-blink-down', 'varlik-price-flash-up', 'varlik-price-flash-down', 'price-up', 'price-down', 'price-neutral', 'blink-positive', 'blink-negative');
    void priceCell.offsetWidth;
    priceCell.classList.add(newPrice > oldPrice ? 'mevcut-bot-blink-up' : 'mevcut-bot-blink-down');
    setTimeout(function () {
        priceCell.classList.remove('mevcut-bot-blink-up', 'mevcut-bot-blink-down');
    }, 780);
}
window.applyVarlikPriceBlink = applyVarlikPriceBlink;

var _varliklarPriceTickLastAt = 0;
var VARLIKLAR_PRICE_TICK_MIN_MS = 350;

function tickVarliklarPrices(opts) {
    opts = opts || {};
    const tbody = document.getElementById('varliklarTableBody');
    if (!tbody || !tbody.querySelector('tr[data-asset]')) return;
    var now = Date.now();
    if (!opts.skipThrottle && (now - _varliklarPriceTickLastAt < VARLIKLAR_PRICE_TICK_MIN_MS)) return;
    _varliklarPriceTickLastAt = now;
    const isTestAcct = typeof State !== 'undefined' && State.isTestAccount;
    const rows = tbody.querySelectorAll('tr[data-asset]');
    const symbolAttr = function (row) {
        return row.getAttribute('data-symbol') || normalizeAssetToSymbol(row.getAttribute('data-asset') || '', QUOTE);
    };
    rows.forEach(function (row) {
        const asset = row.getAttribute('data-asset');
        const symbol = symbolAttr(row);
        const priceCell = row.querySelector('.price-cell');
        const valueCell = row.querySelector('.value-cell');
        const changeCell = row.querySelector('.change-pct');
        if (!priceCell || !valueCell) return;
        const price = getVarlikDisplayPrice(asset, row);
        const oldPrice = parseFloat(priceCell.getAttribute('data-price') || '') || 0;
        if (price == null || !Number.isFinite(price)) return;
        const priceTxt = typeof formatVarlikPriceDisplay === 'function'
            ? formatVarlikPriceDisplay(asset, price)
            : fmtCoinPrice(price);
        if (Math.abs(oldPrice - price) >= 1e-10) {
            applyVarlikPriceBlink(priceCell, price, oldPrice, asset);
            priceCell.setAttribute('data-price', price);
        }
        if (typeof setTextIfChanged === 'function') setTextIfChanged(priceCell, priceTxt);
        else if (priceCell.textContent !== priceTxt) priceCell.textContent = priceTxt;
        if (changeCell) {
            var changePct = getVarlikDisplayChangePct(asset, row);
            if (changePct == null) {
                var miniRow = window.marketStore && window.marketStore.getMini ? window.marketStore.getMini(symbol) : null;
                if (miniRow && Number.isFinite(miniRow.changePct)) changePct = miniRow.changePct;
            }
            var chDisp = formatVarlikChangePctDisplay(asset, changePct);
            if (changePct != null) changeCell.setAttribute('data-change-pct', changePct);
            if (typeof setTextIfChanged === 'function') setTextIfChanged(changeCell, chDisp.text);
            else if (changeCell.textContent !== chDisp.text) changeCell.textContent = chDisp.text;
            if (changeCell.style.color !== chDisp.color) changeCell.style.color = chDisp.color;
        }
        if (isTestAcct && typeof updateTestVarlikRowLiveMetrics === 'function') {
            updateTestVarlikRowLiveMetrics(row, tbody);
        }
    });
    if (isTestAcct && typeof updateTestAccountStripFromTable === 'function') {
        updateTestAccountStripFromTable(tbody);
    }
}

function testAccountRefreshVarlikPctColumn(tbody) {
    var root = tbody || document.getElementById('varliklarTableBody');
    if (!root) return;
    var portTotal = testAccountKpiTotalUsd(root);
    if (!(portTotal > 0)) return;
    root.querySelectorAll('tr[data-asset]').forEach(function (r) {
        var priceCell = r.querySelector('.price-cell');
        var price = priceCell ? parseFloat(priceCell.getAttribute('data-price') || '') : NaN;
        if (!Number.isFinite(price) || price <= 0) {
            price = typeof getAssetPrice === 'function' ? getAssetPrice(r.getAttribute('data-asset') || '') : null;
        }
        var rowTds = r.querySelectorAll('td');
        if (!rowTds[8]) return;
        var share = testAccountVarlikRowShareUsdFromDom(r, price);
        var pctTxt = (share / portTotal * 100).toFixed(2) + '%';
        if (typeof setTextIfChanged === 'function') setTextIfChanged(rowTds[8], pctTxt);
        else rowTds[8].textContent = pctTxt;
    });
}

var _silentWalletRecoveryTimer = null;
function scheduleSilentWalletRecovery() {
    if (_silentWalletRecoveryTimer || !State.accountId) return;
    _silentWalletRecoveryTimer = setTimeout(function () {
        _silentWalletRecoveryTimer = null;
        if (!State.accountId) return;
        if (typeof isWalletDataLive === 'function' && isWalletDataLive()) return;
        if (window.homeFlash && typeof window.homeFlash.resetRefreshThrottle === 'function') {
            window.homeFlash.resetRefreshThrottle(State.accountId);
        }
        if (typeof triggerWalletRefreshForVarliklar === 'function') {
            triggerWalletRefreshForVarliklar(State.accountId, { force: false });
        } else if (window.homeFlash && typeof window.homeFlash.triggerRefresh === 'function') {
            window.homeFlash.triggerRefresh(State.accountId, false);
        }
    }, 6000);
}
window.scheduleSilentWalletRecovery = scheduleSilentWalletRecovery;

var _walletInflightPollTimer = null;
var _walletInflightPollAccountId = null;

/** Sunucuda wallet refresh inflight bitene kadar poll; «Güncelleniyor…» takılmasın. */
function pollWalletRefreshUntilDone(accountId) {
    accountId = Number(accountId);
    if (!accountId || !window.apiClient || typeof window.apiClient.get !== 'function') return;
    _walletInflightPollAccountId = accountId;
    if (_walletInflightPollTimer) return;
    var attempts = 0;
    var maxAttempts = 14;

    function scheduleNext() {
        if (attempts >= maxAttempts) {
            _walletInflightPollAccountId = null;
            if (typeof setWalletPanelUpdating === 'function') setWalletPanelUpdating(false);
            if (typeof updateKpiCuzdanLiveStatus === 'function') updateKpiCuzdanLiveStatus();
            return;
        }
        _walletInflightPollTimer = setTimeout(tick, attempts < 3 ? 1500 : 2500);
    }

    function tick() {
        _walletInflightPollTimer = null;
        if (_walletInflightPollAccountId !== accountId) return;
        attempts += 1;
        window.apiClient.get('/api/home/wallet/status?account_id=' + accountId, { timeout: 8000 })
            .then(function (res) {
                var d = res && res.data;
                if (!d) {
                    scheduleNext();
                    return;
                }
                if (window.__walletDebugMeta && d.last_snapshot_at) {
                    window.__walletDebugMeta.wallet_ts_iso = d.last_snapshot_at;
                    window.__walletDebugMeta.wallet_age_sec = d.last_snapshot_age_sec;
                    window.__walletDebugMeta.wallet_snapshot_stale = !!d.snapshot_stale;
                }
                if (d.inflight) {
                    if (typeof setWalletPanelUpdating === 'function') setWalletPanelUpdating(true);
                    scheduleNext();
                    return;
                }
                _walletInflightPollAccountId = null;
                if (typeof setWalletPanelUpdating === 'function') setWalletPanelUpdating(false);
                var errCode = d.last_error_code ? String(d.last_error_code).toUpperCase() : '';
                if (errCode) {
                    if (typeof _walletHasDisplayableAssets === 'function' && _walletHasDisplayableAssets()
                        && typeof markWalletCachedLiveFetchStale === 'function') {
                        markWalletCachedLiveFetchStale(errCode);
                    } else if (typeof markWalletLiveFetchFailed === 'function') {
                        markWalletLiveFetchFailed(errCode, { force: true });
                    }
                    return;
                }
                if (d.snapshot_stale) {
                    if (typeof _walletHasDisplayableAssets === 'function' && _walletHasDisplayableAssets()
                        && typeof markWalletCachedLiveFetchStale === 'function') {
                        markWalletCachedLiveFetchStale('WALLET_SNAPSHOT_STALE');
                    } else if (typeof markWalletLiveFetchFailed === 'function') {
                        markWalletLiveFetchFailed('WALLET_SNAPSHOT_STALE', { force: true });
                    }
                    if (window.homeFlash && typeof window.homeFlash.resetRefreshThrottle === 'function') {
                        window.homeFlash.resetRefreshThrottle(accountId);
                    }
                    if (window.homeFlash && typeof window.homeFlash.triggerRefresh === 'function') {
                        window.homeFlash.triggerRefresh(accountId, true);
                    }
                    return;
                }
                if (typeof isWalletDataLive === 'function' && isWalletDataLive()) {
                    if (typeof updateKpiCuzdanLiveStatus === 'function') updateKpiCuzdanLiveStatus();
                    return;
                }
                if (window.homeFlash && typeof window.homeFlash.resetRefreshThrottle === 'function') {
                    window.homeFlash.resetRefreshThrottle(accountId);
                }
                if (window.homeFlash && typeof window.homeFlash.triggerRefresh === 'function') {
                    window.homeFlash.triggerRefresh(accountId, false);
                }
            })
            .catch(function () {
                scheduleNext();
            });
    }

    tick();
}
window.pollWalletRefreshUntilDone = pollWalletRefreshUntilDone;

/** Cüzdan varlıkları tablosu: POST /api/home/wallet/refresh (backend TTL/inflight dedupe; homeFlash debounce atlanır). */
var _varliklarWalletRefreshInflight = false;
var _varliklarWalletRefreshLastAt = 0;
var VARLIKLAR_WALLET_REFRESH_MS = 12000;
var VARLIKLAR_WALLET_MIN_GAP_MS = 12000;
var VARLIKLAR_WALLET_REFRESH_LOCK_TTL_MS = 20000;

function _varliklarWalletRefreshLockKey(accountId) {
    return 'tt_wallet_refresh_lock:' + accountId;
}

function _isVarliklarWalletRefreshLocked(accountId) {
    try {
        var raw = localStorage.getItem(_varliklarWalletRefreshLockKey(accountId));
        if (!raw) return false;
        var ts = parseInt(raw, 10);
        return !isNaN(ts) && (Date.now() - ts) < VARLIKLAR_WALLET_REFRESH_LOCK_TTL_MS;
    } catch (e) {
        return false;
    }
}

function _setVarliklarWalletRefreshLock(accountId) {
    try { localStorage.setItem(_varliklarWalletRefreshLockKey(accountId), String(Date.now())); } catch (e) {}
}

function _clearVarliklarWalletRefreshLock(accountId) {
    try { localStorage.removeItem(_varliklarWalletRefreshLockKey(accountId)); } catch (e) {}
}

function triggerWalletRefreshForVarliklar(accountId, opts) {
    opts = opts || {};
    var force = opts.force === true;
    if (!accountId || !window.apiClient || typeof window.apiClient.post !== 'function') return Promise.resolve();
    var now = Date.now();
    if (now - _varliklarWalletRefreshLastAt < VARLIKLAR_WALLET_MIN_GAP_MS) return Promise.resolve();
    if (_isVarliklarWalletRefreshLocked(accountId)) return Promise.resolve();
    if (_varliklarWalletRefreshInflight) return Promise.resolve();
    _varliklarWalletRefreshInflight = true;
    _varliklarWalletRefreshLastAt = now;
    _setVarliklarWalletRefreshLock(accountId);
    var url = '/api/home/wallet/refresh?account_id=' + accountId + (force ? '&force=1' : '');
    return window.apiClient.post(url, null, { timeout: 25000 })
        .then(function (res) {
            _varliklarWalletRefreshLastAt = Date.now();
            if (res && res.ok && res.data && res.data.wallet_live && assetsState && assetsState.wallet) {
                var d = res.data;
                normalizeAndApplyWallet(res.data.wallet_live, {
                    source: force ? 'wallet_refresh_varliklar_force' : 'wallet_refresh_varliklar',
                    skipped: !!d.skipped,
                    stale: !!d.stale,
                    stale_code: d.last_error_code || d.error_code || null
                });
            }
            if (res && res.data && res.data.stale && res.data.last_error_code && typeof markWalletCachedLiveFetchStale === 'function') {
                markWalletCachedLiveFetchStale(res.data.last_error_code);
            }
            if (res && res.data && res.data.stale && !res.data.last_error_code && typeof markWalletCachedLiveFetchStale === 'function') {
                markWalletCachedLiveFetchStale('WALLET_SNAPSHOT_STALE');
            }
            if (res && res.data && res.data.inflight && typeof pollWalletRefreshUntilDone === 'function') {
                pollWalletRefreshUntilDone(accountId);
            }
            if (typeof setWalletPanelUpdating === 'function') setWalletPanelUpdating(false);
            if (window.__walletDebugMeta) {
                window.__walletDebugMeta.last_refresh_at = (res && res.data && res.data.wallet_live_at) ? res.data.wallet_live_at : new Date().toISOString();
                if (res && res.data && res.data.wallet_live_at) {
                    window.__walletDebugMeta.wallet_ts_iso = res.data.wallet_live_at;
                }
            }
        })
        .catch(function (err) {
            var code = (err && (err.error_code || err.code)) || 'WALLET_REFRESH_FAILED';
            if (typeof _walletHasDisplayableAssets === 'function' && _walletHasDisplayableAssets()
                && typeof markWalletCachedLiveFetchStale === 'function') {
                markWalletCachedLiveFetchStale(code);
            } else if (typeof markWalletLiveFetchFailed === 'function') {
                markWalletLiveFetchFailed(code, { force: true });
            }
            if (force && typeof scheduleWalletConnectivityRetry === 'function') {
                scheduleWalletConnectivityRetry(accountId);
            }
        })
        .finally(function () {
            _varliklarWalletRefreshInflight = false;
            _clearVarliklarWalletRefreshLock(accountId);
        });
}
window.triggerWalletRefreshForVarliklar = triggerWalletRefreshForVarliklar;

var _walletConnectivityRetryTimer = null;
function scheduleWalletConnectivityRetry(accountId) {
    if (!accountId || _walletConnectivityRetryTimer) return;
    _walletConnectivityRetryTimer = setTimeout(function () {
        _walletConnectivityRetryTimer = null;
        if (!State.accountId || Number(State.accountId) !== Number(accountId)) return;
        if (typeof navigator !== 'undefined' && navigator.onLine === false) return;
        if (typeof shouldRecoverWalletAfterConnectivity === 'function' && !shouldRecoverWalletAfterConnectivity()) return;
        if (typeof triggerWalletRefreshForVarliklar === 'function') {
            triggerWalletRefreshForVarliklar(accountId, { force: true });
        }
    }, 2500);
}
window.scheduleWalletConnectivityRetry = scheduleWalletConnectivityRetry;

/** Bot silme / spot trade sonrası cüzdan tablosunu kademeli yenile (Binance settlement gecikmesi). */
function scheduleWalletRefreshAfterTrade(accountId, opts) {
    opts = opts || {};
    if (!accountId) return;
    var delays = Array.isArray(opts.delays) ? opts.delays : [0, 700, 2000, 5000];
    delays.forEach(function (ms) {
        setTimeout(function () {
            if (Number(window.__ACTIVE_ACCOUNT_ID || State.accountId) !== Number(accountId)) return;
            if (typeof triggerWalletRefreshForVarliklar === 'function') {
                triggerWalletRefreshForVarliklar(accountId, { force: true });
            } else if (window.homeFlash && typeof window.homeFlash.triggerRefresh === 'function') {
                window.homeFlash.triggerRefresh(accountId, true);
            } else if (typeof pollWallet === 'function') {
                pollWallet(true);
            }
            if (typeof fetchSnapshot === 'function') fetchSnapshot();
            if (typeof loadBotsListFast === 'function') loadBotsListFast(accountId);
        }, ms);
    });
}
window.scheduleWalletRefreshAfterTrade = scheduleWalletRefreshAfterTrade;

function consumePendingWalletRefreshAfterBot(accountId) {
    if (!accountId) return;
    try {
        var raw = sessionStorage.getItem('tt_wallet_refresh_after_bot')
            || localStorage.getItem('tt_wallet_refresh_after_bot_v1');
        if (!raw) return;
        var pending = _parseWalletRefreshAfterBotPayload(raw);
        sessionStorage.removeItem('tt_wallet_refresh_after_bot');
        localStorage.removeItem('tt_wallet_refresh_after_bot_v1');
        if (!pending || Number(pending.accountId) !== Number(accountId)) return;
        _applyWalletRefreshAfterBotPayload(pending);
    } catch (e) { /* ignore */ }
}
window.consumePendingWalletRefreshAfterBot = consumePendingWalletRefreshAfterBot;

/** Anasayfa açıkken periyodik cüzdan yenileme (backend TTL ile hafif; sekme gizliyken çalışmaz) */
function startVarliklarPeriodicRefresh() {
    window.intervalRegistry.stopByOwner('tab.varliklar.wallet_refresh');
    if (!State.accountId) return;
    function doRefresh() {
        if (document.hidden) return;
        var activeTab = document.querySelector('.dm-tab.is-active');
        if (!activeTab || activeTab.getAttribute('data-tab') !== 'binance') return;
        triggerWalletRefreshForVarliklar(State.accountId, { force: false });
    }
    window.intervalRegistry.start('tab.varliklar.wallet_refresh', doRefresh, VARLIKLAR_WALLET_REFRESH_MS, 'tab.varliklar.wallet_refresh');
}

function initVarliklarTab() {
    window.intervalRegistry.stopByOwner('tab.varliklar');
    if (!State.accountId) {
        const tbody = document.getElementById("varliklarTableBody");
        if (tbody) tbody.innerHTML = '<tr><td colspan="10" style="padding: 2rem; text-align: center; color: var(--ds-text-secondary);">Hesap seçin.</td></tr>';
        return;
    }
    // pollWallet startBinanceTabPolling tarafından tek seferde çağrılıyor; burada çağırma (429 önlemek için)
    renderVarliklarList();
    if (typeof refreshVarliklarWalletMarketData === 'function') refreshVarliklarWalletMarketData(true);
}

// --- Coin Listesi (Binance sekmesi): sabit liste + arama ile tüm çiftler ---
// Logolar: Harici CDN 429 verdiği için sadece baş harfler (initials) kullanılıyor.
function coinListLogoInitials(symbol, quote) {
    quote = quote || 'USDT';
    const s = (symbol || '').toUpperCase();
    const base = quote === 'ALL' ? s : (s.endsWith(quote) ? s.slice(0, -quote.length) : s);
    return (base || '—').substring(0, 2).toUpperCase();
}
function coinListBaseName(symbol, quote) {
    quote = quote || 'USDT';
    const s = (symbol || '').toUpperCase();
    const base = quote === 'ALL' ? s : (s.endsWith(quote) ? s.slice(0, -quote.length) : s);
    return assetNameMap[base] || base;
}

function renderBinanceCoinList() {
    var tbody = document.getElementById('binanceCoinListBody');
    var paginationInfo = document.getElementById('coinListPaginationInfo');
    var loadMoreBtn = document.getElementById('coinListLoadMore');
    if (!tbody) return;
    if (binanceCoinListLoadFailed) {
        tbody.innerHTML = '<tr><td colspan="7" class="coin-list-loading-row">Yüklenemedi</td></tr>';
        if (paginationInfo) paginationInfo.style.display = 'none';
        if (loadMoreBtn) loadMoreBtn.style.display = 'none';
        return;
    }
    var finalSymbols = spotFavorites.slice();
    var total = finalSymbols.length;

    if (total === 0) {
        tbody.innerHTML = '<tr><td colspan="7" style="padding: 2.5rem 2rem; text-align: center; color: var(--ds-text-secondary);">Favori yok. Arama çubuğunda çift arayın (örn. BTCETH, ETHSOL), seçip modalda yıldıza tıklayarak favorilere ekleyin.</td></tr>';
        if (paginationInfo) paginationInfo.style.display = 'none';
        if (loadMoreBtn) loadMoreBtn.style.display = 'none';
        return;
    }

    var start = (coinListPage - 1) * COIN_LIST_PAGE_SIZE;
    var pageSymbols = finalSymbols.slice(start, start + COIN_LIST_PAGE_SIZE);

    var list = pageSymbols.map(function (symbol) {
        var mini = window.marketStore && window.marketStore.getMini(symbol);
        var price = (mini && mini.last != null) ? mini.last : (window.marketStore && window.marketStore.getPrice ? window.marketStore.getPrice(symbol) : null);
        var changePct = mini && Number.isFinite(mini.changePct) ? mini.changePct : null;
        var quoteVolume = (mini && mini.quoteVolume != null) ? mini.quoteVolume : null;
        return { symbol: symbol, price: price, changePct: changePct, quoteVolume: quoteVolume, mini: mini };
    });

    var baseFromSymbolForLogo = function (sym) {
        var q = ['USDT', 'FDUSD', 'BUSD', 'BTC', 'ETH', 'BNB', 'TRY'];
        for (var i = 0; i < q.length; i++) {
            if (sym.endsWith(q[i])) return sym.slice(0, -q[i].length) || sym;
        }
        return sym.substring(0, 4) || sym;
    };
    tbody.innerHTML = list.map(function (item) {
        var symbol = item.symbol;
        var price = item.price;
        var changePct = item.changePct;
        var quoteVolume = item.quoteVolume;
        var isFav = isSpotFavorite(symbol);
        var priceDisplay = price != null && Number.isFinite(price) ? fmtCoinPrice(price) : '\u2026';
        var changeStr = changePct != null ? (changePct >= 0 ? '+' : '') + changePct.toFixed(2) + '%' : '\u2014';
        var changeColor = changePct != null ? (changePct >= 0 ? '#0ecb81' : '#f6465d') : 'var(--ds-text-secondary)';
        var volStr = quoteVolume != null && Number.isFinite(quoteVolume) ? (quoteVolume >= 1e6 ? (quoteVolume / 1e6).toFixed(2) + 'M' : quoteVolume >= 1e3 ? (quoteVolume / 1e3).toFixed(2) + 'K' : quoteVolume.toFixed(0)) : '\u2014';
        var base = baseFromSymbolForLogo(symbol);
        var initials = (base || ' ').substring(0, 2).toUpperCase();
        var logoUrl = (typeof getCoinLogoUrl === 'function' && getCoinLogoUrl(base)) || null;
        var starClass = 'fav-star' + (isFav ? ' is-favorite' : '');
        var starChar = isFav ? '\u2605' : '\u2606';
        return '<tr data-coin-symbol="' + symbol + '">' +
            '<td class="coin-list-card-star" style="padding: 0.25rem; vertical-align: middle; text-align: center;">' +
            '<button type="button" class="' + starClass + '" data-fav-symbol="' + symbol + '" title="' + (isFav ? 'Favorilerden \u00e7\u0131kar' : 'Favorilere ekle') + '" aria-label="Favori">' + starChar + '</button>' +
            '</td>' +
            '<td class="varlik-logo-cell coin-list-card-logo" style="padding: 0.5rem 0.75rem; vertical-align: middle;">' +
            '<div class="varlik-logo" title="' + base + '">' +
            (logoUrl ? '<img src="' + logoUrl + '" alt="' + base + '" loading="lazy" onerror="if(window.registerLogo404)window.registerLogo404(this.alt);this.style.display=\'none\';this.nextElementSibling.style.display=\'flex\';" /><span class="varlik-logo-initials" style="display:none">' + initials + '</span>' : '<span class="varlik-logo-initials">' + initials + '</span>') +
            '</div></td>' +
            '<td class="coin-list-card-symbol" style="padding: 0.75rem; vertical-align: middle;"><div class="varlik-symbol">' + symbol + '</div></td>' +
            '<td data-label="Canlı fiyat" style="padding: 0.75rem; text-align: right; vertical-align: middle;"><div class="coin-list-price-cell price-cell" data-price="' + (price != null ? price : '') + '">' + priceDisplay + '</div></td>' +
            '<td data-label="24s değişim %" style="padding: 0.75rem; text-align: right; vertical-align: middle;"><div class="coin-list-change-cell change-pct" style="color: ' + changeColor + '">' + changeStr + '</div></td>' +
            '<td data-label="24s hacim" style="padding: 0.75rem; text-align: right; vertical-align: middle;"><div class="coin-list-volume-cell" data-volume="' + (quoteVolume != null ? quoteVolume : '') + '">$' + volStr + '</div></td>' +
            '<td class="coin-list-card-actions" style="padding: 0.75rem; text-align: center; vertical-align: middle;"><div class="btn-al-sat-wrap">' +
            '<button type="button" class="btn-al" onclick="event.stopPropagation(); openSpotTradeModal(\'' + symbol + '\', \'BUY\')" title="Alış">Alış</button> ' +
            '<button type="button" class="btn-sat" onclick="event.stopPropagation(); openSpotTradeModal(\'' + symbol + '\', \'SELL\')" title="Satış">Satış</button>' +
            '</div></td></tr>';
    }).join('');

    if (total > COIN_LIST_PAGE_SIZE) {
        if (paginationInfo) {
            paginationInfo.style.display = 'inline';
            paginationInfo.textContent = (start + 1) + '\u2013' + Math.min(start + pageSymbols.length, total) + ' / ' + total;
        }
        if (loadMoreBtn) loadMoreBtn.style.display = start + COIN_LIST_PAGE_SIZE < total ? 'inline-block' : 'none';
    } else {
        if (paginationInfo) paginationInfo.style.display = 'none';
        if (loadMoreBtn) loadMoreBtn.style.display = 'none';
    }
}

function tickBinanceCoinListPrices() {
    const tab = document.getElementById('tabBinance');
    if (!tab?.classList.contains('is-active')) return;
    const tbody = document.getElementById('binanceCoinListBody');
    if (!tbody) return;
    const rows = tbody.querySelectorAll('tr[data-coin-symbol]');
    rows.forEach(row => {
        const symbol = row.getAttribute('data-coin-symbol');
        const priceCell = row.querySelector('.coin-list-price-cell');
        const changeCell = row.querySelector('.coin-list-change-cell');
        if (!priceCell || !changeCell) return;
        const mini = window.marketStore?.getMini(symbol);
        const price = (mini && mini.last != null) ? mini.last : (window.marketStore?.getPrice(symbol) ?? null);
        const changePct = mini && Number.isFinite(mini.changePct) ? mini.changePct : null;
        if (price != null && Number.isFinite(price)) {
            const oldPrice = parseFloat(priceCell.getAttribute('data-price') || '') || 0;
            priceCell.setAttribute('data-price', price);
            priceCell.textContent = fmtCoinPrice(price);
            if (Number.isFinite(oldPrice) && Math.abs(oldPrice - price) > 0.0001) {
                priceCell.classList.remove('price-up', 'price-down', 'price-neutral');
                priceCell.classList.add(price > oldPrice ? 'price-up' : 'price-down');
                setTimeout(() => { priceCell.classList.remove('price-up', 'price-down'); priceCell.classList.add('price-neutral'); }, 600);
            }
        }
        if (changePct != null) {
            changeCell.textContent = (changePct >= 0 ? '+' : '') + changePct.toFixed(2) + '%';
            changeCell.style.color = changePct >= 0 ? '#0ecb81' : '#f6465d';
        }
        const volumeCell = row.querySelector('.coin-list-volume-cell');
        if (volumeCell && mini && mini.quoteVolume != null) {
            const qv = mini.quoteVolume;
            const volStr = qv >= 1e6 ? (qv / 1e6).toFixed(2) + 'M' : qv >= 1e3 ? (qv / 1e3).toFixed(2) + 'K' : qv.toFixed(0);
            volumeCell.textContent = '$' + volStr;
            volumeCell.setAttribute('data-volume', qv);
        }
    });
}

let coinListSearchAllSymbols = [];
/** Tüm Binance işlem çiftleri – /api/data/coin-list symbols (scope=usdt veya scope=all) */
let coinListAllBinanceSymbols = [];
/** Quote filtresi: USDT (öne çıkan 10) veya ALL|BTC|ETH|FDUSD|BNB|TRY (tümü, sayfalı) */
let coinListQuoteFilter = 'USDT';
let coinListPage = 1;
const COIN_LIST_PAGE_SIZE = 50;
/** scope=all ile yüklenen tüm semboller (pagination için) */
let coinListAllScopeSymbols = [];

async function ensureCoinListSearchSymbolsLoaded(scope) {
    scope = scope || 'usdt';
    const wantAll = (scope || '').toLowerCase() === 'all';
    if (wantAll && coinListAllScopeSymbols.length > 0) return;
    if (!wantAll && coinListAllBinanceSymbols.length > 0) return;
    try {
        const data = await window.apiClient.get('/api/data/coin-list?scope=' + (wantAll ? 'all' : 'usdt'));
        const syms = (data.symbols || []).map(s => (s || '').toUpperCase()).filter(Boolean).sort((a, b) => a.localeCompare(b));
        if (syms.length > 0) {
            if (wantAll) {
                coinListAllScopeSymbols = syms;
                coinListAllBinanceSymbols = syms;
            } else {
                coinListAllBinanceSymbols = syms;
            }
        } else if (wantAll && coinListAllBinanceSymbols.length > 0) {
            coinListAllScopeSymbols = coinListAllBinanceSymbols.slice();
        }
        buildCoinListSearchSymbols();
    } catch (e) {
        console.warn('[dashboard] ensureCoinListSearchSymbols scope=', scope, e);
    }
}

function buildCoinListSearchSymbols() {
    const allSymbols = coinListAllScopeSymbols.length > 0
        ? coinListAllScopeSymbols
        : coinListAllBinanceSymbols.length > 0
            ? coinListAllBinanceSymbols
            : (window.marketStore?.getAllMini?.() || [])
                .map(m => (m.symbol || '').toUpperCase())
                .filter(Boolean);
    coinListSearchAllSymbols = allSymbols.map(symbol => {
        const mini = window.marketStore?.getMini?.(symbol);
        return { symbol, last: mini?.last, changePct: mini?.changePct };
    }).sort((a, b) => {
        const qA = coinListSearchQuoteOrder(a.symbol);
        const qB = coinListSearchQuoteOrder(b.symbol);
        if (qA !== qB) return qA - qB;
        return (a.symbol || '').localeCompare(b.symbol || '');
    });
    rebuildBinanceTradingSymbolSet();
}

function showCoinListSearchDropdown(query) {
    const dropdown = document.getElementById('coinListSearchDropdown');
    if (!dropdown) return;
    const qn = normalizeSymbolSearchQuery(query);
    const needle = qn.primary || qn.compact || '';
    if (!needle) {
        dropdown.style.display = 'none';
        return;
    }
    const list = filterCoinListForSearch(query, 50);
    if (list.length === 0) {
        dropdown.innerHTML = '<div style="padding: 1rem; color: var(--ds-text-secondary);">Sonuç bulunamadı.</div>';
        dropdown.style.display = 'block';
        return;
    }
    dropdown.innerHTML = list.map(function (item) {
        return renderCoinSearchDropdownItemHtml(item, '');
    }).join('');
    dropdown.style.display = 'block';
    queueCoinSearchPriceFetch(list.map(function (it) { return it.symbol; }), function () {
        var inp = document.getElementById('coinListSearchInput');
        if (inp && (inp.value || '').trim() && typeof showCoinListSearchDropdown === 'function') {
            showCoinListSearchDropdown(inp.value);
        }
    });
}
function hideCoinListSearchDropdown() {
    const dropdown = document.getElementById('coinListSearchDropdown');
    if (dropdown) { dropdown.style.display = 'none'; }
}
function initBinanceCoinListSearch() {
    const input = document.getElementById('coinListSearchInput');
    const dropdown = document.getElementById('coinListSearchDropdown');
    if (!input || !dropdown) return;
    ensureCoinListSearchSymbolsLoaded('all').then(() => buildCoinListSearchSymbols());
    input.onfocus = () => {
        ensureCoinListSearchSymbolsLoaded('all').then(() => {
            buildCoinListSearchSymbols();
            showCoinListSearchDropdown(input.value);
        });
    };
    input.oninput = () => showCoinListSearchDropdown(input.value);
    input.onblur = () => setTimeout(hideCoinListSearchDropdown, 180);
    dropdown.onmousedown = (e) => e.preventDefault();
    dropdown.addEventListener('click', (e) => {
        const item = e.target.closest('.coin-list-search-item');
        if (!item) return;
        const symbol = item.getAttribute('data-symbol');
        if (symbol && typeof openSpotTradeModal === 'function') {
            openSpotTradeModal(symbol);
            input.value = '';
            hideCoinListSearchDropdown();
        }
    });
}

var coinListFavDelegationBound = false;
var binanceCoinListLoadFailed = false;

function initBinanceCoinList() {
    window.intervalRegistry.stopByOwner('tab.coinlist');
    binanceCoinListLoadFailed = false;
    if (spotFavorites.length === 0 && getFavoritesStorageKey()) {
        loadSpotFavoritesFromStorage()
            .then(function () { if (typeof renderBinanceCoinList === 'function') renderBinanceCoinList(); })
            .catch(function () {
                binanceCoinListLoadFailed = true;
                if (typeof renderBinanceCoinList === 'function') renderBinanceCoinList();
            });
    }
    ensureCoinListSearchSymbolsLoaded('all');
    var loadMoreBtn = document.getElementById('coinListLoadMore');
    var tbody = document.getElementById('binanceCoinListBody');
    coinListPage = 1;
    if (loadMoreBtn) {
        loadMoreBtn.onclick = function () {
            coinListPage++;
            renderBinanceCoinList();
        };
    }
    if (tbody && !coinListFavDelegationBound) {
        coinListFavDelegationBound = true;
        tbody.addEventListener('click', function (e) {
            var star = e.target && e.target.closest ? e.target.closest('[data-fav-symbol]') : null;
            if (!star) return;
            e.preventDefault();
            e.stopPropagation();
            var sym = star.getAttribute('data-fav-symbol');
            if (!sym) return;
            var p = toggleSpotFavorite(sym);
            if (typeof renderBinanceCoinList === 'function') renderBinanceCoinList();
            if (typeof renderMobileTradeFavorites === 'function') renderMobileTradeFavorites();
            if (spotTradeState.symbol && normalizePairSymbol(spotTradeState.symbol) === normalizePairSymbol(sym) && typeof syncFavoriteButtonUI === 'function') syncFavoriteButtonUI();
            if (p && p.catch) p.catch(function () {
                if (typeof renderBinanceCoinList === 'function') renderBinanceCoinList();
                if (typeof renderMobileTradeFavorites === 'function') renderMobileTradeFavorites();
                if (spotTradeState.symbol && typeof syncFavoriteButtonUI === 'function') syncFavoriteButtonUI();
            });
        });
    }
    renderBinanceCoinList();
    initBinanceCoinListSearch();
    window.intervalRegistry.start('tab.coinlist.tick', function () { tickBinanceCoinListPrices(); }, 2000, 'tab.coinlist');
}

function updateBinancePricesTick() {
    var tab = document.getElementById("tabBinance");
    if (!tab || !tab.classList.contains("is-active")) return;
    if (typeof tickVarliklarPrices === 'function') tickVarliklarPrices({ skipThrottle: true });
    if (typeof tickBinanceCoinListPrices === 'function') tickBinanceCoinListPrices();
    if (window.BinanceUI) return;
    if (window.BinanceAssetsPanel && typeof BinanceAssetsPanel.tickPrices === 'function') {
        BinanceAssetsPanel.tickPrices();
    }
}

/** Tab kapanınca unsubscribe – memory leak yok */
function onBinanceTabDeactivated() {
    if (binanceUnsubscribePrices) {
        binanceUnsubscribePrices();
        binanceUnsubscribePrices = null;
        if (window.__DEBUG_BINANCE__) console.log("[BINANCE] Unsubscribed from marketStore");
    }
}

const ORDERS_POLL_MS = 10000; // 10sn
const FINANCE_TRADES_POLL_MS = 15000; // 15sn; İşlemler listesi yeni işlemler hemen yansısın

function startBinanceTabPolling() {
    if (!window.intervalRegistry) return;
    if (window.BinanceUI && document.getElementById("tabBinance")?.classList.contains("is-active")) {
        if (window.__DEBUG_BINANCE__) console.log("[BINANCE] startBinanceTabPolling: Skipped (BinanceUI active)");
        return;
    }
    // Idempotent: zaten binanceTab polling aktifse tekrar başlatma (duplicate spam önlemi)
    var active = window.intervalRegistry.getActive ? window.intervalRegistry.getActive() : [];
    if (Array.isArray(active) && active.some(function (x) { return x.owner === 'binanceTab' && (x.key === 'wallet:poll' || x.key === 'orders:poll' || x.key === 'finance.trades:poll'); })) {
        if (window.__DEBUG_BINANCE__) console.log("[BINANCE] startBinanceTabPolling: Already running, skip");
        return;
    }
    if (window.__DEBUG_BINANCE__) console.log("[BINANCE] startBinanceTabPolling: Initializing Binance tab");
    window.intervalRegistry.stopByOwner('binanceTab');
    if (window.intervalRegistry.timeout && window.intervalRegistry.timeout.cancelByOwner) {
        window.intervalRegistry.timeout.cancelByOwner('binanceTab');
    }
    onBinanceTabDeactivated();
    
    const store = window.marketStore;
    if (!store || typeof store.subscribe !== 'function') {
        console.warn("[BINANCE] marketStore.subscribe not available, using interval-only updates");
    } else {
        binanceUnsubscribePrices = store.subscribe(() => {
            const tab = document.getElementById("tabBinance");
            if (!tab?.classList.contains("is-active")) return;
            if (window.__DEBUG_BINANCE__) {
                const n = (store.prices && typeof store.prices.size === 'number') ? store.prices.size : 0;
                console.log("[BINANCE][STORE UPDATE] prices_count:", n);
            }
            if (typeof tickVarliklarPrices === 'function') tickVarliklarPrices({ skipThrottle: true });
            if (typeof tickBinanceCoinListPrices === 'function') tickBinanceCoinListPrices();
            if (!window.BinanceUI && window.BinanceAssetsPanel && typeof BinanceAssetsPanel.tickPrices === 'function') {
                BinanceAssetsPanel.tickPrices();
            }
        });
        if (window.__DEBUG_BINANCE__) console.log("[BINANCE] Subscribed to marketStore");
    }
    
    var priceTickMs = isMobileView() ? 1500 : 500;
    window.intervalRegistry.stop('wallet:poll');
    window.intervalRegistry.stop('orders:poll');
    // wallet from dashboard_snapshot; no wallet:poll
    window.intervalRegistry.start('orders:poll', function () { loadActiveOrders(); }, ORDERS_POLL_MS, 'binanceTab');
    window.intervalRegistry.start('tab.binance.prices', updateBinancePricesTick, priceTickMs, 'binanceTab');
    window.intervalRegistry.start('finance.trades:poll', function () {
        if (!document.getElementById('tabBinance')?.classList.contains('is-active') || !State.accountId) return;
        if (typeof loadFinanceTrades === 'function') loadFinanceTrades(false);
    }, FINANCE_TRADES_POLL_MS, 'binanceTab');

    updateBinancePricesTick();
    window.intervalRegistry.start('tab.binance.walletMarket', function () {
        if (!document.getElementById('tabBinance')?.classList.contains('is-active')) return;
        if (typeof refreshVarliklarWalletMarketData === 'function') refreshVarliklarWalletMarketData(false);
    }, VARLIKLAR_WALLET_MARKET_FETCH_MS, 'binanceTab');
    // wallet from dashboard_snapshot (no pollWallet)
    // open-orders ilk yükleme: 1.5 sn sonra (429 önlemek)
    setTimeout(function () {
        if (typeof loadActiveOrders === 'function') loadActiveOrders();
        setTimeout(function () {
            if (activeOrders && activeOrders.length > 0) {
                showActiveOrdersPanel();
                startActiveOrdersTracking();
            }
        }, 300);
    }, 1500);
    loadCoinList(false).then(() => setTimeout(() => startCoinListUpdates(), 200));
}

// Binance tab bindings
function bindBinanceTab() {
    const refreshBtn = document.getElementById("bnRefreshWallet");
    if (refreshBtn) {
        refreshBtn.onclick = () => {
            if (State.accountId && window.FLASH_HOME_ENABLED && window.homeFlash && typeof window.homeFlash.triggerRefresh === 'function') {
                window.homeFlash.triggerRefresh(State.accountId, true);
            } else if (State.accountId && window.BinanceUI && typeof window.BinanceUI.refresh === 'function') {
                window.BinanceUI.refresh({ accountId: State.accountId });
            } else if (State.accountId && window.BinanceAssetsPanel) {
                BinanceAssetsPanel.refresh();
            }
        };
    }
    const filterInput = document.getElementById("bnAssetsFilter");
    if (filterInput) {
        filterInput.addEventListener("input", () => {
            assetsState.ui.filterText = filterInput.value || '';
            if (lastWalletHash && typeof renderVarliklarList === 'function') renderVarliklarList();
        });
    }
    const hideSmallCheck = document.getElementById("bnAssetsHideSmall");
    if (hideSmallCheck) {
        hideSmallCheck.addEventListener("change", () => {
            assetsState.ui.hideSmall = !!hideSmallCheck.checked;
            if (lastWalletHash && typeof renderVarliklarList === 'function') renderVarliklarList();
        });
    }
    
    // Spot trade modal bindings
    bindSpotTradeModal();
    
    // Active orders panel close
    const closeActiveOrders = document.getElementById("bnCloseActiveOrders");
    if (closeActiveOrders) {
        closeActiveOrders.onclick = () => {
            hideActiveOrdersPanel();
            stopActiveOrdersTracking();
        };
    }
}

// Spot Trading Modal State
async function initDashboard() {
    if (window.__APP_PAGE__ !== 'dashboard') return;
    if (window.__dashboardInited) return;
    window.__dashboardInited = true;
    if (typeof window.__DEBUG_DASH__ !== 'undefined' && window.__DEBUG_DASH__) console.log("[dashboard] initDashboard: START");
    
    initParametrelerModalHandlers();

    var tok = localStorage.getItem('token');
    var usr = localStorage.getItem('user');
    if (!tok || !usr) {
        try { localStorage.removeItem('last_route'); } catch (e) {}
        window.location.replace('/ui/login.html');
        return;
    }
    
    // Çıkış handler'ı hemen tanımla – buton tıklanınca confirm mutlaka çalışsın
    window.handleSecureLogout = async function handleSecureLogout() {
        if (!confirm("Çıkış yapmak istiyor musunuz?")) return;
        var accountId = State.accountId;
        var user = null;
        try {
            var u = localStorage.getItem('user');
            if (u) user = JSON.parse(u);
        } catch (e) {}
        var fromAdmin = new URLSearchParams(window.location.search).get('from_admin') === '1';
        var isAdminViewingUser = fromAdmin && user && user.is_admin;
        if (isAdminViewingUser) {
            if (window.intervalRegistry) {
                window.intervalRegistry.stopByOwner('dashboard');
                window.intervalRegistry.stopByOwner('dashboard.summary');
                window.intervalRegistry.stop('auth.health');
                window.intervalRegistry.stop('dashboard.auth-ping');
                window.intervalRegistry.stopByOwner('binanceTab');
            }
            if (window.modalPriceInterval) clearInterval(window.modalPriceInterval);
            if (typeof stopBalanceUpdates === 'function') stopBalanceUpdates();
            if (typeof stopActiveOrdersTracking === 'function') stopActiveOrdersTracking();
            try { localStorage.removeItem('last_route'); } catch (e) {}
            window.location.replace('/ui/admin.html');
            return;
        }
        var isOwner = user && !user.is_admin && user.account_id != null && Number(user.account_id) === Number(accountId);
        if (accountId && isOwner) {
            try {
                if (window.apiClient && typeof window.apiClient.post === 'function') {
                    await window.apiClient.post('/api/auth/logout', { account_id: accountId }, { timeout: 8000 });
                }
            } catch (e) {}
        }
        localStorage.removeItem('user');
        localStorage.removeItem('token');
        try { localStorage.removeItem('boot_id'); } catch (e) {}
        try { localStorage.removeItem('last_route'); } catch (e) {}
        if (window.intervalRegistry) {
            window.intervalRegistry.stopByOwner('dashboard');
            window.intervalRegistry.stopByOwner('dashboard.summary');
            window.intervalRegistry.stop('auth.health');
            window.intervalRegistry.stop('dashboard.auth-ping');
            window.intervalRegistry.stopByOwner('binanceTab');
        }
        if (window.modalPriceInterval) clearInterval(window.modalPriceInterval);
        if (typeof stopBalanceUpdates === 'function') stopBalanceUpdates();
        if (typeof stopActiveOrdersTracking === 'function') stopActiveOrdersTracking();
        window.location.replace('/ui/login.html?logout=1');
    };
    
    // Boot_id: diagnostic sync only. If server boot_id changed, update local and run whoami; only logout on 401.
    var _authSanityCheckPromise = null;
    async function authSanityCheckAfterBootChange() {
        if (_authSanityCheckPromise) return _authSanityCheckPromise;
        _authSanityCheckPromise = (async function () {
            try {
                var headers = { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' };
                try {
                    var tok = sessionStorage.getItem('token') || localStorage.getItem('token');
                    if (tok) headers.Authorization = 'Bearer ' + tok;
                } catch (eTok) {}
                var who = await fetch(window.location.origin + '/api/auth/whoami', { method: 'GET', credentials: 'include', cache: 'no-store', headers: headers });
                if (who.ok) return true;
                if (who.status !== 401) return true;
                var body = {};
                try { body = await who.json(); } catch (_) {}
                var detail = (body && body.detail && typeof body.detail === 'object') ? body.detail : {};
                var errCode = detail.error_code || body.error_code || 'UNAUTHORIZED';
                // Only SESSION_NOT_FOUND = session invalid. UNAUTHORIZED on whoami can mean cookie not sent; still treat as expired for this explicit auth check.
                if (errCode === 'SESSION_NOT_FOUND') {
                    if (typeof window.apiClient !== 'undefined' && window.apiClient.redirectToLoginOnce) {
                        window.apiClient.redirectToLoginOnce(true);
                    } else {
                        try { sessionStorage.removeItem('user'); sessionStorage.removeItem('token'); localStorage.removeItem('user'); localStorage.removeItem('token'); localStorage.removeItem('boot_id'); localStorage.removeItem('last_route'); } catch (e) {}
                        window.location.replace('/ui/login.html?session_expired=1');
                    }
                    return false;
                }
                if (errCode === 'UNAUTHORIZED') {
                    // Token was not sent to whoami; do not clear session (might be cookie race). Next request with token may still work.
                    return true;
                }
                if (typeof window.apiClient !== 'undefined' && window.apiClient.redirectToLoginOnce) window.apiClient.redirectToLoginOnce(true);
                return false;
            } catch (e) {
                return true;
            } finally {
                _authSanityCheckPromise = null;
            }
        })();
        return _authSanityCheckPromise;
    }
    try {
        var r = await fetch('/api/boot-id', { cache: 'no-store' });
        if (!r.ok) {
            if (r.status === 502 || r.status === 503 || r.status === 504) {
                document.documentElement.style.visibility = '';
                if (typeof window.showMaintenanceOverlay === 'function') window.showMaintenanceOverlay('server_down', r.status);
                return;
            }
            document.documentElement.style.visibility = '';
            if (typeof window.showMaintenanceOverlay === 'function') window.showMaintenanceOverlay('server_down', r.status);
            return;
        }
        var b = await r.json();
        var serverBootId = b && b.boot_id ? String(b.boot_id) : '';
        var localBootId = (function () { try { return localStorage.getItem('boot_id') || ''; } catch (e) { return ''; } })();
        if (serverBootId && localBootId && serverBootId !== localBootId) {
            try { localStorage.setItem('boot_id', serverBootId); } catch (e) {}
            // Toast kaldırıldı: çoklu worker'da her yenilemede farklı boot_id gelir, kullanıcıya "güncellendi" mesajı göstermiyoruz
            var ok = await authSanityCheckAfterBootChange();
            if (!ok) return;
        } else if (!localBootId && serverBootId) {
            try { localStorage.setItem('boot_id', serverBootId); } catch (e) {}
        }
    } catch (e) {
        document.documentElement.style.visibility = '';
        if (typeof window.showMaintenanceOverlay === 'function') window.showMaintenanceOverlay('network_error', 0);
        return;
    }
    document.documentElement.style.visibility = '';
    
    checkFullscreenBlockers();
    
    // Check if user is admin
    const userStr = localStorage.getItem('user');
    let user = null;
    if (userStr) {
        try {
            user = JSON.parse(userStr);
        } catch (e) {}
    }
    
    // Appbar: hesap sahibi adı (sol) – sadece summary/snapshot ile güncellenir (hesap sahibi adı); session user (örn. Admin) yazılmaz
    const adminLink = document.getElementById('adminLink');
    
    // Check first login
    const urlParams = new URLSearchParams(window.location.search);
    const isFirstLogin = urlParams.get('first_login') === 'true' || (user && user.is_first_login);
    
    // Admin sekmesi + Admin'e dön: sadece admin kullanıcı VE admin panelinden hesaba girildiyse (from_admin=1)
    const showAdminNav = shouldShowAdminNav(user);
    patchAdminLinkVisibility(showAdminNav);
    if (adminLink) {
        adminLink.addEventListener('click', function () {
            try { sessionStorage.removeItem('dashboard_from_admin'); } catch (e) {}
        }, { once: true });
    }
    
    // Check must_change_password (zorunlu şifre değiştirme)
    const mustChangePassword = user && user.must_change_password === true;
    
    // Restore active tab immediately (before any async work) – yenilemede bulunduğun sekme kalsın. İlk girişte her zaman Anasayfa (binance).
    let savedTab = isFirstLogin ? 'binance' : (urlParams.get('tab') || localStorage.getItem('dashboard_active_tab') || 'binance');
    var allowedTabs = ['binance', 'bots', 'finance', 'trade', 'contact', 'settings'];
    if (allowedTabs.indexOf(savedTab) === -1) savedTab = 'binance';
    if (savedTab === 'reports' || savedTab === 'varliklar') savedTab = 'binance'; // eski isimler
    if (isFirstLogin) try { localStorage.setItem('dashboard_active_tab', 'binance'); } catch (_) {}
    const savedTabButton = document.querySelector(`[data-tab="${savedTab}"]`);
    if (savedTabButton) {
        document.querySelectorAll('.dm-tab').forEach(t => t.classList.remove('is-active'));
        const allContents = document.querySelectorAll('.dm-tab-content');
        allContents.forEach(c => { c.classList.remove('is-active'); c.style.display = 'none'; });
        savedTabButton.classList.add('is-active');
        let targetContentId;
        if (savedTab === 'finance') targetContentId = 'tabFinance';
        else if (savedTab === 'reports') targetContentId = 'tabBinance';
        else if (savedTab === 'trade') targetContentId = 'mobileTradeView';
        else targetContentId = 'tab' + savedTab.charAt(0).toUpperCase() + savedTab.slice(1);
        const targetContent = document.getElementById(targetContentId);
        if (targetContent) {
            targetContent.classList.add('is-active');
            targetContent.style.display = 'block';
        }
        // Bakiye şeridi: Anasayfa, Trade; diğer sekmelerde gizle
        const unifiedStrip = document.getElementById('unifiedKpiStrip');
        if (unifiedStrip) {
            const showStrip = (savedTab === 'reports' || savedTab === 'binance' || savedTab === 'trade');
            unifiedStrip.classList.toggle('kpi-strip-hidden', !showStrip);
            if (showStrip) unifiedStrip.style.removeProperty('display');
            else unifiedStrip.style.display = 'none';
            unifiedStrip.classList.remove('unified-kpi-bots-only');
        }
        updateBinanceConnectionNotice();
        document.body.classList.toggle('tab-finance-active', savedTab === 'finance');
        document.body.classList.toggle('tab-contact-active', savedTab === 'contact');
        document.body.classList.toggle('tab-settings-active', savedTab === 'settings');
        document.body.classList.toggle('tab-trade-active', savedTab === 'trade');
        document.body.classList.toggle('tab-bots-active', savedTab === 'bots');
        if (savedTab === 'binance') {
            var txPanelInit = document.getElementById('transactionHistoryPanel');
            if (txPanelInit) txPanelInit.style.display = 'block';
        }
    } else {
        // Geçersiz veya eksik sekme (örn. eski "reports"): tek bir içerik görünsün diye Anasayfa’yı aç
        const allContents = document.querySelectorAll(".dm-tab-content");
        allContents.forEach(c => { c.classList.remove("is-active"); c.style.display = "none"; });
        const tabBinance = document.getElementById("tabBinance");
        if (tabBinance) { tabBinance.classList.add("is-active"); tabBinance.style.display = "block"; }
        const binanceBtn = document.querySelector('[data-tab="binance"]');
        if (binanceBtn) binanceBtn.classList.add("is-active");
        localStorage.setItem("dashboard_active_tab", "binance");
        var txPanelInit = document.getElementById('transactionHistoryPanel');
        if (txPanelInit) txPanelInit.style.display = 'block';
    }
    const mainContainer = document.getElementById('dashboardMainContainer');
    if (mainContainer) mainContainer.style.visibility = 'visible';
    bindTabs();
    initMobileBottomNav(savedTab);

    let accountId; let accountCode;
    try {
        const resolved = await resolveAccountFromUrl();
        accountId = resolved.accountId;
        accountCode = resolved.accountCode;
    } catch (error) {
        if (typeof window.__DEBUG_DASH__ !== 'undefined' && window.__DEBUG_DASH__) console.error("[dashboard] resolveAccount failed:", error);
        var msg = "Dashboard yüklenemedi: account_id veya account_code gerekli";
        if (error && (error.status === 403 || (error.message && error.message.indexOf("erişim yetkiniz") !== -1))) {
            msg = error.message || "Bu hesaba erişim yetkiniz yok. Kendi hesap kodunuzu kullanın veya doğru hesapla giriş yapın.";
            try {
                localStorage.removeItem("selectedAccountCode");
                localStorage.removeItem("selectedAccountId");
            } catch (e) {}
        } else if (error && error.status === 404) {
            msg = "Hesap bulunamadı. Geçerli bir account_code veya account_id kullanın.";
        } else if (error && error.message) {
            if (!isBenignDashboardFetchError(error)) {
                msg = "Dashboard yüklenemedi: " + error.message;
            }
        }
        if (!isBenignDashboardFetchError(error)) {
            showError(msg);
        }
        if (window.TtScrollRestore && window.TtScrollRestore.forceUnlock) window.TtScrollRestore.forceUnlock();
        return;
    }
    
    State.accountId = accountId;
    State.accountCode = accountCode;
    window.__ACTIVE_ACCOUNT_ID = accountId;
    if (typeof restoreAppbarFromSessionCache === 'function') restoreAppbarFromSessionCache(accountId, accountCode);
    if (showAdminNav) {
        try {
            sessionStorage.setItem("dashboard_admin_account_id", String(accountId));
            if (accountCode) sessionStorage.setItem("dashboard_admin_account_code", accountCode);
        } catch (e) {}
    }
    if (_dashboardPanelsAccountId !== accountId) {
        _botPerformanceLoaded = false;
        _botPerformanceLastSig = '';
        _botPerformanceLastPeriod = null;
        if (typeof resetTxHistoryClientState === 'function') resetTxHistoryClientState();
        if (typeof clearBotsTabCache === 'function') clearBotsTabCache();
        _dashboardPanelsAccountId = accountId;
    }
    if (typeof hydrateWalletFromStorageCache === 'function') hydrateWalletFromStorageCache(accountId);
    if (typeof hydrateKpisFromStorageCache === 'function') hydrateKpisFromStorageCache(accountId);
    if (typeof hydrateDashboardPanelsFromCache === 'function') hydrateDashboardPanelsFromCache(accountId);
    var showFirstLoginModal = isFirstLogin;
    if (isFirstLogin && accountId) {
        showFirstLoginModal = await shouldShowFirstLoginModal(accountId, true);
    }
    restoreFinanceBotsFromSessionCache(accountId);
    if (savedTab === 'bots' && typeof activateBotsTab === 'function') {
        activateBotsTab();
    }
    // En İyi 5 Bot: hesap hazır olur olmaz yükle (snapshot beklemeden); snapshot geldiğinde de yenilenecek
    if (typeof loadGlobalLeaderboard === 'function') {
        loadGlobalLeaderboard(savedTab === 'bots' && isBotsTabCacheReady());
    }
    await loadSpotFavoritesFromStorage();
    if (typeof prefetchMobileTradeFavTickerCache === 'function') prefetchMobileTradeFavTickerCache();
    if (typeof window.__DEBUG_DASH__ !== 'undefined' && window.__DEBUG_DASH__) console.log("[dashboard] initDashboard: accountId =", accountId, "accountCode =", accountCode);
    updateBinanceConnectionNotice();
    var activeTabName = document.querySelector('.dm-tab.is-active')?.getAttribute('data-tab');
    if (activeTabName === 'trade') {
        initMobileTradeSearch();
        if (typeof renderMobileTradeFavorites === 'function') renderMobileTradeFavorites();
        if (typeof startMobileTradeFavPriceUpdates === 'function') startMobileTradeFavPriceUpdates();
    }
    if (new URLSearchParams(window.location.search).get('debug_wallet') === '1' && typeof window.renderWalletDebugOverlay === 'function') {
        window.renderWalletDebugOverlay();
        if (window.intervalRegistry) {
            window.intervalRegistry.start('wallet.debug_overlay', window.renderWalletDebugOverlay, 2000, 'dashboard');
        } else {
            setInterval(window.renderWalletDebugOverlay, 2000);
        }
    }
    // Mobilde de Binance içeriği (varlık şeridi, cüzdan paneli, aktif emirler) veri alsın; sekme is-active olmasa bile
    var binanceTabActive = document.getElementById('tabBinance')?.classList.contains('is-active');
    if (binanceTabActive || isMobileView()) {
        initVarliklarTab();
        if (typeof initBinanceCoinList === 'function') initBinanceCoinList();
        if (typeof updateActiveOrdersPanelPosition === 'function') updateActiveOrdersPanelPosition();
        if (typeof startBinanceTabPolling === 'function') startBinanceTabPolling();
        if (accountId && typeof loadFinanceTrades === 'function') loadFinanceTrades();
    }
    // İşlem geçmişi: ilk yüklemede sync=1 (Binance geçmişi → dosya)
    if (accountId && typeof loadTransactionHistory === 'function') {
        var txHadCache = _txHistoryLoaded;
        loadTransactionHistory(
            State.txHistoryPeriod || 'daily',
            State.txHistoryType || 'buysell',
            State.txHistoryPage || 1,
            !txHadCache,
            { silent: txHadCache }
        );
    }

    // Keep URL with account, tab, first_login/from_admin – yenilemede sayfa ve sekme aynı kalsın
    if (history.replaceState) {
        const q = new URLSearchParams(window.location.search);
        if (accountCode) {
            q.set("account_code", accountCode);
            q.delete("account_id");
        } else if (accountId) {
            q.set("account_id", String(accountId));
            q.delete("account_code");
        }
        q.set("tab", savedTab);
        if (showFirstLoginModal) q.set("first_login", "true");
        else q.delete("first_login");
        if (showAdminNav) q.set("from_admin", "1");
        const newSearch = "?" + q.toString();
        if (window.location.search !== newSearch) {
            history.replaceState(null, "", window.location.pathname + newSearch + (window.location.hash || ""));
        }
    }
    
    // Must change password: disable all tabs, show mandatory password change modal
    if (mustChangePassword) {
        // Disable all tabs
        document.querySelectorAll('.dm-tab').forEach(tab => {
            tab.style.pointerEvents = 'none';
            tab.style.opacity = '0.5';
        });
        // Disable container (blur/disable)
        const container = document.querySelector('.container');
        if (container) {
            container.style.pointerEvents = 'none';
            container.style.opacity = '0.3';
            container.style.filter = 'blur(2px)';
        }
        // Show mandatory password change modal (kapatılamaz)
        setTimeout(() => {
            const modal = document.getElementById('mustChangePasswordModal');
            if (modal) {
                modal.style.display = 'flex';
                const newPwd = document.getElementById('mustChangePasswordNew');
                if (newPwd) setTimeout(() => newPwd.focus(), 100);
                // Prevent closing by clicking outside or ESC
                modal.addEventListener('click', function(e) {
                    if (e.target === modal) e.stopPropagation();
                }, true);
                document.addEventListener('keydown', function(e) {
                    if (e.key === 'Escape' && modal.style.display === 'flex') {
                        e.preventDefault();
                        e.stopPropagation();
                    }
                }, true);
            }
        }, 300);
    }
    
    // İlk giriş: önce admin first_login popup (varsa), kapatılınca API key modalı gösterilir
    // Admin pop-up: önce göster (ilk girişte API key uyarısından önce)
    setTimeout(function () {
        fetchAndShowUserPopup(showFirstLoginModal).then(function (shown) {
            if (showFirstLoginModal && !mustChangePassword && !shown) {
                var modal = document.getElementById('firstLoginModal');
                if (modal) modal.style.display = 'flex';
            }
        });
    }, 400);
    
    if (feeRatesCache && feeRatesCache.accountId !== accountId) feeRatesCache = null;
    ensureFeeRates(accountId).catch(() => {});

    bindMustChangePasswordModal();
    bindCreateBotModal();
    bindRefresh();
    if (!mustChangePassword && typeof window.startChatNotify === 'function') window.startChatNotify();
    bindBotsActions();
    bindBinanceTab();
    bindCoinList();
    
    // Trigger tab-specific initialization if saved tab was restored
    if (savedTab) {
        setTimeout(() => {
            const savedTabButton = document.querySelector(`[data-tab="${savedTab}"]`);
            if (savedTabButton && savedTabButton.classList.contains('is-active')) {
                // Trigger tab-specific handlers
                if (savedTab === "binance") {
                    initVarliklarTab();
                    if (typeof initBinanceCoinList === 'function') initBinanceCoinList();
                    if (typeof startBinanceTabPolling === 'function') startBinanceTabPolling();
                    if (State.accountId) triggerWalletRefreshForVarliklar(State.accountId, { force: true });
                    startVarliklarPeriodicRefresh();
                    if (State.accountId && typeof loadFinanceTrades === 'function') loadFinanceTrades();
                    if (State.accountId && window.BinanceUI && typeof window.BinanceUI.mount === 'function') {
                        window.BinanceUI.mount({ accountId: State.accountId });
                        // loadActiveOrders zaten startBinanceTabPolling içinde çağrıldı; tekrar çağırma (429/timeout azaltır)
                    } else if (!State.accountId) {
                        const b = document.getElementById("varliklarTableBody");
                        if (b) b.innerHTML = '<tr><td colspan="10" style="text-align: center; padding: 2rem; color: var(--ds-text-secondary);">Hesap seçin.</td></tr>';
                    }
                } else if (savedTab === "finance") {
                    initFinanceTab();
                } else if (savedTab === "reports") {
                    initReportsTab();
                } else if (savedTab === "settings") {
                    initSettingsTab();
                } else if (savedTab === "contact") {
                    if (State.accountId && window.apiClient) {
                        window.apiClient.get('/api/auth/chat?account_id=' + State.accountId + '&open=1').catch(function () {});
                    }
                    if (typeof window.startChatNotify === 'function') window.startChatNotify();
                }
            }
        }, 100);
    }
    
    // MarketDataService auto-starts on page load (no need to call start())
    // DEPRECATED: DataHub.start() - use marketDataService instead
    // DataHub.start(accountId);
    
    loadAccountMeta(accountId);
    loadBotsListFast(accountId);
    consumePendingWalletRefreshAfterBot(accountId);
    // Flash Home (Patch H): when enabled, use /api/home/fast + wallet/refresh; no Binance on critical path
    window.FLASH_HOME_ENABLED = typeof window.FLASH_HOME_ENABLED !== 'undefined' ? window.FLASH_HOME_ENABLED : true;
    window.addEventListener('storage', function (e) {
        if (e.key !== 'tt_wallet_refresh_after_bot_v1' || !e.newValue) return;
        var pending = _parseWalletRefreshAfterBotPayload(e.newValue);
        if (!pending) return;
        _applyWalletRefreshAfterBotPayload(pending);
    });
    if (accountId) {
        if (window.marketDataService && typeof window.marketDataService.stop === 'function') {
            window.marketDataService.stop();
        }
        window.intervalRegistry.stop('dashboard.summary');
        if (window.apiClient && typeof window.apiClient.getPublicConfigAsync === 'function') {
            window.apiClient.getPublicConfigAsync().then(function (cfg) {
                window.__DASHBOARD_SSE_ENABLED = cfg && cfg.dashboard_sse_enabled !== false;
                startDashboardSnapshotTransport();
            }).catch(function () {
                window.__DASHBOARD_SSE_ENABLED = false;
                startDashboardSnapshotTransport();
            });
        } else if (window.apiClient && typeof window.apiClient.getPublicConfig === 'function') {
            var cfg = window.apiClient.getPublicConfig();
            window.__DASHBOARD_SSE_ENABLED = cfg && cfg.dashboard_sse_enabled !== false;
            startDashboardSnapshotTransport();
        } else {
            window.__DASHBOARD_SSE_ENABLED = false;
            startDashboardSnapshotTransport();
        }
        window.intervalRegistry.start('dashboard.tx-history', pollTransactionHistoryRevision, TX_HISTORY_POLL_MS, 'dashboard');
        if (window.FLASH_HOME_ENABLED && window.homeFlash && typeof window.homeFlash.init === 'function') {
            window.homeFlash.init();
            fetchSnapshot();
        } else {
            fetchSnapshot();
        }
        // One-time wallet refresh on dashboard load (homeFlash.init zaten triggerRefresh çağırır — çift istek yok)
        if (accountId && !window.__dashboardWalletRefreshDone) {
            window.__dashboardWalletRefreshDone = true;
            if (!window.FLASH_HOME_ENABLED) {
                setTimeout(function () {
                    if (typeof triggerWalletRefreshForVarliklar === 'function') {
                        triggerWalletRefreshForVarliklar(accountId, { force: true });
                    } else if (window.apiClient && typeof window.apiClient.post === 'function') {
                        window.apiClient.post('/api/home/wallet/refresh?account_id=' + accountId + '&force=1', null, { timeout: 25000 })
                            .then(function (res) {
                                if (res && res.ok && res.data && res.data.wallet_live && assetsState && assetsState.wallet) {
                                    normalizeAndApplyWallet(res.data.wallet_live, { source: 'wallet_refresh_init' });
                                }
                            })
                            .catch(function () {});
                    }
                }, 500);
            }
        }
        // Yenileme devam ederken erken hata gösterme (homeFlash ~12–20 sn sürebilir)
        setTimeout(function () {
            if (!assetsState || !assetsState.wallet) return;
            var w = assetsState.wallet;
            if (w.status !== 'idle' && w.status !== 'loading') return;
            if (typeof _walletHasDisplayableAssets === 'function' && _walletHasDisplayableAssets()) return;
            if (_walletPanelUpdating || _varliklarWalletRefreshInflight) return;
            try {
                var lockKey = 'tt_wallet_refresh_lock:' + accountId;
                var lockRaw = localStorage.getItem(lockKey);
                if (lockRaw && (Date.now() - parseInt(lockRaw, 10)) < 25000) return;
            } catch (eLock) {}
            w.status = 'error';
            w.error = { error_code: 'WALLET_TIMEOUT_NO_SOURCE', message: 'Cüzdan verisi zamanında yüklenemedi.' };
            markWalletLiveFetchFailed('WALLET_TIMEOUT_NO_SOURCE', { force: true });
            if (window.BinanceAssetsPanel?.render) window.BinanceAssetsPanel.render();
            if (typeof renderVarliklarList === 'function') renderVarliklarList();
        }, 22000);
        setTimeout(function () {
            if (assetsState.prices && assetsState.prices.data_status === 'empty' && (!assetsState.prices.ts || assetsState.prices.ts === 0)) {
                assetsState.prices.data_status = 'error';
                assetsState.prices._timeout_code = 'PRICES_TIMEOUT_NO_SOURCE';
            }
        }, 10000);
        setTimeout(function () {
            if (typeof maybeSilentWalletRecovery === 'function') maybeSilentWalletRecovery();
        }, 12000);
    } else {
        loadSummary(accountId);
    }

    if (window.TtScrollRestore && typeof window.TtScrollRestore.scheduleFinalize === 'function') {
        window.TtScrollRestore.scheduleFinalize();
    }
    if (window.TtScrollRestore && typeof window.TtScrollRestore.ensureRestored === 'function') {
        window.TtScrollRestore.ensureRestored();
    }

    var openSpotModalSymbol = new URLSearchParams(window.location.search).get('openSpotModal');
    if (openSpotModalSymbol && openSpotModalSymbol.trim()) {
        var binanceTab = document.getElementById('tabBinance');
        if (binanceTab) binanceTab.click();
        setTimeout(function () {
            if (typeof openSpotTradeModal === 'function') openSpotTradeModal(openSpotModalSymbol.trim());
        }, 400);
        if (history.replaceState) {
            var q = new URLSearchParams(window.location.search);
            q.delete('openSpotModal');
            var newSearch = q.toString();
            var newUrl = window.location.pathname + (newSearch ? '?' + newSearch : '') + (window.location.hash || '');
            history.replaceState(null, '', newUrl);
        }
    }

    try {
        var openBotCreate = sessionStorage.getItem('openBotCreate');
        var openBotCreateSymbol = sessionStorage.getItem('openBotCreateSymbol');
        if (openBotCreate === '1' && openBotCreateSymbol && openBotCreateSymbol.trim()) {
            sessionStorage.removeItem('openBotCreate');
            sessionStorage.removeItem('openBotCreateSymbol');
            setTimeout(function () {
                if (typeof openCreateBotModal === 'function') openCreateBotModal();
                var fSym = document.getElementById('fSymbol');
                if (fSym) {
                    fSym.value = openBotCreateSymbol.trim();
                    if (typeof updateCreateBotModalPairStrip === 'function') updateCreateBotModalPairStrip(openBotCreateSymbol.trim());
                }
            }, 400);
        } else {
            var savedParamScreen = sessionStorage.getItem('createBotParamScreen');
            if (savedParamScreen && typeof BOT_STRUCTURES !== 'undefined') {
                sessionStorage.removeItem('createBotParamScreen');
                var template = BOT_STRUCTURES.find(function (s) { return s.id === savedParamScreen; });
                if (template) {
                    currentSelectedTemplate = template;
                    setTimeout(function () {
                        if (typeof openCreateBotModal === 'function') openCreateBotModal();
                    }, 400);
                }
            }
        }
    } catch (e) {}

    // Bot Performans period buttons (event delegation)
    document.addEventListener('click', function (e) {
        var btn = e.target && e.target.closest && e.target.closest('.bot-perf-btn');
        if (!btn || !State.accountId) return;
        var period = btn.getAttribute('data-period');
        if (!period) return;
        document.querySelectorAll('.bot-perf-btn').forEach(function (b) {
            b.classList.toggle('active', b.getAttribute('data-period') === period);
        });
        if (typeof loadBotPerformance === 'function') loadBotPerformance(period);
    });

    // İşlem Geçmişi filtre butonları (event delegation)
    document.addEventListener('click', function (e) {
        var btn = e.target && e.target.closest && e.target.closest('.tx-period-btn, .tx-type-btn');
        if (!btn || !State.accountId) return;
        var period = btn.closest('.tx-period-btn') ? btn.getAttribute('data-period') : null;
        var type = btn.closest('.tx-type-btn') ? btn.getAttribute('data-type') : null;
        if (period) {
            State.txHistoryPeriod = period;
            document.querySelectorAll('.tx-period-btn').forEach(function (b) { b.classList.toggle('active', b.getAttribute('data-period') === period); });
        }
        if (type) {
            State.txHistoryType = type;
            document.querySelectorAll('.tx-type-btn').forEach(function (b) { b.classList.toggle('active', b.getAttribute('data-type') === type); });
        }
        if (period || type) {
            State.txHistoryPage = 1;
            if (typeof loadTransactionHistory === 'function') loadTransactionHistory(State.txHistoryPeriod, State.txHistoryType, 1, false, { force: true });
        }
    });
    // dashboard_snapshot already started in initDashboard when accountId set; no dashboard.summary
    window.intervalRegistry.start('kpi.spot-status', updateKpiCuzdanLiveStatus, 5000, 'dashboard');
    window.intervalRegistry.start('datahub.ws-status', updateDatahubWsIndicator, 5000, 'dashboard');
    updateDatahubWsIndicator();
    ensureDashboardMarketPriceSubscriber();
    window.intervalRegistry.start('dashboard.market.prices', tickDashboardLiveMarketPrices, PRICE_UI_TICK_MS, 'dashboard');
    window.intervalRegistry.start('finance.bots.live', function () {
        if (typeof pollFinanceBotsLiveEquity === 'function') pollFinanceBotsLiveEquity();
    }, 3000, 'dashboard');
    if (typeof ensureFinanceBotsHealthPolling === 'function') ensureFinanceBotsHealthPolling();
    window.addEventListener('tt-server-unreachable', function (ev) {
        if (!ev || !ev.detail) return;
        if (ev.detail.unreachable) applyFinanceBotsServerOfflineState();
        else clearFinanceBotsServerOfflineState();
    });
    
    // Auth ping: update activity, handle admin kick → redirect to login
    (function setupAuthPing() {
        let user;
        try {
            const u = localStorage.getItem('user');
            if (u) user = JSON.parse(u);
        } catch (e) {}
        const isOwner = user && !user.is_admin && user.account_id != null && Number(user.account_id) === Number(State.accountId);
        if (!isOwner || !State.accountId) return;
        window.intervalRegistry.stop('auth.health');
        window.intervalRegistry.start('auth.health', async () => {
            if (!State.accountId) return;
            try {
                const d = await window.apiClient.get('/api/auth/ping?account_id=' + State.accountId, { timeout: 8000, suppressRateLimitToast: true });
                if (d && d.kicked) {
                    try { if (typeof window.clearAuthAndBroadcast === 'function') window.clearAuthAndBroadcast(); } catch (e) {}
                    localStorage.removeItem('user');
                    localStorage.removeItem('token');
                    try { localStorage.removeItem('boot_id'); } catch (e) {}
                    try { localStorage.removeItem('last_route'); } catch (e) {}
                    window.intervalRegistry.stop('auth.health');
                    window.location.replace('/ui/login.html');
                    return;
                }
            } catch (e) {
                if (e && e.status === 401) {
                    localStorage.removeItem('user');
                    localStorage.removeItem('token');
                    try { localStorage.removeItem('boot_id'); } catch (e) {}
                    try { localStorage.removeItem('last_route'); } catch (e) {}
                    window.intervalRegistry.stop('auth.health');
                    window.location.replace('/ui/login.html');
                }
            }
        }, 60000, 'auth.health');
    })();

    // Lockdown: admin erişimi kapattığında tüm kullanıcılar hesaptan atılsın, login’de bakım ekranı görünsün
    window.intervalRegistry.start('dashboard.lockdown-check', async () => {
        try {
            const r = await fetch('/api/health', { cache: 'no-store' });
            if (!r.ok) return;
            const d = await r.json().catch(() => ({}));
            if (d && d.lockdown === true) {
                let user;
                try {
                    const u = localStorage.getItem('user');
                    if (u) user = JSON.parse(u);
                } catch (e) {}
                if (user && user.is_admin) return;
                window.intervalRegistry.stop('dashboard.lockdown-check');
                localStorage.removeItem('user');
                localStorage.removeItem('token');
                try { localStorage.removeItem('boot_id'); } catch (e) {}
                try { localStorage.removeItem('last_route'); } catch (e) {}
                window.location.replace('/ui/login.html');
            }
        } catch (e) {}
    }, 20000, 'dashboard');
    
    // Mobilde arka plana geçince sekme interval'larını durdur (donma önlemi); görünür olunca özet yenile (throttle)
    var visibilityThrottledRefresh = throttle(function () {
        if (!State.accountId || isSpotModalOpen()) return;
        if (typeof shouldRecoverWalletAfterConnectivity === 'function' && shouldRecoverWalletAfterConnectivity()) {
            if (typeof runWalletConnectivityRecovery === 'function') {
                runWalletConnectivityRecovery({ summary: false });
                return;
            }
        }
        loadSummary(State.accountId);
        if (isBinanceTabActive() && typeof triggerWalletRefreshForVarliklar === 'function') {
            triggerWalletRefreshForVarliklar(State.accountId, { force: true });
        }
    }, 800);
    document.addEventListener("visibilitychange", function () {
        if (document.hidden) {
            if (isMobileView() && window.intervalRegistry) {
                window.intervalRegistry.stopByOwner("binanceTab");
                window.intervalRegistry.stopByOwner("tab.varliklar");
                window.intervalRegistry.stopByOwner("tab.coinlist");
                window.intervalRegistry.stopByOwner("tab.list");
                window.intervalRegistry.stopByOwner("tab.reports");
                window.intervalRegistry.stopByOwner("tab.finance");
                window.intervalRegistry.stopByOwner("tab.bots");
                window.intervalRegistry.stopByOwner("tab.settings");
            }
            return;
        }
        visibilityThrottledRefresh();
    });
    
    window.addEventListener("focus", () => {
        if (!State.accountId || isSpotModalOpen()) return;
        if (typeof shouldRecoverWalletAfterConnectivity === 'function' && shouldRecoverWalletAfterConnectivity()) {
            if (typeof runWalletConnectivityRecovery === 'function') {
                runWalletConnectivityRecovery({ summary: false });
                return;
            }
        }
        loadSummary(State.accountId);
        if (isBinanceTabActive() && typeof triggerWalletRefreshForVarliklar === 'function') {
            triggerWalletRefreshForVarliklar(State.accountId, { force: true });
        }
    });
    window.addEventListener('online', function () {
        if (!State.accountId || isSpotModalOpen()) return;
        if (typeof runWalletConnectivityRecovery === 'function') {
            runWalletConnectivityRecovery({ summary: false });
        }
    });
    
    window.addEventListener("beforeunload", function () {
        var active = document.querySelector('.dm-tab.is-active');
        if (active) {
            var tab = active.getAttribute('data-tab');
            if (tab) try { localStorage.setItem('dashboard_active_tab', tab); } catch (_) {}
        }
        if (window.intervalRegistry) {
            window.intervalRegistry.stopByOwner('dashboard');
            window.intervalRegistry.stopByOwner('dashboard.summary');
            window.intervalRegistry.stop('auth.health');
            window.intervalRegistry.stop('dashboard.auth-ping');
            window.intervalRegistry.stop('dashboard.lockdown-check');
            window.intervalRegistry.stop('binanceApiBanner.time');
            window.intervalRegistry.stopByOwner('binanceTab');
        }
        if (window.modalPriceInterval) {
            clearInterval(window.modalPriceInterval);
            window.modalPriceInterval = null;
        }
        stopBalanceUpdates();
        stopActiveOrdersTracking();
    });
}

function closeFirstLoginModal() {
    const modal = document.getElementById('firstLoginModal');
    if (modal) modal.style.display = 'none';
    markFirstLoginComplete();
}

async function markFirstLoginComplete() {
    const userStr = localStorage.getItem('user');
    if (userStr) {
        try {
            const user = JSON.parse(userStr);
            user.is_first_login = false;
            localStorage.setItem('user', JSON.stringify(user));
        } catch (e) {}
    }
    try {
        const su = sessionStorage.getItem('user');
        if (su) {
            const u2 = JSON.parse(su);
            u2.is_first_login = false;
            sessionStorage.setItem('user', JSON.stringify(u2));
        }
    } catch (_) {}
    if (State.accountId && window.apiClient) {
        try {
            await window.apiClient(`/api/accounts/${State.accountId}/settings`, { method: 'PATCH', body: { is_first_login: false } });
        } catch (_) {}
    }
    if (history.replaceState) {
        const q = new URLSearchParams(window.location.search);
        if (q.has('first_login')) {
            q.delete('first_login');
            const qs = q.toString();
            history.replaceState(null, '', window.location.pathname + (qs ? '?' + qs : '') + (window.location.hash || ''));
        }
    }
}

async function shouldShowFirstLoginModal(accountId, isFirstLogin) {
    if (!isFirstLogin || !accountId) return false;
    try {
        const data = await window.apiClient.get(`/api/accounts/${accountId}/settings`);
        if (data && data.has_binance_keys) {
            await markFirstLoginComplete();
            return false;
        }
    } catch (_) {}
    return true;
}

window.closeFirstLoginModal = closeFirstLoginModal;

// ============================================
// FINANCIAL ACCOUNT TAB (Finansal Hesap)
// ============================================

window.dismissUserPopup = dismissUserPopup;

// Init on DOM ready
if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initDashboard);
} else {
    initDashboard();
}
