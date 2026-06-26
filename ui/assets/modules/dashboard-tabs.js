/**
 * dashboard-tabs.js
 * Sekme bağlama (bindTabs), mobil nav, mobil trade arama, mobil favoriler.
 * dashboard.js'ten SONRA yüklenir.
 */

function desktopTabToMobileTab(desktopTab) {
    if (!desktopTab) return "home";
    var map = { binance: "home", reports: "home", finance: "portfoy", trade: "trade", bots: "bots", settings: "ayarlar", contact: "portfoy" };
    return map[desktopTab] || "home";
}

// Mobil sekme değişince desktop tab + localStorage senkronize (yenilemede doğru sekme kalsın)
function mobileTabToDesktopTab(mobileTab) {
    if (!mobileTab) return "binance";
    var map = { home: "binance", portfoy: "finance", trade: "trade", bots: "bots", ayarlar: "settings" };
    return map[mobileTab] || "binance";
}
function setDesktopTabActiveWithoutClick(desktopTabName) {
    var btn = document.querySelector('.dm-tab[data-tab="' + desktopTabName + '"]');
    if (!btn) return;
    document.querySelectorAll('.dm-tab').forEach(function (t) { t.classList.remove('is-active'); });
    btn.classList.add('is-active');
    try { localStorage.setItem('dashboard_active_tab', desktopTabName); } catch (_) {}
    if (history.replaceState) {
        var q = new URLSearchParams(window.location.search);
        q.set('tab', desktopTabName);
        history.replaceState(null, '', window.location.pathname + '?' + q.toString() + (window.location.hash || ''));
    }
}

// Mobil alt çubuk: Home | Markets | Trade | Botlar | Ayarlar
function initMobileBottomNav(currentDesktopTab) {
    const nav = document.getElementById("mobileBottomNav");
    if (!nav) return;
    const items = nav.querySelectorAll(".mobile-nav-item");
    const body = document.body;
    const TAB_CLASSES = ["mobile-tab-home", "mobile-tab-portfoy", "mobile-tab-trade", "mobile-tab-bots", "mobile-tab-ayarlar"];

    var _mobileTabInProgress = false;
    function setMobileTab(tab) {
        if (!tab) return;
        if (body.classList.contains("mobile-tab-" + tab)) return; // Zaten bu sekmede, tekrar işlem yapma (donma önlemi)
        if (_mobileTabInProgress) return;
        _mobileTabInProgress = true;
        requestAnimationFrame(function () {
            try {
                setMobileTabInner(tab);
            } finally {
                _mobileTabInProgress = false;
            }
        });
    }
    function setMobileTabInner(tab) {
        // Mobilde sekme geçişinde biriken interval'ları durdur (donma önlemi)
        if (window.intervalRegistry) {
            window.intervalRegistry.stopByOwner("binanceTab");
            window.intervalRegistry.stopByOwner("tab.varliklar");
            window.intervalRegistry.stopByOwner("tab.coinlist");
            window.intervalRegistry.stopByOwner("tab.list");
            window.intervalRegistry.stopByOwner("tab.reports");
            window.intervalRegistry.stopByOwner("tab.finance");
            window.intervalRegistry.stopByOwner("tab.bots");
            window.intervalRegistry.stopByOwner("tab.settings");
        }

        items.forEach(i => {
            i.classList.toggle("is-active", i.getAttribute("data-mobile-tab") === tab);
        });
        TAB_CLASSES.forEach(c => body.classList.remove(c));
        body.classList.add("mobile-tab-" + tab);

        const unifiedStrip = document.getElementById("unifiedKpiStrip");
        if (unifiedStrip) {
            const showStrip = tab === "home" || tab === "portfoy" || tab === "trade";
            unifiedStrip.classList.toggle("kpi-strip-hidden", !showStrip);
            if (showStrip) unifiedStrip.style.removeProperty("display");
            else unifiedStrip.style.display = "none";
            unifiedStrip.classList.remove("unified-kpi-bots-only");
        }
        updateBinanceConnectionNotice();

        document.body.classList.remove("tab-finance-active", "tab-contact-active", "tab-settings-active", "tab-trade-active", "tab-bots-active");
        if (tab === "home") {
            setDesktopTabActiveWithoutClick("binance");
            document.querySelectorAll(".dm-tab-content").forEach(c => { c.classList.remove("is-active"); c.style.display = "none"; });
            const tabBinance = document.getElementById("tabBinance");
            if (tabBinance) { tabBinance.classList.add("is-active"); tabBinance.style.display = "block"; }
            var txPanel = document.getElementById("transactionHistoryPanel");
            if (txPanel) txPanel.style.display = "block";
            if (typeof window.syncBootWalletToAssetsState === "function") window.syncBootWalletToAssetsState();
            if (window.BinanceAssetsPanel && typeof window.BinanceAssetsPanel.render === "function") window.BinanceAssetsPanel.render();
            if (typeof renderVarliklarList === "function") renderVarliklarList();
        } else if (tab === "portfoy") {
            setDesktopTabActiveWithoutClick("finance");
            document.body.classList.add("tab-finance-active");
            document.querySelectorAll(".dm-tab-content").forEach(c => { c.classList.remove("is-active"); c.style.display = "none"; });
            const tabFinance = document.getElementById("tabFinance");
            if (tabFinance) { tabFinance.classList.add("is-active"); tabFinance.style.display = "block"; }
            if (typeof initFinanceTab === "function") initFinanceTab();
        } else if (tab === "trade") {
            setDesktopTabActiveWithoutClick("trade");
            document.body.classList.add("tab-trade-active");
            document.querySelectorAll(".dm-tab-content").forEach(c => { c.classList.remove("is-active"); c.style.display = "none"; });
            var mobileTradeEl = document.getElementById("mobileTradeView");
            if (mobileTradeEl) { mobileTradeEl.classList.add("is-active"); mobileTradeEl.style.display = "block"; }
            initMobileTradeSearch();
            if (typeof getFavoritesStorageKey === "function" && getFavoritesStorageKey() && typeof loadSpotFavoritesFromStorage === "function") {
                loadSpotFavoritesFromStorage().then(function () { if (typeof renderMobileTradeFavorites === "function") renderMobileTradeFavorites(); }).catch(function () { if (typeof renderMobileTradeFavorites === "function") renderMobileTradeFavorites(); });
            } else {
                if (typeof renderMobileTradeFavorites === "function") renderMobileTradeFavorites();
            }
            if (typeof startMobileTradeFavPriceUpdates === "function") startMobileTradeFavPriceUpdates();
        } else if (tab === "bots") {
            document.body.classList.add("tab-bots-active");
            document.querySelectorAll(".dm-tab-content").forEach(function (c) { c.classList.remove("is-active"); c.style.display = "none"; });
            var tabBotsEl = document.getElementById("tabBots");
            if (tabBotsEl) { tabBotsEl.classList.add("is-active"); tabBotsEl.style.display = "block"; }
            setDesktopTabActiveWithoutClick("bots");
            if (typeof activateBotsTab === "function") activateBotsTab();
        } else if (tab === "ayarlar") {
            setDesktopTabActiveWithoutClick("settings");
            document.body.classList.add("tab-settings-active");
            document.querySelectorAll(".dm-tab-content").forEach(c => { c.classList.remove("is-active"); c.style.display = "none"; });
            const tabSettings = document.getElementById("tabSettings");
            if (tabSettings) { tabSettings.classList.add("is-active"); tabSettings.style.display = "block"; }
            if (typeof initSettingsTab === "function") initSettingsTab();
        }
    }

    items.forEach(btn => {
        btn.onclick = function () {
            const tab = this.getAttribute("data-mobile-tab");
            if (!tab) return;
            setMobileTab(tab);
        };
    });

    function syncFromDesktop() {
        if (window.innerWidth > 768) {
            TAB_CLASSES.forEach(c => body.classList.remove(c));
            return;
        }
        var mobileTab = desktopTabToMobileTab(currentDesktopTab);
        setMobileTab(mobileTab);
    }

    var resizeThrottled = throttle(function () {
        if (window.innerWidth > 768) TAB_CLASSES.forEach(c => body.classList.remove(c));
    }, 150);
    window.addEventListener("resize", resizeThrottled, { passive: true });
    syncFromDesktop();
}

