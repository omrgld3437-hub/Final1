/*
 * bot-error-assistant.js
 *
 * Bot detay sayfasındaki "Hata Asistanı" akışı.
 * Tasarım, renk, buton ve YAZI AKIŞI (typewriter streaming) Parametre Asistanı ile
 * birebir aynıdır: aynı panel/spark/chip/cursor yapısı, aynı --ai-assistant-* tokenları.
 *
 * Canlı /health verisini ve motor olaylarını okur, aktif uyarıları AIAssistantSpec
 * bilgi tabanına eşler, aynı kökten gelenleri tek bir tema altında bağlar ve
 * kullanıcıya neden + etki + adım adım çözüm + tek tık oto-düzeltme sunar.
 *
 * Kendi cümle havuzunu AÇMAZ; tüm metin/kelime havuzu ve tasarım tokenları
 * window.AIAssistantSpec.errorAssistant kaynağından okunur (bkz. docs/AI_ASSISTANT_README.md).
 */
(function (global) {
    "use strict";

    var spec = null;
    var ea = null;
    var opts = null;
    var overlay = null;
    var panelEl = null;
    var bodyEl = null;
    var statusEl = null;
    var cursorEl = null;
    var chipsEl = null;
    var outputEl = null;
    var choiceEl = null;
    var titleEl = null;
    var isOpen = false;
    var streamToken = 0;
    var timers = [];
    var lastSignature = "";
    var streamDone = false;
    var footerDone = false;
    var CHAT_DRAFT_KEY = "bot_error_assistant_chat_draft_v1";
    var COMPLETE_CACHE_PREFIX = "bot_error_assistant_complete_v1";

    function getSpec() {
        if (spec) return spec;
        spec = global.AIAssistantSpec || null;
        ea = spec && spec.errorAssistant ? spec.errorAssistant : null;
        return spec;
    }

    function timing(key, def) {
        return (ea && ea.timing && ea.timing[key] != null) ? ea.timing[key] : def;
    }

    // -------- yardımcı bağlam --------
    function fallbackName() {
        return (spec && spec.copy && spec.copy.fallbackUserName) || "dostum";
    }

    function resolveUserName() {
        try {
            if (opts && typeof opts.getUserName === "function") {
                var n = (opts.getUserName() || "").trim();
                if (n) return n;
            }
        } catch (e) {}
        try {
            var raw = sessionStorage.getItem("user") || localStorage.getItem("user");
            if (raw) {
                var u = JSON.parse(raw);
                var name = (u && (u.first_name || u.name || u.username || u.email)) || "";
                name = String(name).split("@")[0].split(" ")[0].trim();
                if (name) return name;
            }
        } catch (e2) {}
        return fallbackName();
    }

    function symbolNow() {
        try {
            if (opts && typeof opts.getSymbol === "function") {
                return String(opts.getSymbol() || "").toUpperCase();
            }
        } catch (e) {}
        return "";
    }

    function limitText(text, maxLen) {
        var s = String(text || "").replace(/\s+\n/g, "\n").replace(/\n\s+/g, "\n").trim();
        if (s.length <= maxLen) return s;
        return s.slice(0, Math.max(0, maxLen - 1)).trim() + "…";
    }

    function completeCacheKey() {
        var botId = (opts && opts.botId) || "";
        return COMPLETE_CACHE_PREFIX + ":" + (botId || symbolNow() || "detail");
    }

    function readCompleteCache() {
        try {
            var raw = sessionStorage.getItem(completeCacheKey());
            if (!raw) return null;
            var data = JSON.parse(raw);
            if (!data || !data.signature) return null;
            if (data.ts && Date.now() - Number(data.ts) > 6 * 60 * 60 * 1000) {
                sessionStorage.removeItem(completeCacheKey());
                return null;
            }
            return data;
        } catch (e) {
            return null;
        }
    }

    function storeCompleteCache(model) {
        try {
            if (!model || !model.signature) return;
            sessionStorage.setItem(completeCacheKey(), JSON.stringify({
                signature: model.signature,
                ts: Date.now()
            }));
        } catch (e) {}
    }

    function quoteNow() {
        try {
            if (opts && typeof opts.getQuote === "function") {
                var q = String(opts.getQuote() || "").toUpperCase();
                if (q) return q;
            }
        } catch (e) {}
        var sym = symbolNow();
        if (/USDT$/.test(sym)) return "USDT";
        if (/BUSD$/.test(sym)) return "BUSD";
        if (/USDC$/.test(sym)) return "USDC";
        if (/(TRY|EUR|BTC|ETH|BNB)$/.test(sym)) return RegExp.$1;
        return "USDT";
    }

    function baseFromSymbol(sym, quote) {
        sym = String(sym || "").toUpperCase();
        quote = String(quote || "").toUpperCase();
        if (quote && sym.length > quote.length && sym.slice(-quote.length) === quote) {
            return sym.slice(0, sym.length - quote.length);
        }
        return sym;
    }

    function isRunning() {
        try {
            return !!(opts && typeof opts.isRunning === "function" && opts.isRunning());
        } catch (e) {
            return false;
        }
    }

    function isServerDown() {
        try {
            return !!(opts && typeof opts.isServerUnreachable === "function" && opts.isServerUnreachable());
        } catch (e) {
            return false;
        }
    }

    function healthData() {
        try {
            return (opts && typeof opts.getHealthData === "function" && opts.getHealthData()) || null;
        } catch (e) {
            return null;
        }
    }

    function uiPick() {
        try {
            return (opts && typeof opts.getUiPick === "function" && opts.getUiPick()) || null;
        } catch (e) {
            return null;
        }
    }

    function roundOrNull(v) {
        var n = Number(v);
        return Number.isFinite(n) ? Math.round(n) : null;
    }

    function baseCtx() {
        var sym = symbolNow();
        var quote = quoteNow();
        return {
            name: resolveUserName(),
            symbol: sym || "bot",
            base: baseFromSymbol(sym, quote) || "coin",
            quote: quote,
            botId: (opts && opts.botId) || ""
        };
    }

    // -------- aktif uyarı toplama --------
    function collectAlerts() {
        var list = [];
        var pick = uiPick();
        if (pick && (pick.criticals || pick.warns)) {
            list = (pick.criticals || []).concat(pick.warns || []);
        } else {
            var hd0 = healthData();
            list = (hd0 && Array.isArray(hd0.alerts)) ? hd0.alerts.slice() : [];
        }
        list = list.filter(Boolean);

        var hd = healthData();
        if (hd && hd.connectivity_ok === false && hd.connectivity_failure) {
            var connCode = String(hd.connectivity_failure.error_code || "BINANCE_UNREACHABLE").toUpperCase();
            var already = list.some(function (a) {
                var c = String((a && (a.code || (a.meta && a.meta.error_code) || a.error_code)) || "").toUpperCase();
                return c === connCode || c === "BINANCE_UNREACHABLE" || c === "API_UNAUTHORIZED";
            });
            if (!already) {
                list.push({
                    code: connCode === "BINANCE_UNREACHABLE" ? "BINANCE_UNREACHABLE" : connCode,
                    level: "critical",
                    message: hd.connectivity_failure.message || "",
                    meta: { error_code: connCode, source: hd.connectivity_failure.source }
                });
            }
        }
        if (isServerDown()) {
            var hasServer = list.some(function (a) {
                return String((a && a.code) || "").toUpperCase() === "SERVER_UNREACHABLE";
            });
            if (!hasServer) {
                list.unshift({ code: "SERVER_UNREACHABLE", level: "critical", meta: {} });
            }
        }
        return list;
    }

    function levelRank(level) {
        return String(level || "").toLowerCase() === "critical" ? 2 : 1;
    }

    function dedupeByKbCode(alerts) {
        var byKey = {};
        var order = [];
        alerts.forEach(function (a) {
            var key = spec.normalizeErrorCode(a);
            if (!key) return;
            if (!byKey[key]) {
                byKey[key] = a;
                order.push(key);
            } else if (levelRank(a.level) > levelRank(byKey[key].level)) {
                byKey[key] = a;
            }
        });
        return order.map(function (key) {
            return { key: key, alert: byKey[key] };
        });
    }

    function ctxForAlert(alert) {
        var ctx = baseCtx();
        var meta = (alert && alert.meta) || {};
        var hd = healthData();
        ctx.errorCode = String(meta.error_code || alert.error_code || "").toUpperCase() || ctx.symbol;
        var tickAge = meta.tick_age_s;
        if (tickAge == null && hd) tickAge = hd.tick_age_s;
        ctx.tickAge = roundOrNull(tickAge);
        if (ctx.tickAge == null) ctx.tickAge = "?";
        var interval = meta.interval_s;
        if (interval == null && hd) interval = hd.tick_interval_s;
        ctx.interval = roundOrNull(interval);
        if (ctx.interval == null) ctx.interval = "?";
        ctx.failCount = meta.fail_count != null ? meta.fail_count
            : (meta.lock_skip_count != null ? meta.lock_skip_count
                : (meta.slippage_count != null ? meta.slippage_count : "birkaç"));
        ctx.count = ctx.failCount;
        ctx.ageMin = meta.snapshot_age_s != null
            ? Math.max(1, Math.round(Number(meta.snapshot_age_s) / 60))
            : "birkaç";
        ctx.level = alert.level;
        ctx.title = alert.title || alert.message || "";
        ctx.code = spec.normalizeErrorCode(alert);
        return ctx;
    }

    function buildReports(alerts) {
        var reports = dedupeByKbCode(alerts).map(function (u) {
            return spec.errorReportForCode(u.alert, ctxForAlert(u.alert));
        });
        reports.sort(function (a, b) {
            return levelRank(b.level) - levelRank(a.level);
        });
        return reports;
    }

    function groupByTheme(reports) {
        var groups = {};
        var order = [];
        reports.forEach(function (r) {
            var t = r.theme || "generic";
            if (!groups[t]) { groups[t] = []; order.push(t); }
            groups[t].push(r);
        });
        return order.map(function (t) { return { theme: t, reports: groups[t] }; });
    }

    // -------- ekran modeli (chips + satırlar + footer) --------
    function buildModel() {
        var ctx = baseCtx();
        var running = isRunning();
        var server = isServerDown();
        var alerts = collectAlerts();

        if (!running && !server && !alerts.length) {
            var st = spec.errorStoppedReport(ctx);
            return {
                kind: "stopped",
                signature: "stopped",
                greeting: spec.errorGreeting(ctx),
                chips: [{ label: "Bot durduruldu", cls: "neutral" }],
                lines: [
                    { text: st.lead, cls: "" },
                    { text: st.close, cls: "muted" }
                ],
                actions: ["refresh"],
                needsAdmin: false
            };
        }

        if (!alerts.length) {
            var hp = spec.errorHealthyReport(ctx);
            return {
                kind: "healthy",
                signature: "healthy",
                greeting: spec.errorGreeting(ctx),
                chips: [{ label: "Sağlıklı · sorun yok", cls: "ok" }],
                lines: [{ text: hp.lead, cls: "ok" }],
                actions: ["refresh"],
                needsAdmin: false
            };
        }

        var reports = buildReports(alerts);
        var groups = groupByTheme(reports);
        var chips = reports.map(function (r) {
            return { label: r.label, cls: r.level === "critical" ? "crit" : "warn" };
        });

        var lines = [];
        lines.push({
            text: reports.length === 1
                ? "1 aktif bulgu buldum; aşağıda neden + çözüm olarak açıklıyorum."
                : (reports.length + " aktif bulgu var; ilişkili olanları birbirine bağladım ve önem sırasına dizdim."),
            cls: "muted"
        });

        groups.forEach(function (g) {
            if (g.reports.length > 1) {
                var cn = spec.errorConnectLine(g.theme, ctx);
                if (cn) lines.push({ text: cn, cls: "connect" });
            }
            g.reports.forEach(function (r) {
                var tag = r.continues ? " · bot çalışmaya devam ediyor" : " · işlem duraklamış olabilir";
                lines.push({
                    text: r.badge + " · " + r.label + tag,
                    cls: r.level === "critical" ? "head head-crit" : "head head-warn"
                });
                if (r.why) lines.push({ text: "Neden: " + r.why, cls: "" });
                if (r.impact) lines.push({ text: "Anlamı: " + r.impact, cls: "" });
                if (r.steps && r.steps.length) {
                    var steps = r.steps.map(function (s, i) { return (i + 1) + ") " + s; }).join("   ");
                    lines.push({ text: "Çözüm: " + steps, cls: "solution" });
                }
            });
        });
        lines.push({ text: spec.errorClosing(ctx), cls: "muted" });

        // footer aksiyonları (deduped union; sohbet en altta ayrı)
        var actionSet = {};
        var actionOrder = [];
        reports.forEach(function (r) {
            (r.actions || []).forEach(function (id) {
                if (id === "contact") return;
                if (!actionSet[id]) { actionSet[id] = true; actionOrder.push(id); }
            });
        });
        if (actionOrder.indexOf("refresh") < 0) actionOrder.push("refresh");
        var needsAdmin = reports.some(function (r) {
            return r.needsAdmin || (r.actions || []).indexOf("contact") >= 0;
        });

        return {
            kind: "problem",
            signature: "problem|" + reports.map(function (r) { return r.code; }).join(","),
            greeting: spec.errorGreeting(ctx),
            chips: chips,
            lines: lines,
            actions: actionOrder,
            needsAdmin: needsAdmin,
            adminLine: needsAdmin ? spec.errorAdminPrompt(ctx) : "",
            reports: reports,
            ctx: ctx
        };
    }

    function buildContactDraft(model) {
        var ctx = (model && model.ctx) || baseCtx();
        var reports = (model && model.reports) || [];
        var codes = reports.map(function (r) { return String((r && r.code) || "").toUpperCase(); }).filter(Boolean);
        var supportCode = "HA-" + (ctx.botId ? ("B" + ctx.botId) : (ctx.symbol || "BOT")) + "-" +
            (codes[0] || "AUTO") + "-" + String(Date.now()).slice(-6);
        var lines = [];
        lines.push("Merhaba, Hata Asistanı üzerinden destek istiyorum.");
        lines.push("Takip kodu: " + supportCode);
        lines.push("Bot: " + (ctx.symbol || "bot") + (ctx.botId ? " (#" + ctx.botId + ")" : ""));
        lines.push("Hata kodları: " + (codes.length ? codes.map(function (c) { return "[" + c + "]"; }).join(", ") : "[AUTO_RESOLVER]"));
        if (reports.length) {
            lines.push("Aktif bulgu: " + reports.map(function (r) {
                return (r.label || r.code || "bulgu") + (r.code ? " [" + r.code + "]" : "");
            }).join(", "));
            var primary = reports[0] || {};
            if (primary.why) lines.push("Neden: " + primary.why);
            if (primary.impact) lines.push("Etki: " + primary.impact);
            if (primary.steps && primary.steps.length) lines.push("Kontrol: " + primary.steps.slice(0, 2).join(" / "));
        } else if (model && model.lines && model.lines.length) {
            lines.push("Özet: " + model.lines.slice(0, 2).map(function (x) { return x.text || ""; }).join(" "));
        }
        lines.push("Rica: Bu bot için kontrol edip yönlendirebilir misiniz?");
        return limitText(lines.filter(Boolean).join("\n"), 2000);
    }

    function buildContactContext(model) {
        var ctx = (model && model.ctx) || baseCtx();
        var reports = ((model && model.reports) || []).map(function (r) {
            return {
                code: String((r && r.code) || "").toUpperCase(),
                label: r && r.label,
                level: r && r.level,
                theme: r && r.theme,
                why: r && r.why,
                impact: r && r.impact,
                steps: r && r.steps ? r.steps.slice(0, 5) : [],
                actions: r && r.actions ? r.actions.slice(0, 6) : [],
                needsAdmin: !!(r && r.needsAdmin)
            };
        });
        return {
            source: "bot-error-assistant",
            signature: (model && model.signature) || "",
            kind: (model && model.kind) || "",
            ctx: {
                symbol: ctx.symbol || "",
                botId: ctx.botId || "",
                quote: ctx.quote || "",
                errorCode: ctx.errorCode || ""
            },
            codes: reports.map(function (r) { return r.code; }).filter(Boolean),
            reports: reports
        };
    }

    function storeContactDraft() {
        try {
            var model = buildModel();
            var body = buildContactDraft(model);
            if (!body) return;
            sessionStorage.setItem(CHAT_DRAFT_KEY, JSON.stringify({
                source: "bot-error-assistant",
                body: body,
                assistant_context: buildContactContext(model),
                signature: model.signature || "",
                ts: Date.now()
            }));
        } catch (e) {}
    }

    // -------- DOM kurulum (Parametre Asistanı yapısı) --------
    function el(tag, cls, text) {
        var d = document.createElement(tag);
        if (cls) d.className = cls;
        if (text != null) d.textContent = text;
        return d;
    }

    function spark(idx) {
        var s = el("span", "perf-summary-spark perf-summary-intro-spark perf-summary-intro-spark-" + idx);
        s.setAttribute("aria-hidden", "true");
        return s;
    }

    function ensureModal() {
        if (overlay) return overlay;
        if (spec && typeof spec.applyDesignVars === "function") spec.applyDesignVars();

        overlay = el("div", "modal-overlay dm-param-assistant-modal bea-modal");
        overlay.id = "botErrorAssistantModal";
        overlay.setAttribute("role", "dialog");
        overlay.setAttribute("aria-modal", "true");

        panelEl = el("div", "modal-panel parametreler-modal-panel perf-summary-modal-panel dm-param-assistant-panel");

        var head = el("div", "modal-panel-head dm-param-assistant-head");
        var headLeft = el("div", "dm-pa-head-left");
        titleEl = el("h3", "modal-title dm-param-assistant-title", (ea && ea.modal && ea.modal.title) || "Bot Hata Asistanı");
        headLeft.appendChild(titleEl);
        var closeBtn = el("button", "parametreler-modal-close", "×");
        closeBtn.type = "button";
        closeBtn.setAttribute("aria-label", (ea && ea.modal && ea.modal.closeLabel) || "Kapat");
        closeBtn.addEventListener("click", close);
        head.appendChild(headLeft);
        head.appendChild(closeBtn);

        bodyEl = el("div", "parametreler-body perf-summary-modal-body dm-param-assistant-body");

        var introWrap = el("div", "perf-summary-intro-spark-wrap");
        for (var i = 1; i <= 6; i++) introWrap.appendChild(spark(i));
        var introInner = el("div", "perf-summary-assistant-intro-inner");
        introInner.appendChild(el("div", "perf-summary-assistant-label", (ea && ea.modal && ea.modal.label) || "Hata asistanı"));
        var introP = el("p", "perf-summary-assistant-intro");
        statusEl = el("span", "bea-status-text");
        cursorEl = el("span", "perf-summary-stream-cursor");
        cursorEl.setAttribute("aria-hidden", "true");
        introP.appendChild(statusEl);
        introP.appendChild(cursorEl);
        introInner.appendChild(introP);
        introWrap.appendChild(introInner);

        chipsEl = el("div", "dm-param-assistant-chips");
        outputEl = el("div", "dm-param-assistant-output");
        choiceEl = el("div", "dm-param-assistant-choice");
        choiceEl.style.display = "none";

        bodyEl.appendChild(introWrap);
        bodyEl.appendChild(chipsEl);
        bodyEl.appendChild(outputEl);
        bodyEl.appendChild(choiceEl);

        panelEl.appendChild(head);
        panelEl.appendChild(bodyEl);
        overlay.appendChild(panelEl);

        overlay.addEventListener("click", function (e) {
            if (e.target === overlay) close();
        });
        document.addEventListener("keydown", function (e) {
            if (isOpen && (e.key === "Escape" || e.keyCode === 27)) close();
        });

        document.body.appendChild(overlay);
        return overlay;
    }

    // -------- streaming motoru --------
    function clearTimers() {
        timers.forEach(function (t) { clearTimeout(t); });
        timers = [];
    }
    function setTimer(fn, ms) {
        var id = setTimeout(fn, ms);
        timers.push(id);
        return id;
    }
    function chunkSize() {
        // Hata asistanı hızlı okunur: görünürken 6 karakter/tick, sekme gizliyse hızlı bitir.
        return document.hidden ? 24 : 6;
    }
    function scrollBottom() {
        if (!bodyEl) return;
        var overflow = bodyEl.scrollHeight - bodyEl.clientHeight;
        if (overflow <= 8) {
            bodyEl.scrollTop = 0;
            return;
        }
        bodyEl.scrollTop = bodyEl.scrollHeight;
    }

    function typeInto(node, text, done, options) {
        var local = streamToken;
        var shouldScroll = !(options && options.scroll === false);
        var s = String(text || "");
        var i = 0;
        node.textContent = "";
        var T = timing("textMs", 18);
        var dotMul = timing("dotPauseMul", 2);
        function step() {
            if (local !== streamToken) return;
            var c = chunkSize();
            node.textContent += s.slice(i, i + c);
            i += c;
            if (shouldScroll) scrollBottom();
            if (i < s.length) {
                var last = s.charAt(i - 1);
                setTimer(step, (last === "." || last === ":" ) ? T * dotMul : T);
            } else if (typeof done === "function") {
                setTimer(done, timing("linePauseMs", 220));
            }
        }
        step();
    }

    function renderChips(chips, instant) {
        chipsEl.innerHTML = "";
        var stagger = timing("chipStaggerMs", 70);
        (chips || []).forEach(function (c, idx) {
            var span = el("span", (instant ? "" : "dm-param-assistant-chip-ai ") + "bea-chip-" + (c.cls || "info"));
            span.style.setProperty("--dm-chip-delay", (idx * stagger) + "ms");
            span.appendChild(el("b", null, c.label));
            chipsEl.appendChild(span);
        });
    }

    function renderLinesInstant(lines) {
        outputEl.innerHTML = "";
        (lines || []).forEach(function (item) {
            var line = el("p", "dm-param-assistant-line" + (item.cls ? " bea-line-" + item.cls.split(" ").join(" bea-line-") : ""), item.text || "");
            outputEl.appendChild(line);
        });
    }

    function typeLines(lines, idx, done) {
        if (idx >= lines.length) {
            if (typeof done === "function") done();
            return;
        }
        var local = streamToken;
        var item = lines[idx];
        var line = el("p", "dm-param-assistant-line" + (item.cls ? " bea-line-" + item.cls.split(" ").join(" bea-line-") : ""));
        outputEl.appendChild(line);
        typeInto(line, item.text, function () {
            if (local !== streamToken) return;
            typeLines(lines, idx + 1, done);
        });
    }

    function makeActionBtn(id) {
        var meta = spec.errorActionMeta(id);
        if (!meta) return null;
        if (opts && opts.actions && typeof opts.actions[id] !== "function") return null;
        var cls = "btn dm-pa-action " + (meta.kind === "accent" ? "btn-primary-gold dm-pa-action-accent" : "btn-ghost dm-pa-action-ghost");
        var btn = el("button", cls, meta.label);
        btn.type = "button";
        if (meta.title) btn.title = meta.title;
        btn.addEventListener("click", function () { runAction(id); });
        return btn;
    }

    function makeChoiceBar(model) {
        var bar = el("div", "bea-choice-bar");
        (model.actions || []).forEach(function (id) {
            var b = makeActionBtn(id);
            if (b) bar.appendChild(b);
        });
        var closeBtn = el("button", "btn btn-ghost dm-pa-action dm-pa-action-ghost", (ea && ea.modal && ea.modal.closeLabel) || "Kapat");
        closeBtn.type = "button";
        closeBtn.addEventListener("click", close);
        bar.appendChild(closeBtn);
        return bar;
    }

    function revealAdminSupport(admin, model, done) {
        var local = streamToken;
        admin.classList.remove("bea-admin-loading");
        admin.innerHTML = "";

        var title = el("div", "bea-admin-title");
        var text = el("p", "bea-admin-text");
        admin.appendChild(title);
        admin.appendChild(text);

        typeInto(title, (ea && ea.modal && ea.modal.contactTitle) || "Yönetim desteği gerekebilir", function () {
            if (local !== streamToken) return;
            typeInto(text, model.adminLine || "", function () {
                if (local !== streamToken) return;
                if (opts && opts.actions && typeof opts.actions.contact === "function") {
                    var chat = el("button", "btn btn-primary-gold dm-pa-action dm-pa-action-accent bea-chat-btn bea-admin-chat-in", null);
                    chat.type = "button";
                    var meta = spec.errorActionMeta("contact") || { label: "Yönetimle sohbet" };
                    chat.appendChild(el("span", null, meta.label));
                    if (meta.title) chat.title = meta.title;
                    chat.addEventListener("click", function () { runAction("contact"); });
                    admin.appendChild(chat);
                }
                if (typeof done === "function") setTimer(done, timing("linePauseMs", 220));
                scrollBottom();
            });
        });
    }

    function appendAdminSupportInstant(parent, model) {
        var admin = el("div", "bea-admin");
        admin.appendChild(el("div", "bea-admin-title", (ea && ea.modal && ea.modal.contactTitle) || "Yönetim desteği gerekebilir"));
        if (model.adminLine) admin.appendChild(el("p", "bea-admin-text", model.adminLine));
        if (opts && opts.actions && typeof opts.actions.contact === "function") {
            var chat = el("button", "btn btn-primary-gold dm-pa-action dm-pa-action-accent bea-chat-btn", null);
            chat.type = "button";
            var meta = spec.errorActionMeta("contact") || { label: "Yönetimle sohbet" };
            chat.appendChild(el("span", null, meta.label));
            if (meta.title) chat.title = meta.title;
            chat.addEventListener("click", function () { runAction("contact"); });
            admin.appendChild(chat);
        }
        parent.appendChild(admin);
    }

    function showFooter(model, instant) {
        choiceEl.innerHTML = "";
        choiceEl.style.display = "flex";

        var appendBar = function () {
            choiceEl.appendChild(makeChoiceBar(model));
            footerDone = true;
            storeCompleteCache(model);
            scrollBottom();
        };

        if (instant && model.needsAdmin && opts && opts.actions && typeof opts.actions.contact === "function") {
            appendAdminSupportInstant(choiceEl, model);
            appendBar();
            return;
        }

        if (model.needsAdmin && opts && opts.actions && typeof opts.actions.contact === "function") {
            var admin = el("div", "bea-admin bea-admin-loading");
            var loading = el("div", "bea-admin-loading-line");
            loading.appendChild(el("span", null, "Asistan yönetim notunu hazırlıyor"));
            loading.appendChild(el("span", "bea-admin-loading-dots", "..."));
            admin.appendChild(loading);
            choiceEl.appendChild(admin);
            scrollBottom();
            setTimer(function () {
                revealAdminSupport(admin, model, appendBar);
            }, Math.max(260, timing("linePauseMs", 220) + 160));
            return;
        }

        appendBar();
    }

    function runAction(id) {
        if (!opts || !opts.actions || typeof opts.actions[id] !== "function") return;
        if (id === "contact") storeContactDraft();
        var res;
        try { res = opts.actions[id](); } catch (e) { res = null; }
        if (id === "openParams" || id === "wallet" || id === "apiKeys" || id === "contact") {
            close();
            return;
        }
        if (id === "refresh" || id === "reset") {
            lastSignature = "";  // sonucu yeniden yaz
            var rerun = function () { if (isOpen) startStream(true); };
            if (res && typeof res.then === "function") res.then(rerun, rerun);
            else setTimer(rerun, 650);
        }
    }

    // -------- akış başlat --------
    function renderInstant(model) {
        streamToken++;
        clearTimers();
        lastSignature = model.signature;
        streamDone = true;
        footerDone = true;
        if (titleEl) {
            titleEl.textContent = (model.kind === "problem")
                ? ((ea.modal && ea.modal.title) || "Bot Hata Asistanı")
                : ((ea.modal && ea.modal.healthyTitle) || "Bot Sağlık Durumu");
        }
        statusEl.textContent = model.greeting || "";
        if (cursorEl) cursorEl.style.display = "none";
        renderChips(model.chips, true);
        renderLinesInstant(model.lines);
        showFooter(model, true);
        if (bodyEl) bodyEl.scrollTop = 0;
    }

    function startStream(force) {
        if (!getSpec() || !ea) return;
        var model = buildModel();
        if (!force && streamDone && footerDone && model.signature === lastSignature) {
            if (cursorEl) cursorEl.style.display = "none";
            return;  // aynı durum, yeniden yazma (poll güncellemesi / tekrar açma)
        }
        var completeCache = readCompleteCache();
        if (!force && completeCache && completeCache.signature === model.signature) {
            renderInstant(model);
            return;
        }
        lastSignature = model.signature;
        streamDone = false;
        footerDone = false;
        streamToken++;
        clearTimers();

        if (titleEl) {
            titleEl.textContent = (model.kind === "problem")
                ? ((ea.modal && ea.modal.title) || "Bot Hata Asistanı")
                : ((ea.modal && ea.modal.healthyTitle) || "Bot Sağlık Durumu");
        }
        chipsEl.innerHTML = "";
        outputEl.innerHTML = "";
        choiceEl.innerHTML = "";
        choiceEl.style.display = "none";
        if (cursorEl) cursorEl.style.display = "inline-block";

        var local = streamToken;
        typeInto(statusEl, model.greeting, function () {
            if (local !== streamToken) return;
            renderChips(model.chips);
            setTimer(function () {
                if (local !== streamToken) return;
                typeLines(model.lines, 0, function () {
                    if (local !== streamToken) return;
                    if (cursorEl) cursorEl.style.display = "none";
                    streamDone = true;
                    showFooter(model);
                });
            }, Math.min(900, (model.chips.length * timing("chipStaggerMs", 70)) + 260));
        }, { scroll: false });
    }

    // -------- açılış/kapanış --------
    function lockScroll(lock) {
        try { document.body.style.overflow = lock ? "hidden" : ""; } catch (e) {}
    }

    function open() {
        if (!getSpec() || !ea) return;
        ensureModal();
        isOpen = true;
        overlay.classList.add("is-open");
        overlay.setAttribute("aria-hidden", "false");
        lockScroll(true);

        // açılışta canlı veriyi tazele; gelince akışı başlat
        var started = false;
        var begin = function () { if (isOpen && !started) { started = true; startStream(false); } };
        try {
            if (opts && typeof opts.refresh === "function") {
                var p = opts.refresh();
                if (p && typeof p.then === "function") {
                    p.then(begin, begin);
                    setTimer(begin, 420);  // fallback: ağ yavaşsa bekletme
                    return;
                }
            }
        } catch (e) {}
        setTimer(begin, timing("introPauseMs", 160));
    }

    function close() {
        isOpen = false;
        streamToken++;
        clearTimers();
        if (overlay) {
            overlay.classList.remove("is-open");
            overlay.setAttribute("aria-hidden", "true");
        }
        lockScroll(false);
    }

    function attachButton(btn) {
        if (!btn) return;
        if (getSpec() && ea && ea.button) {
            var cleanLabel = String(ea.button.label || "Hata Asistanı").replace(/^AI\s+/i, "").trim() || "Hata Asistanı";
            var label = btn.querySelector ? btn.querySelector(".bea-btn-label") : null;
            if (label) {
                label.textContent = cleanLabel;
            } else if (!btn.textContent || !btn.textContent.trim()) {
                btn.textContent = cleanLabel;
            }
            if (ea.button.title) btn.title = ea.button.title;
            if (ea.button.ariaLabel) btn.setAttribute("aria-label", ea.button.ariaLabel);
            if (ea.button.className && !btn.classList.contains(ea.button.className)) {
                btn.classList.add(ea.button.className);
            }
        }
        btn.addEventListener("click", function (e) {
            e.preventDefault();
            open();
        });
    }

    function init(config) {
        opts = config || {};
        getSpec();
        if (opts.button) attachButton(opts.button);
        return global.BotErrorAssistant;
    }

    global.BotErrorAssistant = {
        init: init,
        open: open,
        close: close,
        attachButton: attachButton,
        rerender: function () { return false; },
        isOpen: function () { return isOpen; }
    };
})(typeof window !== "undefined" ? window : globalThis);
