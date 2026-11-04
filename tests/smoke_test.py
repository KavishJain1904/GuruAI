"""End-to-end characterization test for the GuruAI HTTP surface.

Runs against a throwaway Postgres database (created and dropped for this run
only), so it never touches the real app database. Exercises every endpoint
that does not require a live LLM call, plus a full route-table snapshot.

Requires a reachable Postgres server with the pgvector extension available
(set via DATABASE_URL, or defaults to the local dev instance used throughout
this migration: postgresql://guruai:guruai_dev_pw@localhost:5432/guruai_dev).
This is a real change from the old SQLite-backed version of this test, which
needed zero external services — worth knowing if this test is ever wired
into CI.

Run with:  python tests/smoke_test.py
Exits non-zero on the first failure.
"""
import atexit
import json
import os
import sys
import uuid
from unittest.mock import patch
from urllib.parse import urlparse, urlunparse

import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Create a throwaway Postgres database BEFORE importing the app ──
_BASE_DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://guruai:guruai_dev_pw@localhost:5432/guruai_dev"
)
_parsed = urlparse(_BASE_DATABASE_URL)
_TEST_DB_NAME = f"test_{uuid.uuid4().hex[:12]}"
_ADMIN_URL = urlunparse(_parsed._replace(path="/postgres"))
_TEST_DB_URL = urlunparse(_parsed._replace(path=f"/{_TEST_DB_NAME}"))


def _admin_execute(sql: str) -> None:
    conn = psycopg2.connect(_ADMIN_URL)
    conn.autocommit = True  # CREATE DATABASE / DROP DATABASE can't run inside a transaction
    try:
        conn.cursor().execute(sql)
    finally:
        conn.close()


_admin_execute(f'CREATE DATABASE "{_TEST_DB_NAME}"')
atexit.register(_admin_execute, f'DROP DATABASE IF EXISTS "{_TEST_DB_NAME}"')

# get_db() registers the pgvector type on every connection, which fails if the
# extension doesn't exist yet — create it here, before any app code connects.
_bootstrap_conn = psycopg2.connect(_TEST_DB_URL)
_bootstrap_conn.autocommit = True
_bootstrap_conn.cursor().execute("CREATE EXTENSION IF NOT EXISTS vector;")
_bootstrap_conn.close()

import src.core.database as database  # noqa: E402
database.DATABASE_URL = _TEST_DB_URL

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402

database.init_db()

_failures = []
_checks = 0


def check(label, actual, expected):
    global _checks
    _checks += 1
    if actual != expected:
        _failures.append(f"{label}\n     expected: {expected!r}\n     actual:   {actual!r}")
        print(f"  FAIL  {label}")
    else:
        print(f"  ok    {label}")


def check_true(label, cond, detail=""):
    check(label + (f" ({detail})" if detail else ""), bool(cond), True)


def section(name):
    print(f"\n=== {name} ===")


# Exercise the additive upgrade against an actual populated legacy schema.
# This database is disposable and contains no app/user data.
section("legacy SRS schema upgrade")
with database.get_db() as conn:
    cur = conn.cursor()
    cur.execute("DROP TABLE review_events")
    cur.execute("ALTER TABLE knowledge_profile DROP COLUMN review_success_streak")
    cur.execute("INSERT INTO users (username, password_hash) VALUES ('legacy_fixture', 'unused') RETURNING id")
    legacy_user = cur.fetchone()["id"]
    cur.execute("""INSERT INTO knowledge_profile
        (user_id, subject, topic, correct, total, ema_score, review_count, next_review_date)
        VALUES (%s, 'Legacy', 'Topic', 2, 3, 0.6, 9, '2026-12-01') RETURNING id""", (legacy_user,))
    legacy_topic = cur.fetchone()["id"]
    conn.commit()
