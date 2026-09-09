#!/usr/bin/env python3
"""Render a Markdown file to a clean A4 PDF (reportlab).

Usage: python scripts/md_to_pdf.py <input.md> [-o output.pdf] [--title T] [--footer F]
Supports: # / ## headings, **bold**, *italic*, `-` bullets, `1.` numbered
items, `---` separators and pipe tables. Latin-1 text (accents, €, «») is safe.
"""
import argparse
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

NAVY = colors.HexColor("#1a3a5c")
H1 = ParagraphStyle("H1", fontName="Helvetica-Bold", fontSize=16, leading=20,
                    spaceBefore=2, spaceAfter=6, textColor=NAVY)
H2 = ParagraphStyle("H2", fontName="Helvetica-Bold", fontSize=12.5, leading=16,
                    spaceBefore=10, spaceAfter=5, textColor=NAVY)
BODY = ParagraphStyle("BODY", fontName="Helvetica", fontSize=10, leading=14,
                      spaceAfter=5)
BULLET = ParagraphStyle("BULLET", parent=BODY, leftIndent=14, bulletIndent=4,
                        spaceAfter=3)
CELL = ParagraphStyle("CELL", parent=BODY, fontSize=9.5, leading=12,
                      spaceAfter=0)
TH = ParagraphStyle("TH", parent=CELL, textColor=colors.white,
                    fontName="Helvetica-Bold")


def inline(text: str) -> str:
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\w)\*(.+?)\*(?!\w)", r"<i>\1</i>", text)
    return text.replace("`", "")


def md_to_flowables(md: str):
    flows, lines, i = [], md.splitlines(), 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip():
            i += 1
            continue
        if line.strip() == "---":
            flows.append(Spacer(1, 6))
            i += 1
            continue
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(set(c) <= set("-: ") for c in cells):
                    style = TH if not rows else CELL
                    rows.append([Paragraph(inline(c), style) for c in cells])
                i += 1
            width = A4[0] - 4 * cm
            t = Table(rows, colWidths=[width / len(rows[0])] * len(rows[0]))
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9db3c8")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            flows.extend([Spacer(1, 4), t, Spacer(1, 6)])
            continue
        stripped = line.lstrip()
        if stripped.startswith("## "):
            flows.append(Paragraph(inline(stripped[3:]), H2))
        elif stripped.startswith("# "):
            flows.append(Paragraph(inline(stripped[2:]), H1))
        elif stripped.startswith("- "):
            flows.append(Paragraph(inline(stripped[2:]), BULLET,
                                   bulletText="\u2022"))
        elif re.match(r"^\d+\.\s", stripped):
            num, rest = stripped.split(".", 1)
            flows.append(Paragraph(inline(rest.strip()), BULLET,
                                   bulletText=f"{num}."))
        else:
            flows.append(Paragraph(inline(stripped), BODY))
        i += 1
    return flows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("-o", "--output", type=Path)
    ap.add_argument("--title", default=None)
    ap.add_argument("--footer", default=None)
    args = ap.parse_args()
    out = args.output or args.input.with_suffix(".pdf")
    title = args.title or args.input.stem
    footer_text = args.footer or title

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.grey)
        canvas.drawCentredString(A4[0] / 2, 1.1 * cm,
                                 f"{footer_text} — page {doc.page}")
        canvas.restoreState()

    md = args.input.read_text(encoding="utf-8")
    doc = SimpleDocTemplate(str(out), pagesize=A4, leftMargin=2 * cm,
                            rightMargin=2 * cm, topMargin=1.8 * cm,
                            bottomMargin=2 * cm, title=title)
    doc.build(md_to_flowables(md), onFirstPage=footer, onLaterPages=footer)
    print(f"built {out}: {out.stat().st_size/1024:.0f} KB")


if __name__ == "__main__":
    main()
