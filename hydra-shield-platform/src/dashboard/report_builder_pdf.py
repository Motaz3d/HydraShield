"""
PDF builder for the interactive Report Builder.

Renders a user-edited section list into a branded PDF. Engine-generated
sections are printed as composed; sections marked edited by the user carry an
"[edited by user]" marker. The metadata block declares how many sections were
edited, so the document is honest about human intervention.
"""

from __future__ import annotations

import io
from typing import Any, Dict, List

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, TableStyle, Image
    _HAS_REPORTLAB = True
except ImportError:  # honest failure handled by the endpoint
    _HAS_REPORTLAB = False

from .site_image import build_site_context_png, site_context_caption
from .verification_report import (
    _xml,
    _kv_table,
    _S,
    _B,
    _SM,
    _TITLE,
    _SUBTITLE,
    _ACCENT,
    _DARK,
    _MUTED,
)

REPORT_ENGINE_VERSION = "1.0.0"

_EDITED = ParagraphStyle(
    "edited",
    fontName="Helvetica-Bold",
    fontSize=9,
    leading=12,
    textColor=_ACCENT,
    spaceBefore=2,
    spaceAfter=4,
)


def _footer(canvas, doc):
    """Footer for the interactive report builder PDF."""
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#cbd5e1"))
    canvas.setLineWidth(0.5)
    canvas.line(18 * mm, 12 * mm, 192 * mm, 12 * mm)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(_MUTED)
    meta = getattr(doc, "_report_meta", {})
    canvas.drawString(
        18 * mm,
        8 * mm,
        f"Talaix — Interactive Report Builder · engine v{REPORT_ENGINE_VERSION} · "
        f"{meta.get('generated', '')} · draft {meta.get('draft_id', '')}",
    )
    canvas.drawRightString(192 * mm, 8 * mm, f"Page {doc.page}")
    canvas.restoreState()


def build_custom_pdf(title: str, sections: List[Dict[str, Any]], meta: Dict[str, Any]) -> bytes:
    """Build a PDF from the edited section list and metadata."""
    if not _HAS_REPORTLAB:
        raise RuntimeError("reportlab is not installed; PDF generation is unavailable")

    story: List[Any] = []

    # ---- Title -------------------------------------------------------------
    story.append(Paragraph(_xml(title), _TITLE))
    story.append(Paragraph("Interactive evidence report — composed section by section", _SUBTITLE))
    story.append(Spacer(1, 4 * mm))

    # ---- Metadata ------------------------------------------------------------
    story.append(Paragraph("Report metadata", _S))
    meta_rows = [
        ["Draft ID", _xml(meta.get("draft_id"))],
        ["Generated", _xml(meta.get("generated_at"))],
        ["Kind", _xml(meta.get("kind"))],
        ["Engine version", _xml(meta.get("engine_version"))],
        ["Total sections", str(len(sections))],
        ["Edited by user", str(meta.get("edited_count", 0))],
    ]
    story.append(_kv_table(meta_rows))

    # ---- Site context image --------------------------------------------------
    lat = meta.get("lat")
    lon = meta.get("lon")
    if lat is not None and lon is not None:
        try:
            img_bytes = build_site_context_png(float(lat), float(lon), window_m=1000.0)
            if img_bytes:
                img = Image(io.BytesIO(img_bytes), width=170 * mm, height=78 * mm)
                story.append(Spacer(1, 3 * mm))
                story.append(img)
                story.append(Paragraph(site_context_caption(), _SM))
            else:
                story.append(Paragraph("Site context image unavailable for this run.", _SM))
        except Exception:
            story.append(Paragraph("Site context image unavailable for this run.", _SM))
    else:
        story.append(Paragraph("Site context image unavailable for this run.", _SM))

    # ---- Sections ------------------------------------------------------------
    for s in sections:
        kind = s.get("kind", "body")
        story.append(Paragraph(f"<i>[{kind.upper()}]</i> {_xml(s.get('heading'))}", _S))
        story.append(Paragraph(_xml(s.get("text", "")).replace("\n", "<br/>"), _B))
        if s.get("why"):
            story.append(Paragraph(f"<i>Why this section:</i> {_xml(s['why'])}", _SM))
        if s.get("edited"):
            story.append(Paragraph("[edited by user]", _EDITED))
        story.append(Spacer(1, 1 * mm))

    # ---- Composition & honesty ---------------------------------------------
    total = len(sections)
    edited = meta.get("edited_count", 0)
    story.append(Paragraph("Composition & honesty", _S))
    story.append(Paragraph(
        f"{edited} of {total} section{'s were' if edited != 1 else ' was'} edited by the user. "
        "Engine-generated text is template-composed from the cited evidence only; "
        "user-edited text is the user's own and is marked in this document.",
        _B,
    ))
    story.append(Paragraph(
        f"Honesty note: {_xml(meta.get('honesty_note', ''))}",
        _SM,
    ))
    if meta.get("disclaimer"):
        story.append(Paragraph(f"Disclaimer: {_xml(meta['disclaimer'])}", _SM))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=18 * mm,
        title=_xml(title),
        author="Talaix (interactive report builder)",
        subject="Interactive evidence report",
    )
    doc._report_meta = {
        "generated": meta.get("generated_at", ""),
        "draft_id": meta.get("draft_id", ""),
    }
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