database.init_db()
with database.get_db() as conn:
    cur = conn.cursor()
    cur.execute("SELECT correct, total, review_count, review_success_streak, next_review_date FROM knowledge_profile WHERE id = %s", (legacy_topic,))
    legacy = cur.fetchone()
    check("upgrade preserves quiz counts", [legacy["correct"], legacy["total"]], [2, 3])
    check("upgrade preserves attempt count", legacy["review_count"], 9)
    check("upgrade starts unknown success streak at zero", legacy["review_success_streak"], 0)
    check("upgrade preserves existing due date", legacy["next_review_date"].date().isoformat(), "2026-12-01")
    cur.execute("SELECT COUNT(*) AS n FROM review_events")
    check("upgrade does not invent historical reviews", cur.fetchone()["n"], 0)
    cur.execute("DELETE FROM users WHERE id = %s", (legacy_user,))
    conn.commit()

client = TestClient(server.app)

# ── Auth ──────────────────────────────────────────────────────────────
section("auth")
r = client.post("/api/auth/register", json={"username": "Alice", "password": "pw123"})
check("register 200", r.status_code, 200)
check("register status ok", r.json()["status"], "ok")
check_true("auth cookie set", "access_token" in r.cookies or "access_token" in client.cookies)
USER_ID = r.json()["user_id"]

r = client.post("/api/auth/register", json={"username": "alice", "password": "pw123"})
check("duplicate username rejected (case-normalized)", r.status_code, 400)

r = client.post("/api/auth/register", json={"username": "", "password": "pw"})
check("empty username rejected", r.status_code, 400)

r = client.post("/api/auth/login", json={"username": "alice", "password": "wrong"})
check("bad password rejected", r.status_code, 400)

r = client.post("/api/auth/login", json={"username": "ALICE", "password": "pw123"})
check("login 200 (case-insensitive)", r.status_code, 200)

# ── Unauthenticated access ────────────────────────────────────────────
section("auth gating")
anon = TestClient(server.app)
check("anon /api/sessions -> 401", anon.get("/api/sessions").status_code, 401)
check("anon /api/profile -> 401", anon.get("/api/profile").status_code, 401)
check("anon /api/user/stats -> 401", anon.get("/api/user/stats").status_code, 401)
r = anon.get("/", follow_redirects=False)
check("anon / -> redirect", r.status_code, 307)
check("anon / -> /login.html", r.headers["location"], "/login.html")
r = client.get("/login.html", follow_redirects=False)
check("logged-in /login.html -> redirect", r.status_code, 307)
check("logged-in /login.html -> /index.html", r.headers["location"], "/index.html")
r = client.get("/", follow_redirects=False)
check("logged-in / -> 200", r.status_code, 200)

# ── Sessions ──────────────────────────────────────────────────────────
section("sessions")
check("sessions initially empty", client.get("/api/sessions").json(), {})

r = client.post("/api/sessions")
check("create session 200", r.status_code, 200)
SID = r.json()["session_id"]
check_true("session_id is uuid-shaped", len(SID) == 36)

sessions = client.get("/api/sessions").json()
check("one session listed", len(sessions), 1)
check("default title", sessions[SID]["title"], "New Chat")
check("no messages yet", sessions[SID]["messages"], [])
check("no documents yet", sessions[SID]["documents"], [])

r = client.patch(f"/api/sessions/{SID}/title", data={"title": "Renamed"})
check("rename 200", r.status_code, 200)
check("title persisted", client.get("/api/sessions").json()[SID]["title"], "Renamed")

check("messages empty", client.get(f"/api/sessions/{SID}/messages").json(), [])
check("db-status false", client.get(f"/api/sessions/{SID}/db-status").json(), {"exists": False})
check("documents empty", client.get(f"/api/sessions/{SID}/documents").json(), [])
check("quiz empty", client.get(f"/api/sessions/{SID}/quiz").json(), {})

