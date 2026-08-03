#!/usr/bin/env python3
import json
import os
import shlex
import subprocess
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


HOST = os.environ.get("STATUS_DASHBOARD_HOST", "127.0.0.1")
PORT = int(os.environ.get("STATUS_DASHBOARD_PORT", "18082"))
SERVER_HOST = os.environ.get("SERVER_HOST", "178.210.168.102")
SERVER_USER = os.environ.get("SERVER_USER", "root")
SSH_PORT = os.environ.get("SSH_PORT", "22666")
KEY_FILE = os.path.expandvars(os.environ.get("KEY_FILE", os.path.expanduser("~/.ssh/aysegul_sunucu_ed25519")))
APP_NAME = os.environ.get("APP_NAME", "final1")
REMOTE_WEB_PORT = os.environ.get("REMOTE_WEB_PORT", "8000")


REMOTE_COLLECTOR = r"""
import json, os, shutil, socket, subprocess, time, urllib.request

def run(cmd, timeout=4):
    try:
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
        return {"code": p.returncode, "out": p.stdout.strip(), "err": p.stderr.strip()}
    except Exception as exc:
        return {"code": 99, "out": "", "err": str(exc)}

def meminfo():
    data = {}
    with open("/proc/meminfo", "r", encoding="utf-8") as fh:
        for line in fh:
            key, value = line.split(":", 1)
            data[key] = int(value.strip().split()[0])
    total = data.get("MemTotal", 0)
    available = data.get("MemAvailable", 0)
    used = max(total - available, 0)
    swap_total = data.get("SwapTotal", 0)
    swap_free = data.get("SwapFree", 0)
    return {
        "total_mb": round(total / 1024),
        "used_mb": round(used / 1024),
        "available_mb": round(available / 1024),
        "percent": round((used / total) * 100, 1) if total else 0,
        "swap_total_mb": round(swap_total / 1024),
        "swap_used_mb": round(max(swap_total - swap_free, 0) / 1024),
    }

def disk(path):
    try:
        usage = shutil.disk_usage(path)
        return {"path": path, "total_gb": round(usage.total / (1024**3), 1), "used_gb": round(usage.used / (1024**3), 1), "percent": round((usage.used / usage.total) * 100, 1)}
    except Exception as exc:
        return {"path": path, "error": str(exc), "percent": 0}

def health():
    try:
        with urllib.request.urlopen("http://127.0.0.1:%s/api/health", timeout=4) as resp:
            body = resp.read(16000).decode("utf-8", "replace")
            return json.loads(body)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

services = ["final1-web", "final1-worker", "final1-manager", "aysegul", "kpss", "nginx"]
service_map = {}
service_memory = {}
for svc in services:
    result = run(["systemctl", "is-active", svc])
    service_map[svc] = result["out"] or result["err"] or "unknown"
    memory = run(["systemctl", "show", svc, "-p", "MemoryCurrent", "--value"])
    try:
        service_memory[svc] = round(int(memory["out"]) / (1024**2))
    except (TypeError, ValueError):
        service_memory[svc] = 0

load_raw = open("/proc/loadavg", "r", encoding="utf-8").read().split()
uptime_seconds = int(float(open("/proc/uptime", "r", encoding="utf-8").read().split()[0]))
cpus = os.cpu_count() or 1
ports = run(["ss", "-tln"])

out = {
    "ok": True,
    "host": socket.gethostname(),
    "time": int(time.time()),
    "uptime": run(["uptime", "-p"])["out"],
    "uptime_seconds": uptime_seconds,
    "services": service_map,
    "service_memory_mb": service_memory,
    "load": {"one": float(load_raw[0]), "five": float(load_raw[1]), "fifteen": float(load_raw[2]), "cpus": cpus, "percent": round(min(float(load_raw[0]) / cpus * 100, 100), 1)},
    "memory": meminfo(),
    "disks": [disk("/"), disk("/opt"), disk("/var/lib/final1")],
    "health": health(),
    "ports": [line for line in ports["out"].splitlines() if any((":%s " % p) in line for p in ["80", "443", "8000", "8081", "8082", "4001", "4002"])],
}
print(json.dumps(out, ensure_ascii=False))
"""


