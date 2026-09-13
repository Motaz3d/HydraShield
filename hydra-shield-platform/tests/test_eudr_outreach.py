"""EUDR exporters outreach: dedicated template integrity + honesty markers.

Operator directive 2026-09-12: the non-EU exporter / EUDR geolocation angle is
the least-contested niche, so it leads backfill priority and is presented in
correspondence from 2026-09-20 onward via a dedicated template.
"""

import os

from src.dashboard import mailer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_PATH = os.path.join(
    ROOT, "src", "dashboard", "email_templates",
    "outreach_eudr_exporters.txt")


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def test_template_exists_and_carries_honesty_markers():
    tpl = _read(TEMPLATE_PATH)
    low = tpl.lower()
    assert "eudr" in low
    assert "screening" in low
    # The claim we explicitly refuse must be named as a refusal, not a promise.
    assert "deforestation-free" in low
    assert "{{unsubscribe_url}}" in tpl
    assert "{{contact_name}}" in tpl
    assert "{{organization}}" in tpl
    # No fabricated urgency or guarantees.
    assert "guarantee" not in low
    assert "guaranteed" not in low


def test_template_renders_clean_and_is_registered():
    """Rendering via the mailer also proves the template is in _TEMPLATE_NAMES."""
    rendered = mailer.render_template("outreach_eudr_exporters", {
        "contact_name": "Sourcing Team",
        "organization": "Example Traders",
        "identified_problem": "Cocoa sourcing exposed to drought and fire.",
        "relevant_capability": "Plot-level origin screening with declared gaps.",
        "custom_message": "",
        "unsubscribe_url": mailer.unsubscribe_mailto(),
    })
    assert "{{" not in rendered["subject"]
    assert "{{" not in rendered["text"]
    assert "Example Traders" in rendered["text"]
    assert "EUDR" in rendered["subject"]
