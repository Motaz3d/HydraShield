"""
PDF builder for Green Finance Verification evidence reports.

Generates a real report from the structured verification payload produced by
``src.climate.verification.verify_asset``. No numbers are invented: every
claim comes from the passed-in verification dict, with the same honesty
contract (unavailable data is declared as UNKNOWN).
"""

from __future__ import annotations

import io
import os
from typing import Any, Dict, List, Optional

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image,
    )
    _HAS_REPORTLAB = True
except ImportError:  # honest failure handled by the endpoint
    _HAS_REPORTLAB = False

from .site_image import build_site_context_png, site_context_caption

REPORT_ENGINE_VERSION = "1.0.0"

_BRAND_MARK_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "website", "assets", "brand",
    "logo-master.png",
)


def _brand_mark(width_mm: float = 11.0):
    """The Talaix T + teal dot mark for PDF letterheads (None when missing).

    Uses the navy-on-white master artwork — correct for white PDF pages.
    """
    if not _HAS_REPORTLAB or not os.path.isfile(_BRAND_MARK_PATH):
        return None
    try:
        from PIL import Image as PILImage

        with PILImage.open(_BRAND_MARK_PATH) as im:
            w, h = im.size
        return Image(_BRAND_MARK_PATH,
                     width=width_mm * mm, height=width_mm * mm * h / w)
    except Exception:
        return None


def _title_with_mark(title_text: str, title_style) -> object:
    """Title paragraph with the brand mark right-aligned beside it."""
    mark = _brand_mark()
    if mark is None:
        return Paragraph(title_text, title_style)
    tbl = Table(
        [[Paragraph(title_text, title_style), mark]],
        colWidths=(150 * mm, 24 * mm),
    )
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return tbl

_ACCENT = colors.HexColor("#0ea5e9")
_DARK = colors.HexColor("#0f172a")
_MUTED = colors.HexColor("#64748b")

_TITLE = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=20,
                        leading=24, textColor=_DARK, spaceAfter=2)
_SUBTITLE = ParagraphStyle("subtitle", fontName="Helvetica", fontSize=10,
                           leading=13, textColor=_ACCENT, spaceAfter=2)
_S = ParagraphStyle("section", fontName="Helvetica-Bold", fontSize=13,
                    leading=16, textColor=_DARK, spaceBefore=12, spaceAfter=5,
                    keepWithNext=1)


