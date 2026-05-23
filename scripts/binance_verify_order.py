"""Uyumluluk shim → scripts/audit/binance_verify_order.py"""
import runpy
from pathlib import Path
runpy.run_path(str(Path(__file__).resolve().parent / "audit/binance_verify_order.py"), run_name="__main__")
