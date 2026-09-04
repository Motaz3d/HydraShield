"""
PDF builder for Sustainability Evidence Reports (CSRD / ESRS-oriented).

Reuses the shared report components from ``src.dashboard.verification_report``
(styles, tables, XML-escape helper) and adds the CSRD-specific sections.
"""

from __future__ import annotations

import io
from typing import Any, Dict, List, Optional

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
    _checklist_table,
    _evidence_table,
    _kv_table,
    _xml,
)

REPORT_ENGINE_VERSION = "1.0.0"


def _footer(canvas, doc):
    """Sustainability report footer with metadata and page numbers."""
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#cbd5e1"))
    canvas.setLineWidth(0.5)
    canvas.line(18 * mm, 12 * mm, 192 * mm, 12 * mm)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#64748b"))
    meta = getattr(doc, "_report_meta", {})
    auth = meta.get("auth_code", "")
    line = (
        f"Talaix — Sustainability Evidence Report · engine v{REPORT_ENGINE_VERSION} · "
        f"{meta.get('generated', '')} · report {meta.get('report_id', '')}"
    )
    if auth:
        suffix = f" · verify {auth}"
        if len(line) + len(suffix) > 155:
            canvas.drawString(18 * mm, 8 * mm, line)
            canvas.drawString(18 * mm, 4.5 * mm, f"verify {auth}")
        else:
            line += suffix
            canvas.drawString(18 * mm, 8 * mm, line)
    else:
        canvas.drawString(18 * mm, 8 * mm, line)
    canvas.drawRightString(192 * mm, 8 * mm, f"Page {doc.page}")
    canvas.restoreState()


