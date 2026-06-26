/**
 * Per-bot health UI — page frame blink, status badges, engine-log rows (no top banner).
 * Critical / warn classes; deduped log rows; reset clears until re-fire; cleared alerts removed from log (no stale "çözüldü" rows).
 */
(function (global) {
    'use strict';

    var _lastDomSyncKey = '';
    var _lastHadActiveHealthUi = {};
    var _autoHealthAckTimerByBot = {};
    var LOG_REGISTRY_PREFIX = 'botHealthLogRegistry_';
    var ROW_STATE_PREFIX = 'botHealthRowState_v1_';
    var ROW_STATE_TTL_MS = 120000;

    var ALERT_PRIORITY = {
        LOOP_TASK_MISSING: 1000,
        BOT_CONTINUES_ON_ERROR: 980,
        TICK_STALE_CRIT: 950,
        INSUFFICIENT_BALANCE: 940,
        BOT_LOOP_AUTO_RESTART: 910,
        BINANCE_UNREACHABLE: 900,
        STATE_ERROR: 880,
        REPEATED_ORDER_FAIL: 850,
        TICK_STALE_WARN: 500,
        STATE_ERROR_WARN: 480,
        FIRST_BUY_STUCK: 450,
        PRICE_STALE_OR_MISSING: 420,
        REPEATED_LOCK_BUSY: 410,
        REPEATED_SLIPPAGE: 405,
        NO_TICK_YET: 400,
        CONNECTIVITY_DEGRADED: 390,
        LOT_SIZE: 300,
        MIN_NOTIONAL: 290,
        MIN_NOTIONAL_AFTER_CAP: 285,
        ORDER_FAILED: 200,
        INSUFFICIENT_QUOTE: 180,
        ORDER_TIMEOUT: 170
    };

    function storageGet(key) {
        try {
            return localStorage.getItem(key);
        } catch (e) {
            try {
                return sessionStorage.getItem(key);
            } catch (e2) {
                return null;
            }
        }
    }

    function storageSet(key, value) {
        try {
            localStorage.setItem(key, value);
            return;
        } catch (e) {}
        try {
            sessionStorage.setItem(key, value);
        } catch (e2) {}
    }

    function storageRemove(key) {
        try {
            localStorage.removeItem(key);
        } catch (e) {}
        try {
            sessionStorage.removeItem(key);
        } catch (e2) {}
    }

    function currentAccountKey() {
        try {
            var params = new URLSearchParams(global.location && global.location.search || '');
            var code = (params.get('account_code') || '').trim();
            if (code) return 'code:' + code;
            var id = (params.get('account_id') || '').trim();
            if (id) return 'id:' + id;
        } catch (e) {}
        return '';
    }

    function normalizeAccountKey(accountKey) {
        var key = String(accountKey || '').trim();
        if (!key) return currentAccountKey();
        if (key.indexOf('code:') === 0 || key.indexOf('id:') === 0) return key;
        return 'id:' + key;
    }

    function rowStateKey(accountKey) {
        var key = normalizeAccountKey(accountKey);
        return key ? ROW_STATE_PREFIX + key : '';
    }

    function readRowStateMap(accountKey) {
        try {
            var key = rowStateKey(accountKey);
            if (!key) return {};
            var raw = storageGet(key);
            if (!raw) return {};
            var data = JSON.parse(raw);
            return data && typeof data === 'object' ? data : {};
        } catch (e) {
            return {};
        }
    }

    function writeRowStateMap(accountKey, data) {
        var key = rowStateKey(accountKey);
        if (!key) return;
        try {
            storageSet(key, JSON.stringify(data || {}));
        } catch (e) {}
    }

    function setStoredRowAlert(botId, level, message, accountKey) {
        var id = String(botId || '');
        if (!id) return;
        var data = readRowStateMap(accountKey);
        if (level) {
            data[id] = {
                level: level,
                message: message || '',
                ts: Date.now()
            };
        } else {
            delete data[id];
        }
        writeRowStateMap(accountKey, data);
    }

    function getStoredRowAlerts(accountKey) {
        var data = readRowStateMap(accountKey);
        var now = Date.now();
        var out = {};
        var changed = false;
        Object.keys(data).forEach(function (botId) {
            var row = data[botId];
            var ts = Number(row && row.ts) || 0;
            if (!row || !row.level || !ts || now - ts > ROW_STATE_TTL_MS) {
                delete data[botId];
                changed = true;
                return;
            }
            out[botId] = {
                level: row.level,
                message: row.message || '',
                stored: true
            };
        });
        if (changed) writeRowStateMap(accountKey, data);
        return out;
    }

    function resetKey(botId) {
        return 'botHealthDismiss_' + String(botId || '');
    }

    function logRegistryKey(botId) {
        return LOG_REGISTRY_PREFIX + String(botId || '');
    }

    function loadLogRegistry(botId) {
        try {
            var raw = storageGet(logRegistryKey(botId));
            if (!raw) return { entries: {} };
            var data = JSON.parse(raw);
            return data && typeof data.entries === 'object' ? data : { entries: {} };
        } catch (e) {
            return { entries: {} };
        }
    }

    function saveLogRegistry(botId, reg) {
        try {
            storageSet(logRegistryKey(botId), JSON.stringify(reg || { entries: {} }));
        } catch (e) {}
    }

    function clearLogRegistry(botId) {
        storageRemove(logRegistryKey(botId));
    }

    function nextSyntheticId(reg) {
        var min = 0;
        Object.keys((reg && reg.entries) || {}).forEach(function (k) {
            var id = reg.entries[k].syntheticId;
            if (typeof id === 'number' && id < min) min = id;
        });
        return min - 1;
    }

    function alertLevel(a) {
        return String((a && a.level) || '').toLowerCase();
    }

    function isAccountWalletStaleAlert(alert) {
        var code = String((alert && (alert.code || alert.health_code || alert.error_code)) || '').toUpperCase();
        return code === 'WALLET_SNAPSHOT_STALE';
    }

    function isFreshLoopTaskMissingAlert(alert, healthSnapshot) {
        var code = String((alert && (alert.code || alert.health_code || alert.error_code)) || '').toUpperCase();
        if (code !== 'LOOP_TASK_MISSING') return false;
        var tickAge = Number(healthSnapshot && healthSnapshot.tick_age_s);
        if (!Number.isFinite(tickAge)) return false;
        var interval = Number(healthSnapshot && healthSnapshot.tick_interval_s);
        var threshold = Math.max(60, (Number.isFinite(interval) && interval > 0 ? interval : 2) * 5);
        return tickAge < threshold;
    }

    /** /health anlık görüntüsü sorunun bittiğini gösteriyorsa uyarıyı aktif sayma. */
    function isAlertResolvedByHealthSnapshot(alert, healthSnapshot) {
        if (!alert || !healthSnapshot) return false;
        var code = healthAlertCode(alert);
        if (healthSnapshot.connectivity_ok !== false && !healthSnapshot.connectivity_failure) {
            if (/^(BINANCE_UNREACHABLE|CONNECTIVITY_DEGRADED|SERVER_UNREACHABLE)$/.test(code)) return true;
        }
        var tickAge = Number(healthSnapshot.tick_age_s);
        var interval = Number(healthSnapshot.tick_interval_s) || 2;
        if (Number.isFinite(tickAge)) {
            if (code === 'TICK_STALE_CRIT' && tickAge < Math.max(300, interval * 12)) return true;
            if (code === 'TICK_STALE_WARN' && tickAge < Math.max(90, interval * 5)) return true;
        }
        if (code === 'LOOP_TASK_MISSING' && isFreshLoopTaskMissingAlert(alert, healthSnapshot)) return true;
        var meta = alert.meta || {};
        var errCode = String(meta.error_code || alert.error_code || '').toUpperCase();
        if (/^(BOT_CONTINUES_ON_ERROR|STATE_ERROR_WARN)$/.test(code)
            || /^(RUN_ACTION_EXCEPTION|BOT_TICK_EXCEPTION|BOT_LOOP_TRDCA_EXCEPTION|BOT_LOOP_TOPLEVEL_EXCEPTION)$/.test(errCode)) {
            if (Number.isFinite(tickAge) && tickAge < Math.max(90, interval * 5)) return true;
        }
        return false;
    }

    function healthAlertCode(alert) {
        return String((alert && (alert.code || alert.health_code || alert.error_code)) || '').toUpperCase();
    }

    function eventTimestampMs(ev) {
        var ts = ev && ev.ts ? new Date(ev.ts).getTime() : 0;
        return Number.isFinite(ts) ? ts : 0;
    }

    function eventResolvedHealthCode(ev) {
        var meta = (ev && ev.meta) || {};
        var code = String(meta.health_code || meta.error_code || '').toUpperCase();
        if (meta.health_resolved === true) return String(meta.health_code || code || '').toUpperCase();
        if (meta.connectivity_stable === true || code === 'CONNECTIVITY_STABLE' || code === 'CONNECTIVITY_RECOVERED') {
            return 'CONNECTIVITY_STABLE';
        }
        if (/bağlantı kuruldu|baglanti kuruldu|sorunsuz çalışıyor|sorunsuz calisiyor|tekrar aktif edildi|normal çalışmaya devam/i.test(String(ev && ev.message || ''))) {
            return 'CONNECTIVITY_STABLE';
        }
        return '';
    }

    function isRecoveryMatchForAlert(alertCode, recoveryCode) {
        if (!alertCode || !recoveryCode) return false;
        if (recoveryCode === alertCode) return true;
        if (recoveryCode === 'CONNECTIVITY_STABLE') {
            return /LOOP_TASK_MISSING|BOT_LOOP_AUTO_RESTART|BOT_CONTINUES_ON_ERROR|TICK_STALE_WARN|TICK_STALE_CRIT|CONNECTIVITY_DEGRADED|BINANCE_UNREACHABLE|SERVER_UNREACHABLE|STATE_ERROR|STATE_ERROR_WARN|RUN_ACTION_EXCEPTION/.test(alertCode);
        }
        return false;
    }

    function latestEventTimeForCode(events, code, matcher) {
        var latest = 0;
        (events || []).forEach(function (ev) {
            if (!matcher(ev, code)) return;
            var ts = eventTimestampMs(ev);
            if (ts > latest) latest = ts;
        });
        return latest;
    }

    function hasRecoveryAfterAlert(alert, recentEvents) {
        var code = healthAlertCode(alert);
        if (!code || !(recentEvents || []).length) return false;
        var latestProblem = latestEventTimeForCode(recentEvents, code, function (ev, c) {
            return resolveEventLogCode(ev) === c || eventHealthCode(ev) === c;
        });
        var latestRecovery = latestEventTimeForCode(recentEvents, code, function (ev, c) {
            return isRecoveryMatchForAlert(c, eventResolvedHealthCode(ev));
        });
        return latestRecovery > 0 && latestRecovery >= latestProblem;
    }

    function normalizeActiveAlerts(alerts, healthSnapshot, recentEvents) {
        return (alerts || []).filter(function (a) {
            return a
                && !isAccountWalletStaleAlert(a)
                && !isFreshLoopTaskMissingAlert(a, healthSnapshot)
                && !isAlertResolvedByHealthSnapshot(a, healthSnapshot)
                && !hasRecoveryAfterAlert(a, recentEvents || []);
        });
    }

    function alertSortKey(a) {
        var lv = alertLevel(a);
        var base = ALERT_PRIORITY[a && a.code] || (lv === 'critical' ? 600 : 300);
        if (lv === 'critical') base += 50;
        return base;
    }

    function getDismissInfo(botId) {
        try {
            var raw = storageGet(resetKey(botId));
            if (!raw) return null;
            var data = JSON.parse(raw);
            if (!data || !data.ts) return null;
            return {
                ts: data.ts,
                codes: Array.isArray(data.codes) ? data.codes : [],
                codeDismissTs: data.codeDismissTs && typeof data.codeDismissTs === 'object' ? data.codeDismissTs : {},
                maxEventId: data.maxEventId != null ? Number(data.maxEventId) : 0,
                perCodeMaxEventId: data.perCodeMaxEventId && typeof data.perCodeMaxEventId === 'object'
                    ? data.perCodeMaxEventId
                    : {}
            };
        } catch (e) {
            return null;
        }
    }

    function maxConnectivityEventId(events) {
        var max = 0;
        (events || []).forEach(function (ev) {
            if (!isConnectivityLogEvent(ev)) return;
            if (ev.meta && ev.meta.synthetic_live) return;
            var id = ev && ev.id != null ? Number(ev.id) : 0;
            if (Number.isFinite(id) && id > max) max = id;
        });
        return max;
    }

    function maxAllEventId(events) {
        var max = 0;
        (events || []).forEach(function (ev) {
            var id = ev && ev.id != null ? Number(ev.id) : 0;
            if (Number.isFinite(id) && id > max) max = id;
        });
        return max;
    }

    function maxDismissAnchorEventId(events) {
        return Math.max(
            maxResettableEventId(events || []),
            maxConnectivityEventId(events || []),
            maxAllEventId(events || [])
        );
    }

    function resolveEventLogCode(ev) {
        if (!ev) return '';
        var meta = (ev && ev.meta) || {};
        var code = String(meta.health_code || meta.healthCode || meta.error_code || '').toUpperCase();
        if (code) return code;
        if (isResilienceLogEvent(ev)) {
            if (/BOT_LOOP|döngü sonlandı|yeniden başlatıyor/i.test(String(ev.message || ''))) {
                return 'BOT_LOOP_AUTO_RESTART';
            }
            if (/ensure_running_bots|LOOP_TASK/i.test(String(ev.message || ''))) {
                return 'LOOP_TASK_MISSING';
            }
            return 'BOT_LOOP_AUTO_RESTART';
        }
        return '';
    }

    function buildPerCodeMaxEventId(events) {
        var per = {};
        (events || []).forEach(function (ev) {
            if (!isResettableLogEvent(ev)) return;
            var code = resolveEventLogCode(ev);
            if (!code) return;
            var id = ev && ev.id != null ? Number(ev.id) : 0;
            if (!Number.isFinite(id) || id <= 0) return;
            if (!per[code] || id > per[code]) per[code] = id;
        });
        return per;
    }

    function setDismiss(botId, alerts, recentEvents) {
        var now = Date.now();
        var codeDismissTs = {};
        (alerts || []).forEach(function (a) {
            if (a && a.code) codeDismissTs[a.code] = now;
        });
        KNOWN_HEALTH_CODES.forEach(function (code) {
            codeDismissTs[code] = now;
        });
        var evs = recentEvents || [];
        var maxEventId = maxDismissAnchorEventId(evs);
        var perCodeMaxEventId = buildPerCodeMaxEventId(evs);
        Object.keys(perCodeMaxEventId).forEach(function (code) {
            if (!codeDismissTs[code]) codeDismissTs[code] = now;
        });
        try {
            storageSet(resetKey(botId), JSON.stringify({
                ts: now,
                codes: Object.keys(codeDismissTs),
                codeDismissTs: codeDismissTs,
                maxEventId: maxEventId,
                perCodeMaxEventId: perCodeMaxEventId
            }));
        } catch (e) {}
    }

    var KNOWN_HEALTH_CODES = [
        'STATE_ERROR_WARN', 'STATE_ERROR', 'REPEATED_ORDER_FAIL',
        'TICK_STALE_WARN', 'TICK_STALE_CRIT', 'NO_TICK_YET',
        'FIRST_BUY_STUCK', 'LOOP_TASK_MISSING', 'BINANCE_UNREACHABLE', 'SERVER_UNREACHABLE',
        'LOT_SIZE', 'MIN_NOTIONAL', 'MIN_NOTIONAL_AFTER_CAP', 'ORDER_FAILED',
        'INSUFFICIENT_QUOTE', 'ORDER_TIMEOUT', 'INSUFFICIENT_BALANCE',
        'BOT_CONTINUES_ON_ERROR', 'BOT_LOOP_AUTO_RESTART', 'PRICE_STALE_OR_MISSING',
        'REPEATED_LOCK_BUSY', 'REPEATED_SLIPPAGE', 'CONNECTIVITY_DEGRADED',
        'OUTAGE_RECOVERY', 'RUN_ACTION_EXCEPTION'
    ];

    var RESETTABLE_SKIP = {
        ORDER_FAILED: 1,
        LOT_SIZE: 1,
        MIN_NOTIONAL: 1,
        MIN_NOTIONAL_AFTER_CAP: 1,
        INSUFFICIENT_QUOTE: 1,
        ORDER_TIMEOUT: 1,
        BINANCE_FREE_QUOTE_INSUFFICIENT: 1,
        BINANCE_FREE_BASE_INSUFFICIENT: 1,
        WEIGHT_DENIED: 1,
        INVALID_ACTION: 1
    };

    function isConnectivityLogEvent(ev) {
        if (!ev) return false;
        var meta = (ev && ev.meta) || {};
        var code = String(meta.error_code || meta.health_code || '').toUpperCase();
        if (/API_UNAUTHORIZED|BINANCE_UNREACHABLE|BINANCE_RATE|ACCOUNT_KEYS|CONNECTIVITY_RECOVERED|CONNECTIVITY_PAUSED/.test(code)) {
            return true;
        }
        return /binance|beyaz liste|401|-2015|ulaşılamıyor|api anahtar|tekrar aktif edildi|beklemeye alındı/i.test(String(ev.message || ''));
    }

    function isReconnectLogEvent(ev) {
        if (!ev) return false;
        var meta = ev.meta || {};
        var code = String(meta.error_code || '').toUpperCase();
        if (code === 'CONNECTIVITY_RECOVERED' || code === 'CONNECTIVITY_STABLE' || code === 'CONNECTIVITY_PAUSED') return true;
        return /tekrar aktif edildi|beklemeye alındı/i.test(String(ev.message || ''));
    }

    /** Döngü yeniden başlatma / ensure_running_bots — Reset ile gizlenir, yeni olay sonra tekrar görünür. */
    function isResilienceLogEvent(ev) {
        if (!ev) return false;
        var meta = (ev && ev.meta) || {};
        if (meta.event_kind === 'BOT_RESILIENCE') return true;
        var code = String(meta.health_code || meta.error_code || '').toUpperCase();
        if (code === 'BOT_LOOP_AUTO_RESTART' || code === 'LOOP_TASK_MISSING' || code === 'BOT_CONTINUES_ON_ERROR') {
            return true;
        }
        var raw = String(ev.message || '');
        return /Dayanıklılık:/i.test(raw) || /döngü yeniden başlatılıyor/i.test(raw)
            || /ensure_running_bots/i.test(raw);
    }

    function isResettableLogEvent(ev) {
        if (!ev) return false;
        if (isResilienceLogEvent(ev)) return true;
        var ty = (ev.type || '').toUpperCase();
        if (ty === 'INFO') {
            if (isReconnectLogEvent(ev)) return true;
            var infoMeta = ev.meta || {};
            if (String(infoMeta.health_code || '').toUpperCase() === 'OUTAGE_RECOVERY') return true;
            var infoRaw = String(ev.message || '');
            if (/kopma sonrası|devam ediyor.*kopma|Bağlantı\/tick boşluğu|grid değerlendirmesi/i.test(infoRaw)) return true;
        }
        if (ty === 'ERROR') {
            if (isConnectivityLogEvent(ev)) return true;
            var errMeta = ev.meta || {};
            var errCode = String(errMeta.error_code || errMeta.health_code || '').toUpperCase();
            if (/^(RUN_ACTION_EXCEPTION|BOT_LOOP_TOPLEVEL_EXCEPTION|BOT_LOOP_TRDCA_EXCEPTION|BOT_TICK_EXCEPTION)$/.test(errCode)) {
                return true;
            }
            var errRaw = String(ev.message || '');
            if (/RUN_ACTION_EXCEPTION|BOT_LOOP|BOT_TICK/i.test(errRaw)) return true;
        }
        if (ty === 'HEALTH_WARN' || ty === 'HEALTH_CRITICAL') return true;
        if (ty === 'SLIPPAGE_WARN') return true;
        if (ty === 'SKIP_REASON') {
            var meta = ev.meta || {};
            var skip = String(meta.skip_reason || meta.error_code || '').toUpperCase();
            if (RESETTABLE_SKIP[skip]) return true;
            var raw = String(ev.message || '').toUpperCase();
            return /ORDER_FAILED|MIN_NOTIONAL|LOT_SIZE|INSUFFICIENT_QUOTE|ORDER_TIMEOUT/i.test(raw);
        }
        return false;
    }

    function isHealthEventType(ty) {
        ty = (ty || '').toUpperCase();
        return ty === 'HEALTH_WARN' || ty === 'HEALTH_CRITICAL';
    }

    function eventHealthCode(ev) {
        var meta = (ev && ev.meta) || {};
        return meta.health_code || meta.healthCode || '';
    }

    function maxResettableEventId(events) {
        var max = 0;
        (events || []).forEach(function (ev) {
            if (!isResettableLogEvent(ev)) return;
            var id = ev && ev.id != null ? Number(ev.id) : 0;
            if (Number.isFinite(id) && id > max) max = id;
        });
        return max;
    }

    function maxHealthEventId(events) {
        var max = 0;
        (events || []).forEach(function (ev) {
            if (!isHealthEventType(ev && ev.type)) return;
            var id = ev && ev.id != null ? Number(ev.id) : 0;
            if (id > max) max = id;
        });
        return max;
    }

    function hasHealthEventForCodeAfterId(events, code, afterId) {
        if (!code) return false;
        afterId = Number(afterId) || 0;
        for (var i = 0; i < (events || []).length; i++) {
            var ev = events[i];
            if (!isHealthEventType(ev && ev.type)) continue;
            if (eventHealthCode(ev) !== code) continue;
            var id = ev && ev.id != null ? Number(ev.id) : 0;
            if (id > afterId) return true;
        }
        return false;
    }

    function hasLogEventForCodeAfterId(events, code, afterId) {
        if (!code) return false;
        afterId = Number(afterId) || 0;
        for (var i = 0; i < (events || []).length; i++) {
            var ev = events[i];
            if (!ev) continue;
            var match = false;
            if (isHealthEventType(ev.type) && eventHealthCode(ev) === code) match = true;
            else if (isResilienceLogEvent(ev) && resolveEventLogCode(ev) === code) match = true;
            if (!match) continue;
            var id = ev && ev.id != null ? Number(ev.id) : 0;
            if (Number.isFinite(id) && id > afterId) return true;
        }
        return false;
    }

    function perCodeDismissAnchor(dismissInfo, code) {
        if (!dismissInfo || !code) return dismissInfo.maxEventId != null ? Number(dismissInfo.maxEventId) : 0;
        var per = dismissInfo.perCodeMaxEventId || {};
        if (per[code] != null) return Number(per[code]);
        return dismissInfo.maxEventId != null ? Number(dismissInfo.maxEventId) : 0;
    }

    function getServerDismissBeforeId(healthData) {
        if (!healthData) return 0;
        var n = Number(healthData.engine_log_dismiss_before_id);
        return Number.isFinite(n) && n > 0 ? n : 0;
    }

    function isActiveConnectivitySnapshotAlert(alert, healthSnapshot) {
        if (!alert || !healthSnapshot) return false;
        if (healthSnapshot.connectivity_ok !== false && !healthSnapshot.connectivity_failure) return false;
        var code = healthAlertCode(alert);
        var meta = alert.meta || {};
        var errCode = String(
            meta.error_code
            || alert.error_code
            || (healthSnapshot.connectivity_failure && (healthSnapshot.connectivity_failure.error_code || healthSnapshot.connectivity_failure.code))
            || ''
        ).toUpperCase();
        return /^(BINANCE_UNREACHABLE|API_UNAUTHORIZED|ACCOUNT_KEYS_EMPTY|ACCOUNT_KEYS_DECRYPT_FAIL|ACCOUNT_KEYS_MISSING|CLOCK_DRIFT|BINANCE_RATE_LIMIT|STATE_ERROR|CONNECTIVITY_DEGRADED)$/.test(code)
            || /^(BINANCE_UNREACHABLE|API_UNAUTHORIZED|ACCOUNT_KEYS_EMPTY|ACCOUNT_KEYS_DECRYPT_FAIL|ACCOUNT_KEYS_MISSING|CLOCK_DRIFT|BINANCE_RATE_LIMIT)$/.test(errCode);
    }

    function effectiveGlobalDismissAnchor(dismissInfo, healthData) {
        var local = dismissInfo && dismissInfo.maxEventId != null ? Number(dismissInfo.maxEventId) : 0;
        var server = getServerDismissBeforeId(healthData);
        return Math.max(local, server);
    }

    function hasHealthEventForCodeAfterTs(events, code, afterTs) {
        if (!code) return false;
        afterTs = Number(afterTs) || 0;
        for (var i = 0; i < (events || []).length; i++) {
            var ev = events[i];
            if (!isHealthEventType(ev && ev.type)) continue;
            if (eventHealthCode(ev) !== code) continue;
            var t = ev.ts ? new Date(ev.ts).getTime() : 0;
            if (t > afterTs) return true;
        }
        return false;
    }

    function dismissTsForCode(dismissInfo, code) {
        if (!dismissInfo || !code) return 0;
        if (dismissInfo.codeDismissTs && dismissInfo.codeDismissTs[code] != null) {
            return Number(dismissInfo.codeDismissTs[code]);
        }
        if (dismissInfo.codes.indexOf(code) >= 0) return Number(dismissInfo.ts) || 0;
        return 0;
    }

    function hasConnectivityEventAfterId(events, afterId) {
        afterId = Number(afterId) || 0;
        for (var i = 0; i < (events || []).length; i++) {
            var ev = events[i];
            if (!isConnectivityLogEvent(ev)) continue;
            var id = ev && ev.id != null ? Number(ev.id) : 0;
            if (Number.isFinite(id) && id > afterId) return true;
        }
        return false;
    }

    function isAlertSuppressed(alert, dismissInfo, recentEvents, healthSnapshot) {
        if (!alert || !alert.code) return false;
        if (isActiveConnectivitySnapshotAlert(alert, healthSnapshot)) return false;
        var serverBefore = getServerDismissBeforeId(healthSnapshot);
        if (serverBefore > 0 && !hasLogEventForCodeAfterId(recentEvents, alert.code, serverBefore)) {
            return true;
        }
        if (!dismissInfo) return false;
        if (dismissInfo.codes.indexOf(alert.code) < 0) return false;
        var afterId = perCodeDismissAnchor(dismissInfo, alert.code);
        if (hasLogEventForCodeAfterId(recentEvents, alert.code, afterId)) {
            return false;
        }
        if (alert.code === 'BINANCE_UNREACHABLE' || alert.code === 'STATE_ERROR') {
            var globalAfter = dismissInfo.maxEventId != null ? Number(dismissInfo.maxEventId) : 0;
            if (hasConnectivityEventAfterId(recentEvents, globalAfter)) return false;
        }
        var dts = dismissTsForCode(dismissInfo, alert.code);
        if (hasHealthEventForCodeAfterTs(recentEvents, alert.code, dts)) {
            return false;
        }
        if (healthSnapshot && (healthSnapshot.alerts || []).some(function (a) {
            return a && a.code === alert.code;
        })) {
            var tickAge = Number(healthSnapshot.tick_age_s) || 0;
            if (alert.code === 'TICK_STALE_CRIT' && tickAge >= 300) return false;
            if (alert.code === 'TICK_STALE_WARN' && tickAge >= 90) return false;
        }
        return true;
    }

    function pickAllAlerts(alerts) {
        var sorted = (alerts || []).slice().sort(function (x, y) {
            return alertSortKey(y) - alertSortKey(x);
        });
        var warns = [];
        var criticals = [];
        sorted.forEach(function (a) {
            if (!a) return;
            var lv = alertLevel(a);
            if (lv === 'critical') criticals.push(a);
            else if (lv === 'warn') warns.push(a);
        });
        return { warns: warns, criticals: criticals };
    }

    function filterAlertsForUi(alerts, dismissInfo, recentEvents, healthSnapshot) {
        if (!alerts || !alerts.length) return { warns: [], criticals: [] };
        alerts = normalizeActiveAlerts(alerts, healthSnapshot, recentEvents);
        if (!alerts.length) return { warns: [], criticals: [] };
        if (!dismissInfo) return pickAllAlerts(alerts);
        var filtered = alerts.filter(function (a) {
            return a && !isAlertSuppressed(a, dismissInfo, recentEvents, healthSnapshot);
        });
        if (!filtered.length) return { warns: [], criticals: [] };
        return pickAllAlerts(filtered);
    }

    function topAlertMessage(list) {
        var a = list && list[0];
        if (!a) return '';
        return (a.message || a.title || '') + (a.cause ? '\n' + a.cause : '');
    }

    function entryKey(entry) {
        return String(entry.code || '') + '#' + String(entry.syntheticId != null ? entry.syntheticId : '');
    }

    function findActiveEntry(reg, code) {
        var found = null;
        Object.keys(reg.entries || {}).forEach(function (k) {
            var e = reg.entries[k];
            if (!e || e.code !== code || !e.active || e.dismissed) return;
            found = e;
        });
        return found;
    }

    function syncLogRegistry(botId, alerts, dismissInfo, recentEvents, healthSnapshot) {
        var reg = loadLogRegistry(botId);
        if (!reg.entries) reg.entries = {};

        var activeList = normalizeActiveAlerts(alerts || [], healthSnapshot, recentEvents).filter(function (a) {
            return a && a.code && !isAlertSuppressed(a, dismissInfo, recentEvents, healthSnapshot);
        });
        var activeCodes = {};
        activeList.forEach(function (a) {
            activeCodes[a.code] = a;
        });

        var now = Date.now();

        Object.keys(reg.entries).forEach(function (k) {
            var e = reg.entries[k];
            if (!e || e.dismissed) return;
            if (activeCodes[e.code]) return;
            if (e.active) {
                e.active = false;
                e.resolvedAt = now;
                e.resolvedEmitted = false;
            } else if (e.resolvedAt) {
                if (e.resolvedEmitted && now - e.resolvedAt > 120000) {
                    delete reg.entries[k];
                }
            } else {
                delete reg.entries[k];
            }
        });

        activeList.forEach(function (a) {
            var code = a.code;
            var e = findActiveEntry(reg, code);
            if (!e) {
                var neu = {
                    code: code,
                    level: alertLevel(a) || 'warn',
                    message: a.message || a.title || code,
                    cause: a.cause || '',
                    active: true,
                    resolvedAt: null,
                    firstSeen: now,
                    syntheticId: nextSyntheticId(reg)
                };
                reg.entries[entryKey(neu)] = neu;
                return;
            }
            e.active = true;
            e.resolvedAt = null;
            e.message = a.message || a.title || e.message;
            e.cause = a.cause || e.cause;
            e.level = alertLevel(a) || e.level;
        });

        saveLogRegistry(botId, reg);
        return reg;
    }

    function buildRegistrySynthetic(entry) {
        var ty = entry.level === 'critical' ? 'HEALTH_CRITICAL' : 'HEALTH_WARN';
        var ts = entry.resolvedAt
            ? new Date(entry.resolvedAt).toISOString()
            : new Date(entry.firstSeen || Date.now()).toISOString();
        return {
            id: entry.syntheticId,
            type: ty,
            ts: ts,
            message: entry.message,
            meta: {
                health_code: entry.code,
                health_ui_track: true,
                health_resolved: !entry.active,
                health_resolved_at: entry.resolvedAt || null,
                cause: entry.cause,
                title: entry.message
            }
        };
    }

    function buildRegistryResolvedSynthetic(entry) {
        var code = String(entry.code || '');
        var isConn = /CONNECTIVITY|BINANCE|API_UNAUTHORIZED|ACCOUNT_KEYS|TICK_STALE/.test(code);
        return {
            id: -(entry.syntheticId || 0) - 900000,
            type: 'INFO',
            ts: new Date(entry.resolvedAt || Date.now()).toISOString(),
            message: entry.message,
            meta: {
                health_code: entry.code,
                health_ui_track: true,
                health_resolved: true,
                recovery_report: isConn,
                connectivity_stable: isConn,
                error_code: isConn ? 'CONNECTIVITY_STABLE' : (code || 'HEALTH_RESOLVED'),
                title: isConn
                    ? 'Sorun giderildi · Bot normal çalışmaya devam ediyor'
                    : (entry.message || 'Sorun giderildi'),
                cycle_id: null
            }
        };
    }

    function hasRecentConnectivityStable(events, withinMs) {
        var cutoff = Date.now() - (withinMs || 45000);
        for (var i = 0; i < (events || []).length; i++) {
            var ev = events[i];
            var meta = ev.meta || {};
            var ec = String(meta.error_code || '').toUpperCase();
            if (ec !== 'CONNECTIVITY_STABLE' && meta.connectivity_stable !== true) continue;
            var ts = ev.ts ? new Date(ev.ts).getTime() : 0;
            if (ts >= cutoff) return true;
        }
        return false;
    }

    function hadRecentConnectivityIncident(events, withinMs) {
        withinMs = withinMs || 45 * 60 * 1000;
        var cutoff = Date.now() - withinMs;
        for (var i = 0; i < (events || []).length; i++) {
            var ev = events[i];
            if (!ev) continue;
            var meta = ev.meta || {};
            var ec = String(meta.error_code || meta.health_code || '').toUpperCase();
            var ty = String(ev.type || '').toUpperCase();
            if (meta.synthetic_live && (ec === 'SERVER_UNREACHABLE' || meta.source === 'server_unreachable')) {
                var st = ev.ts ? new Date(ev.ts).getTime() : Date.now();
                if (st >= cutoff) return true;
            }
            if (/CONNECTIVITY_PAUSED|CONNECTIVITY_LOST|BINANCE_UNREACHABLE|API_UNAUTHORIZED|ACCOUNT_KEYS/.test(ec)) {
                var ts1 = ev.ts ? new Date(ev.ts).getTime() : 0;
                if (!ts1 || ts1 >= cutoff) return true;
            }
            if (ty === 'HEALTH_CRITICAL' && /BINANCE|CONNECTIVITY|API_UNAUTHORIZED|ACCOUNT_KEYS/.test(ec)) {
                var ts2 = ev.ts ? new Date(ev.ts).getTime() : 0;
                if (!ts2 || ts2 >= cutoff) return true;
            }
            if (ty === 'ERROR' && /BINANCE|401|ulaşılamıyor|api anahtar/i.test(String(ev.message || '') + ' ' + ec)) {
                var ts3 = ev.ts ? new Date(ev.ts).getTime() : 0;
                if (!ts3 || ts3 >= cutoff) return true;
            }
        }
        return false;
    }

    function filterDismissedFromEvents(botId, events, healthData) {
        if (!botId) return events || [];
        var dismiss = getDismissInfo(botId);
        var list = events || [];
        if (!dismiss && !getServerDismissBeforeId(healthData)) return list;
        return list.filter(function (ev) {
            return !shouldHideResetLogEvent(ev, botId, list, healthData);
        });
    }

    function mergeHealthDisplayEvents(botId, events, healthData, running) {
        events = filterDismissedFromEvents(botId, events, healthData);
        if (!botId) return events;

        var alerts = normalizeActiveAlerts((healthData && healthData.alerts) ? healthData.alerts : [], healthData, events);
        var dismiss = getDismissInfo(botId);
        var reg = syncLogRegistry(botId, alerts, dismiss, events, healthData);

        var currentAlertCodes = {};
        alerts.forEach(function (a) {
            if (a && a.code) currentAlertCodes[a.code] = true;
        });

        var trackedCodes = {};
        Object.keys(reg.entries || {}).forEach(function (k) {
            var e = reg.entries[k];
            if (e && !e.dismissed && e.active && e.code) trackedCodes[e.code] = true;
        });

        var out = events.filter(function (ev) {
            if (!isHealthEventType(ev && ev.type)) return true;
            var code = eventHealthCode(ev);
            if (code && trackedCodes[code]) return false;
            if (code && KNOWN_HEALTH_CODES.indexOf(code) >= 0 && !currentAlertCodes[code]) return false;
            return true;
        });

        var synthetics = [];
        var registryDirty = false;
        Object.keys(reg.entries || {}).forEach(function (k) {
            var e = reg.entries[k];
            if (!e || e.dismissed) return;
            if (e.active) {
                synthetics.push(buildRegistrySynthetic(e));
            } else if (e.resolvedAt && !e.resolvedEmitted) {
                var code = String(e.code || '');
                if (code === 'SERVER_UNREACHABLE') {
                    e.resolvedEmitted = true;
                    registryDirty = true;
                    return;
                }
                var connCode = /CONNECTIVITY|BINANCE|API_UNAUTHORIZED|ACCOUNT_KEYS|TICK_STALE/.test(code);
                if (connCode && (
                    hasRecentConnectivityStable(events, 45000)
                    || !hadRecentConnectivityIncident(events, 45 * 60 * 1000)
                )) {
                    e.resolvedEmitted = true;
                    registryDirty = true;
                } else {
                    synthetics.push(buildRegistryResolvedSynthetic(e));
                    e.resolvedEmitted = true;
                    registryDirty = true;
                }
            }
        });
        if (registryDirty || synthetics.some(function (s) { return s.meta && s.meta.recovery_report; })) {
            saveLogRegistry(botId, reg);
        }

        return synthetics.concat(out);
    }

    function ensureShell() {
        var shell = document.getElementById('healthAlertShell');
        if (shell) return shell;
        shell = document.createElement('div');
        shell.id = 'healthAlertShell';
        shell.className = 'health-alert-shell';
        var critFrame = document.createElement('div');
        critFrame.id = 'healthCritPageFrame';
        critFrame.className = 'health-crit-page-frame';
        critFrame.setAttribute('aria-hidden', 'true');
        var warnFrame = document.createElement('div');
        warnFrame.id = 'healthWarnPageFrame';
        warnFrame.className = 'health-warn-page-frame';
        warnFrame.setAttribute('aria-hidden', 'true');
        shell.appendChild(critFrame);
        shell.appendChild(warnFrame);
        document.body.insertBefore(shell, document.body.firstChild);
        return shell;
    }

    function hideBanner() {
        var banner = document.getElementById('healthAlertBanner');
        if (banner) {
            banner.classList.remove('is-visible', 'health-alert-banner--critical', 'health-alert-banner--warn');
            banner.style.display = 'none';
        }
        if (document.body) {
            document.body.classList.remove('has-health-alert-banner');
            document.body.style.paddingTop = '';
        }
    }

    function syncShellState(warnActive, critActive) {
        ensureShell();
        var shell = document.getElementById('healthAlertShell');
        var critFrame = document.getElementById('healthCritPageFrame');
        var warnFrame = document.getElementById('healthWarnPageFrame');
        if (critFrame) critFrame.classList.toggle('is-visible', !!critActive);
        if (warnFrame) warnFrame.classList.toggle('is-visible', !!(warnActive && !critActive));
        if (shell) shell.classList.toggle('is-active', !!(warnActive || critActive));
    }

    function syncBotTopStripLayout(hasStripAlert) {
        var strip = document.getElementById('botTopStrip');
        var chartWrap = document.getElementById('botStripMiniChartWrap');
        var btnParam = document.getElementById('btnParametreler');
        var alertSlot = document.getElementById('botStripHealthBadges');
        if (strip) strip.classList.toggle('has-health-alerts', !!hasStripAlert);
        if (chartWrap) chartWrap.style.display = hasStripAlert ? 'none' : '';
        if (btnParam) btnParam.style.display = hasStripAlert ? 'none' : '';
        if (alertSlot) alertSlot.style.display = hasStripAlert ? 'flex' : 'none';
    }

    function syncDom(opts) {
        opts = opts || {};
        hideBanner();
        ensureShell();

        var warnBadge = document.getElementById('healthWarnBadge');
        var critBadge = document.getElementById('healthCriticalBadge');
        var running = !!opts.running;
        var warns = opts.warns || [];
        var criticals = opts.criticals || [];

        var hasCrit = running && criticals.length > 0;
        var hasWarn = running && warns.length > 0;

        if (warnBadge) {
            if (hasWarn) {
                warnBadge.style.display = 'inline-flex';
                warnBadge.textContent = 'Uyarı';
                warnBadge.title = topAlertMessage(warns);
            } else {
                warnBadge.style.display = 'none';
                warnBadge.title = '';
            }
        }
        if (critBadge) {
            if (hasCrit) {
                critBadge.style.display = 'inline-flex';
                critBadge.textContent = 'Kritik';
                critBadge.title = topAlertMessage(criticals);
            } else {
                critBadge.style.display = 'none';
                critBadge.title = '';
            }
        }

        syncBotTopStripLayout(hasWarn || hasCrit);

        var liveProblem = !!(global._botLiveProblem) && !opts.suppressLiveProblem;
        var connFailCode = global._lastConnectivityFailure && global._lastConnectivityFailure.error_code;
        var liveCrit = !hasCrit && !hasWarn && liveProblem && !!(connFailCode || global._serverUnreachable);
        var liveWarn = !hasCrit && !hasWarn && liveProblem && !liveCrit;
        var warnActive = hasWarn || (running && liveWarn);
        var critActive = hasCrit || (running && liveCrit);

        var syncKey = [
            running ? '1' : '0',
            critActive ? '1' : '0',
            warnActive ? '1' : '0',
            liveProblem ? '1' : '0',
            warns.map(function (w) { return w.code; }).join(','),
            criticals.map(function (c) { return c.code; }).join(',')
        ].join('|');
        if (syncKey === _lastDomSyncKey) {
            return;
        }
        _lastDomSyncKey = syncKey;

        syncShellState(warnActive, critActive);

        var engineLogPanel = document.getElementById('engineLogPanel');
        if (engineLogPanel) {
            engineLogPanel.classList.toggle('panel-health-log-active', warnActive || critActive);
        }
    }

    function hadActiveHealthRegistry(botId) {
        var reg = loadLogRegistry(botId);
        return Object.keys(reg.entries || {}).some(function (k) {
            var e = reg.entries[k];
            return e && e.active && !e.dismissed;
        });
    }

    function scheduleAutoHealthAck(botId) {
        var id = String(botId || '');
        if (!id) return;
        if (_autoHealthAckTimerByBot[id]) {
            clearTimeout(_autoHealthAckTimerByBot[id]);
        }
        _autoHealthAckTimerByBot[id] = setTimeout(function () {
            _autoHealthAckTimerByBot[id] = null;
            if (typeof global.scheduleAutoHealthAck === 'function') {
                global.scheduleAutoHealthAck(botId);
            }
        }, 900);
    }

    /** Sorun çözüldüyse Resetle ile aynı UI temizliği (manuel tık gerekmez). */
    function autoClearResolvedHealthState(botId, rawAlerts, recentEvents, healthData) {
        var id = String(botId || '');
        if (!id) return false;
        var normalized = normalizeActiveAlerts(rawAlerts || [], healthData, recentEvents || []);
        if (normalized.length > 0) return false;

        var hadRegistry = hadActiveHealthRegistry(id);
        var hadUi = hadRegistry
            || _lastHadActiveHealthUi[id] === true
            || !!(global._botLiveProblem)
            || !!(global._botBlockingStatus);
        if (!hadUi) return false;

        clearLogRegistry(id);
        if (healthData && healthData.connectivity_ok !== false && !healthData.connectivity_failure) {
            global._lastConnectivityFailure = null;
        }
        if (typeof global.clearBotBlockingStatus === 'function') {
            global.clearBotBlockingStatus();
        } else {
            global._botBlockingStatus = null;
        }
        global._botLiveProblem = false;
        _lastDomSyncKey = '';
        setDismiss(id, rawAlerts || [], recentEvents || []);
        scheduleAutoHealthAck(id);
        if (typeof global.onBotHealthAutoCleared === 'function') {
            global.onBotHealthAutoCleared(botId);
        }
        return true;
    }

    function applyHealth(botId, healthData, running, recentEvents) {
        var dismiss = getDismissInfo(botId);
        var alerts = (healthData && healthData.alerts) ? healthData.alerts : [];
        var picked = filterAlertsForUi(alerts, dismiss, recentEvents, healthData);
        if (running && !picked.criticals.length && !picked.warns.length) {
            if (autoClearResolvedHealthState(botId, alerts, recentEvents, healthData)) {
                dismiss = getDismissInfo(botId);
                picked = filterAlertsForUi(alerts, dismiss, recentEvents, healthData);
            }
        }
        var id = String(botId || '');
        _lastHadActiveHealthUi[id] = !!(running && (picked.criticals.length || picked.warns.length));
        if (typeof global !== 'undefined') global._lastHealthUiPick = picked;
        if (running && !picked.criticals.length && !picked.warns.length) {
            global._botLiveProblem = false;
        }
        var connDismissed = !!(dismiss && dismiss.codes.indexOf('BINANCE_UNREACHABLE') >= 0);
        var statusDismissed = !!(dismiss && dismiss.codes.indexOf('STATE_ERROR') >= 0);
        var connectivityOk = healthData && healthData.connectivity_ok !== false && !healthData.connectivity_failure;
        syncDom({
            running: running,
            warns: picked.warns,
            criticals: picked.criticals,
            suppressLiveProblem: connDismissed || statusDismissed || connectivityOk
        });
        var level = null;
        if (running && picked.criticals.length > 0 && picked.warns.length > 0) level = 'both';
        else if (running && picked.criticals.length > 0) level = 'critical';
        else if (running && picked.warns.length > 0) level = 'warn';
        setStoredRowAlert(botId, level, topAlertMessage(picked.criticals.length ? picked.criticals : picked.warns));
        return picked;
    }

    function resetUi(botId, currentAlerts, recentEvents) {
        clearLogRegistry(botId);
        var events = recentEvents || [];
        var alerts = currentAlerts || [];
        var codes = {};
        alerts.forEach(function (a) {
            if (a && a.code) codes[a.code] = true;
        });
        KNOWN_HEALTH_CODES.forEach(function (code) {
            codes[code] = true;
        });
        ['CONNECTIVITY_RECOVERED', 'CONNECTIVITY_STABLE', 'CONNECTIVITY_PAUSED', 'LOT_SIZE', 'MIN_NOTIONAL',
            'ORDER_FAILED', 'INSUFFICIENT_QUOTE', 'OUTAGE_RECOVERY', 'RUN_ACTION_EXCEPTION',
            'BOT_CONTINUES_ON_ERROR'].forEach(function (code) {
            codes[code] = true;
        });
        var synthetic = Object.keys(codes).map(function (code) {
            return { code: code };
        });
        setDismiss(botId, synthetic.length ? synthetic : alerts, events);
        _lastDomSyncKey = '';
        syncDom({ running: true, warns: [], criticals: [], suppressLiveProblem: true });
    }

    function isConnectivityLogSuppressed(botId, events) {
        var dismissInfo = getDismissInfo(botId);
        if (!dismissInfo) return false;
        var connDismissed = dismissInfo.codes.indexOf('BINANCE_UNREACHABLE') >= 0
            || dismissInfo.codes.indexOf('STATE_ERROR') >= 0;
        if (!connDismissed) return false;
        var afterId = dismissInfo.maxEventId != null ? Number(dismissInfo.maxEventId) : 0;
        var realEvents = (events || []).filter(function (e) {
            return !(e && e.meta && e.meta.synthetic_live);
        });
        if (hasConnectivityEventAfterId(realEvents, afterId)) return false;
        return true;
    }

    function shouldHideResetLogEvent(ev, botId, contextEvents, healthData) {
        if (!ev) return false;
        var events = contextEvents
            || (typeof global !== 'undefined' && global._lastEngineEvents)
            || [];
        healthData = healthData
            || (typeof global !== 'undefined' && global._lastHealthData)
            || null;
        var serverBefore = getServerDismissBeforeId(healthData);
        if (ev.meta && ev.meta.synthetic_live) {
            return isConnectivityLogEvent(ev) && isConnectivityLogSuppressed(botId, events);
        }
        var dismissInfo = getDismissInfo(botId);
        if (ev.meta && ev.meta.health_ui_track) {
            if (!dismissInfo && !serverBefore) return false;
            var hc = eventHealthCode(ev);
            if (hc && isAlertSuppressed({ code: hc }, dismissInfo, events, healthData)) return true;
            return false;
        }
        if ((ev.type || '').toUpperCase() === 'ERROR' && isConnectivityLogEvent(ev)) {
            if (isConnectivityLogSuppressed(botId, events)) return true;
        }
        if (!isResettableLogEvent(ev)) return false;
        var evId = ev.id != null ? Number(ev.id) : 0;
        if (Number.isFinite(evId) && evId > 0 && serverBefore > 0 && evId <= serverBefore) {
            return true;
        }
        if (!dismissInfo) return false;
        var code = resolveEventLogCode(ev);
        var codeMax = code ? perCodeDismissAnchor(dismissInfo, code) : 0;
        var globalMax = effectiveGlobalDismissAnchor(dismissInfo, healthData);
        if (Number.isFinite(evId) && evId > 0) {
            if (code && codeMax >= 0 && evId <= codeMax) return true;
            if (globalMax >= 0 && evId <= globalMax) return true;
        }
        if (dismissInfo.ts) {
            var eventTs = ev.ts ? new Date(ev.ts).getTime() : 0;
            if (eventTs && eventTs <= Number(dismissInfo.ts)) {
                if (!code || !hasLogEventForCodeAfterId(events, code, codeMax)) return true;
            }
        }
        return false;
    }

    function shouldHideHealthLogEvent(ev, botId) {
        return shouldHideResetLogEvent(ev, botId);
    }

    function classifyRowAlerts(botId, healthData, running, recentEvents) {
        if (!running) return { level: null, hasCrit: false, hasWarn: false };
        recentEvents = recentEvents
            || (typeof global !== 'undefined' && global._lastEngineEvents)
            || [];
        var alerts = normalizeActiveAlerts((healthData && healthData.alerts) ? healthData.alerts.slice() : [], healthData, recentEvents);
        if (healthData && healthData.connectivity_ok === false && healthData.connectivity_failure) {
            alerts.push({
                code: healthData.connectivity_failure.error_code || 'BINANCE_UNREACHABLE',
                level: 'critical',
                message: healthData.connectivity_failure.message
            });
        }
        var picked = filterAlertsForUi(alerts, getDismissInfo(botId), recentEvents, healthData);
        var hasCrit = picked.criticals.length > 0;
        var hasWarn = picked.warns.length > 0;
        if (hasCrit && hasWarn) return { level: 'both', hasCrit: true, hasWarn: true };
        if (hasCrit) return { level: 'critical', hasCrit: true, hasWarn: false };
        if (hasWarn) return { level: 'warn', hasCrit: false, hasWarn: true };
        return { level: null, hasCrit: false, hasWarn: false };
    }

    global.BotHealthAlerts = {
        getDismissInfo: getDismissInfo,
        resetUi: resetUi,
        applyHealth: applyHealth,
        autoClearResolvedHealthState: autoClearResolvedHealthState,
        classifyRowAlerts: classifyRowAlerts,
        getStoredRowAlerts: getStoredRowAlerts,
        setStoredRowAlert: setStoredRowAlert,
        syncDom: syncDom,
        filterDismissedFromEvents: filterDismissedFromEvents,
        getServerDismissBeforeId: getServerDismissBeforeId,
        mergeHealthDisplayEvents: mergeHealthDisplayEvents,
        maxHealthEventId: maxHealthEventId,
        maxResettableEventId: maxResettableEventId,
        maxDismissAnchorEventId: maxDismissAnchorEventId,
        isConnectivityLogSuppressed: isConnectivityLogSuppressed,
        hasConnectivityEventAfterId: hasConnectivityEventAfterId,
        hasLogEventForCodeAfterId: hasLogEventForCodeAfterId,
        perCodeDismissAnchor: perCodeDismissAnchor,
        shouldHideResetLogEvent: shouldHideResetLogEvent,
        shouldHideHealthLogEvent: shouldHideHealthLogEvent
    };
})(typeof window !== 'undefined' ? window : globalThis);
