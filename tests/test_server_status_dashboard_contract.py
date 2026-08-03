import runpy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    ROOT / "sunucu" / "tools" / "sunucu_durumu_server.py"
).read_text(encoding="utf-8")


def test_uptime_uses_numeric_kernel_duration():
    assert 'open("/proc/uptime", "r", encoding="utf-8")' in SOURCE
    assert '"uptime_seconds": uptime_seconds' in SOURCE


def test_uptime_display_uses_day_hour_or_month_day():
    assert "function formatUptime(seconds)" in SOURCE
    assert "totalDays >= 30" in SOURCE
    assert "ay ${totalDays % 30} gün" in SOURCE
    assert "gün ${totalHours % 24} saat" in SOURCE
    assert "shortUptime" not in SOURCE


def test_dashboard_includes_all_running_app_services_and_swap():
    assert '"aysegul", "kpss", "nginx"' in SOURCE
    assert '"service_memory_mb": service_memory' in SOURCE
    assert '"swap_total_mb"' in SOURCE
    assert '"swap_used_mb"' in SOURCE


def test_closed_browser_requests_do_not_print_terminal_tracebacks():
    assert "class QuietThreadingHTTPServer(ThreadingHTTPServer)" in SOURCE
    assert "daemon_threads = True" in SOURCE
    assert "BrokenPipeError, ConnectionResetError, ConnectionAbortedError" in SOURCE
    assert "QuietThreadingHTTPServer((HOST, PORT), Handler).serve_forever()" in SOURCE


def test_response_write_tolerates_a_browser_disconnect():
    namespace = runpy.run_path(str(ROOT / "sunucu" / "tools" / "sunucu_durumu_server.py"))

    class ClosedWriter:
        def write(self, data):
            raise BrokenPipeError("browser closed the request")

    class FakeRequest:
        wfile = ClosedWriter()

        def send_response(self, code):
            pass

        def send_header(self, name, value):
            pass

        def end_headers(self):
            pass

    namespace["Handler"]._send(FakeRequest(), 200, "{}", "application/json")
