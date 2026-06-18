/**
 * dashboard-bot-create.js
 * Bot yapıları, oluşturma sekmesi, createAndStartBot, startBotFromCreateTab,
 * openBotParameterModal.
 * dashboard.js'ten SONRA yüklenir.
 */

const BOT_STRUCTURES = [
    {
        id: 'trailing_dca',
        name: 'Trailing DCA Bot',
        description: 'Trailing stop-loss mekanizması ile çalışan DCA (Dollar Cost Averaging) botu. Fiyat hareketlerini takip ederek otomatik alım-satım işlemleri gerçekleştirir.',
        defaultConfig: {
            budget_usd: undefined,
            allocation: { base_pct: 50, quote_pct: 50 },
            up: { trail_pct: 0.30, grids: [] },
            down: { trail_pct: 0.30, grids: [] },
            profit: {
                rebuy_trigger_pct: 1.0,
                rebuy_trail_pct: 0.5,
                resell_trigger_pct: 2.0,
                resell_trail_pct: 1.0
            }
        }
    }];

/**
 * Open bot structure selection modal
 */
function openBotStructureModal() {
    const modal = document.getElementById("botStructureModal");
    const backdrop = document.getElementById("botStructureBackdrop");
    if (!modal || !backdrop) {
        console.warn("[dashboard] Bot structure modal elements not found");
        return;
    }
    
    modal.setAttribute("aria-hidden", "false");
    backdrop.setAttribute("aria-hidden", "false");
    modal.style.display = "flex";
    backdrop.style.display = "block";
    document.body.style.overflow = "hidden";
    
    // Render bot structures
    renderBotStructures();
}

/**
 * Close bot structure selection modal
 */
function closeBotStructureModal() {
    const modal = document.getElementById("botStructureModal");
    const backdrop = document.getElementById("botStructureBackdrop");
    if (!modal || !backdrop) return;
    
    modal.setAttribute("aria-hidden", "true");
    backdrop.setAttribute("aria-hidden", "true");
    modal.style.display = "none";
    backdrop.style.display = "none";
    document.body.style.overflow = "";
}

function escapeHtml(s) {
    if (s == null) return '';
    var div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
}

function formatCreateModalDecimalDisplay(value, fallback) {
    var v = value;
    if (v === undefined || v === null || v === '') v = fallback;
    var n = Number(v);
    if (!Number.isFinite(n)) return String(v || '').replace('.', ',');
    return n.toFixed(2).replace(/\.?0+$/, '').replace('.', ',');
}

function applyLeaderboardParams(structure, params, itemIndex, opts) {
    opts = opts || {};
    closeBotStructureModal();
    if (!structure) return;
    var idx = itemIndex != null && itemIndex !== '' ? parseInt(itemIndex, 10) : NaN;
    var item = Number.isFinite(idx) && State.leaderboardItems ? State.leaderboardItems[idx] : null;
    var dyn = item && typeof resolveLeaderboardItemDynamicMode === 'function'
        ? resolveLeaderboardItemDynamicMode(item)
        : (item && item.dynamic_mode);
    var normalized = normalizeLeaderboardParamsToFormConfig(resolveLeaderboardItemParams(params, itemIndex));
    if (opts.useDynamicApplied && dyn && dyn.snapshot && dyn.snapshot.applied) {
        normalized = mergeLeaderboardParamsWithApplied(normalized, dyn.snapshot.applied);
    }
    if (item && item.symbol && !normalized.symbol) normalized.symbol = item.symbol;
    var enableDynamic = opts.enableDynamicMode === true;
    var synthetic = { id: structure.id, name: structure.name || structure.id, defaultConfig: normalized, fromLeaderboardApply: true };
    currentSelectedTemplate = structure;
    fillModalWithTemplate(synthetic);
    openCreateBotModal(null, null, true, 'fBudget');
    setTimeout(function () {
        applyTrailingDcaConfigToForm(normalized, { clearBudget: true, symbolReadOnly: false });
        var dynEl = document.getElementById('fDynamicMode');
        if (dynEl) {
            dynEl.checked = enableDynamic;
            dynEl.dispatchEvent(new Event('change', { bubbles: true }));
        }
        var focusEl = document.getElementById('fBudget');
        if (focusEl) focusEl.focus();
    }, 130);
}

/**
 * Render bot structures in modal - Clean, professional design
 */
