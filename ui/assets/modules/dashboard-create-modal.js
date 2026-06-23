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
var dmParamAssistantProgressState = null;
var dmParamAssistantProgressTickTimer = null;
var dmParamAssistantActiveJobId = '';
var dmParamAssistantLastSnapshot = null;
var dmParamAssistantLastTierStartFn = null;
var dmParamAssistantApplyTimers = [];
var dmParamAssistantApplying = false;
var DM_PARAM_ASSISTANT_HISTORY_TTL_MS = (AI_ASSISTANT_SPEC.cache && AI_ASSISTANT_SPEC.cache.marketHistoryTtlMs) || 10 * 60 * 1000;
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

function createBotParamsStorageKey(accountId) {
    return DASHBOARD_LAST_CREATE_BOT_PARAMS_PREFIX + String(accountId || "");
}

function createBotParamScreenStorageKey(accountId) {
    return "createBotParamScreen_" + String(accountId || "");
}

function loadLastCreateBotParams(accountId) {
    if (accountId == null || accountId === "") return null;
    var key = createBotParamsStorageKey(accountId);
    try {
        var raw = localStorage.getItem(key);
        if (!raw) {
            var legacy = localStorage.getItem(DASHBOARD_LAST_CREATE_BOT_PARAMS);
            if (legacy) {
                var legacyObj = JSON.parse(legacy);
                if (legacyObj && Number(legacyObj.account_id) === Number(accountId)) {
                    localStorage.setItem(key, legacy);
                    localStorage.removeItem(DASHBOARD_LAST_CREATE_BOT_PARAMS);
                    raw = legacy;
                }
            }
        }
        if (!raw) return null;
        var p = JSON.parse(raw);
        if (!p || typeof p !== "object") return null;
        if (p.account_id != null && Number(p.account_id) !== Number(accountId)) return null;
        return p;
    } catch (e) {
        return null;
    }
}

function saveLastCreateBotParams(accountId, payload) {
    if (accountId == null || accountId === "" || !payload || typeof payload !== "object") return;
    try {
        var body = Object.assign({}, payload, { account_id: Number(accountId) });
        localStorage.setItem(createBotParamsStorageKey(accountId), JSON.stringify(body));
    } catch (e) { /* ignore */ }
}

window.loadLastCreateBotParams = loadLastCreateBotParams;
window.saveLastCreateBotParams = saveLastCreateBotParams;
window.createBotParamScreenStorageKey = createBotParamScreenStorageKey;

