"""Uyumluluk shim → scripts/runtime/win_launcher.py"""
import runpy
from pathlib import Path
runpy.run_path(str(Path(__file__).resolve().parent / "runtime/win_launcher.py"), run_name="__main__")
