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
  let filterLevel = { web: "WARN+", engine: "WARN+", manager: "WARN+", html: "WARN+" };
  let searchQuery = { web: "", engine: "", manager: "", html: "" };
  let autoscroll = { web: true, engine: true, manager: true, html: true };
  const TOAST_QUEUE_MAX = 10;
  const TOAST_DISMISS_MS = 10000;
  const TOAST_SAME_ERROR_COOLDOWN_MS = 600000; // Aynı kritik hata 10 dk'da en fazla 1 kere
  const DIAGNOSIS_COOLDOWN_MS = 600000;        // Aynı teşhis 10 dk'da en fazla 1 kere
  let toastQueue = [];
  let toastCooldown = {};          // "level:messageKey" -> timestamp (aynı hata tekrar gelmesin)
  let lastMetricsReceivedAt = 0;
  let diagnosisToastCooldown = {}; // "service:reason_code" -> timestamp
  let lastDiagnosis = {};          // key -> diagnosis object

  function dismissToast(el) {
    if (el && el.dataset && el.dataset.alertId) {
      fetch(API + "/api/alerts/ack", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: el.dataset.alertId }) }).catch(function () {});
    }
    if (el && el.parentNode) el.parentNode.removeChild(el);
    const i = toastQueue.indexOf(el);
    if (i >= 0) toastQueue.splice(i, 1);
  }

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

  function setHealthBadgeIfChanged(el, text, className) {
    if (!el) return;
    var s = (text == null || text === undefined) ? "" : String(text);
    if (el.textContent !== s) el.textContent = s;
    if (el.className !== className) el.className = className;
  }

  function updateMetricsUI(m) {
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
    if (progressCpu) { progressCpu.style.width = Math.min(100, cpuPct) + "%"; progressCpu.className = "progress-fill" + (cpuPct > 90 ? " crit" : cpuPct > 70 ? " warn" : ""); }
    const progressRam = qs("#progress-ram");
    if (progressRam) { progressRam.style.width = Math.min(100, ramPct) + "%"; progressRam.className = "progress-fill" + (ramPct > 90 ? " crit" : ramPct > 70 ? " warn" : ""); }
    const progressDisk = qs("#progress-disk");
    if (progressDisk) { progressDisk.style.width = Math.min(100, diskPct) + "%"; progressDisk.className = "progress-fill" + (diskPct > 90 ? " crit" : diskPct > 70 ? " warn" : ""); }

    setTextIfChanged(qs("#overview-manager-port"), "7999");
    var mgrRunning = m.status && m.status.manager && m.status.manager.running;
    var mgrStatus = qs("#overview-manager-status");
    if (mgrStatus) { mgrStatus.textContent = mgrRunning ? "ÇALIŞIYOR" : "—"; mgrStatus.className = "status-chip " + (mgrRunning ? "running" : "stopped"); }
    var d = m.status && m.status.manager ? m.status.manager : {};
    var liveMgrUptime = (d.running && m.manager) ? getLiveUptime("manager") : (m.manager ? m.manager.uptime_s : null);
    el("#overview-manager-pid", d.pid != null ? String(d.pid) : "—");
    el("#overview-manager-uptime", formatUptime(liveMgrUptime) || "—");
    el("#overview-manager-resource", [m.manager && m.manager.cpu_pct != null ? m.manager.cpu_pct + "% CPU" : null, m.manager && m.manager.rss_mb != null ? m.manager.rss_mb + " MB" : null].filter(Boolean).join(" · ") || "—");

    const webProc = m.web || {};
    const webApp = m.web_app || {};
    const webRunning = (m.status && m.status.web && m.status.web.running);
    setTextIfChanged(qs("#overview-web-port"), "8000");
    const overviewWebChip = qs("#overview-web-status");
    if (overviewWebChip) { overviewWebChip.textContent = webRunning ? "ÇALIŞIYOR" : "DURDURULDU"; overviewWebChip.className = "status-chip " + (webRunning ? "running" : "stopped"); }
    el("#overview-web-reqmin", webApp.requests_per_min != null ? webApp.requests_per_min : "—");
    el("#overview-web-error-rate", webApp.error_rate != null ? (webApp.error_rate * 100).toFixed(2) + "%" : "—");
    el("#overview-web-p95", webApp.latency_p95_ms != null ? webApp.latency_p95_ms + " ms" : "—");
    setTextIfChanged(qs("#overview-web-err-wrn"), errWeb.length + " / " + wrnWeb.length);

    const engProc = m.engine || {};
    const engApp = m.engine_app || {};
    const engRunning = (m.status && m.status.engine && m.status.engine.running);
    setTextIfChanged(qs("#overview-engine-port"), "—");
    const overviewEngChip = qs("#overview-engine-status");
    if (overviewEngChip) { overviewEngChip.textContent = engRunning ? "ÇALIŞIYOR" : "DURDURULDU"; overviewEngChip.className = "status-chip " + (engRunning ? "running" : "stopped"); }
    el("#overview-engine-bots", engApp.active_bots != null ? engApp.active_bots : "—");
    el("#overview-engine-tick", engApp.tick_rate_10s != null ? engApp.tick_rate_10s : "—");
    el("#overview-engine-tick-age", engApp.last_tick_age_s != null ? engApp.last_tick_age_s + " sn" : "—");
    setTextIfChanged(qs("#overview-engine-err-wrn"), errEng.length + " / " + wrnEng.length);

    var htmlStatus = m.status && m.status.html ? m.status.html : {};
    var htmlChip = qs("#overview-html-status");
    if (htmlChip) { htmlChip.textContent = htmlStatus.running ? "ÇALIŞIYOR" : "DURDURULDU"; htmlChip.className = "status-chip " + (htmlStatus.running ? "running" : "stopped"); }
    setTextIfChanged(qs("#overview-html-port"), "8080");
    el("#overview-html-pid", htmlStatus.pid != null ? String(htmlStatus.pid) : "—");
    var htmlUptime = (typeof htmlStatus.started_at === "number") ? Math.max(0, Math.floor(Date.now() / 1000 - htmlStatus.started_at)) : null;
    el("#overview-html-uptime", formatUptime(htmlUptime) || "—");

    const total = webApp.request_total || 0;
    const bad = webApp.status_5xx || 0;
    const availability = total > 0 ? ((total - bad) / total * 100) : 100;
    const sloBar = qs("#slo-bar");
    if (sloBar) {
      sloBar.style.width = Math.min(100, availability) + "%";
      sloBar.className = "slo-bar " + (availability >= 99.9 ? "ok" : availability >= 99 ? "warn" : "crit");
    }
    el("#slo-text", "Erişilebilirlik: " + availability.toFixed(2) + "% (hedef 99.9%) | 5xx: " + bad);

    const alertsPre = qs("#overview-alerts");
    if (alertsPre) {
      const lines = [];
      errWeb.slice(-5).forEach(function (l) { lines.push("Web · Hata: " + (l || "")); });
      wrnWeb.slice(-5).forEach(function (l) { lines.push("Web · Uyarı: " + (l || "")); });
      errEng.slice(-5).forEach(function (l) { lines.push("Motor · Hata: " + (l || "")); });
      wrnEng.slice(-5).forEach(function (l) { lines.push("Motor · Uyarı: " + (l || "")); });
      errMgr.slice(-3).forEach(function (l) { lines.push("Yönetici · Hata: " + (l || "")); });
      wrnMgr.slice(-3).forEach(function (l) { lines.push("Yönetici · Uyarı: " + (l || "")); });
      var alertsText = lines.length ? lines.join("\n") : "Son hata veya uyarı yok.";
      setTextIfChanged(alertsPre, alertsText);
    }

    setTextIfChanged(qs("#overview-errors-summary"), "Web: " + errWeb.length + ", Motor: " + errEng.length + ", Yönetici: " + errMgr.length);
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
    if (loginPre) loginPre.textContent = loginFails.length
      ? formatLoginFails(loginFails)
      : "Başarısız giriş yok.";
    const ipsPre = qs("#security-top-ips");
    if (ipsPre) ipsPre.textContent = topIps.length
      ? topIps.map(x => (x.ip || "") + " " + (x.count || 0)).join("\n")
      : "IP verisi yok.";
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
      var reason = f.reason ? f.reason : "—";
      return "Tarih: " + ts + "\nIP: " + ip + "\nKullanıcı: " + user + "\nSebep: " + reason;
    }).join("\n\n");
  }

  async function refreshSecurity() {
    try {
      const traffic = await fetch(API + "/api/traffic").then(r => r.ok ? r.json() : {}).catch(function () { return {}; });
      const loginFails = traffic.last_login_fails || [];
      const topIps = traffic.top_ips || [];
      const loginPre = qs("#security-login-fails");
      if (loginPre) loginPre.textContent = loginFails.length
        ? formatLoginFails(loginFails)
        : "Başarısız giriş yok.";
      const ipsPre = qs("#security-top-ips");
      if (ipsPre) ipsPre.textContent = topIps.length
        ? topIps.map(function (x) { return (x.ip || "") + " " + (x.count || 0); }).join("\n")
        : "IP verisi yok.";
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
        const [errWeb, errEng, errMgr] = await Promise.all([
          fetch(API + "/api/logs/web?tail=0").then(r => r.ok ? r.json() : {}).catch(() => ({})),
          fetch(API + "/api/logs/engine?tail=0").then(r => r.ok ? r.json() : {}).catch(() => ({})),
          fetch(API + "/api/logs/manager?tail=0").then(r => r.ok ? r.json() : {}).catch(() => ({}))
        ]);
        metrics.errors_ring = { web: (errWeb.errors || []), engine: (errEng.errors || []), manager: (errMgr.errors || []) };
        metrics.warns_ring = { web: (errWeb.warns || []), engine: (errEng.warns || []), manager: (errMgr.warns || []) };
        updateMetricsUI(metrics);
      }
      keys.forEach(k => setStatus(k, status[k]));
      const [issues, audit] = await Promise.all([
        fetch(API + "/api/issues?status=OPEN").then(r => r.ok ? r.json() : []).catch(() => []),
        fetch(API + "/api/audit?limit=200").then(r => r.ok ? r.json() : []).catch(() => [])
      ]);
      setTextIfChanged(qs("#overview-issue-count"), issues.length);
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

  async function refreshIssues() {
    const openOnly = qs("#incidents-filter-open") ? qs("#incidents-filter-open").checked : false;
    const url = API + "/api/issues" + (openOnly ? "?status=OPEN" : "");
    const list = await fetch(url).then(r => r.ok ? r.json() : []).catch(() => []);
    const tbody = qs("#incidents-list");
    const emptyEl = qs("#incidents-empty");
    const tableWrap = tbody && tbody.closest(".incidents-table-wrap");
    if (!tbody) return;
    tbody.innerHTML = "";
    list.forEach(function (issue) {
      const tr = document.createElement("tr");
      tr.className = "incident-row incident-row-" + (issue.status || "open").toLowerCase();
      const service = (issue.tags && issue.tags.service) ? issue.tags.service : "—";
      tr.innerHTML =
        "<td class=\"incident-id\">" + (issue.id || "—") + "</td>" +
        "<td class=\"incident-severity\"><span class=\"severity-badge severity-" + (issue.severity || "").toLowerCase() + "\">" + (issue.severity || "—") + "</span></td>" +
        "<td class=\"incident-service\">" + service + "</td>" +
        "<td class=\"incident-count\">" + (issue.count != null ? issue.count : "—") + "</td>" +
        "<td class=\"incident-last\">" + formatIssueLastSeen(issue.last_seen) + "</td>" +
        "<td class=\"incident-status\">" + (issue.status || "OPEN") + "</td>";
      tr.addEventListener("click", function () { openDrawer(issue); });
      tbody.appendChild(tr);
    });
    if (emptyEl) emptyEl.classList.toggle("hidden", list.length > 0);
    if (tableWrap) tableWrap.classList.toggle("hidden", list.length === 0);
  }

  function showToast(message, level, kind, alertId) {
    if (!qs("#setting-toast") || !qs("#setting-toast").checked) return;
    var container = qs("#toast-container");
    if (!container) return;
    var cooldownKey = (level || "WARN") + ":" + (kind || (message || "").substring(0, 120));
    var now = Date.now();
    if (toastCooldown[cooldownKey] && (now - toastCooldown[cooldownKey]) < TOAST_SAME_ERROR_COOLDOWN_MS) return;
    toastCooldown[cooldownKey] = now;
    if (toastQueue.length >= TOAST_QUEUE_MAX) {
      var old = toastQueue.shift();
      dismissToast(old);
    }
    var el = document.createElement("div");
    if (alertId) el.dataset.alertId = alertId;
    el.className = "toast " + (level === "CRIT" ? "crit" : "warn") + " toast-with-close";
    el.innerHTML = "<button type=\"button\" class=\"toast-close\" aria-label=\"Kapat\">&times;</button><span class=\"toast-text\">" + (message || "").replace(/</g, "&lt;").replace(/>/g, "&gt;") + "</span>";
    container.appendChild(el);
    toastQueue.push(el);
    el.querySelector(".toast-close").addEventListener("click", function () { dismissToast(el); });
    if (level !== "CRIT") setTimeout(function () { dismissToast(el); }, TOAST_DISMISS_MS);
  }

  const serviceLabel = { web: "WEB", engine: "MOTOR", manager: "YÖNETİCİ" };
  function showDiagnosisToast(diagnosis) {
    if (!diagnosis || !qs("#setting-toast") || !qs("#setting-toast").checked) return;
    var service = diagnosis.service;
    var code = diagnosis.reason_code || "UNKNOWN";
    var cooldownKey = service + ":" + code;
    var now = Date.now();
    if (diagnosisToastCooldown[cooldownKey] && (now - diagnosisToastCooldown[cooldownKey]) < DIAGNOSIS_COOLDOWN_MS) return;
    diagnosisToastCooldown[cooldownKey] = now;
    var container = qs("#toast-container");
    if (!container || toastQueue.length >= TOAST_QUEUE_MAX) return;
    var title = (serviceLabel[service] || service) + ": " + (diagnosis.title_tr || code);
    var el = document.createElement("div");
    el.className = "toast crit toast-with-close";
    el.innerHTML = "<button type=\"button\" class=\"toast-close\" aria-label=\"Kapat\">&times;</button>" +
      "<strong>" + title + "</strong><br/>" + (diagnosis.summary_tr || "") +
      (diagnosis.impact_tr ? "<br/><small>Etkisi: " + diagnosis.impact_tr + "</small>" : "") +
      "<div class=\"toast-diagnosis-actions\">" +
      "<button type=\"button\" class=\"btn btn-sm btn-detail\" data-service=\"" + service + "\">Detay</button>" +
      "<button type=\"button\" class=\"btn btn-sm btn-copy-diagnosis\">Kopyala</button>" +
      "<button type=\"button\" class=\"btn btn-sm btn-ack-toast\">ACK</button></div>";
    container.appendChild(el);
    toastQueue.push(el);
    el.querySelector(".toast-close").addEventListener("click", function () { dismissToast(el); });
    el.querySelector(".btn-detail").addEventListener("click", function () {
      var tab = document.querySelector(".nav-item[data-tab=\"" + service + "\"]");
      if (tab) { tab.click(); qs("#diagnosis-" + service).scrollIntoView({ behavior: "smooth" }); }
      dismissToast(el);
    });
    el.querySelector(".btn-copy-diagnosis").addEventListener("click", function () {
      try { navigator.clipboard.writeText(JSON.stringify(diagnosis, null, 2)); } catch (_) {}
      dismissToast(el);
    });
    el.querySelector(".btn-ack-toast").addEventListener("click", function () { dismissToast(el); });
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

  function openDrawer(issue) {
    selectedIssueId = issue.id;
    const drawer = qs("#incident-drawer");
    if (!drawer) return;
    qs("#drawer-title").textContent = (issue.id || "") + " — " + (issue.severity || "");
    qs("#drawer-meta").textContent = "İlk: " + formatIssueLastSeen(issue.first_seen) + " · Son: " + formatIssueLastSeen(issue.last_seen) + " · Adet: " + (issue.count != null ? issue.count : "—");
    qs("#drawer-status").textContent = "Durum: " + (issue.status || "OPEN");
    const assigneeInp = qs("#drawer-assignee");
    if (assigneeInp) assigneeInp.value = issue.assignee || "";
    const labelsInp = qs("#drawer-labels");
    if (labelsInp) labelsInp.value = Array.isArray(issue.labels) ? issue.labels.join(", ") : "";
    const slaInp = qs("#drawer-sla");
    if (slaInp) slaInp.value = issue.sla_note || "";
    const histEl = qs("#drawer-status-history");
    if (histEl) histEl.textContent = (issue.status_history || []).map(h => (h.ts || "") + " " + (h.status || "")).join("\n") || "—";
    const commentsEl = qs("#drawer-comments");
    if (commentsEl) {
      commentsEl.innerHTML = "";
      (issue.comments || []).forEach(c => {
        const div = document.createElement("div");
        div.className = "drawer-comment-item";
        div.innerHTML = "<span class=\"comment-meta\">" + (c.ts || "") + " " + (c.author || "") + "</span><br/>" + (c.text || "");
        commentsEl.appendChild(div);
      });
    }
    qs("#drawer-comment-text").value = "";
    qs("#drawer-samples").textContent = (issue.samples || []).join("\n") || "Örnek kayıt yok.";
    drawer.classList.remove("hidden");
  }

  function closeDrawer() {
    selectedIssueId = null;
    const drawer = qs("#incident-drawer");
    if (drawer) drawer.classList.add("hidden");
  }

  qs("#drawer-close").addEventListener("click", closeDrawer);
  qs("#drawer-ack").addEventListener("click", function () {
    if (!selectedIssueId) return;
    api("POST", "/api/issues/" + selectedIssueId + "/ack").then(() => { refreshIssues(); refreshMetrics(); closeDrawer(); }).catch(e => alert(e.message));
  });
  qs("#drawer-resolve").addEventListener("click", function () {
    if (!selectedIssueId) return;
    api("POST", "/api/issues/" + selectedIssueId + "/resolve").then(() => { refreshIssues(); refreshMetrics(); closeDrawer(); }).catch(e => alert(e.message));
  });
  qs("#drawer-assign-btn").addEventListener("click", function () {
    if (!selectedIssueId) return;
    const v = qs("#drawer-assignee").value;
    api("POST", "/api/issues/" + selectedIssueId + "/assign", { assignee: v }).then(() => fetch(API + "/api/issues/" + selectedIssueId).then(r => r.json()).then(openDrawer)).catch(e => alert(e.message));
  });
  qs("#drawer-labels-btn").addEventListener("click", function () {
    if (!selectedIssueId) return;
    const v = qs("#drawer-labels").value;
    const labels = v.split(",").map(s => s.trim()).filter(Boolean).slice(0, 10);
    api("POST", "/api/issues/" + selectedIssueId + "/labels", { labels }).then(() => fetch(API + "/api/issues/" + selectedIssueId).then(r => r.json()).then(openDrawer)).catch(e => alert(e.message));
  });
  qs("#drawer-sla-btn").addEventListener("click", function () {
    if (!selectedIssueId) return;
    const v = qs("#drawer-sla").value;
    api("POST", "/api/issues/" + selectedIssueId + "/sla", { sla_note: v }).then(() => fetch(API + "/api/issues/" + selectedIssueId).then(r => r.json()).then(openDrawer)).catch(e => alert(e.message));
  });
  qs("#drawer-comment-btn").addEventListener("click", function () {
    if (!selectedIssueId) return;
    const v = qs("#drawer-comment-text").value;
    if (!v.trim()) return;
    api("POST", "/api/issues/" + selectedIssueId + "/comment", { text: v }).then(() => fetch(API + "/api/issues/" + selectedIssueId).then(r => r.json()).then(openDrawer)).catch(e => alert(e.message));
  });

  async function refreshStatus() {
    try {
      const s = await api("GET", "/api/status");
      keys.forEach(k => setStatus(k, s[k]));
      if (s.html) {
        setStatus("html", s.html);
        var chip = qs("#overview-html-status");
        if (chip) { chip.textContent = s.html.running ? "ÇALIŞIYOR" : "DURDURULDU"; chip.className = "status-chip " + (s.html.running ? "running" : "stopped"); }
        var pidEl = qs("#overview-html-pid"); if (pidEl) pidEl.textContent = s.html.pid != null ? String(s.html.pid) : "—";
        var htmlUptime = (typeof s.html.started_at === "number") ? Math.max(0, Math.floor(Date.now() / 1000 - s.html.started_at)) : null;
        var uptimeEl = qs("#overview-html-uptime"); if (uptimeEl) uptimeEl.textContent = formatUptime(htmlUptime) || "—";
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
        if (ov) ov.textContent = (running || !d || !d.title_tr) ? "—" : ("Son teşhis: " + d.title_tr + (d.ts ? " (" + d.ts + ")" : ""));
      });
    } catch (e) { console.error(e); }
  }

  function formatErrWrnLine(l) {
    const raw = typeof l === "string" ? l : (l.ts || "") + " " + (l.text || l);
    return "Sebep: " + raw;
  }
  function updateNavErrCount(key, count) {
    var navEl = qs("#nav-err-" + key);
    if (!navEl) return;
    navEl.textContent = count;
    navEl.classList.toggle("hidden", !count || count === 0);
  }
  function setErrWrn(key, newErrors, newWarns) {
    var errEl = qs("#err-" + key);
    var wrnEl = qs("#wrn-" + key);
    var errList = Array.isArray(newErrors) ? newErrors : [];
    var wrnList = Array.isArray(newWarns) ? newWarns : [];
    var errNum = errList.length;
    var wrnNum = wrnList.length;
    if (errEl) {
      var errLines = errList.slice(-errWrnMaxLines).map(formatErrWrnLine);
      errEl.textContent = errLines.join("\n") + (errLines.length ? "\n" : "");
      errEl.scrollTop = errEl.scrollHeight;
      var errCountEl = qs("#err-" + key + "-count");
      if (errCountEl) errCountEl.textContent = String(errNum);
      updateNavErrCount(key, errNum);
    }
    if (wrnEl) {
      var wrnLines = wrnList.slice(-errWrnMaxLines).map(formatErrWrnLine);
      wrnEl.textContent = wrnLines.join("\n") + (wrnLines.length ? "\n" : "");
      wrnEl.scrollTop = wrnEl.scrollHeight;
      var wrnCountEl = qs("#wrn-" + key + "-count");
      if (wrnCountEl) wrnCountEl.textContent = String(wrnNum);
    }
  }

  async function fetchLogs(key) {
    try {
      const d = await api("GET", "/api/logs/" + key + "?tail=300");
      rawLogLines[key] = (d.lines || []).map(l => (typeof l === "string" ? l : ((l && l.ts) || "") + " " + toLogText(l)).trim()).filter(Boolean);
      const errEl = qs("#err-" + key);
      const wrnEl = qs("#wrn-" + key);
      var errList = d.errors || [];
      var wrnList = d.warns || [];
      if (errEl) {
        var errLines = errList.slice(-errWrnMaxLines).map(function (l) { return "Sebep: " + (typeof l === "string" ? l : ((l && l.ts) || "") + " " + toLogText(l)); });
        errEl.textContent = errLines.join("\n") + (errLines.length ? "\n" : "");
        var errCountEl = qs("#err-" + key + "-count");
        if (errCountEl) errCountEl.textContent = String(errList.length);
        updateNavErrCount(key, errList.length);
      }
      if (wrnEl) {
        var wrnLines = wrnList.slice(-errWrnMaxLines).map(function (l) { return "Sebep: " + (typeof l === "string" ? l : ((l && l.ts) || "") + " " + toLogText(l)); });
        wrnEl.textContent = wrnLines.join("\n") + (wrnLines.length ? "\n" : "");
        var wrnCountEl = qs("#wrn-" + key + "-count");
        if (wrnCountEl) wrnCountEl.textContent = String(wrnList.length);
      }
      renderLog(key);
    } catch (e) { console.error(e); }
  }

  function renderLog(key) {
    const logEl = qs("#log-" + key);
    if (!logEl) return;
    const level = (filterLevel[key] || "").toUpperCase();
    const q = (searchQuery[key] || "").toLowerCase();
    let lines = rawLogLines[key] || [];
    if (level === "WARN+") {
      lines = lines.filter(l => /WARN|ERROR|Traceback|Exception|CRITICAL/i.test(l));
    } else if (level) {
      lines = lines.filter(l => l.indexOf(level) >= 0 || (level === "ERROR" && (/ERROR|Traceback|Exception|CRITICAL/i.test(l))) || (level === "WARN" && /WARN/i.test(l)));
    }
    if (q) lines = lines.filter(l => l.toLowerCase().indexOf(q) >= 0);
    lines = lines.slice(-logMaxLines);
    const fragment = document.createDocumentFragment();
    lines.forEach(l => {
      const span = document.createElement("span");
      span.className = /ERROR|Traceback|Exception|CRITICAL/i.test(l) ? "line-err" : /WARN/i.test(l) ? "line-wrn" : "";
      span.textContent = l + "\n";
      fragment.appendChild(span);
    });
    logEl.textContent = "";
    logEl.appendChild(fragment);
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
    lines.forEach(l => {
      var text = toLogText(l);
      var lineStr = ((l && l.ts) || "") + (text ? " " + text : "");
      lineStr = lineStr.trim();
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
        if (d.issue_events && d.issue_events.length) refreshIssues();
        if (d.alert_events && d.alert_events.length) {
          d.alert_events.forEach(function (a) { showToast(a.message || a.kind || "Alert", a.level || "WARN", a.kind, a.id); });
        }
      } catch (_) {}
    };
    wsEvents.onclose = function () { if (useWsEvents) setTimeout(connectWsEvents, 3000); };
  }

  async function refreshAudit() {
    try {
      const list = await fetch(API + "/api/audit?limit=200").then(r => r.ok ? r.json() : []).catch(() => []);
      const container = qs("#audit-list");
      if (!container) return;
      container.innerHTML = "";
      (list || []).reverse().forEach(e => {
        const row = document.createElement("div");
        row.className = "audit-row";
        row.innerHTML = "<span class=\"audit-ts\">" + (e.ts || "") + "</span><span class=\"audit-action\">" + (e.action || "") + "</span><span class=\"audit-detail\">" + JSON.stringify(e.detail || {}) + "</span>";
        container.appendChild(row);
      });
      if (!list || list.length === 0) container.innerHTML = "<p class=\"audit-empty\">Denetim kaydı yok.</p>";
    } catch (e) { console.error(e); }
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
    if (tab === "overview") refreshMetrics();
    if (tab === "web") { refreshMetrics(); fetchLogs("web"); }
    if (tab === "engine") { refreshMetrics(); fetchLogs("engine"); }
    if (tab === "manager") { refreshMetrics(); fetchLogs("manager"); }
    if (tab === "html") { refreshStatus(); fetchLogs("html"); }
    if (tab === "security") {
      refreshSecurity();
      securityPollIntervalId = setInterval(refreshSecurity, 1500);
    }
    if (tab === "incidents") refreshIssues();
    if (tab === "audit") refreshAudit();
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

  if (qs("#incidents-filter-open")) qs("#incidents-filter-open").addEventListener("change", refreshIssues);

  function loadSettings() {
    try {
      const raw = localStorage.getItem("manager_settings");
      if (raw) {
        const s = JSON.parse(raw);
        if (s.pollIntervalMs) { pollIntervalMs = s.pollIntervalMs; const sel = qs("#setting-poll-interval"); if (sel) sel.value = String(pollIntervalMs); }
        if (s.logMaxLines) { logMaxLines = s.logMaxLines; const inp = qs("#setting-log-max-lines"); if (inp) inp.value = s.logMaxLines; }
        if (s.toast !== undefined) { const cb = qs("#setting-toast"); if (cb) cb.checked = !!s.toast; }
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
    } catch (_) {}
  }
  function saveSettings() {
    try {
      const themeEl = document.querySelector("input[name=theme]:checked");
      const s = {
        pollIntervalMs,
        logMaxLines,
        toast: qs("#setting-toast") ? qs("#setting-toast").checked : true,
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
    } catch (_) {}
  }
  function setDefaults() {
    const sel = qs("#setting-poll-interval"); if (sel) sel.value = "2000";
    const logInp = qs("#setting-log-max-lines"); if (logInp) logInp.value = "1000";
    const toastCb = qs("#setting-toast"); if (toastCb) toastCb.checked = true;
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
      else if (kind === "issues") url = base + "issues?format=" + format;
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

  if (qs("#setting-toast")) qs("#setting-toast").addEventListener("change", saveSettings);
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
  keys.forEach(k => fetchLogs(k));
  useWsEvents = wsEventsCb && wsEventsCb.checked;
  if (useWsEvents) connectWsEvents(); else keys.forEach(k => connectWs(k));
  setInterval(refreshStatus, 5000);
  metricsIntervalId = setInterval(refreshMetrics, pollIntervalMs);
  setInterval(function () {
    if (lastMetrics && lastMetrics.status) {
      keys.forEach(k => setStatus(k, lastMetrics.status[k] || {}));
      if (lastMetrics.status.html) {
        var h = lastMetrics.status.html;
        setStatus("html", h);
        var chip = qs("#overview-html-status");
        if (chip) { chip.textContent = h.running ? "ÇALIŞIYOR" : "DURDURULDU"; chip.className = "status-chip " + (h.running ? "running" : "stopped"); }
        var pidEl = qs("#overview-html-pid"); if (pidEl) pidEl.textContent = h.pid != null ? String(h.pid) : "—";
        var htmlUptime = (typeof h.started_at === "number") ? Math.max(0, Math.floor(Date.now() / 1000 - h.started_at)) : null;
        var uptimeEl = qs("#overview-html-uptime"); if (uptimeEl) uptimeEl.textContent = formatUptime(htmlUptime) || "—";
      }
      if (lastMetrics.status.manager) {
        const mgrStat = qs("#overview-manager-stat");
        if (mgrStat && lastMetrics.manager) {
          const d = lastMetrics.status.manager;
          const liveUptime = d.running ? getLiveUptime("manager") : null;
          const parts = ["PID " + (d.pid || "—"), "Çalışma süresi: " + formatUptime(liveUptime)];
          if (lastMetrics.manager.cpu_pct != null) parts.push(lastMetrics.manager.cpu_pct + "% CPU");
          if (lastMetrics.manager.rss_mb != null) parts.push(lastMetrics.manager.rss_mb + " MB");
          mgrStat.textContent = parts.join(" · ");
        }
      }
    }
  }, 1000);
})();