// Mobil Trade sekmesi: coin ara, seçince alım satım modalı aç
var _mobileTradeSearchBound = false;
var _mobileTradeSearchPriceGen = 0;
function initMobileTradeSearch() {
    var input = document.getElementById("mobileTradeSearchInput");
    var dropdown = document.getElementById("mobileTradeSearchDropdown");
    var wrap = input ? input.closest(".coin-list-search-wrap") : null;
    if (!input || !dropdown) return;

    function fillDropdown() {
        var q = (input.value || "").trim().toUpperCase();
        if (!q) {
            dropdown.style.display = "none";
            return;
        }
        var list = (typeof filterCoinListForSearch === "function")
            ? filterCoinListForSearch(input.value, 50)
            : [];
        dropdown.innerHTML = list.map(function (item) {
            return renderCoinSearchDropdownItemHtml(item, "mobile-trade-search-item");
        }).join("");
        dropdown.style.display = list.length ? "block" : "none";
        if (list.length > 0 && typeof queueCoinSearchPriceFetch === "function") {
            var gen = ++_mobileTradeSearchPriceGen;
            queueCoinSearchPriceFetch(list.map(function (it) { return it.symbol; }), function () {
                if (gen !== _mobileTradeSearchPriceGen) return;
                if (!(input.value || "").trim()) return;
                fillDropdown();
            });
        }
    }

    if (!_mobileTradeSearchBound) {
        _mobileTradeSearchBound = true;
        input.oninput = fillDropdown;
        input.onclick = function () {
            input.focus();
            ensureCoinListSearchSymbolsLoaded("all").then(function () {
                buildCoinListSearchSymbols();
                if ((input.value || "").trim()) fillDropdown();
            });
        };
        if (wrap) {
            wrap.addEventListener("click", function (e) {
                if (e.target === dropdown || e.target.closest(".mobile-trade-search-item")) return;
                input.focus();
            });
        }
        input.onfocus = function () {
            ensureCoinListSearchSymbolsLoaded("all").then(function () { buildCoinListSearchSymbols(); if ((input.value || "").trim()) fillDropdown(); });
        };
        input.onkeydown = function (e) {
            if (e.key === "Escape") {
                dropdown.style.display = "none";
                return;
            }
            if (e.key === "Enter") {
                var first = dropdown.querySelector(".mobile-trade-search-item");
                if (first) {
                    e.preventDefault();
                    var sym = first.getAttribute("data-symbol");
                    if (sym && typeof openSpotTradeModal === "function") {
                        openSpotTradeModal(sym);
                        input.value = "";
                        dropdown.style.display = "none";
                    }
                }
            }
        };
        input.onblur = function () { setTimeout(function () { dropdown.style.display = "none"; }, 180); };
        dropdown.onmousedown = function (e) { e.preventDefault(); };
        dropdown.addEventListener("click", function (e) {
            var item = e.target.closest(".mobile-trade-search-item");
            if (!item) return;
            var symbol = item.getAttribute("data-symbol");
            if (symbol && typeof openSpotTradeModal === "function") {
                openSpotTradeModal(symbol);
                input.value = "";
                dropdown.style.display = "none";
            }
        });
    }

    ensureCoinListSearchSymbolsLoaded("all").then(function () { buildCoinListSearchSymbols(); fillDropdown(); });
}

