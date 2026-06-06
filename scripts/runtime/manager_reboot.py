#!/usr/bin/env python3
"""Stack reboot: Manager + Web + Engine (+ HTML). Panel API'den ayrı süreç olarak çalışır."""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional

_MANAGER_PORT = 7999
_WEB_PORT = 8000
_HTML_PORT = 8080


def _process_alive(pid: int) -> bool:
    if sys.platform == "win32":
        try:
            r = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0,
            )
            return str(pid) in (r.stdout or "")
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _port_busy(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except (ConnectionRefusedError, OSError):
        return False


def _kill_port(port: int) -> None:
    if sys.platform == "win32":
        try:
            r = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True,
                text=True,
                timeout=3,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0,
            )
            for line in (r.stdout or "").splitlines():
                if "LISTENING" not in line or ":%s" % port not in line:
                    continue
                parts = line.split()
                if len(parts) < 2:
                    continue
                try:
                    p = int(parts[-1])
                    if p > 0:
                        subprocess.run(
                            ["taskkill", "/PID", str(p), "/F"],
                            capture_output=True,
                            timeout=5,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                            or 0,
                        )
                except (ValueError, IndexError):
                    pass
        except Exception:
            pass
    else:
        try:
            r = subprocess.run(
                ["lsof", "-ti", ":%s" % port], capture_output=True, text=True, timeout=5
            )
            for pid_str in (r.stdout or "").strip().split():
                try:
                    subprocess.run(
                        ["kill", "-9", pid_str], capture_output=True, timeout=3
                    )
                except (ValueError, OSError):
                    pass
        except Exception:
            pass


