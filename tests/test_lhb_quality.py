"""Phase 4 验收 — 龙虎榜质量评分与 F16。

覆盖方案 13.4:
- 席位匹配:空白/括号/营业部后缀标准化;
- 基础 50 分 + GOLD(+15)/INSTITUTION(+10)/DEATH(-20);
- F16:绍兴胜利东路首板不扣分,二板及以上扣 25;
- 最终质量等级:>=70 GOOD, 45-69 NEUTRAL, <45 DANGEROUS。
"""
from __future__ import annotations

import pytest

from lhb_quality import _normalize_seat_name, f16_check, quality_grade, score_single_trade


class TestScoreSingleTrade:
    def test_no_seats_returns_50(self):
        assert score_single_trade([]) == 50.0

    def test_normal_seat_stays_50(self):
        seats = [{"seat_name": "某普通营业部", "is_buy": True, "buy_amount": 0.0}]
        assert score_single_trade(seats) == 50.0

    def test_gold_seat_adds_15(self):
        # 配置中 GOLD 席位:西安太华路,武汉紫阳东路,北京知春路等
        seats = [{"seat_name": "西安太华路", "is_buy": True, "buy_amount": 0.0}]
        assert score_single_trade(seats) == pytest.approx(65.0)

    def test_death_seat_subtracts_20(self):
        # 配置中 DEATH 席位:宁波桑田路(score_delta=-20)
        seats = [{"seat_name": "宁波桑田路", "is_buy": True, "buy_amount": 0.0}]
        assert score_single_trade(seats) == pytest.approx(30.0)

    def test_institution_buy_adds_10(self):
        seats = [{"seat_name": "机构专用", "is_buy": True, "buy_amount": 0.0}]
        assert score_single_trade(seats) == pytest.approx(60.0)

    def test_buy_amount_adds_bonus(self):
        seats = [{"seat_name": "某营业部", "is_buy": True, "buy_amount": 200_000_000.0}]
        s = score_single_trade(seats)
        assert 50.0 < s <= 70.0

    def test_score_clamped_0_100(self):
        seats = [{"seat_name": "西安太华路", "is_buy": True, "buy_amount": 10_000_000_000.0}]
        assert score_single_trade(seats) <= 100.0

    def test_multi_seat_accumulates(self):
        seats = [
            {"seat_name": "西安太华路", "is_buy": True, "buy_amount": 0.0},
            {"seat_name": "宁波桑田路", "is_buy": True, "buy_amount": 0.0},
        ]
        # 50 + 15(GOLD) - 20(DEATH) = 45
        assert score_single_trade(seats) == pytest.approx(45.0)


class TestSeatNormalization:
    def test_parens_stripped(self):
        assert _normalize_seat_name("中信证券上海分公司(游资)") == "中信证券上海分公司"

    def test_fullwidth_parens_stripped(self):
        assert _normalize_seat_name("中信证券上海分公司（游资）") == "中信证券上海分公司"

    def test_yingyebu_stripped(self):
        assert "营业部" not in _normalize_seat_name("东方财富证券拉萨团结路第二营业部")


class TestF16:
    def test_first_board_no_penalty(self):
        delta = f16_check("绍兴胜利东路", is_first_board=True, is_buy=True)
        assert delta == 0.0

    def test_second_board_plus_penalty(self):
        delta = f16_check("绍兴胜利东路", is_first_board=False, is_buy=True)
        assert delta == -25.0

    def test_sell_not_penalized(self):
        delta = f16_check("绍兴胜利东路", is_first_board=False, is_buy=False)
        assert delta == 0.0

    def test_other_seat_not_affected(self):
        delta = f16_check("西安太华路", is_first_board=False, is_buy=True)
        assert delta == 0.0


class TestQualityGrade:
    def test_good_above_70(self):
        assert quality_grade(75.0) == "GOOD"
        assert quality_grade(70.0) == "GOOD"

    def test_neutral_45_to_69(self):
        assert quality_grade(60.0) == "NEUTRAL"
        assert quality_grade(45.0) == "NEUTRAL"

    def test_dangerous_below_45(self):
        assert quality_grade(30.0) == "DANGEROUS"
        assert quality_grade(44.9) == "DANGEROUS"
