#!/usr/bin/env python3
"""Build the Talaix pitch deck PDF (16:9, reportlab).

Usage:
    .venv/bin/python scripts/build_deeptechxl_deck.py                 # generic pre-seed deck
    .venv/bin/python scripts/build_deeptechxl_deck.py --fund deeptechxl  # DeepTechXL-branded deck

Output: marketing/outreach/talaix_preseed_deck.pdf (generic)
        marketing/outreach/deeptechxl_pitch_deck.pdf (--fund deeptechxl)
"""

import argparse
from pathlib import Path

from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
LOGO = ROOT.parent / "pic" / "LogoWithText.png"
OUT = ROOT / "marketing" / "outreach" / "deeptechxl_pitch_deck.pdf"

# Fund-facing strings, swapped by --fund in main(). Defaults reproduce the
# DeepTechXL-branded deck; "generic" produces the webform/shareable version.
PROFILE = {
    "fund": "deeptechxl",
    "footer": "Talaix — Confidential · Prepared for DeepTechXL · September 2026",
    "cover": "Prepared for DeepTechXL  ·  Eindhoven  ·  September 2026",
    "pdf_title": "Talaix — Pitch Deck for DeepTechXL (September 2026)",
    "funding_fit": "<b>€850K pre-seed</b> (equity or convertible) — inside DeepTechXL's €100K–€2M "
                   "initial-ticket range; lead or co-lead, syndication welcome",
    "team_eco": "<b>Advisory &amp; ecosystem:</b> targeting the High Tech Campus / TU/e network for scientific "
                "validation and first municipal pilots; open to DeepTechXL introductions across the Brabant "
                "ecosystem (BOM, The Gate, HighTechXL) for pilot sites and follow-on syndication.",
}

GENERIC_PROFILE = {
    "fund": "generic",
    "footer": "Talaix — Confidential · Pre-seed · September 2026",
    "cover": "Pre-seed deck  ·  September 2026",
    "pdf_title": "Talaix — Pre-seed Pitch Deck (September 2026)",
    "funding_fit": "<b>€850K pre-seed</b> (equity or convertible) — lead or co-lead, syndication welcome",
    "team_eco": "<b>Advisory &amp; ecosystem:</b> targeting the High Tech Campus / TU/e network for scientific "
                "validation and first municipal pilots; open to investor introductions across the Brabant "
                "ecosystem (BOM, The Gate, HighTechXL) for pilot sites and follow-on syndication.",
}

GENERIC_OUT = ROOT / "marketing" / "outreach" / "talaix_preseed_deck.pdf"

PAGE_W, PAGE_H = 960.0, 540.0  # 16:9
MARGIN = 54.0

NAVY = HexColor("#17253B")
TEAL = HexColor("#529DA7")
TEAL_DARK = HexColor("#3E7E87")
INK = HexColor("#2A3A4A")
MUTED = HexColor("#5E7183")
FAINT = HexColor("#8CA0B0")
ROW_ALT = HexColor("#F1F6F7")
LINE = HexColor("#CFDDE0")
PANEL = HexColor("#EEF4F5")

F = "Helvetica"
FB = "Helvetica-Bold"
FO = "Helvetica-Oblique"

BODY = ParagraphStyle("body", fontName=F, fontSize=11.5, leading=16.5, textColor=INK)
BODY_SM = ParagraphStyle("body_sm", fontName=F, fontSize=10.5, leading=14.5, textColor=INK)
BULLET = ParagraphStyle("bullet", parent=BODY, leftIndent=14, bulletIndent=2, spaceAfter=5)
BULLET_SM = ParagraphStyle("bullet_sm", parent=BODY_SM, leftIndent=14, bulletIndent=2, spaceAfter=4)
PANEL_TXT = ParagraphStyle("panel", fontName=F, fontSize=10.5, leading=14, textColor=INK)
TBL_CELL = ParagraphStyle("tcell", fontName=F, fontSize=9.5, leading=12.5, textColor=INK)
TBL_HEAD = ParagraphStyle("thead", fontName=FB, fontSize=9.5, leading=12, textColor=white)
TITLE_ST = ParagraphStyle("title_white", fontName=FB, fontSize=27, leading=33,
                          textColor=white, alignment=TA_CENTER)
SUB_ST = ParagraphStyle("sub_white", fontName=F, fontSize=12.5, leading=17,
                        textColor=HexColor("#D8E4E8"), alignment=TA_CENTER)


# ---------------------------------------------------------------------------
# layout helpers
# ---------------------------------------------------------------------------

def footer(c, num, total):
    c.setFont(F, 7.5)
    c.setFillColor(FAINT)
    c.drawString(MARGIN, 26, PROFILE["footer"])
    c.drawRightString(PAGE_W - MARGIN, 26, f"{num} / {total}")
    c.setStrokeColor(LINE)
    c.setLineWidth(0.6)
    c.line(MARGIN, 38, PAGE_W - MARGIN, 38)


