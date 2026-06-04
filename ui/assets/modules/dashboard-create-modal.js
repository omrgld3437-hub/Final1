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
var DASHBOARD_LAST_CREATE_BOT_PARAMS = "dashboard_last_create_bot_params";

/** Son oluşturulan bot parametrelerini forma uygula (yeni bot açılırken önceki değerler girili olsun) */
function applyLastCreateParamsToForm() {
    try {
        var raw = localStorage.getItem(DASHBOARD_LAST_CREATE_BOT_PARAMS);
        if (!raw) return;
        var p = JSON.parse(raw);
        if (!p || typeof p !== "object") return;
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
        if (upCountEl && upGrids.length > 0) { upCountEl.value = upGrids.length; buildGridRows("upGridRows", upGrids.length, "up"); }
        if (downCountEl && downGrids.length > 0) { downCountEl.value = downGrids.length; buildGridRows("downGridRows", downGrids.length, "down"); }
        var upTrailEl = document.getElementById("fUpTrail");
        var downTrailEl = document.getElementById("fDownTrail");
        var maxBuyEl = document.getElementById("fMaxBuyLevels");
        if (upTrailEl && (up.trail_pct != null || up.trail_pct === 0)) upTrailEl.value = up.trail_pct;
        if (downTrailEl && (down.trail_pct != null || down.trail_pct === 0)) downTrailEl.value = down.trail_pct;
        if (maxBuyEl) maxBuyEl.value = p.max_buy_levels || Math.max(1, downGrids.length || 1);
        for (var i = 0; i < upGrids.length; i++) {
            var tEl = document.getElementById("upGrid_" + i + "_trigger");
            var qEl = document.getElementById("upGrid_" + i + "_qty");
            if (tEl && upGrids[i].trigger_pct != null) tEl.value = upGrids[i].trigger_pct;
            if (qEl && upGrids[i].qty_pct != null) qEl.value = upGrids[i].qty_pct;
        }
        for (var j = 0; j < downGrids.length; j++) {
            var t2 = document.getElementById("downGrid_" + j + "_trigger");
            var q2 = document.getElementById("downGrid_" + j + "_qty");
            if (t2 && downGrids[j].trigger_pct != null) t2.value = downGrids[j].trigger_pct;
            if (q2 && downGrids[j].qty_pct != null) q2.value = downGrids[j].qty_pct;
        }
        var rebuyT = document.getElementById("fRebuyTrigger");
        var rebuyTrail = document.getElementById("fRebuyTrail");
        var resellT = document.getElementById("fResellTrigger");
        var resellTrail = document.getElementById("fResellTrail");
        if (rebuyT && (profit.rebuy_trigger_pct != null || profit.rebuy_trigger_pct === 0)) rebuyT.value = profit.rebuy_trigger_pct;
        if (rebuyTrail && profit.rebuy_trail_pct != null) rebuyTrail.value = profit.rebuy_trail_pct;
        if (resellT && (profit.resell_trigger_pct != null || profit.resell_trigger_pct === 0)) resellT.value = profit.resell_trigger_pct;
        if (resellTrail && profit.resell_trail_pct != null) resellTrail.value = profit.resell_trail_pct;
        if (p.symbol && typeof updateCreateBotModalPairStrip === "function") updateCreateBotModalPairStrip(p.symbol);
    } catch (e) { console.debug("applyLastCreateParamsToForm", e); }
}

