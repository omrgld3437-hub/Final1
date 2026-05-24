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
        command_id: 1, command: 1, paper: 1, synthetic: 1, repaired: 1,
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

    function appendMetaExtras(meta, used, parts) {
        if (!meta || typeof meta !== 'object') return;
        Object.keys(meta).forEach(function (k) {
            if (used[k] || META_SKIP_KEYS[k]) return;
            var v = meta[k];
            if (v == null || v === '' || v === false || typeof v === 'object') return;
            parts.push(k.replace(/_/g, ' ') + ': ' + (v === true ? 'evet' : String(v)));
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
        var parts = ['tamamlandı'];
        var pnlPart = formatCycleEndPnl(meta);
        if (pnlPart) parts.push(pnlPart);
        var mode = String(meta.pnl_primary_mode || meta.cycle_type || '').toUpperCase();
        var isInventory = mode.indexOf('INVENTORY') >= 0 || meta.close_reason === 'trail_reentry_buy';
        var fees = num(meta.fees_usdt);
        if (fees == null) fees = num(isInventory ? meta.inventory_fees_usdt : meta.cash_fees_usdt);
        if (fees != null && fees > 0) parts.push('komisyon ' + fmtUsd(fees, false));
        return joinParts(parts);
    }

    function formatCycleStart(meta) {
        meta = meta || {};
        var parts = ['Bismillahirrahmanirrahim.', 'Tur açıldı'];
        if (meta.carry_over) {
            var prev = reasonTr(meta.prev_close_reason);
            if (prev) parts.push(prev + ' sonrası');
        }
        var eq = num(meta.equity_usdt);
        if (eq == null) eq = num(meta.equity_usd);
        if (eq != null && eq > 0) parts.push('Bakiye: ' + fmtUsd(eq, false));
        if (meta.synthetic) parts.push('(kayıt)');
        return joinParts(parts);
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
        } else if (skip === 'ORDER_FAILED') {
            severity = 'critical';
            parts.push('Emir gönderilemedi — borsa veya ağ hatası');
            if (meta.error) parts.push(String(meta.error).slice(0, 100));
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
            if (startBal != null && startBal > 0) {
                startParts.push('Bakiye: ' + fmtUsd(startBal, false));
            }
            return joinParts(startParts);
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

    function formatHealth(meta, raw, isCritical) {
        meta = meta || {};
        var parts = [];
        var title = meta.title || (isCritical ? 'Kritik durum' : 'Uyarı');
        parts.push(title);
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

    function formatEngineEvent(ev) {
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
            typeLabel = 'Tur ' + (meta.cycle_id != null ? meta.cycle_id : '?');
        } else if (ty === 'CYCLE_START') {
            if (meta.reason === 'initial_allocation') {
                return { hidden: true };
            }
            message = formatCycleStart(meta);
            typeLabel = 'Tur ' + (meta.cycle_id != null ? meta.cycle_id : '?');
        } else if (ty === 'HEALTH_CRITICAL') {
            severity = 'critical';
            message = formatHealth(meta, raw, true);
            typeLabel = 'Kritik';
        } else if (ty === 'HEALTH_WARN') {
            severity = 'warn';
            message = formatHealth(meta, raw, false);
            typeLabel = 'Uyarı';
        } else if (ty === 'INFO') {
            var infoRes = formatInfo(meta, raw);
            if (infoRes && typeof infoRes === 'object') {
                message = infoRes.message;
                severity = infoRes.severity || 'info';
            } else {
                message = infoRes || raw;
            }
            if (/quote_qty_capped/i.test(raw)) severity = 'warn';
            if (/COMMAND_EXECUTED/i.test(raw)) {
                typeLabel = 'Tur ' + (meta.cycle_id != null ? meta.cycle_id : 1);
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

    function collapseEngineEvents(events) {
        var collapsed = [];
        var prev = null;
        (events || []).forEach(function (ev) {
            var fmt = formatEngineEvent(ev);
            if (fmt.hidden) return;
            var key = (ev.type || '') + '\0' + fmt.message + '\0' + fmt.severity;
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
                    lastTs: ev.ts
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
        _logContext = ctx && typeof ctx === 'object' ? ctx : {};
    }

    global.EngineLogFormat = {
        formatEngineEvent: formatEngineEvent,
        collapseEngineEvents: collapseEngineEvents,
        hasRecentCritical: hasRecentCritical,
        rowClass: rowClass,
        setLogContext: setLogContext
    };
})(typeof window !== 'undefined' ? window : globalThis);
