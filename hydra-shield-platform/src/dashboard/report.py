"""
Professional PDF reporting for HydraShield analyses.

Generates a real report from the same cached real analysis (and optional
history) that backs the API — every number in the PDF comes from those
payloads, with the same provenance, freshness and limitations. No fake
charts: the only chart is drawn from the real FWI series.

Sections follow the public-trust requirements: executive summary, why this
score, conditions, fire danger, what changed, exposure, micro-area,
proactive recommendations, environmental solutions, modelled scenarios,
action plan, historical lessons (optional), validation status, sources &
provenance, scientific limitations. OBSERVED / DERIVED / MODELLED /
FORECAST / RECOMMENDED / UNKNOWN / UNAVAILABLE labels are kept visible.
"""

from __future__ import annotations

import io
from typing import Dict, List, Optional

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
VALIDATION_STATUS = (
    "NOT VALIDATED — the HydraShield screening score has not yet completed "
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

_S = ParagraphStyle("section", fontName="Helvetica-Bold", fontSize=13,
                    textColor=_DARK, spaceBefore=14, spaceAfter=6)
_B = ParagraphStyle("body", fontName="Helvetica", fontSize=9.5, leading=13)
_SM = ParagraphStyle("small", fontName="Helvetica", fontSize=8, leading=11,
                     textColor=_MUTED)
_TITLE = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=20,
                        textColor=_DARK)


def _kind_label(kind: Optional[str]) -> str:
    return (kind or "unavailable").upper()


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


def build_report_pdf(analysis: Dict, history: Optional[Dict] = None,
                     report_type: str = "decision") -> bytes:
    """
    Render a professional PDF report from a real analysis payload.

    ``report_type`` selects the audience-specific composition — all types
    are rendered from the SAME analysis object (never a separate
    calculation): "simple" (citizens), "decision" (operational users),
    "scientific" (full methodology appendix).
    """
    if not _HAS_REPORTLAB:
        raise RuntimeError("reportlab is not installed on this server")
    if report_type not in REPORT_TYPES:
        raise ValueError(f"Unknown report type: {report_type!r}")
    type_info = REPORT_TYPES[report_type]
    simple = report_type == "simple"
    scientific = report_type == "scientific"

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
    ecology = analysis.get("ecology") or {}
    scenarios = analysis.get("scenarios") or []
    recs = analysis.get("recommendations") or []
    plan = analysis.get("action_plan") or {}
    provenance = analysis.get("provenance") or {}

    story: List = []

    # ---- Header ---------------------------------------------------------
    story.append(Paragraph("HydraShield Wildfire Risk Report", _TITLE))
    story.append(Paragraph(
        f"{type_info['title']} — {type_info['audience']}", _SM))
    story.append(Paragraph(
        f"{loc.get('name', '')} — {loc.get('latitude')}, {loc.get('longitude')}",
        _B))
    story.append(Paragraph(
        f"Generated: {analysis.get('generated_at')} · Model version {MODEL_VERSION} · "
        f"Report type: {report_type} · "
        "Real-data report: every value is observed, derived or modelled with "
        "provenance; unavailable data is stated.", _SM))
    story.append(Spacer(1, 8))

    # ---- 1. Executive summary -------------------------------------------
    story.append(Paragraph("1. Executive summary", _S))
    story.append(_kv_table([
        ["Composite risk score", f"{_fmt(risk.get('baseline'), '', 0)} / 100 — "
         f"{risk.get('class') or 'unavailable'} (DERIVED)"],
        ["Fire danger (FWI)", (_fmt(fd.get("fwi"), '', 1) + f" — {fd.get('class')} on {fd.get('date')} (DERIVED)")
         if fd.get("available") else "unavailable (UNAVAILABLE)"],
        ["Score meaning", (ex.get("disclaimer") or "")],
        ["Validation status", VALIDATION_STATUS],
    ]))

    # ---- 2. Why this score ----------------------------------------------
    story.append(Paragraph("2. Why this score?", _S))
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
    story.append(Paragraph("3. Current conditions", _S))
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
        story.append(Paragraph("4. Fire danger (Canadian FWI System)", _S))
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
        story.append(Paragraph("5. What changed?", _S))
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
        story.append(Paragraph("6. Exposure, vulnerability & micro-area", _S))
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

    # ---- 7. Proactive recommendations ------------------------------------
    story.append(Paragraph(
        "7. What should you do? (RECOMMENDED)" if simple else
        "7. Proactive recommendations (RECOMMENDED)", _S))
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

    # ---- 8. Environmental solutions --------------------------------------
    if not simple:
        story.append(Paragraph("8. Environmental solutions (ecological restoration)", _S))
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

    # ---- 9. Scenarios -----------------------------------------------------
    if not simple:
        story.append(Paragraph("9. Intervention scenarios", _S))
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

    # ---- 10. Action plan --------------------------------------------------
    if not simple:
        story.append(Paragraph("10. Automation / action plan", _S))
        story.append(_kv_table([
            ["Response level", plan.get("level") or "—"],
            ["Automation armed", str(bool(plan.get("automation_enabled")))],
            ["Audit id", plan.get("audit_id") or "not recorded"],
            ["Actions", "; ".join(f"{a['id']} ({a['type']}/{a['status']})"
                                  for a in (plan.get("actions") or [])) or "none"],
        ]))

    # ---- 11. Historical lessons (optional) --------------------------------
    if not simple and history and "error" not in history:
        story.append(Paragraph("11. Lessons from the past", _S))
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

    # ---- 12. Sources & provenance -----------------------------------------
    if simple:
        story.append(Paragraph("8. Data freshness & main sources", _S))
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
        story.append(Paragraph("12. Data sources & provenance", _S))
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
        story.append(Paragraph("13. Methodology appendix", _S))
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

    # ---- 13/14. Limitations ------------------------------------------------
    story.append(Paragraph(
        ("14. " if scientific else ("9. " if simple else "13. ")) +
        "Scientific limitations", _S))
    story.append(Paragraph((analysis.get("methodology") or {}).get("note") or "", _SM))
    story.append(Paragraph(VALIDATION_STATUS, _SM))
    story.append(Paragraph(
        "Screening-level decision support: not a fire-danger rating, not a "
        "probability of fire, not a substitute for official civil-protection "
        "information.", _SM))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"HydraShield Wildfire Risk Report — {loc.get('name', '')}",
        author="HydraShield (real-data decision support)",
    )
    doc.build(story)
    return buf.getvalue()
