/**
 * FILE: core/errorReporter.js
 * VERSION: v2
 * DATE: 2026-01-27
 * CHANGE: Last-action tracking (page, section, button) so errors log "hangi durumda"
 */

var LAST_ACTION_KEY = '__lastErrorContext';
var PAGE_ERRORS_KEY = '__pageErrors';  // { tab: [ { ts, message, detail, context }, ... ] }
var GLOBAL_ERRORS_KEY = '__globalErrors';  // [ ... ] son N hata (tüm sayfalar)

function getPageErrorsStore() {
    try {
        if (typeof window !== 'undefined' && !window[PAGE_ERRORS_KEY]) window[PAGE_ERRORS_KEY] = {};
        return window[PAGE_ERRORS_KEY] || {};
    } catch (e) { return {}; }
}
function getGlobalErrorsStore() {
    try {
        if (typeof window !== 'undefined' && !window[GLOBAL_ERRORS_KEY]) window[GLOBAL_ERRORS_KEY] = [];
        return window[GLOBAL_ERRORS_KEY] || [];
    } catch (e) { return []; }
}
var MAX_PAGE_ERRORS = 50;
var MAX_GLOBAL_ERRORS = 200;

function pushPageError(tab, entry) {
    var store = getPageErrorsStore();
    var key = tab || 'default';
    if (!store[key]) store[key] = [];
    store[key].unshift(entry);
    if (store[key].length > MAX_PAGE_ERRORS) store[key] = store[key].slice(0, MAX_PAGE_ERRORS);
    var global = getGlobalErrorsStore();
    global.unshift(entry);
    if (global.length > MAX_GLOBAL_ERRORS) global.length = MAX_GLOBAL_ERRORS;
}
function getPageErrors(tab) {
    var store = getPageErrorsStore();
    return (store[tab || 'default'] || []).slice();
}
function clearPageErrors(tab) {
    var store = getPageErrorsStore();
    if (tab != null && tab !== '') store[tab] = []; else Object.keys(store).forEach(function(k) { store[k] = []; });
}
function getAllPageErrors() {
    var store = getPageErrorsStore();
    var out = [];
    Object.keys(store).forEach(function(k) { out = out.concat(store[k] || []); });
    out.sort(function(a, b) { return (b.ts || 0) - (a.ts || 0); });
    return out.slice(0, MAX_GLOBAL_ERRORS);
}
function clearAllPageErrors() {
    clearPageErrors(null);
    try { if (window[GLOBAL_ERRORS_KEY]) window[GLOBAL_ERRORS_KEY].length = 0; } catch (e) {}
}

/**
 * Son kullanıcı aksiyonunu kaydet (hata anında "hangi buton, hangi sayfa" görünsün).
 * Örnek: setLastAction({ page: 'Admin', section: 'Ayarlar', button: 'Hatalar', action: 'loadErrorLogs' })
 */
function setLastAction(context) {
    try {
        if (typeof window !== 'undefined' && context && typeof context === 'object') {
            window[LAST_ACTION_KEY] = {
                page: context.page || null,
                section: context.section || null,
                button: context.button || null,
                action: context.action || null,
                tab: context.tab || null,
                symbol: context.symbol || null,
                bot_id: context.bot_id != null ? context.bot_id : null,
                account_id: context.account_id != null ? context.account_id : null,
                timestamp: new Date().toISOString()
            };
        }
    } catch (e) {}
}

function getLastAction() {
    try {
        return (typeof window !== 'undefined' && window[LAST_ACTION_KEY]) || null;
    } catch (e) {
        return null;
    }
}

/** Birleştir: verilen context öncelikli, yoksa son aksiyondan doldur */
function mergeContext(context) {
    var last = getLastAction();
    var base = (last && typeof last === 'object') ? {
        page: last.page,
        section: last.section,
        button: last.button,
        action: last.action,
        tab: last.tab,
        symbol: last.symbol,
        bot_id: last.bot_id,
        account_id: last.account_id
    } : {};
    if (context && typeof context === 'object') {
        if (context.page != null) base.page = context.page;
        if (context.section != null) base.section = context.section;
        if (context.button != null) base.button = context.button;
        if (context.action != null) base.action = context.action;
        if (context.tab != null) base.tab = context.tab;
        if (context.symbol != null) base.symbol = context.symbol;
        if (context.bot_id != null) base.bot_id = context.bot_id;
        if (context.account_id != null) base.account_id = context.account_id;
    }
    return base;
}

/**
 * Send error to backend for admin error logs (fire-and-forget, no throw)
 */
