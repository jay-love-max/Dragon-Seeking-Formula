"""Phase 2 F19 候选过滤与确定性 Top 5 — 纯函数测试。

覆盖方案第 9 节与 Phase 2 验收:
- 2026-06-24 金样本保留长电/太极/三安/航天/亚翔(均通过 F19);
- 2026-06-25/26 的科士达被 F19 过滤(无共振);
- F19 边界:封单 5000万、炸板 5/6、首封 09:59:59/10:00:00/10:00:01、ST;
- 候选每日不超过 5;
- 同样输入重复运行输出 hash、顺序一致;
- 被过滤样本仍存在 observations 中(可训练)。

所有用例本地、确定,不依赖实时网络(AGENTS.md)。
"""
from __future__ import annotations

from candidate_policy import (
    CandidateDecision,
    compute_weighted_score,
    evaluate_f19,
    input_hash,
    rank_candidates,
)
from rule_contract import (
    CandidateEligibility,
    PublicationStatus,
    ReasonCode,
    load_rule_config,
)
from tests.fixtures.golden_samples import (
    GOLDEN_2026_06_24,
    GOLDEN_2026_06_25_KESHIDA,
    SEAL_49_999_999,
    SEAL_50_000_000,
    SEAL_TIME_095959,
    SEAL_TIME_100001,
    f19_blown_boundary_records,
    f19_early_seal_boundary_records,
    f19_seal_boundary_records,
    f19_st_boundary_records,
    first_board_record,
)

# --- 共振信号辅助:近 3 天含当日至少 2 次封板 ---


def _recent_limit_ups_two(*, today_code: str) -> dict[str, list[str]]:
    """返回 limit_ups_by_code:该 code 近 3 天有 2 次封板(含当日)。"""
    return {today_code: ["2026-06-22", "2026-06-24"]}


def _recent_limit_ups_one(*, today_code: str) -> dict[str, list[str]]:
    """返回 limit_ups_by_code:该 code 近 3 天仅当日 1 次封板。"""
    return {today_code: ["2026-06-24"]}


# --- F19 第二层:基础硬门槛 ---


class TestF19HardGates:
    """方案 9.1 第二层:非ST + 封单≥5000万 + 炸板≤5 + 关键字段可用。"""

    def test_seal_exactly_50m_passes_hard_gate(self):
        cfg = load_rule_config()
        recs = f19_seal_boundary_records()
        _, equal, _ = recs
        decision = evaluate_f19(equal, cfg, recent_limit_ups_by_code=_recent_limit_ups_two(today_code=equal["code"]))
        # 封单恰好通过硬门槛;共振由 3d2b 满足
        assert ReasonCode.SEAL_FUNDS_BELOW_50M not in decision.reason_codes

    def test_seal_below_50m_filtered(self):
        cfg = load_rule_config()
        recs = f19_seal_boundary_records()
        below, *_ = recs
        decision = evaluate_f19(below, cfg, recent_limit_ups_by_code=_recent_limit_ups_two(today_code=below["code"]))
        assert decision.eligible != CandidateEligibility.ELIGIBLE
        assert ReasonCode.SEAL_FUNDS_BELOW_50M in decision.reason_codes

    def test_blown_exactly_5_passes(self):
        cfg = load_rule_config()
        recs = f19_blown_boundary_records()
        five, _ = recs
        decision = evaluate_f19(five, cfg, recent_limit_ups_by_code=_recent_limit_ups_two(today_code=five["code"]))
        assert ReasonCode.BLOWN_COUNT_ABOVE_5 not in decision.reason_codes

    def test_blown_6_filtered(self):
        cfg = load_rule_config()
        recs = f19_blown_boundary_records()
        _, six = recs
        decision = evaluate_f19(six, cfg, recent_limit_ups_by_code=_recent_limit_ups_two(today_code=six["code"]))
        assert decision.eligible != CandidateEligibility.ELIGIBLE
        assert ReasonCode.BLOWN_COUNT_ABOVE_5 in decision.reason_codes

    def test_st_filtered(self):
        cfg = load_rule_config()
        recs = f19_st_boundary_records()
        decision = evaluate_f19(recs[0], cfg, recent_limit_ups_by_code=_recent_limit_ups_two(today_code=recs[0]["code"]))
        assert decision.eligible != CandidateEligibility.ELIGIBLE
        assert ReasonCode.ST_OR_DELISTING_RISK in decision.reason_codes

    def test_st_judgment_source_recorded(self):
        """方案 9.2:所有 ST 判断必须保存 st_source。"""
        cfg = load_rule_config()
        recs = f19_st_boundary_records()
        decision = evaluate_f19(recs[0], cfg, recent_limit_ups_by_code=_recent_limit_ups_two(today_code=recs[0]["code"]))
        assert decision.signals.get("st_source") is not None

    def test_hard_gate_collects_all_failure_reasons(self):
        """方案 9.4:禁止只保存最后一条失败原因。"""
        cfg = load_rule_config()
        # 同时违反 ST + 封单不足 + 炸板过多
        bad = first_board_record(
            "300099",
            "ST炸板封单全违规",
            seal_funds_yuan=SEAL_49_999_999,
            blown_count=6,
            first_seal_time=SEAL_TIME_095959,
            is_st=True,
            trade_date="2026-06-24",
        )
        decision = evaluate_f19(bad, cfg, recent_limit_ups_by_code=_recent_limit_ups_one(today_code=bad["code"]))
        assert ReasonCode.ST_OR_DELISTING_RISK in decision.reason_codes
        assert ReasonCode.SEAL_FUNDS_BELOW_50M in decision.reason_codes
        assert ReasonCode.BLOWN_COUNT_ABOVE_5 in decision.reason_codes


