"""Branded transactional email: welcome greeting + HTML shell lockup."""

from src.dashboard import mailer


def test_welcome_greeting_with_display_name():
    rendered = mailer.render_template("welcome", {"display_name": " Motaz"})
    assert rendered["subject"] == "Welcome to Talaix"
    assert rendered["text"].startswith("Hello Motaz,\n")
    assert "welcome to Talaix" in rendered["text"]


def test_welcome_greeting_without_display_name():
    rendered = mailer.render_template("welcome", {})
    assert rendered["text"].startswith("Hello,\n")


def test_html_shell_carries_brand_lockup():
    html = mailer._minimal_html("Hello,\n\nwelcome aboard.")
    assert "assets/brand/logo-email.png" in html
    assert 'alt="Talaix"' in html
    assert "#1E2C4A" in html  # brand navy
    assert "#47B3A8" in html  # brand teal


def test_html_shell_escapes_body():
    html = mailer._minimal_html("<script>alert(1)</script>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_logo_url_follows_base_url_env(monkeypatch):
    monkeypatch.setenv("HYDRASHIELD_BASE_URL", "https://example.test/")
    assert mailer._brand_logo_url() == \
        "https://example.test/assets/brand/logo-email.png"
