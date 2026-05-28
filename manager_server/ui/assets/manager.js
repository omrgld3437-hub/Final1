// manager (assets/).
(function () {
  const API = "";
  const keys = ["web", "engine", "manager", "html"];
  let ws = {};
  let wsEvents = null;
  let pause = { web: false, engine: false, manager: false, html: false };
  let logMaxLines = 1000;
  const errWrnMaxLines = 50;
  let lastMetrics = null;
  let metricsIntervalId = null;
  let securityPollIntervalId = null;
  let pollIntervalMs = 2000;
  let selectedIssueId = null;
  let useWsEvents = true;
  let rawLogLines = { web: [], engine: [], manager: [], html: [] };
  let errWrnSnapshot = {
    web: { errors: [], warns: [] },
    engine: { errors: [], warns: [] },
    manager: { errors: [], warns: [] },
    html: { errors: [], warns: [] }
  };
  let filterLevel = { web: "WARN+", engine: "WARN+", manager: "WARN+", html: "WARN+" };
  let searchQuery = { web: "", engine: "", manager: "", html: "" };
  let autoscroll = { web: true, engine: true, manager: true, html: true };
  let lastMetricsReceivedAt = 0;
  let lastDiagnosis = {};          // key -> diagnosis object
  let lastIssuesFingerprint = "";
  let lastWsIssuesFp = "";

  function showToast() {}
  function showDiagnosisToast() {}

  function qs(s) { return document.querySelector(s); }
  function qsa(s) { return document.querySelectorAll(s); }

  async function api(method, path, body) {
    const opt = { method };
    if (body) opt.body = JSON.stringify(body), opt.headers = { "Content-Type": "application/json" };
    const r = await fetch(API + path, opt);
    const text = await r.text();
    if (!r.ok) {
      var errMsg = text || r.statusText || "HTTP " + r.status;
      if (r.status === 403) errMsg = "Erişim engellendi (403). Uzaktan erişim için sunucuyu MANAGER_ALLOW_REMOTE=1 ile başlatın.";
      throw new Error(errMsg);
    }
    try { return text ? JSON.parse(text) : {}; } catch (e) { return {}; }
  }

  function setButtonsLoading(ids, loading) {
    ids.forEach(function (id) {
      var b = qs("#" + id);
      if (!b) return;
      b.disabled = loading;
      b.style.pointerEvents = loading ? "none" : "";
      b.style.opacity = loading ? "0.7" : "";
    });
  }

  function showActionFeedback(message, isError) {
    var el = qs("#globalLastOp");
    if (el) {
      el.textContent = message;
      el.style.color = isError ? "#e74c3c" : "";
    }
  }

  function getLiveUptime(key) {
    if (!lastMetrics || !lastMetrics[key]) return null;
    const base = lastMetrics[key].uptime_s;
    if (base == null) return null;
    const elapsed = (Date.now() / 1000) - lastMetricsReceivedAt;
    return Math.max(0, Math.floor(base + elapsed));
  }

  function setStatus(key, data) {
    const chip = qs("#status-" + key);
    if (chip) {
      chip.textContent = data.running ? "ÇALIŞIYOR " + (data.pid || "") : "DURDURULDU";
      chip.className = "status-chip " + (data.running ? "running" : "stopped");
    }
    const statEl = qs("#stat-" + key);
    if (statEl && data) {
      const parts = [];
      if (data.pid != null) parts.push("PID " + data.pid);
      var uptime = data.running ? getLiveUptime(key) : (lastMetrics && lastMetrics[key] ? lastMetrics[key].uptime_s : null);
      if (key === "html" && typeof data.started_at === "number") uptime = Math.max(0, Math.floor(Date.now() / 1000 - data.started_at));
      parts.push("Çalışma süresi: " + formatUptime(uptime));
      if (data.restart_count != null) parts.push("Yeniden başlatma: " + data.restart_count);
      if (key === "web" && lastMetrics && lastMetrics.web) {
        if (lastMetrics.web.cpu_pct != null) parts.push(lastMetrics.web.cpu_pct + "% CPU");
        if (lastMetrics.web.rss_mb != null) parts.push(lastMetrics.web.rss_mb + " MB");
      }
      if (key === "engine" && lastMetrics && lastMetrics.engine) {
        if (lastMetrics.engine.cpu_pct != null) parts.push(lastMetrics.engine.cpu_pct + "% CPU");
        if (lastMetrics.engine.rss_mb != null) parts.push(lastMetrics.engine.rss_mb + " MB");
      }
      if (key === "manager" && lastMetrics && lastMetrics.manager) {
        if (lastMetrics.manager.cpu_pct != null) parts.push(lastMetrics.manager.cpu_pct + "% CPU");
        if (lastMetrics.manager.rss_mb != null) parts.push(lastMetrics.manager.rss_mb + " MB");
      }
      statEl.textContent = parts.join(" · ");
    }
  }

  function formatUptime(s) {
    if (s == null || s === undefined) return "—";
    if (s < 60) return s + " sn";
    const m = Math.floor(s / 60);
    const h = Math.floor(m / 60);
    if (h > 0) return h + " sa " + (m % 60) + " dk";
    return m + " dk";
  }

  function setTextIfChanged(el, text) {
    if (!el) return;
    var s = (text == null || text === undefined) ? "" : String(text);
    if (el.textContent !== s) el.textContent = s;
  }

  /** PID null geldiğinde çalışan serviste son bilinen değeri koru (flicker önleme). */
  var overviewPidCache = { manager: null, engine: null, html: null };

  function stickyServicePid(key, status, proc) {
    var st = status || {};
    var pr = proc || {};
    var pid = st.pid != null ? st.pid : (pr.pid != null ? pr.pid : null);
    if (pid != null) {
      overviewPidCache[key] = pid;
      return pid;
    }
    if (st.running && overviewPidCache[key] != null) return overviewPidCache[key];
    if (!st.running) overviewPidCache[key] = null;
    return null;
  }

  function setOverviewPid(key, status, proc) {
    var pid = stickyServicePid(key, status, proc);
    setTextIfChanged(qs("#overview-" + key + "-pid"), pid != null ? String(pid) : "—");
  }

  function setHealthBadgeIfChanged(el, text, className) {
    if (!el) return;
    var s = (text == null || text === undefined) ? "" : String(text);
    if (el.textContent !== s) el.textContent = s;
    if (el.className !== className) el.className = className;
  }

  function setOverviewStatusChip(el, running) {
    if (!el) return;
    var text = running ? "ÇALIŞIYOR" : "DURDURULDU";
    var cls = "status-chip service-status " + (running ? "running" : "stopped");
    setTextIfChanged(el, text);
    if (el.className !== cls) el.className = cls;
  }

  function setProgressBar(el, pct) {
    if (!el) return;
    el.style.width = Math.min(100, pct) + "%";
    el.className = "ov-progress-fill" + (pct > 90 ? " crit" : pct > 70 ? " warn" : "");
  }

  function renderOverviewAlerts(errWeb, wrnWeb, errEng, wrnEng, errMgr, wrnMgr) {
    var listEl = qs("#overview-alerts-list");
    if (!listEl) return;
    var items = [];
    errWeb.slice(-5).forEach(function (l) { items.push({ svc: "TraderTrailing", type: "err", msg: l || "" }); });
    wrnWeb.slice(-5).forEach(function (l) { items.push({ svc: "TraderTrailing", type: "wrn", msg: l || "" }); });
    errEng.slice(-5).forEach(function (l) { items.push({ svc: "Bot Engine", type: "err", msg: l || "" }); });
    wrnEng.slice(-5).forEach(function (l) { items.push({ svc: "Bot Engine", type: "wrn", msg: l || "" }); });
    errMgr.slice(-3).forEach(function (l) { items.push({ svc: "Yönetici", type: "err", msg: l || "" }); });
    wrnMgr.slice(-3).forEach(function (l) { items.push({ svc: "Yönetici", type: "wrn", msg: l || "" }); });
    if (!items.length) {
      listEl.innerHTML = "<div class=\"overview-alerts-empty\">Son hata veya uyarı yok.</div>";
      return;
    }
    listEl.innerHTML = items.map(function (it) {
      var cls = it.type === "err" ? "alert-err" : "alert-wrn";
      var typeLabel = it.type === "err" ? "HATA" : "UYARI";
      var typeCls = it.type === "err" ? "type-err" : "type-wrn";
      return "<div class=\"overview-alert-item " + cls + "\">" +
        "<span class=\"overview-alert-svc\">" + escHtml(it.svc) + "</span>" +
        "<span class=\"overview-alert-type " + typeCls + "\">" + typeLabel + "</span>" +
        "<span class=\"overview-alert-msg\">" + escHtml(it.msg) + "</span></div>";
    }).join("");
  }

  function formatResource(proc) {
    if (!proc) return "—";
    return [proc.cpu_pct != null ? proc.cpu_pct + "% CPU" : null, proc.rss_mb != null ? proc.rss_mb + " MB" : null].filter(Boolean).join(" · ") || "—";
  }

  function mergeMetricsPayload(incoming) {
    incoming = incoming || {};
    if (!lastMetrics) return incoming;
    var out = Object.assign({}, lastMetrics, incoming);
    var prevWeb = lastMetrics.web_app || {};
    var nextWeb = incoming.web_app || {};
    out.web_app = Object.assign({}, prevWeb, nextWeb);
    if (nextWeb.requests_per_min == null && prevWeb.requests_per_min != null) {
      out.web_app.requests_per_min = prevWeb.requests_per_min;
    }
    if (nextWeb.error_rate == null && prevWeb.error_rate != null) {
      out.web_app.error_rate = prevWeb.error_rate;
    }
    if (nextWeb.latency_p95_ms == null && prevWeb.latency_p95_ms != null) {
      out.web_app.latency_p95_ms = prevWeb.latency_p95_ms;
    }
    var prevEng = lastMetrics.engine_app || {};
    var nextEng = incoming.engine_app || {};
    out.engine_app = Object.assign({}, prevEng, nextEng);
    if (!incoming.errors_ring && lastMetrics.errors_ring) out.errors_ring = lastMetrics.errors_ring;
    if (!incoming.warns_ring && lastMetrics.warns_ring) out.warns_ring = lastMetrics.warns_ring;
    if (!incoming.status && lastMetrics.status) out.status = lastMetrics.status;
    return out;
  }

  function metricOrDash(val, running, fmt) {
    if (val != null && val !== "") return fmt ? fmt(val) : String(val);
    return running ? (fmt ? fmt(0) : "0") : "—";
  }

  function updateMetricsUI(m) {
    m = mergeMetricsPayload(m);
    lastMetrics = m;
    lastMetricsReceivedAt = Date.now() / 1000;
    const sys = m.system || {};
    const el = (id, text) => { const e = qs(id); if (e) e.textContent = text; };
    const traffic = m.web_app || {};
    const loginFails = traffic.last_login_fails || [];
    const topIps = traffic.top_ips || [];
    const errWeb = (m.errors_ring && m.errors_ring.web) ? m.errors_ring.web : [];
    const errEng = (m.errors_ring && m.errors_ring.engine) ? m.errors_ring.engine : [];
    const errMgr = (m.errors_ring && m.errors_ring.manager) ? m.errors_ring.manager : [];
    const wrnWeb = (m.warns_ring && m.warns_ring.web) ? m.warns_ring.web : [];
    const wrnEng = (m.warns_ring && m.warns_ring.engine) ? m.warns_ring.engine : [];
    const wrnMgr = (m.warns_ring && m.warns_ring.manager) ? m.warns_ring.manager : [];

    var lastUpdateEl = qs("#overview-last-update");
    if (lastUpdateEl) setTextIfChanged(lastUpdateEl, "Son güncelleme: " + (new Date().toLocaleTimeString("tr-TR") || "—"));
    var healthEl = qs("#overview-health-badge");
    if (healthEl) {
      var webOk = m.status && m.status.web && m.status.web.running;
      var engOk = m.status && m.status.engine && m.status.engine.running;
      var hasErr = errWeb.length + errEng.length > 0;
      var healthText, healthClass;
      if (!webOk || !engOk) { healthText = "Servis durumu uyarı"; healthClass = "overview-health-badge warn"; }
      else if (hasErr) { healthText = "Hata var"; healthClass = "overview-health-badge warn"; }
      else { healthText = "Tümü normal"; healthClass = "overview-health-badge ok"; }
      setHealthBadgeIfChanged(healthEl, healthText, healthClass);
    }

    const cpuPct = sys.cpu_pct != null ? sys.cpu_pct : 0;
    const ramPct = (sys.ram_used_mb != null && sys.ram_total_mb != null && sys.ram_total_mb > 0)
      ? Math.round(100 * sys.ram_used_mb / sys.ram_total_mb) : 0;
    const diskPct = (sys.disk_used_mb != null && sys.disk_total_mb != null && sys.disk_total_mb > 0)
      ? Math.round(100 * sys.disk_used_mb / sys.disk_total_mb) : 0;
    el("#overview-cpu", sys.cpu_pct != null ? sys.cpu_pct + "%" : "—");
    el("#overview-ram", sys.ram_used_mb != null && sys.ram_total_mb != null
      ? sys.ram_used_mb + " / " + sys.ram_total_mb + " MB" : "—");
    el("#overview-disk", sys.disk_used_mb != null && sys.disk_total_mb != null
      ? Math.round(sys.disk_used_mb / 1024) + " / " + Math.round(sys.disk_total_mb / 1024) + " GB" : "—");
    el("#overview-load", sys.load_avg != null ? sys.load_avg : "—");
    const progressCpu = qs("#progress-cpu");
    setProgressBar(progressCpu, cpuPct);
    const progressRam = qs("#progress-ram");
    setProgressBar(progressRam, ramPct);
    const progressDisk = qs("#progress-disk");
    setProgressBar(progressDisk, diskPct);

    setTextIfChanged(qs("#overview-manager-port"), "7999");
    var mgrRunning = m.status && m.status.manager && m.status.manager.running;
    var mgrStatus = qs("#overview-manager-status");
    setOverviewStatusChip(mgrStatus, mgrRunning);
    var d = m.status && m.status.manager ? m.status.manager : {};
    var liveMgrUptime = (d.running && m.manager) ? getLiveUptime("manager") : (m.manager ? m.manager.uptime_s : null);
    setOverviewPid("manager", d, m.manager);
    setTextIfChanged(qs("#overview-manager-uptime"), formatUptime(liveMgrUptime) || "—");
    el("#overview-manager-resource", formatResource(m.manager));
    setTextIfChanged(qs("#overview-manager-err-wrn"), errMgr.length + " / " + wrnMgr.length);

    const webProc = m.web || {};
    const webApp = m.web_app || {};
    const webRunning = (m.status && m.status.web && m.status.web.running);
    setTextIfChanged(qs("#overview-web-port"), "8000");
    const overviewWebChip = qs("#overview-web-status");
    setOverviewStatusChip(overviewWebChip, webRunning);
    el("#overview-web-reqmin", metricOrDash(webApp.requests_per_min, webRunning));
    el("#overview-web-error-rate", metricOrDash(webApp.error_rate, webRunning, function (v) { return (Number(v) * 100).toFixed(2) + "%"; }));
    el("#overview-web-p95", metricOrDash(webApp.latency_p95_ms, webRunning, function (v) { return v + " ms"; }));
    setTextIfChanged(qs("#overview-web-err-wrn"), errWeb.length + " / " + wrnWeb.length);

    const engProc = m.engine || {};
    const engApp = m.engine_app || {};
    const engStatus = m.status && m.status.engine ? m.status.engine : {};
    const engRunning = !!engStatus.running;
    setOverviewPid("engine", engStatus, engProc);
    const overviewEngChip = qs("#overview-engine-status");
    setOverviewStatusChip(overviewEngChip, engRunning);
    el("#overview-engine-bots", engApp.active_bots != null ? engApp.active_bots : "—");
    el("#overview-engine-tick", engApp.tick_rate_10s != null ? engApp.tick_rate_10s : "—");
    el("#overview-engine-tick-age", engApp.last_tick_age_s != null ? engApp.last_tick_age_s + " sn" : "—");
    setTextIfChanged(qs("#overview-engine-err-wrn"), errEng.length + " / " + wrnEng.length);

    var htmlProc = m.html || {};
    var htmlStatus = m.status && m.status.html ? m.status.html : {};
    var htmlChip = qs("#overview-html-status");
    setOverviewStatusChip(htmlChip, !!htmlStatus.running);
    setTextIfChanged(qs("#overview-html-port"), "8080");
    setOverviewPid("html", htmlStatus, htmlProc);
    var htmlUptime = (typeof htmlStatus.started_at === "number")
      ? Math.max(0, Math.floor(Date.now() / 1000 - htmlStatus.started_at))
      : (htmlProc.uptime_s != null ? htmlProc.uptime_s : null);
    setTextIfChanged(qs("#overview-html-uptime"), formatUptime(htmlUptime) || "—");
    var errHtml = (m.errors_ring && m.errors_ring.html) ? m.errors_ring.html : [];
    var wrnHtml = (m.warns_ring && m.warns_ring.html) ? m.warns_ring.html : [];
    el("#overview-html-resource", formatResource(htmlProc));
    setTextIfChanged(qs("#overview-html-err-wrn"), errHtml.length + " / " + wrnHtml.length);

    const total = webApp.request_total || 0;
    const bad = webApp.status_5xx || 0;
    const availability = total > 0 ? ((total - bad) / total * 100) : 100;
    const sloBar = qs("#slo-bar");
    if (sloBar) {
      sloBar.style.width = Math.min(100, availability) + "%";
      sloBar.className = "ov-progress-fill slo-bar" + (availability >= 99.9 ? "" : availability >= 99 ? " warn" : " crit");
    }
    el("#slo-text", availability.toFixed(2) + "% · hedef 99.9% · 5xx: " + bad);

    renderOverviewAlerts(errWeb, wrnWeb, errEng, wrnEng, errMgr, wrnMgr);
    const alertsPre = qs("#overview-alerts");
    if (alertsPre) alertsPre.textContent = "";

    setTextIfChanged(qs("#overview-errors-summary"), "TraderTrailing: " + errWeb.length + ", Bot Engine: " + errEng.length + ", Yönetici: " + errMgr.length);

    keys.forEach(function (k) {
      var ec = (m.errors_ring && m.errors_ring[k]) ? m.errors_ring[k].length : 0;
      var wc = (m.warns_ring && m.warns_ring[k]) ? m.warns_ring[k].length : 0;
      updateNavAlertState(k, ec, wc);
    });

    setTextIfChanged(qs("#overview-login-fail"), "Toplam " + (traffic.login_fail_total || 0) + " · Listede: " + loginFails.length);

    const restWeb = (m.status && m.status.web && m.status.web.restart_count != null) ? m.status.web.restart_count : 0;
    const statWeb = qs("#stat-web");
    if (statWeb) {
      const parts = [];
      if (webProc.pid != null) parts.push("PID " + webProc.pid);
      parts.push("Çalışma süresi: " + formatUptime(webRunning ? getLiveUptime("web") : webProc.uptime_s));
      parts.push("Yeniden başlatma: " + restWeb);
      if (webProc.cpu_pct != null) parts.push(webProc.cpu_pct + "% CPU");
      if (webProc.rss_mb != null) parts.push(webProc.rss_mb + " MB");
      if (webApp.requests_per_min != null) parts.push(webApp.requests_per_min + "/min");
      if (webApp.latency_p95_ms != null) parts.push("P95 " + webApp.latency_p95_ms + "ms");
      statWeb.textContent = parts.join(" · ");
    }
    const restEng = (m.status && m.status.engine && m.status.engine.restart_count != null) ? m.status.engine.restart_count : 0;
    const statEng = qs("#stat-engine");
    if (statEng) {
      const parts = [];
      if (engProc.pid != null) parts.push("PID " + engProc.pid);
      parts.push("Çalışma süresi: " + formatUptime(engRunning ? getLiveUptime("engine") : engProc.uptime_s));
      parts.push("Yeniden başlatma: " + restEng);
      if (engProc.cpu_pct != null) parts.push(engProc.cpu_pct + "% CPU");
      if (engProc.rss_mb != null) parts.push(engProc.rss_mb + " MB");
      if (engApp.active_bots != null) parts.push(engApp.active_bots + " bots");
      if (engApp.tick_rate_10s != null) parts.push("tick/10s " + engApp.tick_rate_10s);
      if (engApp.last_tick_age_s != null) parts.push("tick yaşı " + engApp.last_tick_age_s + " sn");
      statEng.textContent = parts.join(" · ");
    }

    const loginPre = qs("#security-login-fails");
    if (loginPre) patchLogPre(loginPre, loginFails.length ? formatLoginFails(loginFails) : "Başarısız giriş yok.");
    const ipsPre = qs("#security-top-ips");
    if (ipsPre) patchLogPre(ipsPre, topIps.length
      ? topIps.map(x => (x.ip || "") + " " + (x.count || 0)).join("\n")
      : "IP verisi yok.");
    const fivexx = qs("#security-5xx-msg");
    if (fivexx) fivexx.textContent = (traffic.status_5xx || 0) > 0
      ? "5xx: " + traffic.status_5xx + " | Hata oranı: " + (traffic.error_rate != null ? (traffic.error_rate * 100).toFixed(2) + "%" : "—")
      : "5xx yok.";
  }

  function formatLoginFails(list) {
    return list.map(function (f) {
      var ts = f.ts ? new Date(f.ts * 1000).toLocaleString("tr-TR") : "—";
      var ip = f.ip || "—";
      var user = f.user || "—";
      var reasonRaw = f.reason ? f.reason : "—";
      var reason = reasonRaw;
      if (window.LogHumanize && reasonRaw !== "—" && /ERROR|WARN|fail|SSL|401|Unauthorized|Exception/i.test(reasonRaw)) {
        reason = window.LogHumanize.format(reasonRaw, "web");
      }
      return "Tarih: " + ts + "\nIP: " + ip + "\nKullanıcı: " + user + "\nSebep: " + reason;
    }).join("\n\n");
  }

  async function refreshSecurity() {
    try {
      const traffic = await fetch(API + "/api/traffic").then(r => r.ok ? r.json() : {}).catch(function () { return {}; });
      const loginFails = traffic.last_login_fails || [];
      const topIps = traffic.top_ips || [];
      const loginPre = qs("#security-login-fails");
      if (loginPre) patchLogPre(loginPre, loginFails.length ? formatLoginFails(loginFails) : "Başarısız giriş yok.");
      const ipsPre = qs("#security-top-ips");
      if (ipsPre) patchLogPre(ipsPre, topIps.length
        ? topIps.map(function (x) { return (x.ip || "") + " " + (x.count || 0); }).join("\n")
        : "IP verisi yok.");
      const fivexx = qs("#security-5xx-msg");
      if (fivexx) fivexx.textContent = (traffic.status_5xx || 0) > 0
        ? "5xx: " + traffic.status_5xx + " | Hata oranı: " + (traffic.error_rate != null ? (traffic.error_rate * 100).toFixed(2) + "%" : "—")
        : "5xx yok.";
    } catch (e) { console.error(e); }
  }

  function showApiConnectionError(msg) {
    var el = qs("#globalLastOp");
    if (el) {
      el.textContent = msg || "API bağlantı hatası";
      el.style.color = "#e74c3c";
    }
    var statWeb = qs("#stat-web");
    if (statWeb && !statWeb.dataset.hasShownError) {
      statWeb.dataset.hasShownError = "1";
      statWeb.textContent = (statWeb.textContent || "") + " [API erişilemiyor – localhost veya MANAGER_ALLOW_REMOTE=1 gerekli]";
    }
  }

  async function refreshMetrics() {
    try {
      const metricsRes = await fetch(API + "/api/metrics");
      const statusRes = await fetch(API + "/api/status");
      if (!metricsRes.ok || !statusRes.ok) {
        if (metricsRes.status === 403 || statusRes.status === 403) {
          showApiConnectionError("Erişim engellendi (403). Manager'a uzaktan erişim için sunucuyu MANAGER_ALLOW_REMOTE=1 ile başlatın.");
        }
        return;
      }
      const metrics = await metricsRes.json().catch(function () { return {}; });
      const status = await statusRes.json().catch(function () { return {}; });
      if (metrics && typeof metrics === "object") {
        metrics.status = status;
        if (!metrics.web_app || metrics.web_app.requests_per_min == null) {
          try {
            var traffic = await fetch(API + "/api/traffic").then(function (r) { return r.ok ? r.json() : {}; });
            if (traffic && typeof traffic === "object" && Object.keys(traffic).length) {
              metrics.web_app = Object.assign({}, metrics.web_app || {}, traffic);
            }
          } catch (_) {}
        }
        const [errWeb, errEng, errMgr, errHtml] = await Promise.all([
          fetch(API + "/api/logs/web?tail=0").then(r => r.ok ? r.json() : {}).catch(() => ({})),
          fetch(API + "/api/logs/engine?tail=0").then(r => r.ok ? r.json() : {}).catch(() => ({})),
          fetch(API + "/api/logs/manager?tail=0").then(r => r.ok ? r.json() : {}).catch(() => ({})),
          fetch(API + "/api/logs/html?tail=0").then(r => r.ok ? r.json() : {}).catch(() => ({}))
        ]);
        metrics.errors_ring = { web: (errWeb.errors || []), engine: (errEng.errors || []), manager: (errMgr.errors || []), html: (errHtml.errors || []) };
        metrics.warns_ring = { web: (errWeb.warns || []), engine: (errEng.warns || []), manager: (errMgr.warns || []), html: (errHtml.warns || []) };
        updateMetricsUI(metrics);
      }
      keys.forEach(k => setStatus(k, status[k]));
      var hostEl = qs("#manager-controlled-host");
      if (hostEl) hostEl.textContent = "Kontrol edilen sunucu: " + (status.host || "—");
      const [audit] = await Promise.all([
        fetch(API + "/api/audit?limit=300").then(r => r.ok ? r.json() : []).catch(() => []),
      ]);
      var overviewActive = qs("#panel-overview") && qs("#panel-overview").classList.contains("active");
      var incidentsActive = qs("#panel-incidents") && qs("#panel-incidents").classList.contains("active");
      if (overviewActive || incidentsActive) refreshIssueStats();
      const restarts = Array.isArray(audit) ? audit.filter(function (e) { return ["start", "stop", "restart"].indexOf(e.action) >= 0; }).slice(-10) : [];
      var restartsText = restarts.length ? restarts.map(function (e) {
        var svc = (e.detail && e.detail.service) ? e.detail.service : "";
        return (e.action || "") + (svc ? " " + svc : "");
      }).join("\n") : "—";
      setTextIfChanged(qs("#overview-restarts-10"), restartsText);
    } catch (e) { console.error(e); }
  }

  function formatIssueLastSeen(s) {
    if (!s) return "—";
    try {
      var d = new Date(s);
      return isNaN(d.getTime()) ? s : d.toLocaleString("tr-TR");
    } catch (_) { return s; }
  }

  let incidentsView = "ACTIVE";
  let incidentsSearchTimer = null;
  let incidentsPollTimer = null;

  function escHtml(s) {
    return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function issueSummary(issue) {
    var samples = issue.samples || [];
    if (samples.length) return samples[samples.length - 1];
    return (issue.fingerprint || "").slice(0, 80);
  }

  function statusPill(status) {
    var st = (status || "OPEN").toUpperCase();
    var cls = "status-pill-open";
    if (st === "ACK") cls = "status-pill-ack";
    else if (st === "RESOLVED") cls = "status-pill-resolved";
    else if (st === "ARCHIVED") cls = "status-pill-archived";
    return "<span class=\"status-pill " + cls + "\">" + escHtml(st) + "</span>";
  }

  function buildIssuesQuery() {
    var parts = ["limit=200"];
    if (incidentsView && incidentsView !== "BACKUP") parts.push("status=" + encodeURIComponent(incidentsView));
    var svc = qs("#incidents-filter-service") ? qs("#incidents-filter-service").value : "";
    if (svc) parts.push("service=" + encodeURIComponent(svc));
    var q = qs("#incidents-search") ? qs("#incidents-search").value.trim() : "";
    if (q) parts.push("q=" + encodeURIComponent(q));
    return "?" + parts.join("&");
  }

  function buildIssuesArchiveQuery() {
    var parts = ["limit=200"];
    var svc = qs("#incidents-filter-service") ? qs("#incidents-filter-service").value : "";
    if (svc) parts.push("service=" + encodeURIComponent(svc));
    var q = qs("#incidents-search") ? qs("#incidents-search").value.trim() : "";
    if (q) parts.push("q=" + encodeURIComponent(q));
    return "?" + parts.join("&");
  }

  const ISSUE_SUMMARY_FALLBACK_KEY = "mgr_issue_summary_fallback";
  let issueSummaryUseFallback = false;
  try {
    issueSummaryUseFallback = sessionStorage.getItem(ISSUE_SUMMARY_FALLBACK_KEY) === "1";
  } catch (_) {}
  let issueSummaryProbePending = issueSummaryUseFallback;
  let lastIssueStatsFetchMs = 0;

  function markIssueSummaryFallback() {
    issueSummaryUseFallback = true;
    issueSummaryProbePending = false;
    try { sessionStorage.setItem(ISSUE_SUMMARY_FALLBACK_KEY, "1"); } catch (_) {}
  }

  function clearIssueSummaryFallback() {
    issueSummaryUseFallback = false;
    issueSummaryProbePending = false;
    try { sessionStorage.removeItem(ISSUE_SUMMARY_FALLBACK_KEY); } catch (_) {}
  }

  function computeIssueStatsFromList(list) {
    var counts = { open: 0, ack: 0, resolved: 0, archived: 0, active: 0, total: 0 };
    (list || []).forEach(function (i) {
      counts.total += 1;
      var st = (i.status || "OPEN").toUpperCase();
      if (st === "OPEN") counts.open += 1;
      else if (st === "ACK") counts.ack += 1;
      else if (st === "RESOLVED") counts.resolved += 1;
      else if (st === "ARCHIVED") counts.archived += 1;
    });
    counts.active = counts.open + counts.ack + counts.resolved;
    return counts;
  }

  function applyIssueStats(stats) {
    stats = stats || {};
    setTextIfChanged(qs("#inc-stat-open"), stats.open != null ? stats.open : 0);
    setTextIfChanged(qs("#inc-stat-ack"), stats.ack != null ? stats.ack : 0);
    setTextIfChanged(qs("#inc-stat-resolved"), stats.resolved != null ? stats.resolved : 0);
    setTextIfChanged(qs("#inc-stat-archived"), stats.archived != null ? stats.archived : 0);
    setTextIfChanged(qs("#inc-stat-backup"), stats.backup != null ? stats.backup : 0);
    setTextIfChanged(qs("#overview-issue-count"), stats.active != null ? stats.active : (stats.open || 0));
  }

  async function refreshIssueStats(cachedList, force) {
    var now = Date.now();
    if (!force && now - lastIssueStatsFetchMs < 3000) return;
    lastIssueStatsFetchMs = now;
    try {
      var stats = null;
      if (!issueSummaryUseFallback || issueSummaryProbePending) {
        var r = await fetch(API + "/api/issues/summary");
        if (r.ok) {
          stats = await r.json();
          clearIssueSummaryFallback();
        } else if (r.status === 404) {
          markIssueSummaryFallback();
        }
      }
      if (!stats) {
        var list = cachedList;
        if (!list) {
          list = await fetch(API + "/api/issues?limit=200").then(function (res) { return res.ok ? res.json() : []; }).catch(function () { return []; });
        }
        stats = computeIssueStatsFromList(list);
      }
      applyIssueStats(stats);
    } catch (_) {}
  }

  function issuesFingerprint(list) {
    return (list || []).map(function (i) {
      var svc = (i.tags && i.tags.service) ? i.tags.service : "";
      return [
        i.id || "",
        i.status || "",
        String(i.count != null ? i.count : ""),
        i.last_seen || "",
        i.severity || "",
        svc
      ].join("\t");
    }).join("\n");
  }

  function issueAction(path, issueId, after) {
    return api("POST", "/api/issues/" + issueId + path, {})
      .then(function () {
        if (typeof after === "function") after();
        return refreshIssueStats(null, true).then(function () { return refreshIssues(true); });
      })
      .catch(function (e) { alert(e.message); });
  }

  function renderIssueRowActions(issue, readOnly) {
    var id = issue.id;
    var st = (issue.status || "OPEN").toUpperCase();
    function actBtn(cls, label, icon) {
      return "<button type=\"button\" class=\"inc-act " + cls + "\" data-id=\"" + escHtml(id) + "\" title=\"" + escHtml(label) + "\">" +
        "<span class=\"inc-act-icon\" aria-hidden=\"true\">" + icon + "</span>" +
        "<span class=\"inc-act-label\">" + escHtml(label) + "</span></button>";
    }
    var icons = {
      detail: "<svg viewBox=\"0 0 16 16\" width=\"14\" height=\"14\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.5\"><circle cx=\"8\" cy=\"8\" r=\"5.5\"/><path d=\"M8 7v4M8 5.2v.1\"/></svg>",
      ack: "<svg viewBox=\"0 0 16 16\" width=\"14\" height=\"14\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.8\"><path d=\"M4 8.2l2.6 2.6L12 5.2\"/></svg>",
      resolve: "<svg viewBox=\"0 0 16 16\" width=\"14\" height=\"14\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.5\"><circle cx=\"8\" cy=\"8\" r=\"5.5\"/><path d=\"M5.5 8.2l1.8 1.8 3.4-3.6\" stroke-width=\"1.6\"/></svg>",
      archive: "<svg viewBox=\"0 0 16 16\" width=\"14\" height=\"14\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.5\"><path d=\"M3 5.5h10v7a1 1 0 01-1 1H4a1 1 0 01-1-1v-7z\"/><path d=\"M2 5.5l2-2.5h8l2 2.5M6.5 8.5h3\"/></svg>",
      reopen: "<svg viewBox=\"0 0 16 16\" width=\"14\" height=\"14\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.5\"><path d=\"M3.5 8a4.5 4.5 0 018.2-2.6M12.5 8A4.5 4.5 0 014.3 10.6\"/><path d=\"M11.5 3.5V6h-2.5\"/></svg>"
    };
    var html = "<div class=\"incident-actions\" role=\"group\" aria-label=\"Olay işlemleri\">";
    html += actBtn("inc-act-detail btn-issue-detail", "Detay", icons.detail);
    if (!readOnly) {
      if (st !== "ACK" && st !== "ARCHIVED") html += actBtn("inc-act-ack btn-issue-ack", "Onayla", icons.ack);
      if (st !== "RESOLVED" && st !== "ARCHIVED") html += actBtn("inc-act-resolve btn-issue-resolve", "Çöz", icons.resolve);
      if (st !== "ARCHIVED") html += actBtn("inc-act-archive btn-issue-archive", "Arşiv", icons.archive);
      else html += actBtn("inc-act-reopen btn-issue-reopen", "Geri al", icons.reopen);
    }
    html += "</div>";
    return html;
  }

  function bindIssueRowActions(tbody) {
    if (!tbody) return;
    tbody.querySelectorAll(".incident-actions").forEach(function (group) {
      group.addEventListener("click", function (e) { e.stopPropagation(); });
    });
    tbody.querySelectorAll(".btn-issue-detail").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.stopPropagation();
        var id = btn.getAttribute("data-id");
        var cached = lastIssuesListCache.find(function (i) { return i.id === id; });
        if (cached) {
          openDrawer(cached, incidentsView === "BACKUP");
          return;
        }
        fetch(API + "/api/issues/" + id).then(function (r) { return r.ok ? r.json() : null; }).then(function (issue) {
          if (issue) openDrawer(issue, false);
        });
      });
    });
    tbody.querySelectorAll(".btn-issue-ack").forEach(function (btn) {
      btn.addEventListener("click", function (e) { e.stopPropagation(); issueAction("/ack", btn.getAttribute("data-id")); });
    });
    tbody.querySelectorAll(".btn-issue-resolve").forEach(function (btn) {
      btn.addEventListener("click", function (e) { e.stopPropagation(); issueAction("/resolve", btn.getAttribute("data-id")); });
    });
    tbody.querySelectorAll(".btn-issue-archive").forEach(function (btn) {
      btn.addEventListener("click", function (e) { e.stopPropagation(); issueAction("/archive", btn.getAttribute("data-id")); });
    });
    tbody.querySelectorAll(".btn-issue-reopen").forEach(function (btn) {
      btn.addEventListener("click", function (e) { e.stopPropagation(); issueAction("/reopen", btn.getAttribute("data-id")); });
    });
  }

  async function refreshIssues(force) {
    var isBackup = incidentsView === "BACKUP";
    var list = [];
    if (isBackup) {
      var archiveData = await fetch(API + "/api/issues/archive" + buildIssuesArchiveQuery())
        .then(function (r) { return r.ok ? r.json() : { items: [] }; })
        .catch(function () { return { items: [] }; });
      list = archiveData.items || [];
    } else {
      list = await fetch(API + "/api/issues" + buildIssuesQuery()).then(function (r) { return r.ok ? r.json() : []; }).catch(function () { return []; });
    }
    const fp = issuesFingerprint(list) + "|view:" + incidentsView;
    if (!force && fp === lastIssuesFingerprint) return;
    lastIssuesFingerprint = fp;
    await refreshIssueStats(null, force);
    const tbody = qs("#incidents-list");
    const emptyEl = qs("#incidents-empty");
    const footnoteEl = qs("#incidents-footnote");
    const tableWrap = tbody && tbody.closest(".incidents-table-wrap");
    if (!tbody) return;
    tbody.innerHTML = "";
    lastIssuesListCache = list;
    list.forEach(function (issue) {
      const tr = document.createElement("tr");
      var stLower = isBackup ? "backup" : (issue.status || "open").toLowerCase();
      tr.className = "incident-row incident-row-" + stLower + (selectedIssueId === issue.id ? " selected" : "");
      const service = (issue.tags && issue.tags.service) ? issue.tags.service : "—";
      var sev = (issue.severity || "").toLowerCase();
      var statusHtml = isBackup
        ? "<span class=\"status-pill status-pill-backup\">YEDEK</span>"
        : statusPill(issue.status);
      tr.innerHTML =
        "<td class=\"incident-id\">" + escHtml(issue.id || "—") + "</td>" +
        "<td class=\"incident-severity\"><span class=\"severity-badge severity-" + escHtml(sev) + "\">" + escHtml(issue.severity || "—") + "</span></td>" +
        "<td class=\"incident-service\">" + escHtml(service) + "</td>" +
        "<td class=\"incident-summary\" title=\"" + escHtml(issueSummary(issue)) + "\">" + escHtml(issueSummary(issue)) + "</td>" +
        "<td class=\"incident-count\">" + (issue.count != null ? issue.count : "—") + "</td>" +
        "<td class=\"incident-last\">" + escHtml(formatIssueLastSeen(issue.last_seen || issue._backup_at)) + "</td>" +
        "<td class=\"incident-status\">" + statusHtml + "</td>" +
        "<td class=\"inc-col-actions\">" + renderIssueRowActions(issue, isBackup) + "</td>";
      tr.addEventListener("click", function () { openDrawer(issue, isBackup); });
      tbody.appendChild(tr);
    });
    bindIssueRowActions(tbody);
    if (emptyEl) {
      emptyEl.textContent = isBackup ? "Yerel yedekte olay yok." : "Bu filtrede olay yok.";
      emptyEl.classList.toggle("hidden", list.length > 0);
    }
    if (tableWrap) tableWrap.classList.toggle("hidden", list.length === 0);
    if (footnoteEl) footnoteEl.classList.toggle("hidden", false);
  }

  function startIncidentsPoll() {
    stopIncidentsPoll();
    incidentsPollTimer = setInterval(function () {
      if (document.hidden) return;
      var panel = qs("#panel-incidents");
      if (!panel || !panel.classList.contains("active")) return;
      refreshIssues(false);
    }, 5000);
  }

  function stopIncidentsPoll() {
    if (incidentsPollTimer) { clearInterval(incidentsPollTimer); incidentsPollTimer = null; }
  }

  function renderDiagnosis(key, data, isRunning) {
    var box = qs("#diagnosis-" + key);
    if (!box) return;
    if (!data || !data.reason_code) {
      box.classList.add("hidden");
      box.innerHTML = "";
      return;
    }
    if (isRunning && data.reason_code !== "RUNNING") {
      box.classList.add("hidden");
      box.innerHTML = "";
      return;
    }
    lastDiagnosis[key] = data;
    box.classList.remove("hidden");
    const ev = data.evidence || {};
    const stateClass = "state-" + (data.state || "").toLowerCase().replace(" ", "_");
    let html = "<div class=\"diag-badges\"><span class=\"diag-badge " + stateClass + "\">" + (data.state || "—") + "</span><span class=\"diag-badge\">" + (data.reason_code || "") + "</span></div>";
    html += "<div class=\"diag-title\">" + (data.title_tr || "") + "</div>";
    if (data.summary_tr) html += "<div class=\"diag-summary\">" + data.summary_tr + "</div>";
    if (data.impact_tr) html += "<div class=\"diag-impact\">Etkisi: " + data.impact_tr + "</div>";
    if (data.actions_tr && data.actions_tr.length) {
      html += "<div class=\"diag-title\">Yapılacaklar:</div><ul class=\"diag-list\">";
      data.actions_tr.forEach(function (a) { html += "<li>" + a + "</li>"; });
      html += "</ul>";
    }
    if (data.next_checks_tr && data.next_checks_tr.length) {
      html += "<div class=\"diag-title\">Kontroller:</div><ul class=\"diag-list\">";
      data.next_checks_tr.forEach(function (c) { html += "<li>" + c + "</li>"; });
      html += "</ul>";
    }
    html += "<div class=\"diag-title\">Kanıt:</div><div class=\"diag-evidence\">";
    if (ev.exit_code != null) html += "exit_code: " + ev.exit_code + "\n";
    if (ev.signal) html += "signal: " + ev.signal + "\n";
    if (ev.port != null) html += "port: " + ev.port + "\n";
    if (ev.pid != null) html += "pid: " + ev.pid + "\n";
    if (ev.last_lines && ev.last_lines.length) html += (ev.last_lines || []).join("\n");
    html += "</div>";
    html += "<div class=\"diag-export\"><a href=\"" + (API || "") + "/api/export/logs?service=" + key + "&format=csv\" target=\"_blank\" class=\"btn btn-sm btn-export\">Log dışa aktar</a> <a href=\"" + (API || "") + "/api/export/diagnosis?service=" + key + "&format=json\" target=\"_blank\" class=\"btn btn-sm btn-export\">Teşhis dışa aktar</a></div>";
    box.innerHTML = html;
  }

  let lastIssuesListCache = [];

  function openDrawer(issue, isBackup) {
    isBackup = !!isBackup;
    selectedIssueId = isBackup ? null : issue.id;
    const drawer = qs("#incident-drawer");
    const backdrop = qs("#incident-drawer-backdrop");
    if (!drawer) return;
    var st = (issue.status || "OPEN").toUpperCase();
    qs("#drawer-title").textContent = issue.id || "Olay";
    var sub = qs("#drawer-subtitle");
    if (sub) {
      sub.textContent = (issue.severity || "—") + " · " + ((issue.tags && issue.tags.service) || "—") +
        (isBackup ? " · Yerel yedek (salt okunur)" : "");
    }
    var statusEl = qs("#drawer-status");
    if (statusEl) {
      statusEl.innerHTML = isBackup
        ? "<span class=\"status-pill status-pill-backup\">YEDEK</span>"
        : statusPill(st);
    }
    setTextIfChanged(qs("#drawer-first-seen"), formatIssueLastSeen(issue.first_seen));
    setTextIfChanged(qs("#drawer-last-seen"), formatIssueLastSeen(issue.last_seen || issue._backup_at));
    setTextIfChanged(qs("#drawer-count"), issue.count != null ? String(issue.count) : "—");
    const assigneeInp = qs("#drawer-assignee");
    if (assigneeInp) { assigneeInp.value = issue.assignee || ""; assigneeInp.disabled = isBackup; }
    const labelsInp = qs("#drawer-labels");
    if (labelsInp) { labelsInp.value = Array.isArray(issue.labels) ? issue.labels.join(", ") : ""; labelsInp.disabled = isBackup; }
    const slaInp = qs("#drawer-sla");
    if (slaInp) { slaInp.value = issue.sla_note || ""; slaInp.disabled = isBackup; }
    const commentInp = qs("#drawer-comment-text");
    if (commentInp) { commentInp.value = ""; commentInp.disabled = isBackup; }
    const histEl = qs("#drawer-status-history");
    if (histEl) {
      var histLines = (issue.status_history || []).map(function (h) { return (h.ts || "") + " " + (h.status || ""); });
      if (isBackup && issue._backup_at) histLines.unshift((issue._backup_at || "") + " YEDEK");
      patchLogPre(histEl, histLines.join("\n") || "—");
    }
    const commentsEl = qs("#drawer-comments");
    if (commentsEl) {
      commentsEl.innerHTML = "";
      (issue.comments || []).forEach(function (c) {
        const div = document.createElement("div");
        div.className = "drawer-comment-item";
        div.innerHTML = "<span class=\"comment-meta\">" + escHtml(c.ts || "") + " " + escHtml(c.author || "") + "</span><br/>" + escHtml(c.text || "");
        commentsEl.appendChild(div);
      });
    }
    var drawerSamplesEl = qs("#drawer-samples");
    if (drawerSamplesEl) {
      var svc = (issue.tags && issue.tags.service) || "web";
      var samples = issue.samples || [];
      var sampleText = samples.length
        ? samples.map(function (s) {
            return window.LogHumanize ? window.LogHumanize.format(String(s), svc) : String(s);
          }).join("\n\n---\n\n")
        : "Örnek kayıt yok.";
      patchLogPre(drawerSamplesEl, sampleText);
    }
    var actionsTop = qs(".drawer-actions-top");
    if (actionsTop) actionsTop.classList.toggle("hidden", isBackup);
    var ackBtn = qs("#drawer-ack");
    var resolveBtn = qs("#drawer-resolve");
    var archiveBtn = qs("#drawer-archive");
    var reopenBtn = qs("#drawer-reopen");
    if (ackBtn) ackBtn.classList.toggle("hidden", isBackup || st === "ACK" || st === "ARCHIVED");
    if (resolveBtn) resolveBtn.classList.toggle("hidden", isBackup || st === "RESOLVED" || st === "ARCHIVED");
    if (archiveBtn) archiveBtn.classList.toggle("hidden", isBackup || st === "ARCHIVED");
    if (reopenBtn) reopenBtn.classList.toggle("hidden", isBackup || st !== "ARCHIVED");
    drawer.classList.remove("hidden");
    if (backdrop) backdrop.classList.remove("hidden");
    qsa(".incident-row").forEach(function (row) { row.classList.remove("selected"); });
    qsa(".incident-row").forEach(function (row) {
      if (row.querySelector(".incident-id") && row.querySelector(".incident-id").textContent === issue.id) row.classList.add("selected");
    });
  }

  function closeDrawer() {
    selectedIssueId = null;
    const drawer = qs("#incident-drawer");
    const backdrop = qs("#incident-drawer-backdrop");
    if (drawer) drawer.classList.add("hidden");
    if (backdrop) backdrop.classList.add("hidden");
    qsa(".incident-row.selected").forEach(function (row) { row.classList.remove("selected"); });
  }

  function reloadSelectedIssue() {
    if (!selectedIssueId) return Promise.resolve();
    return fetch(API + "/api/issues/" + selectedIssueId)
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (issue) { if (issue) openDrawer(issue); });
  }

  function saveDrawerAssignee() {
    if (!selectedIssueId) return;
    const v = qs("#drawer-assignee").value;
    api("POST", "/api/issues/" + selectedIssueId + "/assign", { assignee: v })
      .then(function () { return reloadSelectedIssue().then(function () { return refreshIssues(true); }); })
      .catch(function (e) { alert(e.message); });
  }

  function saveDrawerLabels() {
    if (!selectedIssueId) return;
    const v = qs("#drawer-labels").value;
    const labels = v.split(",").map(function (s) { return s.trim(); }).filter(Boolean).slice(0, 10);
    api("POST", "/api/issues/" + selectedIssueId + "/labels", { labels: labels })
      .then(function () { return reloadSelectedIssue().then(function () { return refreshIssues(true); }); })
      .catch(function (e) { alert(e.message); });
  }

  function saveDrawerSla() {
    if (!selectedIssueId) return;
    const v = qs("#drawer-sla").value;
    api("POST", "/api/issues/" + selectedIssueId + "/sla", { sla_note: v })
      .then(function () { return reloadSelectedIssue().then(function () { return refreshIssues(true); }); })
      .catch(function (e) { alert(e.message); });
  }

  function addDrawerComment() {
    if (!selectedIssueId) return;
    const inp = qs("#drawer-comment-text");
    const v = inp ? inp.value : "";
    if (!v.trim()) return;
    api("POST", "/api/issues/" + selectedIssueId + "/comment", { text: v })
      .then(function () { return reloadSelectedIssue().then(function () { return refreshIssues(true); }); })
      .catch(function (e) { alert(e.message); });
  }

  function bindDrawerEnterAdvance(inputId, saveFn, nextInputId) {
    const inp = qs(inputId);
    if (!inp) return;
    inp.addEventListener("keydown", function (e) {
      if (e.key !== "Enter") return;
      e.preventDefault();
      saveFn();
      if (nextInputId) {
        var next = qs(nextInputId);
        if (next) {
          setTimeout(function () {
            next.focus();
            if (typeof next.select === "function") next.select();
          }, 0);
        }
      }
    });
  }

  qs("#drawer-close").addEventListener("click", closeDrawer);
  var drawerBackdrop = qs("#incident-drawer-backdrop");
  if (drawerBackdrop) drawerBackdrop.addEventListener("click", closeDrawer);
  qs("#drawer-ack").addEventListener("click", function () {
    if (!selectedIssueId) return;
    issueAction("/ack", selectedIssueId, closeDrawer);
  });
  qs("#drawer-resolve").addEventListener("click", function () {
    if (!selectedIssueId) return;
    issueAction("/resolve", selectedIssueId, closeDrawer);
  });
  var drawerArchiveBtn = qs("#drawer-archive");
  if (drawerArchiveBtn) drawerArchiveBtn.addEventListener("click", function () {
    if (!selectedIssueId) return;
    issueAction("/archive", selectedIssueId, closeDrawer);
  });
  var drawerReopenBtn = qs("#drawer-reopen");
  if (drawerReopenBtn) drawerReopenBtn.addEventListener("click", function () {
    if (!selectedIssueId) return;
    issueAction("/reopen", selectedIssueId);
  });
  bindDrawerEnterAdvance("#drawer-assignee", saveDrawerAssignee, "#drawer-labels");
  bindDrawerEnterAdvance("#drawer-labels", saveDrawerLabels, "#drawer-sla");
  bindDrawerEnterAdvance("#drawer-sla", saveDrawerSla, "#drawer-comment-text");
  bindDrawerEnterAdvance("#drawer-comment-text", addDrawerComment, null);

  async function refreshStatus() {
    try {
      const s = await api("GET", "/api/status");
      keys.forEach(k => setStatus(k, s[k]));
      var hostEl = qs("#manager-controlled-host");
      if (hostEl) hostEl.textContent = "Kontrol edilen sunucu: " + (s.host || "—");
      if (s.html) {
        setStatus("html", s.html);
        var chip = qs("#overview-html-status");
        setOverviewStatusChip(chip, !!s.html.running);
        setOverviewPid("html", s.html, null);
        var htmlUptime = (typeof s.html.started_at === "number") ? Math.max(0, Math.floor(Date.now() / 1000 - s.html.started_at)) : null;
        setTextIfChanged(qs("#overview-html-uptime"), formatUptime(htmlUptime) || "—");
      }
      const locks = await api("GET", "/api/locks");
      keys.forEach(k => {
        const cb = qs("#lock-" + k);
        if (cb) cb.checked = !!locks[k];
      });
      refreshDiagnosis();
    } catch (e) { console.error(e); }
  }

  async function refreshDiagnosis() {
    try {
      var status = {};
      try { status = await api("GET", "/api/status"); } catch (_) {}
      var all = await api("GET", "/api/diagnosis");
      keys.forEach(function (k) {
        var d = all[k];
        var running = !!(status[k] && status[k].running);
        renderDiagnosis(k, d, running);
        var ov = qs("#overview-" + k + "-diagnosis");
        if (ov) {
          var txt = (running || !d || !d.title_tr) ? "—" : ("Son teşhis: " + d.title_tr + (d.ts ? " (" + d.ts + ")" : ""));
          setTextIfChanged(ov, txt);
          ov.classList.toggle("diagnosis-empty", txt === "—");
        }
      });
    } catch (e) { console.error(e); }
  }

  function humanizeLogLineIfNeeded(line, serviceKey) {
    if (!line || !window.LogHumanize) return line;
    if (!/ERROR|CRITICAL|Traceback|Exception|WARNING|\bWARN\b/i.test(line)) return line;
    return window.LogHumanize.format(line, serviceKey);
  }
  function formatErrWrnLine(l, serviceKey) {
    if (window.LogHumanize && typeof window.LogHumanize.formatEntry === "function") {
      return window.LogHumanize.formatEntry(l, serviceKey);
    }
    const raw = typeof l === "string" ? l : (l.ts || "") + " " + (l.text || l);
    return "Sebep: " + raw;
  }
  function updateNavAlertState(key, errCount, wrnCount) {
    errCount = errCount || 0;
    wrnCount = wrnCount || 0;
    var navItem = document.querySelector('.nav-item[data-tab="' + key + '"]');
    if (navItem) {
      navItem.classList.remove("nav-alert-err", "nav-alert-wrn");
      if (errCount > 0) navItem.classList.add("nav-alert-err");
      else if (wrnCount > 0) navItem.classList.add("nav-alert-wrn");
    }
    var badge = qs("#nav-err-" + key);
    if (badge) {
      var showCount = errCount > 0 ? errCount : wrnCount;
      badge.textContent = String(showCount);
      badge.classList.toggle("hidden", showCount === 0);
      badge.classList.remove("nav-badge-err", "nav-badge-wrn");
      if (errCount > 0) badge.classList.add("nav-badge-err");
      else if (wrnCount > 0) badge.classList.add("nav-badge-wrn");
    }
  }
  function logPreWasAtBottom(el, threshold) {
    if (!el) return true;
    threshold = threshold == null ? 32 : threshold;
    return el.scrollHeight - el.scrollTop - el.clientHeight <= threshold;
  }
  function patchLogPre(el, text) {
    if (!el) return;
    var next = text || "";
    if (el.textContent === next) return;
    var atBottom = logPreWasAtBottom(el);
    var prevTop = el.scrollTop;
    el.textContent = next;
    if (atBottom) {
      el.scrollTop = el.scrollHeight;
    } else {
      el.scrollTop = prevTop;
    }
  }
  function normalizeLogLine(l) {
    if (typeof l === "string") return l.trim();
    return (((l && l.ts) || "") + " " + toLogText(l)).trim();
  }
  function errWrnLineSet(key, kind) {
    var snap = errWrnSnapshot[key] || { errors: [], warns: [] };
    var src = kind === "ERROR" ? snap.errors : kind === "WARN" ? snap.warns : snap.errors.concat(snap.warns);
    var set = new Set();
    src.forEach(function (l) {
      var s = normalizeLogLine(l);
      if (s) set.add(s);
    });
    return set;
  }
  function mergedLogLinesFor(key) {
    var lines = (rawLogLines[key] || []).slice();
    var seen = new Set(lines);
    errWrnLineSet(key).forEach(function (s) {
      if (!seen.has(s)) {
        seen.add(s);
        lines.push(s);
      }
    });
    return lines;
  }
  function errWrnFingerprint(errList, wrnList) {
    return errList.map(normalizeLogLine).join("\0") + "\1" + wrnList.map(normalizeLogLine).join("\0");
  }
  function setErrWrn(key, newErrors, newWarns) {
    var errEl = qs("#err-" + key);
    var wrnEl = qs("#wrn-" + key);
    var errList = Array.isArray(newErrors) ? newErrors : [];
    var wrnList = Array.isArray(newWarns) ? newWarns : [];
    var nextFp = errWrnFingerprint(errList, wrnList);
    var prevFp = errWrnSnapshot[key] && errWrnSnapshot[key]._fp;
    errWrnSnapshot[key] = { errors: errList.slice(), warns: wrnList.slice(), _fp: nextFp };
    var errNum = errList.length;
    var wrnNum = wrnList.length;
    if (errEl) {
      var errLines = errList.slice(-errWrnMaxLines).map(function (l) { return formatErrWrnLine(l, key); });
      patchLogPre(errEl, errLines.join("\n\n") + (errLines.length ? "\n" : ""));
      var errCountEl = qs("#err-" + key + "-count");
      if (errCountEl) errCountEl.textContent = String(errNum);
    }
    if (wrnEl) {
      var wrnLines = wrnList.slice(-errWrnMaxLines).map(function (l) { return formatErrWrnLine(l, key); });
      patchLogPre(wrnEl, wrnLines.join("\n\n") + (wrnLines.length ? "\n" : ""));
      var wrnCountEl = qs("#wrn-" + key + "-count");
      if (wrnCountEl) wrnCountEl.textContent = String(wrnNum);
    }
    updateNavAlertState(key, errNum, wrnNum);
    if (nextFp !== prevFp) renderLog(key);
  }

  async function fetchLogs(key) {
    try {
      const d = await api("GET", "/api/logs/" + key + "?tail=300");
      rawLogLines[key] = (d.lines || []).map(function (l) { return normalizeLogLine(l); }).filter(Boolean);
      var errList = d.errors || [];
      var wrnList = d.warns || [];
      errWrnSnapshot[key] = {
        errors: errList.slice(),
        warns: wrnList.slice(),
        _fp: errWrnFingerprint(errList, wrnList)
      };
      const errEl = qs("#err-" + key);
      const wrnEl = qs("#wrn-" + key);
      if (errEl) {
        var errLines = errList.slice(-errWrnMaxLines).map(function (l) { return formatErrWrnLine(typeof l === "string" ? l : { ts: (l && l.ts) || "", text: toLogText(l) }, key); });
        patchLogPre(errEl, errLines.join("\n\n") + (errLines.length ? "\n" : ""));
        var errCountEl = qs("#err-" + key + "-count");
        if (errCountEl) errCountEl.textContent = String(errList.length);
      }
      if (wrnEl) {
        var wrnLines = wrnList.slice(-errWrnMaxLines).map(function (l) { return formatErrWrnLine(typeof l === "string" ? l : { ts: (l && l.ts) || "", text: toLogText(l) }, key); });
        patchLogPre(wrnEl, wrnLines.join("\n\n") + (wrnLines.length ? "\n" : ""));
        var wrnCountEl = qs("#wrn-" + key + "-count");
        if (wrnCountEl) wrnCountEl.textContent = String(wrnList.length);
      }
      updateNavAlertState(key, errList.length, wrnList.length);
      renderLog(key);
    } catch (e) { console.error(e); }
  }

  function renderLog(key) {
    const logEl = qs("#log-" + key);
    if (!logEl) return;
    const level = (filterLevel[key] || "").toUpperCase();
    const q = (searchQuery[key] || "").toLowerCase();
    let lines = mergedLogLinesFor(key);
    if (level === "WARN+") {
      var ewAll = errWrnLineSet(key);
      lines = lines.filter(function (l) {
        return ewAll.has(l) || /WARN|ERROR|Traceback|Exception|CRITICAL/i.test(l);
      });
    } else if (level === "ERROR") {
      var ewErr = errWrnLineSet(key, "ERROR");
      lines = lines.filter(function (l) {
        return ewErr.has(l) || /ERROR|Traceback|Exception|CRITICAL/i.test(l);
      });
    } else if (level === "WARN") {
      var ewWrn = errWrnLineSet(key, "WARN");
      lines = lines.filter(function (l) {
        return ewWrn.has(l) || /WARN/i.test(l);
      });
    } else if (level) {
      lines = lines.filter(function (l) { return l.indexOf(level) >= 0; });
    }
    if (q) lines = lines.filter(l => l.toLowerCase().indexOf(q) >= 0);
    lines = lines.slice(-logMaxLines);
    lines = lines.map(function (l) { return humanizeLogLineIfNeeded(l, key); });
    var logText = lines.join("\n") + (lines.length ? "\n" : "");
    patchLogPre(logEl, logText);
    if (autoscroll[key]) logEl.scrollTop = logEl.scrollHeight;
  }

  function toLogText(l) {
    if (typeof l === "string") return l;
    if (l && typeof l.text === "string") return l.text;
    if (l && typeof l.line === "string") return l.line;
    if (l && typeof l === "object") return "[log]";
    return String(l);
  }
  function appendLinesToKey(key, lines) {
    if (pause[key] || !lines || !lines.length) return;
    var arr = rawLogLines[key] || [];
    var statsPattern = /Günlük:\s*\d+\s*\|\s*Aylık:\s*\d+\s*\|\s*Toplam:\s*\d+/;
    lines.forEach(function (l) {
      var lineStr = normalizeLogLine(l);
      if (!lineStr) return;
      if (key === "html" && statsPattern.test(lineStr) && arr.length && arr[arr.length - 1] === lineStr) return;
      arr.push(lineStr);
    });
    rawLogLines[key] = arr.slice(-logMaxLines);
    renderLog(key);
  }

  function connectWs(key) {
    if (ws[key]) try { ws[key].close(); } catch (_) {}
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    ws[key] = new WebSocket(proto + "//" + location.host + "/ws/logs/" + key);
    ws[key].onmessage = function (ev) {
      if (pause[key]) return;
      try {
        const d = JSON.parse(ev.data);
        if (d.lines && d.lines.length) appendLinesToKey(key, d.lines);
        if (d.new_errors || d.new_warns) setErrWrn(key, d.new_errors || [], d.new_warns || []);
      } catch (_) {}
    };
    ws[key].onclose = function () { setTimeout(() => connectWs(key), 3000); };
  }

  function connectWsEvents() {
    if (wsEvents) try { wsEvents.close(); } catch (_) {}
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    wsEvents = new WebSocket(proto + "//" + location.host + "/ws/events");
    wsEvents.onmessage = function (ev) {
      try {
        const d = JSON.parse(ev.data);
        if (d.lines && d.lines.length) {
          const byKey = {};
          keys.forEach(k => byKey[k] = []);
          d.lines.forEach(l => { const k = l.service; if (byKey[k]) byKey[k].push(l); });
          keys.forEach(k => appendLinesToKey(k, byKey[k]));
        }
        var errByKey = {}; keys.forEach(k => errByKey[k] = []);
        var wrnByKey = {}; keys.forEach(k => wrnByKey[k] = []);
        if (d.errors_by_service && typeof d.errors_by_service === "object") {
          keys.forEach(function (k) { errByKey[k] = Array.isArray(d.errors_by_service[k]) ? d.errors_by_service[k] : []; });
        } else if (d.new_errors) {
          d.new_errors.forEach(function (e) { var k = e.service; if (errByKey[k]) errByKey[k].push(e.line || e); });
        }
        if (d.warns_by_service && typeof d.warns_by_service === "object") {
          keys.forEach(function (k) { wrnByKey[k] = Array.isArray(d.warns_by_service[k]) ? d.warns_by_service[k] : []; });
        } else if (d.new_warns) {
          d.new_warns.forEach(function (e) { var k = e.service; if (wrnByKey[k]) wrnByKey[k].push(e.line || e); });
        }
        keys.forEach(function (k) { setErrWrn(k, errByKey[k] || [], wrnByKey[k] || []); });
        if (d.metrics_update) {
          var mu = d.metrics_update;
          if (d.errors_by_service && typeof d.errors_by_service === "object") mu.errors_ring = d.errors_by_service;
          if (d.warns_by_service && typeof d.warns_by_service === "object") mu.warns_ring = d.warns_by_service;
          updateMetricsUI(mu);
          keys.forEach(k => setStatus(k, mu.status && mu.status[k] ? mu.status[k] : {}));
        }
        if (d.issue_events && d.issue_events.length) {
          var wsFp = d.issue_events.map(function (i) {
            return (i.id || "") + ":" + (i.count != null ? i.count : 0) + ":" + (i.service || "");
          }).join("|");
          if (wsFp !== lastWsIssuesFp) {
            lastWsIssuesFp = wsFp;
            refreshIssues(false);
          }
        }
        if (d.alert_events && d.alert_events.length) {
          d.alert_events.forEach(function (a) { showToast(a.message || a.kind || "Alert", a.level || "WARN", a.kind, a.id); });
        }
      } catch (_) {}
    };
    wsEvents.onclose = function () { if (useWsEvents) setTimeout(connectWsEvents, 3000); };
  }

  let auditView = "";
  let auditSearchTimer = null;
  let auditPollTimer = null;
  let lastAuditFingerprint = "";
  let auditEventsCache = [];

  const AUDIT_ACTION_TR = {
    start: "Servis başlatıldı",
    stop: "Servis durduruldu",
    restart: "Servis yeniden başlatıldı",
    reset: "Metrikler sıfırlandı",
    lock: "Servis kilidi değiştirildi",
    alert_ack: "Uyarı onaylandı",
    export_action: "Dışa aktarma yapıldı",
    issue_ack: "Olay onaylandı",
    issue_resolve: "Olay çözüldü",
    issue_archive: "Olay arşivlendi",
    issue_reopen: "Olay geri alındı",
    issue_assign: "Olay atandı",
    issue_labels: "Olay etiketleri güncellendi",
    issue_comment: "Olaya yorum eklendi",
    issue_sla: "Olay SLA notu güncellendi"
  };

  const AUDIT_CAT_TR = {
    servis: "Servis",
    olay: "Olay",
    uyari: "Uyarı",
    export: "Dışa aktarma",
    diger: "Diğer",
    yedek: "Yedek"
  };

  const AUDIT_EXPORT_TYPE_TR = {
    logs: "Log",
    issues: "Olay listesi",
    metrics: "Metrik",
    audit: "Denetim günlüğü",
    security: "Güvenlik",
    alerts: "Uyarı listesi",
    diagnosis: "Teşhis"
  };

  function auditCategory(action) {
    var a = action || "";
    if (a === "start" || a === "stop" || a === "restart" || a === "reset" || a === "lock") return "servis";
    if (a.indexOf("issue_") === 0) return "olay";
    if (a === "alert_ack") return "uyari";
    if (a === "export_action") return "export";
    return "diger";
  }

  function auditServiceName(key) {
    var map = { web: "Web", engine: "Motor", manager: "Yönetici", html: "HTML", all: "Tümü" };
    return map[key] || key || "—";
  }

  function auditEventService(action, detail) {
    detail = detail || {};
    if (detail.service) return detail.service;
    if (detail.key && detail.key !== "all") return detail.key;
    if (action === "export_action" && detail.service) return detail.service;
    if (action === "lock") {
      if (detail.web && !detail.engine) return "web";
      if (detail.engine && !detail.web) return "engine";
    }
    return "";
  }

  function formatAuditDescription(action, detail) {
    detail = detail || {};
    switch (action) {
      case "start":
      case "stop":
      case "restart":
        return auditServiceName(detail.service) + " servisi " + (action === "start" ? "başlatıldı" : action === "stop" ? "durduruldu" : "yeniden başlatıldı");
      case "reset":
        return detail.key === "all" ? "Tüm servislerin sayaç ve metrikleri sıfırlandı" : auditServiceName(detail.key) + " servis metrikleri sıfırlandı";
      case "lock": {
        var parts = [];
        if ("web" in detail) parts.push("Web: " + (detail.web ? "kilitli (otomatik başlatma kapalı)" : "serbest"));
        if ("engine" in detail) parts.push("Motor: " + (detail.engine ? "kilitli (otomatik başlatma kapalı)" : "serbest"));
        return parts.length ? parts.join(" · ") : "Kilit ayarı güncellendi";
      }
      case "alert_ack":
        return "Uyarı " + (detail.alert_id || "—") + " okundu / onaylandı";
      case "export_action": {
        var label = AUDIT_EXPORT_TYPE_TR[detail.type] || detail.type || "Veri";
        var fmt = (detail.format || "csv").toUpperCase();
        var extra = detail.service ? " · " + auditServiceName(detail.service) : "";
        if (detail.range) extra += " · " + detail.range;
        return label + " " + fmt + " olarak indirildi" + extra;
      }
      case "issue_ack":
        return "Olay " + (detail.issue_id || "—") + " incelendi ve onaylandı";
      case "issue_resolve":
        return "Olay " + (detail.issue_id || "—") + " çözüldü olarak işaretlendi";
      case "issue_archive":
        return "Olay " + (detail.issue_id || "—") + " arşive taşındı";
      case "issue_reopen":
        return "Olay " + (detail.issue_id || "—") + " arşivden geri alındı";
      case "issue_assign":
        return "Olay " + (detail.issue_id || "—") + " → " + (detail.assignee || "atanmadı");
      case "issue_labels":
        return "Olay " + (detail.issue_id || "—") + " · etiketler: " + ((detail.labels || []).join(", ") || "—");
      case "issue_comment":
        return "Olay " + (detail.issue_id || "—") + " · yeni yorum eklendi";
      case "issue_sla":
        return "Olay " + (detail.issue_id || "—") + " · SLA notu güncellendi";
      default:
        return JSON.stringify(detail);
    }
  }

  function formatAuditTs(ts) {
    if (!ts) return "—";
    try {
      var d = new Date(ts);
      return isNaN(d.getTime()) ? ts : d.toLocaleString("tr-TR");
    } catch (_) { return ts; }
  }

  function auditCategoryPill(cat) {
    return "<span class=\"audit-cat-pill audit-cat-" + escHtml(cat) + "\">" + escHtml(AUDIT_CAT_TR[cat] || cat) + "</span>";
  }

  function buildAuditArchiveQuery() {
    var parts = ["limit=300"];
    var svc = qs("#audit-filter-service") ? qs("#audit-filter-service").value : "";
    if (svc) parts.push("service=" + encodeURIComponent(svc));
    var q = qs("#audit-search") ? qs("#audit-search").value.trim() : "";
    if (q) parts.push("q=" + encodeURIComponent(q));
    return "?" + parts.join("&");
  }

  function filterAuditEvents(list) {
    var svc = qs("#audit-filter-service") ? qs("#audit-filter-service").value : "";
    var q = qs("#audit-search") ? qs("#audit-search").value.trim().toLowerCase() : "";
    return (list || []).filter(function (e) {
      var cat = auditCategory(e.action);
      if (auditView && auditView !== "BACKUP" && cat !== auditView) return false;
      var evSvc = auditEventService(e.action, e.detail);
      if (svc && evSvc !== svc) return false;
      if (q) {
        var hay = [
          e.action || "",
          AUDIT_ACTION_TR[e.action] || "",
          formatAuditDescription(e.action, e.detail),
          auditServiceName(evSvc)
        ].join(" ").toLowerCase();
        if (hay.indexOf(q) < 0) return false;
      }
      return true;
    });
  }

  function updateAuditStats(list) {
    var counts = { servis: 0, olay: 0, uyari: 0, export: 0 };
    (list || []).forEach(function (e) {
      var cat = auditCategory(e.action);
      if (counts[cat] != null) counts[cat] += 1;
    });
    setTextIfChanged(qs("#audit-stat-service"), counts.servis);
    setTextIfChanged(qs("#audit-stat-issue"), counts.olay);
    setTextIfChanged(qs("#audit-stat-alert"), counts.uyari);
    setTextIfChanged(qs("#audit-stat-export"), counts.export);
  }

  function auditFingerprint(list) {
    return (list || []).map(function (e) {
      return (e.ts || "") + "\t" + (e.action || "") + "\t" + JSON.stringify(e.detail || {});
    }).join("\n");
  }

  function renderAuditTable(list, isBackup) {
    isBackup = !!isBackup;
    var tbody = qs("#audit-list");
    var emptyEl = qs("#audit-empty");
    var tableWrap = qs(".audit-table-wrap");
    if (!tbody) return;
    tbody.innerHTML = "";
    list.forEach(function (e, idx) {
      var cat = isBackup ? "yedek" : auditCategory(e.action);
      var actionLabel = AUDIT_ACTION_TR[e.action] || e.action || "—";
      var desc = formatAuditDescription(e.action, e.detail);
      var evSvc = auditEventService(e.action, e.detail);
      var svcLabel = evSvc ? auditServiceName(evSvc) : "—";
      var trMain = document.createElement("tr");
      trMain.className = "audit-row-main" + (isBackup ? " audit-row-backup" : "");
      trMain.setAttribute("data-audit-idx", String(idx));
      trMain.innerHTML =
        "<td class=\"audit-ts\">" + escHtml(formatAuditTs(e.ts || e._backup_at)) + "</td>" +
        "<td>" + auditCategoryPill(cat) + "</td>" +
        "<td class=\"audit-action-label\">" + escHtml(actionLabel) + "</td>" +
        "<td class=\"audit-desc\">" + escHtml(desc) + "</td>" +
        "<td class=\"audit-service\">" + escHtml(svcLabel) + "</td>";
      trMain.addEventListener("click", function () {
        var detailRow = trMain.nextElementSibling;
        var open = trMain.classList.toggle("expanded");
        if (detailRow && detailRow.classList.contains("audit-row-detail")) {
          detailRow.classList.toggle("hidden", !open);
        }
      });
      tbody.appendChild(trMain);
      var trDetail = document.createElement("tr");
      trDetail.className = "audit-row-detail hidden";
      trDetail.innerHTML = "<td colspan=\"5\"><pre>" + escHtml(JSON.stringify({ action: e.action, detail: e.detail || {} }, null, 2)) + "</pre></td>";
      tbody.appendChild(trDetail);
    });
    if (emptyEl) {
      emptyEl.textContent = isBackup ? "Yerel yedekte denetim kaydı yok." : "Bu filtrede denetim kaydı yok.";
      emptyEl.classList.toggle("hidden", list.length > 0);
    }
    if (tableWrap) tableWrap.classList.toggle("hidden", list.length === 0);
  }

  async function refreshAuditFootnote() {
    try {
      var stats = await fetch(API + "/api/audit/summary").then(function (r) { return r.ok ? r.json() : {}; }).catch(function () { return {}; });
      var el = qs("#audit-footnote");
      if (!el) return;
      var backup = stats.backup != null ? stats.backup : 0;
      var max = stats.max_active != null ? stats.max_active : 300;
      el.innerHTML = "En fazla " + max + " kayıt bellekte · yerel yedek: <strong>" + backup + "</strong> · taşanlar <code>.run/audit_archive.jsonl</code> dosyasında";
    } catch (_) {}
  }

  async function refreshAudit(force) {
    try {
      var isBackup = auditView === "BACKUP";
      var list = [];
      if (isBackup) {
        var archiveData = await fetch(API + "/api/audit/archive" + buildAuditArchiveQuery())
          .then(function (r) { return r.ok ? r.json() : { items: [] }; })
          .catch(function () { return { items: [] }; });
        list = (archiveData.items || []).slice().reverse();
      } else {
        list = await fetch(API + "/api/audit?limit=300").then(function (r) { return r.ok ? r.json() : []; }).catch(function () { return []; });
        list = (list || []).slice().reverse();
      }
      var fp = auditFingerprint(list) + "|view:" + auditView;
      if (!force && fp === lastAuditFingerprint) return;
      lastAuditFingerprint = fp;
      auditEventsCache = list;
      if (!isBackup) updateAuditStats(list);
      renderAuditTable(filterAuditEvents(list), isBackup);
      refreshAuditFootnote();
    } catch (e) { console.error(e); }
  }

  function startAuditPoll() {
    stopAuditPoll();
    auditPollTimer = setInterval(function () {
      if (document.hidden) return;
      var panel = qs("#panel-audit");
      if (!panel || !panel.classList.contains("active")) return;
      refreshAudit(false);
    }, 5000);
  }

  function stopAuditPoll() {
    if (auditPollTimer) { clearInterval(auditPollTimer); auditPollTimer = null; }
  }

  function applyAuditFilters() {
    renderAuditTable(filterAuditEvents(auditEventsCache), auditView === "BACKUP");
  }

  const VALID_TABS = ["overview", "web", "engine", "manager", "html", "security", "incidents", "audit", "settings"];
  function switchToTab(tab) {
    if (!tab || VALID_TABS.indexOf(tab) < 0) return;
    qsa(".nav-item").forEach(x => {
      x.classList.toggle("active", x.getAttribute("data-tab") === tab);
    });
    qsa(".tab-panel").forEach(x => {
      x.classList.toggle("active", x.id === "panel-" + tab);
    });
    if (securityPollIntervalId) { clearInterval(securityPollIntervalId); securityPollIntervalId = null; }
    if (tab === "overview") { refreshMetrics(); refreshDiagnosis(); }
    if (tab === "web") { refreshMetrics(); fetchLogs("web"); }
    if (tab === "engine") { refreshMetrics(); fetchLogs("engine"); }
    if (tab === "manager") { refreshMetrics(); fetchLogs("manager"); }
    if (tab === "html") { refreshStatus(); fetchLogs("html"); }
    if (tab === "security") {
      refreshSecurity();
      securityPollIntervalId = setInterval(refreshSecurity, 1500);
    }
    if (tab === "incidents") { refreshIssues(true); startIncidentsPoll(); } else { stopIncidentsPoll(); }
    if (tab === "audit") { refreshAudit(true); startAuditPoll(); } else { stopAuditPoll(); }
    if (tab === "web" || tab === "engine" || tab === "manager") refreshDiagnosis();
    if (tab === "settings") loadSettings();
  }
  qsa(".nav-item").forEach(n => {
    n.addEventListener("click", function (e) {
      e.preventDefault();
      const tab = this.getAttribute("data-tab");
      switchToTab(tab);
      try { localStorage.setItem("manager_active_tab", tab); } catch (_) {}
    });
  });
  document.body.addEventListener("click", function (e) {
    var tabLinkCard = e.target && e.target.closest && e.target.closest("[data-tab-link]");
    if (tabLinkCard) {
      e.preventDefault();
      var tabFromCard = tabLinkCard.getAttribute("data-tab-link");
      if (tabFromCard) { switchToTab(tabFromCard); try { localStorage.setItem("manager_active_tab", tabFromCard); } catch (_) {} }
      return;
    }
    var link = e.target && e.target.closest && e.target.closest(".link-tab");
    if (link) {
      e.preventDefault();
      var tab = link.getAttribute("data-tab");
      if (tab) { switchToTab(tab); try { localStorage.setItem("manager_active_tab", tab); } catch (_) {} }
    }
  });

  const pollSelect = qs("#setting-poll-interval");
  if (pollSelect) pollSelect.addEventListener("change", function () {
    pollIntervalMs = parseInt(this.value, 10) || 2000;
    if (metricsIntervalId) clearInterval(metricsIntervalId);
    metricsIntervalId = setInterval(refreshMetrics, pollIntervalMs);
    saveSettings();
  });
  const logMaxInput = qs("#setting-log-max-lines");
  if (logMaxInput) logMaxInput.addEventListener("change", function () { logMaxLines = Math.max(100, Math.min(2000, parseInt(this.value, 10) || 1000)); saveSettings(); });
  const wsEventsCb = qs("#setting-ws-events");
  if (wsEventsCb) {
    wsEventsCb.addEventListener("change", function () {
      useWsEvents = wsEventsCb.checked;
      saveSettings();
      if (useWsEvents) { keys.forEach(k => { if (ws[k]) try { ws[k].close(); } catch (_) {} ws[k] = null; }); connectWsEvents(); }
      else { if (wsEvents) try { wsEvents.close(); } catch (_) {} wsEvents = null; keys.forEach(k => connectWs(k)); }
    });
  }

  function applyAutoscrollFromSetting() {
    var cb = qs("#setting-autoscroll");
    var on = cb ? cb.checked : true;
    autoscroll.web = on;
    autoscroll.engine = on;
    autoscroll.manager = on;
    keys.forEach(function (k) {
      var el = qs("#autoscroll-" + k);
      if (el) el.checked = on;
    });
  }
  qsa("input[name=theme]").forEach(function (r) {
    r.addEventListener("change", function () {
      document.body.classList.remove("theme-dark", "theme-light");
      document.body.classList.add("theme-" + this.value);
      saveSettings();
    });
  });

  qsa(".audit-view-tab").forEach(function (btn) {
    btn.addEventListener("click", function () {
      auditView = btn.getAttribute("data-audit-view") || "";
      qsa(".audit-view-tab").forEach(function (b) { b.classList.toggle("active", b === btn); });
      lastAuditFingerprint = "";
      refreshAudit(true);
    });
  });
  if (qs("#audit-filter-service")) qs("#audit-filter-service").addEventListener("change", function () {
    if (auditView === "BACKUP") { lastAuditFingerprint = ""; refreshAudit(true); }
    else applyAuditFilters();
  });
  if (qs("#audit-search")) qs("#audit-search").addEventListener("input", function () {
    clearTimeout(auditSearchTimer);
    auditSearchTimer = setTimeout(function () {
      if (auditView === "BACKUP") { lastAuditFingerprint = ""; refreshAudit(true); }
      else applyAuditFilters();
    }, 300);
  });
  if (qs("#audit-refresh-btn")) qs("#audit-refresh-btn").addEventListener("click", function () { lastAuditFingerprint = ""; refreshAudit(true); });
  qsa(".audit-stat-card[data-audit-cat]").forEach(function (card) {
    card.addEventListener("click", function () {
      var cat = card.getAttribute("data-audit-cat") || "";
      auditView = cat;
      qsa(".audit-view-tab").forEach(function (b) {
        b.classList.toggle("active", (b.getAttribute("data-audit-view") || "") === cat);
      });
      applyAuditFilters();
    });
  });

  qsa(".inc-view-tab").forEach(function (btn) {
    btn.addEventListener("click", function () {
      incidentsView = btn.getAttribute("data-inc-view") || "";
      qsa(".inc-view-tab").forEach(function (b) { b.classList.toggle("active", b === btn); });
      lastIssuesFingerprint = "";
      refreshIssues(true);
    });
  });
  if (qs("#incidents-filter-service")) qs("#incidents-filter-service").addEventListener("change", function () { lastIssuesFingerprint = ""; refreshIssues(true); });
  if (qs("#incidents-search")) qs("#incidents-search").addEventListener("input", function () {
    clearTimeout(incidentsSearchTimer);
    incidentsSearchTimer = setTimeout(function () { lastIssuesFingerprint = ""; refreshIssues(true); }, 300);
  });
  if (qs("#incidents-refresh-btn")) qs("#incidents-refresh-btn").addEventListener("click", function () { refreshIssues(true); });

  qsa(".inc-stat-card").forEach(function (card) {
    card.addEventListener("click", function () {
      var view = card.getAttribute("data-inc-view") || "";
      if (!view) {
        if (card.classList.contains("inc-stat-open")) view = "OPEN";
        else if (card.classList.contains("inc-stat-ack")) view = "ACK";
        else if (card.classList.contains("inc-stat-resolved")) view = "RESOLVED";
      }
      if (!view) return;
      incidentsView = view;
      qsa(".inc-view-tab").forEach(function (b) {
        b.classList.toggle("active", (b.getAttribute("data-inc-view") || "") === view);
      });
      lastIssuesFingerprint = "";
      refreshIssues(true);
    });
  });

  let settingsSaveTimer = null;
  function flashSettingsSaved() {
    var badge = qs("#settings-save-status");
    if (!badge) return;
    badge.textContent = "Kaydedildi";
    badge.classList.remove("pending");
    if (settingsSaveTimer) clearTimeout(settingsSaveTimer);
    settingsSaveTimer = setTimeout(function () {
      badge.textContent = "Kaydedildi";
    }, 1200);
  }
  function markSettingsPending() {
    var badge = qs("#settings-save-status");
    if (badge) { badge.textContent = "Kaydediliyor…"; badge.classList.add("pending"); }
  }

  function loadSettings() {
    try {
      const raw = localStorage.getItem("manager_settings");
      if (raw) {
        const s = JSON.parse(raw);
        if (s.pollIntervalMs) { pollIntervalMs = s.pollIntervalMs; const sel = qs("#setting-poll-interval"); if (sel) sel.value = String(pollIntervalMs); }
        if (s.logMaxLines) { logMaxLines = s.logMaxLines; const inp = qs("#setting-log-max-lines"); if (inp) inp.value = s.logMaxLines; }
        if (s.sound !== undefined) { const cb = qs("#setting-sound"); if (cb) cb.checked = !!s.sound; }
        if (s.compact !== undefined) { const cb = qs("#setting-compact"); if (cb) cb.checked = !!s.compact; document.body.classList.toggle("compact-mode", !!s.compact); }
        if (s.useWsEvents !== undefined) { useWsEvents = s.useWsEvents; const cb = qs("#setting-ws-events"); if (cb) cb.checked = s.useWsEvents; }
        if (s.theme === "light" || s.theme === "dark") {
          document.body.classList.remove("theme-dark", "theme-light");
          document.body.classList.add("theme-" + s.theme);
          qsa("input[name=theme]").forEach(function (r) { r.checked = r.value === s.theme; });
        }
        if (s.thresh5xx != null) { const inp = qs("#setting-thresh-5xx"); if (inp) inp.value = s.thresh5xx; }
        if (s.threshTick != null) { const inp = qs("#setting-thresh-tick"); if (inp) inp.value = s.threshTick; }
        if (s.threshLogin != null) { const inp = qs("#setting-thresh-login"); if (inp) inp.value = s.threshLogin; }
        if (s.autoscroll !== undefined) { const cb = qs("#setting-autoscroll"); if (cb) cb.checked = !!s.autoscroll; applyAutoscrollFromSetting(); }
      }
      if (!qs("#setting-autoscroll") || !raw) applyAutoscrollFromSetting();
      flashSettingsSaved();
    } catch (_) {}
  }
  function saveSettings() {
    markSettingsPending();
    try {
      const themeEl = document.querySelector("input[name=theme]:checked");
      const s = {
        pollIntervalMs,
        logMaxLines,
        sound: qs("#setting-sound") ? qs("#setting-sound").checked : false,
        compact: qs("#setting-compact") ? qs("#setting-compact").checked : false,
        useWsEvents: qs("#setting-ws-events") ? qs("#setting-ws-events").checked : true,
        theme: themeEl ? themeEl.value : "dark",
        thresh5xx: parseFloat((qs("#setting-thresh-5xx") && qs("#setting-thresh-5xx").value)) || 5,
        threshTick: parseInt((qs("#setting-thresh-tick") && qs("#setting-thresh-tick").value), 10) || 60,
        threshLogin: parseInt((qs("#setting-thresh-login") && qs("#setting-thresh-login").value), 10) || 10,
        autoscroll: qs("#setting-autoscroll") ? qs("#setting-autoscroll").checked : true,
      };
      localStorage.setItem("manager_settings", JSON.stringify(s));
      flashSettingsSaved();
    } catch (_) {}
  }
  function setDefaults() {
    const sel = qs("#setting-poll-interval"); if (sel) sel.value = "2000";
    const logInp = qs("#setting-log-max-lines"); if (logInp) logInp.value = "1000";
    const soundCb = qs("#setting-sound"); if (soundCb) soundCb.checked = false;
    const compactCb = qs("#setting-compact"); if (compactCb) compactCb.checked = false;
    const wsCb = qs("#setting-ws-events"); if (wsCb) wsCb.checked = true;
    qsa("input[name=theme]").forEach(function (r) { r.checked = r.value === "dark"; });
    document.body.classList.remove("theme-light"); document.body.classList.add("theme-dark");
    const thresh5 = qs("#setting-thresh-5xx"); if (thresh5) thresh5.value = "5";
    const threshT = qs("#setting-thresh-tick"); if (threshT) threshT.value = "60";
    const threshL = qs("#setting-thresh-login"); if (threshL) threshL.value = "10";
    const autoCb = qs("#setting-autoscroll"); if (autoCb) autoCb.checked = true;
    pollIntervalMs = 2000;
    logMaxLines = 1000;
    useWsEvents = true;
    document.body.classList.remove("compact-mode");
    applyAutoscrollFromSetting();
    if (metricsIntervalId) clearInterval(metricsIntervalId);
    metricsIntervalId = setInterval(refreshMetrics, pollIntervalMs);
    saveSettings();
  }
  loadSettings();

  try {
    const savedTab = localStorage.getItem("manager_active_tab");
    if (savedTab && VALID_TABS.indexOf(savedTab) >= 0) switchToTab(savedTab);
  } catch (_) {}

  qsa(".btn-export").forEach(btn => {
    btn.addEventListener("click", function () {
      const kind = this.getAttribute("data-export");
      const base = API + "/api/export/";
      const format = "csv";
      let url = "";
      if (kind === "metrics") url = base + "metrics?format=" + format;
      else if (kind === "issues") {
        var parts = ["format=" + format];
        if (incidentsView) parts.push("status=" + encodeURIComponent(incidentsView));
        var svcEl = qs("#incidents-filter-service");
        if (svcEl && svcEl.value) parts.push("service=" + encodeURIComponent(svcEl.value));
        url = base + "issues?" + parts.join("&");
      }
      else if (kind === "audit") url = base + "audit?format=" + format;
      else if (kind === "security") url = base + "security?format=" + format;
      else if (kind === "logs-web") url = base + "logs?service=web&tail=1000&format=" + format;
      else if (kind === "logs-engine") url = base + "logs?service=engine&tail=1000&format=" + format;
      else if (kind === "logs-manager") url = base + "logs?service=manager&tail=1000&format=" + format;
      else if (kind === "logs-html") url = base + "logs?service=html&tail=1000&format=" + format;
      else if (kind === "alerts") url = base + "alerts?format=" + format;
      else if (kind === "diagnosis-web") url = base + "diagnosis?service=web&format=json";
      else if (kind === "diagnosis-engine") url = base + "diagnosis?service=engine&format=json";
      else if (kind === "diagnosis-manager") url = base + "diagnosis?service=manager&format=json";
      if (url) window.open(url, "_blank");
    });
  });

  if (qs("#setting-sound")) qs("#setting-sound").addEventListener("change", saveSettings);
  if (qs("#setting-compact")) qs("#setting-compact").addEventListener("change", function () { document.body.classList.toggle("compact-mode", this.checked); saveSettings(); });
  var autoScrollSetting = qs("#setting-autoscroll");
  if (autoScrollSetting) autoScrollSetting.addEventListener("change", function () { applyAutoscrollFromSetting(); saveSettings(); });
  var resetDefaultsBtn = qs("#setting-reset-defaults");
  if (resetDefaultsBtn) resetDefaultsBtn.addEventListener("click", setDefaults);
  ["#setting-thresh-5xx", "#setting-thresh-tick", "#setting-thresh-login"].forEach(function (id) {
    var el = qs(id);
    if (el) el.addEventListener("change", saveSettings);
  });

  keys.forEach(k => {
    const lockCb = qs("#lock-" + k);
    if (lockCb) lockCb.addEventListener("change", function () {
      api("POST", "/api/locks", { web: k === "web" ? lockCb.checked : qs("#lock-web").checked, engine: k === "engine" ? lockCb.checked : qs("#lock-engine").checked }).then(refreshStatus);
    });
    if (k !== "manager" && k !== "html") {
      var panelBtnIds = k === "web" ? ["btnWebStart", "btnWebStop", "btnWebRestart"] : ["btnEngineStart", "btnEngineStop", "btnEngineRestart"];
      ["Start", "Stop", "Restart"].forEach(action => {
        const btn = qs("#btn" + (k === "web" ? "Web" : "Engine") + action);
        if (btn) btn.addEventListener("click", function () {
          if (btn.disabled) return;
          setButtonsLoading(panelBtnIds, true);
          api("POST", "/api/server/" + k + "/" + action.toLowerCase())
            .then(function (r) {
              refreshStatus();
              refreshMetrics();
              if (r.diagnosis) {
                renderDiagnosis(r.service, r.diagnosis, r.status && r.status[r.service] && r.status[r.service].running);
                if (!r.ok || r.action === "stop") showDiagnosisToast(r.diagnosis);
              }
              refreshDiagnosis();
              showActionFeedback(k + " " + action.toLowerCase() + " tamam.", false);
            })
            .catch(function (e) {
              showActionFeedback("Hata: " + (e.message || String(e)), true);
              alert(e.message || String(e));
            })
            .finally(function () {
              setButtonsLoading(panelBtnIds, false);
              refreshStatus();
              refreshMetrics();
            });
        });
      });
    }
    const resetBtn = k === "manager" ? qs("#btnManagerReset") : k === "html" ? qs("#btnHtmlReset") : qs("#btn" + (k === "web" ? "Web" : "Engine") + "Reset");
    if (resetBtn) resetBtn.addEventListener("click", function () {
      api("POST", "/api/reset/" + k).then(() => { fetchLogs(k); refreshStatus(); refreshMetrics(); }).catch(e => alert(e.message));
    });
    const pauseCb = qs("#pause-" + k);
    if (pauseCb) pauseCb.addEventListener("change", function () { pause[k] = pauseCb.checked; });
    const autoscrollCb = qs("#autoscroll-" + k);
    if (autoscrollCb) autoscrollCb.addEventListener("change", function () { autoscroll[k] = autoscrollCb.checked; });
    const filterSel = qs("#filter-level-" + k);
    if (filterSel) filterSel.addEventListener("change", function () { filterLevel[k] = filterSel.value; renderLog(k); });
    const searchInp = qs("#search-" + k);
    if (searchInp) searchInp.addEventListener("input", function () { searchQuery[k] = searchInp.value; renderLog(k); });
    ["log-" + k, "err-" + k, "wrn-" + k].forEach(id => {
      const copyBtn = qsa("[data-copy=" + id + "]")[0];
      if (copyBtn) copyBtn.addEventListener("click", function () {
        const el = document.getElementById(id);
        if (el) navigator.clipboard.writeText(el.textContent).then(() => {}).catch(() => {});
      });
    });
  });

  function runHtmlAction(action, label) {
    var ids = ["btnHtmlStart", "btnHtmlStop", "btn-html-start", "btn-html-stop"];
    setButtonsLoading(ids.filter(function (id) { return qs("#" + id); }), true);
    showActionFeedback(label + " isleniyor...", false);
    api("POST", "/api/server/html/" + action)
      .then(function () {
        refreshStatus();
        refreshMetrics();
        showActionFeedback("HTML " + label + " tamam.", false);
      })
      .catch(function (e) {
        showActionFeedback("Hata: " + (e.message || String(e)), true);
        alert(e.message || String(e));
      })
      .finally(function () {
        setButtonsLoading(ids.filter(function (id) { return qs("#" + id); }), false);
        refreshStatus();
        refreshMetrics();
      });
  }
  function htmlStart() { runHtmlAction("start", "baslat"); }
  function htmlStop() { runHtmlAction("stop", "durdur"); }
  var btnHtmlStart = qs("#btn-html-start"); if (btnHtmlStart) btnHtmlStart.addEventListener("click", htmlStart);
  var btnHtmlStop = qs("#btn-html-stop"); if (btnHtmlStop) btnHtmlStop.addEventListener("click", htmlStop);
  var btnHtmlStartPanel = qs("#btnHtmlStart"); if (btnHtmlStartPanel) btnHtmlStartPanel.addEventListener("click", htmlStart);
  var btnHtmlStopPanel = qs("#btnHtmlStop"); if (btnHtmlStopPanel) btnHtmlStopPanel.addEventListener("click", htmlStop);

  var globalBtnIds = ["btnGlobalStart", "btnGlobalStop", "btnGlobalRestart"];
  function disableGlobalBtns(disabled) {
    setButtonsLoading(globalBtnIds, disabled);
  }
  function runGlobalAction(path, label) {
    if (qs("#btnGlobalStart").disabled) return;
    disableGlobalBtns(true);
    showActionFeedback(label + " isleniyor...", false);
    api("POST", path)
      .then(function (r) {
        var applied = (r.applied || []).join(", ") || "—";
        var skipped = (r.skipped || []).join(", ") || "—";
        showActionFeedback("Uygulandi: " + applied + (skipped ? "; Atlandi: " + skipped : ""), false);
      })
      .catch(function (e) {
        showActionFeedback("Hata: " + (e.message || String(e)), true);
        alert(e.message || String(e));
      })
      .finally(function () {
        disableGlobalBtns(false);
        refreshStatus();
        refreshMetrics();
      });
  }
  qs("#btnGlobalStart").addEventListener("click", function () { runGlobalAction("/api/global/start", "Tumunu baslat"); });
  qs("#btnGlobalStop").addEventListener("click", function () { runGlobalAction("/api/global/stop", "Tumunu durdur"); });
  qs("#btnGlobalRestart").addEventListener("click", function () { runGlobalAction("/api/global/restart", "Tumunu yeniden baslat"); });
  qs("#btnResetAll").addEventListener("click", function () {
    api("POST", "/api/reset/all").then(() => { keys.forEach(fetchLogs); refreshStatus(); refreshMetrics(); }).catch(e => alert(e.message));
  });

  refreshStatus();
  refreshMetrics();
  refreshDiagnosis();
  refreshIssues();
  var initIncidentsPanel = qs("#panel-incidents");
  if (initIncidentsPanel && initIncidentsPanel.classList.contains("active")) startIncidentsPoll();
  keys.forEach(k => fetchLogs(k));
  useWsEvents = wsEventsCb && wsEventsCb.checked;
  if (useWsEvents) connectWsEvents(); else keys.forEach(k => connectWs(k));
  setInterval(refreshStatus, 5000);
  metricsIntervalId = setInterval(refreshMetrics, pollIntervalMs);
  setInterval(function () {
    if (!lastMetrics || !lastMetrics.status) return;
    keys.forEach(function (k) {
      setStatus(k, lastMetrics.status[k] || {});
    });
    var h = lastMetrics.status.html;
    if (h && h.running && typeof h.started_at === "number") {
      var htmlUptime = Math.max(0, Math.floor(Date.now() / 1000 - h.started_at));
      setTextIfChanged(qs("#overview-html-uptime"), formatUptime(htmlUptime) || "—");
    }
    var mgr = lastMetrics.status.manager;
    if (mgr && mgr.running) {
      setTextIfChanged(qs("#overview-manager-uptime"), formatUptime(getLiveUptime("manager")) || "—");
    }
  }, 1000);
})();
