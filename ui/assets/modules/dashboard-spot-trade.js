/**
 * dashboard-spot-trade.js
 * Spot trade modal, aktif emirler, coin listesi.
 * dashboard.html'de dashboard.js'ten SONRA yüklenir.
 */

var spotTradeState = (window.spotTradeState && typeof window.spotTradeState === 'object') ? window.spotTradeState : {
    symbol: null,
    side: 'BUY',
    type: 'MARKET',
    currentPrice: 0,
    availableBalance: 0,
    quoteBalance: 0,
    baseBalance: 0,
    quoteAvailable: 0,
    baseAvailable: 0,
    quoteAsset: 'USDT',
    baseAsset: null,
    limitPriceEdited: false,  // Flag to track if user has manually edited limit price
    stepSize: 0.00000001,     // Quantity precision (default: 8 decimals)
    stepSizeStr: '0.00000001',
    minQty: 0.00000001,
    tickSize: 0.01,           // Price precision (default: 2 decimals)
    minNotional: 10.0,        // Minimum order value
    selectedPercent: null     // 25 | 50 | 75 | 100 — aktif yüzde butonu
};
window.spotTradeState = spotTradeState;

var TRADE_MODAL_INVALID_CHART_SYMBOLS = Array.isArray(window.TRADE_MODAL_INVALID_CHART_SYMBOLS)
    ? window.TRADE_MODAL_INVALID_CHART_SYMBOLS
    : ['USDTUSDT', 'USDCUSDT', 'FDUSDUSDT', 'BUSDUSDT', 'TUSDUSDT', 'DAIUSDT'];
window.TRADE_MODAL_INVALID_CHART_SYMBOLS = TRADE_MODAL_INVALID_CHART_SYMBOLS;
var STABLE_COINS = Array.isArray(window.STABLE_COINS)
    ? window.STABLE_COINS
    : ['USDT', 'USDC', 'FDUSD', 'BUSD', 'TUSD', 'DAI', 'USDP', 'USDD'];
window.STABLE_COINS = STABLE_COINS;

function isTradeModalInvalidChartSymbol(symbol) {
    var invalidSymbols = Array.isArray(TRADE_MODAL_INVALID_CHART_SYMBOLS)
        ? TRADE_MODAL_INVALID_CHART_SYMBOLS
        : ['USDTUSDT', 'USDCUSDT', 'FDUSDUSDT', 'BUSDUSDT', 'TUSDUSDT', 'DAIUSDT'];
    return invalidSymbols.indexOf((symbol || '').toUpperCase()) >= 0;
}

// Legacy alias for portfolioState (if referenced elsewhere)
// This prevents "portfolioState is not defined" errors from cached/old code
var portfolioState = (window.portfolioState && typeof window.portfolioState === 'object') ? window.portfolioState : spotTradeState;
window.portfolioState = portfolioState;

// Bind spot trade modal
function bindSpotTradeModal() {
    // Quantity and Total calculation
    const qtyInput = document.getElementById("bnTradeQuantity");
    const totalInput = document.getElementById("bnTradeTotal");
    
    if (qtyInput) {
        qtyInput.addEventListener("input", () => {
            spotTradeState.selectedPercent = null;
            updateTradePercentButtonsUI();
            updateTradeTotal();
        });
    }
    
    if (totalInput) {
        totalInput.addEventListener("input", () => {
            spotTradeState.selectedPercent = null;
            updateTradePercentButtonsUI();
            updateTradeQuantity();
        });
    }
    
    // Limit price input - track user edits
    const limitPriceInput = document.getElementById("bnLimitPrice");
    if (limitPriceInput) {
        limitPriceInput.addEventListener("input", () => {
            // Mark as edited when user types
            spotTradeState.limitPriceEdited = true;
        });
        
        limitPriceInput.addEventListener("focus", () => {
            // Mark as edited when user focuses (they might be about to edit)
            // But only if there's already a value
            if (limitPriceInput.value && limitPriceInput.value !== spotTradeState.currentPrice.toFixed(2)) {
                spotTradeState.limitPriceEdited = true;
            }
        });
    }
    
    // Favori (⭐) butonu
    const favBtn = document.getElementById('bnTradeFavoriteBtn');
    if (favBtn) {
        favBtn.addEventListener('click', function (e) {
            e.preventDefault();
            e.stopPropagation();
            var sym = spotTradeState.symbol;
            if (!sym) return;
            if (!State.accountId) {
                if (window.Toast) window.Toast.warn('Hesap seçin'); else alert('Hesap seçin');
                return;
            }
            var p = toggleSpotFavorite(sym);
            syncFavoriteButtonUI();
            if (typeof renderBinanceCoinList === 'function') renderBinanceCoinList();
            if (typeof renderMobileTradeFavorites === 'function') renderMobileTradeFavorites();
            if (p && p.catch) p.catch(function () { syncFavoriteButtonUI(); if (typeof renderBinanceCoinList === 'function') renderBinanceCoinList(); if (typeof renderMobileTradeFavorites === 'function') renderMobileTradeFavorites(); });
        });
    }

    // Modal grafik tıklanınca detay grafik sayfasına git
    const chartWrap = document.getElementById("bnTradeChartWrap");
    if (chartWrap) {
        chartWrap.addEventListener("click", () => {
            const sym = spotTradeState.symbol;
            if (sym && typeof sym === 'string') {
                window.location.href = '/ui/chart.html?symbol=' + encodeURIComponent(sym);
            }
        });
        chartWrap.addEventListener("keydown", (e) => {
            if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                const sym = spotTradeState.symbol;
                if (sym && typeof sym === 'string') {
                    window.location.href = '/ui/chart.html?symbol=' + encodeURIComponent(sym);
                }
            }
        });
    }

    // Close modal on backdrop click
    const backdrop = document.getElementById("dmBackdrop");
    if (backdrop) {
        backdrop.addEventListener("click", () => {
            closeSpotTradeModal();
        });
    }
}

// Prefetch chart when hovering trade rows (modal açılışını hızlandırır)
function prefetchPriceData(symbol) {
    prefetchTradeModalChart(symbol);
}

// Open spot trade modal - YENİ SPOT ENGINE - Flash Hızında
// symbol: e.g. BTCUSDT; side: optional 'BUY'|'SELL' (default BUY). Al -> BUY, Sat -> SELL.
async function openSpotTradeModal(symbol, side) {
    try {
        if (!State.accountId) {
            showError("Hesap ID bulunamadı");
            return;
        }
        
        const { normalized: normalizedSymbol, invalid: invalidParity } = normalizeModalSymbol(symbol || '');
        if (!normalizedSymbol || invalidParity) {
            spotTradeState.symbol = normalizedSymbol || (symbol || '').toUpperCase();
            spotTradeState.baseAsset = spotTradeState.symbol.replace(/USDT$/i, '') || 'USDT';
            spotTradeState.quoteAsset = 'USDT';
            spotTradeState.side = (side === 'SELL' || side === 'sell') ? 'SELL' : 'BUY';
            spotTradeState.type = 'MARKET';
            spotTradeState.selectedPercent = null;
            const modal = document.getElementById("bnSpotTradeModal");
            const backdrop = document.getElementById("dmBackdrop");
            if (modal) {
                modal.style.display = "block";
                modal.setAttribute("aria-hidden", "false");
                if (backdrop) backdrop.style.display = "block";
                document.body.style.overflow = "hidden";
            }
            document.getElementById("bnTradeQuantity").value = "";
            document.getElementById("bnTradeTotal").value = "";
            document.getElementById("bnLimitPrice").value = "";
            document.getElementById("bnTradeError").style.display = "none";
            updateSpotTradeModal();
            loadTradeModalChart(normalizedSymbol || spotTradeState.symbol);
            var priceEl = document.getElementById("bnTradePrice");
            if (priceEl) priceEl.textContent = "Geçersiz parite";
            syncFavoriteButtonUI();
            return;
        }
        
        const engine = getSpotEngine(State.accountId);
        spotTradeState.symbol = normalizedSymbol;
        const pqOpen = parseTradingPairSymbol(normalizedSymbol);
        spotTradeState.baseAsset = pqOpen.base || normalizedSymbol.replace(/USDT$/i, '') || 'BTC';
        spotTradeState.quoteAsset = pqOpen.quote || 'USDT';
        spotTradeState.side = (side === 'SELL' || side === 'sell') ? 'SELL' : 'BUY';
        spotTradeState.type = 'MARKET';
        spotTradeState.selectedPercent = null;
        
        const modal = document.getElementById("bnSpotTradeModal");
        const backdrop = document.getElementById("dmBackdrop");
        if (modal) {
            modal.style.display = "block";
            modal.setAttribute("aria-hidden", "false");
            if (backdrop) backdrop.style.display = "block";
            document.body.style.overflow = "hidden";
        }
        document.getElementById("bnTradeQuantity").value = "";
        document.getElementById("bnTradeTotal").value = "";
        document.getElementById("bnLimitPrice").value = "";
        document.getElementById("bnTradeError").style.display = "none";
        spotTradeState.limitPriceEdited = false;
        
        const cachedPrice = engine.getCachedPrice(normalizedSymbol);
        if (cachedPrice && cachedPrice > 0) updatePriceDisplay(cachedPrice);
        setModalPriceChangePlaceholder();
        
        updateSpotTradeModal();
        loadTradeModalChart(normalizedSymbol);
        ensureFeeRates(State.accountId).then(() => updateSpotTradeModal());
        
        const abortController = new AbortController();
        window.spotEngineAbortController = abortController;
        
        engine.fetchQuickData(normalizedSymbol, abortController.signal)
            .then(data => {
                if (data && data.ok === false && data.error_code === 'INVALID_SYMBOL') return;
                handleSpotEngineData(data || {});
            })
            .catch(() => {});
        
        function fetchTicker24hAndUpdateModal() {
            if (!spotTradeState.symbol || document.getElementById("bnSpotTradeModal")?.style.display !== "block") return;
            fetch(window.location.origin + '/api/spot/ticker_24h?symbol=' + encodeURIComponent(spotTradeState.symbol))
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (!spotTradeState.symbol || document.getElementById("bnSpotTradeModal")?.style.display !== "block") return;
                    var price = parseFloat(data.lastPrice || data.weightedAvgPrice || 0);
                    var pct = parseFloat(data.priceChangePercent || 0);
                    if (price > 0) {
                        updatePriceDisplay(price);
                        if (window.marketStore && spotTradeState.symbol) {
                            window.marketStore.updateMini(spotTradeState.symbol, { last: price, changePct: pct });
                        }
                    }
                    var changeEl = document.getElementById("bnTradePriceChange");
                    if (changeEl && Number.isFinite(pct)) {
                        var text = (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%';
                        if (setTextIfChanged(changeEl, text)) { }
                        changeEl.style.color = pct >= 0 ? '#0ecb81' : '#f6465d';
                    }
                    var low24 = parseFloat(data.lowPrice || 0);
                    var high24 = parseFloat(data.highPrice || 0);
                    if (spotTradeState.symbol && (low24 > 0 || high24 > 0)) {
                        var dailyLowEl = document.getElementById('bnTradeDailyLow');
                        var dailyHighEl = document.getElementById('bnTradeDailyHigh');
                        if (dailyLowEl && low24 > 0) dailyLowEl.textContent = formatModalPriceForSymbol(low24, spotTradeState.symbol);
                        if (dailyHighEl && high24 > 0) dailyHighEl.textContent = formatModalPriceForSymbol(high24, spotTradeState.symbol);
                    }
                })
                .catch(function () {});
        }
        fetchTicker24hAndUpdateModal();
        window.intervalRegistry.stop('trade.modalSpotPrice');
        window.intervalRegistry.start('trade.modalSpotPrice', fetchTicker24hAndUpdateModal, 1000, 'trade');
        
        syncFavoriteButtonUI();
    } catch (error) {
        console.error("[dashboard] openSpotTradeModal error:", error);
        if (window.errorReporter) window.errorReporter.report(error, { action: 'openSpotTradeModal', symbol, side });
        showError(`Modal açılamadı: ${error.message || 'Bilinmeyen hata'}`);
    }
}

// Handle spot engine data - FLASH HIZLI
function handleSpotEngineData(data) {
    if (!data || !spotTradeState.symbol) return;
    
    // Update price
    if (data.price && data.price > 0) {
        updatePriceDisplay(data.price);
        if (window.marketStore && spotTradeState.symbol) {
            window.marketStore.updateMini(spotTradeState.symbol, { last: data.price });
        }
    }
    
    // Price change %: only updated by ticker_24h interval (single source to avoid flicker)
    
    // Update filters
    if (data.filters) {
        spotTradeState.stepSizeStr = String(data.filters.stepSize || '0.00000001');
        spotTradeState.stepSize = parseFloat(spotTradeState.stepSizeStr) || 0.00000001;
        spotTradeState.minQty = parseFloat(data.filters.minQty || data.filters.stepSize || 0.00000001);
        spotTradeState.tickSize = parseFloat(data.filters.tickSize || 0.01);
        spotTradeState.minNotional = parseFloat(data.filters.minNotional || 5);
    }
    
    var sym = (data.symbol || spotTradeState.symbol || '').toUpperCase();
    if (sym === 'USDTUSD') {
        spotTradeState.baseAsset = 'USDT';
        spotTradeState.quoteAsset = 'USD';
    } else {
        if (data.baseAsset) spotTradeState.baseAsset = data.baseAsset;
        if (data.quoteAsset) spotTradeState.quoteAsset = data.quoteAsset;
    }
    
    // Update balances - IMMEDIATE (no requestAnimationFrame delay). Use available (bot-locked subtracted) for display and 100%.
    if (data.baseBalance !== undefined && data.quoteBalance !== undefined) {
        spotTradeState.quoteBalance = data.quoteBalance || 0;
        spotTradeState.baseBalance = data.baseBalance || 0;
        spotTradeState.quoteAvailable = (data.quoteAvailable != null && Number.isFinite(data.quoteAvailable)) ? data.quoteAvailable : (data.quoteBalance || 0);
        spotTradeState.baseAvailable = (data.baseAvailable != null && Number.isFinite(data.baseAvailable)) ? data.baseAvailable : (data.baseBalance || 0);
        if (spotTradeState.side === 'BUY') {
            spotTradeState.availableBalance = spotTradeState.quoteAvailable;
        } else {
            spotTradeState.availableBalance = spotTradeState.baseAvailable;
        }
        updateSpotTradeModal();
    }
}

// Bootstrap: Binance kaldırıldı – boş/default veri (sonra temiz kurulum ile eklenecek)
async function fetchBootstrapData(symbol, signal) {
    return fetchBootstrapDataFallback(symbol, signal);
}

async function fetchBootstrapDataFallback(symbol, signal) {
    try {
        let price = (window.marketStore && window.marketStore.getPrice(symbol)) || 0;
        if (typeof price !== 'number' || !Number.isFinite(price)) price = 0;
        const base = (symbol || "").replace("USDT", "").replace("BTC", "").replace("ETH", "") || "BTC";
        const filters = {
            tickSize: "0.01",
            stepSize: "0.00001",
            minQty: "0.00001",
            minNotional: "5",
            baseAsset: base,
            quoteAsset: "USDT"
        };
        const balances = { baseFree: 0, quoteFree: 0, base, quote: "USDT" };
        return {
            symbol,
            price,
            filters,
            balances,
            ts: Date.now() / 1000
        };
    } catch (e) {
        return {
            symbol,
            price: 0,
            filters: { tickSize: "0.01", stepSize: "0.00001", minQty: "0.00001", minNotional: "5", baseAsset: symbol.replace("USDT", ""), quoteAsset: "USDT" },
            balances: { baseFree: 0, quoteFree: 0, base: symbol.replace("USDT", ""), quote: "USDT" },
            ts: Date.now() / 1000
        };
    }
}

// Handle bootstrap data response
function handleBootstrapData(data) {
    const perfStart = performance.now();
    
    if (!data || !spotTradeState.symbol) return;
    
    if (data.price && data.price > 0) {
        SpotCache.setPrice(data.symbol, data.price);
        priceCache[data.symbol] = data.price;
        priceCacheTime[data.symbol] = Date.now();
        updatePriceDisplay(data.price);
    }
    
    // Update filters
    if (data.filters) {
        SpotCache.setFilters(data.symbol, data.filters);
        spotTradeState.stepSizeStr = String(data.filters.stepSize || '0.00000001');
        spotTradeState.stepSize = parseFloat(spotTradeState.stepSizeStr) || 0.00000001;
        spotTradeState.minQty = parseFloat(data.filters.minQty || data.filters.stepSize || 0.00000001);
        spotTradeState.tickSize = parseFloat(data.filters.tickSize || 0.01);
        spotTradeState.minNotional = parseFloat(data.filters.minNotional || 5);
        if (data.filters.baseAsset) spotTradeState.baseAsset = data.filters.baseAsset;
        if (data.filters.quoteAsset) spotTradeState.quoteAsset = data.filters.quoteAsset;
    }
    
    // Update balances (bootstrap may not have available; use free as fallback)
    if (data.balances) {
        SpotCache.setBalance(State.accountId, data.balances);
        spotTradeState.quoteBalance = data.balances.quoteFree || 0;
        spotTradeState.baseBalance = data.balances.baseFree || 0;
        spotTradeState.quoteAvailable = data.balances.quoteAvailable ?? spotTradeState.quoteBalance;
        spotTradeState.baseAvailable = data.balances.baseAvailable ?? spotTradeState.baseBalance;
        if (spotTradeState.side === 'BUY') {
            spotTradeState.availableBalance = spotTradeState.quoteAvailable;
        } else {
            spotTradeState.availableBalance = spotTradeState.baseAvailable;
        }
        requestAnimationFrame(() => updateSpotTradeModal());
    }
    
    updateModalPriceChange();
}