var MOBILE_TRADE_FAV_TICKER_CACHE_KEY = "mobileTradeFavTicker_v1";
var _mobileTradeFavBatchInflight = null;
var _mobileTradeFavStoreSub = null;

function _readMobileTradeFavTickerCache() {
    try {
        var raw = sessionStorage.getItem(MOBILE_TRADE_FAV_TICKER_CACHE_KEY);
        return raw ? JSON.parse(raw) : {};
    } catch (e) {
        return {};
    }
}

function _writeMobileTradeFavTickerCache(symbol, price, changePct) {
    try {
        var sym = (symbol || "").toUpperCase();
        if (!sym || price == null || !Number.isFinite(price)) return;
        var cache = _readMobileTradeFavTickerCache();
        cache[sym] = { price: price, changePct: changePct, ts: Date.now() };
        sessionStorage.setItem(MOBILE_TRADE_FAV_TICKER_CACHE_KEY, JSON.stringify(cache));
    } catch (e) {}
}

function _fmtMobileTradeFavPriceDisplay(price, symbol) {
    return formatCoinSearchItemPrice(symbol, price);
}

function _applyMobileTradeFavItemQuote(symbol, price, changePct) {
    if (price == null || !Number.isFinite(price) || price <= 0) return;
    var sym = (symbol || "").toUpperCase();
    var item = document.querySelector('#mobileTradeFavoritesList .mobile-trade-fav-item[data-symbol="' + sym + '"]');
    if (!item) return;
    var priceRow = item.querySelector(".mobile-trade-fav-price-row");
    var changeSpan = item.querySelector(".mobile-trade-fav-change");
    if (!priceRow || !changeSpan) return;
    var oldPrice = parseFloat(priceRow.getAttribute("data-price") || "") || 0;
    var priceDisplay = _fmtMobileTradeFavPriceDisplay(price, sym);
    var changeStr = changePct != null && Number.isFinite(changePct)
        ? (changePct >= 0 ? "+" : "") + Number(changePct).toFixed(2) + "%"
        : "—";
    var changeColor = changePct != null && Number.isFinite(changePct)
        ? (changePct >= 0 ? "#0ecb81" : "#f6465d")
        : "var(--ds-text-secondary)";
    priceRow.setAttribute("data-price", price);
    priceRow.setAttribute("data-change-pct", changePct != null && Number.isFinite(changePct) ? changePct : "");
    var priceVal = priceRow.querySelector(".mobile-trade-fav-price-val");
    if (priceVal) priceVal.textContent = priceDisplay;
    changeSpan.textContent = changeStr;
    changeSpan.style.color = changeColor;
    _writeMobileTradeFavTickerCache(sym, price, changePct);
    if (Number.isFinite(oldPrice) && oldPrice > 0 && Math.abs(oldPrice - price) > 0.0001) {
        priceRow.classList.remove("mobile-trade-fav-price-blink-up", "mobile-trade-fav-price-blink-down");
        priceRow.classList.add(price > oldPrice ? "mobile-trade-fav-price-blink-up" : "mobile-trade-fav-price-blink-down");
        setTimeout(function () {
            priceRow.classList.remove("mobile-trade-fav-price-blink-up", "mobile-trade-fav-price-blink-down");
        }, 700);
    }
}

function _parseDataPricesPayload(res) {
    if (!res || typeof res !== "object") return {};
    if (res.prices && typeof res.prices === "object") return res.prices;
    if (res.data && typeof res.data === "object") {
        if (res.data.prices && typeof res.data.prices === "object") return res.data.prices;
        return res.data;
    }
    return res;
}

function _updateCoinSearchSymbolQuote(symbol, price, changePct) {
    var sym = (symbol || "").toUpperCase();
    if (!sym || price == null || !Number.isFinite(price) || price <= 0) return;
    if (window.marketStore && window.marketStore.updateMini) {
        window.marketStore.updateMini(sym, { last: price, changePct: changePct });
    }
    if (typeof coinListSearchAllSymbols !== "undefined" && Array.isArray(coinListSearchAllSymbols)) {
        for (var i = 0; i < coinListSearchAllSymbols.length; i++) {
            if ((coinListSearchAllSymbols[i].symbol || "").toUpperCase() === sym) {
                coinListSearchAllSymbols[i].last = price;
                if (changePct != null && Number.isFinite(changePct)) {
                    coinListSearchAllSymbols[i].changePct = changePct;
                }
                return;
            }
        }
        coinListSearchAllSymbols.push({ symbol: sym, last: price, changePct: changePct });
    }
}

function _getSymbolSearchQuote(symbol) {
    var sym = (symbol || "").toUpperCase();
    var mini = window.marketStore && window.marketStore.getMini && window.marketStore.getMini(sym);
    if (mini && mini.last != null && Number.isFinite(mini.last) && mini.last > 0) {
        return { price: mini.last, changePct: Number.isFinite(mini.changePct) ? mini.changePct : null };
    }
    var storePrice = window.marketStore && window.marketStore.getPrice && window.marketStore.getPrice(sym);
    if (storePrice != null && Number.isFinite(storePrice) && storePrice > 0) {
        return { price: storePrice, changePct: null };
    }
    if (typeof coinListSearchAllSymbols !== "undefined" && Array.isArray(coinListSearchAllSymbols)) {
        for (var i = 0; i < coinListSearchAllSymbols.length; i++) {
            var row = coinListSearchAllSymbols[i];
            if ((row.symbol || "").toUpperCase() === sym && row.last != null && Number.isFinite(row.last) && row.last > 0) {
                return {
                    price: row.last,
                    changePct: row.changePct != null && Number.isFinite(row.changePct) ? row.changePct : null
                };
            }
        }
    }
    var cached = _readMobileTradeFavTickerCache()[sym];
    if (cached && cached.price != null && Number.isFinite(cached.price) && cached.price > 0) {
        return {
            price: cached.price,
            changePct: cached.changePct != null && Number.isFinite(cached.changePct) ? cached.changePct : null
        };
    }
    return { price: null, changePct: null };
}

