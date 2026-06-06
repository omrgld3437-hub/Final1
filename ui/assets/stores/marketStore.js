/**
 * FILE: stores/marketStore.js
 * VERSION: v1
 * DATE: 2026-01-23
 * CHANGE: Single source of truth for market data
 * 
 * RULE: UI pages read from marketStore, never fetch market data directly
 */

const marketStore = {
    // State
    prices: new Map(), // symbol -> number (last price)
    mini: new Map(), // symbol -> { last, open, changePct, volume, quoteVolume, marketCap }
    status: 'disconnected', // 'connected' | 'disconnected' | 'stale'
    lastUpdateTs: 0,
    activeSymbol: null,
    /** Binance tab: wallet summary + assets */
    wallet: null, // { assets, totalUsd, freeUsd, lockedUsd, ts, error }
    /** Binance tab: coin list from /api/data/coin-list */
    coinList: [],
    /** Binance tab: open orders (optional) */
    openOrders: [],

    // Subscribers (simple pub/sub)
    _subscribers: new Set(),

    /**
     * Subscribe to market data updates
     */
    subscribe(callback) {
        this._subscribers.add(callback);
        // Return unsubscribe function
        return () => {
            this._subscribers.delete(callback);
        };
    },

    /**
     * Notify all subscribers
     */
    _notify() {
        const state = this.getState();
        this._subscribers.forEach(callback => {
            try {
                callback(state);
            } catch (error) {
                console.error('[marketStore] Subscriber error:', error);
            }
        });
    },

    getState() {
        return {
            prices: this.prices,
            mini: this.mini,
            status: this.status,
            lastUpdateTs: this.lastUpdateTs,
            activeSymbol: this.activeSymbol,
            wallet: this.wallet,
            coinList: this.coinList,
            openOrders: this.openOrders
        };
    },

    setWallet(data) {
        this.wallet = data && typeof data === 'object' ? data : null;
        this._notify();
    },

    setCoinList(list) {
        this.coinList = Array.isArray(list) ? list : [];
        this._notify();
    },

    setOpenOrders(orders) {
        this.openOrders = Array.isArray(orders) ? orders : [];
        this._notify();
    },

    /**
     * Update price for symbol
     */
    updatePrice(symbol, price) {
        if (!symbol || price == null || !Number.isFinite(price)) {
            return;
        }

        const upperSymbol = symbol.toUpperCase();
        this.prices.set(upperSymbol, price);
        this.lastUpdateTs = Date.now();
        this._notify();
    },

    /**
     * Update mini ticker data for symbol
     */
    updateMini(symbol, data) {
        if (!symbol || !data) {
            return;
        }

        const upperSymbol = symbol.toUpperCase();
        this.mini.set(upperSymbol, {
            last: data.last || data.price || 0,
            open: data.open || 0,
            changePct: data.changePct || data.change24h || 0,
            volume: data.volume || data.volume24h || 0,
            quoteVolume: data.quoteVolume || data.quoteVolume24h || 0,
            marketCap: data.marketCap || 0
        });

        // Also update price if available
        if (data.last || data.price) {
            this.updatePrice(upperSymbol, data.last || data.price);
        }

        this.lastUpdateTs = Date.now();
        this._notify();
    },

    /**
     * Batch update prices
     */
    updatePrices(priceMap) {
        if (!priceMap || typeof priceMap !== 'object') {
            return;
        }

        let updated = false;
        for (const [symbol, price] of Object.entries(priceMap)) {
            if (symbol && price != null && Number.isFinite(price)) {
                this.prices.set(symbol.toUpperCase(), price);
                updated = true;
            }
        }

        if (updated) {
            this.lastUpdateTs = Date.now();
            this._notify();
        }
    },

    /**
     * Batch update mini tickers
     */
    updateMiniBatch(miniArray) {
        if (!Array.isArray(miniArray)) {
            return;
        }

        let updated = false;
        for (const item of miniArray) {
            if (item && item.symbol) {
                this.updateMini(item.symbol, item);
                updated = true;
            }
        }

        if (updated) {
            this.lastUpdateTs = Date.now();
        }
    },

    /**
     * Get price for symbol
     */
    getPrice(symbol) {
        if (!symbol) return null;
        return this.prices.get(symbol.toUpperCase()) || null;
    },

    /**
     * Get mini ticker for symbol
     */
    getMini(symbol) {
        if (!symbol) return null;
        return this.mini.get(symbol.toUpperCase()) || null;
    },

    /**
     * Get all prices as object
     */
    getAllPrices() {
        const result = {};
        for (const [symbol, price] of this.prices.entries()) {
            result[symbol] = price;
        }
        return result;
    },

    /**
     * Get all mini tickers as array
     */
    getAllMini() {
        return Array.from(this.mini.entries()).map(([symbol, data]) => ({
            symbol,
            ...data
        }));
    },

    /**
     * Set connection status
     */
    setStatus(status) {
        if (['connected', 'disconnected', 'stale'].includes(status)) {
            this.status = status;
            this._notify();
        }
    },

    /**
     * Set active symbol (for focused trading view)
     */
    setActiveSymbol(symbol) {
        this.activeSymbol = symbol ? symbol.toUpperCase() : null;
        this._notify();
    },

    /**
     * Clear all data
     */
    clear() {
        this.prices.clear();
        this.mini.clear();
        this.status = 'disconnected';
        this.lastUpdateTs = 0;
        this.activeSymbol = null;
        this.wallet = null;
        this.coinList = [];
        this.openOrders = [];
        this._notify();
    },

    /**
     * Check if data is stale (older than threshold)
     */
    isStale(thresholdMs = 10000) {
        if (this.lastUpdateTs === 0) return true;
        return Date.now() - this.lastUpdateTs > thresholdMs;
    },

    /**
     * Batch update from marketDataService: apply many symbols, _notify once.
     * Avoids 100+ _notify() per tick → fixes "long task" violation.
     */
    batchUpdateFromService(entries) {
        if (!entries || !entries.length) return;
        let updated = false;
        for (const [symbol, data] of entries) {
            const s = (symbol || '').toUpperCase();
            if (!s) continue;
            if (data.price != null && Number.isFinite(data.price)) {
                this.prices.set(s, data.price);
                updated = true;
            }
            if (data.change24h != null || data.volume24h != null || data.quoteVolume24h != null || data.marketCap != null) {
                const prev = this.mini.get(s);
                const last = data.price ?? prev?.last ?? 0;
                this.mini.set(s, {
                    last,
                    open: prev?.open ?? 0,
                    changePct: data.change24h ?? prev?.changePct ?? 0,
                    volume: data.volume24h ?? prev?.volume ?? 0,
                    quoteVolume: data.quoteVolume24h ?? prev?.quoteVolume ?? 0,
                    marketCap: data.marketCap ?? prev?.marketCap ?? 0
                });
                updated = true;
            }
        }
        if (updated) {
            this.lastUpdateTs = Date.now();
            this._notify();
        }
    }
};

// Export
window.marketStore = marketStore;
