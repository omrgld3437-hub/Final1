"""
FILE: test_execution_balance_check_fail_closed.py
VERSION: v1
DATE: 2026-08-03
CHANGE: Bakiye sorgusu başarısızsa emir gönderilmemesi (K3 regresyon kilidi).

Canlı modda gerçek bakiye bilinmeden emir göndermek, sanal bütçe ile borsadaki
gerçek bakiye ayrıştığında karşılıksız işleme yol açar. Bu invariant'ı yapısal
olarak kilitliyoruz: bakiye kontrolünün ``except`` dalları mutlaka ``continue``
ile bitmelidir, aksi halde akış emir gönderme koduna düşer.
"""

from __future__ import annotations

import ast
from pathlib import Path

EXECUTION_PY = Path(__file__).resolve().parents[1] / "app" / "botengine" / "execution.py"


def _load_tree() -> ast.Module:
    return ast.parse(EXECUTION_PY.read_text(encoding="utf-8"))


def _handlers_logging_balance_failure(tree: ast.Module) -> list[ast.ExceptHandler]:
    """`_log_balance_check_fail` çağıran tüm except dalları."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Name)
                and inner.func.id == "_log_balance_check_fail"
            ):
                found.append(node)
                break
    return found


def test_balance_check_failure_handlers_exist():
    """BUY ve SELL dallarının ikisi de bakiye hatasını ele almalı."""
    handlers = _handlers_logging_balance_failure(_load_tree())
    assert len(handlers) == 2, (
        f"beklenen 2 bakiye-hatası dalı, bulunan {len(handlers)}"
    )


def test_balance_check_failure_always_skips_order():
    """Her bakiye-hatası dalı `continue` ile bitmeli (emir gönderilmemeli)."""
    for handler in _handlers_logging_balance_failure(_load_tree()):
        last = handler.body[-1]
        assert isinstance(last, ast.Continue), (
            f"satır {handler.lineno}: bakiye kontrolü hatasında akış emir gönderme "
            f"koduna düşüyor (son ifade {type(last).__name__}, beklenen Continue)"
        )


def test_no_proceeding_wording_in_balance_failure_logs():
    """Bakiye hatası logları 'proceeding' demiyor; emrin atlandığını söylüyor."""
    source = EXECUTION_PY.read_text(encoding="utf-8")
    for line in source.splitlines():
        if "BALANCE_CHECK_FAIL" in line:
            assert "proceeding" not in line.lower(), line.strip()


def test_log_helper_throttles_401_only(monkeypatch):
    """401 throttle edilir; diğer hatalar her seferinde uyarı olarak loglanır."""
    from app.botengine import execution as ex

    records = []
    monkeypatch.setattr(
        ex.logger, "warning", lambda msg, *a, **k: records.append(("warning", msg % a if a else msg))
    )
    monkeypatch.setattr(
        ex.logger, "debug", lambda msg, *a, **k: records.append(("debug", msg % a if a else msg))
    )
    ex._exec_401_log_throttle.clear()

    ex._log_balance_check_fail(1, "BUY", RuntimeError("401 Unauthorized"))
    ex._log_balance_check_fail(1, "BUY", RuntimeError("401 Unauthorized"))
    levels = [level for level, _ in records]
    assert levels == ["warning", "debug"], levels

    records.clear()
    ex._log_balance_check_fail(1, "SELL", ConnectionError("timeout"))
    ex._log_balance_check_fail(1, "SELL", ConnectionError("timeout"))
    assert [level for level, _ in records] == ["warning", "warning"]
    assert all("emir gönderilmedi" in msg for _, msg in records)
