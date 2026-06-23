/**
 * dashboard-wallet-state.js
 * Wallet state yönetimi: live/stale flag, KPI cüzdan, rozet fonksiyonları.
 * dashboard.html'de dashboard.js'ten SONRA yüklenir.
 */

var lastSpotUpdateTs = 0;
var _walletLiveOkAt = 0;
var _walletLiveFailedAt = 0;
// Sayfa yüklenince ilk 3 saniye "Güncel değil" gösterme; canlı veri yoksa ardından çıksın.
var _walletStaleGracePeriodUntil = Date.now() + 3000;
var _kpiCuzdanPnlDisplay = { pnlUsd: null, pnlPct: null };
var _kpiCuzdanLastSpot = 0;
var KPI_CUZDAN_SESSION_PREFIX = "kpi_cuzdan_snap_v1_";
var KPI_CUZDAN_SESSION_MAX_AGE_MS = 24 * 60 * 60 * 1000;
var KPI_CUZDAN_LOCAL_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;
var _walletStaleUi = { wasStale: false, liveSince: null, liveHoldUntil: 0 };
var _walletPanelUpdating = false;
var _walletPanelUpdatingClearTimer = null;
var _walletPanelStaleTimer = null;
var _walletPanelStaleFailureAt = 0;
var WALLET_LIVE_OK_TTL_MS = 300000;
var WALLET_STALE_BADGE_HYSTERESIS_MS = 45000;
var WALLET_STALE_HIDE_AFTER_LIVE_MS = 15000;
var WALLET_PANEL_STALE_DELAY_MS = 10000;
var _dashboardWalletForceTick = 0;
var _binanceWalletIdleCycles = 0;

function cancelWalletPanelStaleBadgeTimer() {
    if (_walletPanelStaleTimer) {
        clearTimeout(_walletPanelStaleTimer);
        _walletPanelStaleTimer = null;
    }
}

function scheduleWalletPanelStaleBadgeAfterFailure() {
    cancelWalletPanelStaleBadgeTimer();
    _walletPanelStaleFailureAt = Date.now();
    _walletPanelStaleTimer = setTimeout(function () {
        _walletPanelStaleTimer = null;
        if (typeof syncWalletPanelStatusBadges === 'function') syncWalletPanelStatusBadges();
    }, WALLET_PANEL_STALE_DELAY_MS);
    if (typeof syncWalletPanelStatusBadges === 'function') syncWalletPanelStatusBadges();
}

/** Panel rozeti: canlı değil + güncelleme yok. */
function shouldShowWalletPanelStaleBadge() {
    if (typeof State !== 'undefined' && State.isTestAccount) return false;
    if (!assetsState.wallet || assetsState.wallet.keys_configured !== true) return false;
    if (isWalletPanelUpdating()) return false;
    return !isWalletDataLive();
}

/** Cüzdan paneli: yalnızca «Güncelleniyor» veya «Güncel değil» (aynı anda ikisi değil). */
function isWalletPanelUpdating() {
    if (_walletPanelUpdating) return true;
    if (typeof assetsState !== 'undefined' && assetsState.wallet) {
        var st = assetsState.wallet.status;
        if ((st === 'loading' || st === 'idle') && typeof _walletHasDisplayableAssets === 'function'
            && !_walletHasDisplayableAssets() && !_walletBinanceCacheHydrated) {
            return true;
        }
    }
    return false;
}

function syncWalletPanelStatusBadges() {
    var updatingEl = document.getElementById('flashHomeUpdatingBadge');
    var staleEl = document.getElementById('bnAssetsStaleBadge');
    var liveEl = document.getElementById('bnWalletLiveBadge');
    var updating = isWalletPanelUpdating();

    if (updatingEl) {
        updatingEl.hidden = !updating;
        updatingEl.setAttribute('aria-hidden', updating ? 'false' : 'true');
    }
    if (updating) {
        if (liveEl) {
            liveEl.hidden = true;
            liveEl.textContent = '';
            liveEl.classList.remove('kpi-spot-status--live', 'kpi-spot-status--stale', 'kpi-spot-status--offline', 'kpi-spot-status--test');
        }
        if (staleEl) staleEl.hidden = true;
        return;
    }
    if (typeof State !== 'undefined' && State.isTestAccount) {
        if (liveEl && typeof applyWalletStaleWarningEl === 'function') applyWalletStaleWarningEl(liveEl);
        if (staleEl) staleEl.hidden = true;
        return;
    }
    if (liveEl && typeof applyWalletStaleWarningEl === 'function') {
        applyWalletStaleWarningEl(liveEl);
    }
    if (staleEl) {
        var staleText = typeof walletStaleStatusText === 'function' ? walletStaleStatusText() : 'Güncel değil';
        staleEl.textContent = staleText;
        var lastText = typeof walletLastUpdatedText === 'function' ? walletLastUpdatedText() : '';
        staleEl.title = lastText
            ? ('Son başarılı cüzdan güncellemesi: ' + lastText + '. Sistem otomatik tekrar deneyecek.')
            : 'Canlı Binance cüzdan yenilemesi şu anda başarısız. Sistem otomatik tekrar deneyecek.';
        staleEl.hidden = true;
    }
    // Bot detay sayfasının wallet stale durumunu bilmesi için localStorage'a yaz (grace period geçmişse).
    try {
        var isLive = typeof isWalletDataLive === 'function' ? isWalletDataLive() : true;
        if (!isLive && Date.now() >= _walletStaleGracePeriodUntil && typeof walletStaleStatusText === 'function') {
            var staleMsg = walletStaleStatusText();
            localStorage.setItem('wallet_stale_for_botdetail_v1', JSON.stringify({ msg: staleMsg, ts: Date.now() }));
        } else if (isLive) {
            localStorage.removeItem('wallet_stale_for_botdetail_v1');
        }
    } catch (e) {}
}
window.syncWalletPanelStatusBadges = syncWalletPanelStatusBadges;

function setWalletPanelUpdating(updating) {
    _walletPanelUpdating = !!updating;
    if (_walletPanelUpdatingClearTimer) {
        clearTimeout(_walletPanelUpdatingClearTimer);
        _walletPanelUpdatingClearTimer = null;
    }
    if (updating) {
        cancelWalletPanelStaleBadgeTimer();
        _walletPanelUpdatingClearTimer = setTimeout(function () {
            _walletPanelUpdatingClearTimer = null;
            if (!_walletPanelUpdating) return;
            _walletPanelUpdating = false;
            if (typeof updateKpiCuzdanLiveStatus === 'function') updateKpiCuzdanLiveStatus();
            else if (typeof syncWalletPanelStatusBadges === 'function') syncWalletPanelStatusBadges();
        }, 28000);
    }
    syncWalletPanelStatusBadges();
    applyWalletStaleWarningEl(document.getElementById('kpiCuzdanLive'));
}
window.setWalletPanelUpdating = setWalletPanelUpdating;