function formatCoinSearchItemPrice(symbol, price) {
    if (price == null || !Number.isFinite(Number(price)) || Number(price) <= 0) return "—";
    if (typeof formatModalPriceForSymbol === "function") {
        return formatModalPriceForSymbol(Number(price), symbol);
    }
    var pq = typeof parseTradingPairSymbol === "function" ? parseTradingPairSymbol(symbol) : null;
    if (pq && pq.valid && pq.quote) {
        var q = pq.quote;
        if (q === "USDT" || q === "FDUSD" || q === "BUSD" || q === "USDC") {
            return typeof fmtCoinPrice === "function" ? fmtCoinPrice(Number(price)) : ("$" + price);
        }
        if (q === "BTC") return fmtNum(price, 8) + " BTC";
        if (q === "ETH") return fmtNum(price, 6) + " ETH";
        if (q === "BNB") return fmtNum(price, 4) + " BNB";
        return fmtNum(price, 8) + " " + q;
    }
    return typeof fmtCoinPrice === "function" ? fmtCoinPrice(Number(price)) : ("$" + price);
}

function renderCoinSearchDropdownItemHtml(item, itemClass) {
    var sym = item.symbol || "";
    var label = typeof formatTradingPairDisplay === "function" ? formatTradingPairDisplay(sym) : sym;
    var pct = item.changePct != null && Number.isFinite(item.changePct) ? item.changePct : null;
    var pctStr = pct != null ? (pct >= 0 ? "+" : "") + pct.toFixed(2) + "%" : "—";
    var pctColor = pct != null ? (pct >= 0 ? "#0ecb81" : "#f6465d") : "var(--ds-text-secondary)";
    var priceStr = formatCoinSearchItemPrice(sym, item.last);
    var cls = "coin-list-search-item" + (itemClass ? " " + itemClass : "");
    return "<div class=\"" + cls + "\" data-symbol=\"" + sym + "\" style=\"padding: 0.6rem 1rem; cursor: pointer; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--ds-border);\"><span style=\"font-weight: 600;\">" + label + "</span><span style=\"display: flex; gap: 0.5rem; align-items: center;\"><span style=\"color: var(--ds-text-secondary);\">" + priceStr + "</span><span style=\"color: " + pctColor + "\">" + pctStr + "</span></span></div>";
}

var _coinSearchPriceFetchInflight = null;
var _coinSearchPricePending = [];
var _coinSearchPriceTimer = null;

function _fetchCoinSearchTickerFallback(symbol) {
    return fetch(window.location.origin + "/api/spot/ticker_24h?symbol=" + encodeURIComponent(symbol))
        .then(function (r) { return r.json(); })
        .then(function (data) {
            var price = parseFloat(data.lastPrice || data.weightedAvgPrice || 0);
            var changePct = parseFloat(data.priceChangePercent || 0);
            if (price > 0 && Number.isFinite(price)) {
                var pct = Number.isFinite(changePct) ? changePct : null;
                _updateCoinSearchSymbolQuote(symbol, price, pct);
                _writeMobileTradeFavTickerCache(symbol, price, pct);
                return { symbol: symbol, price: price, changePct: pct };
            }
            return null;
        })
        .catch(function () { return null; });
}

function fetchCoinSearchPricesBatch(symbols, opts) {
    opts = opts || {};
    var seen = {};
    symbols = (symbols || []).map(function (s) { return (s || "").toUpperCase(); }).filter(function (s) {
        if (!s || seen[s]) return false;
        seen[s] = true;
        return true;
    });
    if (!symbols.length) return Promise.resolve();
    var missing = [];
    symbols.forEach(function (sym) {
        var q = _getSymbolSearchQuote(sym);
        if (q.price != null && q.price > 0) {
            _updateCoinSearchSymbolQuote(sym, q.price, q.changePct);
            if (opts.onEach) opts.onEach(sym, q.price, q.changePct);
        } else {
            missing.push(sym);
        }
    });
    if (!missing.length) {
        if (opts.onUpdated) opts.onUpdated();
        return Promise.resolve();
    }
    if (!window.apiClient || typeof window.apiClient.get !== "function") {
        return Promise.all(missing.map(_fetchCoinSearchTickerFallback)).then(function () {
            if (opts.onUpdated) opts.onUpdated();
        });
    }
    var run = function () {
        return window.apiClient
            .get("/api/data/prices?slim=1&symbols=" + encodeURIComponent(missing.join(",")))
            .then(function (res) {
                var prices = _parseDataPricesPayload(res);
                var stillMissing = [];
                missing.forEach(function (sym) {
                    var row = prices[sym];
                    var price = row && row.price != null ? Number(row.price) : NaN;
                    var changePct = row && row.change24h != null ? Number(row.change24h) : null;
                    if (price > 0 && Number.isFinite(price)) {
                        var pct = Number.isFinite(changePct) ? changePct : null;
                        _updateCoinSearchSymbolQuote(sym, price, pct);
                        _writeMobileTradeFavTickerCache(sym, price, pct);
                        if (opts.onEach) opts.onEach(sym, price, pct);
                    } else {
                        stillMissing.push(sym);
                    }
                });
                return Promise.all(stillMissing.map(_fetchCoinSearchTickerFallback));
            })
            .catch(function () {
                return Promise.all(missing.map(_fetchCoinSearchTickerFallback));
            })
            .then(function () {
                if (opts.onUpdated) opts.onUpdated();
            });
    };
    if (_coinSearchPriceFetchInflight) {
        return _coinSearchPriceFetchInflight.then(run);
    }
    _coinSearchPriceFetchInflight = run().finally(function () {
        _coinSearchPriceFetchInflight = null;
    });
    return _coinSearchPriceFetchInflight;
}