function renderBotStructures() {
    const container = document.getElementById("botStructuresList");
    if (!container) {
        console.warn("[dashboard] botStructuresList container not found");
        return;
    }
    
    container.innerHTML = "";
    
    BOT_STRUCTURES.forEach(structure => {
        if (!structure || structure.id === 'trdca_pro') return;
        const card = document.createElement("div");
        card.style.cssText = `
            background: var(--ds-bg-secondary, #1e2329);
            border: 1px solid var(--ds-border, #2b3139);
            border-radius: 8px;
            padding: 20px 24px;
            cursor: pointer;
            transition: all 0.2s ease;
            width: 100%;
            
        `;
        card.dataset.structureId = structure.id;
        card.className = "bot-structure-card";
        const btnLabel = 'Devam Et →';
        const btnDisabled = '';
        card.innerHTML = `
            <div class="bot-structure-card__inner">
                <div class="bot-structure-card__text">
<h3 style="margin: 0 0 6px 0; font-size: 1.1rem; font-weight: 600; color: var(--ds-text-primary);">${structure.name}</h3>
                    <p style="margin: 0; font-size: 0.9rem; color: var(--ds-text-secondary); line-height: 1.4;">${structure.description}</p>
                </div>
                <div style="display: flex; flex-wrap: wrap; gap: 8px; align-items: center;">
                    <button class="btn btn-primary-gold bot-structure-card__btn" style="padding: 10px 24px; font-weight: 600; white-space: nowrap;" data-action="select" data-structure-id="${structure.id}"${btnDisabled}>
                        ${btnLabel}
                    </button>
                </div>
            </div>
        `;
        
        card.onmouseenter = () => {
            card.style.borderColor = 'var(--ds-accent, #f0b90b)';
            card.style.backgroundColor = 'var(--ds-bg-hover, rgba(240, 185, 11, 0.05))';
        };
        card.onmouseleave = () => {
            card.style.borderColor = 'var(--ds-border, #2b3139)';
            card.style.backgroundColor = 'var(--ds-bg-secondary, #1e2329)';
        };

        // Select button
        const selectBtn = card.querySelector('[data-action="select"]');
        if (selectBtn) {
            selectBtn.onclick = (e) => {
                e.stopPropagation();
                selectBotStructure(structure);
            };
        }
        // Card click
        card.onclick = (e) => {
            if (!e.target.closest('button')) {
                selectBotStructure(structure);
            }
        };
        
        container.appendChild(card);
    });
}

/**
 * Select bot structure and open parameter modal
 */
function selectBotStructure(structure) {
    console.log("[dashboard] Selected bot structure:", structure.id);
    
    // Store selected structure
    currentSelectedTemplate = structure;
    
    // Close bot structure selection modal
    closeBotStructureModal();
    
    // Fill modal with structure defaults
    fillModalWithTemplate(structure);
    
    // Open parameter modal (it will use currentSelectedTemplate to set button)
    openCreateBotModal();
}

/**
 * Show DCA or Multi wizard body in create bot modal
 */
function setCreateBotModalWizard(templateId) {
    const dca = document.getElementById("dmWizardDca");
    const multi = document.getElementById("dmWizardMulti");
    const pairStrip = document.getElementById("dmSelectedPairStrip");
    const tahminStrip = document.getElementById("dmTahminStrip");
    if (dmModalMultiPreviewIntervalId) {
        clearInterval(dmModalMultiPreviewIntervalId);
        dmModalMultiPreviewIntervalId = null;
    }
    if (dca) dca.style.display = "block";
    if (multi) multi.style.display = "none";
    var assistantBtn = document.getElementById("dmParamAssistantBtn");
    if (assistantBtn) assistantBtn.style.display = "inline-flex";
    hideMultiSymbolSearchDropdown();
    if (pairStrip) pairStrip.style.display = "none";
    if (tahminStrip) tahminStrip.style.display = "none";
}

/**
 * Build multi-asset rows (symbol + target_pct)
 */
function buildMultiAssetRows(count) {
    count = Math.min(10, Math.max(2, parseInt(count, 10) || 2));
    const container = document.getElementById("multiAssetRows");
    if (!container) return;
    hideMultiSymbolSearchDropdown();
    container.innerHTML = "";
    for (let i = 0; i < count; i++) {
        const row = document.createElement("div");
        row.className = "multi-asset-row";
        row.setAttribute("data-idx", String(i));
        row.style.marginBottom = "12px";
        row.innerHTML = `
            <div class="grid-2" style="gap: 8px;">
                <div class="form-group" style="position: relative;">
                    <label>Coin ${i + 1}</label>
                    <input type="text" class="form-input multi-asset-symbol" data-idx="${i}" placeholder="Sembol" maxlength="10" style="text-transform: uppercase; width: 100%; padding: 0.6rem 1rem;" autocomplete="off" />
                </div>
                <div class="form-group">
                    <label>Hedef %</label>
                    <input type="number" class="form-input multi-asset-pct" data-idx="${i}" min="0" max="100" step="1" placeholder="" style="width: 100%; padding: 0.6rem 1rem;" />
                </div>
            </div>
            <div class="multi-asset-preview multi-asset-preview-empty" data-idx="${i}" style="margin-top: 6px; padding: 8px 12px; font-size: 0.85rem; background: var(--ds-bg-tertiary); border-radius: 8px; border: 1px solid var(--ds-border); min-height: 24px;">—</div>
        `;
        container.appendChild(row);
    }
    updateMultiPctTotal();
}

