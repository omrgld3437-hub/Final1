#!/usr/bin/env python3
"""
BINANCE_MASTER_KEY .env'de yoksa veya placeholder ise rastgele anahtar üretir.
Kullanım: proje kökünden  python scripts/setup_env_master_key.py
  - .env yoksa .env.example'tan kopyalar ve BINANCE_MASTER_KEY ekler.
  - .env varsa ve BINANCE_MASTER_KEY yok/placeholder ise günceller.
  - Zaten geçerli bir anahtar varsa dokunmaz.
"""

import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV = ROOT / ".env"
EXAMPLE = ROOT / ".env.example"
PLACEHOLDER = "your-32-character-encryption-key-here"


def main():
    key = secrets.token_urlsafe(24)  # 32 karakter
    if not EXAMPLE.is_file():
        print("Hata: .env.example bulunamadı.", file=sys.stderr)
        sys.exit(1)
    if not ENV.is_file():
        content = EXAMPLE.read_text(encoding="utf-8", errors="replace")
        content = content.replace(
            "BINANCE_MASTER_KEY=" + PLACEHOLDER, "BINANCE_MASTER_KEY=" + key, 1
        )
        if "BINANCE_MASTER_KEY=" + PLACEHOLDER in content:
            content = content.replace(
                "BINANCE_MASTER_KEY=your-32-character-encryption-key-here",
                "BINANCE_MASTER_KEY=" + key,
                1,
            )
        ENV.write_text(content, encoding="utf-8")
        print(".env oluşturuldu ve BINANCE_MASTER_KEY eklendi.")
        print("Web/Manager servisini yeniden başlatın.")
        return
    lines = ENV.read_text(encoding="utf-8", errors="replace").splitlines()
    found = False
    updated = []
    for line in lines:
        if line.strip().startswith("BINANCE_MASTER_KEY="):
            val = line.split("=", 1)[1].strip().strip('"').strip("'")
            if not val or val == PLACEHOLDER or len(val) < 32:
                updated.append("BINANCE_MASTER_KEY=" + key)
                found = True
            else:
                updated.append(line)
        else:
            updated.append(line)
    if not found:
        for i, line in enumerate(updated):
            if line.strip().startswith("BINANCE_MASTER_KEY="):
                break
        else:
            updated.append("")
            updated.append("BINANCE_MASTER_KEY=" + key)
            found = True
    if found:
        ENV.write_text("\n".join(updated) + "\n", encoding="utf-8")
        print(".env güncellendi: BINANCE_MASTER_KEY ayarlandı.")
        print("Web/Manager servisini yeniden başlatın.")
    else:
        print("BINANCE_MASTER_KEY zaten .env'de tanımlı; değiştirilmedi.")


if __name__ == "__main__":
    main()