HTML = """<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Final1 Sunucu Durumu</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --line: #dde2ea;
      --text: #17202a;
      --muted: #667085;
      --good: #1f8a5b;
      --bad: #c13b3a;
      --warn: #b7791f;
      --bar: #2f6f9f;
      --bar2: #5b8c5a;
    }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: var(--bg); color: var(--text); }
    main { width: min(1120px, calc(100vw - 32px)); margin: 24px auto 40px; }
    header { display: flex; align-items: end; justify-content: space-between; gap: 16px; margin-bottom: 18px; }
    h1 { font-size: 24px; line-height: 1.2; margin: 0; font-weight: 700; letter-spacing: 0; }
    .sub { color: var(--muted); font-size: 13px; margin-top: 6px; }
    .grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
    .span2 { grid-column: span 2; }
    .card { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 14px; min-height: 118px; }
    .title { color: var(--muted); font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0; margin-bottom: 10px; }
    .value { font-size: 28px; font-weight: 750; line-height: 1; }
    .small { font-size: 12px; color: var(--muted); margin-top: 8px; overflow-wrap: anywhere; }
    .bar { height: 9px; border-radius: 999px; background: #e8edf3; overflow: hidden; margin-top: 12px; }
    .bar > span { display: block; height: 100%; width: 0; background: var(--bar); border-radius: inherit; transition: width .25s ease; }
    .list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .pill { display: flex; align-items: center; justify-content: space-between; gap: 10px; border: 1px solid var(--line); border-radius: 8px; padding: 9px 10px; min-height: 38px; }
    .dot { width: 9px; height: 9px; border-radius: 999px; background: var(--bad); flex: 0 0 auto; }
    .active .dot { background: var(--good); }
    .name { font-size: 13px; font-weight: 650; overflow-wrap: anywhere; }
    .state { font-size: 12px; color: var(--muted); }
    pre { margin: 0; white-space: pre-wrap; font-size: 12px; color: var(--muted); max-height: 150px; overflow: auto; }
    .error { border-color: #e5a6a6; color: var(--bad); }
    @media (max-width: 880px) { .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
    @media (max-width: 560px) { main { width: min(100vw - 20px, 1120px); margin-top: 14px; } header { display: block; } .grid { grid-template-columns: 1fr; } .span2 { grid-column: auto; } .list { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>Final1 Sunucu Durumu</h1>
        <div class="sub" id="meta">Bağlanıyor...</div>
      </div>
      <div class="sub">Otomatik yenileme: 1 sn</div>
    </header>
    <section class="grid">
      <div class="card"><div class="title">Uygulama</div><div class="value" id="app">-</div><div class="small" id="appDetail">-</div></div>
      <div class="card"><div class="title">CPU Yükü</div><div class="value" id="cpu">-</div><div class="bar"><span id="cpuBar"></span></div><div class="small" id="cpuDetail">-</div></div>
      <div class="card"><div class="title">Bellek</div><div class="value" id="mem">-</div><div class="bar"><span id="memBar"></span></div><div class="small" id="memDetail">-</div></div>
      <div class="card"><div class="title">Çalışma Süresi</div><div class="value" id="uptime">-</div><div class="small">Sunucunun açık kalma süresi</div></div>
      <div class="card span2"><div class="title">Servisler</div><div class="list" id="services"></div></div>
      <div class="card span2"><div class="title">Diskler</div><div id="disks"></div></div>
      <div class="card span2"><div class="title">Sağlık Yanıtı</div><pre id="health">-</pre></div>
      <div class="card span2"><div class="title">Dinlenen Portlar</div><pre id="ports">-</pre></div>
    </section>
  </main>
  <script>
    const pct = (v) => `${Math.max(0, Math.min(100, Number(v) || 0)).toFixed(1)}%`;
    function formatUptime(seconds) {
      const totalHours = Math.max(0, Math.floor((Number(seconds) || 0) / 3600));
      const totalDays = Math.floor(totalHours / 24);
      if (totalDays >= 30) {
        return `${Math.floor(totalDays / 30)} ay ${totalDays % 30} gün`;
      }
      return `${totalDays} gün ${totalHours % 24} saat`;
    }
    function barLine(label, percent, detail) {
      return `<div class="small" style="margin-top:10px;display:flex;justify-content:space-between;gap:8px"><strong>${label}</strong><span>${detail}</span></div><div class="bar"><span style="width:${pct(percent)}"></span></div>`;
    }
    function render(data) {
      if (!data.ok) throw new Error(data.error || "Sunucu okunamadı");
      document.getElementById("meta").textContent = `${data.host} | ${new Date(data.time * 1000).toLocaleString("tr-TR")}`;
      const appOk = data.health && data.health.ok;
      document.getElementById("app").textContent = appOk ? "Sağlıklı" : "Uyarı";
      document.getElementById("app").style.color = appOk ? "var(--good)" : "var(--warn)";
      document.getElementById("appDetail").textContent = data.health && data.health.db ? `DB: ${data.health.db} | Worker: ${data.health.worker_running}` : "Sağlık bilgisi sınırlı";
      document.getElementById("cpu").textContent = pct(data.load.percent);
      document.getElementById("cpuBar").style.width = pct(data.load.percent);
      document.getElementById("cpuDetail").textContent = `1 dk: ${data.load.one} | CPU: ${data.load.cpus}`;
      document.getElementById("mem").textContent = pct(data.memory.percent);
      document.getElementById("memBar").style.width = pct(data.memory.percent);
      const swap = data.memory.swap_total_mb ? ` | Swap: ${data.memory.swap_used_mb} / ${data.memory.swap_total_mb} MB` : "";
      document.getElementById("memDetail").textContent = `${data.memory.used_mb} / ${data.memory.total_mb} MB | Kullanılabilir: ${data.memory.available_mb} MB${swap}`;
      document.getElementById("uptime").textContent = formatUptime(data.uptime_seconds);
      document.getElementById("services").innerHTML = Object.entries(data.services).map(([name, state]) => {
        const active = state === "active";
        const memory = Number(data.service_memory_mb && data.service_memory_mb[name]) || 0;
        const detail = memory ? `${state} | ${memory} MB` : state;
        return `<div class="pill ${active ? "active" : ""}"><span style="display:flex;align-items:center;gap:8px"><i class="dot"></i><span class="name">${name}</span></span><span class="state">${detail}</span></div>`;
      }).join("");
      document.getElementById("disks").innerHTML = data.disks.map(d => barLine(d.path, d.percent, d.error ? d.error : `${d.used_gb} / ${d.total_gb} GB`)).join("");
      document.getElementById("health").textContent = JSON.stringify(data.health, null, 2);
      document.getElementById("ports").textContent = data.ports.length ? data.ports.join("\\n") : "Kritik port kaydı yok";
    }
    let refreshing = false;
    async function refresh() {
      if (refreshing) return;
      refreshing = true;
      try {
        const res = await fetch("/api/status", { cache: "no-store" });
        render(await res.json());
      } catch (err) {
        document.getElementById("meta").textContent = "Bağlantı hatası";
        document.querySelector(".grid").classList.add("error");
        document.getElementById("health").textContent = err.message;
      } finally {
        refreshing = false;
      }
    }
    refresh();
    setInterval(refresh, 1000);
  </script>
</body>
</html>
"""