function updateMultiBudgetPlaceholder() {
    var modal = document.getElementById("dmModal");
    var wizardMulti = document.getElementById("dmWizardMulti");
    if (!modal || modal.style.display === "none" || !wizardMulti || wizardMulti.style.display !== "block") return;
    var fMultiBudget = document.getElementById("fMultiBudget");
    if (!fMultiBudget) return;
    fMultiBudget.placeholder = formatAvailableQuotePlaceholder("USDT", getAvailableQuoteInWallet("USDT"));
}

function updateMultiRebalanceModeVisibility() {
    var mode = (document.getElementById("fMultiRebalanceMode") && document.getElementById("fMultiRebalanceMode").value) || "threshold";
    var thresholdPctGroup = document.getElementById("multiThresholdPctGroup");
    var row = document.getElementById("multiIntervalCooldownRow");
    var secGroup = document.getElementById("multiIntervalSecGroup");
    var cooldownGroup = document.getElementById("multiCooldownGroup");
    var hoursGroup = document.getElementById("multiIntervalHoursGroup");
    var fMultiIntervalSec = document.getElementById("fMultiIntervalSec");
    var fMultiIntervalHours = document.getElementById("fMultiIntervalHours");
    if (thresholdPctGroup) thresholdPctGroup.style.display = mode === "interval" ? "none" : "block";
    if (!row) return;
    if (mode === "threshold") {
        row.style.display = "none";
        return;
    }
    row.style.display = "grid";
    if (secGroup) secGroup.style.display = "none";
    if (cooldownGroup) cooldownGroup.style.display = "none";
    if (hoursGroup) hoursGroup.style.display = "block";
    if (fMultiIntervalSec && fMultiIntervalHours) fMultiIntervalHours.value = Math.round(parseInt(fMultiIntervalSec.value, 10) / 3600) || 1;
}

function updateMultiPctTotal() {
    var total = 0;
    document.querySelectorAll("#multiAssetRows .multi-asset-pct").forEach(function (el) {
        total += parseFloat(el.value) || 0;
    });
    var el = document.getElementById("multiPctTotal");
    if (el) {
        el.textContent = total.toFixed(1);
        el.style.color = Math.abs(total - 100) < 0.01 ? "var(--ds-success, #0ecb81)" : "var(--ds-text-secondary)";
    }
}

/**
 * Fill modal with template default values
 */
function fillModalWithTemplate(template) {
    const config = template.defaultConfig || {};
    const fromLeaderboard = !!template.fromLeaderboardApply;
    setCreateBotModalWizard(template.id);

    if (fromLeaderboard) {
        applyTrailingDcaConfigToForm(normalizeLeaderboardParamsToFormConfig(config), { clearBudget: true, symbolReadOnly: false });
        return;
    }

    // Budget: normal şablon açılışı
    const budgetEl = document.getElementById("fBudget");
    if (budgetEl) budgetEl.value = (config.budget_usd !== undefined && config.budget_usd !== null && config.budget_usd !== '') ? config.budget_usd : '';
    
    // Allocation
    const basePctEl = document.getElementById("fBasePct");
    if (basePctEl) basePctEl.value = config.allocation?.base_pct || 50;
    
    const quotePctEl = document.getElementById("fQuotePct");
    if (quotePctEl) quotePctEl.value = config.allocation?.quote_pct || 50;
    
    // Up grid (varsayılan 0.5)
    const upTrailEl = document.getElementById("fUpTrail");
    if (upTrailEl) upTrailEl.value = formatCreateModalDecimalDisplay(config.up?.trail_pct, 0.5);
    
    // Down grid (varsayılan 0.5)
    const downTrailEl = document.getElementById("fDownTrail");
    if (downTrailEl) downTrailEl.value = formatCreateModalDecimalDisplay(config.down?.trail_pct, 0.5);
    
    // Profit config (varsayılan tetik 1.5, trail 0.5)
    const rebuyTriggerEl = document.getElementById("fRebuyTrigger");
    if (rebuyTriggerEl) rebuyTriggerEl.value = formatCreateModalDecimalDisplay(config.profit?.rebuy_trigger_pct, 1.5);
    
    const rebuyTrailEl = document.getElementById("fRebuyTrail");
    if (rebuyTrailEl) rebuyTrailEl.value = formatCreateModalDecimalDisplay(config.profit?.rebuy_trail_pct, 0.30);
    
    const resellTriggerEl = document.getElementById("fResellTrigger");
    if (resellTriggerEl) resellTriggerEl.value = formatCreateModalDecimalDisplay(config.profit?.resell_trigger_pct, 1.5);
    
    const resellTrailEl = document.getElementById("fResellTrail");
    if (resellTrailEl) resellTrailEl.value = formatCreateModalDecimalDisplay(config.profit?.resell_trail_pct, 0.5);
    
    // Reset grid counts
    const upCountEl = document.getElementById("fUpCount");
    if (upCountEl) upCountEl.value = 0;
    
    const downCountEl = document.getElementById("fDownCount");
    if (downCountEl) downCountEl.value = 0;
    
    // Clear grid rows
    const upGridRows = document.getElementById("upGridRows");
    if (upGridRows) upGridRows.innerHTML = "";
    const downGridRows = document.getElementById("downGridRows");
    if (downGridRows) downGridRows.innerHTML = "";
    
    // Clear symbol (user must enter)
    const symbolEl = document.getElementById("fSymbol");
    if (symbolEl) {
        symbolEl.value = "";
        symbolEl.readOnly = false;
    }
}

