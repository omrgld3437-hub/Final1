#!/usr/bin/env python3
"""Reversible Dynamic Mode V2 schema migration."""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

from sqlalchemy import text

from app.db.base import engine
from app.db import models


TABLES = (
    models.DynamicFormulaVersion.__table__,
    models.DynamicAnalysisRun.__table__,
    models.DynamicGridUpdate.__table__,
    models.DynamicLearningOutcome.__table__,
    models.DynamicCalibrationRun.__table__,
)


def upgrade(bind=engine) -> None:
    for table in TABLES:
        table.create(bind=bind, checkfirst=True)


def downgrade(bind=engine) -> None:
    # Children first preserves foreign-key integrity.
    for table in reversed(TABLES):
        table.drop(bind=bind, checkfirst=True)


if __name__ == "__main__":
    action = (sys.argv[1] if len(sys.argv) > 1 else "upgrade").lower()
    if action == "upgrade":
        upgrade()
    elif action == "downgrade":
        downgrade()
    else:
        raise SystemExit("usage: migrate_dynamic_mode_v2.py [upgrade|downgrade]")