# ── Cross-user isolation ──────────────────────────────────────────────
section("cross-user isolation")
other = TestClient(server.app)
other.post("/api/auth/register", json={"username": "bob", "password": "pw"})
check("bob sees no sessions", other.get("/api/sessions").json(), {})
check("bob cannot read alice's messages", other.get(f"/api/sessions/{SID}/messages").status_code, 403)
check("bob cannot rename alice's session",
      other.patch(f"/api/sessions/{SID}/title", data={"title": "hax"}).status_code, 403)
check("bob cannot delete alice's session", other.delete(f"/api/sessions/{SID}").status_code, 403)
check("missing session -> 404", client.get("/api/sessions/no-such-id/messages").status_code, 404)

# ── Quiz answers drive the knowledge profile ──────────────────────────
section("quiz answers -> profile")
check("profile initially empty", client.get("/api/profile").json(), {})

for correct in (True, True, False):
    r = client.post("/api/quiz/answer", json={
        "session_id": SID, "subject": "biology", "topic": "mitosis", "is_correct": correct,
    })
    check(f"submit answer correct={correct}", r.status_code, 200)

profile = client.get("/api/profile").json()
check("subject title-cased", list(profile.keys()), ["Biology"])
buckets = profile["Biology"]
tracked = [t for lvl in buckets.values() for t in lvl]
check("one topic tracked", len(tracked), 1)
check("topic title-cased", tracked[0][0], "Mitosis")
check("correct count", tracked[0][2], 2)
check("total count", tracked[0][3], 3)

stats = client.get("/api/user/stats").json()
check("total_questions", stats["total_questions"], 3)
check_true("average_mastery_pct is a number", isinstance(stats["average_mastery_pct"], (int, float)))

# ── Spaced repetition ─────────────────────────────────────────────────
section("spaced repetition")
tstats = client.get("/api/topics/statistics").json()
check("total_topics", tstats["total_topics"], 1)
check("strongest_topic", tstats["strongest_topic"], "Mitosis")

rq = client.get("/api/suggestions/review-queue").json()
check("review queue total_topics", rq["total_topics"], 1)
check_true("queue is a list", isinstance(rq["queue"], list))
check("bad category rejected",
      client.get("/api/suggestions/review-queue", params={"category": "bogus"}).status_code, 422)
check("bad sort rejected",
      client.get("/api/suggestions/review-queue", params={"sort": "bogus"}).status_code, 422)
check("limit out of range rejected",
      client.get("/api/suggestions/review-queue", params={"limit": 999}).status_code, 422)

# Find the topic id so we can mark it reviewed
topic_id = None
for lvl in client.get("/api/profile").json()["Biology"].values():
    if lvl:
        from src.personalization import mastery as _m
        for row in _m.list_topics_with_schedule(USER_ID):
            if row["topic"] == "Mitosis":
                topic_id = row["id"]
check_true("found topic id", topic_id is not None)

r = client.post(f"/api/topics/{topic_id}/mark-reviewed", json={"score": 8, "notes": "Reviewed cell division <notes>"})
check("mark-reviewed 200", r.status_code, 200)
check("mark-reviewed topic", r.json()["topic"], "Mitosis")
check_true("next_review returned", r.json()["next_review"] is not None)
profile_after_rating = client.get("/api/profile").json()["Biology"]
rated_topic = [t for group in profile_after_rating.values() for t in group][0]
check("self-rating leaves quiz correct/total unchanged", rated_topic[2:], [2, 3])
check("self-rating leaves total_questions unchanged", client.get("/api/user/stats").json()["total_questions"], 3)
check_true("self-rating still updates mastery", rated_topic[1] > tracked[0][1])
check("score > 10 rejected",
      client.post(f"/api/topics/{topic_id}/mark-reviewed", json={"score": 11}).status_code, 400)
check("score < 0 rejected",
      client.post(f"/api/topics/{topic_id}/mark-reviewed", json={"score": -1}).status_code, 400)
