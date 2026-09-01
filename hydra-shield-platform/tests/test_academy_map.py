"""Tests for the Talaix Academy 2.0 knowledge map and spaced reviews.

Mirrors the fixtures and helpers from test_academy.py.
"""

import json
import os
import time

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_academy_map_cache.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from src.climate.academy import (  # noqa: E402
    REVIEW_FAIL_INTERVAL,
    REVIEW_INITIAL_INTERVAL,
    load_course,
    load_knowledge,
    validate_knowledge,
)
from src.dashboard.api import create_app  # noqa: E402


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Isolated DB + outbox per test."""
    db_path = tmp_path / "academy_map.sqlite3"
    monkeypatch.setenv("HYDRASHIELD_CACHE_DB", str(db_path))
    monkeypatch.setenv("HYDRASHIELD_OUTBOX_DIR", str(tmp_path / "outbox"))
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_USER", raising=False)
    import src.dashboard.cache as cache_mod
    import src.dashboard.api as api_module

    monkeypatch.setattr(cache_mod, "_default_cache", None)
    api_module._rate_limiter._hits.clear()
    return {"db": db_path, "outbox": tmp_path / "outbox"}


@pytest.fixture()
def client(env):
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture()
def course():
    return load_course()["courses"][0]


@pytest.fixture()
def knowledge():
    return load_knowledge()


# -----------------------------------------------------------------------------
# Auth helpers
# -----------------------------------------------------------------------------


def _register(client, email="user@example.org", password="correct horse battery"):
    resp = client.post(
        "/api/v2/auth/register",
        json={
            "email": email,
            "password": password,
            "display_name": "Test User",
            "consent": True,
        },
    )
    assert resp.status_code == 201, resp.get_json()
    return resp


def _verification_token(outbox_dir):
    import email as email_lib
    import re

    files = sorted(outbox_dir.glob("*_email_verification_*.eml"))
    assert files, "no verification email in outbox"
    raw = files[-1].read_text(encoding="utf-8")
    msg = email_lib.message_from_string(raw)
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                break
    else:
        body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
    match = re.search(r"token=([A-Za-z0-9_\-]+)", body)
    assert match, "no verification token in email"
    return match.group(1)


def _register_and_verify(client, env, email="user@example.org", password="correct horse battery"):
    _register(client, email, password)
    token = _verification_token(env["outbox"])
    resp = client.get(f"/api/v2/auth/verify?token={token}")
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    return body["user"], body["session_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _correct_answers(module):
    return [q["correct_index"] for q in module["quiz"]]


def _all_wrong_answers(module):
    return [(q["correct_index"] + 1) % len(q["options"]) for q in module["quiz"]]


def _concept_in_model(model, concept_id):
    return next((c for c in model["concepts"] if c["id"] == concept_id), None)


# -----------------------------------------------------------------------------
# Config validation
# -----------------------------------------------------------------------------


def test_validate_knowledge_real_configs(course, knowledge):
    problems = validate_knowledge(knowledge, course)
    assert problems == []


# -----------------------------------------------------------------------------
# Knowledge graph endpoint
# -----------------------------------------------------------------------------


def test_knowledge_public(client, knowledge):
    resp = client.get("/api/v2/academy/knowledge?course_id=climate-risk-finance")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["knowledge"]["course_id"] == "climate-risk-finance"
    assert len(data["knowledge"]["nodes"]) == len(knowledge["nodes"])
    assert data["knowledge"]["tracks"]
    assert data["knowledge"]["competencies"]


def test_knowledge_unknown_course(client):
    resp = client.get("/api/v2/academy/knowledge?course_id=nosuchcourse")
    assert resp.status_code == 404


def test_knowledge_requires_course_id(client):
    resp = client.get("/api/v2/academy/knowledge")
    assert resp.status_code == 400


# -----------------------------------------------------------------------------
# Learner model endpoint
# -----------------------------------------------------------------------------


def test_learner_model_requires_auth(client):
    resp = client.get("/api/v2/academy/learner-model?course_id=climate-risk-finance")
    assert resp.status_code in (401, 403)


def test_learner_model_after_correct_quiz(client, env, course, knowledge):
    user, token = _register_and_verify(client, env)
    module = course["modules"][0]
    resp = client.post(
        "/api/v2/academy/progress",
        json={"course_id": course["id"], "module_id": module["id"], "answers": _correct_answers(module)},
        headers=_auth(token),
    )
    assert resp.status_code == 200

    resp = client.get(f"/api/v2/academy/learner-model?course_id={course['id']}", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.get_json()
    model = data["model"]

    # Module concepts should be mastered.
    for q in module["quiz"]:
        for concept_id in q.get("concepts", []):
            concept = _concept_in_model(model, concept_id)
            assert concept is not None, f"concept {concept_id} missing from model"
            assert concept["mastery"] == 1.0
            assert concept["level"] == "mastered"

    # recommended_next should point to the first not-proficient concept in course order.
    concept_order = [n["id"] for n in knowledge["nodes"] if n["kind"] == "concept"]
    not_mastered = [
        cid for cid in concept_order
        if _concept_in_model(model, cid)["level"] != "mastered"
    ]
    assert data["model"]["recommended_next"]["concept_id"] == not_mastered[0]


def test_learner_model_after_wrong_quiz(client, env, course):
    user, token = _register_and_verify(client, env)
    module = course["modules"][0]
    client.post(
        "/api/v2/academy/progress",
        json={"course_id": course["id"], "module_id": module["id"], "answers": _all_wrong_answers(module)},
        headers=_auth(token),
    )

    resp = client.get(f"/api/v2/academy/learner-model?course_id={course['id']}", headers=_auth(token))
    assert resp.status_code == 200
    model = resp.get_json()["model"]

    for q in module["quiz"]:
        for concept_id in q.get("concepts", []):
            concept = _concept_in_model(model, concept_id)
            assert concept["level"] == "needs_attention"

    # Review schedule row should exist with last_result 0.
    from src.dashboard.verification_store import VerificationStore

    rows = VerificationStore().get_review_schedule(user["id"], course["id"])
    concept_ids = {c for q in module["quiz"] for c in q.get("concepts", [])}
    for concept_id in concept_ids:
        row = next((r for r in rows if r["concept_id"] == concept_id), None)
        assert row is not None, f"no schedule row for {concept_id}"
        assert row["last_result"] == 0


# -----------------------------------------------------------------------------
# Review scheduling
# -----------------------------------------------------------------------------


def test_review_schedule_future_due_empty_reviews(client, env, course):
    user, token = _register_and_verify(client, env)
    module = course["modules"][0]
    client.post(
        "/api/v2/academy/progress",
        json={"course_id": course["id"], "module_id": module["id"], "answers": _correct_answers(module)},
        headers=_auth(token),
    )

    from src.dashboard.verification_store import VerificationStore

    rows = VerificationStore().get_review_schedule(user["id"], course["id"])
    assert rows
    now = int(time.time())
    for r in rows:
        assert r["next_due_ts"] > now

    resp = client.get(f"/api/v2/academy/reviews/due?course_id={course['id']}", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.get_json()["due"] == []


def test_due_review_returns_stripped_questions(client, env, course, knowledge):
    user, token = _register_and_verify(client, env)
    module = course["modules"][0]
    # Any quiz submission creates schedule rows.
    client.post(
        "/api/v2/academy/progress",
        json={"course_id": course["id"], "module_id": module["id"], "answers": _correct_answers(module)},
        headers=_auth(token),
    )

    from src.dashboard.verification_store import VerificationStore

    store = VerificationStore()
    rows = store.get_review_schedule(user["id"], course["id"])
    assert rows
    # Force one row into the past.
    rows[0]["next_due_ts"] = int(time.time()) - 3600
    store.upsert_review_schedule(user["id"], course["id"], [rows[0]])

    resp = client.get(f"/api/v2/academy/reviews/due?course_id={course['id']}", headers=_auth(token))
    assert resp.status_code == 200
    due = resp.get_json()["due"]
    assert len(due) >= 1
    item = due[0]
    assert item["concept_id"]
    assert item["label"]
    assert item["module_id"]
    assert item["questions"]
    for q in item["questions"]:
        assert "correct_index" not in q
        assert "explanation" not in q
        assert "question" in q
        assert "options" in q


# -----------------------------------------------------------------------------
# Review submission endpoint
# -----------------------------------------------------------------------------


def _force_due_review(user_id, course):
    """Submit a correct quiz then force one schedule row into the past."""
    from src.dashboard.verification_store import VerificationStore

    store = VerificationStore()
    rows = store.get_review_schedule(user_id, course["id"])
    rows[0]["next_due_ts"] = int(time.time()) - 3600
    store.upsert_review_schedule(user_id, course["id"], [rows[0]])
    return rows[0]["concept_id"]


def _submit_module_correct(client, course, module_id, token):
    module = next(m for m in course["modules"] if m["id"] == module_id)
    resp = client.post(
        "/api/v2/academy/progress",
        json={"course_id": course["id"], "module_id": module_id, "answers": _correct_answers(module)},
        headers=_auth(token),
    )
    assert resp.status_code == 200


def test_review_correct_extends_interval(client, env, course):
    user, token = _register_and_verify(client, env)
    _submit_module_correct(client, course, "foundations", token)
    concept_id = _force_due_review(user["id"], course)

    # Use the original grading questions to get correct answers.
    from src.climate.academy import review_questions_for_concept, load_knowledge

    knowledge = load_knowledge()
    concept = next(n for n in knowledge["nodes"] if n["id"] == concept_id)
    grading_questions = review_questions_for_concept(course, concept_id, concept, include_answers=True)
    answers = [q["correct_index"] for q in grading_questions]

    resp = client.post(
        "/api/v2/academy/reviews",
        json={"course_id": course["id"], "concept_id": concept_id, "answers": answers},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["concept_id"] == concept_id
    assert data["score_correct"] == len(answers)
    assert data["passed"] is True
    assert data["schedule"]["interval_days"] > REVIEW_INITIAL_INTERVAL

    response_text = json.dumps(data)
    assert "correct_index" not in response_text
    assert "explanation" not in response_text


def test_review_wrong_resets_interval(client, env, course):
    user, token = _register_and_verify(client, env)
    _submit_module_correct(client, course, "foundations", token)
    concept_id = _force_due_review(user["id"], course)

    resp = client.get(f"/api/v2/academy/reviews/due?course_id={course['id']}", headers=_auth(token))
    item = resp.get_json()["due"][0]
    # Intentionally wrong answers: use the original correct_index and pick another option.
    from src.climate.academy import review_questions_for_concept, load_knowledge

    knowledge = load_knowledge()
    concept = next(n for n in knowledge["nodes"] if n["id"] == concept_id)
    grading_questions = review_questions_for_concept(course, concept_id, concept, include_answers=True)
    answers = []
    for q in grading_questions:
        correct = q["correct_index"]
        wrong = (correct + 1) % len(q["options"])
        if wrong == correct:
            wrong = (correct + 2) % len(q["options"])
        answers.append(wrong)

    resp = client.post(
        "/api/v2/academy/reviews",
        json={"course_id": course["id"], "concept_id": concept_id, "answers": answers},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["passed"] is False
    assert data["schedule"]["interval_days"] == REVIEW_FAIL_INTERVAL

    response_text = json.dumps(data)
    assert "correct_index" not in response_text
    assert "explanation" not in response_text


# -----------------------------------------------------------------------------
# Concept attempts accumulation
# -----------------------------------------------------------------------------


def test_concept_attempts_accumulate(client, env, course, knowledge):
    user, token = _register_and_verify(client, env)
    module = course["modules"][0]

    # First all correct.
    client.post(
        "/api/v2/academy/progress",
        json={"course_id": course["id"], "module_id": module["id"], "answers": _correct_answers(module)},
        headers=_auth(token),
    )
    # Then all wrong.
    client.post(
        "/api/v2/academy/progress",
        json={"course_id": course["id"], "module_id": module["id"], "answers": _all_wrong_answers(module)},
        headers=_auth(token),
    )

    resp = client.get(f"/api/v2/academy/learner-model?course_id={course['id']}", headers=_auth(token))
    model = resp.get_json()["model"]

    # Concepts tagged in only one question should have exactly two attempts → 0.5.
    tag_counts = {}
    for q in module["quiz"]:
        for c in q.get("concepts", []):
            tag_counts[c] = tag_counts.get(c, 0) + 1
    single_tagged = [c for c, count in tag_counts.items() if count == 1]
    assert single_tagged
    for concept_id in single_tagged:
        concept = _concept_in_model(model, concept_id)
        assert concept["mastery"] == 0.5, f"expected 0.5 for {concept_id}, got {concept['mastery']}"
        assert concept["level"] == "needs_attention"
