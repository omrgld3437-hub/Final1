#!/usr/bin/env python3
"""Run V4 night audit — baseline + full scan + tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("PARAM_POOL_VERSION", "v4.0.0")
os.environ.setdefault("PARAM_POOL_LAZY_SHELF", "1")

from app.services.dynamic_param_score.audit_v4.night_audit import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