check("unknown topic -> 404",
      client.post("/api/topics/999999/mark-reviewed", json={"score": 5}).status_code, 404)
check("bob cannot review alice's topic",
      other.post(f"/api/topics/{topic_id}/mark-reviewed", json={"score": 5}).status_code, 404)

# SRS regressions: history, ownership, failure scheduling and shared bands.
section("SRS regressions")
history = client.get("/api/reviews").json()
check("all quiz and self-rating events recorded", len(history["items"]), 4)
check("self-rating event distinguished", history["items"][0]["kind"], "self_rating")
check("review notes persisted", history["items"][0]["notes"], "Reviewed cell division <notes>")
check("quiz failure event recorded", history["items"][1]["score"], 0.0)
check("history has owner", history["items"][0]["user_id"], USER_ID)
check("bob cannot read alice topic history", other.get("/api/reviews", params={"topic_id": topic_id}).status_code, 404)
check("bob history empty", other.get("/api/reviews").json()["items"], [])
check("anonymous history denied", anon.get("/api/reviews").status_code, 401)
check("history limit validated", client.get("/api/reviews", params={"limit": 101}).status_code, 422)
check("negative offset rejected", client.get("/api/reviews", params={"offset": -1}).status_code, 422)
page = client.get("/api/reviews", params={"limit": 2}).json()
check("history pagination limit", len(page["items"]), 2)
check("history more flag", page["has_more"], True)
page2 = client.get("/api/reviews", params={"limit": 2, "offset": 2}).json()
check("history final page flag", page2["has_more"], False)
check_true("pages do not overlap", not ({x["id"] for x in page["items"]} & {x["id"] for x in page2["items"]}))
database.init_db()
check("schema upgrade is idempotent", len(client.get("/api/reviews").json()["items"]), 4)

# Both the scheduler and dashboard must classify the exact boundary the same way.
for score, category in ((0.3, "weak"), (0.5, "average"), (0.7, "average"), (0.75, "average"), (0.76, "strong")):
    with database.get_db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE knowledge_profile SET ema_score = %s WHERE id = %s", (score, topic_id))
        conn.commit()
    check(f"profile band at {score}", len(client.get("/api/profile").json()["Biology"][category]), 1)
    check(f"schedule band at {score}", _m.get_topic_by_id(topic_id, USER_ID)["mastery_category"].lower(), category)

with database.get_db() as conn:
    cur = conn.cursor()
    cur.execute("UPDATE knowledge_profile SET ema_score = 0.95, review_success_streak = 40, review_count = 50 WHERE id = %s", (topic_id,))
    conn.commit()
for attempt in range(3):
    r = client.post("/api/quiz/answer", json={
        "session_id": SID, "subject": "Biology", "topic": "Mitosis", "is_correct": False,
        "question": "What does mitosis produce?", "selected_answer": "Four cells", "correct_answer": "Two cells",
    })
    check(f"failure after long streak recorded {attempt}", r.status_code, 200)
    event = client.get("/api/reviews").json()["items"][0]
    check("failure stays due tomorrow", event["review_interval_days"], 1)
    check("answer text saved", event["selected_answer"], "Four cells")
with database.get_db() as conn:
    cur = conn.cursor()
    cur.execute("SELECT review_success_streak, review_count FROM knowledge_profile WHERE id = %s", (topic_id,))
    row = cur.fetchone()
check("failures reset success streak", row["review_success_streak"], 0)
check("attempt count remains truthful", row["review_count"], 53)

before_questions = client.get("/api/user/stats").json()["total_questions"]
r = client.post(f"/api/topics/{topic_id}/mark-reviewed", json={"score": 0, "notes": "Forgot this"})
check("low self-rating recorded", r.status_code, 200)
check("low self-rating due tomorrow", client.get("/api/reviews").json()["items"][0]["review_interval_days"], 1)
check("low self-rating leaves quiz totals unchanged", client.get("/api/user/stats").json()["total_questions"], before_questions)

