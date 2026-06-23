/**
 * dashboard-tx-history.js
 * İşlem geçmişi: loadTransactionHistory, pollTransactionHistoryRevision,
 * openTxDetailModal, closeTxDetailModal.
 * dashboard.js'ten SONRA yüklenir.
 */

var _txHistoryRevision = '';
var _txHistoryLastSig = '';
var _txHistoryPollInFlight = false;
var _txHistoryLoaded = false;
const TX_HISTORY_POLL_MS = 3500;
var _txHistoryRateLimitUntil = 0;

var _txHistoryInitialSyncDone = false;
var _txHistoryLoadSeq = 0;
var _txHistoryInflight = null;
var _txHistoryInflightKey = '';
var _spotTxHistoryPending = {};

function _txHistoryListHasContent() {
    var listEl = document.getElementById('txHistoryList');
    if (!listEl) return false;
    return !!listEl.querySelector('.tx-history-item');
}

function resetTxHistoryClientState() {
    _txHistoryRevision = '';
    _txHistoryLastSig = '';
    _txHistoryLoaded = false;
    _txHistoryInitialSyncDone = false;
    _txHistoryLoadSeq += 1;
    _txHistoryInflight = null;
    _txHistoryInflightKey = '';
    _spotTxHistoryPending = {};
}
window.resetTxHistoryClientState = resetTxHistoryClientState;

function _txHistoryPayload(res) {
    if (!res) return null;
    if (Array.isArray(res.items)) return res;
    if (res.data && Array.isArray(res.data.items)) return res.data;
    if (res.data && typeof res.data === 'object') return res.data;
    return res;
}

function _txEncodeAttr(tx) {
    try {
        return encodeURIComponent(JSON.stringify(tx));
    } catch (e) {
        return '';
    }
}
function _txIsPaperSpotTx(tx) {
    if (!tx) return false;
    if (tx.paper === true) return true;
    var oid = String(tx.order_id || tx.trade_id || '');
    return oid.indexOf('test_paper_') === 0;
}
function _txPlatformLabel(tx) {
    if (!tx) return 'Binance';
    if (tx.bot_id || tx.source === 'bot') return 'ayserose';
    if (_txIsPaperSpotTx(tx)) return 'ayserose';
    var p = tx.platform && String(tx.platform);
    // Eski kayıtlardaki marka adlarını yeni markaya normalleştir (geriye dönük uyum).
    if (p) return (p === 'TradeTrailing' || p === 'TraderTrailing') ? 'ayserose' : p;
    return 'Binance';
}

function isTransactionHistoryPanelVisible() {
    var panel = document.getElementById('transactionHistoryPanel');
    if (!panel || panel.style.display === 'none') return false;
    var tab = document.querySelector('.dm-tab.is-active');
    var tabName = tab && tab.getAttribute('data-tab');
    return tabName === 'binance' || tabName === 'varliklar' || !tabName;
}

function _txHistoryItemsSig(d) {
    if (!d || !Array.isArray(d.items)) return '';
    return String(d.revision || '') + '|' + (d.total || 0) + '|' + d.items.map(function (tx) {
        return (tx.id || '') + ':' + (tx.time || '') + ':' + (tx.qty || '');
    }).join(';');
}

function clearTxHistoryUiCache(accountId) {
    if (!accountId) return;
    try {
        var prefix = TX_HISTORY_CACHE_PREFIX + accountId;
        [sessionStorage, localStorage].forEach(function (store) {
            for (var i = store.length - 1; i >= 0; i--) {
                var k = store.key(i);
                if (k && k.indexOf(prefix) === 0) store.removeItem(k);
            }
        });
    } catch (e) { /* ignore */ }
}

function _fmtTxQtyShort(n) {
    if (n == null || !Number.isFinite(n)) return '—';
    var s = Number(n).toFixed(8).replace(/\.?0+$/, '');
    return s || '0';
}

