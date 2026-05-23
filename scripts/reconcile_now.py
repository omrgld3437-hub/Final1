"""Uyumluluk shim → scripts/audit/reconcile_now.py"""
import runpy
from pathlib import Path
runpy.run_path(str(Path(__file__).resolve().parent / "audit/reconcile_now.py"), run_name="__main__")