function queueCoinSearchPriceFetch(symbols, onUpdated) {
    (symbols || []).forEach(function (s) {
        var u = (s || "").toUpperCase();
        if (u && _coinSearchPricePending.indexOf(u) === -1) _coinSearchPricePending.push(u);
    });
    if (_coinSearchPriceTimer) clearTimeout(_coinSearchPriceTimer);
    _coinSearchPriceTimer = setTimeout(function () {
        _coinSearchPriceTimer = null;
        var batch = _coinSearchPricePending.slice();
        _coinSearchPricePending = [];
        fetchCoinSearchPricesBatch(batch, { onUpdated: onUpdated });
    }, 150);
}

function _getMobileTradeFavQuote(symbol) {
    return _getSymbolSearchQuote(symbol);
}

function _fetchMobileTradeFavTickerFallback(symbol) {
    return _fetchCoinSearchTickerFallback(symbol).then(function (row) {
        if (row && row.price > 0) {
            _applyMobileTradeFavItemQuote(symbol, row.price, row.changePct);
        }
    });
}

function fetchMobileTradeFavPricesBatch(symbols) {
    return fetchCoinSearchPricesBatch(symbols, {
        onEach: function (sym, price, changePct) {
            _applyMobileTradeFavItemQuote(sym, price, changePct);
        }
    });
}

function prefetchMobileTradeFavTickerCache() {
    var favs = (typeof spotFavorites !== "undefined" && Array.isArray(spotFavorites)) ? spotFavorites.slice() : [];
    if (!favs.length) return;
    fetchMobileTradeFavPricesBatch(favs);
}

function refreshMobileTradeFavPricesFromStore() {
    var items = document.querySelectorAll("#mobileTradeFavoritesList .mobile-trade-fav-item");
    if (!items.length) return;
    items.forEach(function (item) {
        var sym = item.getAttribute("data-symbol");
        if (!sym) return;
        var q = _getMobileTradeFavQuote(sym);
        if (q.price != null) _applyMobileTradeFavItemQuote(sym, q.price, q.changePct);
    });
}

function ensureMobileTradeFavMarketStoreHook() {
    if (_mobileTradeFavStoreSub || !window.marketStore || typeof window.marketStore.subscribe !== "function") return;
    _mobileTradeFavStoreSub = window.marketStore.subscribe(function () {
        var view = document.getElementById("mobileTradeView");
        if (!view || !view.classList.contains("is-active")) return;
        refreshMobileTradeFavPricesFromStore();
    });
}

function startMobileTradeFavPriceUpdates() {
    ensureMobileTradeFavMarketStoreHook();
    if (window.intervalRegistry) {
        window.intervalRegistry.stopByOwner("tab.trade");
        tickMobileTradeFavoritesPrices();
        window.intervalRegistry.start("tab.trade.prices", tickMobileTradeFavoritesPrices, 2000, "tab.trade");
    }
}