function _renderTxHistoryItemHtml(tx) {
    var timeStr = tx.time ? new Date(tx.time).toLocaleString('tr-TR', { dateStyle: 'short', timeStyle: 'short' }) : '—';
    var typeLabel = tx.type_label || (tx.type === 'buy' ? 'Alım' : tx.type === 'sell' ? 'Satım' : tx.type === 'deposit' ? 'Yatırım' : tx.type === 'withdraw' ? 'Çekim' : '—');
    var typeClass = tx.type === 'buy' ? 'tx-type-buy' : tx.type === 'sell' ? 'tx-type-sell' : tx.type === 'deposit' ? 'tx-type-deposit' : tx.type === 'withdraw' ? 'tx-type-withdraw' : '';
    var amtRow = _txDisplayAmounts(tx);
    var qtyStr = _fmtTxQtyShort(amtRow.qty);
    var priceStr = amtRow.price > 0 ? (typeof fmtCoinPrice === 'function' ? fmtCoinPrice(amtRow.price) : '$' + Number(amtRow.price).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 8 })) : '—';
    var totalVal = (tx.type === 'deposit' || tx.type === 'withdraw')
        ? (qtyStr + ' ' + (tx.symbol || ''))
        : (amtRow.notional > 0 ? (typeof fmtUsd === 'function' ? fmtUsd(amtRow.notional) : '$' + amtRow.notional) : '—');
    var sourceLabel = tx.source_label || (tx.source === 'bot' ? 'Bot' : tx.source === 'spot' ? 'Spot' : '—');
    var platformLabel = _txPlatformLabel(tx);
    var paperBadge = tx.is_paper ? ' <span style="font-size:0.7rem;padding:1px 5px;border-radius:4px;background:rgba(240,185,11,0.15);color:#f0b90b;font-weight:600;vertical-align:middle;">SİMÜLE</span>' : '';
    var metaRight = (tx.type === 'buy' || tx.type === 'sell') ? ('Miktar ' + qtyStr + ' · Fiyat ' + priceStr) : (qtyStr + (tx.symbol ? ' ' + tx.symbol : ''));
    return '<div class="tx-history-item" data-tx="' + _txEncodeAttr(tx) + '" role="button" tabindex="0">' +
        '<div class="tx-history-item-left">' +
        '<div class="tx-history-item-title"><span class="' + typeClass + '">' + typeLabel + '</span>' + paperBadge + ' ' + (tx.symbol || '') + '</div>' +
        '<div class="tx-history-item-meta">' + timeStr + ' · ' + sourceLabel + ' · ' + platformLabel + (tx.bot_name ? ' · ' + tx.bot_name : '') + '</div>' +
        '</div>' +
        '<div class="tx-history-item-right">' +
        '<div class="tx-history-item-total">' + totalVal + '</div>' +
        '<div class="tx-history-item-meta">' + metaRight + '</div>' +
        '</div></div>';
}

function _bindTxHistoryItemClicks(rootEl) {
    var listEl = rootEl || document.getElementById('txHistoryList');
    if (!listEl) return;
    listEl.querySelectorAll('.tx-history-item').forEach(function (el) {
        el.onclick = function () {
            try {
                var raw = el.getAttribute('data-tx');
                var tx = raw ? JSON.parse(decodeURIComponent(raw)) : null;
                if (tx && typeof openTxDetailModal === 'function') openTxDetailModal(tx);
            } catch (e) {}
        };
    });
}

function spotOrderResultToTxItem(result, symbol, side) {
    var r = result || {};
    var executedQty = parseFloat(r.executedQty != null ? r.executedQty : r.executed_qty);
    var cumQuote = parseFloat(r.cummulativeQuoteQty != null ? r.cummulativeQuoteQty : (r.cumulativeQuoteQty != null ? r.cumulativeQuoteQty : r.executed_value_usdt));
    var price = parseFloat(r.price || 0);
    if (!Number.isFinite(executedQty)) executedQty = 0;
    if (!Number.isFinite(cumQuote)) cumQuote = 0;
    if (!Number.isFinite(price)) price = 0;
    if (executedQty > 0 && cumQuote > 0) price = cumQuote / executedQty;
    var sideU = (side || r.side || '').toUpperCase();
    var isBuy = sideU === 'BUY';
    var sym = (symbol || r.symbol || '').toUpperCase();
    var orderId = String(r.orderId || r.order_id || ('spot_' + Date.now()));
    return {
        id: 'o_' + orderId,
        trade_id: orderId,
        order_id: orderId,
        time: new Date().toISOString(),
        type: isBuy ? 'buy' : 'sell',
        type_label: isBuy ? 'Alım' : 'Satım',
        symbol: sym,
        side: sideU,
        qty: executedQty,
        price: price,
        quote_qty: cumQuote,
        commission: 0,
        commission_asset: 'USDT',
        source: 'spot',
        source_label: 'Spot',
        platform: r.paper ? 'ayserose' : 'Binance',
        fills_count: 1
    };
}

