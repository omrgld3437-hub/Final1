/**
 * dashboardAccountScope.js — strict per-account UI state isolation.
 * Drops stale async responses and filters cached rows when account changes.
 */
(function (global) {
    'use strict';

    var _scopeGen = 0;
    var _activeAccountId = null;

    function normalizeAccountId(id) {
        if (id == null || id === '') return null;
        var n = Number(id);
        return Number.isFinite(n) && n > 0 ? n : null;
    }

    function getActiveAccountId() {
        var fromScope = normalizeAccountId(_activeAccountId);
        if (fromScope) return fromScope;
        var fromWindow = normalizeAccountId(global.__ACTIVE_ACCOUNT_ID);
        if (fromWindow) return fromWindow;
        if (global.State && global.State.accountId != null) {
            return normalizeAccountId(global.State.accountId);
        }
        return null;
    }

    function isActiveAccount(accountId) {
        var active = getActiveAccountId();
        var check = normalizeAccountId(accountId);
        if (!active || !check) return false;
        return active === check;
    }

    function getScopeGeneration() {
        return _scopeGen;
    }

    function isScopeGenerationCurrent(gen, accountId) {
        if (!isActiveAccount(accountId)) return false;
        if (gen == null || gen === undefined) return true;
        return Number(gen) === Number(_scopeGen);
    }

    function rejectStaleAccountResponse(accountId, context) {
        if (isActiveAccount(accountId)) return false;
        if (typeof console !== 'undefined' && console.warn) {
            console.warn(
                '[account-scope] dropped stale response',
                context || '',
                { expected: getActiveAccountId(), got: normalizeAccountId(accountId) }
            );
        }
        return true;
    }

    function extractAccountIdFromPayload(data) {
        if (!data || typeof data !== 'object') return null;
        var acc = data.account
            || (data.kpis && data.kpis.account)
            || (data.kpis && typeof data.kpis === 'object' ? data.kpis : null)
            || {};
        return normalizeAccountId(
            data.account_id
            || acc.account_id
            || acc.id
            || acc.accountId
        );
    }

    function filterBotsForAccount(bots, accountId) {
        var aid = normalizeAccountId(accountId || getActiveAccountId());
        if (!aid || !Array.isArray(bots)) return [];
        return bots.filter(function (bot) {
            if (!bot || typeof bot !== 'object') return false;
            if (bot.account_id == null || bot.account_id === '') return false;
            return Number(bot.account_id) === aid;
        });
    }

    function clearBotListDom() {
        ['financeBotsList', 'financeBotsListBots', 'botsListBody', 'mevcutBotlarList'].forEach(function (id) {
            var el = global.document && global.document.getElementById(id);
            if (el) el.innerHTML = '';
        });
    }

    function resetInMemoryAccountState() {
        if (global.State && typeof global.State === 'object') {
            global.State.bots = [];
            global.State.summary = null;
            global.State.botLiveEquity = {};
            global.State.lastSummaryHash = '';
            global.State.inFlight = false;
        }
    }

    function resetAccountScopedUiState(reason) {
        resetInMemoryAccountState();
        clearBotListDom();
        if (typeof global.stopDashboardSSE === 'function') {
            try { global.stopDashboardSSE(); } catch (e) { /* ignore */ }
        }
        if (typeof console !== 'undefined' && console.info && reason) {
            console.info('[account-scope] reset UI state', reason);
        }
    }

    /**
     * Call when dashboard resolves the active account (URL/admin switch).
     * Bumps generation so in-flight responses for the previous account are ignored.
     */
    function activateAccountScope(accountId, opts) {
        opts = opts || {};
        var id = normalizeAccountId(accountId);
        if (!id) return _scopeGen;
        var prev = getActiveAccountId();
        var changed = prev !== id;
        if (changed || opts.forceReset) {
            _scopeGen += 1;
            resetAccountScopedUiState(changed ? ('account ' + prev + ' -> ' + id) : 'force');
        }
        _activeAccountId = id;
        global.__ACTIVE_ACCOUNT_ID = id;
        global.__DASHBOARD_ACCOUNT_SCOPE_GEN = _scopeGen;
        if (global.State && typeof global.State === 'object') {
            global.State.accountId = id;
        }
        return _scopeGen;
    }

    function guardBotsBeforeRender(bots, accountId, context) {
        var aid = normalizeAccountId(accountId || getActiveAccountId());
        if (!aid) return [];
        if (rejectStaleAccountResponse(aid, context || 'guardBotsBeforeRender')) return [];
        var filtered = filterBotsForAccount(bots, aid);
        if (Array.isArray(bots) && bots.length && filtered.length !== bots.length) {
            if (typeof console !== 'undefined' && console.warn) {
                console.warn('[account-scope] removed cross-account bots', {
                    context: context || '',
                    accountId: aid,
                    before: bots.length,
                    after: filtered.length
                });
            }
        }
        return filtered;
    }

    function guardPayloadForActiveAccount(data, context) {
        if (!data || typeof data !== 'object') return null;
        var payloadAccountId = extractAccountIdFromPayload(data);
        var active = getActiveAccountId();
        if (payloadAccountId && active && payloadAccountId !== active) {
            rejectStaleAccountResponse(payloadAccountId, context || 'guardPayload');
            return null;
        }
        if (!active) return data;
        if (Array.isArray(data.bots)) {
            data.bots = filterBotsForAccount(data.bots, active);
        }
        return data;
    }

    global.DashboardAccountScope = {
        normalizeAccountId: normalizeAccountId,
        getActiveAccountId: getActiveAccountId,
        isActiveAccount: isActiveAccount,
        getScopeGeneration: getScopeGeneration,
        isScopeGenerationCurrent: isScopeGenerationCurrent,
        rejectStaleAccountResponse: rejectStaleAccountResponse,
        extractAccountIdFromPayload: extractAccountIdFromPayload,
        filterBotsForAccount: filterBotsForAccount,
        activateAccountScope: activateAccountScope,
        resetAccountScopedUiState: resetAccountScopedUiState,
        guardBotsBeforeRender: guardBotsBeforeRender,
        guardPayloadForActiveAccount: guardPayloadForActiveAccount
    };
})(typeof window !== 'undefined' ? window : globalThis);