# --- F19 第三层:共振门槛 ---


class TestF19Resonance:
    """方案 9.1 第三层:至少一个共振明确为 true;UNKNOWN != FALSE。"""

    def test_early_seal_095959_is_resonance(self):
        cfg = load_rule_config()
        recs = f19_early_seal_boundary_records()
        early, *_ = recs
        # 仅早盘共振,无 3d2b 无龙虎榜
        decision = evaluate_f19(early, cfg, recent_limit_ups_by_code=_recent_limit_ups_one(today_code=early["code"]))
        assert ReasonCode.EARLY_SEAL_RESONANCE in decision.signals.get("resonance_signals", [])
        assert decision.eligible == CandidateEligibility.ELIGIBLE

    def test_early_seal_exactly_100000_not_resonance(self):
        """严格 <,恰好 10:00:00 不算早盘共振(方案裁决)。"""
        cfg = load_rule_config()
        recs = f19_early_seal_boundary_records()
        _, exact, _ = recs
        decision = evaluate_f19(exact, cfg, recent_limit_ups_by_code=_recent_limit_ups_two(today_code=exact["code"]))
        # 无早盘,但有 3d2b → 仍通过
        assert ReasonCode.EARLY_SEAL_RESONANCE not in decision.signals.get("resonance_signals", [])
        assert ReasonCode.RECENT_3D_2B_RESONANCE in decision.signals.get("resonance_signals", [])

    def test_early_seal_100001_not_resonance(self):
        cfg = load_rule_config()
        recs = f19_early_seal_boundary_records()
        *_, late = recs
        decision = evaluate_f19(late, cfg, recent_limit_ups_by_code=_recent_limit_ups_two(today_code=late["code"]))
        assert ReasonCode.EARLY_SEAL_RESONANCE not in decision.signals.get("resonance_signals", [])

    def test_no_resonance_filtered(self):
        """科士达:封单充足 + 非ST + 0炸板,但无共振 → 过滤。"""
        cfg = load_rule_config()
        decision = evaluate_f19(
            GOLDEN_2026_06_25_KESHIDA,
            cfg,
            recent_limit_ups_by_code=_recent_limit_ups_one(today_code=GOLDEN_2026_06_25_KESHIDA["code"]),
        )
        assert decision.eligible != CandidateEligibility.ELIGIBLE
        assert ReasonCode.NO_F19_RESONANCE in decision.reason_codes

    def test_lhb_unknown_does_not_equal_false(self):
        """方案 9.1:龙虎榜数据源失败时,UNKNOWN 不等于 FALSE。
        若其他共振成立仍可通过;若全无则过滤。"""
        cfg = load_rule_config()
        rec = first_board_record(
            "300040",
            "龙虎榜未知但有早盘",
            seal_funds_yuan=SEAL_50_000_000,
            blown_count=0,
            first_seal_time=SEAL_TIME_095959,
            trade_date="2026-06-24",
        )
        decision = evaluate_f19(
            rec, cfg,
            recent_limit_ups_by_code=_recent_limit_ups_one(today_code=rec["code"]),
            lhb_status="UNKNOWN",
        )
        assert decision.eligible == CandidateEligibility.ELIGIBLE
        assert decision.signals.get("lhb_status") == "UNKNOWN"

    def test_lhb_listed_is_resonance(self):
        cfg = load_rule_config()
        rec = first_board_record(
            "300041",
            "龙虎榜上榜",
            seal_funds_yuan=SEAL_50_000_000,
            blown_count=0,
            first_seal_time=SEAL_TIME_100001,  # 非早盘
            trade_date="2026-06-24",
        )
        decision = evaluate_f19(
            rec, cfg,
            recent_limit_ups_by_code=_recent_limit_ups_one(today_code=rec["code"]),
            lhb_status="LISTED",
        )
        assert ReasonCode.LHB_RESONANCE in decision.signals.get("resonance_signals", [])
        assert decision.eligible == CandidateEligibility.ELIGIBLE

    def test_recent_3d_2b_is_resonance(self):
        cfg = load_rule_config()
        rec = first_board_record(
            "300042",
            "3天2板",
            seal_funds_yuan=SEAL_50_000_000,
            blown_count=0,
            first_seal_time=SEAL_TIME_100001,  # 非早盘
            trade_date="2026-06-24",
        )
        decision = evaluate_f19(
            rec, cfg,
            recent_limit_ups_by_code=_recent_limit_ups_two(today_code=rec["code"]),
            lhb_status="NOT_LISTED",
        )
        assert ReasonCode.RECENT_3D_2B_RESONANCE in decision.signals.get("resonance_signals", [])
        assert decision.eligible == CandidateEligibility.ELIGIBLE


