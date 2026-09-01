"""Run the Python-SDK TX-client offline tests as part of the main suite.

Mirror of tests/test_sdk_python.py for the TX Engine client: loads
`sdk/python/tests/test_tx.py` under a unique module name and re-exports its
test functions (plus their fixture), so `pytest tests/` covers the TX SDK
with no pytest config changes. All tests are offline (urllib monkeypatched).
"""

import importlib.util
import sys
from pathlib import Path

_SDK_ROOT = Path(__file__).resolve().parents[1] / "sdk" / "python"
if str(_SDK_ROOT) not in sys.path:
    sys.path.insert(0, str(_SDK_ROOT))

_spec = importlib.util.spec_from_file_location(
    "hydrashield_sdk_tx_tests", _SDK_ROOT / "tests" / "test_tx.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

for _name in dir(_mod):
    if _name.startswith("test_") or _name == "http":  # tests + their fixture
        globals()[_name] = getattr(_mod, _name)

del _name, _mod, _spec