# A history write failure must roll back the mastery/schedule change too.
before_profile = client.get("/api/profile").json()
before_history = client.get("/api/reviews").json()
with patch.object(_m, "_record_review", side_effect=RuntimeError("simulated history failure")):
    try:
        client.post(f"/api/topics/{topic_id}/mark-reviewed", json={"score": 10})
    except RuntimeError:
        pass
    else:
        check_true("history failure propagates", False)
check("failed history write rolls back mastery", client.get("/api/profile").json(), before_profile)
check("failed history write adds no event", client.get("/api/reviews").json(), before_history)

# Topic-page answers no longer silently disappear when there is no last chat session.
r = client.post("/api/quiz/answer", json={
    "subject": "Biology", "topic": "Mitosis", "is_correct": True,
    "question": "Standalone topic question", "selected_answer": "A", "correct_answer": "A",
})
check("standalone topic answer recorded", r.status_code, 200)
event = client.get("/api/reviews").json()["items"][0]
check("standalone event has no unrelated session", event["session_id"], None)
check("standalone question retained", event["question"], "Standalone topic question")

# Identical topic names in different subjects must remain distinguishable, and a
# review opened from the due queue must update exactly the selected record.
duplicate = client.post("/api/quiz/answer", json={
    "subject": "Physics", "topic": "Mitosis", "is_correct": False,
})
check("same-name topic in another subject recorded", duplicate.status_code, 200)
duplicate_id = duplicate.json()["topic_id"]
stats = client.get("/api/topics/statistics").json()
check("strongest topic subject exposed", stats["strongest_subject"], "Biology")
check("weakest topic subject exposed", stats["weakest_subject"], "Physics")
before_biology = _m.get_topic_by_id(topic_id, USER_ID)["mastery_level"]
exact = client.post("/api/quiz/answer", json={
    "topic_id": duplicate_id, "subject": "Biology", "topic": "Mitosis", "is_correct": True,
})
check("exact review topic recorded", exact.status_code, 200)
check("exact review topic id returned", exact.json()["topic_id"], duplicate_id)
check("other same-name record unchanged", _m.get_topic_by_id(topic_id, USER_ID)["mastery_level"], before_biology)
check("another user cannot update topic by id", other.post("/api/quiz/answer", json={
    "topic_id": duplicate_id, "subject": "Physics", "topic": "Mitosis", "is_correct": True,
}).status_code, 404)
with database.get_db() as conn:
    cur = conn.cursor()
    cur.execute("DELETE FROM review_events WHERE topic_id = %s", (duplicate_id,))
    cur.execute("DELETE FROM knowledge_profile WHERE id = %s", (duplicate_id,))
    conn.commit()

# ── Subjects ──────────────────────────────────────────────────────────
# Both names used here are in topic_graph_seed.CURATED_SEEDS — adding a
# subject kicks off curriculum-graph seeding as a background task, which
# TestClient runs synchronously within the request; an uncurated name would
# fall through to a live Groq call and break this test's "no API keys needed"
# guarantee.
section("subjects")
check("no subjects initially", client.get("/api/subjects").json(), {"subjects": []})
r = client.post("/api/subjects", json={"subject": "Data Structures"})
check("add subject", r.json()["subjects"], ["Data Structures"])
client.post("/api/subjects", json={"subject": "Operating Systems"})
check("two subjects", sorted(client.get("/api/subjects").json()["subjects"]), ["Data Structures", "Operating Systems"])
r = client.delete("/api/subjects/Data Structures")
check("delete subject", r.json()["subjects"], ["Operating Systems"])
check("bob's subjects isolated", other.get("/api/subjects").json(), {"subjects": []})

