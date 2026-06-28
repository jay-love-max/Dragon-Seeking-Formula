"""Phase 0 金样本回归 — 本地、确定、不依赖实时行情接口。

Phase 0 只固化金样本的边界期望与规则契约阈值;F19 过滤纯函数在 Phase 2 实现。
本测试现在断言的是"仅凭规则契约能回答每个边界值"(方案 2.1 验收),
并锁定 2026-06-19/24/25/26 金样本的输入与期望语义,防止后续 Phase 漂移。

金样本不得为了让测试变绿而直接改(AGENTS.md 行为变更与测试)。
"""

from __future__ import annotations

import pytest

from rule_contract import ReasonCode, load_rule_config
from tests.fixtures.golden_samples import (
    GOLDEN_2026_06_24,
    GOLDEN_2026_06_25_F18,
    GOLDEN_2026_06_25_KESHIDA,
    SEAL_49_999_999,
    SEAL_50_000_000,
    SEAL_100_000_000,
    SEAL_TIME_095959,
    SEAL_TIME_100001,
    SEAL_TIME_EXACTLY_100000,
    f19_blown_boundary_records,
    f19_early_seal_boundary_records,
    f19_seal_boundary_records,
    f19_st_boundary_records,
)


class TestF19BoundaryValuesFromContract:
    """仅凭规则契约回答每个边界值(方案 19.1 + 2.1 验收)。"""

    def test_seal_funds_threshold_is_50m_yuan(self):
        cfg = load_rule_config()
        assert cfg.raw["f19"]["min_seal_funds_yuan"] == SEAL_50_000_000

    def test_max_blown_count_is_5(self):
        cfg = load_rule_config()
        assert cfg.raw["f19"]["max_blown_count"] == 5

    def test_early_seal_is_strict_before_10_00_00(self):
        cfg = load_rule_config()
        # 契约值是字符串 "10:00:00";语义为严格 <
        assert cfg.raw["f19"]["early_seal_before"] == "10:00:00"
        # 锁定边界:09:59:59 早盘,10:00:00 与 10:00:01 都不算
        assert SEAL_TIME_095959 < "10:00:00"
        assert not (SEAL_TIME_EXACTLY_100000 < "10:00:00")
        assert not (SEAL_TIME_100001 < "10:00:00")

    def test_recent_resonance_is_3_sessions_min_2_boards(self):
        cfg = load_rule_config()
        assert cfg.raw["f19"]["recent_resonance_sessions"] == 3
        assert cfg.raw["f19"]["recent_resonance_min_limit_ups"] == 2

    def test_f14_is_4_sessions_min_2_boards_1_10_multiplier(self):
        cfg = load_rule_config()
        assert cfg.raw["f14"]["lookback_sessions"] == 4
        assert cfg.raw["f14"]["min_limit_ups"] == 2
        assert cfg.raw["f14"]["score_multiplier"] == 1.10


class TestSealFundsBoundaryRecords:
    def test_below_50m_record_is_below_threshold(self):
        recs = f19_seal_boundary_records()
        below, equal, above = recs
        assert below["seal_funds_yuan"] == SEAL_49_999_999
        assert below["seal_funds_yuan"] < SEAL_50_000_000
        assert equal["seal_funds_yuan"] == SEAL_50_000_000
        assert above["seal_funds_yuan"] == SEAL_100_000_000

    def test_weak_seal_band_is_50m_to_100m(self):
        cfg = load_rule_config()
        assert cfg.raw["seal_funds"]["weak_seal_floor_yuan"] == SEAL_50_000_000
        assert cfg.raw["seal_funds"]["weak_seal_ceiling_yuan"] == SEAL_100_000_000


class TestBlownBoundaryRecords:
    def test_blown_5_passes_6_filtered(self):
        cfg = load_rule_config()
        max_blown = cfg.raw["f19"]["max_blown_count"]
        recs = f19_blown_boundary_records()
        five, six = recs
        assert five["blown_count"] == 5 <= max_blown
        assert six["blown_count"] == 6 > max_blown


class TestEarlySealBoundaryRecords:
    def test_three_time_boundaries_locked(self):
        recs = f19_early_seal_boundary_records()
        early, exact, late = recs
        assert early["first_seal_time"] == SEAL_TIME_095959
        assert exact["first_seal_time"] == SEAL_TIME_EXACTLY_100000
        assert late["first_seal_time"] == SEAL_TIME_100001


class TestSTBoundaryRecords:
    def test_st_record_is_marked(self):
        recs = f19_st_boundary_records()
        assert recs[0]["is_st"] is True


