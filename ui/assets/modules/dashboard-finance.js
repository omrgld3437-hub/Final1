/**
 * dashboard-finance.js
 * Finans sekmesi: portföy, raporlar, K/Z, dışa aktarma, popup.
 * dashboard.html'de dashboard.js'ten SONRA yüklenir.
 */

let financeState = {
    portfolioId: null,
    shortId: null,
    storageKey: null,
    items: [],
    itemInputs: [],
    goldPriceTRY: null // Gram altın fiyatı (TL)
};

// Ticker verilerini al (gram altın ve USDTRY)
async function getTickerData() {
    try {
        const response = await fetch(`/api/ticker?cb=${Date.now()}`);
        if (response.ok) {
            const data = await response.json();
            return {
                goldPriceTRY: parseFloat(data.GRAM_ALTIN_TRY) || null,
                usdtTry: parseFloat(data.USDTTRY) || null
            };
        }
    } catch (e) {
        console.error("[finance] Error fetching ticker data:", e);
    }
    return { goldPriceTRY: null, usdtTry: null };
}

// Gram altın fiyatını ticker'dan al (legacy - getTickerData kullan)
async function getGoldPriceTRY() {
    const data = await getTickerData();
    return data.goldPriceTRY;
}

// Gram altın fiyatını göster (placeholder)
function updateGoldPriceDisplay() {
    // Gram altın fiyatını göster (eğer bir display elementi varsa)
    // Şimdilik sadece state'te tutuyoruz
}

// Finansal hesap sekmesini başlat
function initFinanceTab() {
    console.log("[finance] Initializing finance tab");
    
    // Portfolio ID oluştur
    if (!financeState.portfolioId) {
        const urlParams = new URLSearchParams(window.location.search);
        let urlId = urlParams.get('id');
        
        if (!urlId) {
            urlId = 'p_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 10);
        }
        
        const saved = localStorage.getItem(`dcaPortfolio_${urlId}`);
        let shortId;
        if (saved) {
            const data = JSON.parse(saved);
            shortId = data.shortId || generateShortId();
        } else {
            shortId = generateShortId();
        }
        
        financeState.portfolioId = urlId;
        financeState.shortId = shortId;
        financeState.storageKey = `dcaPortfolio_${urlId}`;
    }
    
    // Ticker verilerini güncelle
    getTickerData().then(data => {
        financeState.goldPriceTRY = data.goldPriceTRY;
        financeState.usdtTry = data.usdtTry;
        updateGoldPriceDisplay();
    });
    
    // REFACTOR: Use intervalRegistry instead of setInterval
    window.intervalRegistry.stop('finance.goldPrice');
    window.intervalRegistry.start('finance.goldPrice', async () => {
        const data = await getTickerData();
        if (data.goldPriceTRY) financeState.goldPriceTRY = data.goldPriceTRY;
        if (data.usdtTry) financeState.usdtTry = data.usdtTry;
        updateGoldPriceDisplay();
    }, 5000, 'tab.finance');
    
    // Kaydedilmiş veriyi yükle
    const saved = localStorage.getItem(financeState.storageKey);
    if (saved) {
        const data = JSON.parse(saved);
        financeState.items = data.items || [];
        if (data.portfolioName) {
            const nameInput = document.getElementById('portfolioNameInput');
            if (nameInput) nameInput.value = data.portfolioName;
        }
        showFinanceScreen2();
    } else {
        showFinanceScreen1();
    }
    
    // Event listener'ları bağla
    bindFinanceEvents();
}

function generateShortId() {
    return Math.floor(100000 + Math.random() * 900000).toString();
}

function bindFinanceEvents() {
    console.log("[finance] Binding finance events");
    // Create button
    const createBtn = document.getElementById('createBtn');
    if (createBtn) {
        console.log("[finance] Create button found, binding click handler");
        // Remove existing handlers
        createBtn.onclick = null;
        createBtn.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            console.log("[finance] Create button clicked");
            createFinanceItemInputs();
        }, { passive: false });
    } else {
        console.error("[finance] Create button not found!");
    }
    
    // Save reference button
    const saveRefBtn = document.getElementById('saveRefBtn');
    if (saveRefBtn) {
        saveRefBtn.onclick = (e) => {
            e.preventDefault();
            e.stopPropagation();
            saveFinanceReference();
        };
    }
    
    // Tekrar ortalama (rebalance) butonu
    const rebalanceBtn = document.getElementById('rebalanceBtn');
    if (rebalanceBtn) {
        rebalanceBtn.onclick = (e) => {
            e.preventDefault();
            e.stopPropagation();
            calculateFinanceRebalance();
        };
    }
    
    // Save current button
    const saveCurrentBtn = document.getElementById('saveCurrentBtn');
    if (saveCurrentBtn) {
        saveCurrentBtn.onclick = (e) => {
            e.preventDefault();
            e.stopPropagation();
            saveFinanceCurrentValues();
        };
    }
    
    // Reset button
    const resetBtn = document.getElementById('resetBtn');
    if (resetBtn) {
        resetBtn.onclick = (e) => {
            e.preventDefault();
            e.stopPropagation();
            resetFinanceReference();
        };
    }
}

function showFinanceScreen1() {
    const screen1 = document.getElementById('financeScreen1');
    const screen2 = document.getElementById('financeScreen2');
    if (screen1) screen1.classList.remove('hidden');
    if (screen2) screen2.classList.add('hidden');
}

function showFinanceScreen2() {
    const screen1 = document.getElementById('financeScreen1');
    const screen2 = document.getElementById('financeScreen2');
    if (screen1) screen1.classList.add('hidden');
    if (screen2) screen2.classList.remove('hidden');
    
    const saved = localStorage.getItem(financeState.storageKey);
    if (saved) {
        const data = JSON.parse(saved);
        const portfolioName = data.portfolioName || 'İsimsiz Portföy';
        const titleEl = document.getElementById('portfolioTitle');
        if (titleEl) titleEl.textContent = portfolioName;
    }
    
    renderFinancePortfolioTable();
}

function createFinanceItemInputs() {
    console.log("[finance] createFinanceItemInputs called");
    const countInput = document.getElementById('itemCount');
    if (!countInput) {
        console.error("[finance] itemCount input not found");
        return;
    }
    
    const count = parseInt(countInput.value);
    console.log("[finance] Creating", count, "item inputs");
    if (count < 1) {
        showFinanceError('error1', 'En az 1 başlık gerekli');
        return;
    }
    
    financeState.itemInputs = [];
    const container = document.getElementById('itemsContainer');
    if (!container) {
        console.error("[finance] itemsContainer not found");
        return;
    }
    
    container.innerHTML = '';
    
    for (let i = 0; i < count; i++) {
        const div = document.createElement('div');
        div.className = 'item-row';
        div.style.cssText = 'margin-bottom: 15px; padding: 15px; background: var(--ds-bg-panel); border-radius: 8px; border: 1px solid var(--ds-border);';
        div.innerHTML = `
            <label style="display: block; margin-bottom: 0.5rem; color: var(--ds-text-primary); font-weight: 500;">Başlık Adı ${i + 1}</label>
            <input type="text" id="name_${i}" placeholder="Örn: Bitcoin" class="form-input" style="width: 100%; margin-bottom: 12px;">
            <label style="display: block; margin-bottom: 0.5rem; color: var(--ds-text-primary); font-weight: 500;">Başlangıç Değeri (USD) ${i + 1}</label>
            <input type="number" id="value_${i}" min="0" step="0.01" placeholder="100.00" class="form-input" style="width: 100%; margin-bottom: 12px;">
            <label style="display: block; margin-bottom: 0.5rem; color: var(--ds-text-primary); font-weight: 500;">Adet (Not) ${i + 1}</label>
            <input type="number" id="quantity_${i}" min="0" step="0.01" placeholder="0.00" class="form-input" style="width: 100%;">
        `;
        container.appendChild(div);
        financeState.itemInputs.push({ name: `name_${i}`, value: `value_${i}`, quantity: `quantity_${i}` });
    }
    
    const saveRefBtn = document.getElementById('saveRefBtn');
    if (saveRefBtn) {
        saveRefBtn.classList.remove('hidden');
        console.log("[finance] Save reference button shown");
    } else {
        console.error("[finance] saveRefBtn not found");
    }
    hideFinanceError('error1');
    console.log("[finance] Item inputs created successfully");
}

function saveFinanceReference() {
    const newItems = [];
    let total0 = 0;
    
    for (let i = 0; i < financeState.itemInputs.length; i++) {
        const nameEl = document.getElementById(financeState.itemInputs[i].name);
        const valueEl = document.getElementById(financeState.itemInputs[i].value);
        const quantityEl = document.getElementById(financeState.itemInputs[i].quantity);
        
        if (!nameEl || !valueEl) continue;
        
        const name = nameEl.value.trim();
        const initialValue = parseFloat(valueEl.value);
        const quantity = parseFloat(quantityEl?.value) || 0;
        
        if (!name) {
            showFinanceError('error1', `Başlık ${i + 1} için isim gerekli`);
            return;
        }
        
        if (isNaN(initialValue) || initialValue < 0) {
            showFinanceError('error1', `Başlık ${i + 1} için geçerli bir değer gerekli (>= 0)`);
            return;
        }
        
        total0 += initialValue;
        newItems.push({ name, initialValue, quantity });
    }
    
    if (total0 <= 0) {
        showFinanceError('error1', 'Toplam 0 olamaz');
        return;
    }
    
    financeState.items = newItems.map(item => ({
        name: item.name,
        targetWeight: item.initialValue / total0,
        initialValue: item.initialValue,
        quantity: item.quantity || 0
    }));
    
    const nameInput = document.getElementById('portfolioNameInput');
    const portfolioName = nameInput?.value.trim() || 'İsimsiz Portföy';
    const data = {
        items: financeState.items,
        createdAt: new Date().toISOString(),
        portfolioName: portfolioName,
        shortId: financeState.shortId
    };
    localStorage.setItem(financeState.storageKey, JSON.stringify(data));
    
    showFinanceScreen2();
}

function renderFinancePortfolioTable() {
    const tbody = document.getElementById('portfolioBody');
    if (!tbody) return;
    
    tbody.innerHTML = '';
    
    financeState.items.forEach((item, index) => {
        const row = document.createElement('tr');
        row.setAttribute('data-item-index', String(index));
        const currentValue = item.lastValue || item.currentValue || item.initialValue || 0;
        const quantity = item.quantity || 0;
        row.innerHTML = `
            <td data-label="Başlık Adı" style="padding: 12px;">${item.name}</td>
            <td data-label="Hedef Yüzde" style="padding: 12px; text-align: right;">${(item.targetWeight * 100).toFixed(2)}%</td>
            <td data-label="Güncel Değer (USD)" style="padding: 12px; text-align: right;">
                <input type="number" 
                       id="current_${index}" 
                       value="${currentValue.toFixed(2)}" 
                       min="0" 
                       step="0.01"
                       class="form-input finance-portfolio-input"
                       style="width: 150px; text-align: right;">
            </td>
            <td data-label="Adet (Not)" style="padding: 12px; text-align: right;">
                <input type="number" 
                       id="quantity_${index}" 
                       value="${quantity.toFixed(2)}" 
                       min="0" 
                       step="0.01"
                       class="form-input finance-portfolio-input"
                       style="width: 100px; text-align: right;"
                       placeholder="Not">
            </td>
            <td id="result_${index}" data-label="Sonuç" style="padding: 12px; text-align: center; font-weight: 600;">-</td>
        `;
        tbody.appendChild(row);
    });
}

/** Portföy tekrar ortalama (rebalance): hedef yüzdelerle mevcut değerleri karşılaştırır, AL/SAT önerisi üretir */
function calculateFinanceRebalance() {
    let total1 = 0;
    const currentValues = [];
    
    for (let index = 0; index < financeState.items.length; index++) {
        const item = financeState.items[index];
        const currentEl = document.getElementById(`current_${index}`);
        if (!currentEl) continue;
        
        const currentValue = parseFloat(currentEl.value);
        if (isNaN(currentValue) || currentValue < 0) {
            showFinanceError('error2', `${item.name} için geçerli bir değer gerekli (>= 0)`);
            return;
        }
        currentValues.push(currentValue);
        total1 += currentValue;
    }
    
    if (total1 <= 0) {
        showFinanceError('error2', 'Toplam değer 0 olamaz');
        return;
    }
    
    hideFinanceError('error2');
    
    financeState.items.forEach((item, index) => {
        const currentValue = currentValues[index];
        const targetValue = item.targetWeight * total1;
        const diff = currentValue - targetValue;
        
        const resultCell = document.getElementById(`result_${index}`);
        if (!resultCell) return;
        
        if (Math.abs(diff) < 0.01) {
            resultCell.textContent = 'DENGEDE';
            resultCell.className = 'action-balanced';
            resultCell.style.color = '#6c757d';
        } else if (diff > 0) {
            const sellAmount = diff;
            resultCell.textContent = `SAT ${sellAmount.toFixed(2)} USD`;
            resultCell.className = 'action-sell';
            resultCell.style.color = '#dc3545';
        } else {
            const buyAmount = -diff;
            resultCell.textContent = `AL ${buyAmount.toFixed(2)} USD`;
            resultCell.className = 'action-buy';
            resultCell.style.color = '#28a745';
        }
    });
    
    showFinanceSummary(total1);
}

function showFinanceSummary(currentTotal) {
    const summary = document.getElementById('summary');
    const content = document.getElementById('summaryContent');
    if (!summary || !content) return;
    
    const saved = JSON.parse(localStorage.getItem(financeState.storageKey) || '{}');
    const lastTotal = saved?.lastTotal;
    
    let prevText = '—';
    let pnlUsdText = '—';
    let pnlPctText = '—';
    let goldText = '—';
    
    if (lastTotal !== undefined && lastTotal > 0) {
        const pnlUsd = currentTotal - lastTotal;
        const pnlPct = (pnlUsd / lastTotal) * 100;
        
        const usdSign = pnlUsd >= 0 ? '+' : '';
        const pctSign = pnlPct >= 0 ? '+' : '';
        
        prevText = `${lastTotal.toFixed(2)} USD`;
        pnlUsdText = `${usdSign}${pnlUsd.toFixed(2)} USD`;
        pnlPctText = `${pctSign}${pnlPct.toFixed(2)} %`;
    }
    
    // Gram altın hesaplama
    if (financeState.goldPriceTRY && financeState.usdtTry && currentTotal > 0) {
        // Portföy değeri USD -> TL çevir
        const portfolioValueTRY = currentTotal * financeState.usdtTry;
        // Gram altın miktarı hesapla
        const goldGrams = portfolioValueTRY / financeState.goldPriceTRY;
        goldText = `${portfolioValueTRY.toFixed(2)} TL (${goldGrams.toFixed(4)} gram)`;
    } else if (financeState.goldPriceTRY && currentTotal > 0) {
        // Sadece gram altın fiyatı varsa (USDTRY yoksa)
        goldText = `Gram altın: ${financeState.goldPriceTRY.toFixed(2)} TL`;
    }
    
    content.innerHTML = `
        <div style="display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid var(--ds-border);">
            <span style="font-weight: 500; color: var(--ds-text-secondary);">Önceki Portföy:</span>
            <span style="font-weight: 600; color: var(--ds-text-primary);">${prevText}</span>
        </div>
        <div style="display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid var(--ds-border);">
            <span style="font-weight: 500; color: var(--ds-text-secondary);">Toplam Portföy:</span>
            <span style="font-weight: 600; color: var(--ds-text-primary);">${currentTotal.toFixed(2)} USD</span>
        </div>
        <div style="display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid var(--ds-border);">
            <span style="font-weight: 500; color: var(--ds-text-secondary);">Kâr / Zarar:</span>
            <span style="font-weight: 600; color: var(--ds-text-primary);">${pnlUsdText}</span>
        </div>
        <div style="display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid var(--ds-border);">
            <span style="font-weight: 500; color: var(--ds-text-secondary);">Değişim:</span>
            <span style="font-weight: 600; color: var(--ds-text-primary);">${pnlPctText}</span>
        </div>
        <div style="display: flex; justify-content: space-between; padding: 8px 0;">
            <span style="font-weight: 500; color: var(--ds-text-secondary);">Gram Altın Değeri:</span>
            <span style="font-weight: 600; color: var(--ds-accent);">${goldText}</span>
        </div>
    `;
    
    summary.classList.remove('hidden');
    
    if (saved) {
        saved.currentTotal = currentTotal;
        localStorage.setItem(financeState.storageKey, JSON.stringify(saved));
    }
}

function updateGoldPriceDisplay() {
    // Gram altın fiyatını göster (eğer bir display elementi varsa)
    // Şimdilik sadece state'te tutuyoruz
}

function saveFinanceCurrentValues() {
    let total = 0;
    const currentValues = [];
    
    for (let index = 0; index < financeState.items.length; index++) {
        const item = financeState.items[index];
        const currentEl = document.getElementById(`current_${index}`);
        if (!currentEl) continue;
        
        const currentValue = parseFloat(currentEl.value);
        if (isNaN(currentValue) || currentValue < 0) {
            showFinanceError('error2', `${item.name} için geçerli bir değer gerekli (>= 0)`);
            return;
        }
        currentValues.push(currentValue);
        total += currentValue;
    }
    
    if (total <= 0) {
        showFinanceError('error2', 'Toplam değer 0 olamaz');
        return;
    }
    
    hideFinanceError('error2');
    
    for (let index = 0; index < financeState.items.length; index++) {
        const item = financeState.items[index];
        const currentValue = currentValues[index];
        const quantityEl = document.getElementById(`quantity_${index}`);
        const quantity = parseFloat(quantityEl?.value) || 0;
        
        item.targetWeight = currentValue / total;
        item.lastValue = currentValue;
        item.quantity = quantity;
    }
    
    const savedData = JSON.parse(localStorage.getItem(financeState.storageKey) || '{}');
    const portfolioName = savedData?.portfolioName || 'İsimsiz Portföy';
    const data = {
        items: financeState.items,
        createdAt: savedData.createdAt || new Date().toISOString(),
        lastTotal: total,
        currentTotal: total,
        portfolioName: portfolioName,
        shortId: savedData?.shortId || financeState.shortId
    };
    localStorage.setItem(financeState.storageKey, JSON.stringify(data));
    
    const titleEl = document.getElementById('portfolioTitle');
    if (titleEl) titleEl.textContent = portfolioName;
    
    for (let index = 0; index < financeState.items.length; index++) {
        const resultCell = document.getElementById(`result_${index}`);
        if (resultCell) {
            resultCell.textContent = '-';
            resultCell.className = '';
            resultCell.style.color = '';
        }
    }
    
    const summary = document.getElementById('summary');
    if (summary) summary.classList.add('hidden');
    
    renderFinancePortfolioTable();
    
    alert('Yeni referans kaydedildi! targetWeight güncellendi.');
}

function resetFinanceReference() {
    if (confirm('Referansı sıfırlamak istediğinize emin misiniz? Bu işlem geri alınamaz.')) {
        localStorage.removeItem(financeState.storageKey);
        financeState.items = [];
        financeState.itemInputs = [];
        const screen2 = document.getElementById('financeScreen2');
        const screen1 = document.getElementById('financeScreen1');
        if (screen2) screen2.classList.add('hidden');
        if (screen1) screen1.classList.remove('hidden');
        const container = document.getElementById('itemsContainer');
        if (container) container.innerHTML = '';
        const saveRefBtn = document.getElementById('saveRefBtn');
        if (saveRefBtn) saveRefBtn.classList.add('hidden');
        const countInput = document.getElementById('itemCount');
        if (countInput) countInput.value = '3';
        const nameInput = document.getElementById('portfolioNameInput');
        if (nameInput) nameInput.value = '';
        hideFinanceError('error1');
        hideFinanceError('error2');
    }
}

function showFinanceError(errorId, message) {
    const errorDiv = document.getElementById(errorId);
    if (errorDiv) {
        errorDiv.textContent = message;
        errorDiv.classList.remove('hidden');
        errorDiv.style.cssText = 'color: #dc3545; background: #f8d7da; padding: 10px; border-radius: 4px; margin: 10px 0;';
    }
}

function hideFinanceError(errorId) {
    const errorDiv = document.getElementById(errorId);
    if (errorDiv) {
        errorDiv.classList.add('hidden');
    }
}

// ============================================
// FINANCE REPORTS TAB (Finans)
// ============================================

let financeReportsState = {
    currentSubTab: "summary",
    equityCurveRange: "7d",
    reportPeriod: "weekly",
    tradesOffset: 0,
    tradesLimit: 100
};

