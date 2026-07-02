/**
 * dashboard-create-modal.js
 * openCreateBotModal, closeCreateBotModal, bindCreateBotModal,
 * sembol arama, form validasyon, createBot.
 * dashboard.js'ten SONRA yüklenir.
 */

let createModalEditMode = {
    botId: null,
    accountId: null,
    isEdit: false
};

// Track current selected template
let currentSelectedTemplate = null;

// Create modal: canlı fiyat güncellemesi
var dmModalLivePriceIntervalId = null;
var dmModalMultiPreviewIntervalId = null;
var dmModalLastPrice = null;
var dmModalLastPct = null;
var dmModalLastLogoBase = null;
var dmModalOpenTs = 0;
var dmModalLastChartSymbol = null;  // Grafik sadece sembol değişince yeniden yüklensin (flicker önleme)
var dmModalLastTahminSymbol = null;
var _dmSymbolSearchPriceGen = 0;
var _dmSymbolSearchOutsideBound = false;
var _dmSymbolSearchPicking = false;
var _dmModalStripSymbol = null;
var dmModalTahminFetchTs = 0;
var dmModalTahminHigh = null;
var dmModalTahminLow = null;
var _dmModalTickerInflightKey = '';
var _dmModalTickerInflight = null;
var _dmModalLastTickerFetchSymbol = null;
var _dmModalTickerFetchTs = 0;
var DM_MODAL_LIVE_PRICE_MS = 1500;
var DM_MODAL_TAHMIN_MIN_MS = 30000;  // Tahmin (high/low) en fazla 30s'de bir yenilensin
var AI_ASSISTANT_SPEC = window.AIAssistantSpec || {};
var DM_PARAM_ASSISTANT_TEXT_MS = (AI_ASSISTANT_SPEC.timing && AI_ASSISTANT_SPEC.timing.textMs) || 14;
var DM_PARAM_ASSISTANT_INPUT_MS = (AI_ASSISTANT_SPEC.timing && AI_ASSISTANT_SPEC.timing.inputMs) || 52;
var DM_PARAM_ASSISTANT_FIELD_PAUSE_MS = (AI_ASSISTANT_SPEC.timing && AI_ASSISTANT_SPEC.timing.fieldPauseMs) || 160;
var dmParamAssistantTimers = [];
var dmParamAssistantRecommendation = null;
var dmParamAssistantTyping = false;
var dmParamAssistantAutoScroll = true;
var dmParamAssistantLastAutoScrollAt = 0;
var dmParamAssistantHistoryCache = {};
var dmParamAssistantBackendRunSeq = 0;
var dmParamAssistantActiveBackendRun = 0;
var dmParamAssistantTierSelectSeq = 0;
var dmParamAssistantResultPresentSeq = 0;
var dmParamAssistantProgressState = null;
var dmParamAssistantProgressTickTimer = null;
var dmParamAssistantLinearProgTimer = null;
var dmParamAssistantMicroStepTimer = null;
var dmParamAssistantLiveTypeToken = 0;
var dmParamAssistantActiveJobId = '';
var dmParamAssistantLastSnapshot = null;
var dmParamAssistantLastTierStartFn = null;
var dmParamAssistantApplyTimers = [];
var dmParamAssistantApplying = false;

function dmParamAssistantIsOpen() {
    var modal = document.getElementById('dmParamAssistantModal');
    return !!(modal && modal.getAttribute('aria-hidden') === 'false');
}

function dmParamAssistantShieldParentModals(shield) {
    var dmBackdrop = document.getElementById('dmBackdrop');
    var dmModal = document.getElementById('dmModal');
    if (dmBackdrop) dmBackdrop.style.pointerEvents = shield ? 'none' : '';
    if (dmModal) dmModal.style.pointerEvents = shield ? 'none' : '';
    document.body.classList.toggle('dm-param-assistant-open', !!shield);
}

function dmParamAssistantIsBackendRunActive() {
    if (!dmParamAssistantIsOpen()) return false;
    var prep = document.getElementById('dmParamAssistantPrep');
    if (!prep || prep.style.display === 'none') return false;
    return !!prep.querySelector('.dm-pa-progress-active');
}
// P0-4: backend (param asistanı) önerisi forma uygulandıysa, oluşturma payload'una
// config_source='param_assistant' iliştirip dinamik referansı bağlamak için saklanır.
var dmParamAssistantAppliedSource = null;
var DM_PARAM_ASSISTANT_HISTORY_TTL_MS = (AI_ASSISTANT_SPEC.cache && AI_ASSISTANT_SPEC.cache.marketHistoryTtlMs) || 10 * 60 * 1000;
var DM_PARAM_ASSISTANT_RESULT_CACHE_PREFIX = 'dm_pa_backend_result_';
var DM_PARAM_ASSISTANT_RESULT_TTL_MS = (AI_ASSISTANT_SPEC.cache && AI_ASSISTANT_SPEC.cache.backendResultTtlMs) || 45 * 60 * 1000;
var DM_PARAM_ASSISTANT_HISTORY_TIMEOUT_MS = (AI_ASSISTANT_SPEC.cache && AI_ASSISTANT_SPEC.cache.marketHistoryTimeoutMs) || 9000;
var DM_PARAM_ASSISTANT_DAY_MS = 24 * 60 * 60 * 1000;
var DM_PARAM_ASSISTANT_BACKEND_START_TIMEOUT_MS = 60000;
var DM_PARAM_ASSISTANT_BACKEND_POLL_TIMEOUT_MS = 60000;

function resolveDmModalChangePct(mini) {
    var raw = (mini && mini.changePct != null) ? Number(mini.changePct) : null;
    if (raw != null && Number.isFinite(raw)) {
        var bogusZero = raw === 0 && dmModalLastPct != null && Number.isFinite(dmModalLastPct) && Math.abs(dmModalLastPct) >= 0.005;
        if (!bogusZero) return raw;
    }
    if (dmModalLastPct != null && Number.isFinite(dmModalLastPct)) return dmModalLastPct;
    return (raw != null && Number.isFinite(raw)) ? raw : null;
}

function applyDmModalPctEl(el, pct) {
    if (!el) return;
    if (pct != null && Number.isFinite(pct)) {
        var newPctStr = (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%';
        var newColor = pct >= 0 ? '#0ecb81' : '#f6465d';
        if (el.textContent !== newPctStr || el.style.color !== newColor) {
            dmModalLastPct = pct;
            el.textContent = newPctStr;
            el.style.color = newColor;
        }
        return;
    }
    if (dmModalLastPct != null && Number.isFinite(dmModalLastPct)) {
        var holdStr = (dmModalLastPct >= 0 ? '+' : '') + dmModalLastPct.toFixed(2) + '%';
        var holdColor = dmModalLastPct >= 0 ? '#0ecb81' : '#f6465d';
        if (el.textContent !== holdStr || el.style.color !== holdColor) {
            el.textContent = holdStr;
            el.style.color = holdColor;
        }
        return;
    }
    if (el.textContent !== '—') {
        el.textContent = '—';
        el.style.color = '';
    }
}
var DASHBOARD_LAST_CREATE_BOT_PARAMS_PREFIX = "dashboard_last_create_bot_params_";
/** @deprecated Yalnızca legacy taşıma — yeni yazımlar hesap suffiksli anahtar kullanır */
var DASHBOARD_LAST_CREATE_BOT_PARAMS = "dashboard_last_create_bot_params";

function createBotParamsStorageKey(accountId, symbol) {
    var base = DASHBOARD_LAST_CREATE_BOT_PARAMS_PREFIX + String(accountId || "");
    var sym = symbol ? String(symbol).trim().toUpperCase() : "";
    return sym ? (base + "_" + sym) : base;
}

function createBotParamScreenStorageKey(accountId) {
    return "createBotParamScreen_" + String(accountId || "");
}

function loadLastCreateBotParams(accountId, symbol) {
    if (accountId == null || accountId === "") return null;
    var sym = symbol ? String(symbol).trim().toUpperCase() : "";
    var keys = [];
    if (sym) keys.push(createBotParamsStorageKey(accountId, sym));
    keys.push(createBotParamsStorageKey(accountId));
    try {
        for (var ki = 0; ki < keys.length; ki++) {
            var raw = localStorage.getItem(keys[ki]);
            if (!raw && ki === keys.length - 1) {
                var legacy = localStorage.getItem(DASHBOARD_LAST_CREATE_BOT_PARAMS);
                if (legacy) {
                    var legacyObj = JSON.parse(legacy);
                    if (legacyObj && Number(legacyObj.account_id) === Number(accountId)) {
                        localStorage.setItem(keys[ki], legacy);
                        localStorage.removeItem(DASHBOARD_LAST_CREATE_BOT_PARAMS);
                        raw = legacy;
                    }
                }
            }
            if (!raw) continue;
            var p = JSON.parse(raw);
            if (!p || typeof p !== "object") continue;
            if (p.account_id != null && Number(p.account_id) !== Number(accountId)) continue;
            var cacheSym = String(p.symbol || "").trim().toUpperCase();
            if (sym && cacheSym && sym !== cacheSym) continue;
            return p;
        }
        return null;
    } catch (e) {
        return null;
    }
}

function saveLastCreateBotParams(accountId, payload) {
    if (accountId == null || accountId === "" || !payload || typeof payload !== "object") return;
    try {
        var sym = String(payload.symbol || "").trim().toUpperCase();
        var body = Object.assign({}, payload, { account_id: Number(accountId) });
        var key = createBotParamsStorageKey(accountId, sym || null);
        localStorage.setItem(key, JSON.stringify(body));
    } catch (e) { /* ignore */ }
}

window.loadLastCreateBotParams = loadLastCreateBotParams;
window.saveLastCreateBotParams = saveLastCreateBotParams;
window.createBotParamScreenStorageKey = createBotParamScreenStorageKey;

function dmParamAssistantResultCacheKey(accountId, symbol, budget) {
    var sym = dmParamAssistantNormalizeSymbol(symbol);
    var b = Number(budget);
    var bKey = Number.isFinite(b) ? b.toFixed(2) : '0';
    return DM_PARAM_ASSISTANT_RESULT_CACHE_PREFIX + String(accountId || '') + '_' + sym + '_' + bKey;
}

function saveParamAssistantBackendResult(accountId, snapshot, result) {
    if (!accountId || !result || !snapshot) return;
    try {
        if (!dmParamAssistantResultIsFresh(snapshot, result)) return;
        var key = dmParamAssistantResultCacheKey(
            accountId,
            snapshot.symbol,
            dmParamAssistantResolveBudget(snapshot)
        );
        localStorage.setItem(key, JSON.stringify({
            ts: Date.now(),
            symbol: dmParamAssistantNormalizeSymbol(snapshot.symbol),
            budget: dmParamAssistantResolveBudget(snapshot),
            result: result
        }));
    } catch (e) { /* ignore quota */ }
}

function loadParamAssistantBackendResult(accountId, snapshot) {
    if (!accountId || !snapshot || !snapshot.symbol) return null;
    try {
        var key = dmParamAssistantResultCacheKey(
            accountId,
            snapshot.symbol,
            dmParamAssistantResolveBudget(snapshot)
        );
        var raw = localStorage.getItem(key);
        if (!raw) return null;
        var parsed = JSON.parse(raw);
        if (!parsed || !parsed.result || !parsed.ts) return null;
        if (Date.now() - Number(parsed.ts) > DM_PARAM_ASSISTANT_RESULT_TTL_MS) {
            localStorage.removeItem(key);
            return null;
        }
        if (!dmParamAssistantResultIsFresh(snapshot, parsed.result)) return null;
        return parsed.result;
    } catch (e) {
        return null;
    }
}

window.saveParamAssistantBackendResult = saveParamAssistantBackendResult;
window.loadParamAssistantBackendResult = loadParamAssistantBackendResult;

function clearParamAssistantBackendCache(accountId, snapshot) {
    if (!accountId) return;
    try {
        if (snapshot && snapshot.symbol) {
            localStorage.removeItem(dmParamAssistantResultCacheKey(
                accountId,
                snapshot.symbol,
                dmParamAssistantResolveBudget(snapshot)
            ));
            return;
        }
        var prefix = DM_PARAM_ASSISTANT_RESULT_CACHE_PREFIX + String(accountId || '') + '_';
        for (var i = localStorage.length - 1; i >= 0; i--) {
            var k = localStorage.key(i);
            if (k && k.indexOf(prefix) === 0) localStorage.removeItem(k);
        }
    } catch (e) { /* ignore */ }
}

/** Param asistanı oturumunu sıfırla — modal kapanınca veya parametre uygulanınca. */
function resetParamAssistantSession(opts) {
    opts = opts || {};
    dmParamAssistantClearTimers();
    dmParamAssistantStopTimeProgress();
    dmParamAssistantClearPrep();
    if (!opts.keepApplyTimers) dmParamAssistantClearApplyTimers();

    dmParamAssistantActiveBackendRun = ++dmParamAssistantBackendRunSeq;
    dmParamAssistantTierSelectSeq++;
    dmParamAssistantResultPresentSeq++;
    dmParamAssistantProgressState = null;
    dmParamAssistantTyping = false;
    dmParamAssistantActiveJobId = '';
    dmParamAssistantRecommendation = null;
    dmParamAssistantLastSnapshot = null;
    dmParamAssistantLastTierStartFn = null;
    dmParamAssistantSetCursorVisible(false);
    dmParamAssistantAutoScroll = true;
    dmParamAssistantLastAutoScrollAt = 0;
    dmParamAssistantHistoryCache = {};

    if (!opts.keepAppliedSource) {
        dmParamAssistantAppliedSource = null;
    }

    if (opts.clearCache !== false) {
        var snap = opts.snapshot || (typeof dmParamAssistantCurrentSnapshot === 'function'
            ? dmParamAssistantCurrentSnapshot()
            : null);
        if (State.accountId) clearParamAssistantBackendCache(State.accountId, snap);
    }

    dmParamAssistantClearResultPanels();
    var output = document.getElementById('dmParamAssistantOutput');
    var status = document.getElementById('dmParamAssistantStatus');
    var choice = document.getElementById('dmParamAssistantChoice');
    var chips = document.getElementById('dmParamAssistantChips');
    if (output) {
        output.innerHTML = '';
        output.classList.add('is-visible');
    }
    if (status) {
        status.textContent = (AI_ASSISTANT_SPEC.modal && AI_ASSISTANT_SPEC.modal.initialStatus) || '';
    }
    if (choice) choice.style.display = 'none';
    if (chips) chips.innerHTML = '';
    var assistantBody = document.querySelector('#dmParamAssistantModal .dm-param-assistant-body');
    if (assistantBody) assistantBody.scrollTop = 0;
}

window.resetParamAssistantSession = resetParamAssistantSession;

/** Param asistanı / sembol değişiminde çapraz parite state sızıntısını kes. */
function resetParamAssistantSymbolIsolation(prevSym, newSym) {
    var n = String(newSym || "").trim().toUpperCase();
    var p = String(prevSym || "").trim().toUpperCase();
    if (!n || n === p) return;
    if (State.accountId) {
        if (p) clearParamAssistantBackendCache(State.accountId, { symbol: p });
        clearParamAssistantBackendCache(State.accountId, { symbol: n });
    }
    if (p) delete dmParamAssistantHistoryCache[p];
    delete dmParamAssistantHistoryCache[n];
    if (dmParamAssistantAppliedSource) {
        var srcSym = String(dmParamAssistantAppliedSource.symbol || "").trim().toUpperCase();
        if (!srcSym || srcSym !== n) dmParamAssistantAppliedSource = null;
    }
    if (dmParamAssistantRecommendation) {
        var recSym = String(dmParamAssistantRecommendation.symbol || "").trim().toUpperCase();
        if (!recSym || recSym !== n) dmParamAssistantRecommendation = null;
    }
    if (dmParamAssistantIsOpen()) {
        resetParamAssistantSession({ keepAppliedSource: true, clearCache: false });
    }
}

/** Son oluşturulan bot parametrelerini forma uygula — yalnızca aynı parite + hesap. */
function applyLastCreateParamsToForm() {
    try {
        var accountId = State.accountId;
        if (!accountId) return;
        var symEl = document.getElementById("fSymbol");
        var curSym = symEl ? String(symEl.value || "").trim().toUpperCase() : "";
        // Sembol seçilmeden önceki bot parametrelerini asla taşıma (BTC→XLM grid kopyası).
        if (!curSym) return;
        var p = loadLastCreateBotParams(accountId, curSym);
        if (!p) return;
        var cacheSym = String(p.symbol || "").trim().toUpperCase();
        if (!cacheSym || curSym !== cacheSym) return;
        var budgetEl = document.getElementById("fBudget");
        var basePctEl = document.getElementById("fBasePct");
        var quotePctEl = document.getElementById("fQuotePct");
        if (symEl && p.symbol) {
            symEl.readOnly = false;
        }
        if (budgetEl && (p.budget_usd != null || p.initial_capital_usdt != null)) budgetEl.value = p.budget_usd != null ? p.budget_usd : p.initial_capital_usdt;
        var alloc = p.allocation || {};
        if (basePctEl && (alloc.base_pct != null || alloc.base_pct === 0)) {
            var upG = (p.up && p.up.grids) || [];
            var downG = (p.down && p.down.grids) || [];
            var normAlloc = resolveCreateFormAllocation(alloc.base_pct, alloc.quote_pct, {
                hasBuyGrids: downG.length > 0,
                hasSellGrids: upG.length > 0
            });
            basePctEl.value = normAlloc.basePct;
            if (quotePctEl) quotePctEl.value = normAlloc.quotePct;
        }
        var up = p.up || {};
        var down = p.down || {};
        var profit = p.profit || {};
        var upCountEl = document.getElementById("fUpCount");
        var downCountEl = document.getElementById("fDownCount");
        var upGrids = up.grids || [];
        var downGrids = down.grids || [];
        if (upCountEl && upGrids.length > 0) { upCountEl.value = upGrids.length; buildGridRows("upGridRows", upGrids.length, "up", upGrids); }
        if (downCountEl && downGrids.length > 0) { downCountEl.value = downGrids.length; buildGridRows("downGridRows", downGrids.length, "down", downGrids); }
        var upTrailEl = document.getElementById("fUpTrail");
        var downTrailEl = document.getElementById("fDownTrail");
        var maxBuyEl = document.getElementById("fMaxBuyLevels");
        if (upTrailEl && (up.trail_pct != null || up.trail_pct === 0)) upTrailEl.value = dmParamAssistantInputTextTr(up.trail_pct, 2);
        if (downTrailEl && (down.trail_pct != null || down.trail_pct === 0)) downTrailEl.value = dmParamAssistantInputTextTr(down.trail_pct, 2);
        if (maxBuyEl) maxBuyEl.value = p.max_buy_levels || Math.max(1, downGrids.length || 1);
        for (var i = 0; i < upGrids.length; i++) {
            var tEl = document.getElementById("upGrid_" + i + "_trigger");
            var qEl = document.getElementById("upGrid_" + i + "_qty");
            if (tEl && upGrids[i].trigger_pct != null) tEl.value = dmParamAssistantInputTextTr(upGrids[i].trigger_pct, 2);
            if (qEl && upGrids[i].qty_pct != null) qEl.value = dmParamAssistantInputTextTr(upGrids[i].qty_pct, 1);
        }
        if (upGrids.length > 0) _updateGridQtySum("upGridRows", "up");
        for (var j = 0; j < downGrids.length; j++) {
            var t2 = document.getElementById("downGrid_" + j + "_trigger");
            var q2 = document.getElementById("downGrid_" + j + "_qty");
            if (t2 && downGrids[j].trigger_pct != null) t2.value = dmParamAssistantInputTextTr(downGrids[j].trigger_pct, 2);
            if (q2 && downGrids[j].qty_pct != null) q2.value = dmParamAssistantInputTextTr(downGrids[j].qty_pct, 1);
        }
        if (downGrids.length > 0) _updateGridQtySum("downGridRows", "down");
        var rebuyT = document.getElementById("fRebuyTrigger");
        var rebuyTrail = document.getElementById("fRebuyTrail");
        var resellT = document.getElementById("fResellTrigger");
        var resellTrail = document.getElementById("fResellTrail");
        if (rebuyT && (profit.rebuy_trigger_pct != null || profit.rebuy_trigger_pct === 0)) rebuyT.value = dmParamAssistantInputTextTr(profit.rebuy_trigger_pct, 2);
        if (rebuyTrail && profit.rebuy_trail_pct != null) rebuyTrail.value = dmParamAssistantInputTextTr(profit.rebuy_trail_pct, 2);
        if (resellT && (profit.resell_trigger_pct != null || profit.resell_trigger_pct === 0)) resellT.value = dmParamAssistantInputTextTr(profit.resell_trigger_pct, 2);
        if (resellTrail && profit.resell_trail_pct != null) resellTrail.value = dmParamAssistantInputTextTr(profit.resell_trail_pct, 2);
        // Dynamic Mode bayrağını restore et (önceki bottan hatırlat)
        var dynEl = document.getElementById("fDynamicMode");
        if (dynEl) {
            dynEl.checked = !!p.dynamic_mode;
            try { dynEl.dispatchEvent(new Event("change")); } catch (e) {}
        }
        if (p.symbol && typeof updateCreateBotModalPairStrip === "function") updateCreateBotModalPairStrip(p.symbol);
    } catch (e) { console.debug("applyLastCreateParamsToForm", e); }
}

function openCreateBotModal(botId = null, accountId = null, skipLastCreateParams = false, focusFieldId = null) {
    const modal = document.getElementById("dmModal");
    const backdrop = document.getElementById("dmBackdrop");
    if (!modal || !backdrop) return;
    try {
        var templateId = (currentSelectedTemplate && currentSelectedTemplate.id) ? currentSelectedTemplate.id : "trailing_dca";
        if (State.accountId) {
            sessionStorage.setItem(createBotParamScreenStorageKey(State.accountId), templateId);
        }
    } catch (e) {}
    // Strip ve tahmin: sembol seçilene kadar gizli (leaderboard Uygula ile sembol doluysa göster)
    const strip = document.getElementById("dmSelectedPairStrip");
    const tahminStrip = document.getElementById("dmTahminStrip");
    var prefillSymbol = (document.getElementById("fSymbol") || {}).value || "";
    if (skipLastCreateParams && prefillSymbol.trim() && typeof updateCreateBotModalPairStrip === "function") {
        updateCreateBotModalPairStrip(prefillSymbol.trim());
    } else {
        if (strip) strip.style.display = "none";
        if (tahminStrip) tahminStrip.style.display = "none";
    }
    hideCreateModalSymbolDropdown();
    ensureCoinListSearchSymbolsLoaded("all").then(function () { buildCoinListSearchSymbols(); });
    var fBudgetReset = document.getElementById("fBudget");
    if (fBudgetReset) fBudgetReset.placeholder = "Kullanılabilir: —";
    if (State.accountId && typeof pollWallet === "function" && (!assetsState.wallet.assets || !assetsState.wallet.assets.length)) pollWallet(true);
    
    // Reset edit mode if opening for new bot
    if (!botId) {
        createModalEditMode = { botId: null, accountId: null, isEdit: false };
    }
    setCreateBotModalWizard(currentSelectedTemplate ? currentSelectedTemplate.id : "trailing_dca");
    
    modal.setAttribute("aria-hidden", "false");
    backdrop.setAttribute("aria-hidden", "false");
    modal.style.display = "flex";
    backdrop.style.display = "block";
    document.body.style.overflow = "hidden";

    dmModalLastPrice = null;
    dmModalLastPct = null;
    dmModalOpenTs = Date.now();
    var priceEl = document.getElementById("dmPairPrice");
    var changeEl = document.getElementById("dmPairChangePct");
    if (priceEl) priceEl.classList.remove("blink-positive", "blink-negative");
    if (changeEl) changeEl.classList.remove("blink-positive", "blink-negative");

    // Oluştur = her zaman oluştur + anında başlat (parametreleri girip Oluştur dediğiniz an bot çalışır)
    const submitBtn = document.getElementById("dmSubmitBtn");
    if (submitBtn) {
        submitBtn.textContent = "Oluştur";
        submitBtn.classList.remove("dm-ai-create-pulse");
        submitBtn.removeAttribute("data-ai-ready");
        submitBtn.onclick = async () => {
            await createAndStartBot(currentSelectedTemplate || null);
        };
    }
    if (typeof dmParamAssistantClearAiInputStyles === 'function') dmParamAssistantClearAiInputStyles();
    
    // Reset modal title
    const titleEl = document.querySelector(".dm-modal__title");
    if (titleEl && !botId) {
        titleEl.textContent = currentSelectedTemplate ? `Bot Oluştur - ${currentSelectedTemplate.name}` : "Bot Oluştur";
    }
    
    if (focusFieldId) {
        setTimeout(function () {
            var focusEl = document.getElementById(focusFieldId);
            if (focusEl) focusEl.focus();
        }, 120);
    } else {
        const firstInput = modal.querySelector("input, select, textarea");
        if (firstInput) setTimeout(() => firstInput.focus(), 100);
    }
    if (!botId && !skipLastCreateParams && typeof applyLastCreateParamsToForm === "function") setTimeout(applyLastCreateParamsToForm, 80);
}

function closeCreateBotModal() {
    const modal = document.getElementById("dmModal");
    const backdrop = document.getElementById("dmBackdrop");
    if (!modal || !backdrop) return;
    closeParamAssistantModal({ immediate: true });
    dmParamAssistantClearApplyTimers();
    hideMultiSymbolSearchDropdown();
    modal.setAttribute("aria-hidden", "true");
    backdrop.setAttribute("aria-hidden", "true");
    modal.style.display = "none";
    backdrop.style.display = "none";
    document.body.style.overflow = "";
    
    // Reset edit mode
    createModalEditMode = { botId: null, accountId: null, isEdit: false };
    currentSelectedTemplate = null; // Reset template selection
    try {
        if (State.accountId) sessionStorage.removeItem(createBotParamScreenStorageKey(State.accountId));
        sessionStorage.removeItem("createBotParamScreen");
    } catch (e) {}
    // Reset submit button (Oluştur = her zaman oluştur + başlat)
    const submitBtn = document.getElementById("dmSubmitBtn");
    if (submitBtn) {
        submitBtn.textContent = "Oluştur";
        submitBtn.disabled = false;
        submitBtn.style.opacity = "1";
        submitBtn.classList.remove("dm-ai-create-pulse");
        submitBtn.removeAttribute("data-ai-ready");
        submitBtn.onclick = async () => { await createAndStartBot(currentSelectedTemplate || null); };
    }
    
    // Reset modal title
    const titleEl = document.querySelector(".dm-modal__title");
    if (titleEl) {
        titleEl.textContent = "Bot Oluştur";
    }
    
    // Clear form and reset readonly states (varsayılan: trail 0.5, tetik 1.5)
    modal.querySelectorAll("input").forEach(input => {
        input.readOnly = false; // Reset readonly state
        if (input.id === "fBasePct") input.value = "50";
        else if (input.id === "fQuotePct") input.value = "50";
        else if (input.id === "fUpCount" || input.id === "fDownCount") input.value = "0";
        else if (input.id === "fMaxBuyLevels") input.value = "1";
        else if (input.id === "fUpTrail" || input.id === "fDownTrail" || input.id === "fResellTrail") input.value = "0,5";
        else if (input.id === "fRebuyTrigger" || input.id === "fResellTrigger") input.value = "1,5";
        else if (input.id === "fRebuyTrail") input.value = "0,30";
        else input.value = "";
    });
    
    // Clear error message
    const errorEl = document.getElementById("createBotError");
    if (errorEl) {
        errorEl.style.display = "none";
        errorEl.textContent = "";
    }
    
    // Clear grid rows
    const upGridRows = document.getElementById("upGridRows");
    if (upGridRows) upGridRows.innerHTML = "";
    const downGridRows = document.getElementById("downGridRows");
    if (downGridRows) downGridRows.innerHTML = "";
    
    const strip = document.getElementById("dmSelectedPairStrip");
    const tahminStrip = document.getElementById("dmTahminStrip");
    if (strip) strip.style.display = "none";
    if (tahminStrip) tahminStrip.style.display = "none";
    hideCreateModalSymbolDropdown();
    _dmModalStripSymbol = null;
    dmModalLastChartSymbol = null;
    dmModalLastTahminSymbol = null;
    dmModalTahminHigh = null;
    dmModalTahminLow = null;
    _dmModalTickerInflightKey = '';
    _dmModalTickerInflight = null;
    _dmModalLastTickerFetchSymbol = null;
    _dmModalTickerFetchTs = 0;
    if (dmModalLivePriceIntervalId) {
        clearInterval(dmModalLivePriceIntervalId);
        dmModalLivePriceIntervalId = null;
    }
    if (dmModalMultiPreviewIntervalId) {
        clearInterval(dmModalMultiPreviewIntervalId);
        dmModalMultiPreviewIntervalId = null;
    }
    dmModalLastPrice = null;
    dmModalLastPct = null;
    dmModalLastLogoBase = null;
}

function bindCreateBotModal() {
    // Open triggers - "Bot Oluştur" buttons should open bot structure selection modal first
    document.querySelectorAll('[onclick*="openCreateBotModal"]').forEach(btn => {
        btn.onclick = () => openBotStructureModal();
    });
    
    // Close triggers for parameter modal
    document.getElementById("dmCloseBtn")?.addEventListener("click", closeCreateBotModal);
    document.getElementById("dmCancelBtn")?.addEventListener("click", closeCreateBotModal);
    document.getElementById("dmBackdrop")?.addEventListener("click", (e) => {
        if (e.target.id !== "dmBackdrop") return;
        if (dmParamAssistantIsOpen()) return;
        closeCreateBotModal();
    });
    
    // Close triggers for bot structure modal
    document.getElementById("botStructureCloseBtn")?.addEventListener("click", closeBotStructureModal);
    document.getElementById("botStructureBackdrop")?.addEventListener("click", (e) => {
        if (e.target.id === "botStructureBackdrop") closeBotStructureModal();
    });

    document.getElementById("dmParamAssistantBtn")?.addEventListener("click", openParamAssistantModal);
    document.getElementById("dmParamAssistantCloseBtn")?.addEventListener("click", function () {
        if (dmParamAssistantIsBackendRunActive()) {
            if (!window.confirm('Parametre analizi devam ediyor. Kapatmak istediğine emin misin?')) return;
        }
        closeParamAssistantModal();
    });
    document.getElementById("dmParamAssistantUseBtn")?.addEventListener("click", acceptParamAssistantRecommendation);
    document.getElementById("dmParamAssistantBackdrop")?.addEventListener("click", function (e) {
        if (e.target.id === "dmParamAssistantBackdrop") e.preventDefault();
    });
    document.getElementById("dmParamAssistantModal")?.addEventListener("click", function (e) {
        if (e.target.id === "dmParamAssistantModal") {
            e.preventDefault();
            e.stopPropagation();
        }
    });
    
    // Ondalık alanlarda type=number kalmışsa virgülü noktaya çevir; text alanlarında virgül görünümü korunur.
    ["fUpTrail", "fDownTrail", "fRebuyTrigger", "fRebuyTrail", "fResellTrigger", "fResellTrail"].forEach(function (id) {
        var el = document.getElementById(id);
        if (el) el.addEventListener("input", function () {
            var v = this.value;
            if (this.type === "number" && v && v.indexOf(",") !== -1) this.value = v.replace(",", ".");
        });
    });

    // Bot oluşturma modalı: number input üzerinde scroll → değer değişmesin, modal kaydırılsın.
    (function normalizeWheelOnNumberInputs() {
        var modal = document.getElementById("dmModal");
        if (!modal) return;
        modal.addEventListener("wheel", function (e) {
            var t = e.target;
            if (t && t.tagName === "INPUT" && t.type === "number" && document.activeElement === t) {
                t.blur();
            }
        }, { passive: true });
    })();

    // ---------------- Dynamic Mode toggle (bot oluşturma ekranı) ----------------
    // Tek ON/OFF butonu. Açıkken ek parametre istenmez; submit'te yalnız
    // dynamic_mode=true gönderilir.
    // NOT: <label> içindeki gizli checkbox tıklanınca zaten otomatik toggle
    // olur; ayrı bir click handler EKLEMEYIZ (aksi halde çift toggle = no-op).
    (function bindDynamicModeToggle() {
        var inputEl = document.getElementById("fDynamicMode");
        if (!inputEl) return;
        function applyVisual(on) {
            var swEl = document.getElementById("dmDynModeSwitch");
            if (swEl) swEl.style.background = on ? "#4caf50" : "#555";
            var knob = document.getElementById("dmDynModeKnob");
            if (knob) knob.style.left = on ? "22px" : "2px";
            var badge = document.getElementById("dmDynModeBadge");
            if (badge) {
                badge.textContent = on ? "AÇIK" : "KAPALI";
                badge.style.background = on ? "#4caf50" : "#444";
            }
            var hint = document.getElementById("dmDynModeHint");
            if (hint) hint.style.display = on ? "block" : "none";
        }
        inputEl.addEventListener("change", function () { applyVisual(!!inputEl.checked); });
        // Modal her açıldığında bayrağı görsel olarak senkronla
        applyVisual(!!inputEl.checked);
    })();

    // ESC key - close active modal
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
            const structureModal = document.getElementById("botStructureModal");
            const paramModal = document.getElementById("dmModal");
            const assistantModal = document.getElementById("dmParamAssistantModal");
            if (assistantModal && assistantModal.getAttribute("aria-hidden") === "false") {
                if (dmParamAssistantIsBackendRunActive()) {
                    if (!window.confirm('Parametre analizi devam ediyor. Kapatmak istediğine emin misin?')) {
                        e.preventDefault();
                        return;
                    }
                }
                closeParamAssistantModal();
                e.preventDefault();
                return;
            } else if (structureModal && structureModal.getAttribute("aria-hidden") === "false") {
                closeBotStructureModal();
            } else if (paramModal && paramModal.getAttribute("aria-hidden") === "false") {
                closeCreateBotModal();
            }
        }
    });
    
    // Parite strip: grafik alanına tıklanınca detay grafik sayfası
    const dmPairChartWrap = document.getElementById("dmPairChartWrap");
    if (dmPairChartWrap) {
        dmPairChartWrap.addEventListener("click", function () {
            const sym = normalizeSymbol(document.getElementById("fSymbol").value);
            if (sym) window.location.href = "/ui/chart.html?symbol=" + encodeURIComponent(sym) + "&from=botcreate";
        });
    }
    
    // fSymbol: yazarken arama dropdown, seçince strip + tahmin güncelle
    bindDmSymbolSearchOutsideClose();
    const fSymbol = document.getElementById("fSymbol");
    const dmSymbolSearchDropdown = document.getElementById("dmSymbolSearchDropdown");
    if (fSymbol) {
        let dmSymbolInputDebounce = null;
        var symWrap = fSymbol.closest(".coin-list-search-wrap");
        if (symWrap) {
            symWrap.addEventListener("pointerdown", function (e) {
                if (e.target.closest("#dmSymbolSearchDropdown")) return;
                if (document.activeElement !== fSymbol) {
                    fSymbol.focus({ preventScroll: true });
                }
            });
        }
        fSymbol.addEventListener("focus", function () {
            var v = (fSymbol.value || "").trim();
            if (coinListSearchAllSymbols.length > 0) {
                if (v.length >= 2) showCreateModalSymbolDropdown(v);
                else showCreateModalSymbolDropdownSuggestions();
            }
            ensureCoinListSearchSymbolsLoaded("all").then(function () {
                buildCoinListSearchSymbols();
                if (document.activeElement !== fSymbol) return;
                var v2 = (fSymbol.value || "").trim();
                if (v2.length >= 2) showCreateModalSymbolDropdown(v2);
                else showCreateModalSymbolDropdownSuggestions();
            });
        });
        fSymbol.addEventListener("input", function () {
            const v = (fSymbol.value || "").trim();
            clearTimeout(dmSymbolInputDebounce);
            if (v.length >= 2) {
                if (coinListSearchAllSymbols.length > 0) showCreateModalSymbolDropdown(v);
                dmSymbolInputDebounce = setTimeout(function () {
                    ensureCoinListSearchSymbolsLoaded("all").then(function () {
                        buildCoinListSearchSymbols();
                        if (document.activeElement !== fSymbol) return;
                        showCreateModalSymbolDropdown((fSymbol.value || "").trim());
                    });
                }, 100);
            } else if (v.length === 1) {
                if (coinListSearchAllSymbols.length > 0) showCreateModalSymbolDropdown(v, 1);
                dmSymbolInputDebounce = setTimeout(function () {
                    ensureCoinListSearchSymbolsLoaded("all").then(function () {
                        buildCoinListSearchSymbols();
                        if (document.activeElement !== fSymbol) return;
                        showCreateModalSymbolDropdown((fSymbol.value || "").trim(), 1);
                    });
                }, 80);
            } else {
                hideCreateModalSymbolDropdown();
                if (v.length === 0) {
                    const strip = document.getElementById("dmSelectedPairStrip");
                    const tahminStrip = document.getElementById("dmTahminStrip");
                    if (strip) strip.style.display = "none";
                    if (tahminStrip) tahminStrip.style.display = "none";
                    _dmModalStripSymbol = null;
                }
            }
        });
        fSymbol.addEventListener("blur", function () {
            setTimeout(function () {
                if (_dmSymbolSearchPicking) {
                    _dmSymbolSearchPicking = false;
                    return;
                }
                hideCreateModalSymbolDropdown();
            }, 160);
        });
        // Enter: parite onayla → strip ve tahmin göster (dropdown açıksa ilk sonucu seç, yoksa yazılanı normalize et)
        fSymbol.addEventListener("keydown", function (e) {
            if (e.key === "Escape") {
                hideCreateModalSymbolDropdown();
                return;
            }
            if (e.key !== "Enter") return;
            const dropdown = document.getElementById("dmSymbolSearchDropdown");
            const firstItem = dropdown && dropdown.querySelector(".dm-symbol-search-item, .coin-list-search-item");
            if (firstItem && dropdown.style.display !== "none") {
                const symbol = firstItem.getAttribute("data-symbol");
                if (symbol) {
                    fSymbol.value = symbol;
                    hideCreateModalSymbolDropdown();
                    updateCreateBotModalPairStrip(symbol);
                    e.preventDefault();
                }
            } else {
                const v = (fSymbol.value || "").trim();
                if (v.length >= 2) {
                    const norm = normalizeModalSymbol(v);
                    if (!norm.invalid && norm.normalized) {
                        updateCreateBotModalPairStrip(norm.normalized);
                        e.preventDefault();
                    }
                }
            }
        });
    }
    if (dmSymbolSearchDropdown) {
        dmSymbolSearchDropdown.addEventListener("mousedown", function (e) {
            var item = e.target.closest(".dm-symbol-search-item, .coin-list-search-item");
            if (!item) return;
            e.preventDefault();
            _dmSymbolSearchPicking = true;
            var symbol = item.getAttribute("data-symbol");
            if (symbol) fetchCreateBotModalTicker24h(symbol, { force: true });
            if (symbol && fSymbol) {
                fSymbol.value = symbol;
                hideCreateModalSymbolDropdown();
                updateCreateBotModalPairStrip(symbol);
            }
        });
    }
    
    // Base/Quote sync — PA forma yazarken ara input olayları quote'u bozmasın
    const fBasePct = document.getElementById("fBasePct");
    const fQuotePct = document.getElementById("fQuotePct");
    if (fBasePct && fQuotePct) {
        fBasePct.addEventListener("input", () => {
            if (dmParamAssistantApplying) return;
            syncQuotePctFromBaseInput();
        });
    }
    
    // Grid rows builders (max 15 her yön)
    document.getElementById("fUpCount")?.addEventListener("input", (e) => {
        var v = Math.min(15, Math.max(0, parseInt(e.target.value) || 0));
        e.target.value = v;
        buildGridRows("upGridRows", v, "up");
    });
    document.getElementById("fDownCount")?.addEventListener("input", (e) => {
        var count = Math.min(15, Math.max(0, parseInt(e.target.value) || 0));
        e.target.value = count;
        buildGridRows("downGridRows", count, "down");
        syncMaxBuyLevelsWithDownCount(count);
    });
    document.getElementById("fMultiCoinCount")?.addEventListener("input", (e) => {
        buildMultiAssetRows(parseInt(e.target.value, 10) || 2);
    });
    document.getElementById("fMultiRebalanceMode")?.addEventListener("change", updateMultiRebalanceModeVisibility);
    var dmMultiSymbolInputDebounce = null;
    var multiAssetRowsEl = document.getElementById("multiAssetRows");
    if (multiAssetRowsEl) {
        multiAssetRowsEl.addEventListener("focusin", function (e) {
            var input = e.target.closest(".multi-asset-symbol");
            if (!input) return;
            if (currentSelectedTemplate && currentSelectedTemplate.id === "multi_rebalance") {
                ensureCoinListSearchSymbolsLoaded("all").then(function () { buildCoinListSearchSymbols(); });
            }
        });
        multiAssetRowsEl.addEventListener("input", function (e) {
            var pctInput = e.target.closest(".multi-asset-pct");
            if (pctInput) {
                updateMultiPctTotal();
                return;
            }
            var input = e.target.closest(".multi-asset-symbol");
            if (!input) return;
            var v = (input.value || "").trim();
            clearTimeout(dmMultiSymbolInputDebounce);
            if (v.length >= 2) {
                dmMultiSymbolInputDebounce = setTimeout(function () {
                    ensureCoinListSearchSymbolsLoaded("all").then(function () {
                        buildCoinListSearchSymbols();
                        showMultiSymbolSearchDropdown(v, input);
                    });
                }, 200);
            } else {
                hideMultiSymbolSearchDropdown();
                if (v.length === 0) {
                    var idx = input.getAttribute("data-idx");
                    if (idx != null) updateMultiAssetPreview(idx, "");
                }
            }
        });
        multiAssetRowsEl.addEventListener("focusout", function (e) {
            if (e.relatedTarget && e.relatedTarget.closest && e.relatedTarget.closest("#dmMultiSymbolSearchDropdown")) return;
            setTimeout(function () {
                hideMultiSymbolSearchDropdown();
                var input = e.target;
                if (input && input.classList && input.classList.contains("multi-asset-symbol")) {
                    var v = (input.value || "").trim();
                    if (v.length >= 2) {
                        var sym = v.toUpperCase().replace(/\s/g, "");
                        if (!sym.endsWith("USDT")) sym = sym + "USDT";
                        var norm = normalizeModalSymbol(sym);
                        if (!norm.invalid && norm.normalized) updateMultiAssetPreview(input.getAttribute("data-idx"), norm.normalized);
                    }
                }
            }, 180);
        });
        multiAssetRowsEl.addEventListener("keydown", function (e) {
            var input = e.target.closest(".multi-asset-symbol");
            if (!input || e.key !== "Enter") return;
            var dropdown = document.getElementById("dmMultiSymbolSearchDropdown");
            var firstItem = dropdown && dropdown.querySelector(".dm-multi-symbol-item, .coin-list-search-item");
            if (firstItem && dropdown.style.display !== "none") {
                var symbol = firstItem.getAttribute("data-symbol");
                if (symbol) {
                    var base = symbol.replace(/USDT$/, "").replace(/FDUSD$/, "");
                    input.value = base;
                    hideMultiSymbolSearchDropdown();
                    var idx = input.getAttribute("data-idx");
                    if (idx != null) updateMultiAssetPreview(idx, symbol);
                    e.preventDefault();
                }
            } else {
                var v = (input.value || "").trim();
                if (v.length >= 2) {
                    var sym = v.toUpperCase().replace(/\s/g, "");
                    if (!sym.endsWith("USDT")) sym = sym + "USDT";
                    var norm = normalizeModalSymbol(sym);
                    if (!norm.invalid && norm.normalized) {
                        input.value = (norm.normalized || "").replace(/USDT$/, "");
                        var idx = input.getAttribute("data-idx");
                        if (idx != null) updateMultiAssetPreview(idx, norm.normalized);
                        e.preventDefault();
                    }
                }
            }
        });
    }
    var dmMultiSymbolSearchDropdownEl = document.getElementById("dmMultiSymbolSearchDropdown");
    if (dmMultiSymbolSearchDropdownEl) {
        dmMultiSymbolSearchDropdownEl.addEventListener("mousedown", function (e) { e.preventDefault(); });
        dmMultiSymbolSearchDropdownEl.addEventListener("click", function (e) {
            var item = e.target.closest(".dm-multi-symbol-item, .coin-list-search-item");
            if (!item) return;
            var symbol = item.getAttribute("data-symbol");
            if (!symbol || !_dmMultiSearchTargetInput) return;
            var base = symbol.replace(/USDT$/, "").replace(/FDUSD$/, "");
            _dmMultiSearchTargetInput.value = base;
            hideMultiSymbolSearchDropdown();
            var idx = _dmMultiSearchTargetIdx;
            if (idx != null) updateMultiAssetPreview(idx, symbol);
        });
    }
    
    // Submit: openCreateBotModal sets dmSubmitBtn.onclick → createAndStartBot (do not add createBot listener — it skips engine start)
}

function buildGridRows(containerId, count, mode, seedGrids) {
    const container = document.getElementById(containerId);
    if (!container) return;

    // Mevcut değerleri koru (count azaldığında kaybetme)
    const prev = {};
    container.querySelectorAll('input[id]').forEach(function(el) { prev[el.id] = el.value; });
    var seeds = Array.isArray(seedGrids) ? seedGrids : [];
    function seedNumber(grid, keys) {
        if (!grid) return null;
        for (var ki = 0; ki < keys.length; ki++) {
            var v = grid[keys[ki]];
            if (v != null && v !== '' && !isNaN(Number(v))) return Number(v);
        }
        return null;
    }
    function seedDisplay(v, digits) {
        if (v == null || isNaN(Number(v))) return '';
        if (typeof dmParamAssistantInputTextTr === 'function') return dmParamAssistantInputTextTr(v, digits);
        return String(Number(v).toFixed(digits)).replace('.', ',').replace(/,?0+$/, '');
    }

    let html = '';
    for (let i = 0; i < count; i++) {
        const triggerLabel = mode === 'up' ? 'Tetik %' : 'Tetik %';
        const triggerTooltip = mode === 'up'
            ? 'Referans fiyatından yukarı yönde %X kadar artışta bu grid tetiklenir.'
            : 'Referans fiyatından aşağı yönde %X kadar düşüşte bu grid tetiklenir.';
        const qtyTooltip = mode === 'up'
            ? 'Bu grid tetiklendiğinde coin miktarının %X\'i satılır. Tüm satış gridlerinin toplamı %100 olmalı.'
            : 'Bu grid tetiklendiğinde USDT miktarının %X\'i ile alış yapılır. Tüm alış gridlerinin toplamı %100 olmalı.';
        const defaultTrigger = ((i + 1) * 0.5).toFixed(1).replace('.', ',');
        const defaultQty = count > 0 ? (100 / count).toFixed(1).replace('.', ',') : '10';

        html += `
            <div class="grid-row">
                <div class="form-group">
                    <label class="label-with-tooltip">
                        ${triggerLabel} <span style="color:var(--ds-text-secondary);font-size:0.78rem">#${i+1}</span>
                        <span class="tooltip-icon">ℹ</span>
                        <span class="tooltip-text">${triggerTooltip}</span>
                    </label>
                    <input type="text" id="${mode}Grid_${i}_trigger" class="form-input" lang="tr" inputmode="decimal" placeholder="${defaultTrigger}" />
                </div>
                <div class="form-group">
                    <label class="label-with-tooltip">
                        Miktar %
                        <span class="tooltip-icon">ℹ</span>
                        <span class="tooltip-text">${qtyTooltip}</span>
                    </label>
                    <input type="text" id="${mode}Grid_${i}_qty" class="form-input" lang="tr" inputmode="decimal" placeholder="${defaultQty}" />
                </div>
            </div>
        `;
    }
    container.innerHTML = html;

    // Cache/öneri verisiyle ilk render: toplam etiketi %0 ara durumuna düşmesin.
    seeds.forEach(function (grid, i) {
        var trigger = seedNumber(grid, [mode === 'up' ? 'sell_grid_pct' : 'buy_grid_pct', 'trigger_pct']);
        var qty = seedNumber(grid, [mode === 'up' ? 'sell_qty_pct_of_base' : 'buy_qty_pct_of_quote', 'qty_pct']);
        var tEl = document.getElementById(mode + 'Grid_' + i + '_trigger');
        var qEl = document.getElementById(mode + 'Grid_' + i + '_qty');
        if (tEl && trigger != null) tEl.value = seedDisplay(trigger, 2);
        if (qEl && qty != null) qEl.value = seedDisplay(qty, 1);
    });

    // Önceki değerleri geri yaz
    container.querySelectorAll('input[id]').forEach(function(el) {
        if (prev[el.id] != null && prev[el.id] !== '') el.value = prev[el.id];
    });

    // Qty değişince toplamı göster
    container.addEventListener('input', function(e) {
        if (e.target && e.target.id && e.target.id.indexOf('_qty') !== -1) {
            _updateGridQtySum(containerId, mode);
        }
    });
    _updateGridQtySum(containerId, mode);
}

function _updateGridQtySum(containerId, mode) {
    var container = document.getElementById(containerId);
    if (!container) return;
    var inputs = container.querySelectorAll('input[id$="_qty"]');
    var sum = 0;
    inputs.forEach(function(el) { sum += parseDecimal(el.value, 0) || 0; });
    sum = Math.round(sum * 10) / 10;

    var summaryId = containerId + '_qtysum';
    var existing = document.getElementById(summaryId);
    if (inputs.length === 0) { if (existing) existing.remove(); return; }

    if (!existing) {
        existing = document.createElement('div');
        existing.id = summaryId;
        existing.style.cssText = 'font-size:0.8rem;margin-top:0.4rem;padding:0.3rem 0.5rem;border-radius:5px;text-align:right;';
        container.parentNode.insertBefore(existing, container.nextSibling);
    }
    var ok = Math.abs(sum - 100) < 0.15;
    existing.style.background = ok ? 'rgba(14,203,129,0.08)' : 'rgba(246,70,93,0.10)';
    existing.style.color = ok ? '#0ecb81' : '#f6465d';
    existing.textContent = 'Miktar toplamı: %' + sum.toFixed(1) + (ok ? ' ✓' : ' — %100 olmalı');
}

function syncMaxBuyLevelsWithDownCount(count) {
    var el = document.getElementById("fMaxBuyLevels");
    if (!el) return;
    var n = Math.max(0, parseInt(count, 10) || 0);
    el.max = String(Math.max(1, n));
    var current = parseInt(el.value, 10);
    if (!Number.isFinite(current) || current < 1) {
        el.value = String(Math.max(1, n));
    } else if (n > 0 && current > n) {
        el.value = String(n);
    }
}

function normalizeSymbol(symbol) {
    return symbol.toUpperCase().replace(/\s+/g, '').replace(/\//g, '');
}

/** Parite sembolünden base/quote çıkar (BTCUSDT → { base: 'BTC', quote: 'USDT' }) */
function parseBaseQuote(symbol) {
    var pq = parseTradingPairSymbol(symbol);
    if (pq.valid) return { base: pq.base, quote: pq.quote };
    return { base: (symbol || '').toUpperCase().replace(/[\s\/\-]/g, ''), quote: 'USDT' };
}

/** Create bot modal: ticker_24h yanıtını strip + tahmin alanına uygula (klines'den hızlı). */
function applyCreateBotModalTickerData(sym, quote, data) {
    if (!sym || !data) return;
    var price = parseFloat(data.lastPrice || data.weightedAvgPrice || 0);
    var pct = parseFloat(data.priceChangePercent);
    var high = parseFloat(data.highPrice || 0);
    var low = parseFloat(data.lowPrice || 0);
    if (!(price > 0 && Number.isFinite(price))) return;
    var pctVal = Number.isFinite(pct) ? pct : null;
    _updateCoinSearchSymbolQuote(sym, price, pctVal);
    if (window.marketStore && window.marketStore.updateMini) {
        var miniPatch = { last: price, changePct: pctVal };
        if (high > 0 && Number.isFinite(high)) miniPatch.high = high;
        if (low > 0 && Number.isFinite(low)) miniPatch.low = low;
        window.marketStore.updateMini(sym, miniPatch);
    }
    var priceEl = document.getElementById('dmPairPrice');
    var changeEl = document.getElementById('dmPairChangePct');
    var changeTahmin = document.getElementById('dmTahminChange');
    var highEl = document.getElementById('dmTahminHigh');
    var lowEl = document.getElementById('dmTahminLow');
    var formatPrice = function (v) {
        return (v != null && Number.isFinite(v) && v > 0)
            ? ((quote === 'USDT' || quote === 'FDUSD') ? fmtUsd(v) : fmtNum(v, 8))
            : '—';
    };
    if (priceEl) {
        var newText = (quote === 'USDT' || quote === 'FDUSD' ? fmtUsd(price) : fmtNum(price, 8) + ' ' + quote);
        if (priceEl.textContent !== newText) {
            var blinkGrace = (typeof dmModalOpenTs === 'number' && (Date.now() - dmModalOpenTs) < 600);
            if (!blinkGrace && dmModalLastPrice != null && Number.isFinite(dmModalLastPrice) && Math.abs(price - dmModalLastPrice) > 1e-10 && typeof triggerValueBlink === 'function') {
                triggerValueBlink(priceEl, price);
            }
            dmModalLastPrice = price;
            priceEl.textContent = newText;
        }
    }
    if (pctVal != null) {
        applyDmModalPctEl(changeEl, pctVal);
        applyDmModalPctEl(changeTahmin, pctVal);
    }
    if (high > 0 && Number.isFinite(high)) {
        dmModalTahminHigh = high;
        if (highEl) highEl.textContent = formatPrice(high);
    }
    if (low > 0 && Number.isFinite(low)) {
        dmModalTahminLow = low;
        if (lowEl) lowEl.textContent = formatPrice(low);
    }
}

/** Create bot modal: /api/spot/ticker_24h — fiyat, 24s %, yüksek/düşük (klines yerine). */
function fetchCreateBotModalTicker24h(symbol, opts) {
    opts = opts || {};
    var sym = (symbol || '').toUpperCase();
    if (!sym) return Promise.resolve(null);
    var now = Date.now();
    var symbolChanged = sym !== _dmModalLastTickerFetchSymbol;
    var stale = (now - _dmModalTickerFetchTs) >= DM_MODAL_TAHMIN_MIN_MS;
    if (!opts.force && !symbolChanged && !stale) {
        if (_dmModalTickerInflightKey === sym && _dmModalTickerInflight) return _dmModalTickerInflight;
        return Promise.resolve(null);
    }
    if (_dmModalTickerInflightKey === sym && _dmModalTickerInflight) return _dmModalTickerInflight;
    var quote = parseBaseQuote(sym).quote;
    _dmModalTickerInflightKey = sym;
    var fetchFn = window.apiClient && typeof window.apiClient.get === 'function'
        ? window.apiClient.get('/api/spot/ticker_24h?symbol=' + encodeURIComponent(sym), { suppressRateLimitToast: true, timeout: 8000 })
        : fetch(window.location.origin + '/api/spot/ticker_24h?symbol=' + encodeURIComponent(sym)).then(function (r) { return r.json(); });
    _dmModalTickerInflight = Promise.resolve(fetchFn).then(function (data) {
        if (_dmModalTickerInflightKey !== sym) return data;
        _dmModalLastTickerFetchSymbol = sym;
        _dmModalTickerFetchTs = Date.now();
        dmModalTahminFetchTs = _dmModalTickerFetchTs;
        applyCreateBotModalTickerData(sym, quote, data);
        return data;
    }).catch(function () {
        return null;
    }).finally(function () {
        if (_dmModalTickerInflightKey === sym) {
            _dmModalTickerInflight = null;
        }
    });
    return _dmModalTickerInflight;
}

/** Create bot modal: seçilen parite strip'ini (logo, fiyat, 24h %, grafik) ve tahmin alanını güncelle */
function updateCreateBotModalPairStrip(symbol, opts) {
    opts = opts || {};
    const strip = document.getElementById('dmSelectedPairStrip');
    const tahminStrip = document.getElementById('dmTahminStrip');
    const logoEl = document.getElementById('dmPairLogo');
    const baseEl = document.getElementById('dmPairBaseSymbol');
    const pairEl = document.getElementById('dmPairSymbol');
    const priceEl = document.getElementById('dmPairPrice');
    const changeEl = document.getElementById('dmPairChangePct');
    const norm = normalizeModalSymbol(symbol || '');
    if (!strip || !tahminStrip) return;
    if (norm.invalid || !norm.normalized) {
        strip.style.display = 'none';
        tahminStrip.style.display = 'none';
        var qEl = document.getElementById('dmQuoteAssetName');
        if (qEl) qEl.textContent = 'USDT';
        var fb = document.getElementById('fBudget');
        if (fb) fb.placeholder = 'Kullanılabilir: —';
        return;
    }
    const sym = norm.normalized;
    if (!opts.preserveDropdown && sym && sym !== _dmModalStripSymbol) {
        resetParamAssistantSymbolIsolation(_dmModalStripSymbol, sym);
        hideCreateModalSymbolDropdown();
        _dmModalStripSymbol = sym;
    }
    const { base, quote } = parseBaseQuote(sym);
    strip.style.display = 'flex';
    tahminStrip.style.display = 'block';
    var quoteNameEl = document.getElementById('dmQuoteAssetName');
    if (quoteNameEl) quoteNameEl.textContent = quote || 'USDT';
    var fBudget = document.getElementById('fBudget');
    if (fBudget) {
        fBudget.placeholder = formatAvailableQuotePlaceholder(quote || 'USDT', getAvailableQuoteInWallet(quote || 'USDT'));
    }
    if (baseEl) baseEl.textContent = base || '—';
    if (pairEl) pairEl.textContent = sym;
    if (logoEl && typeof getCoinLogoUrl === 'function') {
        if (base !== dmModalLastLogoBase) {
            dmModalLastLogoBase = base;
            const url = getCoinLogoUrl(base);
            const initials = (typeof getCoinLogoInitials === 'function' ? getCoinLogoInitials(base) : (base || '?').substring(0, 1).toUpperCase());
            logoEl.innerHTML = url
                ? '<img src="' + url + '" alt="' + base + '" data-symbol="' + base + '" loading="' + ((typeof shouldEagerLoadLogo === 'function' && shouldEagerLoadLogo(base)) ? 'eager' : 'lazy') + '" onload="if(window.markCoinLogoLoaded)window.markCoinLogoLoaded(this)" onerror="if(window.handleCoinLogoError)window.handleCoinLogoError(this)" /><span class="varlik-logo-initials" style="display:none">' + initials + '</span>'
                : '<span class="varlik-logo-initials">' + initials + '</span>';
            logoEl.title = base;
        }
    }
    const mini = window.marketStore && window.marketStore.getMini(sym);
    const price = (mini && mini.last != null) ? mini.last : (window.marketStore && window.marketStore.getPrice(sym));
    const pct = resolveDmModalChangePct(mini);
    if (priceEl) {
        if (price != null && Number.isFinite(price)) {
            const newText = (quote === 'USDT' || quote === 'FDUSD' ? fmtUsd(price) : fmtNum(price, 8) + ' ' + quote);
            if (priceEl.textContent !== newText) {
                var blinkGrace = (typeof dmModalOpenTs === 'number' && (Date.now() - dmModalOpenTs) < 600);
                if (!blinkGrace && dmModalLastPrice != null && Number.isFinite(dmModalLastPrice) && Math.abs(price - dmModalLastPrice) > 1e-10 && typeof triggerValueBlink === 'function') {
                    triggerValueBlink(priceEl, price);
                }
                dmModalLastPrice = price;
                priceEl.textContent = newText;
            }
        } else {
            if (priceEl.textContent !== '—') {
                priceEl.textContent = '—';
                dmModalLastPrice = null;
            }
        }
    }
    if (changeEl) applyDmModalPctEl(changeEl, pct);
    // Grafik sadece sembol değiştiğinde yeniden yüklensin (her tick'te yüklemek flicker yapıyor)
    if (sym !== dmModalLastChartSymbol) {
        dmModalLastChartSymbol = sym;
        loadCreateBotModalChart(sym);
    }
    updateCreateBotModalTahmin(sym, mini, quote);
    var needTicker = sym !== _dmModalLastTickerFetchSymbol || !(price != null && Number.isFinite(price)) || (Date.now() - _dmModalTickerFetchTs) >= DM_MODAL_TAHMIN_MIN_MS;
    if (needTicker) fetchCreateBotModalTicker24h(sym, { force: sym !== _dmModalLastTickerFetchSymbol });
    var fSymApply = document.getElementById('fSymbol');
    if (fSymApply && sym) fSymApply.value = sym;
    if (typeof applyLastCreateParamsToForm === 'function') {
        setTimeout(applyLastCreateParamsToForm, 0);
    }
    // Canlı fiyat: modal açık ve sembol seçiliyse periyodik güncelleme başlat
    if (!dmModalLivePriceIntervalId && document.getElementById('dmModal') && document.getElementById('dmModal').style.display !== 'none') {
        dmModalLivePriceIntervalId = setInterval(function () {
            var modal = document.getElementById('dmModal');
            var fSym = document.getElementById('fSymbol');
            if (!modal || modal.style.display === 'none' || !fSym || !fSym.value.trim()) return;
            if (document.activeElement === fSym || isCreateModalSymbolDropdownOpen()) return;
            var currentSym = normalizeModalSymbol(fSym.value.trim());
            if (currentSym.normalized) updateCreateBotModalPairStrip(currentSym.normalized, { preserveDropdown: true });
        }, DM_MODAL_LIVE_PRICE_MS);
    }
}

/** Create bot modal: Tahmin alanını (24s değişim, yüksek/düşük) önbellekten doldur; veri ticker_24h ile gelir. */
function updateCreateBotModalTahmin(symbol, mini, quoteAsset) {
    const changeEl = document.getElementById('dmTahminChange');
    const highEl = document.getElementById('dmTahminHigh');
    const lowEl = document.getElementById('dmTahminLow');
    const formatPrice = (v) => (v != null && Number.isFinite(v) && v > 0) ? (quoteAsset === 'USDT' || quoteAsset === 'FDUSD' ? fmtUsd(v) : fmtNum(v, 8)) : '—';
    if (changeEl) applyDmModalPctEl(changeEl, resolveDmModalChangePct(mini));
    if (!symbol) return;
    if (symbol !== dmModalLastTahminSymbol) {
        dmModalLastTahminSymbol = symbol;
        dmModalTahminHigh = null;
        dmModalTahminLow = null;
        if (highEl) highEl.textContent = '—';
        if (lowEl) lowEl.textContent = '—';
    }
    var miniHigh = mini && mini.high != null ? Number(mini.high) : null;
    var miniLow = mini && mini.low != null ? Number(mini.low) : null;
    if (miniHigh != null && Number.isFinite(miniHigh) && miniHigh > 0) {
        dmModalTahminHigh = miniHigh;
        if (highEl) highEl.textContent = formatPrice(miniHigh);
    } else if (dmModalTahminHigh != null && highEl) {
        highEl.textContent = formatPrice(dmModalTahminHigh);
    }
    if (miniLow != null && Number.isFinite(miniLow) && miniLow > 0) {
        dmModalTahminLow = miniLow;
        if (lowEl) lowEl.textContent = formatPrice(miniLow);
    } else if (dmModalTahminLow != null && lowEl) {
        lowEl.textContent = formatPrice(dmModalTahminLow);
    }
}

function dmParamAssistantSetTimer(fn, ms) {
    var id = setTimeout(function () {
        dmParamAssistantTimers = dmParamAssistantTimers.filter(function (x) { return x !== id; });
        fn();
    }, ms);
    dmParamAssistantTimers.push(id);
    return id;
}

function dmParamAssistantClearTimers() {
    dmParamAssistantTimers.forEach(function (id) { clearTimeout(id); });
    dmParamAssistantTimers = [];
    if (dmParamAssistantProgressTickTimer) {
        clearTimeout(dmParamAssistantProgressTickTimer);
        dmParamAssistantProgressTickTimer = null;
    }
    dmParamAssistantStopLinearProgress();
    dmParamAssistantStopMicroSteps();
}

function dmParamAssistantSetCursorVisible(on) {
    var c = document.getElementById('dmParamAssistantCursor');
    if (c) c.style.visibility = on ? 'visible' : 'hidden';
}

function dmParamAssistantStopLinearProgress() {
    if (dmParamAssistantLinearProgTimer) {
        clearInterval(dmParamAssistantLinearProgTimer);
        dmParamAssistantLinearProgTimer = null;
    }
}

function dmParamAssistantStartLinearProgress(runId, opts) {
    opts = opts || {};
    var startPct = Number(opts.startPct != null ? opts.startPct : 4);
    var endPct = Number(opts.endPct != null ? opts.endPct : 90);
    var durationMs = Math.max(1200, Number(opts.durationMs) || 14000);
    var tickMs = Number(opts.tickMs) || 45;
    var started = Date.now();
    dmParamAssistantStopLinearProgress();
    dmParamAssistantLinearProgTimer = setInterval(function () {
        if (!dmParamAssistantProgressState || dmParamAssistantProgressState.runId !== runId) {
            dmParamAssistantStopLinearProgress();
            return;
        }
        var t = Math.min(1, (Date.now() - started) / durationMs);
        var pct = startPct + (endPct - startPct) * t;
        dmParamAssistantRenderTimePct(pct);
        if (t >= 1) dmParamAssistantStopLinearProgress();
    }, tickMs);
}

function dmParamAssistantStopMicroSteps() {
    if (dmParamAssistantMicroStepTimer) {
        clearInterval(dmParamAssistantMicroStepTimer);
        dmParamAssistantMicroStepTimer = null;
    }
    dmParamAssistantLiveTypeToken++;
}

function dmParamAssistantTypeLiveLine(text, opts) {
    opts = opts || {};
    var live = document.getElementById('dmPaProgLive');
    var status = document.getElementById('dmParamAssistantStatus');
    var msg = String(text || '');
    if (!live && !status) return;
    if (!opts.animated) {
        if (live) {
            live.textContent = msg;
            live.classList.remove('is-typing');
        }
        if (opts.syncStatus !== false && status) status.textContent = msg;
        return;
    }
    var token = ++dmParamAssistantLiveTypeToken;
    if (live) live.classList.add('is-typing');
    var idx = 0;
    var chunk = document.hidden ? 12 : 4;
    var ms = Math.max(6, (AI_ASSISTANT_SPEC.timing && AI_ASSISTANT_SPEC.timing.textMs) || 14);
    function step() {
        if (token !== dmParamAssistantLiveTypeToken) return;
        if (live) live.textContent = msg.slice(0, idx + chunk);
        if (opts.syncStatus !== false && status) status.textContent = msg.slice(0, idx + chunk);
        idx += chunk;
        if (idx < msg.length) {
            dmParamAssistantSetTimer(step, ms);
        } else if (live) {
            live.classList.remove('is-typing');
        }
    }
    if (live) live.textContent = '';
    step();
}

function dmParamAssistantStartMicroSteps(runId, ticks, intervalMs) {
    dmParamAssistantStopMicroSteps();
    var list = Array.isArray(ticks) ? ticks.filter(Boolean) : [];
    if (!list.length) return;
    var i = 0;
    function showTick() {
        dmParamAssistantTypeLiveLine(list[i], { syncStatus: false });
    }
    showTick();
    dmParamAssistantMicroStepTimer = setInterval(function () {
        if (!dmParamAssistantProgressState || dmParamAssistantProgressState.runId !== runId) {
            dmParamAssistantStopMicroSteps();
            return;
        }
        if (list.length < 2) return;
        i = (i + 1) % list.length;
        showTick();
    }, Math.max(2400, intervalMs || 2800));
}

function dmParamAssistantSetApplyTimer(fn, ms) {
    var id = setTimeout(function () {
        dmParamAssistantApplyTimers = dmParamAssistantApplyTimers.filter(function (x) { return x !== id; });
        fn();
    }, ms);
    dmParamAssistantApplyTimers.push(id);
    return id;
}

function dmParamAssistantClearApplyTimers(opts) {
    opts = opts || {};
    dmParamAssistantApplyTimers.forEach(function (id) { clearTimeout(id); });
    dmParamAssistantApplyTimers = [];
    if (!opts.keepApplyingFlag) {
        dmParamAssistantApplying = false;
    }
    if (!opts.keepFieldStyles) {
        try {
            document.querySelectorAll('.dm-ai-input-writing, .dm-ai-input-done').forEach(function (el) {
                el.classList.remove('dm-ai-input-writing', 'dm-ai-input-done');
            });
        } catch (e) {}
    }
}

function dmParamAssistantClearAiInputStyles() {
    try {
        document.querySelectorAll('.dm-ai-input-writing, .dm-ai-input-done').forEach(function (el) {
            el.classList.remove('dm-ai-input-writing', 'dm-ai-input-done');
        });
    } catch (e) {}
}

function dmParamAssistantBeginInputTyping(el) {
    if (!el) return { finish: function () {} };
    var wasNumber = dmParamAssistantIsNumberInput(el);
    if (wasNumber) {
        el.type = 'text';
        el.setAttribute('inputmode', 'decimal');
    }
    el.classList.add('dm-ai-input-writing');
    el.classList.remove('dm-ai-input-done');
    try { el.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch (e) {}
    try { el.focus({ preventScroll: true }); } catch (e) { try { el.focus(); } catch (_) {} }
    return {
        finish: function (finalValue) {
            if (wasNumber) {
                el.value = dmParamAssistantNormalizeNumberInputValue(finalValue);
                el.type = 'number';
                el.removeAttribute('inputmode');
            }
            el.classList.remove('dm-ai-input-writing');
            el.classList.add('dm-ai-input-done');
        }
    };
}

function dmParamAssistantEnsureCreateModalVisibleForApply() {
    var modal = document.getElementById('dmModal');
    var backdrop = document.getElementById('dmBackdrop');
    if (!modal) return;
    modal.setAttribute('aria-hidden', 'false');
    modal.style.display = 'flex';
    modal.style.pointerEvents = '';
    if (backdrop) {
        backdrop.setAttribute('aria-hidden', 'false');
        backdrop.style.display = 'block';
        backdrop.style.pointerEvents = '';
    }
    document.body.classList.remove('dm-param-assistant-open');
    document.body.style.overflow = 'hidden';
    try { modal.scrollIntoView({ behavior: 'smooth', block: 'start' }); } catch (e) {}
}

function dmParamAssistantEscape(s) {
    var div = document.createElement('div');
    div.textContent = s == null ? '' : String(s);
    return div.innerHTML;
}

function dmParamAssistantClamp(v, min, max) {
    v = Number(v);
    if (!Number.isFinite(v)) v = min;
    return Math.max(min, Math.min(max, v));
}

function dmParamAssistantRound(v, digits) {
    var p = Math.pow(10, digits || 0);
    return Math.round((Number(v) || 0) * p) / p;
}

function dmParamAssistantInputText(v, digits) {
    var n = Number(v);
    if (!Number.isFinite(n)) n = 0;
    var d = digits == null ? 2 : digits;
    if (d === 0) return String(Math.round(n));
    var s = n.toFixed(d);
    if (s.indexOf('.') >= 0) {
        s = s.replace(/0+$/, '').replace(/\.$/, '');
    }
    return s;
}

function dmParamAssistantInputTextTr(v, digits) {
    return dmParamAssistantInputText(v, digits).replace('.', ',');
}

/** Form dağılımı: %100 ölçeğinde, base+quote=100 (PA / önbellek / fraksiyon düzeltmesi). */
function normalizeFormAllocationPct(basePct, quotePct) {
    var base = Number(basePct);
    var quote = Number(quotePct);
    if (!Number.isFinite(base)) base = 50;
    if (!Number.isFinite(quote)) quote = 50;
    if (base > 0 && base <= 1 && quote > 0 && quote <= 1 && Math.abs(base + quote - 1) < 0.05) {
        base *= 100;
        quote *= 100;
    }
    var sum = base + quote;
    if (sum > 0 && Math.abs(sum - 100) > 0.5) {
        base = (base / sum) * 100;
        quote = 100 - base;
    }
    base = Math.round(dmParamAssistantClamp(base, 0, 100) * 10) / 10;
    quote = Math.round(dmParamAssistantClamp(100 - base, 0, 100) * 10) / 10;
    return { basePct: base, quotePct: quote };
}

/**
 * Bot oluşturma formu: ilk sermaye bölüşümü (spec varsayılan ~50/50).
 * DPS ui_config.base_alloc_pct = uzun vadeli hedef exposure; forma doğrudan yazılırsa 10/90 gibi
 * uç değerler çıkar — çift taraflı grid için dengeli banda çekilir.
 */
function resolveCreateFormAllocation(basePct, quotePct, opts) {
    opts = opts || {};
    var norm = normalizeFormAllocationPct(basePct, quotePct);
    var base = norm.basePct;
    var hasBuy = opts.hasBuyGrids !== false;
    var hasSell = opts.hasSellGrids !== false;
    var sellOnly = !!opts.sellManagementOnly;
    var CREATE_FORM_BASE_MIN = 25;
    var CREATE_FORM_BASE_MAX = 65;
    var CREATE_FORM_DEFAULT = 50;

    if (hasBuy && hasSell && !sellOnly) {
        if (base < CREATE_FORM_BASE_MIN || base > CREATE_FORM_BASE_MAX) {
            base = CREATE_FORM_DEFAULT;
        }
        return normalizeFormAllocationPct(base, 100 - base);
    }
    if (hasBuy && !hasSell && base < CREATE_FORM_BASE_MIN) {
        base = CREATE_FORM_DEFAULT;
        return normalizeFormAllocationPct(base, 100 - base);
    }
    return norm;
}

function syncQuotePctFromBaseInput() {
    var fBasePct = document.getElementById('fBasePct');
    var fQuotePct = document.getElementById('fQuotePct');
    if (!fBasePct || !fQuotePct) return;
    var baseVal = parseFloat(String(fBasePct.value).replace(',', '.')) || 0;
    fQuotePct.value = (100 - dmParamAssistantClamp(baseVal, 0, 100)).toFixed(1);
}

function dmParamAssistantTextChunkSize() {
    return document.hidden ? 22 : 5;
}

function dmParamAssistantInputChunkSize() {
    return document.hidden ? 2 : 1;
}

function dmParamAssistantIsNumberInput(el) {
    return !!(el && String(el.type || '').toLowerCase() === 'number');
}

/** type=number alanlarında ondalık için nokta; karakter karakter yazım ara "31." gibi geçersiz durumları bozar. */
function dmParamAssistantNormalizeNumberInputValue(raw) {
    var s = String(raw == null ? '' : raw).replace(',', '.').trim();
    var n = parseFloat(s);
    return Number.isFinite(n) ? String(n) : s;
}

function dmParamAssistantFinalizeFormAllocation(basePct, quotePct) {
    var fBase = document.getElementById('fBasePct');
    var fQuote = document.getElementById('fQuotePct');
    var baseTxt = dmParamAssistantInputText(basePct, 1);
    var quoteTxt = dmParamAssistantInputText(quotePct, 1);
    if (fBase) fBase.value = baseTxt;
    if (fQuote) fQuote.value = quoteTxt;
    dmParamAssistantDispatch(fBase, 'input');
    dmParamAssistantDispatch(fQuote, 'input');
}

function dmParamAssistantAllocationForApply(rec) {
    var ui = (rec.backend && rec.backend.ui_config) || {};
    var allocDisp = rec.allocationDisplay || ui.allocation_display || {};
    var strat = allocDisp.strategic_target || {};
    var baseRaw = strat.base_pct != null ? strat.base_pct : rec.basePct;
    var quoteRaw = strat.quote_pct != null ? strat.quote_pct : rec.quotePct;
    return resolveCreateFormAllocation(baseRaw, quoteRaw, {
        hasBuyGrids: rec.downGrids && rec.downGrids.length > 0,
        hasSellGrids: rec.upGrids && rec.upGrids.length > 0,
        sellManagementOnly: !!rec.sellManagementOnly
    });
}

function dmParamAssistantDisplayPct(v, digits) {
    var n = Number(v);
    if (!Number.isFinite(n)) return '—';
    return (n >= 0 ? '+' : '') + n.toFixed(digits == null ? 2 : digits) + '%';
}

function dmParamAssistantDisplayPrice(v, quote) {
    var n = Number(v);
    if (!Number.isFinite(n) || n <= 0) return '—';
    if ((quote === 'USDT' || quote === 'FDUSD' || quote === 'USDC') && typeof fmtUsd === 'function') return fmtUsd(n);
    if (typeof fmtNum === 'function') return fmtNum(n, 8) + (quote ? ' ' + quote : '');
    return n.toFixed(8).replace(/\.?0+$/, '') + (quote ? ' ' + quote : '');
}

function dmParamAssistantQtys(count) {
    if (count <= 1) return [100];
    var raw;
    if (count === 2) raw = [50, 50];
    else if (count === 3) raw = [40, 35, 25];
    else raw = [30, 25, 25, 20].slice(0, count);
    return dmParamAssistantNormalizeQtys(raw);
}

function dmParamAssistantNormalizeQtys(qtys) {
    if (!qtys || !qtys.length) return [];
    if (qtys.length === 1) return [100];
    var scaled = qtys.map(function (q) { return Math.round(Number(q) * 10) / 10; });
    var sum = scaled.reduce(function (a, b) { return a + b; }, 0);
    var drift = Math.round((100 - sum) * 10) / 10;
    if (Math.abs(drift) >= 0.05) {
        var idx = 0;
        for (var i = 1; i < scaled.length; i++) {
            if (scaled[i] > scaled[idx]) idx = i;
        }
        scaled[idx] = Math.round((scaled[idx] + drift) * 10) / 10;
    }
    return scaled;
}

function dmParamAssistantSnapshotMatchesCurrent(snapshot) {
    if (!snapshot) return false;
    var cur = dmParamAssistantCurrentSnapshot();
    var snapSym = dmParamAssistantNormalizeSymbol(snapshot.symbol);
    var curSym = dmParamAssistantNormalizeSymbol(cur.symbol);
    if (!snapSym || !curSym || snapSym !== curSym) return false;
    var snapBudget = dmParamAssistantResolveBudget(snapshot);
    var curBudget = dmParamAssistantResolveBudget(cur);
    if (snapBudget != null && curBudget != null && Math.abs(Number(snapBudget) - Number(curBudget)) > 0.01) {
        return false;
    }
    return true;
}

function dmParamAssistantCurrentSnapshot() {
    var fSymbol = document.getElementById('fSymbol');
    var rawSymbol = (fSymbol && fSymbol.value ? fSymbol.value : '').trim();
    var norm = normalizeModalSymbol(rawSymbol);
    var symbol = norm && !norm.invalid ? norm.normalized : normalizeSymbol(rawSymbol || '');
    var pq = parseBaseQuote(symbol || '');
    var mini = symbol && window.marketStore && window.marketStore.getMini ? window.marketStore.getMini(symbol) : null;
    var price = dmModalLastPrice;
    if (!(price > 0) && mini && mini.last != null) price = Number(mini.last);
    if (!(price > 0) && symbol && window.marketStore && window.marketStore.getPrice) price = Number(window.marketStore.getPrice(symbol));
    var pct = resolveDmModalChangePct(mini);
    var high = dmModalTahminHigh;
    var low = dmModalTahminLow;
    if (!(high > 0) && mini && mini.high != null) high = Number(mini.high);
    if (!(low > 0) && mini && mini.low != null) low = Number(mini.low);
    var ref = price > 0 ? price : ((high > 0 && low > 0) ? (high + low) / 2 : null);
    var rangePct = (high > 0 && low > 0 && ref > 0) ? ((high - low) / ref * 100) : null;
    var budgetEl = document.getElementById('fBudget');
    var currentBudget = budgetEl && budgetEl.value !== '' ? Number(budgetEl.value) : null;
    var availableQuote = null;
    try { availableQuote = getAvailableQuoteInWallet(pq.quote || 'USDT'); } catch (e) { availableQuote = null; }
    var dynEl = document.getElementById('fDynamicMode');
    return {
        symbol: symbol || '',
        base: pq.base || '',
        quote: pq.quote || 'USDT',
        price: Number.isFinite(price) ? price : null,
        changePct: Number.isFinite(pct) ? pct : null,
        high: Number.isFinite(high) ? high : null,
        low: Number.isFinite(low) ? low : null,
        rangePct: Number.isFinite(rangePct) ? Math.max(0, rangePct) : null,
        currentBudget: Number.isFinite(currentBudget) ? currentBudget : null,
        availableQuote: Number.isFinite(availableQuote) ? availableQuote : null,
        dynamicMode: !!(dynEl && dynEl.checked)
    };
}

function dmParamAssistantFinite(v) {
    var n = Number(v);
    return Number.isFinite(n) ? n : null;
}

function dmParamAssistantNum(v, fallback) {
    var n = Number(v);
    return Number.isFinite(n) ? n : fallback;
}

function dmParamAssistantMean(values) {
    var clean = (values || []).filter(function (v) { return Number.isFinite(Number(v)); }).map(Number);
    if (!clean.length) return null;
    return clean.reduce(function (a, b) { return a + b; }, 0) / clean.length;
}

function dmParamAssistantStd(values) {
    var clean = (values || []).filter(function (v) { return Number.isFinite(Number(v)); }).map(Number);
    if (clean.length < 2) return null;
    var mean = dmParamAssistantMean(clean);
    var variance = clean.reduce(function (sum, v) { return sum + Math.pow(v - mean, 2); }, 0) / (clean.length - 1);
    return Math.sqrt(Math.max(0, variance));
}

function dmParamAssistantPercentile(values, pct) {
    var clean = (values || []).filter(function (v) { return Number.isFinite(Number(v)); }).map(Number).sort(function (a, b) { return a - b; });
    if (!clean.length) return null;
    if (clean.length === 1) return clean[0];
    var pos = dmParamAssistantClamp(pct, 0, 1) * (clean.length - 1);
    var lo = Math.floor(pos);
    var hi = Math.ceil(pos);
    if (lo === hi) return clean[lo];
    return clean[lo] + (clean[hi] - clean[lo]) * (pos - lo);
}

function dmParamAssistantWeightedMean(items, fallback) {
    var total = 0;
    var weight = 0;
    (items || []).forEach(function (it) {
        var value = Number(it && it.value);
        var w = Number(it && it.weight);
        if (Number.isFinite(value) && Number.isFinite(w) && w > 0) {
            total += value * w;
            weight += w;
        }
    });
    return weight > 0 ? total / weight : fallback;
}

function dmParamAssistantCandleList(data) {
    if (!Array.isArray(data)) return [];
    var out = [];
    data.forEach(function (k) {
        var t = Number(k && k.t);
        var o = Number(k && k.o);
        var h = Number(k && k.h);
        var l = Number(k && k.l);
        var c = Number(k && k.c);
        var v = Number(k && k.v);
        if (Number.isFinite(t) && Number.isFinite(o) && Number.isFinite(h) && Number.isFinite(l) && Number.isFinite(c) && c > 0 && h > 0 && l > 0) {
            out.push({ t: t, o: o, h: h, l: l, c: c, v: Number.isFinite(v) ? v : 0 });
        }
    });
    out.sort(function (a, b) { return a.t - b.t; });
    return out;
}

function dmParamAssistantDedupeCandles(candles) {
    var seen = {};
    var out = [];
    (candles || []).forEach(function (c) {
        if (!c || !Number.isFinite(c.t) || seen[c.t]) return;
        seen[c.t] = 1;
        out.push(c);
    });
    out.sort(function (a, b) { return a.t - b.t; });
    return out;
}

function dmParamAssistantSliceDays(candles, days) {
    var list = dmParamAssistantDedupeCandles(candles || []);
    if (!list.length || !Number.isFinite(days) || days <= 0) return [];
    var last = list[list.length - 1].t;
    var cutoff = last - days * DM_PARAM_ASSISTANT_DAY_MS;
    return list.filter(function (c) { return c.t >= cutoff; });
}

function dmParamAssistantCloseReturns(candles) {
    var out = [];
    for (var i = 1; i < (candles || []).length; i++) {
        var prev = Number(candles[i - 1].c);
        var cur = Number(candles[i].c);
        if (prev > 0 && cur > 0) out.push((cur - prev) / prev * 100);
    }
    return out;
}

function dmParamAssistantRangePcts(candles) {
    return (candles || []).map(function (c) {
        var ref = Number(c.c) > 0 ? Number(c.c) : ((Number(c.h) + Number(c.l)) / 2);
        return ref > 0 ? Math.max(0, (Number(c.h) - Number(c.l)) / ref * 100) : null;
    }).filter(function (v) { return Number.isFinite(v); });
}

function dmParamAssistantTrueRangePcts(candles) {
    var out = [];
    for (var i = 0; i < (candles || []).length; i++) {
        var c = candles[i];
        var prevClose = i > 0 ? Number(candles[i - 1].c) : Number(c.o);
        var ref = prevClose > 0 ? prevClose : Number(c.c);
        if (!(ref > 0)) continue;
        var tr = Math.max(
            Number(c.h) - Number(c.l),
            Math.abs(Number(c.h) - prevClose),
            Math.abs(Number(c.l) - prevClose)
        );
        if (Number.isFinite(tr)) out.push(Math.max(0, tr / ref * 100));
    }
    return out;
}

function dmParamAssistantAtrPct(candles, period) {
    var tr = dmParamAssistantTrueRangePcts(candles);
    if (!tr.length) return null;
    var n = Math.max(1, Math.min(period || 14, tr.length));
    return dmParamAssistantMean(tr.slice(-n));
}

function dmParamAssistantReturnPct(candles) {
    if (!candles || candles.length < 2) return null;
    var first = Number(candles[0].c);
    var last = Number(candles[candles.length - 1].c);
    if (!(first > 0) || !(last > 0)) return null;
    return (last - first) / first * 100;
}

function dmParamAssistantMaxDrawdownPct(candles) {
    var peak = null;
    var maxDd = 0;
    (candles || []).forEach(function (c) {
        var close = Number(c.c);
        if (!(close > 0)) return;
        if (peak == null || close > peak) peak = close;
        if (peak > 0) maxDd = Math.min(maxDd, (close - peak) / peak * 100);
    });
    return Math.abs(maxDd);
}

function dmParamAssistantEmaValues(values, period) {
    var clean = (values || []).filter(function (v) { return Number.isFinite(Number(v)); }).map(Number);
    if (!clean.length) return [];
    var n = Math.max(2, Math.min(period || 20, clean.length));
    var k = 2 / (n + 1);
    var ema = clean[0];
    var out = [ema];
    for (var i = 1; i < clean.length; i++) {
        ema = clean[i] * k + ema * (1 - k);
        out.push(ema);
    }
    return out;
}

function dmParamAssistantEmaSlopePct(candles, period, lookback) {
    var closes = (candles || []).map(function (c) { return Number(c.c); }).filter(function (v) { return v > 0; });
    if (closes.length < Math.max(4, period || 20)) return null;
    var ema = dmParamAssistantEmaValues(closes, period || 20);
    var lb = Math.max(1, Math.min(lookback || 5, ema.length - 1));
    var base = ema[ema.length - 1 - lb];
    var last = ema[ema.length - 1];
    if (!(base > 0)) return null;
    return (last - base) / base * 100;
}

function dmParamAssistantRsi(candles, period) {
    var closes = (candles || []).map(function (c) { return Number(c.c); }).filter(function (v) { return v > 0; });
    var n = period || 14;
    if (closes.length <= n) return null;
    var gains = 0;
    var losses = 0;
    for (var i = closes.length - n; i < closes.length; i++) {
        var diff = closes[i] - closes[i - 1];
        if (diff >= 0) gains += diff;
        else losses += Math.abs(diff);
    }
    if (losses === 0) return 100;
    var rs = gains / losses;
    return 100 - (100 / (1 + rs));
}

function dmParamAssistantBbw(candles, period) {
    var closes = (candles || []).map(function (c) { return Number(c.c); }).filter(function (v) { return v > 0; });
    var n = Math.max(5, Math.min(period || 20, closes.length));
    if (closes.length < n) return null;
    var slice = closes.slice(-n);
    var mean = dmParamAssistantMean(slice);
    var std = dmParamAssistantStd(slice);
    if (!(mean > 0) || std == null) return null;
    return (4 * std / mean) * 100;
}

function dmParamAssistantAdx(candles, period) {
    var n = period || 14;
    if (!candles || candles.length < n + 2) return null;
    var plusDm = [];
    var minusDm = [];
    var tr = [];
    for (var i = 1; i < candles.length; i++) {
        var cur = candles[i];
        var prev = candles[i - 1];
        var upMove = Number(cur.h) - Number(prev.h);
        var downMove = Number(prev.l) - Number(cur.l);
        plusDm.push(upMove > downMove && upMove > 0 ? upMove : 0);
        minusDm.push(downMove > upMove && downMove > 0 ? downMove : 0);
        tr.push(Math.max(
            Number(cur.h) - Number(cur.l),
            Math.abs(Number(cur.h) - Number(prev.c)),
            Math.abs(Number(cur.l) - Number(prev.c))
        ));
    }
    if (tr.length < n) return null;
    var dx = [];
    for (var j = n - 1; j < tr.length; j++) {
        var trAvg = dmParamAssistantMean(tr.slice(j - n + 1, j + 1));
        if (!(trAvg > 0)) continue;
        var plus = 100 * (dmParamAssistantMean(plusDm.slice(j - n + 1, j + 1)) || 0) / trAvg;
        var minus = 100 * (dmParamAssistantMean(minusDm.slice(j - n + 1, j + 1)) || 0) / trAvg;
        var denom = plus + minus;
        if (denom > 0) dx.push(100 * Math.abs(plus - minus) / denom);
    }
    if (!dx.length) return null;
    return dmParamAssistantMean(dx.slice(-n));
}

function dmParamAssistantVolumeZ(candles, lookback) {
    if (!candles || candles.length < 8) return null;
    var n = Math.max(5, Math.min(lookback || 30, candles.length - 1));
    var latest = Number(candles[candles.length - 1].v);
    var prev = candles.slice(-(n + 1), -1).map(function (c) { return Number(c.v); }).filter(function (v) { return Number.isFinite(v); });
    var mean = dmParamAssistantMean(prev);
    var std = dmParamAssistantStd(prev);
    if (mean == null || !(std > 0) || !Number.isFinite(latest)) return null;
    return (latest - mean) / std;
}

function dmParamAssistantRangeEfficiency(candles) {
    if (!candles || candles.length < 3) return null;
    var total = dmParamAssistantReturnPct(candles);
    var absMoves = dmParamAssistantCloseReturns(candles).reduce(function (sum, v) { return sum + Math.abs(v); }, 0);
    if (!(absMoves > 0) || total == null) return null;
    return dmParamAssistantClamp(Math.abs(total) / absMoves, 0, 1);
}

function dmParamAssistantDownsideVol(candles) {
    var downs = dmParamAssistantCloseReturns(candles).filter(function (v) { return v < 0; });
    return dmParamAssistantStd(downs);
}

function dmParamAssistantWindowMetrics(dailyCandles, days, label) {
    var candles = dmParamAssistantSliceDays(dailyCandles || [], days);
    var ranges = dmParamAssistantRangePcts(candles);
    var returns = dmParamAssistantCloseReturns(candles);
    var period = Math.min(20, Math.max(5, Math.floor(candles.length / 4)));
    var spanDays = 0;
    if (candles.length > 1) {
        spanDays = Math.max(1, (Number(candles[candles.length - 1].t) - Number(candles[0].t)) / DM_PARAM_ASSISTANT_DAY_MS + 1);
    } else if (candles.length === 1) {
        spanDays = 1;
    }
    var barCoverage = days > 0 ? candles.length / days : 0;
    var timeCoverage = days > 0 ? spanDays / days : 0;
    var coverage = dmParamAssistantClamp(Math.min(barCoverage, timeCoverage), 0, 1);
    return {
        label: label,
        days: days,
        bars: candles.length,
        spanDays: spanDays,
        coverage: coverage,
        sufficient: coverage >= 0.55 && candles.length >= Math.min(days * 0.5, 30),
        returnPct: dmParamAssistantReturnPct(candles),
        atrPct: dmParamAssistantAtrPct(candles, Math.min(14, Math.max(3, candles.length - 1))),
        medianRangePct: dmParamAssistantPercentile(ranges, 0.5),
        p70RangePct: dmParamAssistantPercentile(ranges, 0.7),
        realizedVolPct: dmParamAssistantStd(returns),
        downsideVolPct: dmParamAssistantDownsideVol(candles),
        maxDrawdownPct: dmParamAssistantMaxDrawdownPct(candles),
        emaSlopePct: dmParamAssistantEmaSlopePct(candles, Math.max(8, period), Math.min(10, Math.max(2, Math.floor(candles.length / 10)))),
        rsi: dmParamAssistantRsi(candles, 14),
        bbwPct: dmParamAssistantBbw(candles, 20),
        adx: dmParamAssistantAdx(candles, 14),
        efficiency: dmParamAssistantRangeEfficiency(candles)
    };
}

function dmParamAssistantApiFetch(path, fetchOptions, timeoutMs) {
    fetchOptions = fetchOptions || {};
    var controller = null;
    var timeoutId = null;
    if (timeoutMs > 0 && typeof AbortController !== 'undefined') {
        controller = new AbortController();
        fetchOptions.signal = controller.signal;
        timeoutId = setTimeout(function () { controller.abort(); }, timeoutMs);
    }
    return fetch(path, fetchOptions).then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
    }).finally(function () {
        if (timeoutId) clearTimeout(timeoutId);
    });
}

function dmParamAssistantApiGet(path, options) {
    options = options || {};
    if (window.apiClient && typeof window.apiClient.get === 'function') return window.apiClient.get(path, options);
    return dmParamAssistantApiFetch(path, { credentials: 'same-origin' }, options.timeout || 0);
}

async function dmParamAssistantFetchKlines(symbol, interval, limit, endTime) {
    var qs = '?symbol=' + encodeURIComponent(symbol) + '&interval=' + encodeURIComponent(interval || '1d') + '&limit=' + encodeURIComponent(String(Math.max(1, Math.min(500, limit || 500))));
    if (endTime != null && Number.isFinite(Number(endTime))) qs += '&end_time=' + encodeURIComponent(String(Math.floor(Number(endTime))));
    var data = await dmParamAssistantApiGet('/api/spot/klines' + qs);
    return dmParamAssistantCandleList(data);
}

async function dmParamAssistantFetchDailyHistory(symbol, days) {
    var all = [];
    var endTime = null;
    var chunks = Math.max(1, Math.min(5, Math.ceil((days || 1460) / 500) + 1));
    for (var i = 0; i < chunks; i++) {
        var part = await dmParamAssistantFetchKlines(symbol, '1d', 500, endTime);
        if (!part.length) break;
        all = dmParamAssistantDedupeCandles(all.concat(part));
        endTime = part[0].t - 1;
        if (all.length >= days + 20 || part.length < 490) break;
    }
    var sorted = dmParamAssistantDedupeCandles(all);
    if (sorted.length > days + 30) sorted = sorted.slice(-(days + 30));
    return sorted;
}

function dmParamAssistantWithTimeout(promise, ms) {
    return new Promise(function (resolve) {
        var settled = false;
        var timer = setTimeout(function () {
            if (settled) return;
            settled = true;
            resolve({ timeout: true, value: null });
        }, ms);
        Promise.resolve(promise).then(function (value) {
            if (settled) return;
            settled = true;
            clearTimeout(timer);
            resolve({ timeout: false, value: value });
        }).catch(function (error) {
            if (settled) return;
            settled = true;
            clearTimeout(timer);
            resolve({ timeout: false, error: error, value: null });
        });
    });
}

async function dmParamAssistantLoadMarketContext(symbol, onStatus) {
    var key = (symbol || '').toUpperCase();
    var cached = dmParamAssistantHistoryCache[key];
    if (cached && cached.ts && (Date.now() - cached.ts) < DM_PARAM_ASSISTANT_HISTORY_TTL_MS) {
        return cached.value;
    }
    function status(text) {
        if (typeof onStatus === 'function') onStatus(text);
    }
    status('1 ay / 3 ay / 1 yıl / 4 yıl geçmiş taranıyor');
    var dailyPromise = dmParamAssistantFetchDailyHistory(key, 1460);
    var m5Promise = dmParamAssistantFetchKlines(key, '5m', 288);
    var hourlyPromise = dmParamAssistantFetchKlines(key, '1h', 500);
    var settled = await dmParamAssistantWithTimeout(Promise.allSettled([dailyPromise, m5Promise, hourlyPromise]), DM_PARAM_ASSISTANT_HISTORY_TIMEOUT_MS);
    var ctx = { daily: [], m5: [], hourly: [], errors: [], timeout: !!settled.timeout };
    if (!settled.timeout && Array.isArray(settled.value)) {
        var results = settled.value;
        ctx.daily = results[0] && results[0].status === 'fulfilled' ? results[0].value : [];
        ctx.m5 = results[1] && results[1].status === 'fulfilled' ? results[1].value : [];
        ctx.hourly = results[2] && results[2].status === 'fulfilled' ? results[2].value : [];
        results.forEach(function (r) { if (r && r.status === 'rejected') ctx.errors.push(String(r.reason || 'veri alınamadı')); });
    } else {
        ctx.errors.push('Geçmiş veri zaman aşımına uğradı; hızlı ekran verisiyle devam edildi.');
    }
    ctx.daily = dmParamAssistantDedupeCandles(ctx.daily);
    ctx.m5 = dmParamAssistantDedupeCandles(ctx.m5);
    ctx.hourly = dmParamAssistantDedupeCandles(ctx.hourly);
    dmParamAssistantHistoryCache[key] = { ts: Date.now(), value: ctx };
    return ctx;
}

function dmParamAssistantBuildMarketAnalysis(snapshot, marketCtx) {
    var daily = (marketCtx && marketCtx.daily) || [];
    var hourly = (marketCtx && marketCtx.hourly) || [];
    var m5 = (marketCtx && marketCtx.m5) || [];
    var dataIssues = [];
    var windows = {
        m1: dmParamAssistantWindowMetrics(daily, 30, '1 ay'),
        m3: dmParamAssistantWindowMetrics(daily, 90, '3 ay'),
        y1: dmParamAssistantWindowMetrics(daily, 365, '1 yıl'),
        y4: dmParamAssistantWindowMetrics(daily, 1460, '4 yıl')
    };
    var range24Unit = Number(snapshot.rangePct);
    if (!Number.isFinite(range24Unit) || range24Unit <= 0) {
        var absPct = Math.abs(dmParamAssistantNum(snapshot.changePct, 0));
        range24Unit = Math.max(1.0, absPct * 1.8);
    }
    var hourlyAtr = dmParamAssistantAtrPct(hourly, 24);
    var m5Atr = dmParamAssistantAtrPct(m5, 48);
    var m5Range = dmParamAssistantPercentile(dmParamAssistantRangePcts(m5), 0.65);
    var dailyAtr30 = windows.m1.atrPct;
    var dailyRange30 = windows.m1.medianRangePct;
    var dailyRange90 = windows.m3.medianRangePct;
    var volUnit = dmParamAssistantWeightedMean([
        { value: range24Unit / 4.2, weight: 1.2 },
        { value: hourlyAtr == null ? null : hourlyAtr * 0.95, weight: 1.15 },
        { value: m5Atr == null ? null : m5Atr * 4.2, weight: 0.55 },
        { value: m5Range == null ? null : m5Range * 3.4, weight: 0.35 },
        { value: dailyAtr30 == null ? null : dailyAtr30 * 0.22, weight: 1.0 },
        { value: dailyRange30 == null ? null : dailyRange30 * 0.20, weight: 1.0 },
        { value: dailyRange90 == null ? null : dailyRange90 * 0.18, weight: 0.75 }
    ], Math.max(0.45, Math.min(2.2, range24Unit / 4.0)));
    volUnit = dmParamAssistantClamp(volUnit, 0.25, 4.6);

    var hourlySlope = dmParamAssistantEmaSlopePct(hourly, 50, 12);
    var m5Slope = dmParamAssistantEmaSlopePct(m5, 48, 24);
    var adx = dmParamAssistantWeightedMean([
        { value: dmParamAssistantAdx(hourly, 14), weight: 1.2 },
        { value: windows.m1.adx, weight: 0.9 },
        { value: windows.m3.adx, weight: 0.65 }
    ], null);
    var bbw = dmParamAssistantWeightedMean([
        { value: dmParamAssistantBbw(hourly, 20), weight: 0.9 },
        { value: windows.m1.bbwPct, weight: 0.7 },
        { value: windows.m3.bbwPct, weight: 0.45 }
    ], null);
    var rsi = dmParamAssistantWeightedMean([
        { value: dmParamAssistantRsi(hourly, 14), weight: 1.0 },
        { value: windows.m1.rsi, weight: 0.7 }
    ], null);
    var volumeZ = dmParamAssistantWeightedMean([
        { value: dmParamAssistantVolumeZ(hourly, 72), weight: 0.8 },
        { value: dmParamAssistantVolumeZ(daily, 30), weight: 0.5 }
    ], null);
    var trendScore = dmParamAssistantWeightedMean([
        { value: dmParamAssistantClamp(dmParamAssistantNum(snapshot.changePct, 0) / 4, -1, 1), weight: 0.55 },
        { value: hourlySlope == null ? null : dmParamAssistantClamp(hourlySlope / 2.5, -1, 1), weight: 1.05 },
        { value: m5Slope == null ? null : dmParamAssistantClamp(m5Slope / 1.6, -1, 1), weight: 0.35 },
        { value: windows.m1.returnPct == null ? null : dmParamAssistantClamp(windows.m1.returnPct / 18, -1, 1), weight: 0.9 },
        { value: windows.m3.returnPct == null ? null : dmParamAssistantClamp(windows.m3.returnPct / 32, -1, 1), weight: 0.75 },
        { value: windows.y1.returnPct == null ? null : dmParamAssistantClamp(windows.y1.returnPct / 80, -1, 1), weight: 0.45 },
        { value: windows.m1.emaSlopePct == null ? null : dmParamAssistantClamp(windows.m1.emaSlopePct / 4.5, -1, 1), weight: 0.75 },
        { value: windows.m3.emaSlopePct == null ? null : dmParamAssistantClamp(windows.m3.emaSlopePct / 7.5, -1, 1), weight: 0.55 }
    ], 0);
    trendScore = dmParamAssistantClamp(trendScore, -1, 1);

    var chopScore = dmParamAssistantWeightedMean([
        { value: windows.m1.efficiency == null ? null : 1 - windows.m1.efficiency, weight: 1.1 },
        { value: windows.m3.efficiency == null ? null : 1 - windows.m3.efficiency, weight: 0.9 },
        { value: bbw == null ? null : dmParamAssistantClamp(bbw / 10, 0, 1), weight: 0.45 }
    ], 0.55);
    var riskScore = dmParamAssistantWeightedMean([
        { value: dmParamAssistantClamp((windows.m1.maxDrawdownPct || 0) / 22, 0, 1), weight: 0.85 },
        { value: dmParamAssistantClamp((windows.m3.maxDrawdownPct || 0) / 36, 0, 1), weight: 0.8 },
        { value: dmParamAssistantClamp((windows.y1.maxDrawdownPct || 0) / 60, 0, 1), weight: 0.45 },
        { value: dmParamAssistantClamp((windows.m1.downsideVolPct || 0) / 4, 0, 1), weight: 0.45 },
        { value: dmParamAssistantClamp(Math.max(0, -trendScore), 0, 1), weight: 0.55 }
    ], 0.35);
    var opportunityScore = dmParamAssistantWeightedMean([
        { value: dmParamAssistantClamp(volUnit / 2.3, 0, 1), weight: 0.75 },
        { value: dmParamAssistantClamp(chopScore, 0, 1), weight: 0.85 },
        { value: dmParamAssistantClamp(1 - riskScore * 0.45, 0, 1), weight: 0.55 }
    ], 0.55);

    var code = 'LOW_VOL_RANGING';
    var label = 'sakin yatay';
    if (dmParamAssistantNum(snapshot.changePct, 0) <= -3.0 || (windows.m1.returnPct != null && windows.m1.returnPct <= -18 && riskScore >= 0.55)) {
        code = 'DUMP_RISK';
        label = 'sert düşüş riski';
    } else if ((adx != null && adx >= 24 && trendScore >= 0.28) || trendScore >= 0.48) {
        code = 'TRENDING_UP';
        label = 'yukarı trend';
    } else if ((adx != null && adx >= 24 && trendScore <= -0.28) || trendScore <= -0.48) {
        code = 'TRENDING_DOWN';
        label = 'aşağı baskı';
    } else if ((bbw != null && bbw <= 2.5) || volUnit <= 0.48) {
        code = 'SQUEEZE';
        label = 'sıkışma';
    } else if (volUnit >= 1.65) {
        code = 'HIGH_VOL_RANGING';
        label = 'yüksek volatil yatay';
    } else {
        code = 'LOW_VOL_RANGING';
        label = 'yatay / dalgalı';
    }
    if (code !== 'DUMP_RISK' && dmParamAssistantNum(snapshot.changePct, 0) >= 2.8 && volumeZ != null && volumeZ >= 1.7 && trendScore > 0.18) {
        code = 'BREAKOUT';
        label = 'breakout adayı';
    }

    var coverage = dmParamAssistantWeightedMean([
        { value: windows.m1.coverage, weight: 0.22 },
        { value: windows.m3.coverage, weight: 0.24 },
        { value: windows.y1.coverage, weight: 0.28 },
        { value: windows.y4.coverage, weight: 0.16 },
        { value: hourly.length >= 160 ? 1 : hourly.length / 160, weight: 0.06 },
        { value: m5.length >= 180 ? 1 : m5.length / 180, weight: 0.04 }
    ], 0.18);
    var agreement = dmParamAssistantClamp(1 - Math.abs(trendScore) * (adx != null && adx < 16 ? 0.45 : 0.16), 0.52, 1);
    if ((trendScore > 0 && windows.m1.returnPct != null && windows.m1.returnPct < -4) || (trendScore < 0 && windows.m1.returnPct != null && windows.m1.returnPct > 4)) agreement -= 0.12;
    agreement = dmParamAssistantClamp(agreement, 0.35, 1);
    var confidence = Math.round(dmParamAssistantClamp(48 + coverage * 28 + agreement * 16 + opportunityScore * 12 - riskScore * 10, 45, 96));
    var nowMs = Date.now();
    var latestM5 = m5.length ? m5[m5.length - 1] : null;
    var latestHourly = hourly.length ? hourly[hourly.length - 1] : null;
    var latestDaily = daily.length ? daily[daily.length - 1] : null;
    if (!marketCtx || !marketCtx.ticker || marketCtx.ticker.available === false) {
        dataIssues.push('24s ticker doğrulanamadı');
    }
    if (latestM5 && nowMs - Number(latestM5.t) > 45 * 60 * 1000) {
        dataIssues.push('5 dakikalık veri güncel değil');
    }
    if (latestHourly && nowMs - Number(latestHourly.t) > 4 * 60 * 60 * 1000) {
        dataIssues.push('saatlik veri güncel değil');
    }
    if (latestDaily && nowMs - Number(latestDaily.t) > 60 * 60 * 60 * 1000) {
        dataIssues.push('günlük veri güncel değil');
    }
    var latestClose = latestM5 && Number(latestM5.c) > 0 ? Number(latestM5.c) : (latestHourly && Number(latestHourly.c) > 0 ? Number(latestHourly.c) : (latestDaily && Number(latestDaily.c) > 0 ? Number(latestDaily.c) : null));
    if (Number(snapshot.price) > 0 && latestClose > 0) {
        var priceDiffPct = Math.abs(Number(snapshot.price) - latestClose) / Number(snapshot.price) * 100;
        if (priceDiffPct > 3.5) dataIssues.push('canlı fiyat ile mum kapanışı uyuşmuyor');
    }
    if (!windows.m1.sufficient) dataIssues.push('1 ay penceresi eksik');
    if (!windows.m3.sufficient) dataIssues.push('3 ay penceresi eksik');
    if (!windows.y1.sufficient) dataIssues.push('1 yıl penceresi eksik');
    if (!windows.y4.sufficient) dataIssues.push('4 yıl penceresi eksik');
    if (marketCtx && marketCtx.localFallback) {
        // Yerel hızlı öneri gerçek strateji backtest'i değildir; skor veri kalitesi iyi olsa bile
        // uygulama güveni gibi okunmamalı.
        confidence = Math.min(confidence, dataIssues.length ? 52 : 72);
    }
    // Geçmiş veri hiç çekilemediyse (sunucu yoğun / klines zaman aşımı) ADX/RSI/risk
    // okumaları gerçek değil, sadece "veri yok" varsayılanı (0). Bu durumda 45 güven
    // tabanı YANILTICI olur; güveni dürüstçe dibe çek ve aşağıda açıkça uyar.
    var insufficientData = daily.length < 30 || !windows.m1.sufficient || !windows.m3.sufficient || (marketCtx && marketCtx.localFallback && dataIssues.length >= 3);
    if (insufficientData) {
        confidence = Math.min(confidence, daily.length <= 0 ? 6 : 20);
    }

    return {
        windows: windows,
        range24Unit: range24Unit,
        hourlyAtr: hourlyAtr,
        m5Atr: m5Atr,
        volUnit: volUnit,
        trendScore: trendScore,
        chopScore: chopScore,
        riskScore: riskScore,
        opportunityScore: opportunityScore,
        regimeCode: code,
        regimeLabel: label,
        adx: adx,
        bbw: bbw,
        rsi: rsi,
        volumeZ: volumeZ,
        coverage: coverage,
        confidence: confidence,
        insufficientData: insufficientData,
        dataIssues: dataIssues,
        dataBars: {
            daily: daily.length,
            hourly: hourly.length,
            m5: m5.length
        },
        partial: !!(marketCtx && (marketCtx.timeout || (marketCtx.errors && marketCtx.errors.length) || dataIssues.length))
    };
}

function dmParamAssistantBuildRecommendation(snapshot, marketCtx) {
    var analysis = dmParamAssistantBuildMarketAnalysis(snapshot, marketCtx || {});
    var windows = analysis.windows || {};
    var budget = Number(snapshot.currentBudget);
    if (!Number.isFinite(budget) || budget < 25) {
        var available = Number(snapshot.availableQuote);
        if (Number.isFinite(available) && available >= 25) budget = Math.min(available, 50);
        else budget = 50;
    }
    budget = dmParamAssistantRound(Math.max(25, budget), 2);

    var maxSafeCount = Math.floor((budget * 0.5 * 0.995) / 10.05);
    maxSafeCount = Math.max(1, Math.min(4, maxSafeCount));
    var targetCount = maxSafeCount >= 3 ? 3 : maxSafeCount;
    if (analysis.volUnit >= 1.65 && budget >= 75) targetCount = Math.max(targetCount, Math.min(3, maxSafeCount));
    if (analysis.volUnit >= 2.8 && budget >= 130) targetCount = Math.max(targetCount, Math.min(4, maxSafeCount));
    if (analysis.regimeCode === 'DUMP_RISK' && targetCount > 2) targetCount = 2;
    if (analysis.regimeCode === 'TRENDING_UP' && analysis.chopScore < 0.42 && targetCount > 2) targetCount = 2;
    var count = Math.max(1, Math.min(targetCount, maxSafeCount));

    var baseByRegime = {
        LOW_VOL_RANGING: 50,
        HIGH_VOL_RANGING: 42,
        TRENDING_UP: 58,
        TRENDING_DOWN: 34,
        SQUEEZE: 46,
        BREAKOUT: 54,
        DUMP_RISK: 24
    };
    var basePct = baseByRegime[analysis.regimeCode] || 50;
    if (budget < 70) basePct = 50;
    if (analysis.trendScore > 0.55 && budget >= 90) basePct += 3;
    if (analysis.trendScore < -0.55 && budget >= 90) basePct -= 3;
    basePct = dmParamAssistantClamp(basePct, 20, 65);
    var quotePct = 100 - basePct;

    function legSafe(p, levels) {
        return (budget * (p / 100) * 0.995 / Math.max(1, levels || count)) > 10.05;
    }
    while (count > 1 && (!legSafe(basePct, count) || !legSafe(quotePct, count))) count -= 1;
    if (!legSafe(basePct, count) || !legSafe(quotePct, count)) {
        basePct = 50;
        quotePct = 50;
        while (count > 1 && (!legSafe(basePct, count) || !legSafe(quotePct, count))) count -= 1;
    }

    var feeFloorPct = 0.28;
    var longTermMinStepPct = 1.35;
    var regimeStepMult = {
        LOW_VOL_RANGING: 1.18,
        HIGH_VOL_RANGING: 1.55,
        TRENDING_UP: 1.45,
        TRENDING_DOWN: 1.75,
        SQUEEZE: 1.25,
        BREAKOUT: 1.85,
        DUMP_RISK: 2.15
    };
    var longSwingAnchor = dmParamAssistantWeightedMean([
        { value: windows.m1 && windows.m1.medianRangePct != null ? windows.m1.medianRangePct * 0.55 : null, weight: 0.8 },
        { value: windows.m3 && windows.m3.medianRangePct != null ? windows.m3.medianRangePct * 0.58 : null, weight: 0.9 },
        { value: windows.y1 && windows.y1.medianRangePct != null ? windows.y1.medianRangePct * 0.5 : null, weight: 0.45 },
        { value: analysis.volUnit, weight: 0.6 }
    ], analysis.volUnit);
    var stepRaw = Math.max(longTermMinStepPct, longSwingAnchor * (regimeStepMult[analysis.regimeCode] || 1));
    var drawdownAdd = analysis.riskScore >= 0.6 ? 0.35 : 0;
    var maxStepByDepth = Math.max(longTermMinStepPct, 18.0 / Math.max(1, count));
    var step = dmParamAssistantClamp(stepRaw + drawdownAdd, longTermMinStepPct, Math.min(7.5, maxStepByDepth));
    if (analysis.regimeCode === 'SQUEEZE') step = dmParamAssistantClamp(step, longTermMinStepPct, 2.4);
    if (analysis.regimeCode === 'DUMP_RISK') step = Math.max(step, 2.2);
    step = dmParamAssistantRound(step, 2);

    var trailRatio = {
        LOW_VOL_RANGING: 0.38,
        HIGH_VOL_RANGING: 0.42,
        TRENDING_UP: 0.50,
        TRENDING_DOWN: 0.40,
        SQUEEZE: 0.36,
        BREAKOUT: 0.50,
        DUMP_RISK: 0.34
    };
    var shortAtr = dmParamAssistantWeightedMean([
        { value: analysis.hourlyAtr, weight: 0.8 },
        { value: analysis.m5Atr == null ? null : analysis.m5Atr * 3.0, weight: 0.4 }
    ], analysis.volUnit * 0.55);
    var trail = dmParamAssistantClamp(step * (trailRatio[analysis.regimeCode] || 0.4) + shortAtr * 0.10, 0.20, Math.min(2.5, Math.max(0.28, step * 0.68)));
    trail = dmParamAssistantRound(trail, 2);

    var rebuyMult = analysis.trendScore >= 0.25 ? 1.32 : 1.58;
    var resellMult = analysis.trendScore >= 0.25 ? 1.92 : 1.58;
    if (analysis.regimeCode === 'DUMP_RISK') {
        rebuyMult = 1.95;
        resellMult = 1.35;
    } else if (analysis.regimeCode === 'BREAKOUT') {
        rebuyMult = 1.28;
        resellMult = 2.10;
    } else if (analysis.regimeCode === 'SQUEEZE') {
        rebuyMult = 1.45;
        resellMult = 1.65;
    }
    var rebuyTrigger = dmParamAssistantRound(dmParamAssistantClamp(step * rebuyMult + feeFloorPct * 0.35, 0.85, 6.5), 2);
    var rebuyTrail = dmParamAssistantRound(dmParamAssistantClamp(trail * 0.88, 0.20, 1.8), 2);
    var resellTrigger = dmParamAssistantRound(dmParamAssistantClamp(step * resellMult + feeFloorPct * 0.4, 0.95, 7.0), 2);
    var resellTrail = dmParamAssistantRound(dmParamAssistantClamp(step * 0.52 + trail * 0.22, 0.25, 2.5), 2);

    var qtys = dmParamAssistantQtys(count);
    var upGrids = [];
    var downGrids = [];
    var depthGrowth = analysis.regimeCode === 'DUMP_RISK' ? 1.55 : (analysis.regimeCode === 'TRENDING_DOWN' ? 1.42 : 1.35);
    var sellDepthGrowth = analysis.regimeCode === 'BREAKOUT' ? 1.38 : depthGrowth;
    // Alış gridi referans fiyattan MUTLAK düşüş %'sidir; spot piyasada fiyat en
    // fazla %100 düşer (sıfıra iner). %100+ alış tetiği matematiksel olarak imkânsız
    // ve asla dolmayacak ölü bir seviyedir -> bu eşiği aşan alış seviyelerini at.
    var DM_MAX_BUY_DEPTH_PCT = 92;
    for (var i = 0; i < count; i++) {
        var sellTrigger = dmParamAssistantRound(step * Math.pow(sellDepthGrowth, i), 2);
        var buyTrigger = dmParamAssistantRound(step * Math.pow(depthGrowth, i), 2);
        upGrids.push({ trigger_pct: sellTrigger, qty_pct: qtys[i] });
        if (buyTrigger < DM_MAX_BUY_DEPTH_PCT) {
            downGrids.push({ trigger_pct: buyTrigger });
        }
    }
    if (!downGrids.length) {
        downGrids.push({ trigger_pct: dmParamAssistantRound(Math.min(step, DM_MAX_BUY_DEPTH_PCT - 0.5), 2) });
    }
    var downQtys = dmParamAssistantQtys(downGrids.length);
    downGrids.forEach(function (g, j) { g.qty_pct = downQtys[j]; });
    upGrids = upGrids.slice(0, count);
    if (upGrids.length) {
        var upQtys = dmParamAssistantNormalizeQtys(upGrids.map(function (g) { return g.qty_pct; }));
        upGrids.forEach(function (g, j) { g.qty_pct = upQtys[j]; });
    }

    var volatility = analysis.volUnit >= 2.1 ? 'yüksek' : (analysis.volUnit >= 0.85 ? 'orta' : 'sakin');
    return {
        budget: budget,
        basePct: dmParamAssistantRound(basePct, 1),
        quotePct: dmParamAssistantRound(quotePct, 1),
        upTrail: trail,
        downTrail: trail,
        upGrids: upGrids,
        downGrids: downGrids,
        rebuyTrigger: rebuyTrigger,
        rebuyTrail: rebuyTrail,
        resellTrigger: resellTrigger,
        resellTrail: resellTrail,
        rangePct: dmParamAssistantRound(analysis.range24Unit, 2),
        volatility: volatility,
        regime: analysis.regimeLabel,
        confidence: analysis.confidence,
        analysis: analysis,
        math: {
            feeFloorPct: feeFloorPct,
            volUnit: dmParamAssistantRound(analysis.volUnit, 2),
            stepRaw: dmParamAssistantRound(stepRaw, 2),
            stepPct: step,
            trailPct: trail,
            riskScore: dmParamAssistantRound(analysis.riskScore * 100, 0),
            opportunityScore: dmParamAssistantRound(analysis.opportunityScore * 100, 0)
        }
    };
}

function dmParamAssistantGridText(grids, sign) {
    return grids.map(function (g, idx) {
        return '#' + (idx + 1) + ' ' + sign + dmParamAssistantInputTextTr(g.trigger_pct, 2) + '% / miktar %' + dmParamAssistantInputTextTr(g.qty_pct, 1);
    }).join(', ');
}

function dmParamAssistantMetricPct(v, digits, opts) {
    opts = opts || {};
    var n = Number(v);
    if (!Number.isFinite(n)) return '—';
    var s = dmParamAssistantInputTextTr(Math.abs(n), digits == null ? 2 : digits);
    if (opts.noSign) return '%' + s;
    return (n >= 0 ? '+' : '-') + '%' + s;
}

function dmParamAssistantWindowText(metric) {
    if (!metric || !metric.bars) return metric && metric.label ? metric.label + ': veri yok' : 'veri yok';
    if (!metric.sufficient) {
        var covered = metric.spanDays ? Math.round(metric.spanDays) + ' gün' : metric.bars + ' mum';
        return metric.label + ': veri yetersiz (' + covered + ' kapsama)';
    }
    return metric.label + ': getiri ' + dmParamAssistantMetricPct(metric.returnPct, 2) +
        ', medyan gün içi bant ' + dmParamAssistantMetricPct(metric.medianRangePct, 2, { noSign: true }) +
        ', maks. geri çekilme ' + dmParamAssistantMetricPct(metric.maxDrawdownPct, 2, { noSign: true });
}

function dmParamAssistantIsV6Result(backend) {
    var r = backend || {};
    var tel = r.telemetry || {};
    var sel = r.selection_telemetry || {};
    if (tel.v6_display || tel.pool_version === 'v6') return true;
    if (sel.pool_version === 'v6') return true;
    var ui = r.ui_config || {};
    if (ui.profile_display && String(ui.profile_display).indexOf('DPLV6_') === 0) return true;
    if (r.profile_tile_label === 'V6 Profil Kimliği') return true;
    return false;
}

function dmParamAssistantProfileTileLabel(backend) {
    if (backend && backend.profile_tile_label) return backend.profile_tile_label;
    if (dmParamAssistantIsV6Result(backend)) return 'V6 Profil Kimliği';
    return 'Raf (V5)';
}

function dmParamAssistantCoverageText(analysis) {
    if (!analysis) return 'sınırlı';
    if (analysis.v6DataQualityLabel) return analysis.v6DataQualityLabel;
    if (analysis.coverage >= 0.82) return 'çok güçlü';
    if (analysis.coverage >= 0.58) return 'yeterli';
    if (analysis.coverage >= 0.34) return 'orta';
    return 'sınırlı';
}

var DM_PARAM_ASSISTANT_GREETING_POOL = (
    AI_ASSISTANT_SPEC.paramAssistant && AI_ASSISTANT_SPEC.paramAssistant.greetingPool
) || [
    'Selam {name}, ben parametre asistanın. {symbol} için canlı fiyatı ve geçmiş pencereleri birlikte okuyorum.',
    'Merhaba {name}, {symbol} için kontrollü, veriye dayalı bir parametre seti hazırlıyorum.'
];

function dmParamAssistantCleanName(name) {
    var s = (name == null ? '' : String(name)).trim();
    if (!s || s === '—' || s === '-' || /^id:\s*/i.test(s)) return '';
    return s.replace(/\s+/g, ' ');
}

function dmParamAssistantCurrentUserName(snapshot) {
    var accountId = (typeof State !== 'undefined' && State) ? State.accountId : null;
    var accountCode = (typeof State !== 'undefined' && State) ? State.accountCode : null;
    var summary = (typeof State !== 'undefined' && State) ? State.summary : null;
    var candidates = [];
    try {
        if (typeof getLockedAppbarDisplayName === 'function') candidates.push(getLockedAppbarDisplayName(accountId));
        if (typeof getAppbarCachedDisplayName === 'function') candidates.push(getAppbarCachedDisplayName(accountId));
    } catch (e) {}
    if (summary) {
        var acc = summary.account || {};
        candidates.push([summary.user_name || acc.user_name, summary.user_surname || acc.user_surname].filter(Boolean).join(' '));
        candidates.push(summary.account_name || acc.name);
    }
    try {
        var cacheKeys = [];
        if (accountId != null && accountId !== '') {
            cacheKeys.push('appbarUserName_' + accountId);
            cacheKeys.push('dashboardAppbar_' + accountId);
            cacheKeys.push('dashboardAppbar_ls_' + accountId);
        }
        if (accountCode != null && accountCode !== '') {
            cacheKeys.push('dashboardAppbar_code_' + accountCode);
            cacheKeys.push('dashboardAppbar_code_ls_' + accountCode);
        }
        cacheKeys.forEach(function (key) {
            var raw = sessionStorage.getItem(key) || localStorage.getItem(key);
            if (!raw) return;
            if (raw.charAt(0) === '{') {
                try {
                    var obj = JSON.parse(raw);
                    candidates.push(obj && obj.displayName);
                } catch (e) {}
            } else {
                candidates.push(raw);
            }
        });
    } catch (e) {}
    try {
        var userStr = sessionStorage.getItem('user') || localStorage.getItem('user');
        if (userStr) {
            var user = JSON.parse(userStr);
            if (!accountId || user.account_id == null || String(user.account_id) === String(accountId)) {
                candidates.push([user.name, user.surname].filter(Boolean).join(' '));
                candidates.push(user.username);
            }
        }
    } catch (e) {}
    var appbarEl = document.getElementById('appbarUserName');
    if (appbarEl) candidates.push(appbarEl.textContent);
    for (var i = 0; i < candidates.length; i++) {
        var clean = dmParamAssistantCleanName(candidates[i]);
        if (clean) return clean;
    }
    return (AI_ASSISTANT_SPEC.copy && AI_ASSISTANT_SPEC.copy.fallbackUserName) || 'dostum';
}

function dmParamAssistantRandomIndex(max) {
    max = Math.max(1, Number(max) || 1);
    try {
        if (window.crypto && window.crypto.getRandomValues) {
            var arr = new Uint32Array(1);
            window.crypto.getRandomValues(arr);
            return arr[0] % max;
        }
    } catch (e) {}
    return Math.floor(Math.random() * max);
}

function dmParamAssistantActionLabel(code, backend) {
    if (backend && backend.final_action_label) return backend.final_action_label;
    var map = {
        SELL_MANAGEMENT_ONLY: 'Sadece satış yönetimi',
        WAIT: 'Bekle',
        WAIT_SAFETY: 'Güvenlik bekle',
        NO_TRADE: 'İşlem yok',
        DEFENSIVE_GRID: 'Savunmacı grid',
        BALANCED_GRID: 'Dengeli grid',
        ACTIVE_GRID: 'Aktif grid',
        ACTIVE_DEFENSIVE_GRID: 'Aktif savunmacı grid',
        LOW_FEE_WIDE_GRID: 'Geniş aralıklı grid',
        TREND_TRAILING: 'Trend trailing'
    };
    return map[String(code || '').toUpperCase()] || code || '—';
}

function dmParamAssistantGridCountLabel(rec) {
    var buyN = rec && rec.downGrids ? rec.downGrids.length : 0;
    var sellN = rec && rec.upGrids ? rec.upGrids.length : 0;
    return 'Alış ' + buyN + ' · Satış ' + sellN;
}

function dmParamAssistantAttrEscape(s) {
    return dmParamAssistantEscape(s).replace(/"/g, '&quot;');
}

var DM_PA_REGIME_TR = {
    R1: 'Güçlü yükseliş trendi',
    R2: 'Dengeli aralık',
    R3: 'Zayıf / gürültülü aralık',
    R4: 'Volatil aralık',
    R5: 'Toparlanma',
    R6: 'Tepe / dağılım / zayıflama',
    R7: 'Düşüş trendi',
    R8: 'Crash / sert düşüş',
    NO_DATA: 'Veri yetersiz',
    NO_TRADE: 'İşlem için uygun değil',
    DUMP_RISK: 'Sert düşüş riski',
    TRENDING_DOWN: 'Aşağı baskılı trend',
    HIGH_VOL_UNSTABLE: 'Yüksek volatilite / dengesiz',
    RANGE_LOW_VOL: 'Düşük volatilite aralık',
    RANGE_HIGH_VOL: 'Yüksek volatilite aralık',
    BALANCED_RANGE: 'Dengeli aralık',
    TRENDING_UP: 'Yükseliş trendi',
    BREAKOUT_RISK: 'Kırılım riski',
    LOW_LIQUIDITY: 'Düşük likidite',
    SPREAD_UNSAFE: 'Güvensiz spread'
};

var DM_PA_RISK_TR = {
    SAFE: 'Güvenli',
    NORMAL: 'Normal',
    CAUTION: 'Dikkatli',
    DEFENSIVE: 'Savunmacı',
    BLOCKED: 'Engelli'
};

var DM_PA_V6_MARKET_STATUS = {
    R1: 'Fiyat yükseliş trendinde, aktif fırsat var',
    R2: 'Fiyat yatay bölgede, iki yönlü fırsat var',
    R3: 'Fiyat gürültülü aralıkta, temkinli grid kullanılıyor',
    R4: 'Fiyat sert dalgalanıyor, gridler geniş tutuldu',
    R5: 'Toparlanma başlıyor, kontrollü alım fırsatı var',
    R6: 'Fiyat tepede, geri çekilme riski var',
    R7: 'Düşüş trendi var, savunmacı mod aktif',
    R8: 'Sert düşüş var, yüksek riskli savunmacı mod'
};

var DM_PA_RISK_TONE_PLAIN = {
    'Kontrollü savunmacı': 'Temkinli strateji',
    'Savunmacı': 'Temkinli strateji',
    'Normal': 'Dengeli strateji',
    'Aktif': 'Aktif strateji',
    'DEFENSIVE': 'Temkinli strateji',
    'NORMAL': 'Dengeli strateji',
    'CAUTION': 'Temkinli strateji',
    'AGGRESSIVE': 'Aktif strateji',
    'SAFE': 'Güvenli strateji',
    'BLOCKED': 'İşlem kapalı'
};

var DM_PA_CHIP_TIPS = {
    'Parite': 'Analiz edilen spot işlem çifti.',
    'Parametre çalışma skoru': 'Piyasa verisi, likidite, spread ve grid uygunluğunun birleşik skoru (0–100).',
    'Piyasa durumu': 'Motorun okuduğu piyasa özeti; botun neden temkinli veya aktif davrandığını anlatır.',
    'Rejim': 'Teknik rejim kodu; ayrıntılar panelinde gösterilir.',
    'Risk': 'Kısa vadeli downside risk durumu; NORMAL iken savunmacı mod zorunlu değildir.',
    'Karar': 'Bu koşulda canlıya uygulanacak nihai aksiyon.',
    'Piyasa güven skoru': 'Kararın veri kalitesi ve sinyal tutarlılığına dayalı güven skoru.',
    'Seçilen raf uyum skoru': 'Seçilen V5 rafının route imzası ve senaryo uyum skoru.',
    'Grid': 'Önerilen alış ve satış grid kademe sayısı.',
    'Raf (V5)': '192.780 raflı V5 kütüphaneden exact lookup ile seçilen DPLV5 shelf anahtarı.',
    'V6 Profil Kimliği': 'V6 katalogdan seçilen DPLV6 profil kimliği.',
    'Profil': 'V5 kütüphaneden seçilen raf (DPLV5 shelf ID).'
};

function dmParamAssistantRegimeLabel(tag) {
    var key = String(tag || '').toUpperCase();
    return DM_PA_REGIME_TR[key] || tag || '—';
}

function dmParamAssistantFormatConfidencePct(score) {
    if (score == null || score === '' || score === '—') return '—';
    var n = Number(score);
    if (!isFinite(n)) return '—';
    return '%' + Math.round(n);
}

function dmParamAssistantMarketStatusPlain(rec) {
    var r = (rec && rec.backend) || rec || {};
    var ui = r.ui_config || {};
    if (ui.market_status_plain) return ui.market_status_plain;
    if (r.market_status_plain) return r.market_status_plain;
    var align = (r.telemetry && r.telemetry.scenario_alignment) || ui.scenario_alignment || {};
    if (align.regime_label_plain) return align.regime_label_plain;
    var v6d = (r.telemetry && r.telemetry.v6_display) || {};
    if (v6d.market_status_plain) return v6d.market_status_plain;
    var regime = String(r.regime_tag || (rec && rec.regime) || '').toUpperCase();
    if (DM_PA_V6_MARKET_STATUS[regime]) return DM_PA_V6_MARKET_STATUS[regime];
    return dmParamAssistantRegimeLabel(regime) || 'Piyasa koşulları analiz edildi';
}

function dmParamAssistantRiskTonePlain(rec) {
    var r = (rec && rec.backend) || rec || {};
    var ui = r.ui_config || {};
    if (ui.risk_tone_plain) return ui.risk_tone_plain;
    if (r.risk_tone_plain) return r.risk_tone_plain;
    var v6d = (r.telemetry && r.telemetry.v6_display) || {};
    if (v6d.risk_tone_plain) return v6d.risk_tone_plain;
    var raw = dmParamAssistantRiskLabel(
        ui.effective_risk_state || r.effective_risk_state || r.risk_state || (rec && rec.riskState),
        r
    );
    return DM_PA_RISK_TONE_PLAIN[raw] || DM_PA_RISK_TONE_PLAIN[String(raw || '').toUpperCase()] || raw || 'Temkinli strateji';
}

function dmParamAssistantRegimeTechnicalLabel(rec) {
    var r = (rec && rec.backend) || rec || {};
    var ui = r.ui_config || {};
    if (ui.display_regime_technical) return ui.display_regime_technical;
    if (r.display_regime_technical) return r.display_regime_technical;
    var align = (r.telemetry && r.telemetry.scenario_alignment) || ui.scenario_alignment || {};
    if (align.regime_label) return align.regime_label;
    var v6d = (r.telemetry && r.telemetry.v6_display) || {};
    if (v6d.display_regime_technical) return v6d.display_regime_technical;
    var scen = v6d.scenario_identity || {};
    if (scen.name) return scen.name;
    return ui.display_regime_label || r.display_regime_label || '';
}

function dmParamAssistantRiskLabel(risk, backend) {
    if (backend) {
        if (backend.risk_display_label) return backend.risk_display_label;
        var tel = backend.telemetry || {};
        var v6d = tel.v6_display || {};
        if (v6d.risk_display_label) return v6d.risk_display_label;
    }
    var key = String(risk || '').toUpperCase();
    return DM_PA_RISK_TR[key] || risk || '—';
}

function dmParamAssistantMakeTile(label, value, tip, opts) {
    opts = opts || {};
    return { label: label, value: value, tip: tip || '', mono: opts.mono === true };
}

function dmParamAssistantExactShelfId(r) {
    r = r || {};
    if (r.exact_shelf_id) return String(r.exact_shelf_id);
    var tel = r.telemetry || {};
    var sel = r.selection_telemetry || tel.param_pool || {};
    var v6d = tel.v6_display || {};
    if (dmParamAssistantIsV6Result(r)) {
        return (
            r.v6_catalog_profile_id ||
            v6d.catalog_profile_id ||
            sel.catalog_profile_id ||
            r.selected_profile ||
            (tel.v6_final && tel.v6_final.catalog_profile_id) ||
            '—'
        );
    }
    var ctx = sel.selection_context || {};
    return ctx.v5_shelf_id || sel.selected_template_key || r.selected_profile || '—';
}

function dmParamAssistantFinalShelfId(r) {
    r = r || {};
    var tel = r.telemetry || {};
    var sel = r.selection_telemetry || tel.param_pool || {};
    var v6d = tel.v6_display || {};
    return (
        r.v6_final_profile_id ||
        v6d.final_profile_id ||
        sel.final_profile_id ||
        (tel.v6_final && tel.v6_final.final_profile_id) ||
        ''
    );
}

function dmParamAssistantRenderTileHtml(tile) {
    if (!tile) return '';
    var tipAttr = tile.tip ? ' data-dyn-tip="' + dmParamAssistantAttrEscape(tile.tip) + '"' : '';
    return '<div class="dm-pa-tile"' + tipAttr + '><span>' + dmParamAssistantEscape(tile.label) +
        '</span><strong>' + dmParamAssistantEscape(tile.value) + '</strong></div>';
}

function dmParamAssistantRegimeSlug(tag) {
    return String(tag || 'unknown').toLowerCase().replace(/[^a-z0-9]+/g, '_');
}

function dmParamAssistantRegimeSlugForRec(rec) {
    var r = (rec && rec.backend) || {};
    if (dmParamAssistantIsV6Result(r)) {
        var rid = String(r.regime_tag || (((r.telemetry || {}).v6_display || {}).scenario_identity || {}).regime_id || '').toLowerCase();
        if (/^r[1-8]$/.test(rid)) return rid;
    }
    return dmParamAssistantRegimeSlug(r.regime_tag || (rec && rec.regime));
}

function dmParamAssistantV6GridPlanPlain(rec) {
    var r = (rec && rec.backend) || {};
    var v6d = (r.telemetry && r.telemetry.v6_display) || {};
    if (v6d.grid_plan_plain) return v6d.grid_plan_plain;
    var buy = (v6d.buy_grid_distances_pct || []).map(function (d) { return '-' + Math.abs(Number(d)) + '%'; }).join(' / ');
    var sell = (v6d.sell_grid_distances_pct || []).map(function (d) { return '+' + Number(d) + '%'; }).join(' / ');
    if (!buy && !sell) return 'Grid kapalı';
    if (!buy) return 'Alış kapalı · Satış ' + sell;
    if (!sell) return 'Alış ' + buy + ' · Satış kapalı';
    return 'Alış ' + buy + ' · Satış ' + sell;
}

function dmParamAssistantRenderV6GridChips(rec) {
    var r = (rec && rec.backend) || {};
    var v6d = (r.telemetry && r.telemetry.v6_display) || {};
    var chips = v6d.grid_plan_chips || {};
    var buyList = chips.buy || (v6d.buy_grid_distances_pct || []).map(function (d) { return '-' + Math.abs(Number(d)) + '%'; });
    var sellList = chips.sell || (v6d.sell_grid_distances_pct || []).map(function (d) { return '+' + Number(d) + '%'; });
    var html = '<div class="dm-pa-grid-ladder">';
    html += '<div class="dm-pa-grid-ladder-col dm-pa-grid-ladder-col--buy">';
    html += '<span class="dm-pa-grid-ladder-label">Alış</span>';
    if (!buyList.length || chips.buy_closed) {
        html += '<span class="dm-pa-grid-chip dm-pa-grid-chip--muted">Kapalı</span>';
    } else {
        buyList.forEach(function (t, i) {
            html += '<span class="dm-pa-grid-chip dm-pa-grid-chip--buy" style="--chip-i:' + i + '">' + dmParamAssistantEscape(t) + '</span>';
        });
    }
    html += '</div>';
    html += '<div class="dm-pa-grid-ladder-col dm-pa-grid-ladder-col--sell">';
    html += '<span class="dm-pa-grid-ladder-label">Satış</span>';
    if (!sellList.length || chips.sell_closed) {
        html += '<span class="dm-pa-grid-chip dm-pa-grid-chip--muted">Kapalı</span>';
    } else {
        sellList.forEach(function (t, i) {
            html += '<span class="dm-pa-grid-chip dm-pa-grid-chip--sell" style="--chip-i:' + i + '">' + dmParamAssistantEscape(t) + '</span>';
        });
    }
    html += '</div></div>';
    return html;
}

function dmParamAssistantRenderV6StrategyHero(rec) {
    var r = (rec && rec.backend) || {};
    if (!dmParamAssistantIsV6Result(r)) return '';
    var tel = r.telemetry || {};
    var v6d = tel.v6_display || {};
    var scen = v6d.scenario_identity || {};
    var regimeId = String(r.regime_tag || scen.regime_id || '');
    var headline = v6d.regime_headline || (regimeId + ' · ' + dmParamAssistantRegimeLabel(regimeId));
    var status = v6d.market_status_plain || dmParamAssistantMarketStatusPlain(rec);
    var riskTone = v6d.risk_tone_plain || dmParamAssistantRiskTonePlain(rec);
    var why = v6d.regime_strategy_why || status;
    var gridSummary = v6d.grid_strategy_plain || dmParamAssistantV6GridPlanPlain(rec);
    var profitLoop = v6d.profit_loop_plain || '';
    var opMode = v6d.operational_mode_plain || '';
    var base = v6d.base_allocation_pct != null ? v6d.base_allocation_pct : rec.basePct;
    var quote = v6d.quote_allocation_pct != null ? v6d.quote_allocation_pct : rec.quotePct;
    var behavior = v6d.behavior_id || scen.behavior_id || '—';
    var severity = v6d.severity || scen.severity || '—';
    var work = tel.workability_score_1w;
    var score = r.param_score != null ? r.param_score : rec.paramScore;
    var slug = dmParamAssistantRegimeSlugForRec(rec);
    var btcCtx = v6d.btc_context || {};
    var html = '<section class="dm-pa-v6-hero dm-pa-regime--' + dmParamAssistantEscape(slug) + ' dm-pa-summary-reveal">';
    html += '<div class="dm-pa-v6-hero-glow" aria-hidden="true"></div>';
    html += '<div class="dm-pa-v6-hero-top">';
    html += '<span class="dm-pa-v6-regime-badge">' + dmParamAssistantEscape(regimeId || 'V6') + '</span>';
    html += '<div class="dm-pa-v6-hero-titles">';
    html += '<h3 class="dm-pa-v6-hero-title">' + dmParamAssistantEscape(headline) + '</h3>';
    html += '<p class="dm-pa-v6-hero-sub">' + dmParamAssistantEscape(status) + '</p>';
    html += '</div>';
    html += '<div class="dm-pa-v6-hero-score"><span>Parametre skoru</span><strong>' + dmParamAssistantEscape(String(score != null ? score : '—')) + '</strong></div>';
    html += '</div>';
    html += '<div class="dm-pa-v6-why-card">';
    html += '<span class="dm-pa-v6-why-label">Neden bu rejim?</span>';
    html += '<p class="dm-pa-v6-hero-why">' + dmParamAssistantEscape(why) + '</p>';
    html += '</div>';
    html += '<div class="dm-pa-v6-grid-block">';
    html += '<div class="dm-pa-v6-grid-block-head"><span>Grid planı</span><em>' + dmParamAssistantEscape(gridSummary) + '</em></div>';
    html += dmParamAssistantRenderV6GridChips(rec);
    html += '</div>';
    if (profitLoop) {
        html += '<div class="dm-pa-v6-profit-loop"><span>Kâr döngüsü</span><p>' + dmParamAssistantEscape(profitLoop) + '</p></div>';
    }
    html += '<div class="dm-pa-v6-hero-meta">';
    html += '<span class="dm-pa-v6-meta-pill"><em>Dağılım</em> Coin %' + dmParamAssistantInputTextTr(base, 0) + ' · USDT %' + dmParamAssistantInputTextTr(quote, 0) + '</span>';
    html += '<span class="dm-pa-v6-meta-pill"><em>Davranış</em> ' + dmParamAssistantEscape(behavior) + ' · ' + dmParamAssistantEscape(severity) + '</span>';
    html += '<span class="dm-pa-v6-meta-pill"><em>Risk</em> ' + dmParamAssistantEscape(riskTone) + '</span>';
    if (opMode) {
        html += '<span class="dm-pa-v6-meta-pill dm-pa-v6-meta-pill--ok"><em>Mod</em> ' + dmParamAssistantEscape(opMode) + '</span>';
    }
    if (btcCtx.class) {
        html += '<span class="dm-pa-v6-meta-pill"><em>BTC</em> ' + dmParamAssistantEscape(String(btcCtx.class)) +
            (btcCtx.delta_multiplier != null ? ' · çarpan ' + dmParamAssistantEscape(String(btcCtx.delta_multiplier)) : '') + '</span>';
    }
    if (work != null) {
        html += '<span class="dm-pa-v6-meta-pill"><em>1 hafta çalışabilirlik</em> ' + dmParamAssistantEscape(String(work)) + '/100</span>';
    }
    html += '</div></section>';
    return html;
}

function dmParamAssistantStaggerReveal(root, selector, baseDelayMs, stepMs) {
    if (!root || !root.querySelectorAll) return;
    var delay = baseDelayMs || 0;
    var step = stepMs != null ? stepMs : 55;
    root.querySelectorAll(selector).forEach(function (node, idx) {
        node.classList.add('dm-pa-summary-reveal');
        node.style.animationDelay = (delay + idx * step) + 'ms';
    });
}

function dmParamAssistantCountUsedIndicators(ind) {
    ind = ind || {};
    var n = 0;
    DM_PA_INDICATOR_GROUPS.forEach(function (group) {
        group.keys.forEach(function (key) {
            var v = ind[key];
            if (v != null && v !== '') n++;
        });
    });
    return n;
}

function dmParamAssistantCountCandles(ind) {
    ind = ind || {};
    return (Number(ind.candle_count_5m) || 0) + (Number(ind.candle_count_15m) || 0) + (Number(ind.candle_count_1h) || 0);
}

function dmParamAssistantBuildRichNarrative(snapshot, rec) {
    var sym = snapshot.symbol || 'bu parite';
    var name = dmParamAssistantCurrentUserName(snapshot);
    var r = (rec && rec.backend) || {};
    var tel = r.telemetry || {};
    var ind = tel.indicators || {};
    var v6d = tel.v6_display || {};
    var regimeId = String(r.regime_tag || (v6d.scenario_identity && v6d.scenario_identity.regime_id) || '').toUpperCase();
    var regimeTitle = (v6d.regime_headline || dmParamAssistantRegimeLabel(regimeId)).replace(/ · .+$/, '');
    var status = v6d.market_status_plain || dmParamAssistantMarketStatusPlain(rec);
    var indicatorN = dmParamAssistantCountUsedIndicators(ind);
    var candleN = dmParamAssistantCountCandles(ind);
    var base = v6d.base_allocation_pct != null ? v6d.base_allocation_pct : rec.basePct;
    var quote = v6d.quote_allocation_pct != null ? v6d.quote_allocation_pct : rec.quotePct;
    var score = r.param_score != null ? r.param_score : rec.paramScore;
    var buyN = (rec.downGrids && rec.downGrids.length) || 0;
    var sellN = (rec.upGrids && rec.upGrids.length) || 0;
    var budget = rec.budget != null ? dmParamAssistantInputTextTr(rec.budget, 0) + ' USDT' : '';
    var parts = [];
    parts.push('Merhaba ' + name + '. ' + sym + ' için ' + candleN + ' mum verisi ve ' + indicatorN + ' canlı göstergeyi birlikte okudum.');
    parts.push(regimeTitle + ' — ' + status);
    parts.push('Bu tabloda risk ve fırsat skorlarını dengeleyerek coin %' + base + ' · USDT %' + quote + ' dağılımı ve ' + buyN + ' alış + ' + sellN + ' satış seviyesi öneriyorum.');
    if (budget) parts.push('Bütçe ' + budget + ' üzerinden her emrin borsada çalışabilir kalmasına dikkat ettim.');
    if (v6d.profit_loop_plain || (rec.rebuyTrigger && rec.rebuyTrigger > 0)) {
        parts.push('Satış sonrası geri alım ve yeniden yükselişte kar satış döngüsü de açık — grid dışında ek kazanç fırsatı için.');
    }
    parts.push('Uygunluk skoru ' + (score != null ? score : '—') + '/100. Bu öneri bugünkü veriye dayanır; geleceği garanti etmez, piyasa değişince yeniden kontrol edilmelidir.');
    return parts.join(' ');
}

function dmParamAssistantRegimePlainStory(rec) {
    var r = (rec && rec.backend) || {};
    var v6d = (r.telemetry && r.telemetry.v6_display) || {};
    var regimeId = String(r.regime_tag || (v6d.scenario_identity && v6d.scenario_identity.regime_id) || '').toUpperCase();
    return DM_PA_REGIME_PLAIN_STORY[regimeId] || v6d.market_status_plain || dmParamAssistantMarketStatusPlain(rec);
}

function dmParamAssistantBuildUserParamGroups(rec) {
    var map = dmParamAssistantBuildParamTileMap(rec);
    return DM_PA_PARAM_GROUPS_USER.map(function (group) {
        var rows = [];
        group.keys.forEach(function (key) {
            if (map[key]) rows.push(map[key]);
        });
        return { title: group.title, rows: rows };
    }).filter(function (group) { return group.rows.length > 0; });
}

function dmParamAssistantRenderRegimeStoryCard(rec) {
    var r = (rec && rec.backend) || {};
    if (!dmParamAssistantIsV6Result(r)) {
        return dmParamAssistantRenderRegimeBanner(rec);
    }
    var tel = r.telemetry || {};
    var v6d = tel.v6_display || {};
    var scen = v6d.scenario_identity || {};
    var regimeId = String(r.regime_tag || scen.regime_id || '');
    var headline = (v6d.regime_headline || (regimeId + ' · ' + dmParamAssistantRegimeLabel(regimeId))).split(' · ')[1] || dmParamAssistantRegimeLabel(regimeId);
    var status = v6d.market_status_plain || dmParamAssistantMarketStatusPlain(rec);
    var story = dmParamAssistantRegimePlainStory(rec);
    var base = v6d.base_allocation_pct != null ? v6d.base_allocation_pct : rec.basePct;
    var quote = v6d.quote_allocation_pct != null ? v6d.quote_allocation_pct : rec.quotePct;
    var buyN = (rec.downGrids && rec.downGrids.length) || 0;
    var sellN = (rec.upGrids && rec.upGrids.length) || 0;
    var opMode = v6d.operational_mode_plain || 'İki yönlü grid';
    var buyDisabled = r.ui_config && r.ui_config.buy_disabled === true;
    var allocNote = (buyDisabled || buyN === 0) && sellN > 0
        ? 'yeni alış kapalı, satış ve kontrollü kâr döngüsü aktif'
        : 'iki bacak da işlem yapabilir';
    var score = r.param_score != null ? r.param_score : rec.paramScore;
    var slug = dmParamAssistantRegimeSlugForRec(rec);
    var html = '<section class="dm-pa-regime-story dm-pa-regime--' + dmParamAssistantEscape(slug) + ' dm-pa-summary-reveal">';
    html += '<div class="dm-pa-story-glow" aria-hidden="true"></div>';
    html += '<div class="dm-pa-story-head">';
    html += '<span class="dm-pa-story-badge">' + dmParamAssistantEscape(regimeId || '—') + '</span>';
    html += '<div class="dm-pa-story-titles"><h3 class="dm-pa-story-title">' + dmParamAssistantEscape(headline) + '</h3>';
    html += '<p class="dm-pa-story-lead">' + dmParamAssistantEscape(status) + '</p></div>';
    html += '<div class="dm-pa-story-score" title="Parametre uygunluk skoru"><span>Skor</span><strong>' + dmParamAssistantEscape(String(score != null ? score : '—')) + '</strong></div>';
    html += '</div>';
    html += '<div class="dm-pa-story-body dm-pa-summary-reveal"><p>' + dmParamAssistantEscape(story) + '</p>';
    html += '<ul class="dm-pa-story-points">';
    html += '<li class="dm-pa-story-row dm-pa-summary-reveal">Coin %' + dmParamAssistantInputTextTr(base, 0) + ' · USDT %' + dmParamAssistantInputTextTr(quote, 0) + ' — ' + dmParamAssistantEscape(allocNote) + '</li>';
    html += '<li class="dm-pa-story-row dm-pa-summary-reveal">' + buyN + ' alış · ' + sellN + ' satış seviyesi · ' + dmParamAssistantEscape(opMode) + '</li>';
    if (v6d.profit_loop_plain) {
        html += '<li class="dm-pa-story-row dm-pa-summary-reveal">' + dmParamAssistantEscape(v6d.profit_loop_plain) + '</li>';
    }
    html += '</ul></div>';
    html += '<div class="dm-pa-story-grid dm-pa-summary-reveal">';
    html += dmParamAssistantRenderV6GridChips(rec);
    html += '</div></section>';
    return html;
}

function dmParamAssistantRenderUserParamsHtml(rec) {
    var groups = dmParamAssistantBuildUserParamGroups(rec);
    if (!groups.length) return '';
    var html = '<section class="dm-pa-params-card dm-pa-summary-reveal"><h4 class="dm-pa-params-card-title">Önerilen parametreler</h4>';
    groups.forEach(function (group) {
        if (group.title) {
            html += '<div class="dm-pa-param-group-title dm-pa-summary-reveal">' + dmParamAssistantEscape(group.title) + '</div>';
        }
        html += '<div class="dm-pa-param-list">';
        (group.rows || []).forEach(function (tile) {
            var rowCls = 'dm-pa-param-row dm-pa-param-row-ai dm-pa-summary-reveal' + (tile.mono ? ' dm-pa-param-row--code' : '');
            html += '<div class="' + rowCls + '">' +
                '<span>' + dmParamAssistantEscape(tile.label) + '</span>' +
                '<strong>' + dmParamAssistantEscape(tile.value) + '</strong></div>';
        });
        html += '</div>';
    });
    html += '</section>';
    return html;
}

function dmParamAssistantDataGroupSlug(title) {
    var t = String(title || '').toLowerCase();
    if (t.indexOf('trend') >= 0 || t.indexOf('momentum') >= 0) return 'trend';
    if (t.indexOf('volatil') >= 0 || t.indexOf('aralık') >= 0) return 'vol';
    if (t.indexOf('getiri') >= 0) return 'risk';
    if (t.indexOf('likid') >= 0 || t.indexOf('ücret') >= 0) return 'liq';
    if (t.indexOf('btc') >= 0) return 'btc';
    if (t.indexOf('veri') >= 0) return 'data';
    return 'misc';
}

function dmParamAssistantDataGroupIcon(slug) {
    var icons = { trend: '↗', vol: '〰', risk: '⚡', liq: '◆', btc: '₿', data: '◎', misc: '·' };
    return icons[slug] || '·';
}

function dmParamAssistantDataTileTone(label, value) {
    var s = String(value || '').trim();
    var l = String(label || '').toLowerCase();
    if (s === 'Evet') return 'yes';
    if (s === 'Hayır') return 'no';
    if (l.indexOf('getiri') >= 0 || l.indexOf('roc') >= 0 || l.indexOf('eğim') >= 0 ||
        (l.indexOf('btc') >= 0 && l.indexOf('1s') + l.indexOf('4s') + l.indexOf('24s') >= 0)) {
        if (s.charAt(0) === '+') return 'up';
        if (s.charAt(0) === '-' && s !== '—') return 'down';
    }
    if (l.indexOf('fiyat vs') >= 0) {
        if (s.charAt(0) === '+') return 'up';
        if (s.charAt(0) === '-') return 'down';
    }
    if (l.indexOf('crash') >= 0 || l.indexOf('dd ') >= 0) {
        var n = parseFloat(s.replace(',', '.').replace(/[^0-9.-]/g, ''));
        if (Number.isFinite(n) && Math.abs(n) > 3) return 'down';
    }
    if (l.indexOf('spread') >= 0) {
        var sp = parseFloat(s.replace(',', '.').replace(/[^0-9.-]/g, ''));
        if (Number.isFinite(sp) && sp > 0.08) return 'warn';
    }
    return 'neutral';
}

function dmParamAssistantParseScorePct(value) {
    var m = String(value || '').match(/(\d+)\s*\/\s*100/);
    if (m) return Math.min(100, Math.max(0, parseInt(m[1], 10)));
    var n = parseInt(String(value || '').replace(/\D/g, ''), 10);
    return Number.isFinite(n) ? Math.min(100, Math.max(0, n)) : null;
}

function dmParamAssistantScoreBarClass(pct) {
    if (pct == null) return 'mid';
    if (pct >= 75) return 'high';
    if (pct >= 45) return 'mid';
    return 'low';
}

function dmParamAssistantRenderDataTileHtml(tile) {
    if (!tile) return '';
    var tone = dmParamAssistantDataTileTone(tile.label, tile.value);
    return '<div class="dm-pa-data-tile dm-pa-data-tile--' + tone + ' dm-pa-summary-reveal">' +
        '<span class="dm-pa-data-tile-label">' + dmParamAssistantEscape(tile.label) + '</span>' +
        '<strong class="dm-pa-data-tile-val">' + dmParamAssistantEscape(tile.value) + '</strong></div>';
}

function dmParamAssistantRenderScoreRowHtml(tile) {
    if (!tile) return '';
    var pct = dmParamAssistantParseScorePct(tile.value);
    var barCls = dmParamAssistantScoreBarClass(pct);
    var display = pct != null ? String(pct) : String(tile.value || '—').replace(/\/100$/, '');
    return '<div class="dm-pa-score-row dm-pa-score-row--' + barCls + ' dm-pa-summary-reveal">' +
        '<div class="dm-pa-score-row-head">' +
        '<span class="dm-pa-score-row-label">' + dmParamAssistantEscape(tile.label) + '</span>' +
        '<span class="dm-pa-score-row-dots" aria-hidden="true"></span>' +
        '<strong class="dm-pa-score-row-val">' + dmParamAssistantEscape(display) + '</strong>' +
        '</div>' +
        (pct != null
            ? '<div class="dm-pa-score-row-bar" role="presentation"><div class="dm-pa-score-row-bar-fill" style="width:' + pct + '%"></div></div>'
            : '') +
        '</div>';
}

function dmParamAssistantRenderDataCardsHtml(rec) {
    if (!rec || !rec.backend) return '';
    var sections = dmParamAssistantBackendSummarySections(rec);
    var html = '<div class="dm-pa-data-wrap">';
    if (sections.indicators && sections.indicators.groups && sections.indicators.groups.length) {
        html += '<section class="dm-pa-data-panel dm-pa-data-panel--market dm-pa-summary-reveal">';
        html += '<header class="dm-pa-data-panel-head"><span class="dm-pa-data-panel-icon">◈</span>';
        html += '<h4 class="dm-pa-data-panel-title">Piyasa verileri</h4></header>';
        html += '<div class="dm-pa-data-panel-body">';
        sections.indicators.groups.forEach(function (group, gi) {
            if (!group.rows || !group.rows.length) return;
            var slug = dmParamAssistantDataGroupSlug(group.title);
            html += '<div class="dm-pa-data-group-card dm-pa-data-group-card--' + slug + ' dm-pa-summary-reveal" style="--dm-group-i:' + gi + '">';
            html += '<div class="dm-pa-data-group-head">';
            html += '<span class="dm-pa-data-group-icon" aria-hidden="true">' + dmParamAssistantDataGroupIcon(slug) + '</span>';
            html += '<span class="dm-pa-data-group-title">' + dmParamAssistantEscape(group.title || '') + '</span>';
            html += '<span class="dm-pa-data-group-count">' + group.rows.length + '</span>';
            html += '</div>';
            html += '<div class="dm-pa-data-grid">';
            group.rows.forEach(function (tile) {
                html += dmParamAssistantRenderDataTileHtml(tile);
            });
            html += '</div></div>';
        });
        html += '</div></section>';
    }
    if (sections.sub_scores && sections.sub_scores.groups && sections.sub_scores.groups.length) {
        html += '<section class="dm-pa-data-panel dm-pa-data-panel--scores dm-pa-summary-reveal">';
        html += '<header class="dm-pa-data-panel-head"><span class="dm-pa-data-panel-icon">◉</span>';
        html += '<h4 class="dm-pa-data-panel-title">Motor değerlendirmesi</h4></header>';
        html += '<div class="dm-pa-score-list">';
        sections.sub_scores.groups.forEach(function (group) {
            (group.rows || []).forEach(function (tile) {
                html += dmParamAssistantRenderScoreRowHtml(tile);
            });
        });
        html += '</div></section>';
    }
    html += '</div>';
    return html;
}

function dmParamAssistantWrapIntroAsRichBox() {
    var block = document.querySelector('#dmParamAssistantModal .dm-pa-intro-block');
    var status = document.getElementById('dmParamAssistantStatus');
    if (block) block.classList.add('dm-pa-intro-block--rich');
    if (status) status.classList.add('dm-pa-status--complete');
}

function dmParamAssistantRenderRegimeBanner(rec) {
    var r = rec.backend || {};
    var ui = r.ui_config || {};
    var marketStatus = dmParamAssistantMarketStatusPlain(rec);
    var riskTone = dmParamAssistantRiskTonePlain(rec);
    var conf = ui.confidence_display_pct || r.confidence_display_pct ||
        dmParamAssistantFormatConfidencePct(r.confidence != null ? r.confidence : r.param_score);
    var technical = dmParamAssistantRegimeTechnicalLabel(rec);
    var slug = dmParamAssistantRegimeSlugForRec(rec);
    var v6d = ((rec.backend || {}).telemetry || {}).v6_display || {};
    var regimeBadge = dmParamAssistantIsV6Result(rec.backend) && (v6d.regime_headline || rec.backend.regime_tag)
        ? '<span class="dm-pa-regime-code">' + dmParamAssistantEscape(String(rec.backend.regime_tag || '')) + '</span>'
        : '';
    var tip = 'Piyasa durumu: ' + marketStatus + '. Risk tonu: ' + riskTone + '.';
    if (technical && dmParamAssistantIsV6Result(r)) {
        tip += ' Teknik detay: ' + technical + '.';
    }
    if (ui.effective_route_key || r.effective_route_key) {
        tip += ' Etkin route: ' + (ui.effective_route_key || r.effective_route_key) + '.';
    }
    return '<div class="dm-pa-regime-banner dm-pa-regime--' + dmParamAssistantEscape(slug) +
        '" data-dyn-tip="' + dmParamAssistantAttrEscape(tip) + '">' +
        regimeBadge +
        '<div class="dm-pa-regime-kicker">Piyasa durumu</div>' +
        '<div class="dm-pa-regime-value">' + dmParamAssistantEscape(marketStatus) + '</div>' +
        '<div class="dm-pa-regime-kicker dm-pa-regime-kicker--sub">Risk</div>' +
        '<div class="dm-pa-regime-meta"><em>' + dmParamAssistantEscape(riskTone) +
        '</em> · Güven <em>' + dmParamAssistantEscape(String(conf)) + '</em></div></div>';
}

function dmParamAssistantRenderParamRowHtml(tile) {
    if (!tile) return '';
    var tipAttr = tile.tip ? ' data-dyn-tip="' + dmParamAssistantAttrEscape(tile.tip) + '"' : '';
    return '<div class="dm-pa-param-row"' + tipAttr + '><span>' + dmParamAssistantEscape(tile.label) +
        '</span><strong>' + dmParamAssistantEscape(tile.value) + '</strong></div>';
}

function dmParamAssistantRenderParamsSectionHtml(rec) {
    var sections = dmParamAssistantBackendSummarySections(rec);
    var html = '<div class="dm-pa-summary-wrap dm-pa-params-wrap dm-pa-params-wrap-ai">';
    if (dmParamAssistantIsV6Result(rec.backend)) {
        html += dmParamAssistantRenderV6StrategyHero(rec);
    } else {
        html += dmParamAssistantRenderRegimeBanner(rec);
    }
    html += '<section class="dm-pa-summary-section dm-pa-summary-params">';
    html += '<h4 class="dm-pa-summary-section-title">' + dmParamAssistantEscape(sections.params.title) + '</h4>';
    (sections.params.groups || []).forEach(function (group) {
        if (!group.rows || !group.rows.length) return;
        if (group.title) {
            html += '<div class="dm-pa-param-group-title">' + dmParamAssistantEscape(group.title) + '</div>';
        }
        html += '<div class="dm-pa-param-list">';
        group.rows.forEach(function (tile) {
            html += dmParamAssistantRenderParamRowHtml(tile);
        });
        html += '</div>';
    });
    html += '</section></div>';
    return html;
}

function dmParamAssistantRenderScenarioAlignmentHtml(align) {
    if (!align || typeof align !== 'object') return '';
    var score = align.combined_score;
    var shelf = align.shelf_ideal || {};
    var applied = align.applied || {};
    var adj = (align.adjustments || []).slice(0, 8);
    var isV6 = align.engine === 'v6';
    var badge = align.fully_aligned ? 'Tam uyum' : (align.aligned ? 'Uyumlu (düzeltmeli)' : 'Düşük uyum');
    var html = '<section class="dm-pa-summary-section dm-pa-scenario-alignment dm-pa-summary-reveal">';
    html += '<h4 class="dm-pa-summary-section-title">Senaryo uyumu · ' + dmParamAssistantEscape(badge) + '</h4>';
    if (isV6 && align.regime_headline) {
        html += '<div class="dm-pa-v6-align-hero dm-pa-summary-reveal">';
        html += '<div class="dm-pa-v6-align-regime">' + dmParamAssistantEscape(align.regime_headline) + '</div>';
        if (align.regime_label_plain) {
            html += '<div class="dm-pa-v6-align-status">' + dmParamAssistantEscape(align.regime_label_plain) + '</div>';
        }
        if (align.regime_strategy_why) {
            html += '<p class="dm-pa-v6-align-why">' + dmParamAssistantEscape(align.regime_strategy_why) + '</p>';
        }
        if (align.grid_strategy_plain || align.grid_plan_plain) {
            html += '<div class="dm-pa-v6-align-grid"><span>Grid</span><em>' +
                dmParamAssistantEscape(align.grid_strategy_plain || align.grid_plan_plain) + '</em></div>';
        }
        html += '</div>';
    }
    html += '<div class="dm-pa-tile-grid">';
    html += dmParamAssistantRenderTileHtml({ label: 'Birleşik skor', value: (score != null ? score + '/100' : '—') });
    html += dmParamAssistantRenderTileHtml({ label: isV6 ? 'Katalog skoru' : 'Raf skoru', value: (align.shelf_scenario_fit != null ? align.shelf_scenario_fit + '/100' : '—') });
    html += dmParamAssistantRenderTileHtml({ label: 'İndikatör uyumu', value: (align.indicator_fit != null ? align.indicator_fit + '/100' : '—') });
    html += dmParamAssistantRenderTileHtml({ label: isV6 ? 'Rejim' : 'Rejim (teknik)', value: isV6 && align.regime_headline ? align.regime_headline : (align.regime_label || align.canonical_regime_tag || '—') });
    if (align.regime_label_plain) {
        html += dmParamAssistantRenderTileHtml({ label: 'Piyasa durumu', value: align.regime_label_plain });
    }
    if (isV6 && align.operational_mode_plain) {
        html += dmParamAssistantRenderTileHtml({ label: 'Çalışma modu', value: align.operational_mode_plain });
    }
    if (isV6 && align.behavior_id) {
        html += dmParamAssistantRenderTileHtml({ label: 'Davranış', value: align.behavior_id });
    }
    if (isV6 && align.severity) {
        html += dmParamAssistantRenderTileHtml({ label: 'Şiddet', value: align.severity });
    }
    if (isV6 && align.data_quality_label) {
        html += dmParamAssistantRenderTileHtml({ label: 'Veri kalitesi', value: align.data_quality_label });
    }
    if (isV6 && align.risk_display_label) {
        html += dmParamAssistantRenderTileHtml({ label: 'Risk tonu', value: align.risk_display_label });
    }
    html += '</div>';
    html += '<div class="dm-pa-align-compare">';
    if (isV6 && (align.grid_plan_plain || align.grid_strategy_plain)) {
        html += '<div class="dm-pa-align-col dm-pa-align-col--full"><div class="dm-pa-align-head">Grid planı</div>';
        html += '<div class="dm-pa-align-line dm-pa-align-line--grid">' + dmParamAssistantEscape(align.grid_strategy_plain || align.grid_plan_plain) + '</div>';
        if (align.regime_strategy_why) {
            html += '<div class="dm-pa-align-line dm-pa-align-line--why">' + dmParamAssistantEscape(align.regime_strategy_why) + '</div>';
        }
        html += '</div>';
    }
    html += '<div class="dm-pa-align-col"><div class="dm-pa-align-head">' + (isV6 ? 'Katalog profili' : 'Raf ideali') + '</div>';
    if (isV6 && shelf.grid_plan_plain) {
        html += '<div class="dm-pa-align-line">' + dmParamAssistantEscape(shelf.grid_plan_plain) + '</div>';
    } else {
        html += '<div class="dm-pa-align-line">Alış ' + (shelf.buy_grid_count != null ? shelf.buy_grid_count : '—') + ' · Satış ' + (shelf.sell_grid_count != null ? shelf.sell_grid_count : '—') + '</div>';
    }
    html += '<div class="dm-pa-align-line">Hedef %' + (shelf.base_alloc_pct != null ? shelf.base_alloc_pct : '—') + ' / %' + (shelf.quote_alloc_pct != null ? shelf.quote_alloc_pct : '—') + '</div></div>';
    html += '<div class="dm-pa-align-col"><div class="dm-pa-align-head">Uygulanan</div>';
    if (isV6 && (applied.grid_plan_plain || align.grid_plan_plain)) {
        html += '<div class="dm-pa-align-line">' + dmParamAssistantEscape(applied.grid_plan_plain || align.grid_plan_plain) + '</div>';
    } else {
        html += '<div class="dm-pa-align-line">Alış ' + (applied.buy_grid_count != null ? applied.buy_grid_count : '—') + ' · Satış ' + (applied.sell_grid_count != null ? applied.sell_grid_count : '—') + '</div>';
    }
    html += '<div class="dm-pa-align-line">Hedef %' + (applied.base_alloc_pct != null ? applied.base_alloc_pct : '—') + ' / %' + (applied.quote_alloc_pct != null ? applied.quote_alloc_pct : '—') + '</div></div>';
    html += '</div>';
    if (isV6 && align.profit_loop_plain) {
        html += '<div class="dm-pa-align-adj dm-pa-align-adj--profit">Kâr döngüsü: ' + dmParamAssistantEscape(align.profit_loop_plain) + '</div>';
    }
    if (isV6 && align.final_profile_id) {
        html += '<details class="dm-pa-align-tech"><summary>Teknik profil kimliği</summary>';
        html += '<div class="dm-pa-align-adj">' + dmParamAssistantEscape(align.final_profile_id) + '</div></details>';
    }
    if (adj.length) {
        html += '<details class="dm-pa-align-tech"><summary>Ayarlayıcı düzeltmeleri</summary>';
        html += '<div class="dm-pa-align-adj">' + adj.map(function (a) { return dmParamAssistantEscape(a); }).join(' · ') + '</div></details>';
    }
    html += '</section>';
    return html;
}

function dmParamAssistantRenderDetailsSectionsHtml(sections, rec, result) {
    var html = '<div class="dm-pa-summary-wrap dm-pa-details-wrap">';
    if (sections.notice) {
        html += dmParamAssistantRenderNoticeHtml(sections.notice, rec);
    }
    var ui = (result && result.ui_config) || {};
    var align = ui.scenario_alignment || (result && result.telemetry && result.telemetry.scenario_alignment);
    if (align) {
        html += dmParamAssistantRenderScenarioAlignmentHtml(align);
    }
    if (sections.indicators && sections.indicators.groups && sections.indicators.groups.length) {
        html += dmParamAssistantRenderGroupedSectionHtml(sections.indicators, 'indicators');
    }
    if (sections.sub_scores && sections.sub_scores.groups && sections.sub_scores.groups.length) {
        html += dmParamAssistantRenderGroupedSectionHtml(sections.sub_scores, 'sub_scores');
    }
    if (sections.v6_engine && sections.v6_engine.groups && sections.v6_engine.groups.length) {
        html += dmParamAssistantRenderGroupedSectionHtml(sections.v6_engine, 'v6_engine');
    }
    if (sections.safety && sections.safety.groups && sections.safety.groups.length) {
        html += dmParamAssistantRenderGroupedSectionHtml(sections.safety, 'safety');
    }
    var debugGroups = dmParamAssistantBuildDebugParamGroups(rec).concat(
        dmParamAssistantBuildFeeDisplayTiles(result || (rec && rec.backend) || {}),
        dmParamAssistantBuildSelectionTraceTiles(result || (rec && rec.backend) || {})
    );
    if (debugGroups.length) {
        html += '<details class="dm-pa-sub-scores dm-pa-debug-panel" open>';
        html += '<summary>Gelişmiş teknik detaylar</summary>';
        debugGroups.forEach(function (group) {
            html += '<div class="dm-pa-tile-group">';
            if (group.title) {
                html += '<div class="dm-pa-tile-group-title">' + dmParamAssistantEscape(group.title) + '</div>';
            }
            html += '<div class="dm-pa-tile-grid">';
            (group.rows || []).forEach(function (tile) {
                html += dmParamAssistantRenderTileHtml(tile);
            });
            html += '</div></div>';
        });
        html += '</details>';
    }
    html += '</div>';
    return html;
}

function dmParamAssistantClearResultPanels() {
    ['dmParamAssistantSummary', 'dmParamAssistantOutput', 'dmParamAssistantChips', 'dmParamAssistantDetails'].forEach(function (id) {
        var el = document.getElementById(id);
        if (!el) return;
        el.innerHTML = '';
        if (id !== 'dmParamAssistantOutput') el.style.display = 'none';
    });
}

function dmParamAssistantShowParamsFirst(rec) {
    var el = document.getElementById('dmParamAssistantSummary');
    if (!el || !rec || !rec.backend) return;
    dmParamAssistantRenderParamsSectionAi(rec);
}

function dmParamAssistantRenderParamsSectionAi(rec, done) {
    var el = document.getElementById('dmParamAssistantSummary');
    if (!el || !rec) {
        if (typeof done === 'function') done();
        return;
    }
    el.innerHTML = dmParamAssistantRenderParamsSectionHtml(rec);
    el.style.display = 'block';
    dmParamAssistantStaggerReveal(el, '.dm-pa-v6-hero, .dm-pa-v6-why-card, .dm-pa-v6-grid-block, .dm-pa-v6-profit-loop, .dm-pa-v6-meta-pill, .dm-pa-grid-chip, .dm-pa-regime-banner, .dm-pa-param-row, .dm-pa-param-group-title, .dm-pa-tile');
    if (typeof done === 'function') done();
}

function dmParamAssistantRenderDetailsAi(rec) {
    var el = document.getElementById('dmParamAssistantDetails');
    if (!el || !rec || !rec.backend) return;
    var sections = dmParamAssistantBackendSummarySections(rec);
    var html = dmParamAssistantRenderDetailsSectionsHtml(sections, rec, rec.backend);
    el.innerHTML = html;
    el.style.display = html.trim() ? 'block' : 'none';
    dmParamAssistantStaggerReveal(el, '.dm-pa-summary-section, .dm-pa-v6-align-hero, .dm-pa-tile, details.dm-pa-debug-panel', 120);
}

function dmParamAssistantEnsureAiResultLayout() {
    var body = document.querySelector('#dmParamAssistantModal .dm-param-assistant-body');
    var prep = document.getElementById('dmParamAssistantPrep');
    var output = document.getElementById('dmParamAssistantOutput');
    var chips = document.getElementById('dmParamAssistantChips');
    var summary = document.getElementById('dmParamAssistantSummary');
    var details = document.getElementById('dmParamAssistantDetails');
    var choice = document.getElementById('dmParamAssistantChoice');
    if (!body || !output) return;
    var anchor = prep || document.querySelector('#dmParamAssistantModal .perf-summary-assistant-wrap');
    [output, chips, summary, details, choice].forEach(function (el) {
        if (!el) return;
        if (anchor && anchor.parentNode === body) {
            body.insertBefore(el, anchor.nextSibling);
            anchor = el;
        } else {
            body.appendChild(el);
        }
    });
}

function dmParamAssistantResolveV6StreamLines(result, rec) {
    var tel = (result && result.telemetry) || (rec && rec.backend && rec.backend.telemetry) || {};
    var fromBackend = tel.v6_stream_lines;
    if (fromBackend && fromBackend.length) {
        return fromBackend.filter(function (line) { return line && String(line).trim(); });
    }
    return dmParamAssistantBuildV6PresentationLines(result, rec);
}

function dmParamAssistantPresentBackendResultUi(snapshot, rec, lines) {
    dmParamAssistantClearResultPanels();
    dmParamAssistantClearPrep();
    dmParamAssistantEnsureAiResultLayout();

    var summary = document.getElementById('dmParamAssistantSummary');
    var chips = document.getElementById('dmParamAssistantChips');
    var details = document.getElementById('dmParamAssistantDetails');
    var choice = document.getElementById('dmParamAssistantChoice');
    var output = document.getElementById('dmParamAssistantOutput');

    if (summary) { summary.innerHTML = ''; summary.style.display = 'none'; }
    if (chips) chips.innerHTML = '';
    if (details) { details.innerHTML = ''; details.style.display = 'none'; }
    if (choice) choice.style.display = 'none';
    if (output) {
        output.innerHTML = '';
        output.classList.remove('is-visible');
        output.style.display = 'none';
    }

    dmParamAssistantScrollIntroTop();
    dmParamAssistantAutoScroll = true;
    dmParamAssistantTyping = true;

    var presentSeq = ++dmParamAssistantResultPresentSeq;
    var narrative = dmParamAssistantBuildRichNarrative(snapshot, rec);

    function finishPresentation() {
        if (presentSeq !== dmParamAssistantResultPresentSeq) return;
        if (choice) choice.style.display = 'flex';
        dmParamAssistantTyping = false;
        dmParamAssistantSetCursorVisible(false);
        dmParamAssistantMaybeScrollToBottom();
    }

    function revealDataStage() {
        if (presentSeq !== dmParamAssistantResultPresentSeq) return;
        if (!details) {
            finishPresentation();
            return;
        }
        details.innerHTML = dmParamAssistantRenderDataCardsHtml(rec);
        details.style.display = details.innerHTML.trim() ? 'block' : 'none';
        if (details.innerHTML.trim()) {
            dmParamAssistantStaggerReveal(details, '.dm-pa-data-panel, .dm-pa-data-group-card, .dm-pa-data-tile, .dm-pa-score-row', 0, 18);
            dmParamAssistantMaybeScrollToBottom();
            dmParamAssistantSetTimer(finishPresentation, 320);
        } else {
            finishPresentation();
        }
    }

    function revealParamsStage() {
        if (presentSeq !== dmParamAssistantResultPresentSeq) return;
        if (summary) {
            summary.innerHTML += dmParamAssistantRenderUserParamsHtml(rec);
            dmParamAssistantStaggerReveal(summary, '.dm-pa-params-card, .dm-pa-param-group-title, .dm-pa-param-row', 0, 26);
            dmParamAssistantMaybeScrollToBottom();
        }
        dmParamAssistantSetTimer(revealDataStage, 260);
    }

    function revealRegimeStage() {
        if (presentSeq !== dmParamAssistantResultPresentSeq) return;
        if (summary) {
            summary.innerHTML = dmParamAssistantRenderRegimeStoryCard(rec);
            summary.style.display = 'block';
            dmParamAssistantStaggerReveal(summary, '.dm-pa-regime-story, .dm-pa-story-row, .dm-pa-story-grid, .dm-pa-grid-chip', 0, 30);
            dmParamAssistantMaybeScrollToBottom();
        }
        dmParamAssistantSetTimer(revealParamsStage, 240);
    }

    dmParamAssistantTypeIntroText(narrative, function () {
        if (presentSeq !== dmParamAssistantResultPresentSeq) return;
        dmParamAssistantWrapIntroAsRichBox();
        dmParamAssistantSetTimer(revealRegimeStage, 120);
    }, { fast: true });
}

function dmParamAssistantRenderGroupedSectionHtml(section, kind) {
    if (!section || !section.groups || !section.groups.length) return '';
    var html = '<section class="dm-pa-summary-section dm-pa-summary-' + kind + '">';
    html += '<h4 class="dm-pa-summary-section-title">' + dmParamAssistantEscape(section.title) + '</h4>';
    section.groups.forEach(function (group) {
        if (!group.rows || !group.rows.length) return;
        html += '<div class="dm-pa-tile-group">';
        if (group.title) {
            html += '<div class="dm-pa-tile-group-title">' + dmParamAssistantEscape(group.title) + '</div>';
        }
        html += '<div class="dm-pa-tile-grid">';
        group.rows.forEach(function (tile) {
            html += dmParamAssistantRenderTileHtml(tile);
        });
        html += '</div></div>';
    });
    html += '</section>';
    return html;
}

function dmParamAssistantRenderNoticeHtml(notice, rec) {
    if (!notice) return '';
    var tip = 'Güvenlik veya profil nedeniyle işlem davranışı kısıtlandı; detaylar aşağıdaki bölümlerde.';
    return '<div class="dm-pa-summary-notice" role="note" data-dyn-tip="' + dmParamAssistantAttrEscape(tip) + '">' +
        '<div class="dm-pa-notice-badge">Bilgi</div>' +
        '<p class="dm-pa-notice-text">' + dmParamAssistantEscape(notice) + '</p></div>';
}

function dmParamAssistantProfileLabel(name) {
    var map = {
        NO_TRADE_PROFILE: 'İşlem yok',
        WAIT_PROFILE: 'Bekle',
        SELL_MANAGEMENT_ONLY_PROFILE: 'Yalnızca satış yönetimi',
        ULTRA_DEFENSIVE_GRID_PROFILE: 'Ultra savunmacı grid',
        DEFENSIVE_GRID_PROFILE: 'Savunmacı grid',
        CAUTIOUS_BALANCED_GRID_PROFILE: 'Temkinli dengeli grid',
        BALANCED_GRID_PROFILE: 'Dengeli grid',
        ACTIVE_RANGE_GRID_PROFILE: 'Aktif aralık grid',
        HIGH_CONFIDENCE_ACTIVE_GRID_PROFILE: 'Yüksek güven aktif grid',
        TREND_TRAILING_PROFILE: 'Trend trailing',
        BREAKOUT_PROTECTION_PROFILE: 'Kırılım koruması',
        RECOVERY_SELL_PROFILE: 'Toparlanma satışı',
        LOW_FEE_WIDE_GRID_PROFILE: 'Düşük fee geniş grid',
        HIGH_VOL_PROTECTION_PROFILE: 'Yüksek volatilite koruması',
        LOW_LIQUIDITY_WAIT_PROFILE: 'Düşük likidite bekle',
        INITIAL_ENTRY_PROFILE: 'İlk giriş',
        SMALL_BUDGET_SAFE_PROFILE: 'Küçük bütçe güvenli',
        MICRO_BUDGET_WAIT_PROFILE: 'Mikro bütçe bekle',
        OVEREXPOSED_REDUCTION_PROFILE: 'Aşırı maruz azaltma'
    };
    return map[name] || name || '—';
}

var DM_PA_INDICATOR_LABELS = {
    adx_1h: 'ADX (1h)',
    rsi14_5m: 'RSI (5m)',
    rsi14_1h: 'RSI (1h)',
    atr14_pct_5m: 'ATR (5m)',
    atr14_pct_1h: 'ATR (1h)',
    orderbook_spread_pct: 'Spread',
    total_friction_pct: 'Toplam fee',
    realized_vol_24h: 'Vol 24s',
    realized_vol_7d: 'Vol 7g',
    volatility_percentile: 'Vol persentil',
    return_1h_pct: 'Getiri 1s',
    return_4h_pct: 'Getiri 4s',
    return_24h_pct: 'Getiri 24s',
    drawdown_7d_pct: 'DD 7g',
    drawdown_30d_pct: 'DD 30g',
    bb_width_5m: 'BB genişlik',
    z_score_5m: 'Z-skor',
    mean_reversion_ratio: 'Ort. dönüş',
    range_stability: 'Aralık stabilite',
    roc_5m: 'ROC (5m)',
    quote_volume_24h: 'Hacim 24s',
    volume_consistency: 'Hacim tutarlılık',
    volume_spike_abnormality: 'Hacim spike',
    zero_volume_ratio: 'Sıfır hacim',
    btc_return_1h_pct: 'BTC 1s',
    btc_return_4h_pct: 'BTC 4s',
    btc_return_24h_pct: 'BTC 24s',
    btc_crash_velocity: 'BTC crash hızı',
    price_vs_ema200_pct: 'Fiyat vs EMA200',
    ema20_slope_5m: 'EMA20 eğim',
    ema50_slope_5m: 'EMA50 eğim',
    ema20_5m: 'EMA20 (5m)',
    ema50_5m: 'EMA50 (5m)',
    ema200_1h: 'EMA200 (1h)',
    data_freshness_sec: 'Veri tazeliği',
    data_gap_max_ms: 'Veri boşluğu',
    crash_velocity: 'Crash hızı',
    consecutive_red_pressure: 'Kırmızı baskı',
    high_low_range_pct: 'HL aralık',
    price_in_bb: 'BB konumu',
    candle_count_5m: 'Mum (5m)',
    candle_count_15m: 'Mum (15m)',
    candle_count_1h: 'Mum (1h)',
    higher_highs: 'Üst tepeler',
    lower_lows: 'Alt dipler',
    btc_below_ema200: 'BTC EMA200 altı',
    price_valid: 'Fiyat geçerli'
};

var DM_PA_INDICATOR_TIPS = {
    adx_1h: '1 saatlik ADX: trend gücü. 25 üzeri güçlü trend, 20 altı yatay piyasa sinyali.',
    rsi14_5m: '5 dakikalık RSI: kısa vadeli aşırı alım/satım baskısı.',
    rsi14_1h: '1 saatlik RSI: orta vadeli momentum dengesi.',
    atr14_pct_5m: '5 dakikalık ATR yüzdesi: kısa vadeli oynaklık; grid aralığı için temel girdi.',
    atr14_pct_1h: '1 saatlik ATR yüzdesi: orta vadeli oynaklık.',
    orderbook_spread_pct: 'Emir defteri spreadi; yüksek spread işlem maliyetini artırır.',
    total_friction_pct: 'Tahmini toplam sürtünme (fee + slipaj); grid kârlılık tabanı.',
    realized_vol_24h: 'Son 24 saat gerçekleşen volatilite.',
    realized_vol_7d: 'Son 7 gün gerçekleşen volatilite.',
    volatility_percentile: 'Volatilitenin tarihsel dağılımdaki yüzdelik dilimi.',
    return_1h_pct: 'Son 1 saatlik fiyat değişimi.',
    return_4h_pct: 'Son 4 saatlik fiyat değişimi.',
    return_24h_pct: 'Son 24 saatlik fiyat değişimi.',
    drawdown_7d_pct: 'Son 7 gündeki en derin geri çekilme.',
    drawdown_30d_pct: 'Son 30 gündeki en derin geri çekilme.',
    bb_width_5m: 'Bollinger bant genişliği; dar bant sıkışma, geniş bant genişleme.',
    z_score_5m: 'Fiyatın 5 dakikalık ortalamadan sapması; aşırı sapma geri dönüş sinyali.',
    mean_reversion_ratio: 'Ortalamaya dönüş eğilimi skoru.',
    range_stability: 'Fiyat aralığının ne kadar stabil kaldığı.',
    roc_5m: '5 dakikalık momentum (rate of change).',
    quote_volume_24h: '24 saatlik USDT hacmi; likidite göstergesi.',
    volume_consistency: 'Hacmin zamana göre tutarlılığı.',
    volume_spike_abnormality: 'Anormal hacim artışı şiddeti.',
    zero_volume_ratio: 'Sıfır hacimli mum oranı; veri/likidite kalitesi.',
    btc_return_1h_pct: 'BTC son 1 saat getirisi; piyasa bağlamı.',
    btc_return_4h_pct: 'BTC son 4 saat getirisi.',
    btc_return_24h_pct: 'BTC son 24 saat getirisi.',
    btc_crash_velocity: 'BTC düşüş hızı; sistemik risk göstergesi.',
    price_vs_ema200_pct: 'Fiyatın 1 saatlik EMA200\'e göre uzaklığı.',
    ema20_slope_5m: 'Kısa vadeli EMA20 eğimi.',
    ema50_slope_5m: 'Orta vadeli EMA50 eğimi.',
    ema20_5m: '5 dakikalık EMA20 seviyesi.',
    ema50_5m: '5 dakikalık EMA50 seviyesi.',
    ema200_1h: '1 saatlik EMA200 trend referansı.',
    data_freshness_sec: 'Son mumun ne kadar taze olduğu (saniye).',
    data_gap_max_ms: 'Veri dizisindeki en büyük boşluk.',
    crash_velocity: 'Ani düşüş hızı; dump riski için kullanılır.',
    consecutive_red_pressure: 'Ardışık kırmızı mum baskısı.',
    high_low_range_pct: 'Mevcut mum yüksek-düşük aralığı.',
    price_in_bb: 'Fiyatın Bollinger bandı içindeki konumu (0–1).',
    candle_count_5m: 'Analizde kullanılan 5 dakikalık mum sayısı.',
    candle_count_15m: 'Analizde kullanılan 15 dakikalık mum sayısı.',
    candle_count_1h: 'Analizde kullanılan 1 saatlik mum sayısı.',
    higher_highs: 'Üst tepeler yükseliyor mu (yükseliş yapısı).',
    lower_lows: 'Alt dipler düşüyor mu (düşüş yapısı).',
    btc_below_ema200: 'BTC uzun vadeli trendin altında mı.',
    price_valid: 'Fiyat verisi geçerli ve kullanılabilir mi.'
};

var DM_PA_PARAM_TIPS = {
    exact_shelf_id: 'V6 katalogdan seçilen exact shelf kimliği (DPLV6_…).',
    final_shelf_id: 'Ayarlayıcı pipeline sonrası nihai profil kimliği.',
    profile: 'V5 kütüphaneden exact route lookup ile seçilen DPLV5 shelf.',
    budget: 'Bot için ayrılan toplam USDT bütçesi.',
    allocation: 'Base (coin) ve quote (USDT) başlangıç dağılımı.',
    regime: 'Sınıflandırılmış piyasa rejimi ve karar güveni.',
    sell_grid: 'Satış grid kademeleri: tetik yüzdesi ve miktar payı.',
    buy_grid: 'Alış grid kademeleri: tetik yüzdesi ve miktar payı.',
    grid_step: 'Alış ve satış gridleri arasındaki minimum yüzde aralığı.',
    trailing: 'Grid tetiklendikten sonra kârı korumak için trailing yüzdeleri.',
    rebuy: 'Kar alım tetik ve trailing değerleri.',
    resell: 'Kar satış tetik ve trailing değerleri.',
    profit_cycle: 'Rebuy ve resell döngüsünün birleşik özeti.',
    take_profit: 'Tur kâr hedefi yüzdesi.',
    max_exposure: 'İzin verilen maksimum base maruziyeti.',
    min_profit_fee: 'Komisyon sonrası minimum tur kâr eşiği.',
    buy_quota: 'Tek alışta harcanabilecek maksimum quote payı.',
    stop_buys: 'Parametre skoru bu eşiğin altına düşerse yeni alış durur.',
    trailing_mode: 'Trailing mekanizması açık mı.',
    emergency_no_buy: 'Acil durumda yeni alışların kapalı olması.',
    buy_mode: 'Alış tarafının güvenlik nedeniyle kapatılması.',
    downtrend_throttle: 'Düşüş trendinde alış hızının frenlenmesi.',
    headroom: 'Yeni alış için kalan quote headroom (USDT).',
    min_notional: 'Borsanın kabul ettiği minimum emir tutarı.',
    buy_ladder: 'Alış kademeleri için ayrılan toplam bütçe.',
    worst_exposure: 'En kötü senaryoda oluşabilecek base maruziyeti.',
    fee_floor: 'Komisyon tabanı; grid aralığı bundan dar olamaz.',
    safety_result: 'Güvenlik kapıları sonrası nihai uygulama kararı.'
};

var DM_PA_PARAM_GROUPS = [
    { title: 'Genel ayarlar', keys: ['profile', 'final_profile', 'budget', 'allocation'] },
    { title: 'Grid ve trailing', keys: ['sell_grid', 'buy_grid', 'trailing', 'grid_step'] },
    { title: 'Kâr döngüsü', keys: ['profit_cycle', 'rebuy', 'resell'] },
    { title: 'Limitler ve mod', keys: ['take_profit', 'max_exposure', 'min_profit_fee', 'buy_quota', 'stop_buys', 'trailing_mode', 'emergency_no_buy', 'buy_mode', 'downtrend_throttle'] }
];

/** Kullanıcıya gösterilen sade parametre grupları. */
var DM_PA_PARAM_GROUPS_USER = [
    { title: 'Profil kimliği', keys: ['exact_shelf_id', 'final_shelf_id'] },
    { title: 'Bütçe ve dağılım', keys: ['budget', 'allocation'] },
    { title: 'Grid planı', keys: ['sell_grid', 'buy_grid', 'trailing'] },
    { title: 'Kâr döngüsü', keys: ['profit_cycle'] }
];

var DM_PA_REGIME_PLAIN_STORY = {
    R1: 'Fiyat güçlü yükseliş trendinde. Bot coin tarafını yüksek tutar; yükselişte satış gridleri ve geri çekilmelerde alış gridleri birlikte çalışır.',
    R2: 'Piyasa yatay bir bantta — al-sat için en verimli rejim. Alt bölgede alır, üst bölgede satar; kâr döngüsü sürekli aktif kalır.',
    R3: 'Hareket dar ve sakin; kırılım öncesi sıkışma. Gridler yakın tutulur, küçük ama gerçekçi kâr hedefleri seçilir.',
    R4: 'Sert yukarı-aşağı dalgalanma var, net tek yön yok. Gridler dengeli genişletilir; ani fitillerde kâr alınır, panik alımından kaçınılır.',
    R5: 'Önemli direnç kırılımı veya trend başlangıcı. Fırsatı kaçırmamak için coin payı artırılır; sahte kırılıma karşı USDT rezervi bırakılır.',
    R6: 'Düşüş sonrası toparlanma aşaması. Trend henüz çok güçlü değil; kademeli alım ve erken kâr alma dengesi kurulur.',
    R7: 'Ana yön aşağı; düşen bıçağa atlanmaz. USDT korunur, alış gridleri derinde, satış gridleri erken risk azaltır.',
    R8: 'Sert düşüş veya panik ortamı. Normal alış kısıtlanır; satış ve kontrollü kâr döngüsü açık kalır, sermaye korunur.'
};

var DM_PA_SUB_SCORE_LABELS = {
    trend_score: 'Trend',
    volatility_score: 'Volatilite',
    range_score: 'Aralık',
    liquidity_score: 'Likidite',
    spread_score: 'Spread',
    momentum_score: 'Momentum',
    mean_reversion_score: 'Ortalamaya dönüş',
    drawdown_risk_score: 'Drawdown riski',
    btc_market_risk_score: 'BTC piyasa riski',
    exposure_safety_score: 'Maruziyet güvenliği',
    fee_efficiency_score: 'Fee verimi',
    data_quality_score: 'Veri kalitesi'
};

var DM_PA_DEBUG_PARAM_GROUPS = [
    { title: 'Limitler ve mod', keys: ['grid_step', 'take_profit', 'max_exposure', 'min_profit_fee', 'buy_quota', 'stop_buys', 'trailing_mode', 'emergency_no_buy', 'buy_mode', 'downtrend_throttle', 'profit_cycle'] }
];

var DM_PA_INDICATOR_GROUPS = [
    {
        title: 'Trend ve momentum',
        keys: ['adx_1h', 'rsi14_5m', 'rsi14_1h', 'ema20_slope_5m', 'ema50_slope_5m', 'ema20_5m', 'ema50_5m', 'ema200_1h', 'price_vs_ema200_pct', 'roc_5m', 'higher_highs', 'lower_lows']
    },
    {
        title: 'Volatilite ve aralık',
        keys: ['atr14_pct_5m', 'atr14_pct_1h', 'realized_vol_24h', 'realized_vol_7d', 'volatility_percentile', 'bb_width_5m', 'price_in_bb', 'z_score_5m', 'mean_reversion_ratio', 'range_stability', 'high_low_range_pct']
    },
    {
        title: 'Getiri ve risk',
        keys: ['return_1h_pct', 'return_4h_pct', 'return_24h_pct', 'drawdown_7d_pct', 'drawdown_30d_pct', 'crash_velocity', 'consecutive_red_pressure']
    },
    {
        title: 'Likidite ve ücret',
        keys: ['orderbook_spread_pct', 'total_friction_pct', 'quote_volume_24h', 'volume_consistency', 'volume_spike_abnormality', 'zero_volume_ratio']
    },
    {
        title: 'BTC bağlamı',
        keys: ['btc_return_1h_pct', 'btc_return_4h_pct', 'btc_return_24h_pct', 'btc_crash_velocity', 'btc_below_ema200']
    },
    {
        title: 'Veri kalitesi',
        keys: ['data_freshness_sec', 'data_gap_max_ms', 'candle_count_5m', 'candle_count_15m', 'candle_count_1h', 'price_valid']
    }
];

function dmParamAssistantFormatIndicatorValue(key, val) {
    if (val == null || val === '') return null;
    if (typeof val === 'boolean') return val ? 'Evet' : 'Hayır';
    var n = Number(val);
    if (!Number.isFinite(n)) return String(val);
    if (key === 'orderbook_spread_pct' || key === 'total_friction_pct' || key === 'high_low_range_pct') {
        return dmParamAssistantMetricPct(n, 2, { noSign: true });
    }
    if (key.indexOf('pct') >= 0 || key.indexOf('return_') === 0 || key.indexOf('drawdown') >= 0 ||
        key === 'price_vs_ema200_pct' || key.indexOf('slope') >= 0 || key === 'roc_5m') {
        if (Math.abs(n) < 0.005) return dmParamAssistantMetricPct(0, 2, { noSign: true });
        return dmParamAssistantMetricPct(n, 2);
    }
    if (key === 'quote_volume_24h') {
        if (n >= 1e9) return dmParamAssistantInputTextTr(n / 1e9, 1) + 'B';
        if (n >= 1e6) return dmParamAssistantInputTextTr(n / 1e6, 1) + 'M';
        if (n >= 1e3) return dmParamAssistantInputTextTr(n / 1e3, 1) + 'K';
        return dmParamAssistantInputTextTr(n, 0);
    }
    if (key === 'data_freshness_sec') return dmParamAssistantInputTextTr(n, 0) + ' sn';
    if (key === 'data_gap_max_ms') return dmParamAssistantInputTextTr(n / 1000, 1) + ' sn';
    if (key === 'volatility_percentile' || key === 'price_in_bb' || key === 'mean_reversion_ratio' ||
        key === 'range_stability' || key === 'volume_consistency' || key === 'zero_volume_ratio' ||
        key === 'volume_spike_abnormality' || key === 'consecutive_red_pressure' || key === 'crash_velocity' ||
        key === 'btc_crash_velocity') {
        return dmParamAssistantInputTextTr(n, 2);
    }
    return dmParamAssistantInputTextTr(n, key.indexOf('adx') >= 0 || key.indexOf('rsi') >= 0 ? 1 : 2);
}

function dmParamAssistantBackendProfileText(r) {
    var ui = r.ui_config || {};
    if (ui.profile_display) return ui.profile_display;
    if (dmParamAssistantIsV6Result(r)) {
        var v6d = (r.telemetry && r.telemetry.v6_display) || {};
        var headline = v6d.regime_headline || (r.regime_tag + ' · ' + dmParamAssistantRegimeLabel(r.regime_tag));
        if (v6d.behavior_id) return headline + ' · ' + v6d.behavior_id;
        return headline;
    }
    var sel = r.selection_telemetry || (r.telemetry && r.telemetry.param_pool) || {};
    var profile = dmParamAssistantProfileLabel(r.selected_profile || '');
    var tmpl = sel.selected_template_key || sel.profile_subfamily || '';
    if (profile === '—' && tmpl) return tmpl;
    if (tmpl && tmpl !== r.selected_profile) return profile + ' · ' + tmpl;
    return profile;
}

function dmParamAssistantBuildIndicatorGroups(ind, backend) {
    ind = ind || {};
    var feeDisplay = backend && backend.selection_telemetry && backend.selection_telemetry.fee_display;
    return DM_PA_INDICATOR_GROUPS.map(function (group) {
        var rows = [];
        group.keys.forEach(function (key) {
            if (!Object.prototype.hasOwnProperty.call(ind, key)) return;
            if (key === 'total_friction_pct' && feeDisplay && feeDisplay.fee_data_available === false && feeDisplay.fee_mode !== 'disabled') {
                rows.push(dmParamAssistantMakeTile(
                    'Toplam fee',
                    'veri yok',
                    feeDisplay.display_note || 'Fee verisi okunamadı; güvenli cost floor uygulandı.'
                ));
                return;
            }
            if (key === 'orderbook_spread_pct' && feeDisplay && feeDisplay.spread_pct != null && (!ind[key] || Number(ind[key]) < 0.001)) {
                rows.push(dmParamAssistantMakeTile(
                    DM_PA_INDICATOR_LABELS[key] || key,
                    dmParamAssistantMetricPct(feeDisplay.spread_pct, 2, { noSign: true }),
                    DM_PA_INDICATOR_TIPS[key]
                ));
                return;
            }
            var txt = dmParamAssistantFormatIndicatorValue(key, ind[key]);
            if (txt != null) {
                rows.push(dmParamAssistantMakeTile(
                    DM_PA_INDICATOR_LABELS[key] || key,
                    txt,
                    DM_PA_INDICATOR_TIPS[key]
                ));
            }
        });
        return { title: group.title, rows: rows };
    }).filter(function (group) { return group.rows.length > 0; });
}

function dmParamAssistantBuildParamTileMap(rec) {
    var r = rec.backend || {};
    var tel = r.telemetry || {};
    var ui = rec.backend && rec.backend.ui_config ? rec.backend.ui_config : {};
    var profit = ui.profit || {};
    var rebuyOn = profit.rebuy_enabled === true;
    var resellOn = profit.resell_enabled === true;
    var allocDisp = rec.allocationDisplay || ui.allocation_display || {};
    var ladderDisp = rec.ladderDisplay || ui.ladder_display || {};
    var v6d = tel.v6_display || {};
    var strat = allocDisp.strategic_target || {};
    var p = tel.post_safety_params || tel.pre_safety_params || r.params || {};
    var map = {};
    var profileLabel = dmParamAssistantProfileTileLabel(r);
    map.profile = dmParamAssistantMakeTile(profileLabel, dmParamAssistantBackendProfileText(r), DM_PA_PARAM_TIPS.profile || DM_PA_CHIP_TIPS[profileLabel]);
    if (dmParamAssistantIsV6Result(r) && (r.v6_final_profile_id || (tel.v6_display && tel.v6_display.final_profile_id))) {
        map.final_profile = dmParamAssistantMakeTile(
            'Final profil',
            r.v6_final_profile_id || tel.v6_display.final_profile_id,
            'V6 ayarlayıcı pipeline sonrası nihai profil kimliği.'
        );
    }
    map.budget = dmParamAssistantMakeTile('Bütçe', dmParamAssistantInputTextTr(rec.budget, 2) + ' USDT', DM_PA_PARAM_TIPS.budget);
    var exactShelfId = dmParamAssistantExactShelfId(r);
    map.exact_shelf_id = dmParamAssistantMakeTile(
        'Exact raf ID',
        exactShelfId,
        DM_PA_PARAM_TIPS.exact_shelf_id,
        { mono: true }
    );
    var finalShelfId = dmParamAssistantFinalShelfId(r);
    if (finalShelfId && String(finalShelfId) !== String(exactShelfId)) {
        map.final_shelf_id = dmParamAssistantMakeTile(
            'Final profil ID',
            finalShelfId,
            DM_PA_PARAM_TIPS.final_shelf_id,
            { mono: true }
        );
    }
    var targetBase = v6d.base_allocation_pct != null ? v6d.base_allocation_pct : (strat.base_pct != null ? strat.base_pct : rec.basePct);
    var targetQuote = v6d.quote_allocation_pct != null ? v6d.quote_allocation_pct : (strat.quote_pct != null ? strat.quote_pct : rec.quotePct);
    var allocText = 'Hedef: coin %' + dmParamAssistantInputTextTr(targetBase, 1) +
        ' · USDT %' + dmParamAssistantInputTextTr(targetQuote, 1);
    map.allocation = dmParamAssistantMakeTile('Dağılım', allocText, DM_PA_PARAM_TIPS.allocation);
    var sellGrids = (ladderDisp.planned_sell_ladder && ladderDisp.planned_sell_ladder.length)
        ? ladderDisp.planned_sell_ladder
        : ((ladderDisp.active_sell_ladder && ladderDisp.active_sell_ladder.length)
            ? ladderDisp.active_sell_ladder
            : rec.upGrids);
    map.sell_grid = dmParamAssistantMakeTile(
        'Satış grid',
        sellGrids.length ? dmParamAssistantGridText(sellGrids, '+') : 'Kapalı',
        DM_PA_PARAM_TIPS.sell_grid
    );
    var activeBuy = ladderDisp.active_buy_ladder || rec.downGrids;
    map.buy_grid = dmParamAssistantMakeTile(
        'Alış grid',
        activeBuy.length ? dmParamAssistantGridText(activeBuy, '-') : 'Kapalı',
        DM_PA_PARAM_TIPS.buy_grid
    );
    map.trailing = dmParamAssistantMakeTile('Trailing', dmParamAssistantTrailingLabel(rec), DM_PA_PARAM_TIPS.trailing);
    map.rebuy = dmParamAssistantMakeTile(
        'Kar alım',
        rebuyOn
            ? ('tetik %' + dmParamAssistantInputTextTr(rec.rebuyTrigger, 2) +
                (rec.rebuyTrail > 0 ? ' · Trailing %' + dmParamAssistantInputTextTr(rec.rebuyTrail, 2) : ''))
            : 'Kapalı',
        DM_PA_PARAM_TIPS.rebuy
    );
    map.resell = dmParamAssistantMakeTile(
        'Kar satış',
        resellOn
            ? ('tetik %' + dmParamAssistantInputTextTr(rec.resellTrigger, 2) +
                (rec.resellTrail > 0 ? ' · Trailing %' + dmParamAssistantInputTextTr(rec.resellTrail, 2) : ''))
            : 'Kapalı',
        DM_PA_PARAM_TIPS.resell
    );
    map.profit_cycle = dmParamAssistantMakeTile('Kâr döngüsü', dmParamAssistantProfitCycleLabel(rec), DM_PA_PARAM_TIPS.profit_cycle);
    var buyOff = ui.buy_disabled || !activeBuy.length;
    if (p.sell_grid_spacing_pct != null || (!buyOff && p.buy_grid_spacing_pct != null)) {
        var gridText = buyOff
            ? ('Alış kapalı · Satış %' + dmParamAssistantInputTextTr(p.sell_grid_spacing_pct || 0, 2))
            : ('alış %' + dmParamAssistantInputTextTr(p.buy_grid_spacing_pct || 0, 2) +
                ' · satış %' + dmParamAssistantInputTextTr(p.sell_grid_spacing_pct || 0, 2));
        map.grid_step = dmParamAssistantMakeTile('Grid aralığı', gridText, DM_PA_PARAM_TIPS.grid_step);
    }
    if (p.take_profit_pct != null) {
        map.take_profit = dmParamAssistantMakeTile('Kâr hedefi', '%' + dmParamAssistantInputTextTr(p.take_profit_pct, 2), DM_PA_PARAM_TIPS.take_profit);
    }
    if (p.max_base_exposure_frac != null) {
        map.max_exposure = dmParamAssistantMakeTile('Maks. maruziyet', '%' + dmParamAssistantInputTextTr(p.max_base_exposure_frac * 100, 1), DM_PA_PARAM_TIPS.max_exposure);
    }
    if (p.min_cycle_profit_after_fee_pct != null) {
        map.min_profit_fee = dmParamAssistantMakeTile('Min. kâr/komisyon', '%' + dmParamAssistantInputTextTr(p.min_cycle_profit_after_fee_pct, 2), DM_PA_PARAM_TIPS.min_profit_fee);
    }
    if (p.max_quote_to_spend_per_buy_frac != null) {
        map.buy_quota = dmParamAssistantMakeTile('Alış kotası', '%' + dmParamAssistantInputTextTr(p.max_quote_to_spend_per_buy_frac * 100, 1), DM_PA_PARAM_TIPS.buy_quota);
    }
    if (p.stop_new_buys_below_score != null) {
        map.stop_buys = dmParamAssistantMakeTile('Alış durdur', 'skor < ' + p.stop_new_buys_below_score, DM_PA_PARAM_TIPS.stop_buys);
    }
    if (p.trailing_enabled != null) {
        map.trailing_mode = dmParamAssistantMakeTile('Trailing modu', p.trailing_enabled ? 'Açık' : 'Kapalı', DM_PA_PARAM_TIPS.trailing_mode);
    }
    if (p.emergency_no_buy) map.emergency_no_buy = dmParamAssistantMakeTile('Acil alış', 'Kapalı', DM_PA_PARAM_TIPS.emergency_no_buy);
    if (p.sell_only_mode || p.buy_disabled) map.buy_mode = dmParamAssistantMakeTile('Alış modu', 'Kapalı', DM_PA_PARAM_TIPS.buy_mode);
    if (p.downtrend_buy_throttle) map.downtrend_throttle = dmParamAssistantMakeTile('Düşüş freni', 'Açık', DM_PA_PARAM_TIPS.downtrend_throttle);
    return map;
}

function dmParamAssistantBuildParamGroups(rec) {
    var map = dmParamAssistantBuildParamTileMap(rec);
    return DM_PA_PARAM_GROUPS.map(function (group) {
        var rows = [];
        group.keys.forEach(function (key) {
            if (map[key]) rows.push(map[key]);
        });
        return { title: group.title, rows: rows };
    }).filter(function (group) { return group.rows.length > 0; });
}

function dmParamAssistantBuildDebugParamGroups(rec) {
    var map = dmParamAssistantBuildParamTileMap(rec);
    return DM_PA_DEBUG_PARAM_GROUPS.map(function (group) {
        var rows = [];
        group.keys.forEach(function (key) {
            if (map[key]) rows.push(map[key]);
        });
        return { title: group.title, rows: rows };
    }).filter(function (group) { return group.rows.length > 0; });
}

function dmParamAssistantIsV5Selection(sel, tmpl) {
    var ctx = (sel && sel.selection_context) || {};
    if (String(ctx.engine_version || '') === 'DPS_ENGINE_V5') return true;
    if (String(sel.pool_version || '').indexOf('v5') === 0) return true;
    return String(tmpl || sel.selected_template_key || '').indexOf('DPLV5_') === 0;
}

function dmParamAssistantBuildSubScoreGroups(rec) {
    var r = rec.backend || {};
    var sub = (r.rationale && r.rationale.sub_scores) || (r.telemetry && r.telemetry.sub_scores) || {};
    var rows = [];
    Object.keys(DM_PA_SUB_SCORE_LABELS).forEach(function (key) {
        if (sub[key] == null) return;
        rows.push(dmParamAssistantMakeTile(
            DM_PA_SUB_SCORE_LABELS[key],
            String(sub[key]) + '/100',
            'Motorun bu girdiyi hesaplamada kullandığı alt skor.'
        ));
    });
    return rows.length ? [{ title: 'Alt skorlar', rows: rows }] : [];
}

function dmParamAssistantBuildV6AdjusterGroups(rec) {
    var r = rec.backend || {};
    var tel = r.telemetry || {};
    var trace = (r.selection_telemetry && r.selection_telemetry.adjuster_trace) ||
        (tel.v6_display && tel.v6_display.adjuster_trace) || [];
    if (!trace.length) return [];
    var labels = {
        data_quality: 'Veri kalitesi',
        btc_context: 'BTC bağlamı',
        asset_fragility: 'Varlık kırılganlığı',
        volatility: 'Volatilite',
        liquidity: 'Likidite',
        support_resistance: 'Destek / direnç',
        fake_move: 'Sahte hareket',
        delta_limiter: 'Delta sınırı',
        budget_scaler: 'Bütçe ölçekleyici',
        exchange_validator: 'Borsa doğrulayıcı'
    };
    var rows = trace.map(function (entry) {
        var name = entry.name || 'adjuster';
        var label = labels[name] || name;
        var cls = entry.class != null ? String(entry.class) : '—';
        var riskKey = name + '_risk_score';
        var riskScore = entry.data_quality_risk_score != null ? entry.data_quality_risk_score :
            entry.btc_market_risk_score != null ? entry.btc_market_risk_score :
            entry.fragility_risk_score != null ? entry.fragility_risk_score :
            entry.volatility_risk_score != null ? entry.volatility_risk_score :
            entry.liquidity_risk_score != null ? entry.liquidity_risk_score :
            entry.score;
        var val = cls + ' · risk ' + (riskScore != null ? riskScore : '—');
        if (name === 'btc_context' && entry.delta_multiplier != null) {
            val += ' · çarpan ' + entry.delta_multiplier;
        }
        return dmParamAssistantMakeTile(label, val, 'V6 ayarlayıcı pipeline adımı.');
    });
    return [{ title: 'V6 ayarlayıcı izi', rows: rows }];
}

function dmParamAssistantBuildSelectionTraceTiles(result) {
    var sel = (result && result.selection_telemetry) || {};
    var ctx = sel.selection_context || {};
    var tmpl = sel.selected_template_key || result.selected_profile || '';
    var isV5 = dmParamAssistantIsV5Selection(sel, tmpl);
    var isV6 = dmParamAssistantIsV6Result(result);
    var rows = [];
    function add(label, val) {
        if (val == null || val === '') return;
        rows.push(dmParamAssistantMakeTile(label, String(val), 'Seçim telemetrisi — gelişmiş debug.'));
    }
    if (isV6) {
        add('Motor sürümü', sel.engine_version || ctx.engine_version || 'DPS_ENGINE_V6');
        var v6disp = (result && result.telemetry && result.telemetry.v6_display) || {};
        var scen = v6disp.scenario_identity || ctx.scenario_identity || {};
        add('Rejim kodu', scen.regime_id || ctx.regime_id);
        add('Alt senaryo', scen.sub_id ? ('alt-' + scen.sub_id) : null);
        add('Mikro senaryo', scen.micro_id ? ('mikro-' + scen.micro_id) : null);
        add('Terminal', scen.terminal_id || ctx.terminal_id);
        add('Davranış kodu', scen.behavior_id || sel.behavior_id || ctx.behavior_id);
        add('Senaryo adı', scen.name || ctx.scenario_name);
        add('Teknik rejim özeti', (result && result.display_regime_technical) ||
            v6disp.display_regime_technical || ctx.display_regime_technical);
        add('Katalog profil', sel.catalog_profile_id || tmpl);
        add('Final profil', sel.final_profile_id || ((result && result.telemetry && result.telemetry.v6_display) || {}).final_profile_id);
        add('Davranış', sel.behavior_id || ctx.behavior_id);
        add('Şiddet', sel.severity || ctx.severity);
        add('Seçim tipi', ctx.selection_type || sel.selection_type);
        add('Seçim nedeni', sel.selection_reason || ctx.selection_reason);
        add('Profil skoru', sel.selected_profile_score != null ? sel.selected_profile_score + '/100' : null);
        return rows.length ? [{ title: 'V6 seçim izi', rows: rows }] : [];
    }
    if (isV5) {
        add('Route key', ctx.route_key || ctx.v5_route_key || sel.route_key);
        add('V5 shelf ID', ctx.v5_shelf_id || tmpl);
        add('Seçim tipi', ctx.selection_type || sel.selection_type);
        add('Exact hit', ctx.exact_route_hit === true ? 'evet' : (ctx.exact_route_hit === false ? 'hayır' : null));
        add('Fallback kullanıldı', sel.fallback_used === true ? 'evet' : (sel.fallback_used === false ? 'hayır' : null));
        if (sel.fallback_reason) add('Fallback nedeni', sel.fallback_reason);
        add('Motor sürümü', ctx.engine_version || 'DPS_ENGINE_V5');
    } else {
        add('Exact route aday', sel.exact_route_candidate_count);
        add('Fallback route', sel.fallback_route);
        add('Fallback aday', sel.fallback_candidate_count);
        add('Skorlanan aday', sel.scored_candidate_count);
        add('Profil skoru', sel.selected_profile_score != null ? sel.selected_profile_score + '/100' : null);
        add('Fallback kullanıldı', sel.fallback_used === true ? 'evet' : (sel.fallback_used === false ? 'hayır' : null));
        add('Route index fallback', sel.route_index_fallback_used === true ? 'evet' : null);
        if (sel.runtime_safe_profile_generated) {
            rows.push(dmParamAssistantMakeTile(
                'Runtime profil',
                'güvenli üretici devrede',
                'Route rafı boştu; runtime safe profile generator çalıştı.'
            ));
        }
    }
    if (sel.selection_reason) {
        rows.push(dmParamAssistantMakeTile('Seçim nedeni', sel.selection_reason, 'Raf seçim gerekçesi.'));
    }
    return rows.length ? [{ title: 'Seçim izi', rows: rows }] : [];
}

function dmParamAssistantBuildFeeDisplayTiles(result) {
    var fee = (result && result.fee_display) ||
        (result && result.selection_telemetry && result.selection_telemetry.fee_display) || {};
    if (!fee || (!fee.display_note && fee.fee_data_available === undefined && !fee.fee_mode)) return [];
    var rows = [];
    if (fee.fee_mode === 'disabled' || fee.status === 'v6_cost_floor') {
        rows.push(dmParamAssistantMakeTile('Komisyon modu', fee.mode_label || 'Canlı fee kullanılmaz', DM_PA_PARAM_TIPS.fee_floor));
        rows.push(dmParamAssistantMakeTile(
            'Maliyet tabanı',
            fee.floor_label || ('Sabit cost floor %' + dmParamAssistantInputTextTr(fee.total_cost_floor_pct || 1.2, 1)),
            DM_PA_PARAM_TIPS.fee_floor
        ));
        return [{ title: 'Komisyon ve maliyet', rows: rows }];
    }
    if (fee.display_note) {
        rows.push(dmParamAssistantMakeTile('Fee verisi', 'yok / okunamadı', fee.display_note));
        rows.push(dmParamAssistantMakeTile(
            'Güvenli cost floor',
            '%' + dmParamAssistantInputTextTr(fee.total_cost_floor_pct || 1.2, 2),
            DM_PA_PARAM_TIPS.fee_floor
        ));
        return [{ title: 'Komisyon ve maliyet', rows: rows }];
    }
    function pct(label, val) {
        if (val == null) return;
        rows.push(dmParamAssistantMakeTile(label, '%' + dmParamAssistantInputTextTr(val, 2), DM_PA_PARAM_TIPS.fee_floor));
    }
    pct('Maker fee', fee.maker_fee_pct);
    pct('Taker fee', fee.taker_fee_pct);
    pct('Roundtrip fee', fee.roundtrip_fee_pct);
    pct('Spread', fee.spread_pct);
    pct('Slippage tahmini', fee.estimated_slippage_pct);
    pct('Rounding', fee.rounding_cost_pct);
    pct('Toplam cost floor', fee.total_cost_floor_pct);
    return rows.length ? [{ title: 'Komisyon ve maliyet', rows: rows }] : [];
}

function dmParamAssistantBuildV6PresentationLines(result, rec) {
    var r = result || (rec && rec.backend) || {};
    var tel = r.telemetry || {};
    var v6d = tel.v6_display || {};
    var align = tel.scenario_alignment || {};
    var lines = [];
    var headline = v6d.regime_headline || align.regime_headline ||
        ((r.regime_tag || '') + ' · ' + dmParamAssistantRegimeLabel(r.regime_tag));
    var status = v6d.market_status_plain || align.regime_label_plain || dmParamAssistantMarketStatusPlain({ backend: r });
    var why = v6d.regime_strategy_why || align.regime_strategy_why || '';
    var grid = v6d.grid_strategy_plain || align.grid_strategy_plain || dmParamAssistantV6GridPlanPlain({ backend: r });
    var opMode = v6d.operational_mode_plain || align.operational_mode_plain || '';
    var score = r.param_score != null ? r.param_score : (rec && rec.paramScore);
    lines.push(headline + ' — ' + status);
    if (why && why !== status) lines.push(why);
    lines.push('Grid planı: ' + grid + '.');
    if (opMode) lines.push('Çalışma modu: ' + opMode + '.');
    if (v6d.profit_loop_plain || align.profit_loop_plain) {
        lines.push('Kâr döngüsü: ' + (v6d.profit_loop_plain || align.profit_loop_plain) + '.');
    }
    if (score != null) {
        lines.push('Parametre skoru ' + score + '/100 · komisyon tabanı %1,2 korunarak hesaplandı.');
    }
    lines.push('Not: Bu karar Dynamic Param Score Engine tarafından üretildi; Dinamik Mod her tur başında aynı motoru kullanır.');
    return lines;
}

function dmParamAssistantFormatSelectionPickLine(result) {
    var sel = result.selection_telemetry || (result.telemetry && result.telemetry.param_pool) || {};
    var ctx = sel.selection_context || {};
    var tmpl = sel.selected_template_key || result.selected_profile || '—';
    if (dmParamAssistantIsV6Result(result)) {
        var v6d = (result.telemetry && result.telemetry.v6_display) || {};
        var headline = v6d.regime_headline || ('V6 · ' + dmParamAssistantRegimeLabel(result.regime_tag));
        var grid = v6d.grid_plan_plain || dmParamAssistantV6GridPlanPlain({ backend: result });
        var beh = sel.behavior_id || ctx.behavior_id || v6d.behavior_id || '';
        var parts = [headline];
        if (grid) parts.push('Grid: ' + grid);
        if (beh) parts.push('Davranış ' + beh);
        return parts.join(' · ');
    }
    var routeKey = sel.route_key || ctx.route_key || ctx.v5_route_key || (sel.selection_context && sel.selection_context.route_key) || '';
    var isV5 = dmParamAssistantIsV5Selection(sel, tmpl);
    if (isV5) {
        var pickLine = routeKey
            ? ('Route ' + routeKey + ' için exact V5 raf: ' + tmpl)
            : ('Exact V5 raf: ' + tmpl);
        var parts = [];
        if (ctx.exact_route_hit != null) parts.push('Exact hit: ' + (ctx.exact_route_hit ? 'evet' : 'hayır'));
        if (sel.fallback_used != null) parts.push('Fallback: ' + (sel.fallback_used ? 'evet' : 'hayır'));
        if (ctx.selection_type) parts.push('Seçim: ' + ctx.selection_type);
        if (parts.length) pickLine += '. ' + parts.join(' · ');
        return pickLine;
    }
    var pickLine = routeKey
        ? ('Route ' + routeKey + ' rafından seçilen profil: ' + tmpl)
        : ('Seçilen profil: ' + tmpl);
    if (sel.runtime_safe_profile_generated) {
        pickLine += '. Exact route aday: ' + (sel.exact_route_candidate_count != null ? sel.exact_route_candidate_count : 0) +
            ' · Runtime güvenli profil üretildi';
        return pickLine;
    }
    var exact = sel.exact_route_candidate_count;
    var scored = sel.scored_candidate_count != null ? sel.scored_candidate_count : sel.candidate_count;
    var fbUsed = sel.fallback_used || sel.route_index_fallback_used;
    var parts = [];
    if (exact != null) parts.push('Exact route aday: ' + exact);
    if (fbUsed && sel.fallback_route) {
        parts.push('Fallback route: ' + sel.fallback_route);
        if (sel.fallback_candidate_count != null) {
            parts.push('Fallback aday: ' + sel.fallback_candidate_count);
        }
    }
    if (scored != null && scored !== '') parts.push('Skorlanan aday: ' + scored);
    if (sel.selected_profile_score != null) {
        parts.push('Seçilen profil skoru: ' + sel.selected_profile_score + '/100');
    }
    if (fbUsed != null) parts.push('Fallback used: ' + (fbUsed ? 'true' : 'false'));
    if (parts.length) pickLine += '. ' + parts.join(' · ');
    return pickLine;
}

function dmParamAssistantBuildSafetyGroups(rec) {
    var r = rec.backend || {};
    var tel = r.telemetry || {};
    var ad = r.action_detail || tel.action_detail || {};
    var minN = tel.min_notional || 10;
    var headroom = tel.exposure_headroom_quote_usdt;
    var ladder = tel.buy_ladder_budget_usdt;
    var worst = tel.worst_case_base_exposure_frac;
    var feeFloor = tel.fee_floor_pct || tel.min_grid_spacing_pct;
    var rows = [];
    if (headroom != null) {
        rows.push(dmParamAssistantMakeTile('Headroom', dmParamAssistantInputTextTr(headroom, 2) + ' USDT', DM_PA_PARAM_TIPS.headroom));
    }
    rows.push(dmParamAssistantMakeTile('Min. emir tutarı', dmParamAssistantInputTextTr(minN, 2) + ' USDT', DM_PA_PARAM_TIPS.min_notional));
    if (ladder != null) {
        rows.push(dmParamAssistantMakeTile(
            'Alış merdiveni bütçesi',
            dmParamAssistantInputTextTr(ladder, 2) + ' USDT',
            'Exposure/min-notional sonrası bu turda grid alışlarına ayrılan quote bütçesi.'
        ));
    }
    var allocDisp = (r.ui_config && r.ui_config.allocation_display) || {};
    if (allocDisp.active_buy_ladder_usdt != null && Math.abs(Number(allocDisp.active_buy_ladder_usdt) - Number(ladder || 0)) > 0.05) {
        rows.push(dmParamAssistantMakeTile(
            'Aktif alış ladder toplamı',
            dmParamAssistantInputTextTr(allocDisp.active_buy_ladder_usdt, 2) + ' USDT',
            'Emir niyeti planındaki grid alışlarının toplam quote tutarı.'
        ));
    }
    if (worst != null && r.params && r.params.max_base_exposure_frac != null) {
        rows.push(dmParamAssistantMakeTile(
            'En kötü maruziyet',
            dmParamAssistantInputTextTr(worst * 100, 1) + '% / maks %' + dmParamAssistantInputTextTr(r.params.max_base_exposure_frac * 100, 1),
            DM_PA_PARAM_TIPS.worst_exposure
        ));
    } else if (worst != null) {
        rows.push(dmParamAssistantMakeTile('En kötü maruziyet', dmParamAssistantInputTextTr(worst * 100, 1) + '%', DM_PA_PARAM_TIPS.worst_exposure));
    }
    if (feeFloor != null) {
        rows.push(dmParamAssistantMakeTile('Komisyon tabanı', '%' + dmParamAssistantInputTextTr(feeFloor, 2), DM_PA_PARAM_TIPS.fee_floor));
    }
    rows.push(dmParamAssistantMakeTile(
        'Güvenlik sonucu',
        r.final_action_label || dmParamAssistantActionLabel(ad.post_safety_action || r.final_action, r),
        DM_PA_PARAM_TIPS.safety_result
    ));
    return rows.length ? [{ title: 'Borsa ve maruziyet', rows: rows }] : [];
}

function dmParamAssistantBackendSummarySections(rec) {
    var r = rec.backend || {};
    var tel = r.telemetry || {};
    var ind = tel.indicators || {};
    var notice = '';
    if (rec.sellManagementOnly || r.final_action === 'SELL_MANAGEMENT_ONLY') {
        notice = 'Güvenlik kontrolü alış tarafını kapattı; yalnızca satış yönetimi parametreleri gösteriliyor.';
    }
    return {
        notice: notice,
        params: {
            title: 'Önerilen parametreler',
            groups: dmParamAssistantBuildParamGroups(rec)
        },
        indicators: {
            title: 'Piyasa verileri ve indikatörler',
            groups: dmParamAssistantBuildIndicatorGroups(ind, r)
        },
        sub_scores: {
            title: 'Motor alt skorları',
            groups: dmParamAssistantBuildSubScoreGroups(rec)
        },
        v6_engine: {
            title: 'V6 motor detayı',
            groups: dmParamAssistantIsV6Result(r) ? dmParamAssistantBuildV6AdjusterGroups(rec) : []
        },
        safety: {
            title: 'Güvenlik kontrolleri',
            groups: dmParamAssistantBuildSafetyGroups(rec)
        }
    };
}

function dmParamAssistantRenderSummarySectionsHtml(sections, rec) {
    return dmParamAssistantRenderParamsSectionHtml(rec) + dmParamAssistantRenderDetailsSectionsHtml(sections, rec, rec.backend);
}

function dmParamAssistantTrailingLabel(rec) {
    var sellOnly = rec.sellManagementOnly || (rec.downGrids.length === 0 && rec.upGrids.length > 0);
    if (sellOnly) {
        if (rec.upGrids.length > 0 && rec.upTrail > 0) {
            return 'Alış kapalı · Satış %' + dmParamAssistantInputTextTr(rec.upTrail, 2);
        }
        return 'Kapalı';
    }
    if (!rec.upGrids.length && !rec.downGrids.length) return 'Kapalı';
    var parts = [];
    if (rec.upGrids.length && rec.upTrail > 0) parts.push('Satış %' + dmParamAssistantInputTextTr(rec.upTrail, 2));
    if (rec.downGrids.length && rec.downTrail > 0) parts.push('Alış %' + dmParamAssistantInputTextTr(rec.downTrail, 2));
    return parts.length ? parts.join(' · ') : 'Kapalı';
}

function dmParamAssistantProfitCycleLabel(rec) {
    var ui = rec.backend && rec.backend.ui_config ? rec.backend.ui_config : {};
    var profit = ui.profit || {};
    var rebuyOn = profit.rebuy_enabled === true;
    var resellOn = profit.resell_enabled === true;
    function cyclePart(sign, trigger, trail) {
        var txt = sign + '%' + dmParamAssistantInputTextTr(trigger, 2);
        if (trail > 0) txt += ' · trailing %' + dmParamAssistantInputTextTr(trail, 2);
        return txt;
    }
    if (!rebuyOn && !resellOn) {
        return 'Satış sonrası kar alım: Kapalı · Kar satış: Kapalı';
    }
    if (rebuyOn && resellOn) {
        return 'Satış sonrası kar alım: ' + cyclePart('-', rec.rebuyTrigger, rec.rebuyTrail) +
            ' · Kar alım sonrası kar satış: ' + cyclePart('+', rec.resellTrigger, rec.resellTrail);
    }
    if (rebuyOn) {
        return 'Satış sonrası kar alım: ' + cyclePart('-', rec.rebuyTrigger, rec.rebuyTrail) +
            ' · Kar satış: Kapalı';
    }
    return 'Satış sonrası kar alım: Kapalı · Kar satış: Kapalı';
}

function dmParamAssistantSafetySummaryRows(rec) {
    var r = rec.backend || {};
    var tel = r.telemetry || {};
    var ad = r.action_detail || tel.action_detail || {};
    var minN = tel.min_notional || 10;
    var headroom = tel.exposure_headroom_quote_usdt;
    var ladder = tel.buy_ladder_budget_usdt;
    var worst = tel.worst_case_base_exposure_frac;
    var feeFloor = tel.fee_floor_pct || tel.min_grid_spacing_pct;
    var rows = [];
    if (headroom != null) rows.push(['Headroom', dmParamAssistantInputTextTr(headroom, 2) + ' USDT']);
    rows.push(['Min-notional', dmParamAssistantInputTextTr(minN, 2) + ' USDT']);
    if (ladder != null) rows.push(['Alış ladder bütçesi', dmParamAssistantInputTextTr(ladder, 2) + ' USDT']);
    if (worst != null && r.params && r.params.max_base_exposure_frac != null) {
        rows.push(['Worst-case exposure', dmParamAssistantInputTextTr(worst * 100, 1) + '% / max %' + dmParamAssistantInputTextTr(r.params.max_base_exposure_frac * 100, 1)]);
    } else if (worst != null) {
        rows.push(['Worst-case exposure', dmParamAssistantInputTextTr(worst * 100, 1) + '%']);
    }
    if (feeFloor != null) rows.push(['Fee floor', '%' + dmParamAssistantInputTextTr(feeFloor, 2)]);
    rows.push(['Güvenlik sonucu', dmParamAssistantActionLabel(ad.post_safety_action || r.final_action, r)]);
    return rows;
}

function dmParamAssistantGreetingText(snapshot, rec) {
    var pq = parseBaseQuote(snapshot.symbol || '');
    var name = dmParamAssistantCurrentUserName(snapshot);
    var tel = rec && rec.backend && rec.backend.telemetry ? rec.backend.telemetry : {};
    var sub = tel.sub_scores || {};
    var v6d = tel.v6_display || {};
    var coverage = 'sınırlı';
    if (v6d.data_quality_label) {
        coverage = String(v6d.data_quality_label).toLowerCase().indexOf('yeterli') >= 0 ? 'yeterli' :
            (String(v6d.data_quality_label).toLowerCase().indexOf('hafif') >= 0 ? 'orta' : 'sınırlı');
    } else {
        coverage = sub.data_quality_score >= 70 ? 'yeterli' : (sub.data_quality_score >= 50 ? 'orta' : 'sınırlı');
    }
    var values = {
        name: name,
        symbol: snapshot.symbol || 'bu parite',
        base: snapshot.base || pq.base || 'coin',
        quote: snapshot.quote || pq.quote || 'USDT',
        regime: rec && rec.regime ? rec.regime : 'piyasa',
        basePct: rec && rec.basePct != null ? dmParamAssistantInputTextTr(rec.basePct, 1) : '',
        quotePct: rec && rec.quotePct != null ? dmParamAssistantInputTextTr(rec.quotePct, 1) : '',
        price: snapshot.price != null ? dmParamAssistantDisplayPrice(snapshot.price, snapshot.quote) : '',
        change: snapshot.changePct != null ? dmParamAssistantDisplayPct(snapshot.changePct, 2) : '',
        coverage: coverage,
        budget: rec && rec.budget != null ? dmParamAssistantInputTextTr(rec.budget, 2) + ' ' + (snapshot.quote || 'USDT') : '',
        confidence: rec && rec.confidence != null ? rec.confidence : ''
    };
    if (AI_ASSISTANT_SPEC && typeof AI_ASSISTANT_SPEC.greeting === 'function') {
        return AI_ASSISTANT_SPEC.greeting(values);
    }
    var pool = DM_PARAM_ASSISTANT_GREETING_POOL;
    var template = pool[dmParamAssistantRandomIndex(pool.length)] || pool[0];
    return String(template || '').replace(/\{(name|symbol|base|quote|regime)\}/g, function (_, key) {
        return values[key] || '';
    });
}

function dmParamAssistantLines(snapshot, rec) {
    var sym = snapshot.symbol || 'parite';
    var price = dmParamAssistantDisplayPrice(snapshot.price, snapshot.quote);
    var change = snapshot.changePct == null ? '—' : dmParamAssistantDisplayPct(snapshot.changePct, 2);
    var high = dmParamAssistantDisplayPrice(snapshot.high, snapshot.quote);
    var low = dmParamAssistantDisplayPrice(snapshot.low, snapshot.quote);
    var dyn = snapshot.dynamicMode ? 'açık' : 'kapalı';
    var a = rec.analysis || {};
    var w = a.windows || {};
    var dataText = (a.dataBars && a.dataBars.daily ? a.dataBars.daily : 0) + ' günlük, ' +
        (a.dataBars && a.dataBars.hourly ? a.dataBars.hourly : 0) + ' saatlik, ' +
        (a.dataBars && a.dataBars.m5 ? a.dataBars.m5 : 0) + ' adet 5 dakikalık mum';
    var copySpec = AI_ASSISTANT_SPEC.copy || {};
    var partialText = a.partial
        ? (copySpec.dataPartial || 'Bazı geçmiş pencerelerde veri sınırlı geldi; öneriyi güven skoruna indirim vererek ürettim.')
        : (copySpec.dataHealthy || 'Veri akışı yeterli; öneriyi çok pencereli hesapla üretiyorum.');
    var scenarioLines = [];
    var rationaleLines = [];
    var aiLineValues = {
        name: dmParamAssistantCurrentUserName(snapshot),
        symbol: sym,
        base: snapshot.base || 'coin',
        quote: snapshot.quote || 'USDT',
        price: price,
        change: change,
        coverage: dmParamAssistantCoverageText(a),
        dataText: dataText,
        regime: rec.regime,
        volatility: rec.volatility,
        trendScore: dmParamAssistantMetricPct((a.trendScore || 0) * 100, 0),
        adx: a.adx == null ? '—' : dmParamAssistantInputTextTr(a.adx, 1),
        rsi: a.rsi == null ? '—' : dmParamAssistantInputTextTr(a.rsi, 1),
        volUnit: '%' + dmParamAssistantInputTextTr(rec.math.volUnit, 2),
        stepPct: '%' + dmParamAssistantInputTextTr(rec.math.stepPct, 2),
        riskScore: rec.math.riskScore,
        opportunityScore: rec.math.opportunityScore,
        budget: dmParamAssistantInputTextTr(rec.budget, 2),
        basePct: dmParamAssistantInputTextTr(rec.basePct, 1),
        quotePct: dmParamAssistantInputTextTr(rec.quotePct, 1),
        upGridCount: rec.upGrids.length,
        downGridCount: rec.downGrids.length,
        upTrail: dmParamAssistantInputTextTr(rec.upTrail, 2),
        downTrail: dmParamAssistantInputTextTr(rec.downTrail, 2),
        rebuyTrigger: dmParamAssistantInputTextTr(rec.rebuyTrigger, 2),
        resellTrigger: dmParamAssistantInputTextTr(rec.resellTrigger, 2),
        sellGridText: dmParamAssistantGridText(rec.upGrids, '+'),
        buyGridText: dmParamAssistantGridText(rec.downGrids, '-'),
        confidence: rec.confidence
    };
    if (AI_ASSISTANT_SPEC && typeof AI_ASSISTANT_SPEC.paramScenarioLines === 'function') {
        scenarioLines = AI_ASSISTANT_SPEC.paramScenarioLines(aiLineValues, 6);
    }
    if (AI_ASSISTANT_SPEC && typeof AI_ASSISTANT_SPEC.paramRationaleLines === 'function') {
        rationaleLines = AI_ASSISTANT_SPEC.paramRationaleLines(aiLineValues);
    }
    var head = [
        'Anlık ekran: fiyat ' + price + ', 24s değişim ' + change + ', 24s yüksek ' + high + ', 24s düşük ' + low + '. Dinamik strateji şu an ' + dyn + '.',
        'Geçmiş taraması: ' + dataText + '. Kapsama kalitesi ' + dmParamAssistantCoverageText(a) + '. ' + partialText,
    ];
    if (a.insufficientData) {
        var issueText = a.dataIssues && a.dataIssues.length ? ' Sorun: ' + a.dataIssues.slice(0, 4).join(', ') + '.' : '';
        head.unshift('⛔ Geçmiş veri yeterince doğrulanamadı (' + dataText + '). Aşağıdaki rejim/ADX/RSI/risk değerleri tam güvenilir okuma değil — bu parametreleri UYGULAMA. Lütfen birkaç saniye sonra tekrar dene veya sunucu backtest analizini çalıştır.' + issueText);
    }
    return head.concat(scenarioLines).concat([
        dmParamAssistantWindowText(w.m1) + '.',
        dmParamAssistantWindowText(w.m3) + '.',
        dmParamAssistantWindowText(w.y1) + '.',
        dmParamAssistantWindowText(w.y4) + '.',
        'Rejim sonucu: ' + rec.regime + ', volatilite ' + rec.volatility + ', trend skoru ' + dmParamAssistantMetricPct((a.trendScore || 0) * 100, 0) + ', ADX ' + (a.adx == null ? '—' : dmParamAssistantInputTextTr(a.adx, 1)) + ', RSI ' + (a.rsi == null ? '—' : dmParamAssistantInputTextTr(a.rsi, 1)) + '.',
        'Grid denklemi: aralık = max(ücret tabanı %' + dmParamAssistantInputTextTr(rec.math.feeFloorPct, 2) + ', ATR bileşiği %' + dmParamAssistantInputTextTr(rec.math.volUnit, 2) + ' × rejim katsayısı) = %' + dmParamAssistantInputTextTr(rec.math.stepPct, 2) + '.',
        'Risk denklemi: drawdown + downside volatilite + trend baskısı = ' + rec.math.riskScore + '/100. Fırsat denklemi: kullanılabilir volatilite + yataylık/chop - risk indirimi = ' + rec.math.opportunityScore + '/100.',
        'Bütçe tarafında ' + dmParamAssistantInputTextTr(rec.budget, 2) + ' ' + snapshot.quote + ' kullanıyorum; grid adedini minimum emir tutarını bozmayacak şekilde ' + rec.upGrids.length + ' seviyede tutuyorum.',
        'Başlangıç dağılımı: base %' + dmParamAssistantInputTextTr(rec.basePct, 1) + ' / quote %' + dmParamAssistantInputTextTr(rec.quotePct, 1) + '. Bu dağılım rejim yönünü dikkate alıyor ama iki bacağı da çalışabilir bırakıyor.',
        'Satış gridleri: ' + dmParamAssistantGridText(rec.upGrids, '+') + '.',
        'Alış gridleri: ' + dmParamAssistantGridText(rec.downGrids, '-') + '.',
        'Trailing: satış %' + dmParamAssistantInputTextTr(rec.upTrail, 2) + ', alış %' + dmParamAssistantInputTextTr(rec.downTrail, 2) + '. Kâr döngüsü: rebuy tetik %' + dmParamAssistantInputTextTr(rec.rebuyTrigger, 2) + ' / trail %' + dmParamAssistantInputTextTr(rec.rebuyTrail, 2) + ', resell tetik %' + dmParamAssistantInputTextTr(rec.resellTrigger, 2) + ' / trail %' + dmParamAssistantInputTextTr(rec.resellTrail, 2) + '.',
        'Güven skoru ' + rec.confidence + '/100. Bu set kâr ihtimalini artırmak için gürültüye fazla yakın durmadan, geçmiş bantlara ve güncel rejime göre kapanabilir mesafe üretmek üzere ayarlandı.',
        'Şimdi seçtiğim parametrelerin gerekçesini tek tek açıyorum; burada amaç sayıları ezbere yazmak değil, her inputun hangi risk ve fırsat mantığına bağlandığını göstermek.'
    ]).concat(rationaleLines).concat([
        'Son karar cümlem: bu parametreler bugünkü veriyle uyumlu bir başlangıç planı üretir; uygulandıktan sonra tur kapanış kalitesi, komisyon etkisi ve alpha sonucu birlikte izlenmelidir.'
    ]);
}

function dmParamAssistantChipItems(snapshot, rec) {
    if (rec && rec.backend) return dmParamAssistantBackendChipItems(snapshot, rec);
    var a = rec.analysis || {};
    var w = a.windows || {};
    return [
        ['Parite', snapshot.symbol || '—'],
        ['Fiyat', dmParamAssistantDisplayPrice(snapshot.price, snapshot.quote)],
        ['24s', snapshot.changePct == null ? '—' : dmParamAssistantDisplayPct(snapshot.changePct, 2)],
        ['1 ay', w.m1 && w.m1.returnPct != null ? dmParamAssistantMetricPct(w.m1.returnPct, 1) : '—'],
        ['3 ay', w.m3 && w.m3.returnPct != null ? dmParamAssistantMetricPct(w.m3.returnPct, 1) : '—'],
        ['1 yıl', w.y1 && w.y1.returnPct != null ? dmParamAssistantMetricPct(w.y1.returnPct, 1) : '—'],
        ['4 yıl', w.y4 && w.y4.returnPct != null ? dmParamAssistantMetricPct(w.y4.returnPct, 1) : '—'],
        ['Rejim', rec.regime],
        ['ATR bileşik', '%' + dmParamAssistantInputTextTr(rec.math.volUnit, 2)],
        ['Step', '%' + dmParamAssistantInputTextTr(rec.math.stepPct, 2)],
        ['Güven', rec.confidence + '/100']
    ];
}

function dmParamAssistantFlattenSectionTiles(sections) {
    function fromGroups(groups) {
        return (groups || []).reduce(function (acc, group) {
            return acc.concat((group.rows || []).map(function (tile) {
                return [tile.label, tile.value];
            }));
        }, []);
    }
    return fromGroups(sections.params && sections.params.groups)
        .concat(fromGroups(sections.indicators && sections.indicators.groups))
        .concat(fromGroups(sections.sub_scores && sections.sub_scores.groups))
        .concat(fromGroups(sections.v6_engine && sections.v6_engine.groups))
        .concat(fromGroups(sections.safety && sections.safety.groups));
}

function dmParamAssistantRenderChips(snapshot, rec, opts) {
    var chips = document.getElementById('dmParamAssistantChips');
    if (!chips) return;
    opts = opts || {};
    var items = dmParamAssistantChipItems(snapshot, rec);
    chips.innerHTML = items.map(function (it, idx) {
        var cls = opts.animated ? ' class="dm-param-assistant-chip-ai"' : '';
        var style = opts.animated ? ' style="--dm-chip-delay:' + (idx * 70) + 'ms"' : '';
        var tip = DM_PA_CHIP_TIPS[it[0]];
        var tipAttr = tip ? ' data-dyn-tip="' + dmParamAssistantAttrEscape(tip) + '"' : '';
        return '<span' + cls + style + tipAttr + '><b>' + dmParamAssistantEscape(it[0]) + '</b>' + dmParamAssistantEscape(it[1]) + '</span>';
    }).join('');
}

function dmParamAssistantSummaryRows(rec) {
    if (rec && rec.backend) {
        return dmParamAssistantFlattenSectionTiles(dmParamAssistantBackendSummarySections(rec));
    }
    var a = rec.analysis || {};
    return [
        ['Bütçe', dmParamAssistantInputTextTr(rec.budget, 2)],
        ['Dağılım', '%' + dmParamAssistantInputTextTr(rec.basePct, 1) + ' / %' + dmParamAssistantInputTextTr(rec.quotePct, 1)],
        ['Rejim', rec.regime + ' · güven ' + rec.confidence + '/100'],
        ['Formül', 'Step %' + dmParamAssistantInputTextTr(rec.math.stepPct, 2) + ' = ATR bileşik %' + dmParamAssistantInputTextTr(rec.math.volUnit, 2) + ' + rejim/risk katsayısı'],
        ['Skor', 'Risk ' + rec.math.riskScore + '/100 · fırsat ' + rec.math.opportunityScore + '/100 · kapsama ' + dmParamAssistantCoverageText(a) + ' (%' + dmParamAssistantInputTextTr((a.coverage || 0) * 100, 0) + ')'],
        ['Satış grid', dmParamAssistantGridText(rec.upGrids, '+')],
        ['Alış grid', dmParamAssistantGridText(rec.downGrids, '-')],
        ['Trailing', '%' + dmParamAssistantInputTextTr(rec.upTrail, 2) + ' / %' + dmParamAssistantInputTextTr(rec.downTrail, 2)],
        ['Kar alım', 'tetik %' + dmParamAssistantInputTextTr(rec.rebuyTrigger, 2) + ' · trail %' + dmParamAssistantInputTextTr(rec.rebuyTrail, 2)],
        ['Kar satış', 'tetik %' + dmParamAssistantInputTextTr(rec.resellTrigger, 2) + ' · trail %' + dmParamAssistantInputTextTr(rec.resellTrail, 2)]
    ];
}

function dmParamAssistantRenderSummary(rec) {
    var el = document.getElementById('dmParamAssistantSummary');
    if (!el) return;
    if (rec && rec.backend) {
        el.innerHTML = dmParamAssistantRenderParamsSectionHtml(rec);
        el.style.display = 'block';
        var details = document.getElementById('dmParamAssistantDetails');
        if (details) {
            details.innerHTML = dmParamAssistantRenderDetailsSectionsHtml(
                dmParamAssistantBackendSummarySections(rec), rec, rec.backend
            );
            details.style.display = details.innerHTML.trim() ? 'block' : 'none';
        }
        return;
    }
    var rows = dmParamAssistantSummaryRows(rec);
    el.innerHTML = '<div class="dm-pa-summary-wrap"><div class="dm-pa-tile-grid">' + rows.map(function (row) {
        return dmParamAssistantRenderTileHtml(dmParamAssistantMakeTile(row[0], row[1], ''));
    }).join('') + '</div></div>';
    el.style.display = 'block';
}

function dmParamAssistantRenderSummaryAi(rec) {
    var el = document.getElementById('dmParamAssistantSummary');
    if (!el) return;
    if (rec && rec.backend) {
        dmParamAssistantShowParamsFirst(rec);
        return;
    }
    el.innerHTML = '';
    el.style.display = 'block';
    var rows = dmParamAssistantSummaryRows(rec);
    function renderRow(idx) {
        if (idx >= rows.length) return;
        var row = rows[idx];
        var div = document.createElement('div');
        div.className = 'dm-param-assistant-summary-row dm-param-assistant-summary-row-ai';
        div.style.setProperty('--dm-summary-delay', '0ms');
        var label = document.createElement('span');
        label.textContent = row[0];
        var value = document.createElement('strong');
        div.appendChild(label);
        div.appendChild(value);
        el.appendChild(div);
        dmParamAssistantMaybeScrollToBottom();
        var text = String(row[1] || '');
        var charIdx = 0;
        function typeValue() {
            var chunk = dmParamAssistantTextChunkSize();
            value.textContent += text.slice(charIdx, charIdx + chunk);
            charIdx += chunk;
            dmParamAssistantMaybeScrollToBottom();
            if (charIdx < text.length) {
                dmParamAssistantSetTimer(typeValue, Math.max(10, DM_PARAM_ASSISTANT_TEXT_MS - 4));
                return;
            }
            dmParamAssistantSetTimer(function () { renderRow(idx + 1); }, 85);
        }
        typeValue();
    }
    renderRow(0);
}

function dmParamAssistantBindBodyScroll(body) {
    if (!body || body.__dmParamAssistantScrollBound) return;
    body.__dmParamAssistantScrollBound = true;
    function markManualScroll() {
        dmParamAssistantAutoScroll = false;
    }
    body.addEventListener('wheel', markManualScroll, { passive: true });
    body.addEventListener('touchstart', markManualScroll, { passive: true });
    body.addEventListener('scroll', function () {
        if (Date.now() - dmParamAssistantLastAutoScrollAt < 140) return;
        var distanceToBottom = body.scrollHeight - body.scrollTop - body.clientHeight;
        dmParamAssistantAutoScroll = distanceToBottom < 36;
    }, { passive: true });
}

function dmParamAssistantMaybeScrollToBottom(opts) {
    opts = opts || {};
    var body = document.querySelector('#dmParamAssistantModal .dm-param-assistant-body');
    if (!body || (!dmParamAssistantAutoScroll && !opts.force)) return;
    var now = Date.now();
    if (!opts.force && now - dmParamAssistantLastAutoScrollAt < 160) return;
    dmParamAssistantLastAutoScrollAt = now;
    if (opts.followTyping) {
        var anchor = opts.anchorEl || null;
        if (!anchor) {
            var cursor = document.getElementById('dmParamAssistantCursor');
            anchor = (cursor && cursor.offsetParent) ? cursor : outputAnchorFromTyping();
        }
        if (anchor && anchor.getBoundingClientRect) {
            var anchorTop = anchor.getBoundingClientRect().top - body.getBoundingClientRect().top + body.scrollTop;
            var target = Math.max(0, anchorTop - body.clientHeight * 0.28);
            if (target > body.scrollTop) body.scrollTop = target;
        }
        return;
    }
    body.scrollTop = body.scrollHeight;
}

function outputAnchorFromTyping() {
    var output = document.getElementById('dmParamAssistantOutput');
    if (!output) return null;
    var lines = output.querySelectorAll('.dm-param-assistant-line');
    return lines.length ? lines[lines.length - 1] : output;
}

function dmParamAssistantScrollSummaryIntoView() {
    var body = document.querySelector('#dmParamAssistantModal .dm-param-assistant-body');
    var summary = document.getElementById('dmParamAssistantSummary');
    if (!body || !summary || summary.style.display === 'none') return;
    dmParamAssistantAutoScroll = false;
    dmParamAssistantLastAutoScrollAt = Date.now();
    try {
        summary.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (e) {
        body.scrollTop = Math.max(0, summary.offsetTop - 12);
    }
}

function dmParamAssistantTypeIntroText(text, done, opts) {
    opts = opts || {};
    var status = document.getElementById('dmParamAssistantStatus');
    if (!status) {
        if (typeof done === 'function') done();
        return;
    }
    dmParamAssistantSetCursorVisible(true);
    status.textContent = '';
    var idx = 0;
    var ms = opts.fast ? 5 : DM_PARAM_ASSISTANT_TEXT_MS;
    var chunkMult = opts.fast ? 5 : 1;
    function step() {
        if (!dmParamAssistantTyping) return;
        var chunk = dmParamAssistantTextChunkSize() * chunkMult;
        status.textContent += String(text || '').slice(idx, idx + chunk);
        idx += chunk;
        dmParamAssistantMaybeScrollToBottom({ followTyping: true, anchorEl: status });
        if (idx < String(text || '').length) {
            dmParamAssistantSetTimer(step, ms);
            return;
        }
        dmParamAssistantSetTimer(function () {
            if (typeof done === 'function') done();
        }, opts.fast ? 80 : 180);
    }
    step();
}

function dmParamAssistantAnimateIntroAndChips(snapshot, rec, done) {
    dmParamAssistantTypeIntroText(rec.introText || '', function () {
        dmParamAssistantRenderChips(snapshot, rec, { animated: true });
        dmParamAssistantSetTimer(function () {
            if (typeof done === 'function') done();
        }, Math.min(1200, dmParamAssistantChipItems(snapshot, rec).length * 70 + 320));
    });
}

function dmParamAssistantTypeLines(lines, idx, onDone) {
    var output = document.getElementById('dmParamAssistantOutput');
    var choice = document.getElementById('dmParamAssistantChoice');
    if (!output) return;
    dmParamAssistantSetCursorVisible(true);
    if (idx >= lines.length) {
        if (typeof onDone === 'function') {
            onDone();
            return;
        }
        dmParamAssistantTyping = false;
        dmParamAssistantSetCursorVisible(false);
        if (choice) choice.style.display = 'flex';
        if (dmParamAssistantRecommendation) {
            if (dmParamAssistantRecommendation.backend) {
                dmParamAssistantRenderDetailsAi(dmParamAssistantRecommendation);
            } else {
                dmParamAssistantRenderSummaryAi(dmParamAssistantRecommendation);
            }
            dmParamAssistantSetTimer(dmParamAssistantScrollSummaryIntoView, 90);
        }
        return;
    }
    var line = document.createElement('div');
    line.className = 'dm-param-assistant-line';
    output.appendChild(line);
    var text = lines[idx] || '';
    var charIdx = 0;
    function step() {
        if (!dmParamAssistantTyping) return;
        var chunk = dmParamAssistantTextChunkSize();
        line.textContent += text.slice(charIdx, charIdx + chunk);
        charIdx += chunk;
        dmParamAssistantMaybeScrollToBottom({ followTyping: true, anchorEl: line });
        if (charIdx < text.length) {
            dmParamAssistantSetTimer(step, text.charAt(charIdx - 1) === '.' ? DM_PARAM_ASSISTANT_TEXT_MS * 2 : DM_PARAM_ASSISTANT_TEXT_MS);
        } else {
            dmParamAssistantSetTimer(function () { dmParamAssistantTypeLines(lines, idx + 1); }, 220);
        }
    }
    step();
}

// ===================== Backend backtest optimizer (gerçek analiz) =====================
// Parametre asistanı, tek profesyonel modda (professional_auto) SUNUCUDAKİ gerçek
// strateji backtest'i + Monte Carlo gelecek simülasyonunu çalıştırır (job -> poll).
// Backend ulaşılamaz/başarısızsa AÇIKÇA etiketlenmiş yerel hızlı tahmine düşer.
function dmParamAssistantApiCfg() {
    return (AI_ASSISTANT_SPEC && AI_ASSISTANT_SPEC.api) ||
        { tiers: '/api/param-assistant/tiers', optimize: '/api/param-assistant/optimize' };
}

function dmParamAssistantApiPost(path, body, options) {
    options = options || {};
    if (window.apiClient && typeof window.apiClient.post === 'function') return window.apiClient.post(path, body, options);
    return dmParamAssistantApiFetch(path, {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {})
    }, options.timeout || 0);
}

function dmParamAssistantCancelUrl(jobId) {
    if (jobId) return '/api/param-assistant/optimize/' + encodeURIComponent(jobId) + '/cancel';
    return '/api/param-assistant/cancel-active';
}

function dmParamAssistantCancelActiveJob() {
    var jobId = dmParamAssistantActiveJobId || '';
    var btn = document.getElementById('dmPaCancelBtn');
    var status = document.getElementById('dmParamAssistantStatus');
    var live = document.getElementById('dmPaProgLive');
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'İptal ediliyor';
    }
    dmParamAssistantClearTimers();
    dmParamAssistantStopTimeProgress();
    dmParamAssistantStopDpsProgress();
    dmParamAssistantActiveBackendRun = ++dmParamAssistantBackendRunSeq;
    if (!jobId) {
        if (status) status.textContent = 'Hesaplama iptal edildi.';
        if (live) live.textContent = 'İstek iptal edildi; yeniden başlatabilirsin.';
        dmParamAssistantProgressState = null;
        var prepInstant = dmParamAssistantPrepEl();
        if (prepInstant) {
            prepInstant.style.display = 'block';
            prepInstant.innerHTML =
                '<div class="dm-pa-cancelled-note" role="status" aria-live="polite">' +
                '<div class="dm-pa-cancelled-title">Hesaplama iptal edildi</div>' +
                '<div class="dm-pa-cancelled-copy">Parametre skoru hesaplaması durduruldu. Tekrar denemek için aşağıdan başlatabilirsin.</div>' +
                '</div>';
        }
        dmParamAssistantMaybeScrollToBottom({ force: true });
        dmParamAssistantSetTimer(function () {
            if (dmParamAssistantLastSnapshot && typeof dmParamAssistantLastTierStartFn === 'function') {
                dmParamAssistantShowTierSelect(dmParamAssistantLastSnapshot, dmParamAssistantLastTierStartFn);
            }
        }, 900);
        return;
    }
    if (status) status.textContent = 'Analiz sonlandırılıyor…';
    if (live) live.textContent = 'Arka plandaki analiz işi sonlandırılıyor; kayıt temizlenince yeniden seçim yapabilirsin.';
    dmParamAssistantApiPost(dmParamAssistantCancelUrl(jobId), {}, {
        timeout: 20000,
        owner: 'paramAssistant',
        trigger: 'param-assistant-cancel',
        suppressRateLimitToast: true
    }).then(function () {
        dmParamAssistantActiveJobId = '';
        dmParamAssistantProgressState = null;
        if (status) status.textContent = 'Analiz sonlandırıldı.';
        var prep = dmParamAssistantPrepEl();
        if (prep) {
            prep.style.display = 'block';
            prep.innerHTML =
                '<div class="dm-pa-cancelled-note" role="status" aria-live="polite">' +
                '<div class="dm-pa-cancelled-title">Analiz sonlandırıldı</div>' +
                '<div class="dm-pa-cancelled-copy">Arka plandaki parametre işi kapatıldı ve kayıt temizlendi. Şimdi yeniden analiz seviyesi seçebilirsin.</div>' +
                '</div>';
        }
        dmParamAssistantMaybeScrollToBottom({ force: true });
        dmParamAssistantSetTimer(function () {
            if (dmParamAssistantLastSnapshot && typeof dmParamAssistantLastTierStartFn === 'function') {
                dmParamAssistantShowTierSelect(dmParamAssistantLastSnapshot, dmParamAssistantLastTierStartFn);
            }
        }, 1200);
    }).catch(function (err) {
        var info = dmParamAssistantBackendErrorInfo(err);
        if (btn) {
            btn.disabled = false;
            btn.textContent = 'Sonlandır';
        }
        if (status) status.textContent = 'Sonlandırma isteği tamamlanamadı: ' + (info.label || 'sunucu yanıt vermedi');
    });
}

function dmParamAssistantResolveBudget(snapshot) {
    var b = Number(snapshot.currentBudget);
    if (Number.isFinite(b) && b >= 25) return dmParamAssistantRound(b, 2);
    var avail = Number(snapshot.availableQuote);
    if (Number.isFinite(avail) && avail >= 25) return dmParamAssistantRound(Math.min(avail, 100), 2);
    return 50;
}

function dmParamAssistantFmtDuration(sec) {
    var s = Math.max(0, Math.round(Number(sec) || 0));
    if (s < 60) return s + ' sn';
    if (s < 3600) { var m = Math.floor(s / 60); var r = s % 60; return m + ' dk' + (s < 600 && r ? ' ' + r + ' sn' : ''); }
    var h = Math.floor(s / 3600); var mm = Math.round((s % 3600) / 60); return h + ' sa' + (mm ? ' ' + mm + ' dk' : '');
}

function dmParamAssistantPctTxt(v, d) {
    var n = Number(v);
    if (!Number.isFinite(n)) return '—';
    return (n >= 0 ? '+' : '') + dmParamAssistantInputTextTr(n, d == null ? 1 : d) + '%';
}

function dmParamAssistantBackendErrorInfo(err) {
    var status = Number(err && err.status);
    var code = String((err && (err.error_code || err.code)) || '').toUpperCase();
    var msg = String((err && err.message) || '');
    var retryAfter = Number(err && err.retry_after);
    var retryable = !status || code === 'TIMEOUT' || code === 'NETWORK_ERROR' || status === 429 || status === 502 || status === 503 || status === 504 || status >= 500;
    var label = 'sunucu geçici olarak yanıt vermiyor';
    if (status === 401 || status === 403) {
        retryable = false;
        label = 'oturum veya izin doğrulanamadı';
    } else if (status === 404) {
        retryable = false;
        label = 'optimizasyon işi bulunamadı';
    } else if (status === 429) {
        label = 'sunucu yoğun, yeniden denenecek';
    } else if (code === 'TIMEOUT' || msg.toLowerCase().indexOf('timeout') >= 0) {
        label = 'durum isteği zaman aşımına uğradı';
    } else if (code === 'NETWORK_ERROR') {
        label = 'ağ bağlantısı geçici olarak kesildi';
    } else if (status >= 500) {
        label = 'sunucu yoğun veya geçici hata verdi';
    } else if (msg) {
        label = msg;
    }
    return { status: status || 0, code: code, message: msg, retryAfter: retryAfter, retryable: retryable, label: label };
}

// --- dinamik hazırlık paneli (tier seçimi / onay / ilerleme) ---
function dmParamAssistantPrepEl() {
    var el = document.getElementById('dmParamAssistantPrep');
    if (el) return el;
    var anchor = document.querySelector('#dmParamAssistantModal .perf-summary-assistant-wrap');
    var output = document.getElementById('dmParamAssistantOutput');
    if (!anchor || !anchor.parentNode) {
        if (!output || !output.parentNode) return null;
        anchor = output;
    }
    el = document.createElement('div');
    el.id = 'dmParamAssistantPrep';
    el.className = 'dm-param-assistant-prep dm-pa-tier-select';
    el.style.margin = '0 0 12px';
    if (anchor.id === 'dmParamAssistantOutput') {
        anchor.parentNode.insertBefore(el, anchor);
    } else {
        anchor.parentNode.insertBefore(el, anchor.nextSibling);
    }
    return el;
}

function dmParamAssistantScrollIntroTop() {
    var body = document.querySelector('#dmParamAssistantModal .dm-param-assistant-body');
    if (!body) return;
    dmParamAssistantAutoScroll = true;
    dmParamAssistantLastAutoScrollAt = Date.now();
    body.scrollTop = 0;
}

function dmParamAssistantClearPrep() {
    dmParamAssistantStopDpsProgress();
    dmParamAssistantStopLinearProgress();
    dmParamAssistantStopMicroSteps();
    var el = document.getElementById('dmParamAssistantPrep');
    if (el) { el.innerHTML = ''; el.style.display = 'none'; }
}

// Tek profesyonel mod: kullanıcıya süre/derinlik seçtirilmez (eski Düşük/Orta/
// Yüksek kartları kaldırıldı). Tek buton: "Profesyonel Otomatik Analizi Başlat".
function dmParamAssistantShowTierSelect(snapshot, onPick) {
    var prep = dmParamAssistantPrepEl();
    var status = document.getElementById('dmParamAssistantStatus');
    var introLabel = document.getElementById('dmParamAssistantIntroLabel');
    var selectSeq = ++dmParamAssistantTierSelectSeq;
    var modalSpec = (AI_ASSISTANT_SPEC && AI_ASSISTANT_SPEC.modal) || {};
    if (!prep) {
        if (status) status.textContent = 'Analiz ekranı hazırlanamadı; lütfen modalı kapatıp yeniden aç.';
        return;
    }
    var sym = snapshot.symbol || 'Parite';
    if (introLabel) introLabel.textContent = modalSpec.label || 'Parametre Asistanı';
    dmParamAssistantScrollIntroTop();
    dmParamAssistantTyping = false;
    if (status) status.textContent = sym + ' için Parametre Skoru analizini başlatabilirsin.';
    dmParamAssistantSetCursorVisible(false);
    prep.style.display = 'block';
    prep.className = 'dm-param-assistant-prep dm-pa-tier-select dm-pa-tier-ai';
    prep.innerHTML =
        '<div class="dm-pa-tier-kicker">Analizi başlat</div>' +
        '<div class="dm-pa-tier-cards">' +
        '<button type="button" class="dm-pa-tier-card dm-pa-tier-professional_auto">' +
        '<div class="dm-pa-tier-card-label">Parametre Skorunu Hesapla</div>' +
        '<div class="dm-pa-tier-card-desc">Dynamic Param Score Engine: piyasa atmosferi, likidite, spread ve portföy durumuna göre anında parametre skoru ve raf eşleşmesi. Uygun değilse bilinçli bekleme kararı.</div>' +
        '<div class="dm-pa-tier-card-eta">tahmini süre: birkaç saniye</div>' +
        '</button></div>' +
        '<div class="dm-pa-tier-note">Bu karar anında hesaplanır; Dinamik Mod her tur başında aynı motoru kullanır.</div>';
    var card = prep.querySelector('.dm-pa-tier-card');
    if (card) {
        card.addEventListener('click', function () {
            if (selectSeq !== dmParamAssistantTierSelectSeq) return;
            onPick('professional_auto');
        });
    }
}

// ——— Zamana göre ilerleme (blok blok değil; gerçek kalan-zamana dayalı, akıcı) ———
var dmParamAssistantTimeProg = null;       // {targetPct, totalSec, runId, done}
var dmParamAssistantTimeProgTimer = null;
var dmParamAssistantDpsProgressTimer = null;
var dmParamAssistantDpsWaitCreepTimer = null;
var dmParamAssistantDpsProgressStage = 0;
var DM_PARAM_ASSISTANT_DPS_MAX_AUTO_STAGE = 3;

var DM_PARAM_ASSISTANT_DPS_STAGES = [
    {
        title: 'Piyasa verisi toplanıyor',
        explain: 'Son 7 günlük mum verisi okunuyor (5m, 15m, 1h, 4h).',
        score: 'veri alınıyor…',
        live: 'Kline ve emir defteri verisi çekiliyor.',
        ticks: ['5m mumlar okunuyor…', '15m mumlar okunuyor…', '1h mumlar okunuyor…', '4h mumlar okunuyor…', 'Ticker ve spread alınıyor…']
    },
    {
        title: 'İndikatörler hesaplanıyor',
        explain: 'ATR, volatilite, spread, likidite ve BTC risk metrikleri çıkarılıyor.',
        score: 'hesaplanıyor…',
        live: 'Trend, range, fee ve exposure alt skorları üretiliyor.',
        ticks: ['ATR ve volatilite persentili…', 'RSI, ADX ve momentum…', 'Spread ve fee verimi…', 'BTC baskısı ve crash hızı…', 'Likidite ve hacim tutarlılığı…']
    },
    {
        title: 'Piyasa atmosferi sınıflandırılıyor',
        explain: 'Rejim, yapı yönü, volatilite ve risk sınıfı belirleniyor; route_key oluşturuluyor.',
        score: 'ParamScore + rejim…',
        live: 'Piyasa imzası ve parametre skoru hesaplanıyor.',
        ticks: ['Rejim etiketi çıkarılıyor…', 'Wide-chop / BTC baskısı kontrolü…', 'Risk durumu (Normal/Savunmacı)…', 'Route rafı imzası oluşturuluyor…']
    },
    {
        title: 'Parametre rafı eşleştiriliyor',
        explain: '192.780 raflı V5 kütüphanede tam tarama yapılmaz; coinin route_key imzasına göre tek raf doğrudan çağrılır.',
        score: 'raf seçiliyor…',
        live: 'Exact shelf lookup — bütçe ve komisyon sonradan uygulanır; normal yolda fallback yok.',
        ticks: ['Route key doğrulanıyor…', 'V5 raf indeksi sorgulanıyor…', 'DPLV5 shelf eşleştiriliyor…', 'Grid ve dağılım doğrulanıyor…', 'Exposure ve trailing sınırları kontrol ediliyor…']
    },
    {
        title: 'Sonuç hazırlanıyor',
        explain: 'Seçilen V5 rafı forma aktarılıyor; piyasa zayıfsa savunmacı grid parametreleri gösterilir.',
        score: 'hazır',
        live: 'Dynamic Param Score Engine sonucu üretiyor.',
        ticks: ['Güvenlik kapıları uygulanıyor…', 'Emir niyeti planı oluşturuluyor…', 'UI özeti hazırlanıyor…']
    }
];

function dmParamAssistantStopTimeProgress() {
    if (dmParamAssistantTimeProgTimer) { clearTimeout(dmParamAssistantTimeProgTimer); dmParamAssistantTimeProgTimer = null; }
    dmParamAssistantTimeProg = null;
}

function dmParamAssistantStopDpsProgress() {
    if (dmParamAssistantDpsProgressTimer) {
        clearInterval(dmParamAssistantDpsProgressTimer);
        dmParamAssistantDpsProgressTimer = null;
    }
    if (dmParamAssistantDpsWaitCreepTimer) {
        clearInterval(dmParamAssistantDpsWaitCreepTimer);
        dmParamAssistantDpsWaitCreepTimer = null;
    }
    dmParamAssistantStopLinearProgress();
    dmParamAssistantStopMicroSteps();
}

function dmParamAssistantDpsStagePct(idx) {
    var stagePcts = [12, 28, 44, 60, 92];
    var i = Math.max(0, Math.min(stagePcts.length - 1, idx));
    return stagePcts[i];
}

function dmParamAssistantStartDpsWaitCreep() {
    if (dmParamAssistantDpsWaitCreepTimer) return;
    var cap = 88;
    dmParamAssistantDpsWaitCreepTimer = setInterval(function () {
        if (!dmParamAssistantProgressState) return;
        var cur = Number(dmParamAssistantProgressState.pct) || 60;
        if (cur >= cap) return;
        dmParamAssistantRenderTimePct(Math.min(cap, cur + 0.4));
    }, 450);
}

function dmParamAssistantApplyDpsProgressStage(idx, opts) {
    var stages = DM_PARAM_ASSISTANT_DPS_STAGES;
    var allowFinal = !!(opts && opts.allowFinal);
    var maxIdx = allowFinal ? stages.length - 1 : DM_PARAM_ASSISTANT_DPS_MAX_AUTO_STAGE;
    var i = Math.max(0, Math.min(maxIdx, idx));
    dmParamAssistantDpsProgressStage = i;
    var s = stages[i];
    var step = document.getElementById('dmPaProgStep');
    var stage = document.getElementById('dmPaProgStage');
    var explain = document.getElementById('dmPaProgExplain');
    var score = document.getElementById('dmPaProgScore');
    var live = document.getElementById('dmPaProgLive');
    if (step) step.textContent = (i + 1) + ' / ' + stages.length;
    if (stage) stage.textContent = s.title;
    if (explain) explain.textContent = s.explain;
    if (score) score.textContent = s.score;
    var statusEl = document.getElementById('dmParamAssistantStatus');
    if (statusEl) statusEl.textContent = s.title;
    if (live) {
        live.textContent = s.live || s.explain || s.title;
        live.classList.remove('is-typing');
    }
    var pct = (opts && opts.forcePct != null) ? opts.forcePct : dmParamAssistantDpsStagePct(i);
    dmParamAssistantRenderTimePct(pct);
    if (s.ticks && s.ticks.length > 1) {
        dmParamAssistantStartMicroSteps(
            dmParamAssistantActiveBackendRun,
            s.ticks,
            2800
        );
    } else {
        dmParamAssistantStopMicroSteps();
    }
    if (!allowFinal && i >= DM_PARAM_ASSISTANT_DPS_MAX_AUTO_STAGE) {
        dmParamAssistantStartDpsWaitCreep();
    }
}

function dmParamAssistantShowDpsProgress(snapshot) {
    var prep = dmParamAssistantPrepEl();
    if (!prep) return;
    dmParamAssistantStopTimeProgress();
    dmParamAssistantStopDpsProgress();
    var sym = (snapshot && snapshot.symbol) ? snapshot.symbol : 'Parite';
    dmParamAssistantProgressState = {
        pct: 4,
        stageIndex: 0,
        stageKey: 'dps_data',
        runId: dmParamAssistantActiveBackendRun
    };
    dmParamAssistantAutoScroll = true;
    prep.style.display = 'block';
    prep.innerHTML =
        '<div class="dm-param-assistant-progress dm-pa-progress dm-pa-progress-dps dm-pa-progress-active">' +
        '<div class="dm-pa-progress-top">' +
        '<div id="dmPaProgStep" class="dm-pa-progress-step">1 / 5</div>' +
        '<div class="dm-pa-progress-titlebox">' +
        '<div id="dmPaProgStage" class="dm-pa-progress-stage">Piyasa verisi toplanıyor</div>' +
        '<div id="dmPaProgExplain" class="dm-pa-progress-explain">Son 7 günlük mum verisi okunuyor (5m, 15m, 1h, 4h).</div>' +
        '</div>' +
        '<div id="dmPaProgEta" class="dm-pa-progress-eta"><span id="dmPaProgPct">%4</span></div>' +
        '<button type="button" id="dmPaCancelBtn" class="dm-pa-cancel-btn">İptal</button>' +
        '</div>' +
        '<div class="dm-pa-progress-track"><div id="dmPaProgBar" class="dm-pa-progress-bar" style="width:4%;"></div></div>' +
        '<div class="dm-pa-progress-meta">' +
        '<div><span>Parite</span><strong id="dmPaProgData">' + dmParamAssistantEscape(sym) + '</strong></div>' +
        '<div><span>Durum</span><strong id="dmPaProgScore">başlıyor…</strong></div>' +
        '</div>' +
        '<div id="dmPaProgDetail" class="dm-pa-progress-detail" style="display:none;"></div>' +
        '<div id="dmPaProgLive" class="dm-pa-progress-live">Anında analiz — iş kuyruğu veya simülasyon bekleme yok.</div>' +
        '</div>';
    var cancelBtn = document.getElementById('dmPaCancelBtn');
    if (cancelBtn) cancelBtn.onclick = dmParamAssistantCancelActiveJob;
    dmParamAssistantApplyDpsProgressStage(0);
    dmParamAssistantStartLinearProgress(dmParamAssistantActiveBackendRun, { startPct: 4, endPct: 88, durationMs: 16000, tickMs: 80 });
    dmParamAssistantMaybeScrollToBottom({ force: true });
}

function dmParamAssistantStartDpsProgressAnimation() {
    dmParamAssistantStopDpsProgress();
    dmParamAssistantDpsProgressTimer = setInterval(function () {
        if (!dmParamAssistantProgressState) return;
        if (dmParamAssistantDpsProgressStage >= DM_PARAM_ASSISTANT_DPS_MAX_AUTO_STAGE) {
            if (dmParamAssistantDpsProgressTimer) {
                clearInterval(dmParamAssistantDpsProgressTimer);
                dmParamAssistantDpsProgressTimer = null;
            }
            dmParamAssistantStartDpsWaitCreep();
            return;
        }
        dmParamAssistantApplyDpsProgressStage(dmParamAssistantDpsProgressStage + 1);
    }, 1050);
}

function dmParamAssistantServerWallElapsed(job) {
    var created = Number(job && job.created_at);
    if (!Number.isFinite(created) || created <= 0) return 0;
    return Math.max(0, (Date.now() / 1000) - created);
}

function dmParamAssistantVisibleTimePct(job) {
    if (job && job.status === 'done') return 100;
    var total = Number(job && (job.eta_total_sec || job.time_budget_sec));
    var remain = Number(job && job.eta_remaining_sec);
    var elapsed = Number(job && job.elapsed_sec);
    var wallElapsed = dmParamAssistantServerWallElapsed(job);
    if (!(total > 0) && Number.isFinite(remain) && Number.isFinite(elapsed)) total = elapsed + remain;
    var pct = NaN;
    if (total > 0 && Number.isFinite(remain) && remain >= 0) {
        pct = (1 - Math.min(remain, total) / total) * 100;
    }
    if (total > 0) {
        pct = Math.max(Number.isFinite(pct) ? pct : 0, (Math.max(Number.isFinite(elapsed) ? elapsed : 0, wallElapsed) / total) * 100);
    }
    if (!Number.isFinite(pct)) pct = Number(job && job.percent) || 1;
    return Math.max(1, Math.min(99, pct));
}

function dmParamAssistantRenderTimePct(pct) {
    var n = Math.max(1, Math.min(100, Number(pct) || 1));
    var shown = Math.round(n);
    var bar = document.getElementById('dmPaProgBar');
    var pctEl = document.getElementById('dmPaProgPct');
    if (bar) bar.style.width = shown + '%';
    if (pctEl) pctEl.textContent = '%' + shown;
    if (dmParamAssistantProgressState) dmParamAssistantProgressState.pct = n;
}

function dmParamAssistantSyncTimeProgress(job, runId) {
    var total = Number(job && (job.eta_total_sec || job.time_budget_sec)) || 0;
    if (!(total > 0)) total = 30;
    dmParamAssistantTimeProg = {
        targetPct: dmParamAssistantVisibleTimePct(job), totalSec: total,
        runId: runId, done: job.status === 'done'
    };
    if (!dmParamAssistantTimeProgTimer) dmParamAssistantTimeProgressTick();
}

function dmParamAssistantTimeProgressTick() {
    dmParamAssistantTimeProgTimer = null;
    var tp = dmParamAssistantTimeProg;
    if (!tp || tp.runId !== dmParamAssistantActiveBackendRun) return;
    var cur = Number(dmParamAssistantProgressState && dmParamAssistantProgressState.pct);
    if (!Number.isFinite(cur)) {
        var bar = document.getElementById('dmPaProgBar');
        cur = bar ? (parseFloat(bar.style.width) || 1) : 1;
    }
    var target = Math.max(1, Math.min(tp.done ? 100 : 99, Number(tp.targetPct) || 1));
    var diff = target - cur;
    if (diff < 0 && Math.abs(diff) < 3) target = cur;
    if (target < cur - 8) {
        cur = target; // eski stage yüzdesi (%86/%90) DOM'a düştüyse tek hamlede düzelt.
    } else if (Math.abs(target - cur) > 0.15) {
        var step = Math.max(0.18, Math.min(2.2, Math.abs(target - cur) * 0.25));
        cur += target > cur ? step : -step;
    } else {
        cur = target;
    }
    dmParamAssistantRenderTimePct(cur);
    dmParamAssistantTimeProgTimer = setTimeout(dmParamAssistantTimeProgressTick, 350);
}

function dmParamAssistantShowProgress() {
    var prep = dmParamAssistantPrepEl();
    if (!prep) return;
    dmParamAssistantStopTimeProgress();
    dmParamAssistantProgressState = { pct: 1, stageIndex: 0, stageKey: 'queued', runId: dmParamAssistantActiveBackendRun };
    dmParamAssistantAutoScroll = true;
    prep.style.display = 'block';
    prep.innerHTML =
        '<div class="dm-param-assistant-progress dm-pa-progress">' +
        '<div class="dm-pa-progress-top">' +
        '<div id="dmPaProgStep" class="dm-pa-progress-step">1 / 8</div>' +
        '<div class="dm-pa-progress-titlebox">' +
        '<div id="dmPaProgStage" class="dm-pa-progress-stage">Analiz hazırlanıyor</div>' +
        '<div id="dmPaProgExplain" class="dm-pa-progress-explain">Sunucu işi oluşturuluyor; sonuç ancak backtest ve doğrulama bitince gösterilecek.</div>' +
        '</div>' +
        '<div id="dmPaProgEta" class="dm-pa-progress-eta"><span id="dmPaProgPct">%1</span><span id="dmPaProgSep" class="dm-pa-progress-sep" style="display:none;">·</span><span id="dmPaProgEtaTime"></span></div>' +
        '<button type="button" id="dmPaCancelBtn" class="dm-pa-cancel-btn">Sonlandır</button>' +
        '</div>' +
        '<div class="dm-pa-progress-track"><div id="dmPaProgBar" class="dm-pa-progress-bar" style="width:1%;"></div></div>' +
        '<div class="dm-pa-progress-meta">' +
        '<div><span id="dmPaProgDataLabel">Veri</span><strong id="dmPaProgData">cache kontrolü</strong></div>' +
        '<div><span>Skor</span><strong id="dmPaProgScore">henüz yok</strong></div>' +
        '</div>' +
        '<div id="dmPaProgDetail" class="dm-pa-progress-detail"></div>' +
        '<div id="dmPaProgLive" class="dm-pa-progress-live">Kuyruk hazırlanıyor; kaynak ayrılınca geçmiş veri kontrolüne geçilecek.</div>' +
        '</div>';
    var cancelBtn = document.getElementById('dmPaCancelBtn');
    if (cancelBtn) cancelBtn.onclick = dmParamAssistantCancelActiveJob;
    dmParamAssistantMaybeScrollToBottom({ force: true });
}

function dmParamAssistantProgressMeta(job) {
    var key = String((job && job.stage) || '').toLowerCase();
    var pct = Number(job && job.percent);
    if (!Number.isFinite(pct)) pct = 1;
    var stages = [
        { keys: ['queued'], title: 'Analiz hazırlanıyor', explain: 'Sunucu işi oluşturuluyor ve kaynaklar ayrılıyor.' },
        { keys: ['fetch'], title: 'Geçmiş veri tamamlanıyor', explain: 'Coin mumları kalıcı cache ile karşılaştırılıyor; yalnız eksik yeni/eski aralıklar ekleniyor.' },
        { keys: ['features'], title: 'İndikatörler hesaplanıyor', explain: 'ATR, RSI, ADX, trend, volatilite ve bant metrikleri çıkarılıyor.' },
        { keys: ['split', 'measure'], title: 'Test pencereleri kuruluyor', explain: 'Geçmiş veri eğitim ve görülmemiş doğrulama dönemlerine ayrılıyor.' },
        { keys: ['optimize', 'coarse'], title: 'Parametre uzayı taranıyor', explain: 'Grid, trailing, dağılım ve kâr döngüsü adayları gerçek strateji motorunda deneniyor.' },
        { keys: ['refine', 'converged'], title: 'En iyi adaylar inceltiliyor', explain: 'Öne çıkan adaylar daha dar aralıkta tekrar hesaplanıyor; zayıf kombinasyonlar eleniyor.' },
        { keys: ['validate'], title: 'Görülmemiş veride doğrulanıyor', explain: 'Adaylar son dönem OOS veride tekrar backtest ediliyor; kısa yol sonucu gösterilmiyor.' },
        { keys: ['forecast'], title: 'Gelecek senaryoları sınanıyor', explain: 'Monte Carlo yolları ile ilk aylar için dayanıklılık ve düşüş riski ölçülüyor.' },
        { keys: ['done'], title: 'Sonuç hazırlanıyor', explain: 'Tamamlanan analiz forma uygulanabilir parametre setine dönüştürülüyor.' }
    ];
    var idx = stages.findIndex(function (s) { return s.keys.indexOf(key) >= 0; });
    if (idx < 0) {
        if (pct >= 90) idx = 7;
        else if (pct >= 86) idx = 6;
        else if (pct >= 55) idx = 5;
        else if (pct >= 22) idx = 4;
        else if (pct >= 18) idx = 3;
        else if (pct >= 14) idx = 2;
        else if (pct >= 4) idx = 1;
        else idx = 0;
    }
    return { index: idx, total: 8, title: stages[Math.min(idx, 7)].title, explain: stages[Math.min(idx, 7)].explain, key: key };
}

function dmParamAssistantJobProgressEvent(job) {
    var meta = job && job.meta;
    var ev = meta && meta.last_progress;
    return ev && typeof ev === 'object' ? ev : {};
}

function dmParamAssistantFmtCount(value) {
    var n = Number(value);
    if (!Number.isFinite(n)) return '';
    try { return Math.round(n).toLocaleString('tr-TR'); }
    catch (e) { return String(Math.round(n)); }
}

function dmParamAssistantProgressDataText(job, ev) {
    var meta = (job && job.meta) || {};
    var stage = String((ev && ev.stage) || (job && job.stage) || '').toLowerCase();
    var msg = String((ev && ev.message) || (job && job.message) || '').trim();
    var candidates = dmParamAssistantFmtCount(ev && ev.candidates);
    var candidatesDone = dmParamAssistantFmtCount(ev && ev.candidates_done);
    var mcDone = dmParamAssistantFmtCount(ev && ev.mc_done);
    var mcTotal = dmParamAssistantFmtCount(ev && (ev.mc_total || ev.paths));
    var mcIdx = dmParamAssistantFmtCount(ev && ev.mc_candidate_index);
    var mcCandTotal = dmParamAssistantFmtCount(ev && ev.mc_candidate_total);
    if (stage === 'forecast') {
        if (mcIdx && mcCandTotal && mcDone && mcTotal) return 'Monte Carlo: aday ' + mcIdx + ' / ' + mcCandTotal + ' · yol ' + mcDone + ' / ' + mcTotal;
        if (msg && msg.indexOf('aday') >= 0 && msg.indexOf('yol') >= 0) return msg.charAt(0).toUpperCase() + msg.slice(1);
        if (candidates) return 'Monte Carlo: ' + candidates + ' aday senaryoda sınanıyor';
        return 'Monte Carlo senaryoları çalışıyor';
    }
    if (stage === 'validate') {
        if (candidatesDone && candidates) return 'OOS doğrulama: ' + candidatesDone + ' / ' + candidates + ' aday';
        if (candidates) return 'OOS doğrulama: ' + candidates + ' aday';
        return 'OOS doğrulama çalışıyor';
    }
    if (stage === 'coarse') {
        var evaluated = dmParamAssistantFmtCount(ev && ev.evaluated);
        return evaluated ? 'Arama: ' + evaluated + ' kombinasyon denendi' : 'Parametre araması çalışıyor';
    }
    if (stage === 'refine' || stage === 'converged') {
        var refined = dmParamAssistantFmtCount(ev && ev.evaluated);
        return refined ? 'İnceltme: ' + refined + ' aday tekrar hesaplandı' : 'En iyi adaylar inceltiliyor';
    }
    if (stage === 'features') return 'İndikatörler ve rejim ölçüleri hesaplanıyor';
    if (stage === 'split' || stage === 'measure' || stage === 'optimize') return 'Test pencereleri ve arama bütçesi hazırlanıyor';
    var bars = Number(ev && ev.bars);
    var appended = Number(ev && ev.appended);
    if (Number.isFinite(appended) && appended > 0) {
        return dmParamAssistantFmtCount(appended) + ' yeni mum eklendi' + (Number.isFinite(bars) ? '; toplam ' + dmParamAssistantFmtCount(bars) + ' kayıt hazır' : '');
    }
    if (Number.isFinite(bars) && bars > 0) {
        return 'Kalıcı geçmişte ' + dmParamAssistantFmtCount(bars) + ' mum bulundu; eksik aralıklar tamamlanıyor';
    }
    var daily = Number(meta.daily_bars);
    var backtest = Number(meta.backtest_bars);
    var hourly = Number(meta.hourly_bars);
    if (Number.isFinite(daily) || Number.isFinite(backtest) || Number.isFinite(hourly)) {
        var pieces = [];
        if (Number.isFinite(daily)) pieces.push(dmParamAssistantFmtCount(daily) + ' günlük');
        if (Number.isFinite(backtest)) pieces.push(dmParamAssistantFmtCount(backtest) + ' backtest');
        if (Number.isFinite(hourly)) pieces.push(dmParamAssistantFmtCount(hourly) + ' saatlik');
        return 'Geçmiş hazır: ' + pieces.join(', ') + ' kayıt';
    }
    if (stage === 'fetch') return 'Geçmiş veri önbelleği ve eksik mumlar kontrol ediliyor';
    return 'Veri hazır oldukça burada güncellenecek';
}

function dmParamAssistantStableProgressData(prevText, nextText) {
    nextText = String(nextText || '').trim();
    prevText = String(prevText || '').trim();
    if (!prevText) return nextText;
    var nextIsGeneric = nextText === 'Veri hazır oldukça burada güncellenecek' ||
        nextText === 'Geçmiş veri önbelleği ve eksik mumlar kontrol ediliyor';
    var prevIsReady = prevText.indexOf('Geçmiş hazır:') === 0 ||
        prevText.indexOf('Kalıcı geçmişte') === 0 ||
        prevText.indexOf('yeni mum eklendi') > 0;
    if (nextIsGeneric && prevIsReady) return prevText;
    return nextText || prevText;
}

function dmParamAssistantProgressUnit(stage, ev) {
    stage = String(stage || '').toLowerCase();
    ev = ev || {};
    if (stage === 'forecast') {
        var cTotal = Number(ev.mc_candidate_total || ev.candidates || 0);
        var cIdx = Number(ev.mc_candidate_index || 1);
        var pTotal = Number(ev.mc_total || ev.paths || 0);
        var pDone = Number(ev.mc_done || 0);
        if (Number.isFinite(cTotal) && cTotal > 0 && Number.isFinite(pTotal) && pTotal > 0) {
            return Math.max(0, (Math.max(1, cIdx) - 1) * pTotal + Math.max(0, pDone));
        }
    }
    if (stage === 'validate') {
        var done = Number(ev.candidates_done);
        if (Number.isFinite(done)) return done;
    }
    var evaluated = Number(ev.evaluated);
    if (Number.isFinite(evaluated)) return evaluated;
    return null;
}

function dmParamAssistantProgressScoreText(job, ev) {
    var score = ev && ev.best_score != null ? Number(ev.best_score) : Number(job && job.best_score);
    if (Number.isFinite(score)) return score.toFixed(4);
    var base = ev && ev.base_score != null ? Number(ev.base_score) : NaN;
    if (Number.isFinite(base)) return 'baz ' + base.toFixed(4);
    return 'henüz yok';
}

function dmParamAssistantRoundedEtaSec(sec) {
    var s = Math.max(0, Number(sec) || 0);
    if (s >= 3600) return Math.ceil(s / 300) * 300;
    if (s >= 600) return Math.ceil(s / 60) * 60;
    return Math.ceil(s / 15) * 15;
}

function dmParamAssistantStableEtaText(job, state) {
    if (!job || job.status === 'done' || job.eta_remaining_sec == null) return '';
    var rounded = dmParamAssistantRoundedEtaSec(job.eta_remaining_sec);
    if (state && Number.isFinite(state.etaRoundedSec)) {
        var prev = state.etaRoundedSec;
        if (rounded > prev && rounded - prev < 300) rounded = prev;
    }
    return {
        text: 'kalan ~' + dmParamAssistantFmtDuration(rounded),
        roundedSec: rounded
    };
}

function dmParamAssistantProgressWorkText(job, meta, ev, pct) {
    var stage = String((ev && ev.stage) || (job && job.stage) || meta.key || '').toLowerCase();
    var msg = String((ev && ev.message) || (job && job.detail) || '').trim();
    var dataText = dmParamAssistantProgressDataText(job, ev);
    var evaluated = dmParamAssistantFmtCount(ev && ev.evaluated);
    var best = dmParamAssistantProgressScoreText(job, ev);
    var candidates = dmParamAssistantFmtCount(ev && ev.candidates);
    var candidatesDone = dmParamAssistantFmtCount(ev && ev.candidates_done);
    var mcDone = dmParamAssistantFmtCount(ev && ev.mc_done);
    var mcTotal = dmParamAssistantFmtCount(ev && (ev.mc_total || ev.paths));
    var mcIdx = dmParamAssistantFmtCount(ev && ev.mc_candidate_index);
    var mcCandTotal = dmParamAssistantFmtCount(ev && ev.mc_candidate_total);
    var radius = ev && ev.radius != null ? Number(ev.radius) : NaN;
    var workers = dmParamAssistantFmtCount(ev && ev.workers);
    var perEval = ev && ev.per_eval_sec != null ? Number(ev.per_eval_sec) : NaN;
    if (stage === 'queued') return 'Kaynak ayrılıyor; analiz kuyruğu hazırlanıyor.';
    if (stage === 'fetch') return (msg ? msg + '. ' : '') + dataText + '.';
    if (stage === 'features') return 'ATR, RSI, ADX, trend ve volatilite ölçüleri hesaplanıyor; strateji motoru bu veriyle beslenecek.';
    if (stage === 'split') {
        var train = dmParamAssistantFmtCount(ev && ev.train_bars);
        var oos = dmParamAssistantFmtCount(ev && ev.oos_bars);
        var recent = dmParamAssistantFmtCount(ev && ev.recent_in_bars);
        return 'Walk-forward penceresi kuruldu' + (train ? ': ' + train + ' eğitim' : '') + (oos ? ', ' + oos + ' görülmemiş test' : '') + (recent ? ', ' + recent + ' son dönem kontrol' : '') + '.';
    }
    if (stage === 'measure') {
        return 'Tek strateji koşusunun maliyeti ölçülüyor' + (workers ? '; ' + workers + ' işçi planlandı' : '') + (Number.isFinite(perEval) ? '; koşu başı ~' + perEval.toFixed(3) + ' sn' : '') + '.';
    }
    if (stage === 'optimize') return 'Arama bütçesi, doğrulama ve Monte Carlo payları ayarlanıyor; gerçek strateji motoru başlamak üzere.';
    if (stage === 'coarse') return (evaluated ? evaluated + ' kombinasyon gerçek strateji motorunda koştu' : 'Parametre uzayı gerçek strateji motorunda taranıyor') + '; en iyi skor ' + best + '.';
    if (stage === 'refine' || stage === 'converged') return 'Öne çıkan adaylar daraltılıyor' + (Number.isFinite(radius) ? '; arama yarıçapı ' + radius.toFixed(2) : '') + (evaluated ? '; ' + evaluated + ' ince deneme yapıldı' : '') + '; en iyi skor ' + best + '.';
    if (stage === 'validate') {
        if (msg && msg.indexOf('aday') >= 0) return msg.charAt(0).toUpperCase() + msg.slice(1) + '; kısa yol sonucu gösterilmiyor.';
        return (candidatesDone && candidates ? candidatesDone + ' / ' + candidates + ' aday' : (candidates ? candidates + ' aday' : 'Adaylar')) + ' görülmemiş veride tekrar koşturuluyor; kısa yol sonucu gösterilmiyor.';
    }
    if (stage === 'forecast') {
        if (msg && msg.indexOf('aday') >= 0 && msg.indexOf('yol') >= 0) return msg.charAt(0).toUpperCase() + msg.slice(1) + '; düşüş riski ölçülüyor.';
        return (mcIdx && mcCandTotal ? 'Aday ' + mcIdx + ' / ' + mcCandTotal + ': ' : '') + (mcDone && mcTotal ? mcDone + ' / ' + mcTotal + ' Monte Carlo yolu' : (candidates ? candidates + ' aday' : 'En iyi adaylar') + ' yüzlerce gelecek yolu') + ' sınanıyor; ilk ay dayanıklılığı ve düşüş riski ölçülüyor.';
    }
    if (stage === 'done') return 'Analiz tamamlandı; sonuç forma uygulanabilir parametre setine dönüştürülüyor.';
    return meta.explain + ' İlerleme %' + Math.round(pct) + '.';
}

function dmParamAssistantSetProgressPct(targetPct, runId) {
    var state = dmParamAssistantProgressState || { pct: 1, stageIndex: 0, runId: runId };
    if (state.runId !== runId) return;
    var target = Math.max(state.pct || 1, Math.min(100, Math.round(Number(targetPct) || 1)));
    function tick() {
        if (!dmParamAssistantProgressState || dmParamAssistantProgressState.runId !== runId) return;
        var cur = dmParamAssistantProgressState.pct || 1;
        var next = cur < target ? cur + 1 : target;
        dmParamAssistantProgressState.pct = next;
        var bar = document.getElementById('dmPaProgBar');
        if (bar) bar.style.width = next + '%';
        var pctEl = document.getElementById('dmPaProgPct');
        if (pctEl) pctEl.textContent = '%' + next;
        if (next < target) {
            dmParamAssistantProgressTickTimer = setTimeout(tick, 18);
        } else {
            dmParamAssistantProgressTickTimer = null;
        }
    }
    if (!dmParamAssistantProgressTickTimer) tick();
}

function dmParamAssistantUpdateProgress(job) {
    var runId = dmParamAssistantActiveBackendRun;
    var pct = job.percent != null ? Math.max(0, Math.min(100, job.percent)) : 0;
    var ev = dmParamAssistantJobProgressEvent(job);
    var meta = dmParamAssistantProgressMeta(job);
    var state = dmParamAssistantProgressState || { pct: 1, stageIndex: 0, runId: runId };
    var prevStageIndex = state.stageIndex || 0;
    var incomingStageIndex = meta.index;
    var stageRegressed = incomingStageIndex < prevStageIndex;
    var stageIndex = Math.max(prevStageIndex, incomingStageIndex);
    if (stageIndex !== meta.index) {
        meta = dmParamAssistantProgressMeta({ stage: '', percent: [1, 4, 14, 18, 22, 55, 86, 90][stageIndex] || pct });
        meta.index = stageIndex;
    }
    var displayEv = Object.assign({}, ev || {}, { stage: meta.key });
    var progressUnit = dmParamAssistantProgressUnit(meta.key, displayEv);
    var staleProgress = stageRegressed || (
        meta.key === state.stageKey &&
        progressUnit != null &&
        state.progressUnit != null &&
        progressUnit < state.progressUnit
    );
    var nextDataText = staleProgress ? (state.dataText || dmParamAssistantProgressDataText(job, displayEv)) : dmParamAssistantProgressDataText(job, displayEv);
    var dataText = dmParamAssistantStableProgressData(state.dataText, nextDataText);
    var scoreText = staleProgress ? (state.scoreText || dmParamAssistantProgressScoreText(job, displayEv)) : dmParamAssistantProgressScoreText(job, displayEv);
    if ((scoreText === 'henüz yok' || scoreText === '0.0000') && state.scoreText) scoreText = state.scoreText;
    var eta = staleProgress ? null : dmParamAssistantStableEtaText(job, state);
    dmParamAssistantProgressState = {
        pct: state.pct || 1,
        stageIndex: stageIndex,
        stageKey: meta.key,
        dataText: dataText,
        scoreText: scoreText,
        progressUnit: staleProgress ? state.progressUnit : (progressUnit != null ? progressUnit : state.progressUnit),
        etaRoundedSec: eta ? eta.roundedSec : state.etaRoundedSec,
        etaText: eta ? eta.text : (state.etaText || ''),
        runId: runId
    };
    // İlerleme barı: aşama bloklarına göre DEĞİL, gerçek kalan zamana göre akıcı ilerler.
    dmParamAssistantSyncTimeProgress(job, runId);
    var step = document.getElementById('dmPaProgStep');
    if (step) step.textContent = (Math.min(stageIndex + 1, 8)) + ' / 8';
    var stage = document.getElementById('dmPaProgStage');
    if (stage) stage.textContent = meta.title;
    var explain = document.getElementById('dmPaProgExplain');
    if (explain) explain.textContent = meta.explain;
    var etaTime = document.getElementById('dmPaProgEtaTime');
    var etaText = (dmParamAssistantProgressState && dmParamAssistantProgressState.etaText) || '';
    if (etaTime) etaTime.textContent = etaText;
    var etaSep = document.getElementById('dmPaProgSep');
    if (etaSep) etaSep.style.display = etaText ? '' : 'none';
    var data = document.getElementById('dmPaProgData');
    if (data) data.textContent = dataText;
    var dataLabel = document.getElementById('dmPaProgDataLabel') || (data && data.parentElement ? data.parentElement.querySelector('span') : null);
    if (dataLabel) dataLabel.textContent = (meta.key === 'fetch') ? 'Veri' : 'İşlem';
    var score = document.getElementById('dmPaProgScore');
    if (score) score.textContent = scoreText;
    var detail = document.getElementById('dmPaProgDetail');
    if (detail) {
        detail.textContent = '';
        detail.style.display = 'none';
    }
    var live = document.getElementById('dmPaProgLive');
    if (live && !staleProgress) live.textContent = dmParamAssistantProgressWorkText(job, meta, displayEv, pct);
    var status = document.getElementById('dmParamAssistantStatus');
    if (status) status.textContent = (job.tier_label ? job.tier_label + ' analiz · ' : '') + meta.title;
    dmParamAssistantMaybeScrollToBottom();
}

// Bu süre boyunca ilerleme imzası hiç değişmezse "takılmış olabilir" uyarısı göster.
var DM_PARAM_ASSISTANT_FREEZE_MS = 45000;

function dmParamAssistantSetFreezeNotice(on, secs) {
    var el = document.getElementById('dmPaProgDetail');
    if (!el) return;
    if (on) {
        el.textContent = '⚠ Analiz ' + (secs || 0) + ' sn’dir ilerlemiyor — takılmış olabilir. İzlemeye devam ediliyor; sunucu güvenlik zaman aşımına ulaşırsa neden burada gösterilecek.';
        el.style.display = 'block';
        el.classList.add('dm-pa-freeze');
    } else if (el.classList.contains('dm-pa-freeze')) {
        el.textContent = '';
        el.style.display = 'none';
        el.classList.remove('dm-pa-freeze');
    }
}

// Çalışan/var olan bir analiz işine bağlan ve durumunu poll et (hem ilk başlatma
// hem modalı kapatıp yeniden açınca yeniden-bağlanma bu fonksiyonu kullanır).
function dmParamAssistantAttachAndPoll(jobId, opts) {
    opts = opts || {};
    dmParamAssistantActiveJobId = jobId || '';
    var runId = opts.runId;
    var level = opts.level || 'professional_auto';
    var tb = Number(opts.timeBudgetSec) || 240;
    var onDone = opts.onDone, onFail = opts.onFail;
    var status = document.getElementById('dmParamAssistantStatus');
    var failed = false;
    function isActiveRun() { return runId === dmParamAssistantActiveBackendRun; }
    function setStatus(t) { if (status) status.textContent = t; }
    function fail(msg) {
        if (failed || !isActiveRun()) return;
        failed = true;
        try { console.warn('[paramAssistant] backend analysis stopped:', msg); } catch (e) {}
        dmParamAssistantSetFreezeNotice(false);
        dmParamAssistantClearPrep();
        if (typeof onFail === 'function') dmParamAssistantSetTimer(function () { onFail(msg); }, 350);
    }
    var api = dmParamAssistantApiCfg();
    var pollMs = 1500;  // tek (uzun süren, ağır) profesyonel mod -> daha seyrek poll
    var maxPolls = Math.ceil((tb + 700) / (pollMs / 1000));
    var polls = 0;
    var consecMiss = 0;  // ardışık poll hatası (CPU'yu doldururken geçici olabilir)
    var deadlineAt = Date.now() + (tb + 720) * 1000;
    var lastSig = '';
    var lastChangeAt = Date.now();
    function poll() {
        if (failed || !isActiveRun()) return;
        dmParamAssistantApiGet(api.optimize + '/' + encodeURIComponent(jobId), {
            timeout: DM_PARAM_ASSISTANT_BACKEND_POLL_TIMEOUT_MS,
            owner: 'paramAssistant',
            trigger: 'param-assistant-poll',
            suppressRateLimitToast: true
        }).then(function (job) {
            if (!isActiveRun()) return;
            polls++;
            consecMiss = 0;  // başarılı poll: geçici tıkanma sayacını sıfırla
            if (!job) { fail('durum alınamadı'); return; }
            if (job.status === 'done' && job.result) {
                dmParamAssistantActiveJobId = '';
                dmParamAssistantSetFreezeNotice(false);
                dmParamAssistantClearPrep();
                if (job.result && job.result.stats && job.result.stats.degraded) {
                    fail('analiz tüm doğrulama hesaplarını tamamlayamadı');
                    return;
                }
                var ok = dmParamAssistantRenderBackendResult(dmParamAssistantCurrentSnapshot(), job.result);
                if (ok) { if (typeof onDone === 'function') onDone(); }
                else fail('sonuç uygulanamadı');
                return;
            }
            if (job.status === 'cancelled') { fail('analiz sonlandırıldı'); return; }
            if (job.status === 'error') { fail(job.error || 'backtest tamamlanamadı'); return; }
            if (polls > maxPolls) { fail('optimizasyon zaman aşımına uğradı'); return; }
            dmParamAssistantUpdateProgress(job);
            // Donma tespiti (updateProgress dmPaProgDetail'i temizlediği için SONRA).
            var sig = String(job.updated_at || '') + '|' + String(job.elapsed_sec || '') + '|' + String(job.percent || '') + '|' + String(job.stage || '') + '|' + String(job.message || '');
            if (sig !== lastSig) { lastSig = sig; lastChangeAt = Date.now(); dmParamAssistantSetFreezeNotice(false); }
            else if (Date.now() - lastChangeAt > DM_PARAM_ASSISTANT_FREEZE_MS) { dmParamAssistantSetFreezeNotice(true, Math.round((Date.now() - lastChangeAt) / 1000)); }
            dmParamAssistantSetTimer(poll, pollMs);
        }).catch(function (err) {
            if (!isActiveRun()) return;
            consecMiss++;
            var info = dmParamAssistantBackendErrorInfo(err);
            if (!info.retryable) { fail(info.label); return; }
            if (Date.now() > deadlineAt) { fail('optimizasyon zaman aşımına uğradı'); return; }
            var stageIdx = Math.max(1, Math.min(8, ((dmParamAssistantProgressState && dmParamAssistantProgressState.stageIndex) || 0) + 1));
            var step = document.getElementById('dmPaProgStep');
            if (step) step.textContent = stageIdx + ' / 8';
            var stage = document.getElementById('dmPaProgStage');
            if (stage) stage.textContent = 'Bağlantı yenileniyor';
            var explain = document.getElementById('dmPaProgExplain');
            if (explain) explain.textContent = 'Sunucudaki analiz işi devam ediyor; yalnızca durum bağlantısı tekrar deneniyor.';
            var detail = document.getElementById('dmPaProgDetail');
            if (detail) {
                detail.textContent = info.label + (consecMiss > 1 ? ' · deneme ' + consecMiss : '');
                detail.style.display = 'block';
            }
            var live = document.getElementById('dmPaProgLive');
            if (live) live.textContent = 'Sunucudaki analiz işi devam ediyor; sadece canlı durum bilgisi yeniden isteniyor.';
            setStatus('Derin backtest işi devam ediyor; durum bağlantısı yenileniyor…');
            dmParamAssistantMaybeScrollToBottom();
            var retryMs = pollMs + Math.min(8000, consecMiss * 900);
            if (Number.isFinite(info.retryAfter) && info.retryAfter > 0) retryMs = Math.max(retryMs, Math.min(30000, info.retryAfter * 1000));
            dmParamAssistantSetTimer(poll, retryMs);
        });
    }
    dmParamAssistantSetTimer(poll, opts.firstDelayMs != null ? opts.firstDelayMs : 550);
}

function dmParamAssistantRunBackend(snapshot, level, runId, onDone, onFail) {
    var failed = false;
    var status = document.getElementById('dmParamAssistantStatus');
    function isActiveRun() { return runId === dmParamAssistantActiveBackendRun; }
    function setStatus(t) { if (status) status.textContent = t; }
    function fail(msg) {
        if (failed || !isActiveRun()) return;
        failed = true;
        try { console.warn('[paramAssistant] DPS stopped:', msg); } catch (e) {}
        dmParamAssistantClearPrep();
        if (typeof onFail === 'function') dmParamAssistantSetTimer(function () { onFail(msg); }, 350);
    }
    var api = dmParamAssistantApiCfg();
    var budget = dmParamAssistantResolveBudget(snapshot);
    dmParamAssistantShowDpsProgress(snapshot);
    dmParamAssistantStartDpsProgressAnimation();
    dmParamAssistantSetCursorVisible(true);
    setStatus('Piyasa analizi yapılıyor…');
    var calcUrl = api.calculate || '/api/param-assistant/calculate';
    dmParamAssistantApiPost(calcUrl, { symbol: snapshot.symbol, budget: budget, analysis_level: level, first_start_buy_only: true }, {
        timeout: 90000,
        owner: 'paramAssistant',
        trigger: 'param-assistant-calculate',
        suppressRateLimitToast: true
    }).then(function (result) {
        if (!isActiveRun()) return;
        if (!dmParamAssistantIsOpen()) return;
        dmParamAssistantStopDpsProgress();
        dmParamAssistantStopLinearProgress();
        dmParamAssistantStopMicroSteps();
        dmParamAssistantApplyDpsProgressStage(DM_PARAM_ASSISTANT_DPS_STAGES.length - 1, { allowFinal: true, forcePct: 100 });
        dmParamAssistantStopTimeProgress();
        if (!result || result.ok === false) { fail('hesaplama başarısız'); return; }
        var ok = false;
        try {
            ok = dmParamAssistantRenderBackendResult(snapshot, result);
        } catch (renderErr) {
            try { console.error('[paramAssistant] render failed:', renderErr); } catch (e) {}
            fail('sonuç ekrana yazılamadı');
            return;
        }
        if (ok && typeof onDone === 'function') onDone();
        else if (!ok) {
            var reason = 'sonuç uygulanamadı';
            if (result.result_schema_version && result.result_schema_version !== DM_PARAM_ASSISTANT_RESULT_SCHEMA) {
                reason = 'şema uyumsuzluğu (sunucu ' + result.result_schema_version + ', arayüz ' + DM_PARAM_ASSISTANT_RESULT_SCHEMA + ')';
            }
            fail(reason);
        }
    }).catch(function (err) {
        if (!isActiveRun()) return;
        var info = dmParamAssistantBackendErrorInfo(err);
        fail(info.label || 'hesaplama başarısız');
    });
}

function dmParamAssistantBuildBackendRec(snapshot, result) {
    var ui = result.ui_config || {};
    var up = ui.up || {};
    var down = ui.down || {};
    var profit = ui.profit || {};
    function grids(list) {
        return (list || []).map(function (g) { return { trigger_pct: Number(g.trigger_pct), qty_pct: Number(g.qty_pct) }; });
    }
    var allocDisp = ui.allocation_display || {};
    var strat = allocDisp.strategic_target || {};
    var upGridList = grids(up.grids);
    var downGridList = grids(down.grids);
    var sellOnlyUi = ui.sell_management_only === true || result.sell_management_only === true;
    var allocNorm = resolveCreateFormAllocation(
        strat.base_pct != null ? strat.base_pct : ui.base_alloc_pct,
        strat.quote_pct != null ? strat.quote_pct : ui.quote_alloc_pct,
        {
            hasBuyGrids: downGridList.length > 0,
            hasSellGrids: upGridList.length > 0,
            sellManagementOnly: sellOnlyUi
        }
    );
    return {
        budget: Number(ui.budget_usd != null ? ui.budget_usd : result.budget),
        basePct: allocNorm.basePct,
        quotePct: allocNorm.quotePct,
        upGrids: upGridList,
        downGrids: downGridList,
        upTrail: Number(up.trail_pct),
        downTrail: Number(down.trail_pct),
        rebuyTrigger: Number(profit.rebuy_trigger_pct),
        rebuyTrail: Number(profit.rebuy_trail_pct),
        resellTrigger: Number(profit.resell_trigger_pct),
        resellTrail: Number(profit.resell_trail_pct),
        rebuyEnabled: profit.rebuy_enabled === true,
        resellEnabled: profit.resell_enabled === true,
        regime: result.regime_tag || (result.regime && result.regime.label) || '—',
        confidence: result.confidence != null ? result.confidence : (result.param_score != null ? result.param_score : 0),
        paramScore: result.param_score,
        scoreLabels: (ui.score_labels || (result.selection_telemetry && result.selection_telemetry.score_labels) || {}),
        allocationDisplay: ui.allocation_display || {},
        ladderDisplay: ui.ladder_display || {},
        riskState: result.effective_risk_state || result.risk_state,
        finalAction: result.final_action,
        volatility: '',
        backend: result
    };
}

function dmParamAssistantBackendChipItems(snapshot, rec) {
    var r = rec.backend || {};
    var ui = r.ui_config || {};
    var selTel = (r.selection_telemetry || {});
    var scoreLabels = selTel.score_labels || (r.ui_config && r.ui_config.score_labels) || {};
    var marketConf = scoreLabels.market_confidence || {};
    var paramWork = scoreLabels.param_work_score || {};
    var profileFit = scoreLabels.profile_fit_score || {};
    var profileTxt = dmParamAssistantBackendProfileText(r);
    if (rec.sellManagementOnly || r.final_action === 'SELL_MANAGEMENT_ONLY') {
        profileTxt = profileTxt + ' → ' + dmParamAssistantActionLabel('SELL_MANAGEMENT_ONLY', r);
    }
    return [
        ['Parite', snapshot.symbol || r.symbol || '—'],
        [paramWork.label || 'Parametre çalışma skoru', (paramWork.value != null ? paramWork.value : (r.param_score != null ? r.param_score : rec.paramScore)) + '/100'],
        ['Piyasa durumu', dmParamAssistantMarketStatusPlain(rec)],
        ['Risk', dmParamAssistantRiskTonePlain(rec)],
        ['Karar', dmParamAssistantActionLabel(r.final_action || rec.finalAction, r)],
        [marketConf.label || 'Piyasa güven skoru', ui.confidence_display_pct || r.confidence_display_pct ||
            dmParamAssistantFormatConfidencePct(marketConf.value != null ? marketConf.value : (r.confidence != null ? r.confidence : null))],
        [profileFit.label || (dmParamAssistantIsV6Result(r) ? 'V6 profil uyumu' : 'Seçilen raf uyum skoru'), (profileFit.value != null ? profileFit.value : '—') + (profileFit.value != null ? '/100' : '')],
        ['Grid', dmParamAssistantIsV6Result(r) ? (dmParamAssistantV6GridPlanPlain(rec) || dmParamAssistantGridCountLabel(rec)) : dmParamAssistantGridCountLabel(rec)],
        [dmParamAssistantProfileTileLabel(r), profileTxt]
    ];
}

// Frontend'in beklediği sonuç şema sürümü. Backend PARAM_ASSISTANT_RESULT_SCHEMA ile
// AYNI olmalı; eşleşmezse sonuç 'bayat/uyumsuz' sayılır ve GÖSTERİLMEZ.
// 3.4: selection trace counts, fee_display, debug panel contract.
var DM_PARAM_ASSISTANT_RESULT_SCHEMA =
    (AI_ASSISTANT_SPEC.paramAssistant && AI_ASSISTANT_SPEC.paramAssistant.resultSchemaVersion) || '3.4';

// Backend _normalize_symbol ile aynı kuralla normalize et (BTC -> BTCUSDT).
function dmParamAssistantNormalizeSymbol(s) {
    s = String(s || '').toUpperCase().replace(/[\/\-\s]/g, '');
    if (!s) return '';
    var quotes = ['USDT', 'USDC', 'BUSD', 'FDUSD', 'TUSD', 'BTC', 'ETH', 'TRY'];
    var hasQuote = quotes.some(function (q) { return s.length > q.length && s.slice(-q.length) === q; });
    return hasQuote ? s : (s + 'USDT');
}

// BAYAT SONUÇ ENGELİ: bir job sonucu, yalnız (a) şema sürümü uyuşuyorsa ve
// (b) aynı sembol+bütçe için üretildiyse gösterilir. Aksi halde eski/yanlış config
// sonucudur — stratejiyi ne kadar düzeltsen "iyileşti mi yoksa eskiyi mi görüyorum?"
// karışır. Eşleşmezse false döner; çağıran taze analiz akışına düşer.
function dmParamAssistantResultIsFresh(snapshot, result) {
    if (!result) return false;
    if (result.result_schema_version !== DM_PARAM_ASSISTANT_RESULT_SCHEMA) {
        try { console.warn('[paramAssistant] schema mismatch, result rejected', result.result_schema_version); } catch (e) {}
        return false;
    }
    try {
        var snapSym = dmParamAssistantNormalizeSymbol(snapshot && snapshot.symbol);
        var resSym = dmParamAssistantNormalizeSymbol(result.symbol);
        if (snapSym && resSym && snapSym !== resSym) {
            try { console.warn('[paramAssistant] symbol mismatch, stale result rejected', resSym, '!=', snapSym); } catch (e) {}
            return false;
        }
        var snapBudget = dmParamAssistantResolveBudget(snapshot);
        if (snapBudget != null && result.budget != null &&
            Math.abs(Number(result.budget) - Number(snapBudget)) > 0.01) {
            try { console.warn('[paramAssistant] budget mismatch, stale result rejected', result.budget, '!=', snapBudget); } catch (e) {}
            return false;
        }
    } catch (e) {}
    return true;
}

function dmParamAssistantResolveResultConfig(result) {
    if (!result) return null;
    var ui = result.ui_config;
    if (ui && ((ui.up && ui.up.grids && ui.up.grids.length) || (ui.down && ui.down.grids && ui.down.grids.length))) {
        return ui;
    }
    var rec = result.recommendation_config;
    if (rec && ((rec.up && rec.up.grids && rec.up.grids.length) || (rec.down && rec.down.grids && rec.down.grids.length))) {
        return rec;
    }
    return null;
}

function dmParamAssistantRenderBackendResult(snapshot, result) {
    if (!result) return false;
    if (!dmParamAssistantIsOpen()) return false;
    if (!dmParamAssistantSnapshotMatchesCurrent(snapshot)) return false;
    if (result.stats && result.stats.degraded) return false;
    if (!dmParamAssistantResultIsFresh(snapshot, result)) return false;

    var displayConfig = dmParamAssistantResolveResultConfig(result);
    if (displayConfig) {
        result.ui_config = displayConfig;
    }

    var finalDecision = result.final_action || result.decision || result.final_recommendation;
    var deployable = result.deployable === true;
    var isRecommendedOnly = !deployable && displayConfig && (
        result.result_type === 'recommended_grid' || displayConfig.recommendation_only === true
    );

    if (displayConfig) {
        var rec = dmParamAssistantBuildBackendRec(snapshot, result);
        var hasSell = rec.upGrids.length > 0;
        var hasBuy = rec.downGrids.length > 0;
        if (hasSell || hasBuy) {
            rec.decision = { decision: deployable ? finalDecision : 'recommended_grid' };
            rec.watchOnly = isRecommendedOnly || result.sell_management_only === true ||
                result.final_action === 'SELL_MANAGEMENT_ONLY' || (hasSell && !hasBuy);
            rec.sellManagementOnly = rec.watchOnly && hasSell && !hasBuy;
            rec.recommendationOnly = isRecommendedOnly;
            rec.introText = dmParamAssistantGreetingText(snapshot, rec);
            dmParamAssistantRecommendation = rec;
            dmParamAssistantTyping = true;
            var lines = dmParamAssistantIsV6Result(result)
                ? dmParamAssistantResolveV6StreamLines(result, rec)
                : [];
            if (!lines.length) {
                if (result.explain) lines.push(result.explain);
                var pickLine = dmParamAssistantFormatSelectionPickLine(result);
                lines.push(
                    pickLine +
                    '. Parametre Skoru ' + (result.param_score != null ? result.param_score : '—') +
                    '/100 · ' + dmParamAssistantMarketStatusPlain({ backend: result }) + '.'
                );
            }
            if (isRecommendedOnly) {
                if (displayConfig.reference_display_only || displayConfig.reference_display_reason === 'fee_bad_wait') {
                    lines.push('Fee verimi grid için yetersiz; canlı karar BEKLE. Referans olarak geniş aralıklı grid parametreleri gösteriliyor — bu set uygulanmaz.');
                } else {
                    lines.push('Piyasa koşulları zayıf; savunmacı parametre seti gösteriliyor. Canlı uygulama güvenlik kapılarına bağlı.');
                }
            } else if (rec.sellManagementOnly) {
                lines.push('Yeni alış kapalı; yalnızca satış yönetimi parametreleri önerildi.');
            }
            if (!dmParamAssistantIsV6Result(result)) {
                lines.push('Not: Bu karar Dynamic Param Score Engine tarafından üretildi; Dinamik Mod her tur başında aynı motoru kullanır.');
            }
            dmParamAssistantPresentBackendResultUi(snapshot, rec, lines);
            return true;
        }
    }

    var sellOnly = result.sell_management_only === true || result.final_action === 'SELL_MANAGEMENT_ONLY';
    var isManagement = (
        ['management_decision', 'no_trade'].indexOf(result.result_type || '') >= 0 ||
        (result.can_apply_safe_overlay === true && !displayConfig) ||
        (['WAIT', 'NO_TRADE', 'SAFE_WAIT', 'DATA_STALE_SAFE_WAIT'].indexOf(result.final_action || '') >= 0 && !displayConfig)
    ) && ['recommended_grid', 'single_probe_recommendation', 'first_start_buy_only', 'deployable_grid'].indexOf(result.result_type || '') < 0;

    if (isRecommendedOnly && displayConfig) {
        var recOnly = dmParamAssistantBuildBackendRec(snapshot, result);
        var hasSellRef = recOnly.upGrids.length > 0;
        var hasBuyRef = recOnly.downGrids.length > 0;
        if (hasSellRef || hasBuyRef) {
            recOnly.decision = { decision: 'recommended_grid' };
            recOnly.recommendationOnly = true;
            recOnly.watchOnly = !hasBuyRef && hasSellRef;
            recOnly.sellManagementOnly = recOnly.watchOnly;
            recOnly.introText = dmParamAssistantGreetingText(snapshot, recOnly);
            dmParamAssistantRecommendation = recOnly;
            dmParamAssistantTyping = true;
            var refLines = [];
            if (result.explain) refLines.push(result.explain);
            refLines.push('Piyasa koşulları zayıf; savunmacı parametre seti referans olarak gösteriliyor. Canlı uygulama güvenlik kapılarına bağlı.');
            refLines.push('Not: Bu karar Dynamic Param Score Engine tarafından üretildi; Dinamik Mod her tur başında aynı motoru kullanır.');
            dmParamAssistantPresentBackendResultUi(snapshot, recOnly, refLines);
            return true;
        }
    }

    if (isManagement && !deployable) {
        dmParamAssistantShowDpsManagementDecision(snapshot, result);
        return true;
    }
    if (!deployable || finalDecision === 'abstain' || !displayConfig) {
        if (result.ok === false || result.ui_severity === 'error') {
            dmParamAssistantShowDpsTechnicalError(snapshot, result);
        } else {
            dmParamAssistantShowDpsManagementDecision(snapshot, result);
        }
        return true;
    }
    var rec = dmParamAssistantBuildBackendRec(snapshot, result);
    var hasSell = rec.upGrids.length > 0;
    var hasBuy = rec.downGrids.length > 0;
    if (!hasSell && !hasBuy) {
        dmParamAssistantShowDpsManagementDecision(snapshot, result);
        return true;
    }
    if (!sellOnly && (!hasSell || !hasBuy)) {
        dmParamAssistantShowDpsManagementDecision(snapshot, result);
        return true;
    }
    rec.decision = { decision: finalDecision };
    rec.watchOnly = finalDecision === 'watch_only' || result.sell_management_only === true ||
        result.final_action === 'SELL_MANAGEMENT_ONLY' || (hasSell && !hasBuy);
    rec.sellManagementOnly = rec.watchOnly && hasSell && !hasBuy;
    rec.introText = dmParamAssistantGreetingText(snapshot, rec);
    dmParamAssistantRecommendation = rec;
    dmParamAssistantTyping = true;
    var lines = dmParamAssistantIsV6Result(result)
        ? dmParamAssistantResolveV6StreamLines(result, rec)
        : [];
    if (!lines.length) {
        if (result.explain) lines.push(result.explain);
        if (rec.sellManagementOnly) {
            lines.push('Savunmacı grid profili seçildi; exposure headroom veya min-notional güvenlik kontrolü alış tarafını kapattı. Yalnızca satış yönetimi parametreleri önerildi.');
        }
        lines.push('Not: Bu karar Dynamic Param Score Engine tarafından üretildi; Dinamik Mod her tur başında aynı motoru kullanır.');
    }
    dmParamAssistantPresentBackendResultUi(snapshot, rec, lines);
    return true;
}

function dmParamAssistantShowDpsManagementDecision(snapshot, result) {
    dmParamAssistantRecommendation = null;
    dmParamAssistantTyping = false;
    dmParamAssistantClearPrep();
    var status = document.getElementById('dmParamAssistantStatus');
    var output = document.getElementById('dmParamAssistantOutput');
    var summary = document.getElementById('dmParamAssistantSummary');
    var choice = document.getElementById('dmParamAssistantChoice');
    var chips = document.getElementById('dmParamAssistantChips');
    var details = document.getElementById('dmParamAssistantDetails');
    var fa = (result.final_action || 'WAIT').toUpperCase();
    var mm = result.management_mode || fa;
    var isV6 = !!(result.telemetry && (result.telemetry.v6_display || result.telemetry.pool_version === 'v6')) ||
        (result.selection_telemetry && result.selection_telemetry.pool_version === 'v6') ||
        result.apply_policy_label;
    var cardClass = 'dm-pa-safe-wait';
    var title = 'Parametre önerisi üretilemedi';
    var intro = 'Havuz taraması sonrası gösterilebilir grid parametresi bulunamadı.';
    if (isV6 && result.apply_policy_label) {
        title = result.apply_policy_label;
        intro = result.explain || 'V6 savunmacı profil üretildi; canlı uygulama güvenlik limitlerine bağlı.';
        if (result.apply_policy === 'technical_block') {
            cardClass = 'dm-pa-no-trade';
            intro = result.explain || 'Parametre üretildi ancak emir teknik nedenle uygulanamaz.';
        } else if (result.apply_policy === 'high_risk_controlled') {
            cardClass = 'dm-pa-defensive-ref';
        }
    }
    var rt = String(result.result_type || '');
    if (rt === 'single_probe_recommendation') {
        cardClass = 'dm-pa-single-probe';
        title = 'Tek kademe deneme seviyesi';
        intro = 'Bu koşulda gerçek grid kurulamadı. Sistem yalnızca tek kademe deneme seviyesi hesapladı; otomatik grid deploy kapalı.';
    } else if (rt === 'first_start_buy_only') {
        cardClass = 'dm-pa-first-start-buy';
        title = 'İlk tur — yalnızca alış grid';
        intro = 'Base yok; satış grid şu an kurulamaz. İlk tur alış modu açık olduğu için sadece alış grid kurulabilir. Satış grid base oluşunca aktifleşir.';
    } else if (rt === 'recommended_grid') {
        cardClass = 'dm-pa-recommended';
        title = 'Parametre üretildi — deploy kapalı';
        intro = 'Parametre üretildi ancak mevcut güvenlik koşulları otomatik deploy için yeterli değil.';
    } else if (fa === 'WAIT' || fa === 'SAFE_WAIT') {
        title = 'Bekle modu';
        intro = 'Mevcut koşullarda uygulanabilir grid parametresi oluşmadı; sistem bilinçli bekleme kararı verdi.';
    } else if (fa === 'NO_TRADE') {
        cardClass = 'dm-pa-no-trade';
        title = 'İşlem açma engellendi';
        intro = 'Spread, likidite veya güvenlik nedeniyle işlem açılmadı.';
        if ((result.regime_tag || '').toUpperCase() === 'SPREAD_UNSAFE') {
            intro = 'Spread güvenli değil; işlem açma engellendi.';
        }
    } else if (fa === 'SELL_MANAGEMENT_ONLY') {
        cardClass = 'dm-pa-sell-management';
        title = 'Sadece satış yönetimi seçildi';
        intro = 'Yeni alış kapalı. Elde satılabilir base varsa satış yönetimi uygulanır.';
    } else if (fa === 'ACTIVE_DEFENSIVE_GRID' || fa === 'DEFENSIVE_GRID' || fa === 'LOW_FEE_WIDE_GRID') {
        cardClass = 'dm-pa-defensive-ref';
        title = 'Savunmacı grid — referans parametre';
        intro = 'Fee verimi veya güvenlik nedeniyle otomatik deploy kapalı. Geniş aralıklı savunmacı grid referans olarak gösterilir; canlı emir açılmaz.';
        if (result.apply_policy === 'reference_grid') {
            intro = 'Savunmacı grid profili hesaplandı. Otomatik deploy kapalı — aşağıdaki parametreler yalnızca referans içindir.';
        }
    }
    if (result.selection_telemetry && result.selection_telemetry.fallback_used) {
        intro += ' (Fallback güvenli mod — beklenmeyen kombinasyon için yedek karar.)';
    }
    if (status) status.textContent = title;
    if (summary) { summary.innerHTML = ''; summary.style.display = 'none'; }
    if (choice) choice.style.display = 'none';
    if (chips) chips.innerHTML = '';
    if (details) { details.innerHTML = ''; details.style.display = 'none'; }
    if (!output) return;
    var score = result.param_score != null ? result.param_score : '—';
    var regime = result.regime_tag || '—';
    var risk = result.risk_state || '—';
    var blocking = (result.blocking_reasons || []).map(function (b) {
        return '<li>' + dmParamAssistantEscape(b) + '</li>';
    }).join('');
    var sub = (result.rationale && result.rationale.sub_scores) || (result.telemetry && result.telemetry.sub_scores) || {};
    var subRows = Object.keys(sub).map(function (k) {
        return '<div class="dm-pa-error-reason"><span>' + dmParamAssistantEscape(k) + '</span><strong>' + sub[k] + '/100</strong></div>';
    }).join('');
    var sel = result.selection_telemetry || (result.telemetry && result.telemetry.param_pool) || {};
    var ctx = sel.selection_context || {};
    var techRows = '';
    function techRow(label, val) {
        if (val == null || val === '') return '';
        return '<div class="dm-pa-error-reason"><span>' + dmParamAssistantEscape(label) + '</span><strong>' + dmParamAssistantEscape(String(val)) + '</strong></div>';
    }
    techRows += techRow('decision_id', result.decision_id);
    techRows += techRow('pool_version', sel.pool_version);
    techRows += techRow('template', sel.selected_template_key);
    techRows += techRow('management_mode', mm);
    techRows += techRow('apply_policy', result.apply_policy);
    techRows += techRow('fallback_used', sel.fallback_used);
    techRows += techRow('fallback_reason', sel.fallback_reason);
    techRows += techRow('active_template_count', sel.active_template_count);
    techRows += techRow('templates_scanned', sel.templates_scanned);
    techRows += techRow('candidates_after_filters', sel.candidate_count_after_filters);
    techRows += techRow('profile_subfamily', sel.profile_subfamily);
    techRows += techRow('unique_rejected_templates', sel.unique_rejected_templates);
    techRows += techRow('reject_events_total', sel.reject_events_total);
    techRows += techRow('budget_tier', ctx.budget_tier);
    techRows += techRow('fee_tier', ctx.fee_tier);
    techRows += techRow('liquidity_tier', ctx.liquidity_tier);
    techRows += techRow('has_sellable_base', ctx.has_sellable_base);
    var dw = sel.data_window || {};
    if (dw['5m']) {
        techRows += techRow('5m candles', (dw['5m'].actual || 0) + ' / ' + (dw['5m'].expected || 0));
    }
    if (dw.window_days) techRows += techRow('data_window', dw.window_days + 'd');
    if (sel.intent_execution_enabled === false) {
        techRows += techRow('rebalance/intent', 'telemetry only — henüz emir kaynağı değil');
    }
    output.innerHTML =
        '<div class="dm-param-assistant-error ' + cardClass + '" role="status">' +
        '<div class="dm-pa-error-title-wrap"><div class="dm-pa-error-title">' + dmParamAssistantEscape(title) + '</div></div>' +
        '<p>' + dmParamAssistantEscape(result.explain || intro) + '</p>' +
        '<div class="dm-pa-error-reason"><span>Parametre Skoru</span><strong>' + score + '/100</strong></div>' +
        '<div class="dm-pa-error-reason"><span>Karar</span><strong>' + dmParamAssistantEscape(fa) + '</strong></div>' +
        '<div class="dm-pa-error-reason"><span>Apply policy</span><strong>' + dmParamAssistantEscape(result.apply_policy || '—') + '</strong></div>' +
        '<div class="dm-pa-error-reason"><span>Alış</span><strong>' + (fa === 'SELL_MANAGEMENT_ONLY' ? 'kapalı' : (fa === 'WAIT' || fa === 'SAFE_WAIT' || fa === 'NO_TRADE' ? 'kapalı' : '—')) + '</strong></div>' +
        '<div class="dm-pa-error-reason"><span>Rejim</span><strong>' + dmParamAssistantEscape(regime) + '</strong></div>' +
        '<div class="dm-pa-error-reason"><span>Risk</span><strong>' + dmParamAssistantEscape(risk) + '</strong></div>' +
        (blocking ? '<ul class="dm-pa-abstain-reasons">' + blocking + '</ul>' : '') +
        (subRows ? '<details class="dm-pa-sub-scores" open><summary>Alt skorlar</summary>' + subRows + '</details>' : '') +
        (techRows ? '<details class="dm-pa-sub-scores dm-pa-debug-panel" open><summary>Gelişmiş teknik detaylar</summary>' + techRows + '</details>' : '') +
        '</div>';
}

/** @deprecated use dmParamAssistantShowDpsManagementDecision */
function dmParamAssistantShowDpsNoTrade(snapshot, result) {
    dmParamAssistantShowDpsManagementDecision(snapshot, result);
}

function dmParamAssistantShowDpsTechnicalError(snapshot, result) {
    dmParamAssistantRecommendation = null;
    dmParamAssistantTyping = false;
    dmParamAssistantClearPrep();
    var status = document.getElementById('dmParamAssistantStatus');
    var output = document.getElementById('dmParamAssistantOutput');
    if (status) status.textContent = 'Teknik hata';
    if (!output) return;
    output.innerHTML =
        '<div class="dm-param-assistant-error dm-pa-error" role="alert">' +
        '<div class="dm-pa-error-title">Analiz tamamlanamadı</div>' +
        '<p>' + dmParamAssistantEscape(result.error || result.message || 'Sunucu veya veri kaynağı hatası.') + '</p>' +
        '</div>';
}

// 'Çekil' kararı: çürütülen seti apply'a sunmaz; kendi OOS kanıtına dayalı dürüst verdict.
function dmParamAssistantShowDecisionAbstain(snapshot, result, decision) {
    dmParamAssistantRecommendation = null;   // APPLY YOK — set canlıya önerilmez
    dmParamAssistantTyping = false;
    dmParamAssistantClearPrep();
    var status = document.getElementById('dmParamAssistantStatus');
    var output = document.getElementById('dmParamAssistantOutput');
    var summary = document.getElementById('dmParamAssistantSummary');
    var choice = document.getElementById('dmParamAssistantChoice');
    var chips = document.getElementById('dmParamAssistantChips');
    var details = document.getElementById('dmParamAssistantDetails');
    var noDeployable = result && result.result_type === 'no_deployable_candidate';
    if (status) status.textContent = noDeployable ? 'Uygulanabilir parametre bulunamadı' : 'Karar: önerilmiyor — çekil';
    if (summary) { summary.innerHTML = ''; summary.style.display = 'none'; }
    if (choice) choice.style.display = 'none';
    if (chips) chips.innerHTML = '';
    if (details) { details.innerHTML = ''; details.style.display = 'none'; }
    if (!output) return;
    var hb = decision.honest_benchmark || {};
    var n1 = function (v) { return dmParamAssistantInputTextTr(v, 1); };
    var headline = dmParamAssistantEscape(decision.headline || 'Bu set önerilmiyor.');
    var reasons = (decision.reasons || []).map(function (r) {
        return '<li>' + dmParamAssistantEscape(r) + '</li>';
    }).join('');
    var flags = (decision.red_flags || []).filter(function (f) { return f && f.severity === 'high'; })
        .map(function (f) { return '<li>' + dmParamAssistantEscape(f.text) + '</li>'; }).join('');
    // MC örneklemi tabanın altındaysa ya da karar abstain ise olasılık yüzde
    // olarak GÖSTERİLMEZ ("%35 dağıtıma değer" gibi yanıltıcı bir sayı basılmaz).
    var probDisplay = (result.final_recommendation && result.final_recommendation.probability_display) ||
        (decision.probability_detail && decision.probability_detail.probability_display) || 'not_applicable';
    var probText = probDisplay === 'percent'
        ? '%' + dmParamAssistantInputTextTr((decision.deploy_probability || 0) * 100, 0)
        : (probDisplay === 'insufficient_sample' ? 'MC örneklemi yetersiz' : 'Canlıya uygunluk: kapalı');
    var bench = noDeployable ? '' : (
        '<div class="dm-pa-error-reason"><span>Bot (OOS)</span><strong>%' + n1(hb.bot_return_pct) + '</strong></div>' +
        '<div class="dm-pa-error-reason"><span>Hedef tahsisi PASİF tutma</span><strong>%' + n1(hb.intended_hold_return_pct) + '</strong></div>' +
        '<div class="dm-pa-error-reason"><span>Dürüst alpha (vs pasif)</span><strong>%' + n1(hb.honest_alpha_pct) + '</strong></div>' +
        '<div class="dm-pa-error-reason"><span>Dağıtıma değer olasılığı</span><strong>' + probText + '</strong></div>'
    );
    // no_deployable_candidate: reddedilen en iyi adayı TEŞHİS amaçlı göster —
    // "öneri" değil, hangi aday neden elendiğini açıklayan bir not.
    var rejected = result && result.rejected_best_candidate;
    var rejectedNote = (noDeployable && rejected)
        ? '<div class="dm-pa-error-note"><strong>Reddedilen en iyi aday:</strong> ' +
          dmParamAssistantEscape(rejected.structure || '—') +
          ' (sebep: ' + dmParamAssistantEscape(rejected.reject_reason || '—') + ')' +
          ' — gridler bilgi amaçlı yukarıda gösterilmiş olabilir, bu bir öneri DEĞİLDİR.</div>'
        : '';
    output.innerHTML =
        '<div class="dm-param-assistant-error dm-pa-abstain" role="status" aria-live="polite">' +
        '<div class="dm-pa-error-head">' +
        '<div class="dm-pa-error-mark" aria-hidden="true">⚖</div>' +
        '<div class="dm-pa-error-title-wrap">' +
        '<div class="dm-pa-error-kicker">Dürüst karar</div>' +
        '<div class="dm-pa-error-title">' + (noDeployable ? 'Uygulanabilir parametre bulunamadı' : 'Önerilmiyor — çekil') + '</div>' +
        '</div></div>' +
        '<div class="dm-pa-error-note">' + headline + '</div>' +
        bench +
        rejectedNote +
        (reasons ? '<div class="dm-pa-error-note"><strong>Neden:</strong><ul>' + reasons + '</ul></div>' : '') +
        (flags ? '<div class="dm-pa-error-note"><strong>Kırmızı bayraklar:</strong><ul>' + flags + '</ul></div>' : '') +
        '<div class="dm-pa-error-note">Bu set canlıya UYGULANMAZ olarak işaretlendi: kendi OOS kanıtına göre hedef portföyü pasif tutmaktan iyi değil. Karar burada kapatıldı; uyarı yığıp kararı sana devretmiyoruz.</div>' +
        '<div class="dm-pa-error-actions">' +
        '<button type="button" id="dmPaAbstainRetry" class="btn btn-ghost btn-sm dm-pa-error-secondary">Yeni analiz</button>' +
        '</div>' +
        '</div>';
    var btn = document.getElementById('dmPaAbstainRetry');
    if (btn) btn.onclick = function () { if (typeof openParamAssistantModal === 'function') openParamAssistantModal(); };
}

function dmParamAssistantShowBackendError(reason, retryFn, tierSelectFn) {
    dmParamAssistantRecommendation = null;
    dmParamAssistantTyping = false;
    dmParamAssistantClearPrep();
    var status = document.getElementById('dmParamAssistantStatus');
    var output = document.getElementById('dmParamAssistantOutput');
    var summary = document.getElementById('dmParamAssistantSummary');
    var choice = document.getElementById('dmParamAssistantChoice');
    var chips = document.getElementById('dmParamAssistantChips');
    var details = document.getElementById('dmParamAssistantDetails');
    if (status) status.textContent = 'Parametre skoru hesaplanamadı';
    if (summary) { summary.innerHTML = ''; summary.style.display = 'none'; }
    if (choice) choice.style.display = 'none';
    if (chips) chips.innerHTML = '';
    if (details) { details.innerHTML = ''; details.style.display = 'none'; }
    if (!output) return;
    var safeReason = dmParamAssistantEscape(reason || 'Analiz tamamlanamadı.');
    output.innerHTML =
        '<div class="dm-param-assistant-error" role="status" aria-live="polite">' +
        '<div class="dm-pa-error-head">' +
        '<div class="dm-pa-error-mark" aria-hidden="true">!</div>' +
        '<div class="dm-pa-error-title-wrap">' +
        '<div class="dm-pa-error-kicker">Analiz durdu</div>' +
        '<div class="dm-pa-error-title">Parametre skoru alınamadı</div>' +
        '</div>' +
        '</div>' +
        '<div class="dm-pa-error-reason"><span>Neden</span><strong>' + safeReason + '</strong></div>' +
        '<div class="dm-pa-error-note">Dynamic Param Score Engine yanıt vermedi veya sonuç forma aktarılamadı. Sunucunun çalıştığından ve oturumun açık olduğundan emin olup tekrar dene.</div>' +
        '<div class="dm-pa-error-actions">' +
        '<button type="button" id="dmPaRetrySame" class="btn btn-primary-gold btn-sm dm-pa-error-primary">Tekrar dene</button>' +
        '<button type="button" id="dmPaRetryTier" class="btn btn-ghost btn-sm dm-pa-error-secondary">Yeniden başlat</button>' +
        '</div>' +
        '</div>';
    var retry = document.getElementById('dmPaRetrySame');
    var tier = document.getElementById('dmPaRetryTier');
    if (retry) retry.onclick = function () { if (typeof retryFn === 'function') retryFn(); };
    if (tier) tier.onclick = function () { if (typeof tierSelectFn === 'function') tierSelectFn(); };
}

function openParamAssistantModal() {
    var modal = document.getElementById('dmParamAssistantModal');
    var backdrop = document.getElementById('dmParamAssistantBackdrop');
    if (!modal) return;
    dmParamAssistantClearTimers();
    modal.classList.remove('is-closing');
    resetParamAssistantSession({
        keepAppliedSource: true,
        clearCache: true
    });
    modal.setAttribute('aria-hidden', 'false');
    if (backdrop) backdrop.setAttribute('aria-hidden', 'true');
    modal.style.display = 'flex';
    if (backdrop) backdrop.style.display = 'none';
    dmParamAssistantShieldParentModals(true);

    var output = document.getElementById('dmParamAssistantOutput');
    var summary = document.getElementById('dmParamAssistantSummary');
    var choice = document.getElementById('dmParamAssistantChoice');
    var status = document.getElementById('dmParamAssistantStatus');
    var chips = document.getElementById('dmParamAssistantChips');
    if (output) output.innerHTML = '';
    if (output) output.classList.add('is-visible');
    if (summary) {
        summary.innerHTML = '';
        summary.style.display = 'none';
    }
    if (choice) choice.style.display = 'none';
    if (chips) chips.innerHTML = '';
    var details = document.getElementById('dmParamAssistantDetails');
    if (details) { details.innerHTML = ''; details.style.display = 'none'; }
    if (status) status.textContent = (AI_ASSISTANT_SPEC.modal && AI_ASSISTANT_SPEC.modal.initialStatus) || 'Parite verileri okunuyor';
    var introLabel = document.getElementById('dmParamAssistantIntroLabel');
    if (introLabel) {
        introLabel.textContent = (AI_ASSISTANT_SPEC.modal && AI_ASSISTANT_SPEC.modal.label) || 'Parametre Asistanı';
    }
    dmParamAssistantSetCursorVisible(true);
    var kicker = document.getElementById('dmParamAssistantKicker');
    if (kicker) kicker.textContent = 'V6 exact shelf engine';
    var titleEl = document.getElementById('dmParamAssistantTitle');
    if (titleEl && AI_ASSISTANT_SPEC.modal && AI_ASSISTANT_SPEC.modal.title) {
        titleEl.textContent = AI_ASSISTANT_SPEC.modal.title;
    }
    dmParamAssistantAutoScroll = true;
    dmParamAssistantLastAutoScrollAt = 0;
    var assistantBody = document.querySelector('#dmParamAssistantModal .dm-param-assistant-body');
    dmParamAssistantBindBodyScroll(assistantBody);
    if (assistantBody) assistantBody.scrollTop = 0;

    var firstSnapshot = dmParamAssistantCurrentSnapshot();
    dmParamAssistantLastSnapshot = firstSnapshot;
    if (!firstSnapshot.symbol) {
        dmParamAssistantRecommendation = null;
        dmParamAssistantTyping = false;
        if (status) status.textContent = 'Önce işlem çiftini ve bakiyeni seçmen gerekiyor';
        return;
    }

    var rendered = false;

    function statusFn(text) {
        if (status && !rendered) status.textContent = text;
    }

    function runBackendLevel(level) {
        dmParamAssistantLastTierStartFn = runBackendLevel;
        dmParamAssistantClearTimers();
        dmParamAssistantTierSelectSeq++;
        var runId = ++dmParamAssistantBackendRunSeq;
        dmParamAssistantActiveBackendRun = runId;
        dmParamAssistantProgressState = { pct: 1, stageIndex: 0, stageKey: 'queued', runId: runId };
        rendered = false;
        dmParamAssistantAutoScroll = true;
        if (output) output.innerHTML = '';
        if (summary) { summary.innerHTML = ''; summary.style.display = 'none'; }
        if (choice) choice.style.display = 'none';
        if (chips) chips.innerHTML = '';
        var detailsEl = document.getElementById('dmParamAssistantDetails');
        if (detailsEl) { detailsEl.innerHTML = ''; detailsEl.style.display = 'none'; }
        statusFn('Piyasa analizi yapılıyor…');
        dmParamAssistantRunBackend(firstSnapshot, level, runId, function () {
            rendered = true;
            dmParamAssistantClearPrep();
        }, function (reason) {
            rendered = false;
            dmParamAssistantShowBackendError(reason, function () {
                runBackendLevel(level);
            }, function () {
                if (output) output.innerHTML = '';
                dmParamAssistantShowTierSelect(firstSnapshot, runBackendLevel);
            });
        });
    }
    dmParamAssistantLastTierStartFn = runBackendLevel;

    dmParamAssistantShowTierSelect(firstSnapshot, runBackendLevel);
}

function closeParamAssistantModal(opts) {
    opts = opts || {};
    var modal = document.getElementById('dmParamAssistantModal');
    var backdrop = document.getElementById('dmParamAssistantBackdrop');
    if (!modal) return;
    dmParamAssistantClearTimers();
    dmParamAssistantStopTimeProgress();
    dmParamAssistantStopDpsProgress();
    if (!opts.skipReset) {
        resetParamAssistantSession({
            keepAppliedSource: !!opts.keepAppliedSource,
            keepApplyTimers: !!opts.keepApplyTimers,
            clearCache: opts.clearCache !== false,
            snapshot: opts.snapshot
        });
    } else {
        dmParamAssistantActiveBackendRun = ++dmParamAssistantBackendRunSeq;
        dmParamAssistantTierSelectSeq++;
        dmParamAssistantProgressState = null;
        dmParamAssistantTyping = false;
        dmParamAssistantSetCursorVisible(false);
    }
    function hide() {
        modal.setAttribute('aria-hidden', 'true');
        if (backdrop) backdrop.setAttribute('aria-hidden', 'true');
        modal.style.display = 'none';
        if (backdrop) backdrop.style.display = 'none';
        modal.classList.remove('is-closing');
        dmParamAssistantShieldParentModals(false);
    }
    if (opts.immediate) {
        hide();
        return;
    }
    modal.classList.add('is-closing');
    dmParamAssistantSetTimer(hide, 180);
}

function dmParamAssistantDispatch(el, type) {
    if (!el) return;
    try { el.dispatchEvent(new Event(type, { bubbles: true })); } catch (e) {}
}

function dmParamAssistantTypeInput(task, done) {
    var el = document.getElementById(task.id);
    if (!el) {
        done();
        return;
    }
    var value = String(task.value);
    var oldReadonly = el.readOnly;
    if (task.allowReadonly) el.readOnly = false;
    var typing = dmParamAssistantBeginInputTyping(el);

    el.value = '';
    dmParamAssistantDispatch(el, 'input');
    var idx = 0;
    function finishField() {
        typing.finish(value);
        dmParamAssistantDispatch(el, 'change');
        if (task.allowReadonly) el.readOnly = oldReadonly;
        if (typeof task.after === 'function') task.after();
        dmParamAssistantSetApplyTimer(done, DM_PARAM_ASSISTANT_FIELD_PAUSE_MS);
    }
    function step() {
        var chunk = dmParamAssistantInputChunkSize();
        el.value += value.slice(idx, idx + chunk);
        idx += chunk;
        dmParamAssistantDispatch(el, 'input');
        if (idx < value.length) {
            dmParamAssistantSetApplyTimer(step, DM_PARAM_ASSISTANT_INPUT_MS);
            return;
        }
        finishField();
    }
    step();
}

function applyParamAssistantRecommendation(rec, onDone) {
    if (!rec) return;
    // P0-4: yalnız BACKEND (param asistanı) önerisi uygulanınca kaynağı işaretle;
    // yerel/heuristik öneri uygulanırsa temizle (bot manuel sayılır).
    if (rec.backend && rec.backend.ok) {
        var _bk = rec.backend;
        var _tel = _bk.telemetry || {};
        var _pool = _tel.param_pool || _bk.selection_telemetry || {};
        dmParamAssistantAppliedSource = {
            source: 'param_assistant',
            job_id: _bk.job_id || null,
            decision_id: _bk.decision_id || null,
            decision: (_bk.decision && _bk.decision.decision) || _bk.decision || null,
            confidence: (_bk.confidence != null ? _bk.confidence : null),
            symbol: _bk.symbol || (rec.backend && rec.backend.symbol) || null,
            template_key: _pool.selected_template_key || _pool.template_key || null,
            param_score: _bk.param_score != null ? _bk.param_score : null,
            regime_tag: _bk.regime_tag || null
        };
    } else {
        dmParamAssistantAppliedSource = null;
    }
    dmParamAssistantClearTimers();
    dmParamAssistantClearApplyTimers({ keepApplyingFlag: true, keepFieldStyles: true });
    dmParamAssistantClearAiInputStyles();
    dmParamAssistantApplying = true;
    var dmModal = document.getElementById('dmModal');
    if (dmModal) {
        try { dmModal.scrollIntoView({ behavior: 'smooth', block: 'start' }); } catch (e) {}
    }
    var submitBtn = document.getElementById('dmSubmitBtn');
    if (submitBtn) submitBtn.classList.remove('dm-ai-create-pulse');
    var allocApply = dmParamAssistantAllocationForApply(rec);
    rec.basePct = allocApply.basePct;
    rec.quotePct = allocApply.quotePct;
    var tasks = [
        { id: 'fBudget', value: dmParamAssistantInputText(rec.budget, 2) },
        { id: 'fBasePct', value: dmParamAssistantInputText(rec.basePct, 1), after: syncQuotePctFromBaseInput },
        { id: 'fQuotePct', value: dmParamAssistantInputText(rec.quotePct, 1), allowReadonly: true },
        { id: 'fUpCount', value: String(rec.upGrids.length), after: function () { buildGridRows('upGridRows', rec.upGrids.length, 'up'); } },
        { id: 'fUpTrail', value: dmParamAssistantInputTextTr(rec.upTrail, 2) }
    ];
    rec.upGrids.forEach(function (g, idx) {
        tasks.push({ id: 'upGrid_' + idx + '_trigger', value: dmParamAssistantInputTextTr(g.trigger_pct, 2) });
        tasks.push({ id: 'upGrid_' + idx + '_qty', value: dmParamAssistantInputTextTr(g.qty_pct, 1), after: function () { _updateGridQtySum('upGridRows', 'up'); } });
    });
    tasks.push({ id: 'fDownCount', value: String(rec.downGrids.length), after: function () {
        buildGridRows('downGridRows', rec.downGrids.length, 'down');
        syncMaxBuyLevelsWithDownCount(Math.max(rec.downGrids.length, 1));
    } });
    tasks.push({ id: 'fDownTrail', value: dmParamAssistantInputTextTr(rec.downTrail, 2) });
    rec.downGrids.forEach(function (g, idx) {
        tasks.push({ id: 'downGrid_' + idx + '_trigger', value: dmParamAssistantInputTextTr(g.trigger_pct, 2) });
        tasks.push({ id: 'downGrid_' + idx + '_qty', value: dmParamAssistantInputTextTr(g.qty_pct, 1), after: function () { _updateGridQtySum('downGridRows', 'down'); } });
    });
    if (!rec.sellManagementOnly && rec.downGrids.length > 0) {
        tasks.push({ id: 'fRebuyTrigger', value: dmParamAssistantInputTextTr(rec.rebuyTrigger, 2) });
        tasks.push({ id: 'fRebuyTrail', value: dmParamAssistantInputTextTr(rec.rebuyTrail, 2) });
    }
    if (rec.upGrids.length > 0) {
        tasks.push({ id: 'fResellTrigger', value: dmParamAssistantInputTextTr(rec.resellTrigger, 2) });
        tasks.push({ id: 'fResellTrail', value: dmParamAssistantInputTextTr(rec.resellTrail, 2) });
    }

    function run(i) {
        if (i >= tasks.length) {
            dmParamAssistantFinalizeFormAllocation(rec.basePct, rec.quotePct);
            if (submitBtn) {
                submitBtn.classList.add('dm-ai-create-pulse');
                submitBtn.setAttribute('data-ai-ready', '1');
                try { submitBtn.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch (e) {}
            }
            dmParamAssistantApplying = false;
            if (typeof onDone === 'function') onDone();
            return;
        }
        dmParamAssistantTypeInput(tasks[i], function () { run(i + 1); });
    }
    run(0);
}

function acceptParamAssistantRecommendation() {
    if (dmParamAssistantApplying) return;
    var rec = dmParamAssistantRecommendation;
    var status = document.getElementById('dmParamAssistantStatus');
    if (status) status.textContent = 'Parametreler forma işleniyor...';
    closeParamAssistantModal({
        immediate: true,
        skipReset: true,
        keepApplyTimers: true
    });
    dmParamAssistantEnsureCreateModalVisibleForApply();
    dmParamAssistantSetApplyTimer(function () {
        applyParamAssistantRecommendation(rec, function () {
            resetParamAssistantSession({
                keepAppliedSource: true,
                clearCache: true
            });
        });
    }, 80);
}

/** Create bot modal: mini grafik yükle (dmPairChart) */
async function loadCreateBotModalChart(symbol) {
    const container = document.getElementById('dmPairChart');
    if (!container) return;
    const norm = normalizeModalSymbol(symbol || '');
    if (norm.invalid || !norm.normalized) {
        container.innerHTML = '';
        return;
    }
    const chartSymbol = norm.normalized;
    const invalidChartSymbols = ['USDTUSDT', 'USDCUSDT', 'FDUSDUSDT', 'BUSDUSDT', 'TUSDUSDT', 'DAIUSDT'];
    if (invalidChartSymbols.includes(chartSymbol)) {
        container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--ds-text-tertiary);font-size:0.75rem;">—</div>';
        return;
    }
    var hadContent = container.querySelector('svg');
    if (!hadContent) container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--ds-text-secondary);font-size:0.8rem;">Yükleniyor...</div>';
    try {
        const data = await window.apiClient.get('/api/spot/klines?symbol=' + encodeURIComponent(chartSymbol) + '&interval=5m&limit=288');
        if (!Array.isArray(data) || data.length < 2) {
            container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--ds-text-secondary);font-size:0.75rem;">Veri yok</div>';
            return;
        }
        const points = data.map(k => ({ t: Number(k.t), o: Number(k.o), h: Number(k.h), l: Number(k.l), c: Number(k.c) }));
        const dataMin = Math.min(...points.map(p => p.l));
        const dataMax = Math.max(...points.map(p => p.h));
        const range = dataMax - dataMin || 1;
        const w = 260;
        const h = 100;
        const pad = 12;
        const linePoints = points.map((p, i) => {
            const x = pad + (i / (points.length - 1 || 1)) * (w - 2 * pad);
            const y = pad + (1 - (p.c - dataMin) / range) * (h - 2 * pad);
            return { x, y };
        });
        const pathD = linePoints.map((p, i) => (i === 0 ? 'M' : 'L') + ' ' + p.x + ' ' + p.y).join(' ');
        const first = points[0].c;
        const last = points[points.length - 1].c;
        const isUp = last >= first;
        const stroke = isUp ? '#00C076' : '#F6465D';
        container.innerHTML = '<svg width="100%" height="100%" viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none"><defs><linearGradient id="dmChartGrad" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="' + stroke + '" stop-opacity="0.25"/><stop offset="1" stop-color="' + stroke + '" stop-opacity="0"/></linearGradient></defs><path d="' + pathD + ' L ' + linePoints[linePoints.length - 1].x + ' ' + (h - pad) + ' L ' + pad + ' ' + (h - pad) + ' Z" fill="url(#dmChartGrad)" stroke="' + stroke + '" stroke-width="1.5" fill-opacity="1"/></svg>';
    } catch (e) {
        if (typeof window.__DEBUG_DASH__ !== 'undefined' && window.__DEBUG_DASH__) console.warn('[dashboard] loadCreateBotModalChart error:', e);
        container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--ds-text-tertiary);font-size:0.75rem;">—</div>';
    }
}

var SYMBOL_SEARCH_STOP_WORDS = { COIN: 1, TOKEN: 1, PARITE: 1, PAIR: 1, CRYPTO: 1, KRIPTO: 1, PARITY: 1 };
/** Binance quote varlıkları (uzun sonek önce denenir) — USDT + çapraz (ETH/BTC/BNB/…) */
var SYMBOL_SEARCH_QUOTE_SUFFIXES = [
    'USDT', 'FDUSD', 'USDC', 'BUSD', 'TUSD', 'DAI', 'USDD',
    'BTC', 'ETH', 'BNB', 'SOL', 'XRP', 'DOGE', 'TRX', 'TRY', 'EUR', 'GBP', 'BRL', 'AUD', 'RUB', 'IDR', 'UAH'
];
var INVALID_TRADING_PAIR_SYMBOLS = new Set(['USDTUSDT', 'USDCUSDT', 'FDUSDUSDT', 'BUSDUSDT', 'TUSDUSDT', 'DAIUSDT']);
/** scope=all coin-list sembolleri — geçerli parite doğrulama */
var binanceTradingSymbolsSet = null;

function tradingPairQuotesByLength() {
    return SYMBOL_SEARCH_QUOTE_SUFFIXES.slice().sort(function (a, b) { return b.length - a.length; });
}

/** Binance paritesi: quote sonekleri uzundan kısaya; tabanda ikinci quote yok (BNBFDUSD+USDT engeli). */
function parseTradingPairSymbol(symbol) {
    var s = (symbol || '').toUpperCase().replace(/[\s\/\-]/g, '');
    if (!s) return { base: '', quote: '', normalized: '', valid: false };
    if (s === 'USDTUSD') return { base: 'USDT', quote: 'USD', normalized: 'USDTUSD', valid: true };
    if (INVALID_TRADING_PAIR_SYMBOLS.has(s)) return { base: '', quote: '', normalized: s, valid: false };
    var quotes = tradingPairQuotesByLength();
    for (var i = 0; i < quotes.length; i++) {
        var q = quotes[i];
        if (!s.endsWith(q) || s.length <= q.length) continue;
        var base = s.slice(0, -q.length);
        if (!base || base === q) continue;
        var nested = false;
        for (var j = 0; j < quotes.length; j++) {
            var q2 = quotes[j];
            if (base.endsWith(q2) && base.length > q2.length) {
                nested = true;
                break;
            }
        }
        if (!nested) {
            return { base: base, quote: q, normalized: base + q, valid: true };
        }
    }
    return { base: s, quote: '', normalized: s, valid: false };
}

function rebuildBinanceTradingSymbolSet() {
    var syms = coinListAllScopeSymbols.length > 0
        ? coinListAllScopeSymbols
        : (coinListAllBinanceSymbols.length > 0 ? coinListAllBinanceSymbols : []);
    binanceTradingSymbolsSet = syms.length > 0 ? new Set(syms) : null;
}

function isValidTradingPairSymbol(symbol) {
    var s = (symbol || '').toUpperCase().replace(/[\s\/\-]/g, '');
    if (!s || INVALID_TRADING_PAIR_SYMBOLS.has(s)) return false;
    if (binanceTradingSymbolsSet && binanceTradingSymbolsSet.size > 0) {
        return binanceTradingSymbolsSet.has(s);
    }
    return parseTradingPairSymbol(s).valid;
}

function formatTradingPairDisplay(symbol) {
    var pq = parseTradingPairSymbol(symbol);
    if (!pq.valid) return (symbol || '').toUpperCase() || '—';
    if (pq.normalized === 'USDTUSD') return 'USDT/USD';
    return pq.base + '/' + pq.quote;
}

function normalizeSymbolSearchQuery(raw) {
    var s = (raw || '').trim().toUpperCase();
    if (!s) return { compact: '', tokens: [], primary: '' };
    var tokens = s.split(/[\s,\/\-]+/).filter(Boolean).filter(function (t) { return !SYMBOL_SEARCH_STOP_WORDS[t]; });
    var compact = (tokens.length ? tokens.join('') : s.replace(/[\s,\/\-]+/g, ''));
    var primary = tokens[0] || compact;
    return { compact: compact, tokens: tokens, primary: primary };
}

function parseBaseQuoteForSearch(symbol) {
    var pq = parseTradingPairSymbol(symbol);
    return { base: pq.base || '', quote: pq.quote || '' };
}

function coinListSearchQuoteOrder(sym) {
    if ((sym || '').endsWith('USDT')) return 0;
    if ((sym || '').endsWith('FDUSD')) return 1;
    if ((sym || '').endsWith('USDC')) return 2;
    if ((sym || '').endsWith('BTC')) return 3;
    if ((sym || '').endsWith('ETH')) return 4;
    if ((sym || '').endsWith('BNB')) return 5;
    return 6;
}

/** "xrp eth", "XRP/ETH" → XRPETH vb. aday semboller */
function resolveSearchSymbolCandidates(qn) {
    var out = [];
    var seen = {};
    function add(sym) {
        var s = (sym || '').toUpperCase();
        if (!s || seen[s] || !isValidTradingPairSymbol(s)) return;
        seen[s] = true;
        out.push(s);
    }
    var tokens = (qn && qn.tokens) ? qn.tokens : [];
    if (tokens.length >= 2) {
        add(tokens[0] + tokens[1]);
        add(tokens[1] + tokens[0]);
    }
    var needle = (qn && (qn.primary || qn.compact)) || '';
    if (needle && /^[A-Z0-9]{2,12}$/.test(needle)) {
        for (var i = 0; i < SYMBOL_SEARCH_QUOTE_SUFFIXES.length; i++) {
            add(needle + SYMBOL_SEARCH_QUOTE_SUFFIXES[i]);
        }
    }
    return out;
}

function symbolSearchMatchScore(symbol, qn) {
    var sym = (symbol || '').toUpperCase();
    if (!sym || !qn) return -1;
    var compact = qn.compact || '';
    var primary = qn.primary || compact;
    if (!primary && !compact) return -1;
    var pq = parseBaseQuoteForSearch(sym);
    var base = pq.base || '';
    var quote = pq.quote || '';
    if (qn.tokens.length >= 2) {
        var t0 = qn.tokens[0];
        var t1 = qn.tokens[1];
        if (base === t0 && quote === t1) return 99;
        if (sym === t0 + t1 || sym === t1 + t0) return 92;
    }
    if (compact && sym.indexOf(compact) !== -1) return 100;
    if (qn.tokens.length) {
        if (base === primary) return 95;
        if (base.indexOf(primary) === 0) return 88;
        if (primary.length >= 2 && base.indexOf(primary) !== -1) return 82;
        var allInSym = qn.tokens.every(function (t) { return sym.indexOf(t) !== -1; });
        if (allInSym) return 75;
        return -1;
    }
    if (base === primary) return 95;
    if (primary.length >= 2 && base.indexOf(primary) === 0) return 88;
    if (primary.length >= 2 && base.indexOf(primary) !== -1) return 82;
    if (compact && sym.indexOf(compact) !== -1) return 70;
    return -1;
}

function getCoinListSearchRows() {
    if (coinListSearchAllSymbols.length > 0) return coinListSearchAllSymbols;
    var fromScope = (coinListAllScopeSymbols || []).map(function (symbol) {
        var mini = window.marketStore && window.marketStore.getMini && window.marketStore.getMini(symbol);
        return { symbol: symbol, last: mini && mini.last, changePct: mini && mini.changePct };
    });
    if (fromScope.length > 0) return fromScope;
    if (window.marketStore && window.marketStore.getAllMini) {
        return (window.marketStore.getAllMini() || []).map(function (m) {
            return { symbol: (m.symbol || '').toUpperCase(), last: m.last, changePct: m.changePct };
        }).filter(function (x) { return x.symbol; });
    }
    return [];
}

function filterCoinListForSearch(query, maxResults, minLen) {
    maxResults = maxResults || 60;
    minLen = minLen != null ? minLen : 2;
    var qn = normalizeSymbolSearchQuery(query);
    var needle = qn.primary || qn.compact || '';
    if (needle.length < minLen) return [];
    var rows = getCoinListSearchRows();
    var scored = [];
    for (var i = 0; i < rows.length; i++) {
        var row = rows[i];
        var score = symbolSearchMatchScore(row.symbol, qn);
        if (score < 0 || !isValidTradingPairSymbol(row.symbol)) continue;
        scored.push({ row: row, score: score });
    }
    scored.sort(function (a, b) {
        if (b.score !== a.score) return b.score - a.score;
        var qA = coinListSearchQuoteOrder(a.row.symbol);
        var qB = coinListSearchQuoteOrder(b.row.symbol);
        if (qA !== qB) return qA - qB;
        return (a.row.symbol || '').localeCompare(b.row.symbol || '');
    });
    var list = scored.slice(0, maxResults).map(function (x) { return x.row; });
    if (list.length === 0) {
        list = resolveSearchSymbolCandidates(qn).map(function (sym) {
            var mini = window.marketStore && window.marketStore.getMini && window.marketStore.getMini(sym);
            return { symbol: sym, last: mini && mini.last, changePct: mini && mini.changePct };
        });
    }
    return list.slice(0, maxResults);
}

if (typeof window !== 'undefined') {
    window.parseTradingPairSymbol = parseTradingPairSymbol;
    window.isValidTradingPairSymbol = isValidTradingPairSymbol;
    window.formatTradingPairDisplay = formatTradingPairDisplay;
}

function isCreateModalSymbolDropdownOpen() {
    const dropdown = document.getElementById('dmSymbolSearchDropdown');
    return !!(dropdown && dropdown.style.display === 'block');
}

function paintCreateModalSymbolDropdown(list, emptyHtml) {
    const dropdown = document.getElementById('dmSymbolSearchDropdown');
    if (!dropdown) return;
    if (!list || !list.length) {
        dropdown.innerHTML = emptyHtml || '<div style="padding: 1rem; color: var(--ds-text-secondary); font-size: 0.9rem;">Sonuç yok. Pariteyi elle yazın (örn. BTCUSDT, XRPETH).</div>';
    } else {
        dropdown.innerHTML = list.map(function (item) {
            return renderCoinSearchDropdownItemHtml(item, 'dm-symbol-search-item');
        }).join('');
    }
    dropdown.style.display = 'block';
    dropdown.style.pointerEvents = 'auto';
}

function showCreateModalSymbolDropdownSuggestions() {
    const fSym = document.getElementById('fSymbol');
    var rows = getCoinListSearchRows();
    if (!rows.length) {
        paintCreateModalSymbolDropdown(null, '<div style="padding: 1rem; color: var(--ds-text-secondary); font-size: 0.9rem;">Sembol listesi yükleniyor…</div>');
        ensureCoinListSearchSymbolsLoaded('all').then(function () {
            buildCoinListSearchSymbols();
            if (fSym && document.activeElement === fSym) showCreateModalSymbolDropdownSuggestions();
        });
        return;
    }
    var list = rows.slice(0, 50);
    paintCreateModalSymbolDropdown(list);
    var priceGen = _dmSymbolSearchPriceGen;
    queueCoinSearchPriceFetch(list.map(function (it) { return it.symbol; }), function () {
        if (priceGen !== _dmSymbolSearchPriceGen) return;
        if (!fSym || document.activeElement !== fSym) return;
        if (!isCreateModalSymbolDropdownOpen()) return;
        showCreateModalSymbolDropdownSuggestions();
    });
}

/** Create modal: sembol arama dropdown göster (fSymbol için) */
function showCreateModalSymbolDropdown(query, minLen) {
    const fSym = document.getElementById('fSymbol');
    const dropdown = document.getElementById('dmSymbolSearchDropdown');
    if (!dropdown) return;
    minLen = minLen != null ? minLen : 2;
    const qn = normalizeSymbolSearchQuery(query);
    const needle = qn.primary || qn.compact || '';
    if (!needle || needle.length < minLen) {
        if (minLen <= 1 && needle.length === 0) showCreateModalSymbolDropdownSuggestions();
        else hideCreateModalSymbolDropdown();
        return;
    }
    let list = filterCoinListForSearch(query, 60, minLen);
    if (list.length === 0) {
        paintCreateModalSymbolDropdown(null);
        return;
    }
    paintCreateModalSymbolDropdown(list);
    var priceGen = _dmSymbolSearchPriceGen;
    queueCoinSearchPriceFetch(list.map(function (it) { return it.symbol; }), function () {
        if (priceGen !== _dmSymbolSearchPriceGen) return;
        if (!fSym || document.activeElement !== fSym) return;
        if (!isCreateModalSymbolDropdownOpen()) return;
        var v = (fSym.value || '').trim();
        if (v.length < minLen) return;
        showCreateModalSymbolDropdown(v, minLen);
    });
}

function hideCreateModalSymbolDropdown() {
    _dmSymbolSearchPriceGen++;
    _dmSymbolSearchPicking = false;
    const dropdown = document.getElementById('dmSymbolSearchDropdown');
    if (dropdown) {
        dropdown.style.display = 'none';
        dropdown.style.pointerEvents = 'none';
    }
}

function bindDmSymbolSearchOutsideClose() {
    if (_dmSymbolSearchOutsideBound) return;
    _dmSymbolSearchOutsideBound = true;
    document.addEventListener('mousedown', function (e) {
        var modal = document.getElementById('dmModal');
        if (!modal || modal.style.display === 'none') return;
        if (!isCreateModalSymbolDropdownOpen()) return;
        var fSym = document.getElementById('fSymbol');
        var wrap = fSym && fSym.closest('.coin-list-search-wrap');
        if (wrap && wrap.contains(e.target)) return;
        hideCreateModalSymbolDropdown();
    });
}

var _dmMultiSearchTargetInput = null;
var _dmMultiSearchTargetIdx = null;

function showMultiSymbolSearchDropdown(query, anchorInputEl) {
    const dropdown = document.getElementById('dmMultiSymbolSearchDropdown');
    if (!dropdown || !anchorInputEl) return;
    const qn = normalizeSymbolSearchQuery(query);
    const needle = qn.primary || qn.compact || '';
    if (!needle || needle.length < 2) {
        dropdown.style.display = 'none';
        return;
    }
    _dmMultiSearchTargetInput = anchorInputEl;
    _dmMultiSearchTargetIdx = anchorInputEl.getAttribute('data-idx');
    var list = filterCoinListForSearch(query, 60);
    if (list.length === 0) {
        dropdown.innerHTML = '<div style="padding: 1rem; color: var(--ds-text-secondary); font-size: 0.9rem;">Sonuç yok. Sembolü elle yazın (örn. BTC).</div>';
        dropdown.style.display = 'block';
    } else {
        dropdown.innerHTML = list.map(function (item) {
            return renderCoinSearchDropdownItemHtml(item, 'dm-multi-symbol-item');
        }).join('');
        dropdown.style.display = 'block';
        queueCoinSearchPriceFetch(list.map(function (it) { return it.symbol; }), function () {
            if (_dmMultiSearchTargetInput && (anchorInputEl.value || '').trim()) {
                showMultiSymbolSearchDropdown(anchorInputEl.value, anchorInputEl);
            }
        });
    }
    var rect = anchorInputEl.getBoundingClientRect();
    dropdown.style.left = rect.left + 'px';
    dropdown.style.top = (rect.bottom + 4) + 'px';
    dropdown.style.width = Math.max(rect.width, 320) + 'px';
}

function hideMultiSymbolSearchDropdown() {
    var dropdown = document.getElementById('dmMultiSymbolSearchDropdown');
    if (dropdown) dropdown.style.display = 'none';
    _dmMultiSearchTargetInput = null;
    _dmMultiSearchTargetIdx = null;
}

function updateMultiAssetPreview(idx, symbol, liveOnly) {
    var sym = (symbol || '').trim().toUpperCase().replace(/\s/g, '');
    if (!sym) sym = '';
    if (sym && !sym.endsWith('USDT')) sym = sym + 'USDT';
    var previewEl = document.querySelector('#multiAssetRows .multi-asset-row[data-idx="' + idx + '"] .multi-asset-preview');
    if (!previewEl) return;
    if (!sym || sym === 'USDT') {
        previewEl.innerHTML = '—';
        previewEl.classList.add('multi-asset-preview-empty');
        previewEl.style.display = 'block';
        return;
    }
    previewEl.classList.remove('multi-asset-preview-empty');
    var mini = window.marketStore && window.marketStore.getMini(sym);
    var price = (mini && mini.last != null) ? mini.last : (window.marketStore && window.marketStore.getPrice && window.marketStore.getPrice(sym));
    var pct = mini && mini.changePct != null ? mini.changePct : null;
    var priceStr = price != null && Number.isFinite(price) ? fmtUsd(price) : '—';
    var pctStr = pct != null && Number.isFinite(pct) ? (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%' : '—';
    var pctColor = pct != null ? (pct >= 0 ? '#0ecb81' : '#f6465d') : 'var(--ds-text-secondary)';
    var highStr = '—';
    var lowStr = '—';
    if (liveOnly) {
        var highVal = previewEl.querySelector('.multi-preview-high-val');
        var lowVal = previewEl.querySelector('.multi-preview-low-val');
        if (highVal) highStr = highVal.textContent || '—';
        if (lowVal) lowStr = lowVal.textContent || '—';
    }
    previewEl.innerHTML = '<div style="display: flex; flex-wrap: wrap; gap: 12px 16px; align-items: center;"><span><strong>Fiyat:</strong> ' + priceStr + '</span><span style="color: ' + pctColor + '"><strong>24s:</strong> ' + pctStr + '</span><span class="multi-preview-high"><strong>24s yüksek:</strong> <span class="multi-preview-high-val">' + highStr + '</span></span><span class="multi-preview-low"><strong>24s düşük:</strong> <span class="multi-preview-low-val">' + lowStr + '</span></span></div>';
    previewEl.style.display = 'block';
    if (liveOnly) return;
    window.apiClient.get('/api/spot/klines?symbol=' + encodeURIComponent(sym) + '&interval=5m&limit=288').then(function (data) {
        if (Array.isArray(data) && data.length > 0) {
            var low = Math.min.apply(null, data.map(function (k) { return Number(k.l); }));
            var high = Math.max.apply(null, data.map(function (k) { return Number(k.h); }));
            var highVal = previewEl.querySelector('.multi-preview-high-val');
            var lowVal = previewEl.querySelector('.multi-preview-low-val');
            if (highVal) highVal.textContent = fmtUsd(high);
            if (lowVal) lowVal.textContent = fmtUsd(low);
        }
    }).catch(function () {});
}

function collectForm() {
    const symbol = normalizeSymbol(document.getElementById("fSymbol").value);
    const budget = parseFloat(document.getElementById("fBudget").value);
    const basePct = parseFloat(document.getElementById("fBasePct").value);
    const quotePct = parseFloat(document.getElementById("fQuotePct").value);
    
    const upCount = parseInt(document.getElementById("fUpCount").value) || 0;
    const upTrail = parseDecimal(document.getElementById("fUpTrail")?.value, 0.5);
    const upGrids = [];
    for (let i = 0; i < upCount; i++) {
        const trigger = parseDecimal(document.getElementById(`upGrid_${i}_trigger`)?.value, NaN);
        const qty = parseDecimal(document.getElementById(`upGrid_${i}_qty`)?.value, NaN);
        if (Number.isFinite(trigger) && Number.isFinite(qty)) {
            upGrids.push({ trigger_pct: trigger, qty_pct: qty });
        }
    }

    const downCount = parseInt(document.getElementById("fDownCount").value) || 0;
    const downTrail = parseDecimal(document.getElementById("fDownTrail")?.value, 0.5);
    const downGrids = [];
    for (let i = 0; i < downCount; i++) {
        const trigger = parseDecimal(document.getElementById(`downGrid_${i}_trigger`)?.value, NaN);
        const qty = parseDecimal(document.getElementById(`downGrid_${i}_qty`)?.value, NaN);
        if (Number.isFinite(trigger) && Number.isFinite(qty)) {
            downGrids.push({ trigger_pct: trigger, qty_pct: qty });
        }
    }
    
    const rebuyTrigger = parseDecimal(document.getElementById("fRebuyTrigger")?.value, 1.5);
    const rebuyTrail = parseDecimal(document.getElementById("fRebuyTrail")?.value, 0.3);
    const resellTrigger = parseDecimal(document.getElementById("fResellTrigger")?.value, 1.5);
    const resellTrail = parseDecimal(document.getElementById("fResellTrail")?.value, 0.5);
    
    // Dynamic Mode: toggle açıksa payload'a bayrak ekle. Günlük kayıp limiti
    // devre dışı; otomatik bütçe×%5 default gönderilmez.
    var dynModeEl = document.getElementById("fDynamicMode");
    var dynModeOn = !!(dynModeEl && dynModeEl.checked);
    var dailyLossDefault = 0;

    return {
        account_id: State.accountId,
        symbol: symbol,
        strategy_id: "dca_grid_trailing",
        budget_usd: budget,
        initial_capital_usdt: budget,
        allocation: { base_pct: basePct, quote_pct: quotePct },
        up: { trail_pct: upTrail, grids: upGrids },
        down: { trail_pct: downTrail, grids: downGrids },
        max_buy_levels: Math.max(1, downGrids.length),
        profit: {
            rebuy_trigger_pct: rebuyTrigger,
            rebuy_trail_pct: rebuyTrail,
            resell_trigger_pct: resellTrigger,
            resell_trail_pct: resellTrail
        },
        dynamic_mode: dynModeOn,
        daily_loss_limit_usd: dailyLossDefault
    };
}

/** Cüzdan satırında bot/emir kilidi düşülmüş kullanılabilir miktar (varlıklar tablosu ile aynı). */
function getWalletAssetAvailableQty(assetRow) {
    if (!assetRow || typeof assetRow !== 'object') return null;
    var free = parseFloat(assetRow.free);
    if (!Number.isFinite(free)) return null;
    if (assetRow.available != null && Number.isFinite(Number(assetRow.available))) {
        return Number(assetRow.available);
    }
    var botLocked = Number(assetRow.bot_locked) || 0;
    return Math.max(0, free - botLocked);
}

/** Modal için cüzdandaki kullanılabilir quote (USDT vb.) miktarı. Veri yoksa null. */
function getAvailableQuoteInWallet(quoteAsset) {
    var quote = (quoteAsset || "USDT").toString().trim().toUpperCase();
    if (!quote) return null;
    var assets = (typeof assetsState !== "undefined" && assetsState.wallet && assetsState.wallet.assets) ? assetsState.wallet.assets : [];
    for (var i = 0; i < assets.length; i++) {
        if ((assets[i].asset || "").toUpperCase() === quote) {
            return getWalletAssetAvailableQty(assets[i]);
        }
    }
    return null;
}

function formatAvailableQuotePlaceholder(quoteAsset, availableQty) {
    var quote = (quoteAsset || "USDT").toString().trim().toUpperCase() || "USDT";
    if (availableQty == null || !Number.isFinite(availableQty)) return "Kullanılabilir: —";
    var dec = (quote === "USDT" || quote === "BUSD" || quote === "FDUSD") ? 2 : 8;
    return "Kullanılabilir: " + fmtNum(availableQty, dec) + " " + quote;
}

function updateDcaBudgetPlaceholder() {
    var modal = document.getElementById("dmModal");
    var wizard = document.getElementById("dmWizardDca");
    if (!modal || modal.style.display === "none" || !wizard || wizard.style.display === "none") return;
    var fBudget = document.getElementById("fBudget");
    if (!fBudget) return;
    var sym = ((document.getElementById("fSymbol") || {}).value || "").trim();
    var quote = "USDT";
    if (sym) {
        try { quote = parseBaseQuote(normalizeSymbol(sym)).quote || "USDT"; } catch (e) {}
    } else {
        var qEl = document.getElementById("dmQuoteAssetName");
        if (qEl && qEl.textContent) quote = qEl.textContent.trim() || "USDT";
    }
    fBudget.placeholder = formatAvailableQuotePlaceholder(quote, getAvailableQuoteInWallet(quote));
}

function validateForm(payload) {
    if (!payload.symbol || !/^[A-Z0-9]+$/.test(payload.symbol)) {
        return "Geçersiz parite formatı";
    }
    if (!payload.budget_usd || payload.budget_usd < 10) {
        return "Bütçe en az 10 USD olmalı";
    }
    if (Math.abs(payload.allocation.base_pct + payload.allocation.quote_pct - 100) > 0.5) {
        return "Base ve Quote toplamı 100 olmalı";
    }
    var downGrids = (payload.down && payload.down.grids) || [];
    var upGrids = (payload.up && payload.up.grids) || [];
    if (downGrids.length < 1 || upGrids.length < 1) {
        return "Alış ve satış gridlerinin her ikisinde de en az bir seviye olmalı";
    }
    if (upGrids.length > 0) {
        var upSum = upGrids.reduce(function(s, g) { return s + (Number(g.qty_pct) || 0); }, 0);
        if (Math.abs(upSum - 100) >= 0.5) {
            return "Satış grid miktar toplamı %100 olmalı (şu an %" + upSum.toFixed(1) + ")";
        }
    }
    if (downGrids.length >= 1) {
        var downSum = downGrids.reduce(function(s, g) { return s + (Number(g.qty_pct) || 0); }, 0);
        if (Math.abs(downSum - 100) >= 0.5) {
            return "Alış grid miktar toplamı %100 olmalı (şu an %" + downSum.toFixed(1) + ")";
        }
    }
    var gridErr = validateDcaGridNotionals(payload);
    if (gridErr) return gridErr;
    return null;
}

function showCreateBotFormError(errorEl, message) {
    if (!errorEl) return;
    errorEl.textContent = message || "";
    errorEl.style.display = message ? "block" : "none";
    if (message) {
        try { errorEl.scrollIntoView({ behavior: "smooth", block: "nearest" }); } catch (e) {}
    }
}

/** Tahmini grid emir tutarı (USDT) — backend config_validate ile uyumlu */
function validateDcaGridNotionals(payload) {
    var MIN = 10;
    var buffer = 0.995;
    var budget = Number(payload.budget_usd || payload.initial_capital_usdt) || 0;
    if (budget <= 0) return null;
    var basePct = Number(payload.allocation && payload.allocation.base_pct) || 50;
    var quotePct = Number(payload.allocation && payload.allocation.quote_pct) || 50;
    var baseUsd = budget * basePct / 100 * buffer;
    var quoteUsd = budget * quotePct / 100 * buffer;
    var bad = [];
    var minBudgetCandidates = [];
    var upGrids = (payload.up && payload.up.grids) || [];
    var downGrids = (payload.down && payload.down.grids) || [];

    function legMinBudget(sidePct, qtyPct) {
        var denom = (sidePct / 100) * (qtyPct / 100) * buffer;
        if (denom <= 0) return null;
        return Math.ceil((MIN + 0.001) / denom * 100) / 100;
    }

    upGrids.forEach(function (g, i) {
        var qtyPct = Number(g.qty_pct);
        if (!Number.isFinite(qtyPct) || qtyPct <= 0) return;
        var n = baseUsd * qtyPct / 100;
        var legMin = legMinBudget(basePct, qtyPct);
        if (legMin != null) minBudgetCandidates.push(legMin);
        if (n <= MIN) bad.push({ side: "Satış", idx: i + 1, n: n, pct: qtyPct });
    });
    downGrids.forEach(function (g, i) {
        var qtyPct = Number(g.qty_pct);
        if (!Number.isFinite(qtyPct) || qtyPct <= 0) return;
        var n = quoteUsd * qtyPct / 100;
        var legMin = legMinBudget(quotePct, qtyPct);
        if (legMin != null) minBudgetCandidates.push(legMin);
        if (n <= MIN) bad.push({ side: "Alım", idx: i + 1, n: n, pct: qtyPct });
    });
    if (!bad.length) return null;
    var minBudget = minBudgetCandidates.length ? Math.max.apply(null, minBudgetCandidates) : null;
    var parts = ["Bot oluşturulamaz: en az bir grid emri 10 USDT altında kalıyor (Binance limiti)."];
    bad.forEach(function (b) {
        parts.push(b.side + " grid #" + b.idx + ": tahmini " + b.n.toFixed(2) + " USDT (grid başına en az " + MIN + " USDT gerekir, miktar %" + b.pct + ").");
    });
    if (minBudget != null && minBudget > 0) {
        parts.push("Bu parametrelerle bot için minimum bütçe: " + minBudget.toFixed(2) + " USDT (girdiğiniz: " + budget.toFixed(2) + " USDT).");
    } else {
        parts.push("Bütçeyi artırın, grid sayısını azaltın veya grid miktar yüzdelerini yükseltin.");
    }
    return parts.join(" ");
}

async function createBot() {
    const errorEl = document.getElementById("createBotError");
    if (errorEl) errorEl.style.display = "none";
    
    const payload = collectForm();
    const error = validateForm(payload);

    if (error) {
        showCreateBotFormError(errorEl, error);
        return;
    }

    // Parametre asistanı önerisi uygulanarak açılan bot → config_source + iz metadata.
    if (dmParamAssistantAppliedSource) {
        payload.config_source = 'param_assistant';
        if (dmParamAssistantAppliedSource.job_id) payload.param_assistant_job_id = dmParamAssistantAppliedSource.job_id;
        if (dmParamAssistantAppliedSource.decision != null) payload.param_assistant_decision = dmParamAssistantAppliedSource.decision;
        if (dmParamAssistantAppliedSource.confidence != null) payload.param_assistant_confidence = dmParamAssistantAppliedSource.confidence;
        payload.param_assistant = {
            source: 'param_assistant',
            job_id: dmParamAssistantAppliedSource.job_id || null,
            decision_id: dmParamAssistantAppliedSource.decision_id || null,
            decision: dmParamAssistantAppliedSource.decision != null ? dmParamAssistantAppliedSource.decision : null,
            confidence: dmParamAssistantAppliedSource.confidence != null ? dmParamAssistantAppliedSource.confidence : null,
            template_key: dmParamAssistantAppliedSource.template_key || null,
            param_score: dmParamAssistantAppliedSource.param_score != null ? dmParamAssistantAppliedSource.param_score : null,
            regime_tag: dmParamAssistantAppliedSource.regime_tag || null,
            symbol: dmParamAssistantAppliedSource.symbol || payload.symbol || null
        };
    }

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
        const body = {
            account_id: payload.account_id,
            config_json: JSON.stringify(payload)
        };
        // REFACTOR: Use apiClient instead of fetch
        const data = await window.apiClient.post("/api/bots/create", body);
        const botId = data.bot_id || data.id;
        dmParamAssistantAppliedSource = null;  // P0-4: bir sonraki (manuel) botu yanlış etiketleme
        
        if (window.Toast) {
            window.Toast.success("Bot oluşturuldu");
        }
        try { saveLastCreateBotParams(State.accountId, payload); } catch (e) {}
        
        closeCreateBotModal();
        
        // Refresh bots list
        await loadSummary(State.accountId);
        
    } catch (error) {
        console.error("[dashboard] createBot error:", error);
        if (errorEl) {
            const msg = (error && error.message) || (typeof error === "string" ? error : "Bilinmeyen hata");
            errorEl.textContent = "Hata: " + msg;
            errorEl.style.display = "block";
        }
    }
}

// Refresh button - removed
function bindRefresh() {
    // Refresh button removed from UI
    // No-op function since button was removed
}

// SIMPLIFIED: Filter and sort (disabled for now - always show all bots)
let botsSortOrder = 'default';
let botsFilter = 'all';

function bindBotsActions() {
    // Filter and sort buttons removed - no longer needed
}

// ========== Binance Modal ==========

// ========== Binance Tab Functions ==========

// ---------- BinanceAssetsPanel (rebuilt): wallet + marketStore separation, fast price tick, leak-free ----------
const PRICE_UI_TICK_MS = 1000;