function spotTradeMatchesTxHistoryFilters(side) {
    var typeFilter = (State.txHistoryType || 'buysell').toLowerCase();
    var sideU = (side || '').toUpperCase();
    if (typeFilter === 'buy' && sideU !== 'BUY') return false;
    if (typeFilter === 'sell' && sideU !== 'SELL') return false;
    if (typeFilter === 'deposit' || typeFilter === 'withdraw' || typeFilter === 'depositwithdraw') return false;
    return true;
}

function spotTxPendingMatchesPeriod(tx, period) {
    if (!tx || !tx.time) return true;
    var p = (period || 'daily').toLowerCase();
    if (p === 'all') return true;
    var d = new Date(tx.time);
    if (isNaN(d.getTime())) return true;
    var fmt = function (dt) { return dt.toLocaleDateString('en-CA', { timeZone: 'Europe/Istanbul' }); };
    var txDay = fmt(d);
    var today = fmt(new Date());
    if (p === 'daily') return txDay === today;
    var diffDays = Math.floor((new Date(today).getTime() - new Date(txDay).getTime()) / 86400000);
    if (p === 'weekly') return diffDays >= 0 && diffDays <= 6;
    if (p === 'monthly') return diffDays >= 0 && diffDays <= 29;
    return true;
}

function registerPendingSpotTxHistory(result, symbol, side) {
    if (!spotTradeMatchesTxHistoryFilters(side)) return null;
    var tx = spotOrderResultToTxItem(result, symbol, side);
    if (!(tx.qty > 0) && !(tx.quote_qty > 0)) return null;
    var oid = String(tx.order_id || tx.trade_id || '');
    if (oid) _spotTxHistoryPending[oid] = tx;
    return tx;
}

function clearPendingSpotTxFromServerItems(items) {
    (items || []).forEach(function (tx) {
        var oid = String(tx.order_id || tx.trade_id || '');
        if (oid && _spotTxHistoryPending[oid]) delete _spotTxHistoryPending[oid];
    });
}

function mergePendingSpotTxHistoryItems(serverItems, period) {
    var items = Array.isArray(serverItems) ? serverItems.slice() : [];
    var serverIds = {};
    items.forEach(function (tx) {
        var oid = String(tx.order_id || tx.trade_id || '');
        if (oid) serverIds[oid] = true;
    });
    var pending = [];
    Object.keys(_spotTxHistoryPending).forEach(function (k) {
        var tx = _spotTxHistoryPending[k];
        if (!tx) return;
        var oid = String(tx.order_id || tx.trade_id || '');
        if (serverIds[oid]) return;
        if (!spotTradeMatchesTxHistoryFilters(tx.side)) return;
        if (!spotTxPendingMatchesPeriod(tx, period)) return;
        pending.push(tx);
    });
    pending.sort(function (a, b) {
        return String(b.time || '').localeCompare(String(a.time || ''));
    });
    return pending.concat(items);
}

