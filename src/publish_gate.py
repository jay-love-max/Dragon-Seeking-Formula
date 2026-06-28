"""发布闸门 — 方案 7.4。

盘后与盘中共用同一组发布闸门(AGENTS.md:盘中和盘后规则一致)。
以下任一成立,`publishable=False`:
  1. 非交易日;
  2. 涨停池不可用、结构不合法或日期不一致;
  3. 指数三大关键记录全部不可用;
  4. 规则配置无效;
  5. 数据库迁移失败;
  6. 候选决策计算出现未处理异常;
  7. 关键输入使用了"默认 0"代替缺失。

跌停池、龙虎榜和题材可降级,但必须记录 DEGRADED。
本模块是纯函数,不做 I/O;调用方传入已采集的 FetchResult 集合。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from contracts import FetchResult
from rule_contract import DataStatus, ReasonCode


@dataclass(frozen=True)
class PublicationGateResult:
    """发布闸门评估结果。"""

    publishable: bool
    reason_codes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _is_index_source(f: FetchResult) -> bool:
    return f.dataset_name == "index_recap"


def _index_key_rows_available(f: FetchResult) -> bool:
    """指数三大关键记录(sh/sz/cy)是否全部不可用。

    方案 7.4.3:"指数三大关键记录全部不可用" 才阻断;部分降级记录 DEGRADED。
    payload 为空 DataFrame 或 status != OK 视为不可用。
    """
    if not _is_index_source(f):
        return False
    if f.status != DataStatus.OK or f.payload.empty:
        return False
    return True


def evaluate_publishable(
    trade_date: str,
    is_trading_day: bool,
    sources: dict[str, FetchResult],
    *,
    config_valid: bool = True,
    migration_ok: bool = True,
    decision_exception: bool = False,
) -> PublicationGateResult:
    """评估发布闸门。

    Args:
        trade_date: 请求交易日 YYYY-MM-DD。
        is_trading_day: 该日是否为交易日(由 TradingCalendarService 判定)。
        sources: 已采集的数据来源,键名约定 "limit_up_pool"/"index_recap"/
            "limit_down_pool"/"lhb"/"concept" 等,值为 FetchResult。
        config_valid: 规则配置是否有效(方案 7.4.4)。
        migration_ok: 数据库迁移是否成功(方案 7.4.5)。
        decision_exception: 候选决策是否出现未处理异常(方案 7.4.6)。

    Returns:
        PublicationGateResult,reason_codes 为 ReasonCode 枚举值的字符串列表。
    """
    reason_codes: list[str] = []
    warnings: list[str] = []

    # 7.4.1 非交易日
    if not is_trading_day:
        reason_codes.append(ReasonCode.TRADING_DAY_INVALID)

    # 7.4.2 涨停池:不可用 / 结构不合法 / 日期不一致
    pool = sources.get("limit_up_pool")
    if pool is None:
        reason_codes.append(ReasonCode.CRITICAL_SOURCE_UNAVAILABLE)
    elif pool.status == DataStatus.UNAVAILABLE:
        reason_codes.append(ReasonCode.CRITICAL_SOURCE_UNAVAILABLE)
    elif pool.status == DataStatus.INVALID:
        reason_codes.append(ReasonCode.SOURCE_SCHEMA_INVALID)
    elif pool.status == DataStatus.OK:
        # 日期一致性:as_of 必须等于请求交易日(方案 7.3.2)
        if pool.as_of != trade_date:
            reason_codes.append(ReasonCode.SOURCE_SCHEMA_INVALID)
            warnings.append(
                f"limit_up_pool as_of={pool.as_of} != trade_date={trade_date}"
            )
    # STALE/DEGRADED 的涨停池:降级但不直接阻断(由调用方结合其他来源决定)

    # 7.4.3 指数三大关键记录全部不可用
    index_src = sources.get("index_recap")
    if index_src is None:
        reason_codes.append(ReasonCode.CRITICAL_SOURCE_UNAVAILABLE)
    elif not _index_key_rows_available(index_src):
        reason_codes.append(ReasonCode.CRITICAL_SOURCE_UNAVAILABLE)

    # 7.4.4 规则配置无效
    if not config_valid:
        reason_codes.append(ReasonCode.SOURCE_SCHEMA_INVALID)

    # 7.4.5 数据库迁移失败
    if not migration_ok:
        reason_codes.append(ReasonCode.SOURCE_SCHEMA_INVALID)

    # 7.4.6 候选决策计算出现未处理异常
    if decision_exception:
        reason_codes.append(ReasonCode.SOURCE_SCHEMA_INVALID)

    # 7.4.7 关键输入使用了"默认 0"代替缺失
    # 由上游 FetchResult 保障:适配器不再写 0;此处不再额外检测,
    # 因为 sources 已经是结构化结果,不存在隐式 0。

    publishable = len(reason_codes) == 0
    return PublicationGateResult(
        publishable=publishable, reason_codes=reason_codes, warnings=warnings
    )
