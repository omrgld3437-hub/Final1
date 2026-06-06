/**
 * FILE: core/intervalRegistry.js
 * VERSION: v1
 * DATE: 2026-01-23
 * CHANGE: Centralized interval management to prevent leaks
 * 
 * RULE: No direct setInterval() calls - use intervalRegistry
 */

const intervals = new Map(); // key -> { id, fn, ms, owner }
const timeouts = new Map(); // key -> { id, fn, ms, owner }

/**
 * Start interval with key (idempotent - same key won't create duplicate)
 */
function startInterval(key, fn, ms, owner = null) {
    // Stop existing if same key
    if (intervals.has(key)) {
        const existing = intervals.get(key);
        clearInterval(existing.id);
    }

    const id = setIntervalImpl(key, fn, ms, owner);
    return id;
}

/**
 * Register interval (Binance UI lifecycle).
 * Same key already registered → return; no duplicate.
 */
function register(key, ms, fn) {
    if (intervals.has(key)) {
        return;
    }
    setIntervalImpl(key, fn, ms, key);
}

/**
 * Unregister interval by key.
 */
function unregister(key) {
    return stopInterval(key);
}

function setIntervalImpl(key, fn, ms, owner) {
    const id = setInterval(() => {
        if (typeof document !== 'undefined' && document.visibilityState === 'hidden') {
            return;
        }
        try {
            fn();
        } catch (error) {
            console.error(`[intervalRegistry] Error in interval "${key}":`, error);
            stopInterval(key);
        }
    }, ms);

    intervals.set(key, { id, fn, ms, owner });
    return id;
}

/**
 * Stop interval by key
 */
function stopInterval(key) {
    if (intervals.has(key)) {
        const { id } = intervals.get(key);
        clearInterval(id);
        intervals.delete(key);
        return true;
    }
    return false;
}

/**
 * Stop all intervals owned by owner
 */
function stopByOwner(owner) {
    let stopped = 0;
    for (const [key, value] of intervals.entries()) {
        if (value.owner === owner) {
            clearInterval(value.id);
            intervals.delete(key);
            stopped++;
        }
    }
    return stopped;
}

/**
 * Stop all intervals
 */
function stopAll() {
    let stopped = 0;
    for (const [key, { id }] of intervals.entries()) {
        clearInterval(id);
        stopped++;
    }
    intervals.clear();
    return stopped;
}

/**
 * Get all active intervals (for debugging)
 */
function getActiveIntervals() {
    return Array.from(intervals.entries()).map(([key, value]) => ({
        key,
        owner: value.owner,
        ms: value.ms
    }));
}

/**
 * Start timeout with key (idempotent)
 */
function startTimeout(key, fn, ms, owner = null) {
    // Cancel existing if same key
    if (timeouts.has(key)) {
        const existing = timeouts.get(key);
        clearTimeout(existing.id);
    }

    const id = setTimeout(() => {
        timeouts.delete(key);
        try {
            fn();
        } catch (error) {
            console.error(`[intervalRegistry] Error in timeout "${key}":`, error);
        }
    }, ms);

    timeouts.set(key, { id, fn, ms, owner });
    return id;
}

/**
 * Cancel timeout by key
 */
function cancelTimeout(key) {
    if (timeouts.has(key)) {
        const { id } = timeouts.get(key);
        clearTimeout(id);
        timeouts.delete(key);
        return true;
    }
    return false;
}

/**
 * Cancel all timeouts owned by owner
 */
function cancelByOwner(owner) {
    let cancelled = 0;
    for (const [key, value] of timeouts.entries()) {
        if (value.owner === owner) {
            clearTimeout(value.id);
            timeouts.delete(key);
            cancelled++;
        }
    }
    return cancelled;
}

// Cleanup on page unload
window.addEventListener('beforeunload', () => {
    stopAll();
    for (const [key, { id }] of timeouts.entries()) {
        clearTimeout(id);
    }
    timeouts.clear();
});

// Export
window.intervalRegistry = {
    start: startInterval,
    stop: stopInterval,
    register,
    unregister,
    stopByOwner,
    stopAll,
    getActive: getActiveIntervals,
    timeout: {
        start: startTimeout,
        cancel: cancelTimeout,
        cancelByOwner
    }
};