function _paintTxHistoryList(items, page, total, perPage, totalPages, period, typeFilter) {
    var listEl = document.getElementById('txHistoryList');
    var paginationEl = document.getElementById('txHistoryPagination');
    if (!listEl) return;
    if (!items || items.length === 0) {
        listEl.innerHTML = '<div class="tx-history-empty" style="text-align:center;padding:2rem;color:var(--ds-text-secondary);">Bu filtrede işlem bulunamadı.</div>';
    } else {
        var html = items.map(function (tx) { return _renderTxHistoryItemHtml(tx); }).join('');
        listEl.innerHTML = '<div class="tx-history-items">' + html + '</div>';
        _bindTxHistoryItemClicks(listEl);
    }
    if (paginationEl) {
        if (totalPages > 1) {
            var pg = '';
            if (page > 1) pg += '<button type="button" class="btn btn-sm tx-pg-btn" data-page="' + (page - 1) + '">← Önceki</button>';
            pg += '<span style="margin:0 0.5rem;font-size:0.9rem;color:var(--ds-text-secondary);">Sayfa ' + page + ' / ' + totalPages + '</span>';
            if (page < totalPages) pg += '<button type="button" class="btn btn-sm tx-pg-btn" data-page="' + (page + 1) + '">Sonraki →</button>';
            paginationEl.innerHTML = pg;
            paginationEl.querySelectorAll('.tx-pg-btn').forEach(function (btn) {
                btn.onclick = function () {
                    var p = parseInt(btn.getAttribute('data-page'), 10);
                    if (typeof loadTransactionHistory === 'function') loadTransactionHistory(State.txHistoryPeriod, State.txHistoryType, p, false, { force: true });
                };
            });
        } else {
            paginationEl.innerHTML = '';
        }
    }
    document.querySelectorAll('.tx-period-btn').forEach(function (b) { b.classList.toggle('active', b.getAttribute('data-period') === period); });
    document.querySelectorAll('.tx-type-btn').forEach(function (b) { b.classList.toggle('active', b.getAttribute('data-type') === typeFilter); });
}

function scheduleTxHistoryRefreshAfterTrade(result, symbol, side) {
    if (!State.accountId || typeof loadTransactionHistory !== 'function') return;
    registerPendingSpotTxHistory(result, symbol, side);
    if (typeof prependSpotTradeToTxHistoryPanel === 'function') {
        prependSpotTradeToTxHistoryPanel(result, symbol, side);
    }
    var period = State.txHistoryPeriod || 'daily';
    var typeFilter = State.txHistoryType || 'buysell';
    [0, 400, 1000, 2500].forEach(function (delayMs) {
        setTimeout(function () {
            if (!State.accountId) return;
            loadTransactionHistory(period, typeFilter, 1, false, { force: true, afterTrade: true });
        }, delayMs);
    });
}

function prependSpotTradeToTxHistoryPanel(result, symbol, side) {
    var tx = registerPendingSpotTxHistory(result, symbol, side);
    if (!tx) return null;
    var listEl = document.getElementById('txHistoryList');
    if (!listEl) return tx;
    var container = listEl.querySelector('.tx-history-items');
    var html = _renderTxHistoryItemHtml(tx);
    var dup = false;
    if (container) {
        container.querySelectorAll('.tx-history-item').forEach(function (el) {
            try {
                var raw = el.getAttribute('data-tx');
                var existing = raw ? JSON.parse(decodeURIComponent(raw)) : null;
                if (existing && (String(existing.order_id) === String(tx.order_id) || String(existing.trade_id) === String(tx.trade_id))) dup = true;
            } catch (e) {}
        });
    }
    if (!dup) {
        if (!container) {
            listEl.innerHTML = '<div class="tx-history-items">' + html + '</div>';
        } else {
            container.insertAdjacentHTML('afterbegin', html);
        }
        _bindTxHistoryItemClicks(listEl);
    }
    return tx;
}

function formatSpotTradeFillToast(result, side, orderType, symbol) {
    var tx = spotOrderResultToTxItem(result, symbol, side);
    var typeLabel = (orderType || 'MARKET').toUpperCase() === 'LIMIT' ? 'Limit' : 'Market';
    var sideLabel = tx.type_label || ((side || '').toUpperCase() === 'BUY' ? 'Alış' : 'Satış');
    var sym = (symbol || tx.symbol || '').toUpperCase();
    var base = sym.endsWith('USDT') ? sym.slice(0, -4) : sym;
    var qtyStr = _fmtTxQtyShort(tx.qty);
    var quoteStr = tx.quote_qty > 0
        ? (typeof fmtUsd === 'function' ? fmtUsd(tx.quote_qty) : ('$' + Number(tx.quote_qty).toFixed(2)))
        : '—';
    if (!(tx.qty > 0) && !(tx.quote_qty > 0)) {
        return typeLabel + ' ' + sideLabel + ' emri gönderildi';
    }
    return typeLabel + ' ' + sideLabel + ' gerçekleşti: ' + qtyStr + ' ' + base + ' · ' + quoteStr;
}

