/**
 * FILE: dashboard.js
 * VERSION: vREBUILD1
 * DATE: 2026-01-22
 * CHANGE: Bot listesi komple sıfırdan yazıldı - backend API'ye direkt bağlan, basit render
 */

// Global State
var State = (window.State && typeof window.State === 'object') ? window.State : {
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
State.timers = State.timers && typeof State.timers === 'object' ? State.timers : { summary: null, bots: null };
window.State = State;

var WALLET_FX_ASSETS = Array.isArray(window.WALLET_FX_ASSETS)
    ? window.WALLET_FX_ASSETS
    : ['TRY', 'EUR', 'GBP'];
window.WALLET_FX_ASSETS = WALLET_FX_ASSETS;
var QUOTE = (typeof window.QUOTE === 'string' && window.QUOTE.trim())
    ? window.QUOTE.trim().toUpperCase()
    : 'USDT';
window.QUOTE = QUOTE;
var TEST_WALLET_STABLE_ASSETS = Array.isArray(window.TEST_WALLET_STABLE_ASSETS)
    ? window.TEST_WALLET_STABLE_ASSETS
    : ['USDT', 'USDC', 'FDUSD', 'BUSD', 'TUSD', 'DAI'];
window.TEST_WALLET_STABLE_ASSETS = TEST_WALLET_STABLE_ASSETS;
var _varlikDisplayPriceCache = (window._varlikDisplayPriceCache && typeof window._varlikDisplayPriceCache === 'object')
    ? window._varlikDisplayPriceCache
    : Object.create(null);
window._varlikDisplayPriceCache = _varlikDisplayPriceCache;
var _varlikDisplayChangeCache = (window._varlikDisplayChangeCache && typeof window._varlikDisplayChangeCache === 'object')
    ? window._varlikDisplayChangeCache
    : Object.create(null);
window._varlikDisplayChangeCache = _varlikDisplayChangeCache;
var _varlikPriceBlinkUntil = (window._varlikPriceBlinkUntil && typeof window._varlikPriceBlinkUntil === 'object')
    ? window._varlikPriceBlinkUntil
    : Object.create(null);
window._varlikPriceBlinkUntil = _varlikPriceBlinkUntil;

function ensureVarlikDisplayPriceCache() {
    if (!_varlikDisplayPriceCache || typeof _varlikDisplayPriceCache !== 'object') {
        _varlikDisplayPriceCache = Object.create(null);
    }
    window._varlikDisplayPriceCache = _varlikDisplayPriceCache;
    return _varlikDisplayPriceCache;
}

function ensureVarlikDisplayChangeCache() {
    if (!_varlikDisplayChangeCache || typeof _varlikDisplayChangeCache !== 'object') {
        _varlikDisplayChangeCache = Object.create(null);
    }
    window._varlikDisplayChangeCache = _varlikDisplayChangeCache;
    return _varlikDisplayChangeCache;
}

function ensureVarlikPriceBlinkCache() {
    if (!_varlikPriceBlinkUntil || typeof _varlikPriceBlinkUntil !== 'object') {
        _varlikPriceBlinkUntil = Object.create(null);
    }
    window._varlikPriceBlinkUntil = _varlikPriceBlinkUntil;
    return _varlikPriceBlinkUntil;
}

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
var priceCache = (window.priceCache && typeof window.priceCache === 'object') ? window.priceCache : {};
var priceCacheTime = (window.priceCacheTime && typeof window.priceCacheTime === 'object') ? window.priceCacheTime : {};
window.priceCache = priceCache;
window.priceCacheTime = priceCacheTime;

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
            var sym = img.getAttribute('data-symbol') || img.getAttribute('alt') || '';
            if (typeof shouldEagerLoadLogo === 'function' && shouldEagerLoadLogo(sym)) {
                img.src = dataSrc;
                img.removeAttribute('data-src');
                return;
            }
            img.onload = function () { if (window.markCoinLogoLoaded) window.markCoinLogoLoaded(img); };
            img.onerror = function () { if (window.handleCoinLogoError) window.handleCoinLogoError(img); };
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
    if (typeof isWalletDataLive === 'function' && isWalletDataLive()) return;
    if (typeof _walletHasDisplayableAssets === 'function' && _walletHasDisplayableAssets()
        && typeof _isHardWalletError === 'function' && !_isHardWalletError(walletErrorCode())) {
        return;
    }
    var stale = false;
    if (window.__walletDebugMeta && window.__walletDebugMeta.wallet_age_sec != null) {
        stale = Number(window.__walletDebugMeta.wallet_age_sec) >= 900;
    }
    if (!stale && assetsState && assetsState.wallet) {
        stale = assetsState.wallet.data_status === 'stale'
            && typeof _isHardWalletError === 'function'
            && _isHardWalletError(walletErrorCode());
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

function applySnapshotToUI(data) {
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
        if (data.bots && Array.isArray(data.bots)) {
            State.bots = hydrateBotsWithMetricsCache(data.bots);
            resetFinanceBotsLiveCache(State.bots);
        }
        const merged = { ...data.pnl, binance_balance_usd: spotUsd, spot_balance_usd: spotUsd, free_usd: data.wallet?.free_usd ?? 0, locked_usd: data.wallet?.locked_usd ?? 0, available_usd: data.wallet?.available_usd ?? 0, bot_locked_usd: data.wallet?.bot_locked_usd ?? 0, account: data.account || {}, bots: Array.isArray(data.bots) ? data.bots : (State.bots || []), bot_summary: data.pnl.bot_summary || [] };
        if (typeof updateFinanceKPIs === 'function') updateFinanceKPIs(merged);
    }
    if (data.bots && Array.isArray(data.bots) && data.account) {
        var incomingBots = data.bots;
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
                        renderBotsList(State.bots, { clearWhenEmpty: true });
                    }
                } else {
                    renderBotsList(State.bots, { clearWhenEmpty: true });
                }
            }
            if (typeof updateKPIs === 'function') updateKPIs(summaryShape);
            if (typeof maybeRefreshWalletOnBotsChange === 'function') maybeRefreshWalletOnBotsChange(State.bots, data.account);
            if (typeof updateAccountName === 'function') updateAccountName(data.account.name || "Hesap Dashboard");
            if (typeof setAppbarAccountHolderName === 'function') setAppbarAccountHolderName(summaryShape);
            hideError();
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
var WALLET_POLL_MS = Number.isFinite(Number(window.WALLET_POLL_MS)) ? Number(window.WALLET_POLL_MS) : 12000;
var WALLET_BACKOFF_MIN = Number.isFinite(Number(window.WALLET_BACKOFF_MIN)) ? Number(window.WALLET_BACKOFF_MIN) : 3000;
var WALLET_BACKOFF_MAX = Number.isFinite(Number(window.WALLET_BACKOFF_MAX)) ? Number(window.WALLET_BACKOFF_MAX) : 60000;
window.WALLET_POLL_MS = WALLET_POLL_MS;
window.WALLET_BACKOFF_MIN = WALLET_BACKOFF_MIN;
window.WALLET_BACKOFF_MAX = WALLET_BACKOFF_MAX;
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
    } else if (keysConfigured && !err && (totalUsd != null || assets.length > 0)) {
        var staleMeta = explicitStatus === 'stale' || meta.stale;
        var staleCode = meta.stale_code || payload.last_error_code || payload._error_code || '';
        if (staleMeta) {
            assetsState.wallet.data_status = 'stale';
            markWalletCachedLiveFetchStale(staleCode || 'WALLET_STALE');
        } else if ((_isLiveWalletSource(source) && !meta.skipped) || snapshotFresh) {
            assetsState.wallet.data_status = snapshotFresh ? 'fresh' : 'cached';
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
function isWalletAssetSuspiciousFx(a) {
    var fxAssets = Array.isArray(WALLET_FX_ASSETS) ? WALLET_FX_ASSETS : ['TRY', 'EUR', 'GBP'];
    if (!a || fxAssets.indexOf((a.asset || '').toUpperCase()) === -1) return false;
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
const SPOT_FAVORITES_SYNC_MS = 5 * 60 * 1000;
var spotFavorites = []; // string[] (symbols: BTCUSDT, ETHBTC, ...)
var _spotFavoritesServerSyncAt = 0;
var _spotFavoritesLoadPromise = null;

function getFavoritesStorageKey() {
    return State.accountId ? (FAVORITES_STORAGE_PREFIX + State.accountId) : null;
}

function hydrateSpotFavoritesFromLocal() {
    loadSpotFavoritesFromLocalStorage();
    try {
        var sk = State.accountId ? ('spot_favorites_sync_at_' + State.accountId) : null;
        if (sk) {
            var ts = parseInt(sessionStorage.getItem(sk) || '0', 10);
            if (ts > 0) _spotFavoritesServerSyncAt = ts;
        }
    } catch (e) {}
}

function _markSpotFavoritesSynced() {
    _spotFavoritesServerSyncAt = Date.now();
    try {
        var sk = State.accountId ? ('spot_favorites_sync_at_' + State.accountId) : null;
        if (sk) sessionStorage.setItem(sk, String(_spotFavoritesServerSyncAt));
    } catch (e) {}
}

function ensureSpotFavoritesLoaded(force) {
    if (!State.accountId) return Promise.resolve();
    hydrateSpotFavoritesFromLocal();
    var now = Date.now();
    if (!force && spotFavorites.length > 0 && _spotFavoritesServerSyncAt
        && (now - _spotFavoritesServerSyncAt) < SPOT_FAVORITES_SYNC_MS) {
        return Promise.resolve();
    }
    if (_spotFavoritesLoadPromise) return _spotFavoritesLoadPromise;
    _spotFavoritesLoadPromise = loadSpotFavoritesFromStorage().finally(function () {
        _spotFavoritesLoadPromise = null;
    });
    return _spotFavoritesLoadPromise;
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
    if (!State.accountId) return;
    if (spotFavorites.length === 0) loadSpotFavoritesFromLocalStorage();
    try {
        var data = await window.apiClient.get('/api/accounts/' + State.accountId + '/spot-favorites');
        var list = data && Array.isArray(data.symbols) ? data.symbols : [];
        var next = list.map(function (s) { return normalizePairSymbol(s); }).filter(Boolean);
        if (next.length === 0) {
            if (spotFavorites.length === 0) loadSpotFavoritesFromLocalStorage();
            if (spotFavorites.length > 0) {
                window.apiClient.put('/api/accounts/' + State.accountId + '/spot-favorites', { symbols: spotFavorites.slice() }).catch(function () {});
            }
        } else {
            spotFavorites = next;
        }
        try { localStorage.setItem(getFavoritesStorageKey(), JSON.stringify(spotFavorites)); } catch (e) {}
        _markSpotFavoritesSynced();
    } catch (e) {
        if (spotFavorites.length === 0) loadSpotFavoritesFromLocalStorage();
        if (spotFavorites.length === 0) throw e;
    }
}

function saveSpotFavoritesToStorage() {
    if (!State.accountId) return Promise.resolve();
    var payload = { symbols: spotFavorites.slice() };
    return window.apiClient.put('/api/accounts/' + State.accountId + '/spot-favorites', payload).then(function () {
        try { localStorage.setItem(getFavoritesStorageKey(), JSON.stringify(spotFavorites)); } catch (e) {}
        _markSpotFavoritesSynced();
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
    ensureVarlikDisplayChangeCache()[sym] = Number(pct);
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
    var changeCache = ensureVarlikDisplayChangeCache();
    if (sym && changeCache[sym] != null && Number.isFinite(changeCache[sym])) {
        return changeCache[sym];
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
_varlikDisplayPriceCache = (_varlikDisplayPriceCache && typeof _varlikDisplayPriceCache === 'object')
    ? _varlikDisplayPriceCache
    : Object.create(null);
window._varlikDisplayPriceCache = _varlikDisplayPriceCache;
_varlikDisplayChangeCache = (_varlikDisplayChangeCache && typeof _varlikDisplayChangeCache === 'object')
    ? _varlikDisplayChangeCache
    : Object.create(null);
window._varlikDisplayChangeCache = _varlikDisplayChangeCache;

function rememberVarlikDisplayPrice(asset, price) {
    var sym = (asset || '').toUpperCase();
    if (!sym) return;
    var p = Number(price);
    if (Number.isFinite(p) && p > 0) ensureVarlikDisplayPriceCache()[sym] = p;
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
    var cached = ensureVarlikDisplayPriceCache()[sym];
    if (cached != null && Number.isFinite(cached) && cached > 0) return cached;
    return null;
}

function getVarlikDisplayChangePct(asset, rowEl) {
    var sym = (asset || '').toUpperCase();
    var live = getAssetChangePct(asset);
    if (live != null && Number.isFinite(live)) {
        if (sym) ensureVarlikDisplayChangeCache()[sym] = live;
        return live;
    }
    if (rowEl) {
        var changeCell = rowEl.querySelector('.change-pct');
        if (changeCell) {
            var fromAttr = parseFloat(changeCell.getAttribute('data-change-pct') || '');
            if (Number.isFinite(fromAttr)) return fromAttr;
        }
    }
    var changeCache = ensureVarlikDisplayChangeCache();
    if (sym && changeCache[sym] != null && Number.isFinite(changeCache[sym])) {
        return changeCache[sym];
    }
    return null;
}

function formatVarlikPriceDisplay(asset, price) {
    if (price != null && Number.isFinite(price) && price > 0) return fmtCoinPrice(price);
    var cached = ensureVarlikDisplayPriceCache()[(asset || '').toUpperCase()];
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

function isTestWalletStableAsset(asset) {
    var stableAssets = Array.isArray(TEST_WALLET_STABLE_ASSETS)
        ? TEST_WALLET_STABLE_ASSETS
        : ['USDT', 'USDC', 'FDUSD', 'BUSD', 'TUSD', 'DAI'];
    return stableAssets.indexOf((asset || '').toUpperCase()) >= 0;
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
var _testKpiStableSpot = { total: null, avail: null, locked: null, botSig: '', at: 0 };

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

function testAccountRunningBotsStructureSignature() {
    if (typeof State === 'undefined') return '';
    var bots = (State.summary && Array.isArray(State.summary.bots) && State.summary.bots.length)
        ? State.summary.bots
        : (Array.isArray(State.bots) ? State.bots : []);
    return bots.filter(function (b) {
        var st = String((b && b.status) || '').toLowerCase();
        return st === 'running' || st === 'active';
    }).map(function (b) {
        return String((b && (b.bot_id || b.id)) || '') + ':' + String((b && b.symbol) || '');
    }).sort().join('|');
}

function testAccountBotLockedQtySignature(tbody) {
    var root = tbody || document.getElementById('varliklarTableBody');
    if (root && root.querySelectorAll) {
        var rows = Array.from(root.querySelectorAll('tr[data-asset]')).map(function (row) {
            var asset = row.getAttribute('data-asset') || '';
            var qty = Number(row.getAttribute('data-bot-locked') || 0) || 0;
            return asset.toUpperCase() + ':' + qty.toFixed(8);
        });
        if (rows.length) return rows.sort().join('|');
    }
    var assets = (assetsState && assetsState.wallet && assetsState.wallet.assets) || [];
    return assets.map(function (a) {
        var asset = (a && a.asset) || '';
        var qty = Number((a && a.bot_locked) || 0) || 0;
        return asset.toUpperCase() + ':' + qty.toFixed(8);
    }).sort().join('|');
}

function testAccountKpiParts(tbody) {
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
    return {
        avail: Number(avail) || 0,
        botEq: Number(botEq) || 0,
        locked: Number(locked) || 0,
        botSig: testAccountRunningBotsStructureSignature() + '|' + testAccountBotLockedQtySignature(tbody)
    };
}

/** Test paper: TOPLAM SPOT = USDT kullanılabilir + çalışan bot equity + kilitli. */
function testAccountKpiTotalUsd(tbody) {
    var parts = testAccountKpiParts(tbody);
    return parts.avail + parts.botEq + parts.locked;
}

function stabilizeTestAccountSpotKpi(parts) {
    var total = (Number(parts.avail) || 0) + (Number(parts.botEq) || 0) + (Number(parts.locked) || 0);
    if (!(total > 0)) return total;
    var prev = _testKpiStableSpot;
    var structureSame = prev.botSig === parts.botSig;
    var availSame = prev.avail != null && Math.abs(Number(prev.avail) - Number(parts.avail)) < 0.01;
    var lockedSame = prev.locked != null && Math.abs(Number(prev.locked) - Number(parts.locked)) < 0.01;
    var prevTotal = Number(prev.total);
    if (
        Number.isFinite(prevTotal)
        && prevTotal > 0
        && structureSame
        && availSame
        && lockedSame
    ) {
        return prevTotal;
    }
    _testKpiStableSpot = {
        total: total,
        avail: Number(parts.avail) || 0,
        locked: Number(parts.locked) || 0,
        botSig: parts.botSig || '',
        at: Date.now()
    };
    return total;
}

function updateTestAccountKpiCuzdanFromStrip() {
    if (typeof State === 'undefined' || !State.isTestAccount) return;
    var tbody = document.getElementById('varliklarTableBody');
    var parts = testAccountKpiParts(tbody);
    var total = stabilizeTestAccountSpotKpi(parts);
    if (!(total > 0) && assetsState && assetsState.wallet && Array.isArray(assetsState.wallet.assets)) {
        var avail = testAccountUsdtAvailablePool(assetsState.wallet.assets);
        var botEq = testAccountRunningBotsEquityUsd();
        if (!(botEq > 0) && typeof assetsState.wallet.bot_locked_usd === 'number') {
            botEq = assetsState.wallet.bot_locked_usd;
        }
        var locked = typeof assetsState.wallet.locked_usd === 'number' ? assetsState.wallet.locked_usd : 0;
        total = stabilizeTestAccountSpotKpi({
            avail: avail,
            botEq: botEq,
            locked: locked,
            botSig: testAccountRunningBotsStructureSignature() + '|' + testAccountBotLockedQtySignature()
        });
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

_varlikPriceBlinkUntil = (_varlikPriceBlinkUntil && typeof _varlikPriceBlinkUntil === 'object')
    ? _varlikPriceBlinkUntil
    : Object.create(null);
window._varlikPriceBlinkUntil = _varlikPriceBlinkUntil;

/** Cüzdan tablosu fiyat blink — Mevcut Botlar ile aynı efekt (mevcutBotPriceFlashUp/Down). */
function applyVarlikPriceBlink(priceCell, newPrice, oldPrice, asset) {
    if (!priceCell || !Number.isFinite(newPrice) || !Number.isFinite(oldPrice)) return;
    if (Math.abs(newPrice - oldPrice) < 1e-10) return;
    if (typeof isTestWalletStableAsset === 'function' && asset && isTestWalletStableAsset(asset)) return;
    var key = (asset || '') + '|' + (priceCell.closest('tr') && priceCell.closest('tr').getAttribute('data-asset') || '');
    var now = Date.now();
    var cooldownMs = (typeof FINANCE_BOT_PRICE_BLINK_COOLDOWN_MS === 'number') ? FINANCE_BOT_PRICE_BLINK_COOLDOWN_MS : 350;
    var blinkCache = ensureVarlikPriceBlinkCache();
    if (blinkCache[key] && now < blinkCache[key]) return;
    blinkCache[key] = now + cooldownMs;
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
            triggerWalletRefreshForVarliklar(State.accountId, { force: true });
        } else if (window.homeFlash && typeof window.homeFlash.triggerRefresh === 'function') {
            window.homeFlash.triggerRefresh(State.accountId, true);
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
                var appliedOk = !d.stale && !d.skipped;
                if (appliedOk && typeof markWalletLiveFetchOk === 'function') {
                    markWalletLiveFetchOk();
                }
            }
            var gotWalletLive = !!(res && res.ok && res.data && res.data.wallet_live);
            if (res && res.data && res.data.stale && gotWalletLive
                && typeof _walletHasDisplayableAssets === 'function' && _walletHasDisplayableAssets()
                && typeof _isHardWalletError === 'function'
                && !_isHardWalletError(res.data.last_error_code || res.data.error_code)) {
                /* yumuşak stale + geçerli bakiye: rozeti canlı tut, döngüye girme */
            } else if (res && res.data && res.data.stale && res.data.last_error_code && typeof markWalletCachedLiveFetchStale === 'function') {
                markWalletCachedLiveFetchStale(res.data.last_error_code);
            } else if (res && res.data && res.data.stale && !res.data.last_error_code && typeof markWalletCachedLiveFetchStale === 'function') {
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
        ensureSpotFavoritesLoaded()
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
            const showStrip = (savedTab === 'reports' || savedTab === 'binance' || savedTab === 'trade' || savedTab === 'bots');
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
    if (typeof syncDashboardTestAccountFlag === 'function') syncDashboardTestAccountFlag();
    else if (/^TEST/i.test(String(accountCode || '').trim())) State.isTestAccount = true;
    if (typeof updateKpiCuzdanLiveStatus === 'function') updateKpiCuzdanLiveStatus();
    if (typeof hydrateSpotFavoritesFromLocal === 'function') hydrateSpotFavoritesFromLocal();
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
    if (savedTab === 'trade' && typeof renderMobileTradeFavorites === 'function') {
        renderMobileTradeFavorites();
    }
    ensureSpotFavoritesLoaded().then(function () {
        if (typeof window._mobileTradeFavListChanged === 'function' && window._mobileTradeFavListChanged()) {
            if (typeof renderMobileTradeFavorites === 'function') renderMobileTradeFavorites(true);
        }
        if (typeof prefetchMobileTradeFavTickerCache === 'function') prefetchMobileTradeFavTickerCache();
    }).catch(function () {
        if (typeof prefetchMobileTradeFavTickerCache === 'function') prefetchMobileTradeFavTickerCache();
    });
    if (typeof window.__DEBUG_DASH__ !== 'undefined' && window.__DEBUG_DASH__) console.log("[dashboard] initDashboard: accountId =", accountId, "accountCode =", accountCode);
    updateBinanceConnectionNotice();
    var activeTabName = document.querySelector('.dm-tab.is-active')?.getAttribute('data-tab');
    if (activeTabName === 'trade') {
        initMobileTradeSearch();
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
            setTimeout(function () {
                if (typeof maybeRefreshStaleWalletFromDashboard === 'function') {
                    maybeRefreshStaleWalletFromDashboard();
                }
            }, 2500);
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
            var paramScreenKey = (typeof createBotParamScreenStorageKey === "function" && State.accountId)
                ? createBotParamScreenStorageKey(State.accountId)
                : "createBotParamScreen";
            var savedParamScreen = sessionStorage.getItem(paramScreenKey)
                || sessionStorage.getItem("createBotParamScreen");
            if (savedParamScreen && typeof BOT_STRUCTURES !== "undefined") {
                sessionStorage.removeItem(paramScreenKey);
                sessionStorage.removeItem("createBotParamScreen");
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

window.dismissUserPopup = (typeof window.dismissUserPopup === 'function') ? window.dismissUserPopup : function () {
    var overlay = document.getElementById("userPopupOverlay");
    if (overlay) overlay.style.display = "none";
};

// Init on DOM ready
if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initDashboard);
} else {
    initDashboard();
}
