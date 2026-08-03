/**
 * FILE: core/apiClient.js
 * VERSION: v1
 * DATE: 2026-01-23
 * CHANGE: Single fetch point with backend error standard support
 * 
 * RULE: All pages must use apiClient, no direct fetch() calls
 */

const API_BASE_URL = window.location.origin || 'http://127.0.0.1:8000';
const DEFAULT_TIMEOUT = 15000; // 15s – dashboard/summary and account meta can be slow; avoid 499/timeout
const RATE_LIMIT_TOAST_DEBOUNCE_MS = 30000;
var _lastRateLimitToastAt = 0;
const SERVER_DOWN_TOAST_KEY = 'tt-server-down';
const SERVER_DOWN_TOAST_DEFAULT = 'Sunucuya bağlanılamıyor. Sunucu gelene kadar bekleniyor.';

function showServerDownToast(message) {
    if (typeof window.Toast === 'undefined') return;
    var msg = message || SERVER_DOWN_TOAST_DEFAULT;
    try {
        if (typeof window.Toast.showPersistent === 'function') {
            window.Toast.showPersistent(SERVER_DOWN_TOAST_KEY, msg, 'warning');
        } else if (window.Toast.warning) {
            window.Toast.warning(msg, 0);
        }
    } catch (e) { /* ignore */ }
}

function hideServerDownToast() {
    if (typeof window.Toast === 'undefined') return;
    try {
        if (typeof window.Toast.dismiss === 'function') {
            window.Toast.dismiss(SERVER_DOWN_TOAST_KEY);
        }
    } catch (e) { /* ignore */ }
}

/** FastAPI detail: object { message } or plain string. */
function extractHttpDetailMessage(data) {
    if (!data) return null;
    var d = data.detail;
    if (typeof d === 'string' && d.trim()) return d.trim();
    if (d && typeof d === 'object' && d.message) return String(d.message);
    if (data.message) return String(data.message);
    return null;
}

function maybeShowRateLimitToast(message, options) {
    if (options && options.suppressRateLimitToast) return;
    if (typeof window.Toast === 'undefined' || !window.Toast.warning) return;
    var now = Date.now();
    if (now - _lastRateLimitToastAt < RATE_LIMIT_TOAST_DEBOUNCE_MS) return;
    _lastRateLimitToastAt = now;
    var msg = (message && String(message).trim())
        || 'Çok fazla istek. Lütfen bekleyin.';
    try { window.Toast.warning(msg); } catch (e) {}
    if (window.__DEBUG_NET__) {
        console.warn('[apiClient] 429 rate limit:', msg);
    }
}

/** Global concurrency limiter: max 2 active HTTP requests at once */
const MAX_CONCURRENT_REQUESTS = 2;
let _activeRequestCount = 0;
const _requestQueue = [];

function _acquireSlot() {
    if (_activeRequestCount < MAX_CONCURRENT_REQUESTS) {
        _activeRequestCount++;
        return Promise.resolve();
    }
    return new Promise(function (resolve) {
        _requestQueue.push(resolve);
    });
}

function _releaseSlot() {
    _activeRequestCount--;
    if (_requestQueue.length > 0 && _activeRequestCount < MAX_CONCURRENT_REQUESTS) {
        _activeRequestCount++;
        var next = _requestQueue.shift();
        if (typeof next === 'function') next();
    }
}

// Public config (auth_cookie_primary, csrf_double_submit) – fetched once on first use
var _publicConfig = null;
var _publicConfigPromise = null;
function getPublicConfig() {
    if (_publicConfig) return _publicConfig;
    if (!_publicConfigPromise && typeof fetch !== 'undefined') {
        _publicConfigPromise = fetch((window.location.origin || '') + '/api/config/public', { method: 'GET', credentials: 'include', cache: 'no-store' })
            .then(function (r) { return r.ok ? r.json() : {}; })
            .then(function (c) { _publicConfig = c || {}; return _publicConfig; })
            .catch(function () { _publicConfig = {}; return _publicConfig; });
    }
    return _publicConfig || {};
}
function getPublicConfigAsync() {
    if (_publicConfig) return Promise.resolve(_publicConfig);
    return _publicConfigPromise || getPublicConfig() || Promise.resolve({});
}

