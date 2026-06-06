/**
 * FILE: api.js
 * VERSION: v2
 * DATE: 2025-01-21
 * CHANGE: Add getAdminSummary, getAccountSummary, deleteAccount, getPrice methods
 */

const API_BASE = "/api";

// Simple in-memory cache
const cache = new Map();
const CACHE_TTL = 2000; // 2 seconds default

// Fetch wrapper with caching and error handling
async function apiFetch(endpoint, options = {}) {
    const url = `${API_BASE}${endpoint}`;
    const cacheKey = `${options.method || 'GET'}:${url}`;
    
    // Check cache for GET requests
    if (!options.method || options.method === 'GET') {
        const cached = cache.get(cacheKey);
        if (cached && Date.now() - cached.timestamp < (options.cacheTTL || CACHE_TTL)) {
            return cached.data;
        }
    }
    
    try {
        const response = await fetch(url, {
            ...options,
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            }
        });
        
        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: `HTTP ${response.status}` }));
            throw new Error(error.detail || `HTTP ${response.status}`);
        }
        
        const data = await response.json();
        
        // Cache GET responses
        if (!options.method || options.method === 'GET') {
            cache.set(cacheKey, {
                data,
                timestamp: Date.now()
            });
        }
        
        return data;
    } catch (error) {
        console.error(`API Error [${endpoint}]:`, error);
        if (window.Toast) {
            window.Toast.error(error.message || "An error occurred");
        }
        throw error;
    }
}

// API methods
const API = {
    // Accounts
    getAccounts: () => apiFetch("/accounts"),
    getAccount: (id) => apiFetch(`/accounts/${id}`),
    createAccount: (data) => apiFetch("/accounts", {
        method: "POST",
        body: JSON.stringify(data)
    }),
    updateAccountMode: (id, mode) => apiFetch(`/accounts/${id}/mode`, {
        method: "POST",
        body: JSON.stringify({ mode })
    }),
    deleteAccount: (id) => apiFetch(`/accounts/${id}`, {
        method: "DELETE"
    }),
    
    // Summary
    getAdminSummary: () => apiFetch("/summary/admin"),
    getAccountSummary: (accountId) => apiFetch(`/summary/account?account_id=${accountId}`),
    
    // Price
    getPrice: (symbol) => apiFetch(`/price?symbol=${symbol}`),
    
    // Dashboard summary
    getDashboardSummary: (accountId) => apiFetch(`/summary/account?account_id=${accountId}`),
    
    // Bots
    getBots: (accountId) => apiFetch(`/bots?account_id=${accountId}`),
    getBot: (botId, accountId) => apiFetch(`/bots/${botId}?account_id=${accountId}`),
    getBotStatus: (botId, accountId) => apiFetch(`/bots/${botId}/status?account_id=${accountId}`),
    getBotPnL: (botId, accountId) => apiFetch(`/bots/${botId}/pnl?account_id=${accountId}`),
    getBotTrades: (botId, accountId, limit = 50) => apiFetch(`/bots/${botId}/trades?account_id=${accountId}&limit=${limit}`),
    createBot: (data) => apiFetch("/bots/create", {
        method: "POST",
        body: JSON.stringify(data)
    }),
    startBot: (botId, accountId) => apiFetch(`/bots/${botId}/start?account_id=${accountId}`, {
        method: "POST"
    }),
    stopBot: (botId, accountId) => apiFetch(`/bots/${botId}/stop?account_id=${accountId}`, {
        method: "POST"
    }),
    deleteBot: (botId, accountId) => apiFetch(`/bots/${botId}?account_id=${accountId}`, {
        method: "DELETE"
    }),
    
    // Binance assets
    getBinanceAssets: (accountId) => apiFetch(`/binance/assets?account_id=${accountId}`),
    
    // Ticker
    getTicker: () => apiFetch("/ticker", { cacheTTL: 5000 })
};

// Clear cache utility
function clearCache(pattern = null) {
    if (pattern) {
        for (const [key] of cache) {
            if (key.includes(pattern)) {
                cache.delete(key);
            }
        }
    } else {
        cache.clear();
    }
}

// API delete helper
async function apiDelete(endpoint) {
    return apiFetch(endpoint, { method: "DELETE" });
}

// Export
window.API = API;
window.API_BASE = API_BASE; // Export for ticker.js and other scripts
window.API.apiDelete = apiDelete;
window.apiFetch = apiFetch;
window.clearCache = clearCache;

