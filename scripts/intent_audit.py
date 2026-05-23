"""Uyumluluk shim → scripts/audit/intent_audit.py"""
import runpy
from pathlib import Path
runpy.run_path(str(Path(__file__).resolve().parent / "audit/intent_audit.py"), run_name="__main__")
