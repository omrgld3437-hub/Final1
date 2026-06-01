#!/usr/bin/env python3
"""
Sunucudan bağımsız Web/Worker durdurma, yeniden başlatma ve başlatma.
Log API (stop/restart) bu script'i arka planda çalıştırır; sunucu yanıt döndükten sonra
helper işlemi yapar. Sunucu kapalıyken de komut satırından çalıştırılabilir (start).

Kullanım:
  python scripts/local_web_worker_helper.py web-stop
  python scripts/local_web_worker_helper.py web-restart
  python scripts/local_web_worker_helper.py web-start
  python scripts/local_web_worker_helper.py worker-stop
  python scripts/local_web_worker_helper.py worker-restart
  python scripts/local_web_worker_helper.py worker-start
  python scripts/local_web_worker_helper.py all-stop
  python scripts/local_web_worker_helper.py all-restart
  python scripts/local_web_worker_helper.py all-start
"""
import os
import sys
import time
import signal
import subprocess
import platform
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_TR_TZ = ZoneInfo("Europe/Istanbul")

_IS_WINDOWS = platform.system() == "Windows"
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent
_RUN_DIR = _PROJECT_ROOT / ".run"
_LOGS_DIR = _PROJECT_ROOT / "logs"
_SERVER_LOCKS_FILE = _RUN_DIR / "server_locks.json"
_WEB_LOG = _LOGS_DIR / "web.log"
_WORKER_LOG = _LOGS_DIR / "worker.log"
_WEB_PID_FILE = _RUN_DIR / "web.pid"
_WORKER_PID_FILE = _RUN_DIR / "worker.pid"
_WEB_STARTED_AT = _RUN_DIR / "web.started_at"
_WORKER_STARTED_AT = _RUN_DIR / "worker.started_at"
_HELPER_SPAWN_LOG = _RUN_DIR / "restart_helper.log"


def _spawn_env():
    """Build env for subprocess: inherit parent, set RAM_PROBE defaults only if missing."""
    env = os.environ.copy()
    env.setdefault("RAM_PROBE", "0")
    env.setdefault("RAM_PROBE_INTERVAL", "30")
    return env


def _append_log(path: Path, msg: str) -> None:
    """Log dosyasına zaman damgalı, anlaşılır bir satır ekle (durdurma/yeniden başlatma bildirimi)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(_TR_TZ).strftime("%Y-%m-%d %H:%M:%S")
        with open(path, "a", encoding="utf-8", errors="replace") as f:
            f.write("%s [yönetim] %s\n" % (ts, msg))
    except Exception:
        pass


def _log_spawn(role: str, pid: int, cwd: str) -> None:
    try:
        _RUN_DIR.mkdir(parents=True, exist_ok=True)
        env = _spawn_env()
        line = "[helper] spawned %s pid=%s RAM_PROBE=%s RAM_PROBE_INTERVAL=%s cwd=%s\n" % (
            role, pid, env.get("RAM_PROBE", ""), env.get("RAM_PROBE_INTERVAL", ""), cwd
        )
        with open(_HELPER_SPAWN_LOG, "a", encoding="utf-8", errors="replace") as f:
            f.write(line)
    except Exception:
        pass


def _read_pid(path: Path):
    if not path.exists():
        return None
    try:
        return int(path.read_text().strip())
    except (ValueError, OSError):
        return None


def _process_alive(pid):
    if pid is None:
        return False
    if _IS_WINDOWS:
        try:
            r = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if getattr(subprocess, "CREATE_NO_WINDOW", None) is not None else 0,
            )
            return str(pid) in (r.stdout or "")
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _kill_pid(pid: int) -> bool:
    if _IS_WINDOWS:
        r = subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"],
            capture_output=True,
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        return r.returncode == 0
    try:
        os.kill(pid, signal.SIGTERM)
        time.sleep(1)
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        os.kill(pid, signal.SIGKILL)
        time.sleep(0.5)
        return True
    except OSError:
        return False


def _kill_process_on_port(port: int) -> None:
    """Portu dinleyen süreçleri durdur (PID dosyası yoksa veya IDE'den başlatılmışsa da çalışır)."""
    if _IS_WINDOWS:
        try:
            r = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True,
                text=True,
                timeout=3,
                creationflags=subprocess.CREATE_NO_WINDOW if getattr(subprocess, "CREATE_NO_WINDOW", None) is not None else 0,
            )
            for line in (r.stdout or "").splitlines():
                if "LISTENING" not in line or ":%s" % port not in line:
                    continue
                parts = line.split()
                if len(parts) < 2:
                    continue
                try:
                    pid = int(parts[-1])
                    if pid > 0:
                        _kill_pid(pid)
                        time.sleep(0.5)
                except (ValueError, IndexError):
                    pass
        except Exception:
            pass
    else:
        try:
            r = subprocess.run(
                ["lsof", "-ti", ":%s" % port],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=str(_PROJECT_ROOT),
            )
            pids = (r.stdout or "").strip().split()
            for pid_str in pids:
                try:
                    _kill_pid(int(pid_str))
                    time.sleep(0.3)
                except (ValueError, OSError):
                    pass
        except Exception:
            pass


