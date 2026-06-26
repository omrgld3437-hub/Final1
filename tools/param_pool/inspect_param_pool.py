"""Inspect param pool manifest and profile distribution."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.dynamic_param_score.param_pool.manifest import read_manifest
from app.services.dynamic_param_score.param_pool.sqlite_store import load_templates_from_sqlite


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect param pool")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--sqlite", default="")
    args = parser.parse_args()

    mf = read_manifest(Path(args.manifest))
    print(json.dumps(mf.model_dump(), indent=2, ensure_ascii=False))

    if args.sqlite:
        templates = load_templates_from_sqlite(Path(args.sqlite))
        print(f"\nSQLite active templates: {len(templates)}")
        sample = templates[:5]
        for t in sample:
            print(f"  - {t.template_key} ({t.profile_family})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
