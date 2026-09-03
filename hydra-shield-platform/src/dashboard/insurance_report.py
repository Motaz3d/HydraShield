"""
PDF builder for Insurance Environmental Risk Profiles.

Reuses shared report components from ``src.dashboard.verification_report``.
"""

from __future__ import annotations

import io
from typing import Any, Dict, List

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .verification_report import (
    _HAS_REPORTLAB,
    _B,
    _S,
    _SM,
    _SUBTITLE,
    _TITLE,
    _evidence_table,
    _kv_table,
    _xml,
)

REPORT_ENGINE_VERSION = "1.1.0"


def _footer(canvas, doc):
    """Insurance profile footer with metadata and page numbers."""
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#cbd5e1"))
    canvas.setLineWidth(0.5)
    canvas.line(18 * mm, 12 * mm, 192 * mm, 12 * mm)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#64748b"))
    meta = getattr(doc, "_report_meta", {})
    canvas.drawString(
        18 * mm, 8 * mm,
        f"Talaix — Insurance Environmental Risk Profile · engine v{REPORT_ENGINE_VERSION} · "
        f"{meta.get('generated', '')} · report {meta.get('report_id', '')}",
    )
    canvas.drawRightString(192 * mm, 8 * mm, f"Page {doc.page}")
    canvas.restoreState()


def _peril_overview_table(perils: List[Dict[str, Any]]) -> Table:
    rows = [["Peril", "Current level", "Claim status", "Confidence", "Events status", "Events count"]]
    for p in perils:
        rows.append([
            _xml(p.get("peril")),
            _xml(p.get("current_level")),
            _xml(p.get("claim_status")),
            _xml(p.get("confidence")),
            _xml(p.get("events_status")),
            _xml(p.get("events_count")),
        ])
    t = Table(rows, colWidths=(45 * mm, 25 * mm, 25 * mm, 22 * mm, 25 * mm, 22 * mm))
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _events_summary_list(events: List[Dict[str, Any]]) -> str:
    if not events:
        return "No events in summary."
    parts = []
    for ev in events:
        pairs = [f"{k}={v}" for k, v in ev.items()]
        parts.append("; ".join(pairs))
    return "<br/>".join(f"• {_xml(part)}" for part in parts)


def _pct(x: Any, digits: int = 1) -> str:
    if x is None:
        return "—"
    try:
        return f"{float(x) * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return "—"


def _primary_severity_metric(sev: Dict[str, Any]) -> Any:
    metrics = (sev or {}).get("metrics") or {}
    if not metrics:
        return None
    key = max(metrics, key=lambda k: (metrics[k].get("n", 0), metrics[k].get("mean", 0)))
    return key, metrics[key]


