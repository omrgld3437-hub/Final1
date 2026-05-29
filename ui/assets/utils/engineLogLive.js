/**
 * Bot engine log — canlı poll (after_id), tablo render, scroll koruma.
 */
(function (global) {
    'use strict';

    var POLL_MS = 4000;
    var MAX_EVENTS = 500;
    var FULL_REFRESH_MS = 90000;

    function maxEventId(events) {
        var max = 0;
        (events || []).forEach(function (e) {
            var id = e && e.id != null ? Number(e.id) : 0;
            if (id > max) max = id;
        });
        return max;
    }

    function sortEventsForDisplay(events) {
        if (global.EngineLogFormat && global.EngineLogFormat.sortEngineEventsDesc) {
            return global.EngineLogFormat.sortEngineEventsDesc(events || []);
        }
        return (events || []).slice().sort(function (a, b) {
            return Number(b.id || 0) - Number(a.id || 0);
        });
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
        merged = sortEventsForDisplay(merged);
        if (merged.length > limit) merged = merged.slice(0, limit);
        return merged;
    }

    function wasScrolledToTop(el) {
        if (!el) return true;
        return el.scrollTop < 48;
    }

    function ensureLogScrollPin(container, opts) {
        if (!container || !opts || container._engineLogScrollPin) return;
        container._engineLogScrollPin = true;
        if (opts._logPinTop == null) opts._logPinTop = true;
        container.addEventListener('scroll', function () {
            opts._logPinTop = wasScrolledToTop(container);
        }, { passive: true });
    }

    function scrollLogToTop(container) {
        if (!container) return;
        container.scrollTop = 0;
    }

    function shouldStickLogTop(container, opts) {
        if (opts && opts._logForceTop) return true;
        if (opts && opts._logPinTop === false) return false;
        return wasScrolledToTop(container);
    }

    function trimEventsForDisplay(events, limit) {
        var sorted = sortEventsForDisplay(events || []);
        if (sorted.length > limit) return sorted.slice(0, limit);
        return sorted;
    }

    function isConnectivityEvent(ev) {
        if (!ev) return false;
        var ty = String(ev.type || '').toUpperCase();
        var meta = ev.meta || {};
        var code = String(meta.error_code || meta.health_code || '').toUpperCase();
        if (/API_UNAUTHORIZED|BINANCE_UNREACHABLE|BINANCE_RATE|ACCOUNT_KEYS/.test(code)) return true;
        if (ty === 'ERROR' || ty === 'HEALTH_CRITICAL' || ty === 'HEALTH_WARN') {
            return /binance|beyaz liste|401|-2015|ulaşılamıyor|api anahtar/i.test(String(ev.message || ''));
        }
        return false;
    }

    function connectivityEventVisible(ev, fmtApi) {
        if (!isConnectivityEvent(ev)) return false;
        if (fmtApi && fmtApi.formatEngineEvent) {
            var fmt = fmtApi.formatEngineEvent(ev);
            if (fmt && fmt.hidden) return false;
        }
        return true;
    }

    function injectConnectivityFromHealth(events, healthData, fmtApi, botId, connectivityFailure) {
        var list = (events || []).filter(function (e) {
            return !(e && e.meta && e.meta.synthetic_live);
        });
        var fail = connectivityFailure && connectivityFailure.error_code ? connectivityFailure : null;
        if (!fail && healthData) {
            var alerts = healthData.alerts || [];
            var errCode = String(healthData.last_error_code || '').trim();
            var connAlert = alerts.some(function (a) {
                return a && (a.code === 'BINANCE_UNREACHABLE' || a.code === 'STATE_ERROR');
            });
            if (connAlert || /API_UNAUTHORIZED|BINANCE_UNREACHABLE|ACCOUNT_KEYS/i.test(errCode)) {
                fail = {
                    error_code: errCode || 'BINANCE_UNREACHABLE',
                    message: (alerts[0] && (alerts[0].message || alerts[0].title)) || 'Binance bağlantı hatası'
                };
            }
        }
        if (!fail) return list;
        if (botId && global.BotHealthAlerts && global.BotHealthAlerts.isConnectivityLogSuppressed
            && global.BotHealthAlerts.isConnectivityLogSuppressed(botId, list)) {
            return list;
        }
        if (list.some(function (ev) { return connectivityEventVisible(ev, fmtApi); })) return list;

        var msg = fail.message || 'Binance bağlantı hatası';
        if (/^Binance bağlantı hatası/i.test(msg) === false && fail.error_code) {
            msg = 'Binance bağlantı hatası — ' + msg;
        }
        var nextId = maxEventId(list) + 1;
        var synthetic = {
            id: nextId,
            type: 'ERROR',
            ts: new Date().toISOString(),
            message: msg,
            meta: {
                error_code: fail.error_code || 'BINANCE_UNREACHABLE',
                health_code: 'BINANCE_UNREACHABLE',
                synthetic_live: true,
                source: fail.source || 'connectivity'
            }
        };
        return [synthetic].concat(list);
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

    function archiveIngest(opts, events, incoming) {
        if (!global.EngineLogArchive || !opts || !opts.botId) return;
        if (incoming && incoming.length) global.EngineLogArchive.ingest(opts.botId, incoming);
        else if (events && events.length) global.EngineLogArchive.ingest(opts.botId, events);
    }

    function archiveDisplayEvents(opts, displayEvents, stateEvents) {
        if (!global.EngineLogArchive || !opts || !opts.botId || !displayEvents) return;
        displayEvents.forEach(function (ev) {
            if (ev && ev.meta && ev.meta.synthetic_live) {
                global.EngineLogArchive.ingestOne(opts.botId, ev);
            }
        });
    }

    function mergeHealthForDisplay(botId, events, healthData, opts) {
        var running = typeof opts.isBotRunning === 'function' ? !!opts.isBotRunning() : true;
        if (global.BotHealthAlerts && global.BotHealthAlerts.mergeHealthDisplayEvents) {
            return global.BotHealthAlerts.mergeHealthDisplayEvents(botId, events, healthData, running);
        }
        return events;
    }

    function renderDisplayEvents(opts) {
        if (!opts || !opts.container) return;
        var state = opts.state || { events: [], lastId: 0 };
        if (typeof global !== 'undefined') {
            global._lastEngineEvents = state.events;
        }
        var fmtApi = global.EngineLogFormat;
        var healthData = typeof opts.getHealthData === 'function' ? opts.getHealthData() : opts.healthData;
        var connFail = opts.connectivityFailure || null;
        if (opts.botId && fmtApi && fmtApi.setLogContext) {
            fmtApi.setLogContext({ botId: opts.botId, events: state.events, healthData: healthData });
        }
        var displayEvents = injectConnectivityFromHealth(state.events, healthData, fmtApi, opts.botId, connFail);
        displayEvents = mergeHealthForDisplay(opts.botId, displayEvents, healthData, opts);
        archiveDisplayEvents(opts, displayEvents, state.events);
        renderTable(opts.container, enrichStartEvents(displayEvents, opts), fmtApi, opts.botId, opts);
        if (typeof opts.onAfterRender === 'function') {
            opts.onAfterRender(state.events);
        }
    }

    function renderTable(container, events, fmtApi, botId, opts) {
        if (!container) return { rendered: false, events: events || [] };
        fmtApi = fmtApi || global.EngineLogFormat;
        opts = opts || {};
        ensureLogScrollPin(container, opts);
        var list = sortEventsForDisplay(events || []);
        if (fmtApi && fmtApi.setLogContext) {
            fmtApi.setLogContext({ botId: botId, events: list });
        }
        if (!list.length) {
            container.innerHTML = '<div class="muted" style="padding: 0.75rem;">Henüz event yok.</div>';
            return { rendered: false, events: list };
        }
        var collapsed = fmtApi && fmtApi.collapseEngineEvents ? fmtApi.collapseEngineEvents(list) : [];
        if (!collapsed.length && list.length && (!fmtApi || !fmtApi.collapseEngineEvents)) {
            collapsed = list.map(function (ev) {
                var msg = ev.message || '—';
                return { ts: ev.ts, typeLabel: ev.type || '—', message: msg, severity: 'info', count: 1 };
            });
        }
        if (!collapsed.length) {
            container.innerHTML = '<div class="muted" style="padding: 0.75rem;">Gösterilecek önemli kayıt yok (rutin uyarılar gizlendi).</div>';
            return { rendered: false, events: list };
        }
        var stickTop = shouldStickLogTop(container, opts);
        var html = '<table class="engine-log-table"><colgroup><col class="log-col-time"><col class="log-col-type"><col class="log-col-msg"></colgroup><thead><tr><th>Zaman</th><th>Tür</th><th>Mesaj</th></tr></thead><tbody>';
        collapsed.forEach(function (item) {
            var ts = (fmtApi && fmtApi.formatEventTs)
                ? fmtApi.formatEventTs(item.ts)
                : (item.ts ? String(item.ts) : '—');
            if (item.count > 1) {
                ts += ' <span class="log-repeat-badge" title="Aynı kayıttan ' + item.count + ' adet">(' + item.count + '×)</span>';
            }
            var ty = (item.typeLabel || '—').replace(/</g, '&lt;');
            var msg = (item.message || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
            var rowCl = fmtApi && fmtApi.rowClass ? fmtApi.rowClass(item.severity) : 'log-row-info';
            if (item.healthActive) {
                rowCl += item.severity === 'critical' ? ' log-row-health-active-crit' : ' log-row-health-active-warn';
            }
            html += '<tr class="' + rowCl + '"><td>' + ts + '</td><td>' + ty + '</td><td>' + msg + '</td></tr>';
        });
        html += '</tbody></table>';
        container.innerHTML = html;
        if (stickTop) scrollLogToTop(container);
        if (opts._logForceTop) opts._logForceTop = false;
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
            if (!incremental && !(state.events && state.events.length)) {
                opts.container.innerHTML = '<div class="muted" style="padding: 0.75rem;">Yükleniyor…</div>';
            }
            opts._logForceTop = true;
            opts._logPinTop = true;
            url = '/api/bots-engine/' + opts.botId + '/events' + qBase +
                (qBase ? '&' : '?') + 'limit=' + MAX_EVENTS;
        }
        return opts.apiClient.get(url).then(function (res) {
            opts._failCount = 0;
            opts.connectivityFailure = (res && res.connectivity_failure) ? res.connectivity_failure : null;
            var incoming = (res && res.events) ? res.events : [];
            if (incremental && state.lastId > 0) {
                if (incoming.length) {
                    state.events = mergeEvents(state.events, incoming, MAX_EVENTS);
                    state.lastId = maxEventId(state.events);
                    archiveIngest(opts, state.events, incoming);
                }
            } else {
                state.events = trimEventsForDisplay(incoming, MAX_EVENTS);
                state.lastId = maxEventId(state.events);
                archiveIngest(opts, state.events, incoming);
            }
            if (typeof global !== 'undefined') {
                global._lastEngineEvents = state.events;
            }
            var fmtApi = global.EngineLogFormat;
            var healthData = typeof opts.getHealthData === 'function' ? opts.getHealthData() : opts.healthData;
            if (opts.botId && global.EngineLogFormat && global.EngineLogFormat.setLogContext) {
                global.EngineLogFormat.setLogContext({
                    botId: opts.botId,
                    events: state.events,
                    healthData: healthData
                });
            }
            var connFail = opts.connectivityFailure || null;
            var displayEvents = injectConnectivityFromHealth(state.events, healthData, fmtApi, opts.botId, connFail);
            displayEvents = mergeHealthForDisplay(opts.botId, displayEvents, healthData, opts);
            archiveDisplayEvents(opts, displayEvents, state.events);
            renderTable(opts.container, enrichStartEvents(displayEvents, opts), fmtApi, opts.botId, opts);
            if (typeof opts.onAfterRender === 'function') {
                opts.onAfterRender(state.events);
            }
            return state.events;
        }).catch(function () {
            opts._failCount = (opts._failCount || 0) + 1;
            if (!incremental) {
                opts.container.innerHTML = '<div class="muted" style="padding: 0.75rem;">Loglar yüklenemedi.</div>';
            } else if (opts._failCount >= 2 && typeof opts.onPollError === 'function') {
                opts.onPollError(opts._failCount);
            }
            return state.events;
        });
    }

    function startPolling(opts) {
        stopPolling(opts);
        if (!opts || !opts.botId) return;
        opts.state = opts.state || { events: [], lastId: 0 };
        opts._failCount = 0;
        opts._logPinTop = true;
        opts._logForceTop = true;
        opts._lastFullRefresh = Date.now();
        opts._pollTimer = setInterval(function () {
            if (document.hidden) return;
            var forceFull = (opts._failCount || 0) >= 2
                || (Date.now() - (opts._lastFullRefresh || 0) > FULL_REFRESH_MS);
            if (forceFull) opts._lastFullRefresh = Date.now();
            fetchAndRender(opts, !forceFull && opts.state.lastId > 0);
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
        renderDisplayEvents: renderDisplayEvents,
        startPolling: startPolling,
        stopPolling: stopPolling,
        renderTable: renderTable
    };
})(typeof window !== 'undefined' ? window : globalThis);
