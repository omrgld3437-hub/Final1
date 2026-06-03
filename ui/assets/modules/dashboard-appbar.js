/**
 * dashboard-appbar.js
 * Appbar display name, account name yönetimi.
 * dashboard.html'de dashboard.js'ten SONRA yüklenir.
 */

function updateAccountName(name) {
    /* reserved */
}

function appbarDisplayNameStorageKey(accountId) {
    return 'appbarDisplayName_' + (accountId || '');
}

function lockAppbarDisplayName(accountId, displayName) {
    if (accountId == null || accountId === '' || !displayName || displayName === '—') return;
    try {
        localStorage.setItem(appbarDisplayNameStorageKey(accountId), String(displayName).trim());
    } catch (e) {}
}

function getLockedAppbarDisplayName(accountId) {
    if (accountId == null || accountId === '') return '';
    try {
        var locked = localStorage.getItem(appbarDisplayNameStorageKey(accountId));
        if (locked && locked !== '—') return locked;
    } catch (e) {}
    return '';
}

function getAppbarDisplayNameFromStoredUser(accountId) {
    try {
        var userStr = sessionStorage.getItem('user') || localStorage.getItem('user');
        if (!userStr) return '';
        var user = JSON.parse(userStr);
        if (accountId != null && user.account_id != null && String(user.account_id) !== String(accountId)) return '';
        return [user.name, user.surname].filter(Boolean).map(function (s) { return String(s).trim(); }).join(' ').trim();
    } catch (e) {
        return '';
    }
}

function ensureAppbarDisplayNameLocked(accountId) {
    var locked = getLockedAppbarDisplayName(accountId);
    if (locked) return locked;
    var fromUser = getAppbarDisplayNameFromStoredUser(accountId);
    if (fromUser) {
        lockAppbarDisplayName(accountId, fromUser);
        return fromUser;
    }
    return '';
}

function getAppbarCachedDisplayName(accountId) {
    var locked = getLockedAppbarDisplayName(accountId);
    if (locked) return locked;
    var cached = _readAppbarCache(accountId, State.accountCode || '');
    if (cached && cached.displayName && cached.displayName !== '—') return cached.displayName;
    return '';
}

function resolveAppbarDisplayName(data, accountId) {
    var locked = ensureAppbarDisplayNameLocked(accountId);
    if (locked) return locked;
    data = data || {};
    var acc = data.account || {};
    var first = data.user_name || acc.user_name || '';
    var last = data.user_surname || acc.user_surname || '';
    var fn = [first, last].filter(Boolean).map(function (s) { return String(s).trim(); }).join(' ').trim();
    if (fn) {
        lockAppbarDisplayName(accountId, fn);
        return fn;
    }
    var fromUser = getAppbarDisplayNameFromStoredUser(accountId);
    if (fromUser) {
        lockAppbarDisplayName(accountId, fromUser);
        return fromUser;
    }
    var el = document.getElementById('appbarUserName');
    if (el && el.textContent && el.textContent !== '—') return el.textContent.trim();
    var an = (acc.name || data.account_name || '').trim();
    if (an) return an;
    return '—';
}

var APPBAR_CACHE_LOCAL_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;

function _parseAppbarCacheRaw(raw, maxAgeMs) {
    if (!raw) return null;
    try {
        var o = JSON.parse(raw);
        if (!o) return null;
        if (o.ts != null && maxAgeMs != null && Date.now() - Number(o.ts) > maxAgeMs) return null;
        return o;
    } catch (e) {
        return null;
    }
}

function _readAppbarCache(accountId, accountCode) {
    var code = accountCode != null && accountCode !== '' ? String(accountCode).trim() : '';
    var id = accountId != null && accountId !== '' ? String(accountId) : '';
    var candidates = [];
    if (id) {
        candidates.push(_parseAppbarCacheRaw(sessionStorage.getItem('dashboardAppbar_' + id), null));
        candidates.push(_parseAppbarCacheRaw(localStorage.getItem('dashboardAppbar_ls_' + id), APPBAR_CACHE_LOCAL_MAX_AGE_MS));
        candidates.push({ displayName: sessionStorage.getItem('appbarUserName_' + id), accountCode: code });
    }
    if (code) {
        candidates.push(_parseAppbarCacheRaw(sessionStorage.getItem('dashboardAppbar_code_' + code), null));
        candidates.push(_parseAppbarCacheRaw(localStorage.getItem('dashboardAppbar_code_ls_' + code), APPBAR_CACHE_LOCAL_MAX_AGE_MS));
    }
    for (var i = 0; i < candidates.length; i++) {
        var c = candidates[i];
        if (c && c.displayName && c.displayName !== '—') return c;
    }
    return null;
}

