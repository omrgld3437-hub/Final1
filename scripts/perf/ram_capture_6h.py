#!/usr/bin/env python3
"""
6 saatlik kapsamlı RAM capture + senaryo koşucu.

Başlat (web+worker capture + senaryo arka plan):
  cd /Users/omeraltin/Desktop/final1
  python3 scripts/perf/ram_capture_6h.py --start

Durum:
  python3 scripts/perf/ram_capture_6h.py --status

Analiz (oturum bitince):
  python3 scripts/perf/ram_capture_6h.py --analyze --session <id>

Ortam (opsiyonel auth senaryoları):
  RAM_TEST_AUTH_TOKEN=...   veya RAM_TEST_PHONE + RAM_TEST_PASSWORD
  RAM_TEST_ACCOUNT_ID=3 RAM_TEST_BOT_ID=2
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_LOGS = _PROJECT_ROOT / "logs"
_RUN = _PROJECT_ROOT / ".run"
_DURATION_SEC = 6 * 3600  # 21600
_CAPTURE_INTERVAL = 60
_PROBE_INTERVAL = 120
_PHASE_INTERVAL_SEC = 25 * 60  # 25 dk × 14 ≈ 6 saat


def _session_id() -> str:
    return "ram6h_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _py() -> str:
    venv = _PROJECT_ROOT / ".venv" / "bin" / "python"
    return str(venv) if venv.is_file() else sys.executable


def discover_targets() -> Dict[str, Any]:
    """Çalışan bot + hesap — mevcut botu bozmaz, yalnızca okur."""
    out: Dict[str, Any] = {
        "account_id": None,
        "bot_id": None,
        "symbol": None,
        "status": None,
    }
    env_aid = os.getenv("RAM_TEST_ACCOUNT_ID", "").strip()
    env_bid = os.getenv("RAM_TEST_BOT_ID", "").strip()
    if env_aid.isdigit():
        out["account_id"] = int(env_aid)
    if env_bid.isdigit():
        out["bot_id"] = int(env_bid)
    code = r"""
import json, os
from app.db.session import SessionLocal
from app.db.models import Bot
out = {}
db = SessionLocal()
try:
    q = db.query(Bot).filter(Bot.status == "running")
    bid = os.getenv("RAM_TEST_BOT_ID", "").strip()
    bot = q.filter(Bot.id == int(bid)).first() if bid.isdigit() else q.order_by(Bot.id.asc()).first()
    if bot:
        out = {"bot_id": int(bot.id), "account_id": int(bot.account_id), "symbol": (bot.symbol or "").strip(), "status": bot.status}
finally:
    db.close()
