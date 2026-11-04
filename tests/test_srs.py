"""Pure scheduling regressions; no database or external model required."""
import unittest
from datetime import datetime, timedelta
from src.personalization.spaced_rep import SpacedRepetitionScheduler


class SchedulingTests(unittest.TestCase):
    def setUp(self):
        self.scheduler = SpacedRepetitionScheduler()
        self.now = datetime(2026, 1, 1)

    def test_failure_is_due_tomorrow_even_after_long_success_streak(self):
        for mastery in (0.0, 0.6, 0.95):
            streak, due = self.scheduler.schedule_review(mastery, 50, False, self.now)
            self.assertEqual(streak, 0)
            self.assertEqual(due, self.now + timedelta(days=1))

    def test_repeated_failures_never_extend_interval(self):
        streak = 20
        for _ in range(100):
            streak, due = self.scheduler.schedule_review(0.1, streak, False, self.now)
            self.assertEqual((streak, due), (0, self.now + timedelta(days=1)))

    def test_success_streak_restarts_after_failure(self):
        streak, _ = self.scheduler.schedule_review(0.9, 10, False, self.now)
        streak, due = self.scheduler.schedule_review(0.9, streak, True, self.now)
        self.assertEqual((streak, due), (1, self.now + timedelta(days=7)))
        streak, due = self.scheduler.schedule_review(0.9, streak, True, self.now)
        self.assertEqual((streak, due), (2, self.now + timedelta(days=14)))

    def test_category_boundaries_match_profile(self):
        for score, category in ((0, "Weak"), (0.3, "Weak"), (0.4999, "Weak"),
                                (0.5, "Average"), (0.7, "Average"), (0.75, "Average"),
                                (0.7501, "Strong"), (1, "Strong")):
            with self.subTest(score=score):
                self.assertEqual(self.scheduler.get_mastery_category(score), category)

    def test_success_interval_is_capped(self):
        _, due = self.scheduler.schedule_review(0.9, 100, True, self.now)
        self.assertEqual(due, self.now + timedelta(days=60))


if __name__ == '__main__':
    unittest.main()