def _coverage_table(coverage_map: List[Dict[str, Any]]) -> Table:
    rows = [["Area", "Ref", "Coverage", "Note"]]
    for item in coverage_map:
        rows.append([
            _xml(item.get("area")),
            _xml(item.get("ref")),
            _xml(item.get("coverage")),
            _xml(item.get("note")),
        ])
    t = Table(rows, colWidths=(55 * mm, 28 * mm, 32 * mm, 55 * mm))
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def build_sustainability_pdf(payload: Dict[str, Any]) -> bytes:
    """Build the Sustainability Evidence Report PDF as bytes."""
    if not _HAS_REPORTLAB:
        raise RuntimeError("reportlab is not installed; PDF generation is unavailable")

    company = payload.get("company") or {}
    company_fields = company.get("fields") or {}
    coverage_map = payload.get("coverage_map") or []
    frameworks = payload.get("frameworks") or []
    evidence_standard = payload.get("evidence_standard") or {}
    portfolio_summary = payload.get("portfolio_summary") or {}
    site_results = payload.get("site_results") or []
    declared_gaps = payload.get("declared_gaps") or []

    story: List[Any] = []

    # ---- Title --------------------------------------------------------------
    story.append(Paragraph("Sustainability Evidence Report", _TITLE))
    story.append(Paragraph("CSRD / ESRS physical-evidence pack", _SUBTITLE))
    story.append(Spacer(1, 4 * mm))

    # ---- Report metadata ----------------------------------------------------
    story.append(Paragraph("Report metadata", _S))
    meta_rows = [
        ["Report ID", _xml(payload.get("report_id"))],
        ["Generated", _xml(payload.get("generated_at"))],
        ["Engine version", _xml(payload.get("engine_version"))],
        ["Company", _xml(company_fields.get("name"))],
    ]
    story.append(_kv_table(meta_rows))

    # ---- Company profile ----------------------------------------------------
    story.append(Paragraph("Company profile", _S))
    story.append(Paragraph(
        _xml("Company-supplied metadata — not verified by Talaix."),
        _SM,
    ))
    company_rows = [
        ["Name", _xml(company_fields.get("name"))],
        ["Sector", _xml(company_fields.get("sector"))],
        ["Country", _xml(company_fields.get("country"))],
        ["Website", _xml(company_fields.get("website"))],
        ["Description", _xml(company_fields.get("description"))],
    ]
    story.append(_kv_table(company_rows))

    # ---- Frameworks ---------------------------------------------------------
    story.append(Paragraph("Frameworks", _S))
    for fw in frameworks:
        story.append(Paragraph(
            f"<b>{_xml(fw.get('name'))}</b> — {_xml(fw.get('aspect'))}. "
            f"{_xml(fw.get('note'))}",
            _B,
        ))

    # ---- Disclosure coverage map -------------------------------------------
    story.append(Paragraph("Disclosure coverage map", _S))
    story.append(Paragraph(
        _xml("Items marked 'not_covered' are declared boundaries of this pack, not omissions. "
             "They require company data or other assurance providers."),
        _B,
    ))
    story.append(_coverage_table(coverage_map))

    # ---- Portfolio physical-risk summary ------------------------------------
    story.append(Paragraph("Portfolio physical-risk summary", _S))
    summary_rows = [
        ["Sites analysed", _xml(portfolio_summary.get("site_count"))],
        ["Sites with real data", _xml(portfolio_summary.get("ok_count"))],
        ["Total declared gaps", _xml(portfolio_summary.get("total_declared_gaps"))],
    ]
    story.append(_kv_table(summary_rows))
    highest = portfolio_summary.get("highest_levels") or {}
    if highest:
        story.append(Paragraph("<b>Highest levels across sites:</b>", _B))
        for label, items in highest.items():
            story.append(Paragraph(f"• <b>{_xml(label)}</b>: {_xml('; '.join(items))}", _B))

    # ---- Per-site DNSH checklist --------------------------------------------
    story.append(Paragraph("Per-site DNSH checklist", _S))
    for site in site_results:
        asset = site.get("asset") or {}
        site_label = asset.get("name") or f"{asset.get('lat')}, {asset.get('lon')}"
        story.append(Paragraph(f"<b>{_xml(site_label)}</b> "
                               f"({_xml(site.get('verification_id'))})", _B))
        if not site.get("ok"):
            story.append(Paragraph(
                f"Site could not be verified: {_xml(site.get('error'))}",
                _SM,
            ))
            continue
        # Need full hazard_checks to render checklist; payload stores trimmed results only.
        # Build a lightweight checklist from hazard_levels if available, otherwise note.
        hazard_levels = site.get("hazard_levels") or {}
        if hazard_levels:
            rows = [["Hazard", "Level"]]
            for hazard, level in hazard_levels.items():
                rows.append([_xml(hazard), _xml(level)])
            t = Table(rows, colWidths=(80 * mm, 80 * mm))
            t.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ]))
            story.append(t)
        site_gaps = site.get("declared_gaps") or []
        if site_gaps:
            story.append(Paragraph("<b>Declared gaps at this site:</b>", _SM))
            for gap in site_gaps:
                story.append(Paragraph(
                    f"• {_xml(gap.get('taxonomy_label') or gap.get('hazard'))}: "
                    f"{_xml(gap.get('reason'))}",
                    _SM,
                ))
        story.append(Spacer(1, 2 * mm))

    # ---- All declared data gaps --------------------------------------------
    story.append(Paragraph("All declared data gaps", _S))
    if declared_gaps:
        for gap in declared_gaps:
            story.append(Paragraph(
                f"• <b>{_xml(gap.get('site'))}</b> — "
                f"{_xml(gap.get('taxonomy_label') or gap.get('hazard'))}: "
                f"{_xml(gap.get('reason'))}",
                _B,
            ))
    else:
        story.append(Paragraph("No declared data gaps across the portfolio.", _B))

    # ---- Talaix Evidence Standard -------------------------------------------
    story.append(Paragraph("Talaix Evidence Standard", _S))
    for criterion in evidence_standard.get("criteria") or []:
        story.append(Paragraph(f"• {_xml(criterion)}", _B))
    story.append(Paragraph(
        f"<b>{_xml(evidence_standard.get('not_accreditation'))}</b>",
        _B,
    ))

    # ---- Methodology, honesty contract, disclaimer --------------------------
    story.append(Paragraph("Methodology & limitations", _S))
    story.append(Paragraph(
        f"<b>Honesty contract:</b> {_xml(payload.get('honesty_contract'))}",
        _B,
    ))
    story.append(Paragraph(
        f"<b>Disclaimer:</b> {_xml(payload.get('disclaimer'))}",
        _SM,
    ))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=18 * mm,
        title=f"Talaix Sustainability Evidence Report — {_xml(company_fields.get('name', ''))}",
        author="Talaix (real-data decision support)",
        subject="Sustainability Evidence Report — CSRD / ESRS physical-evidence pack",
    )
    doc._report_meta = {
        "generated": payload.get("generated_at", ""),
        "report_id": payload.get("report_id", ""),
        "auth_code": payload.get("authenticity", {}).get("code", ""),
    }
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