function closeSpotTradeModal() {
    const modal = document.getElementById("bnSpotTradeModal");
    const backdrop = document.getElementById("dmBackdrop");
    if (modal) {
        modal.style.display = "none";
        modal.setAttribute("aria-hidden", "true");
        if (backdrop) {
            backdrop.style.display = "none";
        }
        document.body.style.overflow = "";
    }
    
    // Stop Spot Engine updates
    if (State.accountId && spotTradeState.symbol) {
        const engine = getSpotEngine(State.accountId);
        engine.stopUpdates(`price_${spotTradeState.symbol}`);
        engine.stopUpdates(`quick_${spotTradeState.symbol}`);
    }
    
    // Stop price change update interval
    window.intervalRegistry.stop('trade.modalPriceChange');
    window.intervalRegistry.stop('trade.modalSpotPrice');
    window.intervalRegistry.stop('auth.health');
    
    lastModalLogoBase = null;
    
    // Abort in-flight requests
    if (window.spotEngineAbortController) {
        window.spotEngineAbortController.abort();
        window.spotEngineAbortController = null;
    }
    
    if (modalAbortController) {
        modalAbortController.abort();
        modalAbortController = null;
    }
    
    // REFACTOR: Use intervalRegistry - stop all trade intervals
    window.intervalRegistry.stop('trade.modalPrice');
    window.intervalRegistry.stop('trade.priceChange');
    window.intervalRegistry.stop('trade.modalSpotPrice');
    stopBalanceUpdates();
}

function setTradeSide(side) {
    spotTradeState.side = side;
    spotTradeState.selectedPercent = null;
    
    // Update available balance immediately based on current data
    if (State.accountId && spotTradeState.symbol) {
        const engine = getSpotEngine(State.accountId);
        const cachedData = engine.getCachedQuickData(spotTradeState.symbol);
        if (cachedData) {
            spotTradeState.quoteBalance = cachedData.quoteBalance || 0;
            spotTradeState.baseBalance = cachedData.baseBalance || 0;
            spotTradeState.quoteAvailable = (cachedData.quoteAvailable != null && Number.isFinite(cachedData.quoteAvailable)) ? cachedData.quoteAvailable : spotTradeState.quoteBalance;
            spotTradeState.baseAvailable = (cachedData.baseAvailable != null && Number.isFinite(cachedData.baseAvailable)) ? cachedData.baseAvailable : spotTradeState.baseBalance;
            if (side === 'BUY') {
                spotTradeState.availableBalance = spotTradeState.quoteAvailable;
            } else {
                spotTradeState.availableBalance = spotTradeState.baseAvailable;
            }
        } else {
            // Fetch fresh data if not cached
            engine.fetchQuickData(spotTradeState.symbol)
                .then(data => {
                    handleSpotEngineData(data);
                })
                .catch(() => {});
        }
    }
    
    updateSpotTradeModal();
}

function setTradeType(type) {
    spotTradeState.type = type;
    updateSpotTradeModal();
    // Update summary when type changes (taker vs maker fee)
    updateTradeSummary();
}

function updateTradePercentButtonsUI() {
    var selected = spotTradeState.selectedPercent;
    var activeContainerId = spotTradeState.side === 'BUY' ? 'bnTradeTotalPercentButtons' : 'bnTradeQuantityPercentButtons';
    ['bnTradeTotalPercentButtons', 'bnTradeQuantityPercentButtons'].forEach(function (id) {
        var el = document.getElementById(id);
        if (!el) return;
        el.querySelectorAll('button[data-percent]').forEach(function (btn) {
            var pct = parseInt(btn.getAttribute('data-percent'), 10);
            var isActive = id === activeContainerId && selected != null && pct === selected;
            btn.classList.toggle('is-active', isActive);
            btn.setAttribute('aria-pressed', isActive ? 'true' : 'false');
        });
    });
}

function setTradePercent(percent) {
    spotTradeState.selectedPercent = percent;
    const available = spotTradeState.availableBalance || 0;
    const quoteAsset = spotTradeState.quoteAsset || 'USDT';
    
    if (spotTradeState.side === 'BUY') {
        // For BUY, always use quote asset (USDT) for percentage calculation
        const amount = (available * percent) / 100;
        const totalDecimals = getQuoteAssetDecimals(quoteAsset);
        const tickDecimals = spotTradeState.tickSize ? getDecimalPlaces(spotTradeState.tickSize) : totalDecimals;
        const finalDecimals = Math.max(tickDecimals, totalDecimals);
        const totalInput = document.getElementById("bnTradeTotal");
        if (totalInput) {
            totalInput.value = amount.toFixed(finalDecimals);
        }
        updateTradeQuantity();
    } else {
        // For SELL, use base asset
        const amount = percent >= 100 ? getMaxSellQuantity() : quantizeQuantity((available * percent) / 100);
        const decimals = getStepDecimals(spotTradeState.stepSizeStr || spotTradeState.stepSize);
        const qtyInput = document.getElementById("bnTradeQuantity");
        if (qtyInput) {
            qtyInput.value = amount.toFixed(decimals);
        }
        updateTradeTotal();
    }
    updateTradePercentButtonsUI();
}

function getStepDecimals(step) {
    var s = String(step != null ? step : '');
    if (/e/i.test(s)) {
        var m = s.match(/e-(\d+)/i);
        return m ? parseInt(m[1], 10) : 8;
    }
    if (s.indexOf('.') === -1) return 0;
    var frac = s.split('.')[1];
    return (frac.replace(/0+$/, '') || frac).length;
}

function getMaxSellQuantity() {
    var avail = Number(spotTradeState.baseAvailable != null ? spotTradeState.baseAvailable : (spotTradeState.availableBalance || 0));
    if (!avail || avail <= 0) return 0;
    return quantizeQuantity(avail);
}

// Quantize quantity to step size (using proper rounding to avoid floating point errors)
function quantizeQuantity(qty) {
    if (!spotTradeState.stepSize || spotTradeState.stepSize <= 0) {
        return qty;
    }
    const step = spotTradeState.stepSize;
    const steps = Math.floor(qty / step);
    const quantized = steps * step;
    const decimals = getStepDecimals(spotTradeState.stepSizeStr || step);
    return parseFloat(quantized.toFixed(decimals));
}

// Quantize price to tick size
function quantizePrice(price) {
    if (!spotTradeState.tickSize || spotTradeState.tickSize <= 0) {
        return price;
    }
    const tick = spotTradeState.tickSize;
    const quantized = Math.floor(price / tick) * tick;
    return quantized;
}

// Get decimal places from step size or tick size
function getDecimalPlaces(value) {
    if (value >= 1) return 0;
    const str = value.toString();
    if (str.includes('e')) {
        const match = str.match(/e-(\d+)/);
        return match ? parseInt(match[1]) : 8;
    }
    const parts = str.split('.');
    if (parts.length === 1) return 0;
    return parts[1].length;
}

// Format value based on quote asset
function fmtQuoteAsset(value, quoteAsset) {
    if (!quoteAsset) quoteAsset = 'USDT';
    
    if (quoteAsset === 'USDT' || quoteAsset === 'FDUSD' || quoteAsset === 'BUSD' || quoteAsset === 'USDC' || quoteAsset === 'TUSD' || quoteAsset === 'DAI') {
        return fmtUsd(value);
    } else if (quoteAsset === 'BTC') {
        return `${fmtNum(value, 8)} BTC`;
    } else if (quoteAsset === 'ETH') {
        return `${fmtNum(value, 6)} ETH`;
    } else if (quoteAsset === 'BNB') {
        return `${fmtNum(value, 4)} BNB`;
    } else {
        return `${fmtNum(value, 8)} ${quoteAsset}`;
    }
}

// Get decimal places for quote asset
function getQuoteAssetDecimals(quoteAsset) {
    if (!quoteAsset) quoteAsset = 'USDT';
    
    if (quoteAsset === 'USDT' || quoteAsset === 'FDUSD' || quoteAsset === 'BUSD' || quoteAsset === 'USDC' || quoteAsset === 'TUSD' || quoteAsset === 'DAI') {
        return 2;
    } else if (quoteAsset === 'BTC') {
        return 8;
    } else if (quoteAsset === 'ETH') {
        return 6;
    } else if (quoteAsset === 'BNB') {
        return 4;
    } else {
        return 8;
    }
}

function updateTradeTotal() {
    const qtyInput = document.getElementById("bnTradeQuantity");
    if (!qtyInput) return;
    
    const rawQty = parseFloat(qtyInput.value) || 0;
    
    // Quantize quantity to step size
    const qty = quantizeQuantity(rawQty);
    if (qty !== rawQty && rawQty > 0) {
        // Update input with quantized value
        const decimals = getStepDecimals(spotTradeState.stepSizeStr || spotTradeState.stepSize);
        qtyInput.value = qty.toFixed(decimals);
    }
    
    const price = spotTradeState.currentPrice || 0;
    // Always get quote asset from spotTradeState to ensure it's current
    const quoteAsset = spotTradeState.quoteAsset || 'USDT';
    
    // If quantity is 0 or very small, set total to 0 (don't show total value)
    if (qty === 0 || qty < 0.00000001) {
        const totalInput = document.getElementById("bnTradeTotal");
        if (totalInput) {
            totalInput.value = "0.00";
        }
        const qtyValueEl = document.getElementById("bnTradeQuantityValue");
        if (qtyValueEl) {
            qtyValueEl.style.display = "none";
        }
        updateTradeSummary();
        return;
    }
    
    if (price > 0 && qty > 0) {
        const total = qty * price;
        // Format total based on quote asset decimals
        const totalDecimals = getQuoteAssetDecimals(quoteAsset);
        // Use tick size if available for better precision
        const tickDecimals = spotTradeState.tickSize ? getDecimalPlaces(spotTradeState.tickSize) : totalDecimals;
        const finalDecimals = Math.max(tickDecimals, totalDecimals);
        
        const totalInput = document.getElementById("bnTradeTotal");
        if (totalInput) {
            totalInput.value = total.toFixed(finalDecimals);
        }
        
        // Update quantity value display (show total value in quote asset)
        const qtyValueEl = document.getElementById("bnTradeQuantityValue");
        const qtyValueAmountEl = document.getElementById("bnTradeQuantityValueAmount");
        if (qtyValueEl && qtyValueAmountEl) {
            qtyValueEl.style.display = "block";
            // Always use current quote asset from spotTradeState
            qtyValueAmountEl.textContent = fmtQuoteAsset(total, quoteAsset);
        }
        
        updateTradeSummary();
    } else {
        const qtyValueEl = document.getElementById("bnTradeQuantityValue");
        if (qtyValueEl) {
            qtyValueEl.style.display = "none";
        }
        const totalInput = document.getElementById("bnTradeTotal");
        if (totalInput && !totalInput.value) {
            totalInput.value = "";
        }
    }
}

function updateTradeQuantity() {
    const totalInput = document.getElementById("bnTradeTotal");
    if (!totalInput) return;
    
    const total = parseFloat(totalInput.value) || 0;
    const price = spotTradeState.currentPrice || 0;
    
    if (price > 0 && total > 0) {
        const qty = total / price;
        // Quantize quantity to step size
        const quantizedQty = quantizeQuantity(qty);
        const decimals = getDecimalPlaces(spotTradeState.stepSize);
        
        const qtyInput = document.getElementById("bnTradeQuantity");
        if (qtyInput) {
            qtyInput.value = quantizedQty.toFixed(decimals);
        }
        
        // Update total value display (show quantity in base asset)
        const totalValueEl = document.getElementById("bnTradeTotalValue");
        const totalValueAmountEl = document.getElementById("bnTradeTotalValueAmount");
        if (totalValueEl && totalValueAmountEl) {
            totalValueEl.style.display = "block";
            const baseAsset = spotTradeState.baseAsset || '';
            totalValueAmountEl.textContent = `${fmtNum(quantizedQty, decimals)} ${baseAsset}`;
        }
        
        updateTradeSummary();
    } else {
        const qtyValueEl = document.getElementById("bnTradeQuantityValue");
        if (qtyValueEl) {
            qtyValueEl.style.display = "none";
        }
        const totalInput = document.getElementById("bnTradeTotal");
        if (totalInput && !totalInput.value) {
            totalInput.value = "";
        }
    }
}

function updateTradeSummary() {
    const totalInput = document.getElementById("bnTradeTotal");
    if (!totalInput) return;
    
    const total = parseFloat(totalInput.value) || 0;
    // Always get quote asset from spotTradeState to ensure it's current
    const quoteAsset = spotTradeState.quoteAsset || 'USDT';
    
    // Use Binance fee rate (taker for market orders, maker for limit orders)
    // Default to 0.1% if not available
    const feeRates = window.binanceFeeRates || { taker: 0.001, maker: 0.001 };
    const feeRate = spotTradeState.type === 'MARKET' ? feeRates.taker : feeRates.maker;
    const fee = total * feeRate;
    const feePct = (feeRate * 100).toFixed(4);
    
    // Format total and fee based on quote asset
    const summaryAmountEl = document.getElementById("bnTradeSummaryAmount");
    if (summaryAmountEl) {
        summaryAmountEl.textContent = fmtQuoteAsset(total, quoteAsset);
    }
    
    const feeEl = document.getElementById("bnTradeSummaryFee");
    const feeRateEl = document.getElementById("bnTradeFeeRate");
    if (feeEl) {
        feeEl.textContent = fmtQuoteAsset(fee, quoteAsset);
        feeEl.title = `Komisyon oranı: %${feePct} (Binance'den alındı)`;
    }
    if (feeRateEl) {
        feeRateEl.textContent = `${feePct}%`;
    }
}

