/**
 * Bakım overlay: showMaintenanceOverlay(reason, status), hideMaintenanceOverlay()
 * Backend 5xx/timeout/network → overlay açılır; 5s/10s/20s/30s retry, health 200 → kapanır + reload.
 * Overlay açılınca intervalRegistry.stopAll(); kapanınca sayfa reload ile temiz başlangıç.
 */
(function () {
    var overlay = null;
    var retryTimer = null;
    var retryDelays = [5000, 10000, 20000, 30000];
    var retryIndex = 0;
    var lastAttemptTime = null;

    function getOrigin() {
        return typeof window !== 'undefined' && window.location ? window.location.origin : '';
    }

    function formatTime() {
        if (!lastAttemptTime) return '—';
        try {
            if (typeof window.trTime !== 'undefined' && window.trTime.trFormatTimeWithSeconds)
                return window.trTime.trFormatTimeWithSeconds(lastAttemptTime);
            var d = new Date(lastAttemptTime);
            return d.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: 'Europe/Istanbul' });
        } catch (e) { return '—'; }
    }

    function createOverlay() {
        if (overlay) return overlay;
        var el = document.createElement('div');
        el.id = 'maintenance-overlay';
        el.setAttribute('aria-hidden', 'true');
        el.innerHTML =
            '<div class="maint-backdrop">' +
            '<div class="maint-card">' +
            '<div class="maint-icon" aria-hidden="true">&#9881;</div>' +
            '<h1 class="maint-title">Sunucuya ulaşılamıyor / geçici bakım</h1>' +
            '<p class="maint-subtitle">Son deneme: <span id="maint-last-time">—</span></p>' +
            '<p class="maint-retry">Otomatik tekrar deneniyor: 5s / 10s / 20s</p>' +
            '<div class="maint-pulse" aria-hidden="true"></div>' +
            '<p class="maint-btns">' +
            '<button type="button" class="maint-btn" id="maint-btn-retry">Yeniden Dene</button> ' +
            '<a href="/" class="maint-btn maint-btn-secondary" id="maint-btn-home">Ana Sayfa</a>' +
            '</p></div></div>';
        el.style.cssText = 'position:fixed;inset:0;z-index:999999;display:flex;align-items:center;justify-content:center;' +
            'background: linear-gradient(135deg, #0a0e27 0%, #1a1f3a 100%);font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;';
        var style = document.createElement('style');
        style.textContent = [
            '#maintenance-overlay .maint-backdrop { display: flex; align-items: center; justify-content: center; width: 100%; min-height: 100%; padding: 2rem; box-sizing: border-box; }',
            '#maintenance-overlay .maint-card { text-align: center; max-width: 420px; padding: 2.5rem; background: var(--ds-bg-secondary, #1e2026); border-radius: 16px; border: 1px solid var(--ds-border, #2b3139); box-shadow: 0 20px 60px rgba(0,0,0,0.4), 0 0 0 1px rgba(240,185,11,0.08); position: relative; }',
            '#maintenance-overlay .maint-icon { font-size: 3rem; line-height: 1; color: var(--ds-accent, #f0b90b); margin-bottom: 1rem; opacity: 0.95; }',
            '#maintenance-overlay .maint-title { margin: 0 0 0.5rem 0; font-size: 1.2rem; font-weight: 700; color: var(--ds-text-primary, #eaecef); }',
            '#maintenance-overlay .maint-subtitle { margin: 0 0 0.5rem 0; font-size: 0.9rem; color: var(--ds-text-secondary, #848e9c); }',
            '#maintenance-overlay .maint-retry { margin: 0 0 1rem 0; font-size: 0.85rem; color: var(--ds-text-muted, #5e6673); }',
            '#maintenance-overlay .maint-pulse { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: var(--ds-accent, #f0b90b); box-shadow: 0 0 12px var(--ds-accent, #f0b90b); animation: maint-pulse 1.5s ease-in-out infinite; margin-bottom: 1rem; }',
            '@keyframes maint-pulse { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.4; transform: scale(0.85); } }',
            '#maintenance-overlay .maint-btns { margin: 0; }',
            '#maintenance-overlay .maint-btn { display: inline-block; padding: 0.6rem 1.25rem; margin: 0 0.35rem 0.35rem 0; background: var(--ds-accent, #f0b90b); color: #0a0e27; border: none; border-radius: 8px; font-size: 0.95rem; font-weight: 600; cursor: pointer; text-decoration: none; transition: background 0.2s; }',
            '#maintenance-overlay .maint-btn:hover { background: #f8c622; }',
            '#maintenance-overlay .maint-btn-secondary { background: transparent; color: var(--ds-text-secondary, #848e9c); border: 1px solid var(--ds-border, #2b3139); }',
            '#maintenance-overlay .maint-btn-secondary:hover { background: var(--ds-bg-tertiary, #2b3139); color: var(--ds-text-primary, #eaecef); }'
        ].join('');
        document.head.appendChild(style);
        document.body.appendChild(el);
        overlay = el;
        var btnRetry = el.querySelector('#maint-btn-retry');
        if (btnRetry) btnRetry.addEventListener('click', function () { window.location.reload(); });
        return el;
    }

    function updateLastTime() {
        lastAttemptTime = Date.now();
        var el = document.getElementById('maint-last-time');
        if (el) el.textContent = formatTime();
    }

    function hideOverlay() {
        if (retryTimer) {
            clearTimeout(retryTimer);
            retryTimer = null;
        }
        retryIndex = 0;
        if (overlay) overlay.style.display = 'none';
    }

    function checkHealthAndReload() {
        updateLastTime();
        var url = getOrigin() + '/api/health';
        fetch(url, { method: 'GET', cache: 'no-store' }).then(function (r) {
            if (!r.ok) return;
            return r.json().catch(function () { return {}; });
        }).then(function (data) {
            if (!data) return;
            if (data.lockdown === true) {
                hideOverlay();
                try {
                    if (window.apiClient && window.apiClient.clearAuthAndBroadcast) window.apiClient.clearAuthAndBroadcast(); else { sessionStorage.removeItem('user'); sessionStorage.removeItem('token'); }
                    localStorage.removeItem('boot_id');
                    localStorage.removeItem('last_route');
                } catch (e) {}
                window.location.replace('/ui/login.html');
                return;
            }
            // Sunucu geri geldi: overlay kapat, sayfa yenile. Oturumu temizleme / login'e atma — kullanıcı hesapta kalsın.
            hideOverlay();
            window.location.reload();
        }).catch(function () {});
    }

    function scheduleNext() {
        var delay = retryDelays[retryIndex] !== undefined ? retryDelays[retryIndex] : 30000;
        if (retryIndex < retryDelays.length - 1) retryIndex += 1;
        retryTimer = setTimeout(function () {
            checkHealthAndReload();
            scheduleNext();
        }, delay);
    }

    function showMaintenanceOverlay(reason, status) {
        createOverlay();
        overlay.style.display = 'flex';
        updateLastTime();
        if (typeof window.intervalRegistry !== 'undefined' && window.intervalRegistry.stopAll) {
            try { window.intervalRegistry.stopAll(); } catch (e) {}
        }
        if (retryTimer) return;
        retryIndex = 0;
        checkHealthAndReload();
        scheduleNext();
    }

    function hideMaintenanceOverlay() {
        hideOverlay();
    }

    window.showMaintenanceOverlay = showMaintenanceOverlay;
    window.hideMaintenanceOverlay = hideMaintenanceOverlay;
    window.showMaintenanceScreen = showMaintenanceOverlay;
    window.hideMaintenanceScreen = hideMaintenanceOverlay;
})();