// Initialize Reports tab
function initReportsTab() {
    console.log("[reports] Initializing reports tab (unified view - no sub-tabs)");
    
    if (State.accountId) {
        // Summary from dashboard_snapshot; load period/trades data
        loadEquityCurve('7d');
        
        // Initialize finance period selection (default to daily)
        if (!financePeriod) {
            financePeriod = 'daily';
            setFinancePeriod('daily');
        } else {
            loadFinancePeriodData();
        }
        
        // Initialize trades period selection (default to daily)
        if (!financeTradesPeriod) {
            financeTradesPeriod = 'daily';
            setTradesPeriod('daily');
        } else {
            loadFinanceTrades();
        }
        
        // Summary from dashboard_snapshot; no finance.summary poll
    }
}

function initSettingsTab() {
    if (!State.accountId) return;
    
    const serverPublicIpEl = document.getElementById("settingsServerPublicIp");
    const apiKeyInput = document.getElementById("settingsApiKey");
    const apiSecretInput = document.getElementById("settingsApiSecret");
    const apiKeyBtn = document.getElementById("settingsApiKeyBtn");
    const apiSecretBtn = document.getElementById("settingsApiSecretBtn");
    const apiKeyStatus = document.getElementById("settingsApiKeyStatus");
    const apiSecretStatus = document.getElementById("settingsApiSecretStatus");
    const deleteAccountBtn = document.getElementById("settingsDeleteAccountBtn");
    const deleteAccountStatus = document.getElementById("settingsDeleteAccountStatus");
    const usernameInput = document.getElementById("settingsUsername");
    const phoneInput = document.getElementById("settingsPhone");
    const phoneBtn = document.getElementById("settingsPhoneBtn");
    const phoneStatus = document.getElementById("settingsPhoneStatus");
    const passwordInput = document.getElementById("settingsPassword");
    const passwordConfirmInput = document.getElementById("settingsPasswordConfirm");
    const passwordBtn = document.getElementById("settingsPasswordBtn");
    const passwordStatus = document.getElementById("settingsPasswordStatus");
    
    if (apiKeyStatus) apiKeyStatus.textContent = "";
    if (apiSecretStatus) apiSecretStatus.textContent = "";
    if (deleteAccountStatus) deleteAccountStatus.textContent = "";
    if (passwordStatus) passwordStatus.textContent = "";
    if (phoneStatus) phoneStatus.textContent = "";
    if (apiKeyInput) apiKeyInput.value = "";
    if (apiSecretInput) apiSecretInput.value = "";
    if (passwordInput) passwordInput.value = "";
    if (passwordConfirmInput) passwordConfirmInput.value = "";
    
    // Load account name (not user name) for Ad Soyad field + user_phone + isolate_from_admin
    (async () => {
        try {
            const data = await window.apiClient.get(`/api/accounts/${State.accountId}/settings`);
            if (data.account_name && usernameInput) {
                usernameInput.value = data.account_name;
            } else if (State.accountMeta && State.accountMeta.name && usernameInput) {
                usernameInput.value = State.accountMeta.name;
            } else if (usernameInput) {
                usernameInput.value = "Hesap adı yüklenemedi";
            }
            if (data.user_phone != null && phoneInput) {
                phoneInput.value = typeof data.user_phone === "string" ? data.user_phone : "";
            }
            var isolateBtn = document.getElementById("btnToggleIsolate");
            var isolateStatus = document.getElementById("settingsIsolateStatus");
            if (data.isolate_from_admin !== undefined) {
                if (isolateBtn) {
                    isolateBtn.textContent = data.isolate_from_admin ? "İzolasyonu Kaldır" : "Adminden İzole Ol";
                    isolateBtn.classList.toggle("is-isolated", data.isolate_from_admin === true);
                }
                if (isolateStatus) {
                    isolateStatus.textContent = data.isolate_from_admin ? "Açık (admin erişemez)" : "Kapalı";
                    isolateStatus.style.color = data.isolate_from_admin ? "#0ecb81" : "var(--ds-text-secondary)";
                }
            }
        } catch (e) {
            console.warn("[settings] Failed to load account name:", e);
            if (State.accountMeta && State.accountMeta.name && usernameInput) {
                usernameInput.value = State.accountMeta.name;
            }
        }
    })();
    
    // Sunucu dış IP (otomatik, salt okunur) – GET /settings server_public_ip döndürür
    (async () => {
        try {
            const data = await window.apiClient.get(`/api/accounts/${State.accountId}/settings`);
            if (serverPublicIpEl) {
                const ip = (data.server_public_ip && typeof data.server_public_ip === "string") ? data.server_public_ip.trim() : "";
                serverPublicIpEl.value = ip || "—";
                serverPublicIpEl.placeholder = ip ? "" : "Alınamadı";
            }
        } catch (e) {
            console.warn("[settings] Failed to load server public IP:", e);
            if (serverPublicIpEl) { serverPublicIpEl.value = ""; serverPublicIpEl.placeholder = "Alınamadı"; }
        }
    })();
    
    if (apiKeyBtn) {
        apiKeyBtn.onclick = null;
        apiKeyBtn.onclick = async () => {
            const v = apiKeyInput?.value?.trim();
            if (!v) {
                if (apiKeyStatus) { apiKeyStatus.textContent = "Key girin."; apiKeyStatus.style.color = "var(--ds-text-error, #f6465d)"; }
                return;
            }
            apiKeyBtn.disabled = true;
            if (apiKeyStatus) { apiKeyStatus.textContent = "Güncelleniyor…"; apiKeyStatus.style.color = "var(--ds-text-secondary)"; }
            try {
                await window.apiClient(`/api/accounts/${State.accountId}/settings`, { method: "PATCH", body: { api_key: v } });
                if (apiKeyInput) apiKeyInput.value = "";
                if (apiKeyStatus) { apiKeyStatus.textContent = "Güncellendi."; apiKeyStatus.style.color = "#0ecb81"; }
                if (window.Toast) window.Toast.success("API key güncellendi.");
                updateBinanceConnectionNotice();
            } catch (e) {
                var detail = e && e.detail;
                var isEncryption = detail && detail.error_code === "ENCRYPTION_NOT_CONFIGURED";
                if (apiKeyStatus) {
                    apiKeyStatus.style.color = "var(--ds-text-error, #f6465d)";
                    apiKeyStatus.textContent = isEncryption ? "BINANCE_MASTER_KEY .env'de yok. Aşağıdaki çözüme bakın." : "Hata.";
                }
                const msg = (e && (e.message || (detail && (typeof detail === 'string' ? detail : detail.message)))) || "API key güncellenemedi.";
                if (window.Toast) window.Toast.error(msg);
                if (isEncryption && detail.fix && window.Toast) window.Toast.warning(detail.fix, { duration: 15000 });
            } finally {
                apiKeyBtn.disabled = false;
            }
        };
    }
    
    if (apiSecretBtn) {
        apiSecretBtn.onclick = null;
        apiSecretBtn.onclick = async () => {
            const v = apiSecretInput?.value?.trim();
            if (!v) {
                if (apiSecretStatus) { apiSecretStatus.textContent = "Secret girin."; apiSecretStatus.style.color = "var(--ds-text-error, #f6465d)"; }
                return;
            }
            apiSecretBtn.disabled = true;
            if (apiSecretStatus) { apiSecretStatus.textContent = "Güncelleniyor…"; apiSecretStatus.style.color = "var(--ds-text-secondary)"; }
            try {
                await window.apiClient(`/api/accounts/${State.accountId}/settings`, { method: "PATCH", body: { api_secret: v } });
                if (apiSecretInput) apiSecretInput.value = "";
                if (apiSecretStatus) { apiSecretStatus.textContent = "Güncellendi."; apiSecretStatus.style.color = "#0ecb81"; }
                if (window.Toast) window.Toast.success("API secret güncellendi.");
                updateBinanceConnectionNotice();
            } catch (e) {
                var detail = e && e.detail;
                var isEncryption = detail && detail.error_code === "ENCRYPTION_NOT_CONFIGURED";
                if (apiSecretStatus) {
                    apiSecretStatus.style.color = "var(--ds-text-error, #f6465d)";
                    apiSecretStatus.textContent = isEncryption ? "BINANCE_MASTER_KEY .env'de yok. Aşağıdaki çözüme bakın." : "Hata.";
                }
                const msg = (e && (e.message || (detail && (typeof detail === 'string' ? detail : detail.message)))) || "API secret güncellenemedi.";
                if (window.Toast) window.Toast.error(msg);
                if (isEncryption && detail.fix && window.Toast) window.Toast.warning(detail.fix, { duration: 15000 });
            } finally {
                apiSecretBtn.disabled = false;
            }
        };
    }

    if (phoneBtn && phoneInput) {
        phoneBtn.onclick = null;
        phoneBtn.onclick = async () => {
            const phone = (phoneInput.value || "").trim();
            const digits = phone.replace(/\D/g, "");
            if (digits.length < 10) {
                if (phoneStatus) { phoneStatus.textContent = "En az 10 rakam gerekli."; phoneStatus.style.color = "var(--ds-text-error, #f6465d)"; }
                if (window.Toast) window.Toast.error("Geçerli telefon numarası girin.");
                return;
            }
            phoneBtn.disabled = true;
            if (phoneStatus) { phoneStatus.textContent = ""; phoneStatus.style.color = ""; }
            try {
                const res = await fetch("/api/auth/update-phone", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    credentials: "same-origin",
                    body: JSON.stringify({ account_id: State.accountId, phone })
                });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) throw new Error(data.detail || "Telefon güncellenemedi");
                if (phoneStatus) { phoneStatus.textContent = "Telefon güncellendi."; phoneStatus.style.color = "#0ecb81"; }
                if (window.Toast) window.Toast.success("Telefon güncellendi.");
            } catch (e) {
                if (phoneStatus) { phoneStatus.textContent = (e.message || "Hata"); phoneStatus.style.color = "var(--ds-text-error, #f6465d)"; }
                if (window.Toast) window.Toast.error(e.message || "Telefon güncellenemedi.");
            } finally {
                phoneBtn.disabled = false;
            }
        };
    }
    
    // Real-time password validation (uses shared dashboardValidatePassword)
    const passwordStrengthDiv = document.getElementById("settingsPasswordStrength");
    const passwordMatchDiv = document.getElementById("settingsPasswordMatch");
    
    if (passwordInput) {
        passwordInput.addEventListener('input', () => {
            const password = passwordInput.value;
            if (password.length > 0) {
                // Get user name/surname from localStorage
                const userData = JSON.parse(localStorage.getItem('user') || '{}');
                const name = userData.name || '';
                const surname = userData.surname || '';
                const result = dashboardValidatePassword(password, name, surname);
                if (passwordStrengthDiv) {
                    passwordStrengthDiv.textContent = result.msg;
                    passwordStrengthDiv.style.color = result.valid ? '#0ecb81' : 'var(--ds-text-error, #f6465d)';
                }
            } else {
                if (passwordStrengthDiv) passwordStrengthDiv.textContent = '';
            }
        });
    }
    
    if (passwordConfirmInput && passwordInput) {
        passwordConfirmInput.addEventListener('input', () => {
            const match = passwordInput.value === passwordConfirmInput.value;
            if (passwordConfirmInput.value.length > 0) {
                if (passwordMatchDiv) {
                    passwordMatchDiv.textContent = match ? '✓ Şifreler eşleşiyor' : '✗ Şifreler eşleşmiyor';
                    passwordMatchDiv.style.color = match ? '#0ecb81' : 'var(--ds-text-error, #f6465d)';
                }
            } else {
                if (passwordMatchDiv) passwordMatchDiv.textContent = '';
            }
        });
    }
    
    // Password change handler
    if (passwordBtn && passwordInput && passwordConfirmInput) {
        passwordBtn.onclick = null;
        passwordBtn.onclick = async () => {
            const newPassword = passwordInput.value.trim();
            const newPasswordConfirm = passwordConfirmInput.value.trim();
            
            if (!newPassword || !newPasswordConfirm) {
                if (passwordStatus) { 
                    passwordStatus.textContent = "Lütfen şifre alanlarını doldurun."; 
                    passwordStatus.style.color = "var(--ds-text-error, #f6465d)"; 
                }
                if (window.Toast) window.Toast.error("Lütfen şifre alanlarını doldurun.");
                return;
            }
            
            if (newPassword !== newPasswordConfirm) {
                if (passwordStatus) { 
                    passwordStatus.textContent = "Şifreler eşleşmiyor."; 
                    passwordStatus.style.color = "var(--ds-text-error, #f6465d)"; 
                }
                if (window.Toast) window.Toast.error("Şifreler eşleşmiyor.");
                return;
            }
            
            // Validate password strength before sending
            const userData = JSON.parse(localStorage.getItem('user') || '{}');
            const name = userData.name || '';
            const surname = userData.surname || '';
            const passwordCheck = dashboardValidatePassword(newPassword, name, surname);
            if (!passwordCheck.valid) {
                if (passwordStatus) { 
                    passwordStatus.textContent = passwordCheck.msg; 
                    passwordStatus.style.color = "var(--ds-text-error, #f6465d)"; 
                }
                if (window.Toast) window.Toast.error(passwordCheck.msg);
                return;
            }
            
            passwordBtn.disabled = true;
            if (passwordStatus) { 
                passwordStatus.textContent = "Güncelleniyor…"; 
                passwordStatus.style.color = "var(--ds-text-secondary)"; 
            }
            
            try {
                await window.apiClient.post('/api/auth/change-password', {
                    account_id: State.accountId,
                    new_password: newPassword,
                    new_password_confirm: newPasswordConfirm
                });
                
                if (passwordStatus) { 
                    passwordStatus.textContent = "Şifre başarıyla değiştirildi."; 
                    passwordStatus.style.color = "#0ecb81"; 
                }
                if (passwordStrengthDiv) passwordStrengthDiv.textContent = '';
                if (passwordMatchDiv) passwordMatchDiv.textContent = '';
                if (passwordInput) passwordInput.value = "";
                if (passwordConfirmInput) passwordConfirmInput.value = "";
                if (window.Toast) window.Toast.success("Şifre başarıyla değiştirildi.");
                
                // Update user in localStorage (must_change_password = false)
                try {
                    const u = JSON.parse(localStorage.getItem('user') || '{}');
                    u.must_change_password = false;
                    localStorage.setItem('user', JSON.stringify(u));
                } catch (e) {}
            } catch (e) {
                const errorMsg = e.message || "Şifre değiştirilemedi";
                if (passwordStatus) { 
                    passwordStatus.textContent = errorMsg; 
                    passwordStatus.style.color = "var(--ds-text-error, #f6465d)"; 
                }
                if (window.Toast) window.Toast.error(errorMsg);
            } finally {
                passwordBtn.disabled = false;
            }
        };
    }
    
    if (deleteAccountBtn) {
        var deleteAccountModalEl = document.getElementById("deleteAccountModal");
        var deleteAccountModalBackdrop = document.getElementById("deleteAccountModalBackdrop");
        var deleteAccountPasswordInput = document.getElementById("deleteAccountPasswordInput");
        var deleteAccountModalError = document.getElementById("deleteAccountModalError");
        var deleteAccountModalClose = document.getElementById("deleteAccountModalClose");
        var deleteAccountModalCancel = document.getElementById("deleteAccountModalCancel");
        var deleteAccountModalConfirm = document.getElementById("deleteAccountModalConfirm");

        function openDeleteAccountModal() {
            if (deleteAccountPasswordInput) deleteAccountPasswordInput.value = "";
            if (deleteAccountModalError) deleteAccountModalError.textContent = "";
            if (deleteAccountModalBackdrop) { deleteAccountModalBackdrop.style.display = "block"; deleteAccountModalBackdrop.setAttribute("aria-hidden", "false"); }
            if (deleteAccountModalEl) { deleteAccountModalEl.style.display = "flex"; deleteAccountModalEl.setAttribute("aria-hidden", "false"); }
            if (deleteAccountPasswordInput) setTimeout(function () { deleteAccountPasswordInput.focus(); }, 100);
        }
        function closeDeleteAccountModal() {
            if (deleteAccountModalBackdrop) { deleteAccountModalBackdrop.style.display = "none"; deleteAccountModalBackdrop.setAttribute("aria-hidden", "true"); }
            if (deleteAccountModalEl) { deleteAccountModalEl.style.display = "none"; deleteAccountModalEl.setAttribute("aria-hidden", "true"); }
        }

        deleteAccountBtn.onclick = function () {
            if (deleteAccountStatus) { deleteAccountStatus.textContent = ""; deleteAccountStatus.style.color = ""; }
            openDeleteAccountModal();
        };

        if (deleteAccountModalClose) deleteAccountModalClose.onclick = closeDeleteAccountModal;
        if (deleteAccountModalCancel) deleteAccountModalCancel.onclick = closeDeleteAccountModal;
        if (deleteAccountModalBackdrop) deleteAccountModalBackdrop.onclick = closeDeleteAccountModal;

        if (deleteAccountModalConfirm) {
            deleteAccountModalConfirm.onclick = async function () {
                var pwd = (deleteAccountPasswordInput && deleteAccountPasswordInput.value) ? deleteAccountPasswordInput.value : "";
                if (!pwd.trim()) {
                    if (deleteAccountModalError) deleteAccountModalError.textContent = "Şifre girin.";
                    return;
                }
                if (!State.accountId || !window.apiClient) return;
                deleteAccountModalConfirm.disabled = true;
                if (deleteAccountModalError) deleteAccountModalError.textContent = "";
                try {
                    await window.apiClient.post("/api/accounts/" + State.accountId + "/delete", { password: pwd });
                    closeDeleteAccountModal();
                    if (window.Toast) window.Toast.success("Hesap silindi.");
                    window.location.href = "/ui/login.html";
                } catch (e) {
                    deleteAccountModalConfirm.disabled = false;
                    var msg = (e && e.detail) ? (typeof e.detail === "string" ? e.detail : (e.detail.message || e.detail.detail || "Hata")) : "Hesap silinemedi.";
                    if (e.status === 400 && e.detail && typeof e.detail === "object" && e.detail.detail) msg = e.detail.detail;
                    if (deleteAccountModalError) deleteAccountModalError.textContent = msg;
                    if (window.Toast) window.Toast.error(msg);
                }
            };
        }
    }

    var btnToggleIsolate = document.getElementById("btnToggleIsolate");
    var settingsIsolateStatus = document.getElementById("settingsIsolateStatus");
    if (btnToggleIsolate) {
        btnToggleIsolate.onclick = null;
        btnToggleIsolate.onclick = async function () {
            if (!State.accountId || !window.apiClient) return;
            btnToggleIsolate.disabled = true;
            if (settingsIsolateStatus) { settingsIsolateStatus.textContent = "Güncelleniyor…"; settingsIsolateStatus.style.color = "var(--ds-text-secondary)"; }
            try {
                var data = await window.apiClient.get("/api/accounts/" + State.accountId + "/settings");
                var next = !(data.isolate_from_admin === true);
                await window.apiClient.patch("/api/accounts/" + State.accountId + "/settings", { isolate_from_admin: next });
                if (btnToggleIsolate) {
                    btnToggleIsolate.textContent = next ? "İzolasyonu Kaldır" : "Adminden İzole Ol";
                    btnToggleIsolate.classList.toggle("is-isolated", next === true);
                }
                if (settingsIsolateStatus) {
                    settingsIsolateStatus.textContent = next ? "Açık (admin erişemez)" : "Kapalı";
                    settingsIsolateStatus.style.color = next ? "#0ecb81" : "var(--ds-text-secondary)";
                }
                if (window.Toast) window.Toast.success(next ? "Adminden izole açıldı." : "İzolasyon kaldırıldı.");
            } catch (e) {
                if (settingsIsolateStatus) { settingsIsolateStatus.textContent = "Hata."; settingsIsolateStatus.style.color = "var(--ds-text-error, #f6465d)"; }
                if (window.Toast) window.Toast.error((e && e.message) || "Güncellenemedi.");
            } finally {
                btnToggleIsolate.disabled = false;
            }
        };
    }
}

