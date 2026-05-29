/**
 * Per-bot health UI — page frame blink, status badges, engine-log rows (no top banner).
 * Critical / warn classes; deduped log rows; reset clears until re-fire; resolved rows stay in log.
 */
(function (global) {
    'use strict';

    var _lastDomSyncKey = '';
    var LOG_REGISTRY_PREFIX = 'botHealthLogRegistry_';

    var ALERT_PRIORITY = {
        LOOP_TASK_MISSING: 1000,
        TICK_STALE_CRIT: 950,
        BINANCE_UNREACHABLE: 900,
        STATE_ERROR: 880,
        REPEATED_ORDER_FAIL: 850,
        TICK_STALE_WARN: 500,
        STATE_ERROR_WARN: 480,
        FIRST_BUY_STUCK: 450,
        NO_TICK_YET: 400,
        LOT_SIZE: 300,
        MIN_NOTIONAL: 290,
        MIN_NOTIONAL_AFTER_CAP: 285,
        ORDER_FAILED: 200,
        INSUFFICIENT_QUOTE: 180,
        ORDER_TIMEOUT: 170,
        BOT_CONTINUES_ON_ERROR: 920,
        BOT_LOOP_AUTO_RESTART: 910,
        LOOP_TASK_MISSING: 905,
        PRICE_STALE_OR_MISSING: 420,
        REPEATED_LOCK_BUSY: 410,
        REPEATED_SLIPPAGE: 400,
        CONNECTIVITY_DEGRADED: 390
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
        'FIRST_BUY_STUCK', 'LOOP_TASK_MISSING', 'BINANCE_UNREACHABLE',
        'LOT_SIZE', 'MIN_NOTIONAL', 'MIN_NOTIONAL_AFTER_CAP', 'ORDER_FAILED',
        'INSUFFICIENT_QUOTE', 'ORDER_TIMEOUT',
        'BOT_CONTINUES_ON_ERROR', 'BOT_LOOP_AUTO_RESTART', 'PRICE_STALE_OR_MISSING',
        'REPEATED_LOCK_BUSY', 'REPEATED_SLIPPAGE', 'CONNECTIVITY_DEGRADED'
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
        if (code === 'CONNECTIVITY_RECOVERED' || code === 'CONNECTIVITY_PAUSED') return true;
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
        if (ty === 'INFO' && isReconnectLogEvent(ev)) return true;
        if (ty === 'ERROR' && isConnectivityLogEvent(ev)) return true;
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
            if (alert.code === 'TICK_STALE_CRIT' && tickAge >= 60) return false;
            if (alert.code === 'TICK_STALE_WARN' && tickAge >= 20) return false;
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

        var activeList = (alerts || []).filter(function (a) {
            return a && a.code && !isAlertSuppressed(a, dismissInfo, recentEvents, healthSnapshot);
        });
        var activeCodes = {};
        activeList.forEach(function (a) {
            activeCodes[a.code] = a;
        });

        var now = Date.now();

        Object.keys(reg.entries).forEach(function (k) {
            var e = reg.entries[k];
            if (!e || e.dismissed || !e.active) return;
            if (!activeCodes[e.code]) {
                e.active = false;
                e.resolvedAt = now;
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

        var alerts = (healthData && healthData.alerts) ? healthData.alerts : [];
        var dismiss = getDismissInfo(botId);
        var reg = syncLogRegistry(botId, alerts, dismiss, events, healthData);

        var trackedCodes = {};
        Object.keys(reg.entries || {}).forEach(function (k) {
            var e = reg.entries[k];
            if (e && !e.dismissed && e.code) trackedCodes[e.code] = true;
        });

        var out = events.filter(function (ev) {
            if (!isHealthEventType(ev && ev.type)) return true;
            var code = eventHealthCode(ev);
            if (code && trackedCodes[code]) return false;
            return true;
        });

        var synthetics = [];
        Object.keys(reg.entries || {}).forEach(function (k) {
            var e = reg.entries[k];
            if (!e || e.dismissed) return;
            if (!e.active && !e.resolvedAt) return;
            synthetics.push(buildRegistrySynthetic(e));
        });

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

        var liveProblem = !!(global._botLiveProblem) && !opts.suppressLiveProblem;
        var warnActive = hasWarn || (running && liveProblem && !hasCrit);
        var critActive = hasCrit;

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

    function applyHealth(botId, healthData, running, recentEvents) {
        var dismiss = getDismissInfo(botId);
        var alerts = (healthData && healthData.alerts) ? healthData.alerts : [];
        var picked = filterAlertsForUi(alerts, dismiss, recentEvents, healthData);
        if (typeof global !== 'undefined') global._lastHealthUiPick = picked;
        var connDismissed = !!(dismiss && dismiss.codes.indexOf('BINANCE_UNREACHABLE') >= 0);
        var statusDismissed = !!(dismiss && dismiss.codes.indexOf('STATE_ERROR') >= 0);
        syncDom({
            running: running,
            warns: picked.warns,
            criticals: picked.criticals,
            suppressLiveProblem: connDismissed || statusDismissed
        });
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
        ['CONNECTIVITY_RECOVERED', 'CONNECTIVITY_PAUSED', 'LOT_SIZE', 'MIN_NOTIONAL',
            'ORDER_FAILED', 'INSUFFICIENT_QUOTE'].forEach(function (code) {
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

    global.BotHealthAlerts = {
        getDismissInfo: getDismissInfo,
        resetUi: resetUi,
        applyHealth: applyHealth,
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
