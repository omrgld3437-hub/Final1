"""Uyumluluk shim → scripts/audit/verify_auth_loop_fix.py"""
import runpy
from pathlib import Path
runpy.run_path(str(Path(__file__).resolve().parent / "audit/verify_auth_loop_fix.py"), run_name="__main__")
