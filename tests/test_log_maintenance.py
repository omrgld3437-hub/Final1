"""Log maintenance — rotation, compression, 90-day retention."""

from __future__ import annotations

import gzip
import time

from scripts.maintenance import manage_logs


def test_manage_logs_copy_truncates_large_live_log(tmp_path, monkeypatch):
    root = tmp_path
    logs = root / "logs"
    logs.mkdir()
    live = logs / "web.log"
    live.write_text("x" * 2048, encoding="utf-8")

    monkeypatch.setattr(manage_logs, "ROOT", root)
    monkeypatch.setattr(manage_logs, "LOGS", logs)
    monkeypatch.setattr(manage_logs, "RUN", root / ".run")
    monkeypatch.setattr(manage_logs, "ACTIVE_LOGS", ("web.log",))

    actions = manage_logs.maintain_logs(
        max_active_mb=0,
        compress_after_mb=1,
        delete_after_days=0,
        keep_archives=0,
        rotate_interval_days=0,
    )

    assert live.exists()
    assert live.read_text(encoding="utf-8") == ""
    assert any("rotated-live web.log" in action for action in actions)
    archives = list((logs / "archive").glob("web.log.*.gz"))
    assert len(archives) == 1
    with gzip.open(archives[0], "rt", encoding="utf-8") as f:
        assert f.read() == "x" * 2048


def test_manage_logs_compresses_old_ram_capture(tmp_path, monkeypatch):
    root = tmp_path
    logs = root / "logs"
    logs.mkdir()
    capture = logs / "ram_capture_demo_web.jsonl"
    capture.write_text("line\n" * 400, encoding="utf-8")

    monkeypatch.setattr(manage_logs, "ROOT", root)
    monkeypatch.setattr(manage_logs, "LOGS", logs)
    monkeypatch.setattr(manage_logs, "RUN", root / ".run")
    monkeypatch.setattr(manage_logs, "ACTIVE_LOGS", ())

    actions = manage_logs.maintain_logs(
        max_active_mb=100,
        compress_after_mb=0,
        delete_after_days=0,
        keep_archives=0,
        rotate_interval_days=0,
    )

    assert not capture.exists()
    assert any("compressed ram_capture_demo_web.jsonl" in action for action in actions)
    assert (logs / "archive" / "ram_capture_demo_web.jsonl.gz").exists()


def test_retention_deletes_old_archives(tmp_path, monkeypatch):
    root = tmp_path
    logs = root / "logs"
    archive = logs / "archive"
    archive.mkdir(parents=True)
    old = archive / "web.log.old.gz"
    old.write_bytes(b"old")
    old_ts = time.time() - (100 * 86400)
    import os

    os.utime(old, (old_ts, old_ts))

    monkeypatch.setattr(manage_logs, "ROOT", root)
    monkeypatch.setattr(manage_logs, "LOGS", logs)
    monkeypatch.setattr(manage_logs, "RUN", root / ".run")
    monkeypatch.setattr(manage_logs, "ACTIVE_LOGS", ())

    actions = manage_logs.maintain_logs(
        max_active_mb=100,
        compress_after_mb=100,
        delete_after_days=90,
        keep_archives=0,
        rotate_interval_days=0,
    )

    assert not old.exists()
    assert any("deleted-old" in a for a in actions)


def test_run_if_due_throttles(tmp_path, monkeypatch):
    root = tmp_path
    run = root / ".run"
    run.mkdir()
    (run / "last_log_maintain_ts").write_text(str(time.time()), encoding="utf-8")
    monkeypatch.setattr(manage_logs, "ROOT", root)
    monkeypatch.setattr(manage_logs, "LAST_MAINTAIN_STAMP", run / "last_log_maintain_ts")
    monkeypatch.setenv("LOG_MAINTAIN_INTERVAL_SEC", "86400")

    assert manage_logs.run_if_due(force=False) == []


def test_run_dir_logs_rotated(tmp_path, monkeypatch):
    root = tmp_path
    logs = root / "logs"
    run = root / ".run"
    run.mkdir()
    logs.mkdir()
    server = run / "server.log"
    server.write_text("y" * 3000, encoding="utf-8")

    monkeypatch.setattr(manage_logs, "ROOT", root)
    monkeypatch.setattr(manage_logs, "LOGS", logs)
    monkeypatch.setattr(manage_logs, "RUN", run)
    monkeypatch.setattr(manage_logs, "ACTIVE_LOGS", ())
    monkeypatch.setattr(manage_logs, "RUN_ACTIVE_LOGS", ("server.log",))

    actions = manage_logs.maintain_logs(
        max_active_mb=0,
        compress_after_mb=1,
        delete_after_days=0,
        keep_archives=0,
        rotate_interval_days=0,
    )

    assert server.read_text(encoding="utf-8") == ""
    assert any("server.log" in a for a in actions)
    assert list((logs / "archive" / "run").glob("server.log.*.gz"))