function openAuditModal() {
    var backdrop = document.getElementById("auditModalBackdrop");
    var modal = document.getElementById("auditModal");
    if (!backdrop || !modal) return;
    backdrop.setAttribute("aria-hidden", "false");
    backdrop.style.display = "block";
    modal.setAttribute("aria-hidden", "false");
    modal.style.display = "flex";
    document.body.style.overflow = "hidden";
    backdrop.onclick = function (e) { if (e.target === backdrop) closeAuditModal(); };
    loadSettingsAudit("month");
    var listEl = document.getElementById("settingsAuditList");
    if (listEl) listEl.innerHTML = "<span style=\"color: var(--ds-text-secondary);\">Yükleniyor...</span>";
    document.querySelectorAll(".audit-range-btn").forEach(function (btn) {
        btn.classList.remove("active");
        if ((btn.getAttribute("data-range") || "") === "month") btn.classList.add("active");
    });
    document.querySelectorAll(".audit-range-btn").forEach(function (btn) {
        btn.onclick = function () {
            document.querySelectorAll(".audit-range-btn").forEach(function (b) { b.classList.remove("active"); });
            btn.classList.add("active");
            var range = btn.getAttribute("data-range") || "month";
            loadSettingsAudit(range);
        };
    });
    var typeFilterEl = document.getElementById("settingsAuditTypeFilter");
    if (typeFilterEl) {
        typeFilterEl.value = "";
        typeFilterEl.onchange = setAuditTypeFilter;
    }
}
function closeAuditModal() {
    var backdrop = document.getElementById("auditModalBackdrop");
    var modal = document.getElementById("auditModal");
    if (backdrop) { backdrop.setAttribute("aria-hidden", "true"); backdrop.style.display = "none"; }
    if (modal) { modal.setAttribute("aria-hidden", "true"); modal.style.display = "none"; }
    document.body.style.overflow = "";
}
var AUDIT_EVENT_LABELS = { LOGIN_SUCCESS: "Giriş başarılı", LOGIN_FAILED: "Giriş başarısız", LOGOUT: "Çıkış", SPOT_ORDER_CREATE: "Spot emir", BOT_CREATE: "Bot oluşturuldu", BOT_START: "Bot başlatıldı", BOT_STOP: "Bot durduruldu", BOT_DELETE: "Bot silindi", BOT_TRADE: "Bot alım/satım", PASSWORD_CHANGE: "Şifre değişti", PHONE_UPDATE: "Telefon güncellendi", CHAT_USER_MESSAGE: "Sohbet (siz)", CHAT_ADMIN_MESSAGE: "Sohbet (admin)" };