def _actuarial_account_table(perils: List[Dict[str, Any]]) -> Table:
    rows = [[
        "Peril", "λ̂ /yr (90% CI)", "Tier", "AEP", "Return period",
        "10-yr horizon", "Trend", "Severity mean", "E[S] /yr",
    ]]
    for p in perils:
        act = p.get("actuarial") or {}
        if act.get("status") != "ok":
            rows.append([
                _xml(p.get("peril")),
                f"{_xml(act.get('status', 'unavailable'))} — see details",
                "—", "—", "—", "—", "—", "—", "—",
            ])
            continue
        f = act.get("frequency") or {}
        trend = act.get("trend") or {}
        trend_cell = (
            f"{trend.get('direction')} ×{trend.get('annual_multiplier')}"
            if trend.get("status") == "ok" else "n/a"
        )
        primary = _primary_severity_metric(act.get("severity") or {})
        sev_cell = f"{primary[1].get('mean')} ({primary[0]})" if primary else "—"
        cr = act.get("collective_risk") or {}
        rp = act.get("return_period_years")
        rows.append([
            _xml(p.get("peril")),
            f"{_xml(f.get('lambda_per_year'))} ({_xml(f.get('ci_lower'))}–{_xml(f.get('ci_upper'))})",
            _xml(f.get("tier")),
            _pct(act.get("annual_exceedance_probability")),
            f"{_xml(rp)} yrs" if rp is not None else "—",
            _pct((act.get("horizon_probabilities") or {}).get("10y"), 0),
            _xml(trend_cell),
            _xml(sev_cell),
            _xml(cr.get("expected_annual_index", "—")),
        ])
    t = Table(rows, colWidths=(26 * mm, 26 * mm, 15 * mm, 14 * mm, 17 * mm, 16 * mm, 22 * mm, 20 * mm, 14 * mm),
              repeatRows=1)
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def build_insurance_pdf(profile: Dict[str, Any]) -> bytes:
    """Build the Insurance Environmental Risk Profile PDF as bytes."""
    if not _HAS_REPORTLAB:
        raise RuntimeError("reportlab is not installed; PDF generation is unavailable")

    asset = profile.get("asset") or {}
    perils = profile.get("perils") or []
    frameworks = profile.get("frameworks") or []
    gaps = profile.get("declared_gaps") or []

    story: List[Any] = []

    # ---- Title --------------------------------------------------------------
    story.append(Paragraph("Insurance Environmental Risk Profile", _TITLE))
    story.append(Paragraph("Per-peril levels + long-term event history", _SUBTITLE))
    story.append(Spacer(1, 4 * mm))

    # ---- Metadata ------------------------------------------------------------
    story.append(Paragraph("Report metadata", _S))
    meta_rows = [
        ["Profile ID", _xml(profile.get("profile_id"))],
        ["Generated", _xml(profile.get("generated_at"))],
        ["Asset name", _xml(asset.get("name"))],
        ["Coordinates", f"{_xml(asset.get('lat'))}, {_xml(asset.get('lon'))}"],
        ["Search radius", f"{_xml(profile.get('radius_km'))} km"],
        ["Engine version", _xml(profile.get("engine_version"))],
    ]
    story.append(_kv_table(meta_rows))

    # ---- Frameworks ----------------------------------------------------------
    story.append(Paragraph("Frameworks", _S))
    for fw in frameworks:
        story.append(Paragraph(
            f"<b>{_xml(fw.get('name'))}</b> — {_xml(fw.get('aspect'))}. "
            f"{_xml(fw.get('note'))}",
            _B,
        ))

    # ---- Per-peril overview --------------------------------------------------
    story.append(Paragraph("Per-peril overview", _S))
    story.append(_peril_overview_table(perils))

    # ---- Actuarial screening ---------------------------------------------------
    account = profile.get("actuarial_summary") or {}
    if account:
        story.append(Paragraph("Actuarial screening (non-monetary)", _S))
        if account.get("text"):
            story.append(Paragraph(_xml(account["text"]), _B))
        ins = account.get("insurability") or {}
        if ins.get("status") == "ok":
            story.append(Paragraph(
                f"<b>Insurability screen:</b> {_xml(ins.get('attention_band'))} — "
                f"attention score {_xml(ins.get('attention_score'))}/100, "
                f"confidence {_xml(ins.get('confidence'))}, "
                f"data adequacy {_pct(ins.get('data_adequacy'), 0)}. "
                f"{_xml(ins.get('band_meaning'))}",
                _B,
            ))
            story.append(Paragraph(f"<i>{_xml(ins.get('note'))}</i>", _SM))
        trends = account.get("significant_trends") or {}
        if trends:
            story.append(Paragraph(
                "<b>Significant frequency trends (p&lt;0.05):</b> "
                + "; ".join(
                    f"{_xml(h)} {_xml(t.get('direction'))} "
                    f"(×{_xml(t.get('annual_multiplier'))}/yr)"
                    for h, t in trends.items()
                ) + ".",
                _B,
            ))
        story.append(_actuarial_account_table(perils))
        caveats = list(account.get("assumptions") or [])
        if account.get("independence_caveat"):
            caveats.append(account["independence_caveat"])
        for c in caveats:
            story.append(Paragraph(f"<i>{_xml(c)}</i>", _SM))

    # ---- Per-peril details ---------------------------------------------------
    story.append(Paragraph("Per-peril details", _S))
    for p in perils:
        story.append(Paragraph(f"<b>{_xml(p.get('peril'))}</b> "
                               f"({_xml(p.get('claim_status'))})", _B))
        if p.get("summary"):
            story.append(Paragraph(_xml(p["summary"]), _B))
        if p.get("level_basis"):
            story.append(Paragraph(f"<b>Level basis:</b> {_xml(p['level_basis'])}", _SM))

        ev_table = _evidence_table(p.get("evidence") or [])
        if ev_table:
            story.append(ev_table)

        story.append(Paragraph("<b>Long-term event summary:</b>", _SM))
        if p.get("events_status") == "ok":
            story.append(Paragraph(_events_summary_list(p.get("events_summary") or []), _B))
        else:
            story.append(Paragraph(
                f"Events unavailable: {_xml(p.get('events_reason'))}", _B
            ))

        if p.get("temporal_coverage"):
            story.append(Paragraph(
                f"<b>Dataset temporal coverage:</b> {_xml(p['temporal_coverage'])}",
                _SM,
            ))
        act = p.get("actuarial") or {}
        if act.get("status") == "ok":
            f = act.get("frequency") or {}
            rp = act.get("return_period_years")
            story.append(Paragraph(
                f"<b>Actuarial:</b> λ̂ {_xml(f.get('lambda_per_year'))}/yr "
                f"(90% CI {_xml(f.get('ci_lower'))}–{_xml(f.get('ci_upper'))}, "
                f"{_xml(f.get('tier'))}); AEP {_pct(act.get('annual_exceedance_probability'))}"
                + (f"; return period {_xml(rp)} yrs" if rp is not None else "")
                + ".",
                _SM,
            ))
            trend = act.get("trend") or {}
            if trend.get("status") == "ok":
                story.append(Paragraph(
                    f"<b>Frequency trend:</b> {_xml(trend.get('direction'))}, "
                    f"×{_xml(trend.get('annual_multiplier'))}/yr "
                    f"(p={_xml(trend.get('p_value'))}); λ at latest record year "
                    f"{_xml(trend.get('lambda_current_year'))} vs record average "
                    f"{_xml(trend.get('lambda_average'))}.",
                    _SM,
                ))
            fit = act.get("severity_fit") or {}
            if fit.get("status") == "ok":
                story.append(Paragraph(
                    f"<b>Severity fit ({_xml(fit.get('severity_metric'))}):</b> "
                    + "; ".join(
                        f"{_xml(fl.get('distribution'))} (AIC {_xml(fl.get('aic'))}, "
                        f"KS {_xml(fl.get('ks_statistic'))})"
                        for fl in (fit.get("fits") or [])
                    ) + f" — preferred: {_xml(fit.get('preferred'))}. "
                    f"<i>{_xml(fit.get('note'))}</i>",
                    _SM,
                ))
            for note in (act.get("notes") or []):
                story.append(Paragraph(f"<i>{_xml(note)}</i>", _SM))
        elif act.get("unavailable_reason"):
            story.append(Paragraph(
                f"<b>Actuarial:</b> unavailable — {_xml(act['unavailable_reason'])}",
                _SM,
            ))
        if p.get("limitations"):
            for lim in p["limitations"]:
                story.append(Paragraph(f"<b>Limitation:</b> {_xml(lim)}", _SM))
        story.append(Spacer(1, 2 * mm))

    # ---- Declared gaps -------------------------------------------------------
    story.append(Paragraph("Declared data gaps", _S))
    if gaps:
        for gap in gaps:
            story.append(Paragraph(
                f"• <b>{_xml(gap.get('peril'))}</b> "
                f"({_xml(gap.get('type'))}): {_xml(gap.get('reason'))}",
                _B,
            ))
    else:
        story.append(Paragraph("No declared data gaps for this asset.", _B))

    # ---- Loss quantification -------------------------------------------------
    story.append(Paragraph("Loss quantification", _S))
    story.append(Paragraph(
        f"<b>{_xml(profile.get('loss_quantification')).upper()} — "
        f"{_xml(profile.get('loss_quantification_note'))}</b>",
        _B,
    ))

    # ---- Methodology, honesty contract, disclaimer ---------------------------
    story.append(Paragraph("Methodology & limitations", _S))
    story.append(Paragraph(
        f"<b>Honesty contract:</b> {_xml(profile.get('honesty_contract'))}",
        _B,
    ))
    story.append(Paragraph(
        f"<b>Disclaimer:</b> {_xml(profile.get('disclaimer'))}",
        _SM,
    ))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=18 * mm,
        title=f"Talaix Insurance Risk Profile — {_xml(asset.get('name', ''))}",
        author="Talaix (real-data decision support)",
        subject="Insurance Environmental Risk Profile",
    )
    doc._report_meta = {
        "generated": profile.get("generated_at", ""),
        "report_id": profile.get("profile_id", ""),
    }
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
