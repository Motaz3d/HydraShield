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


def test_html_shell_has_no_header_image():
    html = mailer._minimal_html("Hello,\n\nwelcome aboard.")
    assert "logo-email.png" not in html
    assert "#1E2C4A" in html  # brand navy
    assert "#47B3A8" in html  # brand teal


def test_html_shell_escapes_body():
    html = mailer._minimal_html("<script>alert(1)</script>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_text_part_carries_corporate_signature():
    msg = mailer._build_message("a@b.c", "Hi", "Body text.")
    text = msg.get_body(("plain",)).get_content()
    assert text.endswith(
        "--\nTalaix\nEarth Observation & Environmental Risk\n"
        "Financial Decision Intelligence\n"
        "Luxembourg-based technology team\n"
        "info@talaix.com | talaix.com\n"
    )


def test_html_shell_carries_signature_with_logo():
    html = mailer._minimal_html("Hello.")
    assert f"cid:{mailer._SIGNATURE_CID}" in html
    assert "Earth Observation &amp; Environmental Risk" in html
    assert "Financial Decision Intelligence" in html
    assert "Luxembourg-based technology team" in html
    assert "mailto:info@talaix.com" in html


def test_signature_logo_embedded_as_cid_attachment():
    msg = mailer._build_message("a@b.c", "Hi", "Body text.")
    images = [p for p in msg.walk() if p.get_content_type() == "image/png"]
    assert images, "expected an embedded signature logo"
    assert images[0]["Content-ID"] == f"<{mailer._SIGNATURE_CID}>"


def test_signature_logo_url_follows_base_url_env(monkeypatch):
    monkeypatch.setenv("HYDRASHIELD_BASE_URL", "https://example.test/")
    assert mailer._signature_logo_url() == \
        "https://example.test/assets/brand/logS100.png"
