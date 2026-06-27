from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

_RATE_LIMIT: dict = {}


def _rate_limited(rule_name: str, key: str) -> bool:
    rate_key = f"{rule_name}_{key}"
    now = datetime.now()
    last = _RATE_LIMIT.get(rate_key)
    if last and (now - last) < timedelta(minutes=5):
        return True
    _RATE_LIMIT[rate_key] = now
    return False


@dataclass
class Rule:
    name: str
    condition: Callable[..., bool]
    message_template: str
    dedupe_by: str = "code"

    def format(self, row) -> str:
        return self.message_template.format(
            **{k: getattr(row, k, "?") for k in ["name", "code", "sector", "blown_count", "sector_limit_ups", "score_intraday", "score_intraday_prev"]}
        )

    def matches(self, row) -> bool:
        return self.condition(row)

    def dedupe_key(self, row) -> str:
        value = getattr(row, self.dedupe_by, "")
        if value in (None, "", [], {}):
            value = getattr(row, "code", "")
        if value in (None, "", [], {}):
            value = getattr(row, "sector", "")
        return str(value or "")


RULES: list[Rule] = [
    Rule(
        name="blown_alert",
        condition=lambda r: getattr(r, "blown_count", 0) >= 2,
        message_template="⚠️ {name}({code}) 炸板 {blown_count} 次",
    ),
    Rule(
        name="sector_heat",
        condition=lambda r: getattr(r, "sector_limit_ups", 0) >= 5,
        message_template="🔥 {sector} 板块涨停 {sector_limit_ups} 家",
        dedupe_by="sector",
    ),
    Rule(
        name="opportunity_alert",
        condition=lambda r: getattr(r, "score_intraday", 0) >= 95 and getattr(r, "score_intraday_prev", 0) < 95 and getattr(r, "blown_count", 0) <= 1,
        message_template="🚀 {name}({code}) 接力指数 {score_intraday}，由 {score_intraday_prev} 站上机会区",
    ),
]


def check_rules(row) -> list[Rule]:
    matched = []
    for rule in RULES:
        if rule.matches(row) and not _rate_limited(rule.name, rule.dedupe_key(row)):
            matched.append(rule)
    return matched