function updateSpotTradeModal() {
    var symbolDisplay = formatTradingPairDisplay(spotTradeState.symbol || '');
    var symbolEl = document.getElementById("bnTradeSymbol");
    if (symbolEl) symbolEl.textContent = symbolDisplay;
    
    var base = spotTradeState.baseAsset || (spotTradeState.symbol || '').replace(/USDT$/i, '').replace(/BTC$/i, '').replace(/ETH$/i, '').replace(/BNB$/i, '') || '';
    var logoWrap = document.getElementById("bnTradeSymbolLogo");
    if (logoWrap && typeof getCoinLogoUrl === 'function' && base !== lastModalLogoBase) {
        lastModalLogoBase = base;
        var logoUrl = getCoinLogoUrl(base);
        var initials = (base || ' ').substring(0, 2).toUpperCase();
        logoWrap.innerHTML = (typeof buildCoinLogoHtml === "function"
            ? buildCoinLogoHtml(base, { eager: true })
            : (logoUrl
                ? '<img src="' + logoUrl + '" alt="' + base + '" loading="lazy" onload="if(window.markCoinLogoLoaded)window.markCoinLogoLoaded(this)" onerror="if(window.handleCoinLogoError)window.handleCoinLogoError(this)" /><span class="varlik-logo-initials" style="display:none">' + initials + '</span>'
                : '<span class="varlik-logo-initials">' + initials + '</span>'));
    }
    
    // Update labels based on side
    const qtyLabel = document.getElementById("bnTradeQuantityLabel");
    const qtyUnit = document.getElementById("bnTradeQuantityUnit");
    const totalLabel = document.getElementById("bnTradeTotalLabel");
    const totalUnit = document.getElementById("bnTradeTotalUnit");
    
    // Reorder inputs based on side: BUY = USDT first, SELL = Quantity first
    const container = document.getElementById("bnTradeInputsContainer");
    const totalGroup = document.getElementById("bnTradeTotalGroup");
    const quantityGroup = document.getElementById("bnTradeQuantityGroup");
    const totalPercentButtons = document.getElementById("bnTradeTotalPercentButtons");
    const quantityPercentButtons = document.getElementById("bnTradeQuantityPercentButtons");
    
    if (spotTradeState.side === 'BUY') {
        // For BUY: USDT (Total) first, then Quantity
        if (container && totalGroup && quantityGroup) {
            container.insertBefore(totalGroup, quantityGroup);
        }
        // Show percent buttons on USDT (Total) for BUY
        if (totalPercentButtons) totalPercentButtons.style.display = "flex";
        if (quantityPercentButtons) quantityPercentButtons.style.display = "none";
        
        // Update labels
        if (qtyLabel) qtyLabel.textContent = "Miktar";
        if (qtyUnit) qtyUnit.textContent = spotTradeState.baseAsset || '-';
        if (totalLabel) totalLabel.textContent = "Tutar";
        if (totalUnit) totalUnit.textContent = spotTradeState.quoteAsset || 'USDT';
    } else {
        // For SELL: Quantity first, then USDT (Total)
        if (container && totalGroup && quantityGroup) {
            container.insertBefore(quantityGroup, totalGroup);
        }
        // Show percent buttons on Quantity for SELL
        if (totalPercentButtons) totalPercentButtons.style.display = "none";
        if (quantityPercentButtons) quantityPercentButtons.style.display = "flex";
        
        // Update labels
        if (qtyLabel) qtyLabel.textContent = "Miktar";
        if (qtyUnit) qtyUnit.textContent = spotTradeState.baseAsset || '-';
        if (totalLabel) totalLabel.textContent = "Tutar";
        if (totalUnit) totalUnit.textContent = spotTradeState.quoteAsset || 'USDT';
    }
    
    // Update side buttons — CSS sınıfları ile (inline renk yok)
    const buyBtn = document.getElementById("bnTradeBuyBtn");
    const sellBtn = document.getElementById("bnTradeSellBtn");
    if (buyBtn) buyBtn.classList.toggle("is-active", spotTradeState.side === 'BUY');
    if (sellBtn) sellBtn.classList.toggle("is-active", spotTradeState.side === 'SELL');
    
    // Update type buttons
    const marketBtn = document.getElementById("bnTradeTypeMarket");
    const limitBtn = document.getElementById("bnTradeTypeLimit");
    if (marketBtn) {
        marketBtn.classList.toggle("active", spotTradeState.type === 'MARKET');
    }
    if (limitBtn) {
        limitBtn.classList.toggle("active", spotTradeState.type === 'LIMIT');
    }
    
    // Show/hide limit price input
    const limitGroup = document.getElementById("bnLimitPriceGroup");
    const limitPriceInput = document.getElementById("bnLimitPrice");
    if (limitGroup) {
        limitGroup.style.display = spotTradeState.type === 'LIMIT' ? "block" : "none";
    }
    
    // Update limit price only if user hasn't edited it
    if (limitPriceInput && spotTradeState.type === 'LIMIT' && !spotTradeState.limitPriceEdited) {
        if (spotTradeState.currentPrice > 0) {
            const quantizedPrice = quantizePrice(spotTradeState.currentPrice);
            const decimals = getDecimalPlaces(spotTradeState.tickSize);
            limitPriceInput.value = quantizedPrice.toFixed(decimals);
        }
    }
    
    // Update step attribute for quantity input
    const qtyInput = document.getElementById("bnTradeQuantity");
    if (qtyInput) {
        qtyInput.step = spotTradeState.stepSizeStr || spotTradeState.stepSize || 0.00000001;
    }
    
    // Update step attribute for limit price input
    if (limitPriceInput) {
        limitPriceInput.step = spotTradeState.tickSize || 0.01;
    }
    
    // Update submit button (eski stil: Alış = yeşil, Satış = kırmızı)
    const submitBtn = document.getElementById("bnTradeSubmitBtn");
    const submitText = document.getElementById("bnTradeSubmitText");
    if (submitBtn && submitText) {
        submitBtn.disabled = false;
        if (spotTradeState.side === 'BUY') {
            submitBtn.style.background = "#0ecb81";
            submitBtn.style.border = "1px solid rgba(14, 203, 129, 0.5)";
            submitBtn.style.color = "#fff";
        } else {
            submitBtn.style.background = "#f6465d";
            submitBtn.style.border = "1px solid rgba(246, 70, 93, 0.5)";
            submitBtn.style.color = "#fff";
        }
        submitText.textContent = spotTradeState.side === 'BUY'
            ? (spotTradeState.type === 'MARKET' ? "Market Alış Yap" : "Limit Alış Yap")
            : (spotTradeState.type === 'MARKET' ? "Market Satış Yap" : "Limit Satış Yap");
    }
    
    // Tutar (quote) satırında kullanılabilir: Alışta quote, Miktar (base) satırında: Satışta base
    const availableQuoteWrap = document.getElementById("bnTradeAvailableQuoteWrap");
    const availableQuoteEl = document.getElementById("bnTradeAvailableQuote");
    const availableBaseWrap = document.getElementById("bnTradeAvailableBaseWrap");
    const availableBaseEl = document.getElementById("bnTradeAvailableBase");
    if (availableQuoteWrap && availableQuoteEl) {
        if (spotTradeState.side === 'BUY') {
            availableQuoteWrap.style.display = "";
            availableQuoteEl.textContent = fmtNum(spotTradeState.quoteAvailable ?? spotTradeState.quoteBalance ?? 0, getQuoteAssetDecimals(spotTradeState.quoteAsset));
        } else {
            availableQuoteWrap.style.display = "none";
        }
    }
    if (availableBaseWrap && availableBaseEl) {
        if (spotTradeState.side === 'SELL') {
            availableBaseWrap.style.display = "";
            availableBaseEl.textContent = fmtNum(spotTradeState.baseAvailable ?? spotTradeState.baseBalance ?? 0, getStepDecimals(spotTradeState.stepSizeStr || spotTradeState.stepSize));
        } else {
            availableBaseWrap.style.display = "none";
        }
    }

    // Modal UI only – no fetch. Fee rates from ensureFeeRates cache; balance from quick_data/handleSpotEngineData.
    updateTradeSummary();
    updateTradePercentButtonsUI();
}

/** Spot modal fiyat metni — quote USDT/ETH/BTC… */
function formatModalPriceForSymbol(price, symbol) {
    if (price == null || !Number.isFinite(Number(price)) || Number(price) <= 0) return '—';
    var num = Number(price);
    var pq = parseTradingPairSymbol(symbol || spotTradeState.symbol || '');
    var quoteAsset = (pq.valid && pq.quote) ? pq.quote : (spotTradeState.quoteAsset || 'USDT');
    if (quoteAsset === 'USDT' || quoteAsset === 'FDUSD' || quoteAsset === 'BUSD' || quoteAsset === 'USDC' || quoteAsset === 'TUSD' || quoteAsset === 'DAI') {
        return fmtCoinPrice(num);
    }
    if (quoteAsset === 'BTC') return fmtNum(num, 8) + ' BTC';
    if (quoteAsset === 'ETH') return fmtNum(num, 6) + ' ETH';
    if (quoteAsset === 'BNB') return fmtNum(num, 4) + ' BNB';
    return fmtNum(num, 8) + ' ' + quoteAsset;
}

var _tradeModalChartCache = Object.create(null);
var _tradeModalChartInflight = Object.create(null);
var _tradeModalChartLoadSeq = 0;
var TRADE_MODAL_CHART_TTL_MS = 90000;
function tradeModalChartPlaceholderHtml() {
    return '<svg width="100%" height="100%" viewBox="0 0 400 120" preserveAspectRatio="none"><rect width="400" height="120" fill="#1a1d24"/></svg>';
}

function buildTradeModalChartSvgFromPoints(points) {
    if (!Array.isArray(points) || points.length < 2) return null;
    var dayLow = Math.min.apply(null, points.map(function (p) { return p.l; }));
    var dayHigh = Math.max.apply(null, points.map(function (p) { return p.h; }));
    var dataMin = dayLow;
    var dataMax = dayHigh;
    var range = dataMax - dataMin || 1;
    var w = 400;
    var h = 120;
    var pad = 20;
    var linePoints = points.map(function (p, i) {
        var x = pad + (i / (points.length - 1 || 1)) * (w - 2 * pad);
        var y = pad + (1 - (p.c - dataMin) / range) * (h - 2 * pad);
        return { x: x, y: y };
    });
    var pathD = linePoints.map(function (p, i) { return (i === 0 ? 'M' : 'L') + ' ' + p.x + ' ' + p.y; }).join(' ');
    var first = points[0].c;
    var last = points[points.length - 1].c;
    var stroke = last >= first ? '#0ecb81' : '#f6465d';
    var chartBg = '#1a1d24';
    var gridStroke = 'rgba(255, 255, 255, 0.06)';
    var areaPathD = pathD + ' L ' + linePoints[linePoints.length - 1].x + ' ' + (h - pad) + ' L ' + pad + ' ' + (h - pad) + ' Z';
    var gridLines = [0.25, 0.5, 0.75].map(function (ratio) {
        var y = pad + ratio * (h - 2 * pad);
        return '<line x1="' + pad + '" y1="' + y + '" x2="' + (w - pad) + '" y2="' + y + '" stroke="' + gridStroke + '" stroke-width="1"/>';
    }).join('');
    var svgHtml = '<svg width="100%" height="100%" viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none">' +
        '<defs><linearGradient id="tradeChartGrad" x1="0" y1="0" x2="0" y2="1">' +
        '<stop offset="0" stop-color="' + stroke + '" stop-opacity="0.32"/>' +
        '<stop offset="1" stop-color="' + stroke + '" stop-opacity="0"/></linearGradient></defs>' +
        '<rect width="' + w + '" height="' + h + '" fill="' + chartBg + '"/>' + gridLines +
        '<path d="' + areaPathD + '" fill="url(#tradeChartGrad)"/>' +
        '<path d="' + pathD + '" fill="none" stroke="' + stroke + '" stroke-width="1.75" stroke-linejoin="round" stroke-linecap="round"/>' +
        '</svg>';
    return { svgHtml: svgHtml, dailyLow: dayLow, dailyHigh: dayHigh };
}

function computeYearlyHighLow(klines1d) {
    if (!Array.isArray(klines1d) || !klines1d.length) return { yearlyLow: null, yearlyHigh: null };
    var lows = klines1d.map(function (c) { return Number(c.l); }).filter(function (n) { return Number.isFinite(n); });
    var highs = klines1d.map(function (c) { return Number(c.h); }).filter(function (n) { return Number.isFinite(n); });
    if (!lows.length || !highs.length) return { yearlyLow: null, yearlyHigh: null };
    return { yearlyLow: Math.min.apply(null, lows), yearlyHigh: Math.max.apply(null, highs) };
}

function applyTradeModalHighLow(chartSymbol, dailyLow, dailyHigh, yearlyLow, yearlyHigh) {
    var formatPrice = function (v) { return formatModalPriceForSymbol(v, chartSymbol); };
    var dailyLowEl = document.getElementById('bnTradeDailyLow');
    var dailyHighEl = document.getElementById('bnTradeDailyHigh');
    var yearlyLowEl = document.getElementById('bnTradeYearlyLow');
    var yearlyHighEl = document.getElementById('bnTradeYearlyHigh');
    if (dailyLowEl) dailyLowEl.textContent = dailyLow != null ? formatPrice(dailyLow) : '—';
    if (dailyHighEl) dailyHighEl.textContent = dailyHigh != null ? formatPrice(dailyHigh) : '—';
    if (yearlyLowEl) yearlyLowEl.textContent = yearlyLow != null ? formatPrice(yearlyLow) : '—';
    if (yearlyHighEl) yearlyHighEl.textContent = yearlyHigh != null ? formatPrice(yearlyHigh) : '—';
}

function fetchAndCacheTradeModalChart(chartSymbol) {
    if (_tradeModalChartInflight[chartSymbol]) return _tradeModalChartInflight[chartSymbol];
    var enc = encodeURIComponent(chartSymbol);
    var promise = Promise.all([
        window.apiClient.get('/api/spot/klines?symbol=' + enc + '&interval=5m&limit=288'),
        window.apiClient.get('/api/spot/klines?symbol=' + enc + '&interval=1d&limit=365').catch(function () { return null; })
    ]).then(function (results) {
        var data5m = results[0];
        var klines1d = results[1];
        if (!Array.isArray(data5m) || data5m.length < 2) {
            throw new Error('chart_no_data');
        }
        var points = data5m.map(function (k) {
            return { t: Number(k.t), o: Number(k.o), h: Number(k.h), l: Number(k.l), c: Number(k.c) };
        });
        var built = buildTradeModalChartSvgFromPoints(points);
        if (!built) throw new Error('chart_build_failed');
        var yearly = computeYearlyHighLow(klines1d);
        var entry = {
            ts: Date.now(),
            svgHtml: built.svgHtml,
            dailyLow: built.dailyLow,
            dailyHigh: built.dailyHigh,
            yearlyLow: yearly.yearlyLow,
            yearlyHigh: yearly.yearlyHigh
        };
        _tradeModalChartCache[chartSymbol] = entry;
        return entry;
    }).finally(function () {
        delete _tradeModalChartInflight[chartSymbol];
    });
    _tradeModalChartInflight[chartSymbol] = promise;
    return promise;
}

function prefetchTradeModalChart(symbol) {
    var normalized = normalizeModalSymbol(symbol || '');
    if (normalized.invalid || !normalized.normalized) return;
    var chartSymbol = normalized.normalized;
    if (isTradeModalInvalidChartSymbol(chartSymbol)) return;
    var cached = _tradeModalChartCache[chartSymbol];
    if (cached && (Date.now() - cached.ts) < TRADE_MODAL_CHART_TTL_MS) return;
    fetchAndCacheTradeModalChart(chartSymbol).catch(function () {});
}

/** Alım/Satım modalı: sembole ait son 24 saat grafiği (5m x 288). Geçersiz paritede Binance çağrılmaz. */
async function loadTradeModalChart(symbol) {
    const wrap = document.getElementById('bnTradeChartWrap');
    const container = document.getElementById('bnTradeChart');
    if (!wrap || !container) return;
    const normalized = normalizeModalSymbol(symbol || '');
    if (normalized.invalid || !normalized.normalized || isTradeModalInvalidChartSymbol(normalized.normalized)) {
        container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--ds-text-tertiary);font-size:0.85rem;">Geçersiz parite</div>';
        applyTradeModalHighLow(normalized.normalized || symbol, null, null, null, null);
        return;
    }
    const chartSymbol = normalized.normalized;
    const loadSeq = ++_tradeModalChartLoadSeq;
    container.innerHTML = tradeModalChartPlaceholderHtml();

    const cached = _tradeModalChartCache[chartSymbol];
    if (cached && (Date.now() - cached.ts) < TRADE_MODAL_CHART_TTL_MS) {
        container.innerHTML = cached.svgHtml;
        applyTradeModalHighLow(chartSymbol, cached.dailyLow, cached.dailyHigh, cached.yearlyLow, cached.yearlyHigh);
    }

    try {
        const entry = await fetchAndCacheTradeModalChart(chartSymbol);
        if (loadSeq !== _tradeModalChartLoadSeq) return;
        container.innerHTML = entry.svgHtml;
        applyTradeModalHighLow(chartSymbol, entry.dailyLow, entry.dailyHigh, entry.yearlyLow, entry.yearlyHigh);
    } catch (e) {
        if (loadSeq !== _tradeModalChartLoadSeq) return;
        if (typeof window.__DEBUG_DASH__ !== 'undefined' && window.__DEBUG_DASH__) console.warn('[dashboard] loadTradeModalChart error:', e);
        if (!cached) {
            container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--ds-text-tertiary);font-size:0.85rem;">Grafik yüklenemedi</div>';
        }
    }
}

async function loadExchangeInfo() {
    if (!State.accountId || !spotTradeState.symbol) return;
    
    // Filter out invalid symbols like USDTUSDT, USDCUSDT, FDUSDUSDT
    if (isTradeModalInvalidChartSymbol(spotTradeState.symbol)) {
        console.warn("[dashboard] Invalid symbol for exchange_info:", spotTradeState.symbol);
        return;
    }
    
    try {
        // Binance kaldırıldı – default değerler (sonra temiz kurulum ile eklenecek)
        spotTradeState.stepSize = 0.00000001;
        spotTradeState.tickSize = 0.01;
        spotTradeState.minNotional = 10.0;
    } catch (error) {
        console.error("[dashboard] Error loading exchange info:", error);
    }
}

let feeRatesCache = null;
let feeRatesInflight = null;

async function ensureFeeRates(accountId) {
    if (!accountId) return feeRatesCache;
    if (feeRatesCache && feeRatesCache.accountId === accountId) return Promise.resolve(feeRatesCache);
    
    window.binanceFeeRates = { taker: 0.001, maker: 0.001, taker_pct: 0.1, maker_pct: 0.1 };
    try {
        const data = await window.apiClient.get(`/api/spot/commission?account_id=${accountId}`);
        if (data && (data.maker !== undefined || data.taker !== undefined)) {
            const maker = data.maker != null ? data.maker : 0.001;
            const taker = data.taker != null ? data.taker : 0.001;
            window.binanceFeeRates = {
                maker,
                taker,
                maker_pct: data.maker_pct != null ? data.maker_pct : (maker * 100),
                taker_pct: data.taker_pct != null ? data.taker_pct : (taker * 100)
            };
        }
    } catch (e) {
        // 404 = endpoint yok veya backend güncel değil; varsayılan 0.1% kullan, konsolu kirletme
        if (typeof window.__DEBUG_DASH__ !== 'undefined' && window.__DEBUG_DASH__) {
            console.warn("[dashboard] Commission API failed, using default 0.1%:", e?.message || e);
        }
    }
    feeRatesCache = { accountId, ...window.binanceFeeRates };
    return Promise.resolve(feeRatesCache);
}