def collect_status():
    remote_cmd = "python3 -c " + shlex.quote(REMOTE_COLLECTOR.replace("%s", REMOTE_WEB_PORT, 1))
    cmd = [
        "ssh",
        "-p",
        SSH_PORT,
        "-i",
        KEY_FILE,
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "ForwardAgent=no",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=8",
        f"{SERVER_USER}@{SERVER_HOST}",
        remote_cmd,
    ]
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=12)
    except Exception as exc:
        return {"ok": False, "error": str(exc), "time": int(time.time())}
    if proc.returncode != 0:
        return {"ok": False, "error": proc.stderr.strip() or proc.stdout.strip(), "time": int(time.time())}
    try:
        return json.loads(proc.stdout)
    except Exception as exc:
        return {"ok": False, "error": f"JSON okunamadı: {exc}", "raw": proc.stdout[-2000:], "time": int(time.time())}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, content_type):
        data = body.encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            # The browser may close an in-flight request during refresh or exit.
            return

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, HTML, "text/html; charset=utf-8")
        elif self.path == "/api/status":
            self._send(200, json.dumps(collect_status(), ensure_ascii=False), "application/json; charset=utf-8")
        else:
            self._send(404, "Yok", "text/plain; charset=utf-8")

    def log_message(self, fmt, *args):
        return


class QuietThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        error = sys.exc_info()[1]
        if isinstance(error, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
            return
        super().handle_error(request, client_address)


def main():
    url = f"http://{HOST}:{PORT}"
    print(f"Final1 sunucu durum paneli: {url}")
    if os.environ.get("NO_OPEN") != "1":
        try:
            webbrowser.open(url)
        except Exception:
            pass
    QuietThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
