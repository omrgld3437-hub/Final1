/**
 * Bakım / sunucu kapalı overlay: tema uyumlu, pulse, retry 5s/10s/20s.
 * showMaintenanceScreen() → overlay açılır, /api/health 200 olunca kapanır ve sayfa yenilenir.
 */
(function () {
    var overlay = null;
    var retryTimer = null;
    var retryDelays = [5000, 10000, 20000];
    var retryIndex = 0;

    function getOrigin() {
        return typeof window !== 'undefined' && window.location ? window.location.origin : '';
    }

    function createOverlay() {
        if (overlay) return overlay;
        var el = document.createElement('div');
        el.id = 'maintenance-overlay';
        el.setAttribute('aria-hidden', 'true');
        el.innerHTML = '<div class="maintenance-backdrop">' +
            '<div class="maintenance-card">' +
            '<div class="maintenance-icon" aria-hidden="true">&#9881;</div>' +
            '<h1 class="maintenance-title">Sistem geçici olarak bakımda</h1>' +
            '<p class="maintenance-subtitle">Sunucu yeniden başlatılıyor olabilir.</p>' +
            '<p class="maintenance-retry">Otomatik olarak tekrar deniyoruz.</p>' +
            '<div class="maintenance-pulse" aria-hidden="true"></div>' +
            '</div></div>';
        el.style.cssText = [
            'position:fixed;inset:0;z-index:999999;display:flex;align-items:center;justify-content:center;',
            'background: linear-gradient(135deg, #0a0e27 0%, #1a1f3a 100%);',
            'font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;'
        ].join('');
        var style = document.createElement('style');
        style.textContent = [
            '#maintenance-overlay .maintenance-backdrop { display: flex; align-items: center; justify-content: center; width: 100%; min-height: 100%; padding: 2rem; box-sizing: border-box; }',
            '#maintenance-overlay .maintenance-card { text-align: center; max-width: 420px; padding: 2.5rem; background: var(--ds-bg-secondary, #1e2026); border-radius: 16px; border: 1px solid var(--ds-border, #2b3139); box-shadow: 0 20px 60px rgba(0,0,0,0.4), 0 0 0 1px rgba(240,185,11,0.08); position: relative; }',
            '#maintenance-overlay .maintenance-icon { font-size: 3rem; line-height: 1; color: var(--ds-accent, #f0b90b); margin-bottom: 1rem; opacity: 0.95; }',
            '#maintenance-overlay .maintenance-title { margin: 0 0 0.5rem 0; font-size: 1.35rem; font-weight: 700; color: var(--ds-text-primary, #eaecef); }',
            '#maintenance-overlay .maintenance-subtitle { margin: 0 0 0.75rem 0; font-size: 0.95rem; color: var(--ds-text-secondary, #848e9c); }',
            '#maintenance-overlay .maintenance-retry { margin: 0; font-size: 0.9rem; color: var(--ds-text-muted, #5e6673); }',
            '#maintenance-overlay .maintenance-pulse { position: absolute; bottom: 1.25rem; left: 50%; transform: translateX(-50%); width: 8px; height: 8px; border-radius: 50%; background: var(--ds-accent, #f0b90b); box-shadow: 0 0 12px var(--ds-accent, #f0b90b); animation: maintenance-pulse 1.5s ease-in-out infinite; }',
            '@keyframes maintenance-pulse { 0%, 100% { opacity: 1; transform: translateX(-50%) scale(1); } 50% { opacity: 0.4; transform: translateX(-50%) scale(0.85); } }'
        ].join('');
        document.head.appendChild(style);
        document.body.appendChild(el);
        overlay = el;
        return el;
    }

    function hideOverlay() {
        if (retryTimer) {
            clearTimeout(retryTimer);
            retryTimer = null;
        }
        retryIndex = 0;
        if (overlay) {
            overlay.style.display = 'none';
        }
    }

    function checkHealthAndReload() {
        var url = getOrigin() + '/api/health';
        fetch(url, { method: 'GET', cache: 'no-store' }).then(function (r) {
            if (r.ok) {
                hideOverlay();
                window.location.reload();
            }
        }).catch(function () {});
    }

    function scheduleNext() {
        var delay = retryDelays[retryIndex] !== undefined ? retryDelays[retryIndex] : 20000;
        if (retryIndex < retryDelays.length - 1) retryIndex += 1;
        retryTimer = setTimeout(function () {
            checkHealthAndReload();
            scheduleNext();
        }, delay);
    }

    function showMaintenanceScreen() {
        createOverlay();
        overlay.style.display = 'flex';
        if (retryTimer) return;
        retryIndex = 0;
        checkHealthAndReload();
        scheduleNext();
    }

    window.showMaintenanceScreen = showMaintenanceScreen;
    window.hideMaintenanceScreen = hideOverlay;
})();