async function loadTradeAvailableBalance() {
    if (!State.accountId || !spotTradeState.symbol) return;
    if (!isBinanceTabActive()) return;
    
    try {
        spotTradeState.quoteBalance = 0;
        spotTradeState.baseBalance = 0;
        spotTradeState.quoteAvailable = 0;
        spotTradeState.baseAvailable = 0;
        spotTradeState.availableBalance = 0;
        const totalInput = document.getElementById("bnTradeTotal");
        if (totalInput) totalInput.value = "0.00";
        updateSpotTradeModal();
    } catch (error) {
        console.error("[dashboard] Error loading available balance:", error);
    }
}

// Real-time balance update (only when Binance tab active; modal does not trigger wallet fetch storm)
function startBalanceUpdates() {
    if (!isBinanceTabActive()) return;
    
    window.intervalRegistry.stop('trade.balance');
    loadTradeAvailableBalance();
    
    window.intervalRegistry.start('trade.balance', () => {
        if (!isBinanceTabActive() || !spotTradeState.symbol) return;
        loadTradeAvailableBalance();
    }, 2000, 'trade');
}

function stopBalanceUpdates() {
    // REFACTOR: Use intervalRegistry
    window.intervalRegistry.stop('trade.balance');
}

async function updateModalPrice() {
    if (!spotTradeState.symbol || !State.accountId) return;
    
    try {
        // Use marketStore ONLY - no fallback API calls
        const price = window.marketStore?.getPrice(spotTradeState.symbol);
        if (price !== undefined && price !== null && price > 0) {
            // Update price display
            updatePriceDisplay(price);
            return;
        }
        
        // If marketStore doesn't have price, show "—" or wait
        // NO FALLBACK API CALLS - prevents rate limit
        const priceEl = document.getElementById("bnTradePrice");
        if (priceEl && (!price || price === 0)) {
            // Price not available yet, show placeholder
            const quoteAsset = spotTradeState.quoteAsset || 'USDT';
            if (quoteAsset === 'USDT' || quoteAsset === 'FDUSD' || quoteAsset === 'BUSD' || quoteAsset === 'USDC' || quoteAsset === 'TUSD' || quoteAsset === 'DAI') {
                priceEl.textContent = "$—";
            } else {
                priceEl.textContent = "—";
            }
        }
    } catch (error) {
        console.error("[dashboard] Error updating modal price:", error);
    }
}

// Fiyat gösterimini güncelle (optimize edilmiş, hızlı). Hata/null'da 0.00 gösterme; epsilon ile gereksiz DOM atlanır.
function updatePriceDisplay(price) {
    const priceEl = document.getElementById("bnTradePrice");
    if (!priceEl) return;
    
    const prevPrice = spotTradeState.currentPrice;
    const num = price != null && Number.isFinite(price) ? Number(price) : NaN;
    if (num <= 0 || isNaN(num)) {
        if (prevPrice > 0) priceEl.textContent = (spotTradeState.quoteAsset === 'USDT' || !spotTradeState.quoteAsset) ? '$—' : '—';
        spotTradeState.currentPrice = null;
        return;
    }
    if (prevPrice > 0) {
        const epsAbs = 1e-10;
        const epsRel = 1e-6;
        const diff = Math.abs(num - prevPrice);
        if (diff <= epsAbs || (prevPrice > 0 && diff / prevPrice <= epsRel)) return;
    }
    spotTradeState.currentPrice = num;
    
    priceEl.textContent = formatModalPriceForSymbol(num, spotTradeState.symbol);
    priceEl.classList.remove("price-up", "price-down");
    
    if (prevPrice > 0 && prevPrice !== num) {
        if (num > prevPrice) {
            priceEl.classList.add("price-up");
            setTimeout(() => {
                if (priceEl) priceEl.classList.remove("price-up");
            }, 200);
        } else if (num < prevPrice) {
            priceEl.classList.add("price-down");
            setTimeout(() => {
                if (priceEl) priceEl.classList.remove("price-down");
            }, 200);
        }
    }
    
    const limitPriceInput = document.getElementById("bnLimitPrice");
    if (limitPriceInput && spotTradeState.type === 'LIMIT' && !spotTradeState.limitPriceEdited) {
        limitPriceInput.value = num.toFixed(2);
    }
    
    // Real-time calculation update - update trade summary if needed
    updateTradeSummary();
}

// Modal için tek kaynak: ticker_24h API. Flicker önlemek için handleSpotEngineData ve updateModalPriceChange bu elementi güncellemez.
function setModalPriceChangePlaceholder() {
    const changeEl = document.getElementById("bnTradePriceChange");
    if (changeEl) {
        changeEl.textContent = "—";
        changeEl.style.color = "var(--ds-text-secondary)";
        changeEl.style.fontWeight = "600";
    }
}

// Fiyat değişim yüzdesini güncelle (24h ticker verilerinden) - Sadece trade.modalSpotPrice interval kullanıyor; bu fonksiyon modal % için artık kullanılmıyor (flicker önlemi).
let priceChangeCache = {}; // Cache for price change to prevent flickering

async function updateModalPriceChange() {
    if (!spotTradeState.symbol || !State.accountId) return;
    if (document.getElementById("bnSpotTradeModal")?.style.display === "block") return;
    
    const changeEl = document.getElementById("bnTradePriceChange");
    if (!changeEl) return;
    
    try {
        // REFACTOR: Use marketStore instead of coin-specific ticker request
        // Get price change from marketStore (no separate request needed)
        const mini = window.marketStore?.getMini(spotTradeState.symbol);
        if (mini && mini.changePct !== undefined && mini.changePct != null) {
            const priceChangePercent = mini.changePct;
            
            // Update cache
            priceChangeCache[spotTradeState.symbol] = priceChangePercent;
            
            if (priceChangePercent !== 0) {
                const sign = priceChangePercent > 0 ? '+' : '';
                changeEl.textContent = `${sign}${priceChangePercent.toFixed(2)}%`;
                changeEl.style.color = priceChangePercent > 0 ? '#0ecb81' : '#f6465d';
                changeEl.style.fontWeight = "600";
            } else {
                // If 0, show cached value or empty
                if (priceChangeCache[spotTradeState.symbol] !== undefined) {
                    const cached = priceChangeCache[spotTradeState.symbol];
                    if (cached !== 0) {
                        const sign = cached > 0 ? '+' : '';
                        changeEl.textContent = `${sign}${cached.toFixed(2)}%`;
                        changeEl.style.color = cached > 0 ? "#0ecb81" : "#f6465d";
                        changeEl.style.fontWeight = "600";
                    } else {
                        changeEl.textContent = "0.00%";
                        changeEl.style.color = 'var(--ds-text-secondary)';
                    }
                } else {
                    changeEl.textContent = "0.00%";
                    changeEl.style.color = 'var(--ds-text-secondary)';
                }
            }
            return;
        }
        
        // Fallback: On error, keep cached value if available
        if (priceChangeCache[spotTradeState.symbol] !== undefined) {
            const cached = priceChangeCache[spotTradeState.symbol];
            if (cached !== 0) {
                const sign = cached > 0 ? '+' : '';
                changeEl.textContent = `${sign}${cached.toFixed(2)}%`;
                changeEl.style.color = cached > 0 ? "#0ecb81" : "#f6465d";
                changeEl.style.fontWeight = "600";
            }
        }
    } catch (error) {
        // On error, keep cached value if available - don't clear
        if (priceChangeCache[spotTradeState.symbol] !== undefined) {
            const cached = priceChangeCache[spotTradeState.symbol];
            if (cached !== 0) {
                const sign = cached > 0 ? '+' : '';
                changeEl.textContent = `${sign}${cached.toFixed(2)}%`;
                changeEl.style.color = cached > 0 ? "#0ecb81" : "#f6465d";
                changeEl.style.fontWeight = "600";
            }
        }
    }
}

function startModalPriceUpdates() {
    // REFACTOR: Use intervalRegistry - stop existing first
    window.intervalRegistry.stop('trade.modalPrice');
    window.intervalRegistry.stop('trade.priceChange');
    
    // Update price IMMEDIATELY (don't wait for interval) - ULTRA FAST
    if (spotTradeState.symbol) {
        updateModalPrice();
        updateModalPriceChange();
    }
    
    // REFACTOR: Use intervalRegistry instead of setInterval
    window.intervalRegistry.stop('trade.modalPrice');
    window.intervalRegistry.stop('trade.priceChange');
    
    window.intervalRegistry.start('trade.modalPrice', () => {
        if (spotTradeState.symbol) {
            updateModalPrice();
        }
    }, 500, 'trade');
    
    // Update price change less frequently (every 1s) to avoid flickering
    window.intervalRegistry.start('trade.priceChange', () => {
        if (spotTradeState.symbol) {
            updateModalPriceChange();
        }
    }, 1000, 'trade'); // Update price change every 1 second
}

async function submitSpotTrade() {
    if (!State.accountId || !spotTradeState.symbol) {
        showError("Eksik bilgi");
        return;
    }
    
    const qtyInput = document.getElementById("bnTradeQuantity");
    const totalInput = document.getElementById("bnTradeTotal");
    const limitPriceInput = document.getElementById("bnLimitPrice");
    const errorEl = document.getElementById("bnTradeError");
    const submitBtn = document.getElementById("bnTradeSubmitBtn");
    
    // Get and quantize values
    let quantity = parseFloat(qtyInput.value) || 0;
    let quoteOrderQty = spotTradeState.side === 'BUY' && spotTradeState.type === 'MARKET' ? (parseFloat(totalInput.value) || 0) : null;
    let price = spotTradeState.type === 'LIMIT' ? (parseFloat(limitPriceInput.value) || 0) : null;
    
    // Quantize quantity to step size
    if (quantity > 0) {
        quantity = quantizeQuantity(quantity);
        const decimals = getStepDecimals(spotTradeState.stepSizeStr || spotTradeState.stepSize);
        // Ensure quantity is properly formatted as string to avoid floating point issues
        quantity = parseFloat(quantity.toFixed(decimals));
        qtyInput.value = quantity.toFixed(decimals);
    }
    
    // Quantize price to tick size (for LIMIT orders)
    if (price > 0) {
        price = quantizePrice(price);
        const decimals = getDecimalPlaces(spotTradeState.tickSize);
        // Ensure price is properly formatted
        price = parseFloat(price.toFixed(decimals));
        limitPriceInput.value = price.toFixed(decimals);
    }
    
    // Validate minimum quantity
    if (quantity > 0) {
        const minQty = spotTradeState.minQty || spotTradeState.stepSize || 0;
        if (minQty > 0 && quantity < minQty) {
            if (errorEl) {
                errorEl.textContent = `Minimum miktar: ${minQty}`;
                errorEl.style.display = "block";
            }
            if (submitBtn) submitBtn.disabled = false;
            return;
        }
    }

    // SELL: kullanılabilir bakiyeyi aşma (LOT_SIZE önleme)
    if (spotTradeState.side === 'SELL' && quantity > 0) {
        var maxSell = getMaxSellQuantity();
        if (maxSell > 0) {
            quantity = Math.min(quantity, maxSell);
            quantity = quantizeQuantity(quantity);
            var decSell = getStepDecimals(spotTradeState.stepSizeStr || spotTradeState.stepSize);
            quantity = parseFloat(quantity.toFixed(decSell));
            if (qtyInput) qtyInput.value = quantity.toFixed(decSell);
        }
        if (quantity <= 0) {
            if (errorEl) {
                errorEl.textContent = 'Satılabilir miktar lot adımına uymuyor veya bakiye yetersiz.';
                errorEl.style.display = 'block';
            }
            if (submitBtn) submitBtn.disabled = false;
            return;
        }
    }
    
    // Validation
    if (spotTradeState.type === 'LIMIT' && (!price || price <= 0)) {
        if (errorEl) {
            errorEl.textContent = "Limit fiyat giriniz";
            errorEl.style.display = "block";
        }
        if (submitBtn) submitBtn.disabled = false;
        return;
    }
    
    if (spotTradeState.side === 'BUY' && spotTradeState.type === 'MARKET') {
        // MARKET BUY: quoteOrderQty gerekli
        if (!quoteOrderQty || quoteOrderQty <= 0) {
            if (errorEl) {
                errorEl.textContent = "Tutar giriniz";
                errorEl.style.display = "block";
            }
            if (submitBtn) submitBtn.disabled = false;
            return;
        }
        // Validate minimum notional for MARKET BUY (convert quoteOrderQty to USD)
        if (spotTradeState.minNotional > 0) {
            const quoteAsset = spotTradeState.quoteAsset || 'USDT';
            let quoteOrderQtyUsd = quoteOrderQty;
            
            // Convert quote asset to USD if not USDT/USD stablecoin
            if (quoteAsset !== 'USDT' && quoteAsset !== 'FDUSD' && quoteAsset !== 'BUSD' && 
                quoteAsset !== 'USDC' && quoteAsset !== 'TUSD' && quoteAsset !== 'DAI') {
                // Try to get quote asset price in USD from wallet data
                const quotePriceUsd = window.binanceQuoteAssetPrices?.[quoteAsset] || 0;
                if (quotePriceUsd > 0) {
                    quoteOrderQtyUsd = quoteOrderQty * quotePriceUsd;
                } else {
                    // If price not available, skip validation (Binance will reject if too small)
                    console.warn(`[dashboard] Quote asset ${quoteAsset} USD price not available, skipping minNotional check`);
                }
            }
            
            if (quoteOrderQtyUsd > 0 && quoteOrderQtyUsd < spotTradeState.minNotional) {
                if (errorEl) {
                    errorEl.textContent = `Minimum işlem tutarı: $${spotTradeState.minNotional.toFixed(2)} USD`;
                    errorEl.style.display = "block";
                }
                if (submitBtn) submitBtn.disabled = false;
                return;
            }
        }
    } else if (spotTradeState.type === 'LIMIT') {
        // LIMIT orders (BUY/SELL): quantity ve price gerekli
        if (!quantity || quantity <= 0) {
            if (errorEl) {
                errorEl.textContent = "Miktar giriniz";
                errorEl.style.display = "block";
            }
            if (submitBtn) submitBtn.disabled = false;
            return;
        }
        
        // Validate minimum notional for LIMIT orders
        if (spotTradeState.minNotional > 0 && price > 0) {
            const notional = quantity * price;
            const quoteAsset = spotTradeState.quoteAsset || 'USDT';
            let notionalUsd = notional;
            
            // Convert quote asset to USD if not USDT/USD stablecoin
            if (quoteAsset !== 'USDT' && quoteAsset !== 'FDUSD' && quoteAsset !== 'BUSD' && 
                quoteAsset !== 'USDC' && quoteAsset !== 'TUSD' && quoteAsset !== 'DAI') {
                // Try to get quote asset price in USD from wallet data
                const quotePriceUsd = window.binanceQuoteAssetPrices?.[quoteAsset] || 0;
                if (quotePriceUsd > 0) {
                    notionalUsd = notional * quotePriceUsd;
                } else {
                    // If price not available, skip validation (Binance will reject if too small)
                    console.warn(`[dashboard] Quote asset ${quoteAsset} USD price not available, skipping minNotional check`);
                    notionalUsd = 0; // Skip validation
                }
            }
            
            if (notionalUsd > 0 && notionalUsd < spotTradeState.minNotional) {
                if (errorEl) {
                    errorEl.textContent = `Minimum işlem tutarı: $${spotTradeState.minNotional.toFixed(2)} USD`;
                    errorEl.style.display = "block";
                }
                if (submitBtn) submitBtn.disabled = false;
                return;
            }
        }
    } else {
        // MARKET SELL: quantity gerekli
        if (!quantity || quantity <= 0) {
            if (errorEl) {
                errorEl.textContent = "Miktar giriniz";
                errorEl.style.display = "block";
            }
            if (submitBtn) submitBtn.disabled = false;
            return;
        }
        
        // Validate minimum notional for MARKET SELL (convert to USD)
        if (spotTradeState.minNotional > 0 && spotTradeState.currentPrice > 0) {
            const notional = quantity * spotTradeState.currentPrice;
            const quoteAsset = spotTradeState.quoteAsset || 'USDT';
            let notionalUsd = notional;
            
            // Convert quote asset to USD if not USDT/USD stablecoin
            if (quoteAsset !== 'USDT' && quoteAsset !== 'FDUSD' && quoteAsset !== 'BUSD' && 
                quoteAsset !== 'USDC' && quoteAsset !== 'TUSD' && quoteAsset !== 'DAI') {
                // Try to get quote asset price in USD from wallet data
                const quotePriceUsd = window.binanceQuoteAssetPrices?.[quoteAsset] || 0;
                if (quotePriceUsd > 0) {
                    notionalUsd = notional * quotePriceUsd;
                } else {
                    // If price not available, skip validation (Binance will reject if too small)
                    console.warn(`[dashboard] Quote asset ${quoteAsset} USD price not available, skipping minNotional check`);
                    notionalUsd = 0; // Skip validation
                }
            }
            
            if (notionalUsd > 0 && notionalUsd < spotTradeState.minNotional) {
                if (errorEl) {
                    errorEl.textContent = `Minimum işlem tutarı: $${spotTradeState.minNotional.toFixed(2)} USD`;
                    errorEl.style.display = "block";
                }
                if (submitBtn) submitBtn.disabled = false;
                return;
            }
        }
    }
    
    // Hide error
    if (errorEl) errorEl.style.display = "none";
    
    // Disable button
    if (submitBtn) {
        submitBtn.disabled = true;
        const originalText = submitBtn.textContent;
        submitBtn.textContent = "Gönderiliyor...";
        
        try {
            // Use YENİ Spot Engine for order placement - FLASH HIZLI
            const engine = getSpotEngine(State.accountId);
            
            const orderResult = await engine.placeOrder({
                symbol: spotTradeState.symbol,
                side: spotTradeState.side,
                type: spotTradeState.type,
                quantity: (spotTradeState.type === 'LIMIT' || spotTradeState.side === 'SELL') ? (quantity > 0 ? quantity : null) : null,
                quote_order_qty: (spotTradeState.type === 'MARKET' && spotTradeState.side === 'BUY') ? (quoteOrderQty > 0 ? quoteOrderQty : null) : null,
                price: (spotTradeState.type === 'LIMIT' && price > 0) ? price : null
            }, new AbortController().signal);
            
            // Convert to expected format
            const orderResultPayload = orderResult.order || orderResult;
            const result = (orderResult && orderResult.order && typeof orderResult.order === 'object')
                ? orderResult.order
                : orderResultPayload;
            if (orderResult && orderResult.tx_revision != null) {
                _txHistoryRevision = String(orderResult.tx_revision);
            }
            
            // Success toast: gerçekleşen miktar + tutar
            const successMsg = (typeof formatSpotTradeFillToast === 'function')
                ? formatSpotTradeFillToast(result, spotTradeState.side, spotTradeState.type, spotTradeState.symbol)
                : ((spotTradeState.type === 'MARKET' ? 'Market' : 'Limit') + ' ' + (spotTradeState.side === 'BUY' ? 'Alış' : 'Satış') + ' gerçekleşti');
            
            if (window.Toast) {
                window.Toast.success(successMsg);
            }
            
            // İşlem geçmişi: anında optimistik satır + sunucudan doğrula (retry)
            if (typeof scheduleTxHistoryRefreshAfterTrade === 'function') {
                scheduleTxHistoryRefreshAfterTrade(result, spotTradeState.symbol, spotTradeState.side);
            }
            
            // If LIMIT order, show active orders panel and start tracking
            if (spotTradeState.type === 'LIMIT') {
                setTimeout(function () {
                    loadActiveOrders();
                }, 1000);
            } else {
                // For MARKET orders, also check if there are any pending orders
                setTimeout(() => {
                    loadActiveOrders();
                }, 500);
            }
            
            // Close modal
            closeSpotTradeModal();
            
            if (State.accountId && typeof triggerWalletRefreshForVarliklar === 'function') {
                triggerWalletRefreshForVarliklar(State.accountId, { force: true });
                scheduleWalletRefreshAfterTrade(State.accountId, { delays: [0, 600, 2000, 5000] });
            } else if (State.accountId && window.BinanceAssetsPanel) {
                BinanceAssetsPanel.refresh();
            }
            
        } catch (error) {
            console.error("[SPOT_ENGINE] Order error:", error);
            let errorMsg = error.message || "Bilinmeyen hata";
            
            if (error.data && typeof error.data === 'object') {
                const d = error.data.detail;
                if (d && typeof d === 'object' && typeof d.detail === 'string') {
                    errorMsg = d.detail;
                } else if (typeof d === 'string') {
                    errorMsg = d;
                }
            }
            errorMsg = String(errorMsg);
            
            // Handle specific error cases
            if (errorMsg.includes("Failed to fetch") || errorMsg.includes("NetworkError") || errorMsg.includes("Network request failed")) {
                errorMsg = "Bağlantı hatası. Lütfen internet bağlantınızı kontrol edin ve tekrar deneyin.";
            } else if (errorMsg.includes("timeout") || errorMsg.includes("zaman aşımı")) {
                errorMsg = "İstek zaman aşımına uğradı. Lütfen tekrar deneyin.";
            } else if (error.status === 502) {
                errorMsg = "Binance API hatası. Lütfen tekrar deneyin.";
            } else if (errorMsg.startsWith("HTTP ") && error.status === 400) {
                errorMsg = "Geçersiz emir parametreleri. Lütfen kontrol edin.";
            } else {
                errorMsg = translateErrorToTurkish(errorMsg);
            }
            
            if (errorEl) {
                errorEl.textContent = errorMsg;
                errorEl.style.display = "block";
            }
            if (window.Toast) {
                window.Toast.error(`Emir gönderilemedi: ${errorMsg}`);
            }
        } finally {
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.textContent = originalText;
            }
        }
    }
}

