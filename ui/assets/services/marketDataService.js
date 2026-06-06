/**
 * FILE: services/marketDataService.js
 * VERSION: v1
 * DATE: 2026-01-23
 * CHANGE: Single market data service - idempotent, no duplicates
 * 
 * RULE: This is the ONLY source of market data. No other service/page should fetch market data.
 */

let isRunning = false;
let updateThrottleTimer = null;
let pendingUpdates = new Map(); // symbol -> data
const THROTTLE_MS = 200; // Batch updates every 200ms

/**
 * Start market data service (idempotent)
 * CRITICAL: Only one instance should run - prevents duplicate polling
 */
async function start() {
    if (window.__APP_PAGE__ !== 'dashboard') return;
    if (window.apiClient && typeof window.apiClient.hasToken === 'function' && !window.apiClient.hasToken()) return;
    if (isRunning) return;
    const activeIntervals = window.intervalRegistry?.getActive() || [];
    if (activeIntervals.some(i => i.key === 'marketDataService.poll')) return;

    isRunning = true;
    window.marketStore.setStatus('disconnected');

    // Start polling backend cache endpoint (/api/data/hub)
    // Backend now uses WebSocket stream, this just polls the cache snapshot
    startPolling();

    // Start throttle processor
    startThrottleProcessor();
}

/**
 * Stop market data service
 */
function stop() {
    if (!isRunning) {
        return;
    }

    isRunning = false;

    // Stop polling
    stopPolling();

    // Stop throttle
    if (updateThrottleTimer) {
        clearTimeout(updateThrottleTimer);
        updateThrottleTimer = null;
    }

    // Clear pending updates
    pendingUpdates.clear();

    window.marketStore.setStatus('disconnected');
}

/**
 * Check if service is running
 */
function isServiceRunning() {
    return isRunning;
}

/**
 * Start polling backend cache endpoint
 */
let pollingIntervalId = null;
let fetchInProgress = false;
let failCount = 0;
let retryTimeoutId = null;
const HUB_POLL_MS = 3000; // 3s: favori coin + alım satım fiyatları (log spam azaltma)
const POLL_INTERVAL_MS = HUB_POLL_MS;

function startPolling(skipInitial = false) {
    if (pollingIntervalId) return;
    if (!skipInitial) fetchMarketData();
    pollingIntervalId = window.intervalRegistry.start(
        'marketDataService.poll',
        fetchMarketData,
        POLL_INTERVAL_MS,
        'marketDataService'
    );
}

function stopPolling() {
    if (retryTimeoutId) {
        clearTimeout(retryTimeoutId);
        retryTimeoutId = null;
    }
    if (pollingIntervalId) {
        window.intervalRegistry.stop('marketDataService.poll');
        pollingIntervalId = null;
    }
}

/**
 * Fetch market data from backend cache endpoint.
 * Inflight guard + exponential backoff on error.
 */
async function fetchMarketData() {
    if (!isRunning) return;
    if (fetchInProgress) return;
    fetchInProgress = true;
    try {
        const data = await window.apiClient.get('/api/data/hub', { timeout: 8000 });
        const dataStatus = data.data_status || 'fresh';
        const staleReason = data.stale_reason;

        if (data.prices && typeof data.prices === 'object') {
            for (const [symbol, priceData] of Object.entries(data.prices)) {
                if (priceData && typeof priceData === 'object') {
                    pendingUpdates.set(symbol.toUpperCase(), {
                        price: priceData.price,
                        change24h: priceData.change24h,
                        volume24h: priceData.volume24h,
                        quoteVolume24h: priceData.quoteVolume24h
                    });
                } else if (typeof priceData === 'number') {
                    pendingUpdates.set(symbol.toUpperCase(), { price: priceData });
                }
            }
        }
        if (data.mini && typeof data.mini === 'object') {
            for (const [symbol, miniData] of Object.entries(data.mini)) {
                if (miniData && typeof miniData === 'object') {
                    pendingUpdates.set(symbol.toUpperCase(), {
                        price: miniData.last || miniData.price,
                        change24h: miniData.changePct,
                        volume24h: miniData.volume,
                        quoteVolume24h: miniData.quoteVolume,
                        marketCap: miniData.marketCap
                    });
                }
            }
        }
        if (data.coin_list && Array.isArray(data.coin_list)) {
            for (const coin of data.coin_list) {
                if (coin && coin.symbol) {
                    const symbol = coin.symbol.toUpperCase();
                    if (!pendingUpdates.has(symbol)) {
                        pendingUpdates.set(symbol, {
                            price: coin.price,
                            change24h: coin.change24h || coin.priceChangePercent,
                            volume24h: coin.volume24h || coin.volume,
                            quoteVolume24h: coin.quoteVolume24h || coin.quoteVolume,
                            marketCap: coin.marketCap || coin.marketCapApprox
                        });
                    }
                }
            }
        }

        if (dataStatus === 'fresh') window.marketStore.setStatus('connected');
        else if (dataStatus === 'stale') window.marketStore.setStatus('stale');
        else window.marketStore.setStatus('stale');
        if (typeof window.__DEBUG_MARKET__ !== 'undefined' && window.__DEBUG_MARKET__) console.count('hubTick');

        failCount = 0;
        window['marketDataService.errorCount'] = 0;
        if (retryTimeoutId) {
            clearTimeout(retryTimeoutId);
            retryTimeoutId = null;
        }
        if (!pollingIntervalId) startPolling(true);
    } catch (error) {
        const errorKey = 'marketDataService.errorCount';
        const errorCount = (window[errorKey] || 0) + 1;
        window[errorKey] = errorCount;
        if (typeof window.__DEBUG_MARKET__ !== 'undefined' && window.__DEBUG_MARKET__ && errorCount <= 5) {
            console.warn('[marketDataService] Fetch error (retry backoff):', error.error_code || error.message);
        }
        window.marketStore.setStatus('stale');
        if (window.errorReporter && (error.error_code !== 'TIMEOUT' || errorCount <= 3)) {
            window.errorReporter.report(error, { action: 'fetchMarketData' });
        }
        failCount++;
        stopPolling();
        const base = Math.min(30000, 2000 * Math.pow(2, Math.min(failCount, 4)));
        const jitter = Math.floor(Math.random() * 250);
        const delay = base + jitter;
        retryTimeoutId = setTimeout(() => {
            retryTimeoutId = null;
            fetchMarketData();
        }, delay);
    } finally {
        fetchInProgress = false;
    }
}

