/**
 * FILE: stores/botStore.js
 * VERSION: v1
 * DATE: 2026-01-23
 * CHANGE: Bot data store
 */

const botStore = {
    // State
    bots: [], // Array of bot objects
    botDetails: new Map(), // bot_id -> bot detail object
    lastUpdate: 0,

    // Subscribers
    _subscribers: new Set(),

    /**
     * Subscribe to bot data updates
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
                    bots: this.bots,
                    botDetails: this.botDetails,
                    lastUpdate: this.lastUpdate
                });
            } catch (error) {
                console.error('[botStore] Subscriber error:', error);
            }
        });
    },

    /**
     * Set bots list
     */
    setBots(bots) {
        this.bots = Array.isArray(bots) ? bots : [];
        this.lastUpdate = Date.now();
        this._notify();
    },

    /**
     * Update single bot
     */
    updateBot(bot) {
        if (!bot || !bot.id) return;

        // Update in list
        const index = this.bots.findIndex(b => b.id === bot.id);
        if (index >= 0) {
            this.bots[index] = { ...this.bots[index], ...bot };
        } else {
            this.bots.push(bot);
        }

        this.lastUpdate = Date.now();
        this._notify();
    },

    /**
     * Set bot detail
     */
    setBotDetail(botId, detail) {
        this.botDetails.set(botId, detail);
        this._notify();
    },

    /**
     * Get bot by ID
     */
    getBot(botId) {
        return this.bots.find(b => b.id === botId) || null;
    },

    /**
     * Get bot detail
     */
    getBotDetail(botId) {
        return this.botDetails.get(botId) || null;
    },

    /**
     * Clear all data
     */
    clear() {
        this.bots = [];
        this.botDetails.clear();
        this.lastUpdate = 0;
        this._notify();
    }
};

// Export
window.botStore = botStore;