// When auth_cookie_primary: do not persist token (cookie-only); still persist user for display
function shouldPersistToken() {
    var c = getPublicConfig();
    return !c.auth_cookie_primary;
}

// Stable auth store: sessionStorage for the active page, localStorage for Safari
// standalone/browser restarts. The HttpOnly cookie remains the server-side source.
var AUTH_KEYS = ['token', 'user'];
function getStableAuth() {
    var out = {};
    AUTH_KEYS.forEach(function (k) { out[k] = getAuthStorage(k); });
    return out;
}
function setStableAuth(data) {
    if (!data) return;
    AUTH_KEYS.forEach(function (k) {
        if (k === 'token' && !shouldPersistToken()) return;
        if (data[k] != null) {
            var v = data[k];
            setAuthStorage(k, typeof v === 'string' ? v : JSON.stringify(v));
        }
    });
}
function clearStableAuth() {
    AUTH_KEYS.forEach(function (k) {
        try { if (typeof sessionStorage !== 'undefined') sessionStorage.removeItem(k); } catch (e) {}
        try { if (typeof localStorage !== 'undefined') localStorage.removeItem(k); } catch (e) {}
    });
}

// Explicit logout is broadcast to every open tab.
const AUTH_BC = typeof BroadcastChannel !== 'undefined' ? new BroadcastChannel('app-auth') : null;
function getAuthStorage(key) {
    if (key === 'token' && !shouldPersistToken()) return null;
    try {
        var sessionValue = typeof sessionStorage !== 'undefined' ? sessionStorage.getItem(key) : null;
        var persistentValue = typeof localStorage !== 'undefined' ? localStorage.getItem(key) : null;
        var value = sessionValue || persistentValue;
        if (value && !sessionValue && typeof sessionStorage !== 'undefined') {
            sessionStorage.setItem(key, value);
        }
        return value;
    } catch (e) {
        return null;
    }
}
function setAuthStorage(key, value) {
    try {
        if (typeof sessionStorage !== 'undefined') sessionStorage.setItem(key, value);
    } catch (e) {}
    try {
        if (typeof localStorage !== 'undefined') localStorage.setItem(key, value);
    } catch (e) {}
}
function clearAuthStorage() {
    clearStableAuth();
}
function clearAuthAndBroadcast() {
    clearStableAuth();
    if (AUTH_BC) {
        try {
            AUTH_BC.postMessage({ type: 'logout' });
        } catch (e) {}
    }
}

// Redirect to login at most once; never when already on login page (prevents loop)
var _redirectingToLogin = false;
function isLoginPage() {
    var p = (window.location.pathname || '');
    return p.endsWith('/ui/login.html') || p.indexOf('/ui/login') !== -1;
}
function isDashboardPage() {
    var p = (window.location.pathname || '');
    return p.indexOf('dashboard') !== -1;
}
function showSessionInvalidBanner() {
    if (typeof document === 'undefined' || document.getElementById('apiClientSessionBanner')) return;
    var el = document.createElement('div');
    el.id = 'apiClientSessionBanner';
    el.setAttribute('role', 'alert');
    el.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:100001;background:#1a0a0a;color:#f6465d;padding:12px 16px;font-size:14px;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,0.4);';
    el.innerHTML = '<span>Oturum geçersiz.</span> <button type="button" class="btn btn-sm" style="margin-left:8px;" id="apiClientSessionLoginBtn">Giriş</button>';
    document.body.appendChild(el);
    var btn = document.getElementById('apiClientSessionLoginBtn');
    if (btn) btn.onclick = function () { redirectToLoginOnce(true); };
}
/**
 * @param {boolean} [sessionExpired] - If true, redirect with ?session_expired=1 so login shows "Oturumunuz sona erdi (sunucu yeniden başladı)".
 */
