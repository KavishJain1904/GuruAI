# Spaced repetition behavior

- Mastery categories are shared by the profile and scheduler: Weak below 50%,
  Average from 50% through 75%, Strong above 75%. Review-queue colors use the
  category returned by the server.
- Quiz failures and self-ratings below 5/10 reset the success streak and schedule
  a review for tomorrow. Successful reviews use the category's base interval
  (1, 3, or 7 days), multiplied by the current consecutive-success streak,
  with a 60-day cap. Total review count still includes every attempt.
- Self-ratings update the mastery EMA and schedule, but never increment quiz
  `correct`/`total` or the user dashboard's question count.
- Each quiz answer and self-rating creates a `review_events` row in the same
  transaction as the mastery update. Records contain review type, score,
  mastery before/after, next review, timestamp, and optional notes/question/
  selected-answer/correct-answer snapshots.
- `GET /api/reviews?limit=20&offset=0&topic_id=...` exposes paginated history for
  the signed-in user. `topic_id` is optional. The Review & Progress screen has
  a Review history panel. Deleting a topic removes its history; deleting a
  chat session preserves review history and clears only its session reference.
- Standalone topic quizzes can record an answer without a chat session. The
  authenticated user determines ownership. The existing quiz API still accepts
  client-reported correctness; this change does not add server-side grading.

## Existing databases

Restart the app to run the idempotent startup schema upgrade. It adds a success
streak column and the review-events table without altering existing quiz totals,
mastery scores, or due dates. Existing streaks start at zero because total
attempts cannot establish past consecutive successes. New scheduling applies
when each topic is next reviewed.

Historical self-ratings were mixed into quiz totals and cannot be safely
subtracted without the missing original events. They are left intact. History
begins with reviews submitted after the upgrade; no historical events are fabricated.

## Verification

Run `python -m unittest discover -s tests -p test_srs.py -v` for pure scheduling
regressions and `python tests/smoke_test.py` for PostgreSQL/API integration checks.
The latter creates and removes a temporary local database and requires permission
to do so. It covers legacy-schema upgrades, shared category boundaries, failed
reviews, quiz counts, history isolation/pagination, and transaction rollback.
Run `node tests/test_review_history.cjs` for the history widget behavior.