def header(c, kicker, title):
    y = PAGE_H - MARGIN
    c.setFont(FB, 9.5)
    c.setFillColor(TEAL_DARK)
    c.drawString(MARGIN, y, kicker.upper())
    c.setFont(FB, 24)
    c.setFillColor(NAVY)
    c.drawString(MARGIN, y - 30, title)
    c.setStrokeColor(TEAL)
    c.setLineWidth(2.2)
    c.line(MARGIN, y - 44, MARGIN + 64, y - 44)
    return y - 62


def para(c, text, style, x, y, width):
    p = Paragraph(text, style)
    w, h = p.wrap(width, PAGE_H)
    p.drawOn(c, x, y - h)
    return y - h


def bullets(c, items, x, y, width, style=BULLET, gap=0):
    for it in items:
        p = Paragraph(it, style, bulletText="•")
        w, h = p.wrap(width, PAGE_H)
        p.drawOn(c, x, y - h)
        y -= h + gap
    return y


def panel(c, x, y, width, pad, texts, style=PANEL_TXT, fill=PANEL):
    """Draw a filled rounded panel containing stacked paragraphs; returns bottom y."""
    rendered = []
    total_h = pad * 2
    for t in texts:
        p = Paragraph(t, style)
        w, h = p.wrap(width - pad * 2, PAGE_H)
        rendered.append((p, h))
        total_h += h + 4
    total_h -= 4
    c.setFillColor(fill)
    c.roundRect(x, y - total_h, width, total_h, 8, stroke=0, fill=1)
    ty = y - pad
    for p, h in rendered:
        p.drawOn(c, x + pad, ty - h)
        ty -= h + 4
    return y - total_h


def tbl(c, rows, col_widths, x, y, header_row=True):
    data = []
    for i, row in enumerate(rows):
        st = TBL_HEAD if (header_row and i == 0) else TBL_CELL
        data.append([cell if not isinstance(cell, str) else Paragraph(cell, st) for cell in row])
    t = Table(data, colWidths=col_widths)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, LINE),
    ]
    if header_row:
        style += [("BACKGROUND", (0, 0), (-1, 0), NAVY),
                  ("LINEBELOW", (0, 0), (-1, 0), 0, NAVY)]
        for i in range(1, len(rows)):
            if i % 2 == 0:
                style.append(("BACKGROUND", (0, i), (-1, i), ROW_ALT))
    t.setStyle(TableStyle(style))
    w, h = t.wrapOn(c, sum(col_widths), PAGE_H)
    t.drawOn(c, x, y - h)
    return y - h


def stat_boxes(c, boxes, x, y, width, height=66):
    """Row of stat boxes: [(big, small), ...]."""
    gap = 12
    bw = (width - gap * (len(boxes) - 1)) / len(boxes)
    for i, (big, small) in enumerate(boxes):
        bx = x + i * (bw + gap)
        c.setFillColor(PANEL)
        c.roundRect(bx, y - height, bw, height, 8, stroke=0, fill=1)
        c.setFillColor(NAVY)
        c.setFont(FB, 16)
        c.drawCentredString(bx + bw / 2, y - 26, big)
        p = Paragraph(small, ParagraphStyle("sb", fontName=F, fontSize=8.3,
                                            leading=10, textColor=MUTED, alignment=TA_CENTER))
        w, h = p.wrap(bw - 14, height - 34)
        p.drawOn(c, bx + 7, y - 32 - h)
    return y - height


def phase_strip(c, phases, x, y, width, height=74):
    """Horizontal roadmap: [(phase, text), ...] navy boxes."""
    gap = 10
    bw = (width - gap * (len(phases) - 1)) / len(phases)
    for i, (phase, text) in enumerate(phases):
        bx = x + i * (bw + gap)
        c.setFillColor(NAVY if i % 2 == 0 else TEAL_DARK)
        c.roundRect(bx, y - height, bw, height, 8, stroke=0, fill=1)
        c.setFillColor(white)
        c.setFont(FB, 10.5)
        c.drawString(bx + 10, y - 20, phase)
        p = Paragraph(text, ParagraphStyle("ph", fontName=F, fontSize=8.4, leading=10.8,
                                           textColor=HexColor("#E3EDF0")))
        w, h = p.wrap(bw - 20, height - 30)
        p.drawOn(c, bx + 10, y - 26 - h)
    return y - height


# ---------------------------------------------------------------------------
# slides
# ---------------------------------------------------------------------------

