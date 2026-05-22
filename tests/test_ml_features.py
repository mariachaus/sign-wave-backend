"""Unit tests for ML feature extraction helpers in routes_ml.py."""
import numpy as np
import pytest
from types import SimpleNamespace

from routes.ml import _add_delta, _extract_features_py


def _make_lm(x=0.0, y=0.0, z=0.0):
    return SimpleNamespace(x=x, y=y, z=z)


def _empty_pose():
    return SimpleNamespace(pose_landmarks=[])


def _empty_hands():
    return SimpleNamespace(hand_landmarks=[], handedness=[])


class TestAddDelta:
    def _make_buf(self):
        rng = np.random.default_rng(42)
        return rng.random((20, 225)).tolist()

    def test_output_shape(self):
        result = _add_delta(self._make_buf())
        assert result.shape == (20, 450)

    def test_first_row_delta_is_zero(self):
        result = _add_delta(self._make_buf())
        assert np.all(result[0, 225:] == 0.0)

    def test_delta_equals_frame_difference(self):
        buf = self._make_buf()
        result = _add_delta(buf)
        arr = np.array(buf, dtype=np.float32)
        expected_delta_1 = arr[1] - arr[0]
        np.testing.assert_allclose(result[1, 225:], expected_delta_1, rtol=1e-5)

    def test_original_features_preserved(self):
        buf = self._make_buf()
        result = _add_delta(buf)
        arr = np.array(buf, dtype=np.float32)
        np.testing.assert_array_equal(result[:, :225], arr)

    def test_all_zeros_input_gives_all_zeros(self):
        buf = [[0.0] * 225] * 20
        result = _add_delta(buf)
        assert np.all(result == 0.0)


class TestExtractFeaturesPy:
    def test_no_landmarks_returns_225_zeros(self):
        frame = _extract_features_py(_empty_pose(), _empty_hands())
        assert len(frame) == 225
        assert all(v == 0.0 for v in frame)

    def test_pose_nose_normalized_to_zero(self):
        nose = _make_lm(x=0.5, y=0.3)
        lms = [nose] + [_make_lm(0.6, 0.4) for _ in range(32)]
        pose = SimpleNamespace(pose_landmarks=[lms])
        frame = _extract_features_py(pose, _empty_hands())
        assert len(frame) == 225
        assert abs(frame[0]) < 1e-6  # nose x − nose_x = 0
        assert abs(frame[1]) < 1e-6  # nose y − nose_y = 0

    def test_second_pose_landmark_correctly_normalized(self):
        nose = _make_lm(x=0.5, y=0.3)
        lm1 = _make_lm(x=0.6, y=0.4, z=0.1)
        lms = [nose, lm1] + [_make_lm() for _ in range(31)]
        pose = SimpleNamespace(pose_landmarks=[lms])
        frame = _extract_features_py(pose, _empty_hands())
        assert abs(frame[3] - (0.6 - 0.5)) < 1e-6   # x offset
        assert abs(frame[4] - (0.4 - 0.3)) < 1e-6   # y offset
        assert abs(frame[5] - 0.1) < 1e-6             # z unchanged

    def test_left_hand_written_at_offset_99(self):
        lms = [_make_lm(x=0.2, y=0.2)] + [_make_lm() for _ in range(20)]
        label = SimpleNamespace(category_name="Left")
        hands = SimpleNamespace(hand_landmarks=[lms], handedness=[[label]])
        frame = _extract_features_py(_empty_pose(), hands)
        assert abs(frame[99] - 0.2) < 1e-6
        assert abs(frame[100] - 0.2) < 1e-6

    def test_right_hand_written_at_offset_162(self):
        lms = [_make_lm(x=0.7, y=0.8)] + [_make_lm() for _ in range(20)]
        label = SimpleNamespace(category_name="Right")
        hands = SimpleNamespace(hand_landmarks=[lms], handedness=[[label]])
        frame = _extract_features_py(_empty_pose(), hands)
        assert abs(frame[162] - 0.7) < 1e-6
        assert abs(frame[163] - 0.8) < 1e-6