async function pollTransactionHistoryRevision() {
    if (!State.accountId || !window.apiClient || _txHistoryPollInFlight) return;
    if (Date.now() < _txHistoryRateLimitUntil) return;
    var panelVisible = isTransactionHistoryPanelVisible();
    _txHistoryPollInFlight = true;
    try {
        var res = await window.apiClient.get(
            '/api/accounts/' + State.accountId + '/transaction-history/revision',
            { timeout: 6000, suppressRateLimitToast: true }
        );
        var body = res && (res.data || res);
        var rev = body && body.revision != null ? String(body.revision) : '';
        if (!rev) return;
        if (!_txHistoryLoaded || rev !== _txHistoryRevision) {
            _txHistoryRevision = rev;
            // Panel görünür değilse sadece revision'ı kaydet; görünür olunca hemen yüklesin
            if (!panelVisible) { _txHistoryLastSig = ''; return; }
            await loadTransactionHistory(
                State.txHistoryPeriod || 'daily',
                State.txHistoryType || 'buysell',
                State.txHistoryPage || 1,
                false,
                { silent: _txHistoryLoaded }
            );
        }
    } catch (e) {
        if (e && e.status === 429) {
            var ra = (e.retry_after != null) ? Number(e.retry_after) : 60;
            _txHistoryRateLimitUntil = Date.now() + Math.min(120000, Math.max(15000, ra * 1000));
        }
    } finally {
        _txHistoryPollInFlight = false;
    }
}