// Mobil Trade: Favori coinler listesini doldur; tıklayınca alım satım modalı açılır
function renderMobileTradeFavorites() {
    var listEl = document.getElementById("mobileTradeFavoritesList");
    if (!listEl) return;
    try {
    var favs = (typeof spotFavorites !== "undefined" && Array.isArray(spotFavorites)) ? spotFavorites.slice() : [];
    if (favs.length === 0) {
        listEl.innerHTML = '<div style="padding: 1.5rem; text-align: center; color: var(--ds-text-secondary); font-size: 0.9rem;">Favori yok. Yukarıdaki arama çubuğunda coin arayıp seçin, alım satım ekranında yıldıza tıklayarak favorilere ekleyin.</div>';
        return;
    }
    var baseFromSymbol = function (sym) {
        var pq = parseTradingPairSymbol(sym);
        return pq.valid ? pq.base : sym;
    };
    var symbolDisplay = function (sym) {
        return formatTradingPairDisplay(sym);
    };
    var getLogoHtml = function (base) {
        var initials = (typeof getCoinLogoInitials === "function" ? getCoinLogoInitials(base) : (base || "?").substring(0, 1).toUpperCase());
        var initStyle = 'width:32px;height:32px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-size:0.7rem;font-weight:600;background:var(--ds-bg-tertiary);color:var(--ds-text-secondary);';
        if (!base || typeof getCoinLogoUrl !== "function") return '<span class="varlik-logo-initials" style="' + initStyle + '">' + initials + "</span>";
        var url = getCoinLogoUrl(base);
        return url
            ? '<img src="' + url + '" alt="' + base + '" data-symbol="' + base + '" class="mobile-trade-fav-logo" style="width:32px;height:32px;border-radius:50%;object-fit:cover;" onerror="if(window.handleCoinLogoError)window.handleCoinLogoError(this)" /><span class="varlik-logo-initials" style="display:none;' + initStyle + '">' + initials + "</span>"
            : '<span class="varlik-logo-initials" style="' + initStyle + '">' + initials + "</span>";
    };
    var html = favs.map(function (symbol) {
        var quote = _getMobileTradeFavQuote(symbol);
        var price = quote.price;
        var changePct = quote.changePct;
        var priceDisplay = _fmtMobileTradeFavPriceDisplay(price, symbol);
        var changeStr = changePct != null ? (changePct >= 0 ? "+" : "") + Number(changePct).toFixed(2) + "%" : "—";
        var changeColor = changePct != null ? (changePct >= 0 ? "#0ecb81" : "#f6465d") : "var(--ds-text-secondary)";
        var base = baseFromSymbol(symbol);
        var symbolLabel = symbolDisplay(symbol);
        return '<div class="mobile-trade-fav-item" data-symbol="' + symbol + '" role="button" tabindex="0">' +
            '<div class="mobile-trade-fav-logo-symbol">' +
            getLogoHtml(base) +
            '<span class="mobile-trade-fav-symbol" title="' + symbol + '">' + symbolLabel + '</span>' +
            '</div>' +
            '<div class="mobile-trade-fav-price-wrap">' +
            '<span class="mobile-trade-fav-price-row" data-price="' + (price != null && Number.isFinite(price) ? price : '') + '" data-change-pct="' + (changePct != null ? changePct : '') + '">' +
            '<span class="mobile-trade-fav-price-val">' + priceDisplay + '</span>' +
            '<span class="mobile-trade-fav-change" style="color:' + changeColor + '">' + changeStr + '</span>' +
            '</span></div>' +
            '<span class="mobile-trade-fav-spacer"></span>' +
            '<span class="mobile-trade-fav-action">Al / Sat</span>' +
            '</div>';
    }).join("");
    listEl.innerHTML = html;
    listEl.querySelectorAll(".mobile-trade-fav-item").forEach(function (el) {
        el.onclick = function () {
            var sym = el.getAttribute("data-symbol");
            if (sym && typeof openSpotTradeModal === "function") openSpotTradeModal(sym);
        };
        el.onkeydown = function (e) {
            if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                el.click();
            }
        };
    });
    var view = document.getElementById("mobileTradeView");
    if (view && view.classList.contains("is-active")) {
        fetchMobileTradeFavPricesBatch(favs);
    }
    } catch (err) {
        console.error("[dashboard] renderMobileTradeFavorites:", err);
        listEl.innerHTML = '<div style="padding: 1rem; color: var(--ds-danger); font-size: 0.9rem;">Favori listesi yüklenemedi. Sayfayı yenileyin.</div>';
    }
}

function tickMobileTradeFavoritesPrices() {
    var view = document.getElementById("mobileTradeView");
    if (!view || !view.classList.contains("is-active")) return;
    var items = document.querySelectorAll("#mobileTradeFavoritesList .mobile-trade-fav-item");
    if (items.length === 0) return;
    var symbols = [];
    items.forEach(function (item) {
        var sym = item.getAttribute("data-symbol");
        if (sym) symbols.push(sym);
    });
    fetchMobileTradeFavPricesBatch(symbols);
}