// Active Orders Management
// REFACTOR: activeOrdersInterval removed - use intervalRegistry instead
let activeOrders = [];

function showActiveOrdersPanel() {
    var activeTab = document.querySelector(".dm-tab.is-active");
    if (!activeTab || activeTab.getAttribute("data-tab") !== "binance") return;
    const panel = document.getElementById("bnActiveOrdersPanel");
    if (!panel) return;
    if (!activeOrders || activeOrders.length === 0) {
        panel.style.display = "none";
        return;
    }
    panel.style.display = "block";
}

/** Aktif emir varken panel üstte (varlık strip altı); yoksa her zaman İşlem Geçmişi panelinin hemen altında. */
function updateActiveOrdersPanelPosition() {
    const tab = document.getElementById("tabBinance");
    const panel = document.getElementById("bnActiveOrdersPanel");
    const assetsStrip = tab && tab.querySelector(".binance-assets-strip");
    const txPanel = document.getElementById("transactionHistoryPanel");
    if (!tab || !panel || !assetsStrip) return;
    if (activeOrders.length > 0) {
        if (assetsStrip.nextElementSibling !== panel) {
            tab.insertBefore(panel, assetsStrip.nextElementSibling);
        }
    } else {
        if (txPanel && panel.parentNode === tab) {
            txPanel.after(panel);
        }
    }
}

function hideActiveOrdersPanel() {
    const panel = document.getElementById("bnActiveOrdersPanel");
    if (panel) {
        panel.style.display = "none";
    }
}

// Active orders cache for comparison (prevent unnecessary renders)
let activeOrdersCache = null;
let activeOrdersLastRender = 0;
const ACTIVE_ORDERS_RENDER_THROTTLE = 1000; // Max 1 render per second

async function loadActiveOrders() {
    if (!State.accountId) {
        console.warn("[dashboard] loadActiveOrders: No account ID");
        return;
    }
    if (loadActiveOrders._running) return;
    loadActiveOrders._running = true;
    try {
        const url = `/api/binance/open-orders?account_id=${State.accountId}`;
        if (!window.apiClient || typeof window.apiClient.get !== 'function') throw new Error('apiClient required');
        const data = await window.apiClient.get(url, { timeout: 12000 });
        const newOrders = Array.isArray(data.orders) ? data.orders : [];
        
        // Compare with cache to avoid unnecessary renders
        const ordersChanged = !activeOrdersCache ||
            activeOrdersCache.length !== newOrders.length ||
            JSON.stringify(activeOrdersCache.map(function(o) { return { id: o.orderId || o.order_id, status: o.status, executedQty: o.executedQty }; })) !==
            JSON.stringify(newOrders.map(function(o) { return { id: o.orderId || o.order_id, status: o.status, executedQty: o.executedQty }; }));
        
        // Throttle renders (max once per second)
        const now = Date.now();
        const shouldRender = ordersChanged && (now - activeOrdersLastRender > ACTIVE_ORDERS_RENDER_THROTTLE);
        
        activeOrders = newOrders;
        activeOrdersCache = JSON.parse(JSON.stringify(newOrders));
        
        if (shouldRender) {
            renderActiveOrders();
            activeOrdersLastRender = now;
        } else if (ordersChanged) {
            updateActiveOrdersLivePrices();
        }
        
        if (activeOrders.length === 0) {
            hideActiveOrdersPanel();
            stopActiveOrdersTracking();
        } else {
            showActiveOrdersPanel();
            startActiveOrdersTracking();
            updateActiveOrdersPanelPosition();
        }
    } catch (error) {
        var is429 = error && (error.status === 429 || (error.error_code && String(error.error_code).indexOf('429') !== -1));
        if (is429) {
            var retrySec = (error.retry_after != null) ? Number(error.retry_after) : 10;
            var retryMs = Math.min(60000, Math.max(1000, retrySec * 1000));
            if (window.intervalRegistry) {
                window.intervalRegistry.stop('orders:poll');
                window.intervalRegistry.stop('activeOrders.load');
                if (window.intervalRegistry.timeout && window.intervalRegistry.timeout.cancel) {
                    window.intervalRegistry.timeout.cancel('orders:resume');
                }
                if (window.intervalRegistry.timeout && window.intervalRegistry.timeout.start) {
                    window.intervalRegistry.timeout.start('orders:resume', function () {
                        if (State.accountId && typeof loadActiveOrders === 'function') loadActiveOrders();
                        if (State.accountId && window.intervalRegistry) {
                            window.intervalRegistry.start('orders:poll', function () { loadActiveOrders(); }, ORDERS_POLL_MS, 'binanceTab');
                        }
                    }, retryMs, 'binanceTab');
                }
            }
            return;
        }
        var em = error && (error.message || (typeof error.toString === 'function' ? error.toString() : ''));
        if (!em || (em.indexOf('Failed to fetch') === -1 && em.indexOf('ERR_CONNECTION_REFUSED') === -1)) {
            console.warn("[dashboard] Error loading active orders:", em || error);
        }
        activeOrders = [];
        hideActiveOrdersPanel();
        stopActiveOrdersTracking();
    } finally {
        loadActiveOrders._running = false;
    }
}

function renderActiveOrders() {
    const list = document.getElementById("bnActiveOrdersList");
    if (!list) {
        console.warn("[dashboard] renderActiveOrders: bnActiveOrdersList element not found");
        return;
    }
    
    if (activeOrders.length === 0) {
        list.innerHTML = '';
        hideActiveOrdersPanel();
        return;
    }
    
    // Only log if actually rendering (not throttled)
    // console.log("[dashboard] Rendering", activeOrders.length, "active orders");
    
    list.innerHTML = activeOrders.map((order, index) => {
        const symbol = order.symbol || 'N/A';
        const side = order.side || 'BUY';
        const type = order.type || 'LIMIT';
        const price = parseFloat(order.price || 0);
        const qty = parseFloat(order.origQty || order.quantity || 0);
        const executedQty = parseFloat(order.executedQty || 0);
        const status = order.status || 'NEW';
        const orderId = order.orderId || order.order_id || 'N/A';
        const time = order.time ? new Date(order.time).toLocaleString('tr-TR') : 'N/A';
        
        const sideColor = side === 'BUY' ? '#0ecb81' : '#f6465d';
        const sideText = side === 'BUY' ? 'Alış' : 'Satış';
        const statusText = {
            'NEW': 'Beklemede',
            'PARTIALLY_FILLED': 'Kısmen Gerçekleşti',
            'FILLED': 'Tamamlandı',
            'CANCELED': 'İptal Edildi',
            'EXPIRED': 'Süresi Doldu'
        }[status] || status;
        
        const progress = qty > 0 ? (executedQty / qty * 100) : 0;
        const totalValue = price * qty;
        const executedValue = price * executedQty;
        
        // Extract quote asset from symbol (e.g., ETHBTC -> BTC)
        let quoteAsset = 'USDT';
        const quoteAssets = ['USDT', 'FDUSD', 'BUSD', 'USDC', 'TUSD', 'DAI', 'BTC', 'ETH', 'BNB'];
        for (const qa of quoteAssets) {
            if (symbol.endsWith(qa)) {
                quoteAsset = qa;
                break;
            }
        }
        
        // Format price based on quote asset
        let priceDisplay = 'Market';
        if (price > 0) {
            if (quoteAsset === 'USDT' || quoteAsset === 'FDUSD' || quoteAsset === 'BUSD' || quoteAsset === 'USDC' || quoteAsset === 'TUSD' || quoteAsset === 'DAI') {
                priceDisplay = fmtCoinPrice(price);
            } else if (quoteAsset === 'BTC') {
                priceDisplay = `${fmtNum(price, 8)} BTC`;
            } else if (quoteAsset === 'ETH') {
                priceDisplay = `${fmtNum(price, 6)} ETH`;
            } else if (quoteAsset === 'BNB') {
                priceDisplay = `${fmtNum(price, 4)} BNB`;
            } else {
                priceDisplay = `${fmtNum(price, 8)} ${quoteAsset}`;
            }
        }
        
        // Live price will be updated by updateActiveOrderLivePrice
        const livePriceId = `livePrice_${orderId}_${index}`;
        
        return `
            <div id="activeOrder_${orderId}_${index}" style="border: 1px solid var(--ds-border); border-radius: 8px; padding: 12px; background: var(--ds-bg-secondary);">
                <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 8px;">
                    <div>
                        <strong style="color: ${sideColor};">${symbol}</strong>
                        <span style="margin-left: 8px; color: var(--ds-text-secondary); font-size: 0.85rem;">${sideText} • ${type}</span>
                        <div style="margin-top: 4px; font-size: 0.8rem; color: var(--ds-text-secondary);">
                            Canlı Fiyat: <span id="${livePriceId}" style="color: var(--ds-accent); font-weight: 600;">Yükleniyor...</span>
                        </div>
                    </div>
                    <div style="text-align: right; font-size: 0.85rem; color: var(--ds-text-secondary);">
                        ${statusText}
                    </div>
                </div>
                <div style="display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 8px; margin-bottom: 8px; font-size: 0.9rem;">
                    <div>
                        <div style="color: var(--ds-text-secondary); font-size: 0.8rem;">Emir Fiyatı</div>
                        <div>${priceDisplay}</div>
                    </div>
                    <div>
                        <div style="color: var(--ds-text-secondary); font-size: 0.8rem;">Miktar</div>
                        <div>${fmtNum(qty, 8)}</div>
                    </div>
                    <div>
                        <div style="color: var(--ds-text-secondary); font-size: 0.8rem;">Tutar</div>
                        <div>${fmtUsd(totalValue)}</div>
                    </div>
                    <div>
                        <div style="color: var(--ds-text-secondary); font-size: 0.8rem;">Gerçekleşen</div>
                        <div>${fmtNum(executedQty, 8)}<br><span style="font-size: 0.75rem; color: var(--ds-text-secondary);">${fmtUsd(executedValue)}</span></div>
                    </div>
                </div>
                ${progress > 0 ? `
                    <div style="margin-top: 8px;">
                        <div style="background: var(--ds-bg-tertiary); border-radius: 4px; height: 6px; overflow: hidden;">
                            <div style="background: ${sideColor}; height: 100%; width: ${progress}%; transition: width 0.3s;"></div>
                        </div>
                        <div style="text-align: center; font-size: 0.75rem; color: var(--ds-text-secondary); margin-top: 4px;">
                            %${progress.toFixed(1)} gerçekleşti
                        </div>
                    </div>
                ` : ''}
                <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 12px;">
                    <div style="font-size: 0.75rem; color: var(--ds-text-secondary);">
                        Emir ID: ${orderId} • ${time}
                    </div>
                    ${status === 'NEW' || status === 'PARTIALLY_FILLED' ? `
                        <button 
                            onclick="cancelOrder('${symbol}', ${orderId})" 
                            style="background: rgba(246, 70, 93, 0.15); border: 1px solid #f6465d; color: #f6465d; padding: 0.4rem 0.8rem; border-radius: 4px; cursor: pointer; font-size: 0.85rem; font-weight: 500; transition: all 0.2s;"
                            onmouseover="this.style.background='rgba(246, 70, 93, 0.25)'"
                            onmouseout="this.style.background='rgba(246, 70, 93, 0.15)'"
                        >
                            İptal Et
                        </button>
                    ` : ''}
                </div>
            </div>
        `;
    }).join("");
    
    updateActiveOrdersPanelPosition();
    // Load live prices for all active orders
    // Try to use wallet data first, then fallback to direct fetch
    updateActiveOrdersLivePrices();
}