def slide_title(c, num, total):
    c.setFillColor(NAVY)
    c.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
    img = ImageReader(str(LOGO))
    iw, ih = 170, 121
    card_w, card_h = iw + 48, ih + 32
    card_top = PAGE_H - 58
    c.setFillColor(white)
    c.roundRect(PAGE_W / 2 - card_w / 2, card_top - card_h, card_w, card_h, 14, stroke=0, fill=1)
    c.drawImage(img, PAGE_W / 2 - iw / 2, card_top - card_h + 16, iw, ih,
                preserveAspectRatio=True, mask="auto")
    y = card_top - card_h - 34
    p = Paragraph("Climate-risk compliance evidence,<br/>built on Earth Observation and AI", TITLE_ST)
    w, h = p.wrap(PAGE_W - 160, 120)
    p.drawOn(c, 80, y - h)
    y = y - h - 16
    p = Paragraph("The physical climate-risk evidence layer for CSRD / ESRS E1, EU Taxonomy DNSH and EUDR —<br/>"
                  "audit-ready, transparently priced, and honest about uncertainty.", SUB_ST)
    w, h = p.wrap(PAGE_W - 220, 80)
    p.drawOn(c, 110, y - h)
    c.setStrokeColor(TEAL)
    c.setLineWidth(1.2)
    c.line(100, 92, PAGE_W - 100, 92)
    c.setFillColor(HexColor("#C6D5DA"))
    c.setFont(F, 10.5)
    c.drawCentredString(PAGE_W / 2, 72, PROFILE["cover"])
    c.setFont(F, 9.5)
    c.drawCentredString(PAGE_W / 2, 55, "Motaz Omarien, Founder  ·  motaz3d@gmail.com  ·  +352 661811680  ·  talaix.com")
    c.setFont(FO, 8.5)
    c.drawCentredString(PAGE_W / 2, 28, "Confidential — for evaluation purposes only")


def slide_problem(c, num, total):
    y = header(c, "The problem", "Mandatory climate disclosure meets a missing evidence layer")
    col_w = (PAGE_W - 2 * MARGIN - 30) / 2
    x2 = MARGIN + col_w + 30

    c.setFont(FB, 12.5); c.setFillColor(NAVY)
    c.drawString(MARGIN, y, "Physical climate risk is intensifying")
    ty = para(c, "Documented events in our own loss registry illustrate the scale: the July 2021 Western "
                 "European floods, the 2002 Elbe/Danube floods and the 2018 Attica wildfires — multi-billion-euro "
                 "events hitting assets that were never screened for hazard exposure.",
              BODY_SM, MARGIN, y - 18, col_w)
    c.drawString(x2, y, "Disclosure is now law, on a fixed calendar")
    ty2 = para(c, "CSRD/ESRS E1, EU Taxonomy DNSH and EUDR force companies to disclose <b>site-level physical "
                  "climate-risk evidence</b> — acute and chronic hazards at the coordinates of material assets, "
                  "with stated evidence status and limitations.",
               BODY_SM, x2, y - 18, col_w)
    y2 = min(ty, ty2) - 16

    y2 = stat_boxes(c, [
        ("FY2024 →", "CSRD Wave 1 reports already published — the calendar is running"),
        ("30 Dec 2025", "EUDR in force for large operators &amp; traders"),
        ("~12–15K", "EU companies in post-Omnibus CSRD scope (est.)"),
        ("5–7 figures/yr", "typical contract at specialist climate-risk vendors"),
    ], MARGIN, y2, PAGE_W - 2 * MARGIN)
    y2 -= 18

    y2 = panel(c, MARGIN, y2, PAGE_W - 2 * MARGIN, 12, [
        "<b>The gap:</b> ESG/CSRD reporting suites (Workiva, Position Green, SAP, IBM…) manage workflow "
        "and carbon accounting — <b>none generates physical climate-risk evidence</b>. The specialists who do "
        "(Jupiter, Climate X, Mitiga, XDI…) sell opaque five-to-seven-figure annual enterprise contracts. "
        "Mid-market companies and their auditors are left with consultants or nothing.",
    ])
    y2 -= 14
    c.setFont(FB, 11.5); c.setFillColor(NAVY)
    c.drawString(MARGIN, y2, "What the market is missing")
    bullets(c, [
        "<b>Audit-ready evidence</b> — sourced, reproducible, with an honest evidence status per datapoint · "
        "<b>Transparent pricing</b> — per-report and per-month, not six-figure contracts · "
        "<b>Global coverage</b> — EU companies today; non-EU exporters (EUDR, CSRD Wave 4) tomorrow",
    ], MARGIN, y2 - 17, PAGE_W - 2 * MARGIN - 20)
    footer(c, num, total)


