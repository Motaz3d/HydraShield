#!/usr/bin/env python
"""
Run the HydraShield Benchmark Suite (config/benchmark_suite.json) against
the Ground Truth Event Registry (config/ground_truth_events.json).

Every executable case runs the model's OWN declared detector on real
fetched series (ERA5 / GloFAS via Open-Meteo, ~10-30-year series per case,
platform-cached). The summary is honest: passed / failed / key_required /
errors — 'passed' means the detector reproduced the expected REAL signal
in the declared window (detection reproduction, NOT a skill score, NOT a
validation claim). key_required cases are never executed and never counted
as failures.

Usage:

    python scripts/run_benchmarks.py

Scheduling: wired into NOTHING automatic — manual and CI-manual invocation
only. Each run writes an immutable file
data/evaluation/benchmark_run_<timestamp>.json (never overwritten).

Exit code: 0 always, unless errors > 0 (a case could not even execute —
fetch failure, missing data, bug). 'failed' cases (real data, signal not
reproduced) do NOT set a non-zero exit: they are reported honestly in the
run file and summary.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.climate import benchmark  # noqa: E402


def main() -> int:
    run = benchmark.run_suite()
    summary = run["summary"]

    print("HydraShield Benchmark Suite v%s — %s" % (run["suite_version"], run["executed_at"]))
    print("=" * 78)
    for r in run["results"]:
        line = "%-34s %-30s %s" % (r["case_id"], r["model_id"], r["status"].upper())
        if r["status"] == "error":
            line += "  (%s)" % (r["evidence"].get("error") or "unknown error")
        if r["status"] == "key_required":
            line += "  (not executed — FIRMS_MAP_KEY required)"
        print(line)
    print("=" * 78)
    print(
        "total=%(total)d passed=%(passed)d failed=%(failed)d "
        "key_required=%(key_required)d errors=%(errors)d" % summary
    )
    print("run file (immutable): %s" % run["run_file"])
    print("note: passed = detector reproduced the expected REAL signal in the")
    print("declared window on real data — detection reproduction, not a skill")
    print("score and not a validation claim.")
    return 0 if summary["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
