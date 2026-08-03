/**
 * Bot detay sayfaları — üst appbar (WS göstergesi + ayserose).
 */
(function (global) {
    'use strict';

    function updateDatahubWsIndicator() {
        var el = document.getElementById('datahubWsIndicator');
        if (!el) return;
        var client = global.apiClient;
        if (!client || typeof client.get !== 'function') return;
        if (typeof client.hasToken === 'function' && !client.hasToken()) return;
        client.get('/api/datahub/status', { timeout: 3000 }).then(function (data) {
            if (!data || !el) return;
            var dot = el.querySelector('.datahub-ws-dot');
            var s = (data.ws_status || 'rest').toLowerCase();
            if (dot) {
                dot.style.backgroundColor = s === 'connected' ? '#0ecb81' : (s === 'stale' ? '#f0b90b' : (s === 'rest' ? '#8b9bb4' : '#f6465d'));
            }
            var titles = { connected: 'WebSocket bağlı', stale: 'WebSocket gecikmeli', rest: 'REST modu (WS yok)' };
            el.title = (titles[s] || 'WS durumu') + ' • ' + (data.total_symbols || 0) + ' sembol';
        }).catch(function () {
            var dot = el && el.querySelector('.datahub-ws-dot');
            if (dot) dot.style.backgroundColor = '#f6465d';
        });
    }

    function initBotPageAppbar() {
        updateDatahubWsIndicator();
        if (global.intervalRegistry && typeof global.intervalRegistry.start === 'function') {
            global.intervalRegistry.stop('bot.page.ws-status');
            global.intervalRegistry.start('bot.page.ws-status', updateDatahubWsIndicator, 5000, 'bot.page');
        }
    }

    global.BotPageAppbar = {
        init: initBotPageAppbar,
        updateWsIndicator: updateDatahubWsIndicator
    };

    if (document.getElementById('datahubWsIndicator')) {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', initBotPageAppbar);
        } else {
            initBotPageAppbar();
        }
    }
})(typeof window !== 'undefined' ? window : globalThis);