function sendErrorToBackend(errorInfo, context) {
        try {
            var ctx = mergeContext(context && typeof context === 'object' ? context : {});
            var payload = {
                message: errorInfo.message || String(errorInfo),
                source: 'frontend',
                detail: errorInfo.stack || null,
                path: (typeof window !== 'undefined' && window.location) ? (window.location.pathname || '') + (window.location.search || '') : null,
                context: {
                    page: ctx.page,
                    section: ctx.section,
                    button: ctx.button,
                    action: ctx.action,
                    tab: ctx.tab,
                    symbol: ctx.symbol,
                    bot_id: ctx.bot_id,
                    account_id: ctx.account_id,
                    url: typeof window !== 'undefined' && window.location ? window.location.href : null,
                    user_agent: typeof navigator !== 'undefined' ? navigator.userAgent : null
                }
            };
            var token = null;
            try {
                if (typeof getAuthStorage === 'function') token = getAuthStorage('token');
                else if (typeof sessionStorage !== 'undefined') token = sessionStorage.getItem('token');
            } catch (e) {}
            var headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            };
            if (token) headers['Authorization'] = 'Bearer ' + token;
            try {
                if (typeof document !== 'undefined' && document.cookie) {
                    var csrfMatch = document.cookie.match(/\bcsrf_token=([^;]+)/);
                    if (csrfMatch && csrfMatch[1]) headers['X-CSRF-Token'] = csrfMatch[1].trim();
                }
            } catch (e) {}
            fetch('/api/log-error', {
                method: 'POST',
                credentials: 'include',
                headers: headers,
                body: JSON.stringify(payload)
            }).catch(function() {});
        } catch (e) {}
    }

    /**
     * Report error to console with structured format and send to backend for admin list
     */
    function reportError(error, context) {
        if (typeof context === 'undefined') context = {};
        var merged = mergeContext(context);
        var tab = merged.tab;
        var symbol = merged.symbol;
        var bot_id = merged.bot_id;
        var account_id = merged.account_id;
        var action = merged.action;
        var button = merged.button;
        var page = merged.page;
        var section = merged.section;

    // Build error info
    var errorInfo = {
        timestamp: new Date().toISOString(),
        context: { page: page, section: section, button: button, action: action, tab: tab, symbol: symbol, bot_id: bot_id, account_id: account_id }
    };

    // Extract backend error standard fields
    if (error && (error.type === 'API_ERROR' || (typeof window !== 'undefined' && window.APIError && error instanceof window.APIError))) {
        errorInfo.error_code = error.error_code;
        errorInfo.error_id = error.error_id;
        errorInfo.request_id = error.request_id;
        errorInfo.status = error.status;
        errorInfo.url = error.url;
        errorInfo.method = error.method;
        errorInfo.message = error.message;
    } else if (error) {
        errorInfo.message = error.message || String(error);
        errorInfo.stack = error.stack;
    } else {
        errorInfo.message = String(error);
    }

    var pageEntry = {
        ts: Date.now(),
        message: errorInfo.message || String(errorInfo),
        detail: errorInfo.stack || null,
        context: errorInfo.context,
        error_code: errorInfo.error_code,
        request_id: errorInfo.request_id
    };
    pushPageError(tab || (errorInfo.context && errorInfo.context.tab) || 'default', pageEntry);

    // Console log with structured format
    console.error('[ERROR]', errorInfo);

    // Send to backend for admin error logs (non-blocking); merged context has page/section/button/action
    sendErrorToBackend(errorInfo, merged);

    // Return formatted error info for UI
    return errorInfo;
}

/**
 * Convert error to user-friendly message
 */
function toUserMessage(error) {
    if (error.type === 'API_ERROR' || error instanceof window.APIError) {
        const parts = [];
        
        // Main message - filter out generic/unknown messages
        let mainMsg = error.message || '';
        
        // If message is just "UNKNOWN" or contains only "UNKNOWN", replace with Turkish message
        if (mainMsg === 'UNKNOWN' || mainMsg.trim() === 'UNKNOWN' || (mainMsg.includes('UNKNOWN') && mainMsg.length < 20)) {
            mainMsg = 'Bilinmeyen bir hata oluştu';
        }
        
        // If message is empty or just status code, use a better default
        if (!mainMsg || mainMsg === `HTTP ${error.status}` || mainMsg.startsWith('HTTP ')) {
            // Try to get detail from error object
            if (error.detail && typeof error.detail === 'string') {
                mainMsg = error.detail;
            } else if (error.error_code && error.error_code !== `HTTP_${error.status}`) {
                // Map error codes to user-friendly messages
                const errorCodeMap = {
                    'BINANCE_WALLET_FAILED': 'Binance cüzdan verisi alınamadı',
                    'BINANCE_AUTH_FAILED': 'Binance API anahtarları geçersiz',
                    'BINANCE_RATE_LIMIT': 'Binance API limit aşıldı',
                    'ACCOUNT_NOT_FOUND': 'Hesap bulunamadı',
                    'ACCOUNT_KEYS_MISSING': 'Binance API anahtarları tanımlı değil. Ayarlardan API Key ve Secret ekleyin.',
                    'ACCOUNT_KEYS_ERROR': 'Hesap anahtarları hatası',
                    'ACCOUNT_ERROR': 'Hesap veya API anahtar ayarı hatası. Ayarlardan API Key ve Secret kontrol edin.',
                    'TIMEOUT': 'İstek zaman aşımına uğradı',
                    'NETWORK_ERROR': 'Ağ bağlantı hatası',
                    'BAD_GATEWAY': 'Sunucu hatası'
                };
                mainMsg = errorCodeMap[error.error_code] || (mainMsg || 'Bir hata oluştu');
            } else {
                mainMsg = 'Bir hata oluştu';
            }
        }
        
        parts.push(mainMsg);

        // Error ID (if available) - only show if meaningful
        if (error.error_id && error.error_id !== 'UNKNOWN') {
            parts.push(`(Error ID: ${error.error_id})`);
        }

        // Request ID (if available) - only show if meaningful
        if (error.request_id && error.request_id !== 'UNKNOWN') {
            parts.push(`(Request ID: ${error.request_id})`);
        }

        return parts.join(' ');
    }

    // Fallback for non-API errors
    const msg = error.message || 'Bilinmeyen bir hata oluştu';
    // Filter out UNKNOWN messages
    if (msg === 'UNKNOWN' || msg.trim() === 'UNKNOWN') {
        return 'Bilinmeyen bir hata oluştu';
    }
    return msg;
}

