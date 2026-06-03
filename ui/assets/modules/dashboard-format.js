/**
 * dashboard-format.js
 * Saf format/utility fonksiyonları — State veya DOM bağımlılığı yok.
 * dashboard.js'ten çıkarıldı; dashboard.html'de dashboard.js'ten ÖNCE yüklenir.
 */

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
    if (n >= 1000) return '$' + n.toFixed(2);
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
/** Spot sembolü (Binance LOT_SIZE / stepSize için). */
function varlikTradingSymbol(asset) {
    var a = String(asset || '').toUpperCase();
    if (!a) return '';
    if (a === 'USDT' || a === 'BUSD' || a === 'FDUSD' || a === 'USDC') return 'USDT';
    if (/USDT$|BUSD$|FDUSD$/.test(a)) return a;
    return a + 'USDT';
}
function varlikSpotFilters(asset) {
    var sym = varlikTradingSymbol(asset);
    return (typeof SpotCache !== 'undefined' && SpotCache.getFilters && sym) ? SpotCache.getFilters(sym) : null;
}
/** Miktar büyüklüğüne göre gösterim ondalığı (cüzdan tablosu). */
function inferVarlikQtyDecimalsFromMagnitude(absQty) {
    if (!Number.isFinite(absQty) || absQty <= 0) return 2;
    if (absQty >= 10000) return 2;
    if (absQty >= 1000) return 3;
    if (absQty >= 100) return 4;
    if (absQty >= 1) return 4;
    if (absQty >= 0.01) return 6;
    if (absQty >= 0.000001) return 8;
    return 8;
}
function varlikQtyMaxDecimals(asset) {
    var a = String(asset || '').toUpperCase();
    if (a === 'USDT' || a === 'BUSD' || a === 'FDUSD' || a === 'USDC' || a === 'TUSD' || a === 'DAI') return 2;
    var f = varlikSpotFilters(asset);
    if (f && (f.stepSize != null || f.stepSizeStr)) {
        return Math.min(8, Math.max(0, getStepDecimals(f.stepSizeStr || f.stepSize)));
    }
    if (a === 'BTC') return 8;
    if (a === 'ETH') return 6;
    if (a === 'BNB') return 4;
    return 8;
}
function varlikQtyDisplayDecimals(asset, absQty) {
    return Math.min(varlikQtyMaxDecimals(asset), inferVarlikQtyDecimalsFromMagnitude(absQty));
}
function varlikQtyFallbackDecimals(asset, abs) {
    return varlikQtyDisplayDecimals(asset, abs);
}
/** Filtre yokken tipik minimum adım (işe yaramaz toz). */
function varlikQtyMinStepFallback(asset) {
    var a = String(asset || '').toUpperCase();
    if (a === 'USDT' || a === 'BUSD' || a === 'FDUSD' || a === 'USDC') return 0.01;
    if (a === 'BTC') return 1e-8;
    if (a === 'ETH') return 0.0001;
    if (a === 'BNB') return 0.001;
    return 0.0001;
}
/** Cüzdan tablosu miktarı — miktar + LOT_SIZE üst sınırı; büyük bakiyeler kısa, küçükler anlamlı ondalık. */
function fmtVarlikQty(v, asset) {
    var n = Number(v);
    if (!Number.isFinite(n)) return '—';
    if (n === 0) return '0';
    var abs = Math.abs(n);
    if (abs < 1e-12) return '0';
    var dec = varlikQtyDisplayDecimals(asset, abs);
    var rounded = parseFloat(n.toFixed(dec));
    if (!Number.isFinite(rounded)) return '—';
    if (rounded === 0 && abs > 0) {
        dec = Math.min(varlikQtyMaxDecimals(asset), dec + 2);
        rounded = parseFloat(n.toFixed(dec));
    }
    if (!Number.isFinite(rounded) || rounded === 0) return '0';
    var s = rounded.toFixed(dec);
    if (dec > 0) {
        s = s.replace(/(\.\d*?[1-9])0+$/, '$1').replace(/\.0+$/, '');
    }
    var parts = s.split('.');
    parts[0] = Number(parts[0]).toLocaleString('en-US');
    return parts.length > 1 ? parts[0] + '.' + parts[1] : parts[0];
}
function varlikAssetCellHtml(d) {
    var logoInner = (d.logoUrl
        ? '<img src="' + d.logoUrl + '" alt="' + d.asset + '" loading="lazy" onerror="if(window.registerLogo404)window.registerLogo404(this.alt);this.style.display=\'none\';this.nextElementSibling.style.display=\'flex\';" />'
        : '') +
        '<span class="varlik-logo-initials" style="' + (d.logoUrl ? 'display:none' : '') + '">' + d.initials + '</span>';
    return '<td class="varlik-asset-cell col-symbol col-left" data-label="Varlık">' +
        '<div class="varlik-asset mevcut-bot-symbol-link">' +
        '<span class="mevcut-bot-symbol-logo-slot"><div class="varlik-logo" title="' + d.asset + '">' + logoInner + '</div></span>' +
        '<span class="mevcut-bot-symbol-text varlik-asset-text"><span class="varlik-symbol">' + d.asset + '</span>' +
        '<span class="varlik-name">' + d.name + '</span></span></div></td>';
}
function varlikFiyatCellHtml(d) {
    return '<td class="varlik-fiyat-cell mevcut-botlar-price-cell col-price col-center" data-label="Fiyat">' +
        '<div class="varlik-fiyat-inline">' +
        '<span class="price-cell varlik-wallet-price" data-price="' + (d.price != null ? d.price : '') + '">' + d.priceDisplay + '</span>' +
        '<span class="change-pct varlik-change-inline" data-change-pct="' + (d.changePct != null ? d.changePct : '') + '" style="color: ' + d.changeColor + ';">' + d.changeStr + '</span>' +
        '</div></td>';
}
window.fmtUsd = fmtUsd;
window.fmtNum = fmtNum;
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
function _fmtPerfUsdt(v) {
    var n = Number(v);
    if (!Number.isFinite(n)) return '—';
    var sign = n >= 0 ? '+' : '';
    return sign + n.toFixed(2) + ' USDT';
}

