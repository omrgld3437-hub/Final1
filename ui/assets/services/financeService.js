/**
 * FILE: services/financeService.js
 * VERSION: v1
 * DATE: 2026-01-23
 * CHANGE: Finance service - no spam, manual refresh only
 */

/**
 * Get finance summary (called once when tab opens)
 */
async function getSummary(accountId) {
    try {
        const data = await window.apiClient.get(`/api/finance/summary?account_id=${accountId}`);
        
        // Check data_status
        const dataStatus = data.data_status || 'fresh';
        
        window.financeStore.setSummary(data, dataStatus);
        
        return data;
    } catch (error) {
        window.errorReporter.report(error, { tab: 'finance', account_id: accountId, action: 'getSummary' });
        throw error;
    }
}

/**
 * Get equity curve (called once when tab opens)
 */
async function getEquityCurve(accountId, range = '30d') {
    try {
        const data = await window.apiClient.get(`/api/finance/equity-curve?account_id=${accountId}&range=${range}`);
        
        // Check data_status
        const dataStatus = data.data_status || 'fresh';
        
        window.financeStore.setEquityCurve(data, dataStatus);
        
        return data;
    } catch (error) {
        window.errorReporter.report(error, { tab: 'finance', account_id: accountId, action: 'getEquityCurve' });
        throw error;
    }
}

/**
 * Sync finance data now (manual refresh)
 */
async function syncNow(accountId) {
    try {
        // Call sync endpoint if available
        await window.apiClient.post(`/api/finance/sync?account_id=${accountId}`);
        
        // Then refresh summary and equity curve
        await Promise.all([
            getSummary(accountId),
            getEquityCurve(accountId)
        ]);
    } catch (error) {
        window.errorReporter.report(error, { tab: 'finance', account_id: accountId, action: 'syncNow' });
        throw error;
    }
}

/**
 * Get finance trades
 */
async function getTrades(accountId, page = 1, limit = 50) {
    try {
        const data = await window.apiClient.get(`/api/finance/trades?account_id=${accountId}&page=${page}&limit=${limit}`);
        window.financeStore.setTrades(data);
        return data;
    } catch (error) {
        window.errorReporter.report(error, { tab: 'finance', account_id: accountId, action: 'getTrades' });
        throw error;
    }
}

/**
 * Get finance bots
 */
async function getBots(accountId) {
    try {
        const data = await window.apiClient.get(`/api/finance/bots?account_id=${accountId}`);
        window.financeStore.setBots(data.bots || []);
        return data;
    } catch (error) {
        window.errorReporter.report(error, { tab: 'finance', account_id: accountId, action: 'getBots' });
        throw error;
    }
}

// Export
window.financeService = {
    getSummary,
    getEquityCurve,
    syncNow,
    getTrades,
    getBots
};