print(json.dumps(out))
"""
    try:
        r = subprocess.run(
            [_py(), "-c", code],
            cwd=str(_PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "RAM_TEST_BOT_ID": env_bid},
        )
        if r.returncode == 0 and r.stdout.strip():
            data = json.loads(r.stdout.strip())
            if data.get("bot_id"):
                out["bot_id"] = data["bot_id"]
                out["account_id"] = data["account_id"]
                out["symbol"] = data.get("symbol")
                out["status"] = data.get("status")
        elif r.stderr:
            out["discover_error"] = r.stderr.strip()[:200]
    except Exception as e:
        out["discover_error"] = str(e)
    if not out.get("bot_id") and not env_aid.isdigit():
        out.setdefault("discover_error", "no_running_bot")
    return out


class ScenarioHttpClient:
    """httpx.Client oturumu — login cookie veya Bearer."""

    def __init__(self, base_url: str, token: Optional[str] = None):
        import httpx

        self.base = base_url.rstrip("/")
        self.token = token
        self._client = httpx.Client(timeout=120.0, follow_redirects=True)

    def close(self) -> None:
        self._client.close()

    def _headers(self) -> Dict[str, str]:
        h = {"Accept": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        timeout: float = 120.0,
    ) -> Dict[str, Any]:
        url = path if path.startswith("http") else f"{self.base}{path}"
        t0 = time.perf_counter()
        result: Dict[str, Any] = {
            "method": method,
            "path": path,
            "url": url,
        }
        try:
            r = self._client.request(
                method,
                url,
                params=params,
                json=json_body,
                headers=self._headers(),
                timeout=timeout,
            )
            ms = round((time.perf_counter() - t0) * 1000, 2)
            result["status"] = r.status_code
            result["duration_ms"] = ms
            result["response_bytes"] = len(r.content or b"")
            if r.status_code == 401:
                result["auth_required"] = True
            if r.status_code >= 400:
                result["error_preview"] = (r.text or "")[:200]
            else:
                try:
                    body = r.json()
                    if isinstance(body, dict):
                        result["response_keys"] = list(body.keys())[:20]
                        if "meta" in body and isinstance(body["meta"], dict):
                            result["meta"] = body["meta"]
                except Exception:
                    pass
        except Exception as e:
            result["duration_ms"] = round((time.perf_counter() - t0) * 1000, 2)
            result["error"] = str(e)[:300]
        return result


def create_http_client(base_url: str) -> Tuple[ScenarioHttpClient, bool]:
    """(client, has_auth). Token env veya login cookie."""
    tok = os.getenv("RAM_TEST_AUTH_TOKEN", "").strip()
    if tok:
        return ScenarioHttpClient(base_url, token=tok), True
    phone = os.getenv("RAM_TEST_PHONE", "").strip()
    password = os.getenv("RAM_TEST_PASSWORD", "")
    client = ScenarioHttpClient(base_url)
    if not phone or not password:
        return client, False
    try:
        r = client._client.post(
            f"{base_url.rstrip('/')}/api/auth/login",
            json={"phone": phone, "password": password},
        )
        if r.status_code == 200:
            data = r.json()
            t = data.get("token")
            if t:
                client.token = t
            return client, True
    except Exception:
        pass
    return client, False


def run_one_scenario(
    client: ScenarioHttpClient,
    session_id: str,
    scenario_id: str,
    account_id: int,
    bot_id: int,
    phase: int,
) -> Dict[str, Any]:
    from app.observability.ram_capture_scenarios import (
        append_scenario_record,
        get_scenario_by_id,
    )

    scen = get_scenario_by_id(scenario_id, account_id, bot_id)
    if not scen:
        rec = {
            "kind": "scenario_skip",
            "scenario_id": scenario_id,
            "reason": "unknown_scenario",
        }
        append_scenario_record(session_id, rec)
        return rec

    steps_out: List[Dict[str, Any]] = []
    auth_blocked = False
    for step in scen.steps:
        for rep in range(max(1, step.repeat)):
            if (
                auth_blocked
                and step.path.startswith("/api/")
                and "health" not in step.path
                and "config/public" not in step.path
                and not step.path.startswith("/api/data")
            ):
                steps_out.append(
                    {"label": step.label, "skipped": True, "reason": "no_auth"}
                )
                continue
            res = client.request(
                step.method,
                step.path,
                params=step.params,
                json_body=step.json_body,
            )
            res["label"] = step.label
            res["repeat_index"] = rep
            steps_out.append(res)
            if res.get("status") == 401:
                auth_blocked = True

    record = {
        "kind": "scenario_run",
        "scenario_id": scen.id,
        "scenario_title": scen.title,
        "phase": phase,
        "account_id": account_id,
        "bot_id": bot_id,
        "steps": steps_out,
        "step_count": len(steps_out),
        "auth_blocked": auth_blocked,
    }
    append_scenario_record(session_id, record)
    time.sleep(scen.pause_after_sec)
    return record


def cmd_run_scenarios(session_id: str, duration_sec: int) -> int:
    from app.observability.ram_capture_scenarios import (
        append_scenario_record,
        scenario_log_path,
        scenario_schedule_6h,
    )

    base = os.getenv("WEB_INTERNAL_URL", "http://127.0.0.1:8000")
    targets = discover_targets()
    account_id = targets.get("account_id") or 0
    bot_id = targets.get("bot_id") or 0
    client, has_auth = create_http_client(base)

    schedule = scenario_schedule_6h()
    append_scenario_record(
        session_id,
        {
            "kind": "runner_start",
            "duration_sec": duration_sec,
            "phase_interval_sec": _PHASE_INTERVAL_SEC,
            "schedule": schedule,
            "targets": targets,
            "has_auth": has_auth,
            "base_url": base,
            "scenario_log": str(scenario_log_path(session_id)),
        },
    )

    end_at = time.time() + duration_sec
    phase = 0
    try:
        while time.time() < end_at:
            sid = schedule[phase % len(schedule)]
            try:
                if account_id and bot_id:
                    run_one_scenario(client, session_id, sid, account_id, bot_id, phase)
                else:
                    run_one_scenario(client, session_id, "S00_baseline", 0, 0, phase)
                    run_one_scenario(
                        client, session_id, "S01_market_public", 0, 0, phase
                    )
            except Exception as e:
                append_scenario_record(
                    session_id,
                    {
                        "kind": "scenario_error",
                        "phase": phase,
                        "scenario_id": sid,
                        "error": str(e),
                    },
                )
            phase += 1
            sleep_sec = min(_PHASE_INTERVAL_SEC, max(0, end_at - time.time()))
            if sleep_sec <= 0:
                break
            append_scenario_record(
                session_id,
                {
                    "kind": "phase_sleep",
                    "phase": phase,
                    "sleep_sec": sleep_sec,
                    "next_scenario": schedule[phase % len(schedule)],
                },
            )
            time.sleep(sleep_sec)
    finally:
        client.close()

    append_scenario_record(
        session_id, {"kind": "runner_end", "phases_completed": phase}
    )
    return 0


def restart_web_worker_capture(session_id: str) -> None:
    py = _py()
    web_pid = _RUN / "web.pid"
    worker_pid = _RUN / "worker.pid"
    for pf in (web_pid, worker_pid):
        if pf.exists():
            try:
                os.kill(int(pf.read_text().strip()), 15)
            except (ProcessLookupError, ValueError, OSError):
                pass
            time.sleep(2)
            try:
                if pf.exists():
                    os.kill(int(pf.read_text().strip()), 9)
            except (ProcessLookupError, ValueError, OSError):
                pass
            pf.unlink(missing_ok=True)
    subprocess.run(
        ["bash", "-c", "lsof -ti:8000 | xargs kill -KILL 2>/dev/null || true"],
        check=False,
    )

    env = _ram_capture_env(session_id)
    _LOGS.mkdir(parents=True, exist_ok=True)
    _RUN.mkdir(parents=True, exist_ok=True)
    with open(_LOGS / "web.log", "a", encoding="utf-8") as wf:
        subprocess.Popen(
            [
                py,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
                "--workers",
                "2",
                "--loop",
                "uvloop",
                "--http",
                "httptools",
                "--log-level",
                "info",
            ],
            stdout=wf,
            stderr=subprocess.STDOUT,
            cwd=str(_PROJECT_ROOT),
            env=env,
            start_new_session=True,
        )
    web_pid.write_text("")  # placeholder - get pid from lsof
    time.sleep(2)
    r = subprocess.run(["lsof", "-ti:8000"], capture_output=True, text=True)
    if r.stdout.strip():
        web_pid.write_text(r.stdout.strip().split()[0] + "\n")
    with open(_LOGS / "worker.log", "a", encoding="utf-8") as wf:
        p = subprocess.Popen(
            [py, "-m", "app.botengine.worker_main"],
            stdout=wf,
            stderr=subprocess.STDOUT,
            cwd=str(_PROJECT_ROOT),
            env=env,
            start_new_session=True,
        )
        worker_pid.write_text(str(p.pid))


def _ram_capture_env(session_id: str) -> Dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "RAM_CAPTURE": "1",
            "RAM_CAPTURE_SESSION": session_id,
            "RAM_CAPTURE_DURATION": str(_DURATION_SEC),
            "RAM_CAPTURE_INTERVAL": str(_CAPTURE_INTERVAL),
            "RAM_PROBE": "1",
            "RAM_PROBE_ENABLED": "1",
            "RAM_PROBE_INTERVAL": str(_PROBE_INTERVAL),
            "RAM_CAPTURE_ALSO_PROBE": "1",
            "MARKET_SYNC_FROM_WEB": "1",
        }
    )
    return env


def restart_worker_capture(session_id: str) -> int:
    """Yalnızca worker — aynı RAM oturumu, web/senaryo koşucu dokunulmaz."""
    py = _py()
    worker_pid = _RUN / "worker.pid"
    if worker_pid.exists():
        try:
            os.kill(int(worker_pid.read_text().strip()), 15)
        except (ProcessLookupError, ValueError, OSError):
            pass
        time.sleep(2)
        try:
            if worker_pid.exists():
                os.kill(int(worker_pid.read_text().strip()), 9)
        except (ProcessLookupError, ValueError, OSError):
            pass
        worker_pid.unlink(missing_ok=True)
    _LOGS.mkdir(parents=True, exist_ok=True)
    _RUN.mkdir(parents=True, exist_ok=True)
    with open(_LOGS / "worker.log", "a", encoding="utf-8") as wf:
        wf.write(
            f"\n--- worker restart {datetime.now(timezone.utc).isoformat()} session={session_id} ---\n"
        )
        p = subprocess.Popen(
            [py, "-m", "app.botengine.worker_main"],
            stdout=wf,
            stderr=subprocess.STDOUT,
            cwd=str(_PROJECT_ROOT),
            env=_ram_capture_env(session_id),
            start_new_session=True,
        )
    worker_pid.write_text(str(p.pid))
    return p.pid


def cmd_restart_worker() -> int:
    mf = _LOGS / "ram_capture_session.json"
    if not mf.exists():
        print("Aktif oturum yok — --start ile başlatın.")
        return 1
    data = json.loads(mf.read_text(encoding="utf-8"))
    if data.get("complete"):
        print("Oturum tamamlanmış — worker restart atlandı.")
        return 1
    sid = data.get("session_id", "")
    if not sid:
        print("session_id eksik")
        return 1
    pid = restart_worker_capture(sid)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    data.setdefault("events", []).append(
        {"kind": "worker_restart", "at": data["updated_at"], "pid": pid}
    )
    mf.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Worker yeniden başlatıldı (RAM oturumu korundu): PID={pid} session={sid}")
    return 0


def cmd_start() -> int:
    sid = _session_id()
    targets = discover_targets()
    print("=== RAM 6h Capture Başlatılıyor ===")
    print(f"Session: {sid}")
    print(
        f"Süre: {_DURATION_SEC // 3600} saat | snapshot: {_CAPTURE_INTERVAL}s | probe: {_PROBE_INTERVAL}s"
    )
    print(f"Hedef bot: {targets}")
    print()
    print(
        "Web + worker RAM_CAPTURE ile yeniden başlatılıyor (bot DB status=running kalır)..."
    )
    restart_web_worker_capture(sid)
    time.sleep(5)
    manifest = {
        "session_id": sid,
        "mode": "ram6h",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "duration_sec": _DURATION_SEC,
        "complete": False,
        "targets": targets,
        "files": {
            "web": str(_LOGS / f"ram_capture_{sid}_web.jsonl"),
            "worker": str(_LOGS / f"ram_capture_{sid}_worker.jsonl"),
            "scenarios": str(_LOGS / f"ram_scenario_{sid}.jsonl"),
            "runner_log": str(_LOGS / "ram_scenario_runner.log"),
        },
    }
    (_LOGS / "ram_capture_session.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    runner_log = _LOGS / "ram_scenario_runner.log"
    with open(runner_log, "a", encoding="utf-8") as lf:
        lf.write(
            f"\n--- runner start {datetime.now(timezone.utc).isoformat()} session={sid} ---\n"
        )
        runner_env = os.environ.copy()
        runner_env["RAM_TEST_ACCOUNT_ID"] = str(
            targets.get("account_id") or os.getenv("RAM_TEST_ACCOUNT_ID", "3")
        )
        runner_env["RAM_TEST_BOT_ID"] = str(
            targets.get("bot_id") or os.getenv("RAM_TEST_BOT_ID", "2")
        )
        proc = subprocess.Popen(
            [
                _py(),
                str(_SCRIPT_DIR / "ram_capture_6h.py"),
                "--run-scenarios",
                "--session",
                sid,
            ],
            stdout=lf,
            stderr=subprocess.STDOUT,
            cwd=str(_PROJECT_ROOT),
            env=runner_env,
            start_new_session=True,
        )
    (_RUN / "ram6h_runner.pid").write_text(str(proc.pid))
    print(f"Senaryo koşucu PID: {proc.pid}")
    print("Ham veri:")
    for k, v in manifest["files"].items():
        print(f"  {k}: {v}")
    print()
    print("Bot çalışmaya devam eder. 6 saat sonra:")
    print(f"  python3 scripts/perf/ram_capture_6h.py --analyze --session {sid}")
    return 0


def cmd_status() -> int:
    mf = _LOGS / "ram_capture_session.json"
    if mf.exists():
        print(mf.read_text(encoding="utf-8"))
    rp = _RUN / "ram6h_runner.pid"
    if rp.exists():
        print("runner_pid:", rp.read_text().strip())
    sid = ""
    if mf.exists():
        sid = json.loads(mf.read_text()).get("session_id", "")
    if sid:
        for pattern in [
            f"ram_capture_{sid}_web.jsonl",
            f"ram_capture_{sid}_worker.jsonl",
            f"ram_scenario_{sid}.jsonl",
        ]:
            p = _LOGS / pattern
            if p.exists():
                n = sum(1 for _ in open(p, encoding="utf-8", errors="replace"))
                print(f"  {pattern}: {n} lines ({p.stat().st_size // 1024} KB)")
    return 0


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def cmd_ensure() -> int:
    """Koşucu/web/worker ölmüşse oturum bitene kadar yeniden başlat (capture oturumu açıkken)."""
    mf = _LOGS / "ram_capture_session.json"
    if not mf.exists():
        print("Aktif oturum yok — --start ile başlatın.")
        return 1
    data = json.loads(mf.read_text(encoding="utf-8"))
    if data.get("complete"):
        print("Oturum zaten tamamlanmış.")
        return 0
    sid = data.get("session_id", "")
    restarted = []
    wp = _RUN / "web.pid"
    ep = _RUN / "worker.pid"
    if wp.exists() and not _pid_alive(int(wp.read_text().strip() or 0)):
        restart_web_worker_capture(sid)
        restarted.append("web+worker")
    elif ep.exists() and not _pid_alive(int(ep.read_text().strip() or 0)):
        restart_web_worker_capture(sid)
        restarted.append("web+worker")
    rp = _RUN / "ram6h_runner.pid"
    runner_dead = True
    if rp.exists():
        runner_dead = not _pid_alive(int(rp.read_text().strip() or 0))
    if runner_dead and sid:
        runner_log = _LOGS / "ram_scenario_runner.log"
        targets = data.get("targets") or discover_targets()
        runner_env = os.environ.copy()
        runner_env["RAM_TEST_ACCOUNT_ID"] = str(targets.get("account_id") or 3)
        runner_env["RAM_TEST_BOT_ID"] = str(targets.get("bot_id") or 2)
        with open(runner_log, "a", encoding="utf-8") as lf:
            lf.write(
                f"\n--- runner restart {datetime.now(timezone.utc).isoformat()} ---\n"
            )
            p = subprocess.Popen(
                [
                    _py(),
                    str(_SCRIPT_DIR / "ram_capture_6h.py"),
                    "--run-scenarios",
                    "--session",
                    sid,
                ],
                stdout=lf,
                stderr=subprocess.STDOUT,
                cwd=str(_PROJECT_ROOT),
                env=runner_env,
                start_new_session=True,
            )
        rp.write_text(str(p.pid))
        restarted.append("scenario_runner")
    if restarted:
        print("Yeniden başlatıldı:", ", ".join(restarted))
    else:
        print("Tüm süreçler çalışıyor — session", sid)
    return 0


def cmd_watchdog() -> int:
    """5 dk'da bir --ensure (6 saat oturum boyunca arka plan)."""
    mf = _LOGS / "ram_capture_session.json"
    while mf.exists():
        data = json.loads(mf.read_text(encoding="utf-8"))
        if data.get("complete"):
            break
        cmd_ensure()
        time.sleep(300)
    return 0


