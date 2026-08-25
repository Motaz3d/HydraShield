"""
PDF builder for Supply Chain Origin & EUDR Evidence reports.

Reuses shared report components from ``src.dashboard.verification_report``.
The report is generated from the structured claim payload produced by
``src.climate.supplychain.evaluate_claim``.
"""

from __future__ import annotations

import io
from typing import Any, Dict, List

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .verification_report import (
    _B,
    _HAS_REPORTLAB,
    _S,
    _SM,
    _SUBTITLE,
    _TITLE,
    _kv_table,
    _xml,
)

REPORT_ENGINE_VERSION = "1.0.0"


def _footer(canvas, doc):
    """Supply-chain report footer with metadata and page numbers."""
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#cbd5e1"))
    canvas.setLineWidth(0.5)
    canvas.line(18 * mm, 12 * mm, 192 * mm, 12 * mm)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#64748b"))
    meta = getattr(doc, "_report_meta", {})
    canvas.drawString(
        18 * mm, 8 * mm,
        f"Talaix — Supply Chain Origin Evidence · engine v{REPORT_ENGINE_VERSION} · "
        f"{meta.get('generated', '')} · report {meta.get('report_id', '')}",
    )
    canvas.drawRightString(192 * mm, 8 * mm, f"Page {doc.page}")
    canvas.restoreState()


def _plot_overview_table(plots: List[Dict[str, Any]]) -> Table:
    rows = [["Plot", "Coordinates", "Verdict", "Land cover", "NDVI", "Evidence sources"]]
    for p in plots:
        landcover = p.get("landcover") or {}
        satellite = p.get("satellite") or {}
        lc_label = landcover.get("dominant_label") or landcover.get("error") or "—"
        ndvi = satellite.get("ndvi")
        ndvi_text = f"{ndvi:.3f}" if ndvi is not None else (satellite.get("error") or "—")
        rows.append([
            _xml(p.get("name")),
            f"{_xml(p.get('lat'))}, {_xml(p.get('lon'))}",
            _xml(p.get("verdict")),
            _xml(lc_label),
            _xml(ndvi_text),
            str(len(p.get("evidence") or [])),
        ])
    t = Table(rows, colWidths=(38 * mm, 35 * mm, 28 * mm, 32 * mm, 22 * mm, 25 * mm))
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


def _evidence_list(evidence: List[Dict[str, Any]]) -> str:
    if not evidence:
        return "None."
    parts = []
    for rec in evidence:
        source = rec.get("source") or "—"
        dataset = rec.get("dataset") or ""
        status = rec.get("claim_status") or "—"
        parts.append(f"• {_xml(source)}{(' · ' + _xml(dataset)) if dataset else ''} ({_xml(status)})")
    return "<br/>".join(parts)


