/**
 * FILE: stores/financeStore.js
 * VERSION: v1
 * DATE: 2026-01-23
 * CHANGE: Finance data store with data_status support
 */

const financeStore = {
    // State
    summary: null,
    equityCurve: null,
    trades: null,
    bots: null,
    
    // Metadata
    lastSummaryUpdate: 0,
    lastEquityUpdate: 0,
    dataStatus: null, // 'fresh' | 'stale' | 'empty'
    
    // Subscribers
    _subscribers: new Set(),

    /**
     * Subscribe to finance data updates
     */
    subscribe(callback) {
        this._subscribers.add(callback);
        return () => {
            this._subscribers.delete(callback);
        };
    },

    /**
     * Notify subscribers
     */
    _notify() {
        this._subscribers.forEach(callback => {
            try {
                callback({
                    summary: this.summary,
                    equityCurve: this.equityCurve,
                    trades: this.trades,
                    bots: this.bots,
                    dataStatus: this.dataStatus
                });
            } catch (error) {
                console.error('[financeStore] Subscriber error:', error);
            }
        });
    },

    /**
     * Update summary
     */
    setSummary(data, dataStatus = null) {
        this.summary = data;
        this.lastSummaryUpdate = Date.now();
        if (dataStatus) {
            this.dataStatus = dataStatus;
        }
        this._notify();
    },

    /**
     * Update equity curve
     */
    setEquityCurve(data, dataStatus = null) {
        this.equityCurve = data;
        this.lastEquityUpdate = Date.now();
        if (dataStatus) {
            this.dataStatus = dataStatus;
        }
        this._notify();
    },

    /**
     * Update trades
     */
    setTrades(data) {
        this.trades = data;
        this._notify();
    },

    /**
     * Update bots
     */
    setBots(data) {
        this.bots = data;
        this._notify();
    },

    /**
     * Clear all data
     */
    clear() {
        this.summary = null;
        this.equityCurve = null;
        this.trades = null;
        this.bots = null;
        this.lastSummaryUpdate = 0;
        this.lastEquityUpdate = 0;
        this.dataStatus = null;
        this._notify();
    }
};

// Export
window.financeStore = financeStore;
