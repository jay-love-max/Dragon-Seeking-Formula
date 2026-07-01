"""Publishing orchestration — observation-only vs full publish decisions.

Extracted from publish_gate.py. Determines whether collected data is
sufficient to publish candidate recommendations.
"""
from __future__ import annotations

from dataclasses import dataclass

from contracts import FetchResult
from data_quality import index_majority_available


@dataclass
class PublicationGateResult:
    publishable: bool
    reason_codes: list[str]
    warnings: list[str]


def evaluate_publishable(
    *,
    is_trading_day: bool,
    rule_config_valid: bool,
    migration_ok: bool,
    sources: dict[str, FetchResult],
    require_trading_day: bool = True,
    require_limit_up_pool_valid: bool = True,
    require_index_majority: bool = True,
    require_rule_config_valid: bool = True,
    require_migration_ok: bool = True,
) -> PublicationGateResult:
    reason_codes: list[str] = []
    warnings: list[str] = []

    if not is_trading_day and require_trading_day:
        reason_codes.append("TRADING_DAY_INVALID")
    if not rule_config_valid and require_rule_config_valid:
        reason_codes.append("RULE_CONFIG_INVALID")
    if not migration_ok and require_migration_ok:
        reason_codes.append("MIGRATION_FAILED")

    limit_up = sources.get("limit_up_pool")
    if limit_up is not None:
        if limit_up.status != "OK" and require_limit_up_pool_valid:
            reason_codes.append("LIMIT_UP_POOL_UNAVAILABLE")

    if not index_majority_available(sources, require_majority=require_index_majority):
        reason_codes.append("INDEX_MAJORITY_UNAVAILABLE")

    return PublicationGateResult(
        publishable=len(reason_codes) == 0,
        reason_codes=reason_codes,
        warnings=warnings,
    )
