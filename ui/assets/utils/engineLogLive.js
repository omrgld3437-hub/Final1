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

    function eventMergeKey(e) {
        if (!e) return '';
        var id = e.id != null ? Number(e.id) : 0;
        if (Number.isFinite(id) && id !== 0) return 'id:' + id;
        var meta = e.meta || {};
        if ((e.type || '') === 'CYCLE_START' && meta.cycle_id != null) {
            return 'CYCLE_START:' + meta.cycle_id + ':' + (meta.synthetic ? 's' : 'd');
        }
        if ((e.type || '') === 'CYCLE_END' && meta.cycle_id != null) {
            return 'CYCLE_END:' + meta.cycle_id;
        }
        return 'anon:' + (e.type || '') + ':' + (e.ts || '') + ':' + (e.message || '').slice(0, 40);
    }

    function mergeEvents(existing, incoming, limit) {
        var byKey = {};
        (existing || []).forEach(function (e) {
            var k = eventMergeKey(e);
            if (k) byKey[k] = e;
        });
        (incoming || []).forEach(function (e) {
            var k = eventMergeKey(e);
            if (k) byKey[k] = e;
        });
        var merged = Object.keys(byKey).map(function (k) { return byKey[k]; });
        if (global.EngineLogFormat && global.EngineLogFormat.dedupeCycleStartForDisplay) {
            merged = global.EngineLogFormat.dedupeCycleStartForDisplay(merged);
        }
        if (global.EngineLogFormat && global.EngineLogFormat.dedupeCycleEndForDisplay) {
            merged = global.EngineLogFormat.dedupeCycleEndForDisplay(merged);
        }
        merged = sortEventsForDisplay(merged);
        if (merged.length > limit) merged = merged.slice(0, limit);
        return merged;
    }

    function wasScrolledToTop(el) {
        if (!el) return true;
        return el.scrollTop < 8;
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

    /** DOM yenilendikten sonra scrollTop=0 olur; yalnızca kullanıcı bayrağına güven. */
    function shouldStickLogTop(container, opts) {
        if (opts && opts._logForceTop) return true;
        if (opts && opts._logPinTop === false) return false;
        if (opts && opts._logPinTop === true) return true;
        return wasScrolledToTop(container);
    }

    function restoreScrollAfterRender(container, stickTop, scrollTopBefore, scrollHeightBefore) {
        if (!container) return;
        if (stickTop) {
            scrollLogToTop(container);
            return;
        }
        if (scrollTopBefore <= 0) return;
        var delta = container.scrollHeight - scrollHeightBefore;
        container.scrollTop = Math.max(0, scrollTopBefore + delta);
    }

    function collapsedRenderSignature(collapsed) {
        if (!collapsed || !collapsed.length) return '';
        return collapsed.map(function (item) {
            if (item.spacer) return '\x1fS\x1f';
            return String(item.key || '') + '\x1f' + String(item.count || 1) + '\x1f' + String(item.message || '').slice(0, 120);
        }).join('\n');
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

    function injectConnectivityFromHealth(events, healthData, fmtApi, botId, connectivityFailure, opts) {
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
        var code = fail.error_code || 'BINANCE_UNREACHABLE';
        var prev = opts && opts._connectivitySynthetic;
        if (prev && prev.meta && prev.meta.error_code === code && prev.message === msg) {
            return [prev].concat(list);
        }
        var anchorTs = (list[0] && list[0].ts) ? list[0].ts : null;
        var synthetic = {
            id: -990001,
            type: 'ERROR',
            ts: anchorTs || (prev && prev.ts) || '',
            message: msg,
            meta: {
                error_code: code,
                health_code: 'BINANCE_UNREACHABLE',
                synthetic_live: true,
                source: fail.source || 'connectivity'
            }
        };
        if (opts) opts._connectivitySynthetic = synthetic;
        return [synthetic].concat(list);
    }

    function prepareLogDisplay(events, opts, fmtApi, botId) {
        var healthData = typeof opts.getHealthData === 'function' ? opts.getHealthData() : opts.healthData;
        var connFail = opts.connectivityFailure || null;
        var displayEvents = injectConnectivityFromHealth(events, healthData, fmtApi, botId, connFail, opts);
        displayEvents = mergeHealthForDisplay(botId, displayEvents, healthData, opts);
        displayEvents = enrichStartEvents(displayEvents, opts);
        var list = displayEvents || [];
        if (fmtApi && fmtApi.dedupeCycleStartForDisplay) {
            list = fmtApi.dedupeCycleStartForDisplay(list);
        }
        if (fmtApi && fmtApi.dedupeCycleEndForDisplay) {
            list = fmtApi.dedupeCycleEndForDisplay(list);
        }
        list = sortEventsForDisplay(list);
        if (fmtApi && fmtApi.setLogContext) {
            fmtApi.setLogContext({
                botId: botId,
                events: list,
                healthData: healthData,
                initialCapital: opts.initialCapital,
                currentCycleId: opts.currentCycleId,
                quoteBalance: opts.quoteBalance,
                baseBalance: opts.baseBalance,
                config: opts.config,
                cycleStartEquity: opts.cycleStartEquity,
                cycleOpenTrades: opts.cycleOpenTrades
            });
        }
        var collapsed = [];
        if (list.length && fmtApi && fmtApi.collapseEngineEvents) {
            collapsed = fmtApi.collapseEngineEvents(list);
        } else if (list.length) {
            collapsed = list.map(function (ev) {
                return { ts: ev.ts, typeLabel: ev.type || '—', message: ev.message || '—', severity: 'info', count: 1, key: 'raw\x1f' + (ev.id || '') };
            });
        }
        return {
            displayEvents: displayEvents,
            list: list,
            collapsed: collapsed,
            signature: collapsedRenderSignature(collapsed) + '\x1e' + list.length + '\x1e' + maxEventId(list)
        };
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
            fmtApi.setLogContext({
                botId: opts.botId,
                events: state.events,
                healthData: healthData,
                initialCapital: opts.initialCapital,
                currentCycleId: opts.currentCycleId,
                quoteBalance: opts.quoteBalance,
                baseBalance: opts.baseBalance,
                config: opts.config,
                cycleStartEquity: opts.cycleStartEquity,
                cycleOpenTrades: opts.cycleOpenTrades
            });
        }
        renderTable(opts.container, state.events, fmtApi, opts.botId, opts);
        if (typeof opts.onAfterRender === 'function') {
            opts.onAfterRender(state.events);
        }
    }

    function renderTable(container, events, fmtApi, botId, opts) {
        if (!container) return { rendered: false, events: events || [] };
        fmtApi = fmtApi || global.EngineLogFormat;
        opts = opts || {};
        ensureLogScrollPin(container, opts);
        var prep = prepareLogDisplay(events || [], opts, fmtApi, botId);
        var list = prep.list;
        var collapsed = prep.collapsed;
        if (!list.length) {
            if (opts._logBootstrapping) {
                return { rendered: false, events: list, skipped: true };
            }
            if (opts._lastLogRenderSig !== 'empty') {
                container.innerHTML = '<div class="muted" style="padding: 0.75rem;">Henüz event yok.</div>';
                opts._lastLogRenderSig = 'empty';
            }
            return { rendered: false, events: list, skipped: true };
        }
        if (!collapsed.length) {
            if (opts._logBootstrapping) {
                return { rendered: false, events: list, skipped: true };
            }
            var emptySig = 'hidden\x1e' + prep.signature;
            if (opts._lastLogRenderSig !== emptySig) {
                container.innerHTML = '<div class="muted" style="padding: 0.75rem;">Gösterilecek önemli kayıt yok (rutin uyarılar gizlendi).</div>';
                opts._lastLogRenderSig = emptySig;
            }
            return { rendered: false, events: list, skipped: true };
        }
        if (opts._lastLogRenderSig === prep.signature && container.querySelector('table.engine-log-table')) {
            return { rendered: false, events: list, collapsed: collapsed, skipped: true };
        }
        opts._lastLogRenderSig = prep.signature;
        var stickTop = shouldStickLogTop(container, opts);
        var scrollTopBefore = container.scrollTop;
        var scrollHeightBefore = container.scrollHeight;
        var html = '<table class="engine-log-table"><colgroup><col class="log-col-time"><col class="log-col-type"><col class="log-col-msg"></colgroup><thead><tr><th>Zaman</th><th>Tür</th><th>Mesaj</th></tr></thead><tbody>';
        collapsed.forEach(function (item) {
            if (item.spacer) {
                html += '<tr class="log-row-spacer" aria-hidden="true"><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td></tr>';
                return;
            }
            var ts = (fmtApi && fmtApi.formatEventTs)
                ? fmtApi.formatEventTs(item.ts)
                : (item.ts ? String(item.ts) : '—');
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
        restoreScrollAfterRender(container, stickTop, scrollTopBefore, scrollHeightBefore);
        if (opts._logForceTop) opts._logForceTop = false;
        archiveDisplayEvents(opts, prep.displayEvents, events);
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
                opts._logBootstrapping = true;
                var hasTable = opts.container.querySelector('table.engine-log-table');
                var hasLoading = opts.container.querySelector('.engine-log-loading');
                if (!hasTable && !hasLoading) {
                    opts.container.innerHTML = '<div class="muted engine-log-loading" style="padding: 0.75rem;">Yükleniyor…</div>';
                }
            }
            opts._logForceTop = true;
            opts._logPinTop = true;
            url = '/api/bots-engine/' + opts.botId + '/events' + qBase +
                (qBase ? '&' : '?') + 'limit=' + MAX_EVENTS;
        }
        return opts.apiClient.get(url).then(function (res) {
            opts._failCount = 0;
            opts.connectivityFailure = (res && res.connectivity_failure) ? res.connectivity_failure : null;
            if (typeof global !== 'undefined') {
                global._lastConnectivityProbeOk = !!(res && res.connectivity_ok !== false && !res.connectivity_failure);
                global._lastConnectivityFailure = opts.connectivityFailure || null;
            }
            var incoming = (res && res.events) ? res.events : [];
            var didMerge = false;
            if (incremental && state.lastId > 0) {
                if (incoming.length) {
                    state.events = mergeEvents(state.events, incoming, MAX_EVENTS);
                    state.lastId = maxEventId(state.events);
                    archiveIngest(opts, state.events, incoming);
                    didMerge = true;
                }
            } else {
                state.events = trimEventsForDisplay(incoming, MAX_EVENTS);
                state.lastId = maxEventId(state.events);
                archiveIngest(opts, state.events, incoming);
                didMerge = true;
            }
            if (typeof global !== 'undefined') {
                global._lastEngineEvents = state.events;
            }
            if (didMerge || !incremental || !(state.events && state.events.length)) {
                renderTable(opts.container, state.events, global.EngineLogFormat, opts.botId, opts);
            }
            opts._logBootstrapping = false;
            if (typeof opts.onAfterRender === 'function') {
                opts.onAfterRender(state.events);
            }
            return state.events;
        }).catch(function (err) {
            opts._failCount = (opts._failCount || 0) + 1;
            if (!incremental) {
                var retryBtn = opts._failCount < 3
                    ? ' <button type="button" class="btn btn-sm" data-engine-log-retry style="margin-left:0.5rem;">Tekrar dene</button>'
                    : '';
                opts.container.innerHTML = '<div class="muted" style="padding: 0.75rem;">Loglar yüklenemedi.' + retryBtn + '</div>';
                var retryEl = opts.container.querySelector('[data-engine-log-retry]');
                if (retryEl) {
                    retryEl.onclick = function () {
                        opts._failCount = 0;
                        fetchAndRender(opts, false);
                    };
                }
            } else if (opts._failCount >= 2 && typeof opts.onPollError === 'function') {
                opts.onPollError(opts._failCount);
            }
            if (opts._failCount === 1 && !incremental) {
                setTimeout(function () { fetchAndRender(opts, false); }, 2500);
            }
            if (typeof console !== 'undefined' && console.debug) {
                console.debug('engineLog fetch failed', err);
            }
            return state.events;
        });
    }

    function startPolling(opts, skipSigReset) {
        stopPolling(opts);
        if (!opts || !opts.botId) return;
        opts.state = opts.state || { events: [], lastId: 0 };
        opts._failCount = 0;
        opts._logPinTop = true;
        opts._logForceTop = true;
        if (!skipSigReset) {
            opts._lastLogRenderSig = null;
            opts._connectivitySynthetic = null;
        }
        opts._lastFullRefresh = Date.now();
        opts._pollTimer = setInterval(function () {
            if (document.hidden) return;
            var forceFull = (opts._failCount || 0) >= 1
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