function markWalletLiveFetchOk() {
    _walletLiveOkAt = Date.now();
    _walletLiveFailedAt = 0;
    _walletPanelStaleFailureAt = 0;
    _walletStaleUi.wasStale = false;
    _walletStaleUi.liveSince = null;
    _walletStaleUi.liveHoldUntil = Date.now() + WALLET_STALE_BADGE_HYSTERESIS_MS;
    if (typeof State !== 'undefined') State.walletLastErrorCode = null;
    if (assetsState.wallet && assetsState.wallet.error) {
        assetsState.wallet.error = null;
    }
    cancelWalletPanelStaleBadgeTimer();
    if (typeof updateKpiCuzdanLiveStatus === 'function') updateKpiCuzdanLiveStatus();
    else if (typeof syncWalletPanelStatusBadges === 'function') syncWalletPanelStatusBadges();
}
window.markWalletLiveFetchOk = markWalletLiveFetchOk;

function markWalletLiveFetchFailed(errorCode, opts) {
    opts = opts || {};
    var code = errorCode ? String(errorCode).toUpperCase() : '';
    var hasCache = typeof _walletHasDisplayableAssets === 'function' && _walletHasDisplayableAssets();
    var transient = !code || /BINANCE_TIMEOUT|BINANCE_UNREACHABLE|WALLET_REFRESH|WALLET_TIMEOUT|INFLIGHT/.test(code);
    if (!opts.force && transient && hasCache) {
        _walletLiveFailedAt = Date.now();
        if (code && typeof State !== 'undefined') State.walletLastErrorCode = code;
        if (assetsState.wallet) assetsState.wallet.data_status = 'stale';
        scheduleSilentWalletRecovery();
        scheduleWalletPanelStaleBadgeAfterFailure();
        if (typeof updateKpiCuzdanLiveStatus === 'function') updateKpiCuzdanLiveStatus();
        return;
    }
    _walletLiveFailedAt = Date.now();
    if (code && typeof State !== 'undefined') State.walletLastErrorCode = code;
    if (code && assetsState.wallet) {
        assetsState.wallet.error = {
            message: assetsState.wallet.error && assetsState.wallet.error.message
                ? assetsState.wallet.error.message
                : 'Canlı cüzdan yenilenemedi',
            error_code: code
        };
        assetsState.wallet.status = 'error';
    }
    scheduleWalletPanelStaleBadgeAfterFailure();
    if (typeof updateKpiCuzdanLiveStatus === 'function') updateKpiCuzdanLiveStatus();
}
window.markWalletLiveFetchFailed = markWalletLiveFetchFailed;

function _isHardWalletError(code) {
    var c = String(code || '').toUpperCase();
    if (!c) return false;
    return /API_UNAUTHORIZED|ACCOUNT_KEYS|CLOCK_DRIFT|-2015|KEYS_DECRYPT|KEYS_MISSING|KEYS_EMPTY/.test(c);
}
window._isHardWalletError = _isHardWalletError;

function markWalletCachedLiveFetchStale(errorCode) {
    var code = errorCode ? String(errorCode).toUpperCase() : 'WALLET_STALE';
    var hard = _isHardWalletError(code);
    _walletLiveFailedAt = Date.now();
    if (typeof State !== 'undefined') State.walletLastErrorCode = code;
    if (assetsState.wallet) {
        assetsState.wallet.data_status = 'stale';
        if (assetsState.wallet.status !== 'error') assetsState.wallet.status = 'ready';
        assetsState.wallet.error = hard
            ? {
                message: assetsState.wallet.error && assetsState.wallet.error.message
                    ? assetsState.wallet.error.message
                    : 'Canlı cüzdan yenilenemedi',
                error_code: code
            }
            : null;
    }
    scheduleSilentWalletRecovery();
    scheduleWalletPanelStaleBadgeAfterFailure();
    if (typeof updateKpiCuzdanLiveStatus === 'function') updateKpiCuzdanLiveStatus();
    if (window.BinanceAssetsPanel && typeof window.BinanceAssetsPanel.render === 'function') window.BinanceAssetsPanel.render();
    else if (typeof renderVarliklarList === 'function') renderVarliklarList();
}
window.markWalletCachedLiveFetchStale = markWalletCachedLiveFetchStale;

function _isLiveWalletSource(source) {
    return /binance_wallet|wallet_refresh|wallet_live|homeFlash_live/i.test(String(source || ''));
}

function _walletLiveFailedAfterOk() {
    return _walletLiveFailedAt > 0 && (!_walletLiveOkAt || _walletLiveFailedAt > _walletLiveOkAt);
}

/** Gerçek canlı Binance cüzdan verisi (KPI/PnL iç mantığı). */
function isWalletDataLive() {
    if (typeof State !== 'undefined' && State.isTestAccount) return true;
    if (!assetsState.wallet || assetsState.wallet.keys_configured !== true) return false;
    var code = walletErrorCode();
    if (_isHardWalletError(code)) return false;
    if (assetsState.wallet.status === 'error') return false;
    if (assetsState.wallet.data_status === 'stale') return false;
    if (_walletLiveFailedAfterOk()) return false;
    if (_walletLiveOkAt && (Date.now() - _walletLiveOkAt) <= WALLET_LIVE_OK_TTL_MS) return true;
    if (assetsState.wallet.data_status === 'fresh') return true;
    return false;
}
window.isWalletDataLive = isWalletDataLive;

function walletErrorCode() {
    if (typeof State !== 'undefined' && State.walletLastErrorCode) {
        return String(State.walletLastErrorCode).toUpperCase();
    }
    var e = assetsState.wallet && assetsState.wallet.error;
    if (!e) return '';
    return String(e.error_code || '').toUpperCase();
}
window.walletErrorCode = walletErrorCode;

function parseDashboardWalletTime(raw) {
    if (raw == null || raw === '') return null;
    if (typeof raw === 'number') {
        var dn = new Date(raw);
        return isNaN(dn.getTime()) ? null : dn;
    }
    var s = String(raw).trim();
    if (!s) return null;
    if (s.indexOf('T') < 0 && s.indexOf(' ') > 0) s = s.replace(' ', 'T');
    if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(s) && !/[zZ]|[+\-]\d{2}:?\d{2}$/.test(s)) s += 'Z';
    var d = new Date(s);
    return isNaN(d.getTime()) ? null : d;
}

