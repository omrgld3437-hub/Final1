/**
 * Yenilemede kaydırma konumunu korur — kaydet, yükleme bitince scrollTo (body kilidi yok).
 */
(function (global) {
    'use strict';

    var PREFIX = 'tt_page_scroll_v1:';
    var SAVE_DEBOUNCE_MS = 120;
    var RESTORE_MAX_TRIES = 80;

    var _restoreDone = false;
    var _restorePending = false;
    var _scrollSaveTimer = null;
    var _boundScrollTargets = typeof WeakSet !== 'undefined' ? new WeakSet() : null;
    var _boundScrollList = [];

    try {
        if ('scrollRestoration' in global.history) {
            global.history.scrollRestoration = 'manual';
        }
    } catch (e) { /* ignore */ }

    function getScope() {
        try {
            if (global.__TT_SCROLL_SCOPE__ != null && global.__TT_SCROLL_SCOPE__ !== '') {
                return String(global.__TT_SCROLL_SCOPE__);
            }
            if (typeof global.__TT_SCROLL_SCOPE_FN__ === 'function') {
                return String(global.__TT_SCROLL_SCOPE_FN__() || '');
            }
        } catch (e) { /* ignore */ }
        return '';
    }

    function pageKey() {
        var path = global.location.pathname || '';
        var scope = getScope();
        return PREFIX + path + (scope ? ':' + scope : '');
    }

    function rootScrollY() {
        var doc = global.document;
        if (!doc) return 0;
        var y = global.scrollY || global.pageYOffset || 0;
        if (y > 0) return y;
        y = doc.documentElement ? doc.documentElement.scrollTop : 0;
        if (y > 0) return y;
        y = doc.body ? doc.body.scrollTop : 0;
        return y > 0 ? y : 0;
    }

    function maxScrollY() {
        var doc = global.document;
        if (!doc) return 0;
        var h = Math.max(
            doc.documentElement ? doc.documentElement.scrollHeight : 0,
            doc.body ? doc.body.scrollHeight : 0
        );
        return Math.max(0, h - (global.innerHeight || 0));
    }

    function readScrollY() {
        try {
            var key = pageKey();
            var raw = global.sessionStorage.getItem(key);
            if (raw != null && raw !== '') {
                var direct = parseInt(raw, 10);
                if (!isNaN(direct) && direct > 0) return direct;
            }
            var path = global.location.pathname || '';
            var prefix = PREFIX + path;
            var best = null;
            for (var i = 0; i < global.sessionStorage.length; i++) {
                var k = global.sessionStorage.key(i);
                if (!k || k.indexOf(prefix) !== 0) continue;
                var y = parseInt(global.sessionStorage.getItem(k), 10);
                if (!isNaN(y) && y > 0 && (best == null || y > best)) best = y;
            }
            return best;
        } catch (e) {
            return null;
        }
    }

    function saveScroll() {
        try {
            var y = Math.max(0, Math.round(rootScrollY()));
            global.sessionStorage.setItem(pageKey(), String(y));
        } catch (e) { /* ignore */ }
    }

    function applyScrollY(y) {
        var doc = global.document;
        if (!doc || y == null || y <= 0) return 0;
        var targetY = Math.min(Math.max(0, y), maxScrollY());
        doc.documentElement.scrollTop = targetY;
        if (doc.body) doc.body.scrollTop = targetY;
        global.scrollTo(0, targetY);
        return targetY;
    }

    function clearBootLockArtifacts() {
        var doc = global.document;
        if (!doc) return;
        var html = doc.documentElement;
        var body = doc.body;
        if (html) {
            html.classList.remove('tt-boot-scroll-lock');
            html.style.overflow = '';
            html.style.height = '';
            delete html.dataset.ttBootScrollY;
            delete html.dataset.ttDeferVisible;
        }
        if (body) {
            body.classList.remove('tt-boot-scroll-lock');
            body.style.position = '';
            body.style.top = '';
            body.style.left = '';
            body.style.right = '';
            body.style.width = '';
            delete body.dataset.ttBootScrollY;
        }
        delete global.__TT_PENDING_SCROLL_Y__;
    }

    function ensureRestored() {
        var saved = readScrollY();
        if (saved == null || saved <= 0) {
            _restoreDone = true;
            return;
        }
        var cur = rootScrollY();
        if (cur + 2 >= saved) {
            _restoreDone = true;
            return;
        }
        if (maxScrollY() + 2 < saved) return;
        applyScrollY(saved);
        if (rootScrollY() + 2 >= saved) _restoreDone = true;
    }

    function scheduleRestore() {
        if (_restoreDone || _restorePending) return;
        var saved = readScrollY();
        if (saved == null || saved <= 0) {
            _restoreDone = true;
            return;
        }

        _restorePending = true;
        var tries = 0;
        var lastH = 0;
        var stable = 0;

        function tick() {
            if (_restoreDone) {
                _restorePending = false;
                return;
            }
            tries += 1;
            var h = Math.max(
                global.document.documentElement.scrollHeight || 0,
                global.document.body ? global.document.body.scrollHeight : 0
            );
            if (h === lastH) stable += 1;
            else { stable = 0; lastH = h; }

            if (stable >= 1 || tries >= RESTORE_MAX_TRIES) {
                ensureRestored();
                _restorePending = false;
                if (!_restoreDone && tries < RESTORE_MAX_TRIES) {
                    global.requestAnimationFrame(tick);
                    return;
                }
                _restoreDone = true;
                return;
            }
            global.requestAnimationFrame(tick);
        }

        global.requestAnimationFrame(tick);
    }

    function scheduleSaveScroll() {
        if (_scrollSaveTimer) return;
        _scrollSaveTimer = global.setTimeout(function () {
            _scrollSaveTimer = null;
            saveScroll();
        }, SAVE_DEBOUNCE_MS);
    }

    function bindScrollTarget(target) {
        if (!target) return;
        if (_boundScrollTargets) {
            if (_boundScrollTargets.has(target)) return;
            _boundScrollTargets.add(target);
        } else if (_boundScrollList.indexOf(target) >= 0) {
            return;
        } else {
            _boundScrollList.push(target);
        }
        target.addEventListener('scroll', scheduleSaveScroll, { passive: true });
    }

    function bindAllScrollTargets() {
        bindScrollTarget(global);
        if (!global.document) return;
        bindScrollTarget(global.document);
        bindScrollTarget(global.document.documentElement);
        if (global.document.body) bindScrollTarget(global.document.body);
    }

    function bindListeners() {
        bindAllScrollTargets();
        global.addEventListener('pagehide', saveScroll);
        global.addEventListener('beforeunload', saveScroll);
        global.addEventListener('load', function () {
            scheduleRestore();
            ensureRestored();
            global.setTimeout(ensureRestored, 50);
            global.setTimeout(ensureRestored, 250);
            global.setTimeout(ensureRestored, 1000);
        });
    }

    function boot() {
        clearBootLockArtifacts();
        bindListeners();
        scheduleRestore();
    }

    if (global.document && global.document.body) {
        bindScrollTarget(global.document.body);
        boot();
    } else if (global.document) {
        global.document.addEventListener('DOMContentLoaded', function () {
            bindScrollTarget(global.document.body);
            boot();
        }, { once: true });
    } else {
        boot();
    }

    global.TtScrollRestore = {
        pageKey: pageKey,
        readScrollY: readScrollY,
        save: saveScroll,
        syncBodyLock: clearBootLockArtifacts,
        lock: function () { return false; },
        finalize: function () { ensureRestored(); _restoreDone = true; },
        scheduleFinalize: scheduleRestore,
        scheduleRestore: scheduleRestore,
        ensureRestored: ensureRestored,
        forceUnlock: clearBootLockArtifacts,
        isLocked: function () { return false; }
    };
})(typeof window !== 'undefined' ? window : globalThis);