def slide_solution(c, num, total):
    y = header(c, "The solution — value proposition", "Talaix: site coordinates in, audit-ready evidence out")
    y = para(c, "Talaix converts Earth Observation, environmental modelling and documented loss data into "
                "<b>physical climate-risk evidence packs</b> that plug directly into CSRD/ESRS E1, EU Taxonomy "
                "DNSH and EUDR workflows.", BODY, MARGIN, y, PAGE_W - 2 * MARGIN)
    y -= 16
    steps = [("1 · Locate", "Customer provides site coordinates of material assets"),
             ("2 · Screen", "Multi-hazard engine screens 8 hazards + exposure at those coordinates"),
             ("3 · Evidence", "Each datapoint tagged OBSERVED → ESTIMATED → FRAMEWORK → UNKNOWN"),
             ("4 · Report", "Audit-ready pack: ESRS E1 mapping + XBRL, documented losses, limitations")]
    y = phase_strip(c, steps, MARGIN, y, PAGE_W - 2 * MARGIN, height=70)
    y -= 18

    col_w = (PAGE_W - 2 * MARGIN - 30) / 2
    c.setFont(FB, 12); c.setFillColor(NAVY)
    c.drawString(MARGIN, y, "Why customers buy")
    bullets(c, [
        "<b>The budget already exists</b> — compliance spend is mandatory and deadline-driven, not discretionary",
        "<b>Price transparency as a wedge</b> — €19–39 per report, €49–249/month tiers, published on the website",
        "<b>Near-zero delivery cost</b> — automated engine, no consultants; marginal cost per customer ≈ 0",
        "<b>Self-serve funnel, live today</b> — free CSRD scope check → €19–39 sample pack on the customer's own "
        "sites → €490 pilot → subscription",
    ], MARGIN, y - 18, col_w, BULLET_SM)
    c.drawString(MARGIN + col_w + 30, y, "The trust anchor")
    panel(c, MARGIN + col_w + 30, y - 18, col_w, 10, [
        "<b>Honesty contract:</b> \"unavailable is stated, never filled in.\" Every figure carries its source, "
        "method, reference period and evidence class. The analytical engine is open-source "
        "(<b>tore</b>, EUPL-1.2) with a public source registry — verifiable by any auditor, not a black box.",
    ])
    stat_boxes(c, [
        ("€19", "entry price — evidence on the customer's own sites"),
        ("≈ €0", "marginal cost per generated report"),
        ("8", "hazards screened per evidence pack"),
        ("100%", "of outputs carry source + evidence class"),
    ], MARGIN, 108, PAGE_W - 2 * MARGIN)
    footer(c, num, total)


def slide_technology(c, num, total):
    y = header(c, "Technology", "Deep-tech core: EO + environmental modelling + compliance rules-as-data")
    col_w = (PAGE_W - 2 * MARGIN - 24) / 3
    cols = [
        ("Earth Observation &amp; data", [
            "Copernicus Sentinel-1/2/3, EFFIS, C3S climate services",
            "NASA FIRMS observed-fire history layer",
            "OSM/ohsome exposure (buildings, critical facilities, infrastructure)",
            "NL BAG cadastre — real building floor areas; Eurostat construction-cost calibration",
        ]),
        ("TX Engine — multi-hazard core", [
            "8 hazards: wildfire, flood, drought, heat, wind, coastal, cyclone, earthquake",
            "FWI, fire-spread, ignition and smoke modelling; soil-to-fuel moisture transfer",
            "Exposure &amp; economic screening with declared-assumption discipline",
            "Documented-loss registry (officially sourced figures only)",
        ]),
        ("CsrdTX — compliance layer", [
            "ESRS E1 datapoint mapping as versioned rules-as-data (5 JSON registries)",
            "XBRL output + /api/v2/csrd (shipped 2026-09-05)",
            "Scenario / time-horizon fields, E1-9 financial-effects context",
            "Evidence classes + public source registry on every output",
        ]),
    ]
    top = y - 6
    bottoms = []
    for i, (title, items) in enumerate(cols):
        bx = MARGIN + i * (col_w + 12)
        c.setFillColor(TEAL_DARK if i == 1 else NAVY)
        c.roundRect(bx, top - 26, col_w, 26, 6, stroke=0, fill=1)
        c.setFillColor(white)
        tp = Paragraph(title, ParagraphStyle("ct", fontName=FB, fontSize=10.5, leading=13,
                                             textColor=white, alignment=TA_CENTER))
        w, h = tp.wrap(col_w - 10, 24)
        tp.drawOn(c, bx + 5, top - 18.5)
        by = bullets(c, items, bx + 2, top - 36, col_w - 6, BULLET_SM)
        bottoms.append(by)
    y = min(bottoms) - 14
    panel(c, MARGIN, y, PAGE_W - 2 * MARGIN, 10, [
        "<b>Delivery surface:</b> Flask API v2 (live), PDF report generation, Python &amp; JS SDKs, QGIS plugin, "
        "self-serve web funnel with Stripe billing. Engine mirrored open-source at <b>tore</b> (EUPL-1.2).",
        "<b>Quality bar:</b> 1,670 automated tests across 104 test files; benchmark suite and validation "
        "framework against documented events; screening-level labels until validation completes.",
        "<b>Ground truth (Stage 2):</b> a soil- and fuel-moisture sensor testbed is planned for field "
        "validation — bridging the EO models to measured ground truth with hardware in the loop.",
    ])
    footer(c, num, total)


