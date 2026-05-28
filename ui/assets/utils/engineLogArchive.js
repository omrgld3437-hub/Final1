/**
 * Bot engine log — oturum arşivi (sayfa açılışından beri, Reset ile silinmez) + dışa aktarma.
 */
(function (global) {
    'use strict';

    var sessions = {};

    function sessionKey(botId) {
        return String(botId || '');
    }

    function getSession(botId) {
        var key = sessionKey(botId);
        if (!sessions[key]) {
            sessions[key] = {
                startedAt: new Date().toISOString(),
                byId: {},
                order: []
            };
        }
        return sessions[key];
    }

    function eventKey(ev) {
        if (!ev) return '';
        if (ev.id != null) return 'id:' + String(ev.id);
        return 'ts:' + String(ev.ts || '') + ':' + String(ev.type || '') + ':' + String(ev.message || '').slice(0, 80);
    }

    function ingest(botId, events) {
        if (!botId || !events || !events.length) return;
        var sess = getSession(botId);
        events.forEach(function (ev) {
            if (!ev) return;
            var k = eventKey(ev);
            if (sess.byId[k]) return;
            sess.byId[k] = ev;
            sess.order.push(k);
        });
    }

    function ingestOne(botId, ev) {
        if (!botId || !ev) return;
        ingest(botId, [ev]);
    }

    function resetSession(botId) {
        if (botId != null) delete sessions[sessionKey(botId)];
    }

    function listEvents(botId) {
        var sess = sessions[sessionKey(botId)];
        if (!sess) return [];
        return sess.order.map(function (k) { return sess.byId[k]; }).filter(Boolean);
    }

    function countEvents(botId) {
        return listEvents(botId).length;
    }

    function formatTs(ts) {
        if (!ts) return '—';
        try {
            return new Date(ts).toLocaleString('tr-TR', { timeZone: 'Europe/Istanbul' });
        } catch (e) {
            return String(ts);
        }
    }

    function formatTsFile(d) {
        var p = function (n) { return String(n).padStart(2, '0'); };
        return d.getFullYear() + p(d.getMonth() + 1) + p(d.getDate()) + '-' + p(d.getHours()) + p(d.getMinutes());
    }

    function safeFilePart(s) {
        return String(s || 'bot').replace(/[^\w.-]+/g, '_').replace(/_+/g, '_').slice(0, 48);
    }

    function formatRow(ev, fmtApi) {
        var rawType = String(ev.type || '—');
        var msg = String(ev.message || '—');
        var severity = 'info';
        var typeLabel = rawType;
        if (fmtApi && fmtApi.formatEngineEvent) {
            var fmt = fmtApi.formatEngineEvent(ev, { forExport: true });
            if (fmt && fmt.message) msg = fmt.message;
            if (fmt && fmt.typeLabel) typeLabel = fmt.typeLabel;
            if (fmt && fmt.severity) severity = fmt.severity;
        }
        return {
            ts: formatTs(ev.ts),
            tsIso: ev.ts || null,
            type: typeLabel,
            rawType: rawType,
            severity: severity,
            message: msg,
            id: ev.id != null ? ev.id : null,
            meta: ev.meta || null
        };
    }

    function buildReadableText(botId, meta) {
        meta = meta || {};
        var fmtApi = global.EngineLogFormat;
        var events = listEvents(botId).slice().sort(function (a, b) {
            var ta = a && a.ts ? new Date(a.ts).getTime() : 0;
            var tb = b && b.ts ? new Date(b.ts).getTime() : 0;
            if (ta !== tb) return ta - tb;
            return Number(a.id || 0) - Number(b.id || 0);
        });
        var sess = getSession(botId);
        var lines = [];
        lines.push('Bot Engine Log — Dışa Aktarım');
        lines.push('================================');
        lines.push('Bot ID      : ' + botId);
        if (meta.symbol) lines.push('Sembol      : ' + meta.symbol);
        if (meta.botCode) lines.push('Bot kodu    : ' + meta.botCode);
        if (meta.accountCode) lines.push('Hesap       : ' + meta.accountCode);
        lines.push('Oturum başı : ' + formatTs(sess.startedAt));
        lines.push('Dışa aktarma: ' + formatTs(new Date().toISOString()));
        lines.push('Kayıt sayısı: ' + events.length);
        lines.push('');
        lines.push('Not: Resetle yalnızca ekrandaki uyarı banner\'ını gizler; bu arşiv etkilenmez.');
        lines.push('');
        lines.push('--- Loglar (eskiden yeniye) ---');
        lines.push('');
        if (!events.length) {
            lines.push('(Bu oturumda henüz kayıt yok.)');
        } else {
            events.forEach(function (ev, i) {
                var row = formatRow(ev, fmtApi);
                var head = String(i + 1).padStart(4, '0') + ' | ' + row.ts + ' | ' + row.type;
                lines.push(head);
                lines.push('      ' + row.message.replace(/\r?\n/g, ' '));
                if (row.meta && row.meta.error_code) {
                    lines.push('      [kod: ' + row.meta.error_code + ']');
                }
                lines.push('');
            });
        }
        return lines.join('\n');
    }

    function buildJsonPayload(botId, meta) {
        var sess = getSession(botId);
        var events = listEvents(botId).slice().sort(function (a, b) {
            var ta = a && a.ts ? new Date(a.ts).getTime() : 0;
            var tb = b && b.ts ? new Date(b.ts).getTime() : 0;
            if (ta !== tb) return ta - tb;
            return Number(a.id || 0) - Number(b.id || 0);
        });
        return {
            exported_at: new Date().toISOString(),
            session_started_at: sess.startedAt,
            bot_id: botId,
            symbol: meta.symbol || null,
            bot_code: meta.botCode || null,
            account_code: meta.accountCode || null,
            event_count: events.length,
            events: events
        };
    }

    function downloadBlob(filename, content, mime) {
        try {
            var blob = new Blob([content], { type: mime || 'application/octet-stream;charset=utf-8' });
            var url = URL.createObjectURL(blob);
            var a = document.createElement('a');
            a.href = url;
            a.download = filename;
            a.style.display = 'none';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            setTimeout(function () { URL.revokeObjectURL(url); }, 2000);
            return true;
        } catch (e) {
            return false;
        }
    }

    function exportSession(botId, meta) {
        meta = meta || {};
        if (!botId) return { ok: false, error: 'bot_id_missing' };
        var count = countEvents(botId);
        if (count === 0) return { ok: false, error: 'empty', count: 0 };
        var stamp = formatTsFile(new Date());
        var base = safeFilePart(meta.symbol || meta.botCode || ('bot-' + botId));
        var prefix = base + '-bot' + botId + '-log-' + stamp;
        var txtOk = downloadBlob(prefix + '.txt', buildReadableText(botId, meta), 'text/plain;charset=utf-8');
        var jsonOk = false;
        setTimeout(function () {
            jsonOk = downloadBlob(
                prefix + '.json',
                JSON.stringify(buildJsonPayload(botId, meta), null, 2),
                'application/json;charset=utf-8'
            );
        }, 350);
        return { ok: txtOk, count: count, prefix: prefix, jsonScheduled: true };
    }

    global.EngineLogArchive = {
        ingest: ingest,
        ingestOne: ingestOne,
        resetSession: resetSession,
        listEvents: listEvents,
        countEvents: countEvents,
        exportSession: exportSession
    };
})(typeof window !== 'undefined' ? window : globalThis);
