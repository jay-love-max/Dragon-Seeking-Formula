from __future__ import annotations

from history_backtrack import (
    BacktrackPattern,
    detect_severe_reversal,
    detect_shallow_dip,
    detect_shrink_doji,
)


class TestDetectShrinkDoji:
    def test_insufficient_data_returns_false(self):
        closes = [10.0, 10.1]
        volumes = [100, 110]
        hit, score, evid = detect_shrink_doji(closes, volumes)
        assert hit is False
        assert score == 0.0
        assert "insufficient_data" in evid

    def test_volume_not_shrunken_returns_false(self):
        closes = [10.0] * 15
        volumes = [100] * 14 + [90]
        hit, score, evid = detect_shrink_doji(closes, volumes, shrink_target=0.3)
        assert hit is False

    def test_volume_shrunken_with_doji_returns_true(self):
        closes = [10.0] * 10 + [9.5, 9.6, 9.55, 9.58, 9.57]
        volumes = [1000] * 4 + [500, 450, 480, 460, 470]
        opens = [10.0] * 10 + [9.5, 9.6, 9.55, 9.58, 9.56]
        hit, score, evid = detect_shrink_doji(closes, volumes, opens, shrink_target=0.60)
        assert hit is True
        assert score > 0
        assert "shrink_doji" in evid

    def test_zero_peak_volume_returns_false(self):
        closes = [10.0] * 10
        volumes = [0] * 10
        hit, score, evid = detect_shrink_doji(closes, volumes)
        assert hit is False
        assert "zero_peak_volume" in evid


class TestDetectSevereReversal:
    def test_insufficient_data_returns_false(self):
        closes = [100, 101]
        hit, score, evid = detect_severe_reversal(closes)
        assert hit is False

    def test_no_downtrend_returns_false(self):
        closes = [100, 102, 105, 108, 110, 112, 115, 118, 120]
        hit, score, evid = detect_severe_reversal(closes)
        assert hit is False

    def test_drop_not_severe_enough_returns_false(self):
        closes = [100, 98, 97, 96, 95, 97, 98, 99, 100]
        hit, score, evid = detect_severe_reversal(closes, drop_threshold=-0.10)
        assert hit is False

    def test_severe_drop_with_reversal_returns_true(self):
        closes = [100, 102, 105, 100, 90, 85, 80, 82, 88, 92]
        hit, score, evid = detect_severe_reversal(closes)
        assert hit is True
        assert score > 0
        assert "severe_reversal" in evid

    def test_no_reversal_after_drop_returns_false(self):
        closes = [100, 102, 105, 100, 90, 85, 80, 78, 76, 74]
        hit, score, evid = detect_severe_reversal(closes)
        assert hit is False

    def test_drop_exactly_at_threshold(self):
        closes = [105, 104, 103, 100, 100, 85, 85, 86, 87]
        hit, score, evid = detect_severe_reversal(closes, drop_threshold=-0.15)
        assert hit is True


class TestDetectShallowDip:
    def test_insufficient_data_returns_false(self):
        closes = [100]
        hit, score, evid = detect_shallow_dip(closes, float_mcap_yuan=50e9)
        assert hit is False

    def test_not_large_cap_returns_false(self):
        closes = [100] * 10
        hit, score, evid = detect_shallow_dip(closes, float_mcap_yuan=1e9)
        assert hit is False
        assert "not_large_cap" in evid

    def test_dip_too_deep_returns_false(self):
        closes = [100, 102, 105, 90, 88, 89, 91, 92, 93, 94]
        hit, score, evid = detect_shallow_dip(closes, float_mcap_yuan=20e9, dip_max=-0.05)
        assert hit is False

    def test_shallow_dip_detected(self):
        closes = [100, 101, 102, 99, 98, 97, 98, 99, 100, 101]
        hit, score, evid = detect_shallow_dip(closes, float_mcap_yuan=20e9)
        assert hit is True
        assert score > 0
        assert "shallow_dip" in evid

    def test_exactly_at_large_cap_threshold(self):
        closes = [100] * 8
        hit, score, evid = detect_shallow_dip(closes, float_mcap_yuan=10e9)
        assert hit is True


class TestBacktrackPatternEnum:
    def test_enum_values(self):
        assert BacktrackPattern.SHRINK_DOJI == "SHRINK_DOJI"
        assert BacktrackPattern.SEVERE_REVERSAL == "SEVERE_REVERSAL"
        assert BacktrackPattern.SHALLOW_DIP == "SHALLOW_DIP"