def _start_web() -> bool:
    _RUN_DIR.mkdir(parents=True, exist_ok=True)
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)
    venv_bin = _PROJECT_ROOT / ".venv" / ("Scripts" if _IS_WINDOWS else "bin")
    py_exe = venv_bin / ("python.exe" if _IS_WINDOWS else "python")
    uvicorn_exe = venv_bin / ("uvicorn.exe" if _IS_WINDOWS else "uvicorn")
    host = os.environ.get("WEB_HOST", "0.0.0.0")
    # .venv varsa her zaman .venv Python kullan (fastapi/uvicorn orada kurulu olsun)
    use_py = str(py_exe) if py_exe.exists() else sys.executable
    uvicorn_extra = [] if _IS_WINDOWS else ["--loop", "uvloop", "--http", "httptools"]
    access_log_args = ["--log-level", os.environ.get("WEB_LOG_LEVEL", "warning"), "--no-access-log"]
    if uvicorn_exe.exists():
        cmd = [str(uvicorn_exe), "app.main:app", "--host", host, "--port", "8000", "--workers", "2"] + access_log_args + uvicorn_extra
    else:
        try:
            import uvicorn as _u
        except ModuleNotFoundError:
            _append_log(
                _WEB_LOG,
                "HATA: uvicorn yok. Proje kokunde: .venv\\Scripts\\pip install -r requirements.txt  veya  pip install -r requirements.txt",
            )
            return False
        cmd = [use_py, "-m", "uvicorn", "app.main:app", "--host", host, "--port", "8000", "--workers", "2"] + access_log_args + uvicorn_extra
    cwd = str(_PROJECT_ROOT)
    env = _spawn_env()
    try:
        with open(_WEB_LOG, "a", encoding="utf-8", errors="replace") as logf:
            p = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=logf,
                stderr=subprocess.STDOUT,
                env=env,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if _IS_WINDOWS else 0,
            )
        _WEB_PID_FILE.write_text(str(p.pid))
        _WEB_STARTED_AT.write_text(str(time.time()))
        _log_spawn("web", p.pid, cwd)
        return True
    except Exception:
        return False


def _start_worker() -> bool:
    _RUN_DIR.mkdir(parents=True, exist_ok=True)
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)
    venv_bin = _PROJECT_ROOT / ".venv" / ("Scripts" if _IS_WINDOWS else "bin")
    py_exe = venv_bin / ("python.exe" if _IS_WINDOWS else "python")
    if not py_exe.exists():
        cmd = [sys.executable, "-m", "app.botengine.worker_main"]
    else:
        cmd = [str(py_exe), "-m", "app.botengine.worker_main"]
    cwd = str(_PROJECT_ROOT)
    env = _spawn_env()
    try:
        with open(_WORKER_LOG, "a", encoding="utf-8", errors="replace", buffering=1) as logf:
            p = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=logf,
                stderr=subprocess.STDOUT,
                env=env,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if _IS_WINDOWS else 0,
            )
        _WORKER_PID_FILE.write_text(str(p.pid))
        _WORKER_STARTED_AT.write_text(str(time.time()))
        _log_spawn("worker", p.pid, cwd)
        return True
    except Exception:
        return False