async function loadTransactionHistory(period, typeFilter, page, sync, opts) {
    opts = opts || {};
    var force = !!opts.force;
    var afterTrade = !!opts.afterTrade;
    var silent = !!opts.silent && !force;
    if (!State.accountId || !window.apiClient) return;
    var listEl = document.getElementById('txHistoryList');
    var paginationEl = document.getElementById('txHistoryPagination');
    if (!listEl) return;
    var hadCache = false;
    if (force) {
        if (!afterTrade) _txHistoryRevision = '';
        _txHistoryLastSig = '';
        silent = false;
        clearTxHistoryUiCache(State.accountId);
    } else {
        hadCache = hydrateTransactionHistoryFromCache(State.accountId, period, typeFilter, page);
        if (hadCache) silent = true;
    }
    var hasContent = _txHistoryListHasContent();
    if (hasContent && !force) silent = true;
    if (!silent) _txHistoryLastSig = '';
    var doSync = !!sync || (!_txHistoryInitialSyncDone && (typeFilter || 'buysell') === 'buysell' && !hadCache && !force);
    if (doSync) _txHistoryInitialSyncDone = true;
    if (!force && Date.now() < _txHistoryRateLimitUntil) return;
    var reqKey = String(State.accountId) + '|' + period + '|' + typeFilter + '|' + page + '|' + (doSync ? '1' : '0');
    if (afterTrade) {
        _txHistoryInflight = null;
        _txHistoryInflightKey = '';
        reqKey += '|at' + Date.now();
    } else if (_txHistoryInflight && _txHistoryInflightKey === reqKey) {
        return _txHistoryInflight;
    }
    var mySeq = ++_txHistoryLoadSeq;
    var txHistoryRequestDone = false;
    var loadingTimer = null;
    if (!silent && !hadCache && !hasContent) {
        loadingTimer = setTimeout(function () {
            if (txHistoryRequestDone || mySeq !== _txHistoryLoadSeq) return;
            listEl.innerHTML = '<div class="tx-history-loading" style="text-align:center;padding:2rem;color:var(--ds-text-secondary);">Yükleniyor...</div>';
        }, 200);
        if (paginationEl) paginationEl.innerHTML = '';
    }
    State.txHistoryPeriod = period;
    State.txHistoryType = typeFilter;
    State.txHistoryPage = page;
    var q = '/api/accounts/' + State.accountId + '/transaction-history?period=' + encodeURIComponent(period) + '&type_filter=' + encodeURIComponent(typeFilter) + '&page=' + page + (doSync ? '&sync=1' : '');
    if (!doSync && !force && _txHistoryRevision) {
        q += '&revision=' + encodeURIComponent(_txHistoryRevision);
    }
    if (afterTrade) q += '&_nc=' + Date.now();
    _txHistoryInflightKey = reqKey;
    _txHistoryInflight = (async function () {
    try {
        var res = await window.apiClient.get(q, { suppressRateLimitToast: !!silent });
        if (mySeq !== _txHistoryLoadSeq) return;
        txHistoryRequestDone = true;
        if (loadingTimer) clearTimeout(loadingTimer);
        var d = _txHistoryPayload(res);
        if (d && d.revision != null) _txHistoryRevision = String(d.revision);
        var rawItems = (d && Array.isArray(d.items)) ? d.items : null;
        if (rawItems) clearPendingSpotTxFromServerItems(rawItems);
        var items = rawItems ? mergePendingSpotTxHistoryItems(rawItems, period) : mergePendingSpotTxHistoryItems([], period);
        var sigPayload = d ? Object.assign({}, d, { items: items }) : { items: items };
        var sig = _txHistoryItemsSig(sigPayload);
        if (silent && !force && sig && sig === _txHistoryLastSig) return;
        _txHistoryLastSig = sig;
        _txHistoryLoaded = true;
        if (!rawItems && items.length === 0) {
            if (!hasContent && !_txHistoryListHasContent()) {
                listEl.innerHTML = '<div class="tx-history-empty" style="text-align:center;padding:2rem;color:var(--ds-text-secondary);">İşlem bulunamadı.</div>';
            }
            return;
        }
        var total = Number(d && d.total) || 0;
        var perPage = Number(d && d.per_page) || 20;
        var totalPages = Number(d && d.total_pages) || 0;
        if (page === 1 && items.length > total) total = items.length;
        if (!totalPages && total > 0) totalPages = Math.ceil(total / perPage);
        if (total > 0 && total <= perPage) totalPages = 1;
        if (totalPages < 1 && total > 0) totalPages = 1;
        _paintTxHistoryList(items, page, total, perPage, totalPages, period, typeFilter);
        _persistTxHistoryCache(
            State.accountId,
            period,
            typeFilter,
            page,
            listEl.innerHTML,
            paginationEl ? paginationEl.innerHTML : '',
            sig,
            _txHistoryRevision
        );
        try {
            sessionStorage.setItem('dashboard_tx_period_' + State.accountId, period);
            sessionStorage.setItem('dashboard_tx_type_' + State.accountId, typeFilter);
            sessionStorage.setItem('dashboard_tx_page_' + State.accountId, String(page));
        } catch (eSave) {}
    } catch (e) {
        if (mySeq !== _txHistoryLoadSeq) return;
        txHistoryRequestDone = true;
        if (loadingTimer) clearTimeout(loadingTimer);
        if (e && e.status === 429) {
            var raTx = (e.retry_after != null) ? Number(e.retry_after) : 60;
            _txHistoryRateLimitUntil = Date.now() + Math.min(120000, Math.max(15000, raTx * 1000));
        }
        if (!silent && !_txHistoryListHasContent()) {
            if (window.errorReporter) window.errorReporter.report(e, { account_id: State.accountId, action: 'loadTransactionHistory' });
            listEl.innerHTML = '<div class="tx-history-error" style="text-align:center;padding:2rem;color:var(--ds-loss,#f6465d);">Yüklenemedi.</div>';
        }
    } finally {
        if (_txHistoryInflightKey === reqKey) {
            _txHistoryInflight = null;
            _txHistoryInflightKey = '';
        }
    }
    })();
    return _txHistoryInflight;
}
window.loadTransactionHistory = loadTransactionHistory;
window.pollTransactionHistoryRevision = pollTransactionHistoryRevision;

