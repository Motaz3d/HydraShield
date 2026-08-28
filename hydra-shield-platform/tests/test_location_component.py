"""Tests for the platform Location component (website/js/location.js).

The pure logic (normalize) is exercised in Node; the page wiring is
checked structurally (mount + script present on every consumer page).
"""

import json
import os
import subprocess

ROOT = os.path.join(os.path.dirname(__file__), "..")

HARNESS = r"""
const fs = require('fs');
global.window = {};
eval(fs.readFileSync(process.argv[1], 'utf8'));
const HS = global.window.HS;
const out = {};
out.place = HS.location.normalize(
    {lat: 49.85, lon: 6.03, name: 'Clervaux, Canton Clervaux, Lëtzebuerg'},
    'Clervaux');
out.coords = HS.location.normalize(
    {lat: 37.3892, lon: -5.9845, name: '37.3892, -5.9845'},
    '37.3892, -5.9845');
console.log(JSON.stringify(out));
"""


def test_location_normalize_place_and_coordinates():
    result = subprocess.run(
        ["node", "-e", HARNESS,
         os.path.join(ROOT, "website", "js", "location.js")],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    place = out["place"]
    assert place["hierarchy"] == ["Clervaux", "Canton Clervaux", "Lëtzebuerg"]
    assert place["crs"] == "EPSG:4326"
    assert place["source"] == "Nominatim (OpenStreetMap geocoding)"
    assert place["precision"].startswith("place-name match")
    coords = out["coords"]
    assert coords["precision"] == "exact coordinates"
    assert coords["source"] == "user-entered coordinates"
    assert coords["lat"] == 37.3892


def test_location_component_wired_on_all_consumer_pages():
    # The economy panel (locAssist) merged into intelligence.html; the
    # widget mounts are asserted per host page.
    pages = {"intelligence.html": ["locWidget", "locAssist"],
             "funding.html": ["locWidget"],
             "solutions.html": ["locAssist"], "reports.html": ["locAssist"]}
    for page, mounts in pages.items():
        html = open(os.path.join(ROOT, "website", page),
                    encoding="utf-8").read()
        assert 'js/location.js' in html, page
        for mount in mounts:
            assert f'id="{mount}"' in html, (page, mount)
