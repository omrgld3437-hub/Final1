"""Uyumluluk shim → scripts/devops/setup_env_master_key.py"""
import runpy
from pathlib import Path
runpy.run_path(str(Path(__file__).resolve().parent / "devops/setup_env_master_key.py"), run_name="__main__")
