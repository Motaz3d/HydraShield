"""
TX CLI — the terminal interface to TX Core (``python -m tx_core`` or the
``tx`` console entry point).

Dependency-free (argparse + stdlib only) so it works in the production
environment exactly as on a laptop. Output is plain text by default and
``--json`` for machine consumption. The honesty contract applies here too:
unavailable hazards are printed as unavailable, never invented.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional

from ._version import TX_VERSION
from .engine import DEPTHS, TXEngine
from .registry import TXRegistry


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _print_text(lines: List[str]) -> None:
    print("\n".join(lines))


def _hazard_table(descriptors: List[Dict[str, Any]]) -> List[str]:
    rows = []
    for d in descriptors:
        analysis = d.get("analysis", {})
        rows.append(
            f"{d.get('id', '?'):<12} {d.get('name', '?'):<45} "
            f"available={analysis.get('available', False)}"
        )
    return rows


def cmd_analyze(args: argparse.Namespace) -> int:
    engine = TXEngine()
    try:
        result = engine.analyze(
            lat=args.lat,
            lon=args.lon,
            hazards=args.hazard,
            depth=args.depth,
            name=args.name,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        _print_json(result.to_dict())
        return 0
    if args.format == "md":
        from .reporting import result_to_markdown

        print(result_to_markdown(result))
        return 0

    lines = [
        f"TX Analysis {result.analysis_id}",
        f"  Location : {result.location.name or ''} "
        f"({result.location.lat:.4f}, {result.location.lon:.4f})",
        f"  Depth    : {result.depth}",
        f"  Status   : {result.status}",
        f"  Engine   : tx-core {result.tx_version} / {result.engine_version}",
        "",
    ]
    for hr in result.results:
        level = hr.level.to_dict() if hasattr(hr.level, "to_dict") else hr.level
        label = level.get("label") if level else "-"
        lines.append(f"  {hr.hazard:<12} {hr.status:<12} level={label}")
        if hr.unavailable_reason:
            lines.append(f"    reason: {hr.unavailable_reason}")
        if hr.summary:
            lines.append(f"    {hr.summary}")
    if result.sources:
        lines.append("")
        lines.append("  Sources:")
        for s in result.sources:
            lines.append(f"    - {s.get('name')} ({s.get('url')})")
    _print_text(lines)
    return 0


def cmd_hazards(args: argparse.Namespace) -> int:
    engine = TXEngine()
    descriptors = engine.hazards()
    if args.json:
        _print_json(descriptors)
        return 0
    _print_text(["Registered TX hazards:", ""] + _hazard_table(descriptors))
    return 0


def cmd_sources(args: argparse.Namespace) -> int:
    engine = TXEngine()
    sources = engine.sources()
    if args.json:
        _print_json(sources)
        return 0
    _print_text(
        ["Official data sources behind TX hazards:", ""]
        + [f"  - {s.get('name')} ({s.get('url')})" for s in sources]
    )
    return 0


def cmd_registry(args: argparse.Namespace) -> int:
    registry = TXRegistry()
    if args.json:
        _print_json(registry.summary())
        return 0
    _print_text(
        [
            "TX Registry summary:",
            f"  hazards             : {', '.join(registry.hazard_ids())}",
            f"  models              : {', '.join(m for m in registry.summary()['models'])}",
            f"  datasets integrated : {registry.summary()['datasets_integrated']}",
            f"  sources integrated  : {registry.summary()['sources_integrated']}",
            f"  sources audit date  : {registry.summary()['audit_dates']['sources']}",
        ]
    )
    return 0


def cmd_version(_args: argparse.Namespace) -> int:
    _print_json(
        {
            "tx_version": TX_VERSION,
            "engine_version": TX_VERSION,
            "levels": TXEngine().version_info()["levels"],
        }
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tx",
        description="TX Core — the Talaix analytical engine (CLI).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_analyze = sub.add_parser("analyze", help="Run a TX analysis for a location")
    p_analyze.add_argument("--lat", type=float, required=True)
    p_analyze.add_argument("--lon", type=float, required=True)
    p_analyze.add_argument("--hazard", action="append", default=None,
                           help="Hazard id (repeatable; default: all)")
    p_analyze.add_argument("--depth", choices=DEPTHS, default="standard")
    p_analyze.add_argument("--name", default=None)
    p_analyze.add_argument("--json", action="store_true")
    p_analyze.add_argument("--format", choices=("text", "md"), default="text")
    p_analyze.set_defaults(func=cmd_analyze)

    p_hazards = sub.add_parser("hazards", help="List registered TX hazards")
    p_hazards.add_argument("--json", action="store_true")
    p_hazards.set_defaults(func=cmd_hazards)

    p_sources = sub.add_parser("sources", help="List official TX data sources")
    p_sources.add_argument("--json", action="store_true")
    p_sources.set_defaults(func=cmd_sources)

    p_registry = sub.add_parser("registry", help="TX Registry digest")
    p_registry.add_argument("--json", action="store_true")
    p_registry.set_defaults(func=cmd_registry)

    p_version = sub.add_parser("version", help="Engine versions")
    p_version.set_defaults(func=cmd_version)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
