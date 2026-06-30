"""Phase 0 验收:规则契约加载、阈值单调性与原因码稳定性。

覆盖方案第 6 节与 AGENTS.md"硬规则必须确定、版本化、可解释,并覆盖边界测试"。
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from rule_contract import (
    CONFIG_PATH,
    LHB_SEATS_PATH,
    RULE_VERSION,
    ConfigError,
    DataStatus,
    ExecutionAction,
    MarketRegime,
    PersonalityGrade,
    PositionPolicy,
    PublicationStatus,
    ReasonCode,
    load_lhb_seats_config,
    load_rule_config,
)


class TestRuleContractLoads:
    def test_loads_default_config_without_error(self):
        cfg = load_rule_config()
        assert cfg.rule_version == RULE_VERSION
        assert cfg.max_published_candidates == 5

    def test_config_file_exists_at_expected_path(self):
        assert CONFIG_PATH.exists(), f"rule config missing at {CONFIG_PATH}"

    def test_lhb_seats_file_exists(self):
        assert LHB_SEATS_PATH.exists()

    def test_lhb_seats_loads_with_unique_seat_ids(self):
        config = load_lhb_seats_config()
        assert config["seat_schema_version"] == "lhb-seats/1.0.0"
        seat_ids = [s["seat_id"] for s in config["seats"]]
        assert len(seat_ids) == len(set(seat_ids))
        categories = {s["category"] for s in config["seats"]}
        assert categories <= {"GOLD", "DEATH", "INSTITUTION"}

    def test_lhb_f16_shaoxing_special_case_present(self):
        config = load_lhb_seats_config()
        f16 = config["lhb_scoring"]
        assert f16["f16_shaoxing_first_board_delta"] == 0
        assert f16["f16_shaoxing_second_board_plus_delta"] == -25


class TestConfigValidation:
    """错误配置必须阻止启动,不得使用默认值继续运行(方案 6.1)。"""

    def _with(self, **overrides) -> dict:
        base = load_rule_config().raw
        for dotted, val in overrides.items():
            section, key = dotted.split(".", 1)
            copy.deepcopy(base)
        return base

    def test_empty_rule_version_rejected(self, tmp_path):
        cfg = copy.deepcopy(load_rule_config().raw)
        cfg["rule_version"] = ""
        self._expect_invalid(tmp_path, cfg)

    def test_wrong_rule_version_rejected(self, tmp_path):
        cfg = copy.deepcopy(load_rule_config().raw)
        cfg["rule_version"] = "dragon-formula/0.9.9"
        self._expect_invalid(tmp_path, cfg)

    def test_top_n_out_of_range_rejected(self, tmp_path):
        cfg = copy.deepcopy(load_rule_config().raw)
        cfg["max_published_candidates"] = 0
        self._expect_invalid(tmp_path, cfg)
        cfg2 = copy.deepcopy(load_rule_config().raw)
        cfg2["max_published_candidates"] = 21
        self._expect_invalid(tmp_path, cfg2)

    def test_f18_thresholds_non_monotonic_rejected(self, tmp_path):
        cfg = copy.deepcopy(load_rule_config().raw)
        cfg["f18"]["defensive_below"] = 0.10  # < halt_below=0.20
        self._expect_invalid(tmp_path, cfg)

    def test_f18_thresholds_above_one_rejected(self, tmp_path):
        cfg = copy.deepcopy(load_rule_config().raw)
        cfg["f18"]["standard_at_or_below"] = 1.5
        self._expect_invalid(tmp_path, cfg)

    def test_personality_weights_not_summing_to_one_rejected(self, tmp_path):
        cfg = copy.deepcopy(load_rule_config().raw)
        cfg["personality"]["weight_activity"] = 0.50  # now sums > 1
        self._expect_invalid(tmp_path, cfg)

    def test_personality_grades_non_monotonic_rejected(self, tmp_path):
        cfg = copy.deepcopy(load_rule_config().raw)
        cfg["personality"]["grade_a_min"] = 80.0  # > grade_s_min=75
        self._expect_invalid(tmp_path, cfg)

    def test_market_regime_non_monotonic_rejected(self, tmp_path):
        cfg = copy.deepcopy(load_rule_config().raw)
        cfg["market_regime"]["suppressed_max_boards"] = 1  # < frozen=2
        self._expect_invalid(tmp_path, cfg)

    def test_negative_seal_funds_rejected(self, tmp_path):
        cfg = copy.deepcopy(load_rule_config().raw)
        cfg["f19"]["min_seal_funds_yuan"] = -1
        self._expect_invalid(tmp_path, cfg)

    def test_volume_ratio_thresholds_non_monotonic_rejected(self, tmp_path):
        """volume_ratio significant_threshold > nuke_threshold 必须拒绝(fail closed)。"""
        cfg = copy.deepcopy(load_rule_config().raw)
        cfg["volume_ratio"]["significant_threshold"] = 4.0  # > nuke=3.0
        self._expect_invalid(tmp_path, cfg)

    def _expect_invalid(self, tmp_path: Path, cfg: dict) -> None:
        p = tmp_path / "bad.toml"
        import tomli_w

        p.write_bytes(tomli_w.dumps(cfg).encode())
        with pytest.raises(ConfigError):
            load_rule_config(p)


class TestReasonCodeStability:
    """原因码只能追加或版本化,不能改同一代码语义(方案 6.3)。"""

    REQUIRED_CODES = [
        "NOT_FIRST_BOARD",
        "ST_OR_DELISTING_RISK",
        "SEAL_FUNDS_BELOW_50M",
        "BLOWN_COUNT_ABOVE_5",
        "NO_F19_RESONANCE",
        "PERSONALITY_B_MINUS_BLOCKED",
        "PERSONALITY_C_BLOCKED",
        "PERSONALITY_D_BLOCKED",
        "PERSONALITY_DATA_MISSING",
        "EARLY_SEAL_RESONANCE",
        "LHB_RESONANCE",
        "RECENT_3D_2B_RESONANCE",
        "RECENT_4D_2B_BOOST",
        "MARKET_F18_HALT",
        "MARKET_REGIME_FROZEN",
        "TRADING_DAY_INVALID",
        "SOURCE_STALE",
        "SOURCE_SCHEMA_INVALID",
        "CRITICAL_SOURCE_UNAVAILABLE",
        "PUBLISHED_TOP5",
        "RANKED_OUTSIDE_TOP5",
    ]

    def test_all_required_codes_present(self):
        values = {rc.value for rc in ReasonCode}
        for code in self.REQUIRED_CODES:
            assert code in values, f"missing reason code: {code}"

    def test_codes_are_stable_strings(self):
        # 原因码值必须等于其名,便于跨服务检索
        for rc in ReasonCode:
            assert rc.value == rc.name


class TestEnums:
    def test_data_status_has_five_states(self):
        assert {s.value for s in DataStatus} == {
            "OK",
            "DEGRADED",
            "STALE",
            "INVALID",
            "UNAVAILABLE",
        }

    def test_publication_status_states(self):
        # 方案 9.3:PUBLISHED_TOP5 / RANKED_OUTSIDE_TOP5 用于候选发布标记;
        # OBSERVATION_ONLY 为仅观察;BLOCKED 为发布闸门阻断。
        assert {s.value for s in PublicationStatus} == {
            "PUBLISHED",
            "PUBLISHED_TOP5",
            "RANKED_OUTSIDE_TOP5",
            "OBSERVATION_ONLY",
            "BLOCKED",
        }

    def test_personality_grades(self):
        assert PersonalityGrade.S.value == "S"
        assert PersonalityGrade.B_MINUS.value == "B_MINUS"
        assert PersonalityGrade.UNKNOWN.value == "UNKNOWN"

    def test_market_regime_states(self):
        assert {s.value for s in MarketRegime} == {
            "FROZEN",
            "SUPPRESSED",
            "ACTIVE",
            "MAIN_UP",
            "UNKNOWN",
        }

    def test_position_policy_states(self):
        assert {s.value for s in PositionPolicy} == {
            "HALT",
            "DEFENSIVE",
            "STANDARD",
            "AGGRESSIVE",
            "UNKNOWN",
        }

    def test_execution_actions(self):
        assert {s.value for s in ExecutionAction} == {
            "NO_TRADE",
            "WATCH",
            "CONDITIONAL_BUY",
            "HOLD",
            "REDUCE",
            "EXIT",
        }


def test_volume_ratio_missing_reason_code_exists():
    """VOLUME_RATIO_MISSING 原因码已定义。"""
    from rule_contract import ReasonCode
    assert ReasonCode.VOLUME_RATIO_MISSING.value == "VOLUME_RATIO_MISSING"


def test_volume_ratio_nuke_reason_code_exists():
    """VOLUME_RATIO_NUKE 原因码已定义。"""
    from rule_contract import ReasonCode
    assert ReasonCode.VOLUME_RATIO_NUKE.value == "VOLUME_RATIO_NUKE"


def test_enforce_volume_ratio_flag_validates():
    """feature_flags.enforce_volume_ratio 必须是 bool。"""
    from rule_contract import load_rule_config
    cfg = load_rule_config()
    assert isinstance(cfg.raw["feature_flags"]["enforce_volume_ratio"], bool)


def test_volume_ratio_config_section_exists():
    """[volume_ratio] 配置段存在且阈值有效。"""
    from rule_contract import load_rule_config
    cfg = load_rule_config()
    vr = cfg.raw["volume_ratio"]
    assert float(vr["nuke_threshold"]) == 3.0
    assert int(vr["nuke_points"]) == 10
    assert float(vr["significant_threshold"]) == 2.0
    assert int(vr["significant_points"]) == 5
    assert float(vr["shrink_threshold"]) == 0.8
    assert int(vr["shrink_points"]) == -3
    assert int(vr["position_lookback"]) >= 1
    assert int(vr["volume_ma_window"]) >= 1
