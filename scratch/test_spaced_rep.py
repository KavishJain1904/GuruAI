"""Manual test script for the spaced-repetition scheduler and mastery integration.
Run with: python scratch/test_spaced_rep.py
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Point the app at a throwaway SQLite file before importing anything that opens it.
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
import src.core.database as database
database.DB_FILE = _tmp_db.name

from src.core.database import init_db, get_db
from src.personalization.spaced_rep import SpacedRepetitionScheduler
from src.personalization import mastery

init_db()

passed = 0
failed = 0


def check(label, condition):
    global passed, failed
    if condition:
        print(f"PASS: {label}")
        passed += 1
    else:
        print(f"FAIL: {label}")
        failed += 1


# ── 1. Base interval per mastery category ──
scheduler = SpacedRepetitionScheduler()
base_date = datetime(2024, 7, 15)

weak_next = scheduler.calculate_next_review_date(0.1, 0, base_date)
avg_next = scheduler.calculate_next_review_date(0.5, 0, base_date)
strong_next = scheduler.calculate_next_review_date(0.9, 0, base_date)

check("Weak mastery -> 1 day base interval", weak_next == base_date + timedelta(days=1))
check("Average mastery -> 3 day base interval", avg_next == base_date + timedelta(days=3))
check("Strong mastery -> 7 day base interval", strong_next == base_date + timedelta(days=7))

check("get_mastery_category(0.1) == Weak", scheduler.get_mastery_category(0.1) == "Weak")
check("get_mastery_category(0.5) == Average", scheduler.get_mastery_category(0.5) == "Average")
check("get_mastery_category(0.9) == Strong", scheduler.get_mastery_category(0.9) == "Strong")

# ── 2. Review count multiplier increases interval ──
strong_r0 = scheduler.calculate_next_review_date(0.9, 0, base_date)
strong_r1 = scheduler.calculate_next_review_date(0.9, 1, base_date)
strong_r2 = scheduler.calculate_next_review_date(0.9, 2, base_date)

check(
    "Interval grows with review_count (0 < 1 < 2)",
    (strong_r0 < strong_r1 < strong_r2)
)
check("review_count=1 doubles the base interval", strong_r1 - base_date == timedelta(days=14))

# Cap at max_interval_days
capped_scheduler = SpacedRepetitionScheduler(max_interval_days=10)
capped = capped_scheduler.calculate_next_review_date(0.9, 5, base_date)
check("Interval is capped at max_interval_days", capped == base_date + timedelta(days=10))

# ── 3. is_due_for_review ──
today = datetime.now()
check(
    "Never-reviewed topic is due",
    scheduler.is_due_for_review(None, None) is True
)
check(
    "Future next_review_date is NOT due",
    scheduler.is_due_for_review(today, today + timedelta(days=5)) is False
)
check(
    "Past next_review_date IS due",
    scheduler.is_due_for_review(today - timedelta(days=10), today - timedelta(days=1)) is True
)
check(
    "next_review_date == today IS due",
    scheduler.is_due_for_review(today - timedelta(days=1), today) is True
)

# ── 4. get_review_schedule via mastery (end-to-end through SQLite) ──
with get_db() as conn:
    conn.execute("INSERT INTO users (id, username, password_hash) VALUES (1, 'test', 'x')")
    conn.execute("INSERT INTO sessions (id, user_id, title) VALUES ('s1', 1, 'Test Session')")
    conn.commit()

# Simulate several correct answers on "Calculus" to build up review_count.
for _ in range(3):
    mastery.update_topic_performance("s1", "Math", "Calculus", True)

schedule = mastery.get_review_schedule("Calculus", 1)
print("get_review_schedule result:", schedule)

check("get_review_schedule returns a dict with expected keys",
      all(k in schedule for k in [
          "topic", "mastery_level", "mastery_category", "last_reviewed",
          "next_review", "days_until_review", "review_count"
      ]))
check("get_review_schedule topic matches", schedule.get("topic") == "Calculus")
check("get_review_schedule review_count == 3", schedule.get("review_count") == 3)
check("get_review_schedule last_reviewed is today", schedule.get("last_reviewed") == today.date().isoformat())
# EMA (alpha=0.3) after 3 correct answers is 0.657, which is Average, not yet Strong
check("get_review_schedule mastery_category reflects EMA-derived mastery_level",
      schedule.get("mastery_category") == scheduler.get_mastery_category(schedule.get("mastery_level")))

# Backward compatibility: topic with no reviews at all
none_schedule = mastery.get_review_schedule("Nonexistent Topic", 1)
check("get_review_schedule returns {} for unknown topic", none_schedule == {})

os.unlink(_tmp_db.name)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
