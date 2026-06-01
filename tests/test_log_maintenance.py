import gzip

from scripts.maintenance import manage_logs


def test_manage_logs_copy_truncates_large_live_log(tmp_path, monkeypatch):
    root = tmp_path
    logs = root / "logs"
    logs.mkdir()
    live = logs / "web.log"
    live.write_text("x" * 2048, encoding="utf-8")

    monkeypatch.setattr(manage_logs, "ROOT", root)
    monkeypatch.setattr(manage_logs, "LOGS", logs)
    monkeypatch.setattr(manage_logs, "ACTIVE_LOGS", ("web.log",))

    actions = manage_logs.maintain_logs(
        max_active_mb=0,
        compress_after_mb=1,
        delete_after_days=0,
        keep_archives=5,
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
    monkeypatch.setattr(manage_logs, "ACTIVE_LOGS", ())

    actions = manage_logs.maintain_logs(
        max_active_mb=100,
        compress_after_mb=0,
        delete_after_days=0,
        keep_archives=5,
    )

    assert not capture.exists()
    assert any("compressed ram_capture_demo_web.jsonl" in action for action in actions)
    assert (logs / "archive" / "ram_capture_demo_web.jsonl.gz").exists()
