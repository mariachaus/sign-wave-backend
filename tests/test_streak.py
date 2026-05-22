"""Unit tests for streak logic in routes_lesson: XP milestones and streak update."""
from types import SimpleNamespace
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from routes.lesson import _streak_xp, _update_streak


class TestStreakXp:
    def test_streak_1_base_xp(self):
        assert _streak_xp(1) == 15

    def test_streak_7_milestone(self):
        assert _streak_xp(7) == 65   # 15 + 50

    def test_streak_14_milestone(self):
        assert _streak_xp(14) == 90  # 15 + 75

    def test_streak_30_milestone(self):
        assert _streak_xp(30) == 115  # 15 + 100

    def test_streak_60_milestone(self):
        assert _streak_xp(60) == 165  # 15 + 150

    def test_streak_100_milestone(self):
        assert _streak_xp(100) == 315  # 15 + 300

    def test_non_milestone_streaks(self):
        assert _streak_xp(3) == 15
        assert _streak_xp(50) == 15


class TestUpdateStreak:
    def _make_db(self, streak=None):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = streak
        return db

    def _make_streak(self, streak_length=5, days_ago=1, freeze_shields_count=0):
        return SimpleNamespace(
            streak_length=streak_length,
            last_activity_at=datetime.utcnow() - timedelta(days=days_ago),
            freeze_shields_count=freeze_shields_count,
            is_current=True,
            ended_at=None,
        )

    def test_no_streak_creates_new_and_returns_base_xp(self):
        xp = _update_streak(1, self._make_db(None))
        assert xp == 15  # _streak_xp(1)

    def test_same_day_activity_returns_zero(self):
        streak = self._make_streak(days_ago=0)
        xp = _update_streak(1, self._make_db(streak))
        assert xp == 0

    def test_consecutive_day_increments_streak_length(self):
        streak = self._make_streak(streak_length=4, days_ago=1)
        _update_streak(1, self._make_db(streak))
        assert streak.streak_length == 5

    def test_consecutive_day_reaching_milestone_returns_bonus_xp(self):
        streak = self._make_streak(streak_length=6, days_ago=1)
        xp = _update_streak(1, self._make_db(streak))
        assert xp == _streak_xp(7)  # 65

    def test_gap_2_with_shield_continues_streak(self):
        streak = self._make_streak(streak_length=5, days_ago=2, freeze_shields_count=1)
        _update_streak(1, self._make_db(streak))
        assert streak.streak_length == 6
        assert streak.freeze_shields_count == 0

    def test_gap_2_without_shield_breaks_streak(self):
        streak = self._make_streak(streak_length=5, days_ago=2, freeze_shields_count=0)
        xp = _update_streak(1, self._make_db(streak))
        assert xp == 15  # new streak of 1
        assert streak.is_current is False

    def test_large_gap_breaks_streak(self):
        streak = self._make_streak(streak_length=10, days_ago=5, freeze_shields_count=2)
        xp = _update_streak(1, self._make_db(streak))
        assert xp == 15  # new streak of 1
        assert streak.is_current is False
