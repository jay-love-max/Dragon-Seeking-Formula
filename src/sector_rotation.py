from __future__ import annotations

from dataclasses import dataclass

_SECTOR_MAP: dict[str, list[str]] = {
    "芯片概念": ["002156", "002371", "688981", "300604", "600703"],
    "5G": ["002281", "002897", "600498", "600491", "600183"],
    "军工": ["603261", "002297", "600760", "600893", "002025"],
    "低空经济": ["603261", "002965", "600038", "002025"],
    "PCB": ["002579", "600183", "002384", "002916"],
    "储能": ["002518", "300274", "300763", "002074"],
    "AI": ["603019", "000977", "300308", "688041"],
    "新能源汽车": ["002594", "300750", "002460", "300014"],
    "光伏": ["601012", "600438", "688599", "002459"],
    "机器人": ["300124", "002230", "688017", "300607"],
    "消费电子": ["002475", "601138", "002241", "300433"],
    "医药": ["600276", "300760", "000538", "600196"],
    "白酒": ["600519", "000858", "000568", "002304"],
    "金融": ["601318", "600036", "601166", "600030"],
    "地产": ["001979", "600048", "000002", "600383"],
    "化工": ["600309", "002709", "601899", "600426"],
    "有色": ["601899", "600362", "000630", "002460"],
    "钢铁": ["600019", "000932", "600010", "600022"],
    "煤炭": ["601088", "600188", "600985", "601225"],
    "电力": ["600900", "601985", "600886", "600023"],
    "通信": ["600941", "600050", "300628", "688036"],
    "半导体设备": ["002371", "688012", "300604", "688072"],
    "算力": ["603019", "000977", "300308", "688041"],
}


@dataclass
class SectorSnapshot:
    trade_date: str
    sector: str
    avg_change_pct: float
    representative_codes: list[str]
    status: str


def _tencent_quote_url(codes: list[str]) -> str:
    ts_codes = []
    for c in codes:
        if c.startswith("6"):
            ts_codes.append(f"sh{c}")
        else:
            ts_codes.append(f"sz{c}")
    return f"http://qt.gtimg.cn/q={','.join(ts_codes)}"


def fetch_sector_snapshots(trade_date: str) -> list[SectorSnapshot]:
    """Fetch sector rotation data from Tencent API.

    Returns a list of SectorSnapshot sorted by avg_change_pct descending.
    """
    import requests

    all_codes = list(set(c for codes in _SECTOR_MAP.values() for c in codes))
    url = _tencent_quote_url(all_codes)
    try:
        resp = requests.get(url, timeout=10)
        resp.encoding = "gbk"
    except Exception:
        return []

    price_by_code: dict[str, float] = {}
    for line in resp.text.split(";"):
        line = line.strip()
        if not line or not line.startswith("v_"):
            continue
        try:
            parts = line.split("~")
            if len(parts) < 33:
                continue
            raw_code = parts[2]
            change_pct = float(parts[3]) if parts[3] else 0.0
            price_by_code[raw_code] = change_pct
        except (IndexError, ValueError):
            continue

    results: list[SectorSnapshot] = []
    for sector, codes in _SECTOR_MAP.items():
        changes = [price_by_code.get(c) for c in codes if c in price_by_code]
        if not changes:
            continue
        avg_change = sum(changes) / len(changes)
        if avg_change > 2.0:
            status = "强势"
        elif avg_change < -2.0:
            status = "弱势"
        else:
            status = "中性"
        results.append(SectorSnapshot(
            trade_date=trade_date,
            sector=sector,
            avg_change_pct=round(avg_change, 2),
            representative_codes=[c for c in codes if c in price_by_code],
            status=status,
        ))

    results.sort(key=lambda s: s.avg_change_pct, reverse=True)
    return results


def format_sector_summary(snapshots: list[SectorSnapshot]) -> str:
    lines = ["板块轮动追踪:"]
    for s in snapshots:
        icon = "🔥" if s.status == "强势" else ("⚠️" if s.status == "弱势" else "➡️")
        lines.append(f"  {icon} {s.sector} {s.avg_change_pct:+.2f}%")
    return "\n".join(lines)