def _kill_worker_by_cmdline() -> None:
    """worker_main çalışan süreçleri bulup durdur (PID dosyası yoksa veya IDE'den başlatılmışsa da çalışır)."""
    if _IS_WINDOWS:
        try:
            r = subprocess.run(
                ["wmic", "process", "where", "commandline like '%worker_main%'", "get", "processid"],
                capture_output=True,
                text=True,
                timeout=4,
                creationflags=subprocess.CREATE_NO_WINDOW if getattr(subprocess, "CREATE_NO_WINDOW", None) is not None else 0,
            )
            for line in (r.stdout or "").splitlines():
                line = line.strip()
                if line.isdigit():
                    pid = int(line)
                    if pid > 0 and pid != os.getpid():
                        _kill_pid(pid)
                        time.sleep(0.5)
        except Exception:
            pass
    else:
        try:
            r = subprocess.run(
                ["pgrep", "-f", "app.botengine.worker_main"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=str(_PROJECT_ROOT),
            )
            pids = (r.stdout or "").strip().split()
            for pid_str in pids:
                try:
                    pid = int(pid_str)
                    if pid > 0 and pid != os.getpid():
                        _kill_pid(pid)
                        time.sleep(0.3)
                except (ValueError, OSError):
                    pass
        except Exception:
            pass


def do_web_stop():
    _append_log(_WEB_LOG, "Web sunucusu kullanıcı isteği ile durduruluyor.")
    time.sleep(1)
    pid = _read_pid(_WEB_PID_FILE)
    if pid is not None:
        _kill_pid(pid)
        time.sleep(0.5)
    if _WEB_PID_FILE.exists():
        try:
            _WEB_PID_FILE.unlink()
        except OSError:
            pass
    _kill_process_on_port(8000)
    if _WEB_STARTED_AT.exists():
        try:
            _WEB_STARTED_AT.unlink()
        except OSError:
            pass


def do_web_restart():
    _append_log(_WEB_LOG, "Web sunucusu yeniden başlatılıyor.")
    do_web_stop()
    time.sleep(1.5)
    _start_web()
    _append_log(_WEB_LOG, "Web sunucusu yeniden başlatıldı.")


def _read_server_locks():
    """Return {"web": bool, "worker": bool}. Kilitli sunucular Tüm Yeniden Başlat sırasında atlanır."""
    if not _SERVER_LOCKS_FILE.exists():
        return {"web": False, "worker": False}
    try:
        import json as _json
        d = _json.loads(_SERVER_LOCKS_FILE.read_text(encoding="utf-8"))
        return {"web": bool(d.get("web")), "worker": bool(d.get("worker"))}
    except Exception:
        return {"web": False, "worker": False}


def do_web_start():
    if os.environ.get("RESPECT_LOCKS") == "1" and _read_server_locks().get("web"):
        return
    pid = _read_pid(_WEB_PID_FILE)
    if pid is not None and _process_alive(pid):
        return
    if _WEB_PID_FILE.exists():
        try:
            _WEB_PID_FILE.unlink()
        except OSError:
            pass
    _kill_process_on_port(8000)
    time.sleep(0.5)
    _start_web()


def do_worker_stop():
    _append_log(_WORKER_LOG, "Worker kullanıcı isteği ile durduruluyor.")
    pid = _read_pid(_WORKER_PID_FILE)
    if pid is not None:
        _kill_pid(pid)
        time.sleep(0.5)
    if _WORKER_PID_FILE.exists():
        try:
            _WORKER_PID_FILE.unlink()
        except OSError:
            pass
    _kill_worker_by_cmdline()
    if _WORKER_STARTED_AT.exists():
        try:
            _WORKER_STARTED_AT.unlink()
        except OSError:
            pass


def do_worker_restart():
    _append_log(_WORKER_LOG, "Worker yeniden başlatılıyor.")
    do_worker_stop()
    time.sleep(1.5)
    _start_worker()
    _append_log(_WORKER_LOG, "Worker yeniden başlatıldı.")


def do_worker_start():
    if os.environ.get("RESPECT_LOCKS") == "1" and _read_server_locks().get("worker"):
        return
    pid = _read_pid(_WORKER_PID_FILE)
    if pid is not None and _process_alive(pid):
        return
    if _WORKER_PID_FILE.exists():
        try:
            _WORKER_PID_FILE.unlink()
        except OSError:
            pass
    _kill_worker_by_cmdline()
    time.sleep(0.5)
    _start_worker()


def do_all_stop():
    # Web ve Worker durdur. Manager (7999) Manager Stop.command ile ayrı kapatılır.
    do_web_stop()
    do_worker_stop()


def do_all_restart():
    do_web_restart()
    do_worker_restart()


def do_all_start():
    do_web_start()
    do_worker_start()


def main():
    if len(sys.argv) < 2:
        print("Kullanım: python local_web_worker_helper.py <web-stop|web-restart|web-start|worker-stop|worker-restart|worker-start|all-stop|all-restart|all-start>", file=sys.stderr)
        sys.exit(1)
    action = (sys.argv[1] or "").strip().lower()
    if action == "web-stop":
        do_web_stop()
    elif action == "web-restart":
        do_web_restart()
    elif action == "web-start":
        do_web_start()
    elif action == "worker-stop":
        do_worker_stop()
    elif action == "worker-restart":
        do_worker_restart()
    elif action == "worker-start":
        do_worker_start()
    elif action == "all-stop":
        do_all_stop()
    elif action == "all-restart":
        do_all_restart()
    elif action == "all-start":
        do_all_start()
    else:
        print("Bilinmeyen komut: %s" % sys.argv[1], file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