def slide_stage(c, num, total):
    y = header(c, "Development stage", "Working platform, pre-revenue, pilot-ready")
    y = stat_boxes(c, [
        ("8", "climate hazards modelled by the TX engine"),
        ("1,670", "automated tests across 104 test files"),
        ("2026-09-05", "CsrdTX compliance engine + XBRL + API shipped"),
        ("Live", "pricing + self-serve funnel + Stripe billing"),
    ], MARGIN, y - 4, PAGE_W - 2 * MARGIN)
    y -= 24
    col_w = (PAGE_W - 2 * MARGIN - 30) / 2
    c.setFont(FB, 12); c.setFillColor(NAVY)
    c.drawString(MARGIN, y, "What exists today (not slideware)")
    y1 = bullets(c, [
        "Multi-hazard engine, API v2, PDF evidence reports, SDKs, QGIS plugin — all operational",
        "Compliance products: ESRS E1 evidence brief + published case study, scope checker, pricing page",
        "Open-source engine mirror (<b>tore</b>, EUPL-1.2) published for the NLnet Restack application",
        "Sales funnel live; first-customer motion ready (scope check → sample → pilot → subscription)",
    ], MARGIN, y - 18, col_w, BULLET_SM)
    c.drawString(MARGIN + col_w + 30, y, "Honest status")
    y2 = bullets(c, [
        "<b>Pre-revenue</b> — zero paying customers today; pilot programme opens the first wave",
        "Screening-level labels until model validation vs documented events completes",
        "Company formation: Dutch BV at High Tech Campus, Eindhoven — planned with this round "
        "(see IP &amp; funding slides)",
        "Founder-built to date — this round funds the first team (see Team)",
    ], MARGIN + col_w + 30, y - 18, col_w, BULLET_SM)
    y = min(y1, y2) - 22
    c.setFont(FB, 12); c.setFillColor(NAVY)
    c.drawString(MARGIN, y, "Roadmap to seed")
    phase_strip(c, [
        ("Q4 2026", "Dutch BV at High Tech Campus; IP assigned (inbreng in natura); trademark filed; WBSO active"),
        ("H1 2027", "Model validation vs documented events; sensor testbed live; first paying pilots"),
        ("H2 2027", "Pilots → subscriptions; first GRC-suite integration; EUDR exporter wave"),
        ("2028", "Seed round; EIC Accelerator application (€2.5M grant + equity) with pilot evidence"),
    ], MARGIN, y - 20, PAGE_W - 2 * MARGIN, height=66)
    footer(c, num, total)


def slide_market(c, num, total):
    y = header(c, "Market opportunity", "A regulated-demand market with a published calendar")
    rows = [
        ["Regulation", "Population", "First reports", "Status"],
        ["CSRD Wave 1 (large PIEs)", "largest EU companies", "FY2024 (published 2025)", "In force"],
        ["CSRD Wave 2 (other large)", "~12,000–15,000 post-Omnibus (est.)", "FY2027 (published 2028)",
         "In force; +2y delay"],
        ["CSRD Wave 4 (non-EU groups)", "non-EU >€150M EU turnover", "FY2028 (published 2029)", "In force"],
        ["EUDR operators &amp; traders", "EU + global commodity exporters", "30 Dec 2025 / 30 Jun 2026",
         "In force now"],
        ["EU Taxonomy DNSH + CSDDD", "large undertakings", "2027–2028", "In force"],
    ]
    y = tbl(c, rows, [230, 250, 190, 182], MARGIN, y)
    y -= 16
    col_w = (PAGE_W - 2 * MARGIN - 30) / 2
    c.setFont(FB, 12); c.setFillColor(NAVY)
    c.drawString(MARGIN, y, "Bottom-up sizing (our honesty rules apply)")
    bullets(c, [
        "<b>Beachhead:</b> EU mid-market companies in CSRD scope that cannot access enterprise vendors — "
        "unserved at transparent price points",
        "<b>Least-contested niche:</b> non-EU exporters (EUDR geolocation screening, CSRD Wave 4) — "
        "regulation in force, evidence is satellite-native",
        "<b>Channel multiplier:</b> 17 ESG/CSRD suites need a physical-risk evidence layer — "
        "integration, not competition",
    ], MARGIN, y - 18, col_w, BULLET_SM)
    c.drawString(MARGIN + col_w + 30, y, "Demand validation")
    bullets(c, [
        "Incumbents are buying this layer: MSCI acquired First Street (~$120M); ISS STOXX acquired Sust Global; "
        "Moody's acquired RMS ($2B) — physical-risk evidence is a must-have",
        "Consolidation at the top leaves the mid-market open — our entry point",
        "Post-Omnibus scope figures are estimates and presented as such (claims discipline is our brand)",
    ], MARGIN + col_w + 30, y - 18, col_w, BULLET_SM)
    footer(c, num, total)


def slide_business_model(c, num, total):
    y = header(c, "Business model", "Self-serve SaaS + evidence packs + partner API")
    rows = [
        ["Product", "Price (published)", "Buyer / motion"],
        ["Decision report (per site)", "€19 one-time", "Self-serve sample on customer's own sites"],
        ["Scientific report (per site)", "€39 one-time", "Deeper evidence pack for auditors"],
        ["Professional", "€49 / month (€490 / yr)", "Sustainability &amp; risk officers"],
        ["Business + seats", "€249 / month + €25 / seat", "Multi-site companies, consultancies"],
        ["Pilot programme", "€490 fixed", "3-month structured pilot → publishable case study"],
        ["Partner API (planned)", "usage-based", "GRC suites &amp; auditors embedding the evidence layer"],
    ]
    y = tbl(c, rows, [250, 200, 402], MARGIN, y)
    y -= 16
    col_w = (PAGE_W - 2 * MARGIN - 30) / 2
    y0 = y
    panel(c, MARGIN, y0, col_w, 10, [
        "<b>Why this converts:</b> the trigger is a legal deadline, the entry price is €19, and every step is "
        "self-serve. No sales team needed for the beachhead — outreach plus the free scope checker drives the "
        "funnel.",
    ])
    panel(c, MARGIN + col_w + 30, y0, col_w, 10, [
        "<b>Why this scales:</b> automated engine → marginal cost per report ≈ €0; the same evidence is reused "
        "by insurers (EIOPA/Solvency II) and banks (EBA Pillar 3 ESG) — expansion without new product lines.",
    ])
    footer(c, num, total)


