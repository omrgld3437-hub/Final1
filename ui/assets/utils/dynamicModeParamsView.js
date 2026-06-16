/**
 * dynamicModeParamsView.js — read-only dynamic mode blocks for Parametreler modals.
 */
(function (global) {
    'use strict';

    var REGIME_LABELS = {
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
        if (dyn.enabled === true && dyn.safety_gate && dyn.safety_gate.ok === true) return true;
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
        if (dyn.active) return { text: 'Aktif', cls: 'dyn-param-status--on' };
        if (dyn.safety_gate && dyn.safety_gate.ok === false) {
            return { text: 'Etkin değil (güvenlik ön koşulları)', cls: 'dyn-param-status--warn' };
        }
        return { text: 'Beklemede', cls: 'dyn-param-status--warn' };
    }

    function paramRow(label, value, cls) {
        return '<div class="param-row' + (cls ? ' ' + cls : '') + '"><span class="param-label">' + esc(label) + '</span><span class="param-value">' + esc(value) + '</span></div>';
    }

    function renderGridTable(grids, side) {
        if (!Array.isArray(grids) || !grids.length) {
            return '<p class="param-hint">Bu tur için grid tanımı yok.</p>';
        }
        var isSell = side === 'sell';
        var html = '<table class="param-table"><thead><tr><th>Seviye</th><th class="num">Tetik %</th><th class="num">Miktar %</th></tr></thead><tbody>';
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

    function renderAppliedParamsBlock(applied) {
        applied = applied || {};
        var html = '<div class="param-block"><div class="param-block-title">Uygulanan parametreler (bu tur)</div>';
        html += paramRow('Satış trailing %', fmtPct(applied.sell_trigger_trailing_pct), 'param-sell');
        html += paramRow('Alış trailing %', fmtPct(applied.buy_trigger_trailing_pct), 'param-buy');
        html += paramRow('Kar satış tetik %', fmtPct(applied.profit_exit_rise_pct));
        html += paramRow('Kar satış trailing %', fmtPct(applied.profit_exit_drop_pct));
        html += paramRow('Kar alım tetik %', fmtPct(applied.profit_reentry_drop_pct));
        html += paramRow('Kar alım trailing %', fmtPct(applied.profit_reentry_rise_pct));
        html += '</div>';
        html += '<div class="param-block"><div class="param-block-title">Satış gridleri (dinamik)</div>';
        html += renderGridTable(applied.sell_grids, 'sell');
        html += '</div>';
        html += '<div class="param-block"><div class="param-block-title">Alım gridleri (dinamik)</div>';
        html += renderGridTable(applied.buy_grids, 'buy');
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
        html += renderAppliedParamsBlock(ap);
        html += '</div>';
        return html;
    }

    /** Full Dinamik tab for bot detay / leaderboard parametreler modal. opts.showBalances: bakiye satırları (leaderboard: false). */
    function renderBotDetailDynamicTab(dyn, state, symbol, cfg, opts) {
        dyn = dyn || {};
        state = state || {};
        cfg = cfg || {};
        opts = opts || {};
        var showBalances = opts.showBalances !== false;
        var status = dynamicModeStatusLabel(dyn);
        var html = '<div class="param-block dyn-param-detail-intro ' + status.cls + '">';
        html += '<div class="param-block-title">Dinamik mod</div>';
        html += paramRow('Durum', status.text);
        if (dyn.safety_gate) {
            html += paramRow('Güvenlik kapısı', dyn.safety_gate.ok ? 'Tamam' : 'Eksik / hatalı');
        }
        html += '<p class="param-hint">Parametreler her tur başında piyasa koşullarına göre hesaplanır; tur içinde sabit kalır.</p>';
        html += '</div>';

        if (!dyn.enabled) {
            html += '<p class="param-hint">Bu bot dinamik modda değil. Oluşturma anında seçilen statik parametreler geçerlidir.</p>';
            return html;
        }

        var snap = dyn.snapshot;
        if (!snap) {
            html += '<p class="param-hint">Henüz dinamik snapshot yok. Bot çalıştıkça bu sekme güncellenecek.</p>';
            return html;
        }

        var regime = REGIME_LABELS[snap.regime] || snap.regime || '—';
        html += '<div class="param-block"><div class="param-block-title">Tur özeti</div>';
        html += paramRow('Rejim', regime);
        html += paramRow('Tur no', snap.cycle_id != null ? String(snap.cycle_id) : '—');
        html += paramRow('Veri tazeliği', snap.data_fresh === false ? 'Eski (önceki tur)' : 'Güncel');
        if (snap.stale_reason) html += paramRow('Stale nedeni', snap.stale_reason);
        if (snap.built_at_ms) {
            var built = new Date(Number(snap.built_at_ms));
            html += paramRow('Snapshot zamanı', isNaN(built.getTime()) ? '—' : built.toLocaleString('tr-TR'));
        }
        html += '</div>';

        var feats = snap.features || {};
        if (Object.keys(feats).length) {
            html += '<div class="param-block"><div class="param-block-title">Piyasa sinyalleri</div>';
            if (feats.atr_pct_5m != null) html += paramRow('ATR % (5m)', fmtPct(feats.atr_pct_5m));
            if (feats.adx_1h != null) html += paramRow('ADX (1h)', fmtNumLocal(feats.adx_1h, 0));
            if (feats.bbw_1h != null) html += paramRow('BBW (1h)', fmtNumLocal(feats.bbw_1h, 1));
            if (feats.rsi_5m != null) html += paramRow('RSI (5m)', fmtNumLocal(feats.rsi_5m, 1));
            if (feats.spread_bps != null) html += paramRow('Spread (bps)', fmtNumLocal(feats.spread_bps, 1));
            html += '</div>';
        }

        var position = dyn.position || {
            base_alloc_pct: (snap.applied || {}).base_alloc_pct,
            quote_alloc_pct: (snap.applied || {}).quote_alloc_pct,
            buy_levels_fired: sumFired(state.buy_grid_fired),
            sell_levels_fired: sumFired(state.sell_grid_fired),
            max_buy_levels: cfg.max_buy_levels,
            sell_grid_count: ((snap.applied || {}).sell_grids || []).length,
            buy_grid_count: ((snap.applied || {}).buy_grids || []).length,
            initial_allocation_done: state.initial_allocation_done
        };
        html += renderPositionBlock(position, state, symbol, showBalances);
        html += renderAppliedParamsBlock(snap.applied || {});

        if (Array.isArray(snap.reasons) && snap.reasons.length) {
            html += '<div class="param-block"><div class="param-block-title">Karar gerekçeleri</div><ul class="dyn-param-list">';
            snap.reasons.forEach(function (r) { html += '<li>' + esc(r) + '</li>'; });
            html += '</ul></div>';
        }
        var applied = snap.applied || {};
        var clamps = applied.clamps || snap.clamps || [];
        if (Array.isArray(clamps) && clamps.length) {
            html += '<div class="param-block"><div class="param-block-title">Risk sınırları (clamp)</div><ul class="dyn-param-list">';
            clamps.forEach(function (r) { html += '<li>' + esc(r) + '</li>'; });
            html += '</ul></div>';
        }
        var fallbacks = applied.fallbacks || snap.fallbacks || [];
        if (Array.isArray(fallbacks) && fallbacks.length) {
            html += '<div class="param-block"><div class="param-block-title">Fallback</div><ul class="dyn-param-list">';
            fallbacks.forEach(function (r) { html += '<li>' + esc(r) + '</li>'; });
            html += '</ul></div>';
        }
        if (Array.isArray(snap.history) && snap.history.length) {
            html += '<div class="param-block"><div class="param-block-title">Son turlar</div>';
            html += '<table class="param-table"><thead><tr><th>Tur</th><th>Rejim</th><th class="num">ATR%</th></tr></thead><tbody>';
            snap.history.slice().reverse().slice(0, 10).forEach(function (h) {
                html += '<tr><td>#' + esc(h.cycle_id != null ? h.cycle_id : '—') + '</td><td>' + esc(REGIME_LABELS[h.regime] || h.regime || '—') + '</td><td class="num">' + esc(h.atr_pct_5m != null ? fmtPct(h.atr_pct_5m) : '—') + '</td></tr>';
            });
            html += '</tbody></table></div>';
        }
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
        renderBotDetailDynamicTab: renderBotDetailDynamicTab,
        renderParamModalTabsHtml: renderParamModalTabsHtml,
        bindDynModeLogoTips: bindDynModeLogoTips,
        attrEsc: attrEsc
    };
})(typeof window !== 'undefined' ? window : globalThis);
