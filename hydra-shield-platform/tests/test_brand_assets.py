"""Brand asset integrity: masters preserved, variants referenced correctly."""

import os

import pytest

ROOT = os.path.dirname(__file__)
BRAND = os.path.join(ROOT, "..", "website", "assets", "brand")


def _read(rel):
    with open(os.path.join(ROOT, "..", rel), encoding="utf-8") as fh:
        return fh.read()


def test_masters_and_variants_exist():
    for name in (
        "logo-master.png", "logo-with-text-master.png", "logo-text-site-master.png",
        "favicon-16.png", "favicon-32.png", "apple-touch-icon.png",
        "logo-mark-inverted.png", "logo-with-text-inverted.png",
    ):
        path = os.path.join(BRAND, name)
        assert os.path.isfile(path), name
        with open(path, "rb") as fh:
            assert fh.read(4) == b"\x89PNG", name


def test_inverted_mark_is_transparent_with_white_mark_and_teal_dot():
    np = pytest.importorskip("numpy")
    from PIL import Image

    arr = np.asarray(Image.open(os.path.join(BRAND, "logo-mark-inverted.png")))
    alpha = arr[..., 3].astype(int)
    assert alpha.min() == 0  # transparent background
    opaque = arr[alpha > 100]
    assert len(opaque) > 1000  # the mark itself is opaque
    # Teal dot pixels preserved (greenish), mark pixels white.
    teal = opaque[(opaque[:, 1] > 120) & (opaque[:, 0] < 130)]
    white = opaque[(opaque[:, 0] > 230) & (opaque[:, 1] > 230) & (opaque[:, 2] > 230)]
    assert len(teal) > 50
    assert len(white) > 1000


def test_chrome_uses_the_designer_mark():
    chrome = _read("website/js/chrome.js")
    assert "assets/brand/logo-mark-inverted.png" in chrome
    assert "logo-lockup" in chrome


def test_html_pages_use_png_favicons():
    import glob

    pages = glob.glob(os.path.join(ROOT, "..", "website", "*.html"))
    assert len(pages) > 20
    for path in pages:
        html = open(path, encoding="utf-8").read()
        if "rel=\"icon\"" in html:
            assert "assets/brand/favicon-32.png" in html, os.path.basename(path)
            assert "apple-touch-icon.png" in html, os.path.basename(path)


def test_registry_pages_and_pdfs_reference_brand():
    pages = _read("src/dashboard/registry_pages.py")
    assert "logo-mark-inverted.png" in pages
    report = _read("src/dashboard/verification_report.py")
    assert "logo-master.png" in report
    assert "_brand_mark" in report
    press = _read("src/dashboard/press_pdf.py")
    assert "_title_with_mark" in press