def build_supplychain_pdf(claim: Dict[str, Any]) -> bytes:
    """Build the Supply Chain Origin Evidence PDF as bytes."""
    if not _HAS_REPORTLAB:
        raise RuntimeError("reportlab is not installed; PDF generation is unavailable")

    plots = claim.get("plots") or []
    gaps = claim.get("declared_gaps") or []
    frameworks = claim.get("frameworks") or []
    deforestation = claim.get("deforestation_assessment") or {}

    story: List[Any] = []

    # ---- Title --------------------------------------------------------------
    story.append(Paragraph("Supply Chain Origin Evidence", _TITLE))
    story.append(Paragraph("EUDR screening — not a deforestation-free verification", _SUBTITLE))
    story.append(Spacer(1, 4 * mm))

    # ---- Metadata ------------------------------------------------------------
    story.append(Paragraph("Report metadata", _S))
    meta_rows = [
        ["Claim ID", _xml(claim.get("claim_id"))],
        ["Generated", _xml(claim.get("generated_at"))],
        ["Supplier", _xml(claim.get("supplier"))],
        ["Commodity", _xml(claim.get("commodity"))],
        ["Country", _xml(claim.get("country"))],
        ["Plots screened", _xml(claim.get("plot_count"))],
        ["Engine version", _xml(claim.get("engine_version"))],
        ["Claim verdict", _xml(claim.get("claim_verdict"))],
        ["EUDR cutoff", _xml(claim.get("eudr_cutoff_date"))],
        ["Deforestation assessment", _xml(deforestation.get("status"))],
    ]
    story.append(_kv_table(meta_rows))

    # ---- Scope & frameworks --------------------------------------------------
    story.append(Paragraph("Scope &amp; frameworks", _S))
    story.append(Paragraph(
        _xml("This report screens origin/green claims against the real datasets "
           "available to Talaix. It does not verify EUDR compliance or "
           "deforestation-free status."),
        _B,
    ))
    for fw in frameworks:
        story.append(Paragraph(
            f"<b>{_xml(fw.get('name'))}</b> — {_xml(fw.get('aspect'))}. "
            f"{_xml(fw.get('note'))}",
            _B,
        ))

    # ---- Deforestation assessment ------------------------------------------
    story.append(Paragraph("Deforestation assessment", _S))
    story.append(Paragraph(
        f"<b>Status:</b> {_xml(deforestation.get('status'))}", _B,
    ))
    story.append(Paragraph(
        f"<b>Reason:</b> {_xml(deforestation.get('reason'))}", _B,
    ))
    story.append(Paragraph(
        f"<b>Timeline note:</b> {_xml(claim.get('eudr_timeline_note'))}", _SM,
    ))

    # ---- Plot overview -------------------------------------------------------
    story.append(Paragraph("Per-plot evidence overview", _S))
    if plots:
        story.append(_plot_overview_table(plots))
    else:
        story.append(Paragraph("No plots were supplied or resolved.", _B))

    # ---- Per-plot details ----------------------------------------------------
    if plots:
        story.append(Paragraph("Per-plot details", _S))
        for p in plots:
            story.append(Paragraph(
                f"<b>{_xml(p.get('name'))}</b> — {_xml(p.get('verdict'))}", _B,
            ))
            story.append(Paragraph(
                f"<b>Coordinates:</b> {_xml(p.get('lat'))}, {_xml(p.get('lon'))}", _SM,
            ))
            story.append(Paragraph(
                f"<b>Evidence:</b><br/>{_evidence_list(p.get('evidence') or [])}", _SM,
            ))
            if p.get("limitations"):
                for lim in p["limitations"]:
                    story.append(Paragraph(f"<b>Limitation:</b> {_xml(lim)}", _SM))
            story.append(Spacer(1, 2 * mm))

    # ---- Declared data gaps --------------------------------------------------
    story.append(Paragraph("Declared data gaps", _S))
    if gaps:
        for gap in gaps:
            dataset = gap.get("dataset") or gap.get("type")
            story.append(Paragraph(
                f"• <b>{_xml(dataset)}</b> — {_xml(gap.get('reason'))}",
                _B,
            ))
    else:
        story.append(Paragraph("No declared data gaps for this claim.", _B))

    # ---- Methodology, honesty contract, disclaimer ---------------------------
    story.append(Paragraph("Methodology &amp; limitations", _S))
    story.append(Paragraph(
        f"<b>Honesty contract:</b> {_xml(claim.get('honesty_contract'))}",
        _B,
    ))
    story.append(Paragraph(
        f"<b>Disclaimer:</b> {_xml(claim.get('disclaimer'))}",
        _SM,
    ))

    buf = io.BytesIO()
    safe_label = "".join(c if c.isalnum() else "_" for c in str(claim.get("commodity") or claim.get("supplier") or "claim"))[:40]
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=18 * mm,
        title=f"Talaix Supply Chain Origin Evidence — {_xml(claim.get('supplier', ''))}",
        author="Talaix (real-data decision support)",
        subject="Supply Chain Origin Evidence — EUDR Screening",
    )
    doc._report_meta = {
        "generated": claim.get("generated_at", ""),
        "report_id": claim.get("claim_id", ""),
    }
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
