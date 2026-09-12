"""Tests for scripts/verify_import_batch.py."""

import importlib.util
from pathlib import Path


def _load_module():
    script = Path(__file__).resolve().parent.parent / "scripts" / "verify_import_batch.py"
    spec = importlib.util.spec_from_file_location("verify_import_batch", str(script))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _contact(org, email, source_url, website):
    return {"organization": org, "email": email, "source_url": source_url,
            "website": website}


def test_page_has_email_handles_obfuscation():
    mod = _load_module()
    assert mod.page_has_email("mail us: INFO@EXAMPLE.COM", "info@example.com")
    assert mod.page_has_email("write to info [at] example.com", "info@example.com")
    assert mod.page_has_email("write to info(at)example.com", "info@example.com")
    assert mod.page_has_email("write to info&#64;example.com", "info@example.com")
    assert not mod.page_has_email("no address here", "info@example.com")
    assert not mod.page_has_email(None, "info@example.com")


def test_verify_batch_ok_fixed_dropped():
    mod = _load_module()
    pages = {
        "https://real.example/imprint": "contact: info@real.example",
        "https://moved.example/contact": "mail: hello@moved.example",
    }

    def fake_fetch(url):
        return pages.get(url)

    seed = {"contacts": [
        _contact("Real Co", "info@real.example",
                 "https://real.example/imprint", "https://real.example"),
        _contact("Moved Co", "hello@moved.example",
                 "https://moved.example/en/imprint", "https://moved.example"),
        _contact("Ghost Co", "info@ghost.example",
                 "https://ghost.example/imprint", "https://ghost.example"),
    ]}
    result = mod.verify_batch(seed, fetcher=fake_fetch)
    assert [c["organization"] for c in result["ok"]] == ["Real Co"]
    assert [c["organization"] for c in result["fixed"]] == ["Moved Co"]
    assert result["fixed"][0]["source_url"] == "https://moved.example/contact"
    assert [c["organization"] for c in result["dropped"]] == ["Ghost Co"]


def test_dropped_when_email_missing_everywhere():
    mod = _load_module()
    seed = {"contacts": [
        _contact("No Email Co", "info@noemail.example",
                 "https://noemail.example/imprint", "https://noemail.example"),
        {"organization": "Empty Mail Co", "email": "",
         "source_url": "https://x.example", "website": "https://x.example"},
    ]}
    result = mod.verify_batch(seed, fetcher=lambda url: "page without addresses")
    assert result["ok"] == [] and result["fixed"] == []
    assert len(result["dropped"]) == 2