def _ensure_port_free(port: int, timeout_s: float = 45.0) -> bool:
    """Port dinlenmiyor olana kadar bekle; gerekirse süreçleri sonlandır."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not _port_busy(port):
            return True
        _kill_port(port)
        time.sleep(0.5)
    return not _port_busy(port)


def _wait_old_exit(old_pid: int, timeout_s: float = 30.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not _process_alive(old_pid):
            return
        time.sleep(0.25)
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(old_pid), "/F"],
            capture_output=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0,
        )
    else:
        for sig in (15, 9):
            try:
                os.kill(old_pid, sig)
            except OSError:
                break
            time.sleep(0.4)


def _helper(root: Path) -> Path:
    return root / "scripts" / "runtime" / "local_web_worker_helper.py"


def _run_helper(py: str, root: Path, action: str, timeout: int = 120) -> None:
    h = _helper(root)
    if not h.is_file():
        return
    kw: dict = {"cwd": str(root), "capture_output": True, "timeout": timeout}
    if sys.platform == "win32":
        kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0
    try:
        subprocess.run([py, str(h), action], **kw)
    except Exception:
        pass


def _html_dir(root: Path) -> Optional[Path]:
    env = os.environ.get("OMERALTINHTML_PATH", "").strip()
    if env:
        p = Path(env)
        if p.is_dir():
            return p
    for name in ("marketing", "omeraltinhtml", "Omeraltinhtml"):
        p = root / name
        if p.is_dir():
            return p
    return None


def _stop_html(root: Path) -> None:
    _kill_port(_HTML_PORT)
    pid_file = root / ".run" / "html.pid"
    if pid_file.is_file():
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
            if _process_alive(pid):
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/PID", str(pid), "/F"],
                        capture_output=True,
                        timeout=5,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0,
                    )
                else:
                    os.kill(pid, 9)
        except Exception:
            pass
        try:
            pid_file.unlink()
        except OSError:
            pass


def _start_html(root: Path, py: str) -> None:
    html = _html_dir(root)
    if not html:
        return
    logs = root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log_path = logs / "html.log"
    start_py = html / "start.py"
    run_dir = root / ".run"
    run_dir.mkdir(parents=True, exist_ok=True)
    p = None
    try:
        if start_py.is_file():
            with open(log_path, "a", encoding="utf-8", errors="replace") as logf:
                kw: dict = {
                    "cwd": str(html),
                    "stdout": logf,
                    "stderr": subprocess.STDOUT,
                }
                if sys.platform != "win32":
                    kw["start_new_session"] = True
                p = subprocess.Popen([py, "-u", str(start_py)], **kw)
        else:
            for name in ("calistir.command", "calistir.sh", "calistir"):
                script = html / name
                if script.is_file():
                    p = subprocess.Popen(
                        ["/bin/sh", str(script)], cwd=str(html), start_new_session=True
                    )
                    break
        if p is not None:
            (run_dir / "html.pid").write_text(str(p.pid), encoding="utf-8")
    except Exception:
        pass


def _manager_http_up() -> bool:
    try:
        urllib.request.urlopen(
            "http://127.0.0.1:%d/api/status" % _MANAGER_PORT, timeout=2
        )
        return True
    except Exception:
        return False


def _wait_manager_up(timeout_s: float = 60.0) -> None:
    url = "http://127.0.0.1:%d/api/status" % _MANAGER_PORT
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            return
        except Exception:
            time.sleep(1)


def _start_manager(root: Path, py: str, allow_remote: str) -> None:
    if _manager_http_up():
        return
    logs = root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log_path = logs / "manager.log"
    env = os.environ.copy()
    if allow_remote:
        env["MANAGER_ALLOW_REMOTE"] = allow_remote
    with open(log_path, "a", encoding="utf-8", errors="replace") as logf:
        kw: dict = {
            "cwd": str(root),
            "stdout": logf,
            "stderr": subprocess.STDOUT,
            "env": env,
        }
        if sys.platform == "win32":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
                subprocess, "DETACHED_PROCESS", 0x00000008
            )
            kw["creationflags"] = flags
        else:
            kw["start_new_session"] = True
        p = subprocess.Popen([py, "-m", "manager_server"], **kw)
    try:
        (root / ".run" / "manager.pid").write_text(str(p.pid), encoding="utf-8")
    except Exception:
        pass


def _ensure_manager_running(root: Path, py: str, allow_remote: str) -> None:
    """7999 boşalana kadar bekle; zaten ayaktaysa ikinci süreç başlatma."""
    _ensure_port_free(_MANAGER_PORT, timeout_s=45.0)
    if _manager_http_up():
        return
    _start_manager(root, py, allow_remote)
    _wait_manager_up(timeout_s=60.0)


def _full_stack_reboot(root: Path, py: str, allow_remote: str) -> None:
    _run_helper(py, root, "all-stop", timeout=90)
    _stop_html(root)
    _ensure_port_free(_WEB_PORT, timeout_s=30.0)
    _ensure_port_free(_HTML_PORT, timeout_s=20.0)
    _ensure_manager_running(root, py, allow_remote)
    _run_helper(py, root, "all-start", timeout=120)
    time.sleep(1)
    _start_html(root, py)


def _manager_only_reboot(root: Path, py: str, allow_remote: str) -> None:
    _ensure_manager_running(root, py, allow_remote)


def _acquire_lock(root: Path) -> bool:
    lock = root / ".run" / "stack_reboot.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    if lock.is_file():
        try:
            holder = int(lock.read_text(encoding="utf-8").strip())
            if _process_alive(holder):
                return False
        except Exception:
            pass
    try:
        lock.write_text(str(os.getpid()), encoding="utf-8")
    except Exception:
        return True
    return True


def _release_lock(root: Path) -> None:
    lock = root / ".run" / "stack_reboot.lock"
    try:
        if (
            lock.is_file()
            and int(lock.read_text(encoding="utf-8").strip()) == os.getpid()
        ):
            lock.unlink()
    except Exception:
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old-pid", type=int, required=True)
    ap.add_argument("--root", required=True)
    ap.add_argument("--python", required=True)
    ap.add_argument("--allow-remote", default="")
    ap.add_argument(
        "--full-stack",
        action="store_true",
        help="Web+Engine+HTML+Manager yeniden başlat",
    )
    args = ap.parse_args()
    root = Path(args.root).resolve()
    py = args.python
    allow = (args.allow_remote or "").strip()
    if not _acquire_lock(root):
        return 0
    try:
        _wait_old_exit(args.old_pid)
        time.sleep(0.5)
        if args.full_stack:
            _full_stack_reboot(root, py, allow)
        else:
            _manager_only_reboot(root, py, allow)
    finally:
        _release_lock(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
