"""TAM contract tests (docs/ANALYTICAL_MODEL.md).

Locks the unified development template:
1. One shared clock — no module in src/climate re-declares _utcnow_iso.
2. The ProductResult envelope is uniform and wins key collisions.
3. Every migrated product engine declares id / version / disclaimer.
4. The reference engine (insurance) emits the full envelope.
"""

import os
import re

import pytest

from src.climate.engine import ENVELOPE_KEYS, TAM_VERSION, ProductEngine

CLIMATE_DIR = os.path.join(os.path.dirname(__file__), "..", "src", "climate")

# Engines migrated to the ProductEngine contract. Grow this list as the
# remaining engines adopt the template one by one.
MIGRATED_ENGINES = ("insurance",)

# Product engines that must at least declare an explicit ENGINE_VERSION.
VERSIONED_ENGINES = (
    "forensics", "insurance", "press", "report_builder",
    "supplychain", "sustainability", "verification",
)


def _read(rel):
    with open(os.path.join(CLIMATE_DIR, rel), encoding="utf-8") as fh:
        return fh.read()


def test_single_shared_clock():
    offenders = []
    for name in sorted(os.listdir(CLIMATE_DIR)):
        if not name.endswith(".py") or name == "evidence.py":
            continue
        if re.search(r"def _utcnow_iso", _read(name)):
            offenders.append(name)
    hazards = os.path.join(CLIMATE_DIR, "hazards")
    for name in sorted(os.listdir(hazards)):
        if name.endswith(".py") and re.search(r"def _utcnow_iso", _read(os.path.join("hazards", name))):
            offenders.append(f"hazards/{name}")
    assert not offenders, f"re-declared clock in: {offenders} — import utcnow_iso from evidence"


def test_envelope_merges_blocks_and_wins_collisions():
    engine = ProductEngine()
    engine.id, engine.engine_version, engine.disclaimer = "demo", "9.9.9", "D"
    d = engine.result(summary="s", blocks={"x": 1, "status": "forged"}).to_dict()
    assert d["x"] == 1                      # payload preserved
    assert d["status"] == "ok"              # envelope wins collisions
    assert d["engine_version"] == "9.9.9"
    assert d["disclaimer"] == "D"
    assert d["tam_version"] == TAM_VERSION
    for key in ENVELOPE_KEYS:
        assert key in d


def test_envelope_unavailable_path():
    engine = ProductEngine()
    engine.id = "demo"
    d = engine.unavailable("source down").to_dict()
    assert d["status"] == "unavailable"
    assert d["unavailable_reason"] == "source down"


@pytest.mark.parametrize("module_name", VERSIONED_ENGINES)
def test_product_engine_declares_version(module_name):
    import importlib
    module = importlib.import_module(f"src.climate.{module_name}")
    assert getattr(module, "ENGINE_VERSION", None), f"{module_name} lacks ENGINE_VERSION"


@pytest.mark.parametrize("module_name", MIGRATED_ENGINES)
def test_migrated_engine_contract(module_name):
    import importlib
    module = importlib.import_module(f"src.climate.{module_name}")
    engine = module._ENGINE
    assert isinstance(engine, ProductEngine)
    assert engine.id and engine.name and engine.engine_version and engine.disclaimer
    d = engine.result(summary="contract", blocks={"payload": True}).to_dict()
    for key in ENVELOPE_KEYS:
        assert key in d
    assert d["product"] == engine.id