/** Tarih-saati Türkiye saatine göre formatla (dd.MM.yyyy HH:mm:ss) */
function formatAuditTimeTR(isoOrMs) {
    if (!isoOrMs) return "—";
    try {
        if (window.trTime && window.trTime.trFormatDateTime) return window.trTime.trFormatDateTime(isoOrMs);
        var d = new Date(isoOrMs);
        if (!Number.isFinite(d.getTime())) return "—";
        return d.toLocaleString("tr-TR", { timeZone: "Europe/Istanbul", day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
    } catch (e) { return "—"; }
}

function renderSettingsAuditTable(events, typeFilter) {
    var listEl = document.getElementById("settingsAuditList");
    if (!listEl) return;
    if (!events || events.length === 0) {
        listEl.innerHTML = "<p style=\"color: var(--ds-text-secondary); padding: 1.5rem;\">Bu dönemde kayıt yok.</p>";
        return;
    }
    var filtered = typeFilter ? events.filter(function (e) { return e.event_type === typeFilter; }) : events;
    if (filtered.length === 0) {
        listEl.innerHTML = "<p style=\"color: var(--ds-text-secondary); padding: 1.5rem;\">Seçilen türde kayıt yok.</p>";
        return;
    }
    var html = '<table class="audit-table" style="width:100%; border-collapse: collapse; font-size: 0.8rem;"><thead><tr style="border-bottom: 2px solid var(--ds-border); background: var(--ds-bg-tertiary);"><th style="text-align: left; padding: 0.6rem 0.5rem; font-weight: 600;">Tarih-Saat (TR)</th><th style="text-align: left; padding: 0.6rem 0.5rem; font-weight: 600;">Kim</th><th style="text-align: left; padding: 0.6rem 0.5rem; font-weight: 600;">IP</th><th style="text-align: left; padding: 0.6rem 0.5rem; font-weight: 600;">İşlem türü</th><th style="text-align: left; padding: 0.6rem 0.5rem; font-weight: 600;">Detay</th></tr></thead><tbody>';
    filtered.forEach(function (e) {
        var time = formatAuditTimeTR(e.created_at);
        var actor = (e.actor_type === "admin" ? "Admin" : (e.actor_type === "system" ? "Sistem" : (e.actor_label || "Siz")));
        var ip = (e.ip != null && e.ip !== "") ? e.ip : "—";
        var typeLabel = AUDIT_EVENT_LABELS[e.event_type] || e.event_type || "—";
        var detail = (e.detail != null && e.detail !== "") ? String(e.detail).replace(/</g, "&lt;").replace(/>/g, "&gt;") : "—";
        html += "<tr style=\"border-bottom: 1px solid var(--ds-border);\"><td style=\"padding: 0.6rem 0.5rem; white-space: nowrap; color: var(--ds-text-secondary);\">" + time + "</td><td style=\"padding: 0.6rem 0.5rem;\">" + actor + "</td><td style=\"padding: 0.6rem 0.5rem; font-family: monospace; font-size: 0.75rem;\">" + ip + "</td><td style=\"padding: 0.6rem 0.5rem;\">" + typeLabel + "</td><td style=\"padding: 0.6rem 0.5rem; max-width: 380px; word-break: break-word;\">" + detail + "</td></tr>";
    });
    html += "</tbody></table>";
    listEl.innerHTML = html;
}

function loadSettingsAudit(rangeKey) {
    var listEl = document.getElementById("settingsAuditList");
    if (!listEl || !State.accountId || !window.apiClient) return;
    var range = (rangeKey || "month").toLowerCase();
    if (range === "3month") range = "3m";
    if (range === "6month") range = "6m";
    listEl.innerHTML = "<span style=\"color: var(--ds-text-secondary);\">Yükleniyor...</span>";
    var typeFilterEl = document.getElementById("settingsAuditTypeFilter");
    var typeFilter = (typeFilterEl && typeFilterEl.value) ? typeFilterEl.value : "";
    window.apiClient.get("/api/audit/events?account_id=" + State.accountId + "&range=" + encodeURIComponent(range) + "&limit=200&offset=0&_t=" + Date.now()).then(function (data) {
        var events = (data && data.events) ? data.events : [];
        State.auditEventsCache = events;
        renderSettingsAuditTable(events, typeFilter);
    }).catch(function (e) {
        listEl.innerHTML = "<p style=\"color: var(--ds-danger, #f6465d);\">Yüklenemedi.</p>";
    });
}

function setAuditTypeFilter() {
    var typeFilterEl = document.getElementById("settingsAuditTypeFilter");
    var typeFilter = (typeFilterEl && typeFilterEl.value) ? typeFilterEl.value : "";
    var events = State.auditEventsCache || [];
    renderSettingsAuditTable(events, typeFilter);
}
window.openAuditModal = openAuditModal;
window.closeAuditModal = closeAuditModal;

async function loadFinanceSummary() {
    if (!State.accountId) return;
    
    try {
        // Load finance summary
        let data;
        if (window.financeService) {
            data = await window.financeService.getSummary(State.accountId);
        } else {
            data = await window.apiClient.get(`/api/finance/summary?account_id=${State.accountId}&cb=${Date.now()}`);
        }
        
        // Cüzdan bakiye + Kullanılabilir/Kilitli – tek kaynak: /api/binance/wallet
        data.binance_balance_usd = 0;
        data.spot_balance_usd = 0;
        data.free_usd = 0;
        data.locked_usd = 0;
        data.available_usd = 0;
        data.bot_locked_usd = 0;
        try {
            const wallet = await window.apiClient.get(`/api/binance/wallet?account_id=${State.accountId}`);
            const total = Number(wallet.total_usd) || 0;
            data.binance_balance_usd = total;
            data.spot_balance_usd = total;
            data.free_usd = Number(wallet.free_usd) || 0;
            data.locked_usd = Number(wallet.locked_usd) || 0;
            data.available_usd = Number(wallet.available_usd) ?? data.free_usd;
            data.bot_locked_usd = Number(wallet.bot_locked_usd) || 0;
            // Strip tek kaynak: assetsState.wallet. Finance summary wallet'ı state'e uygula, strip renderAssetsSummary ile güncellenir (flicker önleme).
            if (typeof normalizeAndApplyWallet === 'function') normalizeAndApplyWallet(wallet, { source: 'finance_summary', request_id: null });
        } catch (_) {
            // hata durumunda 0 kalır
        }
        // Bot bakiyesi: finance/summary'dan gelsin; yoksa dashboard summary ile senkron (aynı kaynak = state panel)
        if ((!data.account || data.account.bots_balance_usd == null) && State.summary && State.summary.account && State.summary.account.bots_balance_usd != null) {
            data.account = data.account || {};
            data.account.bots_balance_usd = State.summary.account.bots_balance_usd;
            data.bots_balance_usd = State.summary.account.bots_balance_usd;
        }
        // Update KPI cards
        updateFinanceKPIs(data);
        
        // Mevcut Botlar: canlı API boş liste döndürürse silinmiş bot satırlarını temizle.
        if (State.summary && Array.isArray(State.summary.bots) && State.summary.bots.length > 0) {
            renderFinanceBots(State.summary.bots);
        } else if (data.bots && Array.isArray(data.bots) && data.bots.length) {
            renderFinanceBots(data.bots);
        } else if (State.summary && Array.isArray(State.summary.bots)) {
            renderFinanceBots(State.summary.bots, { clearWhenEmpty: true });
        } else if (data.bots && Array.isArray(data.bots)) {
            renderFinanceBots(data.bots, { clearWhenEmpty: true });
        } else if (State.bots && State.bots.length) {
            renderFinanceBots(State.bots);
        } else {
            renderFinanceBots(data.bot_summary || [], { clearWhenEmpty: true });
        }
        
    } catch (error) {
        console.error("[reports] Error loading finance summary:", error);
        if (window.errorReporter) {
            window.errorReporter.report(error, { tab: 'reports', account_id: State.accountId, action: 'loadFinanceSummary' });
        }
    }
}

// Helper function to update finance KPIs - Refactored
function updateFinanceKPIs(data) {
    const balance = data.binance_balance_usd || data.spot_balance_usd || 0;
    // Bot bakiyesi: bot detay state panel ile aynı kaynak (current_usd / bots_balance_usd)
    let totalBotBalance = (data.account && data.account.bots_balance_usd != null && Number.isFinite(data.account.bots_balance_usd))
        ? data.account.bots_balance_usd
        : (data.bots_balance_usd != null && Number.isFinite(data.bots_balance_usd) ? data.bots_balance_usd : 0);
    if (totalBotBalance === 0 && data.bots && Array.isArray(data.bots)) {
        data.bots.forEach(b => {
            const cu = b.current_usd != null && Number.isFinite(b.current_usd) ? b.current_usd : 0;
            totalBotBalance += cu;
        });
    }
    if (totalBotBalance === 0 && data.bot_summary && Array.isArray(data.bot_summary)) {
        data.bot_summary.forEach(bot => {
            const cu = bot.current_usd != null && Number.isFinite(bot.current_usd) ? bot.current_usd : ((bot.budget_usd || bot.initial_usd || 0) + (bot.total_pnl_usd || bot.total_pnl || bot.pnl_30d || 0));
            totalBotBalance += cu;
        });
    }
    var account = data.account || {};
    var hasDailyKpi = (account.daily_wallet_pnl_usd !== undefined && account.daily_wallet_pnl_usd !== null) || (account.daily_bot_pnl_usd !== undefined && account.daily_bot_pnl_usd !== null)
        || (data.daily_wallet_pnl_usd !== undefined && data.daily_wallet_pnl_usd !== null) || (data.daily_bot_pnl_usd !== undefined && data.daily_bot_pnl_usd !== null);
    var dailyBotPnl = account.daily_bot_pnl_usd ?? data.daily_bot_pnl_usd ?? data.today?.pnl ?? 0;
    var dailyWalletPnl = account.daily_wallet_pnl_usd ?? data.daily_wallet_pnl_usd ?? 0;
    var baseVal = data.initial_value || data.total_usd_value || 1;

    // Ortak KPI şeridi (tek kaynak): Cüzdan, Cüzdan PnL, Botlar Bakiye, Botlar PnL
    var walletEl = document.getElementById('kpiCuzdan');
    if ((typeof State !== 'undefined' && State.isTestAccount) || (account && account.is_test_account)) {
        if (typeof updateTestAccountKpiCuzdanFromStrip === 'function') updateTestAccountKpiCuzdanFromStrip();
    } else {
        updateKpiCuzdanBalance(walletEl, balance);
    }
    applyWalletStaleWarningEl(document.getElementById('kpiCuzdanLive'));
    if (typeof State !== 'undefined' && State.isTestAccount) {
        /* Günlük değişim: updateTestAccountKpiCuzdanFromStrip → updateTestAccountCuzdanDailyPnlLive */
    } else {
        updateCuzdanPnlKpi(dailyWalletPnl, account, data);
    }
    if (hasDailyKpi) {
        var botPnlEl = document.getElementById('kpiBotPnl');
        if (botPnlEl) {
            var botTextChanged = setTextIfChanged(botPnlEl, fmtUsd(dailyBotPnl));
            var botColor = dailyBotPnl >= 0 ? '#0ecb81' : '#f6465d';
            if (botPnlEl.style.color !== botColor) botPnlEl.style.color = botColor;
            if (botTextChanged) triggerValueBlink(botPnlEl, dailyBotPnl);
        }
        var pct = (account.daily_bot_pnl_pct != null && Number.isFinite(account.daily_bot_pnl_pct)) || (data.daily_bot_pnl_pct != null && Number.isFinite(data.daily_bot_pnl_pct))
            ? Number(account.daily_bot_pnl_pct ?? data.daily_bot_pnl_pct).toFixed(2) : (baseVal > 0 ? ((dailyBotPnl / baseVal) * 100).toFixed(2) : '0.00');
        patchText('kpiBotPnlPct', (parseFloat(pct) >= 0 ? '+' : '') + pct + '%');
        pe = document.getElementById('kpiBotPnlPct'); if (pe) { var botPctC = parseFloat(pct) >= 0 ? '#0ecb81' : '#f6465d'; if (pe.style.color !== botPctC) pe.style.color = botPctC; }
    }
    // Tüm kpiBotBakiye göstergeleri aynı toplam (bütün botların bakiye toplamı)
    var botBakiyeEls = document.querySelectorAll('#kpiBotBakiye');
    botBakiyeEls.forEach(function (el) {
        el.textContent = fmtUsd(totalBotBalance);
        triggerValueBlink(el, totalBotBalance);
    });
    applyWalletStaleWarningEl(document.getElementById('kpiBotBakiyePct'));

    // Binance varlık strip tek kaynak: assetsState.wallet -> renderAssetsSummary (flicker önleme). Burada DOM güncellemesi yapılmaz.
    _persistKpisStorageCache(account, data);
}

/** Bot detay statePanel TOPLAM K/Z ile aynı kaynak: /api/bots-engine/{id}/live */
function getBotLiveRow(bot) {
    if (!bot || !State.botLiveEquity) return null;
    var botId = String(bot.bot_id || bot.id || '');
    return botId ? State.botLiveEquity[botId] : null;
}

function resolveBotHeroKz(bot) {
    var budget = Number(bot.budget_usd || bot.initial_usd) || 0;
    var row = getBotLiveRow(bot);
    if (row && row.equity != null && Number.isFinite(row.equity) && !row.equity_unavailable) {
        var ic = row.initial_capital > 0 ? row.initial_capital : budget;
        if (row.first_buy_pending === true) {
            return { usd: 0, pct: 0, equity: row.equity, initial: ic };
        }
        var usd = ic > 0 ? row.equity - ic : null;
        var pct = row.pnl_pct != null && Number.isFinite(Number(row.pnl_pct))
            ? Number(row.pnl_pct)
            : (usd != null && ic > 0 ? (usd / ic) * 100 : null);
        return { usd: usd, pct: pct, equity: row.equity, initial: ic };
    }
    var currentUsd = resolveBotCurrentUsd(bot);
    if (currentUsd != null && budget > 0) {
        var usdFb = currentUsd - budget;
        var pctFb = bot.total_pnl_pct != null && Number.isFinite(Number(bot.total_pnl_pct))
            ? Number(bot.total_pnl_pct)
            : (usdFb / budget) * 100;
        return { usd: usdFb, pct: pctFb, equity: currentUsd, initial: budget };
    }
    if (bot.total_pnl_usd != null && Number.isFinite(bot.total_pnl_usd)) {
        var usdSnap = Number(bot.total_pnl_usd);
        var pctSnap = bot.total_pnl_pct != null && Number.isFinite(Number(bot.total_pnl_pct))
            ? Number(bot.total_pnl_pct)
            : (budget > 0 ? (usdSnap / budget) * 100 : null);
        return { usd: usdSnap, pct: pctSnap, equity: currentUsd, initial: budget };
    }
    if (botNeedsLiveEquity(bot) && !_financeBotsLiveHydrated) {
        return { usd: null, pct: null, equity: null, initial: budget };
    }
    return { usd: 0, pct: 0, equity: currentUsd, initial: budget };
}

function resolveBotRowPnlPct(bot, rowPnl) {
    var kz = resolveBotHeroKz(bot);
    if (kz.pct != null && Number.isFinite(kz.pct)) return kz.pct;
    var budget = Number(bot.budget_usd || bot.initial_usd) || 0;
    if (bot.total_pnl_pct != null && Number.isFinite(Number(bot.total_pnl_pct))) {
        return Number(bot.total_pnl_pct);
    }
    if (rowPnl != null && Number.isFinite(Number(rowPnl)) && budget > 0) {
        return (Number(rowPnl) / budget) * 100;
    }
    return null;
}

/** bot.html formatHeroKzStr ile aynı: +$0.41 +0.75% */
function formatHeroKzDisplay(usd, pct, initialCapital) {
    if (usd == null || !Number.isFinite(Number(usd))) return '—';
    var s = fmtSignedUsd(Number(usd));
    var p = pct;
    if ((p == null || !Number.isFinite(Number(p))) && initialCapital > 0) {
        p = (Number(usd) / initialCapital) * 100;
    }
    if (p != null && Number.isFinite(Number(p))) {
        s += ' ' + (Number(p) >= 0 ? '+' : '') + Number(p).toFixed(2) + '%';
    }
    return s;
}

function fmtSignedUsdWithPct(pnl, pct, initialCapital) {
    return formatHeroKzDisplay(pnl, pct, initialCapital != null ? initialCapital : 0);
}

function isBotWaitingFirstBuy(bot) {
    if (!bot) return false;
    var st = (bot.status || '').toLowerCase();
    if (st !== 'running') return false;
    var ds = (bot.display_status || '').toLowerCase();
    if (ds === 'starting') return true;
    var botId = String(bot.bot_id || bot.id || '');
    var liveRow = botId && State.botLiveEquity && State.botLiveEquity[botId];
    if (liveRow && liveRow.first_buy_pending === true) return true;
    if (liveRow && liveRow.first_buy_pending === false) return false;
    if (liveRow && liveRow.base_balance != null && Number(liveRow.base_balance) > 0) return false;
    if (bot.first_buy_pending === true) return true;
    if (bot.initial_allocation_done === true) return false;
    var base = Number(bot.base_balance);
    if (Number.isFinite(base) && base > 0) return false;
    return true;
}

function getFinanceBotHealthStatus(bot) {
    var botId = String((bot && (bot.bot_id || bot.id)) || '');
    var info = (botId && typeof _financeBotsHealthCache !== 'undefined') ? _financeBotsHealthCache[botId] : null;
    var level = normalizeFinanceBotsTabAlertLevel(info && info.level);
    var message = info && (info.message || info.title);
    if (!level && bot) {
        level = normalizeFinanceBotsTabAlertLevel(bot.health_alert_level || bot.health_level);
        if (!message && Array.isArray(bot.health_alerts) && bot.health_alerts.length) {
            var hasCrit = bot.health_alerts.some(function (a) { return a && String(a.level || '').toLowerCase() === 'critical'; });
            var hasWarn = bot.health_alerts.some(function (a) { return a && String(a.level || '').toLowerCase() === 'warn'; });
            level = normalizeFinanceBotsTabAlertLevel(hasCrit && hasWarn ? 'both' : (hasCrit ? 'critical' : (hasWarn ? 'warn' : '')));
            message = (bot.health_alerts[0] && (bot.health_alerts[0].message || bot.health_alerts[0].title)) || message;
        }
    }
    return { level: level, message: message || '' };
}

function getFinanceBotStatusMeta(bot) {
    if (typeof isDashboardServerUnreachable === 'function' && isDashboardServerUnreachable()
        && typeof isFinanceBotRunningForHealth === 'function' && isFinanceBotRunningForHealth(bot)) {
        return { text: 'HATA', className: 'mevcut-botlar-status--error', title: 'Sunucuya ulaşılamıyor; bot durumu güvenli hata olarak izleniyor. Bağlantı düzelene kadar detay loglarını kontrol edin.' };
    }
    var health = getFinanceBotHealthStatus(bot);
    if (typeof isFinanceBotRunningForHealth === 'function' && isFinanceBotRunningForHealth(bot)
        && (health.level === 'crit' || health.level === 'both')) {
        return {
            text: 'HATA',
            className: 'mevcut-botlar-status--error',
            title: health.message || 'Botta kritik sağlık uyarısı var. Binance/API/IP bağlantısı düzelene kadar hata durumunda izlenir.'
        };
    }
    if (isBotWaitingFirstBuy(bot)) {
        return { text: 'ALIM BEKLİYOR', className: 'mevcut-botlar-status--waiting' };
    }
    var stRaw = (bot.status || 'STOPPED').toUpperCase();
    var ds = (bot.display_status || '').toLowerCase();
    var key = ds === 'starting' ? 'starting' : stRaw.toLowerCase();
    var labels = {
        running: 'ÇALIŞIYOR',
        stopped: 'DURDURULDU',
        paused: 'DURAKLATILDI',
        paused_error: 'Hata (duraklatıldı)',
        paused_insufficient_balance: 'Yetersiz bakiye',
        waiting: 'BEKLİYOR',
        starting: 'BAŞLATILIYOR',
        error: 'HATA'
    };
    var text = labels[key] || stRaw;
    if (key === 'running') return { text: text, className: 'mevcut-botlar-status--running' };
    if (key === 'paused' || key === 'paused_insufficient_balance' || key === 'waiting' || key === 'starting') {
        return { text: text, className: 'mevcut-botlar-status--waiting' };
    }
    return { text: text, className: 'mevcut-botlar-status--stopped' };
}

// Anasayfa + Botlar sekmesi Mevcut Botlar: aynı tablo; financeBotsList (Anasayfa) ve financeBotsListBots (Botlar) birlikte güncellenir
var _financeBotsStructureSignature = null;
var _financeBotsIdsSignature = null;
var _financeBotsLiveHydrated = false;
var _financeBotsLivePollPromise = null;
var _financeBotsLiveSig = '';
var _financeBotsHealthCache = {};
var _financeBotsHealthPollPromise = null;
var FINANCE_BOTS_HEALTH_POLL_MS = 15000;
var FINANCE_BOT_ROW_ALERT_CLASSES = ['mevcut-bot-row-alert-warn', 'mevcut-bot-row-alert-crit', 'mevcut-bot-row-alert-both'];
var FINANCE_BOTS_TAB_ALERT_CLASSES = ['bots-tab-alert-warn', 'bots-tab-alert-crit', 'bots-tab-alert-both'];
var _financeBotsMetricsCache = {};
var _financeBotsModuleLoadedAt = Date.now();

function isFinanceBotsTestAccountContext() {
    if (typeof State === 'undefined') return false;
    var code = String(State.accountCode || '').trim().toUpperCase();
    return !!State.isTestAccount || /^TEST/.test(code);
}

function isFinanceBotAccountWalletStaleAlert(alert) {
    var code = String((alert && (alert.code || alert.health_code || alert.error_code)) || '').toUpperCase();
    return code === 'WALLET_SNAPSHOT_STALE';
}

function financeBotRowHealthAlerts(alerts) {
    return (Array.isArray(alerts) ? alerts : []).filter(function (a) {
        return a && !isFinanceBotAccountWalletStaleAlert(a);
    });
}

function isStoredFinanceBotWalletStaleAlert(row) {
    var msg = String((row && row.message) || '').toLowerCase();
    return msg.indexOf('cüzdan verisi güncel değil') >= 0
        || msg.indexOf('cuzdan verisi guncel degil') >= 0
        || msg.indexOf('wallet snapshot stale') >= 0
        || msg.indexOf('wallet_snapshot_stale') >= 0;
}

function financeBotsSessionCacheKey(accountId) {
    return 'financeBotsTable_' + (accountId || '');
}

function loadFinanceBotsMetricsCache(accountId) {
    try {
        var raw = sessionStorage.getItem(financeBotsSessionCacheKey(accountId));
        if (!raw) return {};
        var data = JSON.parse(raw);
        return (data && data.metrics && typeof data.metrics === 'object') ? data.metrics : {};
    } catch (e) {
        return {};
    }
}

function getFinanceBotCachedMetric(bot) {
    var id = String((bot && (bot.bot_id || bot.id)) || '');
    if (!id) return null;
    if (!_financeBotsMetricsCache[id] && State.accountId) {
        _financeBotsMetricsCache = loadFinanceBotsMetricsCache(State.accountId);
    }
    return _financeBotsMetricsCache[id] || null;
}

function hydrateBotsWithMetricsCache(bots) {
    if (!Array.isArray(bots) || !bots.length) return bots || [];
    if (!Object.keys(_financeBotsMetricsCache).length && State.accountId) {
        _financeBotsMetricsCache = loadFinanceBotsMetricsCache(State.accountId);
    }
    return bots.map(function (bot) {
        var id = String(bot.bot_id || bot.id || '');
        var cached = id ? _financeBotsMetricsCache[id] : null;
        if (!cached) return bot;
        var out = Object.assign({}, bot);
        if ((out.current_usd == null || !Number.isFinite(out.current_usd)) && cached.current_usd != null) {
            out.current_usd = cached.current_usd;
        }
        if ((out.total_pnl_usd == null || !Number.isFinite(out.total_pnl_usd)) && cached.total_pnl_usd != null) {
            out.total_pnl_usd = cached.total_pnl_usd;
        }
        if ((out.total_cycles_completed == null || !Number.isFinite(out.total_cycles_completed)) && cached.cycles != null) {
            out.total_cycles_completed = cached.cycles;
        }
        return out;
    });
}

function persistFinanceBotsSessionCache(bots) {
    if (!State.accountId || !Array.isArray(bots) || !bots.length) return;
    if (typeof DashboardAccountScope !== 'undefined') {
        bots = DashboardAccountScope.filterBotsForAccount(bots, State.accountId);
        if (!bots.length) return;
    }
    try {
        var metrics = {};
        bots.forEach(function (bot) {
            var id = String(bot.bot_id || bot.id || '');
            if (!id) return;
            var currentUsd = resolveBotCurrentUsd(bot);
            if (currentUsd == null && bot.current_usd != null && Number.isFinite(bot.current_usd)) currentUsd = bot.current_usd;
            if (currentUsd == null) return;
            var budget = Number(bot.budget_usd || bot.initial_usd) || 0;
            metrics[id] = {
                current_usd: currentUsd,
                total_pnl_usd: budget > 0 ? currentUsd - budget : (bot.total_pnl_usd != null ? Number(bot.total_pnl_usd) : 0),
                cycles: resolveBotCycles(bot)
            };
        });
        _financeBotsMetricsCache = metrics;
        var slim = bots.map(function (b) {
            return {
                bot_id: b.bot_id || b.id,
                id: b.bot_id || b.id,
                symbol: b.symbol,
                status: b.status,
                display_status: b.display_status,
                initial_allocation_done: b.initial_allocation_done,
                health_alert_level: null,
                health_alerts: [],
                budget_usd: b.budget_usd || b.initial_usd,
                initial_usd: b.initial_usd || b.budget_usd,
                current_usd: b.current_usd,
                total_pnl_usd: b.total_pnl_usd,
                total_pnl_pct: b.total_pnl_pct,
                total_cycles_completed: b.total_cycles_completed,
                cycle_id: b.cycle_id,
                config: b.config,
                config_json: b.config_json
            };
        });
        sessionStorage.setItem(financeBotsSessionCacheKey(State.accountId), JSON.stringify({
            ts: Date.now(),
            bots: slim,
            metrics: metrics
        }));
        try {
            localStorage.setItem(financeBotsSessionCacheKey(State.accountId), JSON.stringify({
                ts: Date.now(),
                bots: slim,
                metrics: metrics
            }));
        } catch (e2) { /* quota */ }
    } catch (e) {}
}

function restoreFinanceBotsFromSessionCache(accountId) {
    if (!accountId) return false;
    if (typeof DashboardAccountScope !== 'undefined' && !DashboardAccountScope.isActiveAccount(accountId)) return false;
    try {
        var raw = sessionStorage.getItem(financeBotsSessionCacheKey(accountId))
            || localStorage.getItem(financeBotsSessionCacheKey(accountId));
        if (!raw) {
            if (typeof adoptEarlyBotsDomBoot === 'function' && adoptEarlyBotsDomBoot(accountId)) {
                return true;
            }
            return false;
        }
        var data = JSON.parse(raw);
        if (!data || typeof data !== 'object') return false;
        if (data.ts && Date.now() - data.ts > 86400000) return false;
        if (data.metrics && typeof data.metrics === 'object') {
            _financeBotsMetricsCache = data.metrics;
        }
        if (data.bots && Array.isArray(data.bots) && data.bots.length) {
            var scopedBots = (typeof DashboardAccountScope !== 'undefined')
                ? DashboardAccountScope.filterBotsForAccount(data.bots, accountId)
                : data.bots;
            if (!scopedBots.length) {
                clearFinanceBotsSessionCache(accountId);
                return false;
            }
            State.bots = hydrateBotsWithMetricsCache(scopedBots.map(function (bot) {
                return Object.assign({}, bot, {
                    health_alert_level: null,
                    health_alerts: []
                });
            }));
            if (Object.keys(_financeBotsMetricsCache).length > 0) _financeBotsLiveHydrated = true;
            if (typeof restoreFinanceBotsDomFromSessionCache === 'function' && restoreFinanceBotsDomFromSessionCache(accountId, State.bots)) {
                patchFinanceBotsMetrics(State.bots);
                updateFinanceBotsLivePrices();
                if (!_financeBotsLiveHydrated) ensureFinanceBotsLiveEquity();
                if (typeof ensureFinanceBotsHealthPolling === 'function') ensureFinanceBotsHealthPolling();
                return true;
            }
            if (typeof renderFinanceBots === 'function') renderFinanceBots(State.bots);
            return true;
        }
        return !!(data.metrics && typeof data.metrics === 'object');
    } catch (e) {
        return false;
    }
}

function clearFinanceBotsUiState(accountId) {
    State.bots = [];
    _financeBotsMetricsCache = {};
    _financeBotsStructureSignature = null;
    _financeBotsIdsSignature = null;
    _financeBotsHealthCache = {};
    _financeBotsLiveSig = '';
    _financeBotsLiveHydrated = true;
    State.botLiveEquity = {};
    if (accountId) clearFinanceBotsSessionCache(accountId);
}

function _financeBotsPanelHasRows(el) {
    return !!(el && (el.querySelector('tr[data-bot-id]') || el.querySelector('.mevcut-botlar-mobile-card[data-bot-id]')));
}

function _financeBotsTableHasRows() {
    return _financeBotsPanelHasRows(document.getElementById('financeBotsList'))
        || _financeBotsPanelHasRows(document.getElementById('financeBotsListBots'));
}

/** Anasayfa tablosu dolu, Botlar sekmesi boşsa (erken return bug) — Botlar panelini senkronize et. */
function _financeBotsBothTablesReady() {
    var home = document.getElementById('financeBotsList');
    var tab = document.getElementById('financeBotsListBots');
    if (!tab) return _financeBotsPanelHasRows(home);
    return _financeBotsPanelHasRows(home) && _financeBotsPanelHasRows(tab);
}

function bindFinanceBotsRowClicks(container) {
    if (!container) return;
    container.querySelectorAll('a.mevcut-botlar-detay-btn').forEach(function (a) {
        a.addEventListener('click', function (e) {
            e.preventDefault();
            e.stopPropagation();
            var href = this.getAttribute('href');
            if (href) {
                if (typeof persistDashboardBeforeBotDetailNav === 'function') persistDashboardBeforeBotDetailNav();
                location.href = href;
            }
        });
    });
    container.querySelectorAll('tbody tr').forEach(function (tr) {
        tr.addEventListener('click', function (e) {
            if (e.target.tagName === 'A' || e.target.closest('a')) return;
            var botId = tr.dataset.botId;
            var page = tr.dataset.detailPage || '/ui/bot.html';
            var q = State.accountCode ? 'account_code=' + encodeURIComponent(State.accountCode) : 'account_id=' + State.accountId;
            if (typeof persistDashboardBeforeBotDetailNav === 'function') persistDashboardBeforeBotDetailNav();
            var symNav = (tr.dataset.symbol || '').trim();
            var symQ = symNav ? '&symbol=' + encodeURIComponent(symNav) : '';
            location.href = page + '?bot_id=' + botId + symQ + '&' + q;
        });
    });
    container.querySelectorAll('.mevcut-botlar-mobile-card').forEach(function (card) {
        card.addEventListener('click', function (e) {
            if (e.target.tagName === 'A' || e.target.closest('a')) return;
            var botId = card.dataset.botId;
            var page = card.dataset.detailPage || '/ui/bot.html';
            var q = State.accountCode ? 'account_code=' + encodeURIComponent(State.accountCode) : 'account_id=' + State.accountId;
            if (typeof persistDashboardBeforeBotDetailNav === 'function') persistDashboardBeforeBotDetailNav();
            var symNav = (card.dataset.symbol || '').trim();
            var symQ = symNav ? '&symbol=' + encodeURIComponent(symNav) : '';
            location.href = page + '?bot_id=' + botId + symQ + '&' + q;
        });
    });
}

function syncFinanceBotsTabFromHome() {
    var home = document.getElementById('financeBotsList');
    var tab = document.getElementById('financeBotsListBots');
    if (!tab) return;
    if (_financeBotsPanelHasRows(tab)) return;
    if (_financeBotsPanelHasRows(home) && home.innerHTML) {
        tab.innerHTML = home.innerHTML;
        bindFinanceBotsRowClicks(tab);
        if (typeof updateFinanceBotsLivePrices === 'function') updateFinanceBotsLivePrices();
        if (typeof applyFinanceBotsLiveEquityToDom === 'function') applyFinanceBotsLiveEquityToDom();
        return;
    }
    if (State.bots && State.bots.length && typeof renderFinanceBots === 'function') {
        if (isBotsTabCacheReady() && _financeBotsPanelHasRows(tab)) {
            patchFinanceBotsMetrics(State.bots);
        } else {
            renderFinanceBots(State.bots);
        }
    }
}

function clearFinanceBotsSessionCache(accountId) {
    if (!accountId) return;
    try {
        sessionStorage.removeItem(financeBotsSessionCacheKey(accountId));
        localStorage.removeItem(financeBotsSessionCacheKey(accountId));
        sessionStorage.removeItem(botsTabCacheSessionKey(accountId));
        sessionStorage.removeItem(financeBotsDomCacheKey(accountId));
        localStorage.removeItem(financeBotsDomCacheKey(accountId));
    } catch (e) {}
    _financeBotsMetricsCache = {};
    _financeBotsStructureSignature = null;
    _financeBotsIdsSignature = null;
    if (State.accountId === accountId && typeof clearBotsTabCache === 'function') clearBotsTabCache();
}
window.clearFinanceBotsSessionCache = clearFinanceBotsSessionCache;

function resetFinanceBotsLiveCache(bots) {
    var sig = (bots || []).map(function (b) { return String(b.bot_id || b.id || ''); }).join(',');
    if (sig === _financeBotsLiveSig) return;
    _financeBotsLiveSig = sig;
    State.botLiveEquity = {};
    _financeBotsLiveHydrated = Object.keys(_financeBotsMetricsCache).length > 0;
    _financeBotsLivePollPromise = null;
}

function resolveFinanceBotDisplayPrice(botId, sym) {
    var mp = resolveMarketLivePrice(sym);
    if (mp != null) return mp;
    if (botId != null && State.botLiveEquity) {
        var row = State.botLiveEquity[String(botId)];
        if (row && row.last_price != null && Number.isFinite(row.last_price) && row.last_price > 0) {
            return row.last_price;
        }
    }
    return null;
}

function resolveBotLivePrice(sym, botId) {
    return resolveFinanceBotDisplayPrice(botId, sym);
}

function seedMarketStorePriceFromBotLive(botId, live) {
    if (!live || live.last_price == null || !Number.isFinite(Number(live.last_price)) || Number(live.last_price) <= 0) return;
    if (!State.bots || !window.marketStore) return;
    var sym = null;
    State.bots.some(function (b) {
        if (String(b.bot_id || b.id || '') !== String(botId)) return false;
        sym = (b.symbol || '').toUpperCase();
        return !!sym && sym !== 'MULTI';
    });
    if (!sym) return;
    var p = Number(live.last_price);
    if (typeof window.marketStore.updatePrice === 'function') window.marketStore.updatePrice(sym, p);
    if (typeof window.marketStore.updateMini === 'function') window.marketStore.updateMini(sym, { last: p });
}

function botNeedsLiveEquity(bot) {
    if (!bot) return false;
    var st = (bot.status || '').toLowerCase();
    var ds = (bot.display_status || '').toLowerCase();
    if (st === 'running' || st === 'paused' || st === 'paused_insufficient_balance') return true;
    if (ds === 'starting' || ds === 'running') return true;
    return false;
}

function resolveBotLiveEquity(bot) {
    if (!bot || !State.botLiveEquity) return null;
    var botId = String(bot.bot_id || bot.id || '');
    if (!botId) return null;
    var row = State.botLiveEquity[botId];
    if (!row || row.equity == null || !Number.isFinite(row.equity) || row.equity_unavailable) return null;
    return row.equity;
}

function resolveBotCurrentUsd(bot) {
    var row = getBotLiveRow(bot);
    if (row && row.equity != null && Number.isFinite(row.equity) && !row.equity_unavailable) {
        return row.equity;
    }
    if (botNeedsLiveEquity(bot)) {
        if (_financeBotsLiveHydrated) {
            var live = resolveBotLiveEquity(bot);
            if (live != null) return live;
        }
        if (bot.current_usd != null && Number.isFinite(bot.current_usd)) return bot.current_usd;
        var cached = getFinanceBotCachedMetric(bot);
        if (cached && cached.current_usd != null && Number.isFinite(cached.current_usd)) return cached.current_usd;
        return null;
    }
    if (bot.current_usd != null && Number.isFinite(bot.current_usd)) return bot.current_usd;
    return 0;
}

function resolveBotRowPnl(bot, currentUsd) {
    var kz = resolveBotHeroKz(bot);
    if (kz.usd != null && Number.isFinite(kz.usd)) return kz.usd;
    var budget = Number(bot.budget_usd || bot.initial_usd) || 0;
    if (currentUsd != null && budget > 0) return currentUsd - budget;
    if (bot.total_pnl_usd != null && Number.isFinite(bot.total_pnl_usd)) return Number(bot.total_pnl_usd);
    var cached = getFinanceBotCachedMetric(bot);
    if (cached && cached.total_pnl_usd != null && Number.isFinite(cached.total_pnl_usd)) return cached.total_pnl_usd;
    if (botNeedsLiveEquity(bot) && !_financeBotsLiveHydrated) return null;
    return Number(bot.total_pnl_usd) || 0;
}

function resolveBotCyclesDisplay(bot) {
    var cycles = resolveBotCycles(bot);
    if (cycles != null && cycles !== '' && Number(cycles) > 0) return String(cycles);
    var cached = getFinanceBotCachedMetric(bot);
    if (cached && cached.cycles != null && cached.cycles !== '') return String(cached.cycles);
    if (botNeedsLiveEquity(bot) && !_financeBotsLiveHydrated) return '—';
    return cycles != null && cycles !== '' ? String(cycles) : '—';
}

function applyFinanceBotsLiveEquityToDom() {
    if (!State.bots || !State.bots.length) return;
    State.bots.forEach(function (bot) {
        var botId = String(bot.bot_id || bot.id || '');
        if (!botId) return;
        var kz = resolveBotHeroKz(bot);
        var currentUsd = kz.equity != null ? kz.equity : resolveBotCurrentUsd(bot);
        var pnl = kz.usd;
        var pnlPct = kz.pct;
        var sc = pnl != null && pnl >= 0 ? '#0ecb81' : (pnl != null ? '#f6465d' : 'var(--ds-text-secondary)');
        var balanceTxt = currentUsd != null ? fmtUsd(currentUsd) : '—';
        var pnlTxt = formatHeroKzDisplay(pnl, pnlPct, kz.initial || Number(bot.budget_usd || bot.initial_usd) || 0);
        var cyclesTxt = resolveBotCyclesDisplay(bot);
        document.querySelectorAll('.finance-bot-balance[data-bot-id="' + botId + '"]').forEach(function (cell) {
            if (setTextIfChanged(cell, balanceTxt)) { /* patched */ }
            cell.setAttribute('data-balance', currentUsd != null ? String(currentUsd) : '');
            cell.classList.toggle('finance-bot-metric-pending', balanceTxt === '—');
        });
        var statusMeta = getFinanceBotStatusMeta(bot);
        document.querySelectorAll('tr[data-bot-id="' + botId + '"]').forEach(function (row) {
            var tds = row.querySelectorAll('td');
            if (tds.length >= 3) {
                var statusEl = tds[2].querySelector('.mevcut-botlar-status');
                if (statusEl) {
                    setTextIfChanged(statusEl, statusMeta.text);
                    var statusCls = 'mevcut-botlar-status ' + statusMeta.className;
                    if (statusEl.className !== statusCls) statusEl.className = statusCls;
                    if (statusMeta.title) statusEl.setAttribute('title', statusMeta.title);
                    else statusEl.removeAttribute('title');
                }
            }
            if (tds.length >= 7) {
                setTextIfChanged(tds[5], pnlTxt);
                if (tds[5].style.color !== sc) tds[5].style.color = sc;
                setTextIfChanged(tds[6], cyclesTxt);
            }
        });
        document.querySelectorAll('.mevcut-botlar-mobile-card[data-bot-id="' + botId + '"] .mevcut-botlar-mobile-stat-value').forEach(function (el) {
            var label = el.parentElement && el.parentElement.querySelector('.mevcut-botlar-mobile-stat-label');
            if (!label) return;
            if ((label.textContent || '') === 'Bakiye') setTextIfChanged(el, balanceTxt);
            if ((label.textContent || '') === 'K/Z' || (label.textContent || '') === 'Toplam K/Z') {
                setTextIfChanged(el, pnlTxt);
                if (el.style.color !== sc) el.style.color = sc;
            }
            if ((label.textContent || '') === 'Tur') setTextIfChanged(el, cyclesTxt);
        });
        document.querySelectorAll('.mevcut-botlar-mobile-card[data-bot-id="' + botId + '"] .mevcut-botlar-status').forEach(function (el) {
            setTextIfChanged(el, statusMeta.text);
            var statusCls = 'mevcut-botlar-status ' + statusMeta.className;
            if (el.className !== statusCls) el.className = statusCls;
            if (statusMeta.title) el.setAttribute('title', statusMeta.title);
            else el.removeAttribute('title');
        });
    });
    if (typeof State !== 'undefined' && State.isTestAccount) {
        if (typeof updateTestAccountStripFromTable === 'function') {
            updateTestAccountStripFromTable(document.getElementById('varliklarTableBody'));
        } else if (typeof updateTestAccountKpiCuzdanFromStrip === 'function') {
            updateTestAccountKpiCuzdanFromStrip();
        }
    }
    if (typeof scheduleLeaderboardSyncFromBots === 'function') scheduleLeaderboardSyncFromBots();
    if (typeof updateFinanceBotsLivePrices === 'function') updateFinanceBotsLivePrices();
}

function applyFinanceBotLiveSnapshot(botId, live) {
    if (!live || typeof live !== 'object') return;
    if (live.equity == null || isNaN(live.equity)) return;
    if (!State.botLiveEquity) State.botLiveEquity = {};
    var ic = live.initial_capital != null && !isNaN(live.initial_capital)
        ? Number(live.initial_capital) : 0;
    var eq = Number(live.equity);
    State.botLiveEquity[String(botId)] = {
        equity: eq,
        equity_unavailable: !!live.equity_unavailable,
        first_buy_pending: live.first_buy_pending === true,
        base_balance: live.base_balance != null ? Number(live.base_balance) : null,
        initial_capital: ic,
        pnl_pct: live.pnl_pct != null && !isNaN(live.pnl_pct) ? Number(live.pnl_pct) : null,
        last_price: live.last_price != null && !isNaN(live.last_price) ? Number(live.last_price) : null,
        ts: Date.now()
    };
    seedMarketStorePriceFromBotLive(botId, live);
}

async function pollFinanceBotsLiveEquity() {
    if (document.hidden || !State.accountId || !window.apiClient || !State.bots || !State.bots.length) {
        _financeBotsLiveHydrated = true;
        return;
    }
    var ids = [];
    State.bots.forEach(function (bot) {
        if (!botNeedsLiveEquity(bot)) return;
        var botId = bot.bot_id || bot.id;
        if (botId) ids.push(String(botId));
    });
    if (!ids.length) {
        _financeBotsLiveHydrated = true;
        return;
    }
    var accountQ = State.accountCode
        ? 'account_code=' + encodeURIComponent(State.accountCode)
        : 'account_id=' + encodeURIComponent(State.accountId);
    var batchUrl = '/api/bots-engine/batch/live?' + accountQ + '&bot_ids=' + encodeURIComponent(ids.join(','));
    try {
        var res = await window.apiClient.get(batchUrl);
        var liveMap = (res && res.live) || {};
        ids.forEach(function (botId) {
            applyFinanceBotLiveSnapshot(botId, liveMap[String(botId)]);
        });
    } catch (e) {
        var q = State.accountCode
            ? '?account_code=' + encodeURIComponent(State.accountCode)
            : '?account_id=' + encodeURIComponent(State.accountId);
        await Promise.all(ids.map(function (botId) {
            return window.apiClient.get('/api/bots-engine/' + botId + '/live' + q)
                .then(function (live) { applyFinanceBotLiveSnapshot(botId, live); })
                .catch(function () {});
        }));
    }
    _financeBotsLiveHydrated = true;
    applyFinanceBotsLiveEquityToDom();
    if (typeof updateFinanceBotsLivePrices === 'function') updateFinanceBotsLivePrices();
    persistFinanceBotsSessionCache(State.bots);
}

function ensureFinanceBotsLiveEquity() {
    if (_financeBotsLiveHydrated) return Promise.resolve();
    if (_financeBotsLivePollPromise) return _financeBotsLivePollPromise;
    _financeBotsLivePollPromise = pollFinanceBotsLiveEquity().finally(function () {
        _financeBotsLivePollPromise = null;
    });
    return _financeBotsLivePollPromise;
}

function resolveBotCycles(bot) {
    var cid = bot.cycle_id;
    if (cid != null && Number.isFinite(Number(cid)) && Number(cid) > 0) return Number(cid);
    var tc = bot.total_cycles_completed;
    if (tc != null && Number.isFinite(tc) && tc > 0) return tc;
    return 0;
}

function financeBotsStructureSignature(bots, sortBy) {
    return (bots || []).map(function (b) {
        return [
            b.bot_id || b.id,
            (b.status || '').toLowerCase(),
            b.display_status || '',
            (b.symbol || '').toUpperCase(),
            b.initial_allocation_done ? 1 : 0
        ].join(':');
    }).join('|') + '|' + (sortBy || 'best');
}

function isFinanceBotRunningForHealth(bot) {
    if (!bot) return false;
    var st = (bot.status || '').toLowerCase();
    if (st !== 'running') return false;
    var ds = (bot.display_status || '').toLowerCase();
    return ds !== 'stopped' && ds !== 'paused' && ds !== 'paused_error' && ds !== 'paused_insufficient_balance';
}

function isDashboardServerUnreachable() {
    return typeof window.isServerUnreachable === 'function' && window.isServerUnreachable();
}
window.isDashboardServerUnreachable = isDashboardServerUnreachable;

function isDashboardFetchServerError(error) {
    if (!error) return false;
    if (isDashboardServerUnreachable()) return true;
    var status = Number(error.status) || 0;
    if (status === 0 || status === 502 || status === 503 || status === 504) return true;
    var code = String(error.error_code || '').toUpperCase();
    return code === 'NETWORK_ERROR' || code === 'BAD_GATEWAY' || code === 'SERVICE_UNAVAILABLE' || code === 'GATEWAY_TIMEOUT';
}

function applyFinanceBotsServerOfflineState() {
    if (!isDashboardServerUnreachable()) return false;
    applyFinanceBotsHealthAlertsToDom();
    applyFinanceBotsLiveEquityToDom();
    return true;
}
window.applyFinanceBotsServerOfflineState = applyFinanceBotsServerOfflineState;

function clearFinanceBotsServerOfflineState() {
    var cleared = false;
    Object.keys(_financeBotsHealthCache).forEach(function (id) {
        if (_financeBotsHealthCache[id] && _financeBotsHealthCache[id].serverOffline) {
            delete _financeBotsHealthCache[id];
            cleared = true;
        }
    });
    if (!cleared) return;
    applyFinanceBotsHealthAlertsToDom();
    applyFinanceBotsLiveEquityToDom();
    if (typeof pollFinanceBotsHealth === 'function') pollFinanceBotsHealth();
}
window.clearFinanceBotsServerOfflineState = clearFinanceBotsServerOfflineState;

function classifyFinanceBotHealth(botId, healthData) {
    if (healthData && Array.isArray(healthData.alerts)) {
        healthData = Object.assign({}, healthData, { alerts: financeBotRowHealthAlerts(healthData.alerts) });
    }
    if (window.BotHealthAlerts && typeof window.BotHealthAlerts.classifyRowAlerts === 'function') {
        return window.BotHealthAlerts.classifyRowAlerts(botId, healthData, true);
    }
    var alerts = financeBotRowHealthAlerts(healthData && healthData.alerts);
    var hasCrit = alerts.some(function (a) { return a && String(a.level || '').toLowerCase() === 'critical'; });
    var hasWarn = alerts.some(function (a) { return a && String(a.level || '').toLowerCase() === 'warn'; });
    if (healthData && healthData.connectivity_ok === false) hasCrit = true;
    if (hasCrit && hasWarn) return { level: 'both' };
    if (hasCrit) return { level: 'critical' };
    if (hasWarn) return { level: 'warn' };
    return { level: null };
}

function financeBotsHealthAccountKey() {
    if (State.accountCode) return 'code:' + String(State.accountCode);
    if (State.accountId) return 'id:' + String(State.accountId);
    return '';
}

function hydrateFinanceBotsStoredHealthAlerts() {
    if (isFinanceBotsTestAccountContext()) return;
    var stored = {};
    if (window.BotHealthAlerts && typeof window.BotHealthAlerts.getStoredRowAlerts === 'function') {
        stored = Object.assign(
            {},
            window.BotHealthAlerts.getStoredRowAlerts() || {},
            window.BotHealthAlerts.getStoredRowAlerts(financeBotsHealthAccountKey()) || {}
        );
    }
    try {
        var params = new URLSearchParams(location.search);
        var qBotId = String(params.get('health_bot_id') || '').trim();
        var qLevel = String(params.get('health_level') || '').trim().toLowerCase();
        var qTs = Number(params.get('health_ts') || 0);
        if (qBotId && (qLevel === 'critical' || qLevel === 'warn' || qLevel === 'both') && (!qTs || Date.now() - qTs < 120000)) {
            stored[qBotId] = { level: qLevel, query: true };
        }
    } catch (e) {}
    Object.keys(stored).forEach(function (id) {
        if (isStoredFinanceBotWalletStaleAlert(stored[id])) return;
        if (!_financeBotsHealthCache[id] || !_financeBotsHealthCache[id].level) {
            _financeBotsHealthCache[id] = stored[id];
        }
    });
}

function normalizeFinanceBotsTabAlertLevel(level) {
    var lv = String(level || '').toLowerCase();
    if (lv === 'critical' || lv === 'crit') return 'crit';
    if (lv === 'warn' || lv === 'warning') return 'warn';
    if (lv === 'both') return 'both';
    return '';
}

function getFinanceBotsTabAlertTargets() {
    var seen = [];
    var out = [];
    document.querySelectorAll('#btnBotsTab, .dm-tab[data-tab="bots"], [data-mobile-tab="bots"]').forEach(function (el) {
        if (!el || seen.indexOf(el) >= 0) return;
        seen.push(el);
        out.push(el);
    });
    return out;
}

function collectFinanceBotsTabAlertSummary() {
    var ids = [];
    if (Array.isArray(State.bots) && State.bots.length) {
        State.bots.forEach(function (bot) {
            var id = String((bot && (bot.bot_id || bot.id)) || '');
            if (id && ids.indexOf(id) < 0) ids.push(id);
        });
    }
    if (!ids.length) {
        document.querySelectorAll('tr[data-bot-id], .mevcut-botlar-mobile-card[data-bot-id]').forEach(function (el) {
            var id = String(el.getAttribute('data-bot-id') || '');
            if (id && ids.indexOf(id) < 0) ids.push(id);
        });
    }

    var alertLevelsByBot = {};
    ids.forEach(function (id) {
        var info = _financeBotsHealthCache[id];
        var level = normalizeFinanceBotsTabAlertLevel(info && info.level);
        if (level) alertLevelsByBot[id] = level;
    });

    var levels = Object.keys(alertLevelsByBot).map(function (id) { return alertLevelsByBot[id]; });
    var hasWarn = levels.indexOf('warn') >= 0 || levels.indexOf('both') >= 0;
    var hasCrit = levels.indexOf('crit') >= 0 || levels.indexOf('both') >= 0;
    var alertCount = levels.length;
    var mode = '';

    // Yalnızca sarı uyarılar (birden fazla olsa bile) → normal hızda sarı blink.
    // Hızlı blink yalnızca kritik + sarı karışımında.
    if (hasCrit && hasWarn) mode = 'both';
    else if (hasCrit) mode = 'crit';
    else if (hasWarn) mode = 'warn';

    return {
        mode: mode,
        alertCount: alertCount,
        hasWarn: hasWarn,
        hasCrit: hasCrit
    };
}

function updateFinanceBotsTabAlertState() {
    var summary = collectFinanceBotsTabAlertSummary();
    // Global cüzdan gecikmesi bot uyarısı değildir; tab/row blink sadece bot health kaynaklıdır.
    var effectiveMode = summary.mode;
    var title = '';
    if (effectiveMode === 'both') {
        title = 'Botlarda birden fazla veya karışık kritik uyarı var. Botlar sekmesini kontrol edin.';
    } else if (effectiveMode === 'crit') {
        title = 'Botlarda kritik hata var. Botlar sekmesini kontrol edin.';
    } else if (effectiveMode === 'warn') {
        title = 'Botlarda uyarı var. Botlar sekmesini kontrol edin.';
    }

    getFinanceBotsTabAlertTargets().forEach(function (el) {
        FINANCE_BOTS_TAB_ALERT_CLASSES.forEach(function (c) { el.classList.remove(c); });
        if (effectiveMode) {
            if (!Object.prototype.hasOwnProperty.call(el.dataset, 'botsTabBaseTitle')) {
                el.dataset.botsTabBaseTitle = el.getAttribute('title') || '';
            }
            el.classList.add('bots-tab-alert-' + effectiveMode);
            el.setAttribute('title', title);
            el.setAttribute('aria-live', 'polite');
        } else {
            if (Object.prototype.hasOwnProperty.call(el.dataset, 'botsTabBaseTitle')) {
                var baseTitle = el.dataset.botsTabBaseTitle || '';
                if (baseTitle) el.setAttribute('title', baseTitle);
                else el.removeAttribute('title');
                delete el.dataset.botsTabBaseTitle;
            }
            el.removeAttribute('aria-live');
        }
    });
}

function financeBotsWalletStaleInfo() {
    if (isFinanceBotsTestAccountContext()) return null;
    if ((Date.now() - _financeBotsModuleLoadedAt) < 3500) return null;
    if (!assetsState || !assetsState.wallet || assetsState.wallet.keys_configured !== true) return null;
    if (typeof isWalletDataLive === 'function' && isWalletDataLive()) return null;
    var msg = typeof walletStaleStatusText === 'function'
        ? walletStaleStatusText()
        : 'Cüzdan verisi güncel değil';
    return {
        level: 'warn',
        message: msg,
        walletSnapshotStale: true
    };
}

function _syncWalletStaleBotNotice(walletInfo) {
    var msg = walletInfo ? ('⚠ ' + (walletInfo.message || 'Cüzdan verisi güncel değil') + ' — Bakiye bilgisi anlık olmayabilir. Bot işlemleri etkilenmez.') : '';
    ['walletStaleBotNotice', 'walletStaleBotNoticeBotsTab'].forEach(function (elId) {
        var el = document.getElementById(elId);
        if (!el) return;
        if (walletInfo) {
            el.textContent = msg;
            el.style.display = 'flex';
        } else {
            el.style.display = 'none';
            el.textContent = '';
        }
    });
}

function applyFinanceBotsHealthAlertsToDom() {
    hydrateFinanceBotsStoredHealthAlerts();
    if (isDashboardServerUnreachable()) {
        (State.bots || []).filter(isFinanceBotRunningForHealth).forEach(function (bot) {
            var id = String(bot.bot_id || bot.id || '');
            if (id) _financeBotsHealthCache[id] = { level: 'critical', serverOffline: true };
        });
    }
    var walletInfo = financeBotsWalletStaleInfo();
    // Wallet stale durumunu bireysel bot satırlarına değil, panel üstündeki notice'a taşı.
    // Bu sayede sarı satır ↔ boş detay uyuşmazlığı ortadan kalkar.
    _syncWalletStaleBotNotice(walletInfo);
    if (!walletInfo) {
        Object.keys(_financeBotsHealthCache).forEach(function (id) {
            if (_financeBotsHealthCache[id] && _financeBotsHealthCache[id].walletSnapshotStale) {
                delete _financeBotsHealthCache[id];
            }
        });
    }
    document.querySelectorAll('tr[data-bot-id]').forEach(function (tr) {
        var botId = tr.getAttribute('data-bot-id');
        var info = botId ? _financeBotsHealthCache[botId] : null;
        FINANCE_BOT_ROW_ALERT_CLASSES.forEach(function (c) { tr.classList.remove(c); });
        // walletSnapshotStale yalnızca panel notice üzerinden gösterilir, satır renklenmez.
        if (info && info.level && !info.walletSnapshotStale) tr.classList.add('mevcut-bot-row-alert-' + (info.level === 'critical' ? 'crit' : info.level));
    });
    document.querySelectorAll('.mevcut-botlar-mobile-card[data-bot-id]').forEach(function (card) {
        var botId = card.getAttribute('data-bot-id');
        var info = botId ? _financeBotsHealthCache[botId] : null;
        FINANCE_BOT_ROW_ALERT_CLASSES.forEach(function (c) { card.classList.remove(c); });
        if (info && info.level && !info.walletSnapshotStale) card.classList.add('mevcut-bot-row-alert-' + (info.level === 'critical' ? 'crit' : info.level));
    });
    updateFinanceBotsTabAlertState();
}

function hydrateFinanceBotsInlineHealthAlerts(bots) {
    if (!Array.isArray(bots)) return;
    bots.forEach(function (bot) {
        var botId = String((bot && (bot.bot_id || bot.id)) || '');
        if (!botId) return;
        var rowAlerts = financeBotRowHealthAlerts(bot.health_alerts);
        var level = '';
        if (rowAlerts.length) {
            var hasCrit = rowAlerts.some(function (a) { return a && String(a.level || '').toLowerCase() === 'critical'; });
            var hasWarn = rowAlerts.some(function (a) { return a && String(a.level || '').toLowerCase() === 'warn'; });
            level = hasCrit && hasWarn ? 'both' : (hasCrit ? 'critical' : (hasWarn ? 'warn' : ''));
        } else if (!Array.isArray(bot.health_alerts)) {
            level = String(bot.health_alert_level || bot.health_level || '').toLowerCase();
        }
        if (level === 'critical' || level === 'warn' || level === 'both') {
            _financeBotsHealthCache[botId] = {
                level: level,
                inline: true
            };
        } else if (_financeBotsHealthCache[botId] && _financeBotsHealthCache[botId].inline) {
            delete _financeBotsHealthCache[botId];
        }
    });
}

function pollFinanceBotsHealth() {
    if (!State.accountId || !window.apiClient || document.hidden) return Promise.resolve();
    if (isDashboardServerUnreachable()) {
        applyFinanceBotsServerOfflineState();
        return Promise.resolve();
    }
    var bots = (State.bots || []).filter(isFinanceBotRunningForHealth);
    if (!bots.length) {
        _financeBotsHealthCache = {};
        applyFinanceBotsHealthAlertsToDom();
        return Promise.resolve();
    }
    var q = State.accountCode
        ? '?account_code=' + encodeURIComponent(State.accountCode)
        : '?account_id=' + (State.accountId || '');
    var updates = {};
    var runningIds = bots.map(function (bot) { return String(bot.bot_id || bot.id || ''); }).filter(Boolean);
    return Promise.all(bots.map(function (bot) {
        var botId = String(bot.bot_id || bot.id || '');
        if (!botId) return Promise.resolve();
        return window.apiClient.get('/api/bots-engine/' + botId + '/health' + q, { timeout: 12000 })
            .then(function (res) {
                updates[botId] = classifyFinanceBotHealth(botId, res || {});
            })
            .catch(function (err) {
                if (isBenignDashboardFetchError(err)) return;
                if (isDashboardFetchServerError(err)) {
                    updates[botId] = { level: 'critical', serverOffline: true };
                    return;
                }
                if (_financeBotsHealthCache[botId]) return;
                updates[botId] = { level: null };
            });
    })).then(function () {
        Object.keys(_financeBotsHealthCache).forEach(function (id) {
            if (runningIds.indexOf(id) < 0) delete _financeBotsHealthCache[id];
        });
        Object.keys(updates).forEach(function (id) {
            _financeBotsHealthCache[id] = updates[id];
            if (window.BotHealthAlerts && typeof window.BotHealthAlerts.setStoredRowAlert === 'function') {
                window.BotHealthAlerts.setStoredRowAlert(
                    id,
                    updates[id] && updates[id].level,
                    updates[id] && updates[id].message,
                    financeBotsHealthAccountKey()
                );
            }
        });
        applyFinanceBotsHealthAlertsToDom();
        applyFinanceBotsLiveEquityToDom();
    });
}

function ensureFinanceBotsHealthPolling() {
    if (!window.intervalRegistry) return;
    window.intervalRegistry.stop('finance.bots.health');
    window.intervalRegistry.start('finance.bots.health', function () {
        if (_financeBotsHealthPollPromise) return;
        _financeBotsHealthPollPromise = pollFinanceBotsHealth().finally(function () {
            _financeBotsHealthPollPromise = null;
        });
    }, FINANCE_BOTS_HEALTH_POLL_MS, 'dashboard');
    if (!_financeBotsHealthPollPromise) {
        _financeBotsHealthPollPromise = pollFinanceBotsHealth().finally(function () {
            _financeBotsHealthPollPromise = null;
        });
    }
}

function patchFinanceBotsMetrics(bots) {
    if (!bots || !bots.length) return;
    State.bots = hydrateBotsWithMetricsCache(bots);
    hydrateFinanceBotsInlineHealthAlerts(State.bots);
    applyFinanceBotsLiveEquityToDom();
    applyFinanceBotsHealthAlertsToDom();
    persistFinanceBotsSessionCache(State.bots);
}

function renderFinanceBots(bots, opts) {
    opts = opts || {};
    bots = Array.isArray(bots) ? bots : [];
    if (typeof DashboardAccountScope !== 'undefined') {
        bots = DashboardAccountScope.guardBotsBeforeRender(bots, State.accountId, 'renderFinanceBots');
    }
    bots = hydrateBotsWithMetricsCache(bots);
    hydrateFinanceBotsInlineHealthAlerts(bots);
    const containerAnasayfa = document.getElementById('financeBotsList');
    const containerBotsTab = document.getElementById('financeBotsListBots');
    if (!containerAnasayfa && !containerBotsTab) return;

    resetFinanceBotsLiveCache(bots);
    var anyNeedsLive = Array.isArray(bots) && bots.some(botNeedsLiveEquity);
    if (!anyNeedsLive) _financeBotsLiveHydrated = true;

    var emptyHtml = '<div style="color: var(--ds-text-secondary); padding: 2rem; text-align: center;">Bot bulunamadı</div>';
    if (!bots || bots.length === 0) {
        if (!opts.clearWhenEmpty && !opts.forceFullRender && _financeBotsTableHasRows()) return;
        clearFinanceBotsUiState(State.accountId);
        clearBotsTabCache();
        if (containerAnasayfa) containerAnasayfa.innerHTML = emptyHtml;
        if (containerBotsTab) containerBotsTab.innerHTML = emptyHtml;
        updateFinanceBotsTabAlertState();
        _bindFinanceBotsSortButtons();
        return;
    }

    var sortBy = normalizeFinanceBotsSortBy(typeof financeBotsSortBy !== 'undefined' ? financeBotsSortBy : 'best');
    var structureSig = financeBotsStructureSignature(bots, sortBy);
    var idsSig = financeBotsIdsSignature(bots);
    var forceFull = !!opts.forceFullRender;
    if (forceFull && idsSig === _financeBotsIdsSignature && applyFinanceBotsSortReorder(bots)) {
        return;
    }
    if (!forceFull && idsSig === _financeBotsIdsSignature && structureSig === _financeBotsStructureSignature && _financeBotsBothTablesReady()) {
        State.bots = bots;
        _financeBotsStructureSignature = structureSig;
        updateFinanceBotsLivePrices();
        applyFinanceBotsLiveEquityToDom();
        patchFinanceBotsMetrics(bots);
        if (!_financeBotsLiveHydrated) ensureFinanceBotsLiveEquity();
        syncFinanceBotsTabFromHome();
        if (containerBotsTab && _financeBotsPanelHasRows(containerBotsTab)) markBotsTabCacheReady();
        return;
    }
    if (!forceFull && _financeBotsStructureSignature === structureSig && _financeBotsBothTablesReady()) {
        updateFinanceBotsLivePrices();
        patchFinanceBotsMetrics(bots);
        if (!_financeBotsLiveHydrated) ensureFinanceBotsLiveEquity();
        syncFinanceBotsTabFromHome();
        if (containerBotsTab && _financeBotsPanelHasRows(containerBotsTab)) markBotsTabCacheReady();
        return;
    }
    _financeBotsStructureSignature = structureSig;
    _financeBotsIdsSignature = idsSig;

    const normalized = bots.map(bot => {
        const budget = bot.budget_usd || bot.initial_usd || 0;
        const totalPnl = Number(bot.total_pnl_usd ?? bot.total_pnl ?? bot.pnl_30d ?? 0);
        const pct = budget > 0 ? (totalPnl / budget * 100) : 0;
        return {
            ...bot,
            budget_usd: budget,
            initial_usd: budget,
            total_pnl_usd: totalPnl,
            total_pnl_pct: bot.total_pnl_pct ?? pct
        };
    });
    const sorted = normalized.slice().sort(compareFinanceBotsForSort);
    var getLogoHtml = function (base, logoOpts) {
        logoOpts = logoOpts || {};
        var sz = 36;
        if (!base || typeof getCoinLogoUrl !== 'function') return '<span class="mevcut-bot-logo-placeholder" style="width:' + sz + 'px;height:' + sz + 'px;display:inline-block;"></span>';
        var url = getCoinLogoUrl(base);
        var initials = (typeof getCoinLogoInitials === 'function' ? getCoinLogoInitials(base) : (base || '?').substring(0, 1).toUpperCase());
        var dynClass = logoOpts.dynamicActive ? ' mevcut-bot-logo-wrap--dynamic' : '';
        var dynAttrs = '';
        if (logoOpts.dynamicActive && logoOpts.dynTip) {
            var tipAttr = window.DynModeParamsView && window.DynModeParamsView.attrEsc
                ? window.DynModeParamsView.attrEsc(logoOpts.dynTip)
                : String(logoOpts.dynTip).replace(/"/g, '&quot;');
            dynAttrs = ' data-dyn-tip="' + tipAttr + '"';
        }
        var wrapStyle = 'position:relative;width:' + sz + 'px;height:' + sz + 'px;border-radius:50%;background:var(--ds-bg-tertiary);display:inline-flex;align-items:center;justify-content:center;overflow:visible;flex-shrink:0;';
        var inner = url
            ? '<span class="mevcut-bot-logo-wrap' + dynClass + '"' + dynAttrs + ' style="' + wrapStyle + '"><img decoding="async" loading="' + ((typeof shouldEagerLoadLogo === 'function' && shouldEagerLoadLogo(base)) ? 'eager' : 'lazy') + '" fetchpriority="low" src="' + url + '" alt="' + (base || '') + '" data-symbol="' + (base || '') + '" class="mevcut-bot-logo" style="width:100%;height:100%;object-fit:cover;border-radius:50%;" onload="if(window.markCoinLogoLoaded)window.markCoinLogoLoaded(this)" onerror="if(window.handleCoinLogoError)window.handleCoinLogoError(this)" /><span class="mevcut-bot-logo-initials" style="display:none;position:absolute;width:' + sz + 'px;height:' + sz + 'px;border-radius:50%;align-items:center;justify-content:center;font-size:0.8rem;font-weight:600;background:var(--ds-bg-tertiary);color:var(--ds-text-secondary);">' + initials + '</span></span>'
            : '<span class="mevcut-bot-logo-initials' + dynClass + '"' + dynAttrs + ' style="width:' + sz + 'px;height:' + sz + 'px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-size:0.8rem;font-weight:600;background:var(--ds-bg-tertiary);color:var(--ds-text-secondary);">' + initials + '</span>';
        return inner;
    };
    var financeBotDynamicModeActive = function (bot) {
        var cfg = getBotConfig(bot);
        var dyn = bot.dynamic_mode || {};
        if (window.DynModeParamsView) {
            return window.DynModeParamsView.isDynamicModeActiveForList(dyn, cfg, bot.status);
        }
        return !!(cfg.dynamic_mode && String(bot.status || '').toLowerCase() === 'running');
    };
    var financeBotDynamicTip = function (bot) {
        var cfg = getBotConfig(bot);
        if (window.DynModeParamsView) {
            return window.DynModeParamsView.dynamicModeLogoTipShort(bot.dynamic_mode || {}, cfg);
        }
        return 'Dinamik mod aktif';
    };
    var getBotConfig = function (bot) {
        var c = bot.config || {};
        if (Object.keys(c).length === 0 && bot.config_json) {
            try { c = typeof bot.config_json === 'string' ? JSON.parse(bot.config_json) : (bot.config_json || {}); } catch (e) {}
        }
        return c;
    };
    var getMultiBotCoins = function (bot) {
        var cfg = getBotConfig(bot);
        var coins = [];
        if (cfg.strategy_id === 'multi_asset_rebalance') {
            if (Array.isArray(cfg.assets)) {
                cfg.assets.forEach(function (a) {
                    var s = (a.symbol || '').toUpperCase().replace(/USDT$|FDUSD$|BUSD$/i, '');
                    if (s && s !== 'USDT' && coins.indexOf(s) < 0) coins.push(s);
                });
            }
            if (coins.length === 0 && cfg.trb && cfg.trb.target_weights_all) {
                Object.keys(cfg.trb.target_weights_all).forEach(function (k) {
                    var s = (k || '').toUpperCase().replace(/USDT$|FDUSD$|BUSD$/i, '');
                    if (s && s !== 'USDT' && coins.indexOf(s) < 0) coins.push(s);
                });
            }
        }
        if (coins.length === 0 && (cfg.dca && cfg.dca.coin_weights)) {
            Object.keys(cfg.dca.coin_weights).forEach(function (k) {
                var s = (k || '').toUpperCase();
                if (s && s !== 'USDT' && coins.indexOf(s) < 0) coins.push(s);
            });
        }
        return coins.slice(0, 6);
    };
    var getMultiLogoHtml = function (coins) {
        if (!coins || coins.length === 0 || typeof getCoinLogoUrl !== 'function') return getLogoHtml('MU');
        var size = Math.min(28, Math.floor(100 / coins.length));
        var overlap = coins.length > 2 ? -Math.floor(size * 0.4) : 0;
        return '<span class="mevcut-bot-multi-logos" style="display:inline-flex;align-items:center;">' + coins.map(function (c, i) {
            var url = getCoinLogoUrl(c);
            var initials = (c || '').substring(0, 2).toUpperCase();
            var style = 'width:' + size + 'px;height:' + size + 'px;border-radius:50%;object-fit:cover;border:2px solid var(--ds-bg-panel);margin-left:' + (i === 0 ? 0 : overlap) + 'px;';
            var fs = size >= 24 ? '0.65rem' : '0.55rem';
            var wrapStyle = 'width:' + size + 'px;height:' + size + 'px;border-radius:50%;background:var(--ds-bg-tertiary);display:inline-flex;align-items:center;justify-content:center;overflow:hidden;flex-shrink:0;margin-left:' + (i === 0 ? 0 : overlap) + 'px;';
        return url
                ? '<span class="mevcut-bot-logo-wrap" style="' + wrapStyle + '"><img decoding="async" src="' + url + '" alt="' + c + '" class="mevcut-bot-logo" style="width:100%;height:100%;object-fit:cover;" onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'inline-flex\'" /><span class="mevcut-bot-logo-initials" style="display:none;position:absolute;' + style + 'align-items:center;justify-content:center;font-size:' + fs + ';font-weight:600;background:var(--ds-bg-tertiary);color:var(--ds-text-secondary);">' + initials + '</span></span>'
                : '<span class="mevcut-bot-logo-initials" style="' + style + 'display:inline-flex;align-items:center;justify-content:center;font-size:' + fs + ';font-weight:600;background:var(--ds-bg-tertiary);color:var(--ds-text-secondary);">' + initials + '</span>';
        }).join('') + '</span>';
    };
    var colgroup = '<colgroup>' +
        '<col class="mevcut-botlar-col-symbol"><col class="mevcut-botlar-col-price"><col class="mevcut-botlar-col-status"><col class="mevcut-botlar-col-budget">' +
        '<col class="mevcut-botlar-col-balance"><col class="mevcut-botlar-col-pnl"><col class="mevcut-botlar-col-tur"><col class="mevcut-botlar-col-action">' +
        '</colgroup>';
    const thead = '<thead><tr>' +
        '<th class="col-symbol col-left">Sembol</th>' +
        '<th class="col-price col-center">Fiyat</th>' +
        '<th class="col-status col-center">Durum</th>' +
        '<th class="col-budget col-center">Bütçe</th>' +
        '<th class="col-balance col-center">Bakiye</th>' +
        '<th class="col-pnl col-center" title="Başlangıç bütçesine göre anlık toplam kar/zarar">Toplam K/Z</th>' +
        '<th class="col-tur col-center">Tur</th>' +
        '<th class="col-action col-center">İşlem</th>' +
        '</tr></thead>';
    const rows = sorted.map(bot => {
        const botId = bot.bot_id || bot.id;
        const sym = (bot.symbol || 'N/A').toUpperCase();
        const cfg = getBotConfig(bot);
        const isMulti = sym === 'MULTI' || cfg.strategy_id === 'multi_asset_rebalance';
        const detailPage = isMulti ? '/ui/bot_multi.html' : '/ui/bot.html';
        const base = parseBaseQuote(sym).base || sym.replace(/USDT|FDUSD|BUSD$/i, '') || sym;
        const multiCoins = isMulti ? getMultiBotCoins(bot) : [];
        const dynActive = financeBotDynamicModeActive(bot);
        const dynTip = financeBotDynamicTip(bot);
        const logoHtml = isMulti && multiCoins.length > 0 ? getMultiLogoHtml(multiCoins) : getLogoHtml(base, { dynamicActive: dynActive, dynTip: dynTip });
        const q = State.accountCode ? 'account_code=' + encodeURIComponent(State.accountCode) : 'account_id=' + (State.accountId || '');
        const href = detailPage + '?bot_id=' + botId + '&symbol=' + encodeURIComponent(sym) + '&' + q;
        const statusMeta = getFinanceBotStatusMeta(bot);
        const kz = resolveBotHeroKz(bot);
        const currentUsd = kz.equity != null ? kz.equity : resolveBotCurrentUsd(bot);
        const balanceDisplay = currentUsd != null ? fmtUsd(currentUsd) : '—';
        const cyclesDisplay = resolveBotCyclesDisplay(bot);
        const budgetUsd = kz.initial > 0 ? kz.initial : (Number(bot.budget_usd || bot.initial_usd) || 0);
        const rowPnl = kz.usd;
        const rowPnlPct = kz.pct;
        const sc = rowPnl != null && rowPnl >= 0 ? '#0ecb81' : (rowPnl != null ? '#f6465d' : 'var(--ds-text-secondary)');
        var symbolCell = isMulti && multiCoins.length > 0
            ? '<a href="' + href + '" class="mevcut-bot-symbol-link"><span class="mevcut-bot-symbol-logo-slot mevcut-bot-symbol-logo-slot--multi">' + getMultiLogoHtml(multiCoins) + '</span></a>'
            : '<a href="' + href + '" class="mevcut-bot-symbol-link"><span class="mevcut-bot-symbol-logo-slot">' + logoHtml + '</span><span class="mevcut-bot-symbol-text">' + (bot.symbol || 'N/A') + '</span></a>';
        var livePrice = isMulti ? null : resolveFinanceBotDisplayPrice(botId, sym);
        var priceCell = isMulti
            ? '<span class="mevcut-bot-portfolio-balance" title="Çoklu sembol">—</span>'
            : '<span class="finance-bot-live-price mevcut-bot-portfolio-balance" data-symbol="' + sym + '" data-bot-id="' + botId + '" title="Sembol canlı fiyatı (bot detay /live)">' + (livePrice != null ? fmtCoinPrice(livePrice) : '—') + '</span>';
        return '<tr style="cursor:pointer" data-bot-id="' + botId + '" data-symbol="' + sym + '" data-detail-page="' + detailPage + '">' +
            '<td class="col-symbol col-left">' + symbolCell + '</td>' +
            '<td class="mevcut-botlar-price-cell col-price col-center">' + priceCell + '</td>' +
            '<td class="col-status col-center"><span class="mevcut-botlar-status ' + statusMeta.className + '"' + (statusMeta.title ? ' title="' + escapeHtml(statusMeta.title).replace(/"/g, '&quot;') + '"' : '') + '>' + statusMeta.text + '</span></td>' +
            '<td class="col-budget col-center">' + fmtUsd(bot.budget_usd || 0) + '</td>' +
            '<td class="mevcut-botlar-balance-cell col-balance col-center finance-bot-balance' + (balanceDisplay === '—' ? ' finance-bot-metric-pending' : '') + '" data-bot-id="' + botId + '" data-balance="' + (currentUsd != null ? currentUsd : '') + '" title="Bot bakiyesi (bot detay /live equity ile aynı)">' + balanceDisplay + '</td>' +
            '<td class="col-pnl col-center" title="Başlangıç bütçesine göre anlık toplam kar/zarar" style="color:' + sc + '">' + formatHeroKzDisplay(rowPnl, rowPnlPct, budgetUsd) + '</td>' +
            '<td class="col-tur col-center">' + cyclesDisplay + '</td>' +
            '<td class="col-action col-center"><a href="' + href + '" class="mevcut-botlar-detay-btn">Detay</a></td></tr>';
    }).join('');
    var tableHtml = '<div class="mevcut-botlar-table-wrap" style="overflow-x: auto; width: 100%;"><table class="binance-assets-table mevcut-botlar-table" style="width: 100%;">' + colgroup + thead + '<tbody>' + rows + '</tbody></table></div>';

    var mobileCardsHtml = sorted.map(bot => {
        const botId = bot.bot_id || bot.id;
        const sym = (bot.symbol || 'N/A').toUpperCase();
        const cfg = getBotConfig(bot);
        const isMulti = sym === 'MULTI' || cfg.strategy_id === 'multi_asset_rebalance';
        const detailPage = isMulti ? '/ui/bot_multi.html' : '/ui/bot.html';
        const base = parseBaseQuote(sym).base || sym.replace(/USDT|FDUSD|BUSD$/i, '') || sym;
        const multiCoins = isMulti ? getMultiBotCoins(bot) : [];
        const dynActive = financeBotDynamicModeActive(bot);
        const dynTip = financeBotDynamicTip(bot);
        const logoHtml = isMulti && multiCoins.length > 0 ? getMultiLogoHtml(multiCoins) : getLogoHtml(base, { dynamicActive: dynActive, dynTip: dynTip });
        const q = State.accountCode ? 'account_code=' + encodeURIComponent(State.accountCode) : 'account_id=' + (State.accountId || '');
        const href = detailPage + '?bot_id=' + botId + '&symbol=' + encodeURIComponent(sym) + '&' + q;
        const statusMeta = getFinanceBotStatusMeta(bot);
        const kzM = resolveBotHeroKz(bot);
        const currentUsd = kzM.equity != null ? kzM.equity : resolveBotCurrentUsd(bot);
        const balanceDisplay = currentUsd != null ? fmtUsd(currentUsd) : '—';
        const cyclesDisplay = resolveBotCyclesDisplay(bot);
        const budgetUsd = kzM.initial > 0 ? kzM.initial : (Number(bot.budget_usd || bot.initial_usd) || 0);
        const rowPnl = kzM.usd;
        const rowPnlPct = kzM.pct;
        const sc = rowPnl != null && rowPnl >= 0 ? '#0ecb81' : (rowPnl != null ? '#f6465d' : 'var(--ds-text-secondary)');
        // Mobil: tek sembolde FİYAT = canlı sembol fiyatı; çoklu botta —
        var mobLp = resolveFinanceBotDisplayPrice(botId, sym);
        var mobilePriceDisplay = isMulti ? '—' : (mobLp != null ? fmtCoinPrice(mobLp) : '—');
        var mobilePriceSpan = isMulti
            ? '<span class="mevcut-botlar-mobile-price" title="Çoklu sembol">—</span>'
            : '<span class="finance-bot-live-price mevcut-botlar-mobile-price" data-symbol="' + sym + '" data-bot-id="' + botId + '" title="Sembol canlı fiyatı">' + mobilePriceDisplay + '</span>';
        return '<div class="mevcut-botlar-mobile-card" data-bot-id="' + botId + '" data-symbol="' + sym + '" data-detail-page="' + detailPage + '">' +
            '<div class="mevcut-botlar-mobile-top">' +
            logoHtml +
            '<a href="' + href + '" class="mevcut-botlar-mobile-symbol">' + (isMulti && multiCoins.length > 0 ? getMultiLogoHtml(multiCoins) : (bot.symbol || 'N/A')) + '</a>' +
            mobilePriceSpan +
            '</div>' +
            '<div class="mevcut-botlar-mobile-stats">' +
            '<div class="mevcut-botlar-mobile-stat"><span class="mevcut-botlar-mobile-stat-label">Durum</span><span class="mevcut-botlar-status ' + statusMeta.className + '"' + (statusMeta.title ? ' title="' + escapeHtml(statusMeta.title).replace(/"/g, '&quot;') + '"' : '') + '>' + statusMeta.text + '</span></div>' +
            '<div class="mevcut-botlar-mobile-stat"><span class="mevcut-botlar-mobile-stat-label">Bütçe</span><span class="mevcut-botlar-mobile-stat-value">' + fmtUsd(bot.budget_usd || 0) + '</span></div>' +
            '<div class="mevcut-botlar-mobile-stat"><span class="mevcut-botlar-mobile-stat-label">Bakiye</span><span class="mevcut-botlar-mobile-stat-value">' + balanceDisplay + '</span></div>' +
            '<div class="mevcut-botlar-mobile-stat"><span class="mevcut-botlar-mobile-stat-label">Toplam K/Z</span><span class="mevcut-botlar-mobile-stat-value mevcut-botlar-mobile-pnl" style="color:' + sc + '">' + formatHeroKzDisplay(rowPnl, rowPnlPct, budgetUsd) + '</span></div>' +
            '<div class="mevcut-botlar-mobile-stat"><span class="mevcut-botlar-mobile-stat-label">Tur</span><span class="mevcut-botlar-mobile-stat-value">' + cyclesDisplay + '</span></div>' +
            '</div>' +
            '<a href="' + href + '" class="mevcut-botlar-detay-btn mevcut-botlar-mobile-detay">Detay</a>' +
            '</div>';
    }).join('');
    var mobileWrapHtml = '<div class="mevcut-botlar-mobile">' + mobileCardsHtml + '</div>';

    var fullHtml = tableHtml + mobileWrapHtml;
    if (containerAnasayfa) { containerAnasayfa.innerHTML = fullHtml; bindFinanceBotsRowClicks(containerAnasayfa); }
    if (containerBotsTab) { containerBotsTab.innerHTML = fullHtml; bindFinanceBotsRowClicks(containerBotsTab); }
    updateFinanceBotsSortButtonUi(sortBy);
    _bindFinanceBotsSortButtons();
    updateFinanceBotsLivePrices();
    ensureDashboardMarketPriceSubscriber();
    ensureFinanceBotsLiveEquity();
    ensureFinanceBotsHealthPolling();
    applyFinanceBotsHealthAlertsToDom();
    persistFinanceBotsSessionCache(sorted);
    if (containerBotsTab && _financeBotsPanelHasRows(containerBotsTab)) markBotsTabCacheReady();
}

var financeBotLastPrices = {};
var _financeBotPriceBlinkUntil = {};
var FINANCE_BOT_PRICE_BLINK_COOLDOWN_MS = 350;
var _dashboardMarketPriceRaf = 0;
var _dashboardMarketUnsub = null;

function clearFinanceBotPriceTone(span) {
    if (!span) return;
    span.classList.remove('mevcut-bot-price-up', 'mevcut-bot-price-down');
}

function applyFinanceBotPriceBlink(span, newPrice, oldPrice, tone) {
    if (!span || !Number.isFinite(newPrice) || !Number.isFinite(oldPrice)) return;
    if (Math.abs(newPrice - oldPrice) < 1e-10) return;
    clearFinanceBotPriceTone(span);
    span.classList.remove('mevcut-bot-blink-up', 'mevcut-bot-blink-down', 'price-up', 'price-down', 'blink-positive', 'blink-negative');
    void span.offsetWidth;
    span.classList.add(tone === 'up' ? 'mevcut-bot-blink-up' : 'mevcut-bot-blink-down');
    setTimeout(function () {
        span.classList.remove('mevcut-bot-blink-up', 'mevcut-bot-blink-down');
        clearFinanceBotPriceTone(span);
    }, 780);
}

function tickDashboardLiveMarketPrices() {
    if (typeof tickVarliklarPrices === 'function') tickVarliklarPrices({ skipThrottle: true });
    if (typeof updateFinanceBotsLivePrices === 'function') updateFinanceBotsLivePrices();
}

function scheduleDashboardLiveMarketPrices() {
    if (_dashboardMarketPriceRaf) return;
    _dashboardMarketPriceRaf = requestAnimationFrame(function () {
        _dashboardMarketPriceRaf = 0;
        tickDashboardLiveMarketPrices();
    });
}

function ensureDashboardMarketPriceSubscriber() {
    var store = window.marketStore;
    if (!store || typeof store.subscribe !== 'function' || _dashboardMarketUnsub) return;
    _dashboardMarketUnsub = store.subscribe(function () {
        scheduleDashboardLiveMarketPrices();
    });
}

function updateFinanceBotsLivePrices() {
    var grouped = {};
    document.querySelectorAll('.finance-bot-live-price').forEach(function (span) {
        var sym = span.getAttribute('data-symbol');
        var botId = span.getAttribute('data-bot-id');
        if (!sym || !botId) return;
        if (!grouped[botId]) grouped[botId] = { sym: sym, spans: [] };
        grouped[botId].spans.push(span);
    });
    var now = Date.now();
    Object.keys(grouped).forEach(function (botId) {
        var entry = grouped[botId];
        var price = resolveFinanceBotDisplayPrice(botId, entry.sym);
        if (price == null) return;
        var newText = fmtCoinPrice(price);
        var prev = financeBotLastPrices[botId];
        var priceChanged = prev != null && Number.isFinite(prev) && Math.abs(price - prev) > 1e-10;
        var tone = priceChanged ? (price > prev ? 'up' : 'down') : null;
        var canBlink = priceChanged && (!_financeBotPriceBlinkUntil[botId] || now >= _financeBotPriceBlinkUntil[botId]);
        if (canBlink) _financeBotPriceBlinkUntil[botId] = now + FINANCE_BOT_PRICE_BLINK_COOLDOWN_MS;
        entry.spans.forEach(function (span) {
            if (canBlink) applyFinanceBotPriceBlink(span, price, prev, tone);
            else clearFinanceBotPriceTone(span);
            if (span.textContent !== newText) span.textContent = newText;
        });
        financeBotLastPrices[botId] = price;
    });
}
function _bindFinanceBotsSortButtons() {
    var handler = function () {
        setFinanceBotsSortBy(normalizeFinanceBotsSortBy(financeBotsSortBy) === 'worst' ? 'best' : 'worst');
    };
    var btn = document.getElementById('btnSortBotsBy');
    if (btn && !btn._boundFinanceBots) { btn._boundFinanceBots = true; btn.addEventListener('click', handler); }
    var btnTab = document.getElementById('btnSortBotsByBotsTab');
    if (btnTab && !btnTab._boundFinanceBots) { btnTab._boundFinanceBots = true; btnTab.addEventListener('click', handler); }
    updateFinanceBotsSortButtonUi(normalizeFinanceBotsSortBy(typeof financeBotsSortBy !== 'undefined' ? financeBotsSortBy : 'best'));
}

async function loadEquityCurve(range) {
    if (!State.accountId) return;
    
    financeReportsState.equityCurveRange = range;
    
    try {
        // REFACTOR: Use financeService instead of direct fetch
        if (window.financeService) {
            const data = await window.financeService.getEquityCurve(State.accountId, range);
            // Data is already in financeStore, just render
            renderEquityCurve(data.data || []);
            return;
        }
        
        // Fallback: Use apiClient
        const data = await window.apiClient.get(`/api/finance/equity-curve?account_id=${State.accountId}&range=${range}&cb=${Date.now()}`);
        renderEquityCurve(data.data || []);
        
    } catch (error) {
        console.error("[reports] Error loading equity curve:", error);
        if (window.errorReporter) {
            window.errorReporter.report(error, { tab: 'reports', account_id: State.accountId, action: 'loadEquityCurve' });
        }
        const chartEl = document.getElementById('equityCurveChart');
        if (chartEl) {
            chartEl.innerHTML = '<div style="text-align: center; padding: 2rem; color: var(--ds-danger);">Grafik yüklenemedi</div>';
        }
    }
}

function renderEquityCurve(data) {
    const chartEl = document.getElementById('equityCurveChart');
    if (!chartEl) return;
    
    if (data.length === 0) {
        chartEl.innerHTML = '<div style="text-align: center; padding: 2rem; color: var(--ds-text-secondary);">Veri yok</div>';
        return;
    }
    
    // Simple line chart using SVG (or use Chart.js if available)
    const maxValue = Math.max(...data.map(d => d.total_usd_value));
    const minValue = Math.min(...data.map(d => d.total_usd_value));
    const range = maxValue - minValue || 1;
    const width = 800;
    const height = 250;
    const padding = 40;
    
    const points = data.map((d, i) => {
        const x = padding + (i / (data.length - 1 || 1)) * (width - 2 * padding);
        const y = padding + (1 - (d.total_usd_value - minValue) / range) * (height - 2 * padding);
        return {x, y, value: d.total_usd_value, time: d.timestamp};
    });
    
    const pathData = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ');
    
    chartEl.innerHTML = `
        <svg width="${width}" height="${height}" style="width: 100%; height: 100%;">
            <defs>
                <linearGradient id="equityGradient" x1="0%" y1="0%" x2="0%" y2="100%">
                    <stop offset="0%" style="stop-color:#0ecb81;stop-opacity:0.3" />
                    <stop offset="100%" style="stop-color:#0ecb81;stop-opacity:0" />
                </linearGradient>
            </defs>
            <path d="${pathData} Z" fill="url(#equityGradient)" stroke="#0ecb81" stroke-width="2"/>
            <text x="${width / 2}" y="${height - 10}" text-anchor="middle" fill="var(--ds-text-secondary)" font-size="12">${fmtUsd(minValue)} - ${fmtUsd(maxValue)}</text>
        </svg>
    `;
}

async function loadFinanceReport() {
    if (!State.accountId) return;
    
    const period = document.getElementById('reportPeriod')?.value || 'weekly';
    
    try {
        const data = await window.apiClient.get(`/api/finance/report?account_id=${State.accountId}&period=${period}&cb=${Date.now()}`, { timeout: 15000 });
        renderFinanceReport(data);
        
    } catch (error) {
        console.error("[reports] Error loading finance report:", error);
    }
}

function renderFinanceReport(data) {
    const container = document.getElementById('financeReportContent');
    if (!container) return;
    
    container.innerHTML = `
        <div style="margin-bottom: 1.5rem;">
            <h3 style="margin: 0 0 1rem 0; font-size: 1.2rem; font-weight: 600; color: var(--ds-text-primary);">Rapor: ${data.period}</h3>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 1.5rem;">
                <div class="panel" style="padding: 1rem;">
                    <div style="font-size: 0.85rem; color: var(--ds-text-secondary); margin-bottom: 0.5rem;">Realized PnL</div>
                    <div style="font-size: 1.5rem; font-weight: 700; color: ${data.realized_pnl >= 0 ? '#0ecb81' : '#f6465d'};">${fmtUsd(data.realized_pnl)}</div>
                </div>
                <div class="panel" style="padding: 1rem;">
                    <div style="font-size: 0.85rem; color: var(--ds-text-secondary); margin-bottom: 0.5rem;">Ücretler</div>
                    <div style="font-size: 1.5rem; font-weight: 700; color: var(--ds-text-primary);">${fmtUsd(data.fees)}</div>
                </div>
                <div class="panel" style="padding: 1rem;">
                    <div style="font-size: 0.85rem; color: var(--ds-text-secondary); margin-bottom: 0.5rem;">Net PnL</div>
                    <div style="font-size: 1.5rem; font-weight: 700; color: ${data.net_pnl >= 0 ? '#0ecb81' : '#f6465d'};">${fmtUsd(data.net_pnl)}</div>
                </div>
                <div class="panel" style="padding: 1rem;">
                    <div style="font-size: 0.85rem; color: var(--ds-text-secondary); margin-bottom: 0.5rem;">İşlem Sayısı</div>
                    <div style="font-size: 1.5rem; font-weight: 700; color: var(--ds-text-primary);">${data.trades_count}</div>
                </div>
            </div>
            <div style="margin-bottom: 1.5rem;">
                <h4 style="margin: 0 0 1rem 0; font-size: 1rem; font-weight: 600; color: var(--ds-text-primary);">Metrikler</h4>
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 1rem;">
                    <div><strong>Win Rate:</strong> ${(data.metrics.win_rate * 100).toFixed(2)}%</div>
                    <div><strong>Profit Factor:</strong> ${data.metrics.profit_factor.toFixed(2)}</div>
                    <div><strong>Gross Profit:</strong> ${fmtUsd(data.metrics.gross_profit)}</div>
                    <div><strong>Gross Loss:</strong> ${fmtUsd(data.metrics.gross_loss)}</div>
                </div>
            </div>
            <div>
                <h4 style="margin: 0 0 1rem 0; font-size: 1rem; font-weight: 600; color: var(--ds-text-primary);">Sembol Bazında</h4>
                <div style="overflow-x: auto;">
                    <table class="binance-assets-table">
                        <thead>
                            <tr>
                                <th style="text-align: left;">Sembol</th>
                                <th style="text-align: right;">PnL</th>
                                <th style="text-align: right;">Ücret</th>
                                <th style="text-align: right;">İşlem</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${Object.entries(data.by_symbol || {}).map(([symbol, d]) => `
                                <tr>
                                    <td><strong>${symbol}</strong></td>
                                    <td style="text-align: right; color: ${d.pnl >= 0 ? '#0ecb81' : '#f6465d'}; font-weight: 600;">${fmtUsd(d.pnl)}</td>
                                    <td style="text-align: right;">${fmtUsd(d.fees)}</td>
                                    <td style="text-align: right;">${d.count}</td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    `;
}

async function loadFinanceBots() {
    if (!State.accountId) return;
    
    try {
        const data = await window.apiClient.get(`/api/finance/bots?account_id=${State.accountId}&cb=${Date.now()}`, { timeout: 15000 });
        renderFinanceBots(data.bots || []);
        
    } catch (error) {
        console.error("[reports] Error loading finance bots:", error);
    }
}

async function loadFinanceBotDetail(botId) {
    const q = State.accountCode ? 'account_code=' + encodeURIComponent(State.accountCode) : 'account_id=' + (State.accountId || '');
    location.href = '/ui/bot.html?bot_id=' + botId + '&' + q;
}

// Finance trades period state
let financeTradesPeriod = 'daily'; // daily, weekly, monthly, yearly, all
let financeTradesTypeFilter = 'all'; // all | buysell | depositwithdraw
let _financeTradesLoadedOnce = false;
let _financeTradesSyncedOnce = false; // sync=1 only for explicit refresh; first paint stays fast

function setTradesPeriod(period) {
    financeTradesPeriod = period;

    ['daily', 'weekly', 'monthly', 'yearly', 'all'].forEach(function (p) {
        var btn = document.getElementById('tradesPeriod' + p.charAt(0).toUpperCase() + p.slice(1));
        if (!btn) return;
        if (p === period) {
            btn.style.background = 'var(--ds-accent-dark, #c9930a)';
            btn.style.color = '#000';
            btn.style.fontWeight = '600';
        } else {
            btn.style.background = '';
            btn.style.color = '';
            btn.style.fontWeight = '';
        }
    });

    if (typeof financeReportsState !== 'undefined' && financeReportsState) {
        financeReportsState.tradesOffset = 0;
    }
    if (typeof loadFinanceTrades === 'function') loadFinanceTrades();
}
window.setTradesPeriod = setTradesPeriod;

/** Türkiye saatine göre dönem aralığı (start/end UTC ISO). Günlük = bugün 00:00 TR → şimdi, vb. */
function getTurkeyDateRange(period) {
    const now = new Date();
    const trDateStr = now.toLocaleDateString('en-CA', { timeZone: 'Europe/Istanbul' });
    const [y, m, d] = trDateStr.split('-').map(Number);
    const turkeyMidnightUTC = new Date(Date.UTC(y, m - 1, d) - 3 * 60 * 60 * 1000);
    const endISO = now.toISOString();
    switch (period) {
        case 'daily':
            return { startISO: turkeyMidnightUTC.toISOString(), endISO };
        case 'weekly':
            const weekStart = new Date(turkeyMidnightUTC.getTime() - 7 * 24 * 60 * 60 * 1000);
            return { startISO: weekStart.toISOString(), endISO };
        case 'monthly':
            const monthStart = new Date(turkeyMidnightUTC.getTime() - 30 * 24 * 60 * 60 * 1000);
            return { startISO: monthStart.toISOString(), endISO };
        case 'yearly':
            const yearStart = new Date(turkeyMidnightUTC.getTime() - 365 * 24 * 60 * 60 * 1000);
            return { startISO: yearStart.toISOString(), endISO };
        default:
            return {};
    }
}

/** UTC ISO string veya Date → Türkiye saati metni (Tarih + Saat). */
function formatTurkeyDateTime(isoOrDate) {
    const d = typeof isoOrDate === 'string' ? new Date(isoOrDate.endsWith('Z') ? isoOrDate : isoOrDate + 'Z') : isoOrDate;
    const dateStr = d.toLocaleDateString('tr-TR', { timeZone: 'Europe/Istanbul', day: '2-digit', month: '2-digit' });
    const timeStr = d.toLocaleTimeString('tr-TR', { timeZone: 'Europe/Istanbul', hour: '2-digit', minute: '2-digit' });
    return { dateStr, timeStr };
}

// Finance period state (for PnL and fees display)
let financePeriod = 'daily'; // daily, weekly, monthly, yearly, all

function setFinancePeriod(period) {
    financePeriod = period;
    
    // Update button styles
    ['daily', 'weekly', 'monthly', 'yearly', 'all'].forEach(p => {
        const btn = document.getElementById(`financePeriod${p.charAt(0).toUpperCase() + p.slice(1)}`);
        if (btn) {
            if (p === period) {
                btn.style.background = 'var(--ds-accent-dark, #c9930a)';
                btn.style.color = '#000';
                btn.style.fontWeight = '600';
            } else {
                btn.style.background = '';
                btn.style.color = '';
                btn.style.fontWeight = '';
            }
        }
    });
    
    // Load period data
    loadFinancePeriodData();
}

async function loadFinancePeriodData() {
    if (!State.accountId) return;
    
    try {
        // Calculate date range based on period (UTC standardize)
        let startDate = '';
        let endDate = '';
        const now = new Date();
        const nowUTC = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), now.getUTCHours(), now.getUTCMinutes(), now.getUTCSeconds()));
        
        switch (financePeriod) {
            case 'daily':
                const todayStart = new Date(Date.UTC(nowUTC.getUTCFullYear(), nowUTC.getUTCMonth(), nowUTC.getUTCDate(), 0, 0, 0));
                startDate = todayStart.toISOString();
                endDate = nowUTC.toISOString();
                break;
            case 'weekly':
                const weekAgo = new Date(nowUTC);
                weekAgo.setUTCDate(nowUTC.getUTCDate() - 7);
                startDate = weekAgo.toISOString();
                endDate = nowUTC.toISOString();
                break;
            case 'monthly':
                const monthAgo = new Date(nowUTC);
                monthAgo.setUTCDate(nowUTC.getUTCDate() - 30);
                startDate = monthAgo.toISOString();
                endDate = nowUTC.toISOString();
                break;
            case 'yearly':
                const yearAgo = new Date(nowUTC);
                yearAgo.setUTCFullYear(nowUTC.getUTCFullYear() - 1);
                startDate = yearAgo.toISOString();
                endDate = nowUTC.toISOString();
                break;
            case 'all':
                // No date filter - use report endpoint with default period
                break;
        }
        
        // Call finance report endpoint
        let url = `/api/finance/report?account_id=${State.accountId}`;
        if (financePeriod === 'all') {
            // For "all", use a very old start date (e.g., 10 years ago)
            const allTimeStart = new Date(nowUTC);
            allTimeStart.setUTCFullYear(nowUTC.getUTCFullYear() - 10);
            url += `&start=${allTimeStart.toISOString()}&end=${endDate || nowUTC.toISOString()}`;
        } else if (startDate && endDate) {
            url += `&start=${startDate}&end=${endDate}`;
        } else {
            // Map period to report period
            const periodMap = {
                'daily': 'weekly', // Use weekly as base for daily
                'weekly': 'weekly',
                'monthly': 'monthly',
                'yearly': 'monthly' // Use monthly as base for yearly
            };
            url += `&period=${periodMap[financePeriod] || 'weekly'}`;
        }
        url += `&cb=${Date.now()}`;
        
        const data = await window.apiClient.get(url);
        
        // Update PnL display
        const pnlEl = document.getElementById('financePeriodPnl');
        if (pnlEl) {
            const pnl = data.realized_pnl || 0;
            pnlEl.textContent = fmtUsd(pnl);
            pnlEl.style.color = pnl >= 0 ? '#0ecb81' : '#f6465d';
        }
        
        const pnlPctEl = document.getElementById('financePeriodPnlPct');
        if (pnlPctEl) {
            // Calculate percentage based on initial value (if available)
            // For now, just show the value
            const pnl = data.realized_pnl || 0;
            // Try to get initial value from summary
            try {
                const summaryData = await window.apiClient.get(`/api/finance/summary?account_id=${State.accountId}&cb=${Date.now()}`);
                const initialValue = summaryData.initial_value || 1;
                const pct = initialValue > 0 ? ((pnl / initialValue) * 100).toFixed(2) : '0.00';
                pnlPctEl.textContent = `${pct >= 0 ? '+' : ''}${pct}%`;
                pnlPctEl.style.color = pct >= 0 ? '#0ecb81' : '#f6465d';
            } catch (e) {
                pnlPctEl.textContent = '-';
            }
        }
        
        // Update Fees display
        const feesEl = document.getElementById('financePeriodFees');
        if (feesEl) {
            const fees = data.fees || 0;
            feesEl.textContent = fmtUsd(fees);
        }
        
        const feesInfoEl = document.getElementById('financePeriodFeesInfo');
        if (feesInfoEl) {
            const periodNames = {
                'daily': 'Günlük',
                'weekly': 'Haftalık',
                'monthly': 'Aylık',
                'yearly': 'Yıllık',
                'all': 'Genel'
            };
            feesInfoEl.textContent = periodNames[financePeriod] || 'Seçilen dönem';
        }
        
        // PnL etiketini seçilen döneme göre güncelle (gerçekleşen işlem K/Z)
        const pnlLabelEl = document.getElementById('financePeriodPnlLabel');
        if (pnlLabelEl) {
            const periodLabels = {
                'daily': 'Günlük Gerçekleşen K/Z',
                'weekly': 'Haftalık Gerçekleşen K/Z',
                'monthly': 'Aylık Gerçekleşen K/Z',
                'yearly': 'Yıllık Gerçekleşen K/Z',
                'all': 'Genel Gerçekleşen K/Z'
            };
            pnlLabelEl.textContent = periodLabels[financePeriod] || 'Gerçekleşen K/Z';
        }
        
        // Bot bazında PnL ve Komisyon (alt özet)
        const listEl = document.getElementById('financeBotsPnlFeesList');
        if (listEl && data.by_bot && typeof data.by_bot === 'object') {
            const entries = Object.entries(data.by_bot);
            if (entries.length === 0) {
                listEl.innerHTML = '<div style="color: var(--ds-text-secondary);">Bu dönemde bot işlemi yok.</div>';
            } else {
                listEl.innerHTML = '<table class="binance-assets-table" style="width:100%; font-size: 0.9rem;"><thead><tr><th style="text-align:left">Bot ID</th><th style="text-align:right">PnL</th><th style="text-align:right">Komisyon</th></tr></thead><tbody>' +
                    entries.map(([botId, d]) => {
                        const pnl = d.pnl != null ? d.pnl : 0;
                        const fees = d.fees != null ? d.fees : 0;
                        const c = pnl >= 0 ? '#0ecb81' : '#f6465d';
                        return '<tr><td>Bot #' + botId + '</td><td style="text-align:right; color:' + c + '">' + fmtSignedUsd(pnl) + '</td><td style="text-align:right">' + fmtUsd(fees) + '</td></tr>';
                    }).join('') +
                    '</tbody></table>';
            }
        } else if (listEl) {
            listEl.innerHTML = '<div style="color: var(--ds-text-secondary);">Veri yok.</div>';
        }
        
    } catch (error) {
        console.error("[reports] Error loading finance period data:", error);
    }
}

function setTradesTypeFilter(filter) {
    financeTradesTypeFilter = filter;
    ['all', 'buysell', 'depositwithdraw'].forEach(f => {
        const btn = document.getElementById(
            f === 'all' ? 'tradesFilterAll' : f === 'buysell' ? 'tradesFilterBuySell' : 'tradesFilterDepositWithdraw'
        );
        if (btn) {
            if (f === filter) {
                btn.style.background = 'var(--ds-accent-dark, #c9930a)';
                btn.style.color = '#000';
                btn.style.fontWeight = '600';
            } else {
                btn.style.background = '';
                btn.style.color = '';
                btn.style.fontWeight = '';
            }
        }
    });
    financeReportsState.tradesOffset = 0;
    loadFinanceTrades();
}

async function loadFinanceTrades(doSync) {
    if (!State.accountId) return;
    
    const body = document.getElementById('financeTradesBody');
    var isBackgroundRefresh = (doSync !== true && _financeTradesLoadedOnce === true);
    if (body && !isBackgroundRefresh) {
        body.innerHTML = '<tr><td colspan="9" style="text-align: center; padding: 2rem; color: var(--ds-text-secondary);">Yükleniyor...</td></tr>';
    }
    
    // Dönem aralığı Türkiye saatine göre (Günlük = bugün 00:00 TR → şimdi)
    const range = getTurkeyDateRange(financeTradesPeriod);
    const startISO = range.startISO || '';
    const endISO = range.endISO || '';
    
    let url = `/api/finance/trades?account_id=${State.accountId}&limit=${financeReportsState.tradesLimit}&offset=${financeReportsState.tradesOffset}`;
    if (startISO) url += '&start=' + encodeURIComponent(startISO);
    if (endISO) url += '&end=' + encodeURIComponent(endISO);
    if (financeTradesTypeFilter && String(financeTradesTypeFilter).toLowerCase() !== 'all') {
        url += '&type_filter=' + encodeURIComponent(String(financeTradesTypeFilter).trim().toLowerCase());
    }
    if (doSync === true) {
        url += '&sync=1';
        _financeTradesSyncedOnce = true;
    }
    url += `&cb=${Date.now()}`;
    
    try {
        // sync=1 Binance'ten veri cekebilir; 90s timeout (varsayilan 20s yetmeyebilir)
        const data = await window.apiClient.get(url, { timeout: 90000 });
        renderFinanceTrades(data);
        updateTradesSummaryStats(data);
        _financeTradesLoadedOnce = true;
        
        // Hide banner on successful load (if error was resolved)
        if (binanceApiErrorState.isError) {
            const errorAge = Date.now() - (binanceApiErrorState.lastErrorTime || 0);
            if (errorAge > 30000) {
                hideBinanceApiBanner();
            }
        }
        
    } catch (error) {
        console.error("[reports] Error loading finance trades:", error);
        
        // Check for Binance API errors and show banner
        if (error.status === 429 || error.error_code === 'HTTP_429' || error.error_code === 'BINANCE_RATE_LIMIT') {
            showBinanceApiBanner('rate_limit', error);
        } else if (error.status === 418 || error.error_code === 'HTTP_418') {
            showBinanceApiBanner('ip_banned', error);
        } else if (error.status === 502 || error.error_code === 'HTTP_502') {
            showBinanceApiBanner('bad_gateway', error);
        }
        
        if (window.errorReporter) {
            window.errorReporter.report(error, { tab: 'reports', account_id: State.accountId, action: 'loadFinanceTrades' });
            if (body) {
                const errorMsg = window.errorReporter.toUserMessage(error);
                body.innerHTML = `<tr><td colspan="9" style="text-align: center; padding: 2rem; color: var(--ds-text-error);">Hata: ${errorMsg}</td></tr>`;
            }
        } else if (body) {
            body.innerHTML = `<tr><td colspan="9" style="text-align: center; padding: 2rem; color: var(--ds-text-error);">Hata: ${error.message || 'İşlemler yüklenemedi'}</td></tr>`;
        }
    }
}

function renderFinanceTrades(data) {
    const body = document.getElementById('financeTradesBody');
    if (!body) return;
    
    if (!data.trades || data.trades.length === 0) {
        body.innerHTML = '<tr><td colspan="9" style="text-align: center; padding: 2rem; color: var(--ds-text-secondary);">İşlem bulunamadı</td></tr>';
        return;
    }
    
    // Backend now returns order-based grouped trades (1 order = 1 row)
    // Dedupe by order_id to prevent duplicates
    const ordersMap = new Map();
    
    data.trades.forEach(order => {
        const orderKey = order.order_id || order.trade_id;
        // If order already exists, replace (don't duplicate)
        ordersMap.set(orderKey, order);
    });
    
    // Convert to array and render
    const uniqueOrders = Array.from(ordersMap.values());
    
    body.innerHTML = uniqueOrders.map(order => {
        const rawTime = order.time || order.last_fill_time || order.first_fill_time;
        const { dateStr, timeStr } = formatTurkeyDateTime(rawTime);
        const typeRaw = (order.type || '').toUpperCase();
        const isDeposit = typeRaw === 'DEPOSIT' || typeRaw === 'YATIRIM';
        const isWithdraw = typeRaw === 'WITHDRAW' || typeRaw === 'CEKIM';
        const turText = isDeposit ? 'Yatırım' : isWithdraw ? 'Çekim' : (order.side === 'BUY' ? 'Alış' : 'Satış');
        const sideColor = isDeposit ? 'var(--ds-accent)' : order.side === 'BUY' ? '#0ecb81' : '#f6465d';
        const sideText = isDeposit ? '—' : (order.side === 'BUY' ? 'AL' : 'SAT');
        
        const isBotTrade = order.is_bot === true || (order.bot_id && order.bot_id > 0);
        const sourceText = isBotTrade ? 'BOT' : 'MANUEL';
        const sourceColor = isBotTrade ? '#f0b90b' : 'var(--ds-text-secondary)';
        const fillsInfo = order.fills_count > 1 ? ` (${order.fills_count} fill)` : '';
        
        return `
            <tr style="cursor: pointer;" onmouseover="this.style.backgroundColor='var(--ds-bg-hover)'" onmouseout="this.style.backgroundColor=''">
                <td style="text-align: left; font-size: 0.9rem;">
                    <div style="font-weight: 500;">${dateStr}</div>
                    <div style="color: var(--ds-text-secondary); font-size: 0.85rem;">${timeStr}</div>
                </td>
                <td style="text-align: left; font-size: 0.85rem;">${turText}</td>
                <td style="text-align: left; font-weight: 600;">${order.symbol || 'N/A'}</td>
                <td style="text-align: center;">
                    <span style="color: ${sideColor}; font-weight: 600; font-size: 0.9rem;">${sideText}</span>
                </td>
                <td style="text-align: right; font-weight: 500;">${fmtNum(order.executed_qty || order.qty || 0, 6)}${fillsInfo}</td>
                <td style="text-align: right; font-weight: 500;">${fmtCoinPrice(order.avg_price || order.price)}</td>
                <td style="text-align: right; font-weight: 600;">${fmtUsd(order.quote_qty || 0)}</td>
                <td style="text-align: right; color: var(--ds-text-secondary); font-size: 0.85rem;">
                    ${order.commission ? `${fmtNum(order.commission, 6)} ${order.commission_asset || ''}` : '-'}
                    ${order.commission_usd !== undefined ? `<div style="font-size: 0.75rem; color: var(--ds-text-tertiary); margin-top: 2px;">≈ ${fmtUsd(order.commission_usd)}</div>` : ''}
                </td>
                <td style="text-align: center;">
                    <span style="display: inline-block; padding: 2px 6px; border-radius: 3px; background: ${isBotTrade ? 'rgba(240, 185, 11, 0.1)' : 'var(--ds-bg-tertiary)'}; color: ${sourceColor}; font-size: 0.75rem; font-weight: 600;">${sourceText}</span>
                </td>
            </tr>
        `;
    }).join('');
    
    // Pagination info
    const paginationEl = document.getElementById('tradesPaginationInfo');
    if (paginationEl) {
        const total = data.total || uniqueOrders.length;
        const start = financeReportsState.tradesOffset + 1;
        const end = Math.min(financeReportsState.tradesOffset + financeReportsState.tradesLimit, total);
        paginationEl.textContent = `${start}-${end} / ${total} işlem`;
    }
}

function updateTradesSummaryStats(data) {
    if (!data || !data.trades) return;
    
    const trades = data.trades;
    const typeOf = t => ((t.type || '').toUpperCase());
    
    const buyCount = trades.filter(t => t.side === 'BUY' && typeOf(t) !== 'DEPOSIT').length;
    const sellCount = trades.filter(t => t.side === 'SELL' && typeOf(t) !== 'WITHDRAW').length;
    const depositCount = trades.filter(t => typeOf(t) === 'DEPOSIT' || typeOf(t) === 'YATIRIM').length;
    const withdrawCount = trades.filter(t => typeOf(t) === 'WITHDRAW' || typeOf(t) === 'CEKIM').length;
    
    const totalCount = buyCount + sellCount + depositCount + withdrawCount;
    
    const totalCountEl = document.getElementById('tradesTotalCount');
    if (totalCountEl) totalCountEl.textContent = String(totalCount);
    const buyCountEl = document.getElementById('tradesBuyCount');
    if (buyCountEl) buyCountEl.textContent = String(buyCount);
    const sellCountEl = document.getElementById('tradesSellCount');
    if (sellCountEl) sellCountEl.textContent = String(sellCount);
    const depositCountEl = document.getElementById('tradesDepositCount');
    if (depositCountEl) depositCountEl.textContent = String(depositCount);
    const withdrawCountEl = document.getElementById('tradesWithdrawCount');
    if (withdrawCountEl) withdrawCountEl.textContent = String(withdrawCount);
}

// DEPRECATED: resetFinanceTradesFilters removed - filters are now replaced with period selection

function exportTradesCSV() {
    // Get current trades data from table
    const body = document.getElementById('financeTradesBody');
    if (!body || body.children.length === 0) {
        if (window.Toast) window.Toast.warning('İşlem verisi yok');
        return;
    }
    
    // Build CSV
    let csv = 'Tarih,Saat,Sembol,Yön,Miktar,Fiyat,Toplam,Komisyon,Komisyon Varlık,Bot ID,Döngü\n';
    
    Array.from(body.children).forEach(row => {
        const cells = row.children;
        if (cells.length >= 10) {
            const dateTime = cells[0].textContent.trim().split('\n');
            const date = dateTime[0] || '';
            const time = dateTime[1] || '';
            const symbol = cells[1].textContent.trim();
            const side = cells[2].textContent.trim();
            const qty = cells[3].textContent.trim();
            const price = cells[4].textContent.trim().replace('$', '').replace(',', '');
            const total = cells[5].textContent.trim().replace('$', '').replace(',', '');
            const commission = cells[6].textContent.trim();
            const commissionAsset = cells[7].textContent.trim();
            const botId = cells[8].textContent.trim();
            const cycle = cells[9].textContent.trim();
            
            csv += `"${date}","${time}","${symbol}","${side}","${qty}","${price}","${total}","${commission}","${commissionAsset}","${botId}","${cycle}"\n`;
        }
    });
    
    // Download
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    const url = URL.createObjectURL(blob);
    link.setAttribute('href', url);
    link.setAttribute('download', `trades_${new Date().toISOString().split('T')[0]}.csv`);
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    
    if (window.Toast) window.Toast.success('CSV dosyası indirildi');
}

function loadFinanceTradesPrev() {
    if (financeReportsState.tradesOffset >= financeReportsState.tradesLimit) {
        financeReportsState.tradesOffset -= financeReportsState.tradesLimit;
        loadFinanceTrades();
    }
}

function loadFinanceTradesNext() {
    financeReportsState.tradesOffset += financeReportsState.tradesLimit;
    loadFinanceTrades();
}

// DEPRECATED: triggerFinanceSync removed - data now auto-updates when Finance tab is active
// Finance tab now automatically refreshes every 10 seconds when active

function exportReportCSV() {
    // TODO: Implement CSV export
    alert('CSV export yakında eklenecek');
}

// Expose global functions
window.openCreateBotModal = openCreateBotModal;
window.closeCreateBotModal = closeCreateBotModal;
window.openBotStructureModal = openBotStructureModal;
window.closeBotStructureModal = closeBotStructureModal;
window.loadEquityCurve = loadEquityCurve;
window.loadFinanceReport = loadFinanceReport;
window.loadFinanceTrades = loadFinanceTrades;
window.loadFinanceTradesPrev = loadFinanceTradesPrev;

// ============================================================
// PERFORMANCE PROFILING HELPER
// ============================================================
/**
 * Performance dump helper for debugging
 * Usage: window.__perfDump() in console
 */
window.__perfDump = function() {
    const activeIntervals = window.intervalRegistry?.getActive() || [];
    const marketStore = window.marketStore || {};
    const pricesSize = marketStore.prices?.size || 0;
    const miniSize = marketStore.mini?.size || 0;
    const lastUpdateTs = marketStore.lastUpdateTs || 0;
    const status = marketStore.status || 'unknown';
    const age = lastUpdateTs > 0 ? Date.now() - lastUpdateTs : null;
    
    // Check marketDataService status
    const marketDataServiceRunning = window.marketDataService?.isRunning() || false;
    const errorCount = window['marketDataService.errorCount'] || 0;
    
    const dump = {
        timestamp: new Date().toISOString(),
        intervals: {
            count: activeIntervals.length,
            details: activeIntervals.map(iv => ({
                key: iv.key,
                owner: iv.owner || 'none',
                ms: iv.ms
            }))
        },
        marketStore: {
            pricesCount: pricesSize,
            miniCount: miniSize,
            status: status,
            lastUpdateTs: lastUpdateTs,
            ageMs: age,
            isStale: age !== null && age > 10000
        },
        marketDataService: {
            running: marketDataServiceRunning,
            errorCount: errorCount
        },
        render: {
            coinListDataLength: coinListData?.length || 0,
            coinListFilteredLength: coinListFiltered?.length || 0
        },
        uiHealth: typeof uiHealth !== 'undefined' ? {
            render_count: uiHealth.render_count || 0,
            last_render_ok_ts: uiHealth.last_render_ok_ts || null
        } : { render_count: 0, last_render_ok_ts: null }
    };
    
    console.table(dump.intervals.details);
    console.log('Market Store:', dump.marketStore);
    console.log('Market Data Service:', dump.marketDataService);
    console.log('Render State:', dump.render);
    console.log('UI Health (Binance render):', dump.uiHealth);
    console.log('Full Dump:', dump);
    
    return dump;
};
window.loadFinanceTradesNext = loadFinanceTradesNext;
window.loadFinanceBotDetail = loadFinanceBotDetail;
// window.triggerFinanceSync removed - auto-update enabled
window.exportReportCSV = exportReportCSV;
window.setFinancePeriod = setFinancePeriod;
window.setTradesTypeFilter = setTradesTypeFilter;
window.exportTradesCSV = exportTradesCSV;

// Admin pop-up: kullanıcıya gösterilen duyuru (X ile kapatılana kadar). İlk girişte kapatılınca API key modalı gösterilir.
var _userPopupId = null;
var _userPopupWasFirstLogin = false;
async function fetchAndShowUserPopup(isFirstLogin) {
    try {
        var q = "first_login=" + (isFirstLogin ? "true" : "false");
        var data = null;
        if (window.apiClient && typeof window.apiClient.get === "function") {
            var apiRes = await window.apiClient.get("/api/auth/popup/active?" + q, { timeout: 8000 });
            data = apiRes && (apiRes.data || apiRes);
        } else {
            var headers = { "Accept": "application/json", "X-Requested-With": "XMLHttpRequest" };
            try {
                var tok = sessionStorage.getItem("token") || localStorage.getItem("token");
                if (tok) headers.Authorization = "Bearer " + tok;
            } catch (eTok) {}
            var res = await fetch(window.location.origin + "/api/auth/popup/active?" + q, { method: "GET", credentials: "include", cache: "no-store", headers: headers });
            if (!res.ok) return false;
            data = await res.json().catch(function () { return null; });
        }
        var popup = data && data.popup;
        if (!popup || !popup.id) return false;
        var card = document.getElementById("userPopupCard");
        var overlay = document.getElementById("userPopupOverlay");
        var titleEl = document.getElementById("userPopupTitle");
        var msgEl = document.getElementById("userPopupMessage");
        if (!card || !overlay || !titleEl || !msgEl) return false;
        var titleKeys = { info: "Bilgi", warning: "Uyarı", success: "Duyuru", maintenance: "Bakım Duyurusu", announcement: "Genel Duyuru" };
        var title = (popup.title_key && titleKeys[popup.title_key]) ? titleKeys[popup.title_key] : (popup.title_key || "Duyuru");
        titleEl.textContent = title;
        msgEl.textContent = popup.message || "";
        card.className = "user-popup-card --" + (popup.title_key || "info");
        _userPopupId = popup.id;
        _userPopupWasFirstLogin = !!isFirstLogin;
        overlay.style.display = "flex";
        return true;
    } catch (e) { return false; }
}
function dismissUserPopup() {
    var overlay = document.getElementById("userPopupOverlay");
    var wasFirstLogin = _userPopupWasFirstLogin;
    if (overlay) overlay.style.display = "none";
    _userPopupWasFirstLogin = false;
    if (!_userPopupId) return;
    var popupId = _userPopupId;
    _userPopupId = null;
    if (window.apiClient && typeof window.apiClient.post === "function") {
        window.apiClient.post("/api/auth/popup/dismiss", { popup_id: popupId }, { timeout: 8000 }).catch(function () {});
    }
    if (wasFirstLogin) {
        setTimeout(function () {
            shouldShowFirstLoginModal(State.accountId, true).then(function (show) {
                if (show) {
                    var modal = document.getElementById("firstLoginModal");
                    if (modal) modal.style.display = "flex";
                }
            });
        }, 200);
    }
}
window.fetchAndShowUserPopup = fetchAndShowUserPopup;
