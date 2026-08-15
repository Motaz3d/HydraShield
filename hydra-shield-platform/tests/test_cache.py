"""Tests for the SQLite TTL cache."""

import time

from src.dashboard.cache import TTLCache


def test_set_get_roundtrip(tmp_path):
    cache = TTLCache(str(tmp_path / "c.sqlite3"))
    cache.set("k1", {"a": 1, "b": [1, 2, None]}, ttl_seconds=60)
    assert cache.get("k1") == {"a": 1, "b": [1, 2, None]}


def test_missing_key_returns_none(tmp_path):
    cache = TTLCache(str(tmp_path / "c.sqlite3"))
    assert cache.get("nope") is None


def test_expired_entry_returns_none(tmp_path):
    cache = TTLCache(str(tmp_path / "c.sqlite3"))
    cache.set("k2", {"x": 1}, ttl_seconds=0.05)
    time.sleep(0.1)
    assert cache.get("k2") is None


def test_purge_expired(tmp_path):
    cache = TTLCache(str(tmp_path / "c.sqlite3"))
    cache.set("old", 1, ttl_seconds=0.01)
    cache.set("fresh", 2, ttl_seconds=600)
    time.sleep(0.05)
    removed = cache.purge_expired()
    assert removed == 1
    assert cache.get("fresh") == 2


def test_make_key_deterministic():
    k1 = TTLCache.make_key("ns", 1, 2, a="b")
    k2 = TTLCache.make_key("ns", 1, 2, a="b")
    k3 = TTLCache.make_key("ns", 1, 2, a="c")
    assert k1 == k2
    assert k1 != k3
    assert k1.startswith("ns:")


def test_stats(tmp_path):
    cache = TTLCache(str(tmp_path / "c.sqlite3"))
    cache.set("a", 1, 60)
    stats = cache.stats()
    assert stats["entries_total"] == 1
    assert stats["entries_live"] == 1
