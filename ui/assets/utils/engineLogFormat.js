/**
 * Bot engine log — Türkçe, tek satır metin ( · ); zengin içerik; gürültü filtresi.
 */
(function (global) {
    'use strict';

    var SILENT_SKIP = {
        PRICE_STALE_OR_MISSING: 1,
        IDEMPOTENT_LOCK: 1
    };

    var REASON_TR = {
        trail_sell_grid: 'Satış gridi',
        trail_buy_grid: 'Alım gridi',
        trail_profit_sell: 'Kar satışı',
        trail_reentry_buy: 'Kar alımı',
        initial_allocation: 'İlk base alımı'
    };

    var _logContext = {};

    var CYCLE_TYPE_TR = {
        LONG_SCALP: 'Cash tur',
        INVENTORY_REBALANCE: 'Inventory tur',
        CASH_USDT_V1: 'Cash tur',
        INVENTORY_QTY_V1: 'Inventory tur'
    };

    var TYPE_TR = {
        ERROR: 'Hata',
        SKIP_REASON: 'Atlandı',
        ORDER_FILLED: 'İşlem',
        ORDER_ATTEMPT: 'Emir',
        SLIPPAGE_WARN: 'Kayma',
        LOCK_BUSY: 'Meşgul',
        LOCK_LEASE_EXPIRED: 'Kilit',
        INFO: 'Bilgi',
        BOT_ACTION: 'Aksiyon',
        CYCLE_END: 'Tur',
        CYCLE_START: 'Tur',
        HEALTH_WARN: 'Uyarı',
        HEALTH_CRITICAL: 'Kritik'
    };

    var META_SKIP_KEYS = {
        skip_reason: 1, error_code: 1, reason: 1, grid_index: 1, side: 1, symbol: 1,
        fill_qty: 1, fill_price: 1, fee: 1, order_id: 1, client_order_id: 1,
        notional: 1, min_notional: 1, quote_qty: 1, qty: 1, required: 1, available: 1,
        error: 1, error_id: 1, free_usdt: 1, free_base: 1, base_asset: 1,
        cycle_id: 1, cycle_type: 1, close_reason: 1, close_side: 1,
        pnl_usdt_net: 1, pnl_usdt: 1, profit_usdt: 1, cash_pnl_usdt: 1,
        fees_usdt: 1, cash_fees_usdt: 1, matched_qty: 1, inventory_coin_adv_qty: 1,
        buy_quote_total: 1, sell_quote_total: 1, base_delta: 1, base_qty: 1,
        reference_price: 1, equity_usdt: 1, carry_over: 1, prev_close_reason: 1,
        base_balance: 1, quote_balance: 1, event_logged: 1, equity_usd: 1, last_price: 1,
        capped_quote_qty: 1, old_qty: 1, virtual_quote: 1, free_quote: 1,
        command_id: 1, command: 1, paper: 1, synthetic: 1, synthetic_live: 1, repaired: 1,
        source: 1, health_code: 1, healthCode: 1,
        slip_pct: 1, trigger_price: 1, action_key: 1, account_id: 1, bot_id: 1,
        pnl_primary_mode: 1, pnl_mode: 1, status: 1, trades_match_count: 1,
        realized_pnl_cycle_net: 1, fee_totals_quote: 1, inventory_fees_usdt: 1
    };

    function num(v) {
        var n = Number(v);
        return isNaN(n) ? null : n;
    }

    function fmtUsd(v, signed) {
        var n = num(v);
        if (n == null) return '';
        if (signed === false) return '$' + Math.abs(n).toFixed(2);
        return (n >= 0 ? '+' : '-') + '$' + Math.abs(n).toFixed(2);
    }

    function fmtQty(q) {
        var n = num(q);
        if (n == null) return '';
        if (n >= 1) return n.toFixed(4);
        var s = n.toFixed(8);
        return s.replace(/(\.\d*?[1-9])0+$/, '$1').replace(/\.0+$/, '');
    }

    function fmtPrice(v) {
        var n = num(v);
        if (n == null) return '';
        return n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    function formatCycleOpenPrice(meta) {
        meta = meta || {};
        var price = num(meta.reference_price);
        if (price == null) price = num(meta.fill_price);
        if (price == null) price = num(meta.last_price);
        if (price == null || price <= 0) return null;
        var coin = coinFromSymbol(meta.symbol);
        if (!coin) return fmtPrice(price);
        return coin + ' ' + fmtPrice(price);
    }

    function sideTr(s) {
        return String(s || '').toUpperCase() === 'SELL' ? 'Satış' : 'Alış';
    }

    function reasonTr(r) {
        if (!r) return '';
        return REASON_TR[r] || String(r).replace(/_/g, ' ');
    }

    function coinFromSymbol(sym) {
        if (!sym) return '';
        return String(sym).replace(/USDT$/i, '');
    }

    function reasonDetail(meta) {
        var label = reasonTr(meta.reason);
        var gi = meta.grid_index;
        if (gi != null && gi !== '' && !isNaN(Number(gi))) {
            return label ? label + ' #' + (Number(gi) + 1) : 'Grid #' + (Number(gi) + 1);
        }
        return label;
    }

    function resolveBotStartBalance(meta) {
        meta = meta || {};
        var initialCap = num(meta.initial_capital_usdt);
        if ((initialCap == null || initialCap <= 0) && _logContext.initialCapital > 0) {
            initialCap = num(_logContext.initialCapital);
        }
        var cycleStartEq = num(meta.cycle_start_equity);
        if ((cycleStartEq == null || cycleStartEq <= 0) && _logContext.cycleStartEquity > 0) {
            cycleStartEq = num(_logContext.cycleStartEquity);
        }
        var iaDone = meta.initial_allocation_done === true;
        var preAlloc = num(meta.base_balance) === 0 && num(meta.quote_balance) === 0 && (num(meta.equity_usd) == null || num(meta.equity_usd) === 0);

        if (!iaDone || preAlloc) {
            if (initialCap != null && initialCap > 0) return initialCap;
        } else if (cycleStartEq != null && cycleStartEq > 0) {
            return cycleStartEq;
        }

        var eq = num(meta.equity_usd);
        if (eq != null && eq > 0) return eq;
        var sq = num(meta.quote_balance);
        var sb = num(meta.base_balance);
        var lp = num(meta.last_price);
        if (sb != null && sb > 0 && lp != null) return sb * lp + (sq || 0);
        if (sq != null && sq > 0) return sq;
        return initialCap;
    }

    function cleanRaw(msg) {
        return String(msg || '').replace(/\s+/g, ' ').trim();
    }

    function joinParts(parts) {
        return (parts || []).filter(function (p) { return p != null && String(p).trim() !== ''; }).join(' · ');
    }

    function formatTurReconnectMessage(meta) {
        meta = meta || {};
        var tur = meta.cycle_id != null ? meta.cycle_id : 1;
        return 'Tur ' + tur + ' tekrar aktif edildi. Bot sorunsuz çalışmaya devam ediyor.';
    }

    function appendColdStartConfigBrief(meta, parts) {
        if (!meta || !meta.cold_start_config) return;
        var bp = num(meta.base_alloc_pct);
        var qp = num(meta.quote_alloc_pct);
        if (bp != null) parts.push('Base %' + bp);
        if (qp != null) parts.push('Quote %' + qp);
        var ns = num(meta.sell_grid_count);
        var nb = num(meta.buy_grid_count);
        if (ns != null && ns > 0) parts.push('Yukarı grid ' + ns + ' adet');
        if (nb != null && nb > 0) parts.push('Aşağı grid ' + nb + ' adet');
        var st = num(meta.sell_trail_pct);
        var bt = num(meta.buy_trail_pct);
        if (st != null || bt != null) {
            var tr = [];
            if (st != null) tr.push('sat trail %' + st);
            if (bt != null) tr.push('al trail %' + bt);
            if (tr.length) parts.push(tr.join(' · '));
        }
        var pre = num(meta.profit_reentry_pct);
        var pex = num(meta.profit_exit_pct);
        if (pre != null || pex != null) {
            var pr = [];
            if (pre != null) pr.push('KA %' + pre);
            if (pex != null) pr.push('KS %' + pex);
            if (pr.length) parts.push(pr.join(' · '));
        }
        (meta.sell_grids_brief || []).forEach(function (line) {
            if (line) parts.push(String(line));
        });
        (meta.buy_grids_brief || []).forEach(function (line) {
            if (line) parts.push(String(line));
        });
    }

    function formatTurPauseMessage(meta) {
        meta = meta || {};
        var tur = meta.cycle_id != null ? meta.cycle_id : 1;
        return 'Tur ' + tur + ' beklemeye alındı. Bağlantı yok';
    }

    function formatBalanceLine(meta, equityOverride) {
        meta = meta || {};
        var eq = num(equityOverride);
        if (eq == null) eq = num(meta.equity_usdt);
        if (eq == null) eq = num(meta.equity_usd);
        var coin = coinFromSymbol(meta.symbol);
        var baseBal = num(meta.base_balance);
        if (baseBal == null) baseBal = num(meta.base_qty);
        var quoteBal = num(meta.quote_balance);
        var iaDone = meta.initial_allocation_done === true;
        var preAlloc = (baseBal == null || baseBal === 0) && (quoteBal == null || quoteBal === 0) && !iaDone;
        if (preAlloc) {
            var ic = num(meta.initial_capital_usdt);
            if ((ic == null || ic <= 0) && _logContext.initialCapital > 0) ic = num(_logContext.initialCapital);
            if (ic != null && ic > 0) quoteBal = ic;
        }
        var balanceDetail = [];
        if (baseBal != null) balanceDetail.push('base: ' + fmtQty(baseBal) + (coin ? ' ' + coin : ''));
        if (quoteBal != null) balanceDetail.push('quote: ' + fmtUsd(quoteBal, false));
        if (eq != null && eq > 0) {
            return 'Bakiye: ' + fmtUsd(eq, false) + (balanceDetail.length ? ' (' + balanceDetail.join(' · ') + ')' : '');
        }
        if (balanceDetail.length) return 'Bakiye (' + balanceDetail.join(' · ') + ')';
        return null;
    }

    function parseFillFromRaw(raw) {
        var m = String(raw || '').match(/(BUY|SELL)\s+([\d.eE+-]+)\s+@\s+([\d.eE+-]+)/i);
        if (!m) return null;
        return { side: m[1], qty: num(m[2]), price: num(m[3]) };
    }

    function parseNotionalFromRaw(raw) {
        var m = String(raw || '').match(/notional=([\d.]+)/i);
        var mn = String(raw || '').match(/min(?:_notional)?=([\d.]+)/i);
        return { notional: m ? num(m[1]) : null, min_notional: mn ? num(mn[1]) : null };
    }

    var META_LABEL_TR = {
        synthetic_live: 'Canlı durum özeti'
    };

    function metaLabelTr(key) {
        if (META_LABEL_TR[key]) return META_LABEL_TR[key];
        return String(key || '').replace(/_/g, ' ');
    }

    function appendMetaExtras(meta, used, parts) {
        if (!meta || typeof meta !== 'object') return;
        Object.keys(meta).forEach(function (k) {
            if (used[k] || META_SKIP_KEYS[k]) return;
            var v = meta[k];
            if (v == null || v === '' || v === false || typeof v === 'object') return;
            parts.push(metaLabelTr(k) + ': ' + (v === true ? 'evet' : String(v)));
        });
    }

    function findInitialAllocFill(events, cycleId) {
        var cid = cycleId != null ? Number(cycleId) : 1;
        var found = null;
        (events || []).forEach(function (e) {
            if (!e || e.type !== 'ORDER_FILLED') return;
            var m = e.meta || {};
            if (String(m.reason || '').trim() !== 'initial_allocation') return;
            if (Number(m.cycle_id) !== cid) return;
            var id = Number(e.id || 0);
            if (!found || id > Number(found.id || 0)) found = e;
        });
        return found;
    }

    function isFirstTurCycleStart(ev) {
        if (!ev || ev.type !== 'CYCLE_START') return false;
        var m = ev.meta || {};
        return !!(m.first_tur || String(m.reason || '').trim() === 'initial_allocation');
    }

    /** Tur 1 (+1sn) ile ilk base aynı kümede; listede önce base, hemen altında tur başlatıldı. */
    function eventSortTimestamp(ev, events) {
        var ts = parseEventTsMs(ev.ts);
        if (!isFirstTurCycleStart(ev)) return ts;
        var fill = findInitialAllocFill(events, (ev.meta || {}).cycle_id);
        if (!fill) return ts;
        var fts = parseEventTsMs(fill.ts);
        if (fts <= 0) return ts;
        if (ts >= fts && ts - fts <= 8000) return fts;
        return ts;
    }

    function parseEventTsMs(ts) {
        if (!ts) return 0;
        var s = String(ts).trim();
        if (s.indexOf('T') < 0 && s.indexOf(' ') > 0) {
            s = s.replace(' ', 'T');
        }
        // Naive ISO → UTC (backend normalize_event_ts_iso_z ile uyumlu)
        if (s.indexOf('Z') < 0 && s.indexOf('+') < 0 && s.indexOf('-', 10) < 0) {
            s = s + 'Z';
        }
        var d = new Date(s);
        if (isNaN(d.getTime())) return 0;
        return d.getTime();
    }

    function formatEventTs(ts) {
        var ms = parseEventTsMs(ts);
        if (ms <= 0) return '—';
        return new Date(ms).toLocaleString('tr-TR', { timeZone: 'Europe/Istanbul' });
    }

    function eventDisplayRank(ev) {
        var meta = ev.meta || {};
        var ty = String(ev.type || '').toUpperCase();
        var reason = String(meta.reason || '').trim();
        var raw = String(ev.message || '');

        if (ty === 'INFO' && /COMMAND_EXECUTED.*START/i.test(raw) && meta.connectivity_resume !== true) {
            return 10;
        }
        if (ty === 'ORDER_FILLED' && reason === 'initial_allocation') {
            return 20;
        }
        if (ty === 'CYCLE_START') {
            var cid = Number(meta.cycle_id != null ? meta.cycle_id : 1);
            if (meta.first_tur || reason === 'initial_allocation') return 30;
            return 700 + cid * 10;
        }
        if (ty === 'ORDER_FILLED' && (reason === 'trail_sell_grid' || reason === 'trail_buy_grid')) {
            var gi = Number(meta.grid_index);
            return 400 + (isNaN(gi) ? 0 : gi);
        }
        if (ty === 'ORDER_FILLED' && (reason === 'trail_reentry_buy' || reason === 'trail_profit_sell')) {
            return 550;
        }
        if (ty === 'CYCLE_END') {
            return 600 + Number(meta.cycle_id != null ? meta.cycle_id : 0);
        }
        return 500;
    }

    function compareEngineEventsAsc(a, b, list) {
        var ta = eventSortTimestamp(a, list);
        var tb = eventSortTimestamp(b, list);
        if (ta !== tb) return ta - tb;
        var ra = eventDisplayRank(a);
        var rb = eventDisplayRank(b);
        if (ra !== rb) return ra - rb;
        return Number(a.id || 0) - Number(b.id || 0);
    }

    /** Yeni → eski (canlı log: en yeni üstte, start altta). */
    function sortEngineEventsDesc(events) {
        var list = events || [];
        return list.slice().sort(function (a, b) {
            return -compareEngineEventsAsc(a, b, list);
        });
    }

    /** Eski → yeni (hikâye/export). */
    function sortEngineEventsAsc(events) {
        var list = events || [];
        return list.slice().sort(function (a, b) {
            return compareEngineEventsAsc(a, b, list);
        });
    }

    function formatOrderFilled(meta, raw) {
        meta = meta || {};
        var reason = String(meta.reason || '').trim();
        var parsed = parseFillFromRaw(raw);
        var side = meta.side || (parsed && parsed.side);
        var qty = num(meta.fill_qty);
        var price = num(meta.fill_price);
        if (qty == null && parsed) qty = parsed.qty;
        if (price == null && parsed) price = parsed.price;

        if (reason === 'initial_allocation') {
            var coin = coinFromSymbol(meta.symbol);
            var iaParts = ['İlk base alımı'];
            if (qty != null && price != null) {
                iaParts.push((coin ? coin + ' ' : '') + fmtQty(qty) + ' @ $' + price.toFixed(2));
                iaParts.push('tutar ' + fmtUsd(qty * price, false));
            }
            return joinParts(iaParts);
        }

        if (reason === 'trail_sell_grid' || reason === 'trail_buy_grid') {
            var gi = meta.grid_index;
            var gridNum = (gi != null && gi !== '' && !isNaN(Number(gi))) ? (Number(gi) + 1) : null;
            var coinGrid = coinFromSymbol(meta.symbol);
            var gridParts = [meta.repaired ? 'Kayıt onarıldı' : null];
            gridParts.push((gridNum != null ? 'Grid ' + gridNum + ' - ' : '') + sideTr(side) + ' gerçekleşti');
            if (qty != null && price != null) {
                gridParts.push((coinGrid ? coinGrid + ' ' : '') + fmtQty(qty) + ' @ $' + price.toFixed(2));
                gridParts.push('tutar ' + fmtUsd(qty * price, false));
            }
            var gridFee = num(meta.fee);
            if (gridFee != null && gridFee > 0) gridParts.push('komisyon ' + fmtUsd(gridFee, false));
            return joinParts(gridParts);
        }

        if (reason === 'trail_profit_sell') {
            var profitParts = [meta.repaired ? 'Kayıt onarıldı' : null, 'Kar satışı gerçekleşti'];
            if (qty != null && price != null) {
                profitParts.push(fmtQty(qty) + ' @ $' + price.toFixed(2));
                profitParts.push('tutar ' + fmtUsd(qty * price, false));
            }
            var profitFee = num(meta.fee);
            if (profitFee != null && profitFee > 0) profitParts.push('komisyon ' + fmtUsd(profitFee, false));
            return joinParts(profitParts);
        }

        if (reason === 'trail_reentry_buy') {
            var reentryParts = [meta.repaired ? 'Kayıt onarıldı' : null, 'Kar alımı gerçekleşti'];
            if (qty != null && price != null) {
                reentryParts.push(fmtQty(qty) + ' @ $' + price.toFixed(2));
                reentryParts.push('tutar ' + fmtUsd(qty * price, false));
            }
            var reentryFee = num(meta.fee);
            if (reentryFee != null && reentryFee > 0) reentryParts.push('komisyon ' + fmtUsd(reentryFee, false));
            if (meta.cycle_id != null) reentryParts.push('tur ' + meta.cycle_id);
            return joinParts(reentryParts);
        }

        var used = { side: 1, fill_qty: 1, fill_price: 1, fee: 1, reason: 1, grid_index: 1, symbol: 1, cycle_id: 1, order_id: 1, client_order_id: 1, status: 1 };
        var fee = num(meta.fee);
        var parts = [meta.repaired ? 'Kayıt onarıldı' : null, sideTr(side) + ' gerçekleşti'];
        if (qty != null && price != null) {
            parts.push(fmtQty(qty) + ' @ $' + price.toFixed(2));
            parts.push('tutar ' + fmtUsd(qty * price, false));
        }
        if (fee != null && fee > 0) parts.push('komisyon ' + fmtUsd(fee, false));
        if (reason && reason !== 'trail_sell_grid' && reason !== 'trail_buy_grid') {
            var rd = reasonDetail(meta);
            if (rd) parts.push(rd);
        }
        if (meta.cycle_id != null) parts.push('tur ' + meta.cycle_id);
        if (meta.order_id) {
            parts.push('order #' + String(meta.order_id));
        } else if (meta.client_order_id) {
            parts.push('coid …' + String(meta.client_order_id).slice(-8));
        }
        if (meta.status) parts.push('durum ' + meta.status);
        appendMetaExtras(meta, used, parts);
        return joinParts(parts);
    }

    function formatCycleEndPnl(meta) {
        meta = meta || {};
        var mode = String(meta.pnl_primary_mode || meta.cycle_type || '').toUpperCase();
        var isInventory = mode.indexOf('INVENTORY') >= 0 || meta.close_reason === 'trail_reentry_buy';
        if (isInventory) {
            var inv = num(meta.inventory_coin_adv_qty);
            if (inv != null && inv !== 0) {
                var coin = coinFromSymbol(meta.symbol);
                return 'net K/Z ' + (inv >= 0 ? '+' : '') + fmtQty(inv) + (coin ? ' ' + coin : '');
            }
        }
        var pnl = num(meta.pnl_usdt_net != null ? meta.pnl_usdt_net : (meta.realized_pnl_cycle_net != null ? meta.realized_pnl_cycle_net : meta.pnl_usdt));
        if (pnl != null) return 'net K/Z ' + fmtUsd(pnl);
        return null;
    }

    function formatCycleEnd(meta) {
        meta = meta || {};
        var cycleNum = meta.cycle_id != null ? meta.cycle_id : '?';
        var parts = ['Tur ' + cycleNum + ' tamamlandı'];
        var pnlPart = formatCycleEndPnl(meta);
        if (pnlPart) parts.push(pnlPart);
        var mode = String(meta.pnl_primary_mode || meta.cycle_type || '').toUpperCase();
        var isInventory = mode.indexOf('INVENTORY') >= 0 || meta.close_reason === 'trail_reentry_buy';
        var fees = num(meta.fees_usdt);
        if (fees == null) fees = num(isInventory ? meta.inventory_fees_usdt : meta.cash_fees_usdt);
        if (fees != null && fees > 0) parts.push('komisyon ' + fmtUsd(fees, false));
        return joinParts(parts);
    }

    function enrichFirstTurStartMeta(meta) {
        meta = meta || {};
        var isFirst = meta.first_tur || String(meta.reason || '').trim() === 'initial_allocation';
        if (!isFirst) return meta;
        var fill = findInitialAllocFill(_logContext.events || [], meta.cycle_id);
        if (!fill || !fill.meta) return meta;
        var fm = fill.meta;
        var out = Object.assign({}, meta);
        if (out.symbol == null && fm.symbol) out.symbol = fm.symbol;
        var fq = num(fm.fill_qty);
        var fp = num(fm.fill_price);
        if (out.base_balance == null && fq != null) {
            out.base_balance = fq;
            out.base_qty = fq;
        }
        if (out.quote_balance == null && fp != null && fq != null) {
            var eq = num(out.equity_usdt);
            if (eq == null) eq = num(out.equity_usd);
            if (eq != null && eq > 0) {
                out.quote_balance = Math.max(0, eq - fq * fp);
            }
        }
        if ((out.equity_usdt == null && out.equity_usd == null) && fq != null && fp != null) {
            var q2 = num(out.quote_balance) || 0;
            out.equity_usdt = q2 + fq * fp;
        }
        return out;
    }

    function formatCycleStart(meta) {
        meta = enrichFirstTurStartMeta(meta || {});
        var cycleNum = meta.cycle_id != null ? meta.cycle_id : '?';
        var isFirst = meta.first_tur || String(meta.reason || '').trim() === 'initial_allocation';
        var parts = ['Tur ' + cycleNum + (isFirst ? ' başlatıldı' : ' açıldı')];
        var coin = coinFromSymbol(meta.symbol);
        var baseBal = num(meta.base_balance);
        if (baseBal == null) baseBal = num(meta.base_qty);
        var quoteBal = num(meta.quote_balance);
        if (baseBal != null && baseBal > 0) {
            parts.push('Base ' + fmtQty(baseBal) + (coin ? ' ' + coin : ''));
        }
        if (quoteBal != null) parts.push('Quote ' + fmtUsd(quoteBal, false));
        var eq = num(meta.equity_usdt);
        if (eq == null) eq = num(meta.equity_usd);
        if (eq != null && eq > 0) parts.push('Bakiye ' + fmtUsd(eq, false));
        return joinParts(parts);
    }

    /** Bağlantı sonrası ikinci START veya connectivity START — üstteki yinelenen Bot başlatıldı. */
    function shouldHideDuplicateBotStart(ev, meta, raw) {
        if (!/COMMAND_EXECUTED.*START/i.test(String(raw || ''))) return false;
        if (meta.connectivity_resume === true) return true;
        var events = _logContext.events || [];
        var id = Number(ev.id || 0);
        if (!id || !events.length) return false;
        var olderStart = false;
        var recoveryBefore = false;
        for (var i = 0; i < events.length; i++) {
            var e = events[i];
            var eid = Number(e.id || 0);
            if (!eid || eid >= id) continue;
            var em = e.meta || {};
            var msg = e.message || '';
            if (msg.indexOf('COMMAND_EXECUTED') >= 0 && msg.indexOf('START') >= 0) olderStart = true;
            if (em.error_code === 'CONNECTIVITY_RECOVERED' || /tekrar aktif edildi/i.test(msg)) recoveryBefore = true;
        }
        return olderStart && (recoveryBefore || meta.initial_allocation_done === true);
    }

    function formatOrderAttempt(meta) {
        meta = meta || {};
        var side = meta.side;
        var parts = [sideTr(side) + ' emri gönderildi'];
        var qq = num(meta.quote_qty);
        var qty = num(meta.qty);
        if (side === 'BUY' && qq != null) parts.push('tutar ' + fmtUsd(qq, false));
        else if (qty != null) parts.push('miktar ' + fmtQty(qty));
        var reason = String(meta.reason || '').trim();
        if (reason && reason !== 'trail_sell_grid' && reason !== 'trail_buy_grid') {
            var rd = reasonDetail(meta);
            if (rd) parts.push(rd);
        } else if (meta.grid_index != null && meta.grid_index !== '' && !isNaN(Number(meta.grid_index))) {
            parts.push('grid #' + (Number(meta.grid_index) + 1));
        }
        if (meta.cycle_id != null) parts.push('tur ' + meta.cycle_id);
        if (meta.paper) parts.push('paper mod');
        return joinParts(parts);
    }

    function formatSlippage(meta, raw) {
        var parts = ['Fiyat kayması'];
        var slip = num(meta.slip_pct);
        var trig = num(meta.trigger_price);
        var fill = num(meta.fill_price);
        if (trig == null || fill == null) {
            var tm = raw.match(/trigger=([\d.]+).*fill=([\d.]+)/i);
            if (tm) { trig = num(tm[1]); fill = num(tm[2]); }
        }
        if (slip != null) parts.push(slip.toFixed(2) + '%');
        if (trig != null && fill != null) parts.push('tetik $' + trig.toFixed(2) + ' → fill $' + fill.toFixed(2));
        var rd = reasonDetail(meta);
        if (rd) parts.push(rd);
        appendMetaExtras(meta, {}, parts);
        return joinParts(parts);
    }

    function formatSkipReason(meta, rawMsg) {
        var skip = String(meta.skip_reason || meta.error_code || '').trim();
        if (!skip && /MIN_NOTIONAL/i.test(rawMsg)) skip = 'MIN_NOTIONAL';
        var severity = 'warn';
        var parts = [];

        if (skip === 'MIN_NOTIONAL' || skip === 'MIN_NOTIONAL_AFTER_CAP') {
            severity = 'critical';
            parts.push(skip === 'MIN_NOTIONAL_AFTER_CAP'
                ? 'Cap sonrası minimum tutar altında — emir yapılamadı'
                : 'Minimum tutar altında — grid emri yapılamadı');
            if (meta.side) parts.push(sideTr(meta.side));
            var rd = reasonDetail(meta);
            if (rd) parts.push(rd);
            var notional = num(meta.notional);
            var minN = num(meta.min_notional);
            if (notional == null || minN == null) {
                var parsed = parseNotionalFromRaw(rawMsg);
                if (notional == null) notional = parsed.notional;
                if (minN == null) minN = parsed.min_notional;
            }
            if (notional != null && minN != null) {
                parts.push('emir ' + fmtUsd(notional, false) + ' / min ' + fmtUsd(minN, false));
                if (minN > notional) parts.push('eksik ' + fmtUsd(minN - notional, false));
            }
            if (num(meta.quote_qty) != null) parts.push('quote ' + fmtUsd(meta.quote_qty, false));
        } else if (skip === 'INSUFFICIENT_QUOTE' || skip === 'VIRTUAL_BUDGET_INSUFFICIENT') {
            severity = 'critical';
            parts.push(skip === 'VIRTUAL_BUDGET_INSUFFICIENT'
                ? 'Sanal bütçe yetersiz — emir gönderilemedi'
                : 'Yetersiz USDT — ilk alım yapılamadı');
            var req = num(meta.required);
            var av = num(meta.available);
            if (req != null && av != null) {
                parts.push('gerekli ' + fmtUsd(req, false) + ', mevcut ' + fmtUsd(av, false));
            }
            var rd2 = reasonDetail(meta);
            if (rd2) parts.push(rd2);
        } else if (skip === 'LOT_SIZE') {
            severity = 'critical';
            parts.push('Lot boyutu hatası — miktar borsa filtresine uymuyor');
            if (meta.binance_msg) parts.push(String(meta.binance_msg).slice(0, 120));
            else if (meta.error) parts.push(String(meta.error).slice(0, 100));
            if (meta.binance_code != null) parts.push('kod ' + meta.binance_code);
            if (meta.error_id) parts.push('id ' + String(meta.error_id).slice(0, 8));
            var rdLot = reasonDetail(meta);
            if (rdLot) parts.push(rdLot);
        } else if (skip === 'ORDER_FAILED') {
            severity = 'critical';
            parts.push('Emir gönderilemedi — borsa veya ağ hatası');
            if (meta.binance_msg) parts.push(String(meta.binance_msg).slice(0, 120));
            else if (meta.error) parts.push(String(meta.error).slice(0, 100));
            if (meta.binance_code != null) parts.push('kod ' + meta.binance_code);
            if (meta.error_id) parts.push('id ' + String(meta.error_id).slice(0, 8));
            var rd3 = reasonDetail(meta);
            if (rd3) parts.push(rd3);
        } else if (skip === 'BINANCE_FREE_QUOTE_INSUFFICIENT') {
            severity = 'critical';
            parts.push('Binance USDT yetersiz');
            if (num(meta.quote_qty) != null) parts.push('emir ' + fmtUsd(meta.quote_qty, false));
            if (num(meta.free_usdt) != null) parts.push('serbest ' + fmtUsd(meta.free_usdt, false));
            var rd4 = reasonDetail(meta);
            if (rd4) parts.push(rd4);
        } else if (skip === 'BINANCE_FREE_BASE_INSUFFICIENT') {
            severity = 'critical';
            parts.push('Binance coin bakiyesi yetersiz');
            if (num(meta.qty) != null) parts.push('emir ' + fmtQty(meta.qty));
            if (num(meta.free_base) != null) parts.push('serbest ' + fmtQty(meta.free_base));
            if (meta.base_asset) parts.push(meta.base_asset);
            var rd5 = reasonDetail(meta);
            if (rd5) parts.push(rd5);
        } else if (skip === 'WEIGHT_DENIED') {
            severity = 'warn';
            parts.push('API limiti dolu — emir bekletildi');
            var rd6 = reasonDetail(meta);
            if (rd6) parts.push(rd6);
        } else if (skip === 'ORDER_TIMEOUT') {
            severity = 'warn';
            parts.push('Emir zaman aşımı — borsa yanıt vermedi');
            if (meta.client_order_id) parts.push('coid …' + String(meta.client_order_id).slice(-8));
            var rd7 = reasonDetail(meta);
            if (rd7) parts.push(rd7);
        } else if (skip === 'INVALID_ACTION') {
            severity = 'warn';
            parts.push('Geçersiz emir — parametre eksik veya hatalı');
            var rd8 = reasonDetail(meta);
            if (rd8) parts.push(rd8);
        } else if (skip === 'LOCK_LEASE_EXPIRED') {
            severity = 'warn';
            parts.push('İşlem kilidi süresi doldu — emir atlandı');
            var rd9 = reasonDetail(meta);
            if (rd9) parts.push(rd9);
        } else if (skip) {
            severity = 'warn';
            parts.push('Emir atlandı: ' + skip.replace(/_/g, ' ').toLowerCase());
            var rd10 = reasonDetail(meta);
            if (rd10) parts.push(rd10);
        } else {
            parts.push(cleanRaw(rawMsg) || 'Emir atlandı');
        }

        if (meta.symbol) parts.push(meta.symbol);
        if (meta.cycle_id != null) parts.push('tur ' + meta.cycle_id);
        appendMetaExtras(meta, {}, parts);
        return { severity: severity, message: joinParts(parts) };
    }

    function formatInfo(meta, raw) {
        meta = meta || {};
        if (meta.event_kind === 'BOT_RESILIENCE' || /Dayanıklılık:/i.test(raw || '')) {
            var rp = [raw.replace(/^Dayanıklılık:\s*/i, '').trim() || 'Bot çalışmaya devam ediyor'];
            if (meta.restart_reason) rp.push('neden: ' + meta.restart_reason);
            if (meta.error_code) rp.push('kod ' + meta.error_code);
            if (meta.continues_running) rp.push('döngü aktif');
            return { message: joinParts(rp), severity: meta.health_code === 'BOT_LOOP_AUTO_RESTART' ? 'warn' : 'info' };
        }
        if (raw.indexOf('İlk alım miktarı') >= 0) {
            var cap = num(meta.capped_quote_qty);
            var av = num(meta.available);
            var parts = ['İlk alım bakiyeye göre ayarlandı'];
            if (cap != null) parts.push('yeni ' + fmtUsd(cap, false));
            if (av != null) parts.push('mevcut bakiye ' + fmtUsd(av, false));
            return joinParts(parts);
        }
        if (/quote_qty_capped/i.test(raw)) {
            var oq = num(meta.old_qty);
            var nq = num(meta.quote_qty);
            var parts2 = ['Alım tutarı sanal bakiyeye göre düşürüldü'];
            if (oq != null && nq != null) parts2.push('$' + oq.toFixed(2) + ' → $' + nq.toFixed(2));
            if (num(meta.free_quote) != null) parts2.push('serbest quote ' + fmtUsd(meta.free_quote, false));
            var rd = reasonDetail(meta);
            if (rd) parts2.push(rd);
            return { message: joinParts(parts2), severity: 'warn' };
        }
        if (/COMMAND_EXECUTED.*START/i.test(raw)) {
            var startParts = ['Bismillahirrahmanirrahim.', 'Bot başlatıldı'];
            var startBal = resolveBotStartBalance(meta);
            if (meta.cold_start_config) {
                var ic = num(meta.initial_capital_usdt);
                if (ic != null && ic > 0) startParts.push('Bakiye: ' + fmtUsd(ic, false));
                else if (startBal != null && startBal > 0) startParts.push('Bakiye: ' + fmtUsd(startBal, false));
                appendColdStartConfigBrief(meta, startParts);
            } else {
                var startBalLine = formatBalanceLine(meta, startBal);
                if (startBalLine) startParts.push(startBalLine);
            }
            return { message: joinParts(startParts), severity: 'info' };
        }
        if (meta.health_code === 'OUTAGE_RECOVERY' || /kopma sonrası grid/i.test(raw)) {
            var outParts = [];
            var turNum = meta.cycle_id != null ? meta.cycle_id : '?';
            if (meta.tur_restarted === true) {
                outParts.push('Tur ' + turNum + ' yeniden başlatıldı');
            } else {
                outParts.push('Tur ' + turNum + ' devam ediyor — kopma sonrası grid değerlendirmesi');
            }
            var gapS = num(meta.gap_sec);
            if (gapS != null) outParts.push('boşluk ' + gapS.toFixed(0) + ' sn');
            if (meta.summary) {
                outParts.push(String(meta.summary));
            } else if (Array.isArray(meta.actions) && meta.actions.length) {
                outParts.push(meta.actions.join(' '));
            }
            return { message: joinParts(outParts), severity: 'warn' };
        }
        if (meta.error_code === 'CONNECTIVITY_PAUSED' || meta.connectivity_pause) {
            return { message: formatTurPauseMessage(meta), severity: 'info' };
        }
        if (meta.error_code === 'CONNECTIVITY_RECOVERED' || (meta.connectivity_resume === true && /tekrar aktif/i.test(raw))) {
            return { message: formatTurReconnectMessage(meta), severity: 'warn' };
        }
        if (/tekrar aktif edildi/i.test(raw)) {
            return { message: formatTurReconnectMessage(meta), severity: 'warn' };
        }
        if (/beklemeye alındı/i.test(raw)) {
            return { message: formatTurPauseMessage(meta), severity: 'info' };
        }
        if (/COMMAND_EXECUTED.*STOP/i.test(raw)) {
            var stopTur = meta.cycle_id != null ? meta.cycle_id : 1;
            var stopParts = ['Bot durduruldu · Tur ' + stopTur];
            var stopCoin = coinFromSymbol(meta.symbol);
            var stopBase = num(meta.base_balance);
            var stopQuote = num(meta.quote_balance);
            var stopEq = num(meta.equity_usd);
            if (stopBase != null && stopBase > 0) {
                stopParts.push('base ' + fmtQty(stopBase) + (stopCoin ? ' ' + stopCoin : ''));
            }
            if (stopQuote != null) stopParts.push('quote ' + fmtUsd(stopQuote, false));
            if (stopEq != null && stopEq > 0) stopParts.push('bot ' + fmtUsd(stopEq, false));
            return joinParts(stopParts);
        }
        if (/COMMAND_FAILED/i.test(raw)) {
            return { message: 'Komut başarısız — bot durumu etkilenebilir' + (meta.error_id ? ' · id ' + String(meta.error_id).slice(0, 8) : ''), severity: 'critical' };
        }
        var parts3 = [];
        appendMetaExtras(meta, {}, parts3);
        if (parts3.length) return joinParts([cleanRaw(raw).slice(0, 80)].concat(parts3));
        return raw.length > 180 ? raw.substring(0, 177) + '…' : raw;
    }

    function formatError(meta, raw) {
        var ec = String(meta.error_code || '').trim();
        var parts = [];
        if (ec === 'ACCOUNT_KEYS_MISSING') parts.push('API anahtarı eksik — bot işlem yapamaz');
        else if (ec === 'LOT_SIZE') parts.push('Lot boyutu hatası — miktar borsa filtresine uymuyor');
        else if (ec === 'BINANCE_UNREACHABLE') parts.push('Binance bağlantı hatası — bakiye/veri alınamadı');
        else if (/401|Unauthorized|API anahtarı/i.test(raw)) parts.push('Binance API geçersiz — anahtar, IP veya Spot izni kontrol edin');
        else if (/INSUFFICIENT_BALANCE/i.test(raw)) parts.push('Yetersiz bakiye — emir reddedildi');
        else if (/SAFE_STOP|paused/i.test(raw) || ec === 'SAFE_STOP') parts.push('Güvenlik durdurması — bot durduruldu');
        else if (/RUN_ACTION_EXCEPTION/i.test(raw) || ec === 'RUN_ACTION_EXCEPTION') parts.push('İşlem hatası — bot etkilenebilir');
        else if (/BOT_LOOP/i.test(raw) || /BOT_LOOP/i.test(ec)) parts.push('Bot döngüsü hatası — tick atlandı');
        else if (raw.indexOf('API anahtarı') >= 0) return raw;
        else parts.push(raw.length > 160 ? raw.substring(0, 157) + '…' : (raw || 'Kritik hata'));
        if (ec && parts[0].indexOf(ec) < 0) parts.push('kod ' + ec);
        if (meta.error_id) parts.push('id ' + String(meta.error_id).slice(0, 8));
        if (meta.action_key) parts.push(meta.action_key);
        appendMetaExtras(meta, {}, parts);
        return joinParts(parts);
    }

    function hasRecentSkipOrErrorForCode(code) {
        var c = String(code || '').toUpperCase();
        if (!c) return false;
        var events = _logContext.events || [];
        for (var i = 0; i < events.length; i++) {
            var ev = events[i];
            var ty = String(ev.type || '').toUpperCase();
            var em = ev.meta || {};
            if (ty === 'SKIP_REASON' && String(em.skip_reason || '').toUpperCase() === c) return true;
            if (ty === 'ERROR' && String(em.error_code || '').toUpperCase() === c) return true;
        }
        return false;
    }

    function shouldHideRedundantStateHealth(ev, meta) {
        if (!ev || (ev.type !== 'HEALTH_WARN' && ev.type !== 'HEALTH_CRITICAL')) return false;
        meta = meta || {};
        var hc = String(meta.health_code || '');
        var ec = String(meta.error_code || '').toUpperCase();
        if (hc === 'STATE_ERROR_WARN' && ec) {
            return hasRecentSkipOrErrorForCode(ec);
        }
        if (hc === ec && /^(LOT_SIZE|MIN_NOTIONAL|ORDER_FAILED|INSUFFICIENT_QUOTE|ORDER_TIMEOUT)/.test(ec)) {
            return hasRecentSkipOrErrorForCode(ec);
        }
        return false;
    }

    function formatHealth(meta, raw, isCritical) {
        meta = meta || {};
        var parts = [];
        if (meta.health_code === 'CONNECTIVITY_LOST' || meta.error_code === 'CONNECTIVITY_LOST') {
            parts.push('Binance bağlantısı yok');
            if (meta.cause) parts.push(String(meta.cause));
            else if (raw && raw.indexOf('Binance') >= 0) parts.push(cleanRaw(raw).replace(/^Binance bağlantısı yok\s*[—-]\s*/i, ''));
            return joinParts(parts);
        }
        var skCode = String(meta.error_code || meta.health_code || '').toUpperCase();
        if (skCode === 'LOT_SIZE') {
            parts.push('Lot / step filtresi — miktar borsa kuralına uymuyor');
            if (meta.cause) parts.push(String(meta.cause));
            var acts = meta.actions;
            if (Array.isArray(acts) && acts.length) parts.push('Çözüm: ' + acts[0]);
            return joinParts(parts);
        }
        if (skCode === 'MIN_NOTIONAL' || skCode === 'MIN_NOTIONAL_AFTER_CAP') {
            parts.push('Minimum işlem tutarı altında');
            if (meta.cause) parts.push(String(meta.cause));
            if (Array.isArray(meta.actions) && meta.actions.length) parts.push('Çözüm: ' + meta.actions[0]);
            return joinParts(parts);
        }
        var title = meta.title || (isCritical ? 'Kritik durum' : 'Uyarı');
        parts.push(title);
        if (meta.continues_running) {
            parts.push('Bot durdurulmadı — çalışmaya devam ediyor');
        }
        if (meta.cause) parts.push('Sebep: ' + meta.cause);
        else if (raw && raw !== title) parts.push(raw);
        var tickAge = num(meta.tick_age_s);
        if (tickAge != null) parts.push('son tick ' + tickAge.toFixed(0) + 's önce');
        if (meta.error_code) parts.push('kod ' + meta.error_code);
        var actions = meta.actions;
        if (Array.isArray(actions) && actions.length) {
            parts.push('Çözüm: ' + actions[0]);
            if (actions.length > 1) parts.push(actions.slice(1).join(' · '));
        }
        return joinParts(parts);
    }

    function formatEngineEvent(ev, options) {
        options = options || {};
        var ty = String(ev.type || '').trim();
        var meta = ev.meta && typeof ev.meta === 'object' ? Object.assign({}, ev.meta) : {};
        var raw = cleanRaw(ev.message);
        var skip = String(meta.skip_reason || '').trim();
        if (!skip && ty === 'SKIP_REASON' && /MIN_NOTIONAL/i.test(raw)) {
            skip = 'MIN_NOTIONAL';
            meta.skip_reason = 'MIN_NOTIONAL';
        }

        if (ty === 'SKIP_REASON' && SILENT_SKIP[skip]) return { hidden: true };
        if (ty === 'SKIP_REASON' && /IDEMPOTENT_LOCK/i.test(raw)) return { hidden: true };
        // Başarılı emir gönderimi gürültü — dolunca ORDER_FILLED; hata SKIP_REASON/ERROR ile yazılır
        if (ty === 'ORDER_ATTEMPT') return { hidden: true };
        if ((ty === 'HEALTH_WARN' || ty === 'HEALTH_CRITICAL') && (meta.test === true || /^TEST_UI_/i.test(String(meta.health_code || '')))) {
            return { hidden: true };
        }
        if (!options.forExport && _logContext.botId && global.BotHealthAlerts && global.BotHealthAlerts.shouldHideResetLogEvent
            && global.BotHealthAlerts.shouldHideResetLogEvent(
                ev,
                _logContext.botId,
                _logContext.events,
                _logContext.healthData
            )) {
            return { hidden: true };
        }
        if (!options.forExport && ty === 'INFO' && shouldHideDuplicateBotStart(ev, meta, raw)) {
            return { hidden: true };
        }
        if (!options.forExport && shouldHideRedundantStateHealth(ev, meta)) {
            return { hidden: true };
        }

        var typeLabel = TYPE_TR[ty] || ty || '—';
        var severity = 'info';
        var message = raw;

        if (ty === 'SKIP_REASON') {
            var sk = formatSkipReason(meta, raw);
            severity = sk.severity;
            message = sk.message;
        } else if (ty === 'ERROR') {
            severity = 'critical';
            message = formatError(meta, raw);
        } else if (ty === 'SLIPPAGE_WARN') {
            severity = 'warn';
            message = formatSlippage(meta, raw);
        } else if (ty === 'LOCK_BUSY') {
            severity = 'warn';
            message = joinParts(['Sembol kilidi meşgul — tick atlandı', meta.symbol || null]);
        } else if (ty === 'LOCK_LEASE_EXPIRED') {
            severity = 'warn';
            message = joinParts(['Kilit süresi doldu — emir gönderilmedi', meta.symbol || null]);
        } else if (ty === 'ORDER_FILLED') {
            message = formatOrderFilled(meta, raw);
            if (meta.reason === 'initial_allocation') {
                typeLabel = 'Alış';
            } else {
                typeLabel = sideTr(meta.side || (parseFillFromRaw(raw) || {}).side);
            }
        } else if (ty === 'CYCLE_END') {
            message = formatCycleEnd(meta);
            typeLabel = 'Kapanış';
        } else if (ty === 'CYCLE_START') {
            message = formatCycleStart(meta);
            typeLabel = 'Tur ' + (meta.cycle_id != null ? meta.cycle_id : '?');
        } else if (ty === 'HEALTH_CRITICAL') {
            severity = 'critical';
            message = formatHealth(meta, raw, true);
            typeLabel = 'Kritik';
            if (meta.health_resolved) {
                message = (message || '—') + ' · çözüldü';
            }
        } else if (ty === 'HEALTH_WARN') {
            severity = 'warn';
            message = formatHealth(meta, raw, false);
            typeLabel = 'Uyarı';
            if (meta.health_resolved) {
                message = (message || '—') + ' · çözüldü';
            }
        } else if (ty === 'INFO') {
            if (/COMMAND_EXECUTED.*START/i.test(raw) && meta.connectivity_resume === true) {
                return { hidden: true };
            }
            var infoRes = formatInfo(meta, raw);
            if (infoRes && typeof infoRes === 'object') {
                message = infoRes.message;
                severity = infoRes.severity || 'info';
            } else {
                message = infoRes || raw;
            }
            if (/quote_qty_capped/i.test(raw)) severity = 'warn';
            if (/COMMAND_EXECUTED.*START/i.test(raw) && meta.connectivity_resume !== true) {
                typeLabel = 'Start';
            } else if (
                meta.error_code === 'CONNECTIVITY_RECOVERED'
                || /tekrar aktif edildi/i.test(message || '')
            ) {
                severity = 'warn';
                typeLabel = 'Uyarı';
            } else if (/COMMAND_EXECUTED/i.test(raw)) {
                typeLabel = 'Tur ' + (meta.cycle_id != null ? meta.cycle_id : 1);
            } else if (
                meta.error_code === 'CONNECTIVITY_PAUSED'
                || meta.connectivity_pause
                || /beklemeye alındı/i.test(raw)
            ) {
                typeLabel = 'Bilgi';
            } else if (meta.cycle_id != null) {
                typeLabel = 'Tur ' + meta.cycle_id;
            }
        } else if (ty === 'BOT_ACTION') {
            message = reasonDetail(meta) || raw || 'Strateji aksiyonu';
        }

        return {
            hidden: false,
            typeLabel: typeLabel,
            message: message || '—',
            severity: severity
        };
    }

    function isHealthEventType(ty) {
        ty = (ty || '').toUpperCase();
        return ty === 'HEALTH_WARN' || ty === 'HEALTH_CRITICAL';
    }

    function collapseEngineEvents(events) {
        var collapsed = [];
        var prev = null;
        (events || []).forEach(function (ev) {
            var fmt = formatEngineEvent(ev);
            if (fmt.hidden) return;
            var meta = ev.meta || {};
            var ec = String(meta.error_code || meta.health_code || '').toUpperCase();
            var key;
            if (meta.health_ui_track && ec) {
                key = 'HEALTH_TRACK\0' + ec + '\0' + (meta.health_resolved ? 'resolved' : 'active');
            } else if (ec && /API_UNAUTHORIZED|BINANCE_UNREACHABLE|BINANCE_RATE|ACCOUNT_KEYS|CONNECTIVITY_RECOVERED|CONNECTIVITY_PAUSED/.test(ec)) {
                key = ec + '\0' + fmt.severity;
            } else if (isHealthEventType(ev.type) && ec) {
                key = (ev.type || '') + '\0' + ec + '\0' + fmt.severity;
            } else {
                key = (ev.type || '') + '\0' + (meta.error_code || '') + '\0' + fmt.message + '\0' + fmt.severity;
            }
            if (prev && prev.key === key) {
                prev.count++;
                prev.lastTs = ev.ts;
            } else {
                collapsed.push({
                    typeLabel: fmt.typeLabel,
                    message: fmt.message,
                    severity: fmt.severity,
                    ts: ev.ts,
                    key: key,
                    count: 1,
                    lastTs: ev.ts,
                    healthActive: !!(meta.health_ui_track && !meta.health_resolved),
                    healthCode: ec || ''
                });
                prev = collapsed[collapsed.length - 1];
            }
        });
        return collapsed;
    }

    function hasRecentCritical(events, maxAgeMs) {
        maxAgeMs = maxAgeMs == null ? 6 * 3600000 : maxAgeMs;
        var now = Date.now();
        for (var i = 0; i < (events || []).length; i++) {
            var fmt = formatEngineEvent(events[i]);
            if (fmt.hidden || fmt.severity !== 'critical') continue;
            var ts = events[i].ts;
            if (ts) {
                var t = new Date(ts).getTime();
                if (!isNaN(t) && now - t > maxAgeMs) continue;
            }
            return true;
        }
        return false;
    }

    function rowClass(severity) {
        if (severity === 'critical') return 'log-row-error';
        if (severity === 'warn') return 'log-row-warn';
        return 'log-row-info';
    }

    function setLogContext(ctx) {
        if (ctx && typeof ctx === 'object') {
            _logContext = Object.assign({}, _logContext, ctx);
            if (typeof global !== 'undefined' && global._lastHealthData) {
                _logContext.healthData = _logContext.healthData || global._lastHealthData;
            }
        } else {
            _logContext = {};
        }
    }

    global.EngineLogFormat = {
        formatEngineEvent: formatEngineEvent,
        collapseEngineEvents: collapseEngineEvents,
        hasRecentCritical: hasRecentCritical,
        rowClass: rowClass,
        setLogContext: setLogContext,
        sortEngineEventsAsc: sortEngineEventsAsc,
        sortEngineEventsDesc: sortEngineEventsDesc,
        parseEventTsMs: parseEventTsMs,
        formatEventTs: formatEventTs
    };
})(typeof window !== 'undefined' ? window : globalThis);
