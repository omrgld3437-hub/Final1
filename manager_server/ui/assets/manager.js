// manager (assets/).
(function () {
  const API = "";
  const keys = ["web", "engine", "manager", "html"];
  const SERVICE_PORTS = { manager: "7999", web: "8000", engine: "—", html: "8080" };
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
      b.disabled = !!loading;
      b.classList.toggle("is-loading", !!loading);
      b.setAttribute("aria-busy", loading ? "true" : "false");
      if (loading) {
        b.style.pointerEvents = "none";
        b.style.opacity = "0.7";
      } else {
        b.style.removeProperty("pointer-events");
        b.style.removeProperty("opacity");
      }
    });
  }

  function setGlobalHeaderBusy(loading) {
    var grp = qs(".manager-header-action-group");
    if (grp) grp.classList.toggle("is-busy", !!loading);
  }

  function showActionFeedback(msg, isError) {
    if (msg) console.log(isError ? "[manager] " + msg : "[manager] " + msg);
  }

  var globalActionBusy = false;
  var globalActionPollTimer = null;
  var globalActionWatchdogTimer = null;
  var globalBtnIds = ["btnGlobalStart", "btnGlobalStop", "btnGlobalRestart"];

  function clearGlobalActionWatchdog() {
    if (globalActionWatchdogTimer) {
      clearTimeout(globalActionWatchdogTimer);
      globalActionWatchdogTimer = null;
    }
  }

  function releaseGlobalActionUi() {
    globalActionBusy = false;
    clearGlobalActionWatchdog();
    setButtonsLoading(globalBtnIds, false);
    setGlobalHeaderBusy(false);
  }

  function healStuckGlobalActionUi(serverBusy) {
    if (globalActionBusy) return;
    if (serverBusy === true) return;
    var grp = qs(".manager-header-action-group");
    var stuck = grp && grp.classList.contains("is-busy");
    globalBtnIds.forEach(function (id) {
      var b = qs("#" + id);
      if (b && (b.disabled || b.classList.contains("is-loading"))) stuck = true;
    });
    if (stuck) releaseGlobalActionUi();
  }

  function stopGlobalActionPoll() {
    if (globalActionPollTimer) {
      clearInterval(globalActionPollTimer);
      globalActionPollTimer = null;
    }
  }

  function pollAfterGlobalAction(seconds) {
    stopGlobalActionPoll();
    var left = Math.max(1, seconds || 45);
    refreshStatus();
    refreshMetrics();
    refreshDiagnosis();
    globalActionPollTimer = setInterval(function () {
      left -= 1;
      refreshStatus();
      refreshMetrics();
      refreshDiagnosis();
      if (left <= 0) stopGlobalActionPoll();
    }, 2000);
  }

  function showApiConnectionError() {}

  function getLiveUptime(key) {
    if (!lastMetrics || !lastMetrics[key]) return null;
    const base = lastMetrics[key].uptime_s;
    if (base == null) return null;
    const elapsed = (Date.now() / 1000) - lastMetricsReceivedAt;
    return Math.max(0, Math.floor(base + elapsed));
  }

  function getLiveSystemUptime() {
    if (!lastMetrics || !lastMetrics.system) return null;
    var sys = lastMetrics.system;
    var started = sys.session_started_at;
    if (started != null && !isNaN(Number(started))) {
      return Math.max(0, Math.floor(Date.now() / 1000 - Number(started)));
    }
    var base = sys.uptime_s;
    if (base == null) return null;
    var elapsed = (Date.now() / 1000) - lastMetricsReceivedAt;
    return Math.max(0, Math.floor(base + elapsed));
  }

  function setStatus(key, data) {
    data = data || {};
    var proc = (lastMetrics && lastMetrics[key]) || {};
    var pid = stickyServicePid(key, data, proc);
    const chip = qs("#status-" + key);
    if (chip) {
      chip.textContent = data.running ? "ÇALIŞIYOR" + (pid != null ? " " + pid : "") : "DURDURULDU";
      chip.className = "status-chip " + (data.running ? "running" : "stopped");
    }
    const statEl = qs("#stat-" + key);
    if (statEl && data) {
      statEl.textContent = data.running ? "ÇALIŞIYOR" : "DURDURULDU";
    }
  }

  function formatUptime(s, chronometer) {
    if (s == null || s === undefined) return "—";
    s = Math.max(0, Math.floor(Number(s)));
    if (chronometer) {
      var h = Math.floor(s / 3600);
      var m = Math.floor((s % 3600) / 60);
      var sec = s % 60;
      if (h > 0) {
        return h + ":" + (m < 10 ? "0" : "") + m + ":" + (sec < 10 ? "0" : "") + sec;
      }
      return m + ":" + (sec < 10 ? "0" : "") + sec;
    }
    if (s < 60) return s + " sn";
    var m = Math.floor(s / 60);
    var h = Math.floor(m / 60);
    var d = Math.floor(h / 24);
    h = h % 24;
    m = m % 60;
    if (d > 0) {
      return d + " gün " + h + " sa";
    }
    if (h > 0) {
      return h + " sa " + (m < 10 ? "0" : "") + m + " dk";
    }
    return m + " dk";
  }

  function setTextIfChanged(el, text) {
    if (!el) return;
    var s = (text == null || text === undefined) ? "" : String(text);
    if (el.textContent !== s) el.textContent = s;
  }

  /** PID null geldiğinde çalışan serviste son bilinen değeri koru (flicker önleme). */
  var overviewPidCache = { manager: null, web: null, engine: null, html: null };
  var engineBotsCache = null;

  function stickyActiveBots(running, engApp) {
    engApp = engApp || {};
    var bots = engApp.active_bots;
    if (bots != null) {
      engineBotsCache = bots;
      return bots;
    }
    if (running && engineBotsCache != null) return engineBotsCache;
    if (!running) engineBotsCache = null;
    return null;
  }

  function getServiceUptime(key, status, proc, running) {
    status = status || {};
    if (key === "html" && typeof status.started_at === "number") {
      return Math.max(0, Math.floor(Date.now() / 1000 - status.started_at));
    }
    if (running) return getLiveUptime(key);
    if (proc && proc.uptime_s != null) return proc.uptime_s;
    return null;
  }

  function updateServiceMetricsDisplay(key, m, errCount, wrnCount) {
    m = m || {};
    var status = (m.status && m.status[key]) || {};
    var proc = m[key] || {};
    var running = !!status.running;
    var pid = stickyServicePid(key, status, proc);
    var uptime = getServiceUptime(key, status, proc, running);
    var errWrn = errCount + " / " + wrnCount;
    var port = SERVICE_PORTS[key] || "—";
    var engApp = m.engine_app || {};

    ["overview", "tab"].forEach(function (scope) {
      var prefix = "#" + scope + "-" + key + "-";
      if (key !== "engine") {
        setTextIfChanged(qs(prefix + "port"), port);
      }
      if (key === "engine") {
        var bots = stickyActiveBots(running, engApp);
        var botsText = bots != null ? String(bots) : (running ? "0" : "—");
        setTextIfChanged(qs(prefix + "bots"), botsText);
      }
      setTextIfChanged(qs(prefix + "pid"), pid != null ? String(pid) : "—");
      setTextIfChanged(qs(prefix + "uptime"), formatUptime(uptime) || "—");
      if (scope === "overview") {
        setTextIfChanged(qs(prefix + "cpu"), formatCpuPct(proc));
        setTextIfChanged(qs(prefix + "ram"), formatRamMb(proc));
        var tickEl = qs(prefix + "hourly-tick");
        setTextIfChanged(tickEl, formatHourlyTick(proc, running));
        if (tickEl && key === "web") {
          var rpm = proc.requests_per_min != null ? Number(proc.requests_per_min) : null;
          var hint = "Son 60 dk HTTP istek (bot canlı, dashboard, API). Engine tick değil.";
          if (rpm != null && !isNaN(rpm)) hint += " Şu an ~" + rpm.toFixed(0) + " istek/dk.";
          tickEl.title = hint;
        }
      } else {
        var resourceEl = qs(prefix + "resource");
        setTextIfChanged(resourceEl, formatResource(proc));
        if (resourceEl) resourceEl.classList.add("metric-resource");
      }
      setTextIfChanged(qs(prefix + "err-wrn"), errWrn);
    });
    setOverviewStatusChip(qs("#overview-" + key + "-status"), running);
  }

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

  function setHealthBadgeIfChanged(cardEl, text, stateClass) {
    if (!cardEl) return;
    var textEl = qs("#overview-health-text");
    var s = (text == null || text === undefined) ? "" : String(text);
    if (textEl && textEl.textContent !== s) textEl.textContent = s;
    var cls = "overview-health-card " + (stateClass || "ok");
    if (cardEl.className !== cls) cardEl.className = cls;
  }

  function setOverviewHeaderMetric(el, text, level) {
    if (!el) return;
    setTextIfChanged(el, text);
    el.classList.remove("warn", "crit");
    if (level) el.classList.add(level);
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

  function formatCpuPct(proc) {
    if (!proc || proc.cpu_pct == null) return "—";
    return Number(proc.cpu_pct).toFixed(1) + "%";
  }

  function formatRamMb(proc) {
    if (!proc || proc.rss_mb == null) return "—";
    return Number(proc.rss_mb).toFixed(1) + " MB";
  }

  function formatResource(proc) {
    if (!proc || (proc.cpu_pct == null && proc.rss_mb == null)) return "—";
    return formatCpuPct(proc) + " · " + formatRamMb(proc);
  }

  function formatHourlyTick(proc, running) {
    if (proc && proc.ticks_last_60m != null && proc.ticks_last_60m !== "") {
      return String(proc.ticks_last_60m);
    }
    return running ? "0" : "—";
  }

  function mergeMetricsPayload(incoming) {
    incoming = incoming || {};
    if (!lastMetrics) return incoming;
    var out = Object.assign({}, lastMetrics, incoming);
    var prevSys = lastMetrics.system || {};
    var nextSys = incoming.system || {};
    out.system = Object.assign({}, prevSys, nextSys);
    if (nextSys.uptime_s == null && prevSys.uptime_s != null) {
      out.system.uptime_s = prevSys.uptime_s;
    }
    if (nextSys.session_started_at == null && prevSys.session_started_at != null) {
      out.system.session_started_at = prevSys.session_started_at;
    }
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

    var lastUpdateEl = qs("#overview-last-update");
    if (lastUpdateEl) setTextIfChanged(lastUpdateEl, new Date().toLocaleTimeString("tr-TR") || "—");

    var runningCount = keys.filter(function (k) {
      return m.status && m.status[k] && m.status[k].running;
    }).length;
    var svcEl = qs("#overview-services-count");
    var svcLevel = runningCount === keys.length ? null : (runningCount <= 1 ? "crit" : "warn");
    setOverviewHeaderMetric(svcEl, runningCount + " / " + keys.length + " aktif", svcLevel);

    var healthEl = qs("#overview-health-badge");
    if (healthEl) {
      var hasErr = keys.some(function (k) {
        return m.errors_ring && m.errors_ring[k] && m.errors_ring[k].length > 0;
      });
      var healthText, healthState;
      if (runningCount < keys.length) {
        var stopped = keys.length - runningCount;
        healthText = stopped === 1 ? "1 servis durdu" : stopped + " servis durdu";
        healthState = runningCount <= 1 ? "crit" : "warn";
      } else if (hasErr) {
        healthText = "Log hatası var";
        healthState = "warn";
      } else {
        healthText = "Tümü normal";
        healthState = "ok";
      }
      setHealthBadgeIfChanged(healthEl, healthText, healthState);
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
    setTextIfChanged(qs("#overview-system-uptime"), formatUptime(getLiveSystemUptime(), true) || "—");
    const progressCpu = qs("#progress-cpu");
    setProgressBar(progressCpu, cpuPct);
    const progressRam = qs("#progress-ram");
    setProgressBar(progressRam, ramPct);
    const progressDisk = qs("#progress-disk");
    setProgressBar(progressDisk, diskPct);

    keys.forEach(function (k) {
      var ec = (m.errors_ring && m.errors_ring[k]) ? m.errors_ring[k].length : 0;
      var wc = (m.warns_ring && m.warns_ring[k]) ? m.warns_ring[k].length : 0;
      updateServiceMetricsDisplay(k, m, ec, wc);
      updateNavAlertState(k, ec, wc);
    });

    updateSecurityUI(traffic);
  }

  function formatLoginFailReason(reasonRaw) {
    var reason = reasonRaw || "—";
    if (window.LogHumanize && reason !== "—" && /ERROR|WARN|fail|SSL|401|Unauthorized|Exception/i.test(reason)) {
      return window.LogHumanize.format(reason, "web");
    }
    return reason;
  }

  function renderSecurityLoginFails(list) {
    var el = qs("#security-login-list");
    var badge = qs("#security-login-count");
    if (!el) return;
    list = list || [];
    if (badge) {
      badge.textContent = String(list.length);
      badge.classList.toggle("warn", list.length > 0);
    }
    if (!list.length) {
      el.innerHTML = "<p class=\"security-empty\">Başarısız giriş yok.</p>";
      return;
    }
    el.innerHTML = list.map(function (f) {
      var ts = f.ts ? new Date(f.ts * 1000).toLocaleString("tr-TR") : "—";
      var ip = escHtml(f.ip || "—");
      var user = escHtml(f.user || "—");
      var reason = escHtml(formatLoginFailReason(f.reason));
      return "<div class=\"sec-login-item\">" +
        "<div class=\"sec-login-meta\">" +
          "<span class=\"sec-login-time\">" + escHtml(ts) + "</span>" +
          "<span class=\"sec-login-ip\">" + ip + "</span>" +
          "<span class=\"sec-login-user\">" + user + "</span>" +
        "</div>" +
        "<p class=\"sec-login-reason\">" + reason + "</p>" +
      "</div>";
    }).join("");
  }

  function renderSecurityTopIps(list, blockedMap) {
    var el = qs("#security-ip-list");
    var badge = qs("#security-ip-count");
    if (!el) return;
    list = list || [];
    blockedMap = blockedMap || {};
    if (badge) badge.textContent = String(list.length);
    if (!list.length) {
      el.innerHTML = "<p class=\"security-empty\">IP verisi yok.</p>";
      return;
    }
    var maxCount = 1;
    list.forEach(function (x) {
      var c = Number(x.count) || 0;
      if (c > maxCount) maxCount = c;
    });
    el.innerHTML = list.map(function (x, i) {
      var ipRaw = x.ip || "—";
      var ip = escHtml(ipRaw);
      var count = Number(x.count) || 0;
      var pct = Math.max(2, Math.round(100 * count / maxCount));
      var local = isLocalIp(ipRaw);
      var blocked = !!blockedMap[ipRaw];
      var localTag = local ? "<span class=\"sec-ip-local\" title=\"Bu makineden gelen trafik (dashboard, API polling)\">yerel</span>" : "";
      var actionBtn = blocked
        ? "<button type=\"button\" class=\"sec-ip-btn sec-ip-unban\" data-ip=\"" + ip + "\" title=\"Engeli kaldır\">Kaldır</button>"
        : "<button type=\"button\" class=\"sec-ip-btn sec-ip-ban\" data-ip=\"" + ip + "\" title=\"Web uygulamasından engelle\">Engelle</button>";
      var rowClass = "sec-ip-row" + (blocked ? " is-blocked" : "");
      return "<div class=\"" + rowClass + "\">" +
        "<span class=\"sec-ip-rank\">" + (i + 1) + "</span>" +
        "<span class=\"sec-ip-addr\" title=\"" + ip + "\">" + ip + localTag + "</span>" +
        "<div class=\"sec-ip-bar-wrap\"><div class=\"sec-ip-bar\" style=\"width:" + pct + "%\"></div></div>" +
        "<span class=\"sec-ip-count\">" + count + "</span>" +
        actionBtn +
      "</div>";
    }).join("");
  }

  function isLocalIp(ip) {
    if (!ip) return false;
    var s = String(ip).trim().toLowerCase();
    return s === "127.0.0.1" || s === "::1" || s === "localhost";
  }

  async function securityBanIp(ip) {
    if (!ip) return;
    if (!securityBlockedAvailable) {
      alert("IP engelleme API'si yok. Manager Server'ı yeniden başlatın (python -m manager_server), ardından sayfayı yenileyin.");
      return;
    }
    var msg = isLocalIp(ip)
      ? "Yerel IP (" + ip + ") engellensin mi? Bu makineden web uygulamasına (8000) erişim kesilir."
      : ip + " engellensin mi? Web uygulamasından gelen istekler reddedilir.";
    if (!confirm(msg)) return;
    try {
      await api("POST", "/api/security/ban-ip", { ip: ip, reason: "Manager güvenlik paneli" });
      refreshSecurity();
    } catch (e) {
      alert(e.message || "Engelleme başarısız");
    }
  }

  async function securityUnbanIp(ip) {
    if (!ip) return;
    try {
      await api("POST", "/api/security/unban-ip", { ip: ip });
      refreshSecurity();
    } catch (e) {
      alert(e.message || "Engel kaldırılamadı");
    }
  }

  var securityBlockedMap = {};
  var securityBlockedAvailable = true;
  var securityBlockedProbePending = false;

  async function fetchSecurityBlocked() {
    if (!securityBlockedAvailable && !securityBlockedProbePending) {
      return { blocked: [] };
    }
    try {
      var data = await api("GET", "/api/security/blocked-ips");
      securityBlockedAvailable = true;
      securityBlockedProbePending = false;
      return data || { blocked: [] };
    } catch (e) {
      if (e && e.message && (e.message.indexOf("404") >= 0 || e.message.indexOf("Not Found") >= 0)) {
        securityBlockedAvailable = false;
        securityBlockedProbePending = false;
      }
    }
    return { blocked: [] };
  }

  function setSecurityStat(el, text, level) {
    if (!el) return;
    setTextIfChanged(el, text);
    el.classList.remove("warn", "crit");
    if (level) el.classList.add(level);
  }

  function updateSecurityUI(traffic) {
    traffic = traffic || {};
    var loginFails = traffic.last_login_fails || [];
    var topIps = traffic.top_ips || [];
    var status5xx = Number(traffic.status_5xx) || 0;
    var errRate = traffic.error_rate != null ? Number(traffic.error_rate) : null;
    var errPctText = errRate != null ? (errRate * 100).toFixed(2) + "%" : "—";

    setSecurityStat(qs("#security-stat-login"), String(loginFails.length), loginFails.length > 0 ? "warn" : null);
    setSecurityStat(
      qs("#security-stat-login-total"),
      traffic.login_fail_total != null ? String(traffic.login_fail_total) : "—",
      traffic.login_fail_total > 0 ? "warn" : null
    );
    setSecurityStat(qs("#security-stat-5xx"), String(status5xx), status5xx > 0 ? "crit" : null);
    setSecurityStat(
      qs("#security-stat-error-rate"),
      errPctText,
      errRate != null && errRate > 0.05 ? "crit" : (errRate != null && errRate > 0.01 ? "warn" : null)
    );
    setSecurityStat(
      qs("#security-stat-rpm"),
      traffic.requests_per_min != null ? String(Math.round(traffic.requests_per_min)) : "—",
      null
    );

    var lastUp = qs("#security-last-update");
    if (lastUp) setTextIfChanged(lastUp, new Date().toLocaleTimeString("tr-TR"));

    var banner = qs("#security-health-banner");
    var detail = qs("#security-5xx-msg");
    var titleEl = banner && banner.querySelector(".security-health-title");
    var warn = status5xx > 0 || (errRate != null && errRate > 0.01) || loginFails.length > 5;
    if (banner) banner.className = "security-health-banner " + (warn ? "warn" : "ok");
    if (titleEl) {
      setTextIfChanged(titleEl, warn ? "Güvenlik uyarısı var" : "Trafik durumu normal");
    }
    if (detail) {
      var parts = [];
      parts.push(status5xx > 0 ? ("5xx: " + status5xx) : "5xx yok");
      parts.push(errRate != null ? ("hata oranı: " + errPctText) : "hata oranı: —");
      if (loginFails.length) parts.push("son giriş hatası: " + loginFails.length);
      setTextIfChanged(detail, parts.join(" · "));
    }

    renderSecurityLoginFails(loginFails);
    renderSecurityTopIps(topIps, securityBlockedMap);
  }

  async function refreshSecurity() {
    try {
      const [traffic, blockedRes] = await Promise.all([
        fetch(API + "/api/traffic").then(function (r) { return r.ok ? r.json() : {}; }).catch(function () { return {}; }),
        fetchSecurityBlocked()
      ]);
      securityBlockedMap = {};
      (blockedRes.blocked || []).forEach(function (b) {
        if (b && b.ip) securityBlockedMap[b.ip] = b;
      });
      updateSecurityUI(traffic);
    } catch (e) { console.error(e); }
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
      if (hostEl) hostEl.textContent = status.host || "—";
      var incidentsActive = qs("#panel-incidents") && qs("#panel-incidents").classList.contains("active");
      if (incidentsActive) refreshIssueStats();
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

  function diagnosisRunningFallback(key, st) {
    st = st || {};
    var portMap = { web: 8000, manager: 7999, html: 8080 };
    var proc = (lastMetrics && lastMetrics[key]) || {};
    return {
      reason_code: "RUNNING",
      state: "RUNNING",
      title_tr: "Çalışıyor",
      summary_tr: "Servis normal çalışıyor.",
      impact_tr: "Yok.",
      evidence: {
        pid: stickyServicePid(key, st, proc),
        port: portMap[key] != null ? portMap[key] : null
      },
      actions_tr: [],
      next_checks_tr: []
    };
  }

  function diagnosisLiveMeta(key, statusObj, ev) {
    statusObj = statusObj || {};
    ev = ev || {};
    var proc = (lastMetrics && lastMetrics[key]) || {};
    var pid = stickyServicePid(key, statusObj, proc);
    if (pid == null && ev.pid != null) pid = ev.pid;
    var portMap = { web: 8000, manager: 7999, html: 8080 };
    var port = portMap[key] != null ? portMap[key] : ev.port;
    var meta = [];
    if (pid != null) meta.push("PID " + pid);
    if (port != null) meta.push("Port " + port);
    return meta;
  }

  function diagnosisFallback(key) {
    var errs = [];
    if (lastMetrics && lastMetrics.errors_ring && lastMetrics.errors_ring[key]) {
      errs = lastMetrics.errors_ring[key].slice(-8);
    } else if (errWrnSnapshot[key] && errWrnSnapshot[key].errors) {
      errs = errWrnSnapshot[key].errors.slice(-8);
    }
    var lines = errs.map(function (l) { return humanizeLogLineIfNeeded(l, key); });
    return {
      reason_code: "STOPPED",
      state: "STOPPED",
      title_tr: "Servis çalışmıyor",
      summary_tr: "Servis durduruldu veya yanıt vermiyor. Özet ve log kanıtına bakın.",
      impact_tr: "Bu servisin sunduğu özellikler şu an kullanılamaz.",
      actions_tr: [
        "Başlat düğmesi ile yeniden başlatmayı deneyin.",
        "Aşağıdaki log satırlarında hata veya port mesajı arayın."
      ],
      next_checks_tr: [],
      evidence: { last_lines: lines }
    };
  }

  function formatEvidenceLines(key, ev) {
    ev = ev || {};
    var lines = [];
    if (ev.exit_code != null) lines.push("exit_code: " + ev.exit_code);
    if (ev.signal) lines.push("signal: " + ev.signal);
    if (ev.port != null) lines.push("port: " + ev.port);
    if (ev.pid != null) lines.push("pid: " + ev.pid);
    if (ev.last_lines && ev.last_lines.length) {
      ev.last_lines.forEach(function (ln) {
        lines.push(humanizeLogLineIfNeeded(ln, key));
      });
    }
    return lines;
  }

  function renderDiagnosis(key, data, isRunning, statusObj) {
    var box = qs("#diagnosis-" + key);
    if (!box) return;
    if ((!data || !data.reason_code) && isRunning) {
      data = diagnosisRunningFallback(key, statusObj);
    }
    if ((!data || !data.reason_code) && !isRunning) {
      data = diagnosisFallback(key);
    }
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

    var code = data.reason_code || "";
    var isHealthy = code === "RUNNING" && isRunning;
    var ev = data.evidence || {};

    if (isHealthy) {
      box.className = "diagnosis-box diagnosis-box-ok";
      var meta = diagnosisLiveMeta(key, statusObj, ev);
      box.innerHTML =
        "<div class=\"diag-compact\">" +
          "<span class=\"diag-compact-icon\" aria-hidden=\"true\"></span>" +
          "<div class=\"diag-compact-body\">" +
            "<span class=\"diag-compact-title\">" + escHtml(data.title_tr || "Çalışıyor") + "</span>" +
            "<span class=\"diag-compact-summary\">" + escHtml(data.summary_tr || "Servis normal çalışıyor.") + "</span>" +
          "</div>" +
          (meta.length ? "<span class=\"diag-compact-meta\">" + escHtml(meta.join(" · ")) + "</span>" : "") +
        "</div>";
      return;
    }

    var stateClass = "state-" + String(data.state || "unknown").toLowerCase().replace(/\s+/g, "_");
    box.className = "diagnosis-box diagnosis-box-issue " + stateClass;

    var html = "<div class=\"diag-panel\">" +
      "<header class=\"diag-panel-head\">" +
        "<span class=\"diag-state-badge " + stateClass + "\">" + escHtml(data.state || "—") + "</span>" +
        "<div class=\"diag-panel-intro\">" +
          "<h4 class=\"diag-panel-title\">" + escHtml(data.title_tr || "Teşhis") + "</h4>" +
          (data.summary_tr ? "<p class=\"diag-panel-summary\">" + escHtml(data.summary_tr) + "</p>" : "") +
          (data.reason_code ? "<p class=\"diag-panel-code\">Kod: " + escHtml(data.reason_code) + "</p>" : "") +
        "</div>" +
      "</header>";

    if (data.impact_tr && data.impact_tr !== "Yok.") {
      html += "<section class=\"diag-section diag-impact-section\">" +
        "<span class=\"diag-section-label\">Etki</span>" +
        "<p class=\"diag-section-text\">" + escHtml(data.impact_tr) + "</p></section>";
    }

    if (data.actions_tr && data.actions_tr.length) {
      html += "<section class=\"diag-section\"><span class=\"diag-section-label\">Ne yapmalı?</span><ul class=\"diag-list\">";
      data.actions_tr.forEach(function (a) { html += "<li>" + escHtml(a) + "</li>"; });
      html += "</ul></section>";
    }

    if (data.next_checks_tr && data.next_checks_tr.length) {
      html += "<section class=\"diag-section\"><span class=\"diag-section-label\">Kontrol listesi</span><ul class=\"diag-list diag-list-checks\">";
      data.next_checks_tr.forEach(function (c) { html += "<li>" + escHtml(c) + "</li>"; });
      html += "</ul></section>";
    }

    var evidenceLines = formatEvidenceLines(key, ev);
    if (evidenceLines.length) {
      html += "<details class=\"diag-evidence-details\" open>" +
        "<summary class=\"diag-evidence-summary\">Log kanıtı (" + evidenceLines.length + " satır)</summary>" +
        "<pre class=\"diag-evidence\">" + escHtml(evidenceLines.join("\n")) + "</pre>" +
      "</details>";
    }

    html += "<footer class=\"diag-panel-foot\">" +
      "<a href=\"" + escHtml(API || "") + "/api/export/logs?service=" + escHtml(key) + "&amp;format=csv\" target=\"_blank\" rel=\"noopener\" class=\"btn btn-sm btn-export\">Log dışa aktar</a>" +
      "<a href=\"" + escHtml(API || "") + "/api/export/diagnosis?service=" + escHtml(key) + "&amp;format=json\" target=\"_blank\" rel=\"noopener\" class=\"btn btn-sm btn-export\">Teşhis dışa aktar</a>" +
    "</footer></div>";

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
      if (hostEl) hostEl.textContent = s.host || "—";
      if (s.html && lastMetrics) {
        lastMetrics.status = lastMetrics.status || {};
        lastMetrics.status.html = s.html;
        var errHtml = (lastMetrics.errors_ring && lastMetrics.errors_ring.html) ? lastMetrics.errors_ring.html.length : 0;
        var wrnHtml = (lastMetrics.warns_ring && lastMetrics.warns_ring.html) ? lastMetrics.warns_ring.html.length : 0;
        updateServiceMetricsDisplay("html", lastMetrics, errHtml, wrnHtml);
      }
      const locks = await api("GET", "/api/locks");
      keys.forEach(k => {
        const cb = qs("#lock-" + k);
        if (cb) cb.checked = !!locks[k];
      });
      healStuckGlobalActionUi(s.global_action_busy === true);
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
        renderDiagnosis(k, d, running, status[k]);
        var ov = qs("#overview-" + k + "-diagnosis");
        if (ov) {
          var showOv = !running && d && d.title_tr && d.reason_code !== "RUNNING";
          var txt = showOv ? ("Son teşhis: " + d.title_tr + (d.ts ? " (" + d.ts + ")" : "")) : "—";
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
  function logPreDistanceFromBottom(el) {
    if (!el) return 0;
    return Math.max(0, el.scrollHeight - el.scrollTop - el.clientHeight);
  }
  function logPreLineHeight(el) {
    if (!el) return 18;
    var lh = parseFloat(window.getComputedStyle(el).lineHeight);
    return isNaN(lh) ? 18 : lh;
  }
  /** Okuma konumunu korumak: görünür ilk anlamlı satır metni. */
  function getLogScrollAnchor(el) {
    if (!el || logPreWasAtBottom(el) || el.scrollTop <= 0) return null;
    var text = el.textContent || "";
    if (!text) return null;
    var lines = text.split("\n");
    var idx = Math.min(lines.length - 1, Math.max(0, Math.floor(el.scrollTop / logPreLineHeight(el))));
    var i;
    for (i = idx; i < lines.length; i++) {
      if (lines[i] && lines[i].trim()) return lines[i];
    }
    for (i = idx; i >= 0; i--) {
      if (lines[i] && lines[i].trim()) return lines[i];
    }
    return null;
  }
  function restoreLogScroll(el, wasAtBottom, distBottom, anchorLine) {
    if (!el) return;
    if (wasAtBottom) {
      el.scrollTop = el.scrollHeight;
      return;
    }
    if (anchorLine) {
      var text = el.textContent || "";
      var pos = text.indexOf(anchorLine);
      if (pos >= 0) {
        var before = text.slice(0, pos);
        var lineIdx = (before.match(/\n/g) || []).length;
        el.scrollTop = Math.max(0, lineIdx * logPreLineHeight(el));
        return;
      }
    }
    el.scrollTop = Math.max(0, el.scrollHeight - el.clientHeight - distBottom);
  }
  function patchLogPre(el, text) {
    if (!el) return;
    var next = text || "";
    if (el.textContent === next) return;
    var distBottom = logPreDistanceFromBottom(el);
    var wasAtBottom = distBottom <= 32;
    var anchorLine = getLogScrollAnchor(el);
    el.textContent = next;
    restoreLogScroll(el, wasAtBottom, distBottom, anchorLine);
  }
  function logHasActiveFilter(key) {
    if ((searchQuery[key] || "").trim()) return true;
    return !!(filterLevel[key] || "").trim();
  }
  function filterDisplayLogLines(key, lines) {
    var level = (filterLevel[key] || "").toUpperCase();
    var q = (searchQuery[key] || "").toLowerCase();
    var out = (lines || []).slice();
    if (level === "WARN+") {
      var ewAll = errWrnLineSet(key);
      out = out.filter(function (l) {
        return ewAll.has(l) || /WARN|ERROR|Traceback|Exception|CRITICAL/i.test(l);
      });
    } else if (level === "ERROR") {
      var ewErr = errWrnLineSet(key, "ERROR");
      out = out.filter(function (l) {
        return ewErr.has(l) || /ERROR|Traceback|Exception|CRITICAL/i.test(l);
      });
    } else if (level === "WARN") {
      var ewWrn = errWrnLineSet(key, "WARN");
      out = out.filter(function (l) {
        return ewWrn.has(l) || /WARN/i.test(l);
      });
    } else if (level) {
      out = out.filter(function (l) { return l.indexOf(level) >= 0; });
    }
    if (q) out = out.filter(function (l) { return l.toLowerCase().indexOf(q) >= 0; });
    return out.slice(-logMaxLines);
  }
  function syncAutoscrollFromLogScroll(key) {
    var logEl = qs("#log-" + key);
    if (!logEl) return;
    var atBottom = logPreWasAtBottom(logEl);
    if (autoscroll[key] === atBottom) return;
    autoscroll[key] = atBottom;
    var autoscrollCb = qs("#autoscroll-" + key);
    if (autoscrollCb) autoscrollCb.checked = atBottom;
  }
  function normalizeLogLine(l) {
    if (typeof l === "string") return l.trim();
    return (((l && l.ts) || "") + " " + toLogText(l)).trim();
  }
  /** Panel hata/uyarı listesinde gösterilmeyecek gürültü (ring’de kalsa bile). */
  function isPanelErrWrnNoise(line) {
    var s = normalizeLogLine(line);
    if (!s) return true;
    if (/deque mutated during iteration/i.test(s)) return true;
    if (/\[TradeSync\]\s*Symbol cache empty/i.test(s)) return true;
    if (/wallet_refresh_attempt error_code=(?:ImportError|WALLET_MODULE_MISSING)/i.test(s)) return true;
    if (/get_price_map_flat/i.test(s) && /wallet_refresh/i.test(s)) return true;
    if (/home_wallet_refresh/i.test(s) && /\s-\sINFO\s-/i.test(s) && /\berror=/i.test(s)) return true;
    if (/\/api\/server\/manager\/restart\b/i.test(s) && /\s400\b/.test(s)) return true;
    if (/\/api\/stack\/restart\b/i.test(s) && /\s404\b/.test(s)) return true;
    if (/EADDRINUSE|Address already in use|error while attempting to bind/i.test(s) && /7999/.test(s)) return true;
    if (/\/api\/server\/manager\/restart\b/i.test(s) && /\s404\b/.test(s)) return true;
    if (/\/api\/issues\/summary\b/i.test(s) && /\s404\b/.test(s)) return true;
    if (/\/api\/security\//i.test(s) && /\s404\b/.test(s)) return true;
    if (/CSRF (?:double-submit mismatch|Origin mismatch|Referer mismatch)/i.test(s) && /\/api\/log-error/i.test(s)) return true;
    if (/POST \/api\/log-error HTTP\/1\.1"\s+403 Forbidden/i.test(s)) return true;
    return false;
  }
  function filterPanelErrWrn(arr) {
    return (arr || []).filter(function (l) { return !isPanelErrWrnNoise(l); });
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
    var errList = filterPanelErrWrn(Array.isArray(newErrors) ? newErrors : []);
    var wrnList = filterPanelErrWrn(Array.isArray(newWarns) ? newWarns : []);
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
      var errList = filterPanelErrWrn(d.errors || []);
      var wrnList = filterPanelErrWrn(d.warns || []);
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
    let lines = filterDisplayLogLines(key, mergedLogLinesFor(key));
    lines = lines.map(function (l) { return humanizeLogLineIfNeeded(l, key); });
    var logText = lines.join("\n") + (lines.length ? "\n" : "");
    patchLogPre(logEl, logText);
    logEl._logIncrementalOk = true;
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
    var added = [];
    lines.forEach(function (l) {
      var lineStr = normalizeLogLine(l);
      if (!lineStr) return;
      if (key === "html" && statsPattern.test(lineStr) && arr.length && arr[arr.length - 1] === lineStr) return;
      arr.push(lineStr);
      added.push(lineStr);
    });
    if (!added.length) return;
    var beforeLen = arr.length - added.length;
    var trimmed = Math.max(0, arr.length - logMaxLines);
    rawLogLines[key] = arr.slice(-logMaxLines);
    var logEl = qs("#log-" + key);
    if (!logEl) return;
    var atBottom = logPreWasAtBottom(logEl);
    if (!atBottom && trimmed === 0 && !logHasActiveFilter(key) && logEl._logIncrementalOk) {
      var displayAdded = filterDisplayLogLines(key, added);
      if (displayAdded.length) {
        var chunk = displayAdded.map(function (l) { return humanizeLogLineIfNeeded(l, key); }).join("\n") + "\n";
        var distBottom = logPreDistanceFromBottom(logEl);
        var cur = logEl.textContent || "";
        logEl.textContent = cur + (cur && !cur.endsWith("\n") ? "\n" : "") + chunk;
        logEl.scrollTop = Math.max(0, logEl.scrollHeight - logEl.clientHeight - distBottom);
        return;
      }
      return;
    }
    logEl._logIncrementalOk = false;
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
    if (tab === "html") { refreshMetrics(); refreshStatus(); fetchLogs("html"); }
    if (tab === "security") {
      refreshSecurity();
      securityPollIntervalId = setInterval(refreshSecurity, 1500);
    }
    if (tab === "incidents") { refreshIssues(true); startIncidentsPoll(); } else { stopIncidentsPoll(); }
    if (tab === "audit") { refreshAudit(true); startAuditPoll(); } else { stopAuditPoll(); }
    if (tab === "web" || tab === "engine" || tab === "manager" || tab === "html") refreshDiagnosis();
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

  function serviceActionButtonIds(key) {
    var ids = ["btn-overview-" + key + "-start", "btn-overview-" + key + "-stop"];
    if (key === "web") ids = ids.concat(["btnWebStart", "btnWebStop", "btnWebRestart"]);
    else if (key === "engine") ids = ids.concat(["btnEngineStart", "btnEngineStop", "btnEngineRestart"]);
    else if (key === "html") ids = ids.concat(["btnHtmlStart", "btnHtmlStop", "btnHtmlRestart"]);
    return ids.filter(function (id) { return qs("#" + id); });
  }

  function waitForManagerBack() {
    var attempts = 0;
    var poll = setInterval(function () {
      attempts += 1;
      fetch(API + "/api/status", { cache: "no-store" })
        .then(function (r) {
          if (r.ok) {
            clearInterval(poll);
            location.reload();
          }
        })
        .catch(function () {});
      if (attempts >= 90) clearInterval(poll);
    }, 1000);
  }

  function runManagerRestart() {
    if (!confirm("Tüm sistem yeniden başlatılacak: Manager (7999), Web (8000), Bot Engine ve HTML (8080).\nPanel 30–60 sn kesilebilir. Devam edilsin mi?")) return;
    var btnIds = ["btn-overview-manager-restart", "btnManagerRestart"].filter(function (id) { return qs("#" + id); });
    setButtonsLoading(btnIds, true);
    showActionFeedback("Tüm sistem yeniden başlatılıyor…", false);
    api("POST", "/api/stack/restart")
      .then(function () {
        waitForManagerBack();
      })
      .catch(function (e) {
        showActionFeedback("Hata: " + (e.message || String(e)), true);
        alert(e.message || String(e));
      })
      .finally(function () {
        setButtonsLoading(btnIds, false);
      });
  }

  function runServiceAction(key, action) {
    if (key === "manager") return;
    var btnIds = serviceActionButtonIds(key);
    setButtonsLoading(btnIds, true);
    showActionFeedback(key + " " + action + " işleniyor…", false);
    api("POST", "/api/server/" + key + "/" + action)
      .then(function (r) {
        refreshStatus();
        refreshMetrics();
        if (r.diagnosis) {
          var st = r.status && r.status[r.service];
          renderDiagnosis(r.service, r.diagnosis, !!(st && st.running), st);
        }
        refreshDiagnosis();
        showActionFeedback(key + " " + action + " tamam.", false);
      })
      .catch(function (e) {
        showActionFeedback("Hata: " + (e.message || String(e)), true);
        alert(e.message || String(e));
      })
      .finally(function () {
        setButtonsLoading(btnIds, false);
        refreshStatus();
        refreshMetrics();
      });
  }

  keys.forEach(function (k) {
    const lockCb = qs("#lock-" + k);
    if (lockCb) lockCb.addEventListener("change", function () {
      api("POST", "/api/locks", { web: k === "web" ? lockCb.checked : qs("#lock-web").checked, engine: k === "engine" ? lockCb.checked : qs("#lock-engine").checked }).then(refreshStatus);
    });
    if (k === "web" || k === "engine") {
      ["Start", "Stop", "Restart"].forEach(function (actionName) {
        const btn = qs("#btn" + (k === "web" ? "Web" : "Engine") + actionName);
        if (btn) btn.addEventListener("click", function () {
          if (btn.disabled) return;
          runServiceAction(k, actionName.toLowerCase());
        });
      });
    }
    if (k === "html") {
      var btnHtmlStart = qs("#btnHtmlStart");
      var btnHtmlStop = qs("#btnHtmlStop");
      var btnHtmlRestart = qs("#btnHtmlRestart");
      if (btnHtmlStart) btnHtmlStart.addEventListener("click", function () { runServiceAction("html", "start"); });
      if (btnHtmlStop) btnHtmlStop.addEventListener("click", function () { runServiceAction("html", "stop"); });
      if (btnHtmlRestart) btnHtmlRestart.addEventListener("click", function () { runServiceAction("html", "restart"); });
    }
    var ovStart = qs("#btn-overview-" + k + "-start");
    var ovStop = qs("#btn-overview-" + k + "-stop");
    if (ovStart && k !== "manager") ovStart.addEventListener("click", function () { runServiceAction(k, "start"); });
    if (ovStop && k !== "manager") ovStop.addEventListener("click", function () { runServiceAction(k, "stop"); });
    if (k === "manager") {
      var ovRestart = qs("#btn-overview-manager-restart");
      var tabRestart = qs("#btnManagerRestart");
      if (ovRestart) ovRestart.addEventListener("click", runManagerRestart);
      if (tabRestart) tabRestart.addEventListener("click", runManagerRestart);
    }
    const resetBtn = k === "manager" ? qs("#btnManagerReset") : k === "html" ? qs("#btnHtmlReset") : qs("#btn" + (k === "web" ? "Web" : "Engine") + "Reset");
    if (resetBtn) resetBtn.addEventListener("click", function () {
      if (!confirm(k.toUpperCase() + " logları sıfırlansın mı?")) return;
      api("POST", "/api/reset/" + k).then(function () { fetchLogs(k); refreshStatus(); refreshMetrics(); }).catch(function (e) { alert(e.message); });
    });
    const pauseCb = qs("#pause-" + k);
    if (pauseCb) pauseCb.addEventListener("change", function () { pause[k] = pauseCb.checked; });
    const autoscrollCb = qs("#autoscroll-" + k);
    if (autoscrollCb) autoscrollCb.addEventListener("change", function () { autoscroll[k] = autoscrollCb.checked; });
    const logPre = qs("#log-" + k);
    if (logPre) {
      logPre.addEventListener("scroll", function () { syncAutoscrollFromLogScroll(k); }, { passive: true });
    }
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

  function disableGlobalBtns(disabled) {
    setButtonsLoading(globalBtnIds, disabled);
    setGlobalHeaderBusy(disabled);
  }
  function runGlobalAction(path, label) {
    if (globalActionBusy) return;
    if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
    globalActionBusy = true;
    disableGlobalBtns(true);
    clearGlobalActionWatchdog();
    globalActionWatchdogTimer = setTimeout(function () {
      showActionFeedback(label + " yanıt gecikti — düğmeler serbest bırakıldı.", true);
      releaseGlobalActionUi();
    }, 90000);
    showActionFeedback(label + " işleniyor…", false);
    api("POST", path)
      .then(function (r) {
        if (r && r.busy) {
          showActionFeedback(r.detail || "Başka bir toplu işlem sürüyor.", true);
          return;
        }
        if (r && r.pending) {
          showActionFeedback(label + " arka planda — durum güncelleniyor…", false);
          pollAfterGlobalAction(60);
          return;
        }
        var applied = (r.applied || []).join(", ") || "—";
        var skipped = (r.skipped || []).join(", ") || "—";
        showActionFeedback("Uygulandı: " + applied + (skipped !== "—" ? " · Atlandı: " + skipped : ""), false);
        pollAfterGlobalAction(30);
      })
      .catch(function (e) {
        showActionFeedback("Hata: " + (e.message || String(e)), true);
        alert(e.message || String(e));
      })
      .finally(function () {
        releaseGlobalActionUi();
        refreshStatus();
        refreshMetrics();
      });
  }
  qs("#btnGlobalStart").addEventListener("click", function () { runGlobalAction("/api/global/start", "Tümünü başlat"); });
  qs("#btnGlobalStop").addEventListener("click", function () {
    if (!confirm("Web, engine ve HTML servisleri durdurulsun mu? (Yönetici çalışmaya devam eder.)")) return;
    runGlobalAction("/api/global/stop", "Tümünü durdur");
  });
  qs("#btnGlobalRestart").addEventListener("click", function () {
    if (!confirm("Web, engine ve HTML yeniden başlatılsın mı?")) return;
    runGlobalAction("/api/global/restart", "Tümünü yeniden başlat");
  });
  qs("#btnResetAll").addEventListener("click", function () {
    if (!confirm("Tüm servis log ring buffer'ları sıfırlansın mı?")) return;
    api("POST", "/api/reset/all").then(function () { keys.forEach(fetchLogs); refreshStatus(); refreshMetrics(); showActionFeedback("Tüm loglar sıfırlandı.", false); }).catch(function (e) { alert(e.message); });
  });

  var securityIpList = qs("#security-ip-list");
  if (securityIpList) {
    securityIpList.addEventListener("click", function (e) {
      var banBtn = e.target.closest(".sec-ip-ban");
      var unbanBtn = e.target.closest(".sec-ip-unban");
      if (banBtn) securityBanIp(banBtn.getAttribute("data-ip"));
      else if (unbanBtn) securityUnbanIp(unbanBtn.getAttribute("data-ip"));
    });
  }

  window.addEventListener("pageshow", function () { healStuckGlobalActionUi(false); });
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) healStuckGlobalActionUi(false);
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
    if (!lastMetrics) return;
    if (lastMetrics.system && (lastMetrics.system.session_started_at != null || lastMetrics.system.uptime_s != null)) {
      setTextIfChanged(qs("#overview-system-uptime"), formatUptime(getLiveSystemUptime(), true) || "—");
    }
    if (!lastMetrics.status) return;
    keys.forEach(function (k) {
      var st = lastMetrics.status[k] || {};
      setStatus(k, st);
      if (!st.running) return;
      var proc = lastMetrics[k] || {};
      var uptimeText = formatUptime(getServiceUptime(k, st, proc, true)) || "—";
      setTextIfChanged(qs("#overview-" + k + "-uptime"), uptimeText);
      setTextIfChanged(qs("#tab-" + k + "-uptime"), uptimeText);
    });
  }, 1000);
})();
