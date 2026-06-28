"""Phase 2 F19 候选过滤与确定性 Top 5 — 纯函数实现。

方案第 9 节:
- 9.1 三层流程:候选宇宙(全部首板)→ 基础硬门槛 → 共振门槛;
- 9.2 ST 判断(主数据优先,名称正则兜底,保存 st_source);
- 9.3 确定性排序(同输入 → 同排名);
- 9.4 可解释输出(eligible / hard_gate_results / resonance_signals /
  exclusion_reason_codes / ranking_factors / rule_version / input_snapshot_hash)。

本模块是纯函数,不做 I/O;盘后与盘中共用同一逻辑(AGENTS.md)。
金额统一"元"单位;首封时间为 "HH:MM:SS" 字符串,F19 早盘共振用严格 <。
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from rule_contract import (
    CandidateEligibility,
    PublicationStatus,
    ReasonCode,
    RuleConfig,
)

# ST 名称正则兜底(方案 9.2):^(\*?ST|S\*ST|退市)
_ST_NAME_RE = re.compile(r"^(\*?ST|S\*ST|退市)")


@dataclass(frozen=True)
class CandidateDecision:
    """单个候选的完整决策记录(方案 9.4 可解释输出)。

    会被写入 candidate_decisions 与 candidate_observations;只有
    publication_status=PUBLISHED_TOP5 的才写入兼容表 candidates。
    """

    trade_date: str
    code: str
    rule_version: str
    eligible: CandidateEligibility
    publication_status: PublicationStatus
    published_rank: int | None
    base_score: int
    adjusted_score: int
    pred_prob: float | None
    personality_score: float | None
    personality_grade: str | None
    reason_codes: list[str]
    signals: dict[str, Any]
    input_hash: str


# --- ST 判断(方案 9.2) ---


def _judge_st(record: dict[str, Any]) -> tuple[bool, str]:
    """返回 (是否ST, st_source)。优先主数据,其次名称正则。

    st_source 取值:"risk_flag" | "name_regex"。
    record["is_st"] 为显式主数据标记时优先采用;否则用名称兜底。
    """
    if record.get("is_st") is True:
        return True, "risk_flag"
    name = str(record.get("name", "")).strip()
    if name and _ST_NAME_RE.match(name):
        return True, "name_regex"
    return False, "none"


# --- 首封时间比较(严格 <) ---


def _seal_before(seal_time: str, threshold: str) -> bool:
    """字符串字典序比较 "HH:MM:SS";严格 <。"""
    return str(seal_time) < threshold


# --- 共振信号 ---


def _recent_limit_up_count(code: str, recent_limit_ups_by_code: dict[str, list[str]]) -> int:
    """近 N 个交易日该 code 的封板次数(含当日)。"""
    return len(recent_limit_ups_by_code.get(code, []))


def _evaluate_resonance(
    record: dict[str, Any],
    cfg: RuleConfig,
    *,
    recent_limit_ups_by_code: dict[str, list[str]],
    lhb_status: str,
) -> tuple[list[str], dict[str, Any]]:
    """返回 (命中的共振信号 ReasonCode 列表, signals)。

    方案 9.1 第三层:至少一个明确为 true;UNKNOWN != FALSE。
    - 早盘:first_seal_time < early_seal_before(严格);
    - 龙虎榜:lhb_status == "LISTED"(明确);UNKNOWN 不计为 true 但不阻断其他信号;
    - 3d2b:近 recent_resonance_sessions 天该 code 封板次数 >= min。
    """
    signals: dict[str, Any] = {}
    resonance_hits: list[str] = []

    f19 = cfg.raw["f19"]
    early_threshold = str(f19["early_seal_before"])

    # 早盘共振
    seal_time = str(record.get("first_seal_time", ""))
    is_early = _seal_before(seal_time, early_threshold) if seal_time else False
    signals["first_seal_time"] = seal_time
    signals["is_early_seal"] = is_early
    if is_early:
        resonance_hits.append(ReasonCode.EARLY_SEAL_RESONANCE)

    # 龙虎榜共振(UNKNOWN != FALSE,但也不 == TRUE)
    signals["lhb_status"] = lhb_status
    if lhb_status == "LISTED":
        resonance_hits.append(ReasonCode.LHB_RESONANCE)

    # 3 天 2 板共振
    code = str(record["code"])
    recent_count = _recent_limit_up_count(code, recent_limit_ups_by_code)
    min_boards = int(f19["recent_resonance_min_limit_ups"])
    signals["recent_limit_up_count"] = recent_count
    signals["recent_resonance_min"] = min_boards
    if recent_count >= min_boards:
        resonance_hits.append(ReasonCode.RECENT_3D_2B_RESONANCE)

    signals["resonance_signals"] = resonance_hits
    return resonance_hits, signals


# --- F19 主流程 ---


def evaluate_f19(
    record: dict[str, Any],
    cfg: RuleConfig,
    *,
    recent_limit_ups_by_code: dict[str, list[str]] | None = None,
    lhb_status: str = "UNKNOWN",
    base_score: int | None = None,
    pred_prob: float | None = None,
) -> CandidateDecision:
    """评估单个首板候选的三层 F19 流程。

    Args:
        record: 首板观察样本(单位:元,first_seal_time 为 "HH:MM:SS")。
        cfg: 加载并校验后的规则配置。
        recent_limit_ups_by_code: {code: [该code近N天封板日期]},用于 3d2b 共振。
        lhb_status: "LISTED" | "NOT_LISTED" | "UNKNOWN"(默认 UNKNOWN)。
        base_score: 0-150 接力指数;默认从 record["score"] 取。
        pred_prob: ML 预测概率;None 表示未预测。

    Returns:
        CandidateDecision,eligible=ELIGIBLE 当且仅当通过全部硬门槛 + 至少一项共振。
        被过滤仍返回完整 decision(含全部失败原因),供 observations 使用。
    """
    recent_limit_ups_by_code = recent_limit_ups_by_code or {}
    f19 = cfg.raw["f19"]
    reason_codes: list[str] = []
    signals: dict[str, Any] = {}

    # --- 第一层:候选宇宙(调用方保证 consecutive_boards==1),此处不重复校验 ---

    # --- 第二层:基础硬门槛 ---
    hard_gate_results: dict[str, bool] = {}

    # 9.2 ST 判断
    is_st, st_source = _judge_st(record)
    signals["st_source"] = st_source
    signals["is_st"] = is_st
    require_non_st = bool(f19["require_non_st"])
    hard_gate_results["non_st"] = (not is_st) if require_non_st else True
    if require_non_st and is_st:
        reason_codes.append(ReasonCode.ST_OR_DELISTING_RISK)

    # 封单资金(元)
    seal_funds = float(record.get("seal_funds_yuan", 0.0))
    min_seal = float(f19["min_seal_funds_yuan"])
    hard_gate_results["seal_funds"] = seal_funds >= min_seal
    signals["seal_funds_yuan"] = seal_funds
    if not hard_gate_results["seal_funds"]:
        reason_codes.append(ReasonCode.SEAL_FUNDS_BELOW_50M)

    # 炸板次数
    blown = int(record.get("blown_count", 0))
    max_blown = int(f19["max_blown_count"])
    hard_gate_results["blown_count"] = blown <= max_blown
    signals["blown_count"] = blown
    if not hard_gate_results["blown_count"]:
        reason_codes.append(ReasonCode.BLOWN_COUNT_ABOVE_5)

    signals["hard_gate_results"] = hard_gate_results
    hard_pass = all(hard_gate_results.values())

    # --- 第三层:共振门槛 ---
    resonance_hits, resonance_signals = _evaluate_resonance(
        record, cfg,
        recent_limit_ups_by_code=recent_limit_ups_by_code,
        lhb_status=lhb_status,
    )
    signals.update(resonance_signals)
    required_resonance = int(f19["required_resonance_count"])
    resonance_pass = len(resonance_hits) >= required_resonance
    if hard_pass and not resonance_pass:
        reason_codes.append(ReasonCode.NO_F19_RESONANCE)

    eligible = CandidateEligibility.ELIGIBLE if (hard_pass and resonance_pass) else CandidateEligibility.INELIGIBLE

    score = int(base_score if base_score is not None else record.get("score", 0))
    return CandidateDecision(
        trade_date=str(record.get("trade_date", "")),
        code=str(record["code"]),
        rule_version=cfg.rule_version,
        eligible=eligible,
        publication_status=PublicationStatus.OBSERVATION_ONLY,  # 排序后决定
        published_rank=None,
        base_score=score,
        adjusted_score=score,  # Phase 5 启用 use_adjusted_score 前等于 base
        pred_prob=pred_prob,
        personality_score=None,
        personality_grade=None,
        reason_codes=reason_codes,
        signals=signals,
        input_hash=input_hash(record),
    )


# --- 输入 hash(方案 9.4) ---


def input_hash(record: dict[str, Any]) -> str:
    """对关键字段做 sha256,确保同输入 → 同 hash。

    只哈希规则相关的确定性字段,排除动态字段(如采集时间)。
    字段顺序固定以保证跨运行稳定。
    """
    keys = [
        "code", "trade_date", "price", "change_pct", "turnover_pct",
        "float_mcap_yuan", "seal_funds_yuan", "first_seal_time",
        "blown_count", "consecutive_boards", "is_st", "sector", "concept",
    ]
    payload = {k: record.get(k) for k in keys if k in record}
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --- 确定性排序(方案 9.3) ---


def _sort_key(d: CandidateDecision) -> tuple:
    """排序键:score 降序 → pred_prob 降序(NULL最后) → 股性分降序 →
    封单降序 → 首封升序(缺失最后) → code 升序。

    使用元组 + 负号实现降序;None 用极值排最后。
    """
    # pred_prob: None 排最后 → 用 -1.0 占位(降序取负后最大)
    pred = d.pred_prob if d.pred_prob is not None else -1.0
    # personality_score: None 排最后
    pers = d.personality_score if d.personality_score is not None else -1.0
    # 封单降序
    seal = float(d.signals.get("seal_funds_yuan", 0.0))
    # 首封升序:空字符串排最后 → 用 "99:99:99" 占位
    seal_time = str(d.signals.get("first_seal_time", "")) or "99:99:99"
    return (
        -d.adjusted_score,
        -pred,
        -pers,
        -seal,
        seal_time,
        d.code,
    )


def rank_candidates(
    decisions: list[CandidateDecision],
    cfg: RuleConfig,
) -> list[CandidateDecision]:
    """确定性排序并标记 Top 5。

    方案 9.3:通过 F17/F19 后按 score 降序等顺序排序;前 5 标记 PUBLISHED_TOP5,
    其余 RANKED_OUTSIDE_TOP5。被过滤的不发布。同样输入必须得到完全相同的排名。

    返回新的 decision 列表(不修改入参),按排名顺序排列;
    被过滤的排在已发布的之后,保持稳定。
    """
    max_n = int(cfg.max_published_candidates)

    # 分离:通过硬门槛的参与排序;被过滤的不参与 Top5
    eligible = [d for d in decisions if d.eligible == CandidateEligibility.ELIGIBLE]
    ineligible = [d for d in decisions if d.eligible != CandidateEligibility.ELIGIBLE]

    # 稳定排序(同输入同输出):Python sort 稳定,先按 code 再按主键确保确定性
    eligible_sorted = sorted(eligible, key=lambda d: d.code)
    eligible_sorted = sorted(eligible_sorted, key=_sort_key)

    ranked: list[CandidateDecision] = []
    for i, d in enumerate(eligible_sorted):
        if i < max_n:
            ranked.append(_with_status(d, PublicationStatus.PUBLISHED_TOP5, published_rank=i + 1))
        else:
            ranked.append(_with_status(d, PublicationStatus.RANKED_OUTSIDE_TOP5, published_rank=None))

    # 被过滤的:保持原顺序(按 code 升序)追加在末尾,不发布
    ineligible_sorted = sorted(ineligible, key=lambda d: d.code)
    for d in ineligible_sorted:
        ranked.append(_with_status(d, PublicationStatus.OBSERVATION_ONLY, published_rank=None))

    return ranked


def _with_status(d: CandidateDecision, status: PublicationStatus, *, published_rank: int | None) -> CandidateDecision:
    """返回更新了 publication_status / published_rank 的新 decision(frozen dataclass)。"""
    return CandidateDecision(
        trade_date=d.trade_date,
        code=d.code,
        rule_version=d.rule_version,
        eligible=d.eligible,
        publication_status=status,
        published_rank=published_rank,
        base_score=d.base_score,
        adjusted_score=d.adjusted_score,
        pred_prob=d.pred_prob,
        personality_score=d.personality_score,
        personality_grade=d.personality_grade,
        reason_codes=d.reason_codes,
        signals=d.signals,
        input_hash=d.input_hash,
    )
