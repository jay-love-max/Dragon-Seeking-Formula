"""Phase 0 金样本 fixture — 本地、确定、不依赖实时行情接口。

覆盖方案第 19.4 节与 2.1 节验收:
- 2026-06-19:交易日闸门阻止旧数据推送(休市工作日)。
- 2026-06-24:预检指定的 5 只仍在前 5(长电/太极/三安/航天/亚翔)。
- 2026-06-25/26:科士达因无共振被 F19 过滤。
- 2026-06-25:二进三 1/7=14.29%、HALT。

所有金额以"元"为单位(方案 7.2:规则计算在统一元单位上完成,
展示转换只发生在持久化兼容层/API 层)。
首封时间为 "HH:MM:SS" 字符串,F19 共振判断用严格 < 10:00:00。
"""

from __future__ import annotations

# --- F19 边界样本(09:59:59 / 10:00:00 / 10:00:01,封单 5000 万,炸板 5/6) ---

# 恰好 10:00:00 不算早盘共振(方案裁决:严格 <)
SEAL_TIME_EXACTLY_100000 = "10:00:00"
SEAL_TIME_095959 = "09:59:59"
SEAL_TIME_100001 = "10:00:01"

# 封单资金边界(元)
SEAL_49_999_999 = 49_999_999  # 低于 5000 万 → F19 硬过滤
SEAL_50_000_000 = 50_000_000  # 等于 → 通过
SEAL_100_000_000 = 100_000_000  # 100m,无弱封单惩罚


def first_board_record(
    code: str,
    name: str,
    *,
    seal_funds_yuan: float,
    blown_count: int,
    first_seal_time: str,
    consecutive_boards: int = 1,
    is_st: bool = False,
    float_mcap_yuan: float = 5_000_000_000.0,
    turnover_pct: float = 8.0,
    change_pct: float = 10.0,
    sector: str = "电子",
    trade_date: str = "2026-06-24",
) -> dict:
    """构造一份符合 Pandera 契约的首板观察样本(单位:元)。

    所有字段显式携带单位,符合 AGENTS.md 工作约定。
    """
    return {
        "code": code,
        "name": name,
        "trade_date": trade_date,
        "price": 10.0,
        "change_pct": change_pct,
        "turnover_pct": turnover_pct,
        "float_mcap_yuan": float_mcap_yuan,
        "seal_funds_yuan": seal_funds_yuan,
        "first_seal_time": first_seal_time,
        "blown_count": blown_count,
        "consecutive_boards": consecutive_boards,
        "is_st": is_st,
        "sector": sector,
        "concept": "",
    }


# --- 2026-06-24 金样本:长电/太极/三安/航天/亚翔 应保留在前 5 ---
# 真实库 seal_funds 以百万元存,float_mcap 以十亿元存;此处 fixture 用元。
# 长电 600584、太极 600667、三安 600703、航天电器 002025、亚翔 603929
GOLDEN_2026_06_24 = [
    # 长电科技:封单 821.26 百万 ≈ 8.2e8 元,0 炸板,首封 09:57:07
    first_board_record(
        "600584",
        "长电科技",
        seal_funds_yuan=821_260_000,
        blown_count=0,
        first_seal_time="09:57:07",
        float_mcap_yuan=40_000_000_000,
        trade_date="2026-06-24",
    ),
    # 太极实业:封单 413.86 百万,1 炸板,首封 09:39:03 (早盘共振)
    first_board_record(
        "600667",
        "太极实业",
        seal_funds_yuan=413_860_000,
        blown_count=1,
        first_seal_time="09:39:03",
        float_mcap_yuan=30_000_000_000,
        trade_date="2026-06-24",
    ),
    # 三安光电:封单 650.44 百万,0 炸板,首封 09:46:12 (早盘共振)
    first_board_record(
        "600703",
        "三安光电",
        seal_funds_yuan=650_440_000,
        blown_count=0,
        first_seal_time="09:46:12",
        float_mcap_yuan=80_000_000_000,
        trade_date="2026-06-24",
    ),
    # 航天电器:封单 225.77 百万,0 炸板,首封 09:34:48 (早盘共振)
    first_board_record(
        "002025",
        "航天电器",
        seal_funds_yuan=225_770_000,
        blown_count=0,
        first_seal_time="09:34:48",
        float_mcap_yuan=25_000_000_000,
        trade_date="2026-06-24",
    ),
    # 亚翔集成:封单 105.57 百万,2 炸板,首封 09:57:59
    first_board_record(
        "603929",
        "亚翔集成",
        seal_funds_yuan=105_570_000,
        blown_count=2,
        first_seal_time="09:57:59",
        float_mcap_yuan=10_000_000_000,
        trade_date="2026-06-24",
    ),
]

