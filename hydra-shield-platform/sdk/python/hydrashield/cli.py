"""talaix — command-line interface for the Talaix public API.

Read-only: the CLI only uses public GET endpoints and the optional X-API-Key
metering header. Portfolio / claim / case / report-builder POST endpoints are
not exposed here.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
from typing import Sequence

from .client import TalaixClient, TalaixError


_DEFAULT_BASE_URL = "https://talaix.com"


def _err(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)


def _fmt(val):
    """Format a scalar for human output."""
    if val is None:
        return "—"
    if isinstance(val, float):
        return f"{val:.4f}"
    return str(val)


def _json_out(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def _client(args) -> TalaixClient:
    return TalaixClient(
        base_url=args.base_url,
        api_key=args.api_key,
        timeout=args.timeout,
    )


def cmd_health(client: TalaixClient, args):
    return client.health()


def render_health(result: dict) -> None:
    status = result.get("status", "unknown")
    cache = result.get("cache") or {}
    version = result.get("version", "—")
    print(f"Talaix API: {status} | cache entries: {cache.get('entries_live', '—')} | version {version}")


def cmd_hazards(client: TalaixClient, args):
    return client.hazards()


def render_hazards(result: dict) -> None:
    hazards = result.get("hazards") or []
    if not hazards:
        print("No hazards returned.")
        return
    print(f"{'ID':<20} {'NAME':<34} {'ANALYSIS':<10} {'EVENTS':<10}")
    for h in hazards:
        analysis = "yes" if (h.get("analysis") or {}).get("available") else "no"
        events = "yes" if (h.get("events") or {}).get("available") else "no"
        name = (h.get("name") or "—")[:32]
        print(f"{h.get('id','—'):<20} {name:<34} {analysis:<10} {events:<10}")


def cmd_analyze(client: TalaixClient, args):
    return client.analyze(args.hazard, args.lat, args.lon)


def render_analyze(result: dict) -> None:
    print(f"Hazard: {result.get('hazard_id') or result.get('hazard', '—')}")
    print(f"Status: {result.get('status', '—')}")
    if result.get("status") == "unavailable":
        print(f"Reason: {result.get('unavailable_reason', '—')}")
        return
    level = result.get("level") or {}
    level_label = level.get("label") or "—"
    score = level.get("score")
    basis = level.get("basis")
    line = f"Level: {level_label}"
    if score is not None:
        line += f" (score {score})"
    if basis:
        line += f" — {basis}"
    print(line)
    summary = result.get("summary")
    if summary:
        print(f"Summary: {summary}")


def cmd_verify(client: TalaixClient, args):
    result = client.verify_asset(args.lat, args.lon, name=args.name)
    pdf_path = None
    pdf_bytes = None
    if args.pdf is not None:
        pdf_path = args.pdf
        if pdf_path == "":
            pdf_path = f"talaix_verification_{args.lat}_{args.lon}.pdf"
        url = client.verification_report_url(args.lat, args.lon, name=args.name)
        pdf_bytes = client._download(url)
        with open(pdf_path, "wb") as fh:
            fh.write(pdf_bytes)
    return result, pdf_path, pdf_bytes


def render_verify(payload) -> None:
    result, pdf_path, pdf_bytes = payload
    asset = result.get("asset") or {}
    name = asset.get("name") or "—"
    lat = asset.get("lat")
    lon = asset.get("lon")
    print(f"Asset: {name} ({_fmt(lat)}, {_fmt(lon)})")
    print(f"Verification ID: {result.get('verification_id', '—')}")
    print(f"Status: {result.get('status', '—')} | Hazard checks: {len(result.get('hazard_checks') or [])}")
    checks = result.get("hazard_checks") or []
    if checks:
        print(f"\n{'TAXONOMY HAZARD':<26} {'CLAIM STATUS':<14} {'LEVEL':<10} {'CONFIDENCE':<12}")
        for c in checks:
            level = (c.get("level") or {}).get("label") or "—"
            print(f"{c.get('taxonomy_label','—'):<26} {c.get('claim_status','—'):<14} {level:<10} {c.get('confidence','—'):<12}")
    gaps = result.get("declared_gaps") or []
    print(f"\nDeclared gaps: {len(gaps)}")
    if pdf_path and pdf_bytes is not None:
        print(f"Wrote {len(pdf_bytes)} bytes to {pdf_path}")


def cmd_insurance(client: TalaixClient, args):
    return client.insurance_profile(args.lat, args.lon, radius_km=args.radius_km)


def render_insurance(result: dict) -> None:
    exposure = result.get("exposure") or {}
    print(f"Exposure summary: {exposure.get('summary') or exposure.get('narrative') or '—'}")
    perils = result.get("perils") or []
    if perils:
        print(f"\n{'PERIL':<22} {'LEVEL':<12} {'CLAIM STATUS':<14} {'EVENTS':<24}")
        for p in perils:
            events = p.get("events_status") or "—"
            count = p.get("events_count")
            if count is not None:
                events += f" ({count})"
            level = (p.get("current_level") or p.get("level") or "—")
            print(f"{p.get('peril','—'):<22} {str(level):<12} {p.get('claim_status','—'):<14} {events:<24}")
    note = result.get("loss_quantification_note")
    if note:
        print(f"\nLoss quantification note: {note}")


def cmd_mapcheck(client: TalaixClient, args):
    return client.mapcheck(args.lat, args.lon, radius_m=args.radius_m)


def render_mapcheck(result: dict) -> None:
    loc = result.get("location") or {}
    print(f"Check ID: {result.get('check_id', '—')}")
    print(f"Location: {_fmt(loc.get('lat'))}, {_fmt(loc.get('lon'))} (radius {loc.get('radius_m', '—')} m)")
    print(f"Discrepancies: {result.get('discrepancies_count', 0)}")
    for c in result.get("checks") or []:
        print(f"\n{c.get('id','—'):<30} {c.get('result','—'):<20}")
        print(f"  Basis: {c.get('basis','—')}")
        causes = c.get("possible_causes") or []
        if causes:
            print("  Possible causes:")
            for cause in causes:
                print(f"    • {cause}")


def cmd_briefs(client: TalaixClient, args):
    if args.brief_id:
        return client.brief(args.brief_id)
    return client.briefs(kind=args.kind)


def render_briefs(result: dict) -> None:
    briefs = result.get("briefs") or []
    if not briefs:
        print("No briefs returned.")
        return
    print(f"{'DATE':<12} {'KIND':<14} {'TITLE':<34} {'SOURCES':<10}")
    for b in briefs:
        title = (b.get("title") or "—")[:32]
        count = b.get("source_count", len(b.get("sources") or []))
        print(f"{b.get('date','—'):<12} {b.get('kind','—'):<14} {title:<34} {count:<10}")


def render_brief(result: dict) -> None:
    print(f"Title: {result.get('title', '—')}")
    print(f"Date: {result.get('date', '—')} | Kind: {result.get('kind', '—')}")
    sections = result.get("sections") or []
    if sections:
        print("\nSections:")
        for i, s in enumerate(sections, 1):
            heading = s.get("heading") or "—"
            text = (s.get("text") or "")[:300]
            print(f"{i}. {heading}")
            if text:
                print(f"   {text}{'…' if len(s.get('text') or '') > 300 else ''}")
    sources = result.get("sources") or []
    if sources:
        print(f"\n{'NAME':<26} {'DATE':<12} {'CLAIM STATUS':<14} {'URL':<40}")
        for src in sources:
            name = (src.get("name") or "—")[:24]
            url = (src.get("url") or src.get("link") or "—")[:38]
            print(f"{name:<26} {src.get('date','—'):<12} {src.get('claim_status','—'):<14} {url:<40}")


def cmd_frameworks(client: TalaixClient, args):
    return client.sustainability_frameworks()


def render_frameworks(result: dict) -> None:
    frameworks = result.get("frameworks") or []
    if not frameworks:
        print("No frameworks returned.")
        return
    for fw in frameworks:
        print(f"Framework: {fw.get('name', '—')}")
        coverage = fw.get("coverage_map") or []
        if coverage:
            print(f"{'AREA':<30} {'REF':<20} {'COVERAGE':<14}")
            for row in coverage:
                area = (row.get("area") or "—")[:28]
                ref = (row.get("ref") or "—")[:18]
                cov = row.get("coverage") or "—"
                print(f"{area:<30} {ref:<20} {cov:<14}")
        print()


def cmd_sources(client: TalaixClient, args):
    return client.sources()


def render_sources(result: dict) -> None:
    sources = result.get("sources") or result.get("evaluated") or []
    print(f"Data sources: {len(sources)}")
    if sources:
        print(f"\n{'NAME':<42} {'STATUS':<12} {'PROVIDER':<30}")
        for s in sources:
            name = (s.get("name") or s.get("source") or "—")[:40]
            status = s.get("status") or s.get("integration_status") or "—"
            provider = (s.get("provider") or s.get("operator") or "—")[:28]
            print(f"{name:<42} {status:<12} {provider:<30}")


def _add_analyze_args(p):
    p.add_argument("--hazard", required=True)
    p.add_argument("--lat", type=float, required=True)
    p.add_argument("--lon", type=float, required=True)


def _add_verify_args(p):
    p.add_argument("--lat", type=float, required=True)
    p.add_argument("--lon", type=float, required=True)
    p.add_argument("--name")
    p.add_argument("--pdf", nargs="?", const="", default=None,
                   help="download PDF to PATH (default: talaix_verification_<lat>_<lon>.pdf)")


def _add_insurance_args(p):
    p.add_argument("--lat", type=float, required=True)
    p.add_argument("--lon", type=float, required=True)
    p.add_argument("--radius-km", type=float, default=50)


def _add_mapcheck_args(p):
    p.add_argument("--lat", type=float, required=True)
    p.add_argument("--lon", type=float, required=True)
    p.add_argument("--radius-m", type=int, default=300)


def _add_briefs_args(p):
    p.add_argument("--kind")
    p.add_argument("brief_id", nargs="?")


# Mapping of subcommand -> (add_args, run, render)
_SUBCOMMANDS = {
    "health": (lambda p: None, cmd_health, render_health),
    "hazards": (lambda p: None, cmd_hazards, render_hazards),
    "analyze": (_add_analyze_args, cmd_analyze, render_analyze),
    "verify": (_add_verify_args, cmd_verify, render_verify),
    "insurance": (_add_insurance_args, cmd_insurance, render_insurance),
    "mapcheck": (_add_mapcheck_args, cmd_mapcheck, render_mapcheck),
    "briefs": (_add_briefs_args, cmd_briefs, None),
    "frameworks": (lambda p: None, cmd_frameworks, render_frameworks),
    "sources": (lambda p: None, cmd_sources, render_sources),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="talaix",
        description="Talaix CLI — read-only access to the public Talaix API.",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("TALAIX_BASE_URL", _DEFAULT_BASE_URL),
        help="API base URL (default: https://talaix.com, env: TALAIX_BASE_URL)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("TALAIX_API_KEY"),
        help="optional X-API-Key metering header (env: TALAIX_API_KEY)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="output raw pretty-printed JSON instead of human summaries",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="request timeout in seconds (default: 30)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, (add_args, _run_fn, _render_fn) in _SUBCOMMANDS.items():
        sub = subparsers.add_parser(name, help=f"{name} command")
        add_args(sub)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    add_args, run_fn, render_fn = _SUBCOMMANDS[args.command]

    # briefs uses a single subcommand for list + detail with different renderers.
    if args.command == "briefs" and args.brief_id:
        render_fn = render_brief
    elif render_fn is None:
        render_fn = render_briefs

    try:
        result = run_fn(_client(args), args)
    except TalaixError as exc:
        if args.json:
            _json_out({"error": exc.message, "status": exc.status})
        _err(f"HTTP {exc.status}: {exc.message}")
        return 2
    except urllib.error.URLError as exc:
        reason = exc.reason
        _err(f"could not reach {args.base_url} ({reason})")
        return 3
    except TimeoutError:
        _err(f"could not reach {args.base_url} (timeout)")
        return 3

    if args.json:
        _json_out(result)
    else:
        render_fn(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
