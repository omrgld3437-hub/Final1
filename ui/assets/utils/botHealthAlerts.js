/**
 * Per-bot health alert UI — sticky top banner, badges, panel/frame blink, reset.
 * Active alerts always show (incl. page refresh). Resetle silences until same code re-fires.
 */
(function (global) {
    'use strict';

    var _lastDomSyncKey = '';
    var _lastBannerHtml = '';
    var _lastBannerVisible = false;

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
                maxEventId: data.maxEventId != null ? Number(data.maxEventId) : 0
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

    function maxDismissAnchorEventId(events) {
        return Math.max(maxResettableEventId(events || []), maxConnectivityEventId(events || []));
    }

    function setDismiss(botId, alerts, recentEvents) {
        var now = Date.now();
        var codeDismissTs = {};
        (alerts || []).forEach(function (a) {
            if (a && a.code) codeDismissTs[a.code] = now;
        });
        var maxEventId = maxDismissAnchorEventId(recentEvents || []);
        try {
            storageSet(resetKey(botId), JSON.stringify({
                ts: now,
                codes: Object.keys(codeDismissTs),
                codeDismissTs: codeDismissTs,
                maxEventId: maxEventId
            }));
        } catch (e) {}
    }

    var KNOWN_HEALTH_CODES = [
        'STATE_ERROR_WARN', 'STATE_ERROR', 'REPEATED_ORDER_FAIL',
        'TICK_STALE_WARN', 'TICK_STALE_CRIT', 'NO_TICK_YET',
        'FIRST_BUY_STUCK', 'LOOP_TASK_MISSING', 'BINANCE_UNREACHABLE'
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

    function maxEventIdAll(events) {
        var max = 0;
        (events || []).forEach(function (ev) {
            var id = ev && ev.id != null ? Number(ev.id) : 0;
            if (id > max) max = id;
        });
        return max;
    }

    function isConnectivityLogEvent(ev) {
        if (!ev) return false;
        var meta = (ev && ev.meta) || {};
        var code = String(meta.error_code || meta.health_code || '').toUpperCase();
        if (/API_UNAUTHORIZED|BINANCE_UNREACHABLE|BINANCE_RATE|ACCOUNT_KEYS/.test(code)) return true;
        return /binance|beyaz liste|401|-2015|ulaşılamıyor|api anahtar/i.test(String(ev.message || ''));
    }

    function isResettableLogEvent(ev) {
        if (!ev) return false;
        var ty = (ev.type || '').toUpperCase();
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

    function clearDismiss(botId) {
        try {
            storageRemove(resetKey(botId));
        } catch (e) {}
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
        if (!dismissInfo) return false;
        if (dismissInfo.codes.indexOf(alert.code) < 0) return false;
        var afterId = dismissInfo.maxEventId != null ? Number(dismissInfo.maxEventId) : 0;
        if (hasHealthEventForCodeAfterId(recentEvents, alert.code, afterId)) {
            return false;
        }
        if (alert.code === 'BINANCE_UNREACHABLE' || alert.code === 'STATE_ERROR') {
            if (hasConnectivityEventAfterId(recentEvents, afterId)) return false;
        }
        var dts = dismissTsForCode(dismissInfo, alert.code);
        if (hasHealthEventForCodeAfterTs(recentEvents, alert.code, dts)) {
            return false;
        }
        // Tick stale: koşul sürerse yeni log satırı olmasa da tekrar göster
        if (healthSnapshot && (healthSnapshot.alerts || []).some(function (a) {
            return a && a.code === alert.code;
        })) {
            var tickAge = Number(healthSnapshot.tick_age_s) || 0;
            if (alert.code === 'TICK_STALE_CRIT' && tickAge >= 60) return false;
            if (alert.code === 'TICK_STALE_WARN' && tickAge >= 20) return false;
        }
        return true;
    }

    function pickTop(alerts) {
        var warn = null;
        var critical = null;
        (alerts || []).forEach(function (a) {
            if (!a || !a.level) return;
            var lv = String(a.level).toLowerCase();
            if (lv === 'critical' && !critical) critical = a;
            if (lv === 'warn' && !warn) warn = a;
        });
        return { warn: warn, critical: critical };
    }

    function alertHasLogEvidence(alert, events) {
        if (!alert || !alert.code) return false;
        for (var i = 0; i < (events || []).length; i++) {
            var ev = events[i];
            if (!isHealthEventType(ev && ev.type)) continue;
            if (eventHealthCode(ev) === alert.code) return true;
        }
        return false;
    }

    function filterAlertsForUi(alerts, dismissInfo, recentEvents, healthSnapshot) {
        if (!alerts || !alerts.length) return { warn: null, critical: null };
        if (!dismissInfo) return pickTop(alerts);
        var filtered = alerts.filter(function (a) {
            return a && !isAlertSuppressed(a, dismissInfo, recentEvents, healthSnapshot);
        });
        if (!filtered.length) return { warn: null, critical: null };
        return pickTop(filtered);
    }

    function escHtml(s) {
        return String(s || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    function ensureShell() {
        var shell = document.getElementById('healthAlertShell');
        if (shell) return shell;
        shell = document.createElement('div');
        shell.id = 'healthAlertShell';
        shell.className = 'health-alert-shell';
        var frame = document.createElement('div');
        frame.id = 'healthCritPageFrame';
        frame.className = 'health-crit-page-frame';
        frame.setAttribute('aria-hidden', 'true');
        shell.appendChild(frame);
        document.body.insertBefore(shell, document.body.firstChild);
        return shell;
    }

    function ensureBanner() {
        ensureShell();
        var shell = document.getElementById('healthAlertShell');
        var banner = document.getElementById('healthAlertBanner');
        if (banner && shell && banner.parentNode !== shell) {
            shell.insertBefore(banner, shell.firstChild);
        }
        if (banner) return banner;
        banner = document.createElement('div');
        banner.id = 'healthAlertBanner';
        banner.className = 'health-alert-banner';
        banner.setAttribute('role', 'alert');
        banner.setAttribute('aria-live', 'assertive');
        banner.innerHTML = '<div class="health-alert-banner-inner"><div class="health-alert-banner-body"></div></div>';
        banner.addEventListener('click', function (e) {
            if (e.target.closest('.health-alert-banner-reset-btn')) {
                e.preventDefault();
                document.dispatchEvent(new CustomEvent('bot-health-reset', { bubbles: true }));
            }
        });
        shell.insertBefore(banner, shell.firstChild);
        return banner;
    }

    function buildBannerBody(showCrit, showWarn, critical, warn) {
        var primary = showCrit ? critical : warn;
        var icon = showCrit ? '!' : '⚠';
        var label = showCrit ? 'Kritik uyarı' : 'Uyarı';
        var html = '';
        html += '<div class="health-alert-banner-icon" aria-hidden="true">' + icon + '</div>';
        html += '<div class="health-alert-banner-label">' + label + '</div>';
        html += '<div class="health-alert-banner-msg">' + escHtml(primary.message || primary.title || label) + '</div>';
        if (primary.cause) {
            html += '<div class="health-alert-banner-cause">' + escHtml(primary.cause) + '</div>';
        }
        if (showCrit && showWarn) {
            html += '<div class="health-alert-banner-sub"><span class="health-alert-banner-sub-tag">Uyarı</span> ' +
                escHtml(warn.message || warn.title || 'Uyarı') + '</div>';
        }
        html += '<button type="button" class="health-alert-banner-reset-btn" title="Uyarı alarmlarını sıfırla">Resetle</button>';
        return html;
    }

    function syncShellState(bannerVisible, critActive) {
        var shell = document.getElementById('healthAlertShell');
        var frame = document.getElementById('healthCritPageFrame');
        if (frame) frame.classList.toggle('is-visible', !!critActive);
        if (shell) shell.classList.toggle('is-active', !!(bannerVisible || critActive));
    }

    function syncBanner(warn, critical, running) {
        var banner = ensureBanner();
        var bodyEl = banner.querySelector('.health-alert-banner-body');
        var showCrit = running && !!critical;
        var showWarn = running && !!warn;
        var wantVisible = showCrit || showWarn;

        if (!wantVisible) {
            if (!_lastBannerVisible) {
                return;
            }
            banner.classList.remove('is-visible', 'health-alert-banner--critical', 'health-alert-banner--warn');
            if (bodyEl) bodyEl.innerHTML = '';
            syncBannerPadding(banner, false);
            syncShellState(false, false);
            _lastBannerHtml = '';
            _lastBannerVisible = false;
            return;
        }

        var newHtml = buildBannerBody(showCrit, showWarn, critical, warn);
        var sameHtml = newHtml === _lastBannerHtml;
        var alreadyVisible = banner.classList.contains('is-visible');

        banner.classList.toggle('health-alert-banner--critical', showCrit);
        banner.classList.toggle('health-alert-banner--warn', !showCrit && showWarn);
        if (bodyEl && !sameHtml) {
            bodyEl.innerHTML = newHtml;
        }
        _lastBannerHtml = newHtml;

        if (alreadyVisible && sameHtml) {
            syncShellState(true, showCrit);
            _lastBannerVisible = true;
            return;
        }

        requestAnimationFrame(function () {
            banner.classList.add('is-visible');
            syncBannerPadding(banner, true);
            syncShellState(true, showCrit);
            _lastBannerVisible = true;
        });
    }

    function syncBannerPadding(banner, visible) {
        if (!document.body) return;
        if (!visible) {
            document.body.classList.remove('has-health-alert-banner');
            document.body.style.paddingTop = '';
            return;
        }
        document.body.classList.add('has-health-alert-banner');
        var h = banner ? banner.offsetHeight : 0;
        document.body.style.paddingTop = h > 0 ? (h + 'px') : '';
    }

    function syncDom(opts) {
        opts = opts || {};
        var warnBadge = document.getElementById('healthWarnBadge');
        var critBadge = document.getElementById('healthCriticalBadge');
        var headerPanel = document.getElementById('headerPanel');
        var engineLogPanel = document.getElementById('engineLogPanel');
        var running = !!opts.running;
        var warn = opts.warn;
        var critical = opts.critical;

        if (warnBadge) {
            if (running && warn) {
                warnBadge.style.display = 'inline-flex';
                warnBadge.textContent = 'Uyarı';
                warnBadge.title = (warn.message || warn.title || '') + (warn.cause ? '\n' + warn.cause : '');
            } else {
                warnBadge.style.display = 'none';
            }
        }
        if (critBadge) {
            if (running && critical) {
                critBadge.style.display = 'inline-flex';
                critBadge.textContent = 'Kritik';
                critBadge.title = (critical.message || critical.title || '') + (critical.cause ? '\n' + critical.cause : '');
            } else {
                critBadge.style.display = 'none';
            }
        }

        syncBanner(warn, critical, running);

        var liveProblem = !!(global._botLiveProblem) && !opts.suppressLiveProblem;
        var warnActive = running && (!!warn || (liveProblem && !critical));
        var critActive = running && !!critical;
        var syncKey = [
            running ? '1' : '0',
            critActive ? '1' : '0',
            warnActive ? '1' : '0',
            liveProblem ? '1' : '0',
            (warn && warn.code) || '',
            (critical && critical.code) || ''
        ].join('|');
        if (syncKey === _lastDomSyncKey) {
            return;
        }
        _lastDomSyncKey = syncKey;

        if (headerPanel) {
            headerPanel.classList.toggle('panel-health-critical', critActive);
            headerPanel.classList.toggle('panel-health-warn', warnActive && !critActive);
        }
        if (engineLogPanel) {
            engineLogPanel.classList.toggle('panel-health-critical', critActive);
            engineLogPanel.classList.toggle('panel-health-warn', warnActive && !critActive);
        }

        var hero = document.getElementById('stateHeroTitle');
        if (hero) {
            hero.classList.toggle('hero-alert-blink', critActive || warnActive || (running && liveProblem));
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
            warn: picked.warn,
            critical: picked.critical,
            suppressLiveProblem: connDismissed || statusDismissed
        });
        return picked;
    }

    function resetUi(botId, currentAlerts, recentEvents) {
        var alerts = currentAlerts || [];
        var codes = {};
        var now = Date.now();
        alerts.forEach(function (a) {
            if (a && a.code) codes[a.code] = true;
        });
        KNOWN_HEALTH_CODES.forEach(function (code) {
            codes[code] = true;
        });
        var synthetic = Object.keys(codes).map(function (code) {
            return { code: code };
        });
        setDismiss(botId, synthetic.length ? synthetic : alerts, recentEvents);
        _lastDomSyncKey = '';
        _lastBannerHtml = '';
        syncDom({ running: true, warn: null, critical: null, suppressLiveProblem: true });
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

    function shouldHideResetLogEvent(ev, botId) {
        if (!ev) return false;
        var events = (typeof global !== 'undefined' && global._lastEngineEvents) || [];
        if (ev.meta && ev.meta.synthetic_live) {
            return isConnectivityLogEvent(ev) && isConnectivityLogSuppressed(botId, events);
        }
        if ((ev.type || '').toUpperCase() === 'ERROR' && isConnectivityLogEvent(ev)) {
            if (isConnectivityLogSuppressed(botId, events)) return true;
        }
        if (!isResettableLogEvent(ev)) return false;
        var dismissInfo = getDismissInfo(botId);
        if (!dismissInfo) return false;
        var evId = ev.id != null ? Number(ev.id) : 0;
        var maxId = dismissInfo.maxEventId != null ? Number(dismissInfo.maxEventId) : 0;
        if (Number.isFinite(evId) && evId > 0 && maxId >= 0 && evId <= maxId) return true;
        if (dismissInfo.ts) {
            var eventTs = ev.ts ? new Date(ev.ts).getTime() : 0;
            if (eventTs && eventTs <= Number(dismissInfo.ts)) return true;
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
        maxHealthEventId: maxHealthEventId,
        maxResettableEventId: maxResettableEventId,
        maxDismissAnchorEventId: maxDismissAnchorEventId,
        isConnectivityLogSuppressed: isConnectivityLogSuppressed,
        hasConnectivityEventAfterId: hasConnectivityEventAfterId,
        shouldHideResetLogEvent: shouldHideResetLogEvent,
        shouldHideHealthLogEvent: shouldHideHealthLogEvent
    };
})(typeof window !== 'undefined' ? window : globalThis);
