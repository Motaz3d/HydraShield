"""
PDF builder for Talaix Academy Certificates of Completion.

A4 landscape, branded header, honest non-accreditation note.
"""

from __future__ import annotations

import io
from typing import Any, Dict

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    _HAS_REPORTLAB = True
except ImportError:  # pragma: no cover
    _HAS_REPORTLAB = False


def _xml(text: Any) -> str:
    return (
        str("" if text is None else text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def build_certificate_pdf(cert: Dict[str, Any], course_title: str) -> bytes:
    """Build a Certificate of Completion PDF as bytes."""
    if not _HAS_REPORTLAB:
        raise RuntimeError("reportlab is not installed; PDF generation is unavailable")

    accent = colors.HexColor("#0ea5e9")
    dark = colors.HexColor("#0f172a")
    muted = colors.HexColor("#64748b")

    title_style = ParagraphStyle(
        "cert_title", fontName="Helvetica-Bold", fontSize=36,
        leading=42, textColor=dark, alignment=1, spaceAfter=8,
    )
    subtitle_style = ParagraphStyle(
        "cert_subtitle", fontName="Helvetica", fontSize=14,
        leading=18, textColor=accent, alignment=1, spaceAfter=24,
    )
    name_style = ParagraphStyle(
        "cert_name", fontName="Helvetica-Bold", fontSize=28,
        leading=34, textColor=dark, alignment=1, spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "cert_body", fontName="Helvetica", fontSize=13,
        leading=18, textColor=dark, alignment=1, spaceAfter=6,
    )
    small_style = ParagraphStyle(
        "cert_small", fontName="Helvetica", fontSize=10,
        leading=14, textColor=muted, alignment=1, spaceAfter=4,
    )
    note_style = ParagraphStyle(
        "cert_note", fontName="Helvetica-Oblique", fontSize=10,
        leading=14, textColor=muted, alignment=1, spaceBefore=20,
    )

    story: list = []

    # Header
    story.append(Paragraph("Talaix Academy", subtitle_style))
    story.append(Paragraph("Certificate of Completion", title_style))
    story.append(Spacer(1, 12 * mm))

    # Recipient
    story.append(Paragraph("This certifies that", body_style))
    story.append(Paragraph(_xml(cert.get("display_name") or "Student"), name_style))
    story.append(Spacer(1, 6 * mm))

    # Course + score
    story.append(Paragraph("has completed the pilot course", body_style))
    story.append(Paragraph(_xml(course_title), name_style))
    story.append(Spacer(1, 4 * mm))

    score_text = (
        f"Score: {cert.get('score_correct')} / {cert.get('score_total')} correct "
        f"· Issued: {_xml(cert.get('issued_at'))}"
    )
    story.append(Paragraph(score_text, body_style))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(f"Certificate ID: {_xml(cert.get('certificate_id'))}", small_style))

    # Honest non-accreditation note
    story.append(Paragraph(
        "This certificate attests completion of the Talaix Academy pilot course. "
        "It is not an accredited academic qualification and not a professional certification.",
        note_style,
    ))

    # Verify hint
    story.append(Paragraph(
        f"Verify at /api/v2/academy/certificates/{_xml(cert.get('certificate_id'))}/verify",
        small_style,
    ))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=25 * mm, rightMargin=25 * mm,
        topMargin=20 * mm, bottomMargin=20 * mm,
        title=f"Talaix Academy Certificate — {_xml(course_title)}",
        author="Talaix Academy",
        subject="Certificate of Completion",
    )
    doc.build(story)
    return buf.getvalue()
