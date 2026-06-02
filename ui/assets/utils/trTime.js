/**
 * Türkiye saati (Europe/Istanbul) – Tüm uygulama tek saat.
 * Anasayfa, giriş/çıkış, işlemler, loglar hep Türkiye saatiyle gösterilir.
 */
(function () {
    var TR_TZ = 'Europe/Istanbul';

    function normalizeUtcIso(v) {
        if (typeof v !== 'string') return v;
        var s = v.trim();
        if (!s) return s;
        if (s.indexOf('T') < 0 && s.indexOf(' ') > 0) s = s.replace(' ', 'T');
        if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(s) && !/[zZ]|[+\-]\d{2}:?\d{2}$/.test(s)) {
            s += 'Z';
        }
        return s;
    }

    function toDate(v) {
        if (v == null || v === '') return null;
        if (v instanceof Date) return isNaN(v.getTime()) ? null : v;
        var ms = typeof v === 'number' ? v : Date.parse(normalizeUtcIso(v));
        if (!Number.isFinite(ms)) return null;
        return new Date(ms);
    }

    function opts(override) {
        var base = { timeZone: TR_TZ };
        if (override) {
            for (var k in override) base[k] = override[k];
        }
        return base;
    }

    /** Tam tarih + saat (örn. 27.01.2026 14:35:22) */
    function trFormatDateTime(isoOrMs) {
        var d = toDate(isoOrMs);
        if (!d) return '—';
        try {
            return d.toLocaleString('tr-TR', opts({
                day: '2-digit', month: '2-digit', year: 'numeric',
                hour: '2-digit', minute: '2-digit', second: '2-digit'
            }));
        } catch (e) { return '—'; }
    }

    /** Sadece tarih (örn. 27.01.2026) */
    function trFormatDate(isoOrMs) {
        var d = toDate(isoOrMs);
        if (!d) return '—';
        try {
            return d.toLocaleDateString('tr-TR', opts({
                day: '2-digit', month: '2-digit', year: 'numeric'
            }));
        } catch (e) { return '—'; }
    }

    /** Sadece saat (HH:mm) */
    function trFormatTime(isoOrMs) {
        var d = toDate(isoOrMs);
        if (!d) return '—';
        try {
            return d.toLocaleTimeString('tr-TR', opts({
                hour: '2-digit', minute: '2-digit'
            }));
        } catch (e) { return '—'; }
    }

    /** Saat HH:mm:ss (bakım overlay vb.) */
    function trFormatTimeWithSeconds(isoOrMs) {
        var d = toDate(isoOrMs);
        if (!d) return '—';
        try {
            return d.toLocaleTimeString('tr-TR', opts({
                hour: '2-digit', minute: '2-digit', second: '2-digit'
            }));
        } catch (e) { return '—'; }
    }

    /** Kısa tarih (örn. 27.01.26) */
    function trFormatDateShort(isoOrMs) {
        var d = toDate(isoOrMs);
        if (!d) return '—';
        try {
            return d.toLocaleDateString('tr-TR', opts({
                day: '2-digit', month: '2-digit', year: '2-digit'
            }));
        } catch (e) { return '—'; }
    }

    /** Tarih + kısa saat (dateStyle: short, timeStyle: short) */
    function trFormatShort(isoOrMs) {
        var d = toDate(isoOrMs);
        if (!d) return '—';
        try {
            return d.toLocaleString('tr-TR', opts({
                dateStyle: 'short', timeStyle: 'short'
            }));
        } catch (e) { return '—'; }
    }

    /** Şu an Türkiye saati (HH:mm) */
    function trNowTime() {
        return trFormatTime(Date.now());
    }

    /** Şu an Türkiye tarihi (gg.aa.yyyy) */
    function trNowDate() {
        return trFormatDate(Date.now());
    }

    /** Chart axis: time = saniye epoch */
    function trFormatChartTime(timeSec) {
        var t = typeof timeSec === 'number' ? timeSec : 0;
        var d = new Date(t * 1000);
        if (!Number.isFinite(t) || isNaN(d.getTime())) return '—';
        try {
            return d.toLocaleString('tr-TR', opts({ hour: '2-digit', minute: '2-digit' }));
        } catch (e) { return '—'; }
    }

    function trFormatChartTimeDay(timeSec) {
        var t = typeof timeSec === 'number' ? timeSec : 0;
        var d = new Date(t * 1000);
        if (!Number.isFinite(t) || isNaN(d.getTime())) return '—';
        try {
            return d.toLocaleString('tr-TR', opts({ day: '2-digit', month: 'short', hour: '2-digit' }));
        } catch (e) { return '—'; }
    }

    function trFormatChartTimeDate(timeSec) {
        var t = typeof timeSec === 'number' ? timeSec : 0;
        var d = new Date(t * 1000);
        if (!Number.isFinite(t) || isNaN(d.getTime())) return '—';
        try {
            return d.toLocaleDateString('tr-TR', opts({ day: '2-digit', month: 'short', year: '2-digit' }));
        } catch (e) { return '—'; }
    }

    function trFormatTooltipTime(timeSec) {
        var t = typeof timeSec === 'number' ? timeSec : 0;
        var d = new Date(t * 1000);
        if (!Number.isFinite(t) || isNaN(d.getTime())) return '—';
        try {
            return d.toLocaleString('tr-TR', opts({ dateStyle: 'short', timeStyle: 'medium' }));
        } catch (e) { return '—'; }
    }

    window.trTime = {
        trFormatDateTime: trFormatDateTime,
        trFormatDate: trFormatDate,
        trFormatTime: trFormatTime,
        trFormatTimeWithSeconds: trFormatTimeWithSeconds,
        trFormatDateShort: trFormatDateShort,
        trFormatShort: trFormatShort,
        trNowTime: trNowTime,
        trNowDate: trNowDate,
        trFormatChartTime: trFormatChartTime,
        trFormatChartTimeDay: trFormatChartTimeDay,
        trFormatChartTimeDate: trFormatChartTimeDate,
        trFormatTooltipTime: trFormatTooltipTime,
        TR_TZ: TR_TZ
    };
})();