// Update active orders live prices from wallet data (more efficient)
function updateActiveOrdersLivePricesFromWallet(walletData) {
    if (!walletData || !walletData.assets) return;
    
    const list = document.getElementById("bnActiveOrdersList");
    if (!list) return;
    
    // Create a map of trading pairs to prices from wallet data
    const priceMap = {};
    walletData.assets.forEach(asset => {
        // Don't create invalid symbols like USDTUSDT, USDCUSDT, FDUSDUSDT
        let tradingPair = asset.trading_pair;
        if (!tradingPair && !isStableCoinAsset(asset.asset)) {
            tradingPair = `${asset.asset}USDT`;
        } else if (!tradingPair) {
            tradingPair = null; // Skip stablecoins
        }
        const priceInQuote = asset.price_in_quote || asset.price_usd || asset.usd_price || 0;
        if (priceInQuote > 0) {
            priceMap[tradingPair] = priceInQuote;
        }
    });
    
    // Get missing prices from marketStore (no API fallback)
    const symbols = [...new Set(activeOrders.map(o => o.symbol))];
    // Filter out invalid symbols like USDTUSDT, USDCUSDT, FDUSDUSDT
    const validSymbols = symbols.filter(s => !isTradeModalInvalidChartSymbol(s));
    const missingSymbols = validSymbols.filter(s => !priceMap[s]);
    
    // Fill missing prices from marketStore
    if (missingSymbols.length > 0 && window.marketStore) {
        missingSymbols.forEach(symbol => {
            const price = window.marketStore.getPrice(symbol);
            if (price !== undefined && price !== null && price > 0) {
                priceMap[symbol] = price;
            }
        });
    }
    
    // Update prices (no API fallback)
    updateActiveOrdersPrices(priceMap);
}

// Helper function to update active orders prices
function updateActiveOrdersPrices(priceMap) {
    if (!window.activeOrderPriceCache) {
        window.activeOrderPriceCache = {};
    }
    if (!window.activeOrderPriceLoaded) {
        window.activeOrderPriceLoaded = {};
    }
    
    activeOrders.forEach((order, index) => {
        const symbol = order.symbol;
        const livePrice = priceMap[symbol] || 0;
        const orderId = order.orderId || order.order_id || 'N/A';
        const livePriceId = `livePrice_${orderId}_${index}`;
        const livePriceEl = document.getElementById(livePriceId);
        
        if (!livePriceEl) return;
        
        const cacheKey = `${symbol}_${orderId}`;
        const isLoaded = window.activeOrderPriceLoaded[cacheKey];
        const prevPrice = window.activeOrderPriceCache[cacheKey];
        
        if (livePrice > 0) {
            // Extract quote asset from symbol
            let quoteAsset = 'USDT';
            const quoteAssets = ['USDT', 'FDUSD', 'BUSD', 'USDC', 'TUSD', 'DAI', 'BTC', 'ETH', 'BNB'];
            for (const qa of quoteAssets) {
                if (symbol.endsWith(qa)) {
                    quoteAsset = qa;
                    break;
                }
            }
            
            // Format price based on quote asset
            let priceDisplay = '';
            if (quoteAsset === 'USDT' || quoteAsset === 'FDUSD' || quoteAsset === 'BUSD' || quoteAsset === 'USDC' || quoteAsset === 'TUSD' || quoteAsset === 'DAI') {
                priceDisplay = fmtUsd(livePrice);
            } else if (quoteAsset === 'BTC') {
                priceDisplay = `${fmtNum(livePrice, 8)} BTC`;
            } else if (quoteAsset === 'ETH') {
                priceDisplay = `${fmtNum(livePrice, 6)} ETH`;
            } else if (quoteAsset === 'BNB') {
                priceDisplay = `${fmtNum(livePrice, 4)} BNB`;
            } else {
                priceDisplay = `${fmtNum(livePrice, 8)} ${quoteAsset}`;
            }
            
            // Always update the display to ensure it's visible
            const shouldAnimate = isLoaded && prevPrice !== undefined && prevPrice !== livePrice && prevPrice > 0;
            
            let priceClass = "price-neutral";
            if (shouldAnimate) {
                priceClass = livePrice > prevPrice ? "price-up" : "price-down";
            }
            
            // Update display
            livePriceEl.textContent = priceDisplay;
            livePriceEl.classList.remove("price-up", "price-down", "price-neutral");
            if (priceClass !== "price-neutral") {
                livePriceEl.classList.add(priceClass);
                // Remove animation class after animation completes
                setTimeout(() => {
                    if (livePriceEl) {
                        livePriceEl.classList.remove("price-up", "price-down");
                    }
                }, 500);
            }
            
            // Update cache
            window.activeOrderPriceCache[cacheKey] = livePrice;
            window.activeOrderPriceLoaded[cacheKey] = true;
        }
    });
}

async function updateActiveOrdersLivePrices() {
    if (!State.accountId) return;
    
    // Get current active orders from DOM (in case they've changed)
    const list = document.getElementById("bnActiveOrdersList");
    if (!list) return;
    
    // Extract symbols from DOM
    const livePriceElements = list.querySelectorAll('[id^="livePrice_"]');
    if (livePriceElements.length === 0) return;
    
    // Get unique symbols from active orders
    const symbols = [...new Set(activeOrders.map(o => o.symbol))];
    if (symbols.length === 0) return;
    
    // Use prices from binancePriceCache (already being fetched by startBinancePriceStream)
    // If cache is empty or missing symbols, fetch directly
    const priceMap = {};
    let needFetch = false;
    
    // Check if we have prices in cache from wallet data
    if (window.binancePriceCache && Object.keys(window.binancePriceCache).length > 0) {
        // Try to get prices from cache
        // Note: binancePriceCache stores prices by asset symbol, not trading pair
        // We need to extract base asset from trading pair symbol
        symbols.forEach(symbol => {
            // Extract base asset from symbol (e.g., ETHBTC -> ETH)
            // But we need the price of the trading pair itself, not the base asset
            // So we'll still need to fetch if not in cache
            needFetch = true; // For now, always fetch to be safe
        });
    } else {
        needFetch = true;
    }
    
    // Fetch prices if needed
    if (needFetch) {
        // Filter out invalid symbols like USDTUSDT, USDCUSDT, FDUSDUSDT
        const validSymbols = symbols.filter(s => !isTradeModalInvalidChartSymbol(s));
        
        if (validSymbols.length === 0) return;
        
        try {
            // REFACTOR: Use marketStore instead of /api/binance/prices
            // Get prices from marketStore (no separate request needed)
            const allPrices = window.marketStore?.getAllPrices() || {};
            const priceData = {};
            validSymbols.forEach(symbol => {
                const price = allPrices[symbol];
                if (price !== undefined) {
                    priceData[symbol] = price;
                }
            });
            
            if (Object.keys(priceData).length === 0) {
                return; // No prices available
            }
            
            // Convert to array format for compatibility
            const data = { prices: Object.entries(priceData).map(([symbol, price]) => ({ symbol, price })) };
            const prices = data.prices || [];
            
            // Create price map
            if (Array.isArray(prices)) {
                prices.forEach(p => {
                    if (p.symbol) {
                        const price = parseFloat(p.price) || 0;
                        priceMap[p.symbol] = price;
                    }
                });
            } else if (typeof prices === 'object') {
                // Handle object format
                Object.keys(prices).forEach(symbol => {
                    const price = parseFloat(prices[symbol]) || 0;
                    priceMap[symbol] = price;
                });
            }
        } catch (error) {
            // Don't log connection refused errors repeatedly
            if (!error.message || !error.message.includes('Failed to fetch') || !error.message.includes('ERR_CONNECTION_REFUSED')) {
                console.error("[dashboard] Error fetching prices for active orders:", error);
            }
            return;
        }
    }
    
    // Initialize cache if not exists
    if (!window.activeOrderPriceCache) {
        window.activeOrderPriceCache = {};
    }
    if (!window.activeOrderPriceLoaded) {
        window.activeOrderPriceLoaded = {};
    }
    
    // Update each order's live price
    try {
        activeOrders.forEach((order, index) => {
            const symbol = order.symbol;
            const livePrice = priceMap[symbol] || 0;
            const orderId = order.orderId || order.order_id || 'N/A';
            const livePriceId = `livePrice_${orderId}_${index}`;
            const livePriceEl = document.getElementById(livePriceId);
            
            if (!livePriceEl) {
                // Element not found - might have been removed
                return;
            }
            
            const cacheKey = `${symbol}_${orderId}`;
            const isLoaded = window.activeOrderPriceLoaded[cacheKey];
            
            if (livePrice > 0) {
                // Price found - update it
                const prevPrice = window.activeOrderPriceCache[cacheKey];
                
                // Extract quote asset from symbol
                let quoteAsset = 'USDT';
                const quoteAssets = ['USDT', 'FDUSD', 'BUSD', 'USDC', 'TUSD', 'DAI', 'BTC', 'ETH', 'BNB'];
                for (const qa of quoteAssets) {
                    if (symbol.endsWith(qa)) {
                        quoteAsset = qa;
                        break;
                    }
                }
                
                // Format price based on quote asset
                let priceDisplay = '';
                if (quoteAsset === 'USDT' || quoteAsset === 'FDUSD' || quoteAsset === 'BUSD' || quoteAsset === 'USDC' || quoteAsset === 'TUSD' || quoteAsset === 'DAI') {
                    priceDisplay = fmtUsd(livePrice);
                } else if (quoteAsset === 'BTC') {
                    priceDisplay = `${fmtNum(livePrice, 8)} BTC`;
                } else if (quoteAsset === 'ETH') {
                    priceDisplay = `${fmtNum(livePrice, 6)} ETH`;
                } else if (quoteAsset === 'BNB') {
                    priceDisplay = `${fmtNum(livePrice, 4)} BNB`;
                } else {
                    priceDisplay = `${fmtNum(livePrice, 8)} ${quoteAsset}`;
                }
                
                // Always update the display to ensure it's visible
                // But only add animation if price actually changed
                const shouldAnimate = isLoaded && prevPrice !== undefined && prevPrice !== livePrice && prevPrice > 0;
                
                let priceClass = "price-neutral";
                if (shouldAnimate) {
                    priceClass = livePrice > prevPrice ? "price-up" : "price-down";
                }
                
                // Update display
                livePriceEl.textContent = priceDisplay;
                livePriceEl.classList.remove("price-up", "price-down", "price-neutral");
                if (priceClass !== "price-neutral") {
                    livePriceEl.classList.add(priceClass);
                    // Remove animation class after animation completes
                    setTimeout(() => {
                        if (livePriceEl) {
                            livePriceEl.classList.remove("price-up", "price-down");
                        }
                    }, 500);
                }
                
                // Update cache
                window.activeOrderPriceCache[cacheKey] = livePrice;
                window.activeOrderPriceLoaded[cacheKey] = true;
            } else {
                // Price not found or 0
                // Only show "Yükleniyor..." if this is the first time (not loaded yet)
                if (!isLoaded) {
                    // Keep "Yükleniyor..." only if not loaded yet
                    if (livePriceEl.textContent === "Yükleniyor..." || !livePriceEl.textContent.trim()) {
                        // Already showing loading, don't change
                    } else {
                        // This shouldn't happen, but just in case
                        livePriceEl.textContent = "Yükleniyor...";
                    }
                } else {
                    // Already loaded before, but now price is 0 - might be temporary error
                    // Don't change the display, keep last known price
                    // Or show error only once
                    if (!window.activeOrderPriceErrorShown) {
                        window.activeOrderPriceErrorShown = {};
                    }
                    if (!window.activeOrderPriceErrorShown[cacheKey]) {
                        console.warn(`[dashboard] Price for ${symbol} is 0 or not found, keeping last known price`);
                        window.activeOrderPriceErrorShown[cacheKey] = true;
                    }
                }
            }
        });
    } catch (error) {
        console.error("[dashboard] Error updating active orders live prices:", error);
    }
}

function startActiveOrdersTracking() {
    // Sadece canlı fiyat güncellemesi; liste yüklemesi orders:poll ile startBinanceTabPolling'de (tek nokta)
    window.intervalRegistry.stop('activeOrders.prices');
    window.intervalRegistry.start('activeOrders.prices', function () {
        updateActiveOrdersLivePrices();
    }, 2000, 'binanceTab');
}

function stopActiveOrdersTracking() {
    window.intervalRegistry.stop('activeOrders.prices');
    window.intervalRegistry.stop('activeOrders.load');
}

async function cancelOrder(symbol, orderId) {
    if (!State.accountId) {
        if (window.Toast) window.Toast.error("Hesap bulunamadı");
        return;
    }
    
    if (!confirm("Bu emri iptal etmek istediğinizden emin misiniz?\n\nParite: " + symbol + "\nEmir ID: " + orderId)) {
        return;
    }
    
    try {
        const url = "/api/binance/order?account_id=" + encodeURIComponent(State.accountId) + "&symbol=" + encodeURIComponent(symbol) + "&order_id=" + encodeURIComponent(orderId);
        var result = await window.apiClient.delete(url, { timeout: 15000 });
        if (window.Toast) window.Toast.success(result.message || "Emir iptal edildi");
        await loadActiveOrders();
        if (typeof loadWallet === "function") loadWallet(true);
    } catch (error) {
        console.error("[dashboard] Cancel order error:", error);
        var errorMsg = typeof translateErrorToTurkish === "function" ? translateErrorToTurkish(error.message || "Bilinmeyen hata") : (error.message || "Bilinmeyen hata");
        if (window.Toast) window.Toast.error("Emir iptal edilemedi: " + errorMsg);
    }
}

// Make cancelOrder global
window.cancelOrder = cancelOrder;

// Coin List Tab
let coinListData = []; // All coins from API
let coinListFiltered = []; // Filtered coins for display
let coinListTop10 = []; // Top 10 coins (stable coins excluded) - for price updates
let coinListAllCoins = []; // All coins for search (includes all from Binance)
// Use window.coinListPriceCache (Binance mantığı ile aynı)
// Initialize in function, not at module level (to avoid window undefined errors)
let coinListUpdateInterval = null;
let coinListSortBy = 'marketCap'; // 'marketCap', 'volume', 'change'

function isStableCoinAsset(asset) {
    var stableCoins = Array.isArray(STABLE_COINS)
        ? STABLE_COINS
        : ['USDT', 'USDC', 'FDUSD', 'BUSD', 'TUSD', 'DAI', 'USDP', 'USDD'];
    return stableCoins.indexOf((asset || '').toUpperCase()) >= 0;
}

function bindCoinList() {
    const searchInput = document.getElementById("coinListSearch");
    const sortSelect = document.getElementById("coinListSort");
    const searchResults = document.getElementById("coinListSearchResults");
    
    if (searchInput) {
        let searchTimeout = null;
        searchInput.addEventListener("input", (e) => {
            clearTimeout(searchTimeout);
            const query = e.target.value.trim();
            
            // Show search results dropdown if query exists
            if (query.length > 0) {
                searchTimeout = setTimeout(() => {
                    showCoinSearchResults(query);
                }, 200);
            } else {
                // Hide dropdown and show top 10
                if (searchResults) searchResults.style.display = 'none';
                coinListFiltered = [...coinListTop10];
                renderCoinList(true);
            }
        });
        
        // Hide dropdown when clicking outside
        document.addEventListener('click', (e) => {
            if (searchResults && !searchInput.contains(e.target) && !searchResults.contains(e.target)) {
                searchResults.style.display = 'none';
            }
        });
        
        // Handle Enter key to select first result
        searchInput.addEventListener("keydown", (e) => {
            if (e.key === 'Enter' && searchResults && searchResults.style.display !== 'none') {
                const firstResult = searchResults.querySelector('.search-result-item');
                if (firstResult) {
                    firstResult.click();
                }
            }
        });
    }
    
    if (sortSelect) {
        sortSelect.addEventListener("change", (e) => {
            coinListSortBy = e.target.value;
            applyCoinListSort();
            updateCoinListTitle();
        });
    }
}

function applyCoinListSort() {
    const searchInput = document.getElementById("coinListSearch");
    const hasSearch = searchInput && searchInput.value.trim();
    
    // If searching, sort search results
    if (hasSearch) {
        if (coinListFiltered.length === 0) return;
        let sortedData = [...coinListFiltered];
        
        // Find and separate USDT/USD - always put first
        const usdtUsdIndex = sortedData.findIndex(coin => {
            const symbol = (coin.symbol || '').toUpperCase();
            return symbol === 'USDTUSDT' || symbol === 'USDTUSD' || symbol === 'USDT/USD';
        });
        const usdtUsdCoin = usdtUsdIndex >= 0 ? sortedData.splice(usdtUsdIndex, 1)[0] : { symbol: 'USDTUSD', baseAsset: 'USDT', price: 1, priceChangePercent: 0, volume: 0, quoteVolume: 0, marketCapApprox: 0 };
        
        switch (coinListSortBy) {
            case 'marketCap':
                sortedData.sort((a, b) => (b.marketCapApprox || 0) - (a.marketCapApprox || 0));
                break;
            case 'volume':
                sortedData.sort((a, b) => (b.quoteVolume || 0) - (a.quoteVolume || 0));
                break;
            case 'change':
                sortedData.sort((a, b) => (b.priceChangePercent || 0) - (a.priceChangePercent || 0));
                break;
            default:
                sortedData.sort((a, b) => (b.marketCapApprox || 0) - (a.marketCapApprox || 0));
        }
        
        sortedData.unshift(usdtUsdCoin);
        coinListFiltered = sortedData;
        renderCoinList();
    } else {
        // Sort top 10
        if (coinListTop10.length === 0) return;
        let sortedData = [...coinListTop10];
        
        // Find and separate USDT/USD - always put first
        const usdtUsdIndex = sortedData.findIndex(coin => {
            const symbol = (coin.symbol || '').toUpperCase();
            return symbol === 'USDTUSDT' || symbol === 'USDTUSD' || symbol === 'USDT/USD';
        });
        const usdtUsdCoin = usdtUsdIndex >= 0 ? sortedData.splice(usdtUsdIndex, 1)[0] : { symbol: 'USDTUSD', baseAsset: 'USDT', price: 1, priceChangePercent: 0, volume: 0, quoteVolume: 0, marketCapApprox: 0 };
        
        switch (coinListSortBy) {
            case 'marketCap':
                sortedData.sort((a, b) => (b.marketCapApprox || 0) - (a.marketCapApprox || 0));
                break;
            case 'volume':
                sortedData.sort((a, b) => (b.quoteVolume || 0) - (a.quoteVolume || 0));
                break;
            case 'change':
                sortedData.sort((a, b) => (b.priceChangePercent || 0) - (a.priceChangePercent || 0));
                break;
            default:
                sortedData.sort((a, b) => (b.marketCapApprox || 0) - (a.marketCapApprox || 0));
        }
        
        sortedData.unshift(usdtUsdCoin);
        coinListTop10 = sortedData;
        coinListData = sortedData;
        coinListFiltered = sortedData;
        renderCoinList();
    }
}

