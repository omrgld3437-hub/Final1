#!/usr/bin/env python3
"""
5 dakikalık RAM capture oturumu — başlatma talimatı, bekleme ve analiz.

1) Ortam değişkenlerini yazdır ve web+worker'ı yeniden başlat:
     cd /path/to/final1 && python3 scripts/perf/ram_capture_5min.py --print-env
     # veya: ops/ram_capture_guide.command (macOS çift tık)

2) Uygulama çalışırken 5 dk bekle (manifest complete=1 olana kadar):
     python scripts/perf/ram_capture_5min.py --wait

3) Analiz raporu üret:
     python scripts/perf/ram_capture_5min.py --analyze

Tek komut (env + talimat; sunucuyu siz başlatırsınız):
     python scripts/perf/ram_capture_5min.py --guide
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_LOGS = _PROJECT_ROOT / "logs"
_MANIFEST = _LOGS / "ram_capture_session.json"
_DURATION_DEFAULT = 300
_INTERVAL_DEFAULT = 10


def _session_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def print_env(session_id: str | None = None) -> str:
    sid = session_id or _session_id()
    lines = [
        f"export RAM_CAPTURE=1",
        f"export RAM_CAPTURE_SESSION={sid}",
        f"export RAM_CAPTURE_DURATION={_DURATION_DEFAULT}",
        f"export RAM_CAPTURE_INTERVAL={_INTERVAL_DEFAULT}",
        "export RAM_PROBE=1",
        f"export RAM_PROBE_INTERVAL={_INTERVAL_DEFAULT}",
        "# Opsiyonel: tüm /api isteklerini logla (varsayılan: yavaş/büyük istekler)",
        "# export RAM_CAPTURE_HTTP_ALL=1",
    ]
    text = "\n".join(lines)
    print(text)
    print()
    print(f"Oturum kimliği: {sid}")
    print(f"Log dosyaları (5 dk sonra):")
    print(f"  {_LOGS}/ram_capture_{sid}_web.jsonl")
    print(f"  {_LOGS}/ram_capture_{sid}_worker.jsonl")
    print(f"  {_LOGS}/ram_snapshots.log  (probe mirror)")
    print(f"  {_LOGS}/ram_capture_session.json")
    return sid


def cmd_status() -> int:
    if not _MANIFEST.exists():
        print("Manifest yok — RAM_CAPTURE=1 ile web/worker henüz başlamamış olabilir.")
        return 1
    data = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    print(json.dumps(data, indent=2, ensure_ascii=False))
    files = data.get("files") or {}
    for comp, path in files.items():
        p = Path(path)
        n = 0
        if p.exists():
            n = sum(1 for ln in p.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip())
        print(f"  {comp}: {n} lines — {path}")
    return 0


def cmd_wait(timeout_sec: int = 400) -> int:
    print(f"Manifest bekleniyor (max {timeout_sec}s): {_MANIFEST}")
    t0 = time.time()
    while time.time() - t0 < timeout_sec:
        if _MANIFEST.exists():
            try:
                data = json.loads(_MANIFEST.read_text(encoding="utf-8"))
                if data.get("complete"):
                    print("Oturum tamamlandı:", data.get("session_id"))
                    cmd_status()
                    return 0
            except Exception:
                pass
        # satır sayısı ilerlemesi
        for p in sorted(_LOGS.glob("ram_capture_*.jsonl")):
            try:
                n = sum(1 for _ in open(p, encoding="utf-8", errors="replace"))
                print(f"  … {p.name}: {n} lines", end="\r")
            except Exception:
                pass
        time.sleep(5)
    print("\nZaman aşımı — yine de --analyze çalıştırılabilir.")
    return 1


def cmd_analyze(session_id: str | None) -> int:
    from app.observability.ram_capture import analyze_session

    try:
        path = analyze_session(session_id)
        print("Rapor:", path)
        return 0
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 1


def cmd_guide() -> int:
    sid = print_env()
    print("—" * 60)
    print("Adımlar:")
    print("  1. Yukarıdaki export'ları shell'e alın ve Server Start / web+worker yeniden başlatın.")
    print("  2. Dashboard ve bot sayfalarında normal kullanım yapın (5 dk).")
    print("  3. python scripts/perf/ram_capture_5min.py --wait")
    print("  4. python scripts/perf/ram_capture_5min.py --analyze")
    print()
    print("Hızlı analiz (beklemeden): --analyze --session", sid)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="RAM capture 5 dakika oturumu")
    parser.add_argument("--print-env", action="store_true", help="export satırlarını yazdır")
    parser.add_argument("--guide", action="store_true", help="env + adımlar")
    parser.add_argument("--wait", action="store_true", help="manifest complete olana kadar bekle")
    parser.add_argument("--status", action="store_true", help="manifest ve satır sayıları")
    parser.add_argument("--analyze", action="store_true", help="Markdown analiz raporu")
    parser.add_argument("--session", type=str, default=None, help="Oturum kimliği (analyze)")
    parser.add_argument("--timeout", type=int, default=400, help="--wait üst sınır (sn)")
    args = parser.parse_args()

    if args.print_env:
        print_env(args.session)
        return 0
    if args.guide:
        return cmd_guide()
    if args.status:
        return cmd_status()
    if args.wait:
        return cmd_wait(args.timeout)
    if args.analyze:
        return cmd_analyze(args.session)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
