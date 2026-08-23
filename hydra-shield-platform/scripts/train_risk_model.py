#!/usr/bin/env python
"""
Train the Talaix wildfire risk model on real fire history (Phase 6).

Requires:
    FIRMS_MAP_KEY  — free NASA FIRMS API key
                     (https://firms.modaps.eosdis.nasa.gov/api/area/)

Example:
    FIRMS_MAP_KEY=... python scripts/train_risk_model.py \
        --bbox -9.5,36.0,-6.0,39.5 --fire-days 10 --out data/models

The trained artifact is written to --out but is NOT promoted to serving
automatically; review the metrics in wildfire_risk_model.meta.json first.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.prediction.training import train_model  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bbox", required=True,
                        help="west,south,east,north in degrees (e.g. -9.5,36.0,-6.0,39.5)")
    parser.add_argument("--fire-days", type=int, default=10,
                        help="Look-back window for FIRMS detections (max 10)")
    parser.add_argument("--max-positives", type=int, default=400)
    parser.add_argument("--out", default="data/models", help="Output directory")
    args = parser.parse_args()

    try:
        bbox = tuple(float(v) for v in args.bbox.split(","))
        assert len(bbox) == 4
    except (ValueError, AssertionError):
        print("Invalid --bbox; expected west,south,east,north")
        return 2

    if not os.environ.get("FIRMS_MAP_KEY"):
        print("FIRMS_MAP_KEY is not set. Register free at "
              "https://firms.modaps.eosdis.nasa.gov/api/area/")
        return 2

    summary = train_model(
        bbox=bbox,  # type: ignore[arg-type]
        out_dir=args.out,
        fire_days=args.fire_days,
        max_positives=args.max_positives,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