function _fmtPerfUsdtPlain(v) {
    var n = Number(v);
    if (!Number.isFinite(n)) return '—';
    return n.toFixed(2) + ' USDT';
}

function _fmtPerfCoin(v, asset) {
    var n = Number(v);
    if (!Number.isFinite(n)) return '—';
    var sign = n >= 0 ? '+' : '';
    var abs = Math.abs(n);
    var txt = abs >= 1 ? abs.toFixed(4) : abs.toFixed(8);
    return sign + txt + ' ' + (asset || '');
}

function _perfColorClass(v) {
    var n = Number(v);
    if (!Number.isFinite(n) || Math.abs(n) < 1e-12) return '';
    return n >= 0 ? ' positive' : ' negative';
}

function _fmtPerfInvByBase(byBase) {
    if (!byBase || typeof byBase !== 'object') return '—';
    var keys = Object.keys(byBase);
    if (!keys.length) return '+0';
    return keys.map(function (k) {
        return _fmtPerfCoin(byBase[k], k);
    }).join(' · ');
}

function _fmtPerfDateOnly(raw) {
    if (raw == null || raw === '') return '';
    var s = String(raw).trim().replace(/\s*UTC\s*$/i, '').trim();
    var m = s.match(/^(\d{4}-\d{2}-\d{2})/);
    if (m) return m[1];
    try {
        var d = new Date(s.indexOf('T') >= 0 || s.indexOf(' ') >= 0 ? s : s + 'T12:00:00');
        if (!isNaN(d.getTime())) {
            var y = d.getFullYear();
            var mo = String(d.getMonth() + 1).padStart(2, '0');
            var da = String(d.getDate()).padStart(2, '0');
            return y + '-' + mo + '-' + da;
        }
    } catch (e) { /* ignore */ }
    return s;
}

function _clientPerfDateRange(period) {
    var p = (period || 'all').toLowerCase();
    var parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Istanbul', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date());
    var y = '', m = '', d = '';
    parts.forEach(function (pt) {
        if (pt.type === 'year') y = pt.value;
        if (pt.type === 'month') m = pt.value;
        if (pt.type === 'day') d = pt.value;
    });
    var today = y + '-' + m + '-' + d;
    if (p === 'daily' || p === 'day') return { from: today, to: today };
    if (p === 'weekly' || p === 'week') {
        var dt = new Date(today + 'T12:00:00');
        dt.setDate(dt.getDate() - 6);
        var f = dt.toISOString().slice(0, 10);
        return { from: f, to: today };
    }
    if (p === 'monthly' || p === 'month') {
        var dt2 = new Date(today + 'T12:00:00');
        dt2.setDate(dt2.getDate() - 29);
        return { from: dt2.toISOString().slice(0, 10), to: today };
    }
    var dt3 = new Date(today + 'T12:00:00');
    dt3.setDate(dt3.getDate() - 365);
    return { from: dt3.toISOString().slice(0, 10), to: today };
}

function _fmtBotPerfRange(data, forPeriod) {
    if (!data) return '';
    var from = _fmtPerfDateOnly(data.date_from);
    var to = _fmtPerfDateOnly(data.date_to);
    if (!from || !to) {
        var fallback = _clientPerfDateRange(forPeriod || (data && data.period_api) || (data && data.period));
        from = fallback.from;
        to = fallback.to;
    }
    if (from && to) {
        return 'Başlangıç: ' + from + ' · Bitiş: ' + to;
    }
    return '';
}

function _perfPeriodPrefix(period) {
    var map = { daily: 'Günlük', weekly: 'Haftalık', monthly: 'Aylık', all: 'Genel' };
    return map[(period || 'all').toLowerCase()] || 'Genel';
}

function _perfPeriodPnlLabel(period) {
    return _perfPeriodPrefix(period) + ' K/Z (komisyon hariç)';
}

function _perfPeriodFeesLabel(period) {
    return _perfPeriodPrefix(period) + ' komisyon';
}

function _botPerfDomSuffixes() {
    return ['', 'Bots'];
}
function fmtSignedUsdOrDash(v) {
    if (v == null || !Number.isFinite(Number(v))) return '—';
    return fmtSignedUsd(v);
}

function fmtSignedPct(pct) {
    if (pct == null || !Number.isFinite(Number(pct))) return '—';
    var n = Number(pct);
    return (n >= 0 ? '+' : '') + n.toFixed(2) + '%';
}

// Explicit window exports (backward compatibility)
window.isMobileView = isMobileView;
window.throttle = throttle;
window.fmtCoinPrice = fmtCoinPrice;
window.fmtSignedUsd = fmtSignedUsd;
window.fmtVarlikQty = fmtVarlikQty;
window.parseDecimal = parseDecimal;
window.parseApiErrorDetail = parseApiErrorDetail;
window.relativeTime = relativeTime;
window.translateErrorToTurkish = translateErrorToTurkish;
window.fmtSignedUsdOrDash = fmtSignedUsdOrDash;
window.fmtSignedPct = fmtSignedPct;