// Tabs
function bindTabs() {
    const tabs = document.querySelectorAll(".dm-tab");
    const contents = document.querySelectorAll(".dm-tab-content");
    
    console.log("[dashboard] bindTabs: Found", tabs.length, "tabs and", contents.length, "contents");
    
    if (tabs.length === 0) {
        console.error("[dashboard] bindTabs: No tabs found!");
        return;
    }
    
    tabs.forEach(tab => {
        // Remove any existing onclick handlers
        tab.onclick = null;
        
        // Use onclick instead of addEventListener for better compatibility
        tab.onclick = function(e) {
            try {
                e.preventDefault();
                e.stopPropagation();
                
                const targetTab = this.getAttribute("data-tab");
                console.log("[dashboard] Tab clicked:", targetTab, "Element:", this);
                
                if (!targetTab) {
                    console.error("[dashboard] Tab has no data-tab attribute:", this);
                    return;
                }
                
                // Re-query tabs and contents to ensure we have fresh references
                const allTabs = document.querySelectorAll(".dm-tab");
                const allContents = document.querySelectorAll(".dm-tab-content");
                
                // Update active states for all tabs
                allTabs.forEach(t => t.classList.remove("is-active"));
                allContents.forEach(c => { c.classList.remove("is-active"); c.style.display = "none"; });
                
                // Activate clicked tab
                this.classList.add("is-active");
                
                // Save active tab to localStorage ve URL – yenilemede aynı sekme kalsın
                localStorage.setItem('dashboard_active_tab', targetTab);
                if (history.replaceState) {
                    var q = new URLSearchParams(window.location.search);
                    q.set('tab', targetTab);
                    var newSearch = '?' + q.toString();
                    history.replaceState(null, '', window.location.pathname + newSearch + (window.location.hash || ''));
                }
                
                // Update Binance API banner visibility based on active tab
                updateBinanceApiBannerVisibility();
                // API bağlantı uyarısı: Anasayfa, Binance, Botlar sekmesinde göster (en üstte, tek blok)
                updateBinanceConnectionNotice();
                // Ortak KPI şeridi: Anasayfa, Trade; Botlar/Portföy/İletişim/Ayarlar’da gizle
                const unifiedStrip = document.getElementById('unifiedKpiStrip');
                if (unifiedStrip) {
                    const showStrip = (targetTab === 'reports' || targetTab === 'binance' || targetTab === 'trade');
                    unifiedStrip.classList.toggle('kpi-strip-hidden', !showStrip);
                    if (showStrip) unifiedStrip.style.removeProperty('display');
                    else unifiedStrip.style.display = 'none';
                    unifiedStrip.classList.remove('unified-kpi-bots-only');
                }
                
                // REFACTOR: Stop intervals from ALL tabs before switching (prevent leaks)
                window.intervalRegistry.stopByOwner('binanceTab');
                window.intervalRegistry.stopByOwner('tab.varliklar');
                window.intervalRegistry.stopByOwner('tab.varliklar.wallet_refresh');
                window.intervalRegistry.stopByOwner('tab.coinlist');
                window.intervalRegistry.stopByOwner('tab.trade');
                window.intervalRegistry.stopByOwner('tab.list');
                window.intervalRegistry.stopByOwner('tab.reports');
                window.intervalRegistry.stopByOwner('tab.finance');
                window.intervalRegistry.stopByOwner('tab.bots');
                window.intervalRegistry.stopByOwner('tab.settings');
                
                if (targetTab !== 'binance') {
                    if (window.BinanceUI && typeof window.BinanceUI.unmount === 'function') window.BinanceUI.unmount();
                }
                
                // Show corresponding content
                // Special handling for "finance" -> "Finance", "reports" -> "Reports", "trade" -> "mobileTradeView"
                let targetContentId;
                if (targetTab === "finance") {
                    targetContentId = "tabFinance";
                } else if (targetTab === "reports") {
                    targetContentId = "tabBinance";
                } else if (targetTab === "trade") {
                    targetContentId = "mobileTradeView";
                } else {
                    targetContentId = `tab${targetTab.charAt(0).toUpperCase() + targetTab.slice(1)}`;
                }
                const targetContent = document.getElementById(targetContentId);
                console.log("[dashboard] Looking for content:", targetContentId, "Found:", !!targetContent);
                
                if (targetContent) {
                    targetContent.classList.add("is-active");
                    targetContent.style.display = "block";
                    console.log("[dashboard] Tab switched successfully to:", targetTab);
                } else {
                    console.error("[dashboard] Tab content not found:", targetContentId, "Available IDs:", Array.from(allContents).map(c => c.id));
                }

                // Aktif Emirler paneli sadece Anasayfa'da göster; diğer sekmelerde gizle
                if (targetTab !== "binance" && typeof hideActiveOrdersPanel === "function") {
                    hideActiveOrdersPanel();
                }

                // Finansal Hesap, İletişim, Ayarlar, Trade sekmelerinde Mevcut Botlar, Bot Performansı ve İşlem Geçmişi gizlensin
                document.body.classList.toggle("tab-finance-active", targetTab === "finance");
                document.body.classList.toggle("tab-contact-active", targetTab === "contact");
                document.body.classList.toggle("tab-settings-active", targetTab === "settings");
                document.body.classList.toggle("tab-trade-active", targetTab === "trade");
                document.body.classList.toggle("tab-bots-active", targetTab === "bots");

                // İşlem Geçmişi paneli: Anasayfa/Binance sekmesinde her zaman görünsün ve veri yüklensin
                var txPanel = document.getElementById("transactionHistoryPanel");
                if (targetTab === "binance" && txPanel) {
                    txPanel.style.display = "block";
                    if (State.accountId && typeof loadTransactionHistory === "function") {
                        // Bekleyen revision varsa (başka sekmede işlem oldu) force yükle
                        var forceLoad = typeof _txHistoryLastSig !== 'undefined' && _txHistoryLastSig === ''
                                        && typeof _txHistoryRevision !== 'undefined' && !!_txHistoryRevision;
                        loadTransactionHistory(
                            State.txHistoryPeriod || "daily",
                            State.txHistoryType || "buysell",
                            State.txHistoryPage || 1,
                            false,
                            { silent: !forceLoad && _txHistoryLoaded, force: forceLoad }
                        );
                    }
                }

                // Special handling for binance tab (varlıklar + coin listesi + wallet 2sn poll)
                if (targetTab === "binance") {
                    updateBinanceConnectionNotice();
                    initVarliklarTab();
                    if (typeof initBinanceCoinList === 'function') initBinanceCoinList();
                    if (typeof updateActiveOrdersPanelPosition === 'function') updateActiveOrdersPanelPosition();
                    if (typeof startBinanceTabPolling === 'function') startBinanceTabPolling();
                    // Bot alımı / dönüş sonrası cüzdan tablosu hemen güncellensin
                    if (State.accountId) {
                        triggerWalletRefreshForVarliklar(State.accountId, { force: true });
                    }
                    startVarliklarPeriodicRefresh();
                    // İşlemler paneli Binance sekmesinde; veri sadece Reports açıldığında yükleniyordu – Binance açıldığında da yükle
                    if (State.accountId && typeof loadFinanceTrades === 'function') loadFinanceTrades();
                    if (window.__DEBUG_BINANCE__) console.log("[dashboard] Binance tab: BinanceUI.mount");
                    if (State.accountId && window.BinanceUI && typeof window.BinanceUI.mount === 'function') {
                        window.BinanceUI.mount({ accountId: State.accountId });
                        // loadActiveOrders startBinanceTabPolling içinde (orders:poll + 1.5s ilk çekim) tetikleniyor; burada tekrar çağırma
                    } else if (!State.accountId) {
                        const b = document.getElementById("varliklarTableBody");
                        if (b) b.innerHTML = '<tr><td colspan="10" style="text-align: center; padding: 2rem; color: var(--ds-text-secondary);">Hesap seçin.</td></tr>';
                    }
                } else if (targetTab === "finance") {
                    // Special handling for Finansal Hesap tab
                    console.log("[dashboard] Finance tab activated");
                    initFinanceTab();
                } else if (targetTab === "reports") {
                    console.log("[dashboard] Reports tab activated");
                    initReportsTab();
                } else if (targetTab === "settings") {
                    initSettingsTab();
                } else if (targetTab === "contact") {
                    // İletişim sekmesine girince: chat API open=1 ile çağrılır → backend boş sohbete otomatik hoş geldin mesajı ekler
                    if (State.accountId && window.apiClient) {
                        window.apiClient.get('/api/auth/chat?account_id=' + State.accountId + '&open=1').catch(function () {});
                    }
                    if (typeof window.startChatNotify === 'function') window.startChatNotify();
                } else if (targetTab === "trade") {
                    initMobileTradeSearch();
                    if (typeof getFavoritesStorageKey === "function" && getFavoritesStorageKey() && typeof loadSpotFavoritesFromStorage === "function") {
                        loadSpotFavoritesFromStorage().then(function () { if (typeof renderMobileTradeFavorites === "function") renderMobileTradeFavorites(); }).catch(function () { if (typeof renderMobileTradeFavorites === "function") renderMobileTradeFavorites(); });
                    } else {
                        if (typeof renderMobileTradeFavorites === "function") renderMobileTradeFavorites();
                    }
                    if (typeof startMobileTradeFavPriceUpdates === "function") startMobileTradeFavPriceUpdates();
                } else if (targetTab === "bots") {
                    if (typeof activateBotsTab === "function") activateBotsTab();
                } else {
                    stopCoinListUpdates();
                }
            } catch (error) {
                console.error("[dashboard] Tab switch error:", error);
                if (window.errorReporter) {
                    window.errorReporter.report(error, { action: 'switchTab', tab: targetTab });
                }
            }
        };
    });
    
    initMobileTradeSearch();
    console.log("[dashboard] bindTabs: All tabs bound");
}

