"""Diff two param pool manifest versions."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.dynamic_param_score.param_pool.manifest import read_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Diff param pool manifests")
    parser.add_argument("manifest_a")
    parser.add_argument("manifest_b")
    args = parser.parse_args()

    a = read_manifest(Path(args.manifest_a))
    b = read_manifest(Path(args.manifest_b))

    diff = {
        "template_count_delta": b.template_count - a.template_count,
        "active_count_delta": b.active_template_count - a.active_template_count,
        "checksum_changed": a.checksum != b.checksum,
        "profile_distribution_delta": {},
    }
    all_profiles = set(a.profile_distribution) | set(b.profile_distribution)
    for p in sorted(all_profiles):
        delta = b.profile_distribution.get(p, 0) - a.profile_distribution.get(p, 0)
        if delta:
            diff["profile_distribution_delta"][p] = delta

    print(json.dumps(diff, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
