"""
  main   modulu (manager_server/).
"""
import sys
import logging
from collections import deque
from pathlib import Path

# Run from project root so app and manager_server resolve
_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

# Manager log: [TS] [MANAGER] [LEVEL] message to stdout + logs/manager.log — Türkiye saati
_logs_dir = _root / "logs"
_logs_dir.mkdir(parents=True, exist_ok=True)
_manager_log = _logs_dir / "manager.log"
_fmt = "[%(asctime)s] [MANAGER] [%(levelname)s] %(message)s"
_date_fmt = "%Y-%m-%d %H:%M:%S"
try:
    from app.utils.tz_utils import TurkeyTimeFormatter
    _formatter = TurkeyTimeFormatter(_fmt, datefmt=_date_fmt)
except Exception:
    _formatter = logging.Formatter(_fmt, datefmt=_date_fmt)
class _TerminalTailHandler(logging.Handler):
    """Stdout'a sadece son N satırı yazar; ekran her logda güncellenir (şişme olmaz)."""
    def __init__(self, stream, max_lines=300):
        super().__init__()
        self.stream = stream
        self.buf = deque(maxlen=max_lines)

    def emit(self, record):
        try:
            msg = self.format(record)
            self.buf.append(msg)
            if self.stream.isatty():
                lines = list(self.buf)
                self.stream.write("\033[2J\033[H")
                for line in lines:
                    self.stream.write(line + "\n")
            else:
                self.stream.write(msg + "\n")
            self.stream.flush()
        except Exception:
            self.handleError(record)

_handler_stdout = _TerminalTailHandler(sys.stdout, max_lines=300)
_handler_stdout.setFormatter(_formatter)
_logger = logging.getLogger()
_logger.handlers.clear()
_logger.addHandler(_handler_stdout)
try:
    _handler_file = logging.FileHandler(_manager_log, encoding="utf-8")
    _handler_file.setFormatter(_formatter)
    _logger.addHandler(_handler_file)
except (OSError, PermissionError) as e:
    # Dosya kilitli veya izin yoksa sadece stdout ile devam et
    sys.stderr.write("[MANAGER] Log dosyası açılamadı (%s), sadece konsola yazılıyor.\n" % (e,))
_logger.setLevel(logging.INFO)

def _suppress_ws_connection_logs():
    """WebSocket 'connection open' / 'connection closed' loglarını bastır (log gürültüsü azalsın)."""
    class _Filter(logging.Filter):
        def filter(self, record):
            msg = record.getMessage()
            if "connection open" in msg or "connection closed" in msg:
                return False
            if "WebSocket" in msg and "accepted" in msg:
                return False
            return True
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        log = logging.getLogger(name)
        log.addFilter(_Filter())


def _suppress_connection_reset():
    """Windows: istemci bağlantıyı kapatınca ConnectionResetError / ProactorBasePipeTransport ERROR logunu bastır (düzeltilemeyen uyarı)."""
    class _Filter(logging.Filter):
        def filter(self, record):
            if record.levelno < logging.ERROR:
                return True
            msg = record.getMessage() or ""
            try:
                msg += getattr(record, "exc_text") or ""
            except Exception:
                pass
            if "ConnectionResetError" in msg or "WinError 10054" in msg or "10054" in msg:
                return False
            if "forcibly closed" in msg or "zorla kapat" in msg.lower():
                return False
            if "_call_connection_lost" in msg or "_ProactorBasePipeTransport" in msg or "PipeTransport" in msg:
                return False
            if "Exception in callback" in msg:
                return False
            if record.exc_info and record.exc_info[1]:
                if type(record.exc_info[1]).__name__ == "ConnectionResetError":
                    return False
            return True
    _f = _Filter()
    root = logging.getLogger()
    root.addFilter(_f)
    logging.getLogger("asyncio").addFilter(_f)
    for _name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(_name).addFilter(_f)


if __name__ == "__main__":
    try:
        import fastapi  # noqa: F401
    except ModuleNotFoundError:
        sys.stderr.write(
            "[MANAGER] Hata: 'fastapi' modülü bulunamadı. Manager proje sanal ortamı (.venv) ile çalıştırılmalı.\n"
            "  Windows:  .venv\\Scripts\\activate  sonra  python -m manager_server\n"
            "  veya:     .venv\\Scripts\\python.exe -m manager_server\n"
            "  Mac/Linux: source .venv/bin/activate  sonra  python -m manager_server\n"
            "  Şu an kullanılan: %s\n" % (sys.executable,)
        )
        sys.exit(1)
    import os
    import uvicorn
    _suppress_ws_connection_logs()
    _suppress_connection_reset()
    _allow_remote = (os.environ.get("MANAGER_ALLOW_REMOTE", "").strip().lower() in ("1", "true", "yes"))
    _host = "0.0.0.0" if _allow_remote else "127.0.0.1"
    logging.info("Manager starting (%s:7999)%s", _host, " (remote allowed)" if _allow_remote else "")
    # access_log=False: 200 OK istekleri terminale yazılmaz (şişme önlenir)
    uvicorn.run(
        "manager_server.app:app",
        host=_host,
        port=7999,
        log_level="info",
        access_log=False,
    )
