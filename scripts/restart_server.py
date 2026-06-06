#!/usr/bin/env python3
"""
Sunucudan bağımsız restart yardımcısı.
Sunucu kapatıldığında bu proses ayakta kalır; 5 sn bekleyip sunucuyu kapatır,
ardından run.sh ile tekrar başlatır. run.sh başarısızsa doğrudan uvicorn dener.

Kullanım:
  python scripts/restart_server.py <sunucu_pid> [run_sh_yolu]
  python scripts/restart_server.py 12345
  python scripts/restart_server.py 12345 /path/to/run.sh

Bu script sunucu (uvicorn) ile aynı process tree'de olmayacak şekilde
admin API tarafından start_new_session=True ile çalıştırılır.
"""
import os
import sys
import time
import signal
import subprocess
import logging

logging.basicConfig(
    level=logging.INFO,
    format="[restart_helper] %(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def _start_uvicorn_direct(project_root: str) -> bool:
    """run.sh başarısızsa doğrudan uvicorn başlat (MODULE_NOT_FOUND önlemi: cwd + PYTHONPATH)."""
    env = os.environ.copy()
    env["PYTHONPATH"] = project_root
    host = env.get("WEB_HOST", "0.0.0.0")
    is_win = sys.platform == "win32"
    venv_bin = os.path.join(project_root, ".venv", "Scripts" if is_win else "bin")
    uvicorn_exe = os.path.join(venv_bin, "uvicorn.exe" if is_win else "uvicorn")
    extra = [] if is_win else ["--loop", "uvloop", "--http", "httptools"]
    if os.path.isfile(uvicorn_exe):
        cmd = [uvicorn_exe, "app.main:app", "--host", host, "--port", "8000", "--workers", "2", "--log-level", "info"] + extra
    else:
        cmd = [sys.executable, "-m", "uvicorn", "app.main:app", "--host", host, "--port", "8000", "--workers", "2", "--log-level", "info"] + extra
    run_dir = os.path.join(project_root, ".run")
    os.makedirs(run_dir, exist_ok=True)
    log_path = os.path.join(run_dir, "server.log")
    try:
        with open(log_path, "a", encoding="utf-8", errors="replace") as logf:
            p = subprocess.Popen(
                cmd,
                cwd=project_root,
                env=env,
                stdout=logf,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        pid_file = os.path.join(run_dir, "server.pid")
        with open(pid_file, "w") as f:
            f.write(str(p.pid))
        log.info("Fallback: uvicorn doğrudan başlatıldı PID=%s", p.pid)
        return True
    except Exception as e:
        log.error("Fallback uvicorn başlatılamadı: %s", e)
        return False


def main():
    if len(sys.argv) < 2:
        log.error("Kullanım: %s <sunucu_pid> [run_sh_yolu]", sys.argv[0])
        sys.exit(1)

    try:
        pid = int(sys.argv[1])
    except ValueError:
        log.error("Geçersiz PID: %s", sys.argv[1])
        sys.exit(1)

    # Proje kökü: bu script scripts/ içinde, proje kökü bir üst dizin
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    run_sh = sys.argv[2] if len(sys.argv) > 2 else os.path.join(project_root, "run.sh")

    if not os.path.isfile(run_sh):
        log.error("run.sh bulunamadı: %s", run_sh)
        sys.exit(1)

    log.info("5 saniye bekleniyor, sonra PID %s kapatılıp %s ile yeniden başlatılacak.", pid, run_sh)
    time.sleep(5)

    # Sunucu prosesine SIGTERM gönder
    try:
        os.kill(pid, signal.SIGTERM)
        log.info("SIGTERM gönderildi PID=%s", pid)
    except ProcessLookupError:
        log.warning("Proses zaten yok: PID=%s", pid)
    except PermissionError:
        log.error("PID %s sonlandırılamadı (yetki yok).", pid)
        sys.exit(1)

    # Prosesin kapanmasını bekle (en fazla 15 sn)
    for _ in range(30):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.5)
    else:
        log.warning("Proses %s 15 sn içinde kapanmadı, yine de run.sh çalıştırılıyor.", pid)

    # Eski PID dosyasını temizle (run.sh "zaten çalışıyor" yanılgısını önler)
    pid_file = os.path.join(project_root, ".run", "server.pid")
    if os.path.isfile(pid_file):
        try:
            os.remove(pid_file)
        except OSError:
            pass

    # run.sh ile sunucuyu başlat (env: PYTHONPATH=project_root, MODULE_NOT_FOUND önlemi)
    env = os.environ.copy()
    env["PYTHONPATH"] = project_root
    bash_cmd = "/bin/bash" if os.path.isfile("/bin/bash") else "bash"
    log.info("Sunucu başlatılıyor: %s", run_sh)
    try:
        r = subprocess.run(
            [bash_cmd, run_sh],
            cwd=project_root,
            env=env,
            timeout=60,
        )
        if r.returncode != 0:
            log.warning("run.sh exit code=%s, fallback deneniyor.", r.returncode)
            if _start_uvicorn_direct(project_root):
                log.info("Restart tamamlandı (fallback ile).")
            else:
                sys.exit(1)
        else:
            log.info("Restart tamamlandı.")
    except subprocess.TimeoutExpired:
        log.warning("run.sh 60 sn içinde bitmedi (arka planda sunucu çalışıyor olabilir).")
    except FileNotFoundError as e:
        log.warning("bash bulunamadı, fallback deneniyor: %s", e)
        if _start_uvicorn_direct(project_root):
            log.info("Restart tamamlandı (fallback ile).")
        else:
            sys.exit(1)


if __name__ == "__main__":
    main()