/**
 * Create bot and start it immediately
 */
async function createAndStartBot(template) {
    if (!State.accountId) {
        showError("Hesap ID bulunamadı");
        return;
    }
    
    const errorEl = document.getElementById("createBotError");
    if (errorEl) errorEl.style.display = "none";
    
    // Collect form data
    const payload = collectForm();
    const error = validateForm(payload);
    
    if (error) {
        showCreateBotFormError(errorEl, error);
        return;
    }

    const displayName = payload.symbol || "Bot";

    var requestedBudget = 0;
    var quoteAsset = "USDT";
    requestedBudget = Number(payload.budget_usd) || 0;
    try {
        var pq = parseBaseQuote(payload.symbol || "");
        quoteAsset = (pq && pq.quote) ? pq.quote : "USDT";
    } catch (e) { quoteAsset = "USDT"; }
    if (requestedBudget > 0) {
        var availableQuote = getAvailableQuoteInWallet(quoteAsset);
        if (availableQuote == null || availableQuote === undefined) {
            if (errorEl) {
                errorEl.textContent = "Bakiye bilgisi yüklenemedi. Lütfen sayfayı yenileyin veya kısa süre sonra tekrar deneyin.";
                errorEl.style.display = "block";
            }
            return;
        }
        if (!Number.isFinite(availableQuote)) availableQuote = 0;
        if (requestedBudget > availableQuote) {
            var fmt = (quoteAsset === "USDT" || quoteAsset === "BUSD" || quoteAsset === "FDUSD") && typeof fmtNum === "function" ? fmtNum(availableQuote, 2) : (availableQuote.toFixed(2));
            if (errorEl) {
                errorEl.textContent = "Bakiye yetersiz. Bot bütçesi: " + requestedBudget + " " + quoteAsset + ", kullanılabilir: " + fmt + " " + quoteAsset + ". Bütçeyi düşürün veya cüzdana bakiye ekleyin.";
                errorEl.style.display = "block";
            }
            return;
        }
    }

    try {
        // Create bot
        const body = {
            account_id: payload.account_id,
            config_json: JSON.stringify(payload)
        };
        
        const createData = await window.apiClient.post("/api/bots/create", body);
        const botId = createData.bot_id || createData.id;
        
        if (!botId) {
            throw new Error("Bot oluşturuldu ancak bot ID alınamadı");
        }
        
        var createLabel = displayName;
        if (window.Toast) {
            window.Toast.success('Bot ' + createLabel + ' oluşturuldu');
        }
        try {
            if (typeof saveLastCreateBotParams === "function") {
                saveLastCreateBotParams(State.accountId, payload);
            }
        } catch (e) {}
        
        // Start bot immediately (bots-engine inserts command for worker)
        try {
            const startResp = await window.apiClient.post(`/api/bots-engine/${botId}/start?account_id=${State.accountId}`);
            
            var startLabel = createLabel;
            if (window.Toast) {
                if (startResp && startResp.worker_alive === false) {
                    window.Toast.warning('Bot oluşturuldu ancak Engine worker çalışmıyor. Proje kökünden ./start.command çalıştırın.');
                } else {
                    window.Toast.success('Bot ' + startLabel + ' başlatıldı; ilk alım worker tarafından işlenecek.');
                }
            }
        } catch (startError) {
            console.error("[dashboard] Error starting bot:", startError);
            if (window.errorReporter) {
                window.errorReporter.report(startError, { tab: 'create', bot_id: botId, account_id: State.accountId, action: 'startBot' });
            }
            if (window.Toast) {
                window.Toast.warning(`Bot oluşturuldu ancak başlatılamadı: ${startError.message}`);
            }
        }
        
        // Close modal
        closeCreateBotModal();
        
        // Refresh bot list in Bots tab
        await loadSummary(State.accountId);
        
        // Yeni bot detayına git (eski bot ekranı / bfcache karışıklığını önler)
        var navQ = State.accountCode ? 'account_code=' + encodeURIComponent(State.accountCode) : 'account_id=' + (State.accountId || '');
        var detailPage = (payload.strategy_id === 'multi_asset_rebalance') ? '/ui/bot_multi.html' : '/ui/bot.html';
        window.location.assign(detailPage + '?bot_id=' + botId + '&' + navQ);
        return;
        
    } catch (error) {
        console.error("[dashboard] Error creating bot:", error);
        if (window.errorReporter) {
            window.errorReporter.report(error, { tab: 'create', account_id: State.accountId, action: 'createBot' });
            window.errorReporter.show(error, { tab: 'create', account_id: State.accountId });
        } else {
            const msg = error.message || "Bilinmeyen hata";
            showCreateBotFormError(errorEl, "Bot oluşturulamadı: " + msg);
        }
    }
}

