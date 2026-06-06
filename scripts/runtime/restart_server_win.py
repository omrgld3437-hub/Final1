#!/usr/bin/env python3
"""
Windows: Sunucudan bagimsiz restart yardimcisi.
Sunucu kapatildiginda bu proses ayakta kalir; 5 sn bekleyip sunucuyu kapatir,
ardindan calistir.bat (veya win_launcher) ile tekrar baslatir.

Kullanım:
  python scripts/restart_server_win.py <sunucu_pid>
  python scripts/restart_server_win.py 12345

Sadece Windows'ta calistirilir. Admin API restart isteginde kullanilir.
"""

import os
import sys
import time
import subprocess
import logging
import platform

if platform.system() != "win32":
    logging.error("Bu script sadece Windows icin.")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="[restart_helper] %(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def main():
    if len(sys.argv) < 2:
        log.error("Kullanım: %s <sunucu_pid>", sys.argv[0])
        sys.exit(1)

    try:
        pid = int(sys.argv[1])
    except ValueError:
        log.error("Geçersiz PID: %s", sys.argv[1])
        sys.exit(1)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(script_dir))
    start_bat = os.path.join(project_root, "calistir.bat")
    if not os.path.isfile(start_bat):
        start_bat = os.path.join(project_root, "Server Start.bat")
    if not os.path.isfile(start_bat):
        log.error("Baslatma scripti bulunamadi: calistir.bat veya Server Start.bat")
        sys.exit(1)

    log.info(
        "5 saniye bekleniyor, sonra PID %s kapatilip %s ile yeniden baslatilacak.",
        pid,
        start_bat,
    )
    time.sleep(5)

    # Windows: taskkill ile sunucu prosesini kapat
    try:
        r = subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=CREATE_NO_WINDOW,
        )
        if r.returncode == 0:
            log.info("PID=%s sonlandirildi.", pid)
        else:
            log.warning("taskkill cikis kodu: %s", r.returncode)
    except Exception as e:
        log.warning("taskkill hatasi: %s", e)

    time.sleep(2)

    # calistir.bat veya Server Start.bat ile baslat (cmd /c)
    log.info("Sunucu baslatiliyor: %s", start_bat)
    try:
        subprocess.Popen(
            ["cmd", "/c", start_bat],
            cwd=project_root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
        )
        log.info("Restart tamamlandi (arka planda baslatildi).")
    except Exception as e:
        log.error("Baslatma hatasi: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