/**
 * Show error in UI (if Toast available)
 */
function showErrorInUI(error, context = {}) {
    const message = toUserMessage(error);
    
    if (window.Toast && typeof window.Toast.error === 'function') {
        window.Toast.error(message);
    } else {
        // Fallback: console or alert
        console.error('[UI Error]', message);
        if (context.showAlert !== false) {
            alert(message);
        }
    }

    // Also report to console
    reportError(error, context);
}

/**
 * Render error box in UI container (standardized error display)
 */
function renderErrorBox(container, error) {
    if (!container) return;
    
    const errorInfo = reportError(error);
    const message = toUserMessage(error);
    
    const errorBox = document.createElement('div');
    errorBox.className = 'error-box';
    errorBox.style.cssText = `
        padding: 1.5rem;
        background: var(--ds-bg-error, #2d1b1b);
        border: 1px solid var(--ds-border-error, #f6465d);
        border-radius: 8px;
        color: var(--ds-text-error, #f6465d);
        margin: 1rem 0;
    `;
    
    let html = `<div style="font-weight: 600; margin-bottom: 0.5rem;">Bir hata oluştu</div>`;
    html += `<div style="margin-bottom: 0.5rem;">${message}</div>`;
    
    if (errorInfo.error_id) {
        html += `<div style="font-size: 0.85rem; opacity: 0.8; margin-bottom: 0.25rem;">Error ID: ${errorInfo.error_id}</div>`;
    }
    
    if (errorInfo.request_id) {
        html += `<div style="font-size: 0.85rem; opacity: 0.8; margin-bottom: 0.5rem;">Request ID: ${errorInfo.request_id}</div>`;
    }
    
    html += `<button onclick="this.parentElement.remove()" style="
        margin-top: 0.5rem;
        padding: 0.5rem 1rem;
        background: var(--ds-accent, #f0b90b);
        border: none;
        border-radius: 4px;
        color: #000;
        cursor: pointer;
        font-weight: 600;
    ">Tekrar Dene</button>`;
    
    errorBox.innerHTML = html;
    container.appendChild(errorBox);
}

// Global catch: yakalanmayan hatalar ve promise rejection'lar backend'e gönderilsin
if (typeof window !== 'undefined') {
    window.addEventListener('error', function(event) {
        reportError(
            event.error || new Error(event.message || 'Unknown error'),
            { action: 'window.onerror', url: event.filename, line: event.lineno, col: event.colno }
        );
    });
    window.addEventListener('unhandledrejection', function(event) {
        var err = event.reason;
        if (err && (err.message || err.reason)) {
            reportError(err instanceof Error ? err : new Error(err.message || err.reason || String(err)), { action: 'unhandledrejection' });
        }
    });
    // Tıklanan buton/öğede data-error-page, data-error-section, data-error-button, data-error-action varsa son aksiyon olarak kaydet
    document.addEventListener('click', function(event) {
        var el = event.target;
        for (var i = 0; i < 5 && el; i++) {
            if (el.getAttribute && (el.getAttribute('data-error-page') || el.getAttribute('data-error-section') || el.getAttribute('data-error-button') || el.getAttribute('data-error-action'))) {
                setLastAction({
                    page: el.getAttribute('data-error-page') || undefined,
                    section: el.getAttribute('data-error-section') || undefined,
                    button: el.getAttribute('data-error-button') || undefined,
                    action: el.getAttribute('data-error-action') || undefined
                });
                break;
            }
            el = el.parentElement;
        }
    }, true);
}

// Export
window.errorReporter = {
    report: reportError,
    toUserMessage: toUserMessage,
    show: showErrorInUI,
    renderBox: renderErrorBox,
    sendToBackend: sendErrorToBackend,
    setLastAction: setLastAction,
    getLastAction: getLastAction,
    getPageErrors: getPageErrors,
    clearPageErrors: clearPageErrors,
    getAllPageErrors: getAllPageErrors,
    clearAllPageErrors: clearAllPageErrors
};
