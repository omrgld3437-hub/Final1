"""Validate param pool JSONL or SQLite artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.dynamic_param_score.param_pool.generator import REQUIRED_COVERAGE_KEYS, assert_required_coverage
from app.services.dynamic_param_score.param_pool.manifest import read_manifest
from app.services.dynamic_param_score.param_pool.models import ParamTemplate
from app.services.dynamic_param_score.param_pool.sqlite_store import load_templates_from_sqlite
from app.services.dynamic_param_score.param_pool.validators import validate_pool


def _load_jsonl(path: Path) -> list[ParamTemplate]:
    templates = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            templates.append(ParamTemplate.model_validate(json.loads(line)))
    return templates


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate param pool artifacts")
    parser.add_argument("--jsonl", type=str, default="")
    parser.add_argument("--sqlite", type=str, default="")
    parser.add_argument("--manifest", type=str, default="")
    parser.add_argument("--min-count", type=int, default=50_000)
    args = parser.parse_args()

    templates: list[ParamTemplate] = []
    if args.sqlite:
        templates = load_templates_from_sqlite(Path(args.sqlite))
    elif args.jsonl:
        templates = _load_jsonl(Path(args.jsonl))
    else:
        print("Provide --jsonl or --sqlite", file=sys.stderr)
        return 1

    active = [t for t in templates if t.status == "active"]
    if len(active) < args.min_count:
        print(f"FAIL: count {len(active)} < min {args.min_count}", file=sys.stderr)
        return 1

    ok, errors = validate_pool(active)
    if not ok:
        print("FAIL: validation errors", file=sys.stderr)
        for e in errors[:20]:
            print(f"  - {e}", file=sys.stderr)
        return 1

    try:
        assert_required_coverage(active)
    except ValueError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    if args.manifest:
        mf = read_manifest(Path(args.manifest))
        if mf.active_template_count != len(active):
            print(
                f"FAIL: manifest active count {mf.active_template_count} != actual {len(active)}",
                file=sys.stderr,
            )
            return 1

    keys = {t.template_key for t in active}
    missing = [k for k in REQUIRED_COVERAGE_KEYS if k not in keys]
    if missing:
        print(f"FAIL: missing coverage keys: {missing}", file=sys.stderr)
        return 1

    print(f"OK: {len(active)} active templates validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