function updateCoinListTitle() {
    const titleEl = document.getElementById("coinListTitle");
    if (!titleEl) return;
    
    const titles = {
        'marketCap': 'En İyi 100 Coin (Piyasa Değerine Göre)',
        'volume': 'En İyi 100 Coin (Hacime Göre)',
        'change': 'En İyi 100 Coin (24s Değişime Göre)'
    };
    
    titleEl.textContent = titles[coinListSortBy] || titles['marketCap'];
}

// Liste sekmesi için WebSocket stream (Binance sekmesi ile aynı hız)
let coinListStreamActive = false;
let coinListSymbols = [];

function startCoinListUpdates() {
    window.intervalRegistry.stop('coinList.update');
    if (window.coinListMarketStoreSubscription) {
        window.coinListMarketStoreSubscription();
        window.coinListMarketStoreSubscription = null;
    }
    // Coin list prices: tab.binance.prices 1s interval (shared with varlıklar)
}

function stopCoinListUpdates() {
    stopCoinListWebSocketStream();
}

// DEPRECATED: startCoinListWebSocketStream - use startCoinListUpdates instead
function startCoinListWebSocketStream() {
    // REFACTOR: This function is deprecated - use startCoinListUpdates() instead
    console.warn("[dashboard] startCoinListWebSocketStream is deprecated, use startCoinListUpdates() instead");
    startCoinListUpdates();
}

// Liste sekmesi stream'ini durdur
function stopCoinListWebSocketStream() {
    if (coinListStreamActive) {
        coinListStreamActive = false;
        coinListSymbols = [];
    }
    window.intervalRegistry.stop('coinList.update');
    if (window.coinListMarketStoreSubscription) {
        window.coinListMarketStoreSubscription();
        window.coinListMarketStoreSubscription = null;
    }
}

async function loadCoinList(updateOnly = false) {
    const body = document.getElementById("coinListBody");
    if (!body) return;
    
    // TEK KAYNAK: marketStore (dataHub kullanılmaz)
    let miniTickers = [];
    try {
        if (window.marketStore && typeof window.marketStore.getAllMini === 'function') {
            miniTickers = window.marketStore.getAllMini() || [];
            console.log("[dashboard] loadCoinList: marketStore.getAllMini() returned", miniTickers.length, "coins");
        } else {
            console.log("[dashboard] loadCoinList: marketStore not available or getAllMini not a function");
        }
    } catch (error) {
        console.warn("[dashboard] loadCoinList: Error getting mini tickers from marketStore:", error);
    }
    
    if (miniTickers.length > 0) {
        const newCoinListData = miniTickers.map(coin => {
            // Extract base asset from symbol (e.g., BTCUSDT -> BTC)
            const symbol = coin.symbol || '';
            const baseAsset = symbol.replace(/USDT$|BTC$|ETH$|BNB$|FDUSD$|BUSD$|TUSD$|DAI$/i, '') || symbol;
            
            return {
                symbol: symbol,
                baseAsset: baseAsset,
                price: coin.last || 0,
                priceChangePercent: coin.changePct || 0,
                volume: coin.volume || 0,
                quoteVolume: coin.quoteVolume || 0,
                marketCapApprox: coin.marketCap || 0
            };
        });
        
        // Store all coins for search
        coinListAllCoins = [...newCoinListData];
        
        // Find USDT/USD and separate it
        const usdtUsdCoin = newCoinListData.find(coin => {
            const symbol = (coin.symbol || '').toUpperCase();
            return symbol === 'USDTUSDT' || symbol === 'USDTUSD' || symbol === 'USDT/USD';
        });
        
        // Filter out stable coins and get top 10
        const nonStableCoins = newCoinListData.filter(coin => {
            const symbol = (coin.symbol || '').toUpperCase();
            // Exclude USDT/USD from stable coin filter (we want to show it)
            if (symbol === 'USDTUSDT' || symbol === 'USDTUSD' || symbol === 'USDT/USD') {
                return false; // Don't include in nonStableCoins, we'll add it separately
            }
            const baseAsset = coin.baseAsset || coin.symbol?.replace(/USDT$|BTC$|ETH$|BNB$|FDUSD$|BUSD$|TUSD$|DAI$/i, '') || '';
            return !isStableCoinAsset(baseAsset);
        });
        
        // Apply sorting to get top 10
        let sortedForTop10 = [...nonStableCoins];
        sortedForTop10.sort((a, b) => (b.marketCapApprox || 0) - (a.marketCapApprox || 0));
        sortedForTop10 = sortedForTop10.slice(0, 10);
        
        // Always put USDT/USD first - use existing or synthetic
        const usdtUsdRow = usdtUsdCoin || {
            symbol: 'USDTUSD',
            baseAsset: 'USDT',
            price: 1,
            priceChangePercent: 0,
            volume: 0,
            quoteVolume: 0,
            marketCapApprox: 0
        };
        coinListTop10 = [usdtUsdRow, ...sortedForTop10];
        
        // Update price cache for blink effects (Binance mantığı)
        if (coinListTop10.length > 0 && updateOnly) {
            // Cache'i güncelle (Binance mantığı - sadece price)
            coinListTop10.forEach(coin => {
                const symbol = coin.symbol;
                const oldCoin = coinListTop10.find(c => c.symbol === symbol);
                if (oldCoin && symbol && typeof window !== 'undefined' && window.coinListPriceCache && window.coinListPriceCache[symbol] === undefined) {
                    window.coinListPriceCache[symbol] = oldCoin.price;
                }
            });
            updateCoinListPrices(coinListTop10);
            return;
        }
        
        // First load - initialize cache (Binance mantığı)
        if (typeof window !== 'undefined') {
            if (!window.coinListPriceCache) {
                window.coinListPriceCache = {};
            }
            coinListTop10.forEach(coin => {
                if (coin.symbol) {
                    window.coinListPriceCache[coin.symbol] = coin.price;
                }
            });
        }
        
        // Set filtered coins to top 10 (default display)
        coinListFiltered = [...coinListTop10];
        coinListData = [...coinListTop10]; // For sorting/filtering operations
        
        applyCoinListSort();
        renderCoinList();
        return;
    }
    
    // Fallback: Fetch from API if marketStore not ready
    if (!updateOnly) {
        body.innerHTML = '<tr><td colspan="8" style="text-align: center; padding: 2rem; color: var(--ds-text-secondary);">Yükleniyor...</td></tr>';
    }
    
    try {
        // REFACTOR: Use apiClient instead of fetch
        // Try /api/data/coin-list first (cached), fallback to /api/binance/coin-list if empty
        let data = null;
        let rawCoins = [];
        
        try {
            data = await window.apiClient.get("/api/data/coin-list");
            console.log("[dashboard] loadCoinList: /api/data/coin-list response, coins count:", data.coins?.length || 0);
            rawCoins = data.coins || [];
        } catch (error) {
            console.warn("[dashboard] loadCoinList: /api/data/coin-list failed:", error);
        }
        
        // Use marketStore or show empty if /api/data/coin-list fails
        // This prevents rate limit issues
        if (!rawCoins || rawCoins.length === 0) {
            // Try to get from marketStore mini tickers
            if (window.marketStore && typeof window.marketStore.getAllMini === 'function') {
                const miniTickers = window.marketStore.getAllMini() || [];
                if (miniTickers.length > 0) {
                    rawCoins = miniTickers.slice(0, 100).map(coin => ({
                        symbol: coin.symbol || '',
                        baseAsset: (coin.symbol || '').replace(/USDT$|BTC$|ETH$|BNB$|FDUSD$|BUSD$|TUSD$|DAI$/i, ''),
                        price: coin.last || 0,
                        priceChangePercent: coin.changePct || 0,
                        volume: coin.volume || 0,
                        quoteVolume: coin.quoteVolume || 0,
                        marketCapApprox: coin.marketCap || 0
                    }));
                    console.log("[dashboard] loadCoinList: Using marketStore data, coins count:", rawCoins.length);
                }
            }
            
            // If still no coins, show empty state
            if (!rawCoins || rawCoins.length === 0) {
                if (body && !updateOnly) {
                    body.innerHTML = '<tr><td colspan="8" style="text-align: center; padding: 2rem; color: var(--ds-text-secondary);">Coin listesi yükleniyor... (WebSocket bağlantısı bekleniyor)</td></tr>';
                }
                console.warn("[dashboard] loadCoinList: No coins available from /api/data/coin-list or marketStore");
                return;
            }
        }
        
        if (rawCoins.length === 0) {
            console.warn("[dashboard] loadCoinList: No coins in API response");
            if (body && !updateOnly) {
                body.innerHTML = '<tr><td colspan="8" style="text-align: center; padding: 2rem; color: var(--ds-text-secondary);">Coin bulunamadı. Lütfen sayfayı yenileyin.</td></tr>';
            }
            return;
        }
        
        const newCoinListData = rawCoins.map(coin => {
            const symbol = coin.symbol || '';
            const baseAsset = coin.baseAsset || symbol.replace(/USDT$|BTC$|ETH$|BNB$|FDUSD$|BUSD$|TUSD$|DAI$/i, '') || symbol;
            const price = coin.price || parseFloat(coin.lastPrice) || 0;
            const priceChangePercent = coin.priceChangePercent || parseFloat(coin.priceChangePercent) || 0;
            const volume = coin.volume || parseFloat(coin.volume) || 0;
            const quoteVolume = coin.quoteVolume || parseFloat(coin.quoteVolume) || 0;
            const marketCapApprox = coin.marketCapApprox || coin.marketCap || 0;
            
            return {
                symbol: symbol,
                baseAsset: baseAsset,
                price: price,
                priceChangePercent: priceChangePercent,
                volume: volume,
                quoteVolume: quoteVolume,
                marketCapApprox: marketCapApprox
            };
        });
        
        // Update price cache for blink effects (Binance mantığı)
        if (coinListData.length > 0 && updateOnly) {
            // Cache'i güncelle (Binance mantığı - sadece price)
            if (typeof window !== 'undefined' && window.coinListPriceCache) {
                newCoinListData.forEach(coin => {
                    const symbol = coin.symbol;
                    const oldCoin = coinListData.find(c => c.symbol === symbol);
                    if (oldCoin && symbol && window.coinListPriceCache[symbol] === undefined) {
                        window.coinListPriceCache[symbol] = oldCoin.price;
                    }
                });
            }
            
            // DOM PATCHING: Update prices with blink effects (Binance mantığı)
            updateCoinListPrices(newCoinListData);
            return; // Exit early, don't re-render
        } else {
            // First load - initialize cache (Binance mantığı)
            if (typeof window !== 'undefined') {
                if (!window.coinListPriceCache) {
                    window.coinListPriceCache = {};
                }
                newCoinListData.forEach(coin => {
                    if (coin.symbol) {
                        window.coinListPriceCache[coin.symbol] = coin.price;
                    }
                });
            }
        }
        
        coinListData = newCoinListData;
        
        console.log("[dashboard] loadCoinList: Processed", newCoinListData.length, "coins");
        
        // Hide banner on successful load (if error was resolved)
        if (binanceApiErrorState.isError) {
            const errorAge = Date.now() - (binanceApiErrorState.lastErrorTime || 0);
            if (errorAge > 30000) {
                hideBinanceApiBanner();
            }
        }
        
        // Store all coins for search
        coinListAllCoins = [...newCoinListData];
        
        // Find USDT/USD and separate it
        const usdtUsdCoin = newCoinListData.find(coin => {
            const symbol = (coin.symbol || '').toUpperCase();
            return symbol === 'USDTUSDT' || symbol === 'USDTUSD' || symbol === 'USDT/USD';
        });
        
        // Filter out stable coins and get top 10
        const nonStableCoins = newCoinListData.filter(coin => {
            const symbol = (coin.symbol || '').toUpperCase();
            // Exclude USDT/USD from stable coin filter (we want to show it)
            if (symbol === 'USDTUSDT' || symbol === 'USDTUSD' || symbol === 'USDT/USD') {
                return false; // Don't include in nonStableCoins, we'll add it separately
            }
            const baseAsset = coin.baseAsset || coin.symbol?.replace(/USDT$|BTC$|ETH$|BNB$|FDUSD$|BUSD$|TUSD$|DAI$/i, '') || '';
            return !isStableCoinAsset(baseAsset);
        });
        
        // Apply sorting to get top 10
        let sortedForTop10 = [...nonStableCoins];
        sortedForTop10.sort((a, b) => (b.marketCapApprox || 0) - (a.marketCapApprox || 0));
        sortedForTop10 = sortedForTop10.slice(0, 10);
        
        // Always put USDT/USD first - use existing or synthetic
        const usdtUsdRow = usdtUsdCoin || {
            symbol: 'USDTUSD',
            baseAsset: 'USDT',
            price: 1,
            priceChangePercent: 0,
            volume: 0,
            quoteVolume: 0,
            marketCapApprox: 0
        };
        coinListTop10 = [usdtUsdRow, ...sortedForTop10];
        
        // Set filtered coins to top 10 (default display)
        coinListFiltered = [...coinListTop10];
        coinListData = [...coinListTop10]; // For sorting/filtering operations
        
        console.log("[dashboard] loadCoinList: Top 10 coins (stable excluded):", coinListTop10.length);
        console.log("[dashboard] loadCoinList: All coins for search:", coinListAllCoins.length);
        
        // Initialize coinListPriceCache before rendering
        if (typeof window !== 'undefined') {
            if (!window.coinListPriceCache) {
                window.coinListPriceCache = {};
            }
        }
        
        renderCoinList(true); // Always enable blink effects
        console.log("[dashboard] loadCoinList: renderCoinList called");
    } catch (error) {
        console.error("[dashboard] Error loading coin list:", error);
        if (body && !updateOnly) {
            body.innerHTML = `<tr><td colspan="8" style="text-align: center; padding: 2rem; color: var(--ds-text-error);">Hata: ${error.message}</td></tr>`;
        }
    }
}

function updateCoinListPricesFromMarketStore() {
    if (window.BinanceUI && document.getElementById("tabBinance")?.classList.contains("is-active")) {
        return;
    }
    if (!coinListTop10 || coinListTop10.length === 0) return;
    if (typeof window !== 'undefined' && !window.coinListPriceCache) window.coinListPriceCache = {};
    const binanceTab = document.getElementById("tabBinance");
    if (!binanceTab || !binanceTab.classList.contains("is-active")) return;
    if (window.__DEBUG_BINANCE__) console.count("coinListPriceUpdate");

    const allPrices = window.marketStore?.getAllPrices() || {};
    const allMini = window.marketStore?.getAllMini() || [];
    const miniMap = new Map((allMini || []).map(m => [m.symbol, m]));

    const newCoinListData = coinListTop10.map(coin => {
        const rawSymbol = coin.symbol || '';
        const storeKey = normalizeUiSymbolToStoreKey(rawSymbol);
        let price = allPrices[storeKey];
        if (price == null) {
            const mini = miniMap.get(storeKey);
            price = mini?.last;
            if (price == null) price = window.marketStore?.getPrice(storeKey);
        }
        const mini = miniMap.get(storeKey);
        const resolvedPrice = (price != null && price > 0) ? price : (coin.price != null && coin.price > 0 ? coin.price : null);
        return {
            ...coin,
            rawSymbol,
            storeKey,
            price: resolvedPrice,
            priceChangePercent: mini?.changePct !== undefined ? mini.changePct : coin.priceChangePercent,
            volume: mini?.volume !== undefined ? mini.volume : coin.volume,
            quoteVolume: mini?.quoteVolume !== undefined ? mini.quoteVolume : coin.quoteVolume,
            marketCapApprox: mini?.marketCap !== undefined ? mini.marketCap : coin.marketCapApprox
        };
    });

    updateCoinListPricesAndDetails(newCoinListData);
}