function redirectToLoginOnce(sessionExpired) {
    if (_redirectingToLogin) return;
    if (isLoginPage()) return;
    _redirectingToLogin = true;
    try {
        clearAuthAndBroadcast();
        if (typeof localStorage !== 'undefined') {
            try { localStorage.removeItem('boot_id'); localStorage.removeItem('last_route'); } catch (e) {}
        }
        if (typeof window.Toast !== 'undefined' && window.Toast.warning) {
            try { window.Toast.warning('Oturum sonlandı. Giriş sayfasına yönlendiriliyorsunuz.'); } catch (e) {}
        }
        var url = '/ui/login.html' + (sessionExpired ? '?session_expired=1' : '');
        window.location.replace(url);
    } catch (e) {
        _redirectingToLogin = false;
    }
}

if (AUTH_BC) {
    AUTH_BC.onmessage = function (e) {
        if (e.data && e.data.type === 'logout') {
            clearStableAuth();
            if (!isLoginPage()) {
                window.location.replace('/ui/login.html?logout=1');
            }
        }
    };
}

// In-flight request deduplication
const inFlightRequests = new Map(); // key -> Promise

// Request statistics (for debugging)
const requestStats = {
    total: 0,
    byRoute: new Map(), // route -> count
    byBinanceEndpoint: new Map(), // binance_endpoint -> count
    errors: 0,
    rateLimitErrors: 0
};

// Request trace (in-memory, last 1000 requests)
const requestTrace = [];
const MAX_TRACE_SIZE = 1000;

// Sunucu geri gelince kontrol: 200 gelince toast göster, oturumu temizleme / login'e atma — kullanıcı hesapta kalsın
var _serverBackCheckerTimer = null;
var _serverUnreachableCandidate = null;
var _serverHealthProbeInFlight = false;
var _lastServerHealthyAt = 0;
var SERVER_UNREACHABLE_CONFIRM_MS = 3000;
var SERVER_HEALTH_CONFIRM_FAILS = 2;
var SERVER_HEALTH_PROBE_INTERVAL_MS = 2500;
var SERVER_HEALTH_PROBE_TIMEOUT_MS = 4000;
var SERVER_HEALTH_OK_CACHE_MS = 5000;

function clearServerUnreachableCandidate() {
    _serverUnreachableCandidate = null;
}

function stopServerBackChecker() {
    if (_serverBackCheckerTimer !== null) {
        clearInterval(_serverBackCheckerTimer);
        _serverBackCheckerTimer = null;
    }
}

function markServerUnreachable() {
    if (typeof window === 'undefined') return;
    if (window.__TT_SERVER_UNREACHABLE__) return;
    window.__TT_SERVER_UNREACHABLE__ = true;
    try {
        window.dispatchEvent(new CustomEvent('tt-server-unreachable', { detail: { unreachable: true } }));
    } catch (e) { /* ignore */ }
}

function markServerReachable() {
    if (typeof window === 'undefined') return;
    _lastServerHealthyAt = Date.now();
    stopServerBackChecker();
    clearServerUnreachableCandidate();
    if (!window.__TT_SERVER_UNREACHABLE__) return;
    window.__TT_SERVER_UNREACHABLE__ = false;
    hideServerDownToast();
    try {
        window.dispatchEvent(new CustomEvent('tt-server-unreachable', { detail: { unreachable: false } }));
    } catch (e) { /* ignore */ }
}

function isServerUnreachable() {
    return !!(typeof window !== 'undefined' && window.__TT_SERVER_UNREACHABLE__);
}

