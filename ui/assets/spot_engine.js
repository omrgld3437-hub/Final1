/**
 * FILE: spot_engine.js
 * VERSION: v1.0
 * DATE: 2026-01-22
 * CHANGE: YENİ - Bağımsız Spot Trading Engine - Flash Hızında
 */

// Backend'de 500 veya geçersiz olan çiftler – istek atma, varsayılan dön
const INVALID_QUICK_DATA_SYMBOLS = new Set(['USDTUSDT', 'USDCUSDT', 'FDUSDUSDT', 'BUSDUSDT', 'TUSDUSDT', 'DAIUSDT']);

// ============================================================
// SPOT ENGINE - Flash Hızlı Trading Motoru (Frontend)
// ============================================================

class SpotEngine {
    constructor(accountId) {
        this.accountId = accountId;
        this.cache = {
            prices: new Map(),      // symbol -> {price, ts}
            quickData: new Map(),   // symbol -> {data, ts}
        };
        this.updateIntervals = new Map();
        this.abortControllers = new Map();
        
        // TTL constants (ms)
        this.PRICE_TTL = 1000;      // 1 second
        this.QUICK_DATA_TTL = 2000; // 2 seconds
    }
    
    // ============================================================
    // CACHE MANAGEMENT
    // ============================================================
    
    getCachedPrice(symbol) {
        const entry = this.cache.prices.get(symbol);
        if (!entry) return null;
        const age = Date.now() - entry.ts;
        if (age > this.PRICE_TTL) {
            this.cache.prices.delete(symbol);
            return null;
        }
        return entry.price;
    }
    
    setCachedPrice(symbol, price) {
        this.cache.prices.set(symbol, { price, ts: Date.now() });
    }
    
    getCachedQuickData(symbol) {
        const entry = this.cache.quickData.get(symbol);
        if (!entry) return null;
        const age = Date.now() - entry.ts;
        if (age > this.QUICK_DATA_TTL) {
            this.cache.quickData.delete(symbol);
            return null;
        }
        return entry.data;
    }
    
    setCachedQuickData(symbol, data) {
        this.cache.quickData.set(symbol, { data, ts: Date.now() });
    }
    
    // ============================================================
    // QUICK DATA FETCH - Tek İstek ile Tüm Veri
    // ============================================================
    
    async fetchQuickData(symbol, signal = null) {
        const cacheKey = symbol.toUpperCase();
        
        // Check cache first
        const cached = this.getCachedQuickData(cacheKey);
        if (cached) {
            return cached;
        }
        // Geçersiz semboller için istek atma (FDUSDUSDT vb. – backend 500 önlemi)
        if (INVALID_QUICK_DATA_SYMBOLS.has(cacheKey)) {
            const fallback = {
                symbol: cacheKey,
                price: this.getCachedPrice(cacheKey) || 0,
                priceChange24h: 0,
                baseAsset: cacheKey.replace(/USDT$/i, '') || 'BTC',
                quoteAsset: 'USDT',
                baseBalance: 0,
                quoteBalance: 0,
                filters: { tickSize: '0.01', stepSize: '0.00001', minNotional: '5' },
                ts: Date.now() / 1000
            };
            this.setCachedQuickData(cacheKey, fallback);
            return fallback;
        }
        
        try {
            if (!window.apiClient) throw new Error('apiClient not available');
            const url = `/api/spot/quick_data?account_id=${this.accountId}&symbol=${encodeURIComponent(cacheKey)}`;
            const data = await window.apiClient.get(url, { signal });
            if (data && data.ok === false && data.error_code === 'INVALID_SYMBOL') {
              const fallback = {
                symbol: cacheKey,
                price: this.getCachedPrice(cacheKey) || 0,
                priceChange24h: 0,
                baseAsset: cacheKey.replace(/USDT$/i, '') || 'BTC',
                quoteAsset: 'USDT',
                baseBalance: 0,
                quoteBalance: 0,
                filters: { tickSize: '0.01', stepSize: '0.00001', minNotional: '5' },
                ts: Date.now() / 1000
              };
              return fallback;
            }
            this.setCachedQuickData(cacheKey, data);
            if (data.price > 0) this.setCachedPrice(cacheKey, data.price);
            return data;
        } catch (error) {
            if (error.name === 'AbortError') {
                throw error;
            }
            console.error(`[SpotEngine] Quick data error for ${cacheKey}:`, error);
            // Return minimal data on error
            return {
                symbol: cacheKey,
                price: this.getCachedPrice(cacheKey) || 0,
                priceChange24h: 0,
                baseAsset: cacheKey.replace("USDT", ""),
                quoteAsset: "USDT",
                baseBalance: 0,
                quoteBalance: 0,
                filters: {
                    tickSize: "0.01",
                    stepSize: "0.00001",
                    minNotional: "5"
                },
                ts: Date.now() / 1000
            };
        }
    }
    