# ── Memory (DB-only paths; extraction needs an LLM) ───────────────────
section("memory")
check("memory initially empty", client.get("/api/memory").json(), {"items": []})
check("memory chat history empty", client.get("/api/memory/chat").json(), {"history": []})
import src.personalization.user_memory as um
um.add_memory_items(USER_ID, ["prefers worked examples", "studying for finals"])
check("two memory items", len(client.get("/api/memory").json()["items"]), 2)
r = client.delete("/api/memory/0")
check("delete by index leaves one", len(r.json()["items"]), 1)
check("clear all", client.delete("/api/memory").json(), {"items": []})

# ── User profile ──────────────────────────────────────────────────────
section("user profile")
prof = client.get("/api/user/profile").json()
check("default name", prof["name"], "The Scholar")
r = client.post("/api/user/profile", json={"name": "Alice A", "bio": "bio text"})
check("profile saved name", r.json()["name"], "Alice A")
check("profile persisted", client.get("/api/user/profile").json()["bio"], "bio text")

# ── Profile topic deletion ────────────────────────────────────────────
section("profile deletion")
r = client.delete("/api/profile/Biology/Mitosis")
check("delete topic 200", r.status_code, 200)
check("profile empty after delete", client.get("/api/profile").json(), {})
check("topic deletion clears its history", client.get("/api/reviews").json()["items"], [])

# ── Chat/quiz guards (no LLM call — these fail before reaching one) ───
section("llm-free guards")
check("chat without vectorstore -> 400",
      client.post("/api/chat", json={"session_id": SID, "question": "hi"}).status_code, 400)
check("quiz without vectorstore -> 400",
      client.post(f"/api/sessions/{SID}/quiz").status_code, 400)
check("bob cannot chat in alice's session",
      other.post("/api/chat", json={"session_id": SID, "question": "hi"}).status_code, 403)

# ── Session deletion cascades ─────────────────────────────────────────
section("session deletion")
from src.sessions import store as _store
_store.add_message(SID, "user", "hello")
check("message added", len(client.get(f"/api/sessions/{SID}/messages").json()), 1)
check("delete session", client.delete(f"/api/sessions/{SID}").json(), {"status": "deleted"})
check("sessions empty after delete", client.get("/api/sessions").json(), {})
check("messages 404 after delete", client.get(f"/api/sessions/{SID}/messages").status_code, 404)

# ── Logout ────────────────────────────────────────────────────────────
section("logout")
check("logout 200", client.post("/api/auth/logout").status_code, 200)
check("sessions 401 after logout", client.get("/api/sessions").status_code, 401)

# ── Route table snapshot ──────────────────────────────────────────────
section("route table")
try:
    from fastapi.routing import iter_route_contexts
    route_entries = iter_route_contexts(server.app.routes)
except ImportError:  # Older FastAPI versions materialize included routers eagerly.
    route_entries = server.app.routes
routes = sorted(
    (r.path, ",".join(sorted(getattr(r, "methods", []) or [])))
    for r in route_entries if r.path is not None
)
snapshot = os.path.join(os.path.dirname(os.path.abspath(__file__)), "routes_snapshot.json")
if os.path.exists(snapshot):
    expected = [tuple(x) for x in json.load(open(snapshot))]
    check("route table unchanged", routes, expected)
    if routes != expected:
        for missing in sorted(set(expected) - set(routes)):
            print(f"     MISSING: {missing}")
        for added in sorted(set(routes) - set(expected)):
            print(f"     ADDED:   {added}")
else:
    json.dump(routes, open(snapshot, "w"), indent=1)
    print(f"  ..    wrote baseline snapshot ({len(routes)} routes)")

# ── Report ────────────────────────────────────────────────────────────
database.close_pool()  # database.py pools connections; DROP DATABASE fails while one's still attached
_admin_execute(f'DROP DATABASE IF EXISTS "{_TEST_DB_NAME}"')
print("\n" + "=" * 60)
if _failures:
    print(f"FAILED — {len(_failures)} of {_checks} checks\n")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print(f"PASSED — all {_checks} checks")