function runServerHealthProbe() {
    if (_serverHealthProbeInFlight) return;
    _serverHealthProbeInFlight = true;
    var controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var timeoutId = controller
        ? setTimeout(function () { controller.abort(); }, SERVER_HEALTH_PROBE_TIMEOUT_MS)
        : null;
    var config = { method: 'GET', cache: 'no-store', credentials: 'include' };
    if (controller) config.signal = controller.signal;

    fetch(API_BASE_URL + '/api/health', config)
        .then(function (r) {
            if (!r.ok) throw new Error('health_http_' + r.status);
            return r.json();
        })
        .then(function (data) {
            if (!data || data.ok !== true) throw new Error('health_not_ready');
            var wasUnreachable = window.__TT_SERVER_UNREACHABLE__ === true;
            markServerReachable();
            if (wasUnreachable && typeof window.Toast !== 'undefined' && window.Toast.success) {
                try { window.Toast.success('Sunucu geldi. Bağlantı yenilendi.'); } catch (e) {}
            }
        })
        .catch(function () {
            var now = Date.now();
            if (!_serverUnreachableCandidate) {
                _serverUnreachableCandidate = {
                    firstAt: now,
                    requestFails: 0,
                    healthFails: 0,
                    message: SERVER_DOWN_TOAST_DEFAULT
                };
            }
            _serverUnreachableCandidate.healthFails += 1;
            var elapsed = now - _serverUnreachableCandidate.firstAt;
            if (
                _serverUnreachableCandidate.healthFails >= SERVER_HEALTH_CONFIRM_FAILS
                && elapsed >= SERVER_UNREACHABLE_CONFIRM_MS
            ) {
                markServerUnreachable();
                showServerDownToast(_serverUnreachableCandidate.message);
            }
        })
        .finally(function () {
            if (timeoutId) clearTimeout(timeoutId);
            _serverHealthProbeInFlight = false;
        });
}

function startServerBackChecker(toastMessage) {
    if (typeof window.location === 'undefined' || (window.location.pathname || '').includes('/login')) return;
    var now = Date.now();
    if (
        !window.__TT_SERVER_UNREACHABLE__
        && _lastServerHealthyAt
        && (now - _lastServerHealthyAt) < SERVER_HEALTH_OK_CACHE_MS
    ) {
        return;
    }
    if (!_serverUnreachableCandidate) {
        _serverUnreachableCandidate = {
            firstAt: now,
            requestFails: 0,
            healthFails: 0,
            message: toastMessage || SERVER_DOWN_TOAST_DEFAULT
        };
    }
    _serverUnreachableCandidate.requestFails += 1;
    if (toastMessage) _serverUnreachableCandidate.message = toastMessage;
    if (_serverBackCheckerTimer !== null) return;

    // Endpoint 5xx/timeout alone does not mean the server is down. Only the
    // dedicated health endpoint may confirm and announce a real outage.
    _serverBackCheckerTimer = setInterval(
        runServerHealthProbe,
        SERVER_HEALTH_PROBE_INTERVAL_MS
    );
    runServerHealthProbe();
}

/**
 * Generate request key for deduplication
 */
function getRequestKey(endpoint, method, body) {
    const bodyStr = body ? (typeof body === 'string' ? body : JSON.stringify(body)) : '';
    return `${method}:${endpoint}:${bodyStr}`;
}

/**
 * Structured error object matching backend standard
 */
class APIError extends Error {
    constructor({ status, error_code, error_id, request_id, message, url, method, retry_after, ban_until, data, binance_code }) {
        super(message || `HTTP ${status}`);
        this.name = 'APIError';
        this.type = 'API_ERROR';
        this.status = status;
        this.error_code = error_code;
        this.error_id = error_id;
        this.request_id = request_id;
        this.url = url;
        this.method = method;
        this.retry_after = retry_after;
        this.ban_until = ban_until;
        this.data = data || null;
        this.binance_code = binance_code != null ? binance_code : null;
    }
}

/**
 * Main API client - single fetch point with in-flight deduplication
 */