/** Appbar isim + ID — flicker önleme; yenilemede anında. */
function applyAppbarSnapshot(displayName, accountCode, accountId, idLabel) {
    var nameEl = document.getElementById('appbarUserName');
    var idEl = document.getElementById('appbarAccountId');
    var code = accountCode != null && accountCode !== '' ? String(accountCode).trim() : '';
    var id = accountId != null && accountId !== '' ? String(accountId) : '';
    var name = (displayName || '').trim();
    if (!name && id) name = getLockedAppbarDisplayName(id) || getAppbarCachedDisplayName(id);
    if (!name && code) {
        var byCode = _readAppbarCache(null, code);
        if (byCode && byCode.displayName) name = byCode.displayName;
    }
    if (name && name !== '—' && nameEl) setTextIfChanged(nameEl, name);
    if (name && name !== '—' && id) State.appbarNameAccountId = Number(id) || id;
    if (idEl) {
        var label = idLabel || (code ? ('ID: ' + code) : (id ? ('ID: ' + id) : 'ID: —'));
        if (label !== 'ID: —') {
            setTextIfChanged(idEl, label);
            if (idEl.style.display !== 'block') idEl.style.display = 'block';
        }
    }
}

function paintAppbarDisplayName(accountId) {
    var nameEl = document.getElementById('appbarUserName');
    if (!nameEl) return '';
    var displayName = ensureAppbarDisplayNameLocked(accountId) || getAppbarCachedDisplayName(accountId);
    if (displayName) setTextIfChanged(nameEl, displayName);
    if (displayName) State.appbarNameAccountId = accountId;
    return displayName || '';
}

function setAppbarAccountHolderName(data) {
    var accountId = State.accountId ?? data.account_id ?? (data.account && data.account.id);
    var accountCode = State.accountCode || (data.account_code ?? (data.account && data.account.account_code));
    var locked = getLockedAppbarDisplayName(accountId);
    var displayName = locked || resolveAppbarDisplayName(data, accountId);
    if (!locked && displayName && displayName !== '—') lockAppbarDisplayName(accountId, displayName);
    applyAppbarSnapshot(displayName, accountCode, accountId);
    if (displayName && displayName !== '—') persistAppbarSessionCache(accountId, displayName, accountCode);
}

function persistAppbarSessionCache(accountId, displayName, accountCode) {
    if ((accountId == null || accountId === '') && (accountCode == null || accountCode === '')) return;
    try {
        var code = accountCode != null && accountCode !== '' ? String(accountCode).trim() : '';
        var id = accountId != null && accountId !== '' ? String(accountId) : '';
        var idLabel = code ? ('ID: ' + code) : (id ? ('ID: ' + id) : 'ID: —');
        var payload = {
            ts: Date.now(),
            displayName: displayName || '',
            accountCode: code,
            idLabel: idLabel
        };
        if (id) {
            sessionStorage.setItem('dashboardAppbar_' + id, JSON.stringify(payload));
            localStorage.setItem('dashboardAppbar_ls_' + id, JSON.stringify(payload));
        }
        if (code) {
            sessionStorage.setItem('dashboardAppbar_code_' + code, JSON.stringify(payload));
            localStorage.setItem('dashboardAppbar_code_ls_' + code, JSON.stringify(payload));
        }
        if (displayName && displayName !== '—' && id) {
            sessionStorage.setItem('appbarUserName_' + id, displayName);
        }
    } catch (e) {}
}

function restoreAppbarFromSessionCache(accountId, accountCode) {
    if ((accountId == null || accountId === '') && (accountCode == null || accountCode === '')) return false;
    var cached = _readAppbarCache(accountId, accountCode);
    var locked = accountId != null ? getLockedAppbarDisplayName(accountId) : '';
    var displayName = locked || (cached && cached.displayName) || '';
    var code = (accountCode != null && accountCode !== '') ? String(accountCode).trim()
        : ((cached && cached.accountCode) || '');
    if (!displayName && accountId) displayName = paintAppbarDisplayName(accountId);
    if (displayName || code || accountId) {
        applyAppbarSnapshot(displayName, code, accountId, cached && cached.idLabel);
        return !!(displayName || code);
    }
    return false;
}

function restoreAppbarEarlyFromStorage(accountId, accountCode) {
    return restoreAppbarFromSessionCache(accountId, accountCode);
}
window.applyAppbarSnapshot = applyAppbarSnapshot;
window.restoreAppbarEarlyFromStorage = restoreAppbarEarlyFromStorage;

function shouldShowAdminNav(user) {
    var fromAdminUrl = new URLSearchParams(window.location.search).get('from_admin') === '1';
    if (fromAdminUrl) {
        try { sessionStorage.setItem('dashboard_from_admin', '1'); } catch (e) {}
    }
    var fromAdminStored = false;
    try { fromAdminStored = sessionStorage.getItem('dashboard_from_admin') === '1'; } catch (e) {}
    return !!(user && user.is_admin) && (fromAdminUrl || fromAdminStored);
}