# --- 确定性排序与 Top 5 ---


class TestDeterministicRanking:
    """方案 9.3:同样输入必须得到完全相同的排名;每日不超过 5。"""

    def _decisions_for_golden(self) -> list[CandidateDecision]:
        cfg = load_rule_config()
        return [
            evaluate_f19(r, cfg, recent_limit_ups_by_code=_recent_limit_ups_two(today_code=r["code"]))
            for r in GOLDEN_2026_06_24
        ]

    def test_ranking_is_deterministic(self):
        decisions = self._decisions_for_golden()
        ranked1 = rank_candidates(decisions, load_rule_config())
        ranked2 = rank_candidates(decisions, load_rule_config())
        codes1 = [d.code for d in ranked1]
        codes2 = [d.code for d in ranked2]
        assert codes1 == codes2

    def test_top5_at_most_five(self):
        cfg = load_rule_config()
        # 构造 7 个通过的候选
        recs = []
        for i in range(7):
            recs.append(first_board_record(
                f"3000{i:02d}", f"股票{i}",
                seal_funds_yuan=SEAL_50_000_000 + i * 10_000_000,
                blown_count=0,
                first_seal_time=SEAL_TIME_095959,
                trade_date="2026-06-24",
            ))
        decisions = [
            evaluate_f19(r, cfg, recent_limit_ups_by_code=_recent_limit_ups_two(today_code=r["code"]))
            for r in recs
        ]
        ranked = rank_candidates(decisions, cfg)
        published = [d for d in ranked if d.publication_status == PublicationStatus.PUBLISHED_TOP5]
        assert len(published) <= cfg.max_published_candidates

    def test_ranking_tiebreakers_score_then_predprob_then_code(self):
        """方案 9.3 排序:score 降序 → pred_prob 降序 → 股性分降序 → 封单降序 → 首封升序 → code 升序。"""
        cfg = load_rule_config()
        recs = [
            first_board_record("300050", "同分A", seal_funds_yuan=60_000_000, blown_count=0, first_seal_time="09:30:00", trade_date="2026-06-24"),
            first_board_record("300051", "同分B", seal_funds_yuan=60_000_000, blown_count=0, first_seal_time="09:30:00", trade_date="2026-06-24"),
        ]
        decisions = [
            evaluate_f19(r, cfg, recent_limit_ups_by_code=_recent_limit_ups_two(today_code=r["code"]))
            for r in recs
        ]
        # 手动注入同分但不同 pred_prob / 封单,验证 tiebreaker
        decisions[0] = CandidateDecision(
            trade_date="2026-06-24", code="300050", rule_version=decisions[0].rule_version,
            eligible=CandidateEligibility.ELIGIBLE, publication_status=PublicationStatus.OBSERVATION_ONLY,
            published_rank=None, base_score=100, adjusted_score=100,
            pred_prob=0.6, personality_score=50.0, personality_grade="A",
            reason_codes=[], signals={}, input_hash="x",
        )
        decisions[1] = CandidateDecision(
            trade_date="2026-06-24", code="300051", rule_version=decisions[0].rule_version,
            eligible=CandidateEligibility.ELIGIBLE, publication_status=PublicationStatus.OBSERVATION_ONLY,
            published_rank=None, base_score=100, adjusted_score=100,
            pred_prob=0.7, personality_score=50.0, personality_grade="A",
            reason_codes=[], signals={}, input_hash="y",
        )
        ranked = rank_candidates(decisions, cfg)
        # pred_prob 0.7 排在 0.6 前
        assert ranked[0].code == "300051"
    def test_use_adjusted_score_flag_controls_order(self):
        cfg = load_rule_config()
        base_raw = {**cfg.raw, "feature_flags": {**cfg.raw.get("feature_flags", {}), "use_adjusted_score": False}}
        adj_raw = {**cfg.raw, "feature_flags": {**cfg.raw.get("feature_flags", {}), "use_adjusted_score": True}}
        cfg_base = type(cfg)(raw=base_raw)
        cfg_adj = type(cfg)(raw=adj_raw)
        decisions = [
            CandidateDecision(
                trade_date="2026-06-24",
                code="300050",
                rule_version=cfg.rule_version,
                eligible=CandidateEligibility.ELIGIBLE,
                publication_status=PublicationStatus.OBSERVATION_ONLY,
                published_rank=None,
                base_score=100,
                adjusted_score=90,
                pred_prob=0.5,
                personality_score=50.0,
                personality_grade="A",
                reason_codes=[],
                signals={},
                input_hash="x",
            ),
            CandidateDecision(
                trade_date="2026-06-24",
                code="300051",
                rule_version=cfg.rule_version,
                eligible=CandidateEligibility.ELIGIBLE,
                publication_status=PublicationStatus.OBSERVATION_ONLY,
                published_rank=None,
                base_score=95,
                adjusted_score=110,
                pred_prob=0.5,
                personality_score=50.0,
                personality_grade="A",
                reason_codes=[],
                signals={},
                input_hash="y",
            ),
        ]
        base_ranked = rank_candidates(decisions, cfg_base)
        adj_ranked = rank_candidates(decisions, cfg_adj)
        assert base_ranked[0].code == "300050"
        assert adj_ranked[0].code == "300051"


    def test_outside_top5_marked_ranked_outside(self):
        cfg = load_rule_config()
        recs = [
            first_board_record(f"3000{i:02d}", f"股票{i}",
                               seal_funds_yuan=SEAL_50_000_000 + i * 10_000_000,
                               blown_count=0, first_seal_time=SEAL_TIME_095959, trade_date="2026-06-24")
            for i in range(7)
        ]
        decisions = [
            evaluate_f19(r, cfg, recent_limit_ups_by_code=_recent_limit_ups_two(today_code=r["code"]))
            for r in recs
        ]
        ranked = rank_candidates(decisions, cfg)
        outside = [d for d in ranked if d.publication_status == PublicationStatus.RANKED_OUTSIDE_TOP5]
        assert len(outside) == 2  # 7 - 5 = 2

    def test_filtered_candidates_not_published(self):
        cfg = load_rule_config()
        bad = first_board_record(
            "300099", "ST违规", seal_funds_yuan=SEAL_49_999_999, blown_count=6,
            first_seal_time=SEAL_TIME_095959, is_st=True, trade_date="2026-06-24",
        )
        decision = evaluate_f19(bad, cfg, recent_limit_ups_by_code=_recent_limit_ups_one(today_code=bad["code"]))
        ranked = rank_candidates([decision], cfg)
        assert ranked[0].publication_status != PublicationStatus.PUBLISHED_TOP5


