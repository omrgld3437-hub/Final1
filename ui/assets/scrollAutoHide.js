/**
 * Custom overlay scrollbar — native gizli, layout daralmaz, thumb tasarımın üstünde.
 */
(function (global) {
    'use strict';
    var ROOT = 'tt-auto-scrollbar';
    var OVERLAY_ID = 'tt-scroll-overlay';
    var HIDE_MS = 900;
    var doc = null;
    var overlay = null;
    var thumb = null;
    var activeEl = null;
    var hideTimer = null;
    var rafId = null;
    var booted = false;
    var userScrolled = false;

    try {
        if (global.document && global.document.documentElement) {
            global.document.documentElement.classList.add(ROOT);
        }
    } catch (e) { /* ignore */ }

    function init() {
        if (booted) return;
        booted = true;
        doc = global.document;
        if (!doc || !doc.documentElement) return;
        doc.documentElement.classList.add(ROOT);

        function boot() {
            ensureOverlay();
            bindListeners();
        }

        if (doc.body) boot();
        else doc.addEventListener('DOMContentLoaded', boot);
    }

    function bindListeners() {
        var reduced = false;
        try {
            reduced = global.matchMedia('(prefers-reduced-motion: reduce)').matches;
        } catch (e) { /* ignore */ }

        global.addEventListener('scroll', onScroll, { passive: true, capture: true });
        global.addEventListener('wheel', onUserPulse, { passive: true, capture: true });
        global.addEventListener('touchmove', onUserPulse, { passive: true, capture: true });
        global.addEventListener('keydown', onKeyPulse, { passive: true, capture: true });
        global.addEventListener('resize', schedulePaint, { passive: true });

        if (reduced) {
            overlay.classList.add('is-visible');
            paint();
        }
    }

    function onScroll(ev) {
        if (!userScrolled) return;
        onPulse(ev);
    }

    function onUserPulse(ev) {
        userScrolled = true;
        onPulse(ev);
    }

    function onKeyPulse(ev) {
        if (!ev) return;
        var k = ev.key;
        if (k === 'ArrowUp' || k === 'ArrowDown' || k === 'PageUp' || k === 'PageDown' ||
            k === 'Home' || k === 'End' || k === ' ') {
            userScrolled = true;
            onPulse(ev);
        }
    }

    function ensureOverlay() {
        overlay = doc.getElementById(OVERLAY_ID);
        if (overlay) {
            thumb = overlay.querySelector('.tt-scroll-overlay__thumb');
            return;
        }
        overlay = doc.createElement('div');
        overlay.id = OVERLAY_ID;
        overlay.setAttribute('aria-hidden', 'true');
        thumb = doc.createElement('div');
        thumb.className = 'tt-scroll-overlay__thumb';
        overlay.appendChild(thumb);
        (doc.body || doc.documentElement).appendChild(overlay);
    }

    function isScrollable(node) {
        if (!node || node.nodeType !== 1) return false;
        try {
            var st = global.getComputedStyle(node);
            var oy = st.overflowY;
            var ox = st.overflowX;
            var canScrollY = (oy === 'auto' || oy === 'scroll' || oy === 'overlay') &&
                node.scrollHeight > node.clientHeight + 1;
            var canScrollX = (ox === 'auto' || ox === 'scroll' || ox === 'overlay') &&
                node.scrollWidth > node.clientWidth + 1;
            return canScrollY || canScrollX;
        } catch (e) {
            return false;
        }
    }

    function scrollTarget(from) {
        var node = from && from.nodeType === 1 ? from : null;
        while (node && node !== doc && node !== doc.documentElement) {
            if (isScrollable(node)) return node;
            node = node.parentElement;
        }
        if (doc.body && isScrollable(doc.body)) return doc.body;
        return doc.documentElement;
    }

    function isRootScroll(el) {
        return el === doc.documentElement || el === doc.body;
    }

    function metrics(el) {
        if (isRootScroll(el)) {
            var root = doc.documentElement;
            var body = doc.body;
            return {
                scrollTop: root.scrollTop || (body ? body.scrollTop : 0),
                scrollHeight: Math.max(root.scrollHeight, body ? body.scrollHeight : 0),
                clientHeight: root.clientHeight
            };
        }
        return {
            scrollTop: el.scrollTop,
            scrollHeight: el.scrollHeight,
            clientHeight: el.clientHeight
        };
    }

    function trackGeometry(el) {
        if (isRootScroll(el)) {
            return {
                top: 0,
                height: global.innerHeight || rootClientHeight(),
                right: 0
            };
        }
        var rect = el.getBoundingClientRect();
        return {
            top: Math.max(0, rect.top),
            height: Math.max(0, rect.height),
            right: Math.max(0, (global.innerWidth || 0) - rect.right)
        };
    }

    function rootClientHeight() {
        return doc.documentElement ? doc.documentElement.clientHeight : 0;
    }

    function showOverlay(el) {
        activeEl = el;
        overlay.classList.add('is-visible');
        if (hideTimer) global.clearTimeout(hideTimer);
        hideTimer = global.setTimeout(function () {
            overlay.classList.remove('is-visible');
            activeEl = null;
            hideTimer = null;
        }, HIDE_MS);
        schedulePaint();
    }

    function onPulse(ev) {
        var el = scrollTarget(ev && ev.target);
        if (!isScrollable(el) && !isRootScroll(el)) {
            overlay.classList.remove('is-visible');
            return;
        }
        showOverlay(el);
    }

    function schedulePaint() {
        if (rafId) return;
        rafId = global.requestAnimationFrame(function () {
            rafId = null;
            paint();
        });
    }

    function paint() {
        if (!overlay || !thumb) return;
        var el = activeEl;
        if (!el) {
            el = doc.body && isScrollable(doc.body) ? doc.body : doc.documentElement;
        }
        if (!isScrollable(el) && !isRootScroll(el)) {
            overlay.classList.remove('is-visible');
            return;
        }

        var m = metrics(el);
        var maxScroll = m.scrollHeight - m.clientHeight;
        if (maxScroll <= 1) {
            overlay.classList.remove('is-visible');
            return;
        }

        var geo = trackGeometry(el);
        var trackH = geo.height - 6;
        if (trackH < 24) return;

        var thumbH = Math.max(32, (m.clientHeight / m.scrollHeight) * trackH);
        var travel = trackH - thumbH;
        var ratio = m.scrollTop / maxScroll;
        var thumbTop = geo.top + 3 + ratio * travel;

        overlay.style.top = '0';
        overlay.style.right = geo.right + 'px';
        overlay.style.height = (global.innerHeight || rootClientHeight()) + 'px';
        overlay.style.width = '6px';

        thumb.style.top = thumbTop + 'px';
        thumb.style.height = thumbH + 'px';
    }

    if (global.document && global.document.readyState !== 'loading') init();
    else global.document.addEventListener('DOMContentLoaded', init);
})(typeof window !== 'undefined' ? window : globalThis);