function _txDisplayAmounts(tx) {
    if (!tx) return { qty: 0, price: 0, notional: 0 };
    var qty = Number(tx.qty) || 0;
    var quote = Number(tx.quote_qty) || 0;
    var price = Number(tx.price) || 0;
    if (tx.type === 'buy' || tx.type === 'sell') {
        if (quote > 0 && qty > 0) {
            return { qty: qty, price: quote / qty, notional: quote };
        }
        if (qty > 0 && price > 0) {
            return { qty: qty, price: price, notional: qty * price };
        }
    }
    return { qty: qty, price: price, notional: quote };
}

function _txCommissionLabel(tx) {
    if (!tx || tx.commission == null || Number(tx.commission) <= 0) return '0';
    var raw = Number(tx.commission);
    if (!Number.isFinite(raw)) return '0';
    var asset = String(tx.commission_asset || 'USDT').toUpperCase();
    var usdt = (tx.commission_usdt != null && Number.isFinite(Number(tx.commission_usdt)))
        ? Number(tx.commission_usdt)
        : ((asset === 'USDT' || asset === 'BUSD' || asset === 'FDUSD' || asset === 'USDC') ? raw : null);
    var rawStr = typeof fmtNum === 'function' ? fmtNum(raw, 8) : String(raw);
    if (usdt != null && asset !== 'USDT') {
        var usdtStr = typeof fmtUsd === 'function' ? fmtUsd(usdt) : ('$' + usdt.toFixed(2));
        return rawStr + ' ' + asset + ' (≈ ' + usdtStr + ')';
    }
    return rawStr + ' ' + asset;
}

function openTxDetailModal(tx) {
    var modal = document.getElementById('txDetailModal');
    if (!modal) return;
    var timeStr = tx.time ? new Date(tx.time).toLocaleString('tr-TR', { dateStyle: 'medium', timeStyle: 'medium' }) : '—';
    var typeLabel = tx.type_label || (tx.type === 'buy' ? 'Alım' : tx.type === 'sell' ? 'Satım' : tx.type === 'deposit' ? 'Yatırım' : tx.type === 'withdraw' ? 'Çekim' : '—');
    var amt = _txDisplayAmounts(tx);
    var qty = amt.qty > 0 ? (typeof fmtNum === 'function' ? fmtNum(amt.qty, 8) : Number(amt.qty).toFixed(4)) : '—';
    var price = amt.price > 0 ? (typeof fmtCoinPrice === 'function' ? fmtCoinPrice(amt.price) : '$' + amt.price) : '—';
    var totalVal = (tx.type === 'deposit' || tx.type === 'withdraw')
        ? (qty + ' ' + (tx.symbol || ''))
        : (amt.notional > 0 ? (typeof fmtUsd === 'function' ? fmtUsd(amt.notional) : '$' + amt.notional) : '—');
    var comm = _txCommissionLabel(tx);
    patchText('txDetailTime', timeStr);
    patchText('txDetailType', typeLabel);
    patchText('txDetailSymbol', tx.symbol || '—');
    patchText('txDetailQty', qty);
    patchText('txDetailPrice', price !== '—' ? price : '—');
    patchText('txDetailTotal', totalVal);
    patchText('txDetailCommission', comm);
    patchText('txDetailSource', tx.source_label || (tx.source === 'bot' ? 'Bot' : tx.source === 'spot' ? 'Spot' : '—'));
    patchText('txDetailPlatform', _txPlatformLabel(tx));
    modal.style.display = 'flex';
    modal.setAttribute('aria-hidden', 'false');
}
window.openTxDetailModal = openTxDetailModal;

function closeTxDetailModal() {
    var modal = document.getElementById('txDetailModal');
    if (modal) { modal.style.display = 'none'; modal.setAttribute('aria-hidden', 'true'); }
}
window.closeTxDetailModal = closeTxDetailModal;
