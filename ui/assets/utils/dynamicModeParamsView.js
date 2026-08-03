/**
 * dynamicModeParamsView.js — read-only dynamic mode blocks for Parametreler modals.
 */
(function (global) {
    'use strict';

    var REGIME_LABELS = {
        R1: 'Güçlü yükseliş trendi',
        R2: 'Dengeli aralık',
        R3: 'Zayıf / gürültülü aralık',
        R4: 'Volatil aralık',
        R5: 'Yukarı kırılım / momentum',
        R6: 'Toparlanma / kontrollü geri dönüş',
        R7: 'Düşüş trendi',
        R8: 'Crash / sert düşüş',
        LOW_VOL_RANGING: 'Düşük volatilite / yatay',
        HIGH_VOL_RANGING: 'Yüksek volatilite / yatay (chop)',
        TRENDING_UP: 'Yukarı trend',
        TRENDING_DOWN: 'Aşağı trend (savunma)',
        SQUEEZE: 'Sıkışma (squeeze)',
        BREAKOUT: 'Kırılım (breakout)',
        DUMP_RISK: 'Dump riski',
        UNKNOWN: 'Belirsiz'
    };

    function attrEsc(v) {
        return String(v == null ? '' : v)
            .replace(/&/g, '&amp;')
            .replace(/"/g, '&quot;')
            .replace(/</g, '&lt;');
    }

    function ensureDynModeGhostTipEl() {
        var el = document.getElementById('dynModeGhostTip');
        if (el) return el;
        el = document.createElement('div');
        el.id = 'dynModeGhostTip';
        el.className = 'dyn-mode-ghost-tip';
        el.setAttribute('role', 'tooltip');
        el.hidden = true;
        document.body.appendChild(el);
        return el;
    }

    function showDynModeGhostTip(host) {
        if (!host) return;
        var text = host.getAttribute('data-dyn-tip');
        if (!text) return;
        var tipEl = ensureDynModeGhostTipEl();
        tipEl.textContent = text;
        tipEl.hidden = false;
        var r = host.getBoundingClientRect();
        tipEl.style.left = Math.round(r.left + r.width / 2) + 'px';
        tipEl.style.top = Math.round(r.top - 6) + 'px';
    }

    function hideDynModeGhostTip() {
        var tipEl = document.getElementById('dynModeGhostTip');
        if (tipEl) tipEl.hidden = true;
    }

    function bindDynModeLogoTips() {
        if (bindDynModeLogoTips._done) return;
        bindDynModeLogoTips._done = true;
        ensureDynModeGhostTipEl();
        document.addEventListener('mouseover', function (e) {
            var host = e.target && e.target.closest ? e.target.closest('[data-dyn-tip]') : null;
            if (!host) return;
            clearTimeout(bindDynModeLogoTips._hideT);
            showDynModeGhostTip(host);
        });
        document.addEventListener('mouseout', function (e) {
            var host = e.target && e.target.closest ? e.target.closest('[data-dyn-tip]') : null;
            if (!host) return;
            var rel = e.relatedTarget;
            if (rel && host.contains(rel)) return;
            bindDynModeLogoTips._hideT = setTimeout(hideDynModeGhostTip, 30);
        });
        document.addEventListener('scroll', hideDynModeGhostTip, true);
    }

    if (typeof document !== 'undefined') {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', bindDynModeLogoTips);
        } else {
            bindDynModeLogoTips();
        }
    }

    function esc(v) {
        if (v === null || v === undefined) return '—';
        var s = String(v);
        return typeof escapeHtml === 'function' ? escapeHtml(s) : s;
    }

    function fmtPct(v) {
        if (v == null || isNaN(Number(v))) return '—';
        return Number(v).toFixed(2) + '%';
    }

    function fmtPctSigned(v, sign) {
        if (v == null || isNaN(Number(v))) return '—';
        return sign + Number(v).toFixed(2) + '%';
    }

    function fmtNumLocal(v, d) {
        if (v == null || isNaN(Number(v))) return '—';
        if (typeof fmtNum === 'function') return fmtNum(v, d == null ? 2 : d);
        return Number(v).toFixed(d == null ? 2 : d);
    }

    function isDynamicModeUiActive(dyn, cfg) {
        dyn = dyn || {};
        cfg = cfg || {};
        if (dyn.active === true) return true;
        if (dyn.enabled === true && (!dyn.safety_gate || dyn.safety_gate.ok !== false)) return true;
        return !!(cfg.dynamic_mode && dyn.enabled !== false && (!dyn.safety_gate || dyn.safety_gate.ok !== false));
    }

    /** Dashboard listeleri: API dynamic_mode veya config + çalışıyor durumu. */
    /** Leaderboard satır rozeti — API dynamic_mode yeterli (params'ta dynamic_mode olmayabilir). */
    function isLeaderboardDynamicBadgeVisible(dyn) {
        dyn = dyn || {};
        if (dyn.active === true || dyn.enabled === true) return true;
        var snap = dyn.snapshot;
        return !!(snap && snap.applied && typeof snap.applied === 'object');
    }

    function isDynamicModeActiveForList(dyn, cfg, botStatus) {
        if (isDynamicModeUiActive(dyn, cfg)) return true;
        cfg = cfg || {};
        if (!cfg.dynamic_mode) return false;
        if (dyn && dyn.enabled === false) return false;
        var st = String(botStatus || '').toLowerCase();
        return !st || st === 'running';
    }

    function dynamicModeHoverTitle(dyn, cfg) {
        dyn = dyn || {};
        var title = 'Dinamik strateji modu aktif — parametreler her tur başında otomatik hesaplanır';
        if (dyn.snapshot && dyn.snapshot.regime) {
            title += ' · Rejim: ' + (REGIME_LABELS[dyn.snapshot.regime] || dyn.snapshot.regime);
        } else if (cfg && cfg.dynamic_mode) {
            title += ' · Tur parametreleri otomatik ayarlanır';
        }
        return title;
    }

    /** Logo hover — kısa metin, anında ghost ipucu. */
    function dynamicModeLogoTipShort(dyn, cfg) {
        dyn = dyn || {};
        if (dyn.snapshot && dyn.snapshot.regime) {
            return 'Dinamik mod · ' + (REGIME_LABELS[dyn.snapshot.regime] || dyn.snapshot.regime);
        }
        return 'Dinamik mod aktif';
    }

    function renderDynamicBadgeHtml(title) {
        title = title || 'Dinamik strateji modu aktif';
        return '<span class="status-badge status-running dyn-mode-list-badge dyn-mode-leaderboard-badge" title="' + esc(title) + '">Dinamik ✓</span>';
    }

    function wrapLogoForDynamicMode(logoHtml, active, tip) {
        if (!active || !logoHtml) return logoHtml;
        tip = tip || 'Dinamik mod aktif';
        return '<span class="dyn-mode-logo-wrap" data-dyn-tip="' + attrEsc(tip) + '">' + logoHtml + '</span>';
    }

    function dynamicModeStatusLabel(dyn) {
        dyn = dyn || {};
        if (!dyn.enabled) return { text: 'Kapalı', cls: 'dyn-param-status--off' };
        if (dyn.first_cycle_manual) return { text: 'İlk tur manuel', cls: 'dyn-param-status--warn' };
        if (dyn.active) return { text: 'Aktif', cls: 'dyn-param-status--on' };
        if (dyn.safety_gate && dyn.safety_gate.ok === false) {
            return { text: 'Etkin değil (güvenlik ön koşulları)', cls: 'dyn-param-status--warn' };
        }
        return { text: 'Beklemede', cls: 'dyn-param-status--warn' };
    }

    function fmtPctDisplay(v) {
        if (v == null || isNaN(Number(v))) return null;
        var n = Number(v);
        if (typeof fmtNum === 'function') {
            return fmtNum(n, Math.abs(n - Math.round(n)) < 0.0001 ? 0 : 2);
        }
        return Math.abs(n - Math.round(n)) < 0.0001 ? String(Math.round(n)) : n.toFixed(2);
    }

    function fmtRefPrice(v) {
        if (v == null || isNaN(Number(v))) return '—';
        if (typeof fmtBotPrice === 'function') return fmtBotPrice(v, [v]);
        return fmtNumLocal(v, 4);
    }

    function paramRow(label, value, cls) {
        var safeCls = cls
            ? String(cls).split(/\s+/).filter(function (part) {
                return /^[a-z0-9_-]+$/i.test(part);
            }).join(' ')
            : '';
        var displayValue = value !== undefined && value !== '' ? value : '—';
        return '<div class="param-row' + (safeCls ? ' ' + safeCls : '') + '">' +
            '<span class="param-label">' + esc(label) + '</span>' +
            '<span class="param-value">' + esc(displayValue) + '</span>' +
            '</div>';
    }

    function resolveConfigAllocation(cfg, allocOverride) {
        cfg = cfg || {};
        var alloc = cfg.allocation || {};
        var basePct = allocOverride && allocOverride.base_alloc_pct != null
            ? allocOverride.base_alloc_pct
            : (cfg.base_alloc_pct != null ? cfg.base_alloc_pct : (alloc.base_pct != null ? alloc.base_pct : null));
        var quotePct = allocOverride && allocOverride.quote_alloc_pct != null
            ? allocOverride.quote_alloc_pct
            : (cfg.quote_alloc_pct != null ? cfg.quote_alloc_pct : (alloc.quote_pct != null ? alloc.quote_pct : null));
        if (quotePct == null && basePct != null && !isNaN(Number(basePct))) {
            quotePct = 100 - Number(basePct);
        }
        return { basePct: basePct, quotePct: quotePct };
    }

    function resolveDynamicAllocation(dyn, applied) {
        dyn = dyn || {};
        applied = applied || {};
        var fromApplied = {
            base_alloc_pct: applied.base_alloc_pct,
            quote_alloc_pct: applied.quote_alloc_pct,
        };
        if (fromApplied.base_alloc_pct != null || fromApplied.quote_alloc_pct != null) {
            return fromApplied;
        }
        var pos = dyn.position || {};
        if (pos.base_alloc_pct != null || pos.quote_alloc_pct != null) {
            return {
                base_alloc_pct: pos.base_alloc_pct,
                quote_alloc_pct: pos.quote_alloc_pct,
            };
        }
        return null;
    }

    /** Genel blok — bot detay Parametreler modalı ile aynı satırlar. */
    function renderGeneralParamsBlock(cfg, symbol, referencePrice, allocOverride, opts) {
        cfg = cfg || {};
        opts = opts || {};
        var budget = cfg.initial_capital_usdt != null ? cfg.initial_capital_usdt : (cfg.budget_usd != null ? cfg.budget_usd : null);
        var ref = referencePrice != null && !isNaN(Number(referencePrice))
            ? referencePrice
            : (cfg.reference_price != null && !isNaN(Number(cfg.reference_price)) ? Number(cfg.reference_price) : null);
        var alloc = resolveConfigAllocation(cfg, allocOverride);
        var baseDisp = alloc.basePct != null ? fmtPctDisplay(alloc.basePct) + '%' : '—';
        var quoteDisp = alloc.quotePct != null ? fmtPctDisplay(alloc.quotePct) + '%' : '—';
        var budgetDisp = typeof fmtUsd === 'function' ? fmtUsd(budget) : fmtNumLocal(budget, 2);
        var html = '<div class="param-block"><div class="param-block-title">Genel</div>';
        html += paramRow('Sembol', symbol || cfg.symbol || '—');
        if (!opts.hideBudget) {
            html += paramRow('Bütçe (USDT)', budgetDisp);
        }
        html += paramRow('Başlangıç fiyatı (referans)', fmtRefPrice(ref));
        html += paramRow('Base dağılım (%)', baseDisp);
        html += paramRow('Quote dağılım (%)', quoteDisp);
        html += '</div>';
        return html;
    }

    function renderGridTable(grids, side) {
        if (!Array.isArray(grids) || !grids.length) {
            return '<p class="param-hint">Bu tur için grid tanımı yok.</p>';
        }
        var isSell = side === 'sell';
        var qtyHead = isSell ? 'Miktar (base %)' : 'Miktar (quote %)';
        var html = '<table class="param-table"><thead><tr><th>Seviye</th><th class="num">Tetik %</th><th class="num">' + qtyHead + '</th></tr></thead><tbody>';
        grids.forEach(function (g, i) {
            var pct = isSell
                ? (g.sell_grid_pct != null ? g.sell_grid_pct : g.trigger_pct)
                : (g.buy_grid_pct != null ? g.buy_grid_pct : g.trigger_pct);
            var qty = isSell
                ? (g.sell_qty_pct_of_base != null ? g.sell_qty_pct_of_base : g.qty_pct)
                : (g.buy_qty_pct_of_quote != null ? g.buy_qty_pct_of_quote : g.qty_pct);
            var sign = isSell ? '+' : '-';
            html += '<tr><td>#' + (i + 1) + '</td><td class="num">' + fmtPctSigned(pct, sign) + '</td><td class="num">' + fmtPct(qty) + '</td></tr>';
        });
        html += '</tbody></table>';
        return html;
    }

    function renderPositionBlock(position, state, symbol, showBalances) {
        position = position || {};
        state = state || {};
        var apBase = position.base_alloc_pct;
        var apQuote = position.quote_alloc_pct;
        var html = '<div class="param-block"><div class="param-block-title">Mevcut tur pozisyonu</div>';
        html += paramRow('Base dağılım (dinamik)', apBase != null ? fmtPct(apBase) : '—');
        html += paramRow('Quote dağılım (dinamik)', apQuote != null ? fmtPct(apQuote) : '—');
        if (position.buy_levels_fired != null || position.max_buy_levels != null) {
            html += paramRow(
                'Alış seviyeleri (tetiklenen / max)',
                (position.buy_levels_fired != null ? position.buy_levels_fired : '—') + ' / ' + (position.max_buy_levels != null ? position.max_buy_levels : '—')
            );
        }
        if (position.sell_levels_fired != null && position.sell_grid_count != null) {
            html += paramRow(
                'Satış seviyeleri (tetiklenen / toplam)',
                position.sell_levels_fired + ' / ' + position.sell_grid_count
            );
        }
        if (position.initial_allocation_done != null) {
            html += paramRow('İlk dağılım tamamlandı', position.initial_allocation_done ? 'Evet' : 'Hayır');
        }
        if (showBalances) {
            var baseBal = state.base_balance;
            var quoteBal = state.quote_balance;
            if (baseBal != null && !isNaN(Number(baseBal))) {
                var baseAsset = symbol ? String(symbol).replace(/USDT$|FDUSD$|BUSD$|TUSD$/i, '') : 'BASE';
                var baseStr = typeof fmtBaseCompact === 'function' ? fmtBaseCompact(baseBal) : fmtNumLocal(baseBal, 4);
                html += paramRow('Base bakiye', baseStr + ' ' + baseAsset);
            }
            if (quoteBal != null && !isNaN(Number(quoteBal))) {
                var quoteStr = typeof fmtUsd === 'function' ? fmtUsd(quoteBal) : fmtNumLocal(quoteBal, 2);
                html += paramRow('Quote bakiye', quoteStr);
            }
        }
        html += '</div>';
        return html;
    }

    function regimeDirectionLabel(regime) {
        regime = String(regime || '').toUpperCase();
        if (regime === 'TRENDING_UP') return 'Yukarı trend';
        if (regime === 'TRENDING_DOWN') return 'Aşağı trend / savunma';
        if (regime === 'DUMP_RISK') return 'Aşağı risk';
        if (regime === 'BREAKOUT') return 'Kırılım yönü';
        if (regime === 'SQUEEZE') return 'Sıkışma / nötr';
        if (regime === 'LOW_VOL_RANGING') return 'Yatay / sakin';
        if (regime === 'HIGH_VOL_RANGING') return 'Yatay / dalgalı';
        return REGIME_LABELS[regime] || 'Belirsiz';
    }

    function renderAppliedParamsBlock(applied, snap) {
        applied = applied || {};
        snap = snap || {};
        var sellGrids = applied.sell_grids || [];
        var buyGrids = applied.buy_grids || [];
        var html = '<div class="param-block"><div class="param-block-title">Satış gridleri</div>';
        html += paramRow('Rejim yönü', regimeDirectionLabel(snap.regime), 'param-sell');
        html += paramRow('Grid sayısı', sellGrids.length, 'param-sell');
        html += paramRow('Trailing % (tetik sonrası gerçekleşme)', fmtPct(applied.sell_trigger_trailing_pct), 'param-sell');
        html += renderGridTable(applied.sell_grids, 'sell');
        html += '</div>';
        html += '<div class="param-block"><div class="param-block-title">Alım gridleri</div>';
        html += paramRow('Grid sayısı', buyGrids.length, 'param-buy');
        html += paramRow('Trailing % (tetik sonrası gerçekleşme)', fmtPct(applied.buy_trigger_trailing_pct), 'param-buy');
        html += renderGridTable(applied.buy_grids, 'buy');
        html += '</div>';
        html += '<div class="param-block"><div class="param-block-title">Kar alım / kar satış</div>';
        html += paramRow('Kar alım tetik %', fmtPct(applied.profit_reentry_drop_pct));
        html += paramRow('Kar alım trailing %', fmtPct(applied.profit_reentry_rise_pct));
        html += paramRow('Kar satış tetik %', fmtPct(applied.profit_exit_rise_pct));
        html += paramRow('Kar satış trailing %', fmtPct(applied.profit_exit_drop_pct));
        html += '</div>';
        return html;
    }

    function fmtMultiplier(v) {
        if (v == null || isNaN(Number(v))) return '—';
        return '×' + Number(v).toFixed(2);
    }

    function renderRegimeMultiplierBlock(snap) {
        snap = snap || {};
        var meta = snap.multiplier || (snap.dps && snap.dps.multiplier) || {};
        var scores = meta.direction_scores || {};
        var confidence = meta.confidence || {};
        var factors = meta.multipliers || {};
        var invariant = meta.grid_count_invariant || {};
        if (!meta.contract_version && !Object.keys(factors).length) return '';

        var html = '<div class="param-block dyn-param-cycle"><div class="param-block-title">Rejim çarpanları</div>';
        html += paramRow('Yukarı yön kanıtı', scores.up != null ? fmtPct(Number(scores.up) * 100) : '—', 'param-sell');
        html += paramRow('Aşağı yön kanıtı', scores.down != null ? fmtPct(Number(scores.down) * 100) : '—', 'param-buy');
        html += paramRow('Uygulama güveni', confidence.effective != null ? fmtPct(Number(confidence.effective) * 100) : '—');
        html += paramRow('Base / quote çarpanı', fmtMultiplier(factors.base_alloc) + ' / ' + fmtMultiplier(factors.quote_alloc));
        html += paramRow('Alış / satış mesafe çarpanı', fmtMultiplier(factors.buy_distance) + ' / ' + fmtMultiplier(factors.sell_distance));
        html += paramRow('Alış / satış trailing çarpanı', fmtMultiplier(factors.buy_trailing) + ' / ' + fmtMultiplier(factors.sell_trailing));
        if (invariant.buy_initial != null || invariant.sell_initial != null) {
            html += paramRow(
                'Grid adedi (alış / satış)',
                (invariant.buy_applied != null ? invariant.buy_applied : invariant.buy_initial) +
                ' / ' +
                (invariant.sell_applied != null ? invariant.sell_applied : invariant.sell_initial) +
                (invariant.preserved === false ? ' · kontrol gerekli' : ' · sabit')
            );
        }
        html += '</div>';
        return html;
    }

    /** Compact block for En İyi 5 Bot (Bots tab) parametreler modal. */
    function renderLeaderboardDynamicSection(dyn, symbol) {
        dyn = dyn || {};
        var status = dynamicModeStatusLabel(dyn);
        var html = '<div class="dyn-param-leaderboard-banner ' + status.cls + '">';
        html += '<div class="dyn-param-leaderboard-head"><span class="dyn-param-leaderboard-title">Dinamik mod</span>';
        html += '<span class="dyn-param-status-badge">' + esc(status.text) + '</span></div>';

        if (!dyn.enabled) {
            html += '<p class="param-hint">Bu bot statik (manuel) parametrelerle çalışıyor.</p></div>';
            return html;
        }

        if (dyn.first_cycle_manual) {
            html += '<p class="param-hint">İlk tur manuel başlangıç değerleriyle çalışıyor; dinamik değerler tur 2 başında hesaplanacak.</p></div>';
            return html;
        }

        if (!dyn.active) {
            html += '<p class="param-hint">Dinamik mod yapılandırılmış ancak şu an aktif değil. Aşağıdaki değerler başlangıç şablonudur.</p></div>';
            return html;
        }

        var snap = dyn.snapshot;
        var ap = snap && snap.applied;
        if (!snap || !ap) {
            html += '<p class="param-hint">Aktif tur snapshot\'ı henüz yok; bir sonraki tur başında güncellenecek.</p></div>';
            return html;
        }

        var regime = REGIME_LABELS[snap.regime] || snap.regime || '—';
        html += '<p class="dyn-param-leaderboard-meta">';
        html += esc('Rejim: ' + regime + ' · Tur #' + (snap.cycle_id != null ? snap.cycle_id : '?'));
        if (snap.data_fresh === false) html += ' · ⚠ veri eski';
        html += '</p>';
        html += renderPositionBlock(dyn.position, null, symbol, false);
        html += renderRegimeMultiplierBlock(snap);
        html += renderAppliedParamsBlock(ap, snap);
        html += '</div>';
        return html;
    }

    /** Full Dinamik tab for bot detay / leaderboard parametreler modal. opts.showBalances: bakiye satırları (leaderboard: false). */
    function renderBotDetailDynamicTab(dyn, state, symbol, cfg, opts) {
        dyn = dyn || {};
        state = state || {};
        cfg = cfg || {};
        opts = opts || {};
        if (!dyn.enabled && !cfg.dynamic_mode) {
            return '<p class="param-hint">Bu bot statik parametrelerle çalışıyor.</p>';
        }

        var snap = resolveDynSnapshot(dyn, state);
        var applied = snap && snap.applied;
        var allocOverride = resolveDynamicAllocation(dyn, applied);
        var html = renderGeneralParamsBlock(cfg, symbol, opts.referencePrice, allocOverride, opts);

        if (snap && snap.regime) {
            var regimeLabel = resolveDynRegimeLabel(dyn, snap) || '—';
            html += '<div class="param-block dyn-param-cycle"><div class="param-block-title">Dinamik tur parametreleri</div>';
            html += paramRow('Ana rejim', regimeLabel);
            html += paramRow('Tur', snap.cycle_id != null ? ('#' + snap.cycle_id) : '—');
            html += paramRow('Veri durumu', snap.data_fresh === false ? 'Gecikmeli / korumalı' : 'Canlı');
            html += '</div>';
        }

        if (dyn.first_cycle_manual && !applied) {
            var firstRegimeLabel = resolveDynRegimeLabel(dyn, snap);
            html += '<div class="param-block dyn-param-cycle"><div class="param-block-title">Dinamik tur parametreleri</div>';
            html += paramRow('Ana rejim', firstRegimeLabel || '—');
            html += paramRow('Tur', 'İlk tur');
            html += '</div>';
            return html;
        }

        if (!snap || !applied) {
            html += '<div class="param-block dyn-param-cycle"><div class="param-block-title">Dinamik tur parametreleri</div>';
            html += paramRow('Ana rejim', resolveDynRegimeLabel(dyn, snap) || '—');
            html += paramRow('Tur', (state.cycle_id != null ? ('#' + state.cycle_id) : '—'));
            html += '</div>';
            return html;
        }

        html += renderRegimeMultiplierBlock(snap);
        html += renderAppliedParamsBlock(applied, snap);
        if (dyn.emergency) {
            var emg = dyn.emergency;
            var emgAction = emg.action || emg.code || '';
            var emgLabel = emgAction === 'EMERGENCY_CLOSE' ? 'Portföy risk freni'
                : emgAction === 'STOP_LOSS' ? 'Tur risk freni'
                : (emgAction || '—');
            html += '<div class="param-block dyn-param-emergency"><div class="param-block-title">Risk freni</div>';
            html += paramRow('Tetik', emgLabel);
            if (emg.reason) html += paramRow('Gerekçe', emg.reason);
            html += paramRow('Durum', 'Bot duraklatıldı — pozisyon korunuyor; devam için operatör müdahalesi gerekir');
            html += '</div>';
        }
        return html;
    }

    function sumFired(arr) {
        if (!Array.isArray(arr)) return null;
        return arr.reduce(function (n, x) { return n + (x ? 1 : 0); }, 0);
    }

    /** Rejim başına varsayılan strateji aksiyonları (yüzdesiz, operatör dili). */
    var REGIME_ACTIONS = {
        LOW_VOL_RANGING: 'Sakin piyasa — gridler daraltıldı, dengeli dağılım',
        HIGH_VOL_RANGING: 'Dalgalı yatay piyasa — gridler genişletildi, alım hacmi kısıldı',
        TRENDING_UP: 'Yukarı trend — base ağırlığı artırıldı, alım temposu düşürüldü, kâr hedefi genişletildi',
        TRENDING_DOWN: 'Aşağı trend — nakit korundu, alım merdiveni daraltıldı, savunma modu',
        SQUEEZE: 'Sıkışma — orta grid aralığı, dengeli pozisyon',
        BREAKOUT: 'Kırılım — geniş grid ve yüksek trailing uygulandı',
        DUMP_RISK: 'Dump riski — minimum alım, maksimum nakit tutuldu',
        UNKNOWN: 'Belirsiz rejim — manuel ayarlara yakın güvenli mod'
    };

    function _humanizeDynReason(raw) {
        if (!raw || typeof raw !== 'string') return null;
        var r = raw.trim();
        if (/^regime=/i.test(r)) return null;
        if (/^atr_pct/i.test(r)) return null;
        if (/^grid_step raw/i.test(r)) return 'Grid aralıkları volatiliteye göre ayarlandı';
        if (/^grid_qty:\s*manual/i.test(r)) return 'Grid miktar oranları manuel şablondan korundu';
        if (/^sell_grids n=/i.test(r)) return null;
        if (/^trailing_raw/i.test(r)) return 'Trailing mesafesi volatilite ve rejime göre ayarlandı';
        if (/^base\/quote target/i.test(r)) return 'Base / quote dağılımı rejime göre kaydırıldı';
        if (/^profit_exit/i.test(r)) return 'Kâr al ve re-entry eşikleri volatiliteye göre ayarlandı';
        if (/DEFENSIVE.*halved/i.test(r)) return 'Alış seviyeleri dolmak üzere — alım dağılımı yarıya indirildi';
        if (/overbought.*buy/i.test(r)) return 'RSI aşırı alım — yeni alımlar azaltıldı';
        if (/oversold.*sell/i.test(r)) return 'RSI aşırı satım — satış baskısı hafifletildi';
        if (/spread.*buy/i.test(r)) return 'Geniş spread — alımlar azaltıldı';
        if (/illiquid.*buy/i.test(r)) return 'Düşük 24s hacim — alımlar azaltıldı';
        if (/^deployment buy_mult/i.test(r)) {
            var m = r.match(/buy_mult=([\d.]+)/);
            var mult = m ? parseFloat(m[1]) : 1;
            if (mult <= 0.35) return 'Rejim riski — alım hacmi minimuma indirildi';
            if (mult <= 0.55) return 'Rejim riski — alım hacmi ciddi şekilde kısıldı';
            if (mult < 0.9) return 'Rejim riski — alım hacmi kısmen kısıldı';
            return null;
        }
        if (/smoothing:\s*no prev/i.test(r)) return 'İlk tur snapshot — doğrudan hesaplama uygulandı';
        if (/smoothing:\s*alpha/i.test(r)) return 'Önceki tur ile yumuşatılarak uygulandı';
        if (/DATA_STALE/i.test(r)) return 'Piyasa verisi eski — önceki tur parametreleri korundu';
        return null;
    }

    function _humanizeDynClamp(raw) {
        if (!raw || typeof raw !== 'string') return null;
        var r = raw.trim();
        if (/grid_step_pct|sell_grids\[|buy_grids\[/i.test(r)) return 'Grid adımı güvenlik sınırına çekildi';
        if (/base_alloc_pct|quote_alloc_pct/i.test(r)) return 'Dağılım güvenlik sınırına çekildi';
        if (/trigger_trailing|profit_exit|profit_reentry/i.test(r)) return 'Trailing / kâr eşiği güvenlik sınırına çekildi';
        if (/rate_limit/i.test(r)) return 'Tur içi değişim hızı sınırlandı';
        return 'Risk motoru güvenlik sınırı uygulandı';
    }

    function _humanizeDynFallback(raw) {
        if (!raw || typeof raw !== 'string') return null;
        if (/data_stale/i.test(raw)) return 'Veri eski — önceki tur değerleri kullanıldı';
        if (/no_prev_snapshot/i.test(raw)) return 'Önceki snapshot yok — manuel şablon kullanıldı';
        if (/manual fallback/i.test(raw)) return 'Boş grid — manuel şablona dönüldü';
        return null;
    }

    /**
     * Grid panel banner için: rejim + yapılan aksiyonlar (yüzdesiz, kısa cümleler).
     * Returns { regimeLabel, cycleId, actions: string[], stale: bool }
     */
    function summarizeDynSnapshotActions(snap) {
        snap = snap || {};
        var regime = snap.regime || 'UNKNOWN';
        var out = [];
        var seen = {};
        function push(msg) {
            if (!msg || seen[msg]) return;
            seen[msg] = true;
            out.push(msg);
        }
        if (REGIME_ACTIONS[regime]) push(REGIME_ACTIONS[regime]);
        (snap.reasons || []).forEach(function (r) { push(_humanizeDynReason(r)); });
        var clamps = (snap.applied && snap.applied.clamps) || snap.clamps || [];
        clamps.forEach(function (c) { push(_humanizeDynClamp(c)); });
        var fallbacks = (snap.applied && snap.applied.fallbacks) || snap.fallbacks || [];
        fallbacks.forEach(function (f) { push(_humanizeDynFallback(f)); });
        if (!out.length) push('Manuel parametreler rejime göre ayarlandı');
        return {
            regimeLabel: REGIME_LABELS[regime] || regime || '—',
            cycleId: snap.cycle_id,
            actions: out,
            stale: snap.data_fresh === false
        };
    }

    /**
     * Snapshot: API dynamic_mode.snapshot veya state.dynamic_snapshot yedek.
     */
    function resolveDynSnapshot(dyn, state) {
        dyn = dyn || {};
        state = state || {};
        var snap = dyn.snapshot;
        if (typeof snap !== 'object' || snap === null) {
            snap = state.dynamic_snapshot;
        }
        return (typeof snap === 'object' && snap !== null) ? snap : null;
    }

    function resolveDynRegimeLabel(dyn, snap) {
        dyn = dyn || {};
        snap = (typeof snap === 'object' && snap !== null) ? snap : (dyn.snapshot || null);
        var label = (snap && (snap.regime_label || snap.main_regime_label || snap.preview_regime_label))
            || dyn.preview_regime_label
            || dyn.main_regime_label;
        if (label != null && label !== '') return String(label);
        var raw = (snap && (snap.regime || snap.main_regime || snap.preview_regime))
            || dyn.preview_regime
            || dyn.main_regime
            || dyn.regime
            || dyn.regime_label;
        if (!raw && dyn.stance && typeof dyn.stance === 'object') {
            raw = dyn.stance.regime || dyn.stance.main_regime;
        }
        if (raw == null || raw === '') return '';
        return REGIME_LABELS[raw] || String(raw);
    }

    /**
     * Grid panel banner HTML — rejim + gösterge satırı.
     */
    function buildDynGridBannerHtml(dyn, snap, esc) {
        esc = esc || function (s) { return String(s == null ? '' : s); };
        var badge = '<span class="status-badge status-running">Dinamik ✓</span>';
        dyn = dyn || {};

        if (dyn.first_cycle_manual) {
            var firstRegimeLabel = resolveDynRegimeLabel(dyn, snap);
            return {
                html: badge + '<span class="dyn-mode-grid-note__line1"><span class="dyn-mode-grid-note__strong">'
                    + (firstRegimeLabel ? esc(firstRegimeLabel) : '') + '</span></span>',
                title: firstRegimeLabel || 'Dinamik mod'
            };
        }

        if (!snap || (!snap.applied && !snap.regime)) {
            if (dyn.active === true) {
                return {
                    html: badge + '<span class="dyn-mode-grid-note__line1"><span class="dyn-mode-grid-note__hint">tur snapshot bekleniyor…</span></span>',
                    title: 'Dinamik mod aktif; engine bir sonraki tick\'te snapshot üretir'
                };
            }
            if (dyn.enabled === true) {
                return {
                    html: badge + '<span class="dyn-mode-grid-note__line1"><span class="dyn-mode-grid-note__hint">açık — overlay henüz yok</span></span>',
                    title: 'Dinamik mod yapılandırıldı'
                };
            }
            return { html: '', title: '', hide: true };
        }

        var regimeLabel = REGIME_LABELS[snap.regime] || snap.regime || '—';
        var staleHint = snap.data_fresh === false ? ' <span class="dyn-mode-grid-note__hint">(veri eski)</span>' : '';
        var indLine = formatDynRegimeIndicatorLine(snap);
        var indHtml = indLine ? ' <span class="dyn-mode-grid-note__inds">· ' + esc(indLine) + '</span>' : '';
        return {
            html: badge + '<span class="dyn-mode-grid-note__line1"><span class="dyn-mode-grid-note__strong">'
                + esc(regimeLabel) + '</span>' + indHtml + staleHint + '</span>',
            title: indLine ? (regimeLabel + ' — ' + indLine) : regimeLabel
        };
    }

    /**
     * Rejim sınıflandırmasında kullanılan gösterge değerleri — grid banner için kısa satır.
     */
    function formatDynRegimeIndicatorLine(snap) {
        snap = snap || {};
        var f = snap.features || {};
        var regime = snap.regime || '';
        var parts = [];

        function add(label, raw, fmt) {
            if (raw == null || raw === '' || isNaN(Number(raw))) return;
            parts.push(label + ' ' + (fmt ? fmt(Number(raw)) : String(raw)));
        }
        function pct(v, d) {
            d = d == null ? 2 : d;
            return (v >= 0 ? '+' : '') + v.toFixed(d) + '%';
        }

        var conf = null;
        (snap.reasons || []).some(function (r) {
            var m = String(r).match(/confidence=([\d.]+)/);
            if (m) { conf = parseFloat(m[1]); return true; }
            return false;
        });

        if (regime === 'TRENDING_UP' || regime === 'TRENDING_DOWN') {
            add('ADX', f.adx_1h, function (v) { return fmtNumLocal(v, 0) + ' (≥25 trend)'; });
            add('EMA eğim', f.ema_slope_1h_pct, function (v) { return pct(v, 2); });
        } else if (regime === 'HIGH_VOL_RANGING' || regime === 'LOW_VOL_RANGING') {
            add('ATR', f.atr_pct_5m, function (v) { return v.toFixed(2) + '%'; });
            add('ADX', f.adx_1h, function (v) { return fmtNumLocal(v, 0) + ' (≤20 yatay)'; });
        } else if (regime === 'SQUEEZE') {
            add('BBW', f.bbw_1h != null ? f.bbw_1h : f.bbw_5m, function (v) { return fmtNumLocal(v, 1) + ' (dar bant)'; });
            add('ATR', f.atr_pct_5m, function (v) { return v.toFixed(2) + '%'; });
        } else if (regime === 'BREAKOUT') {
            add('BBW', f.bbw_1h != null ? f.bbw_1h : f.bbw_5m, function (v) { return fmtNumLocal(v, 1); });
            add('Hacim z', f.volume_zscore_5m, function (v) { return fmtNumLocal(v, 1) + ' (≥2 spike)'; });
            add('EMA eğim', f.ema_slope_1h_pct, function (v) { return pct(v, 2); });
        } else if (regime === 'DUMP_RISK') {
            add('5m düşüş', f.ret_5m_last, function (v) { return pct(v, 2); });
            add('EMA eğim', f.ema_slope_1h_pct, function (v) { return pct(v, 2); });
            add('Hacim z', f.volume_zscore_5m, function (v) { return fmtNumLocal(v, 1); });
        } else {
            add('ADX', f.adx_1h, function (v) { return fmtNumLocal(v, 0); });
            add('ATR', f.atr_pct_5m, function (v) { return v.toFixed(2) + '%'; });
        }

        if (conf != null && !isNaN(conf)) {
            parts.push('Güven %' + Math.round(Math.max(0, Math.min(1, conf)) * 100));
        }

        return parts.join(' · ');
    }

    function renderParamModalTabsHtml(activeTab) {
        activeTab = activeTab || 'genel';
        return '<div class="param-tabs-wrap" role="tablist">' +
            '<button type="button" class="param-tab' + (activeTab === 'genel' ? ' active' : '') + '" data-param-tab="genel" role="tab">Genel</button>' +
            '<button type="button" class="param-tab' + (activeTab === 'dinamik' ? ' active' : '') + '" data-param-tab="dinamik" role="tab">Dinamik</button>' +
            '</div>';
    }

    global.DynModeParamsView = {
        REGIME_LABELS: REGIME_LABELS,
        isDynamicModeUiActive: isDynamicModeUiActive,
        isDynamicModeActiveForList: isDynamicModeActiveForList,
        isLeaderboardDynamicBadgeVisible: isLeaderboardDynamicBadgeVisible,
        dynamicModeHoverTitle: dynamicModeHoverTitle,
        dynamicModeLogoTipShort: dynamicModeLogoTipShort,
        renderDynamicBadgeHtml: renderDynamicBadgeHtml,
        wrapLogoForDynamicMode: wrapLogoForDynamicMode,
        dynamicModeStatusLabel: dynamicModeStatusLabel,
        renderLeaderboardDynamicSection: renderLeaderboardDynamicSection,
        renderGeneralParamsBlock: renderGeneralParamsBlock,
        renderBotDetailDynamicTab: renderBotDetailDynamicTab,
        renderParamModalTabsHtml: renderParamModalTabsHtml,
        summarizeDynSnapshotActions: summarizeDynSnapshotActions,
        formatDynRegimeIndicatorLine: formatDynRegimeIndicatorLine,
        resolveDynSnapshot: resolveDynSnapshot,
        resolveDynRegimeLabel: resolveDynRegimeLabel,
        buildDynGridBannerHtml: buildDynGridBannerHtml,
        bindDynModeLogoTips: bindDynModeLogoTips,
        attrEsc: attrEsc
    };
})(typeof window !== 'undefined' ? window : globalThis);