/**
 * Throttle processor: rAF + batch update + diff.
 * Keeps setTimeout callback light; heavy work in rAF. Single _notify per batch.
 */
function startThrottleProcessor() {
    if (updateThrottleTimer) return;

    function processPendingUpdates() {
        if (pendingUpdates.size === 0) {
            updateThrottleTimer = setTimeout(processPendingUpdates, THROTTLE_MS);
            return;
        }
        const updates = Array.from(pendingUpdates.entries());
        pendingUpdates.clear();

        requestAnimationFrame(() => {
            const store = window.marketStore;
            const filtered = [];
            for (const [symbol, data] of updates) {
                const s = (symbol || '').toUpperCase();
                if (!s) continue;
                const curPrice = store.getPrice(s);
                const curMini = store.getMini(s);
                const price = data.price != null && Number.isFinite(data.price) ? data.price : null;
                const changed = price != null && price !== curPrice
                    || (data.change24h != null || data.volume24h != null) && (
                        (curMini?.changePct !== data.change24h) ||
                        (curMini?.volume !== data.volume24h)
                    );
                if (changed || (price != null && curPrice == null) || (data.change24h != null && !curMini)) {
                    filtered.push([s, data]);
                }
            }
            if (filtered.length) store.batchUpdateFromService(filtered);
            updateThrottleTimer = setTimeout(processPendingUpdates, THROTTLE_MS);
        });
    }

    processPendingUpdates();
}

let binanceRefreshInFlight = false;

/**
 * Tab refresh – Binance kaldırıldı. Boş cüzdan/emir; coin-list sadece /api/data veya marketStore.
 */
async function refreshBinanceTabData(accountId) {
    if (!accountId) return;
    if (binanceRefreshInFlight) return;
    binanceRefreshInFlight = true;
    try {
        const walletPayload = {
            assets: [],
            totalUsd: null,
            freeUsd: null,
            lockedUsd: null,
            ts: Date.now(),
            error: null
        };
        if (window.marketStore) {
            window.marketStore.setWallet(walletPayload);
            window.marketStore.setOpenOrders([]);
        }
        let coinList = [];
        try {
            const res = await window.apiClient.get('/api/data/coin-list', { timeout: 8000 });
            if (res?.coins) coinList = res.coins;
        } catch (_) {}
        if (!coinList.length && window.marketStore && typeof window.marketStore.getAllMini === 'function') {
            const mini = window.marketStore.getAllMini() || [];
            coinList = mini.map(m => ({
                symbol: m.symbol,
                baseAsset: (m.symbol || '').replace(/USDT$|BTC$|ETH$|BNB$|FDUSD$|BUSD$/i, '') || m.symbol,
                price: m.last,
                priceChangePercent: m.changePct,
                volume: m.volume,
                quoteVolume: m.quoteVolume,
                marketCap: m.marketCap
            }));
        }
        if (window.marketStore) window.marketStore.setCoinList(coinList);
    } catch (e) {
        if (window.errorReporter) window.errorReporter.report(e, { action: 'refreshBinanceTabData', accountId });
    } finally {
        binanceRefreshInFlight = false;
    }
}

// Auto-start on page load (only once)
let autoStartAttempted = false;
function autoStart() {
    if (autoStartAttempted) return;
    autoStartAttempted = true;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            start();
        });
    } else {
        start();
    }
}

// Export
window.marketDataService = {
    start,
    stop,
    isRunning: isServiceRunning,
    refreshBinanceTabData
};

// Auto-start
autoStart();
