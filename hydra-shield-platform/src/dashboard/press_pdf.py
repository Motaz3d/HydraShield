"""
PDF builder for Talaix Press evidence packs.

Generates a deterministic, cited PDF from the structured pack produced by
``src.climate.press.build_press_pack``. No prose is invented: every number and
quote comes from the pack payload.
"""

from __future__ import annotations

import io
from typing import Any, Dict, List

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

from .press_charts import build_ndvi_png, climate_series_png
from .site_image import build_site_context_png, site_context_caption
from .verification_report import _title_with_mark

ENGINE_VERSION = "1.0.0"

_ACCENT = colors.HexColor("#0ea5e9") if _HAS_REPORTLAB else None
_DARK = colors.HexColor("#0f172a") if _HAS_REPORTLAB else None
_MUTED = colors.HexColor("#64748b") if _HAS_REPORTLAB else None


def _xml(text: Any) -> str:
    """Escape text for reportlab Paragraph. Numeric zero is a real value."""
    return (
        str("" if text is None else text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _styles():
    return {
        "title": ParagraphStyle(
            "title",
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=24,
            textColor=_DARK,
            spaceAfter=2,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", fontName="Helvetica", fontSize=11, leading=14,
            textColor=_ACCENT, spaceAfter=4
        ),
        "section": ParagraphStyle(
            "section", fontName="Helvetica-Bold", fontSize=13, leading=16,
            textColor=_DARK, spaceBefore=12, spaceAfter=5, keepWithNext=1
        ),
        "body": ParagraphStyle(
            "body", fontName="Helvetica", fontSize=9.5, leading=13, spaceAfter=3
        ),
        "small": ParagraphStyle(
            "small", fontName="Helvetica", fontSize=8, leading=11,
            textColor=_MUTED, spaceAfter=2
        ),
    }


def _footer(canvas, doc):
    """Footer with pack metadata and page numbers."""
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#cbd5e1"))
    canvas.setLineWidth(0.5)
    canvas.line(18 * mm, 12 * mm, 192 * mm, 12 * mm)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(_MUTED)
    meta = getattr(doc, "_press_meta", {})
    auth = meta.get("auth_code", "")
    line = (
        f"Talaix — Press Evidence Pack · engine v{ENGINE_VERSION} · "
        f"{meta.get('generated', '')} · pack {meta.get('pack_id', '')}"
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


def _kv_table(rows: List[List[Any]]) -> Table:
    t = Table(rows, colWidths=(45 * mm, 115 * mm))
    t.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("TEXTCOLOR", (0, 0), (0, -1), _MUTED),
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return t


def _figure_from_bytes(img_bytes: bytes, width: float = 170 * mm, height: float = 85 * mm):
    return Image(io.BytesIO(img_bytes), width=width, height=height)


def build_press_pdf(pack: Dict[str, Any]) -> bytes:
    """Build the Press evidence-pack PDF as bytes."""
    if not _HAS_REPORTLAB:
        raise RuntimeError("reportlab is not installed; PDF generation is unavailable")

    styles = _styles()
    loc = pack.get("location") or {}
    lat = loc.get("lat")
    lon = loc.get("lon")

    story: List[Any] = []

    # Title block
    story.append(_title_with_mark(_xml(pack.get("headline")), styles["title"]))
    if pack.get("subhead"):
        story.append(Paragraph(_xml(pack["subhead"]), styles["subtitle"]))
    story.append(Spacer(1, 2 * mm))

    # Metadata
    story.append(Paragraph("Pack metadata", styles["section"]))
    meta_rows = [
        ["Pack ID", _xml(pack.get("pack_id"))],
        ["Generated", _xml(pack.get("generated_at"))],
        ["Language", _xml(pack.get("language"))],
        ["Tier", _xml(pack.get("tier"))],
        ["Location", _xml(loc.get("name"))],
        ["Coordinates", f"{_xml(lat)}, {_xml(lon)}"],
        ["Verification ID", _xml(pack.get("verification_id"))],
    ]
    story.append(_kv_table(meta_rows))

    # Lead
    if pack.get("lead"):
        story.append(Paragraph("Lead", styles["section"]))
        story.append(Paragraph(_xml(pack["lead"]), styles["body"]))

    # Key facts
    if pack.get("key_facts"):
        story.append(Paragraph("Key facts", styles["section"]))
        for fact in pack["key_facts"]:
            story.append(Paragraph(f"• {_xml(fact)}", styles["body"]))

    # Figures
    story.append(Paragraph("Figures", styles["section"]))
    fig_added = False
    try:
        if lat is not None and lon is not None:
            climate_png = climate_series_png(float(lat), float(lon))
            if climate_png:
                story.append(_figure_from_bytes(climate_png))
                story.append(Paragraph("ERA5-based annual temperature and precipitation context.", styles["small"]))
                fig_added = True
    except Exception:
        pass

    try:
        if lat is not None and lon is not None:
            from ..dashboard.real_data import fetch_satellite_data

            satellite = fetch_satellite_data(float(lat), float(lon))
            grid = satellite.get("ndvi_grid") if isinstance(satellite, dict) else None
            ndvi_png = build_ndvi_png(grid)
            if ndvi_png:
                story.append(_figure_from_bytes(ndvi_png, width=140 * mm, height=140 * mm))
                story.append(Paragraph(f"Sentinel-2 NDVI grid ({satellite.get('observation_date', 'recent')}).", styles["small"]))
                fig_added = True
    except Exception:
        pass

    try:
        if lat is not None and lon is not None:
            site_png = build_site_context_png(float(lat), float(lon))
            if site_png:
                story.append(_figure_from_bytes(site_png, width=170 * mm, height=78 * mm))
                story.append(Paragraph(site_context_caption(), styles["small"]))
                fig_added = True
    except Exception:
        pass

    if not fig_added:
        story.append(Paragraph("No figures could be generated for this location.", styles["body"]))

    # Quotable sourced lines
    if pack.get("quotable_lines"):
        story.append(Paragraph("Quotable sourced lines", styles["section"]))
        for line in pack["quotable_lines"]:
            text = line.get("text", "")
            source = line.get("source", "")
            status = line.get("status", "")
            story.append(Paragraph(f"“{_xml(text)}”", styles["body"]))
            story.append(
                Paragraph(
                    f"<b>Source:</b> {_xml(source)} · <b>Status:</b> {_xml(status)}",
                    styles["small"],
                )
            )
            story.append(Spacer(1, 1 * mm))

    # Press watch
    watch = pack.get("press_watch") or []
    if watch:
        story.append(Paragraph("Press watch registry", styles["section"]))
        for entry in watch:
            name = entry.get("name") or entry.get("title") or "Source"
            url = entry.get("url", "")
            publisher = entry.get("publisher") or entry.get("source") or ""
            line = f"<b>{_xml(name)}</b>"
            if publisher:
                line += f" — {_xml(publisher)}"
            story.append(Paragraph(line, styles["body"]))
            if url:
                story.append(
                    Paragraph(
                        f'<a href="{_xml(url)}" color="blue">{_xml(url[:80])}</a>',
                        styles["small"],
                    )
                )

    # Data sources
    if pack.get("sources"):
        story.append(Paragraph("Data sources", styles["section"]))
        for src in pack["sources"]:
            name = src.get("name", "")
            provider = src.get("provider", "")
            url = src.get("url", "")
            line = f"<b>{_xml(name)}</b>"
            if provider:
                line += f" ({_xml(provider)})"
            story.append(Paragraph(line, styles["body"]))
            if url:
                story.append(
                    Paragraph(
                        f'<a href="{_xml(url)}" color="blue">{_xml(url[:80])}</a>',
                        styles["small"],
                    )
                )

    # Honesty and methodology
    story.append(Paragraph("Methodology & honesty", styles["section"]))
    story.append(Paragraph(_xml(pack.get("methodology_note", "")), styles["body"]))
    story.append(Paragraph(_xml(pack.get("honesty_note", "")), styles["body"]))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=18 * mm,
        title=f"Talaix Press Evidence Pack — {_xml(loc.get('name', ''))}",
        author="Talaix (real-data decision support)",
        subject="Press Evidence Pack",
    )
    doc._press_meta = {
        "generated": pack.get("generated_at", ""),
        "pack_id": pack.get("pack_id", ""),
        "auth_code": pack.get("authenticity", {}).get("code", ""),
    }
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