    // ============================================================
    // PRICE ONLY FETCH - Ultra Fast
    // ============================================================
    
    async fetchPrice(symbol, signal = null) {
        const cacheKey = symbol.toUpperCase();
        
        // Check cache first
        const cachedPrice = this.getCachedPrice(cacheKey);
        if (cachedPrice !== null) {
            return cachedPrice;
        }
        
        try {
            if (!window.apiClient) return this.getCachedPrice(cacheKey) || 0;
            const url = `/api/spot/price?account_id=${this.accountId}&symbol=${encodeURIComponent(cacheKey)}`;
            const data = await window.apiClient.get(url, { signal });
            const price = data.price || 0;
            
            if (price > 0) {
                this.setCachedPrice(cacheKey, price);
            }
            
            return price;
        } catch (error) {
            if (error.name === 'AbortError') {
                throw error;
            }
            // Return cached price if available, otherwise 0
            return this.getCachedPrice(cacheKey) || 0;
        }
    }
    
    // ============================================================
    // PLACE ORDER - Flash Hızlı
    // ============================================================
    
    async placeOrder(orderData, signal = null) {
        if (!window.apiClient) throw new Error('apiClient not available');
        try {
            const result = await window.apiClient.post('/api/spot/order', {
                account_id: this.accountId,
                ...orderData
            }, { signal, timeout: 20000 });
            // Invalidate balance cache after order
            this.cache.quickData.clear();
            return result;
        } catch (error) {
            if (error.name === 'AbortError') throw error;
            throw error;
        }
    }
    
    // ============================================================
    // LIVE UPDATES - Optimize Edilmiş
    // ============================================================
    
    startPriceUpdates(symbol, callback, interval = 500) {
        const key = `price_${symbol}`;
        
        // Stop existing if any
        this.stopUpdates(key);
        
        // Create abort controller
        const controller = new AbortController();
        this.abortControllers.set(key, controller);
        
        // Update immediately
        this.fetchPrice(symbol, controller.signal)
            .then(price => {
                if (price > 0) callback(price);
            })
            .catch(() => {});
        
        // Set interval
        const intervalId = setInterval(() => {
            if (controller.signal.aborted) {
                clearInterval(intervalId);
                return;
            }
            
            this.fetchPrice(symbol, controller.signal)
                .then(price => {
                    if (price > 0) callback(price);
                })
                .catch(() => {});
        }, interval);
        
        this.updateIntervals.set(key, intervalId);
    }
    
    startQuickDataUpdates(symbol, callback, interval = 2000) {
        const key = `quick_${symbol}`;
        
        // Stop existing if any
        this.stopUpdates(key);
        
        // Create abort controller
        const controller = new AbortController();
        this.abortControllers.set(key, controller);
        
        // Update immediately
        this.fetchQuickData(symbol, controller.signal)
            .then(data => callback(data))
            .catch(() => {});
        
        // Set interval
        const intervalId = setInterval(() => {
            if (controller.signal.aborted) {
                clearInterval(intervalId);
                return;
            }
            
            this.fetchQuickData(symbol, controller.signal)
                .then(data => callback(data))
                .catch(() => {});
        }, interval);
        
        this.updateIntervals.set(key, intervalId);
    }
    
    stopUpdates(key) {
        // Stop interval
        const intervalId = this.updateIntervals.get(key);
        if (intervalId) {
            clearInterval(intervalId);
            this.updateIntervals.delete(key);
        }
        
        // Abort requests
        const controller = this.abortControllers.get(key);
        if (controller) {
            controller.abort();
            this.abortControllers.delete(key);
        }
    }
    
    stopAllUpdates() {
        // Stop all intervals
        for (const intervalId of this.updateIntervals.values()) {
            clearInterval(intervalId);
        }
        this.updateIntervals.clear();
        
        // Abort all requests
        for (const controller of this.abortControllers.values()) {
            controller.abort();
        }
        this.abortControllers.clear();
    }
}

// Global instance
let spotEngineInstance = null;

function getSpotEngine(accountId) {
    if (!spotEngineInstance || spotEngineInstance.accountId !== accountId) {
        spotEngineInstance = new SpotEngine(accountId);
    }
    return spotEngineInstance;
}

