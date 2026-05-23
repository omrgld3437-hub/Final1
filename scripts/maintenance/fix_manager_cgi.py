#!/usr/bin/env python3
"""
Eski manager_backend.py (import cgi) dosyasini Python 3.13 uyumlu hale getirir.
StartManager.bat bu scripti Manager'dan once calistirir.
"""
import re
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_MANAGER_PY = _SCRIPT_DIR / "manager_backend.py"

_PARSE_FUNC = '''
def _parse_multipart_form(rfile, content_type: str, content_length: int):
    """Parse multipart/form-data without cgi (Python 3.13+ compatible)."""
    length = int(content_length) if content_length else 0
    body = rfile.read(length) if length else b""
    boundary = None
    for part in content_type.split(";"):
        part = part.strip()
        if part.lower().startswith("boundary="):
            boundary = part[9:].strip().strip('"').strip("'")
            break
    if not boundary:
        raise ValueError("multipart/form-data: no boundary")
    raw = b"Content-Type: " + content_type.encode("utf-8", errors="replace") + b"\\r\\n\\r\\n" + body
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    result: dict = {}
    for part in msg.walk():
        if part.get_content_disposition() != "form-data":
            continue
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            payload = part.get_payload()
        if isinstance(payload, str):
            payload = payload.encode("utf-8", errors="replace")
        if name not in result:
            result[name] = []
        result[name].append(payload)

    class _Part:
        def __init__(self, raw_bytes):
            self.raw = raw_bytes
            self.value = raw_bytes.decode("utf-8", errors="replace") if raw_bytes else ""
            self.file = io.BytesIO(raw_bytes) if raw_bytes else io.BytesIO(b"")

    class _Form:
        def getvalue(self, key):
            if key not in result or not result[key]:
                return None
            b = result[key][0]
            return b.decode("utf-8", errors="replace") if b else None

        def get(self, key):
            if key not in result or not result[key]:
                return None
            return _Part(result[key][0])

    return _Form()
'''


def main():
    if not _MANAGER_PY.exists():
        print("fix_manager_cgi: manager_backend.py bulunamadi.", file=sys.stderr)
        return 1
    text = _MANAGER_PY.read_text(encoding="utf-8", errors="replace")
    # Zaten guncelse dokunma
    if "def _parse_multipart_form" in text and "import cgi" not in text:
        return 0

    changed = False

    # 1) import cgi -> import io (her turlu satir sonu ve bosluk)
    if "import cgi" in text:
        text = re.sub(r"import\s+cgi\s*\r?\n?", "import io\n", text, count=1)
        changed = True

    # 2) email import'lari ekle (urllib.parse oncesi)
    if "from email import policy" not in text:
        text = re.sub(
            r"(from\s+urllib\.parse\s+import\s+parse_qs[^\n]+\n)",
            r"from email import policy\nfrom email.parser import BytesParser\n\1",
            text,
            count=1,
        )
        changed = True

    # 3) cgi.FieldStorage(...) kullanimi -> _parse_multipart_form
    if "cgi.FieldStorage" in text:
        # env = { ... }; form = cgi.FieldStorage(...) blogunu bul ve degistir
        old_pat = re.compile(
            r"\s*env\s*=\s*\{[^}]+\}\s*\n\s*form\s*=\s*cgi\.FieldStorage\s*\([^)]+\)",
            re.DOTALL,
        )
        new_block = (
            "content_length = int(self.headers.get(\"Content-Length\", \"0\") or \"0\")\n"
            "            form = _parse_multipart_form(self.rfile, content_type, content_length)"
        )
        text = old_pat.sub(new_block, text, count=1)
        changed = True

    # 4) _parse_multipart_form fonksiyonunu ekle (_list_custom_servers oncesi)
    if "def _parse_multipart_form" not in text:
        text = re.sub(
            r"(\n\s*def _list_custom_servers\s*\()",
            _PARSE_FUNC + r"\1",
            text,
            count=1,
        )
        changed = True

    if changed:
        _MANAGER_PY.write_text(text, encoding="utf-8")
        print("fix_manager_cgi: manager_backend.py Python 3.13 icin guncellendi.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except Exception as e:
        print("fix_manager_cgi HATA: %s" % e, file=sys.stderr)
        sys.exit(1)
