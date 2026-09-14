#!/usr/bin/env python3
"""Build the public sample evidence pack (PDF) shown on the website.

Why this exists
---------------
The site promises a traceable PDF deliverable, but until now a visitor had to
sign up to see one. This script renders a *format* sample of that deliverable
into `website/assets/samples/talaix-sample-evidence-pack.pdf`, so the promise is
demonstrable without an account.

Honesty rule (root AGENTS.md): no fabricated content. Every figure below is the
real engine output for Clervaux, Luxembourg (2026-08-25) that is already
published on the Green Finance, Reports and Sustainability pages. The document
says so explicitly on its first page — it is a sample of the format, not a live
run.

Usage
-----
    python scripts/build_sample_pack.py
    python scripts/build_sample_pack.py --check   # verify only, no rebuild
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = ROOT / "website" / "assets" / "samples"
MD_PATH = SAMPLE_DIR / "talaix-sample-evidence-pack.md"
PDF_PATH = SAMPLE_DIR / "talaix-sample-evidence-pack.pdf"

FOOTER = "Talaix — sample evidence pack · real engine output, Clervaux (LU), 2026-08-25"

# The Markdown source of the sample pack. Figures are the published real engine
# output for Clervaux, Luxembourg, 2026-08-25 (see website/green-finance.html,
# website/reports.html and website/sustainability.html).
SAMPLE_MD = """# Sample evidence pack
**Real engine output — Clervaux, Luxembourg · 2026-08-25**

## What this document is
This is the format of a Talaix site evidence pack, filled with a real engine run
published on talaix.com on 2026-08-25. It is a sample of the deliverable, not a
live run: run your own coordinates on the platform to get your own pack.

## 1. Site and method
| Field | Value |
| Site | Clervaux, Luxembourg (anonymised demo company: "Demo Estates SA") |
| Coordinates analysed | 50.0547 N, 6.0286 E |
| Engine run | 2026-08-25 |
| Hazards screened per site | up to 10 |
| DNSH-relevant hazards for this asset | 6 of 6 assessed with real data |
| Declared gaps | 0 for this site |
| Evidence labels | OBSERVED · DOCUMENTED · REPORTED · MODELLED · INFERRED · UNKNOWN |

## 2. Hazard evidence
| Hazard | Level | Basis |
| Drought | Severe | Real data |
| Wind | Moderate | Real data |
| Flood | Low | Real data |
| Wildfire | Low | Real data |
| Hail | Low | Real data |
| Extreme heat | Low | Real data |

In a customer pack every row also carries the dataset name, its version, the date
range covered and the confidence behind the level. Where a dataset cannot be read
for a site, the row is returned as UNKNOWN and listed under declared gaps — never
filled in.

## 3. Compliance mapping (CSRD / ESRS)
| Disclosure area | Coverage |
| ESRS E1 — physical climate risk | Covered by evidence |
| ESRS E3 — water and marine resources | Partially covered |
| Other ESRS areas | Not covered — declared boundary |

This is an evidence layer, not assurance. CSRD limited assurance remains with your
auditor or independent assurance provider.

## 4. Sources the engine draws on
Satellite and reanalysis: Sentinel-2, Landsat Collection 2, ERA5 and ERA5-Land,
Open-Meteo, NASA FIRMS (VIIRS/MODIS), ESA WorldCover, GloFAS, SRTM/Copernicus DEM,
WorldPop and OpenStreetMap. 25 datasets are integrated into the engine out of 167
catalogued; every source evaluated — integrated, candidate or rejected, with the
reason — is public at talaix.com/sources.

## 5. Honesty contract and disclaimer
- Unavailable data is declared, never invented.
- Every figure carries its source, date and confidence.
- Levels are screening indicators unless explicitly labelled validated.
- No loss quantification: no AAL, PML or EP curves.
- Not assurance, not a Second Party Opinion, not investment or legal advice.

## What it costs
- Free: multi-hazard analysis, the map, the CSRD applicability check, a simple PDF report.
- Decision-ready pack €19 · Scientific report €39 · Professional €49/month.
- Full pricing: talaix.com/pricing.html

Contact: info@talaix.com
"""


def build() -> Path:
    """Write the Markdown source, then render it to PDF with scripts/md_to_pdf."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from md_to_pdf import md_to_flowables  # local import: sibling script

    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate
    from reportlab.lib import colors
    from reportlab.lib.units import cm

    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    MD_PATH.write_text(SAMPLE_MD, encoding="utf-8")

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.grey)
        canvas.drawCentredString(A4[0] / 2, 1.1 * cm,
                                 f"{FOOTER} — page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(str(PDF_PATH), pagesize=A4, leftMargin=2 * cm,
                            rightMargin=2 * cm, topMargin=1.8 * cm,
                            bottomMargin=2 * cm,
                            title="Talaix — sample evidence pack")
    doc.build(md_to_flowables(SAMPLE_MD), onFirstPage=footer, onLaterPages=footer)
    return PDF_PATH


def check() -> int:
    """Fail loudly if the committed sample is missing or unreadable."""
    problems = []
    if not MD_PATH.exists():
        problems.append(f"missing source: {MD_PATH}")
    if not PDF_PATH.exists():
        problems.append(f"missing PDF: {PDF_PATH}")
    else:
        blob = PDF_PATH.read_bytes()
        if not blob.startswith(b"%PDF"):
            problems.append(f"not a PDF: {PDF_PATH}")
        if len(blob) < 4_000:
            problems.append(f"suspiciously small ({len(blob)} bytes): {PDF_PATH}")
    for problem in problems:
        print(f"FAIL {problem}")
    if not problems:
        print(f"OK {PDF_PATH.name} ({PDF_PATH.stat().st_size // 1024} KB)")
    return 1 if problems else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="verify the committed sample without rebuilding it")
    args = ap.parse_args()
    if args.check:
        return check()
    path = build()
    print(f"built {path}: {path.stat().st_size / 1024:.0f} KB")
    return check()


if __name__ == "__main__":
    raise SystemExit(main())
