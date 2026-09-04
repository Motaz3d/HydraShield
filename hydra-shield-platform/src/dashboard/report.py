"""
Professional PDF reporting for Talaix analyses.

Generates a real report from the same cached real analysis (and optional
history) that backs the API — every number in the PDF comes from those
payloads, with the same provenance, freshness and limitations. No fake
charts: the only chart is drawn from the real FWI series.

Sections follow the public-trust requirements: executive summary, why this
score, conditions, fire danger, what changed, exposure, micro-area,
population & exposure, ignition susceptibility, smoke intelligence,
proactive recommendations, environmental solutions, modelled scenarios,
action plan, historical lessons (optional), validation status, sources &
provenance, scientific limitations. OBSERVED / DERIVED / MODELLED /
FORECAST / RECOMMENDED / UNKNOWN / UNAVAILABLE labels are kept visible.
"""

from __future__ import annotations

import hashlib
import io
import json
from typing import Dict, List, Optional

from ..climate.tx_seal import issue_seal

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    )
    _HAS_REPORTLAB = True
except ImportError:  # honest failure handled by the endpoint
    _HAS_REPORTLAB = False

MODEL_VERSION = "1.0.0"
# Report-generation engine (layout/metadata composition) version, independent
# of the risk-model version above.
REPORT_ENGINE_VERSION = "2.0.0"
VALIDATION_STATUS = (
    "NOT VALIDATED — the Talaix screening score has not yet completed "
    "validation against real historical fire observations (see "
    "docs/VALIDATION.md). Treat all values as screening-level indicators."
)

REPORT_TYPES = {
    "simple": {
        "title": "Simple Report",
        "audience": "For citizens, property owners and general users",
    },
    "decision": {
        "title": "Decision-Support Report",
        "audience": "For municipalities, companies, landowners and emergency planners",
    },
    "scientific": {
        "title": "Scientific / Technical Report",
        "audience": "For researchers, technical institutions and government agencies",
    },
}

_ACCENT = colors.HexColor("#0ea5e9")
_DARK = colors.HexColor("#0f172a")
_MUTED = colors.HexColor("#64748b")

# Paragraph styles with correct leading (the previous overlap defect came
# from reportlab's 12 pt default leading applied to larger font sizes).
_TITLE = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=20,
                        leading=24, textColor=_DARK, spaceAfter=2)
_SUBTITLE = ParagraphStyle("subtitle", fontName="Helvetica", fontSize=10,
                           leading=13, textColor=_ACCENT, spaceAfter=2)
_S = ParagraphStyle("section", fontName="Helvetica-Bold", fontSize=13,
                    leading=16, textColor=_DARK, spaceBefore=12, spaceAfter=5,
                    keepWithNext=1)
_B = ParagraphStyle("body", fontName="Helvetica", fontSize=9.5, leading=13,
                    spaceAfter=3)
_SM = ParagraphStyle("small", fontName="Helvetica", fontSize=8, leading=11,
                     textColor=_MUTED, spaceAfter=2)


def _footer(canvas, doc):
    """Professional footer with page numbers + report metadata."""
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#cbd5e1"))
    canvas.setLineWidth(0.5)
    canvas.line(18 * mm, 12 * mm, 192 * mm, 12 * mm)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(_MUTED)
    canvas.drawString(
        18 * mm, 8 * mm,
        f"Talaix — real-data wildfire decision support · model v{MODEL_VERSION} · "
        f"{doc._report_meta.get('generated', '')} · "
        f"report {doc._report_meta.get('report_id', '')}",
    )
    canvas.drawRightString(192 * mm, 8 * mm, f"Page {doc.page}")
    canvas.restoreState()


def _kind_label(kind: Optional[str]) -> str:
    return (kind or "unavailable").upper()


def documented_losses_rows(losses: Optional[Dict]) -> List[List[str]]:
    """Table rows for the "Documented disaster losses" report section.

    Pure data (no reportlab) so the offline tests can pin exactly what the
    PDF section renders: one row per documented figure, carrying the event
    name, figure label, value+unit and source+period.
    """
    rows = [["Event", "Figure", "Value", "Source · period"]]
    for fig in (losses or {}).get("figures") or []:
        value = fig.get("value")
        rows.append([
            fig.get("event") or "—",
            fig.get("label") or "—",
            f"{value} {fig.get('unit')}" if value is not None else "—",
            f"{fig.get('source')} · {fig.get('reference_period')}",
        ])
    return rows


def _kv_table(rows: List[List[str]], widths=(45 * mm, 115 * mm)) -> Table:
    t = Table(rows, colWidths=list(widths))
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (0, -1), _MUTED),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _fmt(v, unit="", digits=1):
    if v is None:
        return "unavailable"
    if isinstance(v, float):
        v = round(v, digits)
    return f"{v}{unit}"


