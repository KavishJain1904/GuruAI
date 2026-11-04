"""Populate a ready-to-explore demo account.

Intended for public demo deployments (e.g. Hugging Face Spaces) so a reviewer can
sign in and immediately see a populated dashboard and a working RAG chat without
registering or uploading anything.

Idempotent: if the demo user already exists, seeding is skipped. On a host with
an ephemeral filesystem (HF free Spaces) the app re-seeds on each boot, because a
fresh disk means the demo user is gone again.

Run standalone:      python -m scripts.seed_demo
Or automatically:    set SEED_DEMO=1 and start the server (see server.py startup).

Credentials (override via env):
    DEMO_USERNAME (default "demo")
    DEMO_PASSWORD (default "demo1234")
"""
import os

from src.auth.auth import hash_password
from src.core.database import get_db, init_db
from src.personalization import mastery, user_memory
from src.rag.embedder import create_vectorstore
from src.rag.loader import load_documents
from src.sessions import documents as documents_store
from src.sessions import store

DEMO_USERNAME = os.getenv("DEMO_USERNAME", "demo").strip().lower()
DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "demo1234")

# A small, self-contained "textbook" so the demo's RAG chat has something real to
# retrieve and cite. Kept short to keep cold-start embedding fast.
_DEMO_DOC = """Operating Systems — Study Notes

Processes and Threads
A process is a program in execution, with its own memory space and resources. A
thread is the smallest unit of execution within a process; threads of the same
process share that process's memory but have their own stack and registers.
Context switching between threads is cheaper than between processes because the
memory map does not change.

CPU Scheduling
The scheduler decides which ready process runs next. Round Robin gives each
process a fixed time slice in turn, which is fair and responsive for interactive
systems. Shortest Job First minimizes average waiting time but can starve long
jobs. Priority scheduling runs the highest-priority job first and can also lead
to starvation, which aging mitigates by slowly raising a waiting job's priority.

Deadlock
A deadlock occurs when a set of processes are each waiting for a resource held by
another, so none can proceed. The four Coffman conditions — mutual exclusion,
hold and wait, no preemption, and circular wait — must all hold for a deadlock.
Breaking any one of them prevents deadlock.

Virtual Memory
Virtual memory lets a process address more memory than physically exists by
paging inactive pages out to disk. A page fault occurs when a referenced page is
not resident and must be loaded. Thrashing is when the system spends more time
paging than doing useful work, usually because too many processes compete for too
little physical memory.
"""

# (subject, topic, sequence of correct/incorrect answers) — shapes realistic EMA
# scores and spaced-repetition schedules spanning all three buckets. The EMA
# (alpha 0.3, starting at 0) needs a clean run of correct answers to reach the
# >75% "strong" band, so the sequences are tuned to land one topic in each of
# weak / average / strong for a well-rounded demo dashboard.
_DEMO_PERFORMANCE = [
    ("Operating Systems", "CPU Scheduling", [True, True, True, True, True]),    # ~83% strong
    ("Operating Systems", "Deadlock", [True, False, True, True]),               # ~61% average
    ("Operating Systems", "Virtual Memory", [False, False, True, False]),       # ~21% weak
    ("Computer Networks", "TCP Handshake", [True, True, False, True]),          # ~55% average
]

_DEMO_MEMORY = [
    "Prefers explanations with real-world analogies",
    "Second-year computer science student",
    "Studying for end-semester exams",
]

_DEMO_SUBJECTS = ["Operating Systems", "Computer Networks"]


def _get_or_create_demo_user() -> tuple[int, bool]:
    """Return (user_id, created). created is False if the demo user already existed."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE username = %s", (DEMO_USERNAME,))
        row = cur.fetchone()
        if row:
            return row["id"], False
        cur.execute(
            "INSERT INTO users (username, password_hash, name) VALUES (%s, %s, %s) RETURNING id",
            (DEMO_USERNAME, hash_password(DEMO_PASSWORD), "Demo Student"),
        )
        new_id = cur.fetchone()["id"]
        conn.commit()
        return new_id, True


def seed_demo() -> None:
    """Create and populate the demo account. No-op if it already exists."""
    init_db()  # safe to call repeatedly; ensures schema exists before we write
    user_id, created = _get_or_create_demo_user()
    if not created:
        print(f"[seed_demo] user '{DEMO_USERNAME}' already exists — skipping.")
        return

    print(f"[seed_demo] creating demo content for '{DEMO_USERNAME}' …")

    # 1. Subjects + long-term memory (populates the profile/memory pages)
    for subject in _DEMO_SUBJECTS:
        user_memory.save_subject(user_id, subject)
    user_memory.add_memory_items(user_id, _DEMO_MEMORY)

    # 2. A RAG session with a real, retrievable document (makes chat work)
    rag_session = store.create_session(user_id, "Operating Systems — Demo")
    chunks = load_documents([("os_notes.txt", _DEMO_DOC.encode("utf-8"), "demo-os-doc")])
    if chunks:
        create_vectorstore(chunks, rag_session)
        documents_store.add_document(
            rag_session, "demo-os-doc", "os_notes.txt", len(_DEMO_DOC),
            "txt", status="ready", chunk_count=len(chunks),
        )

    # 3. Quiz history → knowledge profile + spaced-repetition schedule.
    #    update_topic_performance derives the user from a session, so route these
    #    through a throwaway session tied to the demo user.
    perf_session = store.create_session(user_id, "Practice History")
    for subject, topic, answers in _DEMO_PERFORMANCE:
        for correct in answers:
            mastery.update_topic_performance(perf_session, subject, topic, correct)

    print(f"[seed_demo] done. Login: {DEMO_USERNAME} / {DEMO_PASSWORD}")


if __name__ == "__main__":
    seed_demo()
