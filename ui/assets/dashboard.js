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
function isMobileView() {
    return typeof window !== "undefined" && window.innerWidth <= 768;
}
/** Throttle: fn en fazla ms aralıkla çağrılır */
function throttle(fn, ms) {
    let last = 0, timer = null;
    return function _throttled() {
        const now = Date.now();
        const elapsed = now - last;
        if (elapsed >= ms || last === 0) {
            last = now;
            fn.apply(this, arguments);
            return;
        }
        if (!timer) {
            timer = setTimeout(() => {
                timer = null;
                last = Date.now();
                fn.apply(this, arguments);
            }, ms - elapsed);
        }
    };
}

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
const SpotCache = {
    prices: new Map(),      // symbol -> {price, ts}
    balances: new Map(),    // accountId -> {freeUSDT, freeBase, assetsMap, ts}
    filters: new Map(),      // symbol -> {tickSize, stepSize, minNotional, ts}
    
    // TTL constants
    PRICE_TTL: 2000,        // 2s
    BALANCE_TTL: 3000,      // 3s
    FILTER_TTL: 6 * 60 * 60 * 1000, // 6 hours
    
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
const usdFmt = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
});

function fmtUsd(v) {
    if (v == null || v === '' || (typeof v === 'number' && !Number.isFinite(v))) return '—';
    const n = Number(v);
    if (!Number.isFinite(n)) return '—';
    return usdFmt.format(n);
}

/** Binance tarzı ondalık: fiyat aralığına göre uygun basamak (tick size benzeri). XRP 1.3676 gibi 4 basamak. */
function fmtCoinPrice(v) {
    const n = Number(v);
    if (n == null || !Number.isFinite(n) || n < 0) return '—';
    if (n === 0) return '$0.00';
    if (n >= 1000) return '$' + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    if (n >= 1) return '$' + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 });
    if (n >= 0.1) return '$' + n.toFixed(4);
    if (n >= 0.01) return '$' + n.toFixed(5);
    if (n >= 0.0001) return '$' + n.toFixed(6);
    if (n >= 1e-6) return '$' + n.toFixed(8);
    return '$' + n.toFixed(8);
}

function fmtSignedUsd(v) {
    const n = Number(v || 0);
    const sign = n >= 0 ? "+" : "-";
    return sign + usdFmt.format(Math.abs(n));
}

function fmtNum(v, decimals = 2) {
    const n = Number(v || 0);
    if (!Number.isFinite(n)) return "0";
    if (decimals === 0) return Math.round(n).toLocaleString('en-US');
    return n.toLocaleString('en-US', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals
    });
}
window.fmtUsd = fmtUsd;
window.fmtNum = fmtNum;

/** Nokta ve virgül geçerli ondalık parse (0,5 veya 0.5) */
function parseDecimal(str, defaultVal) {
    if (str == null || str === "") return defaultVal;
    var s = String(str).trim().replace(",", ".");
    var n = parseFloat(s);
    return Number.isFinite(n) ? n : defaultVal;
}

/** Extract readable message from API error detail (FastAPI 422 returns array of objects) */
function parseApiErrorDetail(detail) {
    if (detail == null) return "Bilinmeyen hata";
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
        return detail.map((d) => (d && typeof d.msg === "string" ? d.msg : JSON.stringify(d))).join("; ") || "Doğrulama hatası";
    }
    if (typeof detail === "object" && detail.msg) return detail.msg;
    return String(detail);
}

function relativeTime(ts) {
    if (!ts) return "—";
    const date = new Date(ts);
    const now = new Date();
    const diffMs = now - date;
    const diffSecs = Math.floor(diffMs / 1000);
    const diffMins = Math.floor(diffSecs / 60);
    const diffHours = Math.floor(diffMins / 60);
    if (diffSecs < 60) return `${diffSecs}s önce`;
    if (diffMins < 60) return `${diffMins}d önce`;
    if (diffHours < 24) return `${diffHours}s önce`;
    return date.toLocaleDateString('tr-TR');
}

// DEPRECATED: fetchWithTimeout - Use apiClient instead
// This function is kept for backward compatibility but should not be used in new code
async function fetchWithTimeout(url, ms = 10000, options = {}) {
    console.warn("[dashboard] fetchWithTimeout is deprecated, use apiClient instead");
    // Convert to apiClient call
    const endpoint = url.startsWith('http') ? url : url.replace(window.location.origin, '');
    try {
        const data = await window.apiClient.get(endpoint, { timeout: ms, ...options });
        // Return Response-like object for backward compatibility
        return {
            ok: true,
            json: async () => data,
            text: async () => (typeof data === 'string' ? data : JSON.stringify(data))
        };
    } catch (error) {
        // Return error Response-like object
        return {
            ok: false,
            status: error.status || 0,
            json: async () => ({ error: error.message }),
            text: async () => error.message
        };
    }
}

// Error translation function
function translateErrorToTurkish(errorMsg) {
    if (!errorMsg) return "Bilinmeyen hata";
    
    const errorLower = errorMsg.toLowerCase();
    
    // Insufficient balance
    if (errorLower.includes("insufficient balance") || errorLower.includes("yetersiz bakiye")) {
        return "Yetersiz bakiye. İşlem için yeterli bakiyeniz bulunmamaktadır.";
    }
    
    // API key errors
    if (errorLower.includes("invalid api") || errorLower.includes("invalid signature") || errorLower.includes("geçersiz api")) {
        return "Geçersiz API anahtarı veya imza. Lütfen API bilgilerinizi kontrol edin.";
    }
    
    // LOT_SIZE / step size
    if (errorLower.includes('lot_size') || errorLower.includes('filter failure: lot_size')) {
        return "Miktar Binance lot kurallarına uymuyor. Miktarı adım boyutuna göre düşürün veya %100 yerine biraz daha az satmayı deneyin.";
    }

    // Min notional
    if (errorLower.includes("min notional") || errorLower.includes("minimum işlem")) {
        return "Minimum işlem tutarı yetersiz. Daha yüksek bir miktar giriniz.";
    }
    
    // Precision errors
    if (errorLower.includes("precision") || errorLower.includes("tick size") || errorLower.includes("step size")) {
        return "Fiyat veya miktar hassasiyeti hatalı. Değerleri doğru formatta giriniz.";
    }
    
    // Order not found / already canceled (Binance -2011: Unknown order sent)
    if (errorLower.includes("order does not exist") || errorLower.includes("emir bulunamadı") || errorLower.includes("unknown order sent")) {
        return "Emir bulunamadı veya zaten iptal edilmiş / gerçekleşmiş.";
    }
    
    // Duplicate order
    if (errorLower.includes("duplicate") || errorLower.includes("aynı emir")) {
        return "Aynı emir zaten mevcut. Lütfen farklı bir emir oluşturun.";
    }
    
    // Market closed
    if (errorLower.includes("market is closed") || errorLower.includes("trading is not allowed") || errorLower.includes("piyasa kapalı")) {
        return "Piyasa kapalı. İşlem yapılamıyor.";
    }
    
    // Rate limit
    if (errorLower.includes("rate limit") || errorLower.includes("too many requests") || errorLower.includes("çok fazla istek")) {
        return "Çok fazla istek. Lütfen birkaç saniye bekleyip tekrar deneyin.";
    }
    
    // Network errors
    if (errorLower.includes("timeout") || errorLower.includes("connection") || errorLower.includes("network") || errorLower.includes("bağlantı")) {
        return "Bağlantı hatası. İnternet bağlantınızı kontrol edip tekrar deneyin.";
    }
    
    // Account not found
    if (errorLower.includes("account not found") || errorLower.includes("hesap bulunamadı")) {
        return "Hesap bulunamadı. Lütfen hesap bilgilerinizi kontrol edin.";
    }
    
    // Order validation
    if (errorLower.includes("validation") || errorLower.includes("required") || errorLower.includes("gerekli")) {
        return "Eksik bilgi. Lütfen tüm gerekli alanları doldurunuz.";
    }
    
    // If already in Turkish or no match, return as is
    return errorMsg;
}

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
        var liveLabel = (typeof State !== 'undefined' && State.isTestAccount) ? 'Test' : (data.has_binance_keys ? 'Canlı' : 'Bağlı değil');
        if (kpiLive) kpiLive.textContent = liveLabel;
        if (kpiBotPct) kpiBotPct.textContent = liveLabel;
    } catch (_) {
        assetsState.wallet.keys_configured = false;
        notice.classList.remove('binance-connection-notice--hidden');
        notice.style.display = 'block';
        var fallbackLabel = (typeof State !== 'undefined' && State.isTestAccount) ? 'Test' : 'Bağlı değil';
        patchText('kpiCuzdanLive', fallbackLabel);
        patchText('kpiBotBakiyePct', fallbackLabel);
    }
}

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

/** Resolve account from URL (account_code or account_id), localStorage, or session user. Returns { accountId, accountCode }. */
async function resolveAccountFromUrl() {
    const qs = new URLSearchParams(location.search);
    const code = qs.get("account_code");
    const idParam = qs.get("account_id");
    const stored = localStorage.getItem("selectedAccountCode") || localStorage.getItem("selectedAccountId");

    if (code && /^\d{6}$/.test(String(code).trim())) {
        const data = await window.apiClient.get("/api/accounts/by-code/" + encodeURIComponent(code.trim()));
        return { accountId: data.id, accountCode: data.account_code || code.trim() };
    }
    if (idParam) {
        const n = parseInt(String(idParam).trim(), 10);
        if (Number.isFinite(n) && n > 0) {
            const data = await window.apiClient.get("/api/accounts/" + n);
            return { accountId: n, accountCode: data.account_code || null };
        }
    }
    if (stored) {
        const s = String(stored).trim();
        if (/^\d{6}$/.test(s)) {
            const data = await window.apiClient.get("/api/accounts/by-code/" + encodeURIComponent(s));
            return { accountId: data.id, accountCode: data.account_code || s };
        }
        const n = parseInt(s, 10);
        if (Number.isFinite(n) && n > 0) {
            const data = await window.apiClient.get("/api/accounts/" + n);
            return { accountId: n, accountCode: data.account_code || null };
        }
    }
    // Oturumdaki kullanıcıdan hesap bilgisi (login sonrası session/localStorage'daki user)
    try {
        var userStr = sessionStorage.getItem("user") || localStorage.getItem("user");
        if (userStr) {
            var user = JSON.parse(userStr);
            var sessionCode = user && (user.account_code || "").trim();
            var sessionId = user && (user.account_id != null ? parseInt(user.account_id, 10) : NaN);
            if (sessionCode && /^\d{6}$/.test(sessionCode)) {
                const data = await window.apiClient.get("/api/accounts/by-code/" + encodeURIComponent(sessionCode));
                try {
                    localStorage.setItem("selectedAccountCode", sessionCode);
                    localStorage.setItem("selectedAccountId", String(data.id));
                } catch (e) {}
                return { accountId: data.id, accountCode: data.account_code || sessionCode };
            }
            if (Number.isFinite(sessionId) && sessionId > 0) {
                const data = await window.apiClient.get("/api/accounts/" + sessionId);
                try {
                    localStorage.setItem("selectedAccountId", String(sessionId));
                    if (data.account_code) localStorage.setItem("selectedAccountCode", data.account_code);
                } catch (e) {}
                return { accountId: sessionId, accountCode: data.account_code || null };
            }
        }
    } catch (e) {
        if (typeof window.__DEBUG_DASH__ !== "undefined" && window.__DEBUG_DASH__) console.warn("[dashboard] resolve from session user failed:", e);
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
        if (State.isTestAccount && typeof renderPageErrorLog === 'function') renderPageErrorLog();
        if (State.isTestAccount && typeof isBinanceTabActive === 'function' && isBinanceTabActive() && typeof renderAllSystemErrors === 'function') renderAllSystemErrors();
    } catch (error) {
        const errorMsg = error instanceof window.APIError ? `Dashboard yüklenemedi: ${error.message}` : `Dashboard yüklenemedi: ${error.message || 'Bilinmeyen hata'}`;
        showError(errorMsg, error);
    } finally {
        State.inFlight = false;
    }
}

// Snapshot: single aggregated endpoint - prices, wallet, pnl, bots in one request
const SNAPSHOT_POLL_MS = 5000;

// BOOT_V2: no tab/wallet-idle gating. Always request wallet so cache-only snapshot serves it (mobile + desktop).
function getSnapshotFields() {
    if (typeof isSpotModalOpen === 'function' && isSpotModalOpen()) return 'wallet,prices';
    var activeTab = document.querySelector('.dm-tab.is-active');
    var tabName = activeTab ? activeTab.getAttribute('data-tab') : '';
    if (tabName === 'bots') return 'prices,bots,kpis';
    return 'prices,bots,kpis,wallet';
}

async function fetchSnapshot() {
    if (!State.accountId || State.inFlight || (typeof isSpotModalOpen === 'function' && isSpotModalOpen())) return;
    State.inFlight = true;
    try {
        var fields = getSnapshotFields();
        var url = '/api/dashboard/snapshot?account_id=' + State.accountId + (fields ? '&fields=' + encodeURIComponent(fields) : '');
        const res = await window.apiClient.get(url, { timeout: 12000 });
        const data = (res && res.ok && res.data)
            ? { ...res.data, account: res.data.kpis?.account || res.data.account, pnl: res.data.kpis?.pnl || res.data.pnl }
            : res;
        applySnapshotToUI(data);
    } catch (error) {
        if (window.errorReporter) window.errorReporter.report(error, { tab: 'dashboard', account_id: State.accountId, action: 'fetchSnapshot' });
        console.warn('[dashboard] Snapshot fetch error:', error?.message || error);
    } finally {
        State.inFlight = false;
    }
}

var _botPerformanceLoaded = false;
var _botPerformanceLastPnl = null;
var _botPerformanceLastRange = '';
var _botPerformanceLastPeriod = null;
async function loadBotPerformance(period) {
    if (!State.accountId || !window.apiClient) return;
    period = (period || 'all').toLowerCase();
    if (!['daily', 'weekly', 'monthly', 'all'].includes(period)) period = 'all';
    State.botPerformancePeriod = period;
    var requestedPeriod = period;
    var pnlEl = document.getElementById('botPerformancePnl');
    var rangeEl = document.getElementById('botPerformanceRange');
    var pnlElBots = document.getElementById('botPerformancePnlBots');
    var rangeElBots = document.getElementById('botPerformanceRangeBots');
    var updateEls = function (pnlUsd, dateFrom, dateTo, isTotal, forPeriod) {
        if (forPeriod !== State.botPerformancePeriod) return; /* race: sadece seçili periyotun yanıtını uygula */
        var s = (pnlUsd >= 0 ? '+' : '') + '$' + (typeof pnlUsd === 'number' ? pnlUsd.toFixed(2) : '0.00');
        var range = (dateFrom && dateTo && dateFrom !== '—') ? (dateFrom + ' – ' + dateTo) : '';
        var periodChanged = _botPerformanceLastPeriod !== forPeriod;
        if (!periodChanged && _botPerformanceLastPnl === pnlUsd && _botPerformanceLastRange === range) return; /* flicker önle: periyot aynı ve değer aynıysa DOM güncelleme */
        var rangeToShow = (range && range.length) ? range : _botPerformanceLastRange;
        _botPerformanceLastPnl = pnlUsd;
        _botPerformanceLastRange = range;
        _botPerformanceLastPeriod = forPeriod;
        if (pnlEl) { pnlEl.textContent = s; pnlEl.className = 'bot-perf-pnl' + (pnlUsd >= 0 ? ' positive' : ' negative'); }
        if (rangeEl) rangeEl.textContent = rangeToShow;
        if (pnlElBots) { pnlElBots.textContent = s; pnlElBots.className = 'bot-perf-pnl' + (pnlUsd >= 0 ? ' positive' : ' negative'); }
        if (rangeElBots) rangeElBots.textContent = rangeToShow;
    };
    try {
        var res = await window.apiClient.get('/api/accounts/' + State.accountId + '/bot-performance?period=' + encodeURIComponent(period));
        var d = (res && (res.data || typeof res.pnl_usd === 'number')) ? (res.data || res) : null;
        if (d && typeof d.pnl_usd === 'number') {
            updateEls(d.pnl_usd, d.date_from || '', d.date_to || '', false, requestedPeriod);
        } else {
            updateEls(0, '', '', false, requestedPeriod);
        }
    } catch (e) {
        if (window.errorReporter) window.errorReporter.report(e, { tab: 'dashboard', account_id: State.accountId, action: 'loadBotPerformance' });
        updateEls(0, '', '', false, requestedPeriod);
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

/** Bot detay stateHeroMetaDur ile aynı format ve UTC kaynak. */
function formatLeaderboardRunningDuration(runningSinceIso) {
    var norm = normalizeRunningSinceIso(runningSinceIso);
    if (!norm) return '—';
    try {
        var d = new Date(norm);
        if (isNaN(d.getTime())) return '—';
        var sec = Math.max(0, Math.floor((Date.now() - d.getTime()) / 1000));
        var h = Math.floor(sec / 3600);
        var m = Math.floor((sec % 3600) / 60);
        var s = sec % 60;
        if (h > 0) return h + 's ' + m + 'dk';
        if (m > 0) return m + 'dk ' + s + 'sn';
        return s + 'sn';
    } catch (e) { return '—'; }
}

function formatLeaderboardTotalPnl(item) {
    var pnl = item && item.total_pnl_usd != null ? Number(item.total_pnl_usd) : null;
    if (pnl == null || !Number.isFinite(pnl)) {
        var pct = item && item.profit_pct != null ? Number(item.profit_pct) : 0;
        pnl = 0;
        if (!Number.isFinite(pct)) pct = 0;
    }
    return {
        text: typeof fmtSignedUsd === 'function' ? fmtSignedUsd(pnl) : ((pnl >= 0 ? '+' : '') + '$' + Math.abs(pnl).toFixed(2)),
        color: pnl >= 0 ? '#0ecb81' : '#f6465d'
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
var LEADERBOARD_EMPTY_HTML = '<div style="text-align: center; color: var(--ds-text-secondary); font-size: 0.9rem; padding: 1rem;">Henüz listelenecek aktif bot yok. Bu sıralama yalnızca çalışan ve toplam K/Z\'si sıfır veya pozitif olan botları gösterir.</div>';
var LEADERBOARD_LOADING_HTML = '<div style="text-align: center; color: var(--ds-text-secondary); padding: 1rem;">Yükleniyor…</div>';

var LEADERBOARD_PARAM_LABELS = {
    symbol: 'Sembol',
    trail_pct: 'Trail %',
    up_trail_pct: 'Yukarı trail %',
    down_trail_pct: 'Aşağı trail %',
    grid_count: 'Grid sayısı',
    base_alloc_pct: 'Base dağılım %',
    quote_alloc_pct: 'Quote dağılım %',
    structure_id: 'Yapı',
    strategy_id: 'Strateji'
};
var LEADERBOARD_PARAM_SKIP_KEYS = { budget_usd: 1, bot_budget_quote: 1, initial_capital_usdt: 1 };

function stripLeaderboardBudgetFromParams(params) {
    if (!params || typeof params !== 'object') return params;
    var p = Object.assign({}, params);
    delete p.initial_capital_usdt;
    delete p.budget_usd;
    delete p.bot_budget_quote;
    return p;
}

function formatLeaderboardParamsForDisplay(params) {
    if (!params || typeof params !== 'object') return '<p class="muted">Parametre yok.</p>';
    var parts = [];
    function row(label, val) {
        var valStr = val === null || val === undefined ? '—' : (Array.isArray(val) ? JSON.stringify(val) : (typeof val === 'number' ? (Number.isInteger(val) ? String(val) : val.toFixed(4)) : String(val)));
        if (typeof escapeHtml === 'function') valStr = escapeHtml(valStr);
        var lab = (typeof escapeHtml === 'function' ? escapeHtml(label) : label);
        return '<div class="leaderboard-param-row"><span class="leaderboard-param-label">' + lab + '</span><span class="leaderboard-param-value">' + valStr + '</span></div>';
    }
    function gridTable(grids, title) {
        if (!Array.isArray(grids) || !grids.length) return '';
        var rows = grids.map(function (g) {
            var tr = (g.trigger_pct != null ? g.trigger_pct + '%' : '—');
            var qty = (g.qty_pct != null ? g.qty_pct + '%' : '—');
            return '<tr><td>' + (typeof escapeHtml === 'function' ? escapeHtml(String(tr)) : tr) + '</td><td>' + (typeof escapeHtml === 'function' ? escapeHtml(String(qty)) : qty) + '</td></tr>';
        }).join('');
        return (title ? '<div class="leaderboard-param-section-title">' + (typeof escapeHtml === 'function' ? escapeHtml(title) : title) + '</div>' : '') + '<table class="leaderboard-param-grid-table"><thead><tr><th>Tetik %</th><th>Miktar %</th></tr></thead><tbody>' + rows + '</tbody></table>';
    }
    Object.keys(params).forEach(function (k) {
        if (LEADERBOARD_PARAM_SKIP_KEYS[k] || k === 'up' || k === 'down') return;
        var v = params[k];
        if (v !== null && v !== undefined && typeof v === 'object' && !Array.isArray(v) && v.constructor === Object) return;
        var label = LEADERBOARD_PARAM_LABELS[k] || k;
        parts.push(row(label, v));
    });
    if (params.up && typeof params.up === 'object') {
        parts.push('<div class="leaderboard-param-section"><div class="leaderboard-param-section-title">Yukarı (satış) grid</div>');
        if (params.up.trail_pct != null) parts.push(row('Trail %', params.up.trail_pct));
        parts.push(gridTable(params.up.grids || [], ''));
        parts.push('</div>');
    }
    if (params.down && typeof params.down === 'object') {
        parts.push('<div class="leaderboard-param-section"><div class="leaderboard-param-section-title">Aşağı (alım) grid</div>');
        if (params.down.trail_pct != null) parts.push(row('Trail %', params.down.trail_pct));
        parts.push(gridTable(params.down.grids || [], ''));
        parts.push('</div>');
    }
    return parts.length ? parts.join('') : '<p class="muted">Parametre yok.</p>';
}

function leaderboardParamsHasDetail(params) {
    if (!params || typeof params !== 'object') return false;
    if (Array.isArray(params.sell_grids) && params.sell_grids.length) return true;
    if (Array.isArray(params.buy_grids) && params.buy_grids.length) return true;
    var up = params.up && typeof params.up === 'object' ? params.up : {};
    var down = params.down && typeof params.down === 'object' ? params.down : {};
    return (Array.isArray(up.grids) && up.grids.length) || (Array.isArray(down.grids) && down.grids.length);
}

async function resolveLeaderboardItemForModal(itemIndex) {
    var idx = itemIndex != null && itemIndex !== '' ? parseInt(itemIndex, 10) : NaN;
    var item = Number.isFinite(idx) && State.leaderboardItems ? State.leaderboardItems[idx] : null;
    if (item && leaderboardParamsHasDetail(item.params || {})) return item;
    if (window.apiClient) {
        try {
            var res = await window.apiClient.get('/api/leaderboard/global/top?limit=5');
            var items = (res && Array.isArray(res.items)) ? res.items
                : (res && res.data && Array.isArray(res.data.items)) ? res.data.items
                : [];
            if (items.length) {
                State.leaderboardItems = items;
                if (Number.isFinite(idx) && items[idx]) return items[idx];
            }
        } catch (e) {}
    }
    return item;
}

function closeParametrelerModal() {
    var modal = document.getElementById('parametrelerModal');
    if (modal) modal.style.display = 'none';
    document.body.style.overflow = '';
}

function initParametrelerModalHandlers() {
    if (initParametrelerModalHandlers._done) return;
    initParametrelerModalHandlers._done = true;
    var modal = document.getElementById('parametrelerModal');
    var closeBtn = document.getElementById('parametrelerModalClose');
    var kapatBtn = document.getElementById('parametrelerModalKapat');
    if (closeBtn) closeBtn.onclick = closeParametrelerModal;
    if (kapatBtn) kapatBtn.onclick = closeParametrelerModal;
    if (modal) {
        modal.onclick = function (e) {
            if (e.target === modal) closeParametrelerModal();
        };
    }
}

async function openLeaderboardParamsModal(rank, structureName, params, createdAtIso, referencePrice, itemIndex) {
    initParametrelerModalHandlers();
    var modal = document.getElementById('parametrelerModal');
    var bodyEl = document.getElementById('configGrid');
    if (!modal || !bodyEl) return;
    bodyEl.innerHTML = '<p class="param-hint">Yükleniyor…</p>';
    modal.style.display = 'flex';
    document.body.style.overflow = 'hidden';

    var item = await resolveLeaderboardItemForModal(itemIndex);
    var resolved = stripLeaderboardBudgetFromParams(item
        ? normalizeLeaderboardParamsToFormConfig(item.params || {})
        : normalizeLeaderboardParamsToFormConfig(resolveLeaderboardItemParams(params, itemIndex)));
    if (item && item.symbol && !resolved.symbol) resolved.symbol = item.symbol;
    var symbol = (item && item.symbol) || resolved.symbol || (params && params.symbol) || '';
    var ref = referencePrice != null && !isNaN(referencePrice) ? referencePrice
        : (item && item.reference_price != null && !isNaN(Number(item.reference_price)) ? Number(item.reference_price) : null);
    if (ref == null && resolved.reference_price != null && !isNaN(Number(resolved.reference_price))) {
        ref = Number(resolved.reference_price);
    }

    bodyEl.innerHTML = renderBotParamsConfig(resolved, symbol, ref, true);
}

window.openLeaderboardParamsModal = openLeaderboardParamsModal;
window.closeParametrelerModal = closeParametrelerModal;

function buildGlobalLeaderboardStructureSignature(items) {
    if (!Array.isArray(items)) return '';
    return items.map(function (item, index) {
        var params = normalizeLeaderboardParamsToFormConfig(item.params || {});
        return index + ':' + (item.structure_id || '') + ':' + (item.symbol || '') + ':' + JSON.stringify(params);
    }).join('|');
}

function buildGlobalLeaderboardItemHtml(item, index) {
    var structureId = (item.structure_id || 'trailing_dca').toLowerCase();
    var structure = typeof BOT_STRUCTURES !== 'undefined' ? BOT_STRUCTURES.find(function (s) { return s.id === structureId; }) : null;
    var structureName = structure ? structure.name : structureId;
    var pnlMeta = formatLeaderboardTotalPnl(item);
    var params = stripLeaderboardBudgetFromParams(normalizeLeaderboardParamsToFormConfig(item.params || {}));
    if (item.reference_price != null && params.reference_price == null) {
        params.reference_price = item.reference_price;
    }
    var symbolRaw = item.symbol || params.symbol || '';
    var symbolStr = (typeof symbolRaw === 'string' ? symbolRaw : '').trim() || '—';
    var logoUrl = (typeof getCoinLogoUrl === 'function' ? getCoinLogoUrl(symbolStr) : null);
    var symbolLogoHtml = logoUrl
        ? '<img src="' + (typeof escapeHtml === 'function' ? escapeHtml(logoUrl) : logoUrl) + '" alt="" class="global-leaderboard-symbol-logo" />'
        : '<span class="global-leaderboard-symbol-initials">' + (symbolStr.length >= 2 ? (typeof escapeHtml === 'function' ? escapeHtml(symbolStr.substring(0, 2)) : symbolStr.substring(0, 2)) : '—') + '</span>';
    var runningSinceNorm = normalizeRunningSinceIso(item.running_since_iso || '');
    var runningStr = formatLeaderboardRunningDuration(runningSinceNorm);
    var paramsJsonAttr = JSON.stringify(params).replace(/"/g, '&quot;');
    var refPrice = item.reference_price != null ? String(item.reference_price) : '';
    var structureNameAttr = (typeof escapeHtml === 'function' ? escapeHtml(structureName) : structureName).replace(/"/g, '&quot;');
    var applyBtnHtml = structure ? '<button type="button" class="btn btn-sm global-leaderboard-apply-btn" data-structure-id="' + (typeof escapeHtml === 'function' ? escapeHtml(structureId) : structureId) + '" data-params="' + paramsJsonAttr + '">Uygula</button>' : '';
    var viewParamsBtnHtml = '<button type="button" class="btn btn-sm global-leaderboard-view-params-btn" data-params="' + paramsJsonAttr + '" data-structure-name="' + structureNameAttr + '" data-rank="' + (index + 1) + '" data-reference-price="' + refPrice.replace(/"/g, '&quot;') + '">Parametreleri görüntüle</button>';
    return '<div class="global-leaderboard-item" data-item-index="' + index + '" data-running-since="' + runningSinceNorm.replace(/"/g, '&quot;') + '">' +
        '<div class="global-leaderboard-item-main">' +
        '<div class="global-leaderboard-item-head">' +
        '<div class="global-leaderboard-symbol-wrap">' + symbolLogoHtml + '<span class="global-leaderboard-symbol-name">' + (typeof escapeHtml === 'function' ? escapeHtml(symbolStr) : symbolStr) + '</span></div>' +
        '<span class="global-leaderboard-rank-name">' + (index + 1) + '. ' + (typeof escapeHtml === 'function' ? escapeHtml(structureName) : structureName) + '</span>' +
        '<span class="global-leaderboard-pct" style="color:' + pnlMeta.color + '">' + pnlMeta.text + '</span>' +
        '</div>' +
        '<div class="global-leaderboard-item-duration">Çalışma süresi: ' + runningStr + '</div>' +
        '</div>' +
        '<div class="global-leaderboard-item-actions">' + viewParamsBtnHtml + applyBtnHtml + '</div>' +
        '</div>';
}

function parseLeaderboardParamsFromAttr(raw) {
    if (!raw) return null;
    try {
        return JSON.parse(raw);
    } catch (e1) {
        try {
            return JSON.parse(raw.replace(/&quot;/g, '"').replace(/&amp;/g, '&').replace(/&lt;/g, '<'));
        } catch (e2) {
            return null;
        }
    }
}

function bindGlobalLeaderboardItemActions(listEl) {
    if (!listEl || listEl.dataset.leaderboardActionsBound === '1') return;
    listEl.dataset.leaderboardActionsBound = '1';
    listEl.addEventListener('click', function (e) {
        var applyBtn = e.target.closest('.global-leaderboard-apply-btn');
        if (applyBtn && listEl.contains(applyBtn)) {
            e.preventDefault();
            var sid = applyBtn.getAttribute('data-structure-id');
            var paramsJson = applyBtn.getAttribute('data-params');
            if (!sid || !paramsJson) return;
            var params = parseLeaderboardParamsFromAttr(paramsJson);
            if (!params) return;
            var structure = typeof BOT_STRUCTURES !== 'undefined' ? BOT_STRUCTURES.find(function (s) { return s.id === sid; }) : null;
            var itemRow = applyBtn.closest('.global-leaderboard-item');
            var itemIdx = itemRow ? itemRow.getAttribute('data-item-index') : null;
            if (structure && typeof applyLeaderboardParams === 'function') applyLeaderboardParams(structure, params, itemIdx);
            return;
        }
        var viewBtn = e.target.closest('.global-leaderboard-view-params-btn');
        if (!viewBtn || !listEl.contains(viewBtn)) return;
        e.preventDefault();
        var paramsJson = viewBtn.getAttribute('data-params');
        var structureName = viewBtn.getAttribute('data-structure-name') || 'Bot';
        var rank = viewBtn.getAttribute('data-rank') || '';
        var refRaw = viewBtn.getAttribute('data-reference-price');
        var refPrice = refRaw !== '' && refRaw != null ? Number(refRaw) : null;
        if (!paramsJson) return;
        var params = parseLeaderboardParamsFromAttr(paramsJson);
        if (!params) return;
        var itemRow = viewBtn.closest('.global-leaderboard-item');
        var itemIdx = itemRow ? itemRow.getAttribute('data-item-index') : null;
        params = resolveLeaderboardItemParams(params, itemIdx);
        var lbItem = (itemIdx != null && itemIdx !== '' && State.leaderboardItems)
            ? State.leaderboardItems[parseInt(itemIdx, 10)]
            : null;
        if (refPrice == null && lbItem && lbItem.reference_price != null) refPrice = Number(lbItem.reference_price);
        if (refPrice == null && params.reference_price != null) refPrice = Number(params.reference_price);
        if (typeof openLeaderboardParamsModal === 'function') {
            openLeaderboardParamsModal(rank, structureName, params, null, refPrice, itemIdx);
        }
    });
}

function patchGlobalLeaderboardMetrics(items) {
    var listEl = document.getElementById('globalLeaderboardList');
    if (!listEl || !Array.isArray(items) || !items.length) return;
    State.leaderboardItems = items;
    items.forEach(function (item, index) {
        var row = listEl.querySelector('.global-leaderboard-item[data-item-index="' + index + '"]');
        if (!row) return;
        var pnlEl = row.querySelector('.global-leaderboard-pct');
        var durEl = row.querySelector('.global-leaderboard-item-duration');
        var pnlMeta = formatLeaderboardTotalPnl(item);
        if (pnlEl) {
            pnlEl.textContent = pnlMeta.text;
            pnlEl.style.color = pnlMeta.color;
        }
        if (durEl) {
            var isoNorm = normalizeRunningSinceIso(item.running_since_iso || row.getAttribute('data-running-since'));
            durEl.textContent = 'Çalışma süresi: ' + formatLeaderboardRunningDuration(isoNorm);
        }
        if (item.running_since_iso) row.setAttribute('data-running-since', normalizeRunningSinceIso(item.running_since_iso));
        var params = stripLeaderboardBudgetFromParams(normalizeLeaderboardParamsToFormConfig(item.params || {}));
        if (item.symbol && !params.symbol) params.symbol = item.symbol;
        var paramsJson = JSON.stringify(params);
        row.querySelectorAll('.global-leaderboard-apply-btn, .global-leaderboard-view-params-btn').forEach(function (btn) {
            btn.setAttribute('data-params', paramsJson);
        });
    });
}

function startGlobalLeaderboardPoll() {
    if (!window.intervalRegistry) return;
    window.intervalRegistry.stop('dashboard.leaderboard');
    window.intervalRegistry.stop('dashboard.leaderboard.duration');
    window.intervalRegistry.start('dashboard.leaderboard', function () {
        if (State.accountId && typeof loadGlobalLeaderboard === 'function') loadGlobalLeaderboard(true);
    }, 5000, 'dashboard');
    window.intervalRegistry.start('dashboard.leaderboard.duration', function () {
        var listEl = document.getElementById('globalLeaderboardList');
        if (!listEl || State.leaderboardLastState !== 'items') return;
        listEl.querySelectorAll('.global-leaderboard-item').forEach(function (row) {
            var durEl = row.querySelector('.global-leaderboard-item-duration');
            var iso = normalizeRunningSinceIso(row.getAttribute('data-running-since'));
            if (durEl && iso) durEl.textContent = 'Çalışma süresi: ' + formatLeaderboardRunningDuration(iso);
        });
    }, 1000, 'dashboard');
}

async function loadGlobalLeaderboard(patchOnly) {
    var panel = document.getElementById('globalLeaderboardPanel');
    var listEl = document.getElementById('globalLeaderboardList');
    if (!listEl || !window.apiClient) return;
    bindGlobalLeaderboardItemActions(listEl);
    if (panel) panel.style.display = 'block';
    var lastState = State.leaderboardLastState || 'idle';
    if (lastState !== 'empty' && lastState !== 'error' && lastState !== 'items') {
        if (listEl.innerHTML !== LEADERBOARD_LOADING_HTML) {
            listEl.innerHTML = LEADERBOARD_LOADING_HTML;
            State.leaderboardLastState = 'loading';
        }
    }
    try {
        var res = await window.apiClient.get('/api/leaderboard/global/top?limit=5');
        var items = (res && Array.isArray(res.items)) ? res.items
            : (res && res.data && Array.isArray(res.data.items)) ? res.data.items
            : [];
        if (!items.length) {
            if (!patchOnly) {
                if (State.leaderboardLastState !== 'empty' || listEl.innerHTML !== LEADERBOARD_EMPTY_HTML) {
                    State.leaderboardLastState = 'empty';
                    State.leaderboardLastHtml = null;
                    State.leaderboardItems = [];
                    listEl.innerHTML = LEADERBOARD_EMPTY_HTML;
                }
            }
            if (window.intervalRegistry) window.intervalRegistry.stop('dashboard.leaderboard');
            return;
        }
        State.leaderboardItems = items;
        var structureSig = buildGlobalLeaderboardStructureSignature(items);
        if (patchOnly && State.leaderboardLastState === 'items') {
            if (State.leaderboardStructureSig && State.leaderboardStructureSig !== structureSig) {
                patchOnly = false;
            } else {
                patchGlobalLeaderboardMetrics(items);
                return;
            }
        }
        var html = '';
        items.forEach(function (item, index) {
            html += buildGlobalLeaderboardItemHtml(item, index);
        });
        if (!State.leaderboardStructureSig || State.leaderboardStructureSig !== structureSig) {
            State.leaderboardLastState = 'items';
            State.leaderboardLastHtml = html;
            State.leaderboardStructureSig = structureSig;
            listEl.innerHTML = html;
            bindGlobalLeaderboardItemActions(listEl);
        } else {
            patchGlobalLeaderboardMetrics(items);
        }
        startGlobalLeaderboardPoll();
    } catch (e) {
        if (window.errorReporter) window.errorReporter.report(e, { tab: 'dashboard', action: 'loadGlobalLeaderboard' });
        if (!patchOnly) {
            if (State.leaderboardLastState !== 'error' || listEl.innerHTML !== LEADERBOARD_EMPTY_HTML) {
                State.leaderboardLastState = 'error';
                State.leaderboardLastHtml = null;
                State.leaderboardItems = [];
                listEl.innerHTML = LEADERBOARD_EMPTY_HTML;
            }
        }
    }
}
window.loadGlobalLeaderboard = loadGlobalLeaderboard;

State.txHistoryPeriod = State.txHistoryPeriod || 'daily';
State.txHistoryType = State.txHistoryType || 'buysell';
State.txHistoryPage = State.txHistoryPage || 1;

async function loadTransactionHistory(period, typeFilter, page, sync) {
    if (!State.accountId || !window.apiClient) return;
    var listEl = document.getElementById('txHistoryList');
    var paginationEl = document.getElementById('txHistoryPagination');
    if (!listEl) return;
    var txHistoryRequestDone = false;
    var loadingTimer = setTimeout(function () {
        if (txHistoryRequestDone) return;
        listEl.innerHTML = '<div class="tx-history-loading" style="text-align:center;padding:2rem;color:var(--ds-text-secondary);">Yükleniyor...</div>';
    }, 200);
    if (paginationEl) paginationEl.innerHTML = '';
    State.txHistoryPeriod = period;
    State.txHistoryType = typeFilter;
    State.txHistoryPage = page;
    var q = '/api/accounts/' + State.accountId + '/transaction-history?period=' + encodeURIComponent(period) + '&type_filter=' + encodeURIComponent(typeFilter) + '&page=' + page + (sync ? '&sync=1' : '');
    try {
        var res = await window.apiClient.get(q);
        txHistoryRequestDone = true;
        clearTimeout(loadingTimer);
        var d = res && (res.data || res);
        if (!d || !Array.isArray(d.items)) {
            listEl.innerHTML = '<div class="tx-history-empty" style="text-align:center;padding:2rem;color:var(--ds-text-secondary);">İşlem bulunamadı.</div>';
            return;
        }
        var items = d.items;
        var total = d.total || 0;
        var totalPages = d.total_pages || 1;
        if (items.length === 0) {
            listEl.innerHTML = '<div class="tx-history-empty" style="text-align:center;padding:2rem;color:var(--ds-text-secondary);">Bu filtrede işlem bulunamadı.</div>';
        } else {
            function fmtQtyShort(n) {
                if (n == null || !Number.isFinite(n)) return '—';
                var s = Number(n).toFixed(8).replace(/\.?0+$/, '');
                return s || '0';
            }
            var html = items.map(function (tx) {
                var timeStr = tx.time ? new Date(tx.time).toLocaleString('tr-TR', { dateStyle: 'short', timeStyle: 'short' }) : '—';
                var typeLabel = tx.type_label || (tx.type === 'buy' ? 'Alım' : tx.type === 'sell' ? 'Satım' : tx.type === 'deposit' ? 'Yatırım' : tx.type === 'withdraw' ? 'Çekim' : '—');
                var typeClass = tx.type === 'buy' ? 'tx-type-buy' : tx.type === 'sell' ? 'tx-type-sell' : tx.type === 'deposit' ? 'tx-type-deposit' : tx.type === 'withdraw' ? 'tx-type-withdraw' : '';
                var qtyStr = fmtQtyShort(tx.qty);
                var priceStr = tx.price != null && tx.price > 0 ? (typeof fmtCoinPrice === 'function' ? fmtCoinPrice(tx.price) : '$' + Number(tx.price).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 8 })) : '—';
                var totalVal = tx.quote_qty != null && tx.quote_qty > 0 ? (typeof fmtUsd === 'function' ? fmtUsd(tx.quote_qty) : '$' + tx.quote_qty) : (tx.type === 'deposit' || tx.type === 'withdraw' ? qtyStr + ' ' + (tx.symbol || '') : '—');
                var sourceLabel = tx.source_label || (tx.source === 'bot' ? 'Bot' : tx.source === 'spot' ? 'Spot' : '—');
                var platformLabel = (tx.platform && String(tx.platform)) || (tx.bot_id || tx.source === 'bot' ? 'TradeTrailing' : 'Binance');
                var metaRight = (tx.type === 'buy' || tx.type === 'sell') ? ('Miktar ' + qtyStr + ' · Fiyat ' + priceStr) : (qtyStr + (tx.symbol ? ' ' + tx.symbol : ''));
                return '<div class="tx-history-item" data-tx=\'' + JSON.stringify(tx).replace(/'/g, "\\'") + '\' role="button" tabindex="0">' +
                    '<div class="tx-history-item-left">' +
                    '<div class="tx-history-item-title"><span class="' + typeClass + '">' + typeLabel + '</span> ' + (tx.symbol || '') + '</div>' +
                    '<div class="tx-history-item-meta">' + timeStr + ' · ' + sourceLabel + ' · ' + platformLabel + (tx.bot_name ? ' · ' + tx.bot_name : '') + '</div>' +
                    '</div>' +
                    '<div class="tx-history-item-right">' +
                    '<div class="tx-history-item-total">' + totalVal + '</div>' +
                    '<div class="tx-history-item-meta">' + metaRight + '</div>' +
                    '</div></div>';
            }).join('');
            listEl.innerHTML = '<div class="tx-history-items">' + html + '</div>';
            listEl.querySelectorAll('.tx-history-item').forEach(function (el) {
                el.onclick = function () {
                    try {
                        var tx = JSON.parse(el.getAttribute('data-tx'));
                        if (typeof openTxDetailModal === 'function') openTxDetailModal(tx);
                    } catch (e) {}
                };
            });
        }
        if (paginationEl && totalPages > 1) {
            var pg = '';
            if (page > 1) pg += '<button type="button" class="btn btn-sm tx-pg-btn" data-page="' + (page - 1) + '">← Önceki</button>';
            pg += '<span style="margin:0 0.5rem;font-size:0.9rem;color:var(--ds-text-secondary);">Sayfa ' + page + ' / ' + totalPages + '</span>';
            if (page < totalPages) pg += '<button type="button" class="btn btn-sm tx-pg-btn" data-page="' + (page + 1) + '">Sonraki →</button>';
            paginationEl.innerHTML = pg;
            paginationEl.querySelectorAll('.tx-pg-btn').forEach(function (btn) {
                btn.onclick = function () {
                    var p = parseInt(btn.getAttribute('data-page'), 10);
                    if (typeof loadTransactionHistory === 'function') loadTransactionHistory(State.txHistoryPeriod, State.txHistoryType, p, false);
                };
            });
        }
        document.querySelectorAll('.tx-period-btn').forEach(function (b) { b.classList.toggle('active', b.getAttribute('data-period') === period); });
        document.querySelectorAll('.tx-type-btn').forEach(function (b) { b.classList.toggle('active', b.getAttribute('data-type') === typeFilter); });
    } catch (e) {
        txHistoryRequestDone = true;
        clearTimeout(loadingTimer);
        if (window.errorReporter) window.errorReporter.report(e, { account_id: State.accountId, action: 'loadTransactionHistory' });
        listEl.innerHTML = '<div class="tx-history-error" style="text-align:center;padding:2rem;color:var(--ds-loss,#f6465d);">Yüklenemedi.</div>';
    }
}
window.loadTransactionHistory = loadTransactionHistory;

function openTxDetailModal(tx) {
    var modal = document.getElementById('txDetailModal');
    if (!modal) return;
    var timeStr = tx.time ? new Date(tx.time).toLocaleString('tr-TR', { dateStyle: 'medium', timeStyle: 'medium' }) : '—';
    var typeLabel = tx.type_label || (tx.type === 'buy' ? 'Alım' : tx.type === 'sell' ? 'Satım' : tx.type === 'deposit' ? 'Yatırım' : tx.type === 'withdraw' ? 'Çekim' : '—');
    var qty = tx.qty != null ? (typeof fmtNum === 'function' ? fmtNum(tx.qty, 8) : Number(tx.qty).toFixed(4)) : '—';
    var price = tx.price != null && tx.price > 0 ? (typeof fmtCoinPrice === 'function' ? fmtCoinPrice(tx.price) : '$' + tx.price) : '—';
    var totalVal = tx.quote_qty != null && tx.quote_qty > 0 ? (typeof fmtUsd === 'function' ? fmtUsd(tx.quote_qty) : '$' + tx.quote_qty) : (tx.type === 'deposit' || tx.type === 'withdraw' ? qty + ' ' + (tx.symbol || '') : '—');
    var comm = tx.commission != null && tx.commission > 0 ? (tx.commission_asset ? (typeof fmtNum === 'function' ? fmtNum(tx.commission, 8) : tx.commission) + ' ' + tx.commission_asset : (typeof fmtUsd === 'function' ? fmtUsd(tx.commission) : tx.commission)) : '0';
    patchText('txDetailTime', timeStr);
    patchText('txDetailType', typeLabel);
    patchText('txDetailSymbol', tx.symbol || '—');
    patchText('txDetailQty', qty);
    patchText('txDetailPrice', price !== '—' ? price : '—');
    patchText('txDetailTotal', totalVal);
    patchText('txDetailCommission', comm);
    patchText('txDetailSource', tx.source_label || (tx.source === 'bot' ? 'Bot' : tx.source === 'spot' ? 'Spot' : '—'));
    patchText('txDetailPlatform', tx.platform || (tx.bot_id || tx.source === 'bot' ? 'TradeTrailing' : 'Binance'));
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
                miniData[sym] = { last: p || 0, open: p || 0, changePct: d.change24h || 0, volume: d.volume24h || 0, quoteVolume: (d.volume24h || 0) * (p || 0), marketCap: 0 };
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
        normalizeAndApplyWallet(w, { source: 'dashboard_snapshot', request_id: meta.request_id || w._request_id });
        if (window.__walletDebugMeta === undefined) window.__walletDebugMeta = {};
        window.__walletDebugMeta.wallet_source = meta.wallet_source;
        window.__walletDebugMeta.wallet_age_sec = meta.wallet_age_sec;
        window.__walletDebugMeta.request_id = meta.request_id;
    }
    if (data.pnl && typeof data.pnl === 'object' && !data.pnl._error) {
        var spotUsd = (data.wallet && typeof data.wallet.total_usd === 'number' && data.wallet.total_usd >= 0) ? data.wallet.total_usd : (State.summary && State.summary.account && typeof State.summary.account.spot_balance_usd === 'number' ? State.summary.account.spot_balance_usd : (typeof (assetsState && assetsState.wallet && assetsState.wallet.total_usd) === 'number' ? assetsState.wallet.total_usd : 0));
        if (data.bots && Array.isArray(data.bots)) {
            State.bots = hydrateBotsWithMetricsCache(data.bots);
            resetFinanceBotsLiveCache(State.bots);
        }
        const merged = { ...data.pnl, binance_balance_usd: spotUsd, spot_balance_usd: spotUsd, free_usd: data.wallet?.free_usd ?? 0, locked_usd: data.wallet?.locked_usd ?? 0, available_usd: data.wallet?.available_usd ?? 0, bot_locked_usd: data.wallet?.bot_locked_usd ?? 0, account: data.account || {}, bots: data.bots || State.bots, bot_summary: data.pnl.bot_summary || [] };
        if (typeof updateFinanceKPIs === 'function') updateFinanceKPIs(merged);
    }
    if (data.bots && Array.isArray(data.bots) && data.account) {
        State.bots = hydrateBotsWithMetricsCache(data.bots);
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
        if (typeof renderBotsList === 'function') renderBotsList(State.bots);
        if (typeof updateKPIs === 'function') updateKPIs(summaryShape);
        if (typeof updateAccountName === 'function') updateAccountName(data.account.name || "Hesap Dashboard");
        if (typeof setAppbarAccountHolderName === 'function') setAppbarAccountHolderName(summaryShape);
        hideError();
        if (State.isTestAccount && typeof renderPageErrorLog === 'function') renderPageErrorLog();
    }
    if (State.accountId && typeof loadBotPerformance === 'function') {
        loadBotPerformance(State.botPerformancePeriod || 'all');
    }
    if (State.accountId && typeof loadGlobalLeaderboard === 'function') {
        loadGlobalLeaderboard();
    }
    if (State.accountId && typeof loadTransactionHistory === 'function') {
        loadTransactionHistory(State.txHistoryPeriod || 'daily', State.txHistoryType || 'buysell', State.txHistoryPage || 1, false);
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

function getCurrentTabKey() {
    var active = document.querySelector('.dm-tab.is-active');
    return (active && active.getAttribute('data-tab')) || 'binance';
}

function renderPageErrorLog() {
    var strip = document.getElementById('pageErrorLogStrip');
    var list = document.getElementById('pageErrorLogList');
    if (!strip || !list) return;
    if (typeof State === 'undefined' || !State.isTestAccount) {
        strip.style.display = 'none';
        return;
    }
    strip.style.display = 'block';
    var tab = getCurrentTabKey();
    var errors = (window.errorReporter && window.errorReporter.getPageErrors) ? window.errorReporter.getPageErrors(tab) : [];
    if (errors.length === 0) {
        list.textContent = 'Bu sayfada henüz hata yok.';
        list.style.color = 'var(--ds-text-tertiary)';
    } else {
        list.style.color = 'var(--ds-text-error, #f6465d)';
        list.textContent = errors.map(function(e) {
            var t = e.ts ? new Date(e.ts).toLocaleTimeString('tr-TR') : '';
            return '[' + t + '] ' + (e.message || '').substring(0, 200) + (e.detail ? '\n  ' + String(e.detail).substring(0, 150) : '');
        }).join('\n\n');
    }
    var resetBtn = document.getElementById('pageErrorLogResetBtn');
    if (resetBtn && !resetBtn._bound) {
        resetBtn._bound = true;
        resetBtn.disabled = false;
        resetBtn.onclick = function() {
            var tab = getCurrentTabKey();
            if (window.errorReporter && window.errorReporter.clearPageErrors) window.errorReporter.clearPageErrors(tab);
            var listEl = document.getElementById('pageErrorLogList');
            if (listEl) {
                listEl.textContent = 'Bu sayfada henüz hata yok.';
                listEl.style.color = 'var(--ds-text-tertiary)';
            }
            // Tek güncelleme; renderPageErrorLog() tekrar yazınca flicker oluyordu
        };
    } else if (resetBtn) {
        resetBtn.disabled = false;
    }
}

function renderAllSystemErrors() {
    var block = document.getElementById('allSystemErrorsBlock');
    var list = document.getElementById('allSystemErrorsList');
    if (!block || !list) return;
    if (typeof State === 'undefined' || !State.isTestAccount || !document.getElementById('tabBinance') || !document.getElementById('tabBinance').classList.contains('is-active')) {
        block.style.display = 'none';
        return;
    }
    block.style.display = 'block';
    var parts = [];
    if (window.errorReporter && window.errorReporter.getAllPageErrors) {
        var front = window.errorReporter.getAllPageErrors();
        if (front.length) {
            parts.push('--- Frontend ---');
            front.slice(0, 30).forEach(function(e) {
                var t = e.ts ? new Date(e.ts).toLocaleString('tr-TR') : '';
                parts.push('[' + t + '] ' + (e.message || '').substring(0, 180));
            });
        }
    }
    function setListText(backendParts) {
        var all = parts.concat(backendParts || []);
        list.textContent = all.length ? all.join('\n') : 'Henüz kayıtlı hata yok.';
        list.style.color = all.length ? 'var(--ds-text-error, #f6465d)' : 'var(--ds-text-tertiary)';
    }
    // Use session user's account_id for error-logs so it matches backend (avoids 403 when State.accountId comes from URL/localStorage)
    var accountIdForLogs = State.accountId;
    try {
        var u = sessionStorage.getItem('user') || localStorage.getItem('user');
        if (u) {
            var uu = JSON.parse(u);
            if (uu && uu.account_id != null && Number.isFinite(parseInt(uu.account_id, 10))) accountIdForLogs = parseInt(uu.account_id, 10);
        }
    } catch (e) {}
    if (accountIdForLogs && window.apiClient) {
        window.apiClient.get('/api/error-logs?account_id=' + accountIdForLogs + '&limit=50').then(function(res) {
            var items = (res && res.items) ? res.items : [];
            var backendParts = [];
            if (items.length) {
                backendParts.push('\n--- Backend ---');
                items.forEach(function(e) {
                    backendParts.push('[' + (e.created_at || '').replace('Z', '') + '] ' + (e.message || '').substring(0, 180));
                });
            }
            setListText(backendParts);
        }).catch(function() {
            setListText(['\n--- Backend ---', 'Backend logları yüklenemedi.']);
        });
    } else {
        setListText([]);
    }
    var resetBtn = document.getElementById('allSystemErrorsResetBtn');
    if (resetBtn && !resetBtn._boundAll) {
        resetBtn._boundAll = true;
        resetBtn.disabled = false;
        resetBtn.onclick = function() {
            if (window.errorReporter && window.errorReporter.clearAllPageErrors) window.errorReporter.clearAllPageErrors();
            var listEl = document.getElementById('allSystemErrorsList');
            if (listEl) {
                listEl.textContent = 'Sıfırlanıyor…';
                listEl.style.color = 'var(--ds-text-tertiary)';
            }
            var accountIdForLogs = State.accountId;
            try {
                var u = sessionStorage.getItem('user') || localStorage.getItem('user');
                if (u) {
                    var uu = JSON.parse(u);
                    if (uu && uu.account_id != null && Number.isFinite(parseInt(uu.account_id, 10))) accountIdForLogs = parseInt(uu.account_id, 10);
                }
            } catch (e) {}
            if (accountIdForLogs && window.apiClient) {
                window.apiClient.post('/api/error-logs/clear?account_id=' + accountIdForLogs).then(function() {
                    if (listEl) {
                        listEl.textContent = 'Hatalar sıfırlandı. Yenileyince de boş kalacak.';
                        listEl.style.color = 'var(--ds-text-tertiary)';
                    }
                }).catch(function() {
                    if (listEl) {
                        listEl.textContent = 'Frontend temizlendi. Backend sıfırlama isteği başarısız.';
                        listEl.style.color = 'var(--ds-text-secondary)';
                    }
                });
            } else {
                if (listEl) {
                    listEl.textContent = 'Hatalar sıfırlandı. (Sadece frontend; hesap bilgisi yok.)';
                    listEl.style.color = 'var(--ds-text-tertiary)';
                }
            }
        };
    } else if (resetBtn) {
        resetBtn.disabled = false;
    }
}

function isBotsTabActive() {
    const t = document.getElementById('tabBots');
    return !!(t && t.classList.contains('is-active'));
}

/** Hızlı bot listesi: /api/bots-engine ile hemen listeyi doldurur; summary gelene kadar "Yükleniyor" kalmaz. */
function loadBotsListFast(accountId) {
    if (!accountId || !window.apiClient) return;
    window.apiClient.get('/api/bots-engine?account_id=' + accountId, { timeout: 8000 })
        .then(function(res) {
            // Summary zaten geldiyse (current_usd dahil) onu ezme; sadece henüz veri yoksa doldur
            if (State.summary && Array.isArray(State.summary.bots) && State.summary.bots.length > 0) return;
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
        })
        .catch(function() {
            State.bots = [];
            renderBotsList([]);
            renderFinanceBots([]);
        });
}

function isSpotModalOpen() {
    const m = document.getElementById('bnSpotTradeModal');
    return !!(m && m.style.display !== 'none');
}

// Update UI (patch updates) – account name no longer in appbar (center = company)
function updateAccountName(name) {
    /* reserved */
}

function appbarDisplayNameStorageKey(accountId) {
    return 'appbarDisplayName_' + (accountId || '');
}

function lockAppbarDisplayName(accountId, displayName) {
    if (accountId == null || accountId === '' || !displayName || displayName === '—') return;
    try {
        localStorage.setItem(appbarDisplayNameStorageKey(accountId), String(displayName).trim());
    } catch (e) {}
}

function getLockedAppbarDisplayName(accountId) {
    if (accountId == null || accountId === '') return '';
    try {
        var locked = localStorage.getItem(appbarDisplayNameStorageKey(accountId));
        if (locked && locked !== '—') return locked;
    } catch (e) {}
    return '';
}

function getAppbarDisplayNameFromStoredUser(accountId) {
    try {
        var userStr = sessionStorage.getItem('user') || localStorage.getItem('user');
        if (!userStr) return '';
        var user = JSON.parse(userStr);
        if (accountId != null && user.account_id != null && String(user.account_id) !== String(accountId)) return '';
        return [user.name, user.surname].filter(Boolean).map(function (s) { return String(s).trim(); }).join(' ').trim();
    } catch (e) {
        return '';
    }
}

function ensureAppbarDisplayNameLocked(accountId) {
    var locked = getLockedAppbarDisplayName(accountId);
    if (locked) return locked;
    var fromUser = getAppbarDisplayNameFromStoredUser(accountId);
    if (fromUser) {
        lockAppbarDisplayName(accountId, fromUser);
        return fromUser;
    }
    return '';
}

function getAppbarCachedDisplayName(accountId) {
    var locked = getLockedAppbarDisplayName(accountId);
    if (locked) return locked;
    if (accountId == null || accountId === '') return '';
    try {
        var raw = sessionStorage.getItem('dashboardAppbar_' + accountId);
        if (raw) {
            var cached = JSON.parse(raw);
            if (cached && cached.displayName && cached.displayName !== '—') return cached.displayName;
        }
        var legacy = sessionStorage.getItem('appbarUserName_' + accountId);
        if (legacy && legacy !== '—') return legacy;
    } catch (e) {}
    return '';
}

function resolveAppbarDisplayName(data, accountId) {
    var locked = ensureAppbarDisplayNameLocked(accountId);
    if (locked) return locked;
    data = data || {};
    var acc = data.account || {};
    var first = data.user_name || acc.user_name || '';
    var last = data.user_surname || acc.user_surname || '';
    var fn = [first, last].filter(Boolean).map(function (s) { return String(s).trim(); }).join(' ').trim();
    if (fn) {
        lockAppbarDisplayName(accountId, fn);
        return fn;
    }
    var fromUser = getAppbarDisplayNameFromStoredUser(accountId);
    if (fromUser) {
        lockAppbarDisplayName(accountId, fromUser);
        return fromUser;
    }
    var el = document.getElementById('appbarUserName');
    if (el && el.textContent && el.textContent !== '—') return el.textContent.trim();
    var an = (acc.name || data.account_name || '').trim();
    if (an) return an;
    return '—';
}

function paintAppbarDisplayName(accountId) {
    var nameEl = document.getElementById('appbarUserName');
    if (!nameEl) return '';
    var displayName = ensureAppbarDisplayNameLocked(accountId) || getAppbarCachedDisplayName(accountId);
    if (displayName) setTextIfChanged(nameEl, displayName);
    if (displayName) State.appbarNameAccountId = accountId;
    return displayName || '';
}

function setAppbarAccountHolderName(data) {
    var accountId = State.accountId ?? data.account_id ?? (data.account && data.account.id);
    var accountCode = State.accountCode || (data.account_code ?? (data.account && data.account.account_code));
    var locked = getLockedAppbarDisplayName(accountId);
    var displayName = locked || resolveAppbarDisplayName(data, accountId);
    if (!locked && displayName && displayName !== '—') lockAppbarDisplayName(accountId, displayName);
    paintAppbarDisplayName(accountId);
    const idEl = document.getElementById('appbarAccountId');
    if (idEl) {
        const aid = accountCode != null && accountCode !== '' ? accountCode : (State.accountId ?? data.account_id ?? (data.account && data.account.id));
        var idLabel = aid != null && aid !== '' ? 'ID: ' + aid : 'ID: —';
        setTextIfChanged(idEl, idLabel);
        if (idEl.style.display !== 'block') idEl.style.display = 'block';
    }
    if (displayName && displayName !== '—') persistAppbarSessionCache(accountId, displayName, accountCode);
}

function persistAppbarSessionCache(accountId, displayName, accountCode) {
    if (accountId == null || accountId === '') return;
    try {
        var code = accountCode != null && accountCode !== '' ? String(accountCode) : '';
        var idLabel = code ? ('ID: ' + code) : ('ID: ' + accountId);
        sessionStorage.setItem('dashboardAppbar_' + accountId, JSON.stringify({
            ts: Date.now(),
            displayName: displayName || '',
            accountCode: code,
            idLabel: idLabel
        }));
        if (displayName && displayName !== '—') {
            sessionStorage.setItem('appbarUserName_' + accountId, displayName);
        }
    } catch (e) {}
}

function restoreAppbarFromSessionCache(accountId, accountCode) {
    if (accountId == null || accountId === '') return false;
    var idEl = document.getElementById('appbarAccountId');
    var restored = false;
    paintAppbarDisplayName(accountId);
    if (getLockedAppbarDisplayName(accountId)) restored = true;
    try {
        var raw = sessionStorage.getItem('dashboardAppbar_' + accountId);
        var cached = raw ? JSON.parse(raw) : null;
        if (idEl) {
            var idLabel = (accountCode != null && accountCode !== '')
                ? ('ID: ' + accountCode)
                : ((cached && cached.idLabel) || ('ID: ' + accountId));
            if (setTextIfChanged(idEl, idLabel)) restored = true;
            if (idEl.style.display !== 'block') idEl.style.display = 'block';
        }
    } catch (e) {}
    return restored;
}

function shouldShowAdminNav(user) {
    var fromAdminUrl = new URLSearchParams(window.location.search).get('from_admin') === '1';
    if (fromAdminUrl) {
        try { sessionStorage.setItem('dashboard_from_admin', '1'); } catch (e) {}
    }
    var fromAdminStored = false;
    try { fromAdminStored = sessionStorage.getItem('dashboard_from_admin') === '1'; } catch (e) {}
    return !!(user && user.is_admin) && (fromAdminUrl || fromAdminStored);
}

function patchAdminLinkVisibility(show) {
    var adminLink = document.getElementById('adminLink');
    if (!adminLink) return;
    var target = show ? 'inline-flex' : 'none';
    if (adminLink.style.display !== target) adminLink.style.display = target;
}
window.restoreAppbarFromSessionCache = restoreAppbarFromSessionCache;

/** Değer değişmediyse DOM'a dokunma; flicker önler. Returns true if updated. */
function setTextIfChanged(el, newText) {
    if (!el) return false;
    var s = (newText == null || newText === '') ? '' : String(newText);
    if (el.textContent === s) return false;
    el.textContent = s;
    return true;
}
window.setTextIfChanged = setTextIfChanged;

var _blinkCooldownUntil = 0;
var BLINK_COOLDOWN_MS = 400;

/** Proje geneli blink: bakiye/PnL değişince yeşil/kırmızı. Cooldown ile aynı anda iki blink engellenir. */
function triggerValueBlink(el, newNum) {
    if (!el) return;
    var now = Date.now();
    if (now < _blinkCooldownUntil) return;
    var oldNum = parseFloat(String(el.textContent).replace(/[^0-9.-]/g, '')) || 0;
    if (Math.abs((newNum || 0) - oldNum) < 0.001) return;
    _blinkCooldownUntil = now + BLINK_COOLDOWN_MS;
    el.classList.remove('blink-positive', 'blink-negative');
    void el.offsetWidth;
    if (newNum > oldNum) el.classList.add('blink-positive');
    else el.classList.add('blink-negative');
    setTimeout(function() { el.classList.remove('blink-positive', 'blink-negative'); }, 750);
}
window.triggerValueBlink = triggerValueBlink;

var lastSpotUpdateTs = 0;

function updateDatahubWsIndicator() {
    var el = document.getElementById('datahubWsIndicator');
    if (!el) return;
    if (!window.apiClient || !window.apiClient.hasToken()) return;
    window.apiClient.get('/api/datahub/status', { timeout: 3000 }).then(function (data) {
        if (!data || !el) return;
        var dot = el.querySelector('.datahub-ws-dot');
        var label = el.querySelector('.datahub-ws-label');
        var s = (data.ws_status || 'rest').toLowerCase();
        if (dot) {
            dot.style.backgroundColor = s === 'connected' ? '#0ecb81' : (s === 'stale' ? '#f0b90b' : '#f6465d');
        }
        var titles = { connected: 'WebSocket bağlı', stale: 'WebSocket gecikmeli', rest: 'REST modu (WS yok)' };
        el.title = (titles[s] || 'WS durumu') + ' • ' + (data.total_symbols || 0) + ' sembol';
    }).catch(function () {
        var dot = el && el.querySelector('.datahub-ws-dot');
        if (dot) dot.style.backgroundColor = '#f6465d';
    });
}

function updateKpiCuzdanLiveStatus() {
    var el = document.getElementById("kpiCuzdanLive");
    if (!el) return;
    if (typeof State !== 'undefined' && State.isTestAccount) {
        if (el.textContent !== "Test") el.textContent = "Test";
        return;
    }
    if (assetsState.wallet.keys_configured !== true) {
        if (el.textContent !== "Bağlı değil") el.textContent = "Bağlı değil";
        return;
    }
    if (lastSpotUpdateTs <= 0) {
        if (el.textContent !== "—") el.textContent = "—";
        return;
    }
    var age = Date.now() - lastSpotUpdateTs;
    var THRESHOLD_MS = 30000;
    if (age < THRESHOLD_MS) {
        if (el.textContent !== "Canlı") el.textContent = "Canlı";
    } else {
        var d = new Date(lastSpotUpdateTs);
        var str = "Son: " + d.toLocaleString("tr-TR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });
        if (el.textContent !== str) el.textContent = str;
    }
}

function updateKPIs(data) {
    const account = data.account || {};
    let botsTotal = account.bots_balance_usd != null && Number.isFinite(account.bots_balance_usd) ? account.bots_balance_usd : 0;
    if (botsTotal === 0 && Array.isArray(data.bots) && data.bots.length) {
        const sum = data.bots.reduce(function (acc, b) {
            const cu = b.current_usd != null && Number.isFinite(b.current_usd) ? b.current_usd : 0;
            return acc + cu;
        }, 0);
        if (sum > 0) botsTotal = sum;
    }
    const dailyBotPnl = data.daily_bot_pnl_usd ?? data.daily_pnl_usd ?? 0;
    const dailyWalletPnl = data.daily_wallet_pnl_usd ?? 0;
    const hasDaily = (account.daily_wallet_pnl_usd !== undefined && account.daily_wallet_pnl_usd !== null) || (account.daily_bot_pnl_usd !== undefined && account.daily_bot_pnl_usd !== null);
    // Avoid flashing to 0 when Binance/wallet temporarily fails: use last-known spot from state
    const walletTotal = (account.spot_balance_usd != null && Number(account.spot_balance_usd) > 0) ? Number(account.spot_balance_usd) : (typeof (assetsState && assetsState.wallet && assetsState.wallet.total_usd) === 'number' ? assetsState.wallet.total_usd : 0);

    var walletEl = document.getElementById("kpiCuzdan");
    if (walletEl) { setTextIfChanged(walletEl, fmtUsd(walletTotal)); triggerValueBlink(walletEl, walletTotal); }
    lastSpotUpdateTs = Date.now();
    var liveLabel = (typeof State !== 'undefined' && State.isTestAccount) ? "Test" : (assetsState.wallet.keys_configured === true ? "Canlı" : "Bağlı değil");
    if (assetsState.wallet && (assetsState.wallet.data_status === 'stale' || assetsState.wallet.error)) liveLabel = "Güncel değil";
    patchText("kpiCuzdanLive", liveLabel);
    if (hasDaily) {
        var cuzdanPnlEl = document.getElementById("kpiCuzdanPnl");
        if (cuzdanPnlEl) {
            var textChanged = setTextIfChanged(cuzdanPnlEl, fmtUsd(dailyWalletPnl));
            var newColor = dailyWalletPnl >= 0 ? '#0ecb81' : '#f6465d';
            if (cuzdanPnlEl.style.color !== newColor) cuzdanPnlEl.style.color = newColor;
            if (textChanged) triggerValueBlink(cuzdanPnlEl, dailyWalletPnl);
        }
        var pctCuzdan = (account.daily_wallet_pnl_pct != null && Number.isFinite(account.daily_wallet_pnl_pct))
            ? Number(account.daily_wallet_pnl_pct).toFixed(2) : ((account.spot_balance_usd || 1) !== 0 ? ((dailyWalletPnl / Math.max(account.spot_balance_usd || 1, 0.01)) * 100).toFixed(2) : '0.00');
        patchText("kpiCuzdanPnlPct", (parseFloat(pctCuzdan) >= 0 ? '+' : '') + pctCuzdan + '%');
        var e = document.getElementById("kpiCuzdanPnlPct"); if (e) { var ec = dailyWalletPnl >= 0 ? '#0ecb81' : '#f6465d'; if (e.style.color !== ec) e.style.color = ec; }
        var botPnlEl = document.getElementById("kpiBotPnl");
        if (botPnlEl) {
            var botTextChanged = setTextIfChanged(botPnlEl, fmtUsd(dailyBotPnl));
            var botColor = dailyBotPnl >= 0 ? '#0ecb81' : '#f6465d';
            if (botPnlEl.style.color !== botColor) botPnlEl.style.color = botColor;
            if (botTextChanged) triggerValueBlink(botPnlEl, dailyBotPnl);
        }
        var pctBot = (account.daily_bot_pnl_pct != null && Number.isFinite(account.daily_bot_pnl_pct))
            ? Number(account.daily_bot_pnl_pct).toFixed(2) : ((account.bots_initial_usd || account.bots_balance_usd || 1) > 0 ? ((dailyBotPnl / (account.bots_initial_usd || account.bots_balance_usd || 1)) * 100).toFixed(2) : '0.00');
        patchText("kpiBotPnlPct", (parseFloat(pctBot) >= 0 ? '+' : '') + pctBot + '%');
        e = document.getElementById("kpiBotPnlPct"); if (e) { var botPctC = parseFloat(pctBot) >= 0 ? '#0ecb81' : '#f6465d'; if (e.style.color !== botPctC) e.style.color = botPctC; }
    }
    // Tek kaynak: account.bots_balance_usd veya botların current_usd toplamı (bot detay state panel ile aynı)
    var botBakiyeEls = document.querySelectorAll("#kpiBotBakiye");
    botBakiyeEls.forEach(function (el) {
        el.textContent = fmtUsd(botsTotal);
        triggerValueBlink(el, botsTotal);
    });
    patchText("kpiBotBakiyePct", (typeof State !== 'undefined' && State.isTestAccount) ? "Test" : (assetsState.wallet.keys_configured === true ? "Canlı" : "Bağlı değil"));
}

function patchText(id, text) {
    const el = document.getElementById(id);
    if (el && el.textContent !== text) {
        el.textContent = text;
    }
}

// ============================================================
// BOT LİSTESİ - Satır görünümü, % kâra göre sıralı; düğme ile bakiye kârına göre; tıklayınca detay
// ============================================================

var botsSortBy = 'pct'; // 'pct' | 'usd'
var financeBotsSortBy = 'pct'; // Anasayfa Mevcut Botlar

function setBotsSortBy(sortBy) {
    botsSortBy = sortBy;
    const btn = document.getElementById('btnBotsSortBy');
    if (btn) {
        btn.title = sortBy === 'usd' ? 'Kâra göre sırala (tutar). Tıkla: orana göre' : 'Kâra göre sırala (oran). Tıkla: tutara göre';
    }
    renderBotsList(State.bots || []);
}

function setFinanceBotsSortBy(sortBy) {
    financeBotsSortBy = sortBy;
    const btn = document.getElementById('btnSortBotsBy');
    const btnTab = document.getElementById('btnSortBotsByBotsTab');
    if (btn) btn.title = sortBy === 'usd' ? 'Kâra göre sırala (tutar). Tıkla: orana göre' : 'Kâra göre sırala (oran). Tıkla: tutara göre';
    if (btnTab) btnTab.title = sortBy === 'usd' ? 'Kâra göre sırala (tutar). Tıkla: orana göre' : 'Kâra göre sırala (oran). Tıkla: tutara göre';
    if (State.bots && State.bots.length) {
        renderFinanceBots(State.bots);
        renderBotsList(State.bots);
    } else {
        loadFinanceBotsList();
    }
}

// Botlar sekmesi + Anasayfa aynı tablo: renderFinanceBots hem financeBotsList hem financeBotsListBots günceller
function renderBotsList(bots) {
    if (typeof window.__DEBUG_DASH__ !== 'undefined' && window.__DEBUG_DASH__) console.count('renderBotsList');
    renderFinanceBots(Array.isArray(bots) ? bots : []);
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
    },
    {
        id: 'trdca_pro',
        name: 'TRDCA Pro+ (Trailing Rebalancing DCA)',
        description: 'Trailing Rebalancing + Trailing DCA/Grid. Aynı coin setinde iki motor: TRB (ağırlık sapması) ve DCA (sepet fiyatı grid). Tek tick\'te 0/1 batch intent.',
        defaultConfig: {
            strategy_id: 'trdca_pro',
            quote_asset: 'USDT',
            tick_interval_ms: 1000,
            execution: { ack_timeout_sec: 5 },
            dca: {
                enabled: true,
                coin_weights: { BTC: 0.30, ETH: 0.30, SOL: 0.20, AVAX: 0.20 },
                grid_up_levels_pct: [1.0, 2.0, 3.0],
                grid_down_levels_pct: [1.0, 2.0, 3.0],
                grid_up_notional_usdt: [200, 200, 200],
                grid_down_notional_usdt: [200, 200, 200],
                sell_trail_back_pct: 0.8,
                buy_trail_up_pct: 0.8,
                buy_buffer_pct: 0.2,
                post_sell: { dip_trigger_pct: 2.0, dip_trail_up_pct: 0.8, dip_buy_notional_usdt: 200 },
                post_buy: { profit_trigger_pct: 2.0, profit_sell_trail_back_pct: 0.8, profit_sell_notional_usdt: 200 }
            },
            trb: {
                enabled: true,
                target_weights_all: { BTC: 0.30, ETH: 0.30, SOL: 0.20, USDT: 0.20 },
                small_eps_pct: 0.8,
                min_leg_notional_usdt: 10,
                gap_arm_pct: 3.0,
                trail_back_pct: 0.6,
                max_batch_legs: 8,
                sell_first: true,
                step_mode: 'SELL_ONLY_THEN_BUY',
                batch_atomicity: 'SOFT',
                partial_fill_behavior: 'SAFE_STOP',
                max_exec_delay_sec: 15,
                ts_bucket_sec: 5,
                gap_peak_bucket_dp: 2
            }
        }
    }
];

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

var copyTradingCache = {};
var COPY_TRADING_CACHE_TTL_MS = 30000;

function toggleCopyTradingDrawer(structure) {
    var drawer = document.querySelector('[data-copy-drawer="' + structure.id + '"]');
    if (!drawer) return;
    if (drawer.style.display === 'block') {
        drawer.style.display = 'none';
        drawer.innerHTML = '';
        return;
    }
    document.querySelectorAll('.bot-structure-card__copy-drawer').forEach(function (d) {
        d.style.display = 'none';
        d.innerHTML = '';
    });
    var cached = copyTradingCache[structure.id];
    if (cached && (Date.now() - cached.ts) < COPY_TRADING_CACHE_TTL_MS && cached.items) {
        renderCopyTradingDrawer(drawer, structure, cached.items);
        drawer.style.display = 'block';
        return;
    }
    drawer.innerHTML = '<div style="padding: 8px; color: var(--ds-text-secondary);">Yükleniyor…</div>';
    drawer.style.display = 'block';
    var url = '/api/leaderboard/structures/' + encodeURIComponent(structure.id) + '/top?limit=5';
    window.apiClient.get(url).then(function (data) {
        var items = (data && data.items) ? data.items : [];
        copyTradingCache[structure.id] = { ts: Date.now(), items: items };
        renderCopyTradingDrawer(drawer, structure, items);
    }).catch(function () {
        drawer.innerHTML = '<div style="padding: 8px; color: var(--ds-text-secondary); font-size: 0.9rem;">Bulunamadı.</div>';
    });
}

function renderCopyTradingDrawer(drawer, structure, items) {
    var structureName = (structure && structure.name) ? structure.name : structure.id;
    var html = '<h4 style="margin: 0 0 10px 0; font-size: 1rem; font-weight: 600; color: var(--ds-text-primary);">Top 5 (' + escapeHtml(structureName) + ')</h4>';
    if (!items.length) {
        html += '<p style="margin: 0; font-size: 0.9rem; color: var(--ds-text-secondary);">Bulunamadı. Bu yapı için kârda olan bot bulunamadı.</p>';
        drawer.innerHTML = html;
        return;
    }
    items.forEach(function (item, idx) {
        var pct = item.profit_pct != null ? Number(item.profit_pct) : 0;
        var pctStr = (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%';
        var pctColor = pct >= 0 ? '#0ecb81' : '#f6465d';
        html += '<div class="copy-trading-row" style="margin-bottom: 12px; padding: 10px; background: var(--ds-bg-secondary); border-radius: 6px; border: 1px solid var(--ds-border);">';
        html += '<div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">';
        html += '<span style="font-weight: 600; color: ' + pctColor + ';">Kâr %: ' + pctStr + '</span>';
        html += '<button type="button" class="btn btn-sm" data-apply-idx="' + idx + '" style="background: var(--ds-accent); color: #000;">Bu parametreleri uygula</button>';
        html += '</div>';
        var params = item.params || {};
        var keys = Object.keys(params).filter(function (k) { return k && params[k] !== undefined && params[k] !== null && typeof params[k] !== 'object'; });
        if (keys.length) {
            html += '<div style="margin-top: 8px; font-size: 0.8rem; color: var(--ds-text-secondary);">';
            keys.slice(0, 8).forEach(function (k) {
                var v = params[k];
                if (typeof v === 'object') return;
                html += '<span style="margin-right: 12px;">' + escapeHtml(String(k)) + ': ' + escapeHtml(String(v)) + '</span>';
            });
            html += '</div>';
        }
        html += '</div>';
    });
    drawer.innerHTML = html;
    drawer.querySelectorAll('[data-apply-idx]').forEach(function (btn) {
        var idx = parseInt(btn.getAttribute('data-apply-idx'), 10);
        var item = items[idx];
        if (!item) return;
        btn.onclick = function (e) {
            e.stopPropagation();
            var p = normalizeLeaderboardParamsToFormConfig(item.params || {});
            if (item.symbol && !p.symbol) p.symbol = item.symbol;
            applyLeaderboardParams(structure, p);
        };
    });
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
        const isTrdcaPro = structure.id === 'trdca_pro';
        const isTestAccount = typeof State !== 'undefined' && State.isTestAccount === true;
        const trdcaProDisabled = isTrdcaPro && !isTestAccount;

        const card = document.createElement("div");
        card.style.cssText = `
            background: var(--ds-bg-secondary, #1e2329);
            border: 1px solid var(--ds-border, #2b3139);
            border-radius: 8px;
            padding: 20px 24px;
            cursor: ${trdcaProDisabled ? 'default' : 'pointer'};
            transition: all 0.2s ease;
            width: 100%;
            ${trdcaProDisabled ? 'opacity: 0.88;' : ''}
        `;
        card.dataset.structureId = structure.id;
        card.className = "bot-structure-card" + (trdcaProDisabled ? " bot-structure-card--coming-soon" : "");
        const badgeHtml = trdcaProDisabled ? '<span class="bot-structure-card__badge" style="display: inline-block; margin-bottom: 8px; padding: 4px 10px; border-radius: 6px; font-size: 0.75rem; font-weight: 600; background: var(--ds-accent, #f0b90b); color: #000;">Çok yakında</span>' : '';
        const btnLabel = trdcaProDisabled ? 'Çok yakında' : 'Devam Et →';
        const btnDisabled = trdcaProDisabled ? ' disabled' : '';
        card.innerHTML = `
            <div class="bot-structure-card__inner">
                <div class="bot-structure-card__text">
                    ${badgeHtml}
                    <h3 style="margin: 0 0 6px 0; font-size: 1.1rem; font-weight: 600; color: var(--ds-text-primary);">${structure.name}</h3>
                    <p style="margin: 0; font-size: 0.9rem; color: var(--ds-text-secondary); line-height: 1.4;">${structure.description}</p>
                </div>
                <div style="display: flex; flex-wrap: wrap; gap: 8px; align-items: center;">
                    <button class="btn btn-primary-gold bot-structure-card__btn" style="padding: 10px 24px; font-weight: 600; white-space: nowrap;" data-action="select" data-structure-id="${structure.id}"${btnDisabled}>
                        ${btnLabel}
                    </button>
                    ${!trdcaProDisabled ? '<button type="button" class="btn bot-structure-card__btn-copy" style="padding: 10px 16px; font-weight: 600; white-space: nowrap; background: var(--ds-bg-tertiary); color: var(--ds-text-primary); border: 1px solid var(--ds-border);" data-action="copy-trading" data-structure-id="' + structure.id + '">Copy Trading</button>' : ''}
                </div>
            </div>
            <div class="bot-structure-card__copy-drawer" data-copy-drawer="${structure.id}" style="display: none; margin-top: 12px; padding: 12px; background: var(--ds-bg-tertiary); border-radius: 8px; border: 1px solid var(--ds-border);"></div>
        `;
        
        // Hover effect only when not disabled
        if (!trdcaProDisabled) {
            card.onmouseenter = () => {
                card.style.borderColor = 'var(--ds-accent, #f0b90b)';
                card.style.backgroundColor = 'var(--ds-bg-hover, rgba(240, 185, 11, 0.05))';
            };
            card.onmouseleave = () => {
                card.style.borderColor = 'var(--ds-border, #2b3139)';
                card.style.backgroundColor = 'var(--ds-bg-secondary, #1e2329)';
            };
        }
        
        // Select button
        const selectBtn = card.querySelector('[data-action="select"]');
        if (selectBtn) {
            selectBtn.onclick = (e) => {
                e.stopPropagation();
                if (trdcaProDisabled) {
                    if (window.Toast) window.Toast.info('TRDCA Pro+ çok yakında. Şu an sadece test hesabında kullanılabilir.');
                    return;
                }
                selectBotStructure(structure);
            };
        }
        const copyBtn = card.querySelector('[data-action="copy-trading"]');
        if (copyBtn) {
            copyBtn.onclick = (e) => {
                e.stopPropagation();
                toggleCopyTradingDrawer(structure);
            };
        }
        
        // Card click
        card.onclick = (e) => {
            if (trdcaProDisabled) {
                if (!e.target.closest('button') && window.Toast) window.Toast.info('TRDCA Pro+ çok yakında. Şu an sadece test hesabında kullanılabilir.');
                return;
            }
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
    // TRDCA Pro+ sadece test hesabında aktif (geliştirme için)
    if (structure.id === 'trdca_pro' && (typeof State === 'undefined' || !State.isTestAccount)) {
        if (window.Toast) window.Toast.info('TRDCA Pro+ çok yakında. Şu an sadece test hesabında kullanılabilir.');
        return;
    }
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
    const trdca = document.getElementById("dmWizardTrdca");
    const pairStrip = document.getElementById("dmSelectedPairStrip");
    const tahminStrip = document.getElementById("dmTahminStrip");
    if (templateId === "trdca_pro") {
        if (dmModalMultiPreviewIntervalId) {
            clearInterval(dmModalMultiPreviewIntervalId);
            dmModalMultiPreviewIntervalId = null;
        }
        if (dca) dca.style.display = "none";
        if (multi) multi.style.display = "none";
        if (trdca) trdca.style.display = "block";
        if (pairStrip) pairStrip.style.display = "none";
        if (tahminStrip) tahminStrip.style.display = "none";
        hideMultiSymbolSearchDropdown();
        var n = parseInt(document.getElementById("fTrdcaCoinCount")?.value || "4", 10);
        buildTrdcaRebalanceRows(n);
        var gridUpCount = parseInt(document.getElementById("fTrdcaGridUpCount")?.value || "3", 10);
        var gridDownCount = parseInt(document.getElementById("fTrdcaGridDownCount")?.value || "3", 10);
        buildTrdcaGridUpRows(gridUpCount);
        buildTrdcaGridDownRows(gridDownCount);
        updateTrdcaBalancePlaceholder();
        updateTrdcaQuoteName();
    } else {
        if (dmModalMultiPreviewIntervalId) {
            clearInterval(dmModalMultiPreviewIntervalId);
            dmModalMultiPreviewIntervalId = null;
        }
        if (dca) dca.style.display = "block";
        if (multi) multi.style.display = "none";
        if (trdca) trdca.style.display = "none";
        hideMultiSymbolSearchDropdown();
        if (pairStrip) pairStrip.style.display = "none";
        if (tahminStrip) tahminStrip.style.display = "none";
    }
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

// --- TRDCA Pro+ wizard: rebalance rows + preview ---
function buildTrdcaRebalanceRows(count) {
    count = Math.min(10, Math.max(2, parseInt(count, 10) || 2));
    var container = document.getElementById("trdcaRebalanceRows");
    if (!container) return;
    container.innerHTML = "";
    for (var i = 0; i < count; i++) {
        var row = document.createElement("div");
        row.className = "trdca-rebalance-row";
        row.setAttribute("data-idx", String(i));
        row.style.marginBottom = "12px";
        var defaultPct = count > 0 ? Math.round((100 / count) * 100) / 100 : 0;
        var lastPct = (i === count - 1 && count > 1) ? (100 - defaultPct * (count - 1)).toFixed(1) : defaultPct;
        row.innerHTML = '<div class="grid-2" style="gap:8px; align-items: end;"><div class="form-group"><label>Coin ' + (i + 1) + '</label><input type="text" class="form-input trdca-rebalance-symbol" data-idx="' + i + '" placeholder="Sembol (BTC, ETH…)" maxlength="12" style="text-transform:uppercase;width:100%;padding:0.6rem 1rem;" autocomplete="off" /></div><div class="form-group"><label>Dağılım %</label><input type="number" class="form-input trdca-rebalance-pct" data-idx="' + i + '" min="0" max="100" step="0.5" placeholder="' + (count === 2 ? '50' : count === 3 ? '33.3' : '25') + '" value="' + lastPct + '" style="width:100%;padding:0.6rem 1rem;" /></div></div><div class="trdca-rebalance-preview" data-idx="' + i + '" style="margin-top:6px;padding:6px 10px;font-size:0.8rem;background:var(--ds-bg-tertiary);border-radius:6px;color:var(--ds-text-secondary);">—</div>';
        container.appendChild(row);
        var symInput = row.querySelector(".trdca-rebalance-symbol");
        if (symInput) symInput.addEventListener("input", function () { updateTrdcaPreviews(); });
    }
    updateTrdcaPctTotal();
    updateTrdcaPreviews();
}

function buildTrdcaGridUpRows(count) {
    count = Math.min(10, Math.max(1, parseInt(count, 10) || 3));
    var container = document.getElementById("trdcaGridUpRows");
    if (!container) return;
    container.innerHTML = "";
    for (var i = 0; i < count; i++) {
        var row = document.createElement("div");
        row.className = "trdca-grid-up-row";
        row.setAttribute("data-idx", String(i));
        row.style.marginBottom = "8px";
        row.innerHTML = '<div class="grid-2" style="gap:8px;"><div class="form-group"><label>Seviye ' + (i + 1) + ' — Tetik %</label><input type="number" class="form-input trdca-grid-up-pos" data-idx="' + i + '" min="0" max="100" step="0.5" placeholder="" style="width:100%;padding:0.6rem 1rem;" /></div><div class="form-group"><label>Satım %</label><input type="number" class="form-input trdca-grid-up-amt" data-idx="' + i + '" min="0" max="100" step="0.5" placeholder="" style="width:100%;padding:0.6rem 1rem;" /></div></div>';
        container.appendChild(row);
    }
}

function buildTrdcaGridDownRows(count) {
    count = Math.min(10, Math.max(1, parseInt(count, 10) || 3));
    var container = document.getElementById("trdcaGridDownRows");
    if (!container) return;
    container.innerHTML = "";
    for (var i = 0; i < count; i++) {
        var row = document.createElement("div");
        row.className = "trdca-grid-down-row";
        row.setAttribute("data-idx", String(i));
        row.style.marginBottom = "8px";
        row.innerHTML = '<div class="grid-2" style="gap:8px;"><div class="form-group"><label>Seviye ' + (i + 1) + ' — Tetik %</label><input type="number" class="form-input trdca-grid-down-pos" data-idx="' + i + '" min="0" max="100" step="0.5" placeholder="" style="width:100%;padding:0.6rem 1rem;" /></div><div class="form-group"><label>Alım %</label><input type="number" class="form-input trdca-grid-down-amt" data-idx="' + i + '" min="0" max="100" step="0.5" placeholder="" style="width:100%;padding:0.6rem 1rem;" /></div></div>';
        container.appendChild(row);
    }
}

function updateTrdcaPctTotal() {
    var total = 0;
    document.querySelectorAll("#trdcaRebalanceRows .trdca-rebalance-pct").forEach(function (el) {
        total += parseFloat(el.value) || 0;
    });
    var totalEl = document.getElementById("trdcaPctTotal");
    var quoteEl = document.getElementById("trdcaQuotePct");
    if (totalEl) {
        totalEl.textContent = total.toFixed(1);
        totalEl.style.color = total <= 100 && total >= 0 ? "var(--ds-text-primary)" : "var(--ds-text-error, #f6465d)";
    }
    if (quoteEl) {
        var quotePct = Math.max(0, 100 - total);
        quoteEl.textContent = quotePct.toFixed(1);
    }
    var baseEl = document.getElementById("fTrdcaBasePct");
    var quoteBarEl = document.getElementById("fTrdcaQuotePctBar");
    var quotePctVal = Math.max(0, 100 - total);
    if (baseEl) baseEl.value = total === 0 && quotePctVal === 100 ? "" : total.toFixed(0);
    if (quoteBarEl) quoteBarEl.value = total === 0 ? "" : quotePctVal.toFixed(0);
}

function getTrdcaBalanceForPreview() {
    var balanceInput = document.getElementById("fTrdcaBotBalance");
    if (balanceInput && balanceInput.value && Number.isFinite(parseFloat(balanceInput.value))) return parseFloat(balanceInput.value);
    var quote = (document.getElementById("fTrdcaQuoteAsset") && document.getElementById("fTrdcaQuoteAsset").value) || "USDT";
    var assets = (typeof assetsState !== "undefined" && assetsState.wallet && assetsState.wallet.assets) ? assetsState.wallet.assets : [];
    for (var i = 0; i < assets.length; i++) {
        if ((assets[i].asset || "").toUpperCase() === (quote || "USDT")) return parseFloat(assets[i].free) || 0;
    }
    return 0;
}

function getTrdcaSymbolPrice(sym, quote) {
    if (!sym) return null;
    var pair = (sym + (quote || "USDT")).toUpperCase();
    var mini = window.marketStore && window.marketStore.getMini ? window.marketStore.getMini(pair) : null;
    var price = (mini && mini.last != null) ? mini.last : (window.marketStore && window.marketStore.getPrice && window.marketStore.getPrice(pair));
    return (price != null && Number.isFinite(Number(price))) ? Number(price) : null;
}

function updateTrdcaPreviews() {
    var balance = getTrdcaBalanceForPreview();
    var quote = (document.getElementById("fTrdcaQuoteAsset") && document.getElementById("fTrdcaQuoteAsset").value) || "USDT";
    document.querySelectorAll("#trdcaRebalanceRows .trdca-rebalance-preview").forEach(function (previewEl) {
        var idx = previewEl.getAttribute("data-idx");
        var pctInput = document.querySelector('.trdca-rebalance-pct[data-idx="' + idx + '"]');
        var symInput = document.querySelector('.trdca-rebalance-symbol[data-idx="' + idx + '"]');
        var pct = pctInput ? (parseFloat(pctInput.value) || 0) : 0;
        var sym = symInput ? (symInput.value || "").trim().toUpperCase() : "";
        if (!sym && pct === 0) {
            previewEl.textContent = "—";
            return;
        }
        var estUsdt = balance > 0 && pct > 0 ? (balance * pct / 100) : 0;
        if (estUsdt > 0) {
            previewEl.textContent = "≈ " + (typeof fmtNum === "function" ? fmtNum(estUsdt, 2) : estUsdt.toFixed(2)) + " " + quote + (sym ? " (" + sym + " " + (pct.toFixed(1)) + "%)" : "");
            return;
        }
        var price = getTrdcaSymbolPrice(sym, quote);
        if (sym && price != null) previewEl.textContent = sym + " ≈ " + (typeof fmtNum === "function" ? fmtNum(price, 2) : price.toFixed(2)) + " " + quote + (pct > 0 ? " · " + pct.toFixed(1) + "%" : " — Dağılım % girin");
        else previewEl.textContent = sym ? sym + (pct > 0 ? " " + pct.toFixed(1) + "%" : " — Dağılım % girin") : "—";
    });
}

function updateTrdcaBalancePlaceholder() {
    var wizard = document.getElementById("dmWizardTrdca");
    if (!wizard || wizard.style.display !== "block") return;
    var quote = (document.getElementById("fTrdcaQuoteAsset") && document.getElementById("fTrdcaQuoteAsset").value) || "USDT";
    var el = document.getElementById("fTrdcaBotBalance");
    if (el) el.placeholder = formatAvailableQuotePlaceholder(quote, getAvailableQuoteInWallet(quote));
}

function updateTrdcaQuoteName() {
    var q = (document.getElementById("fTrdcaQuoteAsset") && document.getElementById("fTrdcaQuoteAsset").value) || "USDT";
    var el = document.getElementById("dmTrdcaQuoteName");
    if (el) el.textContent = q;
    updateTrdcaBalancePlaceholder();
    updateTrdcaPreviews();
}

/**
 * Fill modal with template default values
 */
function fillModalWithTemplate(template) {
    const config = template.defaultConfig || {};
    const fromLeaderboard = !!template.fromLeaderboardApply;
    setCreateBotModalWizard(template.id);

    if (template.id === "trdca_pro") {
        var c = config || {};
        var el = function (id) { return document.getElementById(id); };
        if (el("fTrdcaQuoteAsset")) el("fTrdcaQuoteAsset").value = c.quote_asset || "USDT";
        if (el("fTrdcaBotBalance")) { el("fTrdcaBotBalance").value = fromLeaderboard ? "" : ((c.initial_capital_usdt || c.bot_budget_usdt) ? String(c.initial_capital_usdt || c.bot_budget_usdt) : ""); }
        var trb = c.trb || {};
        var targetAll = trb.target_weights_all || { BTC: 0.3, ETH: 0.3, SOL: 0.2, USDT: 0.2 };
        var coins = [];
        var quoteKey = (c.quote_asset || "USDT").toUpperCase();
        Object.keys(targetAll).forEach(function (k) {
            if (k && (k.toUpperCase() !== quoteKey)) coins.push({ symbol: k.toUpperCase().replace(quoteKey, ""), pct: (targetAll[k] || 0) * 100 });
        });
        if (coins.length === 0) coins = [{ symbol: "BTC", pct: 30 }, { symbol: "ETH", pct: 30 }, { symbol: "SOL", pct: 20 }, { symbol: "AVAX", pct: 20 }];
        var countEl = el("fTrdcaCoinCount");
        if (countEl) countEl.value = coins.length;
        buildTrdcaRebalanceRows(coins.length);
        setTimeout(function () {
            coins.forEach(function (item, i) {
                var symInput = document.querySelector('.trdca-rebalance-symbol[data-idx="' + i + '"]');
                var pctInput = document.querySelector('.trdca-rebalance-pct[data-idx="' + i + '"]');
                if (symInput) symInput.value = item.symbol;
                if (pctInput) pctInput.value = item.pct;
            });
            updateTrdcaPctTotal();
            updateTrdcaPreviews();
        }, 0);
        if (el("fTrdcaGapArmPct")) el("fTrdcaGapArmPct").value = trb.gap_arm_pct != null ? trb.gap_arm_pct : 3;
        if (el("fTrdcaTrailBackPct")) el("fTrdcaTrailBackPct").value = trb.trail_back_pct != null ? trb.trail_back_pct : 0.6;
        var dca = c.dca || {};
        var upLevels = Array.isArray(dca.grid_up_levels_pct) ? dca.grid_up_levels_pct : [1, 2, 3];
        var downLevels = Array.isArray(dca.grid_down_levels_pct) ? dca.grid_down_levels_pct : [1, 2, 3];
        var upNotional = Array.isArray(dca.grid_up_notional_usdt) ? dca.grid_up_notional_usdt : [200, 200, 200];
        var downNotional = Array.isArray(dca.grid_down_notional_usdt) ? dca.grid_down_notional_usdt : [200, 200, 200];
        var upNotionalPct = Array.isArray(dca.grid_up_notional_pct) ? dca.grid_up_notional_pct : null;
        var downNotionalPct = Array.isArray(dca.grid_down_notional_pct) ? dca.grid_down_notional_pct : null;
        var balance = fromLeaderboard ? 0 : ((c.initial_capital_usdt || c.bot_budget_usdt) || 6000);
        var upPos = upLevels.map(function (v) { return Number.isFinite(v) ? v : 0; });
        var downPos = downLevels.map(function (v) { return Number.isFinite(v) ? v : 0; });
        var upAmt = upNotionalPct && upNotionalPct.length ? upNotionalPct.map(function (p) { return Number.isFinite(p) ? p : 0; }) : upNotional.map(function (n) { return balance > 0 ? (n / balance * 100) : (100 / upNotional.length); });
        var downAmt = downNotionalPct && downNotionalPct.length ? downNotionalPct.map(function (p) { return Number.isFinite(p) ? p : 0; }) : downNotional.map(function (n) { return balance > 0 ? (n / balance * 100) : (100 / downNotional.length); });
        if (el("fTrdcaGridUpCount")) el("fTrdcaGridUpCount").value = upLevels.length;
        if (el("fTrdcaGridDownCount")) el("fTrdcaGridDownCount").value = downLevels.length;
        if (el("fTrdcaGridTrailPct")) el("fTrdcaGridTrailPct").value = dca.sell_trail_back_pct != null ? dca.sell_trail_back_pct : 0.8;
        buildTrdcaGridUpRows(upLevels.length);
        buildTrdcaGridDownRows(downLevels.length);
        setTimeout(function () {
            upPos.forEach(function (v, i) {
                var inp = document.querySelector('.trdca-grid-up-pos[data-idx="' + i + '"]');
                if (inp) inp.value = Number.isFinite(v) ? v : '';
            });
            upAmt.forEach(function (v, i) {
                var inp = document.querySelector('.trdca-grid-up-amt[data-idx="' + i + '"]');
                if (inp) inp.value = v.toFixed(1);
            });
            downPos.forEach(function (v, i) {
                var inp = document.querySelector('.trdca-grid-down-pos[data-idx="' + i + '"]');
                if (inp) inp.value = Number.isFinite(v) ? v : '';
            });
            downAmt.forEach(function (v, i) {
                var inp = document.querySelector('.trdca-grid-down-amt[data-idx="' + i + '"]');
                if (inp) inp.value = v.toFixed(1);
            });
        }, 0);
        var ps = dca.post_sell || {};
        var pb = dca.post_buy || {};
        var karTetik = ps.dip_trigger_pct != null ? ps.dip_trigger_pct : (pb.profit_trigger_pct != null ? pb.profit_trigger_pct : 2);
        var karTrail = ps.dip_trail_up_pct != null ? ps.dip_trail_up_pct : (pb.profit_sell_trail_back_pct != null ? pb.profit_sell_trail_back_pct : 0.8);
        if (el("fTrdcaKarAlimTetikPct")) el("fTrdcaKarAlimTetikPct").value = karTetik;
        if (el("fTrdcaKarAlimTrailPct")) el("fTrdcaKarAlimTrailPct").value = karTrail;
        updateTrdcaQuoteName();
        updateTrdcaBalancePlaceholder();
        return;
    }

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
    if (payload.strategy_id === "trdca_pro") {
        requestedBudget = Number(payload.initial_capital_usdt || payload.bot_budget_usdt) || 0;
        quoteAsset = (payload.quote_asset || "USDT").toString().trim().toUpperCase() || "USDT";
    } else {
        requestedBudget = Number(payload.budget_usd) || 0;
        try {
            var pq = parseBaseQuote(payload.symbol || "");
            quoteAsset = (pq && pq.quote) ? pq.quote : "USDT";
        } catch (e) { quoteAsset = "USDT"; }
    }
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
        
        var createLabel = (payload.strategy_id === 'trdca_pro') ? 'TRDCA Pro' : displayName;
        if (window.Toast) {
            window.Toast.success('Bot ' + createLabel + ' oluşturuldu');
        }
        try { localStorage.setItem(DASHBOARD_LAST_CREATE_BOT_PARAMS, JSON.stringify(payload)); } catch (e) {}
        
        // Start bot immediately (bots-engine inserts command for worker)
        try {
            const startResp = await window.apiClient.post(`/api/bots-engine/${botId}/start?account_id=${State.accountId}`);
            
            var startLabel = (payload.strategy_id === 'trdca_pro') ? 'TRDCA Pro' : createLabel;
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
        var detailPage = (payload.strategy_id === 'trdca_pro' || payload.strategy_id === 'multi_asset_rebalance') ? '/ui/bot_multi.html' : '/ui/bot.html';
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
                var isTrdca = cfg.strategy_id === 'trdca_pro';
                var dn = isTrdca ? ('TRDCA Pro #' + (bot.bot_code || botId)) : ((bot.bot_code ? '#' + bot.bot_code : null) || (symbol === 'MULTI' ? ('#' + botId) : symbol));
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
    if ((config.strategy_id || "").toLowerCase() === "trdca_pro") {
        setCreateBotModalWizard("trdca_pro");
        var c = config;
        var el = function (id) { return document.getElementById(id); };
        if (el("fTrdcaQuoteAsset")) el("fTrdcaQuoteAsset").value = c.quote_asset || "USDT";
        if (el("fTrdcaBotBalance")) el("fTrdcaBotBalance").value = (c.initial_capital_usdt || c.bot_budget_usdt) ? String(c.initial_capital_usdt || c.bot_budget_usdt) : "";
        var trb = c.trb || {};
        var targetAll = trb.target_weights_all || {};
        var quoteKey = (c.quote_asset || "USDT").toUpperCase();
        var coins = [];
        Object.keys(targetAll).forEach(function (k) {
            if (k && k.toUpperCase() !== quoteKey) coins.push({ symbol: k.toUpperCase().replace(quoteKey, ""), pct: (targetAll[k] || 0) * 100 });
        });
        if (coins.length < 2) coins = [{ symbol: "BTC", pct: 30 }, { symbol: "ETH", pct: 30 }, { symbol: "SOL", pct: 20 }, { symbol: "AVAX", pct: 20 }];
        if (el("fTrdcaCoinCount")) el("fTrdcaCoinCount").value = coins.length;
        buildTrdcaRebalanceRows(coins.length);
        setTimeout(function () {
            coins.forEach(function (item, i) {
                var symInput = document.querySelector('.trdca-rebalance-symbol[data-idx="' + i + '"]');
                var pctInput = document.querySelector('.trdca-rebalance-pct[data-idx="' + i + '"]');
                if (symInput) symInput.value = item.symbol;
                if (pctInput) pctInput.value = item.pct;
            });
            updateTrdcaPctTotal();
            updateTrdcaPreviews();
        }, 0);
        if (el("fTrdcaGapArmPct")) el("fTrdcaGapArmPct").value = trb.gap_arm_pct != null ? trb.gap_arm_pct : 3;
        if (el("fTrdcaTrailBackPct")) el("fTrdcaTrailBackPct").value = trb.trail_back_pct != null ? trb.trail_back_pct : 0.6;
        var dca = c.dca || {};
        var upLevels = Array.isArray(dca.grid_up_levels_pct) ? dca.grid_up_levels_pct : [1, 2, 3];
        var downLevels = Array.isArray(dca.grid_down_levels_pct) ? dca.grid_down_levels_pct : [1, 2, 3];
        var upNotional = Array.isArray(dca.grid_up_notional_usdt) ? dca.grid_up_notional_usdt : [200, 200, 200];
        var downNotional = Array.isArray(dca.grid_down_notional_usdt) ? dca.grid_down_notional_usdt : [200, 200, 200];
        var upNotionalPct = Array.isArray(dca.grid_up_notional_pct) ? dca.grid_up_notional_pct : null;
        var downNotionalPct = Array.isArray(dca.grid_down_notional_pct) ? dca.grid_down_notional_pct : null;
        var balance = (c.initial_capital_usdt || c.bot_budget_usdt) || 6000;
        var upPos = upLevels.map(function (v) { return Number.isFinite(v) ? v : 0; });
        var downPos = downLevels.map(function (v) { return Number.isFinite(v) ? v : 0; });
        var upAmt = upNotionalPct && upNotionalPct.length ? upNotionalPct.map(function (p) { return Number.isFinite(p) ? p : 0; }) : upNotional.map(function (n) { return balance > 0 ? (n / balance * 100) : (100 / upNotional.length); });
        var downAmt = downNotionalPct && downNotionalPct.length ? downNotionalPct.map(function (p) { return Number.isFinite(p) ? p : 0; }) : downNotional.map(function (n) { return balance > 0 ? (n / balance * 100) : (100 / downNotional.length); });
        if (el("fTrdcaGridUpCount")) el("fTrdcaGridUpCount").value = upLevels.length;
        if (el("fTrdcaGridDownCount")) el("fTrdcaGridDownCount").value = downLevels.length;
        if (el("fTrdcaGridTrailPct")) el("fTrdcaGridTrailPct").value = dca.sell_trail_back_pct != null ? dca.sell_trail_back_pct : 0.8;
        buildTrdcaGridUpRows(upLevels.length);
        buildTrdcaGridDownRows(downLevels.length);
        setTimeout(function () {
            upPos.forEach(function (v, i) {
                var inp = document.querySelector('.trdca-grid-up-pos[data-idx="' + i + '"]');
                if (inp) inp.value = Number.isFinite(v) ? v : '';
            });
            upAmt.forEach(function (v, i) {
                var inp = document.querySelector('.trdca-grid-up-amt[data-idx="' + i + '"]');
                if (inp) inp.value = v.toFixed(1);
            });
            downPos.forEach(function (v, i) {
                var inp = document.querySelector('.trdca-grid-down-pos[data-idx="' + i + '"]');
                if (inp) inp.value = Number.isFinite(v) ? v : '';
            });
            downAmt.forEach(function (v, i) {
                var inp = document.querySelector('.trdca-grid-down-amt[data-idx="' + i + '"]');
                if (inp) inp.value = v.toFixed(1);
            });
        }, 0);
        var ps = dca.post_sell || {};
        var pb = dca.post_buy || {};
        var karTetik = ps.dip_trigger_pct != null ? ps.dip_trigger_pct : (pb.profit_trigger_pct != null ? pb.profit_trigger_pct : 2);
        var karTrail = ps.dip_trail_up_pct != null ? ps.dip_trail_up_pct : (pb.profit_sell_trail_back_pct != null ? pb.profit_sell_trail_back_pct : 0.8);
        if (el("fTrdcaKarAlimTetikPct")) el("fTrdcaKarAlimTetikPct").value = karTetik;
        if (el("fTrdcaKarAlimTrailPct")) el("fTrdcaKarAlimTrailPct").value = karTrail;
        updateTrdcaQuoteName();
        updateTrdcaBalancePlaceholder();
        var trdcaModalTitle = document.querySelector(".dm-modal__title");
        if (trdcaModalTitle) trdcaModalTitle.textContent = "TRDCA Pro+ Parametreleri";
        var errEl = document.getElementById("createBotErrorTrdca");
        if (errEl) { errEl.style.display = "block"; errEl.style.color = "var(--ds-text-secondary)"; errEl.textContent = "Mevcut bot parametreleri. Değiştirmek için botu durdurup yeni bot oluşturabilirsiniz."; }
        return;
    }
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
            unifiedStrip.style.display = showStrip ? "block" : "none";
            if (showStrip) unifiedStrip.classList.remove("unified-kpi-bots-only");
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
            if (window.intervalRegistry) {
                window.intervalRegistry.stopByOwner("tab.trade");
                window.intervalRegistry.start("tab.trade.prices", tickMobileTradeFavoritesPrices, 2000, "tab.trade");
            }
        } else if (tab === "bots") {
            const desktopTab = document.querySelector('.dm-tab[data-tab="bots"]');
            if (desktopTab) desktopTab.click();
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
function initMobileTradeSearch() {
    var input = document.getElementById("mobileTradeSearchInput");
    var dropdown = document.getElementById("mobileTradeSearchDropdown");
    if (!input || !dropdown) return;

    function fillDropdown() {
        var q = (input.value || "").trim().toUpperCase();
        if (!q) {
            dropdown.style.display = "none";
            return;
        }
        var filtered = (typeof coinListSearchAllSymbols !== "undefined" && Array.isArray(coinListSearchAllSymbols))
            ? coinListSearchAllSymbols.filter(function (c) {
                var s = (c.symbol || "").toUpperCase();
                return s && s.indexOf(q) !== -1;
            })
            : [];
        var list = filtered.sort(function (a, b) {
            var sa = (a.symbol || "").toUpperCase();
            var sb = (b.symbol || "").toUpperCase();
            var aUsdt = sa.endsWith("USDT") ? 0 : (sa.endsWith("FDUSD") ? 1 : 2);
            var bUsdt = sb.endsWith("USDT") ? 0 : (sb.endsWith("FDUSD") ? 1 : 2);
            if (aUsdt !== bUsdt) return aUsdt - bUsdt;
            return sa.localeCompare(sb);
        }).slice(0, 50);
        dropdown.innerHTML = list.map(function (item) {
            var sym = item.symbol || "";
            var pct = item.changePct != null ? item.changePct : 0;
            var pctColor = pct >= 0 ? "#0ecb81" : "#f6465d";
            var pctStr = (pct >= 0 ? "+" : "") + (Number(pct).toFixed(2)) + "%";
            var priceStr = item.last != null && Number.isFinite(item.last) && typeof fmtUsd === "function" ? fmtUsd(item.last) : "—";
            return "<div class=\"coin-list-search-item mobile-trade-search-item\" data-symbol=\"" + sym + "\" style=\"padding: 0.6rem 1rem; cursor: pointer; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--ds-border);\"><span style=\"font-weight: 600;\">" + sym + "</span><span style=\"display: flex; gap: 0.5rem; align-items: center;\"><span style=\"color: var(--ds-text-secondary);\">" + priceStr + "</span><span style=\"color: " + pctColor + "\">" + pctStr + "</span></span></div>";
        }).join("");
        dropdown.style.display = list.length ? "block" : "none";
    }

    if (!_mobileTradeSearchBound) {
        _mobileTradeSearchBound = true;
        input.oninput = fillDropdown;
        input.onfocus = function () {
            ensureCoinListSearchSymbolsLoaded("all").then(function () { buildCoinListSearchSymbols(); if ((input.value || "").trim()) fillDropdown(); });
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

// Mobil Trade: Favori coinler listesini doldur; tıklayınca alım satım modalı açılır
function renderMobileTradeFavorites() {
    var listEl = document.getElementById("mobileTradeFavoritesList");
    if (!listEl) return;
    var favs = (typeof spotFavorites !== "undefined" && Array.isArray(spotFavorites)) ? spotFavorites.slice() : [];
    if (favs.length === 0) {
        listEl.innerHTML = '<div style="padding: 1.5rem; text-align: center; color: var(--ds-text-secondary); font-size: 0.9rem;">Favori yok. Yukarıdaki arama çubuğunda coin arayıp seçin, alım satım ekranında yıldıza tıklayarak favorilere ekleyin.</div>';
        return;
    }
    var baseFromSymbol = function (sym) {
        var q = ["USDT", "FDUSD", "BUSD", "BTC", "ETH", "BNB", "TRY"];
        for (var i = 0; i < q.length; i++) {
            if (sym.endsWith(q[i])) return sym.slice(0, -q[i].length) || sym;
        }
        return sym.substring(0, 4) || sym;
    };
    var symbolDisplay = function (sym) {
        var base = baseFromSymbol(sym);
        if (!base || base === sym) return sym;
        if ((sym || "").endsWith("USDT")) return base + "/USDT";
        if ((sym || "").endsWith("FDUSD")) return base + "/FDUSD";
        if ((sym || "").endsWith("BUSD")) return base + "/BUSD";
        return base + "/" + (sym.slice(base.length) || "USDT");
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
        var mini = window.marketStore && window.marketStore.getMini(symbol);
        var price = (mini && mini.last != null) ? mini.last : (window.marketStore && window.marketStore.getPrice ? window.marketStore.getPrice(symbol) : null);
        var changePct = mini && Number.isFinite(mini.changePct) ? mini.changePct : null;
        var priceDisplay = price != null && Number.isFinite(price) ? (typeof fmtCoinPrice === "function" ? fmtCoinPrice(price) : ("$" + Number(price).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 4 }))) : "—";
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
    symbols.forEach(function (symbol) {
        fetch(window.location.origin + '/api/spot/ticker_24h?symbol=' + encodeURIComponent(symbol))
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var price = parseFloat(data.lastPrice || 0);
                var changePct = parseFloat(data.priceChangePercent || 0);
                if (price <= 0 || !Number.isFinite(price)) return;
                var item = document.querySelector('#mobileTradeFavoritesList .mobile-trade-fav-item[data-symbol="' + symbol + '"]');
                if (!item) return;
                var priceRow = item.querySelector(".mobile-trade-fav-price-row");
                var changeSpan = item.querySelector(".mobile-trade-fav-change");
                if (!priceRow || !changeSpan) return;
                var oldPrice = parseFloat(priceRow.getAttribute("data-price") || "") || 0;
                var priceDisplay = typeof fmtCoinPrice === "function" ? fmtCoinPrice(price) : ("$" + Number(price).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 4 }));
                var changeStr = Number.isFinite(changePct) ? (changePct >= 0 ? "+" : "") + Number(changePct).toFixed(2) + "%" : "—";
                var changeColor = Number.isFinite(changePct) ? (changePct >= 0 ? "#0ecb81" : "#f6465d") : "var(--ds-text-secondary)";
                priceRow.setAttribute("data-price", price);
                priceRow.setAttribute("data-change-pct", changePct);
                var priceVal = priceRow.querySelector(".mobile-trade-fav-price-val");
                if (priceVal) priceVal.textContent = priceDisplay;
                changeSpan.textContent = changeStr;
                changeSpan.style.color = changeColor;
                if (Number.isFinite(oldPrice) && Math.abs(oldPrice - price) > 0.0001) {
                    priceRow.classList.remove("mobile-trade-fav-price-blink-up", "mobile-trade-fav-price-blink-down");
                    priceRow.classList.add(price > oldPrice ? "mobile-trade-fav-price-blink-up" : "mobile-trade-fav-price-blink-down");
                    setTimeout(function () {
                        priceRow.classList.remove("mobile-trade-fav-price-blink-up", "mobile-trade-fav-price-blink-down");
                    }, 700);
                }
            })
            .catch(function () {});
    });
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
                // Ortak KPI şeridi (bakiyeler): sadece Anasayfa, Binance, Botlar’da göster; Finansal Hesap, İletişim, Ayarlar’da gizle
                const unifiedStrip = document.getElementById('unifiedKpiStrip');
                if (unifiedStrip) {
                    const showStrip = (targetTab === 'reports' || targetTab === 'binance' || targetTab === 'trade' || targetTab === 'bots');
                    unifiedStrip.classList.toggle('kpi-strip-hidden', !showStrip);
                    unifiedStrip.style.display = showStrip ? 'block' : 'none';
                    if (targetTab === 'bots') unifiedStrip.classList.add('unified-kpi-bots-only');
                    else unifiedStrip.classList.remove('unified-kpi-bots-only');
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

                if (typeof renderPageErrorLog === 'function') renderPageErrorLog();
                if (targetTab === 'binance' && typeof renderAllSystemErrors === 'function') renderAllSystemErrors();

                // İşlem Geçmişi paneli: Anasayfa/Binance sekmesinde her zaman görünsün ve veri yüklensin
                var txPanel = document.getElementById("transactionHistoryPanel");
                if (targetTab === "binance" && txPanel) {
                    txPanel.style.display = "block";
                    if (State.accountId && typeof loadTransactionHistory === "function") {
                        loadTransactionHistory(State.txHistoryPeriod || "daily", State.txHistoryType || "buysell", State.txHistoryPage || 1, false);
                    }
                }

                // Special handling for binance tab (varlıklar + coin listesi + wallet 2sn poll)
                if (targetTab === "binance") {
                    updateBinanceConnectionNotice();
                    showActiveOrdersPanel(); // Panel her zaman görünsün; sayfa yenileyince kaybolmasın
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
                    window.intervalRegistry.stopByOwner("tab.trade");
                    window.intervalRegistry.start("tab.trade.prices", tickMobileTradeFavoritesPrices, 2000, "tab.trade");
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
var dmModalTahminFetchTs = 0;
var DM_MODAL_LIVE_PRICE_MS = 1500;
var DM_MODAL_TAHMIN_MIN_MS = 30000;  // Tahmin (high/low) en fazla 30s'de bir yenilensin
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
        if (strategy === "trdca_pro" && currentId !== "trdca_pro") return;
        if (strategy !== "trdca_pro" && currentId === "trdca_pro") return;
        if (strategy === "trdca_pro") {
            var qEl = document.getElementById("fTrdcaQuoteAsset");
            var bEl = document.getElementById("fTrdcaBotBalance");
            if (qEl && p.quote_asset) qEl.value = p.quote_asset;
            if (bEl && p.initial_capital_usdt != null) bEl.value = p.initial_capital_usdt;
            var trb = p.trb || {};
            var tw = trb.target_weights_all || {};
            var rows = document.querySelectorAll("#trdcaRebalanceRows .trdca-rebalance-symbol");
            rows.forEach(function (symEl, i) {
                var idx = symEl.getAttribute("data-idx");
                var pctEl = document.querySelector('.trdca-rebalance-pct[data-idx="' + idx + '"]');
                if (!pctEl) return;
                var keys = Object.keys(tw).filter(function (k) { return k && (k + "").toUpperCase() !== (p.quote_asset || "USDT"); });
                var k = keys[i];
                if (k != null && tw[k] != null) pctEl.value = (parseFloat(tw[k]) * 100).toFixed(1);
            });
            return;
        }
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
    dmModalLastChartSymbol = null;
    dmModalLastTahminSymbol = null;
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
    const fSymbol = document.getElementById("fSymbol");
    const dmSymbolSearchDropdown = document.getElementById("dmSymbolSearchDropdown");
    if (fSymbol) {
        let dmSymbolInputDebounce = null;
        fSymbol.addEventListener("focus", function () {
            ensureCoinListSearchSymbolsLoaded("all").then(function () { buildCoinListSearchSymbols(); });
        });
        fSymbol.addEventListener("input", function () {
            const v = (fSymbol.value || "").trim();
            clearTimeout(dmSymbolInputDebounce);
            if (v.length >= 2) {
                dmSymbolInputDebounce = setTimeout(function () {
                    ensureCoinListSearchSymbolsLoaded("all").then(function () {
                        buildCoinListSearchSymbols();
                        showCreateModalSymbolDropdown(v);
                    });
                }, 200);
            } else {
                hideCreateModalSymbolDropdown();
                if (v.length === 0) {
                    const strip = document.getElementById("dmSelectedPairStrip");
                    const tahminStrip = document.getElementById("dmTahminStrip");
                    if (strip) strip.style.display = "none";
                    if (tahminStrip) tahminStrip.style.display = "none";
                }
            }
        });
        fSymbol.addEventListener("blur", function () {
            setTimeout(hideCreateModalSymbolDropdown, 180);
        });
        // Enter: parite onayla → strip ve tahmin göster (dropdown açıksa ilk sonucu seç, yoksa yazılanı normalize et)
        fSymbol.addEventListener("keydown", function (e) {
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
        dmSymbolSearchDropdown.addEventListener("mousedown", function (e) { e.preventDefault(); });
        dmSymbolSearchDropdown.addEventListener("click", function (e) {
            const item = e.target.closest(".dm-symbol-search-item, .coin-list-search-item");
            if (!item) return;
            const symbol = item.getAttribute("data-symbol");
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
    document.getElementById("fTrdcaCoinCount")?.addEventListener("input", function (e) {
        buildTrdcaRebalanceRows(parseInt(e.target.value, 10) || 2);
    });
    document.getElementById("fTrdcaGridUpCount")?.addEventListener("input", function (e) {
        buildTrdcaGridUpRows(parseInt(e.target.value, 10) || 3);
    });
    document.getElementById("fTrdcaGridDownCount")?.addEventListener("input", function (e) {
        buildTrdcaGridDownRows(parseInt(e.target.value, 10) || 3);
    });
    function syncTrdcaGridLastRow(containerId, selector, excludeEl) {
        var container = document.getElementById(containerId);
        if (!container) return;
        var all = Array.from(container.querySelectorAll(selector));
        if (all.length < 2) return;
        var lastEl = all[all.length - 1];
        if (excludeEl === lastEl) return;
        var sumOthers = 0;
        for (var i = 0; i < all.length - 1; i++) sumOthers += parseFloat(all[i].value) || 0;
        var remainder = Math.max(0, Math.min(100, 100 - sumOthers));
        lastEl.value = remainder % 1 === 0 ? remainder.toFixed(0) : remainder.toFixed(1);
    }
    var trdcaGridUpEl = document.getElementById("trdcaGridUpRows");
    if (trdcaGridUpEl) {
        trdcaGridUpEl.addEventListener("input", function (e) {
            var t = e.target;
            if (t.classList.contains("trdca-grid-up-amt")) syncTrdcaGridLastRow("trdcaGridUpRows", ".trdca-grid-up-amt", t);
        });
    }
    var trdcaGridDownEl = document.getElementById("trdcaGridDownRows");
    if (trdcaGridDownEl) {
        trdcaGridDownEl.addEventListener("input", function (e) {
            var t = e.target;
            if (t.classList.contains("trdca-grid-down-amt")) syncTrdcaGridLastRow("trdcaGridDownRows", ".trdca-grid-down-amt", t);
        });
    }
    document.getElementById("fTrdcaQuoteAsset")?.addEventListener("change", updateTrdcaQuoteName);
    document.getElementById("fTrdcaBotBalance")?.addEventListener("input", updateTrdcaPreviews);
    (function () {
        var baseEl = document.getElementById("fTrdcaBasePct");
        var quoteEl = document.getElementById("fTrdcaQuotePctBar");
        if (baseEl) baseEl.addEventListener("input", function () {
            var v = parseFloat(baseEl.value);
            if (Number.isFinite(v) && v >= 0 && v <= 100 && quoteEl) {
                var other = Math.round(100 - v);
                if (parseFloat(quoteEl.value) !== other) quoteEl.value = other;
            }
        });
        if (quoteEl) quoteEl.addEventListener("input", function () {
            var v = parseFloat(quoteEl.value);
            if (Number.isFinite(v) && v >= 0 && v <= 100 && baseEl) {
                var other = Math.round(100 - v);
                if (parseFloat(baseEl.value) !== other) baseEl.value = other;
            }
        });
    })();
    var trdcaRowsEl = document.getElementById("trdcaRebalanceRows");
    var dmTrdcaSymbolInputDebounce = null;
    if (trdcaRowsEl) {
        trdcaRowsEl.addEventListener("focusin", function (e) {
            var input = e.target.closest(".trdca-rebalance-symbol");
            if (!input) return;
            if (currentSelectedTemplate && currentSelectedTemplate.id === "trdca_pro") {
                ensureCoinListSearchSymbolsLoaded("all").then(function () { buildCoinListSearchSymbols(); });
            }
        });
        trdcaRowsEl.addEventListener("input", function (e) {
            var pctInput = e.target.closest(".trdca-rebalance-pct");
            if (pctInput) {
                var all = Array.from(document.querySelectorAll("#trdcaRebalanceRows .trdca-rebalance-pct"));
                if (all.length >= 2) {
                    var lastIdx = Math.max.apply(null, all.map(function (el) { return parseInt(el.getAttribute("data-idx") || "0", 10); }));
                    var lastEl = all.find(function (el) { return parseInt(el.getAttribute("data-idx") || "0", 10) === lastIdx; }) || all[all.length - 1];
                    if (pctInput !== lastEl) {
                        var sumOthers = 0;
                        all.forEach(function (el) {
                            if (el !== lastEl) sumOthers += parseFloat(el.value) || 0;
                        });
                        var remainder = Math.max(0, Math.min(100, 100 - sumOthers));
                        if (parseFloat(lastEl.value) !== remainder) lastEl.value = remainder % 1 === 0 ? remainder.toFixed(0) : remainder.toFixed(1);
                    }
                }
                updateTrdcaPctTotal();
                updateTrdcaPreviews();
                return;
            }
            var input = e.target.closest(".trdca-rebalance-symbol");
            if (!input) return;
            updateTrdcaPreviews();
            var v = (input.value || "").trim();
            clearTimeout(dmTrdcaSymbolInputDebounce);
            if (v.length >= 2) {
                dmTrdcaSymbolInputDebounce = setTimeout(function () {
                    ensureCoinListSearchSymbolsLoaded("all").then(function () {
                        buildCoinListSearchSymbols();
                        showMultiSymbolSearchDropdown(v, input);
                    });
                }, 200);
            } else {
                hideMultiSymbolSearchDropdown();
            }
        });
        trdcaRowsEl.addEventListener("change", function (e) {
            var pctInput = e.target.closest(".trdca-rebalance-pct");
            if (pctInput) {
                var all = Array.from(document.querySelectorAll("#trdcaRebalanceRows .trdca-rebalance-pct"));
                if (all.length >= 2) {
                    var lastIdx = Math.max.apply(null, all.map(function (el) { return parseInt(el.getAttribute("data-idx") || "0", 10); }));
                    var lastEl = all.find(function (el) { return parseInt(el.getAttribute("data-idx") || "0", 10) === lastIdx; }) || all[all.length - 1];
                    if (pctInput !== lastEl) {
                        var sumOthers = 0;
                        all.forEach(function (el) {
                            if (el !== lastEl) sumOthers += parseFloat(el.value) || 0;
                        });
                        var remainder = Math.max(0, Math.min(100, 100 - sumOthers));
                        if (parseFloat(lastEl.value) !== remainder) lastEl.value = remainder % 1 === 0 ? remainder.toFixed(0) : remainder.toFixed(1);
                    }
                }
            }
            updateTrdcaPctTotal();
            updateTrdcaPreviews();
        });
        trdcaRowsEl.addEventListener("focusout", function (e) {
            if (e.relatedTarget && e.relatedTarget.closest && e.relatedTarget.closest("#dmMultiSymbolSearchDropdown")) return;
            setTimeout(function () {
                hideMultiSymbolSearchDropdown();
                var input = e.target;
                if (input && input.classList && input.classList.contains("trdca-rebalance-symbol")) {
                    var v = (input.value || "").trim();
                    if (v.length >= 2) updateTrdcaPreviews();
                }
            }, 180);
        });
        trdcaRowsEl.addEventListener("keydown", function (e) {
            var input = e.target.closest(".trdca-rebalance-symbol");
            if (!input || e.key !== "Enter") return;
            var dropdown = document.getElementById("dmMultiSymbolSearchDropdown");
            var firstItem = dropdown && dropdown.querySelector(".dm-multi-symbol-item, .coin-list-search-item");
            if (firstItem && dropdown && dropdown.style.display !== "none") {
                var symbol = firstItem.getAttribute("data-symbol");
                if (symbol) {
                    var base = symbol.replace(/USDT$/, "").replace(/FDUSD$/, "");
                    input.value = base;
                    hideMultiSymbolSearchDropdown();
                    updateTrdcaPreviews();
                    e.preventDefault();
                }
            }
        });
    }

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
            if (_dmMultiSearchTargetInput.classList.contains("trdca-rebalance-symbol")) {
                updateTrdcaPreviews();
            } else {
                var idx = _dmMultiSearchTargetIdx;
                if (idx != null) updateMultiAssetPreview(idx, symbol);
            }
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
    if (!symbol || typeof symbol !== 'string') return { base: '', quote: 'USDT' };
    const s = symbol.toUpperCase().replace(/\s/g, '');
    if (s.endsWith('USDT')) return { base: s.slice(0, -4) || '', quote: 'USDT' };
    if (s.endsWith('FDUSD')) return { base: s.slice(0, -5) || '', quote: 'FDUSD' };
    if (s.endsWith('BTC')) return { base: s.slice(0, -3) || '', quote: 'BTC' };
    if (s.endsWith('ETH')) return { base: s.slice(0, -3) || '', quote: 'ETH' };
    if (s.endsWith('BNB')) return { base: s.slice(0, -3) || '', quote: 'BNB' };
    return { base: s, quote: 'USDT' };
}

/** Create bot modal: seçilen parite strip'ini (logo, fiyat, 24h %, grafik) ve tahmin alanını güncelle */
function updateCreateBotModalPairStrip(symbol) {
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
    const pct = mini && mini.changePct != null ? mini.changePct : null;
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
    if (changeEl) {
        if (pct != null && Number.isFinite(pct)) {
            var newPctStr = (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%';
            var newColor = pct >= 0 ? '#0ecb81' : '#f6465d';
            if (changeEl.textContent !== newPctStr || changeEl.style.color !== newColor) {
                dmModalLastPct = pct;
                changeEl.textContent = newPctStr;
                changeEl.style.color = newColor;
            }
        } else {
            if (changeEl.textContent !== '—') {
                changeEl.textContent = '—';
                changeEl.style.color = '';
                dmModalLastPct = null;
            }
        }
    }
    // Grafik sadece sembol değiştiğinde yeniden yüklensin (her tick'te yüklemek flicker yapıyor)
    if (sym !== dmModalLastChartSymbol) {
        dmModalLastChartSymbol = sym;
        loadCreateBotModalChart(sym);
    }
    updateCreateBotModalTahmin(sym, mini, quote);
    // Canlı fiyat: modal açık ve sembol seçiliyse periyodik güncelleme başlat
    if (!dmModalLivePriceIntervalId && document.getElementById('dmModal') && document.getElementById('dmModal').style.display !== 'none') {
        dmModalLivePriceIntervalId = setInterval(function () {
            var modal = document.getElementById('dmModal');
            var fSym = document.getElementById('fSymbol');
            if (!modal || modal.style.display === 'none' || !fSym || !fSym.value.trim()) return;
            var currentSym = normalizeModalSymbol(fSym.value.trim());
            if (currentSym.normalized) updateCreateBotModalPairStrip(currentSym.normalized);
        }, DM_MODAL_LIVE_PRICE_MS);
    }
}

/** Create bot modal: Tahmin alanını (24s değişim, yüksek/düşük) doldur. High/low API en fazla 30s'de bir (flicker önleme). */
function updateCreateBotModalTahmin(symbol, mini, quoteAsset) {
    const changeEl = document.getElementById('dmTahminChange');
    const highEl = document.getElementById('dmTahminHigh');
    const lowEl = document.getElementById('dmTahminLow');
    const formatPrice = (v) => (v != null && Number.isFinite(v) && v > 0) ? (quoteAsset === 'USDT' ? fmtUsd(v) : fmtNum(v, 8)) : '—';
    if (changeEl) {
        const pct = mini && mini.changePct != null ? mini.changePct : null;
        if (pct != null && Number.isFinite(pct)) {
            changeEl.textContent = (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%';
            changeEl.style.color = pct >= 0 ? '#0ecb81' : '#f6465d';
        } else {
            changeEl.textContent = '—';
            changeEl.style.color = '';
        }
    }
    if (!symbol) return;
    var now = Date.now();
    var symbolChanged = symbol !== dmModalLastTahminSymbol;
    var stale = (now - dmModalTahminFetchTs) >= DM_MODAL_TAHMIN_MIN_MS;
    if (!symbolChanged && !stale) return;
    dmModalLastTahminSymbol = symbol;
    dmModalTahminFetchTs = now;
    if (highEl) highEl.textContent = '—';
    if (lowEl) lowEl.textContent = '—';
    window.apiClient.get('/api/spot/klines?symbol=' + encodeURIComponent(symbol) + '&interval=5m&limit=288').then(function (data) {
        if (Array.isArray(data) && data.length > 0) {
            const low = Math.min(...data.map(k => Number(k.l)));
            const high = Math.max(...data.map(k => Number(k.h)));
            if (highEl) highEl.textContent = formatPrice(high);
            if (lowEl) lowEl.textContent = formatPrice(low);
        }
    }).catch(function () {});
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

/** Create modal: sembol arama dropdown göster (fSymbol için) */
function showCreateModalSymbolDropdown(query) {
    const dropdown = document.getElementById('dmSymbolSearchDropdown');
    if (!dropdown) return;
    const q = (query || '').trim().toUpperCase();
    if (!q || q.length < 2) {
        dropdown.style.display = 'none';
        return;
    }
    function quoteOrder(sym) {
        if ((sym || '').endsWith('USDT')) return 0;
        if ((sym || '').endsWith('FDUSD')) return 1;
        return 2;
    }
    let list = coinListSearchAllSymbols.length > 0
        ? coinListSearchAllSymbols.filter(x => (x.symbol || '').toUpperCase().includes(q)).slice(0, 40)
        : (window.marketStore && window.marketStore.getAllMini && window.marketStore.getAllMini()) ? (window.marketStore.getAllMini() || [])
            .filter(m => {
                const s = (m.symbol || '').toUpperCase();
                return (s.endsWith('USDT') || s.endsWith('FDUSD')) && s.includes(q);
            })
            .slice(0, 40)
            .map(m => ({ symbol: (m.symbol || '').toUpperCase(), last: m.last, changePct: m.changePct }))
        : [];
    list = list.sort((a, b) => {
        const qA = quoteOrder(a.symbol);
        const qB = quoteOrder(b.symbol);
        if (qA !== qB) return qA - qB;
        return (a.symbol || '').localeCompare(b.symbol || '');
    });
    if (list.length === 0) {
        dropdown.innerHTML = '<div style="padding: 1rem; color: var(--ds-text-secondary); font-size: 0.9rem;">Sonuç yok. Pariteyi elle yazın (örn. BTCUSDT).</div>';
        dropdown.style.display = 'block';
        return;
    }
    dropdown.innerHTML = list.map(item => {
        const sym = item.symbol || '';
        const priceStr = item.last != null && Number.isFinite(item.last) ? fmtUsd(item.last) : '…';
        const pct = item.changePct != null && Number.isFinite(item.changePct) ? item.changePct : null;
        const pctStr = pct != null ? (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%' : '—';
        const pctColor = pct != null ? (pct >= 0 ? '#0ecb81' : '#f6465d') : 'var(--ds-text-secondary)';
        return '<div class="coin-list-search-item dm-symbol-search-item" data-symbol="' + sym + '" style="padding: 0.6rem 1rem; cursor: pointer; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--ds-border);"><span style="font-weight: 600;">' + sym + '</span><span style="display: flex; gap: 1rem;"><span>' + priceStr + '</span><span style="color: ' + pctColor + '">' + pctStr + '</span></span></div>';
    }).join('');
    dropdown.style.display = 'block';
}

function hideCreateModalSymbolDropdown() {
    const dropdown = document.getElementById('dmSymbolSearchDropdown');
    if (dropdown) dropdown.style.display = 'none';
}

var _dmMultiSearchTargetInput = null;
var _dmMultiSearchTargetIdx = null;

function showMultiSymbolSearchDropdown(query, anchorInputEl) {
    const dropdown = document.getElementById('dmMultiSymbolSearchDropdown');
    if (!dropdown || !anchorInputEl) return;
    const q = (query || '').trim().toUpperCase();
    if (!q || q.length < 2) {
        dropdown.style.display = 'none';
        return;
    }
    _dmMultiSearchTargetInput = anchorInputEl;
    _dmMultiSearchTargetIdx = anchorInputEl.getAttribute('data-idx');
    function quoteOrder(sym) {
        if ((sym || '').endsWith('USDT')) return 0;
        if ((sym || '').endsWith('FDUSD')) return 1;
        return 2;
    }
    var list = coinListSearchAllSymbols.length > 0
        ? coinListSearchAllSymbols.filter(function (x) { return (x.symbol || '').toUpperCase().includes(q); }).slice(0, 40)
        : (window.marketStore && window.marketStore.getAllMini && window.marketStore.getAllMini()) ? (window.marketStore.getAllMini() || [])
            .filter(function (m) {
                var s = (m.symbol || '').toUpperCase();
                return (s.endsWith('USDT') || s.endsWith('FDUSD')) && s.includes(q);
            })
            .slice(0, 40)
            .map(function (m) { return { symbol: (m.symbol || '').toUpperCase(), last: m.last, changePct: m.changePct }; })
        : [];
    list = list.sort(function (a, b) {
        var qA = quoteOrder(a.symbol);
        var qB = quoteOrder(b.symbol);
        if (qA !== qB) return qA - qB;
        return (a.symbol || '').localeCompare(b.symbol || '');
    });
    if (list.length === 0) {
        dropdown.innerHTML = '<div style="padding: 1rem; color: var(--ds-text-secondary); font-size: 0.9rem;">Sonuç yok. Sembolü elle yazın (örn. BTC).</div>';
        dropdown.style.display = 'block';
    } else {
        dropdown.innerHTML = list.map(function (item) {
            var sym = item.symbol || '';
            var priceStr = item.last != null && Number.isFinite(item.last) ? fmtUsd(item.last) : '…';
            var pct = item.changePct != null && Number.isFinite(item.changePct) ? item.changePct : null;
            var pctStr = pct != null ? (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%' : '—';
            var pctColor = pct != null ? (pct >= 0 ? '#0ecb81' : '#f6465d') : 'var(--ds-text-secondary)';
            return '<div class="coin-list-search-item dm-multi-symbol-item" data-symbol="' + sym + '" style="padding: 0.6rem 1rem; cursor: pointer; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--ds-border);"><span style="font-weight: 600;">' + sym + '</span><span style="display: flex; gap: 1rem;"><span>' + priceStr + '</span><span style="color: ' + pctColor + '">' + pctStr + '</span></span></div>';
        }).join('');
        dropdown.style.display = 'block';
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
    if (currentSelectedTemplate && currentSelectedTemplate.id === "trdca_pro") {
        var quote_asset = (document.getElementById("fTrdcaQuoteAsset") && document.getElementById("fTrdcaQuoteAsset").value || "USDT").trim().toUpperCase();
        var tick_interval_ms = 1000;
        var botBalance = parseFloat(document.getElementById("fTrdcaBotBalance") && document.getElementById("fTrdcaBotBalance").value);
        var initial_capital_usdt = Number.isFinite(botBalance) && botBalance > 0 ? botBalance : 0;

        var target_weights_all = {};
        var basePctSum = 0;
        var baseCoins = [];
        document.querySelectorAll("#trdcaRebalanceRows .trdca-rebalance-symbol").forEach(function (symEl) {
            var idx = symEl.getAttribute("data-idx");
            var pctEl = document.querySelector('.trdca-rebalance-pct[data-idx="' + idx + '"]');
            var sym = (symEl.value || "").trim().toUpperCase().replace(quote_asset, "") || null;
            var pct = pctEl ? (parseFloat(pctEl.value) || 0) : 0;
            if (sym && sym.length >= 2) {
                target_weights_all[sym] = pct / 100;
                basePctSum += pct;
                baseCoins.push({ symbol: sym, pct: pct });
            }
        });
        var trdcaQuotePct = Math.max(0, 100 - basePctSum);
        target_weights_all[quote_asset] = trdcaQuotePct / 100;

        var coin_weights = {};
        if (basePctSum > 0) {
            baseCoins.forEach(function (c) {
                coin_weights[c.symbol] = c.pct / basePctSum;
            });
        }
        if (Object.keys(coin_weights).length === 0) coin_weights = { BTC: 0.3, ETH: 0.3, SOL: 0.2, AVAX: 0.2 };

        var upPos = [], upAmt = [], downPos = [], downAmt = [];
        var trdcaUpCount = document.querySelectorAll("#trdcaGridUpRows .trdca-grid-up-pos").length || 3;
        var trdcaDownCount = document.querySelectorAll("#trdcaGridDownRows .trdca-grid-down-pos").length || 3;
        var defUpPct = 100 / trdcaUpCount;
        var defDownPct = 100 / trdcaDownCount;
        document.querySelectorAll("#trdcaGridUpRows .trdca-grid-up-pos").forEach(function (el, i) {
            var v = parseFloat(el.value);
            upPos.push(Number.isFinite(v) && v >= 0 ? v : (i + 1));
        });
        document.querySelectorAll("#trdcaGridUpRows .trdca-grid-up-amt").forEach(function (el) {
            var v = parseFloat(el.value);
            upAmt.push(Number.isFinite(v) && v >= 0 ? v : defUpPct);
        });
        document.querySelectorAll("#trdcaGridDownRows .trdca-grid-down-pos").forEach(function (el, i) {
            var v = parseFloat(el.value);
            downPos.push(Number.isFinite(v) && v >= 0 ? v : (i + 1));
        });
        document.querySelectorAll("#trdcaGridDownRows .trdca-grid-down-amt").forEach(function (el) {
            var v = parseFloat(el.value);
            downAmt.push(Number.isFinite(v) && v >= 0 ? v : defDownPct);
        });
        var grid_up_levels_pct = upPos.map(function (p) { return Number.isFinite(p) && p >= 0 ? p : 0; });
        var grid_down_levels_pct = downPos.map(function (p) { return Number.isFinite(p) && p >= 0 ? p : 0; });
        var balanceForGrid = initial_capital_usdt > 0 ? initial_capital_usdt : 10000;
        var grid_up_notional_usdt = upAmt.map(function (p) { return Math.max(10, balanceForGrid * p / 100); });
        var grid_down_notional_usdt = downAmt.map(function (p) { return Math.max(10, balanceForGrid * p / 100); });
        if (!grid_up_levels_pct.length) grid_up_levels_pct = [1, 2, 3];
        if (!grid_down_levels_pct.length) grid_down_levels_pct = [1, 2, 3];
        if (!grid_up_notional_usdt.length) grid_up_notional_usdt = [200, 200, 200];
        if (!grid_down_notional_usdt.length) grid_down_notional_usdt = [200, 200, 200];

        var gridTrailPct = parseFloat(document.getElementById("fTrdcaGridTrailPct") && document.getElementById("fTrdcaGridTrailPct").value) || 0.8;
        var sell_trail_back_pct = gridTrailPct;
        var buy_trail_up_pct = gridTrailPct;
        var buy_buffer_pct = 0.2;
        var kar_alim_tetik_pct = parseFloat(document.getElementById("fTrdcaKarAlimTetikPct") && document.getElementById("fTrdcaKarAlimTetikPct").value) || 2;
        var kar_alim_trail_pct = parseFloat(document.getElementById("fTrdcaKarAlimTrailPct") && document.getElementById("fTrdcaKarAlimTrailPct").value) || 0.8;

        var gap_arm_pct = parseFloat(document.getElementById("fTrdcaGapArmPct") && document.getElementById("fTrdcaGapArmPct").value) || 3;
        var trail_back_pct = parseFloat(document.getElementById("fTrdcaTrailBackPct") && document.getElementById("fTrdcaTrailBackPct").value) || 0.6;
        var min_leg_notional_usdt = 10;

        return {
            account_id: State.accountId,
            symbol: "MULTI",
            strategy_id: "trdca_pro",
            quote_asset: quote_asset,
            initial_capital_usdt: initial_capital_usdt,
            bot_budget_usdt: initial_capital_usdt,
            tick_interval_ms: tick_interval_ms,
            execution: { ack_timeout_sec: 5 },
            dca: {
                enabled: true,
                coin_weights: coin_weights,
                grid_up_levels_pct: grid_up_levels_pct.length ? grid_up_levels_pct : [1, 2, 3],
                grid_down_levels_pct: grid_down_levels_pct.length ? grid_down_levels_pct : [1, 2, 3],
                grid_up_notional_usdt: grid_up_notional_usdt,
                grid_down_notional_usdt: grid_down_notional_usdt,
                grid_up_notional_pct: upAmt,
                grid_down_notional_pct: downAmt,
                sell_trail_back_pct: sell_trail_back_pct,
                buy_trail_up_pct: buy_trail_up_pct,
                buy_buffer_pct: buy_buffer_pct,
                post_sell: { dip_trigger_pct: kar_alim_tetik_pct, dip_trail_up_pct: kar_alim_trail_pct, dip_buy_notional_usdt: 200 },
                post_buy: { profit_trigger_pct: kar_alim_tetik_pct, profit_sell_trail_back_pct: kar_alim_trail_pct, profit_sell_notional_usdt: 200 }
            },
            trb: {
                enabled: true,
                target_weights_all: target_weights_all,
                small_eps_pct: 0.8,
                min_leg_notional_usdt: min_leg_notional_usdt,
                gap_arm_pct: gap_arm_pct,
                trail_back_pct: trail_back_pct,
                max_batch_legs: 8,
                sell_first: true,
                step_mode: "SELL_ONLY_THEN_BUY",
                batch_atomicity: "SOFT",
                partial_fill_behavior: "SAFE_STOP",
                max_exec_delay_sec: 15,
                ts_bucket_sec: 5,
                gap_peak_bucket_dp: 2
            }
        };
    }
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
    if (payload.strategy_id === "trdca_pro") {
        if (!payload.quote_asset || payload.quote_asset.length < 2) return "Quote varlık seçin";
        var trb = payload.trb || {};
        var tw2 = trb.target_weights_all || {};
        var sum2 = Object.keys(tw2).reduce(function (s, k) { return s + (parseFloat(tw2[k]) || 0); }, 0);
        if (Math.abs(sum2 - 1) > 0.02) return "Rebalancing dağılımı toplamı %100 olmalı (coinler + kalan quote).";
        var baseKeys = Object.keys(tw2).filter(function (k) { return k && (k.toUpperCase() !== (payload.quote_asset || "USDT")); });
        if (baseKeys.length < 2) return "En az 2 coin girin ve dağılım % girin.";
        var baseSum = baseKeys.reduce(function (s, k) { return s + (parseFloat(tw2[k]) || 0); }, 0);
        if (baseSum <= 0) return "En az bir base coin için hedef dağılım % girin (0'dan büyük). Aksi halde bot alım yapmaz.";
        var dca = payload.dca || {};
        var cw = dca.coin_weights || {};
        var sumDca = Object.keys(cw).reduce(function (s, k) { return s + (parseFloat(cw[k]) || 0); }, 0);
        if (Math.abs(sumDca - 1) > 0.02 && Object.keys(cw).length > 0) return "DCA coin ağırlıkları (otomatik) toplamı 1 olmalı.";
        return null;
    }
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
    const isTrdca = currentSelectedTemplate && currentSelectedTemplate.id === "trdca_pro";
    const errorEl = isTrdca ? document.getElementById("createBotErrorTrdca") : document.getElementById("createBotError");
    if (errorEl) errorEl.style.display = "none";
    
    const payload = collectForm();
    const error = validateForm(payload);
    
    if (error) {
        showCreateBotFormError(errorEl, error);
        return;
    }

    var requestedBudget = 0;
    var quoteAsset = "USDT";
    if (payload.strategy_id === "trdca_pro") {
        requestedBudget = Number(payload.initial_capital_usdt || payload.bot_budget_usdt) || 0;
        quoteAsset = (payload.quote_asset || "USDT").toString().trim().toUpperCase() || "USDT";
    } else {
        requestedBudget = Number(payload.budget_usd) || 0;
        try {
            var pq = parseBaseQuote(payload.symbol || "");
            quoteAsset = (pq && pq.quote) ? pq.quote : "USDT";
        } catch (e) { quoteAsset = "USDT"; }
    }
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

/** Modal için sembol normalize; USDT/USD → USDTUSD (Binance'te geçerli). Sadece base===quote (USDTUSDT) geçersiz. */
function normalizeModalSymbol(symbol) {
    if (!symbol || typeof symbol !== 'string') return { normalized: '', invalid: true };
    const s = String(symbol).replace(/[\s\/\-]/g, '').toUpperCase();
    if (!s) return { normalized: '', invalid: true };
    if (s === 'USDTUSDT') return { normalized: 'USDTUSDT', invalid: true };
    if (s.endsWith('USDT')) {
        const base = s.slice(0, -4) || '';
        if (base === 'USDT' || !base) return { normalized: s, invalid: true };
    }
    const invalidSet = new Set(['USDTUSDT', 'USDCUSDT', 'FDUSDUSDT', 'BUSDUSDT', 'TUSDUSDT', 'DAIUSDT']);
    return { normalized: s, invalid: invalidSet.has(s) };
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
    var totalUsd = coerceNumber(payload.total_usd);
    var freeUsd = coerceNumber(payload.free_usd);
    var lockedUsd = coerceNumber(payload.locked_usd);
    var botLockedUsd = coerceNumber(payload.bot_locked_usd);
    var availableUsd = coerceNumber(payload.available_usd);
    var keysConfigured = payload.keys_configured !== false;
    var assets = Array.isArray(payload.assets) ? payload.assets : [];
    // Bootstrap/minimal wallet uses usdt_value per asset; UI expects total_usd (so list and filter work)
    assets = assets.map(function (a) {
        if (!a || typeof a !== 'object') return a;
        var out = Object.assign({}, a);
        if (out.total_usd == null && out.usdt_value != null) out.total_usd = Number(out.usdt_value);
        return out;
    });
    var ts = payload.ts != null ? (typeof payload.ts === 'number' ? payload.ts : (typeof payload.ts === 'string' ? new Date(payload.ts).getTime() : Date.now())) : Date.now();
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
    assetsState.wallet.data_status = payload.data_status || (err ? 'error' : 'fresh');
    assetsState.wallet.keysMessage = payload.message || null;
    assetsState.wallet.unpriced_assets = Array.isArray(payload.unpriced_assets) ? payload.unpriced_assets : [];
    pushWalletEvent({ source: source, status: status, total_usd: totalUsd, asset_count: assets.length, request_id: meta.request_id, note: meta.note });
    if (window.BinanceAssetsPanel?.render) window.BinanceAssetsPanel.render();
    if (typeof renderVarliklarList === 'function') renderVarliklarList();
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

function hashWalletAssets(assets) {
    if (!Array.isArray(assets)) return '';
    // Round to 8 decimals to avoid re-render flicker from float noise in API responses
    const round8 = (v) => (v != null && Number.isFinite(Number(v))) ? Number(Number(v).toFixed(8)) : v;
    const rows = assets.map(a => [a.asset, round8(a.free), round8(a.locked), round8(a.bot_locked), round8(a.available)]).sort((a, b) => (a[0] || '').localeCompare(b[0] || ''));
    return JSON.stringify(rows);
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

/** TEK KAYNAK: marketStore. dataHub kullanılmaz. */
function getAssetPrice(asset) {
    const symbol = normalizeAssetToSymbol(asset, QUOTE);
    if (asset === 'USDT' || asset === 'USDC' || asset === 'FDUSD' || asset === 'BUSD' || asset === 'TUSD' || asset === 'DAI') return 1;
    return window.marketStore?.getPrice(symbol) ?? null;
}

async function pollWallet(isManualRefresh = false) {
    if (!State.accountId) return;
    if (walletPollInflight && !isManualRefresh) return;
    if (!isManualRefresh && Date.now() < walletPollBackoffUntil) return; // 429 backoff
    walletPollInflight = true;

    const body = document.getElementById("varliklarTableBody");
    const empty = document.getElementById("varliklarEmpty");
    let didUpdateBody = false;
    const isFirst = assetsState.wallet.status === 'idle' || isManualRefresh;
    if (body && isFirst) { body.innerHTML = LOADING_HTML_VARLIKLAR; didUpdateBody = true; }
    if (empty) empty.style.display = 'none';
    if (isFirst) assetsState.wallet.status = 'loading';
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
    const walletLoading = assetsState.wallet.status === 'idle' || assetsState.wallet.status === 'loading';
    if (walletLoading) {
        const loadingText = 'Yükleniyor…';
        if (totalEl) totalEl.textContent = loadingText;
        if (freeEl) freeEl.textContent = loadingText;
        if (lockedEl) lockedEl.textContent = loadingText;
        if (stripAvailable) { stripAvailable.textContent = loadingText; stripAvailable.classList.add('binance-assets-strip-value--loading'); }
        if (stripBotLocked) { stripBotLocked.textContent = loadingText; stripBotLocked.classList.add('binance-assets-strip-value--loading'); }
        if (stripLocked) { stripLocked.textContent = loadingText; stripLocked.classList.add('binance-assets-strip-value--loading'); }
        if (lastEl) lastEl.textContent = '—';
        if (staleEl) staleEl.style.display = 'none';
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
    if (availableUsd == null && (assetsState.wallet.assets || []).length) {
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
    if (stripAvailable) { stripAvailable.classList.remove('binance-assets-strip-value--loading'); stripAvailable.textContent = fmtUsd(availableUsd != null ? availableUsd : freeUsd); triggerValueBlink(stripAvailable, availableUsd != null ? availableUsd : freeUsd); }
    if (stripBotLocked) { stripBotLocked.classList.remove('binance-assets-strip-value--loading'); stripBotLocked.textContent = fmtUsd(botLockedUsd != null ? botLockedUsd : 0); triggerValueBlink(stripBotLocked, botLockedUsd != null ? botLockedUsd : 0); }
    if (stripLocked) { stripLocked.classList.remove('binance-assets-strip-value--loading'); stripLocked.textContent = fmtUsd(lockedUsd); triggerValueBlink(stripLocked, lockedUsd); }
    if (lastEl) lastEl.textContent = assetsState.wallet.ts ? new Date(assetsState.wallet.ts).toLocaleTimeString('tr-TR') : '—';
    if (staleEl) {
        staleEl.style.display = assetsState.prices.data_status === 'stale' ? 'inline' : 'none';
        staleEl.textContent = 'Güncel değil';
    }
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
    if (window.BinanceUI && document.getElementById("tabBinance")?.classList.contains("is-active")) {
        return;
    }
    const body = document.getElementById("varliklarTableBody");
    if (!body) return;
    const rows = body.querySelectorAll('tr[data-asset]');
    if (!window.binancePriceCache) window.binancePriceCache = {};
    requestAnimationFrame(() => {
        rows.forEach(row => {
            const asset = row.getAttribute('data-asset');
            const symbol = row.getAttribute('data-symbol');
            const priceCell = row.querySelector('.price-cell');
            const valueCell = row.querySelector('.value-cell');
            if (!priceCell || !valueCell) return;
            const price = getAssetPrice(asset);
            const oldPrice = parseFloat(priceCell.getAttribute('data-price') || '') || 0;
            if (price == null || !Number.isFinite(price)) {
                if (priceCell.textContent !== '…') priceCell.textContent = '…';
                return;
            }
            const samePrice = Number.isFinite(oldPrice) && Math.abs(oldPrice - price) < 1e-9;
            if (!samePrice && Math.abs(oldPrice - price) > 0.0001 && typeof triggerValueBlink === 'function') {
                triggerValueBlink(priceCell, price);
            }
            priceCell.setAttribute('data-price', price);
            priceCell.textContent = fmtCoinPrice(price);
            // Value cell: do NOT recalculate (stays from backend); avoids USD valuation drift
            if (!samePrice && Math.abs(oldPrice - price) > 0.0001) {
                priceCell.classList.remove('price-up', 'price-down', 'price-neutral');
                priceCell.classList.add(price > oldPrice ? 'price-up' : 'price-down');
                setTimeout(() => { priceCell.classList.remove('price-up', 'price-down'); priceCell.classList.add('price-neutral'); }, 600);
            }
            window.binancePriceCache[asset] = price;
        });
        renderAssetsSummary();
    });
}

const BinanceAssetsPanel = {
    render() {
        renderAssetsSummary();
        if (assetsState.wallet.status === 'loading' || assetsState.wallet.status === 'idle') return;
        if (assetsState.wallet.status === 'error' && !(assetsState.wallet.assets?.length)) {
            if (typeof renderVarliklarList === 'function') renderVarliklarList();
            return;
        }
        const h = hashWalletAssets(assetsState.wallet.assets);
        if (h !== lastWalletHash) { lastWalletHash = h; if (typeof renderVarliklarList === 'function') renderVarliklarList(); }
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

function getAssetChangePct(asset) {
    const symbol = normalizeAssetToSymbol(asset, QUOTE);
    const mini = window.marketStore?.getMini(symbol);
    return mini && Number.isFinite(mini.changePct) ? mini.changePct : null;
}

function renderVarliklarList() {
    const tbody = document.getElementById('varliklarTableBody');
    const emptyEl = document.getElementById('varliklarEmpty');
    if (!tbody) return;
    const assets = assetsState.wallet.assets || [];
    const list = assets.filter(a => !isWalletAssetSuspiciousFx(a)).map(a => {
        const total = (a.free || 0) + (a.locked || 0);
        const valueUsd = (a.total_usd != null && Number.isFinite(Number(a.total_usd))) ? Number(a.total_usd) : null;
        const price = getAssetPrice(a.asset);
        return { ...a, _price: price, _valueUsd: valueUsd != null ? valueUsd : 0, _total: total };
    }).filter(x => (x.total_usd != null ? Number(x.total_usd) : 0) >= VARLIKLAR_MIN_USD);
    list.sort((a, b) => (b.total_usd != null ? Number(b.total_usd) : 0) - (a.total_usd != null ? Number(a.total_usd) : 0));
    const totalPortfolio = typeof assetsState.wallet.total_usd === 'number' ? assetsState.wallet.total_usd : list.reduce((sum, x) => sum + (x._valueUsd || 0), 0);

    if (list.length === 0) {
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

    function rowData(a) {
        const asset = a.asset || 'N/A';
        const symbol = normalizeAssetToSymbol(asset, QUOTE);
        const free = a.free || 0;
        const locked = a.locked || 0;
        const botLocked = Number(a.bot_locked) || 0;
        const available = (a.available != null && Number.isFinite(Number(a.available))) ? Number(a.available) : Math.max(0, free - botLocked);
        const total = a._total || 0;
        const price = a._price;
        const valueUsd = a._valueUsd != null ? a._valueUsd : 0;
        const valueDisplay = (a.total_usd != null && Number.isFinite(Number(a.total_usd))) ? fmtUsd(Number(a.total_usd)) : '—';
        const pctPortfolio = totalPortfolio > 0 && valueUsd != null ? (valueUsd / totalPortfolio * 100).toFixed(2) : '0.00';
        const priceDisplay = price != null && Number.isFinite(price) ? fmtCoinPrice(price) : '…';
        const changePct = getAssetChangePct(asset);
        const changeStr = changePct != null ? (changePct >= 0 ? '+' : '') + changePct.toFixed(2) + '%' : '—';
        const changeColor = changePct != null ? (changePct >= 0 ? '#0ecb81' : '#f6465d') : 'var(--ds-text-secondary)';
        const name = assetNameMap[asset] || asset;
        const initials = logoInitials(a);
        const logoUrl = (typeof getCoinLogoUrl === 'function' && getCoinLogoUrl(a.asset)) || null;
        const canSell = available > 0;
        const isQuote = (asset || '').toUpperCase() === 'USDT' || (asset || '').toUpperCase() === 'BUSD' || (asset || '').toUpperCase() === 'FDUSD';
        const canBuy = isQuote ? available > 0 : true;
        const sellTitle = canSell ? 'Satış (kullanılabilir: ' + fmtNum(available, 8) + ')' : 'Satış yapılamaz: tutar bot veya açık emirde kilitli';
        const buyTitle = canBuy ? 'Alış' : 'Alış yapılamaz: kullanılabilir bakiye yok (bot/emir kilitli)';
        const sellDisabled = !canSell ? ' disabled' : '';
        const buyDisabled = !canBuy ? ' disabled' : '';
        return { asset, symbol, free, locked, botLocked, available, total, price, valueUsd, valueDisplay, pctPortfolio, priceDisplay, changePct, changeStr, changeColor, name, initials, logoUrl, canSell, canBuy, sellTitle, buyTitle, sellDisabled, buyDisabled };
    }

    var currentOrder = Array.from(tbody.querySelectorAll('tr[data-asset]')).map(function(tr) { return tr.getAttribute('data-asset'); });
    var newOrder = list.map(function(a) { return a.asset || 'N/A'; });
    var sameOrder = currentOrder.length === newOrder.length && currentOrder.every(function(asset, i) { return asset === newOrder[i]; });

    if (sameOrder && currentOrder.length > 0) {
        list.forEach(function(a, i) {
            var row = tbody.querySelector('tr[data-asset="' + (a.asset || 'N/A') + '"]');
            if (!row) return;
            var d = rowData(a);
            row.setAttribute('data-symbol', d.symbol);
            row.setAttribute('data-free', d.free);
            row.setAttribute('data-locked', d.locked);
            row.setAttribute('data-total', d.total);
            row.setAttribute('data-available', d.available);
            var symbolCell = row.querySelector('.varlik-symbol');
            if (symbolCell) symbolCell.textContent = d.asset;
            var nameCell = row.querySelector('.varlik-name');
            if (nameCell) nameCell.textContent = d.name;
            var priceCell = row.querySelector('.price-cell');
            if (priceCell) { priceCell.setAttribute('data-price', d.price != null ? d.price : ''); priceCell.textContent = d.priceDisplay; }
            var changeCell = row.querySelector('.change-pct');
            if (changeCell) { changeCell.setAttribute('data-change-pct', d.changePct != null ? d.changePct : ''); changeCell.style.color = d.changeColor; changeCell.textContent = d.changeStr; }
            var tds = row.querySelectorAll('td');
            if (tds[3]) tds[3].textContent = fmtNum(d.total, 8);
            if (tds[4]) tds[4].textContent = fmtNum(d.botLocked, 8);
            if (tds[5]) tds[5].textContent = fmtNum(d.locked, 8);
            if (tds[6]) tds[6].textContent = fmtNum(d.available, 8);
            var valueCell = row.querySelector('.value-cell');
            if (valueCell) { valueCell.setAttribute('data-value', d.valueUsd); valueCell.textContent = d.valueDisplay; }
            if (tds[8]) tds[8].textContent = d.pctPortfolio + '%';
            var actionsCell = row.querySelector('.varlik-card-actions');
            if (actionsCell) {
                actionsCell.innerHTML = '<div class="btn-al-sat-wrap">' +
                    '<button type="button" class="btn-al"' + d.buyDisabled + ' onclick="event.stopPropagation(); ' + (d.canBuy ? "openSpotTradeModal('" + d.symbol + "', 'BUY')" : '') + '" title="' + d.buyTitle + '">Alış</button>' +
                    '<button type="button" class="btn-sat"' + d.sellDisabled + ' onclick="event.stopPropagation(); ' + (d.canSell ? "openSpotTradeModal('" + d.symbol + "', 'SELL')" : '') + '" title="' + d.sellTitle + '">Satış</button></div>';
            }
        });
    } else {
        tbody.innerHTML = list.map(function(a) {
            var d = rowData(a);
            return '<tr data-asset="' + d.asset + '" data-symbol="' + d.symbol + '" data-free="' + d.free + '" data-locked="' + d.locked + '" data-total="' + d.total + '" data-available="' + d.available + '">' +
                '<td class="varlik-logo-cell" style="padding: 0.5rem 0.75rem; vertical-align: middle;">' +
                '<div class="varlik-logo" title="' + d.asset + '">' +
                (d.logoUrl ? '<img src="' + d.logoUrl + '" alt="' + d.asset + '" loading="lazy" onerror="if(window.registerLogo404)window.registerLogo404(this.alt);this.style.display=\'none\';this.nextElementSibling.style.display=\'flex\';" />' : '') +
                '<span class="varlik-logo-initials" style="' + (d.logoUrl ? 'display:none' : '') + '">' + d.initials + '</span></div></td>' +
                '<td style="padding: 0.75rem; vertical-align: middle;"><div class="varlik-symbol">' + d.asset + '</div><div class="varlik-name">' + d.name + '</div></td>' +
                '<td class="varlik-fiyat-cell" data-label="Fiyat" style="padding: 0.75rem; text-align: right; vertical-align: middle;">' +
                '<div class="price-cell" data-price="' + (d.price != null ? d.price : '') + '" style="font-weight: 600;">' + d.priceDisplay + '</div>' +
                '<div class="change-pct" data-change-pct="' + (d.changePct != null ? d.changePct : '') + '" style="color: ' + d.changeColor + ';">' + d.changeStr + '</div></td>' +
                '<td data-label="Toplam" style="padding: 0.75rem; text-align: right; vertical-align: middle;">' + fmtNum(d.total, 8) + '</td>' +
                '<td data-label="Bot kilitli" style="padding: 0.75rem; text-align: right; vertical-align: middle;">' + fmtNum(d.botLocked, 8) + '</td>' +
                '<td data-label="Kilitli" style="padding: 0.75rem; text-align: right; vertical-align: middle;">' + fmtNum(d.locked, 8) + '</td>' +
                '<td data-label="Kullanılabilir" style="padding: 0.75rem; text-align: right; vertical-align: middle;">' + fmtNum(d.available, 8) + '</td>' +
                '<td class="text-right value-cell" data-value="' + d.valueUsd + '" data-label="Değer" style="padding: 0.75rem; vertical-align: middle;">' + d.valueDisplay + '</td>' +
                '<td class="text-right" data-label="Dağılım %" style="padding: 0.75rem; vertical-align: middle;">' + d.pctPortfolio + '%</td>' +
                '<td class="varlik-card-actions" style="padding: 0.75rem; text-align: center; vertical-align: middle;">' +
                '<div class="btn-al-sat-wrap"><button type="button" class="btn-al"' + d.buyDisabled + ' onclick="event.stopPropagation(); ' + (d.canBuy ? "openSpotTradeModal('" + d.symbol + "', 'BUY')" : '') + '" title="' + d.buyTitle + '">Alış</button>' +
                '<button type="button" class="btn-sat"' + d.sellDisabled + ' onclick="event.stopPropagation(); ' + (d.canSell ? "openSpotTradeModal('" + d.symbol + "', 'SELL')" : '') + '" title="' + d.sellTitle + '">Satış</button></div></td></tr>';
        }).join('');
    }
    var unpricedEl = document.getElementById('varliklarUnpricedNotice');
    if (unpricedEl) unpricedEl.style.display = 'none';
}

function tickVarliklarPrices() {
    const tab = document.getElementById('tabBinance');
    if (!tab?.classList.contains('is-active')) return;
    const tbody = document.getElementById('varliklarTableBody');
    if (!tbody) return;
    const rows = tbody.querySelectorAll('tr[data-asset]');
    const symbolAttr = row => row.getAttribute('data-symbol') || normalizeAssetToSymbol(row.getAttribute('data-asset') || '', QUOTE);
    rows.forEach(row => {
        const asset = row.getAttribute('data-asset');
        const symbol = symbolAttr(row);
        const priceCell = row.querySelector('.price-cell');
        const valueCell = row.querySelector('.value-cell');
        const changeCell = row.querySelector('.change-pct');
        if (!priceCell || !valueCell) return;
        const fiyatTd = priceCell.closest('.varlik-fiyat-cell') || priceCell.parentElement;
        const price = getAssetPrice(asset);
        const oldPrice = parseFloat(priceCell.getAttribute('data-price') || '') || 0;
        if (price == null || !Number.isFinite(price)) return;
        const samePrice = Number.isFinite(oldPrice) && Math.abs(oldPrice - price) < 1e-9;
        if (!samePrice && Math.abs(oldPrice - price) > 0.0001 && typeof triggerValueBlink === 'function') {
            triggerValueBlink(priceCell, price);
        }
        priceCell.setAttribute('data-price', price);
        priceCell.textContent = fmtCoinPrice(price);
        // 24s değişim %: marketStore mini ticker ile canlı güncelle
        let changePct = null;
        if (changeCell) {
            const mini = window.marketStore?.getMini(symbol);
            changePct = mini && Number.isFinite(mini.changePct) ? mini.changePct : null;
            const oldChangePct = parseFloat(changeCell.getAttribute('data-change-pct') || '');
            if (changePct != null) {
                changeCell.setAttribute('data-change-pct', changePct);
                changeCell.textContent = (changePct >= 0 ? '+' : '') + changePct.toFixed(2) + '%';
                changeCell.style.color = changePct >= 0 ? '#0ecb81' : '#f6465d';
                const changePctChanged = Number.isFinite(oldChangePct) && Math.abs(oldChangePct - changePct) >= 0.01;
                if (changePctChanged && fiyatTd) {
                    fiyatTd.classList.remove('varlik-fiyat-blink-up', 'varlik-fiyat-blink-down');
                    fiyatTd.classList.add(changePct >= 0 ? 'varlik-fiyat-blink-up' : 'varlik-fiyat-blink-down');
                    setTimeout(() => {
                        if (fiyatTd) fiyatTd.classList.remove('varlik-fiyat-blink-up', 'varlik-fiyat-blink-down');
                    }, 700);
                }
            }
        }
        // Fiyat değişiminde blink
        if (!samePrice && Math.abs(oldPrice - price) > 0.0001) {
            priceCell.classList.remove('price-up', 'price-down', 'price-neutral');
            priceCell.classList.add(price > oldPrice ? 'price-up' : 'price-down');
            if (fiyatTd) {
                fiyatTd.classList.remove('varlik-fiyat-blink-up', 'varlik-fiyat-blink-down');
                fiyatTd.classList.add(price > oldPrice ? 'varlik-fiyat-blink-up' : 'varlik-fiyat-blink-down');
                setTimeout(() => {
                    if (fiyatTd) fiyatTd.classList.remove('varlik-fiyat-blink-up', 'varlik-fiyat-blink-down');
                }, 700);
            }
            setTimeout(() => { priceCell.classList.remove('price-up', 'price-down'); priceCell.classList.add('price-neutral'); }, 600);
        }
    });
}

/** Cüzdan varlıkları tablosu: POST /api/home/wallet/refresh (backend TTL/inflight dedupe; homeFlash debounce atlanır). */
var _varliklarWalletRefreshInflight = false;
var _varliklarWalletRefreshLastAt = 0;
var VARLIKLAR_WALLET_REFRESH_MS = 12000;
var VARLIKLAR_WALLET_MIN_GAP_MS = 4000;

function triggerWalletRefreshForVarliklar(accountId, opts) {
    opts = opts || {};
    var force = opts.force === true;
    if (!accountId || !window.apiClient || typeof window.apiClient.post !== 'function') return Promise.resolve();
    var now = Date.now();
    if (!force && (now - _varliklarWalletRefreshLastAt < VARLIKLAR_WALLET_MIN_GAP_MS)) return Promise.resolve();
    if (_varliklarWalletRefreshInflight) return Promise.resolve();
    _varliklarWalletRefreshInflight = true;
    var url = '/api/home/wallet/refresh?account_id=' + accountId + (force ? '&force=1' : '');
    return window.apiClient.post(url, null, { timeout: 15000 })
        .then(function (res) {
            _varliklarWalletRefreshLastAt = Date.now();
            if (res && res.ok && res.data && res.data.wallet_live && assetsState && assetsState.wallet) {
                normalizeAndApplyWallet(res.data.wallet_live, {
                    source: force ? 'wallet_refresh_varliklar_force' : 'wallet_refresh_varliklar',
                });
            }
            if (window.__walletDebugMeta) {
                window.__walletDebugMeta.last_refresh_at = (res && res.data && res.data.wallet_live_at) ? res.data.wallet_live_at : new Date().toISOString();
            }
        })
        .catch(function () {})
        .finally(function () { _varliklarWalletRefreshInflight = false; });
}
window.triggerWalletRefreshForVarliklar = triggerWalletRefreshForVarliklar;

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
    window.intervalRegistry.start('tab.varliklar.prices', () => { tickVarliklarPrices(); }, 2000, 'tab.varliklar');
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
        if (wantAll) {
            coinListAllScopeSymbols = syms;
            coinListAllBinanceSymbols = syms;
        } else {
            coinListAllBinanceSymbols = syms;
        }
        buildCoinListSearchSymbols();
    } catch (e) {
        console.warn('[dashboard] ensureCoinListSearchSymbols scope=', scope, e);
    }
}

function buildCoinListSearchSymbols() {
    const allSymbols = coinListAllBinanceSymbols.length > 0
        ? coinListAllBinanceSymbols
        : (window.marketStore?.getAllMini?.() || [])
            .filter(m => {
                const s = (m.symbol || '').toUpperCase();
                return s.endsWith('USDT') || s.endsWith('FDUSD');
            })
            .map(m => (m.symbol || '').toUpperCase());
    function quoteOrder(sym) {
        if ((sym || '').endsWith('USDT')) return 0;
        if ((sym || '').endsWith('FDUSD')) return 1;
        return 2;
    }
    coinListSearchAllSymbols = allSymbols.map(symbol => {
        const mini = window.marketStore?.getMini?.(symbol);
        return { symbol, last: mini?.last, changePct: mini?.changePct };
    }).sort((a, b) => {
        const qA = quoteOrder(a.symbol);
        const qB = quoteOrder(b.symbol);
        if (qA !== qB) return qA - qB;
        return (a.symbol || '').localeCompare(b.symbol || '');
    });
}

function showCoinListSearchDropdown(query) {
    const dropdown = document.getElementById('coinListSearchDropdown');
    if (!dropdown) return;
    const q = (query || '').trim().toUpperCase();
    if (!q) {
        dropdown.style.display = 'none';
        return;
    }
    const list = coinListSearchAllSymbols
        .filter(x => (x.symbol || '').toUpperCase().includes(q))
        .slice(0, 50);
    if (list.length === 0) {
        dropdown.innerHTML = '<div style="padding: 1rem; color: var(--ds-text-secondary);">Sonuç bulunamadı.</div>';
        dropdown.style.display = 'block';
        return;
    }
    dropdown.innerHTML = list.map(item => {
        const priceStr = item.last != null && Number.isFinite(item.last) ? fmtUsd(item.last) : '…';
        const pct = item.changePct != null && Number.isFinite(item.changePct) ? item.changePct : null;
        const pctStr = pct != null ? (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%' : '—';
        const pctColor = pct != null ? (pct >= 0 ? '#0ecb81' : '#f6465d') : 'var(--ds-text-secondary)';
        return `<div class="coin-list-search-item" data-symbol="${item.symbol}" style="padding: 0.6rem 1rem; cursor: pointer; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--ds-border);" onmouseenter="this.style.background='var(--ds-bg-tertiary)'" onmouseleave="this.style.background='transparent'">
            <span style="font-weight: 600;">${item.symbol}</span>
            <span style="display: flex; gap: 1rem;">
                <span>${priceStr}</span>
                <span style="color: ${pctColor}">${pctStr}</span>
            </span>
        </div>`;
    }).join('');
    dropdown.style.display = 'block';
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
    if (window.BinanceUI && document.getElementById("tabBinance")?.classList.contains("is-active")) {
        return;
    }
    BinanceAssetsPanel.tickPricesUI();
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
            updateBinancePricesTick();
        });
        if (window.__DEBUG_BINANCE__) console.log("[BINANCE] Subscribed to marketStore");
    }
    
    var priceTickMs = isMobileView() ? 2000 : PRICE_UI_TICK_MS;
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
let spotTradeState = {
    symbol: null,
    side: 'BUY',
    type: 'MARKET',
    currentPrice: 0,
    availableBalance: 0,
    quoteBalance: 0,
    baseBalance: 0,
    quoteAvailable: 0,
    baseAvailable: 0,
    quoteAsset: 'USDT',
    baseAsset: null,
    limitPriceEdited: false,  // Flag to track if user has manually edited limit price
    stepSize: 0.00000001,     // Quantity precision (default: 8 decimals)
    stepSizeStr: '0.00000001',
    minQty: 0.00000001,
    tickSize: 0.01,           // Price precision (default: 2 decimals)
    minNotional: 10.0         // Minimum order value
};

// Legacy alias for portfolioState (if referenced elsewhere)
// This prevents "portfolioState is not defined" errors from cached/old code
let portfolioState = spotTradeState;

// Bind spot trade modal
function bindSpotTradeModal() {
    // Quantity and Total calculation
    const qtyInput = document.getElementById("bnTradeQuantity");
    const totalInput = document.getElementById("bnTradeTotal");
    
    if (qtyInput) {
        qtyInput.addEventListener("input", () => {
            updateTradeTotal();
        });
    }
    
    if (totalInput) {
        totalInput.addEventListener("input", () => {
            updateTradeQuantity();
        });
    }
    
    // Limit price input - track user edits
    const limitPriceInput = document.getElementById("bnLimitPrice");
    if (limitPriceInput) {
        limitPriceInput.addEventListener("input", () => {
            // Mark as edited when user types
            spotTradeState.limitPriceEdited = true;
        });
        
        limitPriceInput.addEventListener("focus", () => {
            // Mark as edited when user focuses (they might be about to edit)
            // But only if there's already a value
            if (limitPriceInput.value && limitPriceInput.value !== spotTradeState.currentPrice.toFixed(2)) {
                spotTradeState.limitPriceEdited = true;
            }
        });
    }
    
    // Favori (⭐) butonu
    const favBtn = document.getElementById('bnTradeFavoriteBtn');
    if (favBtn) {
        favBtn.addEventListener('click', function (e) {
            e.preventDefault();
            e.stopPropagation();
            var sym = spotTradeState.symbol;
            if (!sym) return;
            if (!State.accountId) {
                if (window.Toast) window.Toast.warn('Hesap seçin'); else alert('Hesap seçin');
                return;
            }
            var p = toggleSpotFavorite(sym);
            syncFavoriteButtonUI();
            if (typeof renderBinanceCoinList === 'function') renderBinanceCoinList();
            if (typeof renderMobileTradeFavorites === 'function') renderMobileTradeFavorites();
            if (p && p.catch) p.catch(function () { syncFavoriteButtonUI(); if (typeof renderBinanceCoinList === 'function') renderBinanceCoinList(); if (typeof renderMobileTradeFavorites === 'function') renderMobileTradeFavorites(); });
        });
    }

    // Modal grafik tıklanınca detay grafik sayfasına git
    const chartWrap = document.getElementById("bnTradeChartWrap");
    if (chartWrap) {
        chartWrap.addEventListener("click", () => {
            const sym = spotTradeState.symbol;
            if (sym && typeof sym === 'string') {
                window.location.href = '/ui/chart.html?symbol=' + encodeURIComponent(sym);
            }
        });
        chartWrap.addEventListener("keydown", (e) => {
            if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                const sym = spotTradeState.symbol;
                if (sym && typeof sym === 'string') {
                    window.location.href = '/ui/chart.html?symbol=' + encodeURIComponent(sym);
                }
            }
        });
    }

    // Close modal on backdrop click
    const backdrop = document.getElementById("dmBackdrop");
    if (backdrop) {
        backdrop.addEventListener("click", () => {
            closeSpotTradeModal();
        });
    }
}

// Prefetch price data when hovering over trade buttons (ULTRA FAST prefetching)
// REFACTOR: Use marketStore instead of prefetching prices
// No need to prefetch - marketDataService handles all price updates
function prefetchPriceData(symbol) {
    // No-op: marketStore is the single source of truth, updated by marketDataService
    // This function is kept for backward compatibility but does nothing
    // Prices will be available from marketStore when needed
}

// Open spot trade modal - YENİ SPOT ENGINE - Flash Hızında
// symbol: e.g. BTCUSDT; side: optional 'BUY'|'SELL' (default BUY). Al -> BUY, Sat -> SELL.
async function openSpotTradeModal(symbol, side) {
    try {
        if (!State.accountId) {
            showError("Hesap ID bulunamadı");
            return;
        }
        
        const { normalized: normalizedSymbol, invalid: invalidParity } = normalizeModalSymbol(symbol || '');
        if (!normalizedSymbol || invalidParity) {
            spotTradeState.symbol = normalizedSymbol || (symbol || '').toUpperCase();
            spotTradeState.baseAsset = spotTradeState.symbol.replace(/USDT$/i, '') || 'USDT';
            spotTradeState.quoteAsset = 'USDT';
            spotTradeState.side = (side === 'SELL' || side === 'sell') ? 'SELL' : 'BUY';
            spotTradeState.type = 'MARKET';
            const modal = document.getElementById("bnSpotTradeModal");
            const backdrop = document.getElementById("dmBackdrop");
            if (modal) {
                modal.style.display = "block";
                modal.setAttribute("aria-hidden", "false");
                if (backdrop) backdrop.style.display = "block";
                document.body.style.overflow = "hidden";
            }
            document.getElementById("bnTradeQuantity").value = "";
            document.getElementById("bnTradeTotal").value = "";
            document.getElementById("bnLimitPrice").value = "";
            document.getElementById("bnTradeError").style.display = "none";
            updateSpotTradeModal();
            loadTradeModalChart(normalizedSymbol || spotTradeState.symbol);
            var priceEl = document.getElementById("bnTradePrice");
            if (priceEl) priceEl.textContent = "Geçersiz parite";
            syncFavoriteButtonUI();
            return;
        }
        
        const engine = getSpotEngine(State.accountId);
        spotTradeState.symbol = normalizedSymbol;
        if (normalizedSymbol === 'USDTUSD') {
            spotTradeState.baseAsset = 'USDT';
            spotTradeState.quoteAsset = 'USD';
        } else {
            const quoteAssets = ['USDT', 'BUSD', 'FDUSD', 'BTC', 'ETH', 'BNB', 'TRY', 'EUR', 'GBP'];
            let found = false;
            for (const quote of quoteAssets) {
                if (normalizedSymbol.endsWith(quote)) {
                    spotTradeState.baseAsset = normalizedSymbol.replace(quote, '');
                    spotTradeState.quoteAsset = quote;
                    found = true;
                    break;
                }
            }
            if (!found) {
                spotTradeState.baseAsset = normalizedSymbol.replace(/USDT$/i, '') || 'BTC';
                spotTradeState.quoteAsset = 'USDT';
            }
        }
        spotTradeState.side = (side === 'SELL' || side === 'sell') ? 'SELL' : 'BUY';
        spotTradeState.type = 'MARKET';
        
        const modal = document.getElementById("bnSpotTradeModal");
        const backdrop = document.getElementById("dmBackdrop");
        if (modal) {
            modal.style.display = "block";
            modal.setAttribute("aria-hidden", "false");
            if (backdrop) backdrop.style.display = "block";
            document.body.style.overflow = "hidden";
        }
        document.getElementById("bnTradeQuantity").value = "";
        document.getElementById("bnTradeTotal").value = "";
        document.getElementById("bnLimitPrice").value = "";
        document.getElementById("bnTradeError").style.display = "none";
        spotTradeState.limitPriceEdited = false;
        
        const cachedPrice = engine.getCachedPrice(normalizedSymbol);
        if (cachedPrice && cachedPrice > 0) updatePriceDisplay(cachedPrice);
        setModalPriceChangePlaceholder();
        
        updateSpotTradeModal();
        loadTradeModalChart(normalizedSymbol);
        ensureFeeRates(State.accountId).then(() => updateSpotTradeModal());
        
        const abortController = new AbortController();
        window.spotEngineAbortController = abortController;
        
        engine.fetchQuickData(normalizedSymbol, abortController.signal)
            .then(data => {
                if (data && data.ok === false && data.error_code === 'INVALID_SYMBOL') return;
                handleSpotEngineData(data || {});
            })
            .catch(() => {});
        
        function fetchTicker24hAndUpdateModal() {
            if (!spotTradeState.symbol || document.getElementById("bnSpotTradeModal")?.style.display !== "block") return;
            fetch(window.location.origin + '/api/spot/ticker_24h?symbol=' + encodeURIComponent(spotTradeState.symbol))
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (!spotTradeState.symbol || document.getElementById("bnSpotTradeModal")?.style.display !== "block") return;
                    var price = parseFloat(data.lastPrice || data.weightedAvgPrice || 0);
                    var pct = parseFloat(data.priceChangePercent || 0);
                    if (price > 0) updatePriceDisplay(price);
                    var changeEl = document.getElementById("bnTradePriceChange");
                    if (changeEl && Number.isFinite(pct)) {
                        var text = (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%';
                        if (setTextIfChanged(changeEl, text)) { }
                        changeEl.style.color = pct >= 0 ? '#0ecb81' : '#f6465d';
                    }
                })
                .catch(function () {});
        }
        fetchTicker24hAndUpdateModal();
        window.intervalRegistry.stop('trade.modalSpotPrice');
        window.intervalRegistry.start('trade.modalSpotPrice', fetchTicker24hAndUpdateModal, 1000, 'trade');
        
        syncFavoriteButtonUI();
    } catch (error) {
        console.error("[dashboard] openSpotTradeModal error:", error);
        if (window.errorReporter) window.errorReporter.report(error, { action: 'openSpotTradeModal', symbol, side });
        showError(`Modal açılamadı: ${error.message || 'Bilinmeyen hata'}`);
    }
}

// Handle spot engine data - FLASH HIZLI
function handleSpotEngineData(data) {
    if (!data || !spotTradeState.symbol) return;
    
    // Update price
    if (data.price && data.price > 0) {
        updatePriceDisplay(data.price);
    }
    
    // Price change %: only updated by ticker_24h interval (single source to avoid flicker)
    
    // Update filters
    if (data.filters) {
        spotTradeState.stepSizeStr = String(data.filters.stepSize || '0.00000001');
        spotTradeState.stepSize = parseFloat(spotTradeState.stepSizeStr) || 0.00000001;
        spotTradeState.minQty = parseFloat(data.filters.minQty || data.filters.stepSize || 0.00000001);
        spotTradeState.tickSize = parseFloat(data.filters.tickSize || 0.01);
        spotTradeState.minNotional = parseFloat(data.filters.minNotional || 5);
    }
    
    var sym = (data.symbol || spotTradeState.symbol || '').toUpperCase();
    if (sym === 'USDTUSD') {
        spotTradeState.baseAsset = 'USDT';
        spotTradeState.quoteAsset = 'USD';
    } else {
        if (data.baseAsset) spotTradeState.baseAsset = data.baseAsset;
        if (data.quoteAsset) spotTradeState.quoteAsset = data.quoteAsset;
    }
    
    // Update balances - IMMEDIATE (no requestAnimationFrame delay). Use available (bot-locked subtracted) for display and 100%.
    if (data.baseBalance !== undefined && data.quoteBalance !== undefined) {
        spotTradeState.quoteBalance = data.quoteBalance || 0;
        spotTradeState.baseBalance = data.baseBalance || 0;
        spotTradeState.quoteAvailable = (data.quoteAvailable != null && Number.isFinite(data.quoteAvailable)) ? data.quoteAvailable : (data.quoteBalance || 0);
        spotTradeState.baseAvailable = (data.baseAvailable != null && Number.isFinite(data.baseAvailable)) ? data.baseAvailable : (data.baseBalance || 0);
        if (spotTradeState.side === 'BUY') {
            spotTradeState.availableBalance = spotTradeState.quoteAvailable;
        } else {
            spotTradeState.availableBalance = spotTradeState.baseAvailable;
        }
        updateSpotTradeModal();
    }
}

// Bootstrap: Binance kaldırıldı – boş/default veri (sonra temiz kurulum ile eklenecek)
async function fetchBootstrapData(symbol, signal) {
    return fetchBootstrapDataFallback(symbol, signal);
}

async function fetchBootstrapDataFallback(symbol, signal) {
    try {
        let price = (window.marketStore && window.marketStore.getPrice(symbol)) || 0;
        if (typeof price !== 'number' || !Number.isFinite(price)) price = 0;
        const base = (symbol || "").replace("USDT", "").replace("BTC", "").replace("ETH", "") || "BTC";
        const filters = {
            tickSize: "0.01",
            stepSize: "0.00001",
            minQty: "0.00001",
            minNotional: "5",
            baseAsset: base,
            quoteAsset: "USDT"
        };
        const balances = { baseFree: 0, quoteFree: 0, base, quote: "USDT" };
        return {
            symbol,
            price,
            filters,
            balances,
            ts: Date.now() / 1000
        };
    } catch (e) {
        return {
            symbol,
            price: 0,
            filters: { tickSize: "0.01", stepSize: "0.00001", minQty: "0.00001", minNotional: "5", baseAsset: symbol.replace("USDT", ""), quoteAsset: "USDT" },
            balances: { baseFree: 0, quoteFree: 0, base: symbol.replace("USDT", ""), quote: "USDT" },
            ts: Date.now() / 1000
        };
    }
}

// Handle bootstrap data response
function handleBootstrapData(data) {
    const perfStart = performance.now();
    
    if (!data || !spotTradeState.symbol) return;
    
    if (data.price && data.price > 0) {
        SpotCache.setPrice(data.symbol, data.price);
        priceCache[data.symbol] = data.price;
        priceCacheTime[data.symbol] = Date.now();
        updatePriceDisplay(data.price);
    }
    
    // Update filters
    if (data.filters) {
        SpotCache.setFilters(data.symbol, data.filters);
        spotTradeState.stepSizeStr = String(data.filters.stepSize || '0.00000001');
        spotTradeState.stepSize = parseFloat(spotTradeState.stepSizeStr) || 0.00000001;
        spotTradeState.minQty = parseFloat(data.filters.minQty || data.filters.stepSize || 0.00000001);
        spotTradeState.tickSize = parseFloat(data.filters.tickSize || 0.01);
        spotTradeState.minNotional = parseFloat(data.filters.minNotional || 5);
        if (data.filters.baseAsset) spotTradeState.baseAsset = data.filters.baseAsset;
        if (data.filters.quoteAsset) spotTradeState.quoteAsset = data.filters.quoteAsset;
    }
    
    // Update balances (bootstrap may not have available; use free as fallback)
    if (data.balances) {
        SpotCache.setBalance(State.accountId, data.balances);
        spotTradeState.quoteBalance = data.balances.quoteFree || 0;
        spotTradeState.baseBalance = data.balances.baseFree || 0;
        spotTradeState.quoteAvailable = data.balances.quoteAvailable ?? spotTradeState.quoteBalance;
        spotTradeState.baseAvailable = data.balances.baseAvailable ?? spotTradeState.baseBalance;
        if (spotTradeState.side === 'BUY') {
            spotTradeState.availableBalance = spotTradeState.quoteAvailable;
        } else {
            spotTradeState.availableBalance = spotTradeState.baseAvailable;
        }
        requestAnimationFrame(() => updateSpotTradeModal());
    }
    
    updateModalPriceChange();
}

function closeSpotTradeModal() {
    const modal = document.getElementById("bnSpotTradeModal");
    const backdrop = document.getElementById("dmBackdrop");
    if (modal) {
        modal.style.display = "none";
        modal.setAttribute("aria-hidden", "true");
        if (backdrop) {
            backdrop.style.display = "none";
        }
        document.body.style.overflow = "";
    }
    
    // Stop Spot Engine updates
    if (State.accountId && spotTradeState.symbol) {
        const engine = getSpotEngine(State.accountId);
        engine.stopUpdates(`price_${spotTradeState.symbol}`);
        engine.stopUpdates(`quick_${spotTradeState.symbol}`);
    }
    
    // Stop price change update interval
    window.intervalRegistry.stop('trade.modalPriceChange');
    window.intervalRegistry.stop('trade.modalSpotPrice');
    window.intervalRegistry.stop('auth.health');
    
    lastModalLogoBase = null;
    
    // Abort in-flight requests
    if (window.spotEngineAbortController) {
        window.spotEngineAbortController.abort();
        window.spotEngineAbortController = null;
    }
    
    if (modalAbortController) {
        modalAbortController.abort();
        modalAbortController = null;
    }
    
    // REFACTOR: Use intervalRegistry - stop all trade intervals
    window.intervalRegistry.stop('trade.modalPrice');
    window.intervalRegistry.stop('trade.priceChange');
    window.intervalRegistry.stop('trade.modalSpotPrice');
    stopBalanceUpdates();
}

function setTradeSide(side) {
    spotTradeState.side = side;
    
    // Update available balance immediately based on current data
    if (State.accountId && spotTradeState.symbol) {
        const engine = getSpotEngine(State.accountId);
        const cachedData = engine.getCachedQuickData(spotTradeState.symbol);
        if (cachedData) {
            spotTradeState.quoteBalance = cachedData.quoteBalance || 0;
            spotTradeState.baseBalance = cachedData.baseBalance || 0;
            spotTradeState.quoteAvailable = (cachedData.quoteAvailable != null && Number.isFinite(cachedData.quoteAvailable)) ? cachedData.quoteAvailable : spotTradeState.quoteBalance;
            spotTradeState.baseAvailable = (cachedData.baseAvailable != null && Number.isFinite(cachedData.baseAvailable)) ? cachedData.baseAvailable : spotTradeState.baseBalance;
            if (side === 'BUY') {
                spotTradeState.availableBalance = spotTradeState.quoteAvailable;
            } else {
                spotTradeState.availableBalance = spotTradeState.baseAvailable;
            }
        } else {
            // Fetch fresh data if not cached
            engine.fetchQuickData(spotTradeState.symbol)
                .then(data => {
                    handleSpotEngineData(data);
                })
                .catch(() => {});
        }
    }
    
    updateSpotTradeModal();
}

function setTradeType(type) {
    spotTradeState.type = type;
    updateSpotTradeModal();
    // Update summary when type changes (taker vs maker fee)
    updateTradeSummary();
}

function setTradePercent(percent) {
    const available = spotTradeState.availableBalance || 0;
    const quoteAsset = spotTradeState.quoteAsset || 'USDT';
    
    if (spotTradeState.side === 'BUY') {
        // For BUY, always use quote asset (USDT) for percentage calculation
        const amount = (available * percent) / 100;
        const totalDecimals = getQuoteAssetDecimals(quoteAsset);
        const tickDecimals = spotTradeState.tickSize ? getDecimalPlaces(spotTradeState.tickSize) : totalDecimals;
        const finalDecimals = Math.max(tickDecimals, totalDecimals);
        const totalInput = document.getElementById("bnTradeTotal");
        if (totalInput) {
            totalInput.value = amount.toFixed(finalDecimals);
        }
        updateTradeQuantity();
    } else {
        // For SELL, use base asset
        const amount = percent >= 100 ? getMaxSellQuantity() : quantizeQuantity((available * percent) / 100);
        const decimals = getStepDecimals(spotTradeState.stepSizeStr || spotTradeState.stepSize);
        const qtyInput = document.getElementById("bnTradeQuantity");
        if (qtyInput) {
            qtyInput.value = amount.toFixed(decimals);
        }
        updateTradeTotal();
    }
}

function getStepDecimals(step) {
    var s = String(step != null ? step : '');
    if (/e/i.test(s)) {
        var m = s.match(/e-(\d+)/i);
        return m ? parseInt(m[1], 10) : 8;
    }
    if (s.indexOf('.') === -1) return 0;
    var frac = s.split('.')[1];
    return (frac.replace(/0+$/, '') || frac).length;
}

function getMaxSellQuantity() {
    var avail = Number(spotTradeState.baseAvailable != null ? spotTradeState.baseAvailable : (spotTradeState.availableBalance || 0));
    if (!avail || avail <= 0) return 0;
    return quantizeQuantity(avail);
}

// Quantize quantity to step size (using proper rounding to avoid floating point errors)
function quantizeQuantity(qty) {
    if (!spotTradeState.stepSize || spotTradeState.stepSize <= 0) {
        return qty;
    }
    const step = spotTradeState.stepSize;
    const steps = Math.floor(qty / step);
    const quantized = steps * step;
    const decimals = getStepDecimals(spotTradeState.stepSizeStr || step);
    return parseFloat(quantized.toFixed(decimals));
}

// Quantize price to tick size
function quantizePrice(price) {
    if (!spotTradeState.tickSize || spotTradeState.tickSize <= 0) {
        return price;
    }
    const tick = spotTradeState.tickSize;
    const quantized = Math.floor(price / tick) * tick;
    return quantized;
}

// Get decimal places from step size or tick size
function getDecimalPlaces(value) {
    if (value >= 1) return 0;
    const str = value.toString();
    if (str.includes('e')) {
        const match = str.match(/e-(\d+)/);
        return match ? parseInt(match[1]) : 8;
    }
    const parts = str.split('.');
    if (parts.length === 1) return 0;
    return parts[1].length;
}

// Format value based on quote asset
function fmtQuoteAsset(value, quoteAsset) {
    if (!quoteAsset) quoteAsset = 'USDT';
    
    if (quoteAsset === 'USDT' || quoteAsset === 'FDUSD' || quoteAsset === 'BUSD' || quoteAsset === 'USDC' || quoteAsset === 'TUSD' || quoteAsset === 'DAI') {
        return fmtUsd(value);
    } else if (quoteAsset === 'BTC') {
        return `${fmtNum(value, 8)} BTC`;
    } else if (quoteAsset === 'ETH') {
        return `${fmtNum(value, 6)} ETH`;
    } else if (quoteAsset === 'BNB') {
        return `${fmtNum(value, 4)} BNB`;
    } else {
        return `${fmtNum(value, 8)} ${quoteAsset}`;
    }
}

// Get decimal places for quote asset
function getQuoteAssetDecimals(quoteAsset) {
    if (!quoteAsset) quoteAsset = 'USDT';
    
    if (quoteAsset === 'USDT' || quoteAsset === 'FDUSD' || quoteAsset === 'BUSD' || quoteAsset === 'USDC' || quoteAsset === 'TUSD' || quoteAsset === 'DAI') {
        return 2;
    } else if (quoteAsset === 'BTC') {
        return 8;
    } else if (quoteAsset === 'ETH') {
        return 6;
    } else if (quoteAsset === 'BNB') {
        return 4;
    } else {
        return 8;
    }
}

function updateTradeTotal() {
    const qtyInput = document.getElementById("bnTradeQuantity");
    if (!qtyInput) return;
    
    const rawQty = parseFloat(qtyInput.value) || 0;
    
    // Quantize quantity to step size
    const qty = quantizeQuantity(rawQty);
    if (qty !== rawQty && rawQty > 0) {
        // Update input with quantized value
        const decimals = getStepDecimals(spotTradeState.stepSizeStr || spotTradeState.stepSize);
        qtyInput.value = qty.toFixed(decimals);
    }
    
    const price = spotTradeState.currentPrice || 0;
    // Always get quote asset from spotTradeState to ensure it's current
    const quoteAsset = spotTradeState.quoteAsset || 'USDT';
    
    // If quantity is 0 or very small, set total to 0 (don't show total value)
    if (qty === 0 || qty < 0.00000001) {
        const totalInput = document.getElementById("bnTradeTotal");
        if (totalInput) {
            totalInput.value = "0.00";
        }
        const qtyValueEl = document.getElementById("bnTradeQuantityValue");
        if (qtyValueEl) {
            qtyValueEl.style.display = "none";
        }
        updateTradeSummary();
        return;
    }
    
    if (price > 0 && qty > 0) {
        const total = qty * price;
        // Format total based on quote asset decimals
        const totalDecimals = getQuoteAssetDecimals(quoteAsset);
        // Use tick size if available for better precision
        const tickDecimals = spotTradeState.tickSize ? getDecimalPlaces(spotTradeState.tickSize) : totalDecimals;
        const finalDecimals = Math.max(tickDecimals, totalDecimals);
        
        const totalInput = document.getElementById("bnTradeTotal");
        if (totalInput) {
            totalInput.value = total.toFixed(finalDecimals);
        }
        
        // Update quantity value display (show total value in quote asset)
        const qtyValueEl = document.getElementById("bnTradeQuantityValue");
        const qtyValueAmountEl = document.getElementById("bnTradeQuantityValueAmount");
        if (qtyValueEl && qtyValueAmountEl) {
            qtyValueEl.style.display = "block";
            // Always use current quote asset from spotTradeState
            qtyValueAmountEl.textContent = fmtQuoteAsset(total, quoteAsset);
        }
        
        updateTradeSummary();
    } else {
        const qtyValueEl = document.getElementById("bnTradeQuantityValue");
        if (qtyValueEl) {
            qtyValueEl.style.display = "none";
        }
        const totalInput = document.getElementById("bnTradeTotal");
        if (totalInput && !totalInput.value) {
            totalInput.value = "";
        }
    }
}

function updateTradeQuantity() {
    const totalInput = document.getElementById("bnTradeTotal");
    if (!totalInput) return;
    
    const total = parseFloat(totalInput.value) || 0;
    const price = spotTradeState.currentPrice || 0;
    
    if (price > 0 && total > 0) {
        const qty = total / price;
        // Quantize quantity to step size
        const quantizedQty = quantizeQuantity(qty);
        const decimals = getDecimalPlaces(spotTradeState.stepSize);
        
        const qtyInput = document.getElementById("bnTradeQuantity");
        if (qtyInput) {
            qtyInput.value = quantizedQty.toFixed(decimals);
        }
        
        // Update total value display (show quantity in base asset)
        const totalValueEl = document.getElementById("bnTradeTotalValue");
        const totalValueAmountEl = document.getElementById("bnTradeTotalValueAmount");
        if (totalValueEl && totalValueAmountEl) {
            totalValueEl.style.display = "block";
            const baseAsset = spotTradeState.baseAsset || '';
            totalValueAmountEl.textContent = `${fmtNum(quantizedQty, decimals)} ${baseAsset}`;
        }
        
        updateTradeSummary();
    } else {
        const qtyValueEl = document.getElementById("bnTradeQuantityValue");
        if (qtyValueEl) {
            qtyValueEl.style.display = "none";
        }
        const totalInput = document.getElementById("bnTradeTotal");
        if (totalInput && !totalInput.value) {
            totalInput.value = "";
        }
    }
}

function updateTradeSummary() {
    const totalInput = document.getElementById("bnTradeTotal");
    if (!totalInput) return;
    
    const total = parseFloat(totalInput.value) || 0;
    // Always get quote asset from spotTradeState to ensure it's current
    const quoteAsset = spotTradeState.quoteAsset || 'USDT';
    
    // Use Binance fee rate (taker for market orders, maker for limit orders)
    // Default to 0.1% if not available
    const feeRates = window.binanceFeeRates || { taker: 0.001, maker: 0.001 };
    const feeRate = spotTradeState.type === 'MARKET' ? feeRates.taker : feeRates.maker;
    const fee = total * feeRate;
    const feePct = (feeRate * 100).toFixed(4);
    
    // Format total and fee based on quote asset
    const summaryAmountEl = document.getElementById("bnTradeSummaryAmount");
    if (summaryAmountEl) {
        summaryAmountEl.textContent = fmtQuoteAsset(total, quoteAsset);
    }
    
    const feeEl = document.getElementById("bnTradeSummaryFee");
    const feeRateEl = document.getElementById("bnTradeFeeRate");
    if (feeEl) {
        feeEl.textContent = fmtQuoteAsset(fee, quoteAsset);
        feeEl.title = `Komisyon oranı: %${feePct} (Binance'den alındı)`;
    }
    if (feeRateEl) {
        feeRateEl.textContent = `${feePct}%`;
    }
}

function updateSpotTradeModal() {
    var symbolDisplay = spotTradeState.symbol || '-';
    if ((spotTradeState.symbol || '').toUpperCase() === 'USDTUSD') {
        symbolDisplay = 'USDT/USD';
    } else if (spotTradeState.baseAsset && spotTradeState.quoteAsset) {
        symbolDisplay = spotTradeState.baseAsset + '/' + spotTradeState.quoteAsset;
    }
    var symbolEl = document.getElementById("bnTradeSymbol");
    if (symbolEl) symbolEl.textContent = symbolDisplay;
    
    var base = spotTradeState.baseAsset || (spotTradeState.symbol || '').replace(/USDT$/i, '').replace(/BTC$/i, '').replace(/ETH$/i, '').replace(/BNB$/i, '') || '';
    var logoWrap = document.getElementById("bnTradeSymbolLogo");
    if (logoWrap && typeof getCoinLogoUrl === 'function' && base !== lastModalLogoBase) {
        lastModalLogoBase = base;
        var logoUrl = getCoinLogoUrl(base);
        var initials = (base || ' ').substring(0, 2).toUpperCase();
        logoWrap.innerHTML = (logoUrl
            ? '<img src="' + logoUrl + '" alt="' + base + '" loading="lazy" onerror="if(window.registerLogo404)window.registerLogo404(this.alt);this.style.display=\'none\';this.nextElementSibling.style.display=\'flex\';" /><span class="varlik-logo-initials" style="display:none">' + initials + '</span>'
            : '<span class="varlik-logo-initials">' + initials + '</span>');
    }
    
    // Update labels based on side
    const qtyLabel = document.getElementById("bnTradeQuantityLabel");
    const qtyUnit = document.getElementById("bnTradeQuantityUnit");
    const totalLabel = document.getElementById("bnTradeTotalLabel");
    const totalUnit = document.getElementById("bnTradeTotalUnit");
    
    // Reorder inputs based on side: BUY = USDT first, SELL = Quantity first
    const container = document.getElementById("bnTradeInputsContainer");
    const totalGroup = document.getElementById("bnTradeTotalGroup");
    const quantityGroup = document.getElementById("bnTradeQuantityGroup");
    const totalPercentButtons = document.getElementById("bnTradeTotalPercentButtons");
    const quantityPercentButtons = document.getElementById("bnTradeQuantityPercentButtons");
    
    if (spotTradeState.side === 'BUY') {
        // For BUY: USDT (Total) first, then Quantity
        if (container && totalGroup && quantityGroup) {
            container.insertBefore(totalGroup, quantityGroup);
        }
        // Show percent buttons on USDT (Total) for BUY
        if (totalPercentButtons) totalPercentButtons.style.display = "flex";
        if (quantityPercentButtons) quantityPercentButtons.style.display = "none";
        
        // Update labels
        if (qtyLabel) qtyLabel.textContent = "Miktar";
        if (qtyUnit) qtyUnit.textContent = spotTradeState.baseAsset || '-';
        if (totalLabel) totalLabel.textContent = "Tutar";
        if (totalUnit) totalUnit.textContent = spotTradeState.quoteAsset || 'USDT';
    } else {
        // For SELL: Quantity first, then USDT (Total)
        if (container && totalGroup && quantityGroup) {
            container.insertBefore(quantityGroup, totalGroup);
        }
        // Show percent buttons on Quantity for SELL
        if (totalPercentButtons) totalPercentButtons.style.display = "none";
        if (quantityPercentButtons) quantityPercentButtons.style.display = "flex";
        
        // Update labels
        if (qtyLabel) qtyLabel.textContent = "Miktar";
        if (qtyUnit) qtyUnit.textContent = spotTradeState.baseAsset || '-';
        if (totalLabel) totalLabel.textContent = "Tutar";
        if (totalUnit) totalUnit.textContent = spotTradeState.quoteAsset || 'USDT';
    }
    
    // Update side buttons (eski stil: seçili yeşil/kırmızı, seçili değil gri)
    const buyBtn = document.getElementById("bnTradeBuyBtn");
    const sellBtn = document.getElementById("bnTradeSellBtn");
    const selectedBg = "rgba(14, 203, 129, 0.1)";
    const selectedColor = "#0ecb81";
    const selectedBorder = "1px solid rgba(14, 203, 129, 0.3)";
    const sellBg = "rgba(246, 70, 93, 0.1)";
    const sellColor = "#f6465d";
    const sellBorder = "1px solid rgba(246, 70, 93, 0.3)";
    const unselBg = "transparent";
    const unselColor = "var(--ds-text-tertiary)";
    const unselBorder = "1px solid var(--ds-border)";
    if (buyBtn) {
        if (spotTradeState.side === 'BUY') {
            buyBtn.style.background = selectedBg;
            buyBtn.style.color = selectedColor;
            buyBtn.style.border = selectedBorder;
        } else {
            buyBtn.style.background = unselBg;
            buyBtn.style.color = unselColor;
            buyBtn.style.border = unselBorder;
        }
    }
    if (sellBtn) {
        if (spotTradeState.side === 'SELL') {
            sellBtn.style.background = sellBg;
            sellBtn.style.color = sellColor;
            sellBtn.style.border = sellBorder;
        } else {
            sellBtn.style.background = unselBg;
            sellBtn.style.color = unselColor;
            sellBtn.style.border = unselBorder;
        }
    }
    
    // Update type buttons
    const marketBtn = document.getElementById("bnTradeTypeMarket");
    const limitBtn = document.getElementById("bnTradeTypeLimit");
    if (marketBtn) {
        marketBtn.classList.toggle("active", spotTradeState.type === 'MARKET');
    }
    if (limitBtn) {
        limitBtn.classList.toggle("active", spotTradeState.type === 'LIMIT');
    }
    
    // Show/hide limit price input
    const limitGroup = document.getElementById("bnLimitPriceGroup");
    const limitPriceInput = document.getElementById("bnLimitPrice");
    if (limitGroup) {
        limitGroup.style.display = spotTradeState.type === 'LIMIT' ? "block" : "none";
    }
    
    // Update limit price only if user hasn't edited it
    if (limitPriceInput && spotTradeState.type === 'LIMIT' && !spotTradeState.limitPriceEdited) {
        if (spotTradeState.currentPrice > 0) {
            const quantizedPrice = quantizePrice(spotTradeState.currentPrice);
            const decimals = getDecimalPlaces(spotTradeState.tickSize);
            limitPriceInput.value = quantizedPrice.toFixed(decimals);
        }
    }
    
    // Update step attribute for quantity input
    const qtyInput = document.getElementById("bnTradeQuantity");
    if (qtyInput) {
        qtyInput.step = spotTradeState.stepSizeStr || spotTradeState.stepSize || 0.00000001;
    }
    
    // Update step attribute for limit price input
    if (limitPriceInput) {
        limitPriceInput.step = spotTradeState.tickSize || 0.01;
    }
    
    // Update submit button (eski stil: Alış = yeşil, Satış = kırmızı)
    const submitBtn = document.getElementById("bnTradeSubmitBtn");
    const submitText = document.getElementById("bnTradeSubmitText");
    if (submitBtn && submitText) {
        submitBtn.disabled = false;
        if (spotTradeState.side === 'BUY') {
            submitBtn.style.background = "#0ecb81";
            submitBtn.style.border = "1px solid rgba(14, 203, 129, 0.5)";
            submitBtn.style.color = "#fff";
        } else {
            submitBtn.style.background = "#f6465d";
            submitBtn.style.border = "1px solid rgba(246, 70, 93, 0.5)";
            submitBtn.style.color = "#fff";
        }
        submitText.textContent = spotTradeState.side === 'BUY'
            ? (spotTradeState.type === 'MARKET' ? "Market Alış Yap" : "Limit Alış Yap")
            : (spotTradeState.type === 'MARKET' ? "Market Satış Yap" : "Limit Satış Yap");
    }
    
    // Tutar (quote) satırında kullanılabilir: Alışta quote, Miktar (base) satırında: Satışta base
    const availableQuoteWrap = document.getElementById("bnTradeAvailableQuoteWrap");
    const availableQuoteEl = document.getElementById("bnTradeAvailableQuote");
    const availableBaseWrap = document.getElementById("bnTradeAvailableBaseWrap");
    const availableBaseEl = document.getElementById("bnTradeAvailableBase");
    if (availableQuoteWrap && availableQuoteEl) {
        if (spotTradeState.side === 'BUY') {
            availableQuoteWrap.style.display = "";
            availableQuoteEl.textContent = fmtNum(spotTradeState.quoteAvailable ?? spotTradeState.quoteBalance ?? 0, getQuoteAssetDecimals(spotTradeState.quoteAsset));
        } else {
            availableQuoteWrap.style.display = "none";
        }
    }
    if (availableBaseWrap && availableBaseEl) {
        if (spotTradeState.side === 'SELL') {
            availableBaseWrap.style.display = "";
            availableBaseEl.textContent = fmtNum(spotTradeState.baseAvailable ?? spotTradeState.baseBalance ?? 0, getStepDecimals(spotTradeState.stepSizeStr || spotTradeState.stepSize));
        } else {
            availableBaseWrap.style.display = "none";
        }
    }

    // Modal UI only – no fetch. Fee rates from ensureFeeRates cache; balance from quick_data/handleSpotEngineData.
    updateTradeSummary();
}

/** Alım/Satım modalı: sembole ait son 24 saat grafiği (5m x 288). Geçersiz paritede Binance çağrılmaz. */
async function loadTradeModalChart(symbol) {
    const wrap = document.getElementById('bnTradeChartWrap');
    const container = document.getElementById('bnTradeChart');
    const dailyLowEl = document.getElementById('bnTradeDailyLow');
    const dailyHighEl = document.getElementById('bnTradeDailyHigh');
    const yearlyLowEl = document.getElementById('bnTradeYearlyLow');
    const yearlyHighEl = document.getElementById('bnTradeYearlyHigh');
    if (!wrap || !container) return;
    const normalized = normalizeModalSymbol(symbol || '');
    const invalidChartSymbols = ['USDTUSDT', 'USDCUSDT', 'FDUSDUSDT', 'BUSDUSDT', 'TUSDUSDT', 'DAIUSDT'];
    if (normalized.invalid || !normalized.normalized || invalidChartSymbols.includes((normalized.normalized || '').toUpperCase())) {
        container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--ds-text-tertiary);font-size:0.85rem;">Geçersiz parite</div>';
        if (dailyLowEl) dailyLowEl.textContent = '—';
        if (dailyHighEl) dailyHighEl.textContent = '—';
        if (yearlyLowEl) yearlyLowEl.textContent = '—';
        if (yearlyHighEl) yearlyHighEl.textContent = '—';
        return;
    }
    const chartSymbol = normalized.normalized;
    container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--ds-text-secondary);font-size:0.9rem;">Yükleniyor...</div>';
    if (dailyLowEl) dailyLowEl.textContent = '—';
    if (dailyHighEl) dailyHighEl.textContent = '—';
    if (yearlyLowEl) yearlyLowEl.textContent = '—';
    if (yearlyHighEl) yearlyHighEl.textContent = '—';
    const formatPrice = (v) => (v != null && Number.isFinite(v) && v > 0) ? (spotTradeState.quoteAsset === 'USDT' || !spotTradeState.quoteAsset ? fmtUsd(v) : (fmtNum(v, 8) + ' ' + (spotTradeState.quoteAsset || ''))) : '—';
    try {
        const interval = '5m';
        const limit = 288;
        const data = await window.apiClient.get(`/api/spot/klines?symbol=${encodeURIComponent(chartSymbol)}&interval=${interval}&limit=${limit}`);
        if (!Array.isArray(data) || data.length < 2) {
            container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--ds-text-secondary);font-size:0.85rem;">Veri yok</div>';
            return;
        }
        const points = data.map(k => ({
            t: Number(k.t),
            o: Number(k.o),
            h: Number(k.h),
            l: Number(k.l),
            c: Number(k.c)
        }));
        const dayLow = Math.min(...points.map(p => p.l));
        const dayHigh = Math.max(...points.map(p => p.h));
        const dataMin = dayLow;
        const dataMax = dayHigh;
        const range = dataMax - dataMin || 1;
        const w = 400;
        const h = 120;
        const pad = 20;
        const linePoints = points.map((p, i) => {
            const x = pad + (i / (points.length - 1 || 1)) * (w - 2 * pad);
            const y = pad + (1 - (p.c - dataMin) / range) * (h - 2 * pad);
            return { x, y };
        });
        const pathD = linePoints.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ');
        const first = points[0].c;
        const last = points[points.length - 1].c;
        const isUp = last >= first;
        const UP = '#00C076';
        const DOWN = '#F6465D';
        const stroke = isUp ? UP : DOWN;
        container.innerHTML = `
            <svg width="100%" height="100%" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
                <defs>
                    <linearGradient id="tradeChartGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0" stop-color="${stroke}" stop-opacity="0.25"/>
                        <stop offset="1" stop-color="${stroke}" stop-opacity="0"/>
                    </linearGradient>
                </defs>
                <path d="${pathD} L ${linePoints[linePoints.length-1].x} ${h-pad} L ${pad} ${h-pad} Z" fill="url(#tradeChartGrad)" stroke="${stroke}" stroke-width="1.5" fill-opacity="1"/>
            </svg>`;
        if (dailyLowEl) dailyLowEl.textContent = formatPrice(dayLow);
        if (dailyHighEl) dailyHighEl.textContent = formatPrice(dayHigh);
        if (!invalidChartSymbols.includes((chartSymbol || '').toUpperCase())) {
            window.apiClient.get(`/api/spot/klines?symbol=${encodeURIComponent(chartSymbol)}&interval=1d&limit=365`)
                .then((klines1d) => {
                    if (Array.isArray(klines1d) && klines1d.length > 0) {
                        const yLow = Math.min(...klines1d.map(c => Number(c.l)));
                        const yHigh = Math.max(...klines1d.map(c => Number(c.h)));
                        if (yearlyLowEl) yearlyLowEl.textContent = formatPrice(yLow);
                        if (yearlyHighEl) yearlyHighEl.textContent = formatPrice(yHigh);
                    }
                }).catch(() => {});
        }
    } catch (e) {
        if (typeof window.__DEBUG_DASH__ !== 'undefined' && window.__DEBUG_DASH__) console.warn('[dashboard] loadTradeModalChart error:', e);
        container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--ds-text-tertiary);font-size:0.85rem;">Grafik yüklenemedi</div>';
    }
}

async function loadExchangeInfo() {
    if (!State.accountId || !spotTradeState.symbol) return;
    
    // Filter out invalid symbols like USDTUSDT, USDCUSDT, FDUSDUSDT
    const invalidSymbols = ["USDTUSDT", "USDCUSDT", "FDUSDUSDT", "BUSDUSDT", "TUSDUSDT", "DAIUSDT"];
    if (invalidSymbols.includes(spotTradeState.symbol.toUpperCase())) {
        console.warn("[dashboard] Invalid symbol for exchange_info:", spotTradeState.symbol);
        return;
    }
    
    try {
        // Binance kaldırıldı – default değerler (sonra temiz kurulum ile eklenecek)
        spotTradeState.stepSize = 0.00000001;
        spotTradeState.tickSize = 0.01;
        spotTradeState.minNotional = 10.0;
    } catch (error) {
        console.error("[dashboard] Error loading exchange info:", error);
    }
}

let feeRatesCache = null;
let feeRatesInflight = null;

async function ensureFeeRates(accountId) {
    if (!accountId) return feeRatesCache;
    if (feeRatesCache && feeRatesCache.accountId === accountId) return Promise.resolve(feeRatesCache);
    
    window.binanceFeeRates = { taker: 0.001, maker: 0.001, taker_pct: 0.1, maker_pct: 0.1 };
    try {
        const data = await window.apiClient.get(`/api/spot/commission?account_id=${accountId}`);
        if (data && (data.maker !== undefined || data.taker !== undefined)) {
            const maker = data.maker != null ? data.maker : 0.001;
            const taker = data.taker != null ? data.taker : 0.001;
            window.binanceFeeRates = {
                maker,
                taker,
                maker_pct: data.maker_pct != null ? data.maker_pct : (maker * 100),
                taker_pct: data.taker_pct != null ? data.taker_pct : (taker * 100)
            };
        }
    } catch (e) {
        // 404 = endpoint yok veya backend güncel değil; varsayılan 0.1% kullan, konsolu kirletme
        if (typeof window.__DEBUG_DASH__ !== 'undefined' && window.__DEBUG_DASH__) {
            console.warn("[dashboard] Commission API failed, using default 0.1%:", e?.message || e);
        }
    }
    feeRatesCache = { accountId, ...window.binanceFeeRates };
    return Promise.resolve(feeRatesCache);
}

async function loadTradeAvailableBalance() {
    if (!State.accountId || !spotTradeState.symbol) return;
    if (!isBinanceTabActive()) return;
    
    try {
        spotTradeState.quoteBalance = 0;
        spotTradeState.baseBalance = 0;
        spotTradeState.quoteAvailable = 0;
        spotTradeState.baseAvailable = 0;
        spotTradeState.availableBalance = 0;
        const totalInput = document.getElementById("bnTradeTotal");
        if (totalInput) totalInput.value = "0.00";
        updateSpotTradeModal();
    } catch (error) {
        console.error("[dashboard] Error loading available balance:", error);
    }
}

// Real-time balance update (only when Binance tab active; modal does not trigger wallet fetch storm)
function startBalanceUpdates() {
    if (!isBinanceTabActive()) return;
    
    window.intervalRegistry.stop('trade.balance');
    loadTradeAvailableBalance();
    
    window.intervalRegistry.start('trade.balance', () => {
        if (!isBinanceTabActive() || !spotTradeState.symbol) return;
        loadTradeAvailableBalance();
    }, 2000, 'trade');
}

function stopBalanceUpdates() {
    // REFACTOR: Use intervalRegistry
    window.intervalRegistry.stop('trade.balance');
}

async function updateModalPrice() {
    if (!spotTradeState.symbol || !State.accountId) return;
    
    try {
        // Use marketStore ONLY - no fallback API calls
        const price = window.marketStore?.getPrice(spotTradeState.symbol);
        if (price !== undefined && price !== null && price > 0) {
            // Update price display
            updatePriceDisplay(price);
            return;
        }
        
        // If marketStore doesn't have price, show "—" or wait
        // NO FALLBACK API CALLS - prevents rate limit
        const priceEl = document.getElementById("bnTradePrice");
        if (priceEl && (!price || price === 0)) {
            // Price not available yet, show placeholder
            const quoteAsset = spotTradeState.quoteAsset || 'USDT';
            if (quoteAsset === 'USDT' || quoteAsset === 'FDUSD' || quoteAsset === 'BUSD' || quoteAsset === 'USDC' || quoteAsset === 'TUSD' || quoteAsset === 'DAI') {
                priceEl.textContent = "$—";
            } else {
                priceEl.textContent = "—";
            }
        }
    } catch (error) {
        console.error("[dashboard] Error updating modal price:", error);
    }
}

// Fiyat gösterimini güncelle (optimize edilmiş, hızlı). Hata/null'da 0.00 gösterme; epsilon ile gereksiz DOM atlanır.
function updatePriceDisplay(price) {
    const priceEl = document.getElementById("bnTradePrice");
    if (!priceEl) return;
    
    const prevPrice = spotTradeState.currentPrice;
    const num = price != null && Number.isFinite(price) ? Number(price) : NaN;
    if (num <= 0 || isNaN(num)) {
        if (prevPrice > 0) priceEl.textContent = (spotTradeState.quoteAsset === 'USDT' || !spotTradeState.quoteAsset) ? '$—' : '—';
        spotTradeState.currentPrice = null;
        return;
    }
    if (prevPrice > 0) {
        const epsAbs = 1e-10;
        const epsRel = 1e-6;
        const diff = Math.abs(num - prevPrice);
        if (diff <= epsAbs || (prevPrice > 0 && diff / prevPrice <= epsRel)) return;
    }
    spotTradeState.currentPrice = num;
    
    const quoteAsset = spotTradeState.quoteAsset || 'USDT';
    let priceDisplay = '';
    if (quoteAsset === 'USDT' || quoteAsset === 'FDUSD' || quoteAsset === 'BUSD' || quoteAsset === 'USDC' || quoteAsset === 'TUSD' || quoteAsset === 'DAI') {
        priceDisplay = fmtCoinPrice(num);
    } else if (quoteAsset === 'BTC') {
        priceDisplay = `${fmtNum(num, 8)} BTC`;
    } else if (quoteAsset === 'ETH') {
        priceDisplay = `${fmtNum(num, 6)} ETH`;
    } else if (quoteAsset === 'BNB') {
        priceDisplay = `${fmtNum(num, 4)} BNB`;
    } else {
        priceDisplay = `${fmtNum(num, 8)} ${quoteAsset}`;
    }
    priceEl.textContent = priceDisplay;
    priceEl.classList.remove("price-up", "price-down");
    
    if (prevPrice > 0 && prevPrice !== num) {
        if (num > prevPrice) {
            priceEl.classList.add("price-up");
            setTimeout(() => {
                if (priceEl) priceEl.classList.remove("price-up");
            }, 200);
        } else if (num < prevPrice) {
            priceEl.classList.add("price-down");
            setTimeout(() => {
                if (priceEl) priceEl.classList.remove("price-down");
            }, 200);
        }
    }
    
    const limitPriceInput = document.getElementById("bnLimitPrice");
    if (limitPriceInput && spotTradeState.type === 'LIMIT' && !spotTradeState.limitPriceEdited) {
        limitPriceInput.value = num.toFixed(2);
    }
    
    // Real-time calculation update - update trade summary if needed
    updateTradeSummary();
}

// Modal için tek kaynak: ticker_24h API. Flicker önlemek için handleSpotEngineData ve updateModalPriceChange bu elementi güncellemez.
function setModalPriceChangePlaceholder() {
    const changeEl = document.getElementById("bnTradePriceChange");
    if (changeEl) {
        changeEl.textContent = "—";
        changeEl.style.color = "var(--ds-text-secondary)";
        changeEl.style.fontWeight = "600";
    }
}

// Fiyat değişim yüzdesini güncelle (24h ticker verilerinden) - Sadece trade.modalSpotPrice interval kullanıyor; bu fonksiyon modal % için artık kullanılmıyor (flicker önlemi).
let priceChangeCache = {}; // Cache for price change to prevent flickering

async function updateModalPriceChange() {
    if (!spotTradeState.symbol || !State.accountId) return;
    if (document.getElementById("bnSpotTradeModal")?.style.display === "block") return;
    
    const changeEl = document.getElementById("bnTradePriceChange");
    if (!changeEl) return;
    
    try {
        // REFACTOR: Use marketStore instead of coin-specific ticker request
        // Get price change from marketStore (no separate request needed)
        const mini = window.marketStore?.getMini(spotTradeState.symbol);
        if (mini && mini.changePct !== undefined && mini.changePct != null) {
            const priceChangePercent = mini.changePct;
            
            // Update cache
            priceChangeCache[spotTradeState.symbol] = priceChangePercent;
            
            if (priceChangePercent !== 0) {
                const sign = priceChangePercent > 0 ? '+' : '';
                changeEl.textContent = `${sign}${priceChangePercent.toFixed(2)}%`;
                changeEl.style.color = priceChangePercent > 0 ? '#0ecb81' : '#f6465d';
                changeEl.style.fontWeight = "600";
            } else {
                // If 0, show cached value or empty
                if (priceChangeCache[spotTradeState.symbol] !== undefined) {
                    const cached = priceChangeCache[spotTradeState.symbol];
                    if (cached !== 0) {
                        const sign = cached > 0 ? '+' : '';
                        changeEl.textContent = `${sign}${cached.toFixed(2)}%`;
                        changeEl.style.color = cached > 0 ? "#0ecb81" : "#f6465d";
                        changeEl.style.fontWeight = "600";
                    } else {
                        changeEl.textContent = "0.00%";
                        changeEl.style.color = 'var(--ds-text-secondary)';
                    }
                } else {
                    changeEl.textContent = "0.00%";
                    changeEl.style.color = 'var(--ds-text-secondary)';
                }
            }
            return;
        }
        
        // Fallback: On error, keep cached value if available
        if (priceChangeCache[spotTradeState.symbol] !== undefined) {
            const cached = priceChangeCache[spotTradeState.symbol];
            if (cached !== 0) {
                const sign = cached > 0 ? '+' : '';
                changeEl.textContent = `${sign}${cached.toFixed(2)}%`;
                changeEl.style.color = cached > 0 ? "#0ecb81" : "#f6465d";
                changeEl.style.fontWeight = "600";
            }
        }
    } catch (error) {
        // On error, keep cached value if available - don't clear
        if (priceChangeCache[spotTradeState.symbol] !== undefined) {
            const cached = priceChangeCache[spotTradeState.symbol];
            if (cached !== 0) {
                const sign = cached > 0 ? '+' : '';
                changeEl.textContent = `${sign}${cached.toFixed(2)}%`;
                changeEl.style.color = cached > 0 ? "#0ecb81" : "#f6465d";
                changeEl.style.fontWeight = "600";
            }
        }
    }
}

function startModalPriceUpdates() {
    // REFACTOR: Use intervalRegistry - stop existing first
    window.intervalRegistry.stop('trade.modalPrice');
    window.intervalRegistry.stop('trade.priceChange');
    
    // Update price IMMEDIATELY (don't wait for interval) - ULTRA FAST
    if (spotTradeState.symbol) {
        updateModalPrice();
        updateModalPriceChange();
    }
    
    // REFACTOR: Use intervalRegistry instead of setInterval
    window.intervalRegistry.stop('trade.modalPrice');
    window.intervalRegistry.stop('trade.priceChange');
    
    window.intervalRegistry.start('trade.modalPrice', () => {
        if (spotTradeState.symbol) {
            updateModalPrice();
        }
    }, 200, 'trade'); // 200ms - Balanced speed
    
    // Update price change less frequently (every 1s) to avoid flickering
    window.intervalRegistry.start('trade.priceChange', () => {
        if (spotTradeState.symbol) {
            updateModalPriceChange();
        }
    }, 1000, 'trade'); // Update price change every 1 second
}

async function submitSpotTrade() {
    if (!State.accountId || !spotTradeState.symbol) {
        showError("Eksik bilgi");
        return;
    }
    
    const qtyInput = document.getElementById("bnTradeQuantity");
    const totalInput = document.getElementById("bnTradeTotal");
    const limitPriceInput = document.getElementById("bnLimitPrice");
    const errorEl = document.getElementById("bnTradeError");
    const submitBtn = document.getElementById("bnTradeSubmitBtn");
    
    // Get and quantize values
    let quantity = parseFloat(qtyInput.value) || 0;
    let quoteOrderQty = spotTradeState.side === 'BUY' && spotTradeState.type === 'MARKET' ? (parseFloat(totalInput.value) || 0) : null;
    let price = spotTradeState.type === 'LIMIT' ? (parseFloat(limitPriceInput.value) || 0) : null;
    
    // Quantize quantity to step size
    if (quantity > 0) {
        quantity = quantizeQuantity(quantity);
        const decimals = getStepDecimals(spotTradeState.stepSizeStr || spotTradeState.stepSize);
        // Ensure quantity is properly formatted as string to avoid floating point issues
        quantity = parseFloat(quantity.toFixed(decimals));
        qtyInput.value = quantity.toFixed(decimals);
    }
    
    // Quantize price to tick size (for LIMIT orders)
    if (price > 0) {
        price = quantizePrice(price);
        const decimals = getDecimalPlaces(spotTradeState.tickSize);
        // Ensure price is properly formatted
        price = parseFloat(price.toFixed(decimals));
        limitPriceInput.value = price.toFixed(decimals);
    }
    
    // Validate minimum quantity
    if (quantity > 0) {
        const minQty = spotTradeState.minQty || spotTradeState.stepSize || 0;
        if (minQty > 0 && quantity < minQty) {
            if (errorEl) {
                errorEl.textContent = `Minimum miktar: ${minQty}`;
                errorEl.style.display = "block";
            }
            if (submitBtn) submitBtn.disabled = false;
            return;
        }
    }

    // SELL: kullanılabilir bakiyeyi aşma (LOT_SIZE önleme)
    if (spotTradeState.side === 'SELL' && quantity > 0) {
        var maxSell = getMaxSellQuantity();
        if (maxSell > 0) {
            quantity = Math.min(quantity, maxSell);
            quantity = quantizeQuantity(quantity);
            var decSell = getStepDecimals(spotTradeState.stepSizeStr || spotTradeState.stepSize);
            quantity = parseFloat(quantity.toFixed(decSell));
            if (qtyInput) qtyInput.value = quantity.toFixed(decSell);
        }
        if (quantity <= 0) {
            if (errorEl) {
                errorEl.textContent = 'Satılabilir miktar lot adımına uymuyor veya bakiye yetersiz.';
                errorEl.style.display = 'block';
            }
            if (submitBtn) submitBtn.disabled = false;
            return;
        }
    }
    
    // Validation
    if (spotTradeState.type === 'LIMIT' && (!price || price <= 0)) {
        if (errorEl) {
            errorEl.textContent = "Limit fiyat giriniz";
            errorEl.style.display = "block";
        }
        if (submitBtn) submitBtn.disabled = false;
        return;
    }
    
    if (spotTradeState.side === 'BUY' && spotTradeState.type === 'MARKET') {
        // MARKET BUY: quoteOrderQty gerekli
        if (!quoteOrderQty || quoteOrderQty <= 0) {
            if (errorEl) {
                errorEl.textContent = "Tutar giriniz";
                errorEl.style.display = "block";
            }
            if (submitBtn) submitBtn.disabled = false;
            return;
        }
        // Validate minimum notional for MARKET BUY (convert quoteOrderQty to USD)
        if (spotTradeState.minNotional > 0) {
            const quoteAsset = spotTradeState.quoteAsset || 'USDT';
            let quoteOrderQtyUsd = quoteOrderQty;
            
            // Convert quote asset to USD if not USDT/USD stablecoin
            if (quoteAsset !== 'USDT' && quoteAsset !== 'FDUSD' && quoteAsset !== 'BUSD' && 
                quoteAsset !== 'USDC' && quoteAsset !== 'TUSD' && quoteAsset !== 'DAI') {
                // Try to get quote asset price in USD from wallet data
                const quotePriceUsd = window.binanceQuoteAssetPrices?.[quoteAsset] || 0;
                if (quotePriceUsd > 0) {
                    quoteOrderQtyUsd = quoteOrderQty * quotePriceUsd;
                } else {
                    // If price not available, skip validation (Binance will reject if too small)
                    console.warn(`[dashboard] Quote asset ${quoteAsset} USD price not available, skipping minNotional check`);
                }
            }
            
            if (quoteOrderQtyUsd > 0 && quoteOrderQtyUsd < spotTradeState.minNotional) {
                if (errorEl) {
                    errorEl.textContent = `Minimum işlem tutarı: $${spotTradeState.minNotional.toFixed(2)} USD`;
                    errorEl.style.display = "block";
                }
                if (submitBtn) submitBtn.disabled = false;
                return;
            }
        }
    } else if (spotTradeState.type === 'LIMIT') {
        // LIMIT orders (BUY/SELL): quantity ve price gerekli
        if (!quantity || quantity <= 0) {
            if (errorEl) {
                errorEl.textContent = "Miktar giriniz";
                errorEl.style.display = "block";
            }
            if (submitBtn) submitBtn.disabled = false;
            return;
        }
        
        // Validate minimum notional for LIMIT orders
        if (spotTradeState.minNotional > 0 && price > 0) {
            const notional = quantity * price;
            const quoteAsset = spotTradeState.quoteAsset || 'USDT';
            let notionalUsd = notional;
            
            // Convert quote asset to USD if not USDT/USD stablecoin
            if (quoteAsset !== 'USDT' && quoteAsset !== 'FDUSD' && quoteAsset !== 'BUSD' && 
                quoteAsset !== 'USDC' && quoteAsset !== 'TUSD' && quoteAsset !== 'DAI') {
                // Try to get quote asset price in USD from wallet data
                const quotePriceUsd = window.binanceQuoteAssetPrices?.[quoteAsset] || 0;
                if (quotePriceUsd > 0) {
                    notionalUsd = notional * quotePriceUsd;
                } else {
                    // If price not available, skip validation (Binance will reject if too small)
                    console.warn(`[dashboard] Quote asset ${quoteAsset} USD price not available, skipping minNotional check`);
                    notionalUsd = 0; // Skip validation
                }
            }
            
            if (notionalUsd > 0 && notionalUsd < spotTradeState.minNotional) {
                if (errorEl) {
                    errorEl.textContent = `Minimum işlem tutarı: $${spotTradeState.minNotional.toFixed(2)} USD`;
                    errorEl.style.display = "block";
                }
                if (submitBtn) submitBtn.disabled = false;
                return;
            }
        }
    } else {
        // MARKET SELL: quantity gerekli
        if (!quantity || quantity <= 0) {
            if (errorEl) {
                errorEl.textContent = "Miktar giriniz";
                errorEl.style.display = "block";
            }
            if (submitBtn) submitBtn.disabled = false;
            return;
        }
        
        // Validate minimum notional for MARKET SELL (convert to USD)
        if (spotTradeState.minNotional > 0 && spotTradeState.currentPrice > 0) {
            const notional = quantity * spotTradeState.currentPrice;
            const quoteAsset = spotTradeState.quoteAsset || 'USDT';
            let notionalUsd = notional;
            
            // Convert quote asset to USD if not USDT/USD stablecoin
            if (quoteAsset !== 'USDT' && quoteAsset !== 'FDUSD' && quoteAsset !== 'BUSD' && 
                quoteAsset !== 'USDC' && quoteAsset !== 'TUSD' && quoteAsset !== 'DAI') {
                // Try to get quote asset price in USD from wallet data
                const quotePriceUsd = window.binanceQuoteAssetPrices?.[quoteAsset] || 0;
                if (quotePriceUsd > 0) {
                    notionalUsd = notional * quotePriceUsd;
                } else {
                    // If price not available, skip validation (Binance will reject if too small)
                    console.warn(`[dashboard] Quote asset ${quoteAsset} USD price not available, skipping minNotional check`);
                    notionalUsd = 0; // Skip validation
                }
            }
            
            if (notionalUsd > 0 && notionalUsd < spotTradeState.minNotional) {
                if (errorEl) {
                    errorEl.textContent = `Minimum işlem tutarı: $${spotTradeState.minNotional.toFixed(2)} USD`;
                    errorEl.style.display = "block";
                }
                if (submitBtn) submitBtn.disabled = false;
                return;
            }
        }
    }
    
    // Hide error
    if (errorEl) errorEl.style.display = "none";
    
    // Disable button
    if (submitBtn) {
        submitBtn.disabled = true;
        const originalText = submitBtn.textContent;
        submitBtn.textContent = "Gönderiliyor...";
        
        try {
            // Use YENİ Spot Engine for order placement - FLASH HIZLI
            const engine = getSpotEngine(State.accountId);
            
            const orderResult = await engine.placeOrder({
                symbol: spotTradeState.symbol,
                side: spotTradeState.side,
                type: spotTradeState.type,
                quantity: (spotTradeState.type === 'LIMIT' || spotTradeState.side === 'SELL') ? (quantity > 0 ? quantity : null) : null,
                quote_order_qty: (spotTradeState.type === 'MARKET' && spotTradeState.side === 'BUY') ? (quoteOrderQty > 0 ? quoteOrderQty : null) : null,
                price: (spotTradeState.type === 'LIMIT' && price > 0) ? price : null
            }, new AbortController().signal);
            
            // Convert to expected format
            const result = orderResult.order || orderResult;
            
            // Success message
            const orderType = spotTradeState.type === 'MARKET' ? 'Market' : 'Limit';
            const sideText = spotTradeState.side === 'BUY' ? 'Alış' : 'Satış';
            const successMsg = `${orderType} ${sideText} emri başarıyla gönderildi`;
            
            if (window.Toast) {
                window.Toast.success(successMsg);
            }
            
            // If LIMIT order, show active orders panel and start tracking
            if (spotTradeState.type === 'LIMIT') {
                showActiveOrdersPanel();
                // Wait a bit for Binance to process the order, then load
                setTimeout(() => {
                    loadActiveOrders();
                    startActiveOrdersTracking();
                }, 1000); // 1 second delay to ensure order is registered
            } else {
                // For MARKET orders, also check if there are any pending orders
                setTimeout(() => {
                    loadActiveOrders();
                }, 500);
            }
            
            // Close modal
            closeSpotTradeModal();
            
            // Refresh wallet table (TTL-aware; force after trade)
            if (State.accountId && typeof triggerWalletRefreshForVarliklar === 'function') {
                setTimeout(function () {
                    triggerWalletRefreshForVarliklar(State.accountId, { force: true });
                }, spotTradeState.type === 'LIMIT' ? 1200 : 600);
            } else if (State.accountId && window.BinanceAssetsPanel) {
                BinanceAssetsPanel.refresh();
            }
            
        } catch (error) {
            console.error("[SPOT_ENGINE] Order error:", error);
            let errorMsg = error.message || "Bilinmeyen hata";
            
            if (error.data && typeof error.data === 'object') {
                const d = error.data.detail;
                if (d && typeof d === 'object' && typeof d.detail === 'string') {
                    errorMsg = d.detail;
                } else if (typeof d === 'string') {
                    errorMsg = d;
                }
            }
            errorMsg = String(errorMsg);
            
            // Handle specific error cases
            if (errorMsg.includes("Failed to fetch") || errorMsg.includes("NetworkError") || errorMsg.includes("Network request failed")) {
                errorMsg = "Bağlantı hatası. Lütfen internet bağlantınızı kontrol edin ve tekrar deneyin.";
            } else if (errorMsg.includes("timeout") || errorMsg.includes("zaman aşımı")) {
                errorMsg = "İstek zaman aşımına uğradı. Lütfen tekrar deneyin.";
            } else if (error.status === 502) {
                errorMsg = "Binance API hatası. Lütfen tekrar deneyin.";
            } else if (errorMsg.startsWith("HTTP ") && error.status === 400) {
                errorMsg = "Geçersiz emir parametreleri. Lütfen kontrol edin.";
            } else {
                errorMsg = translateErrorToTurkish(errorMsg);
            }
            
            if (errorEl) {
                errorEl.textContent = errorMsg;
                errorEl.style.display = "block";
            }
            if (window.Toast) {
                window.Toast.error(`Emir gönderilemedi: ${errorMsg}`);
            }
        } finally {
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.textContent = originalText;
            }
        }
    }
}

// Active Orders Management
// REFACTOR: activeOrdersInterval removed - use intervalRegistry instead
let activeOrders = [];

function showActiveOrdersPanel() {
    // Aktif Emirler sadece Anasayfa (binance) sekmesinde gösterilir
    var activeTab = document.querySelector(".dm-tab.is-active");
    if (!activeTab || activeTab.getAttribute("data-tab") !== "binance") return;
    const panel = document.getElementById("bnActiveOrdersPanel");
    if (panel) {
        panel.style.display = "block";
    }
}

/** Aktif emir varken panel üstte (varlık strip altı); yoksa her zaman İşlem Geçmişi panelinin hemen altında. */
function updateActiveOrdersPanelPosition() {
    const tab = document.getElementById("tabBinance");
    const panel = document.getElementById("bnActiveOrdersPanel");
    const assetsStrip = tab && tab.querySelector(".binance-assets-strip");
    const txPanel = document.getElementById("transactionHistoryPanel");
    if (!tab || !panel || !assetsStrip) return;
    if (activeOrders.length > 0) {
        if (assetsStrip.nextElementSibling !== panel) {
            tab.insertBefore(panel, assetsStrip.nextElementSibling);
        }
    } else {
        if (txPanel && panel.parentNode === tab) {
            txPanel.after(panel);
        }
    }
}

function hideActiveOrdersPanel() {
    const panel = document.getElementById("bnActiveOrdersPanel");
    if (panel) {
        panel.style.display = "none";
    }
}

// Active orders cache for comparison (prevent unnecessary renders)
let activeOrdersCache = null;
let activeOrdersLastRender = 0;
const ACTIVE_ORDERS_RENDER_THROTTLE = 1000; // Max 1 render per second

async function loadActiveOrders() {
    if (!State.accountId) {
        console.warn("[dashboard] loadActiveOrders: No account ID");
        return;
    }
    if (loadActiveOrders._running) return;
    loadActiveOrders._running = true;
    try {
        const url = `/api/binance/open-orders?account_id=${State.accountId}`;
        if (!window.apiClient || typeof window.apiClient.get !== 'function') throw new Error('apiClient required');
        const data = await window.apiClient.get(url, { timeout: 12000 });
        const newOrders = Array.isArray(data.orders) ? data.orders : [];
        
        // Compare with cache to avoid unnecessary renders
        const ordersChanged = !activeOrdersCache ||
            activeOrdersCache.length !== newOrders.length ||
            JSON.stringify(activeOrdersCache.map(function(o) { return { id: o.orderId || o.order_id, status: o.status, executedQty: o.executedQty }; })) !==
            JSON.stringify(newOrders.map(function(o) { return { id: o.orderId || o.order_id, status: o.status, executedQty: o.executedQty }; }));
        
        // Throttle renders (max once per second)
        const now = Date.now();
        const shouldRender = ordersChanged && (now - activeOrdersLastRender > ACTIVE_ORDERS_RENDER_THROTTLE);
        
        activeOrders = newOrders;
        activeOrdersCache = JSON.parse(JSON.stringify(newOrders));
        
        if (shouldRender) {
            renderActiveOrders();
            activeOrdersLastRender = now;
        } else if (ordersChanged) {
            updateActiveOrdersLivePrices();
        }
        
        if (activeOrders.length === 0) {
            showActiveOrdersPanel(); // Panel her zaman görünsün; liste "Aktif emir yok" gösterir
            stopActiveOrdersTracking();
            updateActiveOrdersPanelPosition(); // Cüzdan Varlıkları altına taşı
        } else {
            showActiveOrdersPanel();
            startActiveOrdersTracking();
            updateActiveOrdersPanelPosition(); // Varlık strip altına taşı
        }
    } catch (error) {
        var is429 = error && (error.status === 429 || (error.error_code && String(error.error_code).indexOf('429') !== -1));
        if (is429) {
            var retrySec = (error.retry_after != null) ? Number(error.retry_after) : 10;
            var retryMs = Math.min(60000, Math.max(1000, retrySec * 1000));
            if (window.intervalRegistry) {
                window.intervalRegistry.stop('orders:poll');
                window.intervalRegistry.stop('activeOrders.load');
                if (window.intervalRegistry.timeout && window.intervalRegistry.timeout.cancel) {
                    window.intervalRegistry.timeout.cancel('orders:resume');
                }
                if (window.intervalRegistry.timeout && window.intervalRegistry.timeout.start) {
                    window.intervalRegistry.timeout.start('orders:resume', function () {
                        if (State.accountId && typeof loadActiveOrders === 'function') loadActiveOrders();
                        if (State.accountId && window.intervalRegistry) {
                            window.intervalRegistry.start('orders:poll', function () { loadActiveOrders(); }, ORDERS_POLL_MS, 'binanceTab');
                        }
                    }, retryMs, 'binanceTab');
                }
            }
            return;
        }
        var em = error && (error.message || (typeof error.toString === 'function' ? error.toString() : ''));
        if (!em || (em.indexOf('Failed to fetch') === -1 && em.indexOf('ERR_CONNECTION_REFUSED') === -1)) {
            console.warn("[dashboard] Error loading active orders:", em || error);
        }
        activeOrders = [];
        showActiveOrdersPanel();
        renderActiveOrders();
        stopActiveOrdersTracking();
    } finally {
        loadActiveOrders._running = false;
    }
}

function renderActiveOrders() {
    const list = document.getElementById("bnActiveOrdersList");
    if (!list) {
        console.warn("[dashboard] renderActiveOrders: bnActiveOrdersList element not found");
        return;
    }
    
    if (activeOrders.length === 0) {
        list.innerHTML = '<div style="text-align: center; padding: 1rem; color: var(--ds-text-secondary);">Aktif emir yok</div>';
        updateActiveOrdersPanelPosition();
        return;
    }
    
    // Only log if actually rendering (not throttled)
    // console.log("[dashboard] Rendering", activeOrders.length, "active orders");
    
    list.innerHTML = activeOrders.map((order, index) => {
        const symbol = order.symbol || 'N/A';
        const side = order.side || 'BUY';
        const type = order.type || 'LIMIT';
        const price = parseFloat(order.price || 0);
        const qty = parseFloat(order.origQty || order.quantity || 0);
        const executedQty = parseFloat(order.executedQty || 0);
        const status = order.status || 'NEW';
        const orderId = order.orderId || order.order_id || 'N/A';
        const time = order.time ? new Date(order.time).toLocaleString('tr-TR') : 'N/A';
        
        const sideColor = side === 'BUY' ? '#0ecb81' : '#f6465d';
        const sideText = side === 'BUY' ? 'Alış' : 'Satış';
        const statusText = {
            'NEW': 'Beklemede',
            'PARTIALLY_FILLED': 'Kısmen Gerçekleşti',
            'FILLED': 'Tamamlandı',
            'CANCELED': 'İptal Edildi',
            'EXPIRED': 'Süresi Doldu'
        }[status] || status;
        
        const progress = qty > 0 ? (executedQty / qty * 100) : 0;
        const totalValue = price * qty;
        const executedValue = price * executedQty;
        
        // Extract quote asset from symbol (e.g., ETHBTC -> BTC)
        let quoteAsset = 'USDT';
        const quoteAssets = ['USDT', 'FDUSD', 'BUSD', 'USDC', 'TUSD', 'DAI', 'BTC', 'ETH', 'BNB'];
        for (const qa of quoteAssets) {
            if (symbol.endsWith(qa)) {
                quoteAsset = qa;
                break;
            }
        }
        
        // Format price based on quote asset
        let priceDisplay = 'Market';
        if (price > 0) {
            if (quoteAsset === 'USDT' || quoteAsset === 'FDUSD' || quoteAsset === 'BUSD' || quoteAsset === 'USDC' || quoteAsset === 'TUSD' || quoteAsset === 'DAI') {
                priceDisplay = fmtCoinPrice(price);
            } else if (quoteAsset === 'BTC') {
                priceDisplay = `${fmtNum(price, 8)} BTC`;
            } else if (quoteAsset === 'ETH') {
                priceDisplay = `${fmtNum(price, 6)} ETH`;
            } else if (quoteAsset === 'BNB') {
                priceDisplay = `${fmtNum(price, 4)} BNB`;
            } else {
                priceDisplay = `${fmtNum(price, 8)} ${quoteAsset}`;
            }
        }
        
        // Live price will be updated by updateActiveOrderLivePrice
        const livePriceId = `livePrice_${orderId}_${index}`;
        
        return `
            <div id="activeOrder_${orderId}_${index}" style="border: 1px solid var(--ds-border); border-radius: 8px; padding: 12px; background: var(--ds-bg-secondary);">
                <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 8px;">
                    <div>
                        <strong style="color: ${sideColor};">${symbol}</strong>
                        <span style="margin-left: 8px; color: var(--ds-text-secondary); font-size: 0.85rem;">${sideText} • ${type}</span>
                        <div style="margin-top: 4px; font-size: 0.8rem; color: var(--ds-text-secondary);">
                            Canlı Fiyat: <span id="${livePriceId}" style="color: var(--ds-accent); font-weight: 600;">Yükleniyor...</span>
                        </div>
                    </div>
                    <div style="text-align: right; font-size: 0.85rem; color: var(--ds-text-secondary);">
                        ${statusText}
                    </div>
                </div>
                <div style="display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 8px; margin-bottom: 8px; font-size: 0.9rem;">
                    <div>
                        <div style="color: var(--ds-text-secondary); font-size: 0.8rem;">Emir Fiyatı</div>
                        <div>${priceDisplay}</div>
                    </div>
                    <div>
                        <div style="color: var(--ds-text-secondary); font-size: 0.8rem;">Miktar</div>
                        <div>${fmtNum(qty, 8)}</div>
                    </div>
                    <div>
                        <div style="color: var(--ds-text-secondary); font-size: 0.8rem;">Tutar</div>
                        <div>${fmtUsd(totalValue)}</div>
                    </div>
                    <div>
                        <div style="color: var(--ds-text-secondary); font-size: 0.8rem;">Gerçekleşen</div>
                        <div>${fmtNum(executedQty, 8)}<br><span style="font-size: 0.75rem; color: var(--ds-text-secondary);">${fmtUsd(executedValue)}</span></div>
                    </div>
                </div>
                ${progress > 0 ? `
                    <div style="margin-top: 8px;">
                        <div style="background: var(--ds-bg-tertiary); border-radius: 4px; height: 6px; overflow: hidden;">
                            <div style="background: ${sideColor}; height: 100%; width: ${progress}%; transition: width 0.3s;"></div>
                        </div>
                        <div style="text-align: center; font-size: 0.75rem; color: var(--ds-text-secondary); margin-top: 4px;">
                            %${progress.toFixed(1)} gerçekleşti
                        </div>
                    </div>
                ` : ''}
                <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 12px;">
                    <div style="font-size: 0.75rem; color: var(--ds-text-secondary);">
                        Emir ID: ${orderId} • ${time}
                    </div>
                    ${status === 'NEW' || status === 'PARTIALLY_FILLED' ? `
                        <button 
                            onclick="cancelOrder('${symbol}', ${orderId})" 
                            style="background: rgba(246, 70, 93, 0.15); border: 1px solid #f6465d; color: #f6465d; padding: 0.4rem 0.8rem; border-radius: 4px; cursor: pointer; font-size: 0.85rem; font-weight: 500; transition: all 0.2s;"
                            onmouseover="this.style.background='rgba(246, 70, 93, 0.25)'"
                            onmouseout="this.style.background='rgba(246, 70, 93, 0.15)'"
                        >
                            İptal Et
                        </button>
                    ` : ''}
                </div>
            </div>
        `;
    }).join("");
    
    updateActiveOrdersPanelPosition();
    // Load live prices for all active orders
    // Try to use wallet data first, then fallback to direct fetch
    updateActiveOrdersLivePrices();
}

// Update active orders live prices from wallet data (more efficient)
function updateActiveOrdersLivePricesFromWallet(walletData) {
    if (!walletData || !walletData.assets) return;
    
    const list = document.getElementById("bnActiveOrdersList");
    if (!list) return;
    
    // Create a map of trading pairs to prices from wallet data
    const priceMap = {};
    walletData.assets.forEach(asset => {
        // Don't create invalid symbols like USDTUSDT, USDCUSDT, FDUSDUSDT
        const stablecoins = ["USDT", "USDC", "FDUSD", "BUSD", "TUSD", "DAI"];
        let tradingPair = asset.trading_pair;
        if (!tradingPair && !stablecoins.includes(asset.asset)) {
            tradingPair = `${asset.asset}USDT`;
        } else if (!tradingPair) {
            tradingPair = null; // Skip stablecoins
        }
        const priceInQuote = asset.price_in_quote || asset.price_usd || asset.usd_price || 0;
        if (priceInQuote > 0) {
            priceMap[tradingPair] = priceInQuote;
        }
    });
    
    // Get missing prices from marketStore (no API fallback)
    const symbols = [...new Set(activeOrders.map(o => o.symbol))];
    // Filter out invalid symbols like USDTUSDT, USDCUSDT, FDUSDUSDT
    const invalidSymbols = ["USDTUSDT", "USDCUSDT", "FDUSDUSDT", "BUSDUSDT", "TUSDUSDT", "DAIUSDT"];
    const validSymbols = symbols.filter(s => !invalidSymbols.includes(s));
    const missingSymbols = validSymbols.filter(s => !priceMap[s]);
    
    // Fill missing prices from marketStore
    if (missingSymbols.length > 0 && window.marketStore) {
        missingSymbols.forEach(symbol => {
            const price = window.marketStore.getPrice(symbol);
            if (price !== undefined && price !== null && price > 0) {
                priceMap[symbol] = price;
            }
        });
    }
    
    // Update prices (no API fallback)
    updateActiveOrdersPrices(priceMap);
}

// Helper function to update active orders prices
function updateActiveOrdersPrices(priceMap) {
    if (!window.activeOrderPriceCache) {
        window.activeOrderPriceCache = {};
    }
    if (!window.activeOrderPriceLoaded) {
        window.activeOrderPriceLoaded = {};
    }
    
    activeOrders.forEach((order, index) => {
        const symbol = order.symbol;
        const livePrice = priceMap[symbol] || 0;
        const orderId = order.orderId || order.order_id || 'N/A';
        const livePriceId = `livePrice_${orderId}_${index}`;
        const livePriceEl = document.getElementById(livePriceId);
        
        if (!livePriceEl) return;
        
        const cacheKey = `${symbol}_${orderId}`;
        const isLoaded = window.activeOrderPriceLoaded[cacheKey];
        const prevPrice = window.activeOrderPriceCache[cacheKey];
        
        if (livePrice > 0) {
            // Extract quote asset from symbol
            let quoteAsset = 'USDT';
            const quoteAssets = ['USDT', 'FDUSD', 'BUSD', 'USDC', 'TUSD', 'DAI', 'BTC', 'ETH', 'BNB'];
            for (const qa of quoteAssets) {
                if (symbol.endsWith(qa)) {
                    quoteAsset = qa;
                    break;
                }
            }
            
            // Format price based on quote asset
            let priceDisplay = '';
            if (quoteAsset === 'USDT' || quoteAsset === 'FDUSD' || quoteAsset === 'BUSD' || quoteAsset === 'USDC' || quoteAsset === 'TUSD' || quoteAsset === 'DAI') {
                priceDisplay = fmtUsd(livePrice);
            } else if (quoteAsset === 'BTC') {
                priceDisplay = `${fmtNum(livePrice, 8)} BTC`;
            } else if (quoteAsset === 'ETH') {
                priceDisplay = `${fmtNum(livePrice, 6)} ETH`;
            } else if (quoteAsset === 'BNB') {
                priceDisplay = `${fmtNum(livePrice, 4)} BNB`;
            } else {
                priceDisplay = `${fmtNum(livePrice, 8)} ${quoteAsset}`;
            }
            
            // Always update the display to ensure it's visible
            const shouldAnimate = isLoaded && prevPrice !== undefined && prevPrice !== livePrice && prevPrice > 0;
            
            let priceClass = "price-neutral";
            if (shouldAnimate) {
                priceClass = livePrice > prevPrice ? "price-up" : "price-down";
            }
            
            // Update display
            livePriceEl.textContent = priceDisplay;
            livePriceEl.classList.remove("price-up", "price-down", "price-neutral");
            if (priceClass !== "price-neutral") {
                livePriceEl.classList.add(priceClass);
                // Remove animation class after animation completes
                setTimeout(() => {
                    if (livePriceEl) {
                        livePriceEl.classList.remove("price-up", "price-down");
                    }
                }, 500);
            }
            
            // Update cache
            window.activeOrderPriceCache[cacheKey] = livePrice;
            window.activeOrderPriceLoaded[cacheKey] = true;
        }
    });
}

async function updateActiveOrdersLivePrices() {
    if (!State.accountId) return;
    
    // Get current active orders from DOM (in case they've changed)
    const list = document.getElementById("bnActiveOrdersList");
    if (!list) return;
    
    // Extract symbols from DOM
    const livePriceElements = list.querySelectorAll('[id^="livePrice_"]');
    if (livePriceElements.length === 0) return;
    
    // Get unique symbols from active orders
    const symbols = [...new Set(activeOrders.map(o => o.symbol))];
    if (symbols.length === 0) return;
    
    // Use prices from binancePriceCache (already being fetched by startBinancePriceStream)
    // If cache is empty or missing symbols, fetch directly
    const priceMap = {};
    let needFetch = false;
    
    // Check if we have prices in cache from wallet data
    if (window.binancePriceCache && Object.keys(window.binancePriceCache).length > 0) {
        // Try to get prices from cache
        // Note: binancePriceCache stores prices by asset symbol, not trading pair
        // We need to extract base asset from trading pair symbol
        symbols.forEach(symbol => {
            // Extract base asset from symbol (e.g., ETHBTC -> ETH)
            // But we need the price of the trading pair itself, not the base asset
            // So we'll still need to fetch if not in cache
            needFetch = true; // For now, always fetch to be safe
        });
    } else {
        needFetch = true;
    }
    
    // Fetch prices if needed
    if (needFetch) {
        // Filter out invalid symbols like USDTUSDT, USDCUSDT, FDUSDUSDT
        const invalidSymbols = ["USDTUSDT", "USDCUSDT", "FDUSDUSDT", "BUSDUSDT", "TUSDUSDT", "DAIUSDT"];
        const validSymbols = symbols.filter(s => !invalidSymbols.includes(s));
        
        if (validSymbols.length === 0) return;
        
        try {
            // REFACTOR: Use marketStore instead of /api/binance/prices
            // Get prices from marketStore (no separate request needed)
            const allPrices = window.marketStore?.getAllPrices() || {};
            const priceData = {};
            validSymbols.forEach(symbol => {
                const price = allPrices[symbol];
                if (price !== undefined) {
                    priceData[symbol] = price;
                }
            });
            
            if (Object.keys(priceData).length === 0) {
                return; // No prices available
            }
            
            // Convert to array format for compatibility
            const data = { prices: Object.entries(priceData).map(([symbol, price]) => ({ symbol, price })) };
            const prices = data.prices || [];
            
            // Create price map
            if (Array.isArray(prices)) {
                prices.forEach(p => {
                    if (p.symbol) {
                        const price = parseFloat(p.price) || 0;
                        priceMap[p.symbol] = price;
                    }
                });
            } else if (typeof prices === 'object') {
                // Handle object format
                Object.keys(prices).forEach(symbol => {
                    const price = parseFloat(prices[symbol]) || 0;
                    priceMap[symbol] = price;
                });
            }
        } catch (error) {
            // Don't log connection refused errors repeatedly
            if (!error.message || !error.message.includes('Failed to fetch') || !error.message.includes('ERR_CONNECTION_REFUSED')) {
                console.error("[dashboard] Error fetching prices for active orders:", error);
            }
            return;
        }
    }
    
    // Initialize cache if not exists
    if (!window.activeOrderPriceCache) {
        window.activeOrderPriceCache = {};
    }
    if (!window.activeOrderPriceLoaded) {
        window.activeOrderPriceLoaded = {};
    }
    
    // Update each order's live price
    try {
        activeOrders.forEach((order, index) => {
            const symbol = order.symbol;
            const livePrice = priceMap[symbol] || 0;
            const orderId = order.orderId || order.order_id || 'N/A';
            const livePriceId = `livePrice_${orderId}_${index}`;
            const livePriceEl = document.getElementById(livePriceId);
            
            if (!livePriceEl) {
                // Element not found - might have been removed
                return;
            }
            
            const cacheKey = `${symbol}_${orderId}`;
            const isLoaded = window.activeOrderPriceLoaded[cacheKey];
            
            if (livePrice > 0) {
                // Price found - update it
                const prevPrice = window.activeOrderPriceCache[cacheKey];
                
                // Extract quote asset from symbol
                let quoteAsset = 'USDT';
                const quoteAssets = ['USDT', 'FDUSD', 'BUSD', 'USDC', 'TUSD', 'DAI', 'BTC', 'ETH', 'BNB'];
                for (const qa of quoteAssets) {
                    if (symbol.endsWith(qa)) {
                        quoteAsset = qa;
                        break;
                    }
                }
                
                // Format price based on quote asset
                let priceDisplay = '';
                if (quoteAsset === 'USDT' || quoteAsset === 'FDUSD' || quoteAsset === 'BUSD' || quoteAsset === 'USDC' || quoteAsset === 'TUSD' || quoteAsset === 'DAI') {
                    priceDisplay = fmtUsd(livePrice);
                } else if (quoteAsset === 'BTC') {
                    priceDisplay = `${fmtNum(livePrice, 8)} BTC`;
                } else if (quoteAsset === 'ETH') {
                    priceDisplay = `${fmtNum(livePrice, 6)} ETH`;
                } else if (quoteAsset === 'BNB') {
                    priceDisplay = `${fmtNum(livePrice, 4)} BNB`;
                } else {
                    priceDisplay = `${fmtNum(livePrice, 8)} ${quoteAsset}`;
                }
                
                // Always update the display to ensure it's visible
                // But only add animation if price actually changed
                const shouldAnimate = isLoaded && prevPrice !== undefined && prevPrice !== livePrice && prevPrice > 0;
                
                let priceClass = "price-neutral";
                if (shouldAnimate) {
                    priceClass = livePrice > prevPrice ? "price-up" : "price-down";
                }
                
                // Update display
                livePriceEl.textContent = priceDisplay;
                livePriceEl.classList.remove("price-up", "price-down", "price-neutral");
                if (priceClass !== "price-neutral") {
                    livePriceEl.classList.add(priceClass);
                    // Remove animation class after animation completes
                    setTimeout(() => {
                        if (livePriceEl) {
                            livePriceEl.classList.remove("price-up", "price-down");
                        }
                    }, 500);
                }
                
                // Update cache
                window.activeOrderPriceCache[cacheKey] = livePrice;
                window.activeOrderPriceLoaded[cacheKey] = true;
            } else {
                // Price not found or 0
                // Only show "Yükleniyor..." if this is the first time (not loaded yet)
                if (!isLoaded) {
                    // Keep "Yükleniyor..." only if not loaded yet
                    if (livePriceEl.textContent === "Yükleniyor..." || !livePriceEl.textContent.trim()) {
                        // Already showing loading, don't change
                    } else {
                        // This shouldn't happen, but just in case
                        livePriceEl.textContent = "Yükleniyor...";
                    }
                } else {
                    // Already loaded before, but now price is 0 - might be temporary error
                    // Don't change the display, keep last known price
                    // Or show error only once
                    if (!window.activeOrderPriceErrorShown) {
                        window.activeOrderPriceErrorShown = {};
                    }
                    if (!window.activeOrderPriceErrorShown[cacheKey]) {
                        console.warn(`[dashboard] Price for ${symbol} is 0 or not found, keeping last known price`);
                        window.activeOrderPriceErrorShown[cacheKey] = true;
                    }
                }
            }
        });
    } catch (error) {
        console.error("[dashboard] Error updating active orders live prices:", error);
    }
}

function startActiveOrdersTracking() {
    // Sadece canlı fiyat güncellemesi; liste yüklemesi orders:poll ile startBinanceTabPolling'de (tek nokta)
    window.intervalRegistry.stop('activeOrders.prices');
    window.intervalRegistry.start('activeOrders.prices', function () {
        updateActiveOrdersLivePrices();
    }, 2000, 'binanceTab');
}

function stopActiveOrdersTracking() {
    window.intervalRegistry.stop('activeOrders.prices');
    window.intervalRegistry.stop('activeOrders.load');
}

async function cancelOrder(symbol, orderId) {
    if (!State.accountId) {
        if (window.Toast) window.Toast.error("Hesap bulunamadı");
        return;
    }
    
    if (!confirm("Bu emri iptal etmek istediğinizden emin misiniz?\n\nParite: " + symbol + "\nEmir ID: " + orderId)) {
        return;
    }
    
    try {
        const url = "/api/binance/order?account_id=" + encodeURIComponent(State.accountId) + "&symbol=" + encodeURIComponent(symbol) + "&order_id=" + encodeURIComponent(orderId);
        const opts = { method: "DELETE", headers: {} };
        var tok = localStorage.getItem("token");
        if (tok) opts.headers["Authorization"] = "Bearer " + tok;
        var r = await fetch(url, opts);
        var result = await r.json().catch(function() { return {}; });
        if (!r.ok) {
            var detail = result.detail;
            var msg = (typeof detail === "object" && detail && detail.message) ? detail.message : (result.message || result.error || "HTTP " + r.status);
            if (typeof msg !== "string") msg = JSON.stringify(msg);
            var err = new Error(msg);
            err.status = r.status;
            err.error_code = typeof detail === "object" && detail ? detail.error_code : null;
            throw err;
        }
        if (window.Toast) window.Toast.success(result.message || "Emir iptal edildi");
        await loadActiveOrders();
        if (typeof loadWallet === "function") loadWallet(true);
    } catch (error) {
        console.error("[dashboard] Cancel order error:", error);
        var errorMsg = typeof translateErrorToTurkish === "function" ? translateErrorToTurkish(error.message || "Bilinmeyen hata") : (error.message || "Bilinmeyen hata");
        if (window.Toast) window.Toast.error("Emir iptal edilemedi: " + errorMsg);
    }
}

// Make cancelOrder global
window.cancelOrder = cancelOrder;

// Coin List Tab
let coinListData = []; // All coins from API
let coinListFiltered = []; // Filtered coins for display
let coinListTop10 = []; // Top 10 coins (stable coins excluded) - for price updates
let coinListAllCoins = []; // All coins for search (includes all from Binance)
// Use window.coinListPriceCache (Binance mantığı ile aynı)
// Initialize in function, not at module level (to avoid window undefined errors)
let coinListUpdateInterval = null;
let coinListSortBy = 'marketCap'; // 'marketCap', 'volume', 'change'

// Stable coins list (excluded from top 10)
const STABLE_COINS = ["USDT", "USDC", "FDUSD", "BUSD", "TUSD", "DAI", "USDP", "USDD"];

function bindCoinList() {
    const searchInput = document.getElementById("coinListSearch");
    const sortSelect = document.getElementById("coinListSort");
    const searchResults = document.getElementById("coinListSearchResults");
    
    if (searchInput) {
        let searchTimeout = null;
        searchInput.addEventListener("input", (e) => {
            clearTimeout(searchTimeout);
            const query = e.target.value.trim();
            
            // Show search results dropdown if query exists
            if (query.length > 0) {
                searchTimeout = setTimeout(() => {
                    showCoinSearchResults(query);
                }, 200);
            } else {
                // Hide dropdown and show top 10
                if (searchResults) searchResults.style.display = 'none';
                coinListFiltered = [...coinListTop10];
                renderCoinList(true);
            }
        });
        
        // Hide dropdown when clicking outside
        document.addEventListener('click', (e) => {
            if (searchResults && !searchInput.contains(e.target) && !searchResults.contains(e.target)) {
                searchResults.style.display = 'none';
            }
        });
        
        // Handle Enter key to select first result
        searchInput.addEventListener("keydown", (e) => {
            if (e.key === 'Enter' && searchResults && searchResults.style.display !== 'none') {
                const firstResult = searchResults.querySelector('.search-result-item');
                if (firstResult) {
                    firstResult.click();
                }
            }
        });
    }
    
    if (sortSelect) {
        sortSelect.addEventListener("change", (e) => {
            coinListSortBy = e.target.value;
            applyCoinListSort();
            updateCoinListTitle();
        });
    }
}

function applyCoinListSort() {
    const searchInput = document.getElementById("coinListSearch");
    const hasSearch = searchInput && searchInput.value.trim();
    
    // If searching, sort search results
    if (hasSearch) {
        if (coinListFiltered.length === 0) return;
        let sortedData = [...coinListFiltered];
        
        // Find and separate USDT/USD - always put first
        const usdtUsdIndex = sortedData.findIndex(coin => {
            const symbol = (coin.symbol || '').toUpperCase();
            return symbol === 'USDTUSDT' || symbol === 'USDTUSD' || symbol === 'USDT/USD';
        });
        const usdtUsdCoin = usdtUsdIndex >= 0 ? sortedData.splice(usdtUsdIndex, 1)[0] : { symbol: 'USDTUSD', baseAsset: 'USDT', price: 1, priceChangePercent: 0, volume: 0, quoteVolume: 0, marketCapApprox: 0 };
        
        switch (coinListSortBy) {
            case 'marketCap':
                sortedData.sort((a, b) => (b.marketCapApprox || 0) - (a.marketCapApprox || 0));
                break;
            case 'volume':
                sortedData.sort((a, b) => (b.quoteVolume || 0) - (a.quoteVolume || 0));
                break;
            case 'change':
                sortedData.sort((a, b) => (b.priceChangePercent || 0) - (a.priceChangePercent || 0));
                break;
            default:
                sortedData.sort((a, b) => (b.marketCapApprox || 0) - (a.marketCapApprox || 0));
        }
        
        sortedData.unshift(usdtUsdCoin);
        coinListFiltered = sortedData;
        renderCoinList();
    } else {
        // Sort top 10
        if (coinListTop10.length === 0) return;
        let sortedData = [...coinListTop10];
        
        // Find and separate USDT/USD - always put first
        const usdtUsdIndex = sortedData.findIndex(coin => {
            const symbol = (coin.symbol || '').toUpperCase();
            return symbol === 'USDTUSDT' || symbol === 'USDTUSD' || symbol === 'USDT/USD';
        });
        const usdtUsdCoin = usdtUsdIndex >= 0 ? sortedData.splice(usdtUsdIndex, 1)[0] : { symbol: 'USDTUSD', baseAsset: 'USDT', price: 1, priceChangePercent: 0, volume: 0, quoteVolume: 0, marketCapApprox: 0 };
        
        switch (coinListSortBy) {
            case 'marketCap':
                sortedData.sort((a, b) => (b.marketCapApprox || 0) - (a.marketCapApprox || 0));
                break;
            case 'volume':
                sortedData.sort((a, b) => (b.quoteVolume || 0) - (a.quoteVolume || 0));
                break;
            case 'change':
                sortedData.sort((a, b) => (b.priceChangePercent || 0) - (a.priceChangePercent || 0));
                break;
            default:
                sortedData.sort((a, b) => (b.marketCapApprox || 0) - (a.marketCapApprox || 0));
        }
        
        sortedData.unshift(usdtUsdCoin);
        coinListTop10 = sortedData;
        coinListData = sortedData;
        coinListFiltered = sortedData;
        renderCoinList();
    }
}

function updateCoinListTitle() {
    const titleEl = document.getElementById("coinListTitle");
    if (!titleEl) return;
    
    const titles = {
        'marketCap': 'En İyi 100 Coin (Piyasa Değerine Göre)',
        'volume': 'En İyi 100 Coin (Hacime Göre)',
        'change': 'En İyi 100 Coin (24s Değişime Göre)'
    };
    
    titleEl.textContent = titles[coinListSortBy] || titles['marketCap'];
}

// Liste sekmesi için WebSocket stream (Binance sekmesi ile aynı hız)
let coinListStreamActive = false;
let coinListSymbols = [];

function startCoinListUpdates() {
    window.intervalRegistry.stop('coinList.update');
    if (window.coinListMarketStoreSubscription) {
        window.coinListMarketStoreSubscription();
        window.coinListMarketStoreSubscription = null;
    }
    // Coin list prices: tab.binance.prices 1s interval (shared with varlıklar)
}

function stopCoinListUpdates() {
    stopCoinListWebSocketStream();
}

// DEPRECATED: startCoinListWebSocketStream - use startCoinListUpdates instead
function startCoinListWebSocketStream() {
    // REFACTOR: This function is deprecated - use startCoinListUpdates() instead
    console.warn("[dashboard] startCoinListWebSocketStream is deprecated, use startCoinListUpdates() instead");
    startCoinListUpdates();
}

// Liste sekmesi stream'ini durdur
function stopCoinListWebSocketStream() {
    if (coinListStreamActive) {
        coinListStreamActive = false;
        coinListSymbols = [];
    }
    window.intervalRegistry.stop('coinList.update');
    if (window.coinListMarketStoreSubscription) {
        window.coinListMarketStoreSubscription();
        window.coinListMarketStoreSubscription = null;
    }
}

async function loadCoinList(updateOnly = false) {
    const body = document.getElementById("coinListBody");
    if (!body) return;
    
    // TEK KAYNAK: marketStore (dataHub kullanılmaz)
    let miniTickers = [];
    try {
        if (window.marketStore && typeof window.marketStore.getAllMini === 'function') {
            miniTickers = window.marketStore.getAllMini() || [];
            console.log("[dashboard] loadCoinList: marketStore.getAllMini() returned", miniTickers.length, "coins");
        } else {
            console.log("[dashboard] loadCoinList: marketStore not available or getAllMini not a function");
        }
    } catch (error) {
        console.warn("[dashboard] loadCoinList: Error getting mini tickers from marketStore:", error);
    }
    
    if (miniTickers.length > 0) {
        const newCoinListData = miniTickers.map(coin => {
            // Extract base asset from symbol (e.g., BTCUSDT -> BTC)
            const symbol = coin.symbol || '';
            const baseAsset = symbol.replace(/USDT$|BTC$|ETH$|BNB$|FDUSD$|BUSD$|TUSD$|DAI$/i, '') || symbol;
            
            return {
                symbol: symbol,
                baseAsset: baseAsset,
                price: coin.last || 0,
                priceChangePercent: coin.changePct || 0,
                volume: coin.volume || 0,
                quoteVolume: coin.quoteVolume || 0,
                marketCapApprox: coin.marketCap || 0
            };
        });
        
        // Store all coins for search
        coinListAllCoins = [...newCoinListData];
        
        // Find USDT/USD and separate it
        const usdtUsdCoin = newCoinListData.find(coin => {
            const symbol = (coin.symbol || '').toUpperCase();
            return symbol === 'USDTUSDT' || symbol === 'USDTUSD' || symbol === 'USDT/USD';
        });
        
        // Filter out stable coins and get top 10
        const nonStableCoins = newCoinListData.filter(coin => {
            const symbol = (coin.symbol || '').toUpperCase();
            // Exclude USDT/USD from stable coin filter (we want to show it)
            if (symbol === 'USDTUSDT' || symbol === 'USDTUSD' || symbol === 'USDT/USD') {
                return false; // Don't include in nonStableCoins, we'll add it separately
            }
            const baseAsset = coin.baseAsset || coin.symbol?.replace(/USDT$|BTC$|ETH$|BNB$|FDUSD$|BUSD$|TUSD$|DAI$/i, '') || '';
            return !STABLE_COINS.includes(baseAsset.toUpperCase());
        });
        
        // Apply sorting to get top 10
        let sortedForTop10 = [...nonStableCoins];
        sortedForTop10.sort((a, b) => (b.marketCapApprox || 0) - (a.marketCapApprox || 0));
        sortedForTop10 = sortedForTop10.slice(0, 10);
        
        // Always put USDT/USD first - use existing or synthetic
        const usdtUsdRow = usdtUsdCoin || {
            symbol: 'USDTUSD',
            baseAsset: 'USDT',
            price: 1,
            priceChangePercent: 0,
            volume: 0,
            quoteVolume: 0,
            marketCapApprox: 0
        };
        coinListTop10 = [usdtUsdRow, ...sortedForTop10];
        
        // Update price cache for blink effects (Binance mantığı)
        if (coinListTop10.length > 0 && updateOnly) {
            // Cache'i güncelle (Binance mantığı - sadece price)
            coinListTop10.forEach(coin => {
                const symbol = coin.symbol;
                const oldCoin = coinListTop10.find(c => c.symbol === symbol);
                if (oldCoin && symbol && typeof window !== 'undefined' && window.coinListPriceCache && window.coinListPriceCache[symbol] === undefined) {
                    window.coinListPriceCache[symbol] = oldCoin.price;
                }
            });
            updateCoinListPrices(coinListTop10);
            return;
        }
        
        // First load - initialize cache (Binance mantığı)
        if (typeof window !== 'undefined') {
            if (!window.coinListPriceCache) {
                window.coinListPriceCache = {};
            }
            coinListTop10.forEach(coin => {
                if (coin.symbol) {
                    window.coinListPriceCache[coin.symbol] = coin.price;
                }
            });
        }
        
        // Set filtered coins to top 10 (default display)
        coinListFiltered = [...coinListTop10];
        coinListData = [...coinListTop10]; // For sorting/filtering operations
        
        applyCoinListSort();
        renderCoinList();
        return;
    }
    
    // Fallback: Fetch from API if marketStore not ready
    if (!updateOnly) {
        body.innerHTML = '<tr><td colspan="8" style="text-align: center; padding: 2rem; color: var(--ds-text-secondary);">Yükleniyor...</td></tr>';
    }
    
    try {
        // REFACTOR: Use apiClient instead of fetch
        // Try /api/data/coin-list first (cached), fallback to /api/binance/coin-list if empty
        let data = null;
        let rawCoins = [];
        
        try {
            data = await window.apiClient.get("/api/data/coin-list");
            console.log("[dashboard] loadCoinList: /api/data/coin-list response, coins count:", data.coins?.length || 0);
            rawCoins = data.coins || [];
        } catch (error) {
            console.warn("[dashboard] loadCoinList: /api/data/coin-list failed:", error);
        }
        
        // Use marketStore or show empty if /api/data/coin-list fails
        // This prevents rate limit issues
        if (!rawCoins || rawCoins.length === 0) {
            // Try to get from marketStore mini tickers
            if (window.marketStore && typeof window.marketStore.getAllMini === 'function') {
                const miniTickers = window.marketStore.getAllMini() || [];
                if (miniTickers.length > 0) {
                    rawCoins = miniTickers.slice(0, 100).map(coin => ({
                        symbol: coin.symbol || '',
                        baseAsset: (coin.symbol || '').replace(/USDT$|BTC$|ETH$|BNB$|FDUSD$|BUSD$|TUSD$|DAI$/i, ''),
                        price: coin.last || 0,
                        priceChangePercent: coin.changePct || 0,
                        volume: coin.volume || 0,
                        quoteVolume: coin.quoteVolume || 0,
                        marketCapApprox: coin.marketCap || 0
                    }));
                    console.log("[dashboard] loadCoinList: Using marketStore data, coins count:", rawCoins.length);
                }
            }
            
            // If still no coins, show empty state
            if (!rawCoins || rawCoins.length === 0) {
                if (body && !updateOnly) {
                    body.innerHTML = '<tr><td colspan="8" style="text-align: center; padding: 2rem; color: var(--ds-text-secondary);">Coin listesi yükleniyor... (WebSocket bağlantısı bekleniyor)</td></tr>';
                }
                console.warn("[dashboard] loadCoinList: No coins available from /api/data/coin-list or marketStore");
                return;
            }
        }
        
        if (rawCoins.length === 0) {
            console.warn("[dashboard] loadCoinList: No coins in API response");
            if (body && !updateOnly) {
                body.innerHTML = '<tr><td colspan="8" style="text-align: center; padding: 2rem; color: var(--ds-text-secondary);">Coin bulunamadı. Lütfen sayfayı yenileyin.</td></tr>';
            }
            return;
        }
        
        const newCoinListData = rawCoins.map(coin => {
            const symbol = coin.symbol || '';
            const baseAsset = coin.baseAsset || symbol.replace(/USDT$|BTC$|ETH$|BNB$|FDUSD$|BUSD$|TUSD$|DAI$/i, '') || symbol;
            const price = coin.price || parseFloat(coin.lastPrice) || 0;
            const priceChangePercent = coin.priceChangePercent || parseFloat(coin.priceChangePercent) || 0;
            const volume = coin.volume || parseFloat(coin.volume) || 0;
            const quoteVolume = coin.quoteVolume || parseFloat(coin.quoteVolume) || 0;
            const marketCapApprox = coin.marketCapApprox || coin.marketCap || 0;
            
            return {
                symbol: symbol,
                baseAsset: baseAsset,
                price: price,
                priceChangePercent: priceChangePercent,
                volume: volume,
                quoteVolume: quoteVolume,
                marketCapApprox: marketCapApprox
            };
        });
        
        // Update price cache for blink effects (Binance mantığı)
        if (coinListData.length > 0 && updateOnly) {
            // Cache'i güncelle (Binance mantığı - sadece price)
            if (typeof window !== 'undefined' && window.coinListPriceCache) {
                newCoinListData.forEach(coin => {
                    const symbol = coin.symbol;
                    const oldCoin = coinListData.find(c => c.symbol === symbol);
                    if (oldCoin && symbol && window.coinListPriceCache[symbol] === undefined) {
                        window.coinListPriceCache[symbol] = oldCoin.price;
                    }
                });
            }
            
            // DOM PATCHING: Update prices with blink effects (Binance mantığı)
            updateCoinListPrices(newCoinListData);
            return; // Exit early, don't re-render
        } else {
            // First load - initialize cache (Binance mantığı)
            if (typeof window !== 'undefined') {
                if (!window.coinListPriceCache) {
                    window.coinListPriceCache = {};
                }
                newCoinListData.forEach(coin => {
                    if (coin.symbol) {
                        window.coinListPriceCache[coin.symbol] = coin.price;
                    }
                });
            }
        }
        
        coinListData = newCoinListData;
        
        console.log("[dashboard] loadCoinList: Processed", newCoinListData.length, "coins");
        
        // Hide banner on successful load (if error was resolved)
        if (binanceApiErrorState.isError) {
            const errorAge = Date.now() - (binanceApiErrorState.lastErrorTime || 0);
            if (errorAge > 30000) {
                hideBinanceApiBanner();
            }
        }
        
        // Store all coins for search
        coinListAllCoins = [...newCoinListData];
        
        // Find USDT/USD and separate it
        const usdtUsdCoin = newCoinListData.find(coin => {
            const symbol = (coin.symbol || '').toUpperCase();
            return symbol === 'USDTUSDT' || symbol === 'USDTUSD' || symbol === 'USDT/USD';
        });
        
        // Filter out stable coins and get top 10
        const nonStableCoins = newCoinListData.filter(coin => {
            const symbol = (coin.symbol || '').toUpperCase();
            // Exclude USDT/USD from stable coin filter (we want to show it)
            if (symbol === 'USDTUSDT' || symbol === 'USDTUSD' || symbol === 'USDT/USD') {
                return false; // Don't include in nonStableCoins, we'll add it separately
            }
            const baseAsset = coin.baseAsset || coin.symbol?.replace(/USDT$|BTC$|ETH$|BNB$|FDUSD$|BUSD$|TUSD$|DAI$/i, '') || '';
            return !STABLE_COINS.includes(baseAsset.toUpperCase());
        });
        
        // Apply sorting to get top 10
        let sortedForTop10 = [...nonStableCoins];
        sortedForTop10.sort((a, b) => (b.marketCapApprox || 0) - (a.marketCapApprox || 0));
        sortedForTop10 = sortedForTop10.slice(0, 10);
        
        // Always put USDT/USD first - use existing or synthetic
        const usdtUsdRow = usdtUsdCoin || {
            symbol: 'USDTUSD',
            baseAsset: 'USDT',
            price: 1,
            priceChangePercent: 0,
            volume: 0,
            quoteVolume: 0,
            marketCapApprox: 0
        };
        coinListTop10 = [usdtUsdRow, ...sortedForTop10];
        
        // Set filtered coins to top 10 (default display)
        coinListFiltered = [...coinListTop10];
        coinListData = [...coinListTop10]; // For sorting/filtering operations
        
        console.log("[dashboard] loadCoinList: Top 10 coins (stable excluded):", coinListTop10.length);
        console.log("[dashboard] loadCoinList: All coins for search:", coinListAllCoins.length);
        
        // Initialize coinListPriceCache before rendering
        if (typeof window !== 'undefined') {
            if (!window.coinListPriceCache) {
                window.coinListPriceCache = {};
            }
        }
        
        renderCoinList(true); // Always enable blink effects
        console.log("[dashboard] loadCoinList: renderCoinList called");
    } catch (error) {
        console.error("[dashboard] Error loading coin list:", error);
        if (body && !updateOnly) {
            body.innerHTML = `<tr><td colspan="8" style="text-align: center; padding: 2rem; color: var(--ds-text-error);">Hata: ${error.message}</td></tr>`;
        }
    }
}

function updateCoinListPricesFromMarketStore() {
    if (window.BinanceUI && document.getElementById("tabBinance")?.classList.contains("is-active")) {
        return;
    }
    if (!coinListTop10 || coinListTop10.length === 0) return;
    if (typeof window !== 'undefined' && !window.coinListPriceCache) window.coinListPriceCache = {};
    const binanceTab = document.getElementById("tabBinance");
    if (!binanceTab || !binanceTab.classList.contains("is-active")) return;
    if (window.__DEBUG_BINANCE__) console.count("coinListPriceUpdate");

    const allPrices = window.marketStore?.getAllPrices() || {};
    const allMini = window.marketStore?.getAllMini() || [];
    const miniMap = new Map((allMini || []).map(m => [m.symbol, m]));

    const newCoinListData = coinListTop10.map(coin => {
        const rawSymbol = coin.symbol || '';
        const storeKey = normalizeUiSymbolToStoreKey(rawSymbol);
        let price = allPrices[storeKey];
        if (price == null) {
            const mini = miniMap.get(storeKey);
            price = mini?.last;
            if (price == null) price = window.marketStore?.getPrice(storeKey);
        }
        const mini = miniMap.get(storeKey);
        const resolvedPrice = (price != null && price > 0) ? price : (coin.price != null && coin.price > 0 ? coin.price : null);
        return {
            ...coin,
            rawSymbol,
            storeKey,
            price: resolvedPrice,
            priceChangePercent: mini?.changePct !== undefined ? mini.changePct : coin.priceChangePercent,
            volume: mini?.volume !== undefined ? mini.volume : coin.volume,
            quoteVolume: mini?.quoteVolume !== undefined ? mini.quoteVolume : coin.quoteVolume,
            marketCapApprox: mini?.marketCap !== undefined ? mini.marketCap : coin.marketCapApprox
        };
    });

    updateCoinListPricesAndDetails(newCoinListData);
}

// DOM PATCHING: Update coin prices AND details with blink effects - REAL-TIME UPDATES
function updateCoinListPricesAndDetails(newCoinListData) {
    // Initialize cache if not exists (Binance mantığı)
    if (typeof window === 'undefined' || !window.coinListPriceCache) {
        if (typeof window !== 'undefined') {
            window.coinListPriceCache = {};
        } else {
            return; // Window not available
        }
    }
    
    let hasUpdate = false;
    
    newCoinListData.forEach(coin => {
        const rawSymbol = coin.rawSymbol || coin.symbol || '';
        const storeKey = coin.storeKey || normalizeUiSymbolToStoreKey(rawSymbol);
        
        // Update PRICE
        const priceEl = document.getElementById(`coinPrice_${storeKey}`);
        if (priceEl) {
            const prevPrice = window.coinListPriceCache[storeKey];
            const newPrice = coin.price;
            const hasPrice = newPrice != null && Number.isFinite(newPrice) && newPrice > 0;
            const priceChanged = hasPrice && prevPrice !== undefined && Math.abs(prevPrice - newPrice) > 0.0001;
            if (priceChanged) hasUpdate = true;

            priceEl.textContent = hasPrice ? fmtUsd(newPrice) : '…';
            let priceClass = "price-neutral";
            if (priceChanged) priceClass = newPrice > prevPrice ? "price-up" : "price-down";
            priceEl.classList.remove("price-up", "price-down", "price-neutral");
            priceEl.classList.add(priceClass);
            if (priceChanged) {
                setTimeout(() => { if (priceEl) priceEl.classList.remove("price-up", "price-down"); }, 500);
            }
            if (hasPrice) window.coinListPriceCache[storeKey] = newPrice;
        }
        
        // Update 24H CHANGE - with blink effect (same as assets table)
        const changeEl = document.getElementById(`coinChange_${storeKey}`);
        if (changeEl) {
            const priceChange = coin.priceChangePercent || 0;
            const prevChange = window.coinListChangeCache?.[storeKey];
            
            // Check if change value changed (for blink effect)
            const changeChanged = prevChange !== undefined && Math.abs(prevChange - priceChange) > 0.01;
            
            const priceChangeColor = priceChange > 0 ? "#0ecb81" : priceChange < 0 ? "#f6465d" : "var(--ds-text-primary)";
            changeEl.textContent = `${priceChange > 0 ? '+' : ''}${priceChange.toFixed(2)}%`;
            changeEl.style.color = priceChangeColor;
            
            // Apply blink class if change value changed (same as assets table)
            if (changeChanged) {
                const changeClass = priceChange > prevChange ? "price-up" : "price-down";
                changeEl.classList.remove("price-up", "price-down");
                changeEl.classList.add(changeClass);
                
                // Remove animation class after animation completes
                setTimeout(() => {
                    if (changeEl) {
                        changeEl.classList.remove("price-up", "price-down");
                    }
                }, 500);
            }
            
            // Update cache
            if (!window.coinListChangeCache) {
                window.coinListChangeCache = {};
            }
            window.coinListChangeCache[storeKey] = priceChange;
        }
        
        // Update VOLUME
        const volumeEl = document.getElementById(`coinVol_${storeKey}`);
        if (volumeEl) {
            const volume = coin.volume || 0;
            const formatVolume = (vol) => {
                if (vol >= 1e9) return `${(vol / 1e9).toFixed(2)}B`;
                if (vol >= 1e6) return `${(vol / 1e6).toFixed(2)}M`;
                if (vol >= 1e3) return `${(vol / 1e3).toFixed(2)}K`;
                return vol.toFixed(2);
            };
            volumeEl.textContent = '$' + formatVolume(coin.quoteVolume || volume);
        }
        
        // Update MARKET CAP
        const marketCapEl = document.getElementById(`coinMcap_${storeKey}`);
        if (marketCapEl) {
            const marketCap = coin.marketCapApprox || 0;
            const formatVolume = (vol) => {
                if (vol >= 1e9) return `${(vol / 1e9).toFixed(2)}B`;
                if (vol >= 1e6) return `${(vol / 1e6).toFixed(2)}M`;
                if (vol >= 1e3) return `${(vol / 1e3).toFixed(2)}K`;
                return vol.toFixed(2);
            };
            marketCapEl.textContent = '$' + formatVolume(marketCap);
        }
    });
    
    // Update coinListTop10 for next comparison
    coinListTop10 = newCoinListData;
    
    // Also update coinListData if we're showing top 10
    const searchInput = document.getElementById("coinListSearch");
    if (!searchInput || !searchInput.value.trim()) {
        coinListData = newCoinListData;
        coinListFiltered = newCoinListData;
    }
}

// DOM PATCHING: Update coin prices with blink effects - BINANCE VARLIKLAR TASARIMI İLE TAMAMEN AYNI
// Binance varlıklar sekmesindeki mantığın aynısı - sadece fiyat değişiminde blink
function updateCoinListPrices(newCoinListData) {
    // Use the new comprehensive function
    updateCoinListPricesAndDetails(newCoinListData);
}

// Show search results dropdown
function showCoinSearchResults(query) {
    const searchResults = document.getElementById("coinListSearchResults");
    if (!searchResults) return;
    
    if (!query || query.length === 0) {
        searchResults.style.display = 'none';
        coinListFiltered = [...coinListTop10];
        renderCoinList(true);
        return;
    }
    
    const queryUpper = query.toUpperCase();
    
    // Search in all coins (not just top 10)
    const matches = coinListAllCoins.filter(coin => {
        const symbol = (coin.symbol || '').toUpperCase();
        const baseAsset = (coin.baseAsset || symbol.replace(/USDT$|BTC$|ETH$|BNB$|FDUSD$|BUSD$|TUSD$|DAI$/i, '') || '').toUpperCase();
        return symbol.includes(queryUpper) || baseAsset.includes(queryUpper);
    }).slice(0, 20); // Limit to 20 results
    
    if (matches.length === 0) {
        searchResults.innerHTML = '<div style="padding: 12px; color: var(--ds-text-secondary); text-align: center;">Sonuç bulunamadı</div>';
        searchResults.style.display = 'block';
        return;
    }
    
    // Render search results
    searchResults.innerHTML = matches.map(coin => {
        const priceChange = coin.priceChangePercent || 0;
        const priceChangeColor = priceChange > 0 ? "#0ecb81" : priceChange < 0 ? "#f6465d" : "var(--ds-text-primary)";
        
        return `
            <div class="search-result-item" 
                 onclick="selectCoinFromSearch('${coin.symbol}')" 
                 style="padding: 12px; cursor: pointer; border-bottom: 1px solid var(--ds-border); transition: background 0.2s;"
                 onmouseenter="this.style.background='var(--ds-bg-hover)'"
                 onmouseleave="this.style.background='transparent'">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <strong style="color: var(--ds-text-primary); font-size: 0.95rem;">${coin.baseAsset || coin.symbol?.replace(/USDT$|BTC$|ETH$|BNB$|FDUSD$|BUSD$|TUSD$|DAI$/i, '') || 'N/A'}</strong>
                        <div style="font-size: 0.8rem; color: var(--ds-text-secondary); margin-top: 2px;">${coin.symbol}</div>
                    </div>
                    <div style="text-align: right;">
                        <div style="font-weight: 600; color: var(--ds-text-primary);">${fmtCoinPrice(coin.price)}</div>
                        <div style="font-size: 0.85rem; color: ${priceChangeColor}; font-weight: 600;">
                            ${priceChange > 0 ? '+' : ''}${priceChange.toFixed(2)}%
                        </div>
                    </div>
                </div>
            </div>
        `;
    }).join('');
    
    searchResults.style.display = 'block';
}

// Select coin from search results
function selectCoinFromSearch(symbol) {
    const searchInput = document.getElementById("coinListSearch");
    const searchResults = document.getElementById("coinListSearchResults");
    
    if (searchInput) {
        searchInput.value = '';
    }
    if (searchResults) {
        searchResults.style.display = 'none';
    }
    
    // Open spot trade modal
    if (typeof openSpotTradeModal === 'function') {
        openSpotTradeModal(symbol);
    } else {
        console.error("[dashboard] openSpotTradeModal function not found");
    }
}

// Make function global
window.selectCoinFromSearch = selectCoinFromSearch;

function filterCoinList(query) {
    if (!query) {
        coinListFiltered = [...coinListTop10];
    } else {
        // Search in all coins
        coinListFiltered = coinListAllCoins.filter(coin => {
            const symbol = coin.symbol.toUpperCase();
            const baseAsset = coin.baseAsset.toUpperCase();
            return symbol.includes(query) || baseAsset.includes(query);
        });
    }
    renderCoinList();
}

function renderCoinList(enableBlink = true) {
    const body = document.getElementById("coinListBody");
    if (!body) {
        console.error("[dashboard] renderCoinList: coinListBody element not found!");
        return;
    }
    if (window.BinanceUI && document.getElementById("tabBinance")?.classList.contains("is-active")) {
        return;
    }
    
    console.log("[dashboard] renderCoinList: Called with", coinListFiltered.length, "filtered coins");
    
    if (coinListFiltered.length === 0) {
        console.log("[dashboard] renderCoinList: No coins to display");
        body.innerHTML = '<tr><td colspan="8" style="text-align: center; padding: 2rem; color: var(--ds-text-secondary);">Coin bulunamadı</td></tr>';
        return;
    }
    
    body.innerHTML = coinListFiltered.map((coin, index) => {
        const priceChange = coin.priceChangePercent || 0;
        const priceChangeColor = priceChange > 0 ? "#0ecb81" : priceChange < 0 ? "#f6465d" : "var(--ds-text-primary)";
        
        // Check for price changes for blink effect - BINANCE VARLIKLAR MANTIĞI (TAMAMEN AYNI)
        const symbol = coin.symbol;
        let priceClass = "price-neutral";
        
        if (typeof window !== 'undefined' && window.coinListPriceCache) {
            const prevPrice = window.coinListPriceCache[symbol];
            
            // Price blink class (Binance varlıklar mantığı - TAMAMEN AYNI)
            if (prevPrice !== undefined && prevPrice !== coin.price) {
                priceClass = coin.price > prevPrice ? "price-up" : "price-down";
            }
            
            // Update cache (Binance mantığı - sadece price)
            if (symbol) {
                window.coinListPriceCache[symbol] = coin.price;
            }
        }
        
        // Format large numbers
        const formatVolume = (vol) => {
            if (vol >= 1e9) return `${(vol / 1e9).toFixed(2)}B`;
            if (vol >= 1e6) return `${(vol / 1e6).toFixed(2)}M`;
            if (vol >= 1e3) return `${(vol / 1e3).toFixed(2)}K`;
            return vol.toFixed(2);
        };
        
        const base = coin.baseAsset || (coin.symbol && coin.symbol.replace(/USDT$/i, '').replace(/BTC$/i, '').replace(/ETH$/i, '').replace(/BNB$/i, '')) || 'N/A';
        const logoUrl = (typeof getCoinLogoUrl === 'function' && getCoinLogoUrl(base)) || null;
        const initials = (base || ' ').substring(0, 2).toUpperCase();
        
        const originalIndex = coinListData.findIndex(c => c.symbol === coin.symbol);
        const rank = originalIndex >= 0 ? originalIndex + 1 : index + 1;
        const sym = (coin.symbol || '').toUpperCase();
        const displaySymbol = (sym === 'USDTUSD' || sym === 'USDTUSDT' || sym === 'USDT/USD') ? 'USDT/USD' : (coin.symbol || '');
        
        return `
            <tr id="coinRow_${symbol}" style="cursor: pointer;" onclick="openSpotTradeModal('${coin.symbol}')" onmouseenter="prefetchPriceData('${coin.symbol}')">
                <td class="varlik-logo-cell" style="padding: 12px; vertical-align: middle;">
                    <div class="varlik-logo" title="${base}">
                        ${logoUrl ? `<img src="${logoUrl}" alt="${base}" loading="lazy" onerror="if(window.registerLogo404)window.registerLogo404(this.alt);this.style.display='none';this.nextElementSibling.style.display='flex';" />` : ''}
                        <span class="varlik-logo-initials" style="${logoUrl ? 'display:none' : ''}">${initials}</span>
                    </div>
                </td>
                <td style="padding: 12px; color: var(--ds-text-secondary); font-size: 0.9rem;">${rank}</td>
                <td style="padding: 12px;">
                    <strong style="color: var(--ds-text-primary); font-size: 0.95rem;">${coin.baseAsset || coin.symbol?.replace('USDT', '').replace('BTC', '').replace('ETH', '').replace('BNB', '') || 'N/A'}</strong>
                    <div style="font-size: 0.8rem; color: var(--ds-text-secondary); margin-top: 2px;">${displaySymbol}</div>
                </td>
                <td style="text-align: right; padding: 12px; font-weight: 600;">
                    <span id="coinPrice_${symbol}" class="text-right price-cell ${priceClass}" data-price="${coin.price}">${fmtCoinPrice(coin.price)}</span>
                </td>
                <td style="text-align: right; padding: 12px;">
                    <span id="coinChange_${symbol}" class="text-right" style="color: ${priceChangeColor}; font-weight: 600;">
                        ${priceChange > 0 ? '+' : ''}${priceChange.toFixed(2)}%
                    </span>
                </td>
                <td style="text-align: right; padding: 12px; color: var(--ds-text-primary);">
                    <span id="coinVolume_${symbol}">${formatVolume(coin.quoteVolume)}</span>
                </td>
                <td style="text-align: right; padding: 12px; color: var(--ds-text-primary);">
                    <span id="coinMarketCap_${symbol}">$${formatVolume(coin.marketCapApprox)}</span>
                </td>
                <td style="text-align: center; padding: 12px;">
                    <div class="btn-al-sat-wrap">
                        <button type="button" class="btn-al" onclick="event.stopPropagation(); openSpotTradeModal('${coin.symbol}', 'BUY')" title="Alış">Alış</button>
                        <button type="button" class="btn-sat" onclick="event.stopPropagation(); openSpotTradeModal('${coin.symbol}', 'SELL')" title="Satış">Satış</button>
                    </div>
                </td>
            </tr>
        `;
    }).join("");
    
    // Apply blink effects after rendering - ALWAYS ACTIVE - FIXED
    requestAnimationFrame(() => {
        coinListFiltered.forEach(coin => {
            const symbol = coin.symbol;
            const priceEl = document.getElementById(`coinPrice_${symbol}`);
            const changeEl = document.getElementById(`coinChange_${symbol}`);
            
            // Apply blink to price if changed - FLASH HIZLI blink efekti
            if (priceEl) {
                if (priceEl.classList.contains("price-up")) {
                    // Force reflow to trigger animation
                    void priceEl.offsetHeight;
                    setTimeout(() => {
                        if (priceEl) priceEl.classList.remove("price-up");
                    }, 300); // 300ms - Binance varlıklar ile aynı
                } else if (priceEl.classList.contains("price-down")) {
                    // Force reflow to trigger animation
                    void priceEl.offsetHeight;
                    setTimeout(() => {
                        if (priceEl) priceEl.classList.remove("price-down");
                    }, 300); // 300ms - Binance varlıklar ile aynı
                }
            }
            
            // Apply blink to price change if changed - FLASH HIZLI blink efekti
            if (changeEl) {
                if (changeEl.classList.contains("price-up")) {
                    // Force reflow to trigger animation
                    void changeEl.offsetHeight;
                    setTimeout(() => {
                        if (changeEl) changeEl.classList.remove("price-up");
                    }, 300); // 300ms - Binance varlıklar ile aynı
                } else if (changeEl.classList.contains("price-down")) {
                    // Force reflow to trigger animation
                    void changeEl.offsetHeight;
                    setTimeout(() => {
                        if (changeEl) changeEl.classList.remove("price-down");
                    }, 300); // 300ms - Binance varlıklar ile aynı
                }
            }
        });
    });
}

// Make functions global
window.openSpotTradeModal = openSpotTradeModal;
window.closeSpotTradeModal = closeSpotTradeModal;
window.setTradeSide = setTradeSide;
window.setTradeType = setTradeType;
window.setTradePercent = setTradePercent;

// Fullscreen blocker safety valve
function checkFullscreenBlockers() {
    const children = Array.from(document.body.children);
    const w = window.innerWidth;
    const h = window.innerHeight;
    
    children.forEach(el => {
        if (!el || el.id === "topTicker" || el.id === "dmModal" || el.id === "dmBackdrop") return;
        
        const cs = getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        
        const isFullscreen = rect.width >= w * 0.8 && rect.height >= h * 0.8;
        const isBlocking = (cs.position === "fixed" || cs.position === "absolute") &&
                          cs.pointerEvents !== "none" &&
                          Number(cs.zIndex || 0) >= 100 &&
                          isFullscreen;
        
        if (isBlocking) {
            console.error("[dashboard] Fullscreen blocker detected:", el);
            el.style.pointerEvents = "none";
            el.style.display = "none";
        }
    });
}

// Main init
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
                await fetch('/api/auth/logout', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ account_id: accountId })
                });
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
                var who = await fetch(window.location.origin + '/api/auth/whoami', { method: 'GET', credentials: 'include', cache: 'no-store' });
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
        // Bakiye şeridi: Finansal Hesap, İletişim, Ayarlar sekmelerinde gösterilmez (kpi-strip-hidden ile CSS !important geçilir)
        const unifiedStrip = document.getElementById('unifiedKpiStrip');
        if (unifiedStrip) {
            const showStrip = (savedTab === 'reports' || savedTab === 'binance' || savedTab === 'trade' || savedTab === 'bots');
            unifiedStrip.classList.toggle('kpi-strip-hidden', !showStrip);
            unifiedStrip.style.display = showStrip ? 'block' : 'none';
            if (savedTab === 'bots') unifiedStrip.classList.add('unified-kpi-bots-only');
            else unifiedStrip.classList.remove('unified-kpi-bots-only');
        }
        updateBinanceConnectionNotice();
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
            msg = "Dashboard yüklenemedi: " + error.message;
        }
        showError(msg);
        return;
    }
    
    State.accountId = accountId;
    State.accountCode = accountCode;
    window.__ACTIVE_ACCOUNT_ID = accountId;
    var showFirstLoginModal = isFirstLogin;
    if (isFirstLogin && accountId) {
        showFirstLoginModal = await shouldShowFirstLoginModal(accountId, true);
    }
    restoreFinanceBotsFromSessionCache(accountId);
    restoreAppbarFromSessionCache(accountId, accountCode);
    // En İyi 5 Bot: hesap hazır olur olmaz yükle (snapshot beklemeden); snapshot geldiğinde de yenilenecek
    if (typeof loadGlobalLeaderboard === 'function') loadGlobalLeaderboard();
    await loadSpotFavoritesFromStorage();
    if (typeof window.__DEBUG_DASH__ !== 'undefined' && window.__DEBUG_DASH__) console.log("[dashboard] initDashboard: accountId =", accountId, "accountCode =", accountCode);
    updateBinanceConnectionNotice();
    var activeTabName = document.querySelector('.dm-tab.is-active')?.getAttribute('data-tab');
    if (activeTabName === 'trade') {
        initMobileTradeSearch();
        if (typeof renderMobileTradeFavorites === 'function') renderMobileTradeFavorites();
        window.intervalRegistry.stopByOwner('tab.trade');
        window.intervalRegistry.start('tab.trade.prices', tickMobileTradeFavoritesPrices, 2000, 'tab.trade');
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
        showActiveOrdersPanel();
        initVarliklarTab();
        if (typeof initBinanceCoinList === 'function') initBinanceCoinList();
        if (typeof updateActiveOrdersPanelPosition === 'function') updateActiveOrdersPanelPosition();
        if (typeof startBinanceTabPolling === 'function') startBinanceTabPolling();
        if (accountId && typeof loadFinanceTrades === 'function') loadFinanceTrades();
    }
    // İşlem geçmişi: sayfa açılır açılmaz Günlük + Alım/Satım yükle (snapshot beklemeden)
    if (accountId && typeof loadTransactionHistory === 'function') {
        loadTransactionHistory(State.txHistoryPeriod || 'daily', State.txHistoryType || 'buysell', 1, false);
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
                    showActiveOrdersPanel();
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
    // Flash Home (Patch H): when enabled, use /api/home/fast + wallet/refresh; no Binance on critical path
    window.FLASH_HOME_ENABLED = typeof window.FLASH_HOME_ENABLED !== 'undefined' ? window.FLASH_HOME_ENABLED : true;
    var _binanceWalletIdleCycles = 0;
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
            return;
        }
        _binanceWalletIdleCycles = 0;
        fetchSnapshot();
    }
    if (accountId) {
        if (window.marketDataService && typeof window.marketDataService.stop === 'function') {
            window.marketDataService.stop();
        }
        window.intervalRegistry.stop('dashboard.summary');
        window.intervalRegistry.start('dashboard_snapshot', dashboardDataRefresh, SNAPSHOT_POLL_MS, 'dashboard');
        if (window.FLASH_HOME_ENABLED && window.homeFlash && typeof window.homeFlash.init === 'function') {
            window.homeFlash.init();
            fetchSnapshot();
        } else {
            fetchSnapshot();
        }
        // One-time wallet refresh on dashboard load (cache-only snapshot needs one live refresh to populate cache)
        if (accountId && !window.__dashboardWalletRefreshDone) {
            window.__dashboardWalletRefreshDone = true;
            setTimeout(function () {
                if (typeof triggerWalletRefreshForVarliklar === 'function') {
                    triggerWalletRefreshForVarliklar(accountId, { force: true });
                } else if (window.FLASH_HOME_ENABLED && window.homeFlash && typeof window.homeFlash.triggerRefresh === 'function') {
                    window.homeFlash.triggerRefresh(accountId, true);
                } else if (window.apiClient && typeof window.apiClient.post === 'function') {
                    window.apiClient.post('/api/home/wallet/refresh?account_id=' + accountId + '&force=1', null, { timeout: 15000 })
                        .then(function (res) {
                            if (res && res.ok && res.data && res.data.wallet_live && assetsState && assetsState.wallet) {
                                normalizeAndApplyWallet(res.data.wallet_live, { source: 'wallet_refresh_init' });
                            }
                        })
                        .catch(function () {});
                }
            }, 500);
        }
        // 10s timeout guard: wallet stuck in idle/loading => set error (eliminates indefinite loading flicker)
        setTimeout(function () {
            if (!assetsState || !assetsState.wallet) return;
            var w = assetsState.wallet;
            if (w.status === 'idle' || w.status === 'loading') {
                w.status = 'error';
                w.error = { error_code: 'WALLET_TIMEOUT_NO_SOURCE', message: 'Cüzdan verisi 10 saniye içinde yüklenemedi.' };
                if (window.BinanceAssetsPanel?.render) window.BinanceAssetsPanel.render();
                if (typeof renderVarliklarList === 'function') renderVarliklarList();
            }
            if (assetsState.prices && assetsState.prices.data_status === 'empty' && (!assetsState.prices.ts || assetsState.prices.ts === 0)) {
                assetsState.prices.data_status = 'error';
                assetsState.prices._timeout_code = 'PRICES_TIMEOUT_NO_SOURCE';
            }
        }, 10000);
    } else {
        loadSummary(accountId);
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
            if (typeof loadTransactionHistory === 'function') loadTransactionHistory(State.txHistoryPeriod, State.txHistoryType, 1, false);
        }
    });
    // dashboard_snapshot already started in initDashboard when accountId set; no dashboard.summary
    window.intervalRegistry.start('kpi.spot-status', updateKpiCuzdanLiveStatus, 5000, 'dashboard');
    window.intervalRegistry.start('datahub.ws-status', updateDatahubWsIndicator, 5000, 'dashboard');
    updateDatahubWsIndicator();
    window.intervalRegistry.start('finance.bots.prices', updateFinanceBotsLivePrices, 1500, 'dashboard');
    window.intervalRegistry.start('finance.bots.live', function () {
        if (typeof pollFinanceBotsLiveEquity === 'function') pollFinanceBotsLiveEquity();
    }, 2500, 'dashboard');
    
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
                const r = await fetch('/api/auth/ping?account_id=' + State.accountId, { cache: 'no-store' });
                if (r.status === 401) {
                    try { if (typeof window.clearAuthAndBroadcast === 'function') window.clearAuthAndBroadcast(); } catch (e) {}
                    localStorage.removeItem('user');
                    localStorage.removeItem('token');
                    try { localStorage.removeItem('boot_id'); } catch (e) {}
                    try { localStorage.removeItem('last_route'); } catch (e) {}
                    window.intervalRegistry.stop('auth.health');
                    window.location.replace('/ui/login.html');
                    return;
                }
                const d = await r.json().catch(() => ({}));
                if (d.kicked) {
                    localStorage.removeItem('user');
                    localStorage.removeItem('token');
                    try { localStorage.removeItem('boot_id'); } catch (e) {}
                    try { localStorage.removeItem('last_route'); } catch (e) {}
                    window.intervalRegistry.stop('auth.health');
                    window.location.replace('/ui/login.html');
                }
            } catch (e) {}
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
        loadSummary(State.accountId);
        if (isBinanceTabActive() && typeof triggerWalletRefreshForVarliklar === 'function') {
            triggerWalletRefreshForVarliklar(State.accountId, { force: true });
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

let financeState = {
    portfolioId: null,
    shortId: null,
    storageKey: null,
    items: [],
    itemInputs: [],
    goldPriceTRY: null // Gram altın fiyatı (TL)
};

// Ticker verilerini al (gram altın ve USDTRY)
async function getTickerData() {
    try {
        const response = await fetch(`/api/ticker?cb=${Date.now()}`);
        if (response.ok) {
            const data = await response.json();
            return {
                goldPriceTRY: parseFloat(data.GRAM_ALTIN_TRY) || null,
                usdtTry: parseFloat(data.USDTTRY) || null
            };
        }
    } catch (e) {
        console.error("[finance] Error fetching ticker data:", e);
    }
    return { goldPriceTRY: null, usdtTry: null };
}

// Gram altın fiyatını ticker'dan al (legacy - getTickerData kullan)
async function getGoldPriceTRY() {
    const data = await getTickerData();
    return data.goldPriceTRY;
}

// Gram altın fiyatını göster (placeholder)
function updateGoldPriceDisplay() {
    // Gram altın fiyatını göster (eğer bir display elementi varsa)
    // Şimdilik sadece state'te tutuyoruz
}

// Finansal hesap sekmesini başlat
function initFinanceTab() {
    console.log("[finance] Initializing finance tab");
    
    // Portfolio ID oluştur
    if (!financeState.portfolioId) {
        const urlParams = new URLSearchParams(window.location.search);
        let urlId = urlParams.get('id');
        
        if (!urlId) {
            urlId = 'p_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 10);
        }
        
        const saved = localStorage.getItem(`dcaPortfolio_${urlId}`);
        let shortId;
        if (saved) {
            const data = JSON.parse(saved);
            shortId = data.shortId || generateShortId();
        } else {
            shortId = generateShortId();
        }
        
        financeState.portfolioId = urlId;
        financeState.shortId = shortId;
        financeState.storageKey = `dcaPortfolio_${urlId}`;
    }
    
    // Ticker verilerini güncelle
    getTickerData().then(data => {
        financeState.goldPriceTRY = data.goldPriceTRY;
        financeState.usdtTry = data.usdtTry;
        updateGoldPriceDisplay();
    });
    
    // REFACTOR: Use intervalRegistry instead of setInterval
    window.intervalRegistry.stop('finance.goldPrice');
    window.intervalRegistry.start('finance.goldPrice', async () => {
        const data = await getTickerData();
        if (data.goldPriceTRY) financeState.goldPriceTRY = data.goldPriceTRY;
        if (data.usdtTry) financeState.usdtTry = data.usdtTry;
        updateGoldPriceDisplay();
    }, 5000, 'tab.finance');
    
    // Kaydedilmiş veriyi yükle
    const saved = localStorage.getItem(financeState.storageKey);
    if (saved) {
        const data = JSON.parse(saved);
        financeState.items = data.items || [];
        if (data.portfolioName) {
            const nameInput = document.getElementById('portfolioNameInput');
            if (nameInput) nameInput.value = data.portfolioName;
        }
        showFinanceScreen2();
    } else {
        showFinanceScreen1();
    }
    
    // Event listener'ları bağla
    bindFinanceEvents();
}

function generateShortId() {
    return Math.floor(100000 + Math.random() * 900000).toString();
}

function bindFinanceEvents() {
    console.log("[finance] Binding finance events");
    // Create button
    const createBtn = document.getElementById('createBtn');
    if (createBtn) {
        console.log("[finance] Create button found, binding click handler");
        // Remove existing handlers
        createBtn.onclick = null;
        createBtn.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            console.log("[finance] Create button clicked");
            createFinanceItemInputs();
        }, { passive: false });
    } else {
        console.error("[finance] Create button not found!");
    }
    
    // Save reference button
    const saveRefBtn = document.getElementById('saveRefBtn');
    if (saveRefBtn) {
        saveRefBtn.onclick = (e) => {
            e.preventDefault();
            e.stopPropagation();
            saveFinanceReference();
        };
    }
    
    // Tekrar ortalama (rebalance) butonu
    const rebalanceBtn = document.getElementById('rebalanceBtn');
    if (rebalanceBtn) {
        rebalanceBtn.onclick = (e) => {
            e.preventDefault();
            e.stopPropagation();
            calculateFinanceRebalance();
        };
    }
    
    // Save current button
    const saveCurrentBtn = document.getElementById('saveCurrentBtn');
    if (saveCurrentBtn) {
        saveCurrentBtn.onclick = (e) => {
            e.preventDefault();
            e.stopPropagation();
            saveFinanceCurrentValues();
        };
    }
    
    // Reset button
    const resetBtn = document.getElementById('resetBtn');
    if (resetBtn) {
        resetBtn.onclick = (e) => {
            e.preventDefault();
            e.stopPropagation();
            resetFinanceReference();
        };
    }
}

function showFinanceScreen1() {
    const screen1 = document.getElementById('financeScreen1');
    const screen2 = document.getElementById('financeScreen2');
    if (screen1) screen1.classList.remove('hidden');
    if (screen2) screen2.classList.add('hidden');
}

function showFinanceScreen2() {
    const screen1 = document.getElementById('financeScreen1');
    const screen2 = document.getElementById('financeScreen2');
    if (screen1) screen1.classList.add('hidden');
    if (screen2) screen2.classList.remove('hidden');
    
    const saved = localStorage.getItem(financeState.storageKey);
    if (saved) {
        const data = JSON.parse(saved);
        const portfolioName = data.portfolioName || 'İsimsiz Portföy';
        const titleEl = document.getElementById('portfolioTitle');
        if (titleEl) titleEl.textContent = portfolioName;
    }
    
    renderFinancePortfolioTable();
}

function createFinanceItemInputs() {
    console.log("[finance] createFinanceItemInputs called");
    const countInput = document.getElementById('itemCount');
    if (!countInput) {
        console.error("[finance] itemCount input not found");
        return;
    }
    
    const count = parseInt(countInput.value);
    console.log("[finance] Creating", count, "item inputs");
    if (count < 1) {
        showFinanceError('error1', 'En az 1 başlık gerekli');
        return;
    }
    
    financeState.itemInputs = [];
    const container = document.getElementById('itemsContainer');
    if (!container) {
        console.error("[finance] itemsContainer not found");
        return;
    }
    
    container.innerHTML = '';
    
    for (let i = 0; i < count; i++) {
        const div = document.createElement('div');
        div.className = 'item-row';
        div.style.cssText = 'margin-bottom: 15px; padding: 15px; background: var(--ds-bg-panel); border-radius: 8px; border: 1px solid var(--ds-border);';
        div.innerHTML = `
            <label style="display: block; margin-bottom: 0.5rem; color: var(--ds-text-primary); font-weight: 500;">Başlık Adı ${i + 1}</label>
            <input type="text" id="name_${i}" placeholder="Örn: Bitcoin" class="form-input" style="width: 100%; margin-bottom: 12px;">
            <label style="display: block; margin-bottom: 0.5rem; color: var(--ds-text-primary); font-weight: 500;">Başlangıç Değeri (USD) ${i + 1}</label>
            <input type="number" id="value_${i}" min="0" step="0.01" placeholder="100.00" class="form-input" style="width: 100%; margin-bottom: 12px;">
            <label style="display: block; margin-bottom: 0.5rem; color: var(--ds-text-primary); font-weight: 500;">Adet (Not) ${i + 1}</label>
            <input type="number" id="quantity_${i}" min="0" step="0.01" placeholder="0.00" class="form-input" style="width: 100%;">
        `;
        container.appendChild(div);
        financeState.itemInputs.push({ name: `name_${i}`, value: `value_${i}`, quantity: `quantity_${i}` });
    }
    
    const saveRefBtn = document.getElementById('saveRefBtn');
    if (saveRefBtn) {
        saveRefBtn.classList.remove('hidden');
        console.log("[finance] Save reference button shown");
    } else {
        console.error("[finance] saveRefBtn not found");
    }
    hideFinanceError('error1');
    console.log("[finance] Item inputs created successfully");
}

function saveFinanceReference() {
    const newItems = [];
    let total0 = 0;
    
    for (let i = 0; i < financeState.itemInputs.length; i++) {
        const nameEl = document.getElementById(financeState.itemInputs[i].name);
        const valueEl = document.getElementById(financeState.itemInputs[i].value);
        const quantityEl = document.getElementById(financeState.itemInputs[i].quantity);
        
        if (!nameEl || !valueEl) continue;
        
        const name = nameEl.value.trim();
        const initialValue = parseFloat(valueEl.value);
        const quantity = parseFloat(quantityEl?.value) || 0;
        
        if (!name) {
            showFinanceError('error1', `Başlık ${i + 1} için isim gerekli`);
            return;
        }
        
        if (isNaN(initialValue) || initialValue < 0) {
            showFinanceError('error1', `Başlık ${i + 1} için geçerli bir değer gerekli (>= 0)`);
            return;
        }
        
        total0 += initialValue;
        newItems.push({ name, initialValue, quantity });
    }
    
    if (total0 <= 0) {
        showFinanceError('error1', 'Toplam 0 olamaz');
        return;
    }
    
    financeState.items = newItems.map(item => ({
        name: item.name,
        targetWeight: item.initialValue / total0,
        initialValue: item.initialValue,
        quantity: item.quantity || 0
    }));
    
    const nameInput = document.getElementById('portfolioNameInput');
    const portfolioName = nameInput?.value.trim() || 'İsimsiz Portföy';
    const data = {
        items: financeState.items,
        createdAt: new Date().toISOString(),
        portfolioName: portfolioName,
        shortId: financeState.shortId
    };
    localStorage.setItem(financeState.storageKey, JSON.stringify(data));
    
    showFinanceScreen2();
}

function renderFinancePortfolioTable() {
    const tbody = document.getElementById('portfolioBody');
    if (!tbody) return;
    
    tbody.innerHTML = '';
    
    financeState.items.forEach((item, index) => {
        const row = document.createElement('tr');
        row.setAttribute('data-item-index', String(index));
        const currentValue = item.lastValue || item.currentValue || item.initialValue || 0;
        const quantity = item.quantity || 0;
        row.innerHTML = `
            <td data-label="Başlık Adı" style="padding: 12px;">${item.name}</td>
            <td data-label="Hedef Yüzde" style="padding: 12px; text-align: right;">${(item.targetWeight * 100).toFixed(2)}%</td>
            <td data-label="Güncel Değer (USD)" style="padding: 12px; text-align: right;">
                <input type="number" 
                       id="current_${index}" 
                       value="${currentValue.toFixed(2)}" 
                       min="0" 
                       step="0.01"
                       class="form-input finance-portfolio-input"
                       style="width: 150px; text-align: right;">
            </td>
            <td data-label="Adet (Not)" style="padding: 12px; text-align: right;">
                <input type="number" 
                       id="quantity_${index}" 
                       value="${quantity.toFixed(2)}" 
                       min="0" 
                       step="0.01"
                       class="form-input finance-portfolio-input"
                       style="width: 100px; text-align: right;"
                       placeholder="Not">
            </td>
            <td id="result_${index}" data-label="Sonuç" style="padding: 12px; text-align: center; font-weight: 600;">-</td>
        `;
        tbody.appendChild(row);
    });
}

/** Portföy tekrar ortalama (rebalance): hedef yüzdelerle mevcut değerleri karşılaştırır, AL/SAT önerisi üretir */
function calculateFinanceRebalance() {
    let total1 = 0;
    const currentValues = [];
    
    for (let index = 0; index < financeState.items.length; index++) {
        const item = financeState.items[index];
        const currentEl = document.getElementById(`current_${index}`);
        if (!currentEl) continue;
        
        const currentValue = parseFloat(currentEl.value);
        if (isNaN(currentValue) || currentValue < 0) {
            showFinanceError('error2', `${item.name} için geçerli bir değer gerekli (>= 0)`);
            return;
        }
        currentValues.push(currentValue);
        total1 += currentValue;
    }
    
    if (total1 <= 0) {
        showFinanceError('error2', 'Toplam değer 0 olamaz');
        return;
    }
    
    hideFinanceError('error2');
    
    financeState.items.forEach((item, index) => {
        const currentValue = currentValues[index];
        const targetValue = item.targetWeight * total1;
        const diff = currentValue - targetValue;
        
        const resultCell = document.getElementById(`result_${index}`);
        if (!resultCell) return;
        
        if (Math.abs(diff) < 0.01) {
            resultCell.textContent = 'DENGEDE';
            resultCell.className = 'action-balanced';
            resultCell.style.color = '#6c757d';
        } else if (diff > 0) {
            const sellAmount = diff;
            resultCell.textContent = `SAT ${sellAmount.toFixed(2)} USD`;
            resultCell.className = 'action-sell';
            resultCell.style.color = '#dc3545';
        } else {
            const buyAmount = -diff;
            resultCell.textContent = `AL ${buyAmount.toFixed(2)} USD`;
            resultCell.className = 'action-buy';
            resultCell.style.color = '#28a745';
        }
    });
    
    showFinanceSummary(total1);
}

function showFinanceSummary(currentTotal) {
    const summary = document.getElementById('summary');
    const content = document.getElementById('summaryContent');
    if (!summary || !content) return;
    
    const saved = JSON.parse(localStorage.getItem(financeState.storageKey) || '{}');
    const lastTotal = saved?.lastTotal;
    
    let prevText = '—';
    let pnlUsdText = '—';
    let pnlPctText = '—';
    let goldText = '—';
    
    if (lastTotal !== undefined && lastTotal > 0) {
        const pnlUsd = currentTotal - lastTotal;
        const pnlPct = (pnlUsd / lastTotal) * 100;
        
        const usdSign = pnlUsd >= 0 ? '+' : '';
        const pctSign = pnlPct >= 0 ? '+' : '';
        
        prevText = `${lastTotal.toFixed(2)} USD`;
        pnlUsdText = `${usdSign}${pnlUsd.toFixed(2)} USD`;
        pnlPctText = `${pctSign}${pnlPct.toFixed(2)} %`;
    }
    
    // Gram altın hesaplama
    if (financeState.goldPriceTRY && financeState.usdtTry && currentTotal > 0) {
        // Portföy değeri USD -> TL çevir
        const portfolioValueTRY = currentTotal * financeState.usdtTry;
        // Gram altın miktarı hesapla
        const goldGrams = portfolioValueTRY / financeState.goldPriceTRY;
        goldText = `${portfolioValueTRY.toFixed(2)} TL (${goldGrams.toFixed(4)} gram)`;
    } else if (financeState.goldPriceTRY && currentTotal > 0) {
        // Sadece gram altın fiyatı varsa (USDTRY yoksa)
        goldText = `Gram altın: ${financeState.goldPriceTRY.toFixed(2)} TL`;
    }
    
    content.innerHTML = `
        <div style="display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid var(--ds-border);">
            <span style="font-weight: 500; color: var(--ds-text-secondary);">Önceki Portföy:</span>
            <span style="font-weight: 600; color: var(--ds-text-primary);">${prevText}</span>
        </div>
        <div style="display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid var(--ds-border);">
            <span style="font-weight: 500; color: var(--ds-text-secondary);">Toplam Portföy:</span>
            <span style="font-weight: 600; color: var(--ds-text-primary);">${currentTotal.toFixed(2)} USD</span>
        </div>
        <div style="display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid var(--ds-border);">
            <span style="font-weight: 500; color: var(--ds-text-secondary);">Kâr / Zarar:</span>
            <span style="font-weight: 600; color: var(--ds-text-primary);">${pnlUsdText}</span>
        </div>
        <div style="display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid var(--ds-border);">
            <span style="font-weight: 500; color: var(--ds-text-secondary);">Değişim:</span>
            <span style="font-weight: 600; color: var(--ds-text-primary);">${pnlPctText}</span>
        </div>
        <div style="display: flex; justify-content: space-between; padding: 8px 0;">
            <span style="font-weight: 500; color: var(--ds-text-secondary);">Gram Altın Değeri:</span>
            <span style="font-weight: 600; color: var(--ds-accent);">${goldText}</span>
        </div>
    `;
    
    summary.classList.remove('hidden');
    
    if (saved) {
        saved.currentTotal = currentTotal;
        localStorage.setItem(financeState.storageKey, JSON.stringify(saved));
    }
}

function updateGoldPriceDisplay() {
    // Gram altın fiyatını göster (eğer bir display elementi varsa)
    // Şimdilik sadece state'te tutuyoruz
}

function saveFinanceCurrentValues() {
    let total = 0;
    const currentValues = [];
    
    for (let index = 0; index < financeState.items.length; index++) {
        const item = financeState.items[index];
        const currentEl = document.getElementById(`current_${index}`);
        if (!currentEl) continue;
        
        const currentValue = parseFloat(currentEl.value);
        if (isNaN(currentValue) || currentValue < 0) {
            showFinanceError('error2', `${item.name} için geçerli bir değer gerekli (>= 0)`);
            return;
        }
        currentValues.push(currentValue);
        total += currentValue;
    }
    
    if (total <= 0) {
        showFinanceError('error2', 'Toplam değer 0 olamaz');
        return;
    }
    
    hideFinanceError('error2');
    
    for (let index = 0; index < financeState.items.length; index++) {
        const item = financeState.items[index];
        const currentValue = currentValues[index];
        const quantityEl = document.getElementById(`quantity_${index}`);
        const quantity = parseFloat(quantityEl?.value) || 0;
        
        item.targetWeight = currentValue / total;
        item.lastValue = currentValue;
        item.quantity = quantity;
    }
    
    const savedData = JSON.parse(localStorage.getItem(financeState.storageKey) || '{}');
    const portfolioName = savedData?.portfolioName || 'İsimsiz Portföy';
    const data = {
        items: financeState.items,
        createdAt: savedData.createdAt || new Date().toISOString(),
        lastTotal: total,
        currentTotal: total,
        portfolioName: portfolioName,
        shortId: savedData?.shortId || financeState.shortId
    };
    localStorage.setItem(financeState.storageKey, JSON.stringify(data));
    
    const titleEl = document.getElementById('portfolioTitle');
    if (titleEl) titleEl.textContent = portfolioName;
    
    for (let index = 0; index < financeState.items.length; index++) {
        const resultCell = document.getElementById(`result_${index}`);
        if (resultCell) {
            resultCell.textContent = '-';
            resultCell.className = '';
            resultCell.style.color = '';
        }
    }
    
    const summary = document.getElementById('summary');
    if (summary) summary.classList.add('hidden');
    
    renderFinancePortfolioTable();
    
    alert('Yeni referans kaydedildi! targetWeight güncellendi.');
}

function resetFinanceReference() {
    if (confirm('Referansı sıfırlamak istediğinize emin misiniz? Bu işlem geri alınamaz.')) {
        localStorage.removeItem(financeState.storageKey);
        financeState.items = [];
        financeState.itemInputs = [];
        const screen2 = document.getElementById('financeScreen2');
        const screen1 = document.getElementById('financeScreen1');
        if (screen2) screen2.classList.add('hidden');
        if (screen1) screen1.classList.remove('hidden');
        const container = document.getElementById('itemsContainer');
        if (container) container.innerHTML = '';
        const saveRefBtn = document.getElementById('saveRefBtn');
        if (saveRefBtn) saveRefBtn.classList.add('hidden');
        const countInput = document.getElementById('itemCount');
        if (countInput) countInput.value = '3';
        const nameInput = document.getElementById('portfolioNameInput');
        if (nameInput) nameInput.value = '';
        hideFinanceError('error1');
        hideFinanceError('error2');
    }
}

function showFinanceError(errorId, message) {
    const errorDiv = document.getElementById(errorId);
    if (errorDiv) {
        errorDiv.textContent = message;
        errorDiv.classList.remove('hidden');
        errorDiv.style.cssText = 'color: #dc3545; background: #f8d7da; padding: 10px; border-radius: 4px; margin: 10px 0;';
    }
}

function hideFinanceError(errorId) {
    const errorDiv = document.getElementById(errorId);
    if (errorDiv) {
        errorDiv.classList.add('hidden');
    }
}

// ============================================
// FINANCE REPORTS TAB (Finans)
// ============================================

let financeReportsState = {
    currentSubTab: "summary",
    equityCurveRange: "7d",
    reportPeriod: "weekly",
    tradesOffset: 0,
    tradesLimit: 100
};

// Initialize Reports tab
function initReportsTab() {
    console.log("[reports] Initializing reports tab (unified view - no sub-tabs)");
    
    if (State.accountId) {
        // Summary from dashboard_snapshot; load period/trades data
        loadEquityCurve('7d');
        
        // Initialize finance period selection (default to daily)
        if (!financePeriod) {
            financePeriod = 'daily';
            setFinancePeriod('daily');
        } else {
            loadFinancePeriodData();
        }
        
        // Initialize trades period selection (default to daily)
        if (!financeTradesPeriod) {
            financeTradesPeriod = 'daily';
            setTradesPeriod('daily');
        } else {
            loadFinanceTrades();
        }
        
        // Summary from dashboard_snapshot; no finance.summary poll
    }
}

function initSettingsTab() {
    if (!State.accountId) return;
    
    const serverPublicIpEl = document.getElementById("settingsServerPublicIp");
    const apiKeyInput = document.getElementById("settingsApiKey");
    const apiSecretInput = document.getElementById("settingsApiSecret");
    const apiKeyBtn = document.getElementById("settingsApiKeyBtn");
    const apiSecretBtn = document.getElementById("settingsApiSecretBtn");
    const apiKeyStatus = document.getElementById("settingsApiKeyStatus");
    const apiSecretStatus = document.getElementById("settingsApiSecretStatus");
    const deleteAccountBtn = document.getElementById("settingsDeleteAccountBtn");
    const deleteAccountStatus = document.getElementById("settingsDeleteAccountStatus");
    const usernameInput = document.getElementById("settingsUsername");
    const phoneInput = document.getElementById("settingsPhone");
    const phoneBtn = document.getElementById("settingsPhoneBtn");
    const phoneStatus = document.getElementById("settingsPhoneStatus");
    const passwordInput = document.getElementById("settingsPassword");
    const passwordConfirmInput = document.getElementById("settingsPasswordConfirm");
    const passwordBtn = document.getElementById("settingsPasswordBtn");
    const passwordStatus = document.getElementById("settingsPasswordStatus");
    
    if (apiKeyStatus) apiKeyStatus.textContent = "";
    if (apiSecretStatus) apiSecretStatus.textContent = "";
    if (deleteAccountStatus) deleteAccountStatus.textContent = "";
    if (passwordStatus) passwordStatus.textContent = "";
    if (phoneStatus) phoneStatus.textContent = "";
    if (apiKeyInput) apiKeyInput.value = "";
    if (apiSecretInput) apiSecretInput.value = "";
    if (passwordInput) passwordInput.value = "";
    if (passwordConfirmInput) passwordConfirmInput.value = "";
    
    // Load account name (not user name) for Ad Soyad field + user_phone + isolate_from_admin
    (async () => {
        try {
            const data = await window.apiClient.get(`/api/accounts/${State.accountId}/settings`);
            if (data.account_name && usernameInput) {
                usernameInput.value = data.account_name;
            } else if (State.accountMeta && State.accountMeta.name && usernameInput) {
                usernameInput.value = State.accountMeta.name;
            } else if (usernameInput) {
                usernameInput.value = "Hesap adı yüklenemedi";
            }
            if (data.user_phone != null && phoneInput) {
                phoneInput.value = typeof data.user_phone === "string" ? data.user_phone : "";
            }
            var isolateBtn = document.getElementById("btnToggleIsolate");
            var isolateStatus = document.getElementById("settingsIsolateStatus");
            if (data.isolate_from_admin !== undefined) {
                if (isolateBtn) {
                    isolateBtn.textContent = data.isolate_from_admin ? "İzolasyonu Kaldır" : "Adminden İzole Ol";
                    isolateBtn.classList.toggle("is-isolated", data.isolate_from_admin === true);
                }
                if (isolateStatus) {
                    isolateStatus.textContent = data.isolate_from_admin ? "Açık (admin erişemez)" : "Kapalı";
                    isolateStatus.style.color = data.isolate_from_admin ? "#0ecb81" : "var(--ds-text-secondary)";
                }
            }
        } catch (e) {
            console.warn("[settings] Failed to load account name:", e);
            if (State.accountMeta && State.accountMeta.name && usernameInput) {
                usernameInput.value = State.accountMeta.name;
            }
        }
    })();
    
    // Sunucu dış IP (otomatik, salt okunur) – GET /settings server_public_ip döndürür
    (async () => {
        try {
            const data = await window.apiClient.get(`/api/accounts/${State.accountId}/settings`);
            if (serverPublicIpEl) {
                const ip = (data.server_public_ip && typeof data.server_public_ip === "string") ? data.server_public_ip.trim() : "";
                serverPublicIpEl.value = ip || "—";
                serverPublicIpEl.placeholder = ip ? "" : "Alınamadı";
            }
        } catch (e) {
            console.warn("[settings] Failed to load server public IP:", e);
            if (serverPublicIpEl) { serverPublicIpEl.value = ""; serverPublicIpEl.placeholder = "Alınamadı"; }
        }
    })();
    
    if (apiKeyBtn) {
        apiKeyBtn.onclick = null;
        apiKeyBtn.onclick = async () => {
            const v = apiKeyInput?.value?.trim();
            if (!v) {
                if (apiKeyStatus) { apiKeyStatus.textContent = "Key girin."; apiKeyStatus.style.color = "var(--ds-text-error, #f6465d)"; }
                return;
            }
            apiKeyBtn.disabled = true;
            if (apiKeyStatus) { apiKeyStatus.textContent = "Güncelleniyor…"; apiKeyStatus.style.color = "var(--ds-text-secondary)"; }
            try {
                await window.apiClient(`/api/accounts/${State.accountId}/settings`, { method: "PATCH", body: { api_key: v } });
                if (apiKeyInput) apiKeyInput.value = "";
                if (apiKeyStatus) { apiKeyStatus.textContent = "Güncellendi."; apiKeyStatus.style.color = "#0ecb81"; }
                if (window.Toast) window.Toast.success("API key güncellendi.");
                updateBinanceConnectionNotice();
            } catch (e) {
                var detail = e && e.detail;
                var isEncryption = detail && detail.error_code === "ENCRYPTION_NOT_CONFIGURED";
                if (apiKeyStatus) {
                    apiKeyStatus.style.color = "var(--ds-text-error, #f6465d)";
                    apiKeyStatus.textContent = isEncryption ? "BINANCE_MASTER_KEY .env'de yok. Aşağıdaki çözüme bakın." : "Hata.";
                }
                const msg = (e && (e.message || (detail && (typeof detail === 'string' ? detail : detail.message)))) || "API key güncellenemedi.";
                if (window.Toast) window.Toast.error(msg);
                if (isEncryption && detail.fix && window.Toast) window.Toast.warning(detail.fix, { duration: 15000 });
            } finally {
                apiKeyBtn.disabled = false;
            }
        };
    }
    
    if (apiSecretBtn) {
        apiSecretBtn.onclick = null;
        apiSecretBtn.onclick = async () => {
            const v = apiSecretInput?.value?.trim();
            if (!v) {
                if (apiSecretStatus) { apiSecretStatus.textContent = "Secret girin."; apiSecretStatus.style.color = "var(--ds-text-error, #f6465d)"; }
                return;
            }
            apiSecretBtn.disabled = true;
            if (apiSecretStatus) { apiSecretStatus.textContent = "Güncelleniyor…"; apiSecretStatus.style.color = "var(--ds-text-secondary)"; }
            try {
                await window.apiClient(`/api/accounts/${State.accountId}/settings`, { method: "PATCH", body: { api_secret: v } });
                if (apiSecretInput) apiSecretInput.value = "";
                if (apiSecretStatus) { apiSecretStatus.textContent = "Güncellendi."; apiSecretStatus.style.color = "#0ecb81"; }
                if (window.Toast) window.Toast.success("API secret güncellendi.");
                updateBinanceConnectionNotice();
            } catch (e) {
                var detail = e && e.detail;
                var isEncryption = detail && detail.error_code === "ENCRYPTION_NOT_CONFIGURED";
                if (apiSecretStatus) {
                    apiSecretStatus.style.color = "var(--ds-text-error, #f6465d)";
                    apiSecretStatus.textContent = isEncryption ? "BINANCE_MASTER_KEY .env'de yok. Aşağıdaki çözüme bakın." : "Hata.";
                }
                const msg = (e && (e.message || (detail && (typeof detail === 'string' ? detail : detail.message)))) || "API secret güncellenemedi.";
                if (window.Toast) window.Toast.error(msg);
                if (isEncryption && detail.fix && window.Toast) window.Toast.warning(detail.fix, { duration: 15000 });
            } finally {
                apiSecretBtn.disabled = false;
            }
        };
    }

    if (phoneBtn && phoneInput) {
        phoneBtn.onclick = null;
        phoneBtn.onclick = async () => {
            const phone = (phoneInput.value || "").trim();
            const digits = phone.replace(/\D/g, "");
            if (digits.length < 10) {
                if (phoneStatus) { phoneStatus.textContent = "En az 10 rakam gerekli."; phoneStatus.style.color = "var(--ds-text-error, #f6465d)"; }
                if (window.Toast) window.Toast.error("Geçerli telefon numarası girin.");
                return;
            }
            phoneBtn.disabled = true;
            if (phoneStatus) { phoneStatus.textContent = ""; phoneStatus.style.color = ""; }
            try {
                const res = await fetch("/api/auth/update-phone", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    credentials: "same-origin",
                    body: JSON.stringify({ account_id: State.accountId, phone })
                });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) throw new Error(data.detail || "Telefon güncellenemedi");
                if (phoneStatus) { phoneStatus.textContent = "Telefon güncellendi."; phoneStatus.style.color = "#0ecb81"; }
                if (window.Toast) window.Toast.success("Telefon güncellendi.");
            } catch (e) {
                if (phoneStatus) { phoneStatus.textContent = (e.message || "Hata"); phoneStatus.style.color = "var(--ds-text-error, #f6465d)"; }
                if (window.Toast) window.Toast.error(e.message || "Telefon güncellenemedi.");
            } finally {
                phoneBtn.disabled = false;
            }
        };
    }
    
    // Real-time password validation (uses shared dashboardValidatePassword)
    const passwordStrengthDiv = document.getElementById("settingsPasswordStrength");
    const passwordMatchDiv = document.getElementById("settingsPasswordMatch");
    
    if (passwordInput) {
        passwordInput.addEventListener('input', () => {
            const password = passwordInput.value;
            if (password.length > 0) {
                // Get user name/surname from localStorage
                const userData = JSON.parse(localStorage.getItem('user') || '{}');
                const name = userData.name || '';
                const surname = userData.surname || '';
                const result = dashboardValidatePassword(password, name, surname);
                if (passwordStrengthDiv) {
                    passwordStrengthDiv.textContent = result.msg;
                    passwordStrengthDiv.style.color = result.valid ? '#0ecb81' : 'var(--ds-text-error, #f6465d)';
                }
            } else {
                if (passwordStrengthDiv) passwordStrengthDiv.textContent = '';
            }
        });
    }
    
    if (passwordConfirmInput && passwordInput) {
        passwordConfirmInput.addEventListener('input', () => {
            const match = passwordInput.value === passwordConfirmInput.value;
            if (passwordConfirmInput.value.length > 0) {
                if (passwordMatchDiv) {
                    passwordMatchDiv.textContent = match ? '✓ Şifreler eşleşiyor' : '✗ Şifreler eşleşmiyor';
                    passwordMatchDiv.style.color = match ? '#0ecb81' : 'var(--ds-text-error, #f6465d)';
                }
            } else {
                if (passwordMatchDiv) passwordMatchDiv.textContent = '';
            }
        });
    }
    
    // Password change handler
    if (passwordBtn && passwordInput && passwordConfirmInput) {
        passwordBtn.onclick = null;
        passwordBtn.onclick = async () => {
            const newPassword = passwordInput.value.trim();
            const newPasswordConfirm = passwordConfirmInput.value.trim();
            
            if (!newPassword || !newPasswordConfirm) {
                if (passwordStatus) { 
                    passwordStatus.textContent = "Lütfen şifre alanlarını doldurun."; 
                    passwordStatus.style.color = "var(--ds-text-error, #f6465d)"; 
                }
                if (window.Toast) window.Toast.error("Lütfen şifre alanlarını doldurun.");
                return;
            }
            
            if (newPassword !== newPasswordConfirm) {
                if (passwordStatus) { 
                    passwordStatus.textContent = "Şifreler eşleşmiyor."; 
                    passwordStatus.style.color = "var(--ds-text-error, #f6465d)"; 
                }
                if (window.Toast) window.Toast.error("Şifreler eşleşmiyor.");
                return;
            }
            
            // Validate password strength before sending
            const userData = JSON.parse(localStorage.getItem('user') || '{}');
            const name = userData.name || '';
            const surname = userData.surname || '';
            const passwordCheck = dashboardValidatePassword(newPassword, name, surname);
            if (!passwordCheck.valid) {
                if (passwordStatus) { 
                    passwordStatus.textContent = passwordCheck.msg; 
                    passwordStatus.style.color = "var(--ds-text-error, #f6465d)"; 
                }
                if (window.Toast) window.Toast.error(passwordCheck.msg);
                return;
            }
            
            passwordBtn.disabled = true;
            if (passwordStatus) { 
                passwordStatus.textContent = "Güncelleniyor…"; 
                passwordStatus.style.color = "var(--ds-text-secondary)"; 
            }
            
            try {
                await window.apiClient.post('/api/auth/change-password', {
                    account_id: State.accountId,
                    new_password: newPassword,
                    new_password_confirm: newPasswordConfirm
                });
                
                if (passwordStatus) { 
                    passwordStatus.textContent = "Şifre başarıyla değiştirildi."; 
                    passwordStatus.style.color = "#0ecb81"; 
                }
                if (passwordStrengthDiv) passwordStrengthDiv.textContent = '';
                if (passwordMatchDiv) passwordMatchDiv.textContent = '';
                if (passwordInput) passwordInput.value = "";
                if (passwordConfirmInput) passwordConfirmInput.value = "";
                if (window.Toast) window.Toast.success("Şifre başarıyla değiştirildi.");
                
                // Update user in localStorage (must_change_password = false)
                try {
                    const u = JSON.parse(localStorage.getItem('user') || '{}');
                    u.must_change_password = false;
                    localStorage.setItem('user', JSON.stringify(u));
                } catch (e) {}
            } catch (e) {
                const errorMsg = e.message || "Şifre değiştirilemedi";
                if (passwordStatus) { 
                    passwordStatus.textContent = errorMsg; 
                    passwordStatus.style.color = "var(--ds-text-error, #f6465d)"; 
                }
                if (window.Toast) window.Toast.error(errorMsg);
            } finally {
                passwordBtn.disabled = false;
            }
        };
    }
    
    if (deleteAccountBtn) {
        var deleteAccountModalEl = document.getElementById("deleteAccountModal");
        var deleteAccountModalBackdrop = document.getElementById("deleteAccountModalBackdrop");
        var deleteAccountPasswordInput = document.getElementById("deleteAccountPasswordInput");
        var deleteAccountModalError = document.getElementById("deleteAccountModalError");
        var deleteAccountModalClose = document.getElementById("deleteAccountModalClose");
        var deleteAccountModalCancel = document.getElementById("deleteAccountModalCancel");
        var deleteAccountModalConfirm = document.getElementById("deleteAccountModalConfirm");

        function openDeleteAccountModal() {
            if (deleteAccountPasswordInput) deleteAccountPasswordInput.value = "";
            if (deleteAccountModalError) deleteAccountModalError.textContent = "";
            if (deleteAccountModalBackdrop) { deleteAccountModalBackdrop.style.display = "block"; deleteAccountModalBackdrop.setAttribute("aria-hidden", "false"); }
            if (deleteAccountModalEl) { deleteAccountModalEl.style.display = "flex"; deleteAccountModalEl.setAttribute("aria-hidden", "false"); }
            if (deleteAccountPasswordInput) setTimeout(function () { deleteAccountPasswordInput.focus(); }, 100);
        }
        function closeDeleteAccountModal() {
            if (deleteAccountModalBackdrop) { deleteAccountModalBackdrop.style.display = "none"; deleteAccountModalBackdrop.setAttribute("aria-hidden", "true"); }
            if (deleteAccountModalEl) { deleteAccountModalEl.style.display = "none"; deleteAccountModalEl.setAttribute("aria-hidden", "true"); }
        }

        deleteAccountBtn.onclick = function () {
            if (deleteAccountStatus) { deleteAccountStatus.textContent = ""; deleteAccountStatus.style.color = ""; }
            openDeleteAccountModal();
        };

        if (deleteAccountModalClose) deleteAccountModalClose.onclick = closeDeleteAccountModal;
        if (deleteAccountModalCancel) deleteAccountModalCancel.onclick = closeDeleteAccountModal;
        if (deleteAccountModalBackdrop) deleteAccountModalBackdrop.onclick = closeDeleteAccountModal;

        if (deleteAccountModalConfirm) {
            deleteAccountModalConfirm.onclick = async function () {
                var pwd = (deleteAccountPasswordInput && deleteAccountPasswordInput.value) ? deleteAccountPasswordInput.value : "";
                if (!pwd.trim()) {
                    if (deleteAccountModalError) deleteAccountModalError.textContent = "Şifre girin.";
                    return;
                }
                if (!State.accountId || !window.apiClient) return;
                deleteAccountModalConfirm.disabled = true;
                if (deleteAccountModalError) deleteAccountModalError.textContent = "";
                try {
                    await window.apiClient.post("/api/accounts/" + State.accountId + "/delete", { password: pwd });
                    closeDeleteAccountModal();
                    if (window.Toast) window.Toast.success("Hesap silindi.");
                    window.location.href = "/ui/login.html";
                } catch (e) {
                    deleteAccountModalConfirm.disabled = false;
                    var msg = (e && e.detail) ? (typeof e.detail === "string" ? e.detail : (e.detail.message || e.detail.detail || "Hata")) : "Hesap silinemedi.";
                    if (e.status === 400 && e.detail && typeof e.detail === "object" && e.detail.detail) msg = e.detail.detail;
                    if (deleteAccountModalError) deleteAccountModalError.textContent = msg;
                    if (window.Toast) window.Toast.error(msg);
                }
            };
        }
    }

    var btnToggleIsolate = document.getElementById("btnToggleIsolate");
    var settingsIsolateStatus = document.getElementById("settingsIsolateStatus");
    if (btnToggleIsolate) {
        btnToggleIsolate.onclick = null;
        btnToggleIsolate.onclick = async function () {
            if (!State.accountId || !window.apiClient) return;
            btnToggleIsolate.disabled = true;
            if (settingsIsolateStatus) { settingsIsolateStatus.textContent = "Güncelleniyor…"; settingsIsolateStatus.style.color = "var(--ds-text-secondary)"; }
            try {
                var data = await window.apiClient.get("/api/accounts/" + State.accountId + "/settings");
                var next = !(data.isolate_from_admin === true);
                await window.apiClient.patch("/api/accounts/" + State.accountId + "/settings", { isolate_from_admin: next });
                if (btnToggleIsolate) {
                    btnToggleIsolate.textContent = next ? "İzolasyonu Kaldır" : "Adminden İzole Ol";
                    btnToggleIsolate.classList.toggle("is-isolated", next === true);
                }
                if (settingsIsolateStatus) {
                    settingsIsolateStatus.textContent = next ? "Açık (admin erişemez)" : "Kapalı";
                    settingsIsolateStatus.style.color = next ? "#0ecb81" : "var(--ds-text-secondary)";
                }
                if (window.Toast) window.Toast.success(next ? "Adminden izole açıldı." : "İzolasyon kaldırıldı.");
            } catch (e) {
                if (settingsIsolateStatus) { settingsIsolateStatus.textContent = "Hata."; settingsIsolateStatus.style.color = "var(--ds-text-error, #f6465d)"; }
                if (window.Toast) window.Toast.error((e && e.message) || "Güncellenemedi.");
            } finally {
                btnToggleIsolate.disabled = false;
            }
        };
    }
}

function openAuditModal() {
    var backdrop = document.getElementById("auditModalBackdrop");
    var modal = document.getElementById("auditModal");
    if (!backdrop || !modal) return;
    backdrop.setAttribute("aria-hidden", "false");
    backdrop.style.display = "block";
    modal.setAttribute("aria-hidden", "false");
    modal.style.display = "flex";
    document.body.style.overflow = "hidden";
    backdrop.onclick = function (e) { if (e.target === backdrop) closeAuditModal(); };
    loadSettingsAudit("month");
    var listEl = document.getElementById("settingsAuditList");
    if (listEl) listEl.innerHTML = "<span style=\"color: var(--ds-text-secondary);\">Yükleniyor...</span>";
    document.querySelectorAll(".audit-range-btn").forEach(function (btn) {
        btn.classList.remove("active");
        if ((btn.getAttribute("data-range") || "") === "month") btn.classList.add("active");
    });
    document.querySelectorAll(".audit-range-btn").forEach(function (btn) {
        btn.onclick = function () {
            document.querySelectorAll(".audit-range-btn").forEach(function (b) { b.classList.remove("active"); });
            btn.classList.add("active");
            var range = btn.getAttribute("data-range") || "month";
            loadSettingsAudit(range);
        };
    });
    var typeFilterEl = document.getElementById("settingsAuditTypeFilter");
    if (typeFilterEl) {
        typeFilterEl.value = "";
        typeFilterEl.onchange = setAuditTypeFilter;
    }
}
function closeAuditModal() {
    var backdrop = document.getElementById("auditModalBackdrop");
    var modal = document.getElementById("auditModal");
    if (backdrop) { backdrop.setAttribute("aria-hidden", "true"); backdrop.style.display = "none"; }
    if (modal) { modal.setAttribute("aria-hidden", "true"); modal.style.display = "none"; }
    document.body.style.overflow = "";
}
var AUDIT_EVENT_LABELS = { LOGIN_SUCCESS: "Giriş başarılı", LOGIN_FAILED: "Giriş başarısız", LOGOUT: "Çıkış", SPOT_ORDER_CREATE: "Spot emir", BOT_CREATE: "Bot oluşturuldu", BOT_START: "Bot başlatıldı", BOT_STOP: "Bot durduruldu", BOT_DELETE: "Bot silindi", BOT_TRADE: "Bot alım/satım", PASSWORD_CHANGE: "Şifre değişti", PHONE_UPDATE: "Telefon güncellendi", CHAT_USER_MESSAGE: "Sohbet (siz)", CHAT_ADMIN_MESSAGE: "Sohbet (admin)" };

/** Tarih-saati Türkiye saatine göre formatla (dd.MM.yyyy HH:mm:ss) */
function formatAuditTimeTR(isoOrMs) {
    if (!isoOrMs) return "—";
    try {
        if (window.trTime && window.trTime.trFormatDateTime) return window.trTime.trFormatDateTime(isoOrMs);
        var d = new Date(isoOrMs);
        if (!Number.isFinite(d.getTime())) return "—";
        return d.toLocaleString("tr-TR", { timeZone: "Europe/Istanbul", day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
    } catch (e) { return "—"; }
}

function renderSettingsAuditTable(events, typeFilter) {
    var listEl = document.getElementById("settingsAuditList");
    if (!listEl) return;
    if (!events || events.length === 0) {
        listEl.innerHTML = "<p style=\"color: var(--ds-text-secondary); padding: 1.5rem;\">Bu dönemde kayıt yok.</p>";
        return;
    }
    var filtered = typeFilter ? events.filter(function (e) { return e.event_type === typeFilter; }) : events;
    if (filtered.length === 0) {
        listEl.innerHTML = "<p style=\"color: var(--ds-text-secondary); padding: 1.5rem;\">Seçilen türde kayıt yok.</p>";
        return;
    }
    var html = '<table class="audit-table" style="width:100%; border-collapse: collapse; font-size: 0.8rem;"><thead><tr style="border-bottom: 2px solid var(--ds-border); background: var(--ds-bg-tertiary);"><th style="text-align: left; padding: 0.6rem 0.5rem; font-weight: 600;">Tarih-Saat (TR)</th><th style="text-align: left; padding: 0.6rem 0.5rem; font-weight: 600;">Kim</th><th style="text-align: left; padding: 0.6rem 0.5rem; font-weight: 600;">IP</th><th style="text-align: left; padding: 0.6rem 0.5rem; font-weight: 600;">İşlem türü</th><th style="text-align: left; padding: 0.6rem 0.5rem; font-weight: 600;">Detay</th></tr></thead><tbody>';
    filtered.forEach(function (e) {
        var time = formatAuditTimeTR(e.created_at);
        var actor = (e.actor_type === "admin" ? "Admin" : (e.actor_type === "system" ? "Sistem" : (e.actor_label || "Siz")));
        var ip = (e.ip != null && e.ip !== "") ? e.ip : "—";
        var typeLabel = AUDIT_EVENT_LABELS[e.event_type] || e.event_type || "—";
        var detail = (e.detail != null && e.detail !== "") ? String(e.detail).replace(/</g, "&lt;").replace(/>/g, "&gt;") : "—";
        html += "<tr style=\"border-bottom: 1px solid var(--ds-border);\"><td style=\"padding: 0.6rem 0.5rem; white-space: nowrap; color: var(--ds-text-secondary);\">" + time + "</td><td style=\"padding: 0.6rem 0.5rem;\">" + actor + "</td><td style=\"padding: 0.6rem 0.5rem; font-family: monospace; font-size: 0.75rem;\">" + ip + "</td><td style=\"padding: 0.6rem 0.5rem;\">" + typeLabel + "</td><td style=\"padding: 0.6rem 0.5rem; max-width: 380px; word-break: break-word;\">" + detail + "</td></tr>";
    });
    html += "</tbody></table>";
    listEl.innerHTML = html;
}

function loadSettingsAudit(rangeKey) {
    var listEl = document.getElementById("settingsAuditList");
    if (!listEl || !State.accountId || !window.apiClient) return;
    var range = (rangeKey || "month").toLowerCase();
    if (range === "3month") range = "3m";
    if (range === "6month") range = "6m";
    listEl.innerHTML = "<span style=\"color: var(--ds-text-secondary);\">Yükleniyor...</span>";
    var typeFilterEl = document.getElementById("settingsAuditTypeFilter");
    var typeFilter = (typeFilterEl && typeFilterEl.value) ? typeFilterEl.value : "";
    window.apiClient.get("/api/audit/events?account_id=" + State.accountId + "&range=" + encodeURIComponent(range) + "&limit=200&offset=0&_t=" + Date.now()).then(function (data) {
        var events = (data && data.events) ? data.events : [];
        State.auditEventsCache = events;
        renderSettingsAuditTable(events, typeFilter);
    }).catch(function (e) {
        listEl.innerHTML = "<p style=\"color: var(--ds-danger, #f6465d);\">Yüklenemedi.</p>";
    });
}

function setAuditTypeFilter() {
    var typeFilterEl = document.getElementById("settingsAuditTypeFilter");
    var typeFilter = (typeFilterEl && typeFilterEl.value) ? typeFilterEl.value : "";
    var events = State.auditEventsCache || [];
    renderSettingsAuditTable(events, typeFilter);
}
window.openAuditModal = openAuditModal;
window.closeAuditModal = closeAuditModal;

async function loadFinanceSummary() {
    if (!State.accountId) return;
    
    try {
        // Load finance summary
        let data;
        if (window.financeService) {
            data = await window.financeService.getSummary(State.accountId);
        } else {
            data = await window.apiClient.get(`/api/finance/summary?account_id=${State.accountId}&cb=${Date.now()}`);
        }
        
        // Cüzdan bakiye + Kullanılabilir/Kilitli – tek kaynak: /api/binance/wallet
        data.binance_balance_usd = 0;
        data.spot_balance_usd = 0;
        data.free_usd = 0;
        data.locked_usd = 0;
        data.available_usd = 0;
        data.bot_locked_usd = 0;
        try {
            const wallet = await window.apiClient.get(`/api/binance/wallet?account_id=${State.accountId}`);
            const total = Number(wallet.total_usd) || 0;
            data.binance_balance_usd = total;
            data.spot_balance_usd = total;
            data.free_usd = Number(wallet.free_usd) || 0;
            data.locked_usd = Number(wallet.locked_usd) || 0;
            data.available_usd = Number(wallet.available_usd) ?? data.free_usd;
            data.bot_locked_usd = Number(wallet.bot_locked_usd) || 0;
            // Strip tek kaynak: assetsState.wallet. Finance summary wallet'ı state'e uygula, strip renderAssetsSummary ile güncellenir (flicker önleme).
            if (typeof normalizeAndApplyWallet === 'function') normalizeAndApplyWallet(wallet, { source: 'finance_summary', request_id: null });
        } catch (_) {
            // hata durumunda 0 kalır
        }
        // Bot bakiyesi: finance/summary'dan gelsin; yoksa dashboard summary ile senkron (aynı kaynak = state panel)
        if ((!data.account || data.account.bots_balance_usd == null) && State.summary && State.summary.account && State.summary.account.bots_balance_usd != null) {
            data.account = data.account || {};
            data.account.bots_balance_usd = State.summary.account.bots_balance_usd;
            data.bots_balance_usd = State.summary.account.bots_balance_usd;
        }
        // Update KPI cards
        updateFinanceKPIs(data);
        
        // Mevcut Botlar: snapshot/API bot listesi öncelikli (session cache hayalet satır üretmesin)
        if (State.summary && Array.isArray(State.summary.bots)) {
            renderFinanceBots(State.summary.bots);
        } else if (data.bots && Array.isArray(data.bots) && data.bots.length) {
            renderFinanceBots(data.bots);
        } else if (State.bots && State.bots.length) {
            renderFinanceBots(State.bots);
        } else {
            renderFinanceBots(data.bot_summary || []);
        }
        
    } catch (error) {
        console.error("[reports] Error loading finance summary:", error);
        if (window.errorReporter) {
            window.errorReporter.report(error, { tab: 'reports', account_id: State.accountId, action: 'loadFinanceSummary' });
        }
    }
}

// Helper function to update finance KPIs - Refactored
function updateFinanceKPIs(data) {
    const balance = data.binance_balance_usd || data.spot_balance_usd || 0;
    // Bot bakiyesi: bot detay state panel ile aynı kaynak (current_usd / bots_balance_usd)
    let totalBotBalance = (data.account && data.account.bots_balance_usd != null && Number.isFinite(data.account.bots_balance_usd))
        ? data.account.bots_balance_usd
        : (data.bots_balance_usd != null && Number.isFinite(data.bots_balance_usd) ? data.bots_balance_usd : 0);
    if (totalBotBalance === 0 && data.bots && Array.isArray(data.bots)) {
        data.bots.forEach(b => {
            const cu = b.current_usd != null && Number.isFinite(b.current_usd) ? b.current_usd : 0;
            totalBotBalance += cu;
        });
    }
    if (totalBotBalance === 0 && data.bot_summary && Array.isArray(data.bot_summary)) {
        data.bot_summary.forEach(bot => {
            const cu = bot.current_usd != null && Number.isFinite(bot.current_usd) ? bot.current_usd : ((bot.budget_usd || bot.initial_usd || 0) + (bot.total_pnl_usd || bot.total_pnl || bot.pnl_30d || 0));
            totalBotBalance += cu;
        });
    }
    var account = data.account || {};
    var hasDailyKpi = (account.daily_wallet_pnl_usd !== undefined && account.daily_wallet_pnl_usd !== null) || (account.daily_bot_pnl_usd !== undefined && account.daily_bot_pnl_usd !== null)
        || (data.daily_wallet_pnl_usd !== undefined && data.daily_wallet_pnl_usd !== null) || (data.daily_bot_pnl_usd !== undefined && data.daily_bot_pnl_usd !== null);
    var dailyBotPnl = account.daily_bot_pnl_usd ?? data.daily_bot_pnl_usd ?? data.today?.pnl ?? 0;
    var dailyWalletPnl = account.daily_wallet_pnl_usd ?? data.daily_wallet_pnl_usd ?? 0;
    var baseVal = data.initial_value || data.total_usd_value || 1;

    // Ortak KPI şeridi (tek kaynak): Cüzdan, Cüzdan PnL, Botlar Bakiye, Botlar PnL
    var walletEl = document.getElementById('kpiCuzdan');
    if (walletEl) { setTextIfChanged(walletEl, fmtUsd(balance)); triggerValueBlink(walletEl, balance); }
    lastSpotUpdateTs = Date.now();
    var cuzdanLiveLabel = (typeof State !== 'undefined' && State.isTestAccount) ? 'Test' : (assetsState.wallet.keys_configured === true ? 'Canlı' : 'Bağlı değil');
    patchText('kpiCuzdanLive', cuzdanLiveLabel);
    if (hasDailyKpi) {
        var cuzdanPnlEl = document.getElementById('kpiCuzdanPnl');
        if (cuzdanPnlEl) {
            var textChanged = setTextIfChanged(cuzdanPnlEl, fmtUsd(dailyWalletPnl));
            var newColor = dailyWalletPnl >= 0 ? '#0ecb81' : '#f6465d';
            if (cuzdanPnlEl.style.color !== newColor) cuzdanPnlEl.style.color = newColor;
            if (textChanged) triggerValueBlink(cuzdanPnlEl, dailyWalletPnl);
        }
        var pctCuzdan = (account.daily_wallet_pnl_pct != null && Number.isFinite(account.daily_wallet_pnl_pct)) || (data.daily_wallet_pnl_pct != null && Number.isFinite(data.daily_wallet_pnl_pct))
            ? Number(account.daily_wallet_pnl_pct ?? data.daily_wallet_pnl_pct).toFixed(2) : ((data.total_usd_value || 1) > 0 ? ((dailyWalletPnl / (data.total_usd_value || 1)) * 100).toFixed(2) : '0.00');
        patchText('kpiCuzdanPnlPct', (parseFloat(pctCuzdan) >= 0 ? '+' : '') + pctCuzdan + '%');
        var pe = document.getElementById('kpiCuzdanPnlPct'); if (pe) { var ec = dailyWalletPnl >= 0 ? '#0ecb81' : '#f6465d'; if (pe.style.color !== ec) pe.style.color = ec; }
        var botPnlEl = document.getElementById('kpiBotPnl');
        if (botPnlEl) {
            var botTextChanged = setTextIfChanged(botPnlEl, fmtUsd(dailyBotPnl));
            var botColor = dailyBotPnl >= 0 ? '#0ecb81' : '#f6465d';
            if (botPnlEl.style.color !== botColor) botPnlEl.style.color = botColor;
            if (botTextChanged) triggerValueBlink(botPnlEl, dailyBotPnl);
        }
        var pct = (account.daily_bot_pnl_pct != null && Number.isFinite(account.daily_bot_pnl_pct)) || (data.daily_bot_pnl_pct != null && Number.isFinite(data.daily_bot_pnl_pct))
            ? Number(account.daily_bot_pnl_pct ?? data.daily_bot_pnl_pct).toFixed(2) : (baseVal > 0 ? ((dailyBotPnl / baseVal) * 100).toFixed(2) : '0.00');
        patchText('kpiBotPnlPct', (parseFloat(pct) >= 0 ? '+' : '') + pct + '%');
        pe = document.getElementById('kpiBotPnlPct'); if (pe) { var botPctC = parseFloat(pct) >= 0 ? '#0ecb81' : '#f6465d'; if (pe.style.color !== botPctC) pe.style.color = botPctC; }
    }
    // Tüm kpiBotBakiye göstergeleri aynı toplam (bütün botların bakiye toplamı)
    var botBakiyeEls = document.querySelectorAll('#kpiBotBakiye');
    botBakiyeEls.forEach(function (el) {
        el.textContent = fmtUsd(totalBotBalance);
        triggerValueBlink(el, totalBotBalance);
    });
    patchText('kpiBotBakiyePct', cuzdanLiveLabel);

    // Binance varlık strip tek kaynak: assetsState.wallet -> renderAssetsSummary (flicker önleme). Burada DOM güncellemesi yapılmaz.
}

function fmtSignedUsdOrDash(v) {
    if (v == null || !Number.isFinite(Number(v))) return '—';
    return fmtSignedUsd(v);
}

function isBotWaitingFirstBuy(bot) {
    if (!bot) return false;
    var st = (bot.status || '').toLowerCase();
    if (st !== 'running') return false;
    var ds = (bot.display_status || '').toLowerCase();
    if (ds === 'starting') return true;
    var botId = String(bot.bot_id || bot.id || '');
    var liveRow = botId && State.botLiveEquity && State.botLiveEquity[botId];
    if (liveRow && liveRow.first_buy_pending === true) return true;
    if (liveRow && liveRow.first_buy_pending === false) return false;
    if (liveRow && liveRow.base_balance != null && Number(liveRow.base_balance) > 0) return false;
    if (bot.first_buy_pending === true) return true;
    if (bot.initial_allocation_done === true) return false;
    var base = Number(bot.base_balance);
    if (Number.isFinite(base) && base > 0) return false;
    return true;
}

function getFinanceBotStatusMeta(bot) {
    if (isBotWaitingFirstBuy(bot)) {
        return { text: 'ALIM BEKLİYOR', className: 'mevcut-botlar-status--waiting' };
    }
    var stRaw = (bot.status || 'STOPPED').toUpperCase();
    var ds = (bot.display_status || '').toLowerCase();
    var key = ds === 'starting' ? 'starting' : stRaw.toLowerCase();
    var labels = {
        running: 'ÇALIŞIYOR',
        stopped: 'DURDURULDU',
        paused: 'DURAKLATILDI',
        paused_insufficient_balance: 'Yetersiz bakiye',
        waiting: 'BEKLİYOR',
        starting: 'BAŞLATILIYOR',
        error: 'HATA'
    };
    var text = labels[key] || stRaw;
    if (key === 'running') return { text: text, className: 'mevcut-botlar-status--running' };
    if (key === 'paused' || key === 'paused_insufficient_balance' || key === 'waiting' || key === 'starting') {
        return { text: text, className: 'mevcut-botlar-status--waiting' };
    }
    return { text: text, className: 'mevcut-botlar-status--stopped' };
}

// Anasayfa + Botlar sekmesi Mevcut Botlar: aynı tablo; financeBotsList (Anasayfa) ve financeBotsListBots (Botlar) birlikte güncellenir
var _financeBotsStructureSignature = null;
var _financeBotsLiveHydrated = false;
var _financeBotsLivePollPromise = null;
var _financeBotsLiveSig = '';
var _financeBotsMetricsCache = {};

function financeBotsSessionCacheKey(accountId) {
    return 'financeBotsTable_' + (accountId || '');
}

function loadFinanceBotsMetricsCache(accountId) {
    try {
        var raw = sessionStorage.getItem(financeBotsSessionCacheKey(accountId));
        if (!raw) return {};
        var data = JSON.parse(raw);
        return (data && data.metrics && typeof data.metrics === 'object') ? data.metrics : {};
    } catch (e) {
        return {};
    }
}

function getFinanceBotCachedMetric(bot) {
    var id = String((bot && (bot.bot_id || bot.id)) || '');
    if (!id) return null;
    if (!_financeBotsMetricsCache[id] && State.accountId) {
        _financeBotsMetricsCache = loadFinanceBotsMetricsCache(State.accountId);
    }
    return _financeBotsMetricsCache[id] || null;
}

function hydrateBotsWithMetricsCache(bots) {
    if (!Array.isArray(bots) || !bots.length) return bots || [];
    if (!Object.keys(_financeBotsMetricsCache).length && State.accountId) {
        _financeBotsMetricsCache = loadFinanceBotsMetricsCache(State.accountId);
    }
    return bots.map(function (bot) {
        var id = String(bot.bot_id || bot.id || '');
        var cached = id ? _financeBotsMetricsCache[id] : null;
        if (!cached) return bot;
        var out = Object.assign({}, bot);
        if ((out.current_usd == null || !Number.isFinite(out.current_usd)) && cached.current_usd != null) {
            out.current_usd = cached.current_usd;
        }
        if ((out.total_pnl_usd == null || !Number.isFinite(out.total_pnl_usd)) && cached.total_pnl_usd != null) {
            out.total_pnl_usd = cached.total_pnl_usd;
        }
        if ((out.total_cycles_completed == null || !Number.isFinite(out.total_cycles_completed)) && cached.cycles != null) {
            out.total_cycles_completed = cached.cycles;
        }
        return out;
    });
}

function persistFinanceBotsSessionCache(bots) {
    if (!State.accountId || !Array.isArray(bots) || !bots.length) return;
    try {
        var metrics = {};
        bots.forEach(function (bot) {
            var id = String(bot.bot_id || bot.id || '');
            if (!id) return;
            var currentUsd = resolveBotCurrentUsd(bot);
            if (currentUsd == null && bot.current_usd != null && Number.isFinite(bot.current_usd)) currentUsd = bot.current_usd;
            if (currentUsd == null) return;
            var budget = Number(bot.budget_usd || bot.initial_usd) || 0;
            metrics[id] = {
                current_usd: currentUsd,
                total_pnl_usd: budget > 0 ? currentUsd - budget : (bot.total_pnl_usd != null ? Number(bot.total_pnl_usd) : 0),
                cycles: resolveBotCycles(bot)
            };
        });
        _financeBotsMetricsCache = metrics;
        var slim = bots.map(function (b) {
            return {
                bot_id: b.bot_id || b.id,
                id: b.bot_id || b.id,
                symbol: b.symbol,
                status: b.status,
                display_status: b.display_status,
                initial_allocation_done: b.initial_allocation_done,
                budget_usd: b.budget_usd || b.initial_usd,
                initial_usd: b.initial_usd || b.budget_usd,
                current_usd: b.current_usd,
                total_pnl_usd: b.total_pnl_usd,
                total_pnl_pct: b.total_pnl_pct,
                total_cycles_completed: b.total_cycles_completed,
                cycle_id: b.cycle_id,
                config: b.config,
                config_json: b.config_json
            };
        });
        sessionStorage.setItem(financeBotsSessionCacheKey(State.accountId), JSON.stringify({
            ts: Date.now(),
            bots: slim,
            metrics: metrics
        }));
    } catch (e) {}
}

function restoreFinanceBotsFromSessionCache(accountId) {
    if (!accountId) return false;
    try {
        var raw = sessionStorage.getItem(financeBotsSessionCacheKey(accountId));
        if (!raw) return false;
        var data = JSON.parse(raw);
        if (!data || !data.metrics || typeof data.metrics !== 'object') return false;
        if (data.ts && Date.now() - data.ts > 86400000) return false;
        // Yalnızca metrik cache (flicker önleme); bot listesi API'den gelene kadar gösterilmez — silinen bot hayalet satır olmasın
        _financeBotsMetricsCache = data.metrics;
        return true;
    } catch (e) {
        return false;
    }
}

function clearFinanceBotsSessionCache(accountId) {
    if (!accountId) return;
    try {
        sessionStorage.removeItem(financeBotsSessionCacheKey(accountId));
    } catch (e) {}
    _financeBotsMetricsCache = {};
    _financeBotsStructureSignature = null;
}
window.clearFinanceBotsSessionCache = clearFinanceBotsSessionCache;

function resetFinanceBotsLiveCache(bots) {
    var sig = (bots || []).map(function (b) { return String(b.bot_id || b.id || ''); }).join(',');
    if (sig === _financeBotsLiveSig && _financeBotsLiveHydrated) return;
    _financeBotsLiveSig = sig;
    State.botLiveEquity = {};
    _financeBotsLiveHydrated = false;
    _financeBotsLivePollPromise = null;
}

function resolveBotLivePrice(sym) {
    if (!sym) return null;
    var s = (sym || '').toUpperCase();
    var mini = window.marketStore && window.marketStore.getMini(s);
    var p = (mini && mini.last != null) ? mini.last : (window.marketStore && window.marketStore.getPrice && window.marketStore.getPrice(s));
    return (p != null && Number.isFinite(p) && p > 0) ? p : null;
}

function botNeedsLiveEquity(bot) {
    if (!bot) return false;
    var st = (bot.status || '').toLowerCase();
    var ds = (bot.display_status || '').toLowerCase();
    if (st === 'running' || st === 'paused' || st === 'paused_insufficient_balance') return true;
    if (ds === 'starting' || ds === 'running') return true;
    return false;
}

function resolveBotLiveEquity(bot) {
    if (!bot || !State.botLiveEquity) return null;
    var botId = String(bot.bot_id || bot.id || '');
    if (!botId) return null;
    var row = State.botLiveEquity[botId];
    if (!row || row.equity == null || !Number.isFinite(row.equity) || row.equity_unavailable) return null;
    return row.equity;
}

function resolveBotCurrentUsd(bot) {
    if (botNeedsLiveEquity(bot)) {
        if (_financeBotsLiveHydrated) {
            var live = resolveBotLiveEquity(bot);
            if (live != null) return live;
        }
        if (bot.current_usd != null && Number.isFinite(bot.current_usd)) return bot.current_usd;
        var cached = getFinanceBotCachedMetric(bot);
        if (cached && cached.current_usd != null && Number.isFinite(cached.current_usd)) return cached.current_usd;
        return null;
    }
    if (bot.current_usd != null && Number.isFinite(bot.current_usd)) return bot.current_usd;
    return 0;
}

function resolveBotRowPnl(bot, currentUsd) {
    var budget = Number(bot.budget_usd || bot.initial_usd) || 0;
    if (currentUsd != null && budget > 0) return currentUsd - budget;
    if (bot.total_pnl_usd != null && Number.isFinite(bot.total_pnl_usd)) return Number(bot.total_pnl_usd);
    var cached = getFinanceBotCachedMetric(bot);
    if (cached && cached.total_pnl_usd != null && Number.isFinite(cached.total_pnl_usd)) return cached.total_pnl_usd;
    if (botNeedsLiveEquity(bot) && !_financeBotsLiveHydrated) return null;
    return Number(bot.total_pnl_usd) || 0;
}

function resolveBotCyclesDisplay(bot) {
    var cycles = resolveBotCycles(bot);
    if (cycles != null && cycles !== '' && Number(cycles) > 0) return String(cycles);
    var cached = getFinanceBotCachedMetric(bot);
    if (cached && cached.cycles != null && cached.cycles !== '') return String(cached.cycles);
    if (botNeedsLiveEquity(bot) && !_financeBotsLiveHydrated) return '—';
    return cycles != null && cycles !== '' ? String(cycles) : '—';
}

function applyFinanceBotsLiveEquityToDom() {
    if (!State.bots || !State.bots.length) return;
    State.bots.forEach(function (bot) {
        var botId = String(bot.bot_id || bot.id || '');
        if (!botId) return;
        var currentUsd = resolveBotCurrentUsd(bot);
        var pnl = resolveBotRowPnl(bot, currentUsd);
        var sc = pnl != null && pnl >= 0 ? '#0ecb81' : (pnl != null ? '#f6465d' : 'var(--ds-text-secondary)');
        var balanceTxt = currentUsd != null ? fmtUsd(currentUsd) : '—';
        var cyclesTxt = resolveBotCyclesDisplay(bot);
        document.querySelectorAll('.finance-bot-balance[data-bot-id="' + botId + '"]').forEach(function (cell) {
            if (setTextIfChanged(cell, balanceTxt)) { /* patched */ }
            cell.setAttribute('data-balance', currentUsd != null ? String(currentUsd) : '');
            cell.classList.toggle('finance-bot-metric-pending', balanceTxt === '—');
        });
        var statusMeta = getFinanceBotStatusMeta(bot);
        document.querySelectorAll('tr[data-bot-id="' + botId + '"]').forEach(function (row) {
            var tds = row.querySelectorAll('td');
            if (tds.length >= 3) {
                var statusEl = tds[2].querySelector('.mevcut-botlar-status');
                if (statusEl) {
                    setTextIfChanged(statusEl, statusMeta.text);
                    var statusCls = 'mevcut-botlar-status ' + statusMeta.className;
                    if (statusEl.className !== statusCls) statusEl.className = statusCls;
                }
            }
            if (tds.length >= 7) {
                setTextIfChanged(tds[5], fmtSignedUsdOrDash(pnl));
                if (tds[5].style.color !== sc) tds[5].style.color = sc;
                setTextIfChanged(tds[6], cyclesTxt);
            }
        });
        document.querySelectorAll('.mevcut-botlar-mobile-card[data-bot-id="' + botId + '"] .mevcut-botlar-mobile-stat-value').forEach(function (el) {
            var label = el.parentElement && el.parentElement.querySelector('.mevcut-botlar-mobile-stat-label');
            if (!label) return;
            if ((label.textContent || '') === 'Bakiye') setTextIfChanged(el, balanceTxt);
            if ((label.textContent || '') === 'K/Z') {
                setTextIfChanged(el, fmtSignedUsdOrDash(pnl));
                if (el.style.color !== sc) el.style.color = sc;
            }
            if ((label.textContent || '') === 'Tur') setTextIfChanged(el, cyclesTxt);
        });
        document.querySelectorAll('.mevcut-botlar-mobile-card[data-bot-id="' + botId + '"] .mevcut-botlar-status').forEach(function (el) {
            setTextIfChanged(el, statusMeta.text);
            var statusCls = 'mevcut-botlar-status ' + statusMeta.className;
            if (el.className !== statusCls) el.className = statusCls;
        });
    });
}

async function pollFinanceBotsLiveEquity() {
    if (document.hidden || !State.accountId || !window.apiClient || !State.bots || !State.bots.length) {
        _financeBotsLiveHydrated = true;
        return;
    }
    var q = State.accountCode
        ? '?account_code=' + encodeURIComponent(State.accountCode)
        : '?account_id=' + encodeURIComponent(State.accountId);
    if (!State.botLiveEquity) State.botLiveEquity = {};
    var jobs = [];
    State.bots.forEach(function (bot) {
        if (!botNeedsLiveEquity(bot)) return;
        var botId = bot.bot_id || bot.id;
        if (!botId) return;
        jobs.push(
            window.apiClient.get('/api/bots-engine/' + botId + '/live' + q)
                .then(function (live) {
                    if (!live || typeof live !== 'object') return;
                    if (live.equity == null || isNaN(live.equity)) return;
                    State.botLiveEquity[String(botId)] = {
                        equity: Number(live.equity),
                        equity_unavailable: !!live.equity_unavailable,
                        first_buy_pending: live.first_buy_pending === true,
                        base_balance: live.base_balance != null ? Number(live.base_balance) : null,
                        ts: Date.now()
                    };
                })
                .catch(function () {})
        );
    });
    if (!jobs.length) {
        _financeBotsLiveHydrated = true;
        return;
    }
    await Promise.all(jobs);
    _financeBotsLiveHydrated = true;
    applyFinanceBotsLiveEquityToDom();
    persistFinanceBotsSessionCache(State.bots);
}

function ensureFinanceBotsLiveEquity() {
    if (_financeBotsLiveHydrated) return Promise.resolve();
    if (_financeBotsLivePollPromise) return _financeBotsLivePollPromise;
    _financeBotsLivePollPromise = pollFinanceBotsLiveEquity().finally(function () {
        _financeBotsLivePollPromise = null;
    });
    return _financeBotsLivePollPromise;
}

function resolveBotCycles(bot) {
    var cid = bot.cycle_id;
    if (cid != null && Number.isFinite(Number(cid)) && Number(cid) > 0) return Number(cid);
    var tc = bot.total_cycles_completed;
    if (tc != null && Number.isFinite(tc) && tc > 0) return tc;
    return 0;
}

function financeBotsStructureSignature(bots, sortBy) {
    return (bots || []).map(function (b) {
        return [
            b.bot_id || b.id,
            (b.status || '').toLowerCase(),
            b.display_status || '',
            (b.symbol || '').toUpperCase(),
            b.initial_allocation_done ? 1 : 0
        ].join(':');
    }).join('|') + '|' + (sortBy || 'pct');
}

function patchFinanceBotsMetrics(bots) {
    if (!bots || !bots.length) return;
    State.bots = hydrateBotsWithMetricsCache(bots);
    applyFinanceBotsLiveEquityToDom();
    persistFinanceBotsSessionCache(State.bots);
}

function renderFinanceBots(bots) {
    bots = hydrateBotsWithMetricsCache(Array.isArray(bots) ? bots : []);
    const containerAnasayfa = document.getElementById('financeBotsList');
    const containerBotsTab = document.getElementById('financeBotsListBots');
    if (!containerAnasayfa && !containerBotsTab) return;

    resetFinanceBotsLiveCache(bots);
    var anyNeedsLive = Array.isArray(bots) && bots.some(botNeedsLiveEquity);
    if (!anyNeedsLive) _financeBotsLiveHydrated = true;

    var emptyHtml = '<div style="color: var(--ds-text-secondary); padding: 2rem; text-align: center;">Bot bulunamadı</div>';
    if (!bots || bots.length === 0) {
        _financeBotsStructureSignature = null;
        if (containerAnasayfa) containerAnasayfa.innerHTML = emptyHtml;
        if (containerBotsTab) containerBotsTab.innerHTML = emptyHtml;
        _bindFinanceBotsSortButtons();
        return;
    }

    var sortBy = (typeof financeBotsSortBy !== 'undefined' ? financeBotsSortBy : 'pct');
    var structureSig = financeBotsStructureSignature(bots, sortBy);
    if (_financeBotsStructureSignature === structureSig) {
        updateFinanceBotsLivePrices();
        patchFinanceBotsMetrics(bots);
        if (!_financeBotsLiveHydrated) ensureFinanceBotsLiveEquity();
        return;
    }
    _financeBotsStructureSignature = structureSig;

    const normalized = bots.map(bot => {
        const budget = bot.budget_usd || bot.initial_usd || 0;
        const totalPnl = Number(bot.total_pnl_usd ?? bot.total_pnl ?? bot.pnl_30d ?? 0);
        const pct = budget > 0 ? (totalPnl / budget * 100) : 0;
        return {
            ...bot,
            budget_usd: budget,
            initial_usd: budget,
            total_pnl_usd: totalPnl,
            total_pnl_pct: bot.total_pnl_pct ?? pct
        };
    });
    const sorted = normalized.slice().sort((a, b) => {
        if (financeBotsSortBy === 'usd') return (b.total_pnl_usd || 0) - (a.total_pnl_usd || 0);
        return (b.total_pnl_pct || 0) - (a.total_pnl_pct || 0);
    });
    var getLogoHtml = function (base) {
        var sz = 36;
        if (!base || typeof getCoinLogoUrl !== 'function') return '<span class="mevcut-bot-logo-placeholder" style="width:' + sz + 'px;height:' + sz + 'px;display:inline-block;"></span>';
        var url = getCoinLogoUrl(base);
        var initials = (base || '').substring(0, 2).toUpperCase();
        var wrapStyle = 'position:relative;width:' + sz + 'px;height:' + sz + 'px;border-radius:50%;background:var(--ds-bg-tertiary);display:inline-flex;align-items:center;justify-content:center;overflow:hidden;flex-shrink:0;';
        return url
            ? '<span class="mevcut-bot-logo-wrap" style="' + wrapStyle + '"><img decoding="async" loading="lazy" fetchpriority="low" src="' + url + '" alt="' + (base || '') + '" class="mevcut-bot-logo" style="width:100%;height:100%;object-fit:cover;" onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'inline-flex\'" /><span class="mevcut-bot-logo-initials" style="display:none;position:absolute;width:' + sz + 'px;height:' + sz + 'px;border-radius:50%;align-items:center;justify-content:center;font-size:0.8rem;font-weight:600;background:var(--ds-bg-tertiary);color:var(--ds-text-secondary);">' + initials + '</span></span>'
            : '<span class="mevcut-bot-logo-initials" style="width:' + sz + 'px;height:' + sz + 'px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-size:0.8rem;font-weight:600;background:var(--ds-bg-tertiary);color:var(--ds-text-secondary);">' + initials + '</span>';
    };
    var getBotConfig = function (bot) {
        var c = bot.config || {};
        if (Object.keys(c).length === 0 && bot.config_json) {
            try { c = typeof bot.config_json === 'string' ? JSON.parse(bot.config_json) : (bot.config_json || {}); } catch (e) {}
        }
        return c;
    };
    var getMultiBotCoins = function (bot) {
        var cfg = getBotConfig(bot);
        var coins = [];
        var quoteKey = (cfg.quote_asset || 'USDT').toUpperCase();
        if (cfg.strategy_id === 'trdca_pro') {
            if (cfg.trb && cfg.trb.target_weights_all) {
                Object.keys(cfg.trb.target_weights_all).forEach(function (k) {
                    var s = (k || '').toUpperCase().replace(/USDT$|FDUSD$|BUSD$/i, '').trim();
                    if (s && s !== quoteKey && s !== 'USDT' && coins.indexOf(s) < 0) coins.push(s);
                });
            }
            if (coins.length === 0 && cfg.dca && cfg.dca.coin_weights) {
                Object.keys(cfg.dca.coin_weights).forEach(function (k) {
                    var s = (k || '').toUpperCase().replace(/USDT$|FDUSD$|BUSD$/i, '').trim();
                    if (s && s !== quoteKey && s !== 'USDT' && coins.indexOf(s) < 0) coins.push(s);
                });
            }
        } else if (cfg.strategy_id === 'multi_asset_rebalance') {
            if (Array.isArray(cfg.assets)) {
                cfg.assets.forEach(function (a) {
                    var s = (a.symbol || '').toUpperCase().replace(/USDT$|FDUSD$|BUSD$/i, '');
                    if (s && s !== 'USDT' && coins.indexOf(s) < 0) coins.push(s);
                });
            }
            if (coins.length === 0 && cfg.trb && cfg.trb.target_weights_all) {
                Object.keys(cfg.trb.target_weights_all).forEach(function (k) {
                    var s = (k || '').toUpperCase().replace(/USDT$|FDUSD$|BUSD$/i, '');
                    if (s && s !== 'USDT' && coins.indexOf(s) < 0) coins.push(s);
                });
            }
        }
        if (coins.length === 0 && cfg.strategy_id !== 'trdca_pro' && (cfg.dca && cfg.dca.coin_weights)) {
            Object.keys(cfg.dca.coin_weights).forEach(function (k) {
                var s = (k || '').toUpperCase();
                if (s && s !== 'USDT' && coins.indexOf(s) < 0) coins.push(s);
            });
        }
        return coins.slice(0, 6);
    };
    var getMultiLogoHtml = function (coins) {
        if (!coins || coins.length === 0 || typeof getCoinLogoUrl !== 'function') return getLogoHtml('MU');
        var size = Math.min(28, Math.floor(100 / coins.length));
        var overlap = coins.length > 2 ? -Math.floor(size * 0.4) : 0;
        return '<span class="mevcut-bot-multi-logos" style="display:inline-flex;align-items:center;">' + coins.map(function (c, i) {
            var url = getCoinLogoUrl(c);
            var initials = (c || '').substring(0, 2).toUpperCase();
            var style = 'width:' + size + 'px;height:' + size + 'px;border-radius:50%;object-fit:cover;border:2px solid var(--ds-bg-panel);margin-left:' + (i === 0 ? 0 : overlap) + 'px;';
            var fs = size >= 24 ? '0.65rem' : '0.55rem';
            var wrapStyle = 'width:' + size + 'px;height:' + size + 'px;border-radius:50%;background:var(--ds-bg-tertiary);display:inline-flex;align-items:center;justify-content:center;overflow:hidden;flex-shrink:0;margin-left:' + (i === 0 ? 0 : overlap) + 'px;';
        return url
                ? '<span class="mevcut-bot-logo-wrap" style="' + wrapStyle + '"><img decoding="async" src="' + url + '" alt="' + c + '" class="mevcut-bot-logo" style="width:100%;height:100%;object-fit:cover;" onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'inline-flex\'" /><span class="mevcut-bot-logo-initials" style="display:none;position:absolute;' + style + 'align-items:center;justify-content:center;font-size:' + fs + ';font-weight:600;background:var(--ds-bg-tertiary);color:var(--ds-text-secondary);">' + initials + '</span></span>'
                : '<span class="mevcut-bot-logo-initials" style="' + style + 'display:inline-flex;align-items:center;justify-content:center;font-size:' + fs + ';font-weight:600;background:var(--ds-bg-tertiary);color:var(--ds-text-secondary);">' + initials + '</span>';
        }).join('') + '</span>';
    };
    var getLivePrice = function (sym) {
        var mini = window.marketStore && window.marketStore.getMini(sym);
        var p = (mini && mini.last != null) ? mini.last : (window.marketStore && window.marketStore.getPrice && window.marketStore.getPrice(sym));
        return (p != null && Number.isFinite(p)) ? p : null;
    };
    const thead = '<thead><tr><th style="text-align:left">Sembol</th><th style="text-align:right">FİYAT</th><th style="text-align:center">Durum</th><th style="text-align:right">Bütçe</th><th style="text-align:right">Bot Bakiyesi</th><th style="text-align:right">Toplam K/Z</th><th style="text-align:center">Tur</th><th style="text-align:center">İşlem</th></tr></thead>';
    const rows = sorted.map(bot => {
        const botId = bot.bot_id || bot.id;
        const sym = (bot.symbol || 'N/A').toUpperCase();
        const cfg = getBotConfig(bot);
        const isMulti = sym === 'MULTI' || cfg.strategy_id === 'multi_asset_rebalance' || cfg.strategy_id === 'trdca_pro';
        const detailPage = isMulti ? '/ui/bot_multi.html' : '/ui/bot.html';
        const base = parseBaseQuote(sym).base || sym.replace(/USDT|FDUSD|BUSD$/i, '') || sym;
        const multiCoins = isMulti ? getMultiBotCoins(bot) : [];
        const logoHtml = isMulti && multiCoins.length > 0 ? getMultiLogoHtml(multiCoins) : getLogoHtml(base);
        const q = State.accountCode ? 'account_code=' + encodeURIComponent(State.accountCode) : 'account_id=' + (State.accountId || '');
        const href = detailPage + '?bot_id=' + botId + '&' + q;
        const statusMeta = getFinanceBotStatusMeta(bot);
        const currentUsd = resolveBotCurrentUsd(bot);
        const balanceDisplay = currentUsd != null ? fmtUsd(currentUsd) : '—';
        const cyclesDisplay = resolveBotCyclesDisplay(bot);
        const budgetUsd = Number(bot.budget_usd || bot.initial_usd) || 0;
        const rowPnl = resolveBotRowPnl(bot, currentUsd);
        const sc = rowPnl != null && rowPnl >= 0 ? '#0ecb81' : (rowPnl != null ? '#f6465d' : 'var(--ds-text-secondary)');
        var symbolCell = isMulti && multiCoins.length > 0
            ? '<a href="' + href + '" style="color:inherit;text-decoration:none;display:inline-flex;align-items:center;gap:6px">' + getMultiLogoHtml(multiCoins) + '</a>'
            : '<a href="' + href + '" style="color:inherit;text-decoration:none;display:inline-flex;align-items:center;gap:6px">' + logoHtml + (bot.symbol || 'N/A') + '</a>';
        var livePrice = isMulti ? null : getLivePrice(sym);
        var priceCell = isMulti
            ? '<span class="mevcut-bot-portfolio-balance" title="Çoklu sembol">—</span>'
            : '<span class="finance-bot-live-price mevcut-bot-portfolio-balance" data-symbol="' + sym + '" data-bot-id="' + botId + '" title="Sembol canlı fiyatı">' + (livePrice != null ? fmtUsd(livePrice) : '—') + '</span>';
        return '<tr style="cursor:pointer" data-bot-id="' + botId + '" data-symbol="' + sym + '" data-detail-page="' + detailPage + '">' +
            '<td style="font-weight:600">' + symbolCell + '</td>' +
            '<td class="mevcut-botlar-price-cell" style="text-align:right">' + priceCell + '</td>' +
            '<td style="text-align:center"><span class="mevcut-botlar-status ' + statusMeta.className + '">' + statusMeta.text + '</span></td>' +
            '<td style="text-align:right">' + fmtUsd(bot.budget_usd || 0) + '</td>' +
            '<td class="mevcut-botlar-balance-cell finance-bot-balance' + (balanceDisplay === '—' ? ' finance-bot-metric-pending' : '') + '" style="text-align:right" data-bot-id="' + botId + '" data-balance="' + (currentUsd != null ? currentUsd : '') + '" title="Bot bakiyesi (bot detay /live equity ile aynı)">' + balanceDisplay + '</td>' +
            '<td style="text-align:right;color:' + sc + '">' + fmtSignedUsdOrDash(rowPnl) + '</td>' +
            '<td style="text-align:center">' + cyclesDisplay + '</td>' +
            '<td style="text-align:center"><a href="' + href + '" class="mevcut-botlar-detay-btn">Detay</a></td></tr>';
    }).join('');
    var tableHtml = '<div class="mevcut-botlar-table-wrap" style="overflow-x: auto; width: 100%;"><table class="binance-assets-table mevcut-botlar-table" style="width: 100%;">' + thead + '<tbody>' + rows + '</tbody></table></div>';

    var mobileCardsHtml = sorted.map(bot => {
        const botId = bot.bot_id || bot.id;
        const sym = (bot.symbol || 'N/A').toUpperCase();
        const cfg = getBotConfig(bot);
        const isMulti = sym === 'MULTI' || cfg.strategy_id === 'multi_asset_rebalance' || cfg.strategy_id === 'trdca_pro';
        const detailPage = isMulti ? '/ui/bot_multi.html' : '/ui/bot.html';
        const base = parseBaseQuote(sym).base || sym.replace(/USDT|FDUSD|BUSD$/i, '') || sym;
        const multiCoins = isMulti ? getMultiBotCoins(bot) : [];
        const logoHtml = isMulti && multiCoins.length > 0 ? getMultiLogoHtml(multiCoins) : getLogoHtml(base);
        const q = State.accountCode ? 'account_code=' + encodeURIComponent(State.accountCode) : 'account_id=' + (State.accountId || '');
        const href = detailPage + '?bot_id=' + botId + '&' + q;
        const statusMeta = getFinanceBotStatusMeta(bot);
        const currentUsd = resolveBotCurrentUsd(bot);
        const balanceDisplay = currentUsd != null ? fmtUsd(currentUsd) : '—';
        const cyclesDisplay = resolveBotCyclesDisplay(bot);
        const budgetUsd = Number(bot.budget_usd || bot.initial_usd) || 0;
        const rowPnl = resolveBotRowPnl(bot, currentUsd);
        const sc = rowPnl != null && rowPnl >= 0 ? '#0ecb81' : (rowPnl != null ? '#f6465d' : 'var(--ds-text-secondary)');
        // Mobil: tek sembolde FİYAT = canlı sembol fiyatı; çoklu botta —
        var mobilePriceDisplay = isMulti ? '—' : (getLivePrice(sym) != null ? fmtUsd(getLivePrice(sym)) : '—');
        var mobilePriceSpan = isMulti
            ? '<span class="mevcut-botlar-mobile-price" title="Çoklu sembol">—</span>'
            : '<span class="finance-bot-live-price mevcut-botlar-mobile-price" data-symbol="' + sym + '" data-bot-id="' + botId + '" title="Sembol canlı fiyatı">' + mobilePriceDisplay + '</span>';
        return '<div class="mevcut-botlar-mobile-card" data-bot-id="' + botId + '" data-symbol="' + sym + '" data-detail-page="' + detailPage + '">' +
            '<div class="mevcut-botlar-mobile-top">' +
            logoHtml +
            '<a href="' + href + '" class="mevcut-botlar-mobile-symbol">' + (isMulti && multiCoins.length > 0 ? getMultiLogoHtml(multiCoins) : (bot.symbol || 'N/A')) + '</a>' +
            mobilePriceSpan +
            '</div>' +
            '<div class="mevcut-botlar-mobile-stats">' +
            '<div class="mevcut-botlar-mobile-stat"><span class="mevcut-botlar-mobile-stat-label">Durum</span><span class="mevcut-botlar-status ' + statusMeta.className + '">' + statusMeta.text + '</span></div>' +
            '<div class="mevcut-botlar-mobile-stat"><span class="mevcut-botlar-mobile-stat-label">Bütçe</span><span class="mevcut-botlar-mobile-stat-value">' + fmtUsd(bot.budget_usd || 0) + '</span></div>' +
            '<div class="mevcut-botlar-mobile-stat"><span class="mevcut-botlar-mobile-stat-label">Bakiye</span><span class="mevcut-botlar-mobile-stat-value">' + balanceDisplay + '</span></div>' +
            '<div class="mevcut-botlar-mobile-stat"><span class="mevcut-botlar-mobile-stat-label">K/Z</span><span class="mevcut-botlar-mobile-stat-value mevcut-botlar-mobile-pnl" style="color:' + sc + '">' + fmtSignedUsdOrDash(rowPnl) + '</span></div>' +
            '<div class="mevcut-botlar-mobile-stat"><span class="mevcut-botlar-mobile-stat-label">Tur</span><span class="mevcut-botlar-mobile-stat-value">' + cyclesDisplay + '</span></div>' +
            '</div>' +
            '<a href="' + href + '" class="mevcut-botlar-detay-btn mevcut-botlar-mobile-detay">Detay</a>' +
            '</div>';
    }).join('');
    var mobileWrapHtml = '<div class="mevcut-botlar-mobile">' + mobileCardsHtml + '</div>';

    function bindRowClicks(container) {
        if (!container) return;
        container.querySelectorAll('a.mevcut-botlar-detay-btn').forEach(function(a) {
            a.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                var href = this.getAttribute('href');
                if (href) location.href = href;
            });
        });
        container.querySelectorAll('tbody tr').forEach(tr => {
            tr.addEventListener('click', function(e) {
                if (e.target.tagName === 'A' || e.target.closest('a')) return;
                const botId = tr.dataset.botId;
                const page = tr.dataset.detailPage || '/ui/bot.html';
                const q = State.accountCode ? 'account_code=' + encodeURIComponent(State.accountCode) : 'account_id=' + State.accountId;
                location.href = page + '?bot_id=' + botId + '&' + q;
            });
        });
        container.querySelectorAll('.mevcut-botlar-mobile-card').forEach(card => {
            card.addEventListener('click', function(e) {
                if (e.target.tagName === 'A' || e.target.closest('a')) return;
                const botId = card.dataset.botId;
                const page = card.dataset.detailPage || '/ui/bot.html';
                const q = State.accountCode ? 'account_code=' + encodeURIComponent(State.accountCode) : 'account_id=' + State.accountId;
                location.href = page + '?bot_id=' + botId + '&' + q;
            });
        });
    }
    var fullHtml = tableHtml + mobileWrapHtml;
    if (containerAnasayfa) { containerAnasayfa.innerHTML = fullHtml; bindRowClicks(containerAnasayfa); }
    if (containerBotsTab) { containerBotsTab.innerHTML = fullHtml; bindRowClicks(containerBotsTab); }
    _bindFinanceBotsSortButtons();
    updateFinanceBotsLivePrices();
    ensureFinanceBotsLiveEquity();
    persistFinanceBotsSessionCache(sorted);
}

var financeBotLastPrices = {};
function updateFinanceBotsLivePrices() {
    document.querySelectorAll('.finance-bot-live-price').forEach(function (span) {
        var sym = span.getAttribute('data-symbol');
        var botId = span.getAttribute('data-bot-id');
        if (!sym || !botId) return;
        var price = resolveBotLivePrice(sym);
        if (price == null) return;
        var newText = fmtUsd(price);
        var prev = financeBotLastPrices[botId];
        if (span.textContent !== newText) {
            if (prev != null && Number.isFinite(prev) && Math.abs(price - prev) > 1e-10) {
                var cell = span.closest('.mevcut-botlar-price-cell') || span;
                [span, cell].forEach(function (el) {
                    el.classList.remove('blink-positive', 'blink-negative');
                });
                void span.offsetWidth;
                var blinkClass = price > prev ? 'blink-positive' : 'blink-negative';
                span.classList.add(blinkClass);
                if (cell !== span) cell.classList.add(blinkClass);
                setTimeout(function () {
                    [span, cell].forEach(function (el) {
                        el.classList.remove('blink-positive', 'blink-negative');
                    });
                }, 750);
            }
            span.textContent = newText;
        }
        financeBotLastPrices[botId] = price;
    });
}
function _bindFinanceBotsSortButtons() {
    var handler = function () { setFinanceBotsSortBy(financeBotsSortBy === 'pct' ? 'usd' : 'pct'); renderFinanceBots(State.bots || []); };
    var btn = document.getElementById('btnSortBotsBy');
    if (btn && !btn._boundFinanceBots) { btn._boundFinanceBots = true; btn.addEventListener('click', handler); }
    var btnTab = document.getElementById('btnSortBotsByBotsTab');
    if (btnTab && !btnTab._boundFinanceBots) { btnTab._boundFinanceBots = true; btnTab.addEventListener('click', handler); }
}

async function loadEquityCurve(range) {
    if (!State.accountId) return;
    
    financeReportsState.equityCurveRange = range;
    
    try {
        // REFACTOR: Use financeService instead of direct fetch
        if (window.financeService) {
            const data = await window.financeService.getEquityCurve(State.accountId, range);
            // Data is already in financeStore, just render
            renderEquityCurve(data.data || []);
            return;
        }
        
        // Fallback: Use apiClient
        const data = await window.apiClient.get(`/api/finance/equity-curve?account_id=${State.accountId}&range=${range}&cb=${Date.now()}`);
        renderEquityCurve(data.data || []);
        
    } catch (error) {
        console.error("[reports] Error loading equity curve:", error);
        if (window.errorReporter) {
            window.errorReporter.report(error, { tab: 'reports', account_id: State.accountId, action: 'loadEquityCurve' });
        }
        const chartEl = document.getElementById('equityCurveChart');
        if (chartEl) {
            chartEl.innerHTML = '<div style="text-align: center; padding: 2rem; color: var(--ds-danger);">Grafik yüklenemedi</div>';
        }
    }
}

function renderEquityCurve(data) {
    const chartEl = document.getElementById('equityCurveChart');
    if (!chartEl) return;
    
    if (data.length === 0) {
        chartEl.innerHTML = '<div style="text-align: center; padding: 2rem; color: var(--ds-text-secondary);">Veri yok</div>';
        return;
    }
    
    // Simple line chart using SVG (or use Chart.js if available)
    const maxValue = Math.max(...data.map(d => d.total_usd_value));
    const minValue = Math.min(...data.map(d => d.total_usd_value));
    const range = maxValue - minValue || 1;
    const width = 800;
    const height = 250;
    const padding = 40;
    
    const points = data.map((d, i) => {
        const x = padding + (i / (data.length - 1 || 1)) * (width - 2 * padding);
        const y = padding + (1 - (d.total_usd_value - minValue) / range) * (height - 2 * padding);
        return {x, y, value: d.total_usd_value, time: d.timestamp};
    });
    
    const pathData = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ');
    
    chartEl.innerHTML = `
        <svg width="${width}" height="${height}" style="width: 100%; height: 100%;">
            <defs>
                <linearGradient id="equityGradient" x1="0%" y1="0%" x2="0%" y2="100%">
                    <stop offset="0%" style="stop-color:#0ecb81;stop-opacity:0.3" />
                    <stop offset="100%" style="stop-color:#0ecb81;stop-opacity:0" />
                </linearGradient>
            </defs>
            <path d="${pathData} Z" fill="url(#equityGradient)" stroke="#0ecb81" stroke-width="2"/>
            <text x="${width / 2}" y="${height - 10}" text-anchor="middle" fill="var(--ds-text-secondary)" font-size="12">${fmtUsd(minValue)} - ${fmtUsd(maxValue)}</text>
        </svg>
    `;
}

async function loadFinanceReport() {
    if (!State.accountId) return;
    
    const period = document.getElementById('reportPeriod')?.value || 'weekly';
    
    try {
        const response = await fetch(`/api/finance/report?account_id=${State.accountId}&period=${period}&cb=${Date.now()}`);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        
        const data = await response.json();
        renderFinanceReport(data);
        
    } catch (error) {
        console.error("[reports] Error loading finance report:", error);
    }
}

function renderFinanceReport(data) {
    const container = document.getElementById('financeReportContent');
    if (!container) return;
    
    container.innerHTML = `
        <div style="margin-bottom: 1.5rem;">
            <h3 style="margin: 0 0 1rem 0; font-size: 1.2rem; font-weight: 600; color: var(--ds-text-primary);">Rapor: ${data.period}</h3>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 1.5rem;">
                <div class="panel" style="padding: 1rem;">
                    <div style="font-size: 0.85rem; color: var(--ds-text-secondary); margin-bottom: 0.5rem;">Realized PnL</div>
                    <div style="font-size: 1.5rem; font-weight: 700; color: ${data.realized_pnl >= 0 ? '#0ecb81' : '#f6465d'};">${fmtUsd(data.realized_pnl)}</div>
                </div>
                <div class="panel" style="padding: 1rem;">
                    <div style="font-size: 0.85rem; color: var(--ds-text-secondary); margin-bottom: 0.5rem;">Ücretler</div>
                    <div style="font-size: 1.5rem; font-weight: 700; color: var(--ds-text-primary);">${fmtUsd(data.fees)}</div>
                </div>
                <div class="panel" style="padding: 1rem;">
                    <div style="font-size: 0.85rem; color: var(--ds-text-secondary); margin-bottom: 0.5rem;">Net PnL</div>
                    <div style="font-size: 1.5rem; font-weight: 700; color: ${data.net_pnl >= 0 ? '#0ecb81' : '#f6465d'};">${fmtUsd(data.net_pnl)}</div>
                </div>
                <div class="panel" style="padding: 1rem;">
                    <div style="font-size: 0.85rem; color: var(--ds-text-secondary); margin-bottom: 0.5rem;">İşlem Sayısı</div>
                    <div style="font-size: 1.5rem; font-weight: 700; color: var(--ds-text-primary);">${data.trades_count}</div>
                </div>
            </div>
            <div style="margin-bottom: 1.5rem;">
                <h4 style="margin: 0 0 1rem 0; font-size: 1rem; font-weight: 600; color: var(--ds-text-primary);">Metrikler</h4>
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 1rem;">
                    <div><strong>Win Rate:</strong> ${(data.metrics.win_rate * 100).toFixed(2)}%</div>
                    <div><strong>Profit Factor:</strong> ${data.metrics.profit_factor.toFixed(2)}</div>
                    <div><strong>Gross Profit:</strong> ${fmtUsd(data.metrics.gross_profit)}</div>
                    <div><strong>Gross Loss:</strong> ${fmtUsd(data.metrics.gross_loss)}</div>
                </div>
            </div>
            <div>
                <h4 style="margin: 0 0 1rem 0; font-size: 1rem; font-weight: 600; color: var(--ds-text-primary);">Sembol Bazında</h4>
                <div style="overflow-x: auto;">
                    <table class="binance-assets-table">
                        <thead>
                            <tr>
                                <th style="text-align: left;">Sembol</th>
                                <th style="text-align: right;">PnL</th>
                                <th style="text-align: right;">Ücret</th>
                                <th style="text-align: right;">İşlem</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${Object.entries(data.by_symbol || {}).map(([symbol, d]) => `
                                <tr>
                                    <td><strong>${symbol}</strong></td>
                                    <td style="text-align: right; color: ${d.pnl >= 0 ? '#0ecb81' : '#f6465d'}; font-weight: 600;">${fmtUsd(d.pnl)}</td>
                                    <td style="text-align: right;">${fmtUsd(d.fees)}</td>
                                    <td style="text-align: right;">${d.count}</td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    `;
}

async function loadFinanceBots() {
    if (!State.accountId) return;
    
    try {
        const response = await fetch(`/api/finance/bots?account_id=${State.accountId}&cb=${Date.now()}`);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        
        const data = await response.json();
        renderFinanceBots(data.bots || []);
        
    } catch (error) {
        console.error("[reports] Error loading finance bots:", error);
    }
}

async function loadFinanceBotDetail(botId) {
    const q = State.accountCode ? 'account_code=' + encodeURIComponent(State.accountCode) : 'account_id=' + (State.accountId || '');
    location.href = '/ui/bot.html?bot_id=' + botId + '&' + q;
}

// Finance trades period state
let financeTradesPeriod = 'daily'; // daily, weekly, monthly, yearly, all
let financeTradesTypeFilter = 'all'; // all | buysell | depositwithdraw
let _financeTradesSyncedOnce = false; // sync=1 on first load for fresh Binance data

/** Türkiye saatine göre dönem aralığı (start/end UTC ISO). Günlük = bugün 00:00 TR → şimdi, vb. */
function getTurkeyDateRange(period) {
    const now = new Date();
    const trDateStr = now.toLocaleDateString('en-CA', { timeZone: 'Europe/Istanbul' });
    const [y, m, d] = trDateStr.split('-').map(Number);
    const turkeyMidnightUTC = new Date(Date.UTC(y, m - 1, d) - 3 * 60 * 60 * 1000);
    const endISO = now.toISOString();
    switch (period) {
        case 'daily':
            return { startISO: turkeyMidnightUTC.toISOString(), endISO };
        case 'weekly':
            const weekStart = new Date(turkeyMidnightUTC.getTime() - 7 * 24 * 60 * 60 * 1000);
            return { startISO: weekStart.toISOString(), endISO };
        case 'monthly':
            const monthStart = new Date(turkeyMidnightUTC.getTime() - 30 * 24 * 60 * 60 * 1000);
            return { startISO: monthStart.toISOString(), endISO };
        case 'yearly':
            const yearStart = new Date(turkeyMidnightUTC.getTime() - 365 * 24 * 60 * 60 * 1000);
            return { startISO: yearStart.toISOString(), endISO };
        default:
            return {};
    }
}

/** UTC ISO string veya Date → Türkiye saati metni (Tarih + Saat). */
function formatTurkeyDateTime(isoOrDate) {
    const d = typeof isoOrDate === 'string' ? new Date(isoOrDate.endsWith('Z') ? isoOrDate : isoOrDate + 'Z') : isoOrDate;
    const dateStr = d.toLocaleDateString('tr-TR', { timeZone: 'Europe/Istanbul', day: '2-digit', month: '2-digit' });
    const timeStr = d.toLocaleTimeString('tr-TR', { timeZone: 'Europe/Istanbul', hour: '2-digit', minute: '2-digit' });
    return { dateStr, timeStr };
}

// Finance period state (for PnL and fees display)
let financePeriod = 'daily'; // daily, weekly, monthly, yearly, all

function setFinancePeriod(period) {
    financePeriod = period;
    
    // Update button styles
    ['daily', 'weekly', 'monthly', 'yearly', 'all'].forEach(p => {
        const btn = document.getElementById(`financePeriod${p.charAt(0).toUpperCase() + p.slice(1)}`);
        if (btn) {
            if (p === period) {
                btn.style.background = 'var(--ds-accent-dark, #c9930a)';
                btn.style.color = '#000';
                btn.style.fontWeight = '600';
            } else {
                btn.style.background = '';
                btn.style.color = '';
                btn.style.fontWeight = '';
            }
        }
    });
    
    // Load period data
    loadFinancePeriodData();
}

async function loadFinancePeriodData() {
    if (!State.accountId) return;
    
    try {
        // Calculate date range based on period (UTC standardize)
        let startDate = '';
        let endDate = '';
        const now = new Date();
        const nowUTC = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), now.getUTCHours(), now.getUTCMinutes(), now.getUTCSeconds()));
        
        switch (financePeriod) {
            case 'daily':
                const todayStart = new Date(Date.UTC(nowUTC.getUTCFullYear(), nowUTC.getUTCMonth(), nowUTC.getUTCDate(), 0, 0, 0));
                startDate = todayStart.toISOString();
                endDate = nowUTC.toISOString();
                break;
            case 'weekly':
                const weekAgo = new Date(nowUTC);
                weekAgo.setUTCDate(nowUTC.getUTCDate() - 7);
                startDate = weekAgo.toISOString();
                endDate = nowUTC.toISOString();
                break;
            case 'monthly':
                const monthAgo = new Date(nowUTC);
                monthAgo.setUTCDate(nowUTC.getUTCDate() - 30);
                startDate = monthAgo.toISOString();
                endDate = nowUTC.toISOString();
                break;
            case 'yearly':
                const yearAgo = new Date(nowUTC);
                yearAgo.setUTCFullYear(nowUTC.getUTCFullYear() - 1);
                startDate = yearAgo.toISOString();
                endDate = nowUTC.toISOString();
                break;
            case 'all':
                // No date filter - use report endpoint with default period
                break;
        }
        
        // Call finance report endpoint
        let url = `/api/finance/report?account_id=${State.accountId}`;
        if (financePeriod === 'all') {
            // For "all", use a very old start date (e.g., 10 years ago)
            const allTimeStart = new Date(nowUTC);
            allTimeStart.setUTCFullYear(nowUTC.getUTCFullYear() - 10);
            url += `&start=${allTimeStart.toISOString()}&end=${endDate || nowUTC.toISOString()}`;
        } else if (startDate && endDate) {
            url += `&start=${startDate}&end=${endDate}`;
        } else {
            // Map period to report period
            const periodMap = {
                'daily': 'weekly', // Use weekly as base for daily
                'weekly': 'weekly',
                'monthly': 'monthly',
                'yearly': 'monthly' // Use monthly as base for yearly
            };
            url += `&period=${periodMap[financePeriod] || 'weekly'}`;
        }
        url += `&cb=${Date.now()}`;
        
        const data = await window.apiClient.get(url);
        
        // Update PnL display
        const pnlEl = document.getElementById('financePeriodPnl');
        if (pnlEl) {
            const pnl = data.realized_pnl || 0;
            pnlEl.textContent = fmtUsd(pnl);
            pnlEl.style.color = pnl >= 0 ? '#0ecb81' : '#f6465d';
        }
        
        const pnlPctEl = document.getElementById('financePeriodPnlPct');
        if (pnlPctEl) {
            // Calculate percentage based on initial value (if available)
            // For now, just show the value
            const pnl = data.realized_pnl || 0;
            // Try to get initial value from summary
            try {
                const summaryData = await window.apiClient.get(`/api/finance/summary?account_id=${State.accountId}&cb=${Date.now()}`);
                const initialValue = summaryData.initial_value || 1;
                const pct = initialValue > 0 ? ((pnl / initialValue) * 100).toFixed(2) : '0.00';
                pnlPctEl.textContent = `${pct >= 0 ? '+' : ''}${pct}%`;
                pnlPctEl.style.color = pct >= 0 ? '#0ecb81' : '#f6465d';
            } catch (e) {
                pnlPctEl.textContent = '-';
            }
        }
        
        // Update Fees display
        const feesEl = document.getElementById('financePeriodFees');
        if (feesEl) {
            const fees = data.fees || 0;
            feesEl.textContent = fmtUsd(fees);
        }
        
        const feesInfoEl = document.getElementById('financePeriodFeesInfo');
        if (feesInfoEl) {
            const periodNames = {
                'daily': 'Günlük',
                'weekly': 'Haftalık',
                'monthly': 'Aylık',
                'yearly': 'Yıllık',
                'all': 'Genel'
            };
            feesInfoEl.textContent = periodNames[financePeriod] || 'Seçilen dönem';
        }
        
        // PnL etiketini seçilen döneme göre güncelle (Günlük PnL, Haftalık PnL, ...)
        const pnlLabelEl = document.getElementById('financePeriodPnlLabel');
        if (pnlLabelEl) {
            const periodLabels = {
                'daily': 'Günlük PnL',
                'weekly': 'Haftalık PnL',
                'monthly': 'Aylık PnL',
                'yearly': 'Yıllık PnL',
                'all': 'Genel PnL'
            };
            pnlLabelEl.textContent = periodLabels[financePeriod] || 'PnL';
        }
        
        // Bot bazında PnL ve Komisyon (alt özet)
        const listEl = document.getElementById('financeBotsPnlFeesList');
        if (listEl && data.by_bot && typeof data.by_bot === 'object') {
            const entries = Object.entries(data.by_bot);
            if (entries.length === 0) {
                listEl.innerHTML = '<div style="color: var(--ds-text-secondary);">Bu dönemde bot işlemi yok.</div>';
            } else {
                listEl.innerHTML = '<table class="binance-assets-table" style="width:100%; font-size: 0.9rem;"><thead><tr><th style="text-align:left">Bot ID</th><th style="text-align:right">PnL</th><th style="text-align:right">Komisyon</th></tr></thead><tbody>' +
                    entries.map(([botId, d]) => {
                        const pnl = d.pnl != null ? d.pnl : 0;
                        const fees = d.fees != null ? d.fees : 0;
                        const c = pnl >= 0 ? '#0ecb81' : '#f6465d';
                        return '<tr><td>Bot #' + botId + '</td><td style="text-align:right; color:' + c + '">' + fmtSignedUsd(pnl) + '</td><td style="text-align:right">' + fmtUsd(fees) + '</td></tr>';
                    }).join('') +
                    '</tbody></table>';
            }
        } else if (listEl) {
            listEl.innerHTML = '<div style="color: var(--ds-text-secondary);">Veri yok.</div>';
        }
        
    } catch (error) {
        console.error("[reports] Error loading finance period data:", error);
    }
}

// Early definition to prevent ReferenceError
window.setTradesPeriod = window.setTradesPeriod || function(period) {
    console.warn("[dashboard] setTradesPeriod called before initialization, period:", period);
};

function setTradesPeriod(period) {
    financeTradesPeriod = period;
    
    // Update button styles
    ['daily', 'weekly', 'monthly', 'yearly', 'all'].forEach(p => {
        const btn = document.getElementById(`tradesPeriod${p.charAt(0).toUpperCase() + p.slice(1)}`);
        if (btn) {
            if (p === period) {
                btn.style.background = 'var(--ds-accent-dark, #c9930a)';
                btn.style.color = '#000';
                btn.style.fontWeight = '600';
            } else {
                btn.style.background = '';
                btn.style.color = '';
                btn.style.fontWeight = '';
            }
        }
    });
    
    // Reset offset and load trades
    financeReportsState.tradesOffset = 0;
    loadFinanceTrades();
}

function setTradesTypeFilter(filter) {
    financeTradesTypeFilter = filter;
    ['all', 'buysell', 'depositwithdraw'].forEach(f => {
        const btn = document.getElementById(
            f === 'all' ? 'tradesFilterAll' : f === 'buysell' ? 'tradesFilterBuySell' : 'tradesFilterDepositWithdraw'
        );
        if (btn) {
            if (f === filter) {
                btn.style.background = 'var(--ds-accent-dark, #c9930a)';
                btn.style.color = '#000';
                btn.style.fontWeight = '600';
            } else {
                btn.style.background = '';
                btn.style.color = '';
                btn.style.fontWeight = '';
            }
        }
    });
    financeReportsState.tradesOffset = 0;
    loadFinanceTrades();
}

async function loadFinanceTrades(doSync) {
    if (!State.accountId) return;
    
    const body = document.getElementById('financeTradesBody');
    var isBackgroundRefresh = (doSync !== true && _financeTradesSyncedOnce === true);
    if (body && !isBackgroundRefresh) {
        body.innerHTML = '<tr><td colspan="9" style="text-align: center; padding: 2rem; color: var(--ds-text-secondary);">Yükleniyor...</td></tr>';
    }
    
    // Dönem aralığı Türkiye saatine göre (Günlük = bugün 00:00 TR → şimdi)
    const range = getTurkeyDateRange(financeTradesPeriod);
    const startISO = range.startISO || '';
    const endISO = range.endISO || '';
    
    let url = `/api/finance/trades?account_id=${State.accountId}&limit=${financeReportsState.tradesLimit}&offset=${financeReportsState.tradesOffset}`;
    if (startISO) url += '&start=' + encodeURIComponent(startISO);
    if (endISO) url += '&end=' + encodeURIComponent(endISO);
    if (financeTradesTypeFilter && String(financeTradesTypeFilter).toLowerCase() !== 'all') {
        url += '&type_filter=' + encodeURIComponent(String(financeTradesTypeFilter).trim().toLowerCase());
    }
    if (doSync || _financeTradesSyncedOnce === false) {
        url += '&sync=1';
        _financeTradesSyncedOnce = true;
    }
    url += `&cb=${Date.now()}`;
    
    try {
        // sync=1 Binance'ten veri cekebilir; 90s timeout (varsayilan 20s yetmeyebilir)
        const data = await window.apiClient.get(url, { timeout: 90000 });
        renderFinanceTrades(data);
        updateTradesSummaryStats(data);
        
        // Hide banner on successful load (if error was resolved)
        if (binanceApiErrorState.isError) {
            const errorAge = Date.now() - (binanceApiErrorState.lastErrorTime || 0);
            if (errorAge > 30000) {
                hideBinanceApiBanner();
            }
        }
        
    } catch (error) {
        console.error("[reports] Error loading finance trades:", error);
        
        // Check for Binance API errors and show banner
        if (error.status === 429 || error.error_code === 'HTTP_429' || error.error_code === 'BINANCE_RATE_LIMIT') {
            showBinanceApiBanner('rate_limit', error);
        } else if (error.status === 418 || error.error_code === 'HTTP_418') {
            showBinanceApiBanner('ip_banned', error);
        } else if (error.status === 502 || error.error_code === 'HTTP_502') {
            showBinanceApiBanner('bad_gateway', error);
        }
        
        if (window.errorReporter) {
            window.errorReporter.report(error, { tab: 'reports', account_id: State.accountId, action: 'loadFinanceTrades' });
            if (body) {
                const errorMsg = window.errorReporter.toUserMessage(error);
                body.innerHTML = `<tr><td colspan="9" style="text-align: center; padding: 2rem; color: var(--ds-text-error);">Hata: ${errorMsg}</td></tr>`;
            }
        } else if (body) {
            body.innerHTML = `<tr><td colspan="9" style="text-align: center; padding: 2rem; color: var(--ds-text-error);">Hata: ${error.message || 'İşlemler yüklenemedi'}</td></tr>`;
        }
    }
}

function renderFinanceTrades(data) {
    const body = document.getElementById('financeTradesBody');
    if (!body) return;
    
    if (!data.trades || data.trades.length === 0) {
        body.innerHTML = '<tr><td colspan="9" style="text-align: center; padding: 2rem; color: var(--ds-text-secondary);">İşlem bulunamadı</td></tr>';
        return;
    }
    
    // Backend now returns order-based grouped trades (1 order = 1 row)
    // Dedupe by order_id to prevent duplicates
    const ordersMap = new Map();
    
    data.trades.forEach(order => {
        const orderKey = order.order_id || order.trade_id;
        // If order already exists, replace (don't duplicate)
        ordersMap.set(orderKey, order);
    });
    
    // Convert to array and render
    const uniqueOrders = Array.from(ordersMap.values());
    
    body.innerHTML = uniqueOrders.map(order => {
        const rawTime = order.time || order.last_fill_time || order.first_fill_time;
        const { dateStr, timeStr } = formatTurkeyDateTime(rawTime);
        const typeRaw = (order.type || '').toUpperCase();
        const isDeposit = typeRaw === 'DEPOSIT' || typeRaw === 'YATIRIM';
        const isWithdraw = typeRaw === 'WITHDRAW' || typeRaw === 'CEKIM';
        const turText = isDeposit ? 'Yatırım' : isWithdraw ? 'Çekim' : (order.side === 'BUY' ? 'Alış' : 'Satış');
        const sideColor = isDeposit ? 'var(--ds-accent)' : order.side === 'BUY' ? '#0ecb81' : '#f6465d';
        const sideText = isDeposit ? '—' : (order.side === 'BUY' ? 'AL' : 'SAT');
        
        const isBotTrade = order.is_bot === true || (order.bot_id && order.bot_id > 0);
        const sourceText = isBotTrade ? 'BOT' : 'MANUEL';
        const sourceColor = isBotTrade ? '#f0b90b' : 'var(--ds-text-secondary)';
        const fillsInfo = order.fills_count > 1 ? ` (${order.fills_count} fill)` : '';
        
        return `
            <tr style="cursor: pointer;" onmouseover="this.style.backgroundColor='var(--ds-bg-hover)'" onmouseout="this.style.backgroundColor=''">
                <td style="text-align: left; font-size: 0.9rem;">
                    <div style="font-weight: 500;">${dateStr}</div>
                    <div style="color: var(--ds-text-secondary); font-size: 0.85rem;">${timeStr}</div>
                </td>
                <td style="text-align: left; font-size: 0.85rem;">${turText}</td>
                <td style="text-align: left; font-weight: 600;">${order.symbol || 'N/A'}</td>
                <td style="text-align: center;">
                    <span style="color: ${sideColor}; font-weight: 600; font-size: 0.9rem;">${sideText}</span>
                </td>
                <td style="text-align: right; font-weight: 500;">${fmtNum(order.executed_qty || order.qty || 0, 6)}${fillsInfo}</td>
                <td style="text-align: right; font-weight: 500;">${fmtCoinPrice(order.avg_price || order.price)}</td>
                <td style="text-align: right; font-weight: 600;">${fmtUsd(order.quote_qty || 0)}</td>
                <td style="text-align: right; color: var(--ds-text-secondary); font-size: 0.85rem;">
                    ${order.commission ? `${fmtNum(order.commission, 6)} ${order.commission_asset || ''}` : '-'}
                    ${order.commission_usd !== undefined ? `<div style="font-size: 0.75rem; color: var(--ds-text-tertiary); margin-top: 2px;">≈ ${fmtUsd(order.commission_usd)}</div>` : ''}
                </td>
                <td style="text-align: center;">
                    <span style="display: inline-block; padding: 2px 6px; border-radius: 3px; background: ${isBotTrade ? 'rgba(240, 185, 11, 0.1)' : 'var(--ds-bg-tertiary)'}; color: ${sourceColor}; font-size: 0.75rem; font-weight: 600;">${sourceText}</span>
                </td>
            </tr>
        `;
    }).join('');
    
    // Pagination info
    const paginationEl = document.getElementById('tradesPaginationInfo');
    if (paginationEl) {
        const total = data.total || uniqueOrders.length;
        const start = financeReportsState.tradesOffset + 1;
        const end = Math.min(financeReportsState.tradesOffset + financeReportsState.tradesLimit, total);
        paginationEl.textContent = `${start}-${end} / ${total} işlem`;
    }
}

function updateTradesSummaryStats(data) {
    if (!data || !data.trades) return;
    
    const trades = data.trades;
    const typeOf = t => ((t.type || '').toUpperCase());
    
    const buyCount = trades.filter(t => t.side === 'BUY' && typeOf(t) !== 'DEPOSIT').length;
    const sellCount = trades.filter(t => t.side === 'SELL' && typeOf(t) !== 'WITHDRAW').length;
    const depositCount = trades.filter(t => typeOf(t) === 'DEPOSIT' || typeOf(t) === 'YATIRIM').length;
    const withdrawCount = trades.filter(t => typeOf(t) === 'WITHDRAW' || typeOf(t) === 'CEKIM').length;
    
    const totalCount = buyCount + sellCount + depositCount + withdrawCount;
    
    const totalCountEl = document.getElementById('tradesTotalCount');
    if (totalCountEl) totalCountEl.textContent = String(totalCount);
    const buyCountEl = document.getElementById('tradesBuyCount');
    if (buyCountEl) buyCountEl.textContent = String(buyCount);
    const sellCountEl = document.getElementById('tradesSellCount');
    if (sellCountEl) sellCountEl.textContent = String(sellCount);
    const depositCountEl = document.getElementById('tradesDepositCount');
    if (depositCountEl) depositCountEl.textContent = String(depositCount);
    const withdrawCountEl = document.getElementById('tradesWithdrawCount');
    if (withdrawCountEl) withdrawCountEl.textContent = String(withdrawCount);
}

// DEPRECATED: resetFinanceTradesFilters removed - filters are now replaced with period selection

function exportTradesCSV() {
    // Get current trades data from table
    const body = document.getElementById('financeTradesBody');
    if (!body || body.children.length === 0) {
        if (window.Toast) window.Toast.warning('İşlem verisi yok');
        return;
    }
    
    // Build CSV
    let csv = 'Tarih,Saat,Sembol,Yön,Miktar,Fiyat,Toplam,Komisyon,Komisyon Varlık,Bot ID,Döngü\n';
    
    Array.from(body.children).forEach(row => {
        const cells = row.children;
        if (cells.length >= 10) {
            const dateTime = cells[0].textContent.trim().split('\n');
            const date = dateTime[0] || '';
            const time = dateTime[1] || '';
            const symbol = cells[1].textContent.trim();
            const side = cells[2].textContent.trim();
            const qty = cells[3].textContent.trim();
            const price = cells[4].textContent.trim().replace('$', '').replace(',', '');
            const total = cells[5].textContent.trim().replace('$', '').replace(',', '');
            const commission = cells[6].textContent.trim();
            const commissionAsset = cells[7].textContent.trim();
            const botId = cells[8].textContent.trim();
            const cycle = cells[9].textContent.trim();
            
            csv += `"${date}","${time}","${symbol}","${side}","${qty}","${price}","${total}","${commission}","${commissionAsset}","${botId}","${cycle}"\n`;
        }
    });
    
    // Download
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    const url = URL.createObjectURL(blob);
    link.setAttribute('href', url);
    link.setAttribute('download', `trades_${new Date().toISOString().split('T')[0]}.csv`);
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    
    if (window.Toast) window.Toast.success('CSV dosyası indirildi');
}

function loadFinanceTradesPrev() {
    if (financeReportsState.tradesOffset >= financeReportsState.tradesLimit) {
        financeReportsState.tradesOffset -= financeReportsState.tradesLimit;
        loadFinanceTrades();
    }
}

function loadFinanceTradesNext() {
    financeReportsState.tradesOffset += financeReportsState.tradesLimit;
    loadFinanceTrades();
}

// DEPRECATED: triggerFinanceSync removed - data now auto-updates when Finance tab is active
// Finance tab now automatically refreshes every 10 seconds when active

function exportReportCSV() {
    // TODO: Implement CSV export
    alert('CSV export yakında eklenecek');
}

// Expose global functions
window.openCreateBotModal = openCreateBotModal;
window.closeCreateBotModal = closeCreateBotModal;
window.openBotStructureModal = openBotStructureModal;
window.closeBotStructureModal = closeBotStructureModal;
window.loadEquityCurve = loadEquityCurve;
window.loadFinanceReport = loadFinanceReport;
window.loadFinanceTrades = loadFinanceTrades;
window.loadFinanceTradesPrev = loadFinanceTradesPrev;

// ============================================================
// PERFORMANCE PROFILING HELPER
// ============================================================
/**
 * Performance dump helper for debugging
 * Usage: window.__perfDump() in console
 */
window.__perfDump = function() {
    const activeIntervals = window.intervalRegistry?.getActive() || [];
    const marketStore = window.marketStore || {};
    const pricesSize = marketStore.prices?.size || 0;
    const miniSize = marketStore.mini?.size || 0;
    const lastUpdateTs = marketStore.lastUpdateTs || 0;
    const status = marketStore.status || 'unknown';
    const age = lastUpdateTs > 0 ? Date.now() - lastUpdateTs : null;
    
    // Check marketDataService status
    const marketDataServiceRunning = window.marketDataService?.isRunning() || false;
    const errorCount = window['marketDataService.errorCount'] || 0;
    
    const dump = {
        timestamp: new Date().toISOString(),
        intervals: {
            count: activeIntervals.length,
            details: activeIntervals.map(iv => ({
                key: iv.key,
                owner: iv.owner || 'none',
                ms: iv.ms
            }))
        },
        marketStore: {
            pricesCount: pricesSize,
            miniCount: miniSize,
            status: status,
            lastUpdateTs: lastUpdateTs,
            ageMs: age,
            isStale: age !== null && age > 10000
        },
        marketDataService: {
            running: marketDataServiceRunning,
            errorCount: errorCount
        },
        render: {
            coinListDataLength: coinListData?.length || 0,
            coinListFilteredLength: coinListFiltered?.length || 0
        },
        uiHealth: typeof uiHealth !== 'undefined' ? {
            render_count: uiHealth.render_count || 0,
            last_render_ok_ts: uiHealth.last_render_ok_ts || null
        } : { render_count: 0, last_render_ok_ts: null }
    };
    
    console.table(dump.intervals.details);
    console.log('Market Store:', dump.marketStore);
    console.log('Market Data Service:', dump.marketDataService);
    console.log('Render State:', dump.render);
    console.log('UI Health (Binance render):', dump.uiHealth);
    console.log('Full Dump:', dump);
    
    return dump;
};
window.loadFinanceTradesNext = loadFinanceTradesNext;
window.loadFinanceBotDetail = loadFinanceBotDetail;
// window.triggerFinanceSync removed - auto-update enabled
window.exportReportCSV = exportReportCSV;
window.setFinancePeriod = setFinancePeriod;
// Update window reference after function definition
window.setTradesPeriod = setTradesPeriod;
window.setTradesTypeFilter = setTradesTypeFilter;
window.exportTradesCSV = exportTradesCSV;

// Admin pop-up: kullanıcıya gösterilen duyuru (X ile kapatılana kadar). İlk girişte kapatılınca API key modalı gösterilir.
var _userPopupId = null;
var _userPopupWasFirstLogin = false;
async function fetchAndShowUserPopup(isFirstLogin) {
    try {
        var q = "first_login=" + (isFirstLogin ? "true" : "false");
        var res = await fetch(window.location.origin + "/api/auth/popup/active?" + q, { method: "GET", credentials: "include", cache: "no-store" });
        if (!res.ok) return false;
        var data = await res.json().catch(function () { return null; });
        var popup = data && data.popup;
        if (!popup || !popup.id) return false;
        var card = document.getElementById("userPopupCard");
        var overlay = document.getElementById("userPopupOverlay");
        var titleEl = document.getElementById("userPopupTitle");
        var msgEl = document.getElementById("userPopupMessage");
        if (!card || !overlay || !titleEl || !msgEl) return false;
        var titleKeys = { info: "Bilgi", warning: "Uyarı", success: "Duyuru", maintenance: "Bakım Duyurusu", announcement: "Genel Duyuru" };
        var title = (popup.title_key && titleKeys[popup.title_key]) ? titleKeys[popup.title_key] : (popup.title_key || "Duyuru");
        titleEl.textContent = title;
        msgEl.textContent = popup.message || "";
        card.className = "user-popup-card --" + (popup.title_key || "info");
        _userPopupId = popup.id;
        _userPopupWasFirstLogin = !!isFirstLogin;
        overlay.style.display = "flex";
        return true;
    } catch (e) { return false; }
}
function dismissUserPopup() {
    var overlay = document.getElementById("userPopupOverlay");
    var wasFirstLogin = _userPopupWasFirstLogin;
    if (overlay) overlay.style.display = "none";
    _userPopupWasFirstLogin = false;
    if (!_userPopupId) return;
    var popupId = _userPopupId;
    _userPopupId = null;
    fetch(window.location.origin + "/api/auth/popup/dismiss", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ popup_id: popupId })
    }).catch(function () {});
    if (wasFirstLogin) {
        setTimeout(function () {
            shouldShowFirstLoginModal(State.accountId, true).then(function (show) {
                if (show) {
                    var modal = document.getElementById("firstLoginModal");
                    if (modal) modal.style.display = "flex";
                }
            });
        }, 200);
    }
}
window.fetchAndShowUserPopup = fetchAndShowUserPopup;
window.dismissUserPopup = dismissUserPopup;

// Init on DOM ready
if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initDashboard);
} else {
    initDashboard();
}