async function apiClient(endpoint, options = {}) {
    // Check for in-flight duplicate request
    const requestKey = getRequestKey(endpoint, options.method || 'GET', options.body);
    if (inFlightRequests.has(requestKey)) {
        if (typeof window !== 'undefined' && window.__DEBUG_API_CLIENT__ === true) {
            console.log(`[apiClient] Deduplicating in-flight request: ${requestKey}`);
        }
        return inFlightRequests.get(requestKey);
    }
    const {
        method = 'GET',
        body = null,
        headers = {},
        timeout = DEFAULT_TIMEOUT,
        signal = null
    } = options;

    const url = endpoint.startsWith('http') ? endpoint : `${API_BASE_URL}${endpoint}`;
    
    // Correlation ID: propagated to backend and response
    var requestId = (typeof crypto !== 'undefined' && crypto.randomUUID) ? crypto.randomUUID() : ('req-' + Date.now() + '-' + Math.random().toString(36).substr(2, 9));
    
    // Koruma altındaki API'ler için Bearer token ekle (login ve boot-id hariç)
    const isPublic = typeof endpoint === 'string' && (
        endpoint.includes('/auth/login') ||
        endpoint.includes('/auth/register') ||
        endpoint === '/api/boot-id' || endpoint.includes('/api/boot-id') ||
        endpoint === '/api/health' || endpoint.includes('/api/health')
    );
    const token = isPublic ? null : getAuthStorage('token');
    const authHeaders = token ? { 'Authorization': 'Bearer ' + token } : {};
    authHeaders['X-Request-ID'] = requestId;
    if (method !== 'GET' && getPublicConfig().csrf_double_submit && typeof document !== 'undefined' && document.cookie) {
        var csrfMatch = document.cookie.match(/\bcsrf_token=([^;]+)/);
        if (csrfMatch && csrfMatch[1]) authHeaders['X-CSRF-Token'] = csrfMatch[1].trim();
    }

    var abortController = null;
    var timeoutId = null;
    var effectiveSignal = signal;

    var config = {
        method: method,
        credentials: 'include',
        headers: Object.assign(
            { 'Content-Type': 'application/json', 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
            authHeaders,
            headers
        )
    };
    if (effectiveSignal) config.signal = effectiveSignal;

    if (body && method !== 'GET') {
        config.body = typeof body === 'string' ? body : JSON.stringify(body);
    }

    var requestId = null;
    var response = null;

    var traceRequestId = Date.now() + '-' + Math.random().toString(36).substr(2, 9);
    var startTime = performance.now();
    var isBinanceRoute = endpoint.indexOf('/binance/') !== -1 || endpoint.indexOf('/data/hub') !== -1;

    if (window.__DEBUG_NET__) {
        console.log('[apiClient] ' + method + ' ' + endpoint + ' request_id=' + traceRequestId);
    }

    var requestPromise = (async function () {
        await _acquireSlot();
        try {
            if (!effectiveSignal && timeout > 0 && typeof AbortController !== 'undefined') {
                abortController = new AbortController();
                effectiveSignal = abortController.signal;
                config.signal = effectiveSignal;
                timeoutId = setTimeout(function () {
                    if (abortController) abortController.abort();
                }, timeout);
            } else if (!effectiveSignal && timeout > 0 && typeof AbortSignal !== 'undefined' && AbortSignal.timeout) {
                effectiveSignal = AbortSignal.timeout(timeout);
                config.signal = effectiveSignal;
            }
            response = await fetch(url, config);
            if (timeoutId) clearTimeout(timeoutId);
            timeoutId = null;
        
        // Extract request ID from response header
        requestId = response.headers.get('X-Request-ID');

        // Parse JSON
        let data;
        const contentType = response.headers.get('content-type');
        try {
            if (contentType && contentType.includes('application/json')) {
                data = await response.json();
            } else {
                data = await response.text();
            }
        } catch (parseError) {
            // If JSON parsing fails, try to get text
            try {
                const text = await response.text();
                data = text || `Failed to parse response: ${parseError.message}`;
            } catch (textError) {
                data = `Failed to parse response: ${parseError.message}`;
            }
        }

        // Check for backend error standard
        if (!response.ok) {
            // 499: istemci isteği iptal etti (yenileme, navigasyon) — fatal değil
            if (response.status === 499) {
                throw new APIError({
                    status: 499,
                    error_code: 'CLIENT_DISCONNECT',
                    error_id: null,
                    request_id: requestId,
                    message: (typeof data === 'object' && data && (data.detail || data.message)) || 'client_disconnect',
                    url,
                    method
                });
            }
            // 401: only SESSION_NOT_FOUND = session invalid (logout/redirect). UNAUTHORIZED/missing_token = request had no token, do NOT clear session (e.g. prefetch without cookie).
            if (response.status === 401) {
                var body = data;
                var detail = (body && body.detail && typeof body.detail === 'object') ? body.detail : {};
                var errCode = detail.error_code || (body && body.error_code) || 'UNAUTHORIZED';
                var isSessionInvalid = errCode === 'SESSION_NOT_FOUND';
                if (isSessionInvalid) {
                    if (isDashboardPage()) {
                        showSessionInvalidBanner();
                    } else {
                        redirectToLoginOnce(true);
                    }
                }
            }
            // 409 LAST_DEVICE_CANNOT_BE_REMOVED → toast (UI zaten butonu disable eder)
            if (response.status === 409 && data?.detail && data.detail.error_code === 'LAST_DEVICE_CANNOT_BE_REMOVED' && typeof window.Toast !== 'undefined' && window.Toast.warning) {
                try { window.Toast.warning(data.detail.message || 'En az 1 onaylı cihaz kalmalı.'); } catch (e) {}
            }
            // 403 BINANCE_AUTH: Binance API key geçersiz – login'e atma, sadece toast
            // 403 CSRF_BLOCKED: CSRF koruması – toast, login'e atma
            if (response.status === 403) {
                var d403 = data?.detail && typeof data.detail === 'object' ? data.detail : (data && data.error_code ? data : {});
                var code403 = d403.error_code || data?.error_code;
                if (code403 === 'CSRF_BLOCKED' && typeof window.Toast !== 'undefined' && window.Toast.warning) {
                    try { window.Toast.warning(d403.message || 'Güvenlik doğrulaması başarısız. Sayfayı yenileyip tekrar deneyin.'); } catch (e) {}
                } else if (code403 === 'BINANCE_AUTH' && typeof window.Toast !== 'undefined' && window.Toast.warning) {
                    try { window.Toast.warning(d403.message || 'Binance API anahtarı veya IP izni geçersiz. Ayarlar üzerinden kontrol edin.'); } catch (e) {}
                }
            }
            // 429 RATE_LIMITED (FastAPI detail may be string — show server text; debounce spam)
            if (response.status === 429) {
                maybeShowRateLimitToast(extractHttpDetailMessage(data), options);
            }
            // Sunucu kapalı/erişilemez: 502, 503, 504 → login'e atma, toast + sunucu geri gelince kontrol
            if (response.status === 503 || response.status === 502 || response.status === 504) {
                var detailObj = data?.detail && typeof data.detail === 'object' ? data.detail : null;
                var msg = detailObj?.message || (typeof data?.detail === 'string' ? data.detail : null) || data?.message
                    || (response.status === 503 ? 'Sunucu erişime kapalı.' : (response.status === 504 ? 'Sunucu yanıt vermiyor.' : 'Sunucu kapalı veya erişilemiyor.'));
                if (response.status !== 503 || !detailObj?.error_code) {
                    startServerBackChecker(msg);
                } else {
                    startServerBackChecker();
                }
                var code = detailObj?.error_code || (response.status === 503 ? 'SERVICE_UNAVAILABLE' : (response.status === 504 ? 'GATEWAY_TIMEOUT' : 'BAD_GATEWAY'));
                throw new APIError({
                    status: response.status,
                    error_code: code,
                    error_id: null,
                    request_id: requestId,
                    message: msg,
                    url,
                    method
                });
            }
            
            var errObj = (data?.error && typeof data.error === 'object') ? data.error : (data?.detail && typeof data.detail === 'object' ? data.detail : null);
            var errMsg = (errObj && errObj.message)
                || (errObj && typeof errObj.detail === 'string' ? errObj.detail : null)
                || data?.message
                || (typeof data?.detail === 'string' ? data.detail : null)
                || (typeof data === 'string' ? data : 'HTTP ' + response.status);
            var errCode = (errObj && (errObj.error_code || errObj.error)) || data?.error_code || 'HTTP_' + response.status;
            var errorData = {
                status: response.status,
                error_code: errCode,
                error_id: (errObj && errObj.error_id) || data?.error_id || null,
                request_id: requestId || (errObj && errObj.request_id) || (data?.detail && data.detail.request_id) || null,
                message: errMsg,
                url: url,
                method: method,
                data: data || null,
                binance_code: (errObj && errObj.code != null) ? errObj.code : null,
            };

            // Include data_status if present
            if (data?.data_status) {
                errorData.data_status = data.data_status;
            }
            
            // Include Retry-After header if present (for rate limit errors)
            const retryAfter = response.headers.get('Retry-After');
            if (retryAfter) {
                errorData.retry_after = parseInt(retryAfter);
            }
            
            // Include ban_until from response data if present (check both data.ban_until and data.detail.ban_until)
            if (data?.ban_until) {
                errorData.ban_until = data.ban_until;
            } else if (data?.detail && typeof data.detail === 'object' && data.detail.ban_until) {
                errorData.ban_until = data.detail.ban_until;
            }
            
            // Include retry_after from response data if present (check both data.retry_after and data.detail.retry_after)
            if (data?.retry_after && !errorData.retry_after) {
                errorData.retry_after = parseInt(data.retry_after);
            } else if (data?.detail && typeof data.detail === 'object' && data.detail.retry_after && !errorData.retry_after) {
                errorData.retry_after = parseInt(data.detail.retry_after);
            }

            throw new APIError(errorData);
        }

            // Success - attach request_id to response if available
            if (requestId && typeof data === 'object' && data !== null) {
                data._request_id = requestId;
            }

            // Update statistics
            const latency = Math.round(performance.now() - startTime);
            requestStats.total++;
            const routeKey = endpoint.split('?')[0]; // Remove query params
            requestStats.byRoute.set(routeKey, (requestStats.byRoute.get(routeKey) || 0) + 1);
            
            // Trace request
            const traceEntry = {
                timestamp: new Date().toISOString(),
                layer: 'frontend',
                type: 'http',
                request_id: traceRequestId,
                route: routeKey,
                binance_endpoint: isBinanceRoute ? routeKey : 'N/A',
                weight: 0, // Will be updated by backend trace
                status: response.status,
                latency_ms: latency,
                trigger: options.trigger || 'unknown',
                owner: options.owner || 'unknown',
                symbol: options.symbol || 'N/A'
            };
            
            // Add to trace (keep last MAX_TRACE_SIZE)
            requestTrace.push(traceEntry);
            if (requestTrace.length > MAX_TRACE_SIZE) {
                requestTrace.shift();
            }
            
            // Log if debug enabled
            if (window.__DEBUG_NET__) {
                console.log(`[apiClient] ${method} ${endpoint} status=${response.status} latency=${latency}ms`);
            }

            markServerReachable();
            return data;

        } catch (error) {
            const latency = Math.round(performance.now() - startTime);
            requestStats.errors++;
            
            // Check for rate limit errors
            if (error instanceof APIError && (error.status === 429 || error.status === 418)) {
                requestStats.rateLimitErrors++;
            }
            
            // Trace error
            const routeKey = endpoint.split('?')[0];
            const traceEntry = {
                timestamp: new Date().toISOString(),
                layer: 'frontend',
                type: 'http',
                request_id: traceRequestId,
                route: routeKey,
                binance_endpoint: isBinanceRoute ? routeKey : 'N/A',
                weight: 0,
                status: error.status || 0,
                latency_ms: latency,
                trigger: options.trigger || 'unknown',
                owner: options.owner || 'unknown',
                symbol: options.symbol || 'N/A',
                error: error.error_code || error.message
            };
            
            requestTrace.push(traceEntry);
            if (requestTrace.length > MAX_TRACE_SIZE) {
                requestTrace.shift();
            }
            
            // Log if debug enabled
            if (window.__DEBUG_NET__) {
                console.error(`[apiClient] ${method} ${endpoint} ERROR:`, error);
            }
            
            // Timeout / istek iptali (AbortError = yenileme veya sayfa kapatma). Yönlendirme yapma; sadece hata fırlat.
            if (error.name === 'AbortError' || error.name === 'TimeoutError') {
                throw new APIError({
                    status: 0,
                    error_code: 'TIMEOUT',
                    error_id: null,
                    request_id: requestId,
                    message: `Request timeout after ${timeout}ms`,
                    url,
                    method
                });
            }

            // APIError: 5xx / ağ hatası → sunucu geri gelince kontrol (toast debounce startServerBackChecker içinde)
            if (error instanceof APIError) {
                var s = error.status || 0;
                if (s === 502 || s === 503 || s === 504) {
                    // Already registered in the response branch; avoid counting one HTTP failure twice.
                } else if (s === 0 && String(error.error_code || '').toUpperCase() === 'NETWORK_ERROR') {
                    startServerBackChecker();
                } else if (s >= 500 && s < 600) {
                    startServerBackChecker();
                }
                throw error;
            }

            // Ağ hatası (sunucu kapalı)
            startServerBackChecker();
            throw new APIError({
                status: 0,
                error_code: 'NETWORK_ERROR',
                error_id: null,
                request_id: requestId,
                message: error.message || 'Network error',
                url,
                method
            });
        } finally {
            if (timeoutId) clearTimeout(timeoutId);
            _releaseSlot();
            inFlightRequests.delete(requestKey);
        }
    })();

    // Store promise for deduplication
    inFlightRequests.set(requestKey, requestPromise);

    return requestPromise;
}

// Convenience methods
apiClient.get = (endpoint, options = {}) => apiClient(endpoint, { ...options, method: 'GET' });
apiClient.post = (endpoint, body, options = {}) => apiClient(endpoint, { ...options, method: 'POST', body });
apiClient.put = (endpoint, body, options = {}) => apiClient(endpoint, { ...options, method: 'PUT', body });
apiClient.patch = (endpoint, body, options = {}) => apiClient(endpoint, { ...options, method: 'PATCH', body });
apiClient.delete = (endpoint, options = {}) => apiClient(endpoint, { ...options, method: 'DELETE' });

/** Auth gate: token yoksa polling/summary başlatma. Login sayfası ve dashboard token kontrolü için kullanılır. */
apiClient.hasToken = function () {
    // Cookie-authenticated Safari launches may not expose the HttpOnly token.
    return !!getAuthStorage('token') || !!getAuthStorage('user');
};
apiClient.clearAuthAndBroadcast = clearAuthAndBroadcast;
apiClient.redirectToLoginOnce = redirectToLoginOnce;
apiClient.getPublicConfigAsync = getPublicConfigAsync;

// Debug function to dump network statistics
window.dumpNetStats = function() {
    const stats = {
        total: requestStats.total,
        errors: requestStats.errors,
        rateLimitErrors: requestStats.rateLimitErrors,
        byRoute: Object.fromEntries(requestStats.byRoute),
        byBinanceEndpoint: Object.fromEntries(requestStats.byBinanceEndpoint),
        recentTrace: requestTrace.slice(-50) // Last 50 requests
    };
    
    console.table(stats.byRoute);
    console.log('Recent trace (last 50):', stats.recentTrace);
    return stats;
};

// Export
window.apiClient = apiClient;
window.APIError = APIError;
window.isServerUnreachable = isServerUnreachable;
window.markServerUnreachable = markServerUnreachable;
window.markServerReachable = markServerReachable;