# --- 2026-06-25/26 金样本:科士达 002518 应被 F19 过滤 ---
# 科士达教训(知识库 F19):封 1.44 亿 + 0 炸板 + B 级,但无共振无龙虎榜,
# 首封 10:03 偏晚 → 三项共振全无 → 过滤。
# 首封 10:03 > 10:00:00 → 非早盘;无龙虎榜;近 3 天仅今日 1 板 → 共振不达 2 次。
GOLDEN_2026_06_25_KESHIDA = first_board_record(
    "002518",
    "科士达",
    seal_funds_yuan=144_000_000,  # 1.44 亿,封单充足
    blown_count=0,
    first_seal_time="10:03:00",  # 晚于 10:00 → 非早盘共振
    float_mcap_yuan=20_000_000_000,
    trade_date="2026-06-25",
)

# --- 2026-06-25 F18 二进三:1/7=14.29% → HALT ---
# 真实库 T-1 (2026-06-24) 收盘有 7 只 consecutive_boards==2,
# T (2026-06-25) 收盘这 7 只中仅 1 只晋级为 3 板。
GOLDEN_2026_06_25_F18 = {
    "trade_date": "2026-06-25",
    "prev_trade_date": "2026-06-24",
    "prev_two_boards_codes": ["A", "B", "C", "D", "E", "F", "G"],  # denominator=7
    "today_three_boards_codes": ["A"],  # numerator=1
    "expected_rate": 1 / 7,
    "expected_policy": "HALT",  # 14.29% < 20%
}


# --- F19 边界:炸板 5(通过) vs 6(过滤) ---
def f19_blown_boundary_records() -> list[dict]:
    """炸板恰好 5 通过,6 被过滤;其余条件满足(早盘共振 + 50m 封单)。"""
    return [
        first_board_record(
            "300001",
            "炸板5通过",
            seal_funds_yuan=SEAL_50_000_000,
            blown_count=5,
            first_seal_time=SEAL_TIME_095959,
            trade_date="2026-06-24",
        ),
        first_board_record(
            "300002",
            "炸板6过滤",
            seal_funds_yuan=SEAL_50_000_000,
            blown_count=6,
            first_seal_time=SEAL_TIME_095959,
            trade_date="2026-06-24",
        ),
    ]


def f19_seal_boundary_records() -> list[dict]:
    """封单 49,999,999 过滤;50,000,000 通过;100,000,000 无弱封单惩罚标记。"""
    return [
        first_board_record(
            "300010",
            "封单不足过滤",
            seal_funds_yuan=SEAL_49_999_999,
            blown_count=0,
            first_seal_time=SEAL_TIME_095959,
            trade_date="2026-06-24",
        ),
        first_board_record(
            "300011",
            "封单恰好通过",
            seal_funds_yuan=SEAL_50_000_000,
            blown_count=0,
            first_seal_time=SEAL_TIME_095959,
            trade_date="2026-06-24",
        ),
        first_board_record(
            "300012",
            "封单充足无惩罚",
            seal_funds_yuan=SEAL_100_000_000,
            blown_count=0,
            first_seal_time=SEAL_TIME_095959,
            trade_date="2026-06-24",
        ),
    ]


def f19_early_seal_boundary_records() -> list[dict]:
    """09:59:59 早盘共振;10:00:00 不算;10:00:01 不算(严格 <)。"""
    return [
        first_board_record(
            "300020",
            "早盘095959",
            seal_funds_yuan=SEAL_50_000_000,
            blown_count=0,
            first_seal_time=SEAL_TIME_095959,
            trade_date="2026-06-24",
        ),
        first_board_record(
            "300021",
            "恰好100000不算",
            seal_funds_yuan=SEAL_50_000_000,
            blown_count=0,
            first_seal_time=SEAL_TIME_EXACTLY_100000,
            trade_date="2026-06-24",
        ),
        first_board_record(
            "300022",
            "100001不算",
            seal_funds_yuan=SEAL_50_000_000,
            blown_count=0,
            first_seal_time=SEAL_TIME_100001,
            trade_date="2026-06-24",
        ),
    ]


# --- ST 边界:ST 先被 F19 硬过滤 ---
def f19_st_boundary_records() -> list[dict]:
    return [
        first_board_record(
            "300030",
            "ST被过滤",
            seal_funds_yuan=SEAL_50_000_000,
            blown_count=0,
            first_seal_time=SEAL_TIME_095959,
            is_st=True,
            trade_date="2026-06-24",
        ),
    ]
