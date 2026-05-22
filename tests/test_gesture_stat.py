"""Unit tests for gesture_stat_engine: SM-2 ease factor and stat update logic."""
from types import SimpleNamespace
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from services.gesture_stat_engine import _ease_factor, update_gesture_stat


class TestEaseFactor:
    def test_zero_total_returns_default(self):
        assert _ease_factor(0, 0) == 2.5

    def test_all_correct_clamps_at_max(self):
        assert _ease_factor(10, 10) == 2.5

    def test_no_correct_clamps_at_min(self):
        assert _ease_factor(0, 10) == 1.3

    def test_half_correct_returns_midpoint(self):
        # 1.3 + 0.5 * 1.2 = 1.9
        assert abs(_ease_factor(5, 10) - 1.9) < 1e-9

    def test_single_correct_attempt(self):
        # 1.3 + 1.0 * 1.2 = 2.5 (clamped to max)
        assert _ease_factor(1, 1) == 2.5

    def test_result_always_within_bounds(self):
        for correct, total in [(1, 3), (7, 10), (3, 7), (0, 1), (9, 10)]:
            ef = _ease_factor(correct, total)
            assert 1.3 <= ef <= 2.5, f"Out of bounds for {correct}/{total}: {ef}"


class TestUpdateGestureStat:
    def _make_stat(self, **kw):
        defaults = dict(
            user_id=1, gesture_id=1,
            correct_count=3, error_count=2,
            mastery_level=1,
            last_attempt_at=None, next_review_at=None,
        )
        defaults.update(kw)
        return SimpleNamespace(**defaults)

    def _make_db(self, stat):
        db = MagicMock()
        db.query.return_value.filter_by.return_value.first.return_value = stat
        return db

    def test_creates_new_record_when_stat_missing(self):
        db = self._make_db(None)
        update_gesture_stat(1, 1, correct=True, db=db)
        db.add.assert_called_once()

    def test_correct_increments_correct_count(self):
        stat = self._make_stat(correct_count=3, error_count=2)
        update_gesture_stat(1, 1, correct=True, db=self._make_db(stat))
        assert stat.correct_count == 4

    def test_wrong_increments_error_count(self):
        stat = self._make_stat(correct_count=3, error_count=2)
        update_gesture_stat(1, 1, correct=False, db=self._make_db(stat))
        assert stat.error_count == 3

    def test_correct_advances_mastery_level(self):
        stat = self._make_stat(mastery_level=1)
        update_gesture_stat(1, 1, correct=True, db=self._make_db(stat))
        assert stat.mastery_level == 2

    def test_mastery_level_capped_at_3(self):
        stat = self._make_stat(mastery_level=3)
        update_gesture_stat(1, 1, correct=True, db=self._make_db(stat))
        assert stat.mastery_level == 3

    def test_wrong_drops_mastery_level(self):
        stat = self._make_stat(mastery_level=2)
        update_gesture_stat(1, 1, correct=False, db=self._make_db(stat))
        assert stat.mastery_level == 1

    def test_mastery_level_not_below_zero(self):
        stat = self._make_stat(mastery_level=0)
        update_gesture_stat(1, 1, correct=False, db=self._make_db(stat))
        assert stat.mastery_level == 0

    def test_next_review_at_is_populated(self):
        stat = self._make_stat()
        update_gesture_stat(1, 1, correct=True, db=self._make_db(stat))
        assert stat.next_review_at is not None

    def test_wrong_schedules_next_review_in_one_day(self):
        stat = self._make_stat()
        before = datetime.now(timezone.utc)
        update_gesture_stat(1, 1, correct=False, db=self._make_db(stat))
        expected = before + timedelta(days=1)
        diff = abs((stat.next_review_at - expected).total_seconds())
        assert diff < 5