def slide_competition(c, num, total):
    y = header(c, "Competition", "The gap: cheap, auditable, standalone physical-risk evidence")
    rows = [
        ["Category", "Players", "Physical-risk evidence?", "Gap vs Talaix"],
        ["ESG/CSRD suites (17 profiled)", "Workiva, Position Green, IBM Envizi, SAP, Greenly, osapiens…",
         "No (workflow + carbon)", "Integration targets, not competitors"],
        ["Climate-risk specialists (16 profiled)", "Jupiter, Climate X, Mitiga, repath, XDI, First Street/MSCI…",
         "Yes — bundled, opaque", "5–7-figure contracts; no list prices; SME unserved"],
        ["Open research models", "CLIMADA (ETH Zurich)", "Yes — research-grade",
         "No compliance workflow, audit trail, or API product"],
        ["<b>Talaix</b>", "—", "Yes — standalone packs",
         "€19–249 transparent pricing, evidence classes, open engine"],
    ]
    y = tbl(c, rows, [185, 290, 180, 197], MARGIN, y)
    y -= 16
    c.setFont(FB, 12); c.setFillColor(NAVY)
    c.drawString(MARGIN, y, "Defensibility &amp; the honest risk")
    bullets(c, [
        "<b>Moat:</b> evidence-class discipline + public source registry + open engine = the trust anchor auditors "
        "respond to; curated loss/benchmark registries accumulate as proprietary data assets",
        "<b>Stated risk (we name it):</b> Cervest collapsed in 2024 selling cheap discretionary analytics. "
        "Our difference: mandatory-deadline pull (CSRD/EUDR) and near-zero delivery cost — engine, not consultants",
    ], MARGIN, y - 18, PAGE_W - 2 * MARGIN - 20, BULLET_SM)
    footer(c, num, total)


def slide_ip(c, num, total):
    y = header(c, "Intellectual property", "Open-core IP strategy, clean chain of title into the Dutch BV")
    col_w = (PAGE_W - 2 * MARGIN - 30) / 2
    c.setFont(FB, 12); c.setFillColor(NAVY)
    c.drawString(MARGIN, y, "Chain of title at incorporation")
    y1 = bullets(c, [
        "<b>Contribution in kind (inbreng in natura):</b> the full pre-incorporation IP portfolio — code, models, "
        "knowledge registries, documentation, brand, domains — contributed to the BV in exchange for founder "
        "shares; described and valued in the notarial deed (flex-BV: no auditor required)",
        "<b>Tax-clean &amp; VC-standard:</b> no immediate income-tax charge on a genuine contribution in kind, "
        "supported by a contemporaneous valuation memo; no licence/terbeschikking construction",
        "<b>Trademark:</b> \"Talaix\" to be filed at BOIP/EUIPO (classes 9 &amp; 42) at incorporation, "
        "held by the BV",
        "<b>Contributors &amp; team:</b> CLA to govern the open-source repo (company keeps enforce/relicence "
        "rights); every hire signs explicit IP assignment",
    ], MARGIN, y - 18, col_w, BULLET_SM)
    c.drawString(MARGIN + col_w + 30, y, "Open core — why the moat holds")
    y2 = bullets(c, [
        "<b>Open (tore, EUPL-1.2):</b> the analytical engine — auditor trust anchor, public-funding eligibility "
        "(NLnet Restack filed); interoperable copyleft does not contaminate the API-calling proprietary layer "
        "and blocks competitors from enclosing the engine",
        "<b>Closed (the BV):</b> web platform, accounts &amp; billing, compliance knowledge registries "
        "(CSRD rules, loss registry, benchmarks, cascading graph), operational pipeline, brand",
        "<b>Precedent:</b> GitLab, Elastic, Confluent, QuestDB — venture-scale on open cores",
        "<b>NL IP economics:</b> WBSO R&amp;D wage-tax credit (32% first bracket) filed at incorporation → "
        "unlocks the Innovation Box (9% vs 25% CIT) on qualifying IP profits",
        "<b>Patent assessment</b> planned for the soil-to-fuel moisture-transfer methods during field validation",
    ], MARGIN + col_w + 30, y - 18, col_w, BULLET_SM)
    y = min(y1, y2) - 12
    panel(c, MARGIN, y, PAGE_W - 2 * MARGIN, 10, [
        "<b>What an investor gets:</b> a BV holding the brand, the commercial platform, the compliance data "
        "assets and the customer relationships — with the open engine as a credibility asset, not a leakage "
        "risk (EUPL-1.2 copyleft keeps commercial forks honest).",
    ])
    footer(c, num, total)