# --- F27 加权排名 ---


class TestWeightedRanking:
    """F27:ranking_mode=weighted 使用 weighted_score 排序而非 score 降序。"""

    def _make_decision(self, cfg, code: str, base_score: int = 100,
                       personality_score: float | None = 50.0,
                       seal_funds_yuan: float = 80_000_000,
                       first_seal_time: str = "09:59:59",
                       blown_count: int = 0,
                       sector_limit_up_count: int = 3) -> CandidateDecision:
        return CandidateDecision(
            trade_date="2026-06-24",
            code=code,
            rule_version=cfg.rule_version,
            eligible=CandidateEligibility.ELIGIBLE,
            publication_status=PublicationStatus.OBSERVATION_ONLY,
            published_rank=None,
            base_score=base_score,
            adjusted_score=base_score,
            pred_prob=0.5,
            personality_score=personality_score,
            personality_grade="A",
            reason_codes=[],
            signals={
                "seal_funds_yuan": seal_funds_yuan,
                "first_seal_time": first_seal_time,
                "blown_count": blown_count,
                "sector_limit_up_count": sector_limit_up_count,
            },
            input_hash="x",
        )

    def test_weighted_score_stability_early_seal(self):
        cfg = load_rule_config()
        weights = {"bid_stability": 0.40, "personality_grade": 0.25, "sector_heat": 0.20, "seal_funds": 0.15}
        d_early = self._make_decision(cfg, "300050", first_seal_time="09:59:59", blown_count=0)
        d_late = self._make_decision(cfg, "300051", first_seal_time="13:00:00", blown_count=3)
        s_early = compute_weighted_score(d_early, weights)
        s_late = compute_weighted_score(d_late, weights)
        assert s_early > s_late  # 早盘 + 0炸板 > 尾盘 + 3炸板

    def test_weighted_score_personality_matters(self):
        cfg = load_rule_config()
        weights = {"bid_stability": 0.40, "personality_grade": 0.25, "sector_heat": 0.20, "seal_funds": 0.15}
        d_high = self._make_decision(cfg, "300050", personality_score=85.0)
        d_low = self._make_decision(cfg, "300051", personality_score=30.0)
        s_high = compute_weighted_score(d_high, weights)
        s_low = compute_weighted_score(d_low, weights)
        assert s_high > s_low

    def test_weighted_mode_ranks_by_composite(self):
        cfg = load_rule_config()
        raw = {
            **cfg.raw,
            "feature_flags": {**cfg.raw.get("feature_flags", {}), "ranking_mode": "weighted"},
            "ranking_weights": {"bid_stability": 0.40, "personality_grade": 0.25, "sector_heat": 0.20, "seal_funds": 0.15},
        }
        cfg_w = type(cfg)(raw=raw)

        d_good = self._make_decision(cfg_w, "300050", base_score=100, personality_score=85.0,
                                     first_seal_time="09:30:00", blown_count=0,
                                     seal_funds_yuan=200_000_000, sector_limit_up_count=5)
        d_bad = self._make_decision(cfg_w, "300051", base_score=145, personality_score=30.0,
                                    first_seal_time="14:55:00", blown_count=5,
                                    seal_funds_yuan=50_000_001, sector_limit_up_count=0)

        ranked = rank_candidates([d_good, d_bad], cfg_w)
        # 高维合成分的应在低分前,即使 base_score 更低
        assert ranked[0].code == "300050"
        assert ranked[1].code == "300051"

    def test_weighted_scores_stored_in_return_no_signals_mutation(self):
        """加权排序不修改 decision 对象的 signals。"""
        cfg = load_rule_config()
        weights = {"bid_stability": 0.40, "personality_grade": 0.25, "sector_heat": 0.20, "seal_funds": 0.15}
        d = self._make_decision(cfg, "300050")
        signals_before = dict(d.signals)
        _ = compute_weighted_score(d, weights)
        assert d.signals == signals_before


