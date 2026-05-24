/**
 * Per-bot health alert UI — sticky top banner, badges, panel/frame blink, reset.
 * Active alerts always show (incl. page refresh). Resetle silences until same code re-fires.
 */
(function (global) {
    'use strict';

    function resetKey(botId) {
        return 'botHealthDismiss_' + (botId || '');
    }

    function getDismissInfo(botId) {
        try {
            var raw = sessionStorage.getItem(resetKey(botId));
            if (!raw) return null;
            var data = JSON.parse(raw);
            if (!data || !data.ts) return null;
            return {
                ts: data.ts,
                codes: Array.isArray(data.codes) ? data.codes : [],
                codeDismissTs: data.codeDismissTs && typeof data.codeDismissTs === 'object' ? data.codeDismissTs : {}
            };
        } catch (e) {
            return null;
        }
    }

    function setDismiss(botId, alerts) {
        var now = Date.now();
        var codeDismissTs = {};
        (alerts || []).forEach(function (a) {
            if (a && a.code) codeDismissTs[a.code] = now;
        });
        try {
            sessionStorage.setItem(resetKey(botId), JSON.stringify({
                ts: now,
                codes: Object.keys(codeDismissTs),
                codeDismissTs: codeDismissTs
            }));
        } catch (e) {}
    }

    function clearDismiss(botId) {
        try {
            sessionStorage.removeItem(resetKey(botId));
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

    function maxHealthEventId(events) {
        var max = 0;
        (events || []).forEach(function (ev) {
            if (!isHealthEventType(ev && ev.type)) return;
            var id = ev && ev.id != null ? Number(ev.id) : 0;
            if (id > max) max = id;
        });
        return max;
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

    function isAlertSuppressed(alert, dismissInfo, recentEvents) {
        if (!alert || !alert.code) return false;
        if (!dismissInfo) return false;
        if (dismissInfo.codes.indexOf(alert.code) < 0) return false;
        var dts = dismissTsForCode(dismissInfo, alert.code);
        if (hasHealthEventForCodeAfterTs(recentEvents, alert.code, dts)) {
            return false;
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

    function filterAlertsForUi(alerts, dismissInfo, recentEvents) {
        if (!alerts || !alerts.length) return { warn: null, critical: null };
        var evidenced = alerts.filter(function (a) {
            return a && alertHasLogEvidence(a, recentEvents);
        });
        if (!evidenced.length) return { warn: null, critical: null };
        if (!dismissInfo) return pickTop(evidenced);
        var filtered = evidenced.filter(function (a) {
            return !isAlertSuppressed(a, dismissInfo, recentEvents);
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

        if (!showCrit && !showWarn) {
            banner.classList.remove('is-visible', 'health-alert-banner--critical', 'health-alert-banner--warn');
            if (bodyEl) bodyEl.innerHTML = '';
            syncBannerPadding(banner, false);
            syncShellState(false, false);
            return;
        }

        banner.classList.toggle('health-alert-banner--critical', showCrit);
        banner.classList.toggle('health-alert-banner--warn', !showCrit && showWarn);
        if (bodyEl) {
            bodyEl.innerHTML = buildBannerBody(showCrit, showWarn, critical, warn);
        }

        requestAnimationFrame(function () {
            banner.classList.add('is-visible');
            syncBannerPadding(banner, true);
            syncShellState(true, showCrit);
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

        var critActive = running && !!critical;
        if (headerPanel) headerPanel.classList.toggle('panel-health-critical', critActive);
        if (engineLogPanel) engineLogPanel.classList.toggle('panel-health-critical', critActive);

        var hero = document.getElementById('stateHeroTitle');
        if (hero) {
            if (critActive) hero.classList.add('hero-alert-blink');
            else hero.classList.remove('hero-alert-blink');
        }
    }

    function applyHealth(botId, healthData, running, recentEvents) {
        var dismiss = getDismissInfo(botId);
        var alerts = (healthData && healthData.alerts) ? healthData.alerts : [];
        if (!alerts.length && dismiss) {
            clearDismiss(botId);
            dismiss = null;
        }
        var picked = filterAlertsForUi(alerts, dismiss, recentEvents);
        syncDom({
            running: running,
            warn: picked.warn,
            critical: picked.critical
        });
        return picked;
    }

    function resetUi(botId, currentAlerts) {
        setDismiss(botId, currentAlerts);
        syncDom({ running: true, warn: null, critical: null });
    }

    global.BotHealthAlerts = {
        getDismissInfo: getDismissInfo,
        resetUi: resetUi,
        applyHealth: applyHealth,
        syncDom: syncDom,
        maxHealthEventId: maxHealthEventId
    };
})(typeof window !== 'undefined' ? window : globalThis);