def slide_team(c, num, total):
    y = header(c, "Team", "Founder-led, building the Eindhoven core team")
    col_w = (PAGE_W - 2 * MARGIN - 30) / 2
    y0 = y
    y1 = panel(c, MARGIN, y0, col_w, 12, [
        "<b>Motaz Omarien — Founder</b><br/>Designed and built the entire platform single-handedly: the "
        "multi-hazard TX engine, EO ingestion, the CsrdTX compliance layer (rules-as-data + XBRL), API v2, "
        "billing and the self-serve funnel — 1,670 tests of engineering depth, plus the market study and "
        "compliance strategy behind the positioning. Prepared to relocate and incorporate in Eindhoven.",
    ])
    c.setFont(FB, 12); c.setFillColor(NAVY)
    c.drawString(MARGIN + col_w + 30, y0 - 4, "Hiring plan for this round (2–3 FTE)")
    y2b = bullets(c, [
        "<b>Climate/ML validation scientist</b> — model validation vs documented events (Eindhoven/TU/e pool)",
        "<b>Geospatial software engineer</b> — EO pipeline depth, performance, partner API",
        "<b>Commercial &amp; pilot lead</b> — pilot conversions, GRC-suite partnerships, EUDR exporter outreach",
    ], MARGIN + col_w + 30, y0 - 24, col_w, BULLET_SM)
    y2 = min(y1, y2b) - 26
    panel(c, MARGIN, y2, PAGE_W - 2 * MARGIN, 10, [PROFILE["team_eco"]])
    footer(c, num, total)


def slide_funding(c, num, total):
    y = header(c, "Funding requirements", "Raising €850K pre-seed — 24 months to seed-ready")
    col_w = (PAGE_W - 2 * MARGIN - 30) / 2
    c.setFont(FB, 12); c.setFillColor(NAVY)
    c.drawString(MARGIN, y, "The ask")
    y1 = bullets(c, [
        PROFILE["funding_fit"],
        "24 months of runway at a lean 3–4 FTE burn (~€25–35K/month) in Eindhoven",
        "<b>Calibration:</b> comparable European climate/EO early rounds closed at €1M–€1.8M "
        "(Dryad, repath, Mitiga, Coolset) — we ask less because the platform is already built",
        "<b>Non-dilutive stack extends runway:</b> NLnet Restack (applied), Copernicus Incubation "
        "(€50K equity-free), CASSINI (€100K), WBSO",
        "Company formation: Dutch BV at High Tech Campus Eindhoven; founder relocating",
    ], MARGIN, y - 18, col_w, BULLET_SM)
    c.drawString(MARGIN + col_w + 30, y, "Use of funds")
    y2 = tbl(c, [
        ["Area", "Share", "What it buys"],
        ["Product &amp; validation", "~55%", "2 technical FTE; model validation campaign; E1-9 depth; partner API"],
        ["Commercial", "~25%", "pilot lead; 3–5 pilots; GRC-suite + EUDR exporter outreach"],
        ["Operations", "~20%", "BV setup, IP assignment, trademarks, hosting, compliance"],
    ], [col_w * 0.32, col_w * 0.16, col_w * 0.52], MARGIN + col_w + 30, y - 18)
    y = min(y1, y2) - 16
    c.setFont(FB, 12); c.setFillColor(NAVY)
    c.drawString(MARGIN, y, "Milestones this round buys (24 months)")
    bullets(c, [
        "<b>M6:</b> BV incorporated with clean IP chain (inbreng in natura); WBSO active; validation vs "
        "documented events published → screening labels upgraded where the evidence supports it",
        "<b>M12:</b> 3–5 paying pilots converted to subscriptions; first GRC-suite integration live; "
        "€50K+ ARR run-rate",
        "<b>M18:</b> EUDR exporter wave + EBA/EIOPA reuse pack; €150K ARR run-rate",
        "<b>M24:</b> seed-ready: €250K ARR trajectory, 2+ suite channels, EIC Accelerator application "
        "(€2.5M grant + equity) filed with pilot evidence",
    ], MARGIN, y - 18, PAGE_W - 2 * MARGIN - 20, BULLET_SM)
    footer(c, num, total)


