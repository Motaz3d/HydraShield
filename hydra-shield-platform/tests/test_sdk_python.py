"""Run the Python-SDK offline tests as part of the main suite.

The SDK lives outside the installable package (`sdk/python/`, stdlib-only).
This module loads `sdk/python/tests/test_client.py` under a unique module
name and re-exports its test functions, so `pytest tests/` covers the SDK
with no pytest config changes. All tests are offline (urllib monkeypatched).
"""

import importlib.util
import sys
from pathlib import Path

_SDK_ROOT = Path(__file__).resolve().parents[1] / "sdk" / "python"
if str(_SDK_ROOT) not in sys.path:
    sys.path.insert(0, str(_SDK_ROOT))

_spec = importlib.util.spec_from_file_location(
    "hydrashield_sdk_python_tests", _SDK_ROOT / "tests" / "test_client.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

for _name in dir(_mod):
    if _name.startswith("test_") or _name == "http":  # tests + their fixture
        globals()[_name] = getattr(_mod, _name)

del _name, _mod, _spec