def cmd_analyze(session_id: Optional[str]) -> int:
    from app.observability.ram_capture import analyze_session, load_capture_lines

    sid = session_id
    if not sid and (_LOGS / "ram_capture_session.json").exists():
        sid = json.loads((_LOGS / "ram_capture_session.json").read_text()).get(
            "session_id"
        )
    if not sid:
        print("session_id gerekli", file=sys.stderr)
        return 1
    report = analyze_session(sid)
    scen_path = _LOGS / f"ram_scenario_{sid}.jsonl"
    lines: List[Dict[str, Any]] = []
    if scen_path.exists():
        for ln in scen_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if ln.strip():
                try:
                    lines.append(json.loads(ln))
                except json.JSONDecodeError:
                    pass
    summary_path = _LOGS / f"ram6h_summary_{sid}.md"
    out: List[str] = [
        f"# RAM 6h Summary — {sid}",
        "",
        f"Analysis report: {report}",
        "",
        "## Scenario runs",
        "",
    ]
    runs = [x for x in lines if x.get("kind") == "scenario_run"]
    out.append(f"- Total scenario runs: {len(runs)}")
    for r in runs:
        steps = r.get("steps") or []
        slow = sorted(
            [
                s
                for s in steps
                if isinstance(s, dict) and (s.get("duration_ms") or 0) > 500
            ],
            key=lambda s: s.get("duration_ms", 0),
            reverse=True,
        )[:3]
        out.append(
            f"- **{r.get('scenario_id')}** phase={r.get('phase')} steps={len(steps)} auth_blocked={r.get('auth_blocked')}"
        )
        for s in slow:
            out.append(
                f"  - slow: {s.get('label')} {s.get('duration_ms')}ms status={s.get('status')}"
            )
    summary_path.write_text("\n".join(out), encoding="utf-8")
    print("Reports:", report, summary_path)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="6 saatlik RAM capture + senaryolar")
    parser.add_argument(
        "--start", action="store_true", help="Web/worker capture + senaryo runner"
    )
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--analyze", action="store_true")
    parser.add_argument(
        "--ensure", action="store_true", help="Ölü süreçleri yeniden başlat"
    )
    parser.add_argument(
        "--restart-worker",
        action="store_true",
        help="Yalnızca worker; mevcut RAM_CAPTURE oturumu ve web/senaryo aynı kalır",
    )
    parser.add_argument("--watchdog", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--run-scenarios", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--session", type=str, default=None)
    args = parser.parse_args()
    if args.run_scenarios:
        sid = args.session or ""
        if not sid:
            print("--session required", file=sys.stderr)
            return 1
        return cmd_run_scenarios(sid, _DURATION_SEC)
    if args.start:
        return cmd_start()
    if args.status:
        return cmd_status()
    if args.ensure:
        return cmd_ensure()
    if args.restart_worker:
        return cmd_restart_worker()
    if args.watchdog:
        return cmd_watchdog()
    if args.analyze:
        return cmd_analyze(args.session)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