function walletLastUpdatedDate() {
    var w = assetsState && assetsState.wallet ? assetsState.wallet : null;
    var raw = w && w.ts ? w.ts : null;
    if (!raw && window.__walletDebugMeta) raw = window.__walletDebugMeta.wallet_ts_iso;
    return parseDashboardWalletTime(raw);
}
window.walletLastUpdatedDate = walletLastUpdatedDate;

function walletLastUpdatedText() {
    var d = walletLastUpdatedDate();
    if (!d) return '';
    try {
        return d.toLocaleString('tr-TR', {
            timeZone: 'Europe/Istanbul',
            day: '2-digit',
            month: '2-digit',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    } catch (e) {
        return '';
    }
}
window.walletLastUpdatedText = walletLastUpdatedText;

/** Stale KPI rozeti: yalnızca gerçek bağlantı/API hatasında. */
function walletStaleStatusText() {
    var code = walletErrorCode();
    if (!_isHardWalletError(code) && typeof isWalletDataLive === 'function' && isWalletDataLive()) return 'Canlı';
    var last = walletLastUpdatedText();
    return last ? ('Güncel değil · Son: ' + last) : 'Güncel değil';
}
window.walletStaleStatusText = walletStaleStatusText;

function walletErrorDetailText() {
    var code = walletErrorCode();
    if (!code) return '';
    if (code === 'CLOCK_DRIFT') return 'Neden: sunucu saat senkronu.';
    if (code === 'API_UNAUTHORIZED' || code.indexOf('KEY') >= 0) return 'Neden: API anahtarı / IP yetkisi.';
    return 'Neden: ' + code + '.';
}
window.walletErrorDetailText = walletErrorDetailText;

/** Cüzdan durum etiketi (iç mantık; UI'da Canlı gösterilmez). */
function walletLiveStatusLabel() {
    if (typeof State !== 'undefined' && State.isTestAccount) return 'Test';
    if (assetsState.wallet.keys_configured !== true) return 'Bağlı değil';
    if (isWalletDataLive()) return 'Canlı';
    return walletStaleStatusText();
}
window.walletLiveStatusLabel = walletLiveStatusLabel;

/** KPI stale uyarısı — canlıyken gizle; yalnızca gerçekten eski/hatalı veride göster. */
function shouldShowWalletStaleWarning() {
    if (typeof State !== 'undefined' && State.isTestAccount) return false;
    if (assetsState.wallet.keys_configured !== true) {
        _walletStaleUi.wasStale = false;
        _walletStaleUi.liveSince = null;
        return false;
    }
    if (isWalletDataLive()) {
        _walletStaleUi.wasStale = false;
        _walletStaleUi.liveSince = null;
        return false;
    }
    if (typeof isWalletPanelUpdating === 'function' && isWalletPanelUpdating()) {
        return false;
    }
    // 3 saniyelik grace: yüklenme anında "Canlı"dan "Güncel değil"e geçişi engelle.
    if (Date.now() < _walletStaleGracePeriodUntil) {
        return false;
    }
    _walletStaleUi.liveSince = null;
    _walletStaleUi.wasStale = true;
    return true;
}
window.shouldShowWalletStaleWarning = shouldShowWalletStaleWarning;

/** KPI/Binance rozeti: canlı → Canlı; değilse Güncel değil (kpiBotBakiyePct yalnızca uyarı). */
function applyWalletStaleWarningEl(el) {
    if (!el) return;
    var warnOnly = el.id === 'kpiBotBakiyePct';
    if (typeof State !== 'undefined' && State.isTestAccount) {
        if (warnOnly) {
            el.hidden = true;
            el.textContent = '';
            el.classList.remove('kpi-spot-status--live', 'kpi-spot-status--stale', 'kpi-spot-status--offline', 'kpi-spot-status--test');
            return;
        }
        el.hidden = false;
        el.textContent = 'Test';
        el.classList.toggle('kpi-spot-status--test', true);
        el.classList.toggle('kpi-spot-status--live', false);
        el.classList.toggle('kpi-spot-status--stale', false);
        el.classList.toggle('kpi-spot-status--offline', false);
        return;
    }
    if (assetsState.wallet.keys_configured !== true) {
        el.hidden = true;
        el.textContent = '';
        el.classList.remove('kpi-spot-status--live', 'kpi-spot-status--stale', 'kpi-spot-status--offline', 'kpi-spot-status--test');
        return;
    }
    if (isWalletDataLive()) {
        if (warnOnly) {
            el.hidden = true;
            el.textContent = '';
            el.classList.remove('kpi-spot-status--live', 'kpi-spot-status--stale', 'kpi-spot-status--offline');
            return;
        }
        el.hidden = false;
        el.textContent = 'Canlı';
        el.title = 'Cüzdan Binance üzerinden canlı güncellendi.';
        el.classList.toggle('kpi-spot-status--live', true);
        el.classList.toggle('kpi-spot-status--stale', false);
        el.classList.toggle('kpi-spot-status--offline', false);
        el.classList.toggle('kpi-spot-status--test', false);
        return;
    }
    var activeFailure = !!walletErrorCode() || _walletLiveFailedAfterOk();
    var showStale = activeFailure || shouldShowWalletStaleWarning();
    if (!activeFailure && !showStale && _walletStaleUi.liveHoldUntil && Date.now() < _walletStaleUi.liveHoldUntil) {
        if (warnOnly) {
            el.hidden = true;
            el.textContent = '';
            el.classList.remove('kpi-spot-status--live', 'kpi-spot-status--stale', 'kpi-spot-status--offline');
            return;
        }
        el.hidden = false;
        el.textContent = 'Canlı';
        el.title = 'Cüzdan Binance üzerinden güncellendi.';
        el.classList.toggle('kpi-spot-status--live', true);
        el.classList.toggle('kpi-spot-status--stale', false);
        el.classList.toggle('kpi-spot-status--offline', false);
        el.classList.toggle('kpi-spot-status--test', false);
        return;
    }
    if (!showStale && warnOnly) {
        el.hidden = true;
        el.textContent = '';
        el.classList.remove('kpi-spot-status--live', 'kpi-spot-status--stale', 'kpi-spot-status--offline');
        return;
    }
    if (!showStale) {
        el.hidden = true;
        el.textContent = '';
        el.classList.remove('kpi-spot-status--live', 'kpi-spot-status--stale', 'kpi-spot-status--offline');
        return;
    }
    el.hidden = false;
    var statusText = walletStaleStatusText();
    var lastText = walletLastUpdatedText();
    var detailText = walletErrorDetailText();
    el.textContent = statusText;
    el.title = (detailText ? (detailText + ' ') : '') + (lastText
        ? ('Son görünen bakiye korunuyor. Son başarılı cüzdan güncellemesi: ' + lastText + '. Sistem otomatik tekrar deneyecek.')
        : 'Son görünen bakiye korunuyor; canlı Binance cüzdan yenilemesi şu anda başarısız. Sistem otomatik tekrar deneyecek.');
    el.classList.toggle('kpi-spot-status--stale', true);
    el.classList.toggle('kpi-spot-status--live', false);
    el.classList.toggle('kpi-spot-status--offline', false);
    el.classList.toggle('kpi-spot-status--test', false);
    if (walletErrorCode() === 'CLOCK_DRIFT') {
        el.classList.toggle('kpi-spot-status--clock', true);
    } else {
        el.classList.remove('kpi-spot-status--clock');
    }
}
window.applyWalletStaleWarningEl = applyWalletStaleWarningEl;

var _clockDriftToastAt = 0;
var _walletConnectivityToastAt = 0;
var _walletConnectivitySuccessToastAt = 0;
var CLOCK_DRIFT_TOAST_DEBOUNCE_MS = 120000;
var WALLET_CONNECTIVITY_TOAST_DEBOUNCE_MS = 120000;
var WALLET_CONNECTIVITY_SUCCESS_TOAST_DEBOUNCE_MS = 120000;

function _walletHasCachedBalance() {
    return typeof _walletHasDisplayableAssets === 'function' && _walletHasDisplayableAssets();
}

/** Geçici Binance/ağ hatasında toast spam etme; önbellek varsa sessiz yeniden dene. */
function debouncedWalletConnectivityToast(code, msg) {
    if (typeof window.Toast === 'undefined' || !window.Toast.warning) return;
    var c = String(code || '').toUpperCase();
    var now = Date.now();
    if (c !== 'API_UNAUTHORIZED' && c.indexOf('KEY') < 0 && _walletHasCachedBalance()
        && /BINANCE_TIMEOUT|BINANCE_UNREACHABLE|WALLET_REFRESH|WALLET_TIMEOUT/.test(c)) {
        return;
    }
    if (c === 'CLOCK_DRIFT') {
        if (now - _clockDriftToastAt < CLOCK_DRIFT_TOAST_DEBOUNCE_MS) return;
        _clockDriftToastAt = now;
    } else if (/BINANCE_TIMEOUT|BINANCE_UNREACHABLE|WALLET_REFRESH|API_UNAUTHORIZED/.test(c)) {
        if (now - _walletConnectivityToastAt < WALLET_CONNECTIVITY_TOAST_DEBOUNCE_MS) return;
        _walletConnectivityToastAt = now;
    }
    window.Toast.warning(msg || (typeof connectivityCheckToastMessage === 'function'
        ? connectivityCheckToastMessage({ error_code: c })
        : 'Canlı cüzdan yenilenemedi.'));
}
window.debouncedWalletConnectivityToast = debouncedWalletConnectivityToast;

/** CLOCK_DRIFT uyarısını en fazla 2 dk'da bir göster; diğer kodlar normal toast. */
function maybeToastConnectivityWarning(d) {
    if (typeof window.Toast === 'undefined' || !window.Toast.warning) return;
    var code = String((d && (d.error_code || d.wallet_last_error_code)) || '').toUpperCase();
    debouncedWalletConnectivityToast(code, connectivityCheckToastMessage(d));
}
window.maybeToastConnectivityWarning = maybeToastConnectivityWarning;

function connectivityCheckToastMessage(d) {
    if (!d) return 'Binance bağlantısı kontrol edilemedi.';
    var code = String(d.error_code || d.wallet_last_error_code || '').toUpperCase();
    var ip = (d.server_public_ip && d.server_public_ip !== '—') ? d.server_public_ip : '';
    if (code === 'CLOCK_DRIFT') {
        return 'Sunucu saati Binance ile uyuşmuyor (-1021). ' + (d.clock_sync_hint || 'NTP ile saat senkronu gerekli.');
    }
    if (code === 'API_UNAUTHORIZED' || code.indexOf('KEY') >= 0) {
        return (ip
            ? 'Binance 401: API anahtarı veya IP beyaz liste. Sunucu dış IP: ' + ip + ' (PC IP değil).'
            : 'Binance 401: API anahtarı veya IP beyaz liste hatası.');
    }
    if (code === 'BINANCE_TIMEOUT' || code === 'BINANCE_UNREACHABLE') {
        return (ip
            ? 'Binance API bağlantısı kurulamadı. Sunucu dış IP adresinin (' + ip + ') Binance API beyaz listesine tanımlı olduğundan emin olun.'
            : 'Binance API bağlantısı kurulamadı. Ayarlar bölümündeki sunucu dış IP adresinin Binance API beyaz listesine tanımlı olduğundan emin olun.');
    }
    if (d.message) return String(d.message).slice(0, 220);
    return 'Canlı cüzdan yenilenemedi.';
}

/** Kullanıcıya gösterilen gerçek bağlantı/cüzdan hatası var mı (geçici TTL stale değil). */
function _hadUserVisibleConnectivityIssue() {
    if (typeof State !== 'undefined' && State.isTestAccount) return false;
    var code = typeof walletErrorCode === 'function' ? walletErrorCode() : '';
    if (code && /BINANCE_|CLOCK_DRIFT|API_UNAUTHORIZED|WALLET_REFRESH|WALLET_TIMEOUT/.test(code)) return true;
    if (typeof _walletLiveFailedAfterOk === 'function' && _walletLiveFailedAfterOk()) return true;
    if (_walletStaleUi.wasStale) return true;
    var w = assetsState.wallet;
    if (!w) return false;
    if (w.status === 'error' && w.error) return true;
    if (w.data_status === 'stale') {
        if (typeof _walletHasCachedBalance === 'function' && !_walletHasCachedBalance()) return true;
        if (typeof _walletLiveFailedAfterOk === 'function' && _walletLiveFailedAfterOk()) return true;
    }
    return false;
}

/** İnternet / API geri gelince: kilit + stale bayrak sıfırla, canlı cüzdan + snapshot yenile. */
function recoverDashboardAfterConnectivity(opts) {
    opts = opts || {};
    if (!State.accountId) return;
    var hadIssue = _hadUserVisibleConnectivityIssue();
    var aid = State.accountId;
    try {
        localStorage.removeItem('tt_wallet_refresh_lock:' + aid);
    } catch (e) {}
    if (window.homeFlash && typeof window.homeFlash.resetRefreshThrottle === 'function') {
        window.homeFlash.resetRefreshThrottle(aid);
    }
    if (window.marketDataService) {
        if (typeof window.marketDataService.stop === 'function') window.marketDataService.stop();
        if (typeof window.marketDataService.start === 'function') window.marketDataService.start();
    }
    if (typeof fetchSnapshot === 'function') fetchSnapshot();
    if (window.FLASH_HOME_ENABLED && window.homeFlash && typeof window.homeFlash.triggerRefresh === 'function') {
        window.homeFlash.triggerRefresh(aid, true);
    } else if (typeof triggerWalletRefreshForVarliklar === 'function') {
        triggerWalletRefreshForVarliklar(aid, { force: true });
    }
    if (opts.summary !== false && typeof loadSummary === 'function') loadSummary(aid);
    if (typeof updateKpiCuzdanLiveStatus === 'function') updateKpiCuzdanLiveStatus();
    if (window.apiClient && typeof window.apiClient.get === 'function') {
        window.apiClient.get('/api/home/connectivity-check?account_id=' + aid, { timeout: 20000 })
            .then(function (res) {
                var d = res && res.data;
                if (!d || typeof window.Toast === 'undefined') return;
                var errCode = String(d.error_code || d.wallet_last_error_code || '').toUpperCase();
                if (errCode && typeof State !== 'undefined') State.walletLastErrorCode = errCode;
                if (typeof updateKpiCuzdanLiveStatus === 'function') updateKpiCuzdanLiveStatus();
                if (d.connectivity_ok) {
                    if (hadIssue && window.Toast.success) {
                        var nowOk = Date.now();
                        if (nowOk - _walletConnectivitySuccessToastAt >= WALLET_CONNECTIVITY_SUCCESS_TOAST_DEBOUNCE_MS) {
                            _walletConnectivitySuccessToastAt = nowOk;
                            window.Toast.success('Binance bağlantısı kuruldu.');
                        }
                    }
                    if (typeof State !== 'undefined') State.walletLastErrorCode = null;
                    if (typeof markWalletLiveFetchOk === 'function') markWalletLiveFetchOk();
                    return;
                }
                if (_walletHasCachedBalance()) return;
                if (typeof maybeToastConnectivityWarning === 'function') {
                    maybeToastConnectivityWarning(d);
                } else if (window.Toast.warning) {
                    window.Toast.warning(connectivityCheckToastMessage(d));
                }
            })
            .catch(function () {});
    }
}
window.recoverDashboardAfterConnectivity = recoverDashboardAfterConnectivity;
window.connectivityCheckToastMessage = connectivityCheckToastMessage;

/** Binance erişilebilir ama cüzdan rozeti takılı kaldıysa sessiz kurtarma (toast yok). */
function maybeSilentWalletRecovery() {
    if (!State.accountId || (typeof State !== 'undefined' && State.isTestAccount)) return;
    if (typeof isWalletDataLive === 'function' && isWalletDataLive()) return;
    if (!assetsState.wallet || assetsState.wallet.keys_configured !== true) return;
    if (!window.apiClient || typeof window.apiClient.get !== 'function') return;
    window.apiClient.get('/api/home/connectivity-check?account_id=' + State.accountId, { timeout: 15000 })
        .then(function (res) {
            var d = res && res.data;
            if (!d || !d.connectivity_ok) return;
            if (typeof markWalletLiveFetchOk === 'function') markWalletLiveFetchOk();
            if (window.homeFlash && typeof window.homeFlash.resetRefreshThrottle === 'function') {
                window.homeFlash.resetRefreshThrottle(State.accountId);
            }
            if (window.homeFlash && typeof window.homeFlash.triggerRefresh === 'function') {
                window.homeFlash.triggerRefresh(State.accountId, true);
            }
        })
        .catch(function () { /* sessiz */ });
}
window.maybeSilentWalletRecovery = maybeSilentWalletRecovery;

function shouldRecoverWalletAfterConnectivity() {
    if (typeof State !== 'undefined' && State.isTestAccount) return false;
    if (typeof navigator !== 'undefined' && navigator.onLine === false) return false;
    if (assetsState.wallet.keys_configured !== true) return false;
    return _hadUserVisibleConnectivityIssue();
}

function runWalletConnectivityRecovery(opts) {
    if (typeof _hadUserVisibleConnectivityIssue === 'function' && _hadUserVisibleConnectivityIssue()) {
        if (typeof recoverDashboardAfterConnectivity === 'function') {
            recoverDashboardAfterConnectivity(opts || { summary: false });
        }
        return;
    }
    if (typeof maybeSilentWalletRecovery === 'function') maybeSilentWalletRecovery();
}
window.runWalletConnectivityRecovery = runWalletConnectivityRecovery;

function updateCuzdanPnlKpi(dailyWalletPnl, account, data) {
    var spotUsd = (account && account.spot_balance_usd != null) ? Number(account.spot_balance_usd)
        : (data && data.spot_balance_usd != null) ? Number(data.spot_balance_usd)
        : (assetsState.wallet && typeof assetsState.wallet.total_usd === 'number') ? assetsState.wallet.total_usd : 0;
    var hasDaily = (account && account.daily_wallet_pnl_usd !== undefined && account.daily_wallet_pnl_usd !== null)
        || (data && data.daily_wallet_pnl_usd !== undefined && data.daily_wallet_pnl_usd !== null);
    if (!hasDaily && _kpiCuzdanPnlDisplay.pnlUsd == null) return;
    var liveOk = isWalletDataLive();
    var pctCuzdan = (account && account.daily_wallet_pnl_pct != null && Number.isFinite(Number(account.daily_wallet_pnl_pct)))
        ? Number(account.daily_wallet_pnl_pct).toFixed(2)
        : ((data && data.daily_wallet_pnl_pct != null && Number.isFinite(Number(data.daily_wallet_pnl_pct)))
            ? Number(data.daily_wallet_pnl_pct).toFixed(2)
            : ((spotUsd || 1) !== 0 ? ((dailyWalletPnl / Math.max(spotUsd || 1, 0.01)) * 100).toFixed(2) : '0.00'));
    var bogusZeroSpot = spotUsd <= 0 && dailyWalletPnl < -0.001;
    if (hasDaily && !bogusZeroSpot) {
        _kpiCuzdanPnlDisplay.pnlUsd = Number(dailyWalletPnl);
        _kpiCuzdanPnlDisplay.pnlPct = pctCuzdan;
    } else if (_kpiCuzdanPnlDisplay.pnlUsd == null) {
        return;
    }
    var pnlShow = _kpiCuzdanPnlDisplay.pnlUsd;
    var pctShow = _kpiCuzdanPnlDisplay.pnlPct;
    if (pnlShow == null) return;
    var cuzdanPnlEl = document.getElementById('kpiCuzdanPnl');
    if (cuzdanPnlEl) {
        var textChanged = setKpiUsdTextIfChanged(cuzdanPnlEl, pnlShow);
        var newColor = pnlShow >= 0 ? '#0ecb81' : '#f6465d';
        if (cuzdanPnlEl.style.color !== newColor) cuzdanPnlEl.style.color = newColor;
        if (textChanged && liveOk && !bogusZeroSpot) triggerValueBlink(cuzdanPnlEl, pnlShow);
    }
    var pctNum = parseFloat(pctShow);
    var pe = document.getElementById('kpiCuzdanPnlPct');
    if (pe && Number.isFinite(pctNum)) {
        setKpiPctTextIfChanged(pe, pctNum);
        var ec = pnlShow >= 0 ? '#0ecb81' : '#f6465d';
        if (pe.style.color !== ec) pe.style.color = ec;
    }
}
window.updateCuzdanPnlKpi = updateCuzdanPnlKpi;

function updateKpiCuzdanBalance(el, walletTotal) {
    if (!el) return;
    var prev = parseFloat(String(el.textContent).replace(/[^0-9.-]/g, '')) || 0;
    var next = walletTotal != null && Number.isFinite(Number(walletTotal)) ? Number(walletTotal) : null;
    if (next != null && next < 0) return;
    if ((next == null || next <= 0) && prev > 0) return;
    if (next == null || next <= 0) {
        if (prev <= 0) setKpiUsdTextIfChanged(el, 0);
        return;
    }
    setKpiUsdTextIfChanged(el, next);
    if (prev > 0 && !(typeof State !== 'undefined' && State.isTestAccount && el.id === 'kpiCuzdan')) {
        triggerValueBlink(el, next);
    }
    if (typeof State !== 'undefined' && State.isTestAccount && el.id === 'kpiCuzdan') {
        el.classList.remove('blink-positive', 'blink-negative');
    }
}

function updateDatahubWsIndicator() {
    var el = document.getElementById('datahubWsIndicator');
    if (!el) return;
    if (!window.apiClient || !window.apiClient.hasToken()) return;
    window.apiClient.get('/api/datahub/status', { timeout: 3000 }).then(function (data) {
        if (!data || !el) return;
        var dot = el.querySelector('.datahub-ws-dot');
        var label = el.querySelector('.datahub-ws-label');
        var s = (data.ws_status || 'rest').toLowerCase();
        if (dot) {
            dot.style.backgroundColor = s === 'connected' ? '#0ecb81' : (s === 'stale' ? '#f0b90b' : '#f6465d');
        }
        var titles = { connected: 'WebSocket bağlı', stale: 'WebSocket gecikmeli', rest: 'REST modu (WS yok)' };
        el.title = (titles[s] || 'WS durumu') + ' • ' + (data.total_symbols || 0) + ' sembol';
    }).catch(function () {
        var dot = el && el.querySelector('.datahub-ws-dot');
        if (dot) dot.style.backgroundColor = '#f6465d';
    });
}

function updateKpiCuzdanLiveStatus() {
    applyWalletStaleWarningEl(document.getElementById('kpiCuzdanLive'));
    applyWalletStaleWarningEl(document.getElementById('kpiBotBakiyePct'));
    syncWalletPanelStatusBadges();
}

function updateKPIs(data) {
    const account = data.account || {};
    let botsTotal = account.bots_balance_usd != null && Number.isFinite(account.bots_balance_usd) ? account.bots_balance_usd : 0;
    if (botsTotal === 0 && Array.isArray(data.bots) && data.bots.length) {
        const sum = data.bots.reduce(function (acc, b) {
            const cu = b.current_usd != null && Number.isFinite(b.current_usd) ? b.current_usd : 0;
            return acc + cu;
        }, 0);
        if (sum > 0) botsTotal = sum;
    }
    const dailyBotPnl = data.daily_bot_pnl_usd ?? data.daily_pnl_usd ?? 0;
    const dailyWalletPnl = account.daily_wallet_pnl_usd ?? data.daily_wallet_pnl_usd ?? 0;
    const hasDaily = (account.daily_wallet_pnl_usd !== undefined && account.daily_wallet_pnl_usd !== null) || (account.daily_bot_pnl_usd !== undefined && account.daily_bot_pnl_usd !== null);
    // Avoid flashing to 0 when Binance/wallet temporarily fails: use last-known spot from state
    const walletTotal = (account.spot_balance_usd != null && Number(account.spot_balance_usd) > 0) ? Number(account.spot_balance_usd) : (typeof (assetsState && assetsState.wallet && assetsState.wallet.total_usd) === 'number' ? assetsState.wallet.total_usd : 0);

    var walletEl = document.getElementById("kpiCuzdan");
    if (typeof State !== 'undefined' && State.isTestAccount && typeof updateTestAccountKpiCuzdanFromStrip === 'function') {
        updateTestAccountKpiCuzdanFromStrip();
    } else {
        updateKpiCuzdanBalance(walletEl, walletTotal);
    }
    if (assetsState.wallet && assetsState.wallet.data_status !== 'stale' && !assetsState.wallet.error) {
        lastSpotUpdateTs = Date.now();
    }
    applyWalletStaleWarningEl(document.getElementById('kpiCuzdanLive'));
    if (typeof State !== 'undefined' && State.isTestAccount) {
        /* Günlük değişim: updateTestAccountKpiCuzdanFromStrip → updateTestAccountCuzdanDailyPnlLive */
    } else {
        updateCuzdanPnlKpi(dailyWalletPnl, account, data);
    }
    if (hasDaily) {
        var botPnlEl = document.getElementById("kpiBotPnl");
        if (botPnlEl) {
            var botTextChanged = setTextIfChanged(botPnlEl, fmtUsd(dailyBotPnl));
            var botColor = dailyBotPnl >= 0 ? '#0ecb81' : '#f6465d';
            if (botPnlEl.style.color !== botColor) botPnlEl.style.color = botColor;
            if (botTextChanged) triggerValueBlink(botPnlEl, dailyBotPnl);
        }
        var pctBot = (account.daily_bot_pnl_pct != null && Number.isFinite(account.daily_bot_pnl_pct))
            ? Number(account.daily_bot_pnl_pct).toFixed(2) : ((account.bots_initial_usd || account.bots_balance_usd || 1) > 0 ? ((dailyBotPnl / (account.bots_initial_usd || account.bots_balance_usd || 1)) * 100).toFixed(2) : '0.00');
        patchText("kpiBotPnlPct", (parseFloat(pctBot) >= 0 ? '+' : '') + pctBot + '%');
        var botPctEl = document.getElementById("kpiBotPnlPct");
        if (botPctEl) { var botPctC = parseFloat(pctBot) >= 0 ? '#0ecb81' : '#f6465d'; if (botPctEl.style.color !== botPctC) botPctEl.style.color = botPctC; }
    }
    // Tek kaynak: account.bots_balance_usd veya botların current_usd toplamı (bot detay state panel ile aynı)
    var botBakiyeEls = document.querySelectorAll("#kpiBotBakiye");
    botBakiyeEls.forEach(function (el) {
        el.textContent = fmtUsd(botsTotal);
        triggerValueBlink(el, botsTotal);
    });
    applyWalletStaleWarningEl(document.getElementById('kpiBotBakiyePct'));
    _persistKpisStorageCache(account, data);
    if (typeof maybeRefreshWalletOnBotsChange === 'function') {
        maybeRefreshWalletOnBotsChange(data.bots || State.bots, account);
    }
}

/** Bot durdurma/silme sonrası cüzdan tablosunu canlı yenile (cached snapshot USDT toplamını güncellemez). */
var _walletBotsWatch = { sig: '', activeBots: null, botsBalanceUsd: null, runningCount: null };

function _botsWalletWatchSignature(bots, account) {
    bots = bots || [];
    var running = bots.filter(function (b) { return String(b.status || '').toLowerCase() === 'running'; });
    var ids = running.map(function (b) { return String(b.bot_id || b.id); }).sort().join(',');
    account = account || {};
    return [
        running.length,
        ids,
        account.active_bots,
        account.bots_balance_usd,
        account.total_bots
    ].join('|');
}

function maybeRefreshWalletOnBotsChange(bots, account) {
    if (!State.accountId) return;
    account = account || (State.summary && State.summary.account) || {};
    bots = bots || State.bots || [];
    var sig = _botsWalletWatchSignature(bots, account);
    var runningNow = bots.filter(function (b) { return String(b.status || '').toLowerCase() === 'running'; }).length;
    if (!_walletBotsWatch.sig) {
        _walletBotsWatch.sig = sig;
        _walletBotsWatch.activeBots = account.active_bots;
        _walletBotsWatch.botsBalanceUsd = account.bots_balance_usd;
        _walletBotsWatch.runningCount = runningNow;
        _walletBotsWatch.totalBots = account.total_bots;
        return;
    }
    if (sig === _walletBotsWatch.sig) return;
    var prevActive = _walletBotsWatch.activeBots;
    var prevBal = _walletBotsWatch.botsBalanceUsd;
    var prevRunning = _walletBotsWatch.runningCount;
    var prevTotal = _walletBotsWatch.totalBots;
    _walletBotsWatch.sig = sig;
    _walletBotsWatch.activeBots = account.active_bots;
    _walletBotsWatch.botsBalanceUsd = account.bots_balance_usd;
    _walletBotsWatch.runningCount = runningNow;
    _walletBotsWatch.totalBots = account.total_bots;
    var activeNow = account.active_bots;
    var balNow = account.bots_balance_usd;
    var totalNow = account.total_bots;
    var shouldRefresh = false;
    if (prevRunning != null && runningNow < prevRunning) shouldRefresh = true;
    if (prevActive != null && activeNow != null && Number(activeNow) < Number(prevActive)) shouldRefresh = true;
    if (prevBal != null && balNow != null && Number(balNow) < Number(prevBal) - 0.5) shouldRefresh = true;
    if (prevTotal != null && totalNow != null && Number(totalNow) < Number(prevTotal)) shouldRefresh = true;
    if (!shouldRefresh) return;
    if (typeof scheduleWalletRefreshAfterTrade === 'function') {
        scheduleWalletRefreshAfterTrade(State.accountId, { delays: [200, 800, 2000, 5000, 10000] });
    }
}
window.maybeRefreshWalletOnBotsChange = maybeRefreshWalletOnBotsChange;

function _parseWalletRefreshAfterBotPayload(raw) {
    if (!raw) return null;
    try {
        var pending = JSON.parse(raw);
        if (!pending || pending.accountId == null) return null;
        if (Date.now() - (pending.at || 0) > 120000) return null;
        return pending;
    } catch (e) {
        return null;
    }
}

function _applyWalletRefreshAfterBotPayload(pending) {
    if (!pending) return;
    if (Number(window.__ACTIVE_ACCOUNT_ID || State.accountId) !== Number(pending.accountId)) return;
    var delays = pending.convert ? [300, 900, 2500, 6000, 12000] : [200, 800, 2000, 5000, 10000];
    if (typeof scheduleWalletRefreshAfterTrade === 'function') {
        scheduleWalletRefreshAfterTrade(pending.accountId, { delays: delays });
    }
}

function _readKpiCuzdanSessionCache(accountId) {
    if (!accountId) return null;
    try {
        var raw = sessionStorage.getItem(KPI_CUZDAN_SESSION_PREFIX + accountId);
        if (!raw) return null;
        var o = JSON.parse(raw);
        if (!o || o.ts == null || Date.now() - Number(o.ts) > KPI_CUZDAN_SESSION_MAX_AGE_MS) return null;
        return o;
    } catch (e) {
        return null;
    }
}

function _loadPersistedKpiCuzdanFields(accountId) {
    var sess = _readKpiCuzdanSessionCache(accountId);
    if (sess && sess.spot != null && Number(sess.spot) > 0) return sess;
    try {
        var raw = localStorage.getItem("tt_home_cache_v1:" + accountId);
        if (!raw) return null;
        var data = JSON.parse(raw);
        if (!data || !data.kpis || typeof data.kpis !== "object") return null;
        var age = Date.now() - (data.stored_at || 0);
        if (age > KPI_CUZDAN_LOCAL_MAX_AGE_MS) return null;
        var k = data.kpis;
        var spot = k.spot_balance_usd != null ? Number(k.spot_balance_usd) : (k.spot_kpi_total_usd != null ? Number(k.spot_kpi_total_usd) : null);
        if (spot == null || !Number.isFinite(spot) || spot <= 0) return null;
        return {
            spot: spot,
            pnl: k.daily_wallet_pnl_usd != null ? Number(k.daily_wallet_pnl_usd) : null,
            pct: k.daily_wallet_pnl_pct != null ? Number(k.daily_wallet_pnl_pct) : null,
            ts: data.stored_at || Date.now()
        };
    } catch (e2) {
        return null;
    }
}

function _persistKpiCuzdanSessionCache(accountId, spotUsd, pnlUsd, pnlPct) {
    if (!accountId) return;
    var spot = spotUsd != null && Number.isFinite(Number(spotUsd)) ? Number(spotUsd) : null;
    var pnl = pnlUsd != null && Number.isFinite(Number(pnlUsd)) ? Number(pnlUsd) : null;
    var pct = pnlPct != null && Number.isFinite(Number(pnlPct)) ? Number(pnlPct) : null;
    if (spot == null && pnl == null) return;
    try {
        sessionStorage.setItem(KPI_CUZDAN_SESSION_PREFIX + accountId, JSON.stringify({
            spot: spot,
            pnl: pnl,
            pct: pct,
            ts: Date.now()
        }));
    } catch (e) { /* ignore */ }
    if (window.storageCache && spot != null && spot > 0) {
        try {
            window.storageCache.mergeSaved(accountId, {
                kpis: {
                    spot_balance_usd: spot,
                    daily_wallet_pnl_usd: pnl,
                    daily_wallet_pnl_pct: pct
                }
            });
        } catch (e2) { /* ignore */ }
    }
}

/** KPI cüzdan bloğunu doğrudan boyar (test strip hazır olmadan; yenilemede anında). */
function applyKpiCuzdanSnapshot(spotUsd, pnlUsd, pnlPct, opts) {
    opts = opts || {};
    var strip = document.getElementById("unifiedKpiStrip");
    if (strip && opts.showStrip !== false) strip.style.removeProperty("display");
    var spot = spotUsd != null && Number.isFinite(Number(spotUsd)) ? Number(spotUsd) : null;
    if (spot != null && spot > 0) {
        _kpiCuzdanLastSpot = spot;
        var walletEl = document.getElementById("kpiCuzdan");
        if (walletEl) {
            setKpiUsdTextIfChanged(walletEl, spot);
            walletEl.classList.remove("blink-positive", "blink-negative");
        }
    }
    if (pnlUsd != null && Number.isFinite(Number(pnlUsd))) {
        _kpiCuzdanPnlDisplay.pnlUsd = Number(pnlUsd);
        if (pnlPct != null && Number.isFinite(Number(pnlPct))) {
            _kpiCuzdanPnlDisplay.pnlPct = Number(pnlPct).toFixed(2);
        }
        var cuzdanPnlEl = document.getElementById("kpiCuzdanPnl");
        if (cuzdanPnlEl) {
            setKpiUsdTextIfChanged(cuzdanPnlEl, _kpiCuzdanPnlDisplay.pnlUsd);
            var pnlColor = _kpiCuzdanPnlDisplay.pnlUsd >= 0 ? "#0ecb81" : "#f6465d";
            if (cuzdanPnlEl.style.color !== pnlColor) cuzdanPnlEl.style.color = pnlColor;
            cuzdanPnlEl.classList.remove("blink-positive", "blink-negative");
        }
        var pctShow = _kpiCuzdanPnlDisplay.pnlPct;
        if (pctShow != null) {
            var pctNum = parseFloat(pctShow);
            var pe = document.getElementById("kpiCuzdanPnlPct");
            if (pe && Number.isFinite(pctNum)) setKpiPctTextIfChanged(pe, pctNum);
            if (pe) {
                var pctColor = _kpiCuzdanPnlDisplay.pnlUsd >= 0 ? "#0ecb81" : "#f6465d";
                if (pe.style.color !== pctColor) pe.style.color = pctColor;
                pe.classList.remove("blink-positive", "blink-negative");
            }
        }
    }
}
window.applyKpiCuzdanSnapshot = applyKpiCuzdanSnapshot;

function restoreKpiCuzdanEarlyFromStorage(accountId) {
    var snap = _loadPersistedKpiCuzdanFields(accountId);
    if (!snap) return false;
    applyKpiCuzdanSnapshot(snap.spot, snap.pnl, snap.pct, { showStrip: true });
    return true;
}
window.restoreKpiCuzdanEarlyFromStorage = restoreKpiCuzdanEarlyFromStorage;

function _persistKpisStorageCache(account, data) {
    if (!State.accountId || !window.storageCache) return;
    account = account || {};
    data = data || {};
    var spot = account.spot_balance_usd ?? data.spot_balance_usd ?? (_kpiCuzdanLastSpot > 0 ? _kpiCuzdanLastSpot : assetsState.wallet?.total_usd);
    if (typeof State !== 'undefined' && State.isTestAccount && _kpiCuzdanLastSpot > 0) {
        spot = _kpiCuzdanLastSpot;
    }
    if (account.daily_wallet_pnl_usd == null && data.daily_wallet_pnl_usd == null && spot == null) return;
    var pnl = account.daily_wallet_pnl_usd ?? data.daily_wallet_pnl_usd ?? _kpiCuzdanPnlDisplay.pnlUsd;
    var pct = account.daily_wallet_pnl_pct ?? data.daily_wallet_pnl_pct ?? _kpiCuzdanPnlDisplay.pnlPct;
    try {
        window.storageCache.mergeSaved(State.accountId, {
            kpis: Object.assign({}, account, {
                spot_balance_usd: spot,
                daily_wallet_pnl_usd: pnl,
                daily_wallet_pnl_pct: pct,
                daily_bot_pnl_usd: account.daily_bot_pnl_usd ?? data.daily_bot_pnl_usd,
                daily_bot_pnl_pct: account.daily_bot_pnl_pct ?? data.daily_bot_pnl_pct,
                bots_balance_usd: account.bots_balance_usd ?? data.bots_balance_usd,
                total_bots: account.total_bots ?? data.total_bots,
                active_bots: account.active_bots ?? data.active_bots
            })
        });
    } catch (e) { /* ignore */ }
    if (spot != null && Number(spot) > 0) {
        _persistKpiCuzdanSessionCache(State.accountId, spot, pnl, pct);
    }
}

function hydrateKpisFromStorageCache(accountId) {
    if (!accountId) return false;
    var snap = _loadPersistedKpiCuzdanFields(accountId);
    if (!snap) return false;
    applyKpiCuzdanSnapshot(snap.spot, snap.pnl, snap.pct, { showStrip: true });
    var cached = window.storageCache && window.storageCache.load(accountId);
    var k = (cached && cached.kpis) ? cached.kpis : {};
    if (k.total_bots != null || k.active_bots != null || k.daily_bot_pnl_usd != null) {
        var botBakiye = k.bots_balance_usd != null && Number.isFinite(Number(k.bots_balance_usd)) ? Number(k.bots_balance_usd) : null;
        if (botBakiye != null) {
            document.querySelectorAll("#kpiBotBakiye").forEach(function (el) {
                if (typeof fmtUsd === "function") setTextIfChanged(el, fmtUsd(botBakiye));
            });
        }
        if (k.daily_bot_pnl_usd != null && Number.isFinite(Number(k.daily_bot_pnl_usd)) && typeof fmtUsd === "function") {
            var botPnlEl = document.getElementById("kpiBotPnl");
            if (botPnlEl) setTextIfChanged(botPnlEl, fmtUsd(Number(k.daily_bot_pnl_usd)));
        }
    }
    return true;
}
window.hydrateKpisFromStorageCache = hydrateKpisFromStorageCache;

function patchText(id, text) {
    const el = document.getElementById(id);
    if (el && el.textContent !== text) {
        el.textContent = text;
    }
}