/** Son oluşturulan bot parametrelerini forma uygula (yalnızca aktif hesap) */
function applyLastCreateParamsToForm() {
    try {
        var accountId = State.accountId;
        if (!accountId) return;
        var p = loadLastCreateBotParams(accountId);
        if (!p) return;
        var strategy = (p.strategy_id || "").trim().toLowerCase();
        var currentId = (currentSelectedTemplate && currentSelectedTemplate.id) ? currentSelectedTemplate.id : "trailing_dca";
        var symEl = document.getElementById("fSymbol");
        var budgetEl = document.getElementById("fBudget");
        var basePctEl = document.getElementById("fBasePct");
        var quotePctEl = document.getElementById("fQuotePct");
        if (symEl && p.symbol) { symEl.value = p.symbol; symEl.readOnly = false; }
        if (budgetEl && (p.budget_usd != null || p.initial_capital_usdt != null)) budgetEl.value = p.budget_usd != null ? p.budget_usd : p.initial_capital_usdt;
        var alloc = p.allocation || {};
        if (basePctEl && (alloc.base_pct != null || alloc.base_pct === 0)) basePctEl.value = alloc.base_pct;
        if (quotePctEl && (alloc.quote_pct != null || alloc.quote_pct === 0)) quotePctEl.value = alloc.quote_pct;
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
        if (e.target.id === "dmBackdrop") closeCreateBotModal();
    });
    
    // Close triggers for bot structure modal
    document.getElementById("botStructureCloseBtn")?.addEventListener("click", closeBotStructureModal);
    document.getElementById("botStructureBackdrop")?.addEventListener("click", (e) => {
        if (e.target.id === "botStructureBackdrop") closeBotStructureModal();
    });

    document.getElementById("dmParamAssistantBtn")?.addEventListener("click", openParamAssistantModal);
    document.getElementById("dmParamAssistantCloseBtn")?.addEventListener("click", function () { closeParamAssistantModal(); });
    document.getElementById("dmParamAssistantUseBtn")?.addEventListener("click", acceptParamAssistantRecommendation);
    document.getElementById("dmParamAssistantBackdrop")?.addEventListener("click", function (e) {
        if (e.target.id === "dmParamAssistantBackdrop") e.preventDefault();
    });
    document.getElementById("dmParamAssistantModal")?.addEventListener("click", function (e) {
        if (e.target.id === "dmParamAssistantModal") e.preventDefault();
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
    
    // Base/Quote sync
    const fBasePct = document.getElementById("fBasePct");
    const fQuotePct = document.getElementById("fQuotePct");
    if (fBasePct && fQuotePct) {
        fBasePct.addEventListener("input", () => {
            const baseVal = parseFloat(fBasePct.value) || 0;
            fQuotePct.value = (100 - baseVal).toFixed(1);
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
            const initials = (base || ' ').substring(0, 2).toUpperCase();
            logoEl.innerHTML = url
                ? '<img src="' + url + '" alt="' + base + '" loading="lazy" onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'flex\';" /><span class="varlik-logo-initials" style="display:none">' + initials + '</span>'
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
}

function dmParamAssistantSetApplyTimer(fn, ms) {
    var id = setTimeout(function () {
        dmParamAssistantApplyTimers = dmParamAssistantApplyTimers.filter(function (x) { return x !== id; });
        fn();
    }, ms);
    dmParamAssistantApplyTimers.push(id);
    return id;
}

function dmParamAssistantClearApplyTimers() {
    dmParamAssistantApplyTimers.forEach(function (id) { clearTimeout(id); });
    dmParamAssistantApplyTimers = [];
    dmParamAssistantApplying = false;
    try {
        document.querySelectorAll('.dm-ai-input-writing').forEach(function (el) {
            el.classList.remove('dm-ai-input-writing');
        });
    } catch (e) {}
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
    return n.toFixed(digits == null ? 2 : digits).replace(/\.?0+$/, '');
}

function dmParamAssistantInputTextTr(v, digits) {
    return dmParamAssistantInputText(v, digits).replace('.', ',');
}

function dmParamAssistantTextChunkSize() {
    return document.hidden ? 22 : 5;
}

function dmParamAssistantInputChunkSize() {
    return document.hidden ? 2 : 1;
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
    if (count === 2) return [50, 50];
    if (count === 3) return [40, 35, 25];
    return [30, 25, 25, 20].slice(0, count);
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
    // Alış gridi referans fiyattan MUTLAK düşüş %'sidir; spot piyasada fiyat en
    // fazla %100 düşer (sıfıra iner). %100+ alış tetiği matematiksel olarak imkânsız
    // ve asla dolmayacak ölü bir seviyedir -> bu eşiği aşan alış seviyelerini at.
    var DM_MAX_BUY_DEPTH_PCT = 92;
    for (var i = 0; i < count; i++) {
        var trigger = dmParamAssistantRound(step * Math.pow(depthGrowth, i), 2);
        upGrids.push({ trigger_pct: trigger, qty_pct: qtys[i] });  // satış: yukarı yön, %100+ fiziksel olarak mümkün
        if (trigger < DM_MAX_BUY_DEPTH_PCT) {
            downGrids.push({ trigger_pct: trigger });  // qty aşağıda yeniden dağıtılır
        }
    }
    if (!downGrids.length) {
        downGrids.push({ trigger_pct: dmParamAssistantRound(Math.min(step, DM_MAX_BUY_DEPTH_PCT - 0.5), 2) });
    }
    var downQtys = dmParamAssistantQtys(downGrids.length);
    downGrids.forEach(function (g, j) { g.qty_pct = downQtys[j]; });

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

function dmParamAssistantCoverageText(analysis) {
    if (!analysis) return 'sınırlı';
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

function dmParamAssistantGreetingText(snapshot, rec) {
    var pq = parseBaseQuote(snapshot.symbol || '');
    var name = dmParamAssistantCurrentUserName(snapshot);
    var values = {
        name: name,
        symbol: snapshot.symbol || 'bu parite',
        base: snapshot.base || pq.base || 'coin',
        quote: snapshot.quote || pq.quote || 'USDT',
        regime: rec && rec.regime ? rec.regime : 'piyasa'
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

function dmParamAssistantRenderChips(snapshot, rec, opts) {
    var chips = document.getElementById('dmParamAssistantChips');
    if (!chips) return;
    opts = opts || {};
    var items = dmParamAssistantChipItems(snapshot, rec);
    chips.innerHTML = items.map(function (it, idx) {
        var cls = opts.animated ? ' class="dm-param-assistant-chip-ai"' : '';
        var style = opts.animated ? ' style="--dm-chip-delay:' + (idx * 70) + 'ms"' : '';
        return '<span' + cls + style + '><b>' + dmParamAssistantEscape(it[0]) + '</b>' + dmParamAssistantEscape(it[1]) + '</span>';
    }).join('');
}

function dmParamAssistantSummaryRows(rec) {
    if (rec && rec.backend) return dmParamAssistantBackendSummaryRows(rec);
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
        ['Kâr', 'Rebuy %' + dmParamAssistantInputTextTr(rec.rebuyTrigger, 2) + ', Resell %' + dmParamAssistantInputTextTr(rec.resellTrigger, 2)]
    ];
}

function dmParamAssistantRenderSummary(rec) {
    var el = document.getElementById('dmParamAssistantSummary');
    if (!el) return;
    var rows = dmParamAssistantSummaryRows(rec);
    el.innerHTML = rows.map(function (row) {
        return '<div class="dm-param-assistant-summary-row"><span>' + dmParamAssistantEscape(row[0]) + '</span><strong>' + dmParamAssistantEscape(row[1]) + '</strong></div>';
    }).join('');
    el.style.display = 'grid';
}

function dmParamAssistantRenderSummaryAi(rec) {
    var el = document.getElementById('dmParamAssistantSummary');
    if (!el) return;
    var rows = dmParamAssistantSummaryRows(rec);
    el.innerHTML = '';
    el.style.display = 'grid';
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
    dmParamAssistantLastAutoScrollAt = Date.now();
    body.scrollTop = body.scrollHeight;
    if (window.requestAnimationFrame) {
        window.requestAnimationFrame(function () {
            if (!body || (!dmParamAssistantAutoScroll && !opts.force)) return;
            dmParamAssistantLastAutoScrollAt = Date.now();
            body.scrollTop = body.scrollHeight;
        });
    }
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

function dmParamAssistantTypeIntroText(text, done) {
    var status = document.getElementById('dmParamAssistantStatus');
    if (!status) {
        if (typeof done === 'function') done();
        return;
    }
    status.textContent = '';
    var idx = 0;
    function step() {
        if (!dmParamAssistantTyping) return;
        var chunk = dmParamAssistantTextChunkSize();
        status.textContent += String(text || '').slice(idx, idx + chunk);
        idx += chunk;
        if (idx < String(text || '').length) {
            dmParamAssistantSetTimer(step, DM_PARAM_ASSISTANT_TEXT_MS);
            return;
        }
        dmParamAssistantSetTimer(function () {
            if (typeof done === 'function') done();
        }, 180);
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

function dmParamAssistantTypeLines(lines, idx) {
    var output = document.getElementById('dmParamAssistantOutput');
    var choice = document.getElementById('dmParamAssistantChoice');
    var status = document.getElementById('dmParamAssistantStatus');
    if (!output) return;
    if (idx >= lines.length) {
        dmParamAssistantTyping = false;
        if (choice) choice.style.display = 'flex';
        if (dmParamAssistantRecommendation) {
            dmParamAssistantRenderSummaryAi(dmParamAssistantRecommendation);
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
        dmParamAssistantMaybeScrollToBottom();
        if (charIdx < text.length) {
            dmParamAssistantSetTimer(step, text.charAt(charIdx - 1) === '.' ? DM_PARAM_ASSISTANT_TEXT_MS * 2 : DM_PARAM_ASSISTANT_TEXT_MS);
        } else {
            dmParamAssistantSetTimer(function () { dmParamAssistantTypeLines(lines, idx + 1); }, 220);
        }
    }
    step();
}

// ===================== Backend backtest optimizer (gerçek analiz) =====================
// Parametre asistanı, seçilen analiz seviyesinde (Soft/Orta/Yüksek) SUNUCUDAKİ gerçek
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
        btn.textContent = 'Sonlandırılıyor';
    }
    if (status) status.textContent = 'Analiz sonlandırılıyor…';
    if (live) live.textContent = 'Arka plandaki analiz işi sonlandırılıyor; kayıt temizlenince yeniden seçim yapabilirsin.';
    dmParamAssistantClearTimers();
    dmParamAssistantStopTimeProgress();
    dmParamAssistantActiveBackendRun = ++dmParamAssistantBackendRunSeq;
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
    var output = document.getElementById('dmParamAssistantOutput');
    if (!output || !output.parentNode) return null;
    el = document.createElement('div');
    el.id = 'dmParamAssistantPrep';
    el.className = 'dm-param-assistant-prep dm-pa-tier-select';
    el.style.margin = '4px 0 12px';
    output.parentNode.insertBefore(el, output);
    return el;
}

function dmParamAssistantClearPrep() {
    var el = document.getElementById('dmParamAssistantPrep');
    if (el) { el.innerHTML = ''; el.style.display = 'none'; }
}

function dmParamAssistantShowTierSelect(snapshot, onPick) {
    var prep = dmParamAssistantPrepEl();
    var status = document.getElementById('dmParamAssistantStatus');
    var selectSeq = ++dmParamAssistantTierSelectSeq;
    if (!prep) {
        if (status) status.textContent = 'Analiz seviyesi ekranı hazırlanamadı; lütfen modalı kapatıp yeniden aç.';
        return;
    }
    if (status) status.textContent = 'Analiz derinliğini seç — ' + (snapshot.symbol || 'parite') + ' için en iyi parametreleri sunucuda GERÇEK backtest ile hesaplayacağım.';
    prep.style.display = 'block';

    var fallback = [
        { key: 'soft', label: 'Düşük', description: 'Sunucuda gerçek strateji backtest + son dönem doğrulama. Yerel hızlı tahmin değildir.', eta_low_sec: 30, eta_high_sec: 90, requires_confirm: false },
        { key: 'medium', label: 'Orta', description: '15dk ince veri + OOS doğrulama + Monte Carlo gelecek senaryoları.', eta_low_sec: 180, eta_high_sec: 420, requires_confirm: false },
        { key: 'high', label: 'Yüksek', description: '5dk son yıl + tüm geçmiş + 6-fold walk-forward + ağır Monte Carlo. En az 1 saat, tavan 6 saat.', eta_low_sec: 3600, eta_high_sec: 21600, requires_confirm: true }
    ];

    function render(tiers) {
        if (selectSeq !== dmParamAssistantTierSelectSeq) return;
        if (!prep || prep.style.display === 'none') return;
        prep.innerHTML = '';
        var title = document.createElement('div');
        title.className = 'dm-pa-tier-title';
        title.textContent = 'Analiz seviyesi';
        prep.appendChild(title);
        var cards = document.createElement('div');
        cards.className = 'dm-pa-tier-cards';
        prep.appendChild(cards);
        tiers.forEach(function (t) {
            var card = document.createElement('button');
            card.type = 'button';
            card.className = 'dm-pa-tier-card dm-pa-tier-' + t.key;
            var etaTxt = '~' + dmParamAssistantFmtDuration(t.eta_low_sec) +
                (t.eta_high_sec && t.eta_high_sec !== t.eta_low_sec ? ' – ' + dmParamAssistantFmtDuration(t.eta_high_sec) : '');
            card.innerHTML = '<div class="dm-pa-tier-card-label">' + dmParamAssistantEscape(t.label) + '</div>' +
                '<div class="dm-pa-tier-card-desc">' + dmParamAssistantEscape(t.description || '') + '</div>' +
                '<div class="dm-pa-tier-card-eta">tahmini süre: ' + dmParamAssistantEscape(etaTxt) + (t.cores ? ' · ' + t.cores + ' çekirdek' : '') + '</div>';
            card.addEventListener('click', function () { dmParamAssistantPickTier(snapshot, t, onPick); });
            cards.appendChild(card);
        });
        var note = document.createElement('div');
        note.className = 'dm-pa-tier-note';
        note.textContent = 'Hiçbir seviyede hızlı yerel tahmin gösterilmez; sonuç ancak sunucu backtest ve doğrulama tamamlanınca gelir.';
        prep.appendChild(note);
    }

    render(fallback);
    var api = dmParamAssistantApiCfg();
    dmParamAssistantApiGet(api.tiers, {
        timeout: 12000,
        owner: 'paramAssistant',
        trigger: 'param-assistant-tiers',
        suppressRateLimitToast: true
    }).then(function (resp) {
        render(resp && resp.tiers && resp.tiers.length ? resp.tiers : fallback);
    }).catch(function () {});
}

function dmParamAssistantPickTier(snapshot, tier, onPick) {
    if (!tier.requires_confirm) { onPick(tier.key); return; }
    var prep = dmParamAssistantPrepEl();
    if (!prep) { onPick(tier.key); return; }
    var lo = dmParamAssistantFmtDuration(tier.eta_low_sec);
    var hi = dmParamAssistantFmtDuration(tier.eta_high_sec);
    var accent = 'var(--ai-assistant-accent, #f0b90b)';
    prep.style.display = 'block';
    prep.innerHTML =
        '<div class="dm-pa-tier-confirm" style="border:1px solid ' + accent + ';border-radius:10px;padding:12px 14px;">' +
        '<div style="font-weight:600;margin-bottom:6px;">Yüksek analiz</div>' +
        '<div style="font-size:0.86rem;line-height:1.5;opacity:0.92;">Tüm geçmişi, indikatörleri, gerçek strateji backtest\'ini ve <b>binlerce gelecek senaryosunu (Monte Carlo)</b> işler. İşlemci <b>tam güçte</b> kullanılır. Tahmini süre <b>~' + lo + ' – ' + hi + '</b>. En az 1 saat gerçek arama yapar; skor ancak bundan sonra gerçekten yakınsarsa erken biter.</div>' +
        '<div style="display:flex;gap:8px;margin-top:12px;">' +
        '<button type="button" id="dmPaConfirmYes" class="btn btn-primary-gold btn-sm">Başlat</button>' +
        '<button type="button" id="dmPaConfirmNo" class="btn btn-ghost btn-sm">Geri</button>' +
        '</div></div>';
    var yes = document.getElementById('dmPaConfirmYes');
    var no = document.getElementById('dmPaConfirmNo');
    if (yes) yes.onclick = function () { onPick(tier.key); };
    if (no) no.onclick = function () { dmParamAssistantShowTierSelect(snapshot, onPick); };
}

// ——— Zamana göre ilerleme (blok blok değil; gerçek kalan-zamana dayalı, akıcı) ———
var dmParamAssistantTimeProg = null;       // {targetPct, totalSec, runId, done}
var dmParamAssistantTimeProgTimer = null;

function dmParamAssistantStopTimeProgress() {
    if (dmParamAssistantTimeProgTimer) { clearTimeout(dmParamAssistantTimeProgTimer); dmParamAssistantTimeProgTimer = null; }
    dmParamAssistantTimeProg = null;
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
    var level = opts.level || 'high';
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
    var pollMs = level === 'high' ? 1500 : 850;  // daha sık -> işlenen veri "tık tık" akar
    var maxPolls = Math.ceil((tb + 700) / (pollMs / 1000));
    var polls = 0;
    var consecMiss = 0;  // ardışık poll hatası (Yüksek tier CPU'yu doldururken geçici olabilir)
    var deadlineAt = Date.now() + (tb + (level === 'high' ? 720 : 240)) * 1000;
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
        try { console.warn('[paramAssistant] backend analysis stopped:', msg); } catch (e) {}
        dmParamAssistantClearPrep();
        if (typeof onFail === 'function') dmParamAssistantSetTimer(function () { onFail(msg); }, 350);
    }
    var api = dmParamAssistantApiCfg();
    var budget = dmParamAssistantResolveBudget(snapshot);
    dmParamAssistantShowProgress();
    setStatus('Sunucuda geçmiş veri çekiliyor ve motor hazırlanıyor…');
    dmParamAssistantApiPost(api.optimize, { symbol: snapshot.symbol, budget: budget, analysis_level: level }, {
        timeout: DM_PARAM_ASSISTANT_BACKEND_START_TIMEOUT_MS,
        owner: 'paramAssistant',
        trigger: 'param-assistant-start',
        suppressRateLimitToast: true
    }).then(function (resp) {
        if (!isActiveRun()) return;
        if (!resp || !resp.job_id) { fail('optimizasyon başlatılamadı'); return; }
        dmParamAssistantActiveJobId = resp.job_id;
        if (resp.reused) {
            var runningSymbol = resp.symbol || 'mevcut sembol';
            setStatus('Bu hesapta zaten çalışan analiz var (' + runningSymbol + '); mevcut analize bağlanıldı.');
        }
        dmParamAssistantAttachAndPoll(resp.job_id, {
            runId: runId, level: level, timeBudgetSec: resp.time_budget_sec,
            onDone: onDone, onFail: onFail, firstDelayMs: 550
        });
    }).catch(function (err) {
        if (!isActiveRun()) return;
        var info = dmParamAssistantBackendErrorInfo(err);
        fail(info.label || 'optimizasyon başlatılamadı');
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
    return {
        budget: Number(ui.budget_usd != null ? ui.budget_usd : result.budget),
        basePct: Number(ui.base_alloc_pct),
        quotePct: Number(ui.quote_alloc_pct),
        upGrids: grids(up.grids),
        downGrids: grids(down.grids),
        upTrail: Number(up.trail_pct),
        downTrail: Number(down.trail_pct),
        rebuyTrigger: Number(profit.rebuy_trigger_pct),
        rebuyTrail: Number(profit.rebuy_trail_pct),
        resellTrigger: Number(profit.resell_trigger_pct),
        resellTrail: Number(profit.resell_trail_pct),
        regime: (result.regime && result.regime.label) || '—',
        confidence: result.confidence != null ? result.confidence : 0,
        volatility: '',
        backend: result
    };
}

function dmParamAssistantBackendChipItems(snapshot, rec) {
    var r = rec.backend || {};
    var oos = r.oos || {};
    var ins = r.in_sample || {};
    var st = r.stats || {};
    return [
        ['Parite', snapshot.symbol || r.symbol || '—'],
        ['Rejim', (r.regime && r.regime.label) || rec.regime || '—'],
        ['Güven', (r.confidence != null ? r.confidence : '—') + '/100'],
        ['6 ay getiri*', oos.return_pct != null ? dmParamAssistantPctTxt(oos.return_pct, 1) : '—'],
        ['6 ay tur*', oos.cycles_closed != null ? String(oos.cycles_closed) : '—'],
        ['Geçmiş getiri', ins.return_pct != null ? dmParamAssistantPctTxt(ins.return_pct, 1) : '—'],
        ['Win-rate', ins.win_rate != null ? '%' + dmParamAssistantInputTextTr(ins.win_rate, 0) : '—'],
        ['Grid', rec.upGrids.length + ' / ' + rec.downGrids.length],
        ['Denenen set', (st.evals_total != null ? st.evals_total : '—')]
    ];
}

function dmParamAssistantBackendSummaryRows(rec) {
    var r = rec.backend || {};
    var oos = r.oos || {};
    var ins = r.in_sample || {};
    var st = r.stats || {};
    var fc = r.forecast || {};
    var rows = [
        ['Bütçe', dmParamAssistantInputTextTr(rec.budget, 2)],
        ['Dağılım', '%' + dmParamAssistantInputTextTr(rec.basePct, 1) + ' / %' + dmParamAssistantInputTextTr(rec.quotePct, 1)],
        ['Rejim', ((r.regime && r.regime.label) || rec.regime || '—') + ' · güven ' + (r.confidence != null ? r.confidence : '—') + '/100'],
        ['Satış grid', dmParamAssistantGridText(rec.upGrids, '+')],
        ['Alış grid', dmParamAssistantGridText(rec.downGrids, '-')],
        ['Trailing', '%' + dmParamAssistantInputTextTr(rec.upTrail, 2) + ' / %' + dmParamAssistantInputTextTr(rec.downTrail, 2)],
        ['Kâr döngüsü', 'Rebuy %' + dmParamAssistantInputTextTr(rec.rebuyTrigger, 2) + ' · Resell %' + dmParamAssistantInputTextTr(rec.resellTrigger, 2)]
    ];
    if (oos && oos.return_pct != null) {
        rows.push(['Doğrulama (6 ay)*', 'getiri ' + dmParamAssistantPctTxt(oos.return_pct, 1) + ' · ' + (oos.cycles_closed || 0) + ' tur · maks. düşüş %' + dmParamAssistantInputTextTr(oos.max_drawdown_pct, 1)]);
    }
    if (ins && ins.return_pct != null) {
        rows.push(['Geçmiş (in-sample)', 'getiri ' + dmParamAssistantPctTxt(ins.return_pct, 1) + ' · win %' + dmParamAssistantInputTextTr(ins.win_rate, 0) + ' · ' + (ins.cycles_closed || 0) + ' tur']);
    }
    if (fc && fc.median_return_pct != null) {
        rows.push(['Gelecek (Monte Carlo)', 'medyan ' + dmParamAssistantPctTxt(fc.median_return_pct, 1) + ' · kâr olasılığı %' + dmParamAssistantInputTextTr((fc.prob_profit || 0) * 100, 0) + ' · ' + (fc.n_paths || 0) + ' senaryo']);
    }
    rows.push(['Hesap', (st.evals_total != null ? st.evals_total : '—') + ' kombinasyon · ' + (st.workers != null ? st.workers : '—') + ' çekirdek · ' + (st.elapsed_sec != null ? st.elapsed_sec : '—') + ' sn' + (st.degraded ? ' · kısa arama' : '')]);
    return rows;
}

function dmParamAssistantRenderBackendResult(snapshot, result) {
    if (!result || !result.ui_config) return false;
    if (result.stats && result.stats.degraded) return false;
    // KARAR KAPANIŞI: backend 'çekil' dediyse seti ÖNERME — apply sunma, dürüst verdict göster.
    var decision = result.decision || {};
    if (decision.decision === 'abstain') {
        dmParamAssistantShowDecisionAbstain(snapshot, result, decision);
        return true;
    }
    var rec = dmParamAssistantBuildBackendRec(snapshot, result);
    if (!rec.upGrids.length || !rec.downGrids.length) return false;
    rec.decision = decision;
    rec.watchOnly = (decision.decision === 'watch_only');
    rec.introText = dmParamAssistantGreetingText(snapshot, rec);
    dmParamAssistantRecommendation = rec;
    dmParamAssistantTyping = true;
    var lines = (result.rationale && result.rationale.lines) ? result.rationale.lines.slice() : [];
    lines.push('Not: "6 ay" satırları botun GÖRMEDİĞİ son ~6 ay üzerinde yapılan doğrulamadır (out-of-sample) — gerçeğe en yakın beklenti budur.');
    dmParamAssistantAnimateIntroAndChips(snapshot, rec, function () {
        dmParamAssistantTypeLines(lines, 0);
    });
    return true;
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
    if (status) status.textContent = 'Karar: önerilmiyor — çekil';
    if (summary) { summary.innerHTML = ''; summary.style.display = 'none'; }
    if (choice) choice.style.display = 'none';
    if (chips) chips.innerHTML = '';
    if (!output) return;
    var hb = decision.honest_benchmark || {};
    var n1 = function (v) { return dmParamAssistantInputTextTr(v, 1); };
    var headline = dmParamAssistantEscape(decision.headline || 'Bu set önerilmiyor.');
    var reasons = (decision.reasons || []).map(function (r) {
        return '<li>' + dmParamAssistantEscape(r) + '</li>';
    }).join('');
    var flags = (decision.red_flags || []).filter(function (f) { return f && f.severity === 'high'; })
        .map(function (f) { return '<li>' + dmParamAssistantEscape(f.text) + '</li>'; }).join('');
    var bench =
        '<div class="dm-pa-error-reason"><span>Bot (OOS)</span><strong>%' + n1(hb.bot_return_pct) + '</strong></div>' +
        '<div class="dm-pa-error-reason"><span>Hedef tahsisi PASİF tutma</span><strong>%' + n1(hb.intended_hold_return_pct) + '</strong></div>' +
        '<div class="dm-pa-error-reason"><span>Dürüst alpha (vs pasif)</span><strong>%' + n1(hb.honest_alpha_pct) + '</strong></div>' +
        '<div class="dm-pa-error-reason"><span>Dağıtıma değer olasılığı</span><strong>%' + dmParamAssistantInputTextTr((decision.deploy_probability || 0) * 100, 0) + '</strong></div>';
    output.innerHTML =
        '<div class="dm-param-assistant-error dm-pa-abstain" role="status" aria-live="polite">' +
        '<div class="dm-pa-error-head">' +
        '<div class="dm-pa-error-mark" aria-hidden="true">⚖</div>' +
        '<div class="dm-pa-error-title-wrap">' +
        '<div class="dm-pa-error-kicker">Dürüst karar</div>' +
        '<div class="dm-pa-error-title">Önerilmiyor — çekil</div>' +
        '</div></div>' +
        '<div class="dm-pa-error-note">' + headline + '</div>' +
        bench +
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
    if (status) status.textContent = 'Backtest tamamlanmadı — parametre gösterilmiyor';
    if (summary) { summary.innerHTML = ''; summary.style.display = 'none'; }
    if (choice) choice.style.display = 'none';
    if (chips) chips.innerHTML = '';
    if (!output) return;
    var safeReason = dmParamAssistantEscape(reason || 'Analiz tamamlanamadı.');
    output.innerHTML =
        '<div class="dm-param-assistant-error" role="status" aria-live="polite">' +
        '<div class="dm-pa-error-head">' +
        '<div class="dm-pa-error-mark" aria-hidden="true">!</div>' +
        '<div class="dm-pa-error-title-wrap">' +
        '<div class="dm-pa-error-kicker">Analiz durdu</div>' +
        '<div class="dm-pa-error-title">Backtest tamamlanmadı</div>' +
        '</div>' +
        '</div>' +
        '<div class="dm-pa-error-reason"><span>Neden</span><strong>' + safeReason + '</strong></div>' +
        '<div class="dm-pa-error-note">Parametre gösterilmedi; hızlı yerel tahmin kapalı. Bir seviye sunucuda gerçek backtest ve doğrulama ile tamamlanmadan öneri uygulanmaz.</div>' +
        '<div class="dm-pa-error-actions">' +
        '<button type="button" id="dmPaRetrySame" class="btn btn-primary-gold btn-sm dm-pa-error-primary">Tekrar dene</button>' +
        '<button type="button" id="dmPaRetryTier" class="btn btn-ghost btn-sm dm-pa-error-secondary">Seviye seç</button>' +
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
    dmParamAssistantActiveBackendRun = ++dmParamAssistantBackendRunSeq;
    dmParamAssistantProgressState = null;
    dmParamAssistantTyping = false;
    dmParamAssistantRecommendation = null;
    modal.classList.remove('is-closing');
    modal.setAttribute('aria-hidden', 'false');
    if (backdrop) backdrop.setAttribute('aria-hidden', 'true');
    modal.style.display = 'flex';
    if (backdrop) backdrop.style.display = 'none';

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
    if (status) status.textContent = (AI_ASSISTANT_SPEC.modal && AI_ASSISTANT_SPEC.modal.initialStatus) || 'Parite verileri okunuyor';
    dmParamAssistantAutoScroll = true;
    dmParamAssistantLastAutoScrollAt = 0;
    var assistantBody = document.querySelector('#dmParamAssistantModal .dm-param-assistant-body');
    dmParamAssistantBindBodyScroll(assistantBody);
    if (assistantBody) assistantBody.scrollTop = 0;

    var firstSnapshot = dmParamAssistantCurrentSnapshot();
    dmParamAssistantLastSnapshot = firstSnapshot;
    if (!firstSnapshot.symbol) {
        dmParamAssistantTyping = false;
        if (status) status.textContent = 'Önce işlem çiftini ve bakiyeni seçmen gerekiyor';
        return;
    }

    dmParamAssistantClearPrep();

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
        statusFn('Sunucu analizi başlıyor — backtest, doğrulama ve seçilen seviye hesapları tamamlanmadan sonuç gösterilmeyecek…');
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

    // Yeniden-bağlanma / tek-sefer: bu hesabın arka planda çalışan ya da yeni biten işi var mı?
    statusFn('Önceki analiz durumu kontrol ediliyor…');
    var paApi = dmParamAssistantApiCfg();
    var openRunId = dmParamAssistantActiveBackendRun;
    function showTierFlow() {
        if (openRunId !== dmParamAssistantActiveBackendRun) return;
        statusFn('Analiz seviyesini seç — sonuç yalnız sunucuda tamamlanan backtest sonrası gösterilecek');
        dmParamAssistantShowTierSelect(firstSnapshot, runBackendLevel);
    }
    dmParamAssistantApiGet((paApi.active || '/api/param-assistant/active'), {
        timeout: 9000, owner: 'paramAssistant', trigger: 'param-assistant-active', suppressRateLimitToast: true
    }).then(function (res) {
        if (openRunId !== dmParamAssistantActiveBackendRun) return; // kullanıcı bu arada seviye seçtiyse bırak
        var st = res && res.state;
        var job = res && res.job;
        if (st === 'running' && job) {
            // Modal kapatılıp yeniden açıldı: arka planda DEVAM EDEN işe yeniden bağlan (sıfırdan başlatma YOK).
            dmParamAssistantActiveJobId = job.id || job.job_id || '';
            dmParamAssistantProgressState = { pct: 1, stageIndex: 0, stageKey: job.stage || 'queued', runId: openRunId };
            dmParamAssistantShowProgress();
            dmParamAssistantUpdateProgress(job);
            statusFn('Bu hesapta çalışan analiz var' + (job.symbol ? ' (' + job.symbol + ')' : '') + '; kaldığı yerden izleniyor.');
            dmParamAssistantAttachAndPoll(job.job_id || job.id, {
                runId: openRunId, level: job.tier || 'high', timeBudgetSec: job.time_budget_sec, firstDelayMs: 200,
                onDone: function () { rendered = true; dmParamAssistantClearPrep(); },
                onFail: function (reason) {
                    rendered = false;
                    dmParamAssistantShowBackendError(reason, function () { runBackendLevel(job.tier || 'high'); }, function () {
                        if (output) output.innerHTML = '';
                        dmParamAssistantShowTierSelect(firstSnapshot, runBackendLevel);
                    });
                }
            });
            return;
        }
        if (st === 'finished' && job && job.result) {
            // İş bittikten sonra açıldı: bitmiş öneriyi TEK SEFER göster (sunucu consumed işaretler).
            var ok = dmParamAssistantRenderBackendResult(firstSnapshot, job.result);
            if (ok) { rendered = true; return; }
            showTierFlow();
            return;
        }
        if (st === 'error' && job) {
            // Son iş başarısızsa: nedenini TEK SEFER göster (tekrar dene / seviye seç).
            rendered = false;
            dmParamAssistantShowBackendError(job.error || 'Önceki analiz tamamlanamadı.', function () { runBackendLevel('high'); }, function () {
                if (output) output.innerHTML = '';
                dmParamAssistantShowTierSelect(firstSnapshot, runBackendLevel);
            });
            return;
        }
        showTierFlow(); // none -> normal seviye seçimi
    }).catch(function () { showTierFlow(); });
}

function closeParamAssistantModal(opts) {
    opts = opts || {};
    var modal = document.getElementById('dmParamAssistantModal');
    var backdrop = document.getElementById('dmParamAssistantBackdrop');
    if (!modal) return;
    dmParamAssistantClearTimers();
    dmParamAssistantStopTimeProgress();
    // NOT: Sunucudaki analiz işi İPTAL EDİLMEZ — arka planda devam eder; yalnızca
    // istemci poll'ü durur. Modal yeniden açılınca GET /active ile bağlanılır.
    dmParamAssistantActiveBackendRun = ++dmParamAssistantBackendRunSeq;
    dmParamAssistantTierSelectSeq++;
    dmParamAssistantProgressState = null;
    dmParamAssistantTyping = false;
    function hide() {
        modal.setAttribute('aria-hidden', 'true');
        if (backdrop) backdrop.setAttribute('aria-hidden', 'true');
        modal.style.display = 'none';
        if (backdrop) backdrop.style.display = 'none';
        modal.classList.remove('is-closing');
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
    el.classList.add('dm-ai-input-writing');
    try { el.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch (e) {}
    try { el.focus({ preventScroll: true }); } catch (e) { try { el.focus(); } catch (_) {} }
    el.value = '';
    dmParamAssistantDispatch(el, 'input');
    var idx = 0;
    function step() {
        var chunk = dmParamAssistantInputChunkSize();
        el.value += value.slice(idx, idx + chunk);
        idx += chunk;
        dmParamAssistantDispatch(el, 'input');
        if (idx < value.length) {
            dmParamAssistantSetApplyTimer(step, DM_PARAM_ASSISTANT_INPUT_MS);
            return;
        }
        dmParamAssistantDispatch(el, 'change');
        if (task.allowReadonly) el.readOnly = oldReadonly;
        el.classList.remove('dm-ai-input-writing');
        if (typeof task.after === 'function') task.after();
        dmParamAssistantSetApplyTimer(done, DM_PARAM_ASSISTANT_FIELD_PAUSE_MS);
    }
    step();
}

function applyParamAssistantRecommendation(rec, onDone) {
    if (!rec) return;
    dmParamAssistantClearTimers();
    dmParamAssistantClearApplyTimers();
    dmParamAssistantApplying = true;
    var submitBtn = document.getElementById('dmSubmitBtn');
    if (submitBtn) submitBtn.classList.remove('dm-ai-create-pulse');
    var tasks = [
        { id: 'fBudget', value: dmParamAssistantInputText(rec.budget, 2) },
        { id: 'fBasePct', value: dmParamAssistantInputText(rec.basePct, 1) },
        { id: 'fQuotePct', value: dmParamAssistantInputText(rec.quotePct, 1), allowReadonly: true },
        { id: 'fUpCount', value: String(rec.upGrids.length), after: function () { buildGridRows('upGridRows', rec.upGrids.length, 'up'); } },
        { id: 'fUpTrail', value: dmParamAssistantInputTextTr(rec.upTrail, 2) }
    ];
    rec.upGrids.forEach(function (g, idx) {
        tasks.push({ id: 'upGrid_' + idx + '_trigger', value: dmParamAssistantInputTextTr(g.trigger_pct, 2) });
        tasks.push({ id: 'upGrid_' + idx + '_qty', value: dmParamAssistantInputTextTr(g.qty_pct, 1), after: function () { _updateGridQtySum('upGridRows', 'up'); } });
    });
    tasks.push({ id: 'fDownCount', value: String(rec.downGrids.length), after: function () { buildGridRows('downGridRows', rec.downGrids.length, 'down'); syncMaxBuyLevelsWithDownCount(rec.downGrids.length); } });
    tasks.push({ id: 'fDownTrail', value: dmParamAssistantInputTextTr(rec.downTrail, 2) });
    rec.downGrids.forEach(function (g, idx) {
        tasks.push({ id: 'downGrid_' + idx + '_trigger', value: dmParamAssistantInputTextTr(g.trigger_pct, 2) });
        tasks.push({ id: 'downGrid_' + idx + '_qty', value: dmParamAssistantInputTextTr(g.qty_pct, 1), after: function () { _updateGridQtySum('downGridRows', 'down'); } });
    });
    tasks.push({ id: 'fRebuyTrigger', value: dmParamAssistantInputTextTr(rec.rebuyTrigger, 2) });
    tasks.push({ id: 'fRebuyTrail', value: dmParamAssistantInputTextTr(rec.rebuyTrail, 2) });
    tasks.push({ id: 'fResellTrigger', value: dmParamAssistantInputTextTr(rec.resellTrigger, 2) });
    tasks.push({ id: 'fResellTrail', value: dmParamAssistantInputTextTr(rec.resellTrail, 2) });

    function run(i) {
        if (i >= tasks.length) {
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
    closeParamAssistantModal({ immediate: true });
    applyParamAssistantRecommendation(rec, function () {
        if (status) status.textContent = 'Parametreler forma işlendi.';
    });
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
    if (payload.allocation.base_pct + payload.allocation.quote_pct !== 100) {
        return "Base ve Quote toplamı 100 olmalı";
    }
    var downGrids = (payload.down && payload.down.grids) || [];
    if (downGrids.length < 1) {
        return "En az bir alış grid seviyesi tanımlayın";
    }
    var upGrids = (payload.up && payload.up.grids) || [];
    if (upGrids.length > 0) {
        var upSum = upGrids.reduce(function(s, g) { return s + (Number(g.qty_pct) || 0); }, 0);
        if (Math.abs(upSum - 100) >= 0.5) {
            return "Satış grid miktar toplamı %100 olmalı (şu an %" + upSum.toFixed(1) + ")";
        }
    }
    var downSum = downGrids.reduce(function(s, g) { return s + (Number(g.qty_pct) || 0); }, 0);
    if (Math.abs(downSum - 100) >= 0.5) {
        return "Alış grid miktar toplamı %100 olmalı (şu an %" + downSum.toFixed(1) + ")";
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
