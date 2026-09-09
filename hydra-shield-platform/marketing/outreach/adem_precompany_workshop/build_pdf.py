#!/usr/bin/env python3
"""Build ADEM_PreCompany_Workshop_Proposal.pdf (FR + DE + EN) from the
proposal_*.md files in this folder. Personal document — no Talaix branding."""
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (PageBreak, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

HERE = Path(__file__).resolve().parent
OUT = HERE / "ADEM_PreCompany_Workshop_Proposal.pdf"
SECTIONS = ["fr", "de", "en"]

H1 = ParagraphStyle("H1", fontName="Helvetica-Bold", fontSize=17, leading=21,
                    spaceAfter=4, textColor=colors.HexColor("#1a3a5c"))
H2 = ParagraphStyle("H2", fontName="Helvetica-Bold", fontSize=12.5, leading=16,
                    spaceBefore=10, spaceAfter=5,
                    textColor=colors.HexColor("#1a3a5c"))
BODY = ParagraphStyle("BODY", fontName="Helvetica", fontSize=10, leading=14,
                      spaceAfter=5)
CENTER = ParagraphStyle("CENTER", parent=BODY, alignment=TA_CENTER)
BULLET = ParagraphStyle("BULLET", parent=BODY, leftIndent=14, bulletIndent=4,
                        spaceAfter=3)
CELL = ParagraphStyle("CELL", parent=BODY, fontSize=9.5, leading=12,
                      spaceAfter=0)


def inline(text: str) -> str:
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\w)\*(.+?)\*(?!\w)", r"<i>\1</i>", text)
    return text.replace("`", "")


def md_to_flowables(md: str):
    flows, lines, i = [], md.splitlines(), 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip() or line.strip() == "---":
            i += 1
            continue
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(set(c) <= set("-: ") for c in cells):
                    style = CELL if rows else ParagraphStyle(
                        "TH", parent=CELL, textColor=colors.white,
                        fontName="Helvetica-Bold")
                    rows.append([Paragraph(inline(c), style) for c in cells])
                i += 1
            t = Table(rows, colWidths=[11 * cm, 5 * cm])
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3a5c")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9db3c8")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            flows.extend([Spacer(1, 4), t, Spacer(1, 6)])
            continue
        if line.startswith("## "):
            flows.append(Paragraph(inline(line[3:]), H2))
        elif line.startswith("# "):
            flows.append(Paragraph(inline(line[2:]), H1))
        elif line.lstrip().startswith("- "):
            flows.append(Paragraph(inline(line.lstrip()[2:]), BULLET,
                                   bulletText="\u2022"))
        else:
            flows.append(Paragraph(inline(line), BODY))
        i += 1
    return flows


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.grey)
    canvas.drawCentredString(A4[0] / 2, 1.1 * cm,
                             f"From Experience to Enterprise — proposal to ADEM — page {doc.page}")
    canvas.restoreState()


def main():
    story = []
    for n, lang in enumerate(SECTIONS):
        if n:
            story.append(PageBreak())
        md = (HERE / f"proposal_{lang}.md").read_text(encoding="utf-8")
        story.extend(md_to_flowables(md))
    doc = SimpleDocTemplate(str(OUT), pagesize=A4, leftMargin=2 * cm,
                            rightMargin=2 * cm, topMargin=1.8 * cm,
                            bottomMargin=2 * cm,
                            title="From Experience to Enterprise — ADEM proposal",
                            author="Motaz Omarien")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print(f"built {OUT.name}: {OUT.stat().st_size/1024:.0f} KB")


if __name__ == "__main__":
    main()
