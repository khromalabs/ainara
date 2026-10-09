# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
# Dual-licensed under LGPL-3.0 or a commercial license (see project headers).

"""Unit tests for the habit tracker's streak calculation.

    python -m unittest scripts.evaluation.tests.test_habit_streak

Covers compute_streak, the pure function behind get_streak. Does NOT
exercise the SQLite-backed run() path.
"""

import os
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from ainara.orakle.skills.tools.habit_tracker import compute_streak  # noqa: E402

TODAY = date(2026, 10, 8)


def days_ago(*offsets):
    return [TODAY - timedelta(days=n) for n in offsets]


class ComputeStreak(unittest.TestCase):
    def test_no_completions_is_zero(self):
        self.assertEqual(compute_streak([], TODAY), 0)

    def test_only_today(self):
        self.assertEqual(compute_streak(days_ago(0), TODAY), 1)

    def test_long_daily_streak_is_not_capped(self):
        # Regression: the old loop compared against today - streak days,
        # so every streak broke on its third day.
        self.assertEqual(compute_streak(days_ago(*range(10)), TODAY), 10)

    def test_streak_through_yesterday_still_counts(self):
        # Today not logged yet: the streak is still alive.
        self.assertEqual(compute_streak(days_ago(1, 2, 3), TODAY), 3)

    def test_last_completion_two_days_ago_is_broken(self):
        self.assertEqual(compute_streak(days_ago(2, 3, 4), TODAY), 0)

    def test_gap_ends_the_streak(self):
        self.assertEqual(compute_streak(days_ago(0, 1, 3, 4, 5), TODAY), 2)

    def test_unsorted_and_duplicate_dates(self):
        self.assertEqual(compute_streak(days_ago(2, 0, 1, 1, 0), TODAY), 3)

    def test_future_dates_do_not_break_streak_counting(self):
        # A completion logged ahead of time (e.g. tomorrow) still chains
        # onto today; the streak is measured from the newest date.
        self.assertEqual(compute_streak(days_ago(-1, 0, 1), TODAY), 3)


if __name__ == "__main__":
    unittest.main()