// DOM PATCHING: Update coin prices AND details with blink effects - REAL-TIME UPDATES
function updateCoinListPricesAndDetails(newCoinListData) {
    // Initialize cache if not exists (Binance mantığı)
    if (typeof window === 'undefined' || !window.coinListPriceCache) {
        if (typeof window !== 'undefined') {
            window.coinListPriceCache = {};
        } else {
            return; // Window not available
        }
    }
    
    let hasUpdate = false;
    
    newCoinListData.forEach(coin => {
        const rawSymbol = coin.rawSymbol || coin.symbol || '';
        const storeKey = coin.storeKey || normalizeUiSymbolToStoreKey(rawSymbol);
        
        // Update PRICE
        const priceEl = document.getElementById(`coinPrice_${storeKey}`);
        if (priceEl) {
            const prevPrice = window.coinListPriceCache[storeKey];
            const newPrice = coin.price;
            const hasPrice = newPrice != null && Number.isFinite(newPrice) && newPrice > 0;
            const priceChanged = hasPrice && prevPrice !== undefined && Math.abs(prevPrice - newPrice) > 0.0001;
            if (priceChanged) hasUpdate = true;

            priceEl.textContent = hasPrice ? fmtUsd(newPrice) : '…';
            let priceClass = "price-neutral";
            if (priceChanged) priceClass = newPrice > prevPrice ? "price-up" : "price-down";
            priceEl.classList.remove("price-up", "price-down", "price-neutral");
            priceEl.classList.add(priceClass);
            if (priceChanged) {
                setTimeout(() => { if (priceEl) priceEl.classList.remove("price-up", "price-down"); }, 500);
            }
            if (hasPrice) window.coinListPriceCache[storeKey] = newPrice;
        }
        
        // Update 24H CHANGE - with blink effect (same as assets table)
        const changeEl = document.getElementById(`coinChange_${storeKey}`);
        if (changeEl) {
            const priceChange = coin.priceChangePercent || 0;
            const prevChange = window.coinListChangeCache?.[storeKey];
            
            // Check if change value changed (for blink effect)
            const changeChanged = prevChange !== undefined && Math.abs(prevChange - priceChange) > 0.01;
            
            const priceChangeColor = priceChange > 0 ? "#0ecb81" : priceChange < 0 ? "#f6465d" : "var(--ds-text-primary)";
            changeEl.textContent = `${priceChange > 0 ? '+' : ''}${priceChange.toFixed(2)}%`;
            changeEl.style.color = priceChangeColor;
            
            // Apply blink class if change value changed (same as assets table)
            if (changeChanged) {
                const changeClass = priceChange > prevChange ? "price-up" : "price-down";
                changeEl.classList.remove("price-up", "price-down");
                changeEl.classList.add(changeClass);
                
                // Remove animation class after animation completes
                setTimeout(() => {
                    if (changeEl) {
                        changeEl.classList.remove("price-up", "price-down");
                    }
                }, 500);
            }
            
            // Update cache
            if (!window.coinListChangeCache) {
                window.coinListChangeCache = {};
            }
            window.coinListChangeCache[storeKey] = priceChange;
        }
        
        // Update VOLUME
        const volumeEl = document.getElementById(`coinVol_${storeKey}`);
        if (volumeEl) {
            const volume = coin.volume || 0;
            const formatVolume = (vol) => {
                if (vol >= 1e9) return `${(vol / 1e9).toFixed(2)}B`;
                if (vol >= 1e6) return `${(vol / 1e6).toFixed(2)}M`;
                if (vol >= 1e3) return `${(vol / 1e3).toFixed(2)}K`;
                return vol.toFixed(2);
            };
            volumeEl.textContent = '$' + formatVolume(coin.quoteVolume || volume);
        }
        
        // Update MARKET CAP
        const marketCapEl = document.getElementById(`coinMcap_${storeKey}`);
        if (marketCapEl) {
            const marketCap = coin.marketCapApprox || 0;
            const formatVolume = (vol) => {
                if (vol >= 1e9) return `${(vol / 1e9).toFixed(2)}B`;
                if (vol >= 1e6) return `${(vol / 1e6).toFixed(2)}M`;
                if (vol >= 1e3) return `${(vol / 1e3).toFixed(2)}K`;
                return vol.toFixed(2);
            };
            marketCapEl.textContent = '$' + formatVolume(marketCap);
        }
    });
    
    // Update coinListTop10 for next comparison
    coinListTop10 = newCoinListData;
    
    // Also update coinListData if we're showing top 10
    const searchInput = document.getElementById("coinListSearch");
    if (!searchInput || !searchInput.value.trim()) {
        coinListData = newCoinListData;
        coinListFiltered = newCoinListData;
    }
}

// DOM PATCHING: Update coin prices with blink effects - BINANCE VARLIKLAR TASARIMI İLE TAMAMEN AYNI
// Binance varlıklar sekmesindeki mantığın aynısı - sadece fiyat değişiminde blink
function updateCoinListPrices(newCoinListData) {
    // Use the new comprehensive function
    updateCoinListPricesAndDetails(newCoinListData);
}

// Show search results dropdown
function showCoinSearchResults(query) {
    const searchResults = document.getElementById("coinListSearchResults");
    if (!searchResults) return;
    
    if (!query || query.length === 0) {
        searchResults.style.display = 'none';
        coinListFiltered = [...coinListTop10];
        renderCoinList(true);
        return;
    }
    
    const queryUpper = query.toUpperCase();
    
    // Search in all coins (not just top 10)
    const matches = coinListAllCoins.filter(coin => {
        const symbol = (coin.symbol || '').toUpperCase();
        const baseAsset = (coin.baseAsset || symbol.replace(/USDT$|BTC$|ETH$|BNB$|FDUSD$|BUSD$|TUSD$|DAI$/i, '') || '').toUpperCase();
        return symbol.includes(queryUpper) || baseAsset.includes(queryUpper);
    }).slice(0, 20); // Limit to 20 results
    
    if (matches.length === 0) {
        searchResults.innerHTML = '<div style="padding: 12px; color: var(--ds-text-secondary); text-align: center;">Sonuç bulunamadı</div>';
        searchResults.style.display = 'block';
        return;
    }
    
    // Render search results
    searchResults.innerHTML = matches.map(coin => {
        const priceChange = coin.priceChangePercent || 0;
        const priceChangeColor = priceChange > 0 ? "#0ecb81" : priceChange < 0 ? "#f6465d" : "var(--ds-text-primary)";
        
        return `
            <div class="search-result-item" 
                 onclick="selectCoinFromSearch('${coin.symbol}')" 
                 style="padding: 12px; cursor: pointer; border-bottom: 1px solid var(--ds-border); transition: background 0.2s;"
                 onmouseenter="this.style.background='var(--ds-bg-hover)'"
                 onmouseleave="this.style.background='transparent'">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <strong style="color: var(--ds-text-primary); font-size: 0.95rem;">${coin.baseAsset || coin.symbol?.replace(/USDT$|BTC$|ETH$|BNB$|FDUSD$|BUSD$|TUSD$|DAI$/i, '') || 'N/A'}</strong>
                        <div style="font-size: 0.8rem; color: var(--ds-text-secondary); margin-top: 2px;">${coin.symbol}</div>
                    </div>
                    <div style="text-align: right;">
                        <div style="font-weight: 600; color: var(--ds-text-primary);">${fmtCoinPrice(coin.price)}</div>
                        <div style="font-size: 0.85rem; color: ${priceChangeColor}; font-weight: 600;">
                            ${priceChange > 0 ? '+' : ''}${priceChange.toFixed(2)}%
                        </div>
                    </div>
                </div>
            </div>
        `;
    }).join('');
    
    searchResults.style.display = 'block';
}

// Select coin from search results
function selectCoinFromSearch(symbol) {
    const searchInput = document.getElementById("coinListSearch");
    const searchResults = document.getElementById("coinListSearchResults");
    
    if (searchInput) {
        searchInput.value = '';
    }
    if (searchResults) {
        searchResults.style.display = 'none';
    }
    
    // Open spot trade modal
    if (typeof openSpotTradeModal === 'function') {
        openSpotTradeModal(symbol);
    } else {
        console.error("[dashboard] openSpotTradeModal function not found");
    }
}

// Make function global
window.selectCoinFromSearch = selectCoinFromSearch;

function filterCoinList(query) {
    if (!query) {
        coinListFiltered = [...coinListTop10];
    } else {
        // Search in all coins
        coinListFiltered = coinListAllCoins.filter(coin => {
            const symbol = coin.symbol.toUpperCase();
            const baseAsset = coin.baseAsset.toUpperCase();
            return symbol.includes(query) || baseAsset.includes(query);
        });
    }
    renderCoinList();
}

function renderCoinList(enableBlink = true) {
    const body = document.getElementById("coinListBody");
    if (!body) {
        console.error("[dashboard] renderCoinList: coinListBody element not found!");
        return;
    }
    if (window.BinanceUI && document.getElementById("tabBinance")?.classList.contains("is-active")) {
        return;
    }
    
    console.log("[dashboard] renderCoinList: Called with", coinListFiltered.length, "filtered coins");
    
    if (coinListFiltered.length === 0) {
        console.log("[dashboard] renderCoinList: No coins to display");
        body.innerHTML = '<tr><td colspan="8" style="text-align: center; padding: 2rem; color: var(--ds-text-secondary);">Coin bulunamadı</td></tr>';
        return;
    }
    
    body.innerHTML = coinListFiltered.map((coin, index) => {
        const priceChange = coin.priceChangePercent || 0;
        const priceChangeColor = priceChange > 0 ? "#0ecb81" : priceChange < 0 ? "#f6465d" : "var(--ds-text-primary)";
        
        // Check for price changes for blink effect - BINANCE VARLIKLAR MANTIĞI (TAMAMEN AYNI)
        const symbol = coin.symbol;
        let priceClass = "price-neutral";
        
        if (typeof window !== 'undefined' && window.coinListPriceCache) {
            const prevPrice = window.coinListPriceCache[symbol];
            
            // Price blink class (Binance varlıklar mantığı - TAMAMEN AYNI)
            if (prevPrice !== undefined && prevPrice !== coin.price) {
                priceClass = coin.price > prevPrice ? "price-up" : "price-down";
            }
            
            // Update cache (Binance mantığı - sadece price)
            if (symbol) {
                window.coinListPriceCache[symbol] = coin.price;
            }
        }
        
        // Format large numbers
        const formatVolume = (vol) => {
            if (vol >= 1e9) return `${(vol / 1e9).toFixed(2)}B`;
            if (vol >= 1e6) return `${(vol / 1e6).toFixed(2)}M`;
            if (vol >= 1e3) return `${(vol / 1e3).toFixed(2)}K`;
            return vol.toFixed(2);
        };
        
        const base = coin.baseAsset || (coin.symbol && coin.symbol.replace(/USDT$/i, '').replace(/BTC$/i, '').replace(/ETH$/i, '').replace(/BNB$/i, '')) || 'N/A';
        const logoUrl = (typeof getCoinLogoUrl === 'function' && getCoinLogoUrl(base)) || null;
        const initials = (base || ' ').substring(0, 2).toUpperCase();
        
        const originalIndex = coinListData.findIndex(c => c.symbol === coin.symbol);
        const rank = originalIndex >= 0 ? originalIndex + 1 : index + 1;
        const sym = (coin.symbol || '').toUpperCase();
        const displaySymbol = (sym === 'USDTUSD' || sym === 'USDTUSDT' || sym === 'USDT/USD') ? 'USDT/USD' : (coin.symbol || '');
        
        return `
            <tr id="coinRow_${symbol}" style="cursor: pointer;" onclick="openSpotTradeModal('${coin.symbol}')" onmouseenter="prefetchPriceData('${coin.symbol}')">
                <td class="varlik-logo-cell" style="padding: 12px; vertical-align: middle;">
                    <div class="varlik-logo" title="${base}">
                        ${logoUrl ? `<img src="${logoUrl}" alt="${base}" loading="lazy" onerror="if(window.registerLogo404)window.registerLogo404(this.alt);this.style.display='none';this.nextElementSibling.style.display='flex';" />` : ''}
                        <span class="varlik-logo-initials" style="${logoUrl ? 'display:none' : ''}">${initials}</span>
                    </div>
                </td>
                <td style="padding: 12px; color: var(--ds-text-secondary); font-size: 0.9rem;">${rank}</td>
                <td style="padding: 12px;">
                    <strong style="color: var(--ds-text-primary); font-size: 0.95rem;">${coin.baseAsset || coin.symbol?.replace('USDT', '').replace('BTC', '').replace('ETH', '').replace('BNB', '') || 'N/A'}</strong>
                    <div style="font-size: 0.8rem; color: var(--ds-text-secondary); margin-top: 2px;">${displaySymbol}</div>
                </td>
                <td style="text-align: right; padding: 12px; font-weight: 600;">
                    <span id="coinPrice_${symbol}" class="text-right price-cell ${priceClass}" data-price="${coin.price}">${fmtCoinPrice(coin.price)}</span>
                </td>
                <td style="text-align: right; padding: 12px;">
                    <span id="coinChange_${symbol}" class="text-right" style="color: ${priceChangeColor}; font-weight: 600;">
                        ${priceChange > 0 ? '+' : ''}${priceChange.toFixed(2)}%
                    </span>
                </td>
                <td style="text-align: right; padding: 12px; color: var(--ds-text-primary);">
                    <span id="coinVolume_${symbol}">${formatVolume(coin.quoteVolume)}</span>
                </td>
                <td style="text-align: right; padding: 12px; color: var(--ds-text-primary);">
                    <span id="coinMarketCap_${symbol}">$${formatVolume(coin.marketCapApprox)}</span>
                </td>
                <td style="text-align: center; padding: 12px;">
                    <div class="btn-al-sat-wrap">
                        <button type="button" class="btn-al" onclick="event.stopPropagation(); openSpotTradeModal('${coin.symbol}', 'BUY')" title="Alış">Alış</button>
                        <button type="button" class="btn-sat" onclick="event.stopPropagation(); openSpotTradeModal('${coin.symbol}', 'SELL')" title="Satış">Satış</button>
                    </div>
                </td>
            </tr>
        `;
    }).join("");
    
    // Apply blink effects after rendering - ALWAYS ACTIVE - FIXED
    requestAnimationFrame(() => {
        coinListFiltered.forEach(coin => {
            const symbol = coin.symbol;
            const priceEl = document.getElementById(`coinPrice_${symbol}`);
            const changeEl = document.getElementById(`coinChange_${symbol}`);
            
            // Apply blink to price if changed - FLASH HIZLI blink efekti
            if (priceEl) {
                if (priceEl.classList.contains("price-up")) {
                    // Force reflow to trigger animation
                    void priceEl.offsetHeight;
                    setTimeout(() => {
                        if (priceEl) priceEl.classList.remove("price-up");
                    }, 300); // 300ms - Binance varlıklar ile aynı
                } else if (priceEl.classList.contains("price-down")) {
                    // Force reflow to trigger animation
                    void priceEl.offsetHeight;
                    setTimeout(() => {
                        if (priceEl) priceEl.classList.remove("price-down");
                    }, 300); // 300ms - Binance varlıklar ile aynı
                }
            }
            
            // Apply blink to price change if changed - FLASH HIZLI blink efekti
            if (changeEl) {
                if (changeEl.classList.contains("price-up")) {
                    // Force reflow to trigger animation
                    void changeEl.offsetHeight;
                    setTimeout(() => {
                        if (changeEl) changeEl.classList.remove("price-up");
                    }, 300); // 300ms - Binance varlıklar ile aynı
                } else if (changeEl.classList.contains("price-down")) {
                    // Force reflow to trigger animation
                    void changeEl.offsetHeight;
                    setTimeout(() => {
                        if (changeEl) changeEl.classList.remove("price-down");
                    }, 300); // 300ms - Binance varlıklar ile aynı
                }
            }
        });
    });
}

// Make functions global
window.openSpotTradeModal = openSpotTradeModal;
window.closeSpotTradeModal = closeSpotTradeModal;
window.setTradeSide = setTradeSide;
window.setTradeType = setTradeType;
window.setTradePercent = setTradePercent;

// Fullscreen blocker safety valve
function checkFullscreenBlockers() {
    const children = Array.from(document.body.children);
    const w = window.innerWidth;
    const h = window.innerHeight;
    
    children.forEach(el => {
        if (!el || el.id === "topTicker" || el.id === "dmModal" || el.id === "dmBackdrop" ||
            el.id === "dmParamAssistantModal" || el.id === "dmParamAssistantBackdrop") return;
        
        const cs = getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        
        const isFullscreen = rect.width >= w * 0.8 && rect.height >= h * 0.8;
        const isBlocking = (cs.position === "fixed" || cs.position === "absolute") &&
                          cs.pointerEvents !== "none" &&
                          Number(cs.zIndex || 0) >= 100 &&
                          isFullscreen;
        
        if (isBlocking) {
            console.error("[dashboard] Fullscreen blocker detected:", el);
            el.style.pointerEvents = "none";
            el.style.display = "none";
        }
    });
}

// Main init
