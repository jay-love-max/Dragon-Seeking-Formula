"""Tests for prefetch_volume_features — mootdx volume ratio pre-fetching."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd

from recap_engine import prefetch_volume_features


def _mock_bars_df(volumes: list[float], closes: list[float],
                  highs: list[float], lows: list[float]) -> pd.DataFrame:
    """构造 mootdx.bars() 返回格式的 DataFrame。"""
    n = len(volumes)
    return pd.DataFrame({
        "volume": volumes,
        "close": closes,
        "high": highs,
        "low": lows,
        "datetime": [f"2026-06-{20+i:02d} 15:00" for i in range(n)],
    })


class TestPrefetchVolumeFeatures:
    def test_computes_volume_ratio_and_position(self):
        """正常返回 volume_ratio 和 price_position。"""
        # 25日:今日 volume=300000,前5日均=100000 → ratio=3.0(核弹)
        volumes = [100000] * 24 + [300000]
        closes = [10.0] * 20 + [11.0, 12.0, 9.0, 10.5, 11.0]
        highs = [10.5] * 20 + [11.5, 12.5, 9.5, 11.0, 11.5]
        lows = [9.5] * 20 + [10.5, 11.5, 8.5, 10.0, 10.5]
        mock_df = _mock_bars_df(volumes, closes, highs, lows)

        mock_client = MagicMock()
        mock_client.bars.return_value = mock_df
        with patch("recap_engine.Quotes") as mock_quotes_cls:
            mock_quotes_cls.factory.return_value = mock_client
            result = prefetch_volume_features(["000001"], "2026-06-30")

        assert "000001" in result
        vr = result["000001"]["volume_ratio"]
        pp = result["000001"]["price_position"]
        assert vr is not None
        assert 2.9 <= vr <= 3.1  # 300000/100000 = 3.0
        assert pp is not None
        assert 0.0 <= pp <= 1.0

    def test_bars_called_with_correct_mootdx_params(self):
        """bars() 必须用 frequency/offset(mootdx 真实参数),而非 category/count。"""
        mock_df = _mock_bars_df([100000] * 24 + [300000],
                                [10.0] * 25, [10.5] * 25, [9.5] * 25)
        mock_client = MagicMock()
        mock_client.bars.return_value = mock_df
        with patch("recap_engine.Quotes") as mock_quotes_cls:
            mock_quotes_cls.factory.return_value = mock_client
            prefetch_volume_features(["000001"], "2026-06-30")

        mock_client.bars.assert_called_once_with(
            symbol="000001", frequency=9, start=0, offset=25
        )

    def test_short_frame_returns_none(self):
        """K线不足6根时返回 None(数据不足降级)。"""
        short_df = _mock_bars_df([100000] * 3, [10.0] * 3, [10.5] * 3, [9.5] * 3)
        mock_client = MagicMock()
        mock_client.bars.return_value = short_df
        with patch("recap_engine.Quotes") as mock_quotes_cls:
            mock_quotes_cls.factory.return_value = mock_client
            result = prefetch_volume_features(["000001"], "2026-06-30")

        assert result["000001"]["volume_ratio"] is None
        assert result["000001"]["price_position"] is None

    def test_single_code_failure_does_not_affect_others(self):
        """code A 抛异常,code B 正常返回。"""
        good_df = _mock_bars_df([100000] * 24 + [200000],
                                [10.0] * 25, [10.5] * 25, [9.5] * 25)
        mock_client = MagicMock()
        mock_client.bars.side_effect = [Exception("network error"), good_df]
        with patch("recap_engine.Quotes") as mock_quotes_cls:
            mock_quotes_cls.factory.return_value = mock_client
            result = prefetch_volume_features(["000001", "000002"], "2026-06-30")

        assert result["000001"]["volume_ratio"] is None
        assert result["000002"]["volume_ratio"] is not None

    def test_all_failure_returns_all_none(self):
        """全部失败返回全 None dict(不阻断流程)。"""
        mock_client = MagicMock()
        mock_client.bars.side_effect = Exception("network error")
        with patch("recap_engine.Quotes") as mock_quotes_cls:
            mock_quotes_cls.factory.return_value = mock_client
            result = prefetch_volume_features(["000001", "000002"], "2026-06-30")

        assert all(v["volume_ratio"] is None for v in result.values())
        assert all(v["price_position"] is None for v in result.values())

    def test_empty_codes_returns_empty_dict(self):
        with patch("recap_engine.Quotes"):
            result = prefetch_volume_features([], "2026-06-30")
        assert result == {}
