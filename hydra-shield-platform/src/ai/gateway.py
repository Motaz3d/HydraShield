"""
Server-side AI gateway for the Talaix platform.

Provides a cheap-first, tiered interface to the Kimi API. The gateway is
opt-in via ``KIMI_API_KEY``; when the key is absent every call raises
``AIUnavailable`` so callers can degrade gracefully.

Usage is logged to the shared platform SQLite database so daily caps can be
enforced and operators can audit spend.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests

from ..dashboard.cache import default_cache

KIMI_BASE_URL = "https://api.kimi.com/coding/v1/chat/completions"

TASK_TIERS: Dict[str, str] = {
    "classify": "kimi-for-coding",
    "polish": "kimi-for-coding",
    "summarize": "kimi-for-coding",
    "draft_prose": "kimi-for-coding",
    "deep_analysis": "k3-256k",
}

POLISH_SYSTEM_PROMPT = (
    "You are a cautious editorial assistant for a climate-risk evidence platform. "
    "Rewrite the user's section text to be clearer, more concise, and grammatically correct. "
    "Do NOT add new facts, numbers, hazard labels, source references, or conclusions that are "
    "not already present in the user's text. Do NOT change the meaning. Preserve the section "
    "heading if provided. Return only the polished prose, with no markdown code fences, "
    "preface, or explanation. If the text is already clear, return it nearly unchanged."
)

DEFAULT_DAILY_CAP = 50


class AIUnavailable(Exception):
    """Raised when the AI gateway is not configured or the upstream call fails."""

    pass


def configured() -> bool:
    """Return True when a non-empty ``KIMI_API_KEY`` is present."""
    return bool(os.environ.get("KIMI_API_KEY", "").strip())


def _api_key() -> str:
    """Return the configured API key, or raise AIUnavailable."""
    key = os.environ.get("KIMI_API_KEY", "").strip()
    if not key:
        raise AIUnavailable("AI gateway is not configured (KIMI_API_KEY is missing)")
    return key


def _daily_cap() -> int:
    """Return the daily call cap from the environment or the default."""
    try:
        return int(os.environ.get("AI_DAILY_CALL_CAP", DEFAULT_DAILY_CAP))
    except (TypeError, ValueError):
        return DEFAULT_DAILY_CAP


def _db_path() -> str:
    """Use the same SQLite file as the rest of the platform."""
    return default_cache().db_path


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _init_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_kind TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt_tokens INTEGER NOT NULL DEFAULT 0,
            completion_tokens INTEGER NOT NULL DEFAULT 0,
            called_at TEXT NOT NULL
        )
        """
    )


# Module-level lock serialises table creation and usage writes across threads.
_db_lock = threading.Lock()


def log_usage(
    task_kind: str,
    model: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> None:
    """Record one AI call in the shared database."""
    db_path = _db_path()
    called_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with _db_lock, _connect(db_path) as conn:
        _init_table(conn)
        conn.execute(
            "INSERT INTO ai_usage (task_kind, model, prompt_tokens, completion_tokens, called_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (task_kind, model, int(prompt_tokens), int(completion_tokens), called_at),
        )


def calls_today() -> int:
    """Return the number of AI calls recorded since midnight UTC today."""
    db_path = _db_path()
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    iso_today = today.isoformat().replace("+00:00", "Z")
    with _db_lock, _connect(db_path) as conn:
        _init_table(conn)
        row = conn.execute(
            "SELECT COUNT(*) FROM ai_usage WHERE called_at >= ?",
            (iso_today,),
        ).fetchone()
    return row[0] if row else 0


def _resolve_model(task_kind: str) -> str:
    """Return the model for a task kind, or raise AIUnavailable."""
    if task_kind not in TASK_TIERS:
        raise AIUnavailable(f"unknown task kind: {task_kind}")
    return TASK_TIERS[task_kind]


def _post(url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    """
    POST to the Kimi API. Split out so tests can monkeypatch a single helper.
    Returns the parsed JSON response or raises AIUnavailable on failure.
    """
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        raise AIUnavailable(f"AI request failed: {exc}") from exc

    if response.status_code != 200:
        raise AIUnavailable(
            f"AI request returned HTTP {response.status_code}"
        )

    try:
        return response.json()
    except ValueError as exc:
        raise AIUnavailable(f"AI response was not valid JSON: {exc}") from exc


def complete(
    task_kind: str,
    user_prompt: str,
    *,
    system_prompt: Optional[str] = None,
    max_tokens: int = 800,
    timeout: float = 30,
) -> str:
    """
    Run a single chat completion against the Kimi API.

    Returns the trimmed text content of the assistant message. Raises
    ``AIUnavailable`` when the gateway is not configured, the daily cap is
    reached, or the upstream request fails. No API key is ever included in
    exception messages.
    """
    if not configured():
        raise AIUnavailable("AI gateway is not configured")

    cap = _daily_cap()
    if cap > 0 and calls_today() >= cap:
        raise AIUnavailable("daily AI call cap reached")

    model = _resolve_model(task_kind)
    key = _api_key()

    messages: list[Dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max(max_tokens, 1),
        "temperature": 0,
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    data = _post(KIMI_BASE_URL, headers, payload, timeout)

    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AIUnavailable(f"AI response shape was unexpected: {exc}") from exc

    usage = data.get("usage") or {}
    log_usage(
        task_kind=task_kind,
        model=model,
        prompt_tokens=usage.get("prompt_tokens", 0) or 0,
        completion_tokens=usage.get("completion_tokens", 0) or 0,
    )

    return text.strip()
