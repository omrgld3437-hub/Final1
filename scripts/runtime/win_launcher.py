#!/usr/bin/env python3
"""
Windows: Proje kokunden tum sunuculari aciksa restart, kapaliysa start eder.
Tek giris: python scripts/win_launcher.py
"""

import os
import sys
import time
import subprocess
import urllib.request
from pathlib import Path

if sys.platform != "win32":
    print("Bu script sadece Windows icin.")
    sys.exit(1)

_SCRIPT_DIR = Path(__file__).resolve().parent
_ROOT = _SCRIPT_DIR.parent
_LOGS = _ROOT / "logs"
_RUN = _ROOT / ".run"
_MANAGER_LOG = _LOGS / "manager.log"
_HELPER = _SCRIPT_DIR / "local_web_worker_helper.py"
_MANAGER = "manager_server"  # -m manager_server
_FIX_CGI = _SCRIPT_DIR / "fix_cgi_once.py"

# Python 3.14+ icin pydantic-core wheel yok; 3.12 veya 3.13 tercih et
_PREFERRED_VERSIONS = ("3.12", "3.13")


def _get_python_version(exe):
    """Verilen python exe'nin major.minor versiyonunu dondurur (ornek: '3.12')."""
    try:
        r = subprocess.run(
            [
                exe,
                "-c",
                "import sys; print('%s.%s' % (sys.version_info.major, sys.version_info.minor))",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW
            if getattr(subprocess, "CREATE_NO_WINDOW", None)
            else 0,
        )
        if r.returncode == 0 and r.stdout:
            return r.stdout.strip()
    except Exception:
        pass
    return None


def _preferred_system_python():
    """Windows: py -3.12 / py -3.13 varsa onu kullan (3.14 uyumsuz). Yoksa sys.executable."""
    for ver in _PREFERRED_VERSIONS:
        try:
            r = subprocess.run(
                ["py", "-%s" % ver, "-c", "import sys; print(sys.executable)"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=str(_ROOT),
                creationflags=subprocess.CREATE_NO_WINDOW
                if getattr(subprocess, "CREATE_NO_WINDOW", None)
                else 0,
            )
            if r.returncode == 0 and r.stdout and r.stdout.strip():
                exe = r.stdout.strip()
                if os.path.isfile(exe):
                    return exe
        except Exception:
            pass
    # Mevcut Python 3.14+ ise uyari ver
    ver = _get_python_version(sys.executable)
    if ver and ver.startswith("3."):
        try:
            minor = int(ver.split(".")[1])
            if minor >= 14:
                print(
                    "     UYARI: Python %s kullaniyorsunuz; bazi paketler (pydantic) icin wheel yok."
                    % ver
                )
                print(
                    "     Cozum: Python 3.12 veya 3.13 kurun, .venv silin, tekrar calistirin."
                )
                print("     Indir: https://www.python.org/downloads/")
        except (ValueError, IndexError):
            pass
    return sys.executable


def _python():
    venv = _ROOT / ".venv" / "Scripts" / "python.exe"
    return str(venv) if venv.exists() else sys.executable


def _run(cmd, timeout=15, quiet=False):
    try:
        flags = (
            subprocess.CREATE_NO_WINDOW
            if getattr(subprocess, "CREATE_NO_WINDOW", None)
            else 0
        )
        r = subprocess.run(
            cmd,
            cwd=str(_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=flags,
        )
        if not quiet and r.stderr:
            print(r.stderr, end="")
        return r.returncode == 0
    except Exception:
        return False


def _manager_up():
    try:
        req = urllib.request.Request("http://127.0.0.1:7999/api/status")
        urllib.request.urlopen(req, timeout=3)
        return True
    except Exception:
        return False


def _stop_all():
    print("[0] Acik processler kapatiliyor (7999, 8000, worker)...")
    _run([_python(), str(_HELPER), "all-stop"], timeout=25, quiet=True)
    time.sleep(2)
    print("     Tamamlandi.")


def _start_manager():
    print("[1] Manager (7999) baslatiliyor...")
    _LOGS.mkdir(parents=True, exist_ok=True)
    _RUN.mkdir(parents=True, exist_ok=True)
    logf = open(_MANAGER_LOG, "a", encoding="utf-8", errors="replace")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.Popen(
            [_python(), "-m", _MANAGER],
            cwd=str(_ROOT),
            stdout=logf,
            stderr=subprocess.STDOUT,
            creationflags=flags,
        )
        logf.close()
    except Exception:
        logf.close()
        raise
    for _ in range(40):
        time.sleep(1)
        if _manager_up():
            print("     Manager hazir.")
            return True
        print(".", end="", flush=True)
    print("\n     UYARI: Manager 40 sn icinde yanit vermedi.")
    return False


def _check_web_deps():
    """Web (fastapi/uvicorn) icin bagimlilik var mi kontrol et."""
    try:
        r = subprocess.run(
            [_python(), "-c", "import fastapi; import uvicorn"],
            cwd=str(_ROOT),
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW
            if getattr(subprocess, "CREATE_NO_WINDOW", None)
            else 0,
        )
        return r.returncode == 0
    except Exception:
        return False


def _ensure_venv():
    """.venv yoksa olustur; Python 3.12/3.13 tercih edilir (3.14 uyumsuz)."""
    venv_dir = _ROOT / ".venv"
    if venv_dir.exists():
        return True
    py_exe = _preferred_system_python()
    print("     .venv bulunamadi, olusturuluyor (%s ile)..." % py_exe)
    ok = _run([py_exe, "-m", "venv", str(venv_dir)], timeout=120, quiet=False)
    if ok:
        print("     .venv olusturuldu.")
    return ok


def _venv_python_version():
    """.venv icindeki Python versiyonunu dondurur (ornek: '3.14'). Yoksa None."""
    venv_py = _ROOT / ".venv" / "Scripts" / "python.exe"
    if not venv_py.exists():
        return None
    return _get_python_version(str(venv_py))


def _ensure_venv_deps():
    """.venv yoksa olustur; fastapi/uvicorn yoksa pip install -r requirements.txt calistir."""
    req_file = _ROOT / "requirements.txt"
    if not req_file.exists():
        return False
    if not (_ROOT / ".venv").exists():
        if not _ensure_venv():
            return False
    venv_py = _ROOT / ".venv" / "Scripts" / "python.exe"
    if not venv_py.exists():
        return False
    # Mevcut .venv Python 3.14+ ise pydantic wheel yok; pip deneme, net talimat ver
    venv_ver = _venv_python_version()
    if venv_ver:
        try:
            minor = int(venv_ver.split(".")[1])
            if minor >= 14:
                print(
                    "     HATA: .venv Python %s ile olusturulmus; bu surum uyumlu degil."
                    % venv_ver
                )
                print("")
                print("     YAPMANIZ GEREKENLER:")
                print("     1. Bu klasorde .venv klasorunu SILIN (sag tik -> Sil)")
                print(
                    "     2. Python 3.12 veya 3.13 kurun: https://www.python.org/downloads/"
                )
                print("     3. calistir.bat veya Server Start.bat'i tekrar calistirin.")
                print("")
                return False
        except (ValueError, IndexError):
            pass
    if _check_web_deps():
        return True
    print("     Bagimliliklar kuruluyor (ilk calistirmada 1-2 dk surebilir)...")
    # python -m pip kullan (pip kendini guncellerken "To modify pip, run python -m pip ..." hatasini onler)
    ok = _run(
        [str(venv_py), "-m", "pip", "install", "-r", str(req_file), "--prefer-binary"],
        timeout=300,
        quiet=False,
    )
    if ok and _check_web_deps():
        return True
    if not _check_web_deps():
        print(
            "     UYARI: Kurulum basarisiz veya eksik. Python 3.14 cok yeni; bazi paketler wheel sunmuyor."
        )
        print(
            "     Cozum: Python 3.12 veya 3.13 kurun, .venv silin, tekrar calistirin."
        )
        print("     Indir: https://www.python.org/downloads/")
    return False


def _start_web_worker():
    if not _check_web_deps():
        if _ensure_venv_deps():
            pass
        else:
            print("[2] Web (8000) ve Worker baslatiliyor...")
            print("     HATA: fastapi/uvicorn yok.")
            print("     Proje kokunde su komutu calistirin:")
            venv_py = _ROOT / ".venv" / "Scripts" / "python.exe"
            if venv_py.exists():
                print("       %s -m pip install -r requirements.txt" % venv_py)
            else:
                print("       python -m venv .venv")
                print(
                    "       .venv\\Scripts\\python.exe -m pip install -r requirements.txt"
                )
            print("     Tamamlandi (Web baslamadi).")
            return
    print("[2] Web (8000) ve Worker baslatiliyor...")
    _run([_python(), str(_HELPER), "all-start"], timeout=30, quiet=True)
    time.sleep(1)
    print("     Tamamlandi.")


def main():
    os.chdir(_ROOT)
    print("")
    print("========================================")
    print("  ayserose - Windows Baslat")
    print("========================================")
    print("Kok: %s" % _ROOT)
    print("")

    if _FIX_CGI.exists():
        _run([_python(), str(_FIX_CGI)], timeout=10, quiet=True)

    _stop_all()
    print("")
    if not _start_manager():
        print("Manager baslamadi. Log: %s" % _MANAGER_LOG)
        return 1
    print("")
    _start_web_worker()
    print("")
    print("[3] Bitti.")
    print("========================================")
    print("  Panel:  http://127.0.0.1:7999/")
    print("  Login:  http://127.0.0.1:8000/ui/login.html")
    print("========================================")
    print("")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        print("HATA: %s" % e)
        sys.exit(1)