function openCreateBotModal(botId = null, accountId = null, skipLastCreateParams = false, focusFieldId = null) {
    const modal = document.getElementById("dmModal");
    const backdrop = document.getElementById("dmBackdrop");
    if (!modal || !backdrop) return;
    try {
        var templateId = (currentSelectedTemplate && currentSelectedTemplate.id) ? currentSelectedTemplate.id : "trailing_dca";
        sessionStorage.setItem("createBotParamScreen", templateId);
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
    hideMultiSymbolSearchDropdown();
    modal.setAttribute("aria-hidden", "true");
    backdrop.setAttribute("aria-hidden", "true");
    modal.style.display = "none";
    backdrop.style.display = "none";
    document.body.style.overflow = "";
    
    // Reset edit mode
    createModalEditMode = { botId: null, accountId: null, isEdit: false };
    currentSelectedTemplate = null; // Reset template selection
    try { sessionStorage.removeItem("createBotParamScreen"); } catch (e) {}
    // Reset submit button (Oluştur = her zaman oluştur + başlat)
    const submitBtn = document.getElementById("dmSubmitBtn");
    if (submitBtn) {
        submitBtn.textContent = "Oluştur";
        submitBtn.disabled = false;
        submitBtn.style.opacity = "1";
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
        else if (input.id === "fUpTrail" || input.id === "fDownTrail" || input.id === "fResellTrail") input.value = "0.5";
        else if (input.id === "fRebuyTrigger" || input.id === "fResellTrigger") input.value = "1.5";
        else if (input.id === "fRebuyTrail") input.value = "0.30";
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
    
    // Ondalık alanlarda virgülü noktaya çevir (0,5 → 0.5) type="number" uyumu için
    ["fUpTrail", "fDownTrail", "fRebuyTrigger", "fRebuyTrail", "fResellTrigger", "fResellTrail"].forEach(function (id) {
        var el = document.getElementById(id);
        if (el) el.addEventListener("input", function () {
            var v = this.value;
            if (v && v.indexOf(",") !== -1) this.value = v.replace(",", ".");
        });
    });

    // ESC key - close active modal
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
            const structureModal = document.getElementById("botStructureModal");
            const paramModal = document.getElementById("dmModal");
            if (structureModal && structureModal.getAttribute("aria-hidden") === "false") {
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

function _gridInputWheelHandler(e) {
    e.preventDefault();
    var step = parseFloat(this.dataset.wheelStep) || 0.5;
    var cur = parseFloat(this.value) || 0;
    var delta = e.deltaY < 0 ? step : -step;
    var min = this.min !== '' ? parseFloat(this.min) : -Infinity;
    var max = this.max !== '' ? parseFloat(this.max) : Infinity;
    var next = Math.round((cur + delta) * 1000) / 1000;
    if (next < min) next = min;
    if (next > max) next = max;
    this.value = next;
    this.dispatchEvent(new Event('input', { bubbles: true }));
}

function buildGridRows(containerId, count, mode) {
    const container = document.getElementById(containerId);
    if (!container) return;

    // Mevcut değerleri koru (count azaldığında kaybetme)
    const prev = {};
    container.querySelectorAll('input[id]').forEach(function(el) { prev[el.id] = el.value; });

    let html = '';
    for (let i = 0; i < count; i++) {
        const triggerLabel = mode === 'up' ? 'Tetik %' : 'Tetik %';
        const triggerTooltip = mode === 'up'
            ? 'Referans fiyatından yukarı yönde %X kadar artışta bu grid tetiklenir.'
            : 'Referans fiyatından aşağı yönde %X kadar düşüşte bu grid tetiklenir.';
        const qtyTooltip = mode === 'up'
            ? 'Bu grid tetiklendiğinde coin miktarının %X\'i satılır. Tüm satış gridlerinin toplamı %100 olmalı.'
            : 'Bu grid tetiklendiğinde USDT miktarının %X\'i ile alış yapılır. Tüm alış gridlerinin toplamı %100 olmalı.';
        const defaultTrigger = ((i + 1) * 0.5).toFixed(1);
        const defaultQty = count > 0 ? (100 / count).toFixed(1) : '10';

        html += `
            <div class="grid-row">
                <div class="form-group">
                    <label class="label-with-tooltip">
                        ${triggerLabel} <span style="color:var(--ds-text-secondary);font-size:0.78rem">#${i+1}</span>
                        <span class="tooltip-icon">ℹ</span>
                        <span class="tooltip-text">${triggerTooltip}</span>
                    </label>
                    <input type="number" id="${mode}Grid_${i}_trigger" class="form-input" step="0.5" min="0.1" data-wheel-step="0.5" placeholder="${defaultTrigger}" />
                </div>
                <div class="form-group">
                    <label class="label-with-tooltip">
                        Miktar %
                        <span class="tooltip-icon">ℹ</span>
                        <span class="tooltip-text">${qtyTooltip}</span>
                    </label>
                    <input type="number" id="${mode}Grid_${i}_qty" class="form-input" step="0.5" min="0.1" max="100" data-wheel-step="0.5" placeholder="${defaultQty}" />
                </div>
            </div>
        `;
    }
    container.innerHTML = html;

    // Önceki değerleri geri yaz
    container.querySelectorAll('input[id]').forEach(function(el) {
        if (prev[el.id] != null && prev[el.id] !== '') el.value = prev[el.id];
    });

    // Scroll (wheel) ile 0.5 adımlı artış
    container.querySelectorAll('input[data-wheel-step]').forEach(function(el) {
        el.removeEventListener('wheel', _gridInputWheelHandler);
        el.addEventListener('wheel', _gridInputWheelHandler, { passive: false });
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
    inputs.forEach(function(el) { sum += parseFloat(el.value) || 0; });
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
        const trigger = parseFloat(document.getElementById(`upGrid_${i}_trigger`)?.value);
        const qty = parseFloat(document.getElementById(`upGrid_${i}_qty`)?.value);
        if (Number.isFinite(trigger) && Number.isFinite(qty)) {
            upGrids.push({ trigger_pct: trigger, qty_pct: qty });
        }
    }

    const downCount = parseInt(document.getElementById("fDownCount").value) || 0;
    const downTrail = parseDecimal(document.getElementById("fDownTrail")?.value, 0.5);
    const downGrids = [];
    for (let i = 0; i < downCount; i++) {
        const trigger = parseFloat(document.getElementById(`downGrid_${i}_trigger`)?.value);
        const qty = parseFloat(document.getElementById(`downGrid_${i}_qty`)?.value);
        if (Number.isFinite(trigger) && Number.isFinite(qty)) {
            downGrids.push({ trigger_pct: trigger, qty_pct: qty });
        }
    }
    
    const rebuyTrigger = parseDecimal(document.getElementById("fRebuyTrigger")?.value, 1.5);
    const rebuyTrail = parseDecimal(document.getElementById("fRebuyTrail")?.value, 0.3);
    const resellTrigger = parseDecimal(document.getElementById("fResellTrigger")?.value, 1.5);
    const resellTrail = parseDecimal(document.getElementById("fResellTrail")?.value, 0.5);
    
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
        }
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
        try { localStorage.setItem(DASHBOARD_LAST_CREATE_BOT_PARAMS, JSON.stringify(payload)); } catch (e) {}
        
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
