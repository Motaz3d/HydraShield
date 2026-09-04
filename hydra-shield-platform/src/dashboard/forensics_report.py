"""
PDF builder for Environmental Forensic Evidence Packs.

Reuses shared report components from ``src.dashboard.verification_report``.
The report is generated from the structured payload produced by
``src.climate.forensics.assess_case``.
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
    _evidence_table,
    _kv_table,
    _xml,
)

REPORT_ENGINE_VERSION = "1.0.0"


def _footer(canvas, doc):
    """Forensic evidence pack footer with metadata and page numbers."""
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#cbd5e1"))
    canvas.setLineWidth(0.5)
    canvas.line(18 * mm, 12 * mm, 192 * mm, 12 * mm)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#64748b"))
    meta = getattr(doc, "_report_meta", {})
    auth = meta.get("auth_code", "")
    line = (
        f"Talaix — Environmental Forensic Evidence Pack · engine v{REPORT_ENGINE_VERSION} · "
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


def _result_badge(result: str) -> str:
    if result == "consistent":
        return f'<font color="#15803d">{_xml(result)}</font>'
    if result == "inconsistent":
        return f'<font color="#b91c1c">{_xml(result)}</font>'
    return f'<font color="#64748b">{_xml(result)}</font>'


def _consistency_matrix(checks: List[Dict[str, Any]]) -> Table:
    rows = [["Check", "Result", "Basis"]]
    for c in checks:
        rows.append([
            _xml(c.get("check")),
            Paragraph(_result_badge(c.get("result", "—")), _B),
            Paragraph(_xml(c.get("basis")), _B),
        ])
    t = Table(rows, colWidths=(45 * mm, 28 * mm, 102 * mm))
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _chain_of_custody_table(records: List[Dict[str, Any]]) -> Table:
    rows = [["Evidence ID", "Source", "Dataset", "Acquired", "Content hash"]]
    for rec in records:
        rows.append([
            _xml(rec.get("evidence_id")),
            _xml(rec.get("source")),
            _xml(rec.get("dataset")),
            _xml(rec.get("acquired_at")),
            _xml(rec.get("content_hash")),
        ])
    t = Table(rows, colWidths=(35 * mm, 32 * mm, 38 * mm, 32 * mm, 38 * mm))
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def _bundle_summary(bundle: Dict[str, Any]) -> str:
    parts = []
    landcover = bundle.get("landcover") or {}
    if "error" not in landcover and landcover.get("dominant_label"):
        parts.append(f"Land cover: {_xml(landcover.get('dominant_label'))} ({landcover.get('dominant_fraction')}).")
    satellite = bundle.get("satellite") or {}
    if "error" not in satellite and satellite.get("ndvi") is not None:
        parts.append(f"NDVI: {satellite['ndvi']:.3f}.")
    fires = bundle.get("active_fires") or {}
    if fires.get("available"):
        parts.append(f"Active fires: {fires.get('count', 0)} detections within {fires.get('radius_km')} km / {fires.get('days')} days.")
    return " ".join(parts)


def build_forensics_pdf(payload: Dict[str, Any]) -> bytes:
    """Build the Environmental Forensic Evidence Pack PDF as bytes."""
    if not _HAS_REPORTLAB:
        raise RuntimeError("reportlab is not installed; PDF generation is unavailable")

    case_id = payload.get("case_id", "")
    title = payload.get("title") or "Untitled case"
    site = payload.get("site") or {}
    typology = payload.get("typology") or {}
    subject_claim = payload.get("subject_claim") or {}
    checks = payload.get("checks") or []
    bundle = payload.get("evidence_bundle") or {}
    gaps = payload.get("declared_gaps") or []
    chain = payload.get("chain_of_custody") or {}

    story: List[Any] = []

    # ---- Title --------------------------------------------------------------
    story.append(Paragraph("Environmental Forensic Evidence Pack", _TITLE))
    story.append(Paragraph("Satellite × land cover × active-fire consistency check", _SUBTITLE))
    story.append(Spacer(1, 4 * mm))

    # ---- Case metadata -------------------------------------------------------
    story.append(Paragraph("Case metadata", _S))
    meta_rows = [
        ["Case ID", _xml(case_id)],
        ["Title", _xml(title)],
        ["Generated", _xml(payload.get("generated_at"))],
        ["Typology", _xml(typology.get("label"))],
        ["Site", f"{_xml(site.get('lat'))}, {_xml(site.get('lon'))}"],
        ["Site name", _xml(site.get("name"))],
        ["Search radius", f"{_xml(payload.get('radius_km'))} km"],
        ["Engine version", _xml(payload.get("engine_version"))],
    ]
    story.append(_kv_table(meta_rows))

    # ---- Subject claim & reference docs --------------------------------------
    story.append(Paragraph("Subject claim &amp; reference documents", _S))
    story.append(Paragraph(
        f"<b>Claim type:</b> {_xml(subject_claim.get('label'))} "
        f"({_xml(subject_claim.get('type'))})",
        _B,
    ))
    if subject_claim.get("text"):
        story.append(Paragraph(f"<b>Claim text:</b> {_xml(subject_claim['text'])}", _B))
    story.append(Paragraph(
        f"<b>Submitter note:</b> {_xml(subject_claim.get('submitter_note'))}",
        _SM,
    ))
    docs = payload.get("reference_documents") or []
    if docs:
        story.append(Paragraph("Reference documents (declared, not fetched):", _B))
        for doc in docs:
            url = doc.get("url") or ""
            if url:
                story.append(Paragraph(
                    f"• {_xml(doc.get('title'))} — "
                    f'<a href="{_xml(url)}" color="blue">{_xml(url[:60])}</a>',
                    _SM,
                ))
            else:
                story.append(Paragraph(f"• {_xml(doc.get('title'))}", _SM))
    else:
        story.append(Paragraph("No reference documents supplied.", _SM))

    # ---- Consistency matrix --------------------------------------------------
    story.append(Paragraph("Consistency matrix", _S))
    story.append(_consistency_matrix(checks))

    # ---- Evidence bundle -----------------------------------------------------
    story.append(Paragraph("Evidence bundle", _S))
    story.append(Paragraph(_bundle_summary(bundle), _B))
    for layer, label in (("landcover", "Land cover"), ("satellite", "Sentinel-2"), ("active_fires", "Active fires")):
        block = bundle.get(layer) or {}
        story.append(Paragraph(f"<b>{label}</b>", _B))
        if "error" in block:
            story.append(Paragraph(f"Unavailable: {_xml(block['error'])}", _SM))
        elif layer == "landcover":
            story.append(Paragraph(
                f"Dominant class: {_xml(block.get('dominant_label'))} "
                f"(fraction {block.get('dominant_fraction')}); source: {_xml(block.get('source'))}; "
                f"resolution: {_xml(block.get('resolution'))}.",
                _SM,
            ))
        elif layer == "satellite":
            story.append(Paragraph(
                f"NDVI {block.get('ndvi')} · NDMI {block.get('ndmi')} · NDWI {block.get('ndwi')} · "
                f"observation {block.get('observation_date')} · source {_xml(block.get('source'))}.",
                _SM,
            ))
        elif layer == "active_fires":
            story.append(Paragraph(
                f"{block.get('count', 0)} detection(s) within {block.get('radius_km')} km / "
                f"{block.get('days')} days · sensor {block.get('sensor')} · "
                f"source {_xml(block.get('source'))}.",
                _SM,
            ))
    ev_records = []
    for rec in (bundle.get("evidence_records") or []):
        ev_records.append(rec)
    # Evidence records are also at top-level chain_of_custody; prefer those.
    ev_table = _evidence_table((payload.get("chain_of_custody") or {}).get("evidence_records") or [])
    if ev_table:
        story.append(Paragraph("Typed evidence records", _S))
        story.append(ev_table)

    # ---- Declared gaps -------------------------------------------------------
    story.append(Paragraph("Declared data gaps", _S))
    if gaps:
        for gap in gaps:
            dataset = gap.get("dataset") or gap.get("type")
            story.append(Paragraph(
                f"• <b>{_xml(dataset)}</b> — {_xml(gap.get('reason'))}",
                _B,
            ))
    else:
        story.append(Paragraph("No declared data gaps.", _B))

    # ---- Chain of custody ----------------------------------------------------
    story.append(Paragraph("Chain of custody", _S))
    story.append(Paragraph(_xml(chain.get("note")), _SM))
    story.append(_chain_of_custody_table(chain.get("evidence_records") or []))

    # ---- Verdict & legal notes -----------------------------------------------
    story.append(Paragraph("Case verdict", _S))
    story.append(Paragraph(
        f"<b>{_xml(payload.get('case_verdict')).upper()}</b>",
        _B,
    ))
    story.append(Paragraph(
        f"<b>Verdict note:</b> {_xml(payload.get('verdict_note'))}",
        _B,
    ))
    story.append(Paragraph(
        f"<b>Legal note:</b> {_xml(payload.get('legal_note'))}",
        _SM,
    ))

    # ---- Methodology & disclaimer --------------------------------------------
    story.append(Paragraph("Methodology &amp; limitations", _S))
    story.append(Paragraph(
        f"<b>Honesty contract:</b> {_xml(payload.get('honesty_contract'))}",
        _B,
    ))
    story.append(Paragraph(
        f"<b>Disclaimer:</b> {_xml(payload.get('disclaimer'))}",
        _SM,
    ))

    buf = io.BytesIO()
    safe = "".join(c if c.isalnum() else "_" for c in str(title))[:40]
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=18 * mm,
        title=f"Talaix Forensic Evidence — {_xml(title)}",
        author="Talaix (real-data decision support)",
        subject="Environmental Forensic Evidence Pack",
    )
    doc._report_meta = {
        "generated": payload.get("generated_at", ""),
        "report_id": case_id,
        "auth_code": payload.get("authenticity", {}).get("code", ""),
    }
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
