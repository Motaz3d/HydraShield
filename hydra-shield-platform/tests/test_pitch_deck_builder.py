import importlib.util
import sys
from pathlib import Path

import pytest
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "build_deeptechxl_deck", ROOT / "scripts" / "build_deeptechxl_deck.py"
)
_builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_builder)

_DEEP_BASELINE = dict(_builder.PROFILE)


def test_lsa_profile_is_defined():
    assert _builder.LSA_PROFILE["fund"] == "lsa"
    assert "Luxembourg Space Agency" in _builder.LSA_PROFILE["footer"]
    assert "Luxembourg Space Agency" in _builder.LSA_PROFILE["cover"]
    assert "Luxembourg Space Agency" in _builder.LSA_PROFILE["pdf_title"]
    assert "ESA BIC Luxembourg" in _builder.LSA_PROFILE["funding_fit"]
    assert "LIST" in _builder.LSA_PROFILE["team_eco"]
    assert _builder.LSA_OUT.name == "lsa_pitch_deck.pdf"


def test_argparse_accepts_lsa(monkeypatch, tmp_path):
    out = tmp_path / "lsa_argparse.pdf"
    _builder.PROFILE.clear()
    _builder.PROFILE.update(_DEEP_BASELINE)
    _builder.LSA_OUT = out
    monkeypatch.setattr(sys, "argv", ["build_deeptechxl_deck.py", "--fund", "lsa"])
    _builder.main()
    assert out.exists()
    reader = PdfReader(str(out))
    assert len(reader.pages) == 12
    assert reader.metadata.title == _builder.LSA_PROFILE["pdf_title"]


@pytest.mark.parametrize("fund,attr,expected_title", [
    ("generic", "GENERIC_OUT", _builder.GENERIC_PROFILE["pdf_title"]),
    ("deeptechxl", "OUT", _builder.PROFILE["pdf_title"]),
    ("lsa", "LSA_OUT", _builder.LSA_PROFILE["pdf_title"]),
])
def test_builds_expected_output(fund, attr, expected_title, tmp_path, monkeypatch):
    out = tmp_path / f"{fund}.pdf"
    _builder.PROFILE.clear()
    _builder.PROFILE.update(_DEEP_BASELINE)
    setattr(_builder, attr, out)
    monkeypatch.setattr(sys, "argv", ["build_deeptechxl_deck.py", "--fund", fund])
    _builder.main()
    assert out.exists()
    assert out.stat().st_size > 10_000
    reader = PdfReader(str(out))
    assert len(reader.pages) == 12
    assert reader.metadata.title == expected_title
