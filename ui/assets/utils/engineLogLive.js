/**
 * Bot engine log — canlı poll (after_id), tablo render, scroll koruma.
 */
(function (global) {
    'use strict';

    var POLL_MS = 4000;
    var MAX_EVENTS = 500;

    function maxEventId(events) {
        var max = 0;
        (events || []).forEach(function (e) {
            var id = e && e.id != null ? Number(e.id) : 0;
            if (id > max) max = id;
        });
        return max;
    }

    function mergeEvents(existing, incoming, limit) {
        var byId = {};
        (existing || []).forEach(function (e) {
            if (e && e.id != null) byId[String(e.id)] = e;
        });
        (incoming || []).forEach(function (e) {
            if (e && e.id != null) byId[String(e.id)] = e;
        });
        var merged = Object.keys(byId).map(function (k) { return byId[k]; });
        merged.sort(function (a, b) { return Number(b.id || 0) - Number(a.id || 0); });
        if (merged.length > limit) merged = merged.slice(0, limit);
        return merged;
    }

    function wasScrolledToTop(el) {
        if (!el) return true;
        return el.scrollTop < 48;
    }

    function enrichStartEvents(events, opts) {
        var ic = opts && opts.initialCapital != null ? Number(opts.initialCapital) : 0;
        var cse = opts && opts.cycleStartEquity != null ? Number(opts.cycleStartEquity) : 0;
        if (!(ic > 0) && !(cse > 0)) return events;
        return (events || []).map(function (ev) {
            var msg = ev.message || '';
            if ((ev.type || '') !== 'INFO' || msg.indexOf('COMMAND_EXECUTED') < 0 || msg.indexOf('START') < 0) {
                return ev;
            }
            var meta = Object.assign({}, ev.meta || {});
            if (ic > 0 && meta.initial_capital_usdt == null) meta.initial_capital_usdt = ic;
            var pre = Number(meta.base_balance || 0) === 0
                && Number(meta.quote_balance || 0) === 0
                && Number(meta.equity_usd || 0) === 0;
            if (pre) meta.initial_allocation_done = false;
            else if (cse > 0 && meta.cycle_start_equity == null) meta.cycle_start_equity = cse;
            return Object.assign({}, ev, { meta: meta });
        });
    }

    function renderTable(container, events, fmtApi) {
        if (!container) return { rendered: false, events: events || [] };
        fmtApi = fmtApi || global.EngineLogFormat;
        var list = (events || []).slice().sort(function (a, b) {
            return Number(b.id || 0) - Number(a.id || 0);
        });
        if (!list.length) {
            container.innerHTML = '<div class="muted" style="padding: 0.75rem;">Henüz event yok.</div>';
            return { rendered: false, events: list };
        }
        var collapsed = fmtApi && fmtApi.collapseEngineEvents ? fmtApi.collapseEngineEvents(list) : [];
        if (!collapsed.length) {
            container.innerHTML = '<div class="muted" style="padding: 0.75rem;">Gösterilecek önemli kayıt yok (rutin uyarılar gizlendi).</div>';
            return { rendered: false, events: list };
        }
        var stickTop = wasScrolledToTop(container);
        var html = '<table class="engine-log-table"><colgroup><col class="log-col-time"><col class="log-col-type"><col class="log-col-msg"></colgroup><thead><tr><th>Zaman</th><th>Tür</th><th>Mesaj</th></tr></thead><tbody>';
        collapsed.forEach(function (item) {
            var ts = item.ts ? (function () {
                var d = new Date(item.ts);
                return d.toLocaleString('tr-TR', { timeZone: 'Europe/Istanbul' });
            })() : '—';
            if (item.count > 1) {
                ts += ' <span class="log-repeat-badge" title="Aynı kayıttan ' + item.count + ' adet">(' + item.count + '×)</span>';
            }
            var ty = (item.typeLabel || '—').replace(/</g, '&lt;');
            var msg = (item.message || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
            var rowCl = fmtApi && fmtApi.rowClass ? fmtApi.rowClass(item.severity) : 'log-row-info';
            html += '<tr class="' + rowCl + '"><td>' + ts + '</td><td>' + ty + '</td><td>' + msg + '</td></tr>';
        });
        html += '</tbody></table>';
        container.innerHTML = html;
        if (stickTop) container.scrollTop = 0;
        return { rendered: true, events: list, collapsed: collapsed };
    }

    function buildQuery(accountId, accountCode, extra) {
        var parts = [];
        if (accountCode) parts.push('account_code=' + encodeURIComponent(accountCode));
        else if (accountId) parts.push('account_id=' + encodeURIComponent(accountId));
        if (extra) parts.push(extra);
        return parts.length ? '?' + parts.join('&') : '';
    }

    /**
     * @param {object} opts — botId, accountId, accountCode, container, apiClient, state { events, lastId }, onAfterRender(events)
     * @param {boolean} incremental — after_id poll (no loading flash)
     */
    function fetchAndRender(opts, incremental) {
        if (!opts || !opts.botId || !opts.apiClient || !opts.container) return Promise.resolve();
        var state = opts.state || { events: [], lastId: 0 };
        var qBase = buildQuery(opts.accountId, opts.accountCode, '');
        var url;
        if (incremental && state.lastId > 0) {
            url = '/api/bots-engine/' + opts.botId + '/events' + qBase +
                (qBase ? '&' : '?') + 'limit=100&after_id=' + encodeURIComponent(state.lastId);
        } else {
            if (!incremental) {
                opts.container.innerHTML = '<div class="muted" style="padding: 0.75rem;">Yükleniyor…</div>';
            }
            url = '/api/bots-engine/' + opts.botId + '/events' + qBase +
                (qBase ? '&' : '?') + 'limit=' + MAX_EVENTS;
        }
        return opts.apiClient.get(url).then(function (res) {
            var incoming = (res && res.events) ? res.events : [];
            if (incremental && state.lastId > 0) {
                if (!incoming.length) return state.events;
                state.events = mergeEvents(state.events, incoming, MAX_EVENTS);
            } else {
                state.events = incoming.slice(0, MAX_EVENTS);
            }
            state.lastId = maxEventId(state.events);
            renderTable(opts.container, enrichStartEvents(state.events, opts), global.EngineLogFormat);
            if (typeof opts.onAfterRender === 'function') {
                opts.onAfterRender(state.events);
            }
            return state.events;
        }).catch(function () {
            if (!incremental) {
                opts.container.innerHTML = '<div class="muted" style="padding: 0.75rem;">Loglar yüklenemedi.</div>';
            }
            return state.events;
        });
    }

    function startPolling(opts) {
        stopPolling(opts);
        if (!opts || !opts.botId) return;
        opts.state = opts.state || { events: [], lastId: 0 };
        opts._pollTimer = setInterval(function () {
            if (document.hidden) return;
            fetchAndRender(opts, true);
        }, opts.pollMs || POLL_MS);
    }

    function stopPolling(opts) {
        if (opts && opts._pollTimer) {
            clearInterval(opts._pollTimer);
            opts._pollTimer = null;
        }
    }

    global.EngineLogLive = {
        POLL_MS: POLL_MS,
        fetchAndRender: fetchAndRender,
        startPolling: startPolling,
        stopPolling: stopPolling,
        renderTable: renderTable
    };
})(typeof window !== 'undefined' ? window : globalThis);