def _xml(text: Any) -> str:
    """Escape text for reportlab Paragraph. Numeric zero is a real value."""
    return (
        str("" if text is None else text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
_B = ParagraphStyle("body", fontName="Helvetica", fontSize=9.5, leading=13,
                    spaceAfter=3)
_SM = ParagraphStyle("small", fontName="Helvetica", fontSize=8, leading=11,
                     textColor=_MUTED, spaceAfter=2)
_TH = ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=8, leading=10,
                     textColor=colors.white)
_TD = ParagraphStyle("td", fontName="Helvetica", fontSize=8, leading=10)


def _footer(canvas, doc):
    """Professional footer with report metadata and page numbers."""
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#cbd5e1"))
    canvas.setLineWidth(0.5)
    canvas.line(18 * mm, 12 * mm, 192 * mm, 12 * mm)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(_MUTED)
    meta = getattr(doc, "_report_meta", {})
    auth = meta.get("auth_code", "")
    line = (
        f"Talaix — Green Finance Verification · engine v{REPORT_ENGINE_VERSION} · "
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


def _kv_table(rows: List[List[Any]], widths=(45 * mm, 115 * mm)) -> Table:
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


def _checklist_table(checks: List[Dict[str, Any]]) -> Table:
    """DNSH hazard checklist table."""
    rows = [[
        "Taxonomy hazard", "Class", "Claim status", "Level", "Confidence",
    ]]
    for c in checks:
        level = c.get("level") or {}
        level_text = level.get("label") or "—"
        rows.append([
            _xml(c.get("taxonomy_label")),
            _xml(" & ".join(cls.capitalize() for cls in c.get("risk_class", []))),
            _xml(c.get("claim_status", "UNKNOWN")),
            _xml(level_text),
            _xml(c.get("confidence", "—")),
        ])
    t = Table(rows, colWidths=(55 * mm, 28 * mm, 30 * mm, 35 * mm, 22 * mm))
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 0), (-1, 0), _DARK),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _evidence_table(records: List[Dict[str, Any]]) -> Optional[Table]:
    """Evidence records for one hazard."""
    if not records:
        return None
    rows = [[
        Paragraph("Status", _TH), Paragraph("Class", _TH),
        Paragraph("Source / dataset", _TH), Paragraph("Period", _TH),
        Paragraph("Link", _TH),
    ]]
    for rec in records:
        period = "—"
        ref = rec.get("reference_period")
        if ref and (ref.get("start") or ref.get("end")):
            period = f"{ref.get('start') or ''} → {ref.get('end') or ''}".strip(" →")
        link = rec.get("link") or rec.get("provider_url") or ""
        link_cell = f'<a href="{_xml(link)}" color="blue">{_xml(link[:60])}</a>' if link else "—"
        rows.append([
            Paragraph(_xml(rec.get("claim_status") or "UNKNOWN"), _TD),
            Paragraph(_xml(rec.get("evidence_class") or "—"), _TD),
            Paragraph(_xml(f"{rec.get('source') or ''}{(' · ' + rec.get('dataset')) if rec.get('dataset') else ''}"), _TD),
            Paragraph(_xml(period), _TD),
            Paragraph(link_cell, _TD) if link else Paragraph("—", _TD),
        ])
    t = Table(rows, colWidths=(22 * mm, 25 * mm, 55 * mm, 30 * mm, 38 * mm))
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 0), (-1, 0), _ACCENT),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def build_verification_pdf(verification: Dict[str, Any]) -> bytes:
    """Build the Green Finance Verification PDF as bytes."""
    if not _HAS_REPORTLAB:
        raise RuntimeError("reportlab is not installed; PDF generation is unavailable")

    asset = verification.get("asset") or {}
    checks = verification.get("hazard_checks") or []
    gaps = verification.get("declared_gaps") or []
    frameworks = verification.get("frameworks") or []

    story: List[Any] = []

    # ---- Title --------------------------------------------------------------
    story.append(_title_with_mark("Physical Asset Verification", _TITLE))
    story.append(Paragraph("Green Finance Evidence Report", _SUBTITLE))
    story.append(Spacer(1, 4 * mm))

    # ---- Metadata ------------------------------------------------------------
    story.append(Paragraph("Report metadata", _S))
    meta_rows = [
        ["Verification ID", _xml(verification.get("verification_id"))],
        ["Generated", _xml(verification.get("generated_at"))],
        ["Asset name", _xml(asset.get("name"))],
        ["Coordinates", f"{_xml(asset.get('lat'))}, {_xml(asset.get('lon'))}"],
        ["Engine version", _xml(verification.get("engine_version"))],
        ["Frameworks", _xml(", ".join(f.get("name") for f in frameworks))],
    ]
    story.append(_kv_table(meta_rows))

    # ---- Site context image --------------------------------------------------
    lat = asset.get("lat")
    lon = asset.get("lon")
    if lat is not None and lon is not None:
        try:
            img_bytes = build_site_context_png(float(lat), float(lon), window_m=1000.0)
            if img_bytes:
                img = Image(io.BytesIO(img_bytes), width=170 * mm, height=78 * mm)
                story.append(Spacer(1, 3 * mm))
                story.append(img)
                story.append(Paragraph(site_context_caption(), _SM))
        except Exception:
            pass  # Skip image honestly on any rendering failure.

    # ---- Scope & frameworks --------------------------------------------------
    story.append(Paragraph("Scope & frameworks", _S))
    story.append(Paragraph(
        _xml("This report assesses the physical climate hazards listed in the EU Taxonomy "
           "Climate Delegated Act Appendix A for which Talaix has registered, real-data "
           "modules. Each framework below gives context to the vocabulary; the report itself "
           "provides the physical-evidence layer only."),
        _B,
    ))
    for fw in frameworks:
        story.append(Paragraph(
            f"<b>{_xml(fw.get('name'))}</b> — {_xml(fw.get('aspect'))}. "
            f"{_xml(fw.get('note'))}",
            _B,
        ))

    # ---- DNSH checklist ------------------------------------------------------
    story.append(Paragraph("DNSH hazard checklist", _S))
    story.append(_checklist_table(checks))
    story.append(Spacer(1, 2 * mm))

    # ---- Per-hazard evidence -------------------------------------------------
    story.append(Paragraph("Per-hazard evidence details", _S))
    for c in checks:
        label = c.get("taxonomy_label") or c.get("hazard")
        story.append(Paragraph(f"<b>{_xml(label)}</b> "
                               f"({_xml(c.get('claim_status', 'UNKNOWN'))})", _B))
        if c.get("summary"):
            story.append(Paragraph(_xml(c["summary"]), _B))
        level = c.get("level") or {}
        if level.get("basis"):
            story.append(Paragraph(f"<b>Level basis:</b> {_xml(level['basis'])}", _SM))
        ev_table = _evidence_table(c.get("evidence") or [])
        if ev_table:
            story.append(ev_table)
        if c.get("limitations"):
            for lim in c["limitations"]:
                story.append(Paragraph(f"<b>Limitation:</b> {_xml(lim)}", _SM))
        story.append(Spacer(1, 2 * mm))

    # ---- Declared data gaps --------------------------------------------------
    story.append(Paragraph("Declared data gaps", _S))
    if gaps:
        for gap in gaps:
            story.append(Paragraph(
                f"• <b>{_xml(gap.get('taxonomy_label') or gap.get('hazard'))}</b> — "
                f"{_xml(gap.get('reason'))}",
                _B,
            ))
    else:
        story.append(Paragraph("No declared data gaps for this asset.", _B))

    # ---- Methodology, honesty contract, disclaimer ---------------------------
    story.append(Paragraph("Methodology & limitations", _S))
    story.append(Paragraph(
        _xml("Each hazard check is produced by the corresponding Talaix hazard module from "
           "real, documented data sources. Claim status follows the platform ontology: "
           "OBSERVED, DOCUMENTED, REPORTED, MODELLED, INFERRED or UNKNOWN. A status of "
           "MODELLED means a declared model with declared inputs; it is a screening "
           "indicator unless explicitly labelled validated (DOCUMENTED)."),
        _B,
    ))
    story.append(Paragraph(
        f"<b>Honesty contract:</b> {_xml(verification.get('honesty_contract'))}",
        _B,
    ))
    story.append(Paragraph(
        f"<b>Disclaimer:</b> {_xml(verification.get('disclaimer'))}",
        _SM,
    ))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=18 * mm,
        title=f"Talaix Green Finance Verification — {_xml(asset.get('name', ''))}",
        author="Talaix (real-data decision support)",
        subject="Physical Asset Verification — Green Finance Evidence Report",
    )
    doc._report_meta = {
        "generated": verification.get("generated_at", ""),
        "report_id": verification.get("verification_id", ""),
        "auth_code": verification.get("authenticity", {}).get("code", ""),
    }
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
