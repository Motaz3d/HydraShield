"""Tests for the Talaix Academy feature.

Uses the real config JSON files and verifies server-side grading, progress
persistence, certificate eligibility and honest certificate wording.
"""

import json
import os

import pytest

os.environ["HYDRASHIELD_CACHE_DB"] = "/tmp/hydrashield_test_academy_cache.sqlite3"
if os.path.exists(os.environ["HYDRASHIELD_CACHE_DB"]):
    os.remove(os.environ["HYDRASHIELD_CACHE_DB"])

from src.climate.academy import load_course, load_glossary  # noqa: E402
from src.dashboard.api import create_app  # noqa: E402


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Isolated DB + outbox per test."""
    db_path = tmp_path / "academy.sqlite3"
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


# -----------------------------------------------------------------------------
# Endpoint tests
# -----------------------------------------------------------------------------


def test_courses_public(client, course):
    resp = client.get("/api/v2/academy/courses")
    assert resp.status_code == 200
    data = resp.get_json()
    assert any(c["id"] == course["id"] for c in data["courses"])


def test_course_public_strips_answers(client, course):
    resp = client.get(f"/api/v2/academy/courses/{course['id']}")
    assert resp.status_code == 200
    public = resp.get_json()["course"]
    for module in public["modules"]:
        for q in module["quiz"]:
            assert "correct_index" not in q
            assert "explanation" not in q
            assert "question" in q
            assert "options" in q


def test_unknown_course(client):
    resp = client.get("/api/v2/academy/courses/nosuchcourse")
    assert resp.status_code == 404


def test_glossary_public(client):
    resp = client.get("/api/v2/academy/glossary")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["terms"]) >= 18
    term = data["terms"][0]
    assert term["id"] and term["term"] and term["short"] and term["long"]


def test_glossary_term(client):
    term = load_glossary()["terms"][0]
    resp = client.get(f"/api/v2/academy/glossary/{term['id']}")
    assert resp.status_code == 200
    assert resp.get_json()["term"]["id"] == term["id"]


def test_progress_requires_auth(client):
    resp = client.post("/api/v2/academy/progress", json={
        "course_id": "climate-risk-finance",
        "module_id": "foundations",
        "answers": [0, 0, 0],
    })
    assert resp.status_code in (401, 403)


def test_grade_correct_answers_pass(client, env, course):
    user, token = _register_and_verify(client, env)
    module = course["modules"][0]
    answers = _correct_answers(module)
    resp = client.post("/api/v2/academy/progress", json={
        "course_id": course["id"],
        "module_id": module["id"],
        "answers": answers,
    }, headers=_auth(token))
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    assert data["score_correct"] == len(answers)
    assert data["passed"] is True
    assert data["results"][0]["explanation"]

    progress = client.get(f"/api/v2/academy/progress?course_id={course['id']}", headers=_auth(token)).get_json()["progress"]
    assert any(p["module_id"] == module["id"] and p["passed"] for p in progress)


def test_grade_wrong_answers_fail(client, env, course):
    user, token = _register_and_verify(client, env)
    module = course["modules"][0]
    answers = _all_wrong_answers(module)
    resp = client.post("/api/v2/academy/progress", json={
        "course_id": course["id"],
        "module_id": module["id"],
        "answers": answers,
    }, headers=_auth(token))
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["passed"] is False
    assert data["score_correct"] == 0


def test_grade_keeps_best_score(client, env, course):
    user, token = _register_and_verify(client, env)
    module = course["modules"][0]
    # First attempt: wrong.
    client.post("/api/v2/academy/progress", json={
        "course_id": course["id"],
        "module_id": module["id"],
        "answers": _all_wrong_answers(module),
    }, headers=_auth(token))
    # Second attempt: correct.
    client.post("/api/v2/academy/progress", json={
        "course_id": course["id"],
        "module_id": module["id"],
        "answers": _correct_answers(module),
    }, headers=_auth(token))

    progress = client.get(f"/api/v2/academy/progress?course_id={course['id']}", headers=_auth(token)).get_json()["progress"]
    row = next(p for p in progress if p["module_id"] == module["id"])
    assert row["best_correct"] == len(module["quiz"])
    assert row["passed"] is True


def test_pass_threshold_three_question_module(client, env, course):
    """A 3-question module requires 3/3 (ceil(0.7*3)=3)."""
    user, token = _register_and_verify(client, env)
    module = next(m for m in course["modules"] if len(m["quiz"]) == 3)
    answers = _correct_answers(module)
    answers[0] = (answers[0] + 1) % len(module["quiz"][0]["options"])  # 2/3
    resp = client.post("/api/v2/academy/progress", json={
        "course_id": course["id"],
        "module_id": module["id"],
        "answers": answers,
    }, headers=_auth(token))
    data = resp.get_json()
    assert data["score_correct"] == 2
    assert data["score_total"] == 3
    assert data["pass_threshold"] == 3
    assert data["passed"] is False


def test_certificate_blocked_until_eligible(client, env, course):
    user, token = _register_and_verify(client, env)
    # Pass only the first module.
    first = course["modules"][0]
    client.post("/api/v2/academy/progress", json={
        "course_id": course["id"],
        "module_id": first["id"],
        "answers": _correct_answers(first),
    }, headers=_auth(token))

    resp = client.post("/api/v2/academy/certificate", json={
        "course_id": course["id"],
    }, headers=_auth(token))
    assert resp.status_code == 409, resp.get_json()
    body = resp.get_json()
    assert "missing_modules" in body
    assert len(body["missing_modules"]) == len(course["modules"]) - 1


def test_full_certificate_flow(client, env, course):
    pytest.importorskip("reportlab")
    user, token = _register_and_verify(client, env)

    for module in course["modules"]:
        resp = client.post("/api/v2/academy/progress", json={
            "course_id": course["id"],
            "module_id": module["id"],
            "answers": _correct_answers(module),
        }, headers=_auth(token))
        assert resp.status_code == 200
        assert resp.get_json()["passed"] is True

    resp = client.post("/api/v2/academy/certificate", json={
        "course_id": course["id"],
    }, headers=_auth(token))
    assert resp.status_code == 200, resp.get_json()
    cert = resp.get_json()["certificate"]
    assert cert["certificate_id"]
    assert cert["course_id"] == course["id"]
    assert cert["score_total"] == sum(len(m["quiz"]) for m in course["modules"])
    assert cert["score_correct"] == cert["score_total"]

    # Idempotent second issue returns same id.
    resp2 = client.post("/api/v2/academy/certificate", json={
        "course_id": course["id"],
    }, headers=_auth(token))
    assert resp2.get_json()["certificate"]["certificate_id"] == cert["certificate_id"]

    pdf_resp = client.get(f"/api/v2/academy/certificate/pdf?course_id={course['id']}", headers=_auth(token))
    assert pdf_resp.status_code == 200
    assert pdf_resp.mimetype == "application/pdf"
    assert pdf_resp.data[:5] == b"%PDF-"

    # Public verify.
    verify = client.get(f"/api/v2/academy/certificates/{cert['certificate_id']}/verify").get_json()
    assert verify["valid"] is True
    assert verify["course_title"] == course["title"]
    assert verify["score_correct"] == cert["score_correct"]

    # Fake verify.
    fake = client.get("/api/v2/academy/certificates/nosuchcert/verify").get_json()
    assert fake["valid"] is False


def test_certificate_verify_honest_note(client, env, course):
    user, token = _register_and_verify(client, env)
    for module in course["modules"]:
        client.post("/api/v2/academy/progress", json={
            "course_id": course["id"],
            "module_id": module["id"],
            "answers": _correct_answers(module),
        }, headers=_auth(token))
    cert_resp = client.post("/api/v2/academy/certificate", json={"course_id": course["id"]}, headers=_auth(token))
    cert = cert_resp.get_json()["certificate"]

    verify = client.get(f"/api/v2/academy/certificates/{cert['certificate_id']}/verify").get_json()
    note = verify.get("note", "").lower()
    assert "not an accredited academic qualification" in note
    assert "professional certification" in note