// Must-change-password modal: always bind (modal shows before any tab switch)
function bindMustChangePasswordModal() {
    const btn = document.getElementById('mustChangePasswordBtn');
    const newInput = document.getElementById('mustChangePasswordNew');
    const confirmInput = document.getElementById('mustChangePasswordConfirm');
    const statusEl = document.getElementById('mustChangePasswordStatus');
    const strengthEl = document.getElementById('mustChangePasswordStrength');
    const matchEl = document.getElementById('mustChangePasswordMatch');
    if (!btn || !newInput || !confirmInput) return;

    function updateStrength() {
        const user = JSON.parse(localStorage.getItem('user') || '{}');
        const check = dashboardValidatePassword(newInput.value, user.name || '', user.surname || '');
        if (strengthEl) {
            strengthEl.textContent = newInput.value ? check.msg : '';
            strengthEl.style.color = check.valid ? '#0ecb81' : 'var(--ds-danger)';
        }
    }
    function updateMatch() {
        const match = confirmInput.value === newInput.value;
        if (matchEl) {
            matchEl.textContent = !confirmInput.value ? '' : match ? '✓ Şifreler eşleşiyor' : '✗ Şifreler eşleşmiyor';
            matchEl.style.color = match ? '#0ecb81' : 'var(--ds-danger)';
        }
    }

    newInput.addEventListener('input', updateStrength);
    newInput.addEventListener('blur', updateStrength);
    confirmInput.addEventListener('input', updateMatch);
    confirmInput.addEventListener('blur', updateMatch);

    btn.onclick = null;
    btn.onclick = async function () {
        const newPassword = newInput.value.trim();
        const newPasswordConfirm = confirmInput.value.trim();

        if (!newPassword || !newPasswordConfirm) {
            if (statusEl) {
                statusEl.textContent = 'Lütfen her iki alanı da doldurun.';
                statusEl.style.color = 'var(--ds-danger)';
            }
            return;
        }
        if (newPassword !== newPasswordConfirm) {
            if (statusEl) {
                statusEl.textContent = 'Şifreler eşleşmiyor.';
                statusEl.style.color = 'var(--ds-danger)';
            }
            return;
        }
        const user = JSON.parse(localStorage.getItem('user') || '{}');
        const check = dashboardValidatePassword(newPassword, user.name || '', user.surname || '');
        if (!check.valid) {
            if (statusEl) {
                statusEl.textContent = check.msg;
                statusEl.style.color = 'var(--ds-danger)';
            }
            return;
        }

        btn.disabled = true;
        if (statusEl) {
            statusEl.textContent = 'Güncelleniyor…';
            statusEl.style.color = 'var(--ds-text-secondary)';
        }
        try {
            await window.apiClient.post('/api/auth/change-password', {
                account_id: State.accountId,
                new_password: newPassword,
                new_password_confirm: newPasswordConfirm
            });

            const u = JSON.parse(localStorage.getItem('user') || '{}');
            u.must_change_password = false;
            localStorage.setItem('user', JSON.stringify(u));

            const modal = document.getElementById('mustChangePasswordModal');
            if (modal) modal.style.display = 'none';
            const container = document.querySelector('.container');
            if (container) {
                container.style.pointerEvents = '';
                container.style.opacity = '';
                container.style.filter = '';
            }
            document.querySelectorAll('.dm-tab').forEach(t => {
                t.style.pointerEvents = '';
                t.style.opacity = '';
            });
            if (window.Toast) window.Toast.success('Şifre başarıyla değiştirildi. Artık platformu kullanabilirsiniz.');

            newInput.value = '';
            confirmInput.value = '';
            if (statusEl) statusEl.textContent = '';
            if (strengthEl) strengthEl.textContent = '';
            if (matchEl) matchEl.textContent = '';
        } catch (e) {
            const msg = e.message || 'Şifre değiştirilemedi';
            if (statusEl) {
                statusEl.textContent = msg;
                statusEl.style.color = 'var(--ds-danger)';
            }
            if (window.Toast) window.Toast.error(msg);
        } finally {
            btn.disabled = false;
        }
    };
}