/**
 * Render bot list in Create tab - Clean, professional design
 */
function renderCreateTabBotsList() {
    const container = document.getElementById("createTabBotsList");
    const emptyEl = document.getElementById("createTabBotsEmpty");
    
    if (!container) {
        console.warn("[dashboard] createTabBotsList container not found");
        return;
    }
    
    // Use State.bots if available, otherwise load
    const bots = State.bots || [];
    
    if (bots.length === 0) {
        container.style.display = "none";
        if (emptyEl) emptyEl.style.display = "block";
        return;
    }
    
    if (emptyEl) emptyEl.style.display = "none";
    container.style.display = "grid";
    container.innerHTML = "";
    
    bots.forEach(bot => {
        const botId = bot.bot_id ?? bot.id ?? 0;
        const symbol = bot.symbol || 'N/A';
        const status = (bot.status || 'stopped').toLowerCase();
        const accountId = bot.account_id || State.accountId || 0;
        
        // Status colors
        let statusColor = '#6c757d';
        let statusBg = 'rgba(108, 117, 125, 0.1)';
        if (status === 'running') {
            statusColor = '#0ecb81';
            statusBg = 'rgba(14, 203, 129, 0.1)';
        } else if (status === 'paused') {
            statusColor = '#f0b90b';
            statusBg = 'rgba(240, 185, 11, 0.1)';
        } else if (status === 'error') {
            statusColor = '#f6465d';
            statusBg = 'rgba(246, 70, 93, 0.1)';
        }
        
        // PnL
        const totalPnl = Number(bot.total_pnl_usd ?? 0);
        const pnlColor = totalPnl > 0 ? '#0ecb81' : totalPnl < 0 ? '#f6465d' : 'var(--ds-text-secondary)';
        // Card title: MULTI botlarda bot_code (#456789) göster, diğerlerinde symbol
        const cardTitle = (symbol === 'MULTI' && (bot.bot_code || botId)) ? ('#' + (bot.bot_code || botId)) : symbol;
        
        // Card - Clean, minimal design
        const card = document.createElement("div");
        card.style.cssText = `
            background: var(--ds-bg-secondary, #1e2329);
            border: 1px solid var(--ds-border, #2b3139);
            border-radius: 8px;
            padding: 20px;
            transition: all 0.2s ease;
        `;
        card.dataset.botId = botId;
        card.dataset.accountId = accountId;
        
        card.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px;">
                <div>
                    <div style="font-size: 1.25rem; font-weight: 600; color: var(--ds-text-primary); margin-bottom: 4px;">${cardTitle}</div>
                    <div style="font-size: 0.85rem; color: var(--ds-text-secondary);">Bot ID: ${botId}</div>
                </div>
                <span style="display: inline-block; padding: 4px 10px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; color: ${statusColor}; background: ${statusBg};">
                    ${(bot.status || 'STOPPED').toUpperCase()}
                </span>
            </div>
            
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; padding: 12px; background: var(--ds-bg-tertiary, #2b3139); border-radius: 6px;">
                <div>
                    <div style="font-size: 0.75rem; color: var(--ds-text-secondary); margin-bottom: 4px;">Bütçe</div>
                    <div style="font-size: 1rem; font-weight: 600; color: var(--ds-text-primary);">${fmtUsd(bot.budget_usd || bot.initial_usd || 0)}</div>
                </div>
                <div>
                    <div style="font-size: 0.75rem; color: var(--ds-text-secondary); margin-bottom: 4px;">Kazanç/Zarar</div>
                    <div style="font-size: 1rem; font-weight: 600; color: ${pnlColor};">${fmtSignedUsd(totalPnl)}</div>
                </div>
            </div>
            
            <div style="display: flex; gap: 8px; align-items: center;">
                <span style="flex: 1; font-size: 0.875rem; font-weight: 600; color: ${status === 'running' ? 'var(--ds-success, #0ecb81)' : 'var(--ds-text-secondary)'};">
                    ${status === 'running' ? '✓ Aktif' : 'Durduruldu'}
                </span>
                ${status !== 'running' ? `<a href="#" data-action="start" data-bot-id="${botId}" data-account-id="${accountId}" style="font-size: 0.8rem; color: var(--ds-accent, #f0b90b);">Yeniden başlat</a>` : ''}
                <button class="btn btn-sm" style="flex: 1; background: var(--ds-bg-tertiary, #2b3139); color: var(--ds-text-primary); font-weight: 500; padding: 8px;" data-action="edit" data-bot-id="${botId}" data-account-id="${accountId}">
                    Parametreler
                </button>
            </div>
        `;
        
        // Hover effect
        card.onmouseenter = () => {
            card.style.borderColor = 'var(--ds-accent, #f0b90b)';
            card.style.transform = 'translateY(-2px)';
        };
        card.onmouseleave = () => {
            card.style.borderColor = 'var(--ds-border, #2b3139)';
            card.style.transform = 'translateY(0)';
        };
        
        // Yeniden başlat linki (sadece durdurulmuş botlarda görünür)
        const startLink = card.querySelector('[data-action="start"]');
        if (startLink) {
            startLink.onclick = async (e) => {
                e.preventDefault();
                e.stopPropagation();
                if (status === 'running') {
                    if (window.Toast) window.Toast.info("Bot zaten çalışıyor");
                    return;
                }
                var cfg = bot.config || {};
                var dn = (bot.bot_code ? '#' + bot.bot_code : null) || (symbol === 'MULTI' ? ('#' + botId) : symbol);
                await startBotFromCreateTab(botId, accountId, symbol, dn);
            };
        }
        
        // Edit button - opens parameter modal
        const editBtn = card.querySelector('[data-action="edit"]');
        if (editBtn) {
            editBtn.onclick = async (e) => {
                e.stopPropagation();
                await openBotParameterModal(botId, accountId);
            };
        }
        
        // Card click - opens parameter modal
        card.onclick = (e) => {
            if (!e.target.closest('button')) {
                openBotParameterModal(botId, accountId);
            }
        };
        
        container.appendChild(card);
    });
}

/**
 * Start bot from Create tab
 */
async function startBotFromCreateTab(botId, accountId, symbol, displayName) {
    if (!State.accountId) {
        showError("Hesap ID bulunamadı");
        return;
    }
    var botLabel = displayName || (symbol === 'MULTI' ? ('#' + botId) : symbol) || ('#' + botId);
    try {
        // bots-engine inserts command so worker picks up the bot
        const data = await window.apiClient.post(`/api/bots-engine/${botId}/start?account_id=${accountId}`);
        
        if (window.Toast) {
            window.Toast.success('Bot ' + botLabel + ' başlatıldı');
        }
        
        // Refresh bot list
        await loadSummary(State.accountId);
        renderCreateTabBotsList();
    } catch (error) {
        console.error("[dashboard] Start bot error:", error);
        if (window.errorReporter) {
            window.errorReporter.report(error, { tab: 'create', bot_id: botId, account_id: accountId, action: 'startBot' });
            window.errorReporter.show(error, { tab: 'create', bot_id: botId, account_id: accountId });
        } else {
            const msg = error.message || "Bilinmeyen hata";
            showError(`Bot başlatılamadı: ${msg}`);
        }
    }
}

/**
 * Open bot parameter modal (loads bot config and shows in create modal)
 */
async function openBotParameterModal(botId, accountId) {
    try {
        // REFACTOR: Use apiClient to get bot detail
        // Use /bots/{bot_id}/detail endpoint which returns full bot config
        const botDetail = await window.apiClient.get(`/api/bots/${botId}/detail?account_id=${accountId}`);
        
        // Parse config from botDetail response
        // The /bots/{bot_id}/detail endpoint returns config in various formats
        let config = {};
        try {
            // Try direct config_json field
            if (botDetail.config_json) {
                config = typeof botDetail.config_json === 'string' 
                    ? JSON.parse(botDetail.config_json) 
                    : botDetail.config_json;
            } 
            // Try config field
            else if (botDetail.config) {
                config = typeof botDetail.config === 'string'
                    ? JSON.parse(botDetail.config)
                    : botDetail.config;
            }
            // Try extracting from botDetail structure (dashboard_bot_detail format)
            else if (botDetail.bot && botDetail.bot.config_json) {
                const botConfigJson = botDetail.bot.config_json;
                config = typeof botConfigJson === 'string' 
                    ? JSON.parse(botConfigJson) 
                    : botConfigJson;
            }
            // Try to reconstruct from detail fields
            else {
                // Extract from detail structure
                config = {
                    budget_usd: botDetail.budget_usd || botDetail.initial_usd || 0,
                    allocation: {
                        base_pct: botDetail.base_pct || 50,
                        quote_pct: botDetail.quote_pct || 50
                    },
                    up: {
                        trail_pct: botDetail.up_trail_pct || 0.30,
                        grids: botDetail.up_grids || []
                    },
                    down: {
                        trail_pct: botDetail.down_trail_pct || 0.30,
                        grids: botDetail.down_grids || []
                    },
                    profit: {
                        rebuy_trigger_pct: botDetail.rebuy_trigger_pct || 0,
                        rebuy_trail_pct: botDetail.rebuy_trail_pct || 0,
                        resell_trigger_pct: botDetail.resell_trigger_pct || 0,
                        resell_trail_pct: botDetail.resell_trail_pct || 0
                    }
                };
            }
        } catch (e) {
            console.warn("[dashboard] Failed to parse bot config:", e);
            // Fallback: use botDetail fields directly
            config = {
                budget_usd: botDetail.budget_usd || botDetail.initial_usd || 0,
                allocation: { base_pct: 50, quote_pct: 50 },
                up: { trail_pct: 0.30, grids: [] },
                down: { trail_pct: 0.30, grids: [] },
                profit: {}
            };
        }
        
        // Fill form with bot config
        fillCreateModalWithBotConfig(botId, accountId, botDetail, config);
        
        // Set edit mode
        createModalEditMode = { botId, accountId, isEdit: true };
        
        // Open modal
        openCreateBotModal(botId, accountId);
        
        // Show start button instead of create
        const submitBtn = document.getElementById("dmSubmitBtn");
        if (submitBtn) {
            const status = (botDetail.status || 'stopped').toLowerCase();
            if (status === 'running') {
                submitBtn.textContent = "✓ Çalışıyor";
                submitBtn.disabled = true;
                submitBtn.style.opacity = "0.6";
            } else {
                submitBtn.textContent = "Botu Başlat";
                submitBtn.disabled = false;
                submitBtn.style.opacity = "1";
                submitBtn.onclick = async () => {
                    var dn = (botDetail.bot_code ? '#' + botDetail.bot_code : null) || (botDetail.symbol === 'MULTI' ? ('#' + botId) : (botDetail.symbol || ''));
                    await startBotFromCreateTab(botId, accountId, botDetail.symbol || '', dn);
                    closeCreateBotModal();
                };
            }
        }
    } catch (error) {
        console.error("[dashboard] Load bot detail error:", error);
        if (window.errorReporter) {
            window.errorReporter.report(error, { tab: 'create', bot_id: botId, account_id: accountId, action: 'openBotParameterModal' });
            window.errorReporter.show(error, { tab: 'create', bot_id: botId, account_id: accountId });
        } else {
            showError(`Bot bilgileri yüklenemedi: ${error.message}`);
        }
    }
}

/**
 * Fill create modal with existing bot config
 */
function fillCreateModalWithBotConfig(botId, accountId, botDetail, config) {
    // Symbol
    const symbolEl = document.getElementById("fSymbol");
    if (symbolEl) {
        symbolEl.value = botDetail.symbol || '';
        symbolEl.readOnly = true; // Prevent editing symbol when viewing existing bot
    }
    
    // Budget
    const budgetEl = document.getElementById("fBudget");
    if (budgetEl) {
        const budget = config.budget_usd || botDetail.budget_usd || botDetail.initial_usd || 0;
        budgetEl.value = budget;
        budgetEl.readOnly = true; // Prevent editing budget when viewing existing bot
    }
    
    // Allocation
    const allocation = config.allocation || {};
    const basePctEl = document.getElementById("fBasePct");
    if (basePctEl) {
        basePctEl.value = allocation.base_pct || 50;
        basePctEl.readOnly = true; // Prevent editing allocation when viewing existing bot
    }
    
    const quotePctEl = document.getElementById("fQuotePct");
    if (quotePctEl) {
        quotePctEl.value = allocation.quote_pct || 50;
        quotePctEl.readOnly = true; // Prevent editing allocation when viewing existing bot
    }
    
    // Up grid
    const upCfg = config.up || {};
    const upCountEl = document.getElementById("fUpCount");
    if (upCountEl) {
        const upGrids = upCfg.grids || botDetail.up_grids || [];
        upCountEl.value = upGrids.length;
        upCountEl.readOnly = true; // Prevent editing grids when viewing existing bot
    }
    
    const upTrailEl = document.getElementById("fUpTrail");
    if (upTrailEl) {
        upTrailEl.value = formatCreateModalDecimalDisplay(upCfg.trail_pct ?? botDetail.up_trail_pct, 0.5);
        upTrailEl.readOnly = true;
    }
    
    // Down grid
    const downCfg = config.down || {};
    const downCountEl = document.getElementById("fDownCount");
    if (downCountEl) {
        const downGrids = downCfg.grids || botDetail.down_grids || [];
        downCountEl.value = downGrids.length;
        downCountEl.readOnly = true;
    }
    
    const downTrailEl = document.getElementById("fDownTrail");
    if (downTrailEl) {
        downTrailEl.value = formatCreateModalDecimalDisplay(downCfg.trail_pct ?? botDetail.down_trail_pct, 0.5);
        downTrailEl.readOnly = true;
    }
    
    // Profit config
    const profitCfg = config.profit || {};
    const rebuyTriggerEl = document.getElementById("fRebuyTrigger");
    if (rebuyTriggerEl) {
        rebuyTriggerEl.value = formatCreateModalDecimalDisplay(profitCfg.rebuy_trigger_pct ?? botDetail.rebuy_trigger_pct, 1.5);
        rebuyTriggerEl.readOnly = true;
    }
    
    const rebuyTrailEl = document.getElementById("fRebuyTrail");
    if (rebuyTrailEl) {
        rebuyTrailEl.value = formatCreateModalDecimalDisplay(profitCfg.rebuy_trail_pct ?? botDetail.rebuy_trail_pct, 0.30);
        rebuyTrailEl.readOnly = true;
    }
    
    const resellTriggerEl = document.getElementById("fResellTrigger");
    if (resellTriggerEl) {
        resellTriggerEl.value = formatCreateModalDecimalDisplay(profitCfg.resell_trigger_pct ?? botDetail.resell_trigger_pct, 1.5);
        resellTriggerEl.readOnly = true;
    }
    
    const resellTrailEl = document.getElementById("fResellTrail");
    if (resellTrailEl) {
        resellTrailEl.value = formatCreateModalDecimalDisplay(profitCfg.resell_trail_pct ?? botDetail.resell_trail_pct, 0.5);
        resellTrailEl.readOnly = true;
    }
    
    // Update modal title
    const titleEl = document.querySelector(".dm-modal__title");
    if (titleEl) {
        titleEl.textContent = `Bot Parametreleri - ${botDetail.symbol || 'N/A'}`;
    }
    
    // Strip + tahmin: parite bilgisini göster
    if (botDetail.symbol) updateCreateBotModalPairStrip(botDetail.symbol);
    
    // Show info message that this is view-only
    const errorEl = document.getElementById("createBotError");
    if (errorEl) {
        errorEl.style.display = "block";
        errorEl.style.color = "var(--ds-text-secondary)";
        errorEl.textContent = "Bu botun parametrelerini görüntülüyorsunuz. Parametreleri değiştirmek için botu durdurup yeni bot oluşturmanız gerekir.";
    }
}

// Shared password validation (settings form + must-change-password modal)
function dashboardValidatePassword(password, name, surname) {
    if (password.length < 10) return { valid: false, msg: 'Şifre en az 10 karakter olmalıdır' };
    if (!/[A-Z]/.test(password)) return { valid: false, msg: 'Şifre en az 1 büyük harf içermelidir' };
    if (!/[a-z]/.test(password)) return { valid: false, msg: 'Şifre en az 1 küçük harf içermelidir' };
    if (!/[0-9]/.test(password)) return { valid: false, msg: 'Şifre en az 1 rakam içermelidir' };
    if (!/[.,!?;:]/.test(password)) return { valid: false, msg: 'Şifre en az 1 noktalama işareti (.,!?;:) içermelidir' };
    const passLower = password.toLowerCase();
    if (name && name.toLowerCase().length >= 3 && passLower.includes(name.toLowerCase())) return { valid: false, msg: 'Şifre isminizi içeremez' };
    if (surname && surname.toLowerCase().length >= 3 && passLower.includes(surname.toLowerCase())) return { valid: false, msg: 'Şifre soyadınızı içeremez' };
    const weak = ['password', '123456', 'qwerty', 'abc123', 'password123', 'admin', 'welcome'];
    if (weak.includes(passLower)) return { valid: false, msg: 'Bu şifre çok zayıf, lütfen daha güçlü bir şifre seçin' };
    const obvious = ['12345', '23456', '34567', '45678', '56789', '67890', 'abcdef', 'qwerty', 'asdfgh', 'zxcvbn'];
    if (obvious.some(seq => passLower.includes(seq))) return { valid: false, msg: 'Şifre çok belirgin sıralı karakterler içeremez' };
    return { valid: true, msg: '✓ Şifre güçlü görünüyor' };
}

window.applyLeaderboardParams = applyLeaderboardParams;
