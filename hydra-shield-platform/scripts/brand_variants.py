#!/usr/bin/env python3
"""
Regenerate Talaix brand variants from the master artwork.

Masters (DESIGN SOURCE — never edit, commit as-is) live in
``website/assets/brand/``:

    logo-master.png            the T + teal dot mark (navy on white)
    logo-with-text-master.png  mark + TALAIX wordmark
    logo-text-site-master.png  mark + wordmark + talaix.com

This script derives (idempotent; safe to re-run after a master changes):

    favicon-16.png / favicon-32.png   white-background favicons
    apple-touch-icon.png              180x180 touch icon (mark on white)
    logo-mark-inverted.png            white T + teal dot, transparent bg
                                      (for the DARK navbar/footer/chrome)
    logo-with-text-inverted.png       same inversion with the wordmark
    logo-email.png                    mark + wordmark, 400px wide on white
                                      (transactional-email header lockup)

Inversion rule: navy pixels become white with luminance-derived alpha
(white background turns transparent, anti-aliased edges keep their
softness); teal-dot pixels keep their original colour.

Usage: .venv/bin/python scripts/brand_variants.py
"""

from __future__ import annotations

import os

import numpy as np
from PIL import Image

BRAND_DIR = os.path.join(
    os.path.dirname(__file__), "..", "website", "assets", "brand"
)


def _path(name: str) -> str:
    return os.path.join(BRAND_DIR, name)


def _save_favicons() -> None:
    master = Image.open(_path("logo-master.png")).convert("RGBA")
    for size in (16, 32):
        icon = master.resize((size, size), Image.LANCZOS)
        icon.save(_path(f"favicon-{size}.png"))

    # Apple touch icon: mark centred on a white square.
    touch = Image.new("RGBA", (180, 180), (255, 255, 255, 255))
    mark = master.resize((140, 146), Image.LANCZOS)
    touch.alpha_composite(mark, ((180 - 140) // 2, (180 - 146) // 2))
    touch.save(_path("apple-touch-icon.png"))


def _save_email_logo() -> None:
    """Email header lockup: wordmark master at 400px wide on white.

    Email clients see a hosted <img>; a flat white background keeps the
    lockup intact in both light and dark mail themes. 400px covers a
    200px display width at 2x (retina).
    """
    master = Image.open(_path("logo-with-text-master.png")).convert("RGBA")
    w, h = master.size
    target_w = 400
    resized = master.resize((target_w, round(h * target_w / w)), Image.LANCZOS)
    canvas = Image.new("RGBA", resized.size, (255, 255, 255, 255))
    canvas.alpha_composite(resized)
    canvas.convert("RGB").save(_path("logo-email.png"))


def _invert_for_dark(master_name: str, out_name: str) -> None:
    """Navy-on-white -> white-on-transparent, teal dot preserved."""
    im = Image.open(_path(master_name)).convert("RGBA")
    arr = np.asarray(im).astype(np.uint8).copy()
    r = arr[..., 0].astype(np.int32)
    g = arr[..., 1].astype(np.int32)
    b = arr[..., 2].astype(np.int32)

    lum = (299 * r + 587 * g + 114 * b) // 1000  # 0..255 luminance

    # Teal dot: greenish hue — clearly greener than the navy T and not white.
    is_teal = (g > 120) & (r < 130) & (b > 100) & ((g - r) > 30)

    out = np.zeros_like(arr)
    # Non-teal: white graphic whose alpha comes from the darkness of the
    # original pixel (navy -> opaque, white -> transparent, edges -> soft).
    alpha = np.clip(255 - lum, 0, 255).astype(np.uint8)
    out[..., 0] = 255
    out[..., 1] = 255
    out[..., 2] = 255
    out[..., 3] = np.where(is_teal, 0, alpha).astype(np.uint8)
    # Teal pixels keep their original colour at full opacity.
    out[is_teal] = np.stack(
        [r[is_teal], g[is_teal], b[is_teal],
         np.full(is_teal.sum(), 255, dtype=np.uint8)], axis=-1)

    Image.fromarray(out, "RGBA").save(_path(out_name))


def main() -> None:
    os.makedirs(BRAND_DIR, exist_ok=True)
    _save_favicons()
    _save_email_logo()
    _invert_for_dark("logo-master.png", "logo-mark-inverted.png")
    _invert_for_dark("logo-with-text-master.png", "logo-with-text-inverted.png")
    for name in sorted(os.listdir(BRAND_DIR)):
        if name.endswith(".png"):
            print("brand asset:", name)


if __name__ == "__main__":
    main()
