"""Shared test isolation for the suite.

Several API endpoints enforce per-IP / per-user sliding-window budgets on a
process-wide in-memory limiter (``src.dashboard.api._rate_limiter``). The
whole suite shares Flask's default test-client IP, so cumulative calls from
earlier tests could exhaust a budget (e.g. register allows 20/hour) and make
later tests fail with 429 depending on execution order. Clearing the buckets
around every test keeps each test's budget its own; tests that exercise rate
limiting create their hits inside the test itself and are unaffected.
"""

import pytest


@pytest.fixture(autouse=True)
def _clear_rate_limiter():
    from src.dashboard import api as api_module

    api_module._rate_limiter._hits.clear()
    yield
    api_module._rate_limiter._hits.clear()