def report_content_id(analysis: Dict, report_type: str) -> str:
    """
    Stable report ID: a content hash of the analysis payload (excluding the
    volatile generation timestamp and the authenticity seal, which is added
    after content is frozen) plus the report type. Identical content always
    yields the same ID; any content change yields a new one.
    """
    basis = {k: v for k, v in (analysis or {}).items()
             if k not in ("generated_at", "authenticity")}
    canonical = json.dumps({"analysis": basis, "report_type": report_type},
                           sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _evidence_status_summary(analysis: Dict) -> str:
    """Counts per claim status across the analysis' data claims (provenance
    kinds and risk-factor kinds), using the report's label vocabulary.
    Legacy US spelling is normalised (modeled → MODELLED)."""
    counts: Dict[str, int] = {}
    _alias = {"modeled": "modelled", "derived": "inferred"}

    def _bump(kind: Optional[str]) -> None:
        raw = (kind or "unavailable").lower()
        label = _alias.get(raw, raw).upper()
        counts[label] = counts.get(label, 0) + 1

    for p in (analysis.get("provenance") or {}).values():
        _bump((p or {}).get("kind"))
    for f in (analysis.get("risk_explanation") or {}).get("factors") or []:
        _bump(f.get("provenance_kind"))
    if not counts:
        return "no provenance recorded"
    return " · ".join(f"{label}: {counts[label]}" for label in sorted(counts))


def _data_sources(analysis: Dict) -> str:
    """De-duplicated data-source list from the analysis provenance."""
    sources: List[str] = []
    for p in (analysis.get("provenance") or {}).values():
        source = str((p or {}).get("source") or "").strip()
        if source and source not in sources:
            sources.append(source)
    return "; ".join(sources) if sources else "no provenance recorded"


def _metadata_table(analysis: Dict, report_type: str, loc: Dict) -> Table:
    """Report metadata block (Stage 7): identity, engine, sources, evidence
    and validation status — placed right after the title on every report."""
    rows = [
        ["Report ID", report_content_id(analysis, report_type)],
        ["Generated", str(analysis.get("generated_at") or "—")],
        ["Location", f"{loc.get('name', '')} "
         f"({loc.get('latitude')}, {loc.get('longitude')})"],
        ["Report engine", f"v{REPORT_ENGINE_VERSION} (risk model v{MODEL_VERSION}, "
                          f"report type: {report_type})"],
        ["Data sources", Paragraph(_data_sources(analysis), _SM)],
        ["Evidence status", Paragraph(_evidence_status_summary(analysis), _SM)],
        ["Validation status", Paragraph(VALIDATION_STATUS, _SM)],
    ]
    return _kv_table(rows)


def _bar_chart(title: str, pairs, note: str = ""):
    """Horizontal bar chart for real count data (reportlab graphics).

    ``pairs`` is a list of (label, value) from real analysis data. Returns
    None when there is nothing meaningful to draw (fewer than 2 non-zero
    values) — a chart is only rendered when it materially helps.
    """
    if not _HAS_REPORTLAB:
        return None
    data = [(str(l), float(v)) for l, v in (pairs or [])
            if v is not None and float(v) > 0]
    if len(data) < 2:
        return None
    from reportlab.graphics.shapes import Drawing, Rect, String

    W, row_h = 460.0, 22.0
    H = 30 + row_h * len(data) + 10
    label_w = 130.0
    max_v = max(v for _l, v in data) or 1.0
    bar_w_max = W - label_w - 70

    d = Drawing(W, H)
    d.add(String(0, H - 12, title, fontName="Helvetica-Bold", fontSize=9,
                 fillColor=_DARK))
    y = H - 30
    for label, value in data:
        w = max(2.0, bar_w_max * value / max_v)
        d.add(String(0, y + 3, label, fontName="Helvetica", fontSize=7.5,
                     fillColor=_DARK))
        d.add(Rect(label_w, y, w, row_h - 8,
                   fillColor=_ACCENT, fillOpacity=0.75,
                   strokeColor=None))
        d.add(String(label_w + w + 5, y + 3, f"{value:,.0f}",
                     fontName="Helvetica", fontSize=7.5, fillColor=_MUTED))
        y -= row_h
    if note:
        d.add(String(0, 2, note, fontName="Helvetica", fontSize=7,
                     fillColor=_MUTED))
    return d


def _fwi_chart(fwi_block: Dict):
    """Real FWI series line chart (reportlab graphics). None when no series."""
    series = (fwi_block or {}).get("series") or []
    if len(series) < 3 or not _HAS_REPORTLAB:
        return None
    from reportlab.graphics.shapes import Drawing, String
    from reportlab.graphics.charts.lineplots import LinePlot
    from reportlab.graphics.charts.axes import XValueAxis

    data = [[(i, float(d["fwi"])) for i, d in enumerate(series) if d.get("fwi") is not None]]
    drawing = Drawing(460, 130)
    lp = LinePlot()
    lp.x = 35
    lp.y = 25
    lp.height = 90
    lp.width = 400
    lp.data = data
    lp.lines[0].strokeColor = _ACCENT
    lp.lines[0].strokeWidth = 2
    xa = XValueAxis()
    xa.valueMin = 0
    xa.valueMax = max(1, len(data[0]) - 1)
    xa.valueStep = max(1, (len(data[0]) - 1) // 6)
    lp.xValueAxis = xa
    drawing.add(lp)
    drawing.add(String(35, 118, "FWI (real daily series)", fontName="Helvetica-Bold",
                       fontSize=9, fillColor=_DARK))
    drawing.add(String(400, 8, f"{series[0].get('date')} → {series[-1].get('date')}",
                       fontName="Helvetica", fontSize=7, fillColor=_MUTED))
    return drawing


_CLASS_COLORS = {
    "Low": colors.HexColor("#22c55e"),
    "Moderate": colors.HexColor("#eab308"),
    "High": colors.HexColor("#f97316"),
    "Extreme": colors.HexColor("#ef4444"),
}


def _map_drawing(analysis: Dict, grid: Optional[Dict]):
    """
    Real-data map graphic: the actual fire-danger grid cells around the
    location (FWI-derived risk per cell), the analysed point, and real
    active-fire detections when available. No fake map data: when the grid
    is unavailable the caller states it instead of drawing anything.
    """
    if not _HAS_REPORTLAB or not grid or grid.get("error"):
        return None
    features = grid.get("features") or []
    if not features:
        return None
    from reportlab.graphics.shapes import Drawing, Rect, Circle, String, Line

    W, H = 460.0, 300.0
    bbox = (grid.get("grid") or {}).get("bbox") or []
    if len(bbox) != 4:
        return None
    south, west, north, east = [float(v) for v in bbox]
    span_x = max(east - west, 1e-9)
    span_y = max(north - south, 1e-9)
    scale = min((W - 60) / span_x, (H - 50) / span_y)
    ox, oy = 30.0, 30.0

    def px(lon, lat):
        return ox + (lon - west) * scale, oy + (lat - south) * scale

    d = Drawing(W, H)
    # Real grid cells coloured by their real risk class.
    for f in features:
        coords = ((f.get("geometry") or {}).get("coordinates") or [[]])[0]
        if not coords:
            continue
        lons = [c[0] for c in coords]
        lats = [c[1] for c in coords]
        x0, y0 = px(min(lons), min(lats))
        w = (max(lons) - min(lons)) * scale
        h = (max(lats) - min(lats)) * scale
        props = f.get("properties") or {}
        color = _CLASS_COLORS.get(props.get("risk_class"),
                                  colors.HexColor("#94a3b8"))
        d.add(Rect(x0, y0, w, h, fillColor=color, fillOpacity=0.55,
                   strokeColor=colors.HexColor("#334155"), strokeWidth=0.3))

    # Real active-fire detections (FIRMS), when available.
    fires = analysis.get("active_fires") or {}
    n_fire = 0
    if fires.get("available"):
        for f in (fires.get("fires") or [])[:60]:
            fx, fy = px(float(f["lon"]), float(f["lat"]))
            if ox <= fx <= ox + (east - west) * scale and oy <= fy <= oy + (north - south) * scale:
                d.add(Circle(fx, fy, 2.4, fillColor=colors.HexColor("#7f1d1d"),
                             strokeColor=colors.white, strokeWidth=0.4))
                n_fire += 1

    # The analysed location.
    loc = analysis.get("location") or {}
    lx, ly = px(float(loc.get("longitude")), float(loc.get("latitude")))
    d.add(Circle(lx, ly, 5, fillColor=colors.HexColor("#0ea5e9"),
                 strokeColor=colors.white, strokeWidth=1.2))
    d.add(String(lx + 8, ly - 3, "analysed point", fontName="Helvetica-Bold",
                 fontSize=7.5, fillColor=_DARK))

    # Legend + scale/source note.
    ly0 = H - 12
    for i, (cls, col) in enumerate(_CLASS_COLORS.items()):
        d.add(Rect(ox + i * 70, ly0 - 7, 8, 8, fillColor=col, fillOpacity=0.55,
                   strokeColor=colors.HexColor("#334155"), strokeWidth=0.3))
        d.add(String(ox + 11 + i * 70, ly0 - 6, cls, fontName="Helvetica",
                     fontSize=7, fillColor=_DARK))
    cell_km = (grid.get("grid") or {}).get("cell_size_km")
    d.add(String(ox, 10,
                 f"Fire-danger grid (FWI-derived risk, real Open-Meteo data; "
                 f"~{cell_km} km cells)" + (f" · {n_fire} FIRMS detection(s)"
                                           if n_fire else ""),
                 fontName="Helvetica", fontSize=7, fillColor=_MUTED))
    d.add(Line(ox, 22, ox + 60, 22, strokeColor=_MUTED, strokeWidth=0.7))
    d.add(String(ox + 62, 20, "N ↑", fontName="Helvetica", fontSize=7,
                 fillColor=_MUTED))
    return d


def build_report_pdf(analysis: Dict, history: Optional[Dict] = None,
                     report_type: str = "decision",
                     grid: Optional[Dict] = None,
                     solutions: Optional[Dict] = None,
                     funding: Optional[Dict] = None,
                     losses: Optional[Dict] = None,
                     loss_estimate: Optional[Dict] = None) -> bytes:
    """
    Render a professional PDF report from a real analysis payload.

    ``report_type`` selects the audience-specific composition — all types
    are rendered from the SAME analysis object (never a separate
    calculation): "simple" (citizens), "decision" (operational users),
    "scientific" (full methodology appendix). ``solutions``/``funding``
    carry the Solutions/Funding Intelligence engine outputs (decision and
    scientific types); when absent, the section is honestly omitted.
    ``losses`` carries ``documented_loss_figures`` output for the location;
    the "Documented disaster losses" section renders published figures when
    present and declares their absence otherwise. ``loss_estimate`` carries
    the Talaix loss-screening ESTIMATE (strictly separated sub-block —
    ESTIMATED, never merged with the documented figures).
    """
    if not _HAS_REPORTLAB:
        raise RuntimeError("reportlab is not installed on this server")
    if report_type not in REPORT_TYPES:
        raise ValueError(f"Unknown report type: {report_type!r}")
    type_info = REPORT_TYPES[report_type]
    simple = report_type == "simple"
    scientific = report_type == "scientific"

    # Sequential section numbering (handles optional sections cleanly).
    _sec_no = [0]

    def S(title: str) -> str:
        _sec_no[0] += 1
        return f"{_sec_no[0]}. {title}"

    loc = analysis.get("location") or {}
    a = analysis.get("analysis") or {}
    risk = a.get("risk") or {}
    fd = analysis.get("fire_danger") or {}
    ex = analysis.get("risk_explanation") or {}
    weather = analysis.get("weather") or {}
    terrain = analysis.get("terrain") or {}
    landcover = analysis.get("landcover") or {}
    satellite = analysis.get("satellite") or {}
    fires = analysis.get("active_fires") or {}
    change = analysis.get("change") or {}
    exposure = analysis.get("exposure") or {}
    micro = analysis.get("micro_area") or {}
    population = analysis.get("population") or {}
    ignition = analysis.get("ignition") or {}
    smoke_s = analysis.get("smoke_scenario") or {}
    ecology = analysis.get("ecology") or {}
    scenarios = analysis.get("scenarios") or []
    recs = analysis.get("recommendations") or []
    plan = analysis.get("action_plan") or {}
    provenance = analysis.get("provenance") or {}

    story: List = []

    # ---- Header ---------------------------------------------------------
    story.append(Paragraph("Talaix Wildfire Risk Report", _TITLE))
    story.append(Paragraph(
        f"{type_info['title']} — {type_info['audience']}", _SUBTITLE))
    story.append(Paragraph(
        f"{loc.get('name', '')} — {loc.get('latitude')}, {loc.get('longitude')}",
        _B))
    story.append(Paragraph(
        f"Generated: {analysis.get('generated_at')} · Model version {MODEL_VERSION} · "
        f"Report type: {report_type} · "
        "Real-data report: every value is observed, derived or modelled with "
        "provenance; unavailable data is stated.", _SM))
    story.append(Spacer(1, 8))

    # ---- Report metadata (identity/engine/sources/evidence/validation) ----
    story.append(Paragraph("Report metadata", _S))
    story.append(_metadata_table(analysis, report_type, loc))
    story.append(Spacer(1, 4))

    # ---- 1. Executive summary -------------------------------------------
    story.append(Paragraph(S("Executive summary"), _S))
    story.append(_kv_table([
        ["Composite risk score", f"{_fmt(risk.get('baseline'), '', 0)} / 100 — "
         f"{risk.get('class') or 'unavailable'} (DERIVED)"],
        ["Fire danger (FWI)", (_fmt(fd.get("fwi"), '', 1) + f" — {fd.get('class')} on {fd.get('date')} (DERIVED)")
         if fd.get("available") else "unavailable (UNAVAILABLE)"],
        ["Score meaning", (ex.get("disclaimer") or "")],
        ["Validation status", VALIDATION_STATUS],
    ]))

    # ---- 2. Why this score ----------------------------------------------
    story.append(Paragraph(S("Why this score?"), _S))
    rows = [["Factor", "Value", "Level", "Contribution", "Kind"]]
    for f in ex.get("factors") or []:
        rows.append([
            f["label"],
            _fmt(f["value"], f" {f['unit']}" if f["unit"] else ""),
            f["level"] or "unavailable",
            str(f["contribution"]) if f["contribution"] is not None else "—",
            _kind_label(f["provenance_kind"]),
        ])
    t = Table(rows, colWidths=[42 * mm, 28 * mm, 28 * mm, 34 * mm, 28 * mm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("TOPPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(t)
    story.append(Paragraph((ex.get("formula") or ""), _SM))

    # ---- 3. Conditions ---------------------------------------------------
    story.append(Paragraph(S("Current conditions"), _S))
    story.append(_kv_table([
        ["Temperature", _fmt(weather.get("temperature_c"), " °C") + " (MODELLED)"],
        ["Wind", _fmt(weather.get("wind_speed_kmh"), " km/h") + " (MODELLED)"],
        ["Humidity", _fmt(weather.get("relative_humidity_pct"), " %") + " (MODELLED)"],
        ["Soil moisture", _fmt(weather.get("soil_moisture_m3m3"), " m³/m³", 3) + " (MODELLED)"],
        ["Fuel moisture (FMC)", _fmt(a.get("fuel_moisture_baseline_pct"), " %") +
         f" — {a.get('fuel_moisture_source') or ''} (DERIVED)"],
        ["Elevation / slope", f"{_fmt(terrain.get('elevation_m'), ' m', 0)} / "
         f"{_fmt(terrain.get('slope_degrees'), '°')} (OBSERVED)"],
        ["Land cover", (f"{landcover.get('dominant_label')} (fuel {a.get('fire_spread', {}).get('fuel_model')}) (OBSERVED)"
                        if "error" not in landcover else "unavailable (UNAVAILABLE)")],
        ["Satellite scene", (f"NDVI {_fmt(satellite.get('ndvi'), '', 2)}, NDMI "
                             f"{_fmt(satellite.get('ndmi'), '', 2)} — "
                             f"{str(satellite.get('observation_date'))[:10]} (OBSERVED)"
                             if "error" not in satellite else
                             f"unavailable — {satellite.get('error')} (UNAVAILABLE)")],
        ["Active fires", (f"{fires.get('count')} detection(s) within {fires.get('radius_km')} km / "
                          f"{fires.get('days')} d (OBSERVED)" if fires.get("available") else
                          f"unavailable — {fires.get('error')} (UNAVAILABLE)")],
    ]))

    # ---- 4. Fire danger --------------------------------------------------
    if not simple and fd.get("available"):
        story.append(Paragraph(S("Fire danger (Canadian FWI System)"), _S))
        story.append(_kv_table([
            ["FWI / class", f"{_fmt(fd.get('fwi'), '', 1)} — {fd.get('class')} (EFFIS: {fd.get('effis_class')})"],
            ["FFMC / DMC / DC", f"{_fmt(fd.get('ffmc'), '', 1)} / {_fmt(fd.get('dmc'), '', 1)} / {_fmt(fd.get('dc'), '', 1)}"],
            ["ISI / BUI", f"{_fmt(fd.get('isi'), '', 1)} / {_fmt(fd.get('bui'), '', 1)}"],
            ["Trend", (analysis.get("fire_danger_trend") or {}).get("trend", "unknown")],
        ]))
        chart = _fwi_chart(fd)
        if chart:
            story.append(Spacer(1, 4))
            story.append(chart)

    # ---- 5. What changed -------------------------------------------------
    if not simple:
        story.append(Paragraph(S("What changed?"), _S))
        if change.get("available"):
            r = change.get("risk") or {}
            rows = [["Driver", "7 days ago", "Today", "Δ"]]
            for d in change.get("drivers_7d") or []:
                rows.append([d["label"], _fmt(d["then"]), _fmt(d["now"]),
                             ("+" if (d["delta"] or 0) > 0 else "") + _fmt(d["delta"])])
            story.append(_kv_table([
                ["Risk (comparison basis)", f"{_fmt(r.get('d7d_ago'))} → {_fmt(r.get('today'))} "
                 f"(Δ {_fmt(r.get('delta_7d'))})"],
            ]))
            t2 = Table(rows, colWidths=[50 * mm, 35 * mm, 35 * mm, 30 * mm])
            t2.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
            ]))
            story.append(t2)
            story.append(Paragraph(f"<b>{change.get('explanation') or ''}</b>", _B))
            story.append(Paragraph(change.get("basis_note") or "", _SM))
        else:
            story.append(Paragraph(change.get("reason") or "unavailable", _B))

    # ---- 6. Exposure & micro-area ---------------------------------------
    if not simple:
        story.append(Paragraph(S("Exposure, vulnerability & micro-area"), _S))
        if exposure.get("status") == "ok":
            va = exposure.get("vulnerable_assets") or {}
            ac = exposure.get("access") or {}
            story.append(_kv_table([
                ["Buildings mapped", f"{(exposure.get('exposure') or {}).get('buildings_mapped')} "
                 f"within {exposure.get('radius_m')} m — exposure {(exposure.get('exposure') or {}).get('level')} (OBSERVED)"],
                ["Critical facilities", f"total {va.get('total')} "
                 f"(hospitals {va.get('hospitals')}, schools {va.get('schools')}, "
                 f"fire stations {va.get('fire_stations')}, power {va.get('power_facilities')}) (OBSERVED)"],
                ["Access", ("limited — " + "; ".join(ac.get("constraints") or []))
                 if ac.get("limited") else "no mapped constraint detected"],
                ["Potential WUI", str((exposure.get("wui_indicator") or {}).get("potential_wui")) +
                 " — " + (exposure.get("wui_indicator") or {}).get("note", "")],
            ]))
        else:
            story.append(Paragraph(f"OSM context unavailable — {exposure.get('reason')} (UNAVAILABLE)", _B))
        mc = micro.get("micro_context") or {}
        story.append(Paragraph(
            f"Resolution honesty: weather/FWI ~11 km (regional) · DEM "
            f"{(micro.get('local_context') or {}).get('resolution') or 'n/a'} (local) · "
            f"Sentinel-2 & WorldCover 10 m (micro). NDMI scene variability: "
            + (f"range {((mc.get('ndmi_variability') or {}).get('range'))} over "
               f"{(mc.get('ndmi_variability') or {}).get('cells')} measured cells"
               if mc.get("ndmi_variability") else "unavailable (no usable scene)")
            + ".", _SM))

    # ---- 7. Population & exposure -----------------------------------------
    if not simple:
        story.append(Paragraph(S("Population & exposure"), _S))
        if population.get("status") == "ok":
            rows = [
                ["Estimated population (radius)",
                 f"{_fmt(population.get('estimated_population'), '', 0)} within "
                 f"{_fmt(population.get('radius_km'), ' km')} of the analysed point (MODELLED)"],
                ["Mean density",
                 _fmt(population.get("mean_density_per_km2"), " people/km²") + " (MODELLED)"],
                ["Density level", population.get("density_level") or "unavailable"],
                ["Reference", f"{population.get('product') or 'unavailable'}, reference year "
                 f"{population.get('reference_year') or 'unavailable'}"],
                ["Hazard class", f"{population.get('hazard_class') or 'unavailable'} (DERIVED)"],
                ["Est. population in hazard area",
                 _fmt(population.get("estimated_population_in_hazard_area"), '', 0)],
                ["Human exposure priority",
                 f"{population.get('human_exposure_priority') or 'unavailable'} — "
                 f"{population.get('human_exposure_note') or ''}"],
                ["Mapped buildings", _fmt(population.get("mapped_buildings"), '', 0) + " (OBSERVED)"],
            ]
            cf = population.get("critical_facilities")
            if cf is not None:
                rows.append(["Critical facilities",
                             f"hospitals {_fmt(cf.get('hospitals'), '', 0)}, schools "
                             f"{_fmt(cf.get('schools'), '', 0)}, fire stations "
                             f"{_fmt(cf.get('fire_stations'), '', 0)}, power "
                             f"{_fmt(cf.get('power_facilities'), '', 0)} (OBSERVED)"])
            story.append(_kv_table(rows))
            # Material graphics from the real population data: population by
            # hazard class and the critical-facilities breakdown — only
            # drawn when there are at least two non-zero values.
            by_class = population.get("population_by_hazard_class") or {}
            class_pairs = [(k, v) for k, v in by_class.items()
                           if isinstance(v, (int, float)) and v > 0]
            pop_chart = _bar_chart(
                "Estimated population by hazard class "
                f"({population.get('product') or 'population grid'}, "
                f"ref {population.get('reference_year') or 'n/a'})",
                class_pairs,
                "Gridded estimates — not exact counts (MODELLED)")
            if pop_chart is not None:
                story.append(pop_chart)
                story.append(Spacer(1, 6))
            cf = population.get("critical_facilities")
            if cf:
                cf_pairs = [(k.replace("_", " "), v) for k, v in cf.items()
                            if isinstance(v, (int, float)) and v > 0]
                cf_chart = _bar_chart(
                    "Mapped critical facilities (OpenStreetMap — counts are a "
                    "lower bound)", cf_pairs, "OBSERVED, completeness varies")
                if cf_chart is not None:
                    story.append(cf_chart)
                    story.append(Spacer(1, 6))
            # Mandatory honesty notes — population is a gridded estimate,
            # never an exact count, and is kept separate from the score.
            story.append(Paragraph(population.get("estimate_note") or "", _SM))
            story.append(Paragraph(population.get("separate_from_score_note") or "", _SM))
        else:
            story.append(Paragraph(
                f"Population estimate unavailable — "
                f"{population.get('reason') or 'not computed for this analysis'} "
                "(UNAVAILABLE)", _B))

    # ---- 8. Ignition susceptibility ---------------------------------------
    if not simple:
        story.append(Paragraph(S("Ignition susceptibility"), _S))
        if ignition.get("status") == "ok":
            rows = [
                ["Indicator", ignition.get("name") or "Relative Ignition-Likelihood Indicator"],
                ["Indicator value (0-100)",
                 f"{_fmt(ignition.get('indicator'), '', 1)} / 100 — "
                 f"{ignition.get('class') or 'unavailable'} (DERIVED, relative)"],
                ["Input coverage",
                 ", ".join(str(c).replace("_", " ")
                           for c in (ignition.get("input_coverage") or [])) or "unavailable"],
            ]
            if ignition.get("coverage_note"):
                rows.append(["Coverage note", ignition["coverage_note"]])
            story.append(_kv_table(rows))
            comp = ignition.get("components") or {}
            if comp:
                story.append(Paragraph(
                    "Components (declared threshold functions, a-priori weights): "
                    + "; ".join(
                        f"{name.replace('_', ' ')} score {_fmt(c.get('score'))}, "
                        f"weight {_fmt(c.get('weight'), '', 2)} — {c.get('basis')}"
                        for name, c in comp.items()), _SM))
            # Mandatory honesty notes (wording fixed by the ignition layer).
            story.append(Paragraph(ignition.get("not_a_probability") or "", _SM))
            for d in (ignition.get("distinctions") or [])[:2]:
                story.append(Paragraph(d, _SM))
            story.append(Paragraph(ignition.get("lightning_note") or "", _SM))
            vs = ignition.get("validation_status") or {}
            story.append(Paragraph(
                f"Validation status: {vs.get('status') or 'unavailable'}", _SM))
            if scientific and vs.get("method_when_run"):
                story.append(Paragraph(
                    f"Validation method (when run): {vs['method_when_run']}", _SM))
        else:
            story.append(Paragraph(
                f"Ignition indicator unavailable — "
                f"{ignition.get('reason') or 'not computed for this analysis'} "
                "(UNAVAILABLE)", _B))

    # ---- 9. Smoke intelligence --------------------------------------------
    if not simple:
        story.append(Paragraph(S("Smoke intelligence"), _S))
        if smoke_s.get("status") == "ok":
            # The SCENARIO / MODELLED label must stand out: no fire is observed.
            story.append(Paragraph(f"<b>{smoke_s.get('mode_label') or ''}</b>", _B))
            win = smoke_s.get("window") or {}
            tr = smoke_s.get("transport") or {}
            story.append(_kv_table([
                ["Forecast window",
                 f"{win.get('from')} → {win.get('to')} "
                 f"({_fmt(win.get('hours'), ' h', 0)}, {win.get('timezone') or 'UTC'})"],
                ["Dominant transport direction",
                 f"{tr.get('dominant_transport_direction') or 'unavailable'} "
                 f"(heading {_fmt(tr.get('dominant_transport_heading_deg'), '°')})"],
                ["Mean transport speed", _fmt(tr.get("mean_transport_speed_kmh"), " km/h")],
                ["Corridor displacement", _fmt(tr.get("displacement_km"), " km")],
                ["Confidence", f"{tr.get('confidence') or 'unavailable'} — "
                 f"{tr.get('confidence_note') or ''}"],
            ]))
            ov = smoke_s.get("overlays") or {}
            ov_pop = ov.get("population") or {}
            ov_fac = ov.get("facilities") or {}
            ov_rows = []
            if ov_pop.get("available"):
                ov_rows.append(["Est. population in corridor",
                                f"{_fmt(ov_pop.get('estimated_population_in_corridor'), '', 0)} — "
                                f"{ov_pop.get('estimate_note') or ''} (MODELLED)"])
            if ov_fac.get("available"):
                counts = ov_fac.get("counts") or {}
                ov_rows.append(["Facilities in corridor",
                                f"hospitals {counts.get('hospitals', 0)}, schools "
                                f"{counts.get('schools', 0)}, fire stations "
                                f"{counts.get('fire_stations', 0)} (mapped OSM, OBSERVED)"])
            if ov_rows:
                story.append(_kv_table(ov_rows))
            story.append(Paragraph(smoke_s.get("disclaimer") or "", _SM))
            story.append(Paragraph(
                (smoke_s.get("safety") or {}).get("distinction_note") or "", _SM))
        else:
            story.append(Paragraph(
                f"Smoke transport estimate unavailable — "
                f"{smoke_s.get('error') or smoke_s.get('reason') or 'not computed for this analysis'} "
                "(UNAVAILABLE)", _B))
        story.append(Paragraph(
            "Observed-fire smoke transport (anchored at real NASA FIRMS "
            "detections) is available via GET /api/smoke when a FIRMS key is "
            "configured.", _SM))

    # ---- 10. Proactive recommendations ------------------------------------
    story.append(Paragraph(
        S("What should you do? (RECOMMENDED)") if simple else
        S("Proactive recommendations (RECOMMENDED)"), _S))
    if recs:
        rows = [["Priority", "Action", "Why (real evidence)"]]
        for r in (recs[:3] if simple else recs):
            rows.append([r["priority"].upper(), Paragraph(r["what"], _B),
                         Paragraph(r["why"], _SM)])
        t3 = Table(rows, colWidths=[22 * mm, 66 * mm, 72 * mm])
        t3.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(t3)
    else:
        story.append(Paragraph(
            "No condition-triggered recommendations — no significant risk "
            "driver currently detected.", _B))
    story.append(Paragraph((plan.get("no_guarantee_note") or ""), _SM))

    # ---- 11. Environmental solutions --------------------------------------
    if not simple:
        story.append(Paragraph(S("Environmental solutions (ecological restoration)"), _S))
    if not simple and ecology.get("status") == "ok":
        site = ecology.get("site_conditions") or {}
        story.append(Paragraph(
            f"Site: climate zone {site.get('climate_zone') or 'undetermined'}, "
            f"moisture regime {site.get('moisture_regime') or 'undetermined'}, "
            f"elevation {_fmt(site.get('elevation_m'), ' m', 0)}, "
            f"land cover {site.get('land_cover') or 'n/a'}.", _B))
        for bucket, title in [("recommended", "Suitable species (site-fitted)"),
                              ("recommended_with_caution", "Suitable with caution"),
                              ("not_recommended", "NOT recommended here")]:
            entries = ecology.get(bucket) or []
            if not entries:
                continue
            rows = [["Species", "Drought tol.", "Fire considerations", "Confidence"]]
            for e in entries:
                rows.append([
                    Paragraph(f"<b>{e['common_name']}</b><br/><i>{e['scientific_name']}</i>", _SM),
                    e.get("drought_tolerance") or "—",
                    Paragraph(e.get("fire_considerations") or "", _SM),
                    Paragraph(e.get("confidence") or "", _SM),
                ])
            story.append(Paragraph(title, _B))
            t4 = Table(rows, colWidths=[34 * mm, 22 * mm, 74 * mm, 30 * mm])
            t4.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            story.append(t4)
        story.append(Paragraph((ecology.get("fire_note") or "") + " " +
                               (ecology.get("verification_note") or ""), _SM))
    elif not simple:
        story.append(Paragraph(ecology.get("message") or "unavailable", _B))

    # ---- 11b. Solutions & potential funding (decision/scientific) --------
    if not simple and solutions and solutions.get("status") == "ok":
        story.append(Paragraph(S("Solutions & potential funding"), _S))
        recs_by_hazard = solutions.get("recommendations_by_hazard") or {}
        fitted = [s for sols in recs_by_hazard.values() for s in sols]
        fitted.sort(key=lambda s: (-s.get("fit_score", 0), s.get("solution_id", "")))
        if fitted:
            rows = [["Solution", "Fit", "Why it fits (real site values)",
                     "Limitations"]]
            for s in fitted[:5]:
                rows.append([
                    Paragraph(f"<b>{s.get('name')}</b>", _SM),
                    s.get("fit_band", "—").replace("_", " "),
                    Paragraph(s.get("why_it_fits") or "", _SM),
                    Paragraph("; ".join(s.get("limitations") or []), _SM),
                ])
            t_sol = Table(rows, colWidths=[34 * mm, 20 * mm, 66 * mm, 40 * mm])
            t_sol.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            story.append(t_sol)
            story.append(Paragraph(
                solutions.get("guarantee_disclaimer") or "", _SM))
        if funding and funding.get("matches"):
            story.append(Paragraph("Potential funding sources", _B))
            rows = [["Programme", "Type", "Why it matches", "Not verified"]]
            for m in funding["matches"][:4]:
                rows.append([
                    Paragraph(f"<b>{m.get('name')}</b>", _SM),
                    Paragraph(", ".join(m.get("funding_type") or []), _SM),
                    Paragraph(m.get("why_it_matches") or "", _SM),
                    Paragraph("; ".join(m.get("not_verified") or []) or "—", _SM),
                ])
            t_fund = Table(rows, colWidths=[32 * mm, 26 * mm, 62 * mm, 40 * mm])
            t_fund.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            story.append(t_fund)
            story.append(Paragraph(funding.get("disclaimer") or "", _SM))

    # ---- 12. Scenarios -----------------------------------------------------
    if not simple:
        story.append(Paragraph(S("Intervention scenarios"), _S))
        rows = [["Scenario", "Baseline risk", "Scenario risk", "Δ", "Status"]]
        for s in scenarios:
            if s.get("status") == "modelled":
                rows.append([s["name"], _fmt((s.get("baseline") or {}).get("risk")),
                             _fmt((s.get("result") or {}).get("risk")),
                             _fmt((s.get("result") or {}).get("risk_delta")),
                             "MODELLED"])
            else:
                rows.append([s["name"], "—", "—", "—", "NOT QUANTIFIED"])
        t5 = Table(rows, colWidths=[58 * mm, 26 * mm, 26 * mm, 20 * mm, 30 * mm])
        t5.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
        ]))
        story.append(t5)
        story.append(Paragraph(
            "MODELLED INTERVENTION SCENARIO — not an observed result. Effects "
            "beyond the models are reported as NOT QUANTIFIED; no improvement "
            "percentage is invented.", _SM))

    # ---- 13. Action plan --------------------------------------------------
    if not simple:
        story.append(Paragraph(S("Automation / action plan"), _S))
        story.append(_kv_table([
            ["Response level", plan.get("level") or "—"],
            ["Automation armed", str(bool(plan.get("automation_enabled")))],
            ["Audit id", plan.get("audit_id") or "not recorded"],
            ["Actions", "; ".join(f"{a['id']} ({a['type']}/{a['status']})"
                                  for a in (plan.get("actions") or [])) or "none"],
        ]))

    # ---- 14. Historical lessons (optional) --------------------------------
    if not simple and history and "error" not in history:
        story.append(Paragraph(S("Lessons from the past"), _S))
        w = history.get("window") or {}
        story.append(Paragraph(
            f"Window {w.get('start')} → {w.get('end')} ({w.get('days')} days): "
            f"{len(history.get('high_risk_periods') or [])} high-risk period(s). "
            f"Fire observations: "
            f"{'available' if (history.get('fire_observations') or {}).get('available') else 'unavailable — ' + str((history.get('fire_observations') or {}).get('reason'))}.",
            _B))
        for l in (history.get("lessons") or [])[:5]:
            p = l.get("period") or {}
            story.append(Paragraph(
                f"{p.get('start')} → {p.get('end')}: modelled risk "
                f"{(l.get('hydrashield_score') or {}).get('value')}/100 "
                f"({(l.get('hydrashield_score') or {}).get('label')}) · observed fire: "
                f"{(l.get('observed_fire') or {}).get('status')} "
                f"({(l.get('observed_fire') or {}).get('label')})", _SM))

    # ---- Documented disaster losses (documented figures only) -------------
    story.append(Paragraph(S("Documented disaster losses"), _S))
    if losses and losses.get("status") == "ok" and losses.get("figures"):
        story.append(Paragraph(
            "Published loss figures from integrated sources and the curated "
            "Talaix loss registry whose geographic scope covers this location's "
            "country/region. These are documented national or multi-country "
            "aggregates — not a loss estimate for this asset. Estimated and "
            "modelled loss figures are deliberately not included (strict "
            "observed/estimated separation, docs/ECONOMIC_INTELLIGENCE.md).", _B))
        header = documented_losses_rows(losses)[0]
        body = [[Paragraph(cell, _SM) for cell in r]
                for r in documented_losses_rows(losses)[1:]]
        t = Table([header] + body, colWidths=[52 * mm, 38 * mm, 42 * mm, 38 * mm])
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("TOPPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(t)
        story.append(Paragraph(
            "Every figure carries its source, reference period, geographic "
            "scope, licence note and method in the Talaix loss registry "
            "(GET /api/v2/losses).", _SM))
    else:
        reason = (losses or {}).get("reason") or "the loss registry was not queried"
        story.append(Paragraph(
            "No documented loss figures from integrated sources cover this "
            f"location — declared, not estimated. ({reason}) Estimated and "
            "modelled loss figures are deliberately not included (strict "
            "observed/estimated separation).", _B))

    # ---- Loss screening estimate (ESTIMATED — strictly separated) ---------
    if loss_estimate and loss_estimate.get("status") == "ok":
        est = loss_estimate.get("estimate") or {}
        ev = est.get("exposed_value_eur") or {}
        inputs = loss_estimate.get("inputs") or {}
        b = inputs.get("buildings_count") or {}
        cb = inputs.get("country_benchmark") or {}
        ab = inputs.get("area_basis") or {}
        pc = inputs.get("price_calibration") or {}
        story.append(Paragraph(
            "<b>Talaix loss screening estimate (ESTIMATED — computed by the "
            "Talaix function, not a documented figure)</b>", _B))
        area_word = ("real cadastral floor-area"
                     if ab.get("status") == "real_cadastral"
                     else "declared floor-area")
        est_rows = [
            ["Exposed value (screening)",
             f"EUR {ev.get('low', 0):,} – {ev.get('high', 0):,} "
             f"(central {ev.get('central', 0):,}) (ESTIMATED)"],
            ["Basis",
             f"{int(b.get('value') or 0):,} mapped buildings"
             + (f" within {int(b.get('radius_m'))} m" if b.get("radius_m") else "")
             + f" × {area_word} and replacement-cost benchmarks "
               f"({cb.get('name') or 'fallback defaults'}) — method and "
               "benchmark bases printed in config/loss_estimate_benchmarks.json"],
        ]
        if pc.get("status") == "ok":
            est_rows.append(["Price calibration",
                             f"Eurostat STS_COPI_A {pc.get('basis_value')} "
                             f"({pc.get('basis_year')}) → {pc.get('latest_value')} "
                             f"({pc.get('latest_year')}) ×{pc.get('factor')} — official "
                             "construction-cost index; all bands scaled equally"])
        if ab.get("status") == "real_cadastral":
            est_rows.append(["Floor area basis",
                             f"Real cadastral mean {ab.get('mean_area_m2')} m² "
                             f"over {ab.get('building_count')} buildings — "
                             f"{ab.get('source')}"])
        el = loss_estimate.get("expected_loss") or {}
        if el.get("status") == "ok" and el.get("expected_loss_eur"):
            elv = el["expected_loss_eur"]
            est_rows.append(["Expected loss (screening)",
                             f"EUR {elv.get('low', 0):,} – {elv.get('high', 0):,} "
                             f"(central {elv.get('central', 0):,}) at depth "
                             f"{el.get('depth_m')} m — damage ratio "
                             f"{el.get('damage_ratio')} (ESTIMATED)"])
        else:
            est_rows.append(["Expected loss",
                             "not available — no validated damage-ratio model is "
                             "integrated; the exposed value is not converted into "
                             "an expected loss (declared)"])
        story.append(_kv_table(est_rows))
        story.append(Paragraph(
            "This is an exposed-VALUE screening range — what could be at "
            "stake — computed from real mapped building counts and declared "
            "benchmark ranges; it is not a valuation, not an expected loss "
            "and never mixed with the documented figures above.", _SM))
    elif loss_estimate and loss_estimate.get("reason"):
        story.append(Paragraph(
            "<b>Talaix loss screening estimate (ESTIMATED)</b> — unavailable: "
            f"{loss_estimate.get('reason')}", _SM))

    # ---- Map (real grid data; decision/scientific) -------------------------
    if not simple:
        story.append(Paragraph(S("Map (real fire-danger grid)"), _S))
        map_drawing = _map_drawing(analysis, grid)
        if map_drawing is not None:
            story.append(map_drawing)
            story.append(Paragraph(
                "Grid computed from real Open-Meteo daily data over the "
                "displayed bounding box; cells are coarse (~km) and do not "
                "resolve streets. Detections (when shown) are NASA FIRMS "
                "hotspots, not fire perimeters.", _SM))
        else:
            story.append(Paragraph(
                "Map unavailable — the real fire-danger grid could not be "
                "computed for this area at report time.", _B))

    # ---- 15. Sources & provenance -----------------------------------------
    if simple:
        story.append(Paragraph(S("Data freshness & main sources"), _S))
        main = []
        for k in ("satellite", "weather", "fire_danger", "terrain", "landcover"):
            p = provenance.get(k) or {}
            main.append([k.replace("_", " "), _kind_label(p.get("kind")),
                         Paragraph(str(p.get("source") or "—"), _SM),
                         str(p.get("acquired") or "—")])
        t6s = Table([["Component", "Kind", "Source", "Acquired"]] + main,
                    colWidths=[30 * mm, 26 * mm, 76 * mm, 28 * mm])
        t6s.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(t6s)
    else:
        story.append(Paragraph(S("Data sources & provenance"), _S))
        rows = [["Component", "Kind", "Source", "Acquired", "Limitations"]]
        for k, p in provenance.items():
            rows.append([k.replace("_", " "), _kind_label(p.get("kind")),
                         Paragraph(str(p.get("source") or "—"), _SM),
                         str(p.get("acquired") or "—"),
                         Paragraph(str(p.get("limitations") or "—"), _SM)])
        t6 = Table(rows, colWidths=[26 * mm, 24 * mm, 48 * mm, 24 * mm, 38 * mm], repeatRows=1)
        t6.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(t6)

    # ---- Scientific appendix (scientific report only) --------------------
    if scientific:
        story.append(Paragraph(S("Methodology appendix"), _S))
        meth = analysis.get("methodology") or {}
        story.append(_kv_table([
            ["Risk model", "FWI-anchored composite screening score, v" + MODEL_VERSION +
             " — 100·FWI/(FWI+25) + slope term (max +8) + fuel-moisture adjustment "
             "(+6/+3/−4), ×0.3 for non-burnable dominant cover (DERIVED)"],
            ["FWI methodology", "Canadian FWI System (Van Wagner 1987): FFMC/DMC/DC/"
             "ISI/BUI/FWI from daily T_max, RH_min, mean wind, precipitation sum "
             "(screening approximation of noon-standard inputs), 21-day spin-up (DERIVED)"],
            ["Sentinel-2 methodology", "L2A scene selection via Earth Search STAC "
             "(lowest cloud cover within 30 days); windowed COG reads of B03/B04/"
             "B08/B11 + SCL cloud mask; NDVI=(B08−B04)/(B08+B04), "
             "NDMI=(B08−B11)/(B08+B11) at 10 m (OBSERVED)"],
            ["Fuel moisture", "Sentinel-2 NDMI → FMC calibration blended 60/40 with "
             "capillary transfer from modelled surface soil moisture; RH-equilibrium "
             "fallback (DERIVED)"],
            ["Terrain methodology", "3×3 DEM window (EU-DEM 25 m / SRTM 90 m via "
             "OpenTopoData); slope/aspect from central differences (OBSERVED)"],
            ["Land cover", "ESA WorldCover 10 m dominant class in a local window → "
             "fuel-model mapping (screening approximation) (OBSERVED)"],
            ["Exposure methodology", "Mapped OSM feature counts within a declared "
             "radius via the ohsome aggregation API (Overpass fallback); "
             "completeness varies by region (OBSERVED, declared limitation)"],
            ["Intervention scenario", f"Hydration +{meth.get('intervention_fmc_increase_pct')}% FMC "
             f"({meth.get('intervention_water_m3')} m³) through the FireSpreadModel "
             "and the composite score (MODELLED)"],
            ["Model version", MODEL_VERSION],
            ["Validation status", VALIDATION_STATUS],
        ]))
        meth_rows = []
        if ignition.get("status") == "ok":
            meth_rows.append(["Ignition model",
                              f"{ignition.get('name') or 'Relative Ignition-Likelihood Indicator'}, "
                              f"model version {ignition.get('model_version') or 'unavailable'} — "
                              "declared piecewise threshold functions over real component "
                              "inputs, a-priori weights renormalised over available "
                              "components (DERIVED, relative)"])
            weights = ignition.get("weights") or {}
            if weights:
                meth_rows.append(["Ignition weights (a priori)",
                                  ", ".join(f"{k.replace('_', ' ')} {v}"
                                            for k, v in weights.items())])
            meth_rows.append(["Ignition validation",
                              (ignition.get("validation_status") or {}).get("status")
                              or "unavailable"])
        if population.get("status") == "ok":
            meth_rows.append(["Population dataset",
                              f"{population.get('product') or 'unavailable'}, reference year "
                              f"{population.get('reference_year') or 'unavailable'}, resolution "
                              f"{population.get('resolution') or 'unavailable'}, license "
                              f"{population.get('license') or 'not declared in analysis block'} "
                              "(MODELLED)"])
        if smoke_s.get("status") == "ok":
            cm = (smoke_s.get("transport") or {}).get("corridor_model") or {}
            meth_rows.append(["Smoke corridor model",
                              f"{cm.get('type') or 'unavailable'} — initial half-width "
                              f"{_fmt(cm.get('initial_half_width_km'), ' km', 2)}, growth "
                              f"{_fmt(cm.get('growth_km_per_hour'), ' km/h per transport hour', 2)}"])
            meth_rows.append(["Smoke safety guidance",
                              (smoke_s.get("safety") or {}).get("kind") or "unavailable"])
        if meth_rows:
            story.append(Paragraph(
                "Population, ignition & smoke model provenance", _B))
            story.append(_kv_table(meth_rows))
        story.append(Paragraph("Assumptions & declared approximations", _B))
        story.append(Paragraph(
            "Daily aggregates approximate noon-standard FWI inputs; the FMC "
            "calibration is a placeholder pending field fitting; the spread "
            "ellipse is a screening estimate without spotting, fuel breaks or "
            "suppression; the change comparison excludes the fuel-moisture "
            "adjustment (no historical FMC).", _SM))
        story.append(Paragraph("References", _B))
        story.append(Paragraph(
            "Van Wagner, C.E. (1987) Development and Structure of the Canadian "
            "Forest Fire Weather Index System · EFFIS danger classes (JRC) · "
            "Copernicus Sentinel-2 L2A · ESA WorldCover v200 · Open-Meteo / "
            "ERA5 (C3S) · OpenTopoData (EU-DEM/SRTM) · OpenStreetMap "
            "contributors (ohsome API, Heidelberg Institute) · NASA FIRMS "
            "(when configured).", _SM))

    # ---- 16/17. Limitations ------------------------------------------------
    story.append(Paragraph(S("Scientific limitations"), _S))
    story.append(Paragraph((analysis.get("methodology") or {}).get("note") or "", _SM))
    story.append(Paragraph(VALIDATION_STATUS, _SM))
    story.append(Paragraph(
        "Screening-level decision support: not a fire-danger rating, not a "
        "probability of fire, not a substitute for official civil-protection "
        "information.", _SM))

    # TX authenticity seal.  Compute after the story is built so that the
    # report ID shown in the body and footer is stable (matches the id
    # computed from the unmodified analysis dict).  Then stamp the analysis
    # payload so callers receive the authenticity block.
    rid = report_content_id(analysis, report_type)
    if not analysis.get("authenticity"):
        analysis["authenticity"] = issue_seal(
            "report",
            rid,
            {
                "analysis": {k: v for k, v in (analysis or {}).items() if k != "generated_at"},
                "report_type": report_type,
            },
        )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=18 * mm,
        title=f"Talaix {type_info['title']} — {loc.get('name', '')}",
        author="Talaix (real-data decision support)",
        subject=f"Wildfire risk report ({report_type}) — real Earth Observation data",
    )
    doc._report_meta = {
        "generated": analysis.get("generated_at", ""),
        "report_id": rid,
        "auth_code": analysis.get("authenticity", {}).get("code", ""),
    }
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