class TestGolden2026_06_24Top5:
    """2026-06-24 预检指定的 5 只应能保留(均满足 F19 硬门槛且至少一项共振)。"""

    EXPECTED_CODES = {"600584", "600667", "600703", "002025", "603929"}
    EXPECTED_NAMES = {"长电科技", "太极实业", "三安光电", "航天电器", "亚翔集成"}

    def test_all_five_present_in_fixture(self):
        codes = {r["code"] for r in GOLDEN_2026_06_24}
        assert codes == self.EXPECTED_CODES

    def test_all_five_meet_hard_gates(self):
        cfg = load_rule_config()
        min_seal = cfg.raw["f19"]["min_seal_funds_yuan"]
        max_blown = cfg.raw["f19"]["max_blown_count"]
        for r in GOLDEN_2026_06_24:
            assert r["consecutive_boards"] == 1, f"{r['code']} not first board"
            assert not r["is_st"], f"{r['code']} is ST"
            assert r["seal_funds_yuan"] >= min_seal, f"{r['code']} seal below 50m"
            assert r["blown_count"] <= max_blown, f"{r['code']} blown above 5"

    def test_all_five_have_early_seal_resonance(self):
        # 5 只首封均 < 10:00:00 → 早盘共振成立
        for r in GOLDEN_2026_06_24:
            assert r["first_seal_time"] < "10:00:00", (
                f"{r['code']} {r['name']} 首封 {r['first_seal_time']} 不满足早盘共振"
            )


class TestGolden2026_06_25KeshidaFiltered:
    """科士达 002518 因无共振被 F19 过滤(知识库 F19 教训)。"""

    def test_keshida_seal_is_sufficient(self):
        # 封单 1.44 亿,通过硬门槛
        assert GOLDEN_2026_06_25_KESHIDA["seal_funds_yuan"] >= SEAL_50_000_000
        assert GOLDEN_2026_06_25_KESHIDA["blown_count"] == 0
        assert GOLDEN_2026_06_25_KESHIDA["is_st"] is False

    def test_keshida_has_no_early_seal_resonance(self):
        # 首封 10:03 > 10:00:00 → 非早盘共振
        assert GOLDEN_2026_06_25_KESHIDA["first_seal_time"] >= "10:00:00"

    def test_keshida_has_no_lhb_resonance(self):
        # fixture 不含龙虎榜上榜信号
        assert GOLDEN_2026_06_25_KESHIDA.get("lhb_listed") in (None, False)

    def test_keshida_has_no_recent_3d_2b(self):
        # 单日首板,近 3 天(含当日)仅 1 次封板 < 2 → 无 3d2b 共振
        assert GOLDEN_2026_06_25_KESHIDA.get("recent_3d_2b", False) is False


class TestGolden2026_06_25F18:
    """2026-06-25 二进三 1/7=14.29% → HALT(方案 19.4 + 二进三联动风控.md)。"""

    def test_denominator_is_7(self):
        assert len(GOLDEN_2026_06_25_F18["prev_two_boards_codes"]) == 7

    def test_numerator_is_1(self):
        assert len(GOLDEN_2026_06_25_F18["today_three_boards_codes"]) == 1

    def test_rate_is_one_seventh(self):
        assert GOLDEN_2026_06_25_F18["expected_rate"] == pytest.approx(1 / 7)

    def test_expected_policy_is_halt(self):
        assert GOLDEN_2026_06_25_F18["expected_policy"] == "HALT"

    def test_rate_is_below_halt_threshold(self):
        cfg = load_rule_config()
        assert GOLDEN_2026_06_25_F18["expected_rate"] < cfg.raw["f18"]["halt_below"]


class TestTradingDayGate:
    """2026-06-19 为休市工作日,交易日闸门必须阻止旧数据推送(方案 19.4)。"""

    # 2026-06-19 是周五,但属于 A 股休市(端午节假期区间)。
    # exchange_calendars XSHG 是 Phase 1 主日历;此处先锁定契约要求。
    NON_TRADING_DATE = "2026-06-19"

    def test_publishing_requires_trading_day(self):
        cfg = load_rule_config()
        assert cfg.raw["publishing"]["require_trading_day"] is True

    def test_non_trading_day_must_block(self):
        # 契约:非交易日 publishable=false(方案 7.4 第 1 条)
        # Phase 1 将用 exchange_calendars XSHG.is_session 验证
        # 此处锁定语义:该日期不得发布
        assert load_rule_config().raw["publishing"]["require_trading_day"] is True

    def test_trading_day_invalid_reason_code_exists(self):
        assert ReasonCode.TRADING_DAY_INVALID.value == "TRADING_DAY_INVALID"


class TestReasonCodesForGoldenSamples:
    """金样本对应的失败/通过原因码必须存在且语义稳定。"""

    def test_seal_below_reason_code(self):
        assert ReasonCode.SEAL_FUNDS_BELOW_50M.value == "SEAL_FUNDS_BELOW_50M"

    def test_blown_above_reason_code(self):
        assert ReasonCode.BLOWN_COUNT_ABOVE_5.value == "BLOWN_COUNT_ABOVE_5"

    def test_no_resonance_reason_code(self):
        assert ReasonCode.NO_F19_RESONANCE.value == "NO_F19_RESONANCE"

    def test_st_reason_code(self):
        assert ReasonCode.ST_OR_DELISTING_RISK.value == "ST_OR_DELISTING_RISK"

    def test_market_halt_reason_code(self):
        assert ReasonCode.MARKET_F18_HALT.value == "MARKET_F18_HALT"