def slide_why(c, num, total):
    y = header(c, "Why DeepTechXL · Why Eindhoven", "A stated fit: Digital Technologies × Sustainability × Security")
    col_w = (PAGE_W - 2 * MARGIN - 30) / 2
    c.setFont(FB, 12); c.setFillColor(NAVY)
    c.drawString(MARGIN, y, "Fit with the DeepTechXL thesis")
    y1 = bullets(c, [
        "<b>KET — Digital Technologies:</b> Earth Observation, environmental physics and AI fused into a "
        "digital-twin engine — with a Stage-2 soil/fuel-moisture sensor testbed bridging models to hardware "
        "ground truth",
        "<b>Themes — Energy Transition &amp; Sustainability, Security:</b> climate-resilience evidence for "
        "thousands of EU companies, on a legal deadline (CSRD/EUDR)",
        "<b>Stage:</b> pre-seed with a working platform — inside the €100K–€2M initial-ticket range; follow-on "
        "needs aligned with Fund I's lifecycle model (seed → Series C)",
        "<b>Ecosystem:</b> we chose High Tech Campus / Brainport as our base before choosing investors — "
        "the commitment to Brabant is already made",
    ], MARGIN, y - 18, col_w, BULLET_SM)
    c.drawString(MARGIN + col_w + 30, y, "Why Eindhoven / Brabant")
    y2 = bullets(c, [
        "High Tech Campus density: deep-tech talent, hardware/EO ecosystem, TU/e pipeline",
        "BOM and the Brabant support ladder for follow-on stages (familiar co-investment pattern)",
        "Central EU base for CSRD customers and EUDR exporter outreach (Rotterdam port corridor)",
        "HighTechXL / PreSeedXL venture-building heritage as the ecosystem's pre-seed fabric",
    ], MARGIN + col_w + 30, y - 18, col_w, BULLET_SM)
    y = min(y1, y2) - 14
    panel(c, MARGIN, y, PAGE_W - 2 * MARGIN, 12, [
        "<b>Next step:</b> we would welcome a 30-minute introductory call to walk through the engine live "
        "(talaix.com — the product, not a demo video) and discuss fit with DeepTechXL's investment strategy."
        "<br/><br/><b>Motaz Omarien</b> · Founder · motaz3d@gmail.com · +352 661811680 · talaix.com",
    ])
    footer(c, num, total)


def slide_why_generic(c, num, total):
    y = header(c, "Why Talaix · Why now", "A working platform ahead of a regulated-demand wave")
    col_w = (PAGE_W - 2 * MARGIN - 30) / 2
    c.setFont(FB, 12); c.setFillColor(NAVY)
    c.drawString(MARGIN, y, "Why now")
    y1 = bullets(c, [
        "<b>Regulated demand on a fixed calendar:</b> EUDR in force since 30 Dec 2025; CSRD Wave 2 reports "
        "FY2027 — compliance budgets are mandatory and deadline-driven, not discretionary",
        "<b>Consolidation at the top:</b> MSCI/First Street, ISS STOXX/Sust Global, Moody's/RMS — "
        "physical-risk evidence is proven must-have, and the mid-market is left open at transparent prices",
        "<b>The platform is already built:</b> 8-hazard engine, CsrdTX + XBRL, API v2, live self-serve "
        "funnel — this round funds validation and go-to-market, not a build",
    ], MARGIN, y - 18, col_w, BULLET_SM)
    c.drawString(MARGIN + col_w + 30, y, "Why Talaix")
    y2 = bullets(c, [
        "<b>Honesty as a product feature:</b> every datapoint carries source, method and evidence class; "
        "the engine is open source (tore, EUPL-1.2) — diligence can read the code today",
        "<b>Near-zero marginal cost:</b> automated evidence packs from €19 — a tier opaque enterprise "
        "vendors structurally cannot serve",
        "<b>Open-core defensibility:</b> GitLab/Elastic/Confluent precedent; curated loss and benchmark "
        "registries accumulate as proprietary data assets",
        "<b>EU base:</b> Dutch BV at High Tech Campus Eindhoven planned with this round; founder relocating",
    ], MARGIN + col_w + 30, y - 18, col_w, BULLET_SM)
    y = min(y1, y2) - 14
    panel(c, MARGIN, y, PAGE_W - 2 * MARGIN, 12, [
        "<b>Next step:</b> we would welcome a 30-minute introductory call to walk through the engine live "
        "(talaix.com — the product, not a demo video) and discuss fit with your investment strategy."
        "<br/><br/><b>Motaz Omarien</b> · Founder · motaz3d@gmail.com · +352 661811680 · talaix.com",
    ])
    footer(c, num, total)


SLIDES = [
    slide_title, slide_problem, slide_solution, slide_technology, slide_stage,
    slide_market, slide_business_model, slide_competition, slide_ip, slide_team,
    slide_funding, slide_why,
]

SLIDES_GENERIC = SLIDES[:-1] + [slide_why_generic]


def main():
    global OUT
    parser = argparse.ArgumentParser(description="Build the Talaix pre-seed pitch deck PDF")
    parser.add_argument("--fund", default="generic", choices=["generic", "deeptechxl"],
                        help="deeptechxl reproduces the DeepTechXL-branded deck; "
                             "generic (default) is the shareable webform version")
    args = parser.parse_args()
    if args.fund == "generic":
        PROFILE.update(GENERIC_PROFILE)
        OUT = GENERIC_OUT
    slides = SLIDES if PROFILE["fund"] == "deeptechxl" else SLIDES_GENERIC
    OUT.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(OUT), pagesize=(PAGE_W, PAGE_H))
    c.setTitle(PROFILE["pdf_title"])
    c.setAuthor("Motaz Omarien — Talaix")
    total = len(slides)
    for i, fn in enumerate(slides, 1):
        c.setFillColor(white)
        c.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
        fn(c, i, total)
        c.showPage()
    c.save()
    print(f"written: {OUT} ({OUT.stat().st_size/1024:.0f} KB, {total} slides)")


if __name__ == "__main__":
    main()