function patchAdminLinkVisibility(show) {
    var adminLink = document.getElementById('adminLink');
    if (!adminLink) return;
    var target = show ? 'inline-flex' : 'none';
    if (adminLink.style.display !== target) adminLink.style.display = target;
}
window.restoreAppbarFromSessionCache = restoreAppbarFromSessionCache;

/** Değer değişmediyse DOM'a dokunma; flicker önler. Returns true if updated. */
function setTextIfChanged(el, newText) {
    if (!el) return false;
    var s = (newText == null || newText === '') ? '' : String(newText);
    if (el.textContent === s) return false;
    el.textContent = s;
    return true;
}
window.setTextIfChanged = setTextIfChanged;

/** KPI / strip USD: 2 ondalık gösterim — cent altı DOM güncellemesi yok (canlı fiyat tick flicker). */
function kpiUsdCents(n) {
    if (n == null || !Number.isFinite(Number(n))) return null;
    return Math.round(Number(n) * 100);
}
function kpiUsdDisplayChanged(prevNum, nextNum) {
    var a = kpiUsdCents(prevNum);
    var b = kpiUsdCents(nextNum);
    if (a == null && b == null) return false;
    if (a == null || b == null) return true;
    return a !== b;
}
function setKpiUsdTextIfChanged(el, value) {
    if (!el) return false;
    var next = Number(value);
    if (!Number.isFinite(next)) return false;
    var prevAttr = parseFloat(el.getAttribute('data-kpi-value') || '');
    var prev = Number.isFinite(prevAttr) ? prevAttr : (parseFloat(String(el.textContent).replace(/[^0-9.-]/g, '')) || 0);
    if (!kpiUsdDisplayChanged(prev, next)) return false;
    el.setAttribute('data-kpi-value', String(next));
    return setTextIfChanged(el, fmtUsd(next));
}
function kpiPctDisplayChanged(prevPct, nextPct) {
    var a = Math.round((Number(prevPct) || 0) * 100);
    var b = Math.round((Number(nextPct) || 0) * 100);
    return a !== b;
}
function setKpiPctTextIfChanged(el, pctNum) {
    if (!el) return false;
    var next = Number(pctNum);
    if (!Number.isFinite(next)) return false;
    var prevAttr = parseFloat(el.getAttribute('data-kpi-pct') || '');
    var prev = Number.isFinite(prevAttr) ? prevAttr : (parseFloat(String(el.textContent).replace(/[^0-9.+\-]/g, '')) || 0);
    if (!kpiPctDisplayChanged(prev, next)) return false;
    el.setAttribute('data-kpi-pct', String(next));
    var txt = (next >= 0 ? '+' : '') + next.toFixed(2) + '%';
    return setTextIfChanged(el, txt);
}

var _blinkCooldownUntil = 0;
var BLINK_COOLDOWN_MS = 400;

/** Test paper: KPI + varlık strip canlı güncellenir; yeşil/kırmızı blink yok. */
var TEST_ACCOUNT_NO_BLINK_IDS = {
    kpiCuzdan: true,
    kpiCuzdanPnl: true,
    kpiCuzdanPnlPct: true,
    binanceAvailableAssets: true,
    binanceBotLockedAssets: true,
    binanceLockedAssets: true
};

/** Proje geneli blink: bakiye/PnL değişince yeşil/kırmızı. Cooldown ile aynı anda iki blink engellenir. */
function triggerValueBlink(el, newNum) {
    if (!el) return;
    if (typeof State !== 'undefined' && State.isTestAccount) {
        if (el.id && TEST_ACCOUNT_NO_BLINK_IDS[el.id]) return;
        if (el.classList && el.classList.contains('value-cell')) return;
        if (el.closest && el.closest('#varliklarTableBody') && !(el.classList && el.classList.contains('price-cell'))) return;
    }
    var now = Date.now();
    if (now < _blinkCooldownUntil) return;
    var oldNum = parseFloat(String(el.textContent).replace(/[^0-9.-]/g, '')) || 0;
    if (Math.abs((newNum || 0) - oldNum) < 0.001) return;
    _blinkCooldownUntil = now + BLINK_COOLDOWN_MS;
    el.classList.remove('blink-positive', 'blink-negative');
    void el.offsetWidth;
    if (newNum > oldNum) el.classList.add('blink-positive');
    else el.classList.add('blink-negative');
    setTimeout(function() { el.classList.remove('blink-positive', 'blink-negative'); }, 750);
}
window.triggerValueBlink = triggerValueBlink;