# --- 输入 hash 稳定性 ---


class TestInputHash:
    """方案 9.4 input_snapshot_hash:同样输入必须得到相同 hash。"""

    def test_same_input_same_hash(self):
        rec = GOLDEN_2026_06_24[0]
        h1 = input_hash(rec)
        h2 = input_hash(rec)
        assert h1 == h2

    def test_different_input_different_hash(self):
        rec1 = GOLDEN_2026_06_24[0]
        rec2 = dict(rec1)
        rec2["seal_funds_yuan"] = rec1["seal_funds_yuan"] + 1
        assert input_hash(rec1) != input_hash(rec2)

    def test_hash_is_hex_digest(self):
        rec = GOLDEN_2026_06_24[0]
        h = input_hash(rec)
        assert len(h) == 64  # sha256 hex
        int(h, 16)  # valid hex

    def test_decision_records_input_hash(self):
        cfg = load_rule_config()
        rec = GOLDEN_2026_06_24[0]
        decision = evaluate_f19(rec, cfg, recent_limit_ups_by_code=_recent_limit_ups_two(today_code=rec["code"]))
        assert decision.input_hash == input_hash(rec)


# --- 金样本集成 ---


class TestGolden2026_06_24Integration:
    """2026-06-24 金样本:5 只全部通过 F19,排序后全部进入 Top 5。"""

    def test_all_five_eligible(self):
        cfg = load_rule_config()
        for r in GOLDEN_2026_06_24:
            decision = evaluate_f19(r, cfg, recent_limit_ups_by_code=_recent_limit_ups_two(today_code=r["code"]))
            assert decision.eligible == CandidateEligibility.ELIGIBLE, (
                f"{r['code']} {r['name']} not eligible: {decision.reason_codes}"
            )

    def test_all_five_published_in_top5(self):
        cfg = load_rule_config()
        decisions = [
            evaluate_f19(r, cfg, recent_limit_ups_by_code=_recent_limit_ups_two(today_code=r["code"]))
            for r in GOLDEN_2026_06_24
        ]
        ranked = rank_candidates(decisions, cfg)
        published_codes = {d.code for d in ranked if d.publication_status == PublicationStatus.PUBLISHED_TOP5}
        expected = {"600584", "600667", "600703", "002025", "603929"}
        assert published_codes == expected

    def test_ranking_order_stable_across_runs(self):
        cfg = load_rule_config()
        decisions = [
            evaluate_f19(r, cfg, recent_limit_ups_by_code=_recent_limit_ups_two(today_code=r["code"]))
            for r in GOLDEN_2026_06_24
        ]
        run1 = [d.code for d in rank_candidates(decisions, cfg)]
        run2 = [d.code for d in rank_candidates(decisions, cfg)]
        assert run1 == run2


class TestGolden2026_06_25KeshidaFilteredIntegration:
    """科士达 002518 被过滤(无共振),但仍进入 observations 可训练。"""

    def test_keshida_filtered(self):
        cfg = load_rule_config()
        decision = evaluate_f19(
            GOLDEN_2026_06_25_KESHIDA, cfg,
            recent_limit_ups_by_code=_recent_limit_ups_one(today_code=GOLDEN_2026_06_25_KESHIDA["code"]),
        )
        assert decision.eligible != CandidateEligibility.ELIGIBLE
        assert ReasonCode.NO_F19_RESONANCE in decision.reason_codes

    def test_keshida_still_in_observations(self):
        """方案 9.1 第一层:全量进入 candidate_observations,供训练。"""
        # 被过滤的候选仍保留 decision 记录(不写入 candidates 兼容表,但写 observations)
        cfg = load_rule_config()
        decision = evaluate_f19(
            GOLDEN_2026_06_25_KESHIDA, cfg,
            recent_limit_ups_by_code=_recent_limit_ups_one(today_code=GOLDEN_2026_06_25_KESHIDA["code"]),
        )
        assert decision.eligible == CandidateEligibility.INELIGIBLE
        assert decision.publication_status != PublicationStatus.PUBLISHED_TOP5
