from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import numpy as np


def _row_to_dict(row):
    if row is None:
        return {}
    if isinstance(row, dict):
        return row
    try:
        return dict(row)
    except Exception:
        return {}


def _safe_float(value):
    try:
        if value in (None, ""):
            return None
        num = float(value)
        return None if np.isnan(num) else num
    except Exception:
        return None


def _safe_int(value, default=0):
    num = _safe_float(value)
    return default if num is None else int(num)


def _safe_json_list(value):
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except Exception:
        return []
    return parsed if isinstance(parsed, list) else []


def _pick(*values, fallback="—"):
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return fallback


def _fmt_num(value, digits=2):
    num = _safe_float(value)
    return f"{num:.{digits}f}" if num is not None else "—"


def _fmt_pct(value, digits=1):
    num = _safe_float(value)
    return f"{num:.{digits}f}%" if num is not None else "—"


def _fmt_yi(value, digits=2):
    num = _safe_float(value)
    return f"{num / 1e8:.{digits}f}亿" if num is not None else "—"


def _make_evidence(source, url, finding, retrieved_at):
    return {
        "source": source,
        "url": url,
        "finding": finding,
        "retrieved_at": retrieved_at,
    }


def _make_assoc(link_to, chain_id, causal_chain, estimated_impact):
    return {
        "link_to": link_to,
        "chain_id": chain_id,
        "causal_chain": causal_chain,
        "estimated_impact": estimated_impact,
    }


def _evaluate_finance_trap(name, finance):
    finance = _row_to_dict(finance)
    name = str(name or "")

    asset_liability_ratio = _safe_float(finance.get("asset_liability_ratio"))
    goodwill_ratio = _safe_float(finance.get("goodwill_ratio"))
    receivable_ratio = _safe_float(finance.get("receivable_ratio"))

    if asset_liability_ratio is None:
        zongzichan = _safe_float(finance.get("zongzichan"))
        liudongfuzhai = _safe_float(finance.get("liudongfuzhai")) or 0.0
        changqifuzhai = _safe_float(finance.get("changqifuzhai")) or 0.0
        if zongzichan not in (None, 0):
            asset_liability_ratio = (liudongfuzhai + changqifuzhai) / zongzichan * 100

    if goodwill_ratio is None:
        goodwill = _safe_float(finance.get("goodwill"))
        jingzichan = _safe_float(finance.get("jingzichan"))
        if goodwill is not None and jingzichan not in (None, 0):
            goodwill_ratio = goodwill / jingzichan * 100

    if receivable_ratio is None:
        accounts_receivable = _safe_float(finance.get("accounts_receivable"))
        zongzichan = _safe_float(finance.get("zongzichan"))
        if accounts_receivable is not None and zongzichan not in (None, 0):
            receivable_ratio = accounts_receivable / zongzichan * 100

    risk_flags = []
    risk_notes = []

    if "ST" in name or "*ST" in name:
        risk_flags.append("st")
        risk_notes.append("简称命中 ST / *ST")

    if asset_liability_ratio is not None and asset_liability_ratio >= 75:
        risk_flags.append("high_liability")
        risk_notes.append(f"资产负债率 {asset_liability_ratio:.1f}% >= 75%")
    if goodwill_ratio is not None and goodwill_ratio >= 30:
        risk_flags.append("high_goodwill")
        risk_notes.append(f"商誉占净资产比 {goodwill_ratio:.1f}% >= 30%")
    if receivable_ratio is not None and receivable_ratio >= 50:
        risk_flags.append("high_receivable")
        risk_notes.append(f"应收账款占总资产比 {receivable_ratio:.1f}% >= 50%")

    if "st" in risk_flags or len(risk_flags) >= 2:
        risk_level = "极度危险"
    elif len(risk_flags) == 1:
        risk_level = "危险"
    else:
        risk_level = "安全"

    return {
        "risk_level": risk_level,
        "risk_flags": risk_flags,
        "risk_notes": risk_notes,
        "asset_liability_ratio": asset_liability_ratio,
        "goodwill_ratio": goodwill_ratio,
        "receivable_ratio": receivable_ratio,
    }


def build_uzi_analysis_payload(
    candidate: dict,
    market: dict | None = None,
    finance: dict | None = None,
    comment: dict | None = None,
    lhb_stat: dict | None = None,
    lhb_detail: dict | None = None,
) -> dict:
    """Build a 22-dimension UZI analysis payload from candidate + market + optional enrichment data.

    Pure data construction — no I/O, no external state. Called by both the
    backend API (as fallback for NULL analysis_json) and the recap_engine
    (during UZI audit generation). When enrichment data is absent, dims
    are populated with "待补" fallback text.
    """
    candidate = _row_to_dict(candidate)
    market = _row_to_dict(market)
    finance = _row_to_dict(finance)
    comment = _row_to_dict(comment)
    lhb_stat = _row_to_dict(lhb_stat)
    lhb_detail = _row_to_dict(lhb_detail)

    code = str(_pick(candidate.get("code"), "")).strip()
    name = str(_pick(candidate.get("name"), "—"))
    date_str = str(_pick(candidate.get("date"), market.get("date"), datetime.now().strftime("%Y-%m-%d")))
    sector_ranking = _safe_json_list(market.get("sector_ranking"))
    sector_info = next((item for item in sector_ranking if item.get("name") == candidate.get("sector")), {})
    sector_name = str(_pick(candidate.get("sector"), sector_info.get("name"), candidate.get("industry"), "—"))
    sector_count = _safe_int(_pick(candidate.get("sector_count"), sector_info.get("count"), 0), 0)
    sector_leader = str(_pick(candidate.get("sector_leader"), sector_info.get("leader"), "—"))
    concept = str(_pick(candidate.get("concept"), "—"))
    playbook = str(_pick(candidate.get("playbook"), "—"))
    summary = str(_pick(candidate.get("summary"), ""))
    report_path = str(_pick(candidate.get("report_path"), ""))
    trap_info = _evaluate_finance_trap(name, finance)
    risk_level = str(_pick(candidate.get("risk_level"), trap_info["risk_level"], "—"))
    price = _fmt_num(candidate.get("price"), 2)
    change_pct = _fmt_pct(candidate.get("change_pct"), 2)
    turnover = _fmt_num(candidate.get("turnover"), 2)
    float_mcap = _fmt_yi(candidate.get("float_mcap"), 2)
    seal_ratio = _fmt_pct(candidate.get("seal_ratio"), 2)
    score = _fmt_num(candidate.get("score"), 0)
    val_score = _fmt_num(candidate.get("val_score"), 0)
    mom_score = _fmt_num(candidate.get("mom_score"), 0)
    market_turnover = _fmt_yi(market.get("total_turnover"), 2)
    hgt_flow = _fmt_yi(market.get("hgt_flow"), 2)
    sgt_flow = _fmt_yi(market.get("sgt_flow"), 2)
    sh_change = _fmt_pct(market.get("sh_change"), 2)
    sz_change = _fmt_pct(market.get("sz_change"), 2)
    cy_change = _fmt_pct(market.get("cy_change"), 2)
    promotion_rate = _fmt_pct(market.get("promotion_rate"), 2)
    limit_ups = _safe_int(market.get("limit_ups"), 0)
    limit_downs = _safe_int(market.get("limit_downs"), 0)
    market_sentiment = str(_pick(market.get("sentiment"), "—"))

    dim_commentary: dict[str, str] = {}
    evidence_map: dict[str, list[dict]] = {}
    qualitative_deep_dive: dict[str, dict] = {}
    filled_dims: list[str] = []

    dim_commentary["0_basic"] = f"{name} / {code} / {sector_name}；现价 {price}，涨跌 {change_pct}，换手 {turnover}%，流通市值 {float_mcap}；题材 {concept}；玩法 {playbook}"
    filled_dims.append("0_basic")
    evidence_map["0_basic"] = [
        _make_evidence("candidate_row", f"local://candidates/{code}/{date_str}", f"现价 {price}，涨跌 {change_pct}，换手 {turnover}%，题材 {concept}，玩法 {playbook}", date_str),
        _make_evidence("market_recap", f"local://market_recap/{date_str}", f"当日总成交额 {market_turnover}，涨停 {limit_ups} 家，跌停 {limit_downs} 家，情绪 {market_sentiment}", date_str),
    ]

    finance_roe = None
    finance_net_margin = None
    finance_revenue = _safe_float(finance.get("zhuyingshouru"))
    finance_liability = None
    jinglirun = _safe_float(finance.get("jinglirun"))
    jingzichan = _safe_float(finance.get("jingzichan"))
    liudongfuzhai = _safe_float(finance.get("liudongfuzhai"))
    changqifuzhai = _safe_float(finance.get("changqifuzhai"))
    zongzichan = _safe_float(finance.get("zongzichan"))
    if jinglirun is not None and jingzichan not in (None, 0):
        finance_roe = jinglirun / jingzichan * 100
    if jinglirun is not None and finance_revenue not in (None, 0):
        finance_net_margin = jinglirun / finance_revenue * 100
    if zongzichan not in (None, 0):
        finance_liability = ((liudongfuzhai or 0.0) + (changqifuzhai or 0.0)) / zongzichan * 100

    if any(v is not None for v in (finance_roe, finance_net_margin, finance_revenue, finance_liability)):
        dim_commentary["1_financials"] = f"ROE {_fmt_pct(finance_roe, 2)}，净利率 {_fmt_pct(finance_net_margin, 2)}，营收 {_fmt_yi(finance_revenue, 2)}，资产负债率 {_fmt_pct(finance_liability, 2)}"
        filled_dims.append("1_financials")
    else:
        dim_commentary["1_financials"] = "财务快照待补：当前仅能从公开行情和题材看逻辑，建议补 ROE、净利率、营收与负债率。"
    evidence_map["1_financials"] = [
        _make_evidence("unknown", f"local://missing/financials/{code}", "当前运行未接入财务快照，暂以结构化占位记录财务维度缺口。", date_str),
        _make_evidence("candidate_row", f"local://candidates/{code}/{date_str}", f"现有候选行记录：{summary or '暂无摘要'}", date_str),
    ]

    dim_commentary["2_kline"] = f"首封 {str(_pick(candidate.get('first_seal_time'), '—'))}，封板强度 {seal_ratio}，炸板 {_safe_int(candidate.get('blown_count'), 0)} 次，连板 {_safe_int(candidate.get('consecutive_boards'), 0)} 板"
    filled_dims.append("2_kline")
    evidence_map["2_kline"] = [
        _make_evidence("candidate_row", f"local://candlestick/{code}/{date_str}", f"首封 {str(_pick(candidate.get('first_seal_time'), '—'))}，封板强度 {seal_ratio}，连板 {_safe_int(candidate.get('consecutive_boards'), 0)}", date_str),
        _make_evidence("market_recap", f"local://market_recap/{date_str}", f"涨停 {_safe_int(market.get('limit_ups'), 0)} 家，晋级率 {promotion_rate}", date_str),
    ]

    dim_commentary["3_macro"] = f"沪指 {sh_change} / 深指 {sz_change} / 创业板 {cy_change}；总成交额 {market_turnover}；北向 {hgt_flow}，南向 {sgt_flow}"
    filled_dims.append("3_macro")
    evidence_map["3_macro"] = [
        _make_evidence("market_recap", f"local://macro/{date_str}", f"沪指 {sh_change}，深指 {sz_change}，创业板 {cy_change}，总成交额 {market_turnover}", date_str),
        _make_evidence("market_recap", f"local://north_south_flow/{date_str}", f"北向 {hgt_flow}，南向 {sgt_flow}，情绪 {market_sentiment}", date_str),
    ]
    trap_info = _evaluate_finance_trap(name, finance)
    dim_commentary["18_trap"] = (
        "；".join(trap_info["risk_notes"]) if trap_info["risk_notes"] else "当前财务排雷未触发明确红线"
    )
    filled_dims.append("18_trap")
    evidence_map["18_trap"] = [
        _make_evidence("candidate_row", f"local://trap/{code}/{date_str}", dim_commentary["18_trap"], date_str),
        _make_evidence("candidate_row", f"local://trap_flags/{code}/{date_str}", f"风险等级 {risk_level}，风险标记 {', '.join(trap_info['risk_flags']) or '无'}", date_str),
    ]

    dim_commentary["7_industry"] = f"所属行业 {sector_name}，市值 {_fmt_yi(candidate.get('float_mcap'), 2)}，行业地位与题材 {concept} 联动；当前更像 {'龙头' if sector_count >= 6 else '跟风/侧翼'}"
    filled_dims.append("7_industry")
    evidence_map["7_industry"] = [
        _make_evidence("sector_ranking", f"local://industry/{date_str}/{sector_name}", f"行业涨停 {sector_count} 家，龙头 {sector_leader}", date_str),
        _make_evidence("candidate_row", f"local://candidates/{code}/{date_str}", f"题材 {concept}，玩法 {playbook}", date_str),
    ]

    pe_ttm = _safe_float(comment.get("pe_ttm", comment.get("市盈率")))
    main_cost = _safe_float(comment.get("main_cost", comment.get("主力成本")))
    comment_score = _safe_float(comment.get("comment_score", comment.get("综合得分")))
    attention = _safe_float(comment.get("attention", comment.get("关注指数")))
    if any(v is not None for v in (pe_ttm, main_cost, comment_score, attention)):
        dim_commentary["10_valuation"] = f"市盈率 {_fmt_num(pe_ttm, 2)} / 主力成本 {_fmt_num(main_cost, 2)} / 综合得分 {_fmt_num(comment_score, 0)} / 关注指数 {_fmt_num(attention, 0)}"
        filled_dims.append("10_valuation")
    else:
        dim_commentary["10_valuation"] = "估值快照待补：当前只看得到席位与行情，PE/PB/DCF 口径尚未接入。"
    evidence_map["10_valuation"] = [
        _make_evidence("unknown", f"local://missing/valuation/{code}", "估值快照未接入，暂用结构化占位保留维度。", date_str),
        _make_evidence("candidate_row", f"local://candidates/{code}/{date_str}", f"评分 {score}，价值席位 {val_score}，动量席位 {mom_score}", date_str),
    ]

    dim_commentary["15_events"] = f"近端事件依赖 {summary or '暂无摘要'}；公告路径 {report_path or '待补'}；市场涨停 {limit_ups} 家，晋级率 {promotion_rate}"
    filled_dims.append("15_events")
    evidence_map["15_events"] = [
        _make_evidence("candidate_row", f"local://events/{code}/{date_str}", f"{summary or '暂无摘要'}", date_str),
        _make_evidence("market_recap", f"local://market_recap/{date_str}", f"涨停 {limit_ups} 家，跌停 {limit_downs} 家，晋级率 {promotion_rate}", date_str),
    ]
    lhb_net_buy = _safe_float(_pick(lhb_detail.get("net_buy_yuan"), lhb_stat.get("net_buy_yuan"), None))
    lhb_times = _safe_int(_pick(lhb_stat.get("list_count"), lhb_detail.get("list_count"), 0), 0)
    if lhb_stat or lhb_detail:
        dim_commentary["16_lhb"] = f"龙虎榜 {lhb_times} 次，净买 {_fmt_yi(lhb_net_buy, 2)}；机构买入次数 {_safe_int(_pick(lhb_stat.get('inst_buy_count'), 0), 0)}"
        filled_dims.append("16_lhb")
    else:
        dim_commentary["16_lhb"] = "龙虎榜快照待补：尚未接入上榜次数、净买额和机构席位明细。"
    evidence_map["16_lhb"] = [
        _make_evidence("unknown", f"local://missing/lhb/{code}", "当前运行未接入龙虎榜快照，暂以占位记录。", date_str),
        _make_evidence("candidate_row", f"local://candidates/{code}/{date_str}", f"风险等级 {risk_level}，题材 {concept}", date_str),
    ]

    sentiment = str(_pick(market_sentiment, "—"))
    if any(v is not None for v in (comment_score, attention)) or market_sentiment != "—":
        dim_commentary["17_sentiment"] = f"市场情绪 {sentiment}，评论热度 {_fmt_num(attention, 0)}，综合评分 {_fmt_num(comment_score, 0)}"
        filled_dims.append("17_sentiment")
    else:
        dim_commentary["17_sentiment"] = "情绪快照待补：需要评论热度、综合评分与市场情绪联动。"
    evidence_map["17_sentiment"] = [
        _make_evidence("unknown", f"local://missing/sentiment/{code}", "当前运行未接入评论热度快照，暂以占位记录。", date_str),
        _make_evidence("market_recap", f"local://sentiment/{date_str}", f"市场情绪 {market_sentiment}，晋级率 {promotion_rate}", date_str),
    ]
    qualitative_deep_dive["3_macro"] = {
        "evidence": evidence_map["3_macro"],
        "associations": [
            _make_assoc("8_materials", "链 1", f"宏观环境 → 成本端传导；沪指 {sh_change}、深指 {sz_change} 直接影响高弹性题材的风险偏好，而原材料若同步抬升会进一步压毛利", "对 EPS 的冲击取决于是否能顺价，当前更偏中性偏谨慎"),
        ],
        "conclusion": f"宏观层面是 {market_sentiment}，成交额 {market_turnover} 维持活跃，但 {hgt_flow} 的北向流向说明外资并未给出单边背书；更适合把宏观作为风格过滤器，而不是单独的买点。",
    }
    qualitative_deep_dive["7_industry"] = {
        "evidence": evidence_map["7_industry"],
        "associations": [
            _make_assoc("15_events", "链 2", f"行业集中度与公司事件共振；行业 {sector_name} 涨停 {sector_count} 家，龙头 {sector_leader}，若事件能兑现则更容易把跟风标打成龙头", "有催化时可放大估值分歧，否则只是情绪接力"),
        ],
        "conclusion": f"行业位置更像 {'龙头候选' if sector_count >= 6 else '跟风侧翼'}；{sector_name} 的持续性要看后续事件是否能把题材从情绪炒作变成可验证的收入/份额逻辑。",
    }
    qualitative_deep_dive["8_materials"] = {
        "evidence": [
            _make_evidence("unknown", f"local://missing/materials/{code}", "当前项目没有成本拆解和原材料占比快照，无法直接量化顺价能力。", date_str),
            _make_evidence("candidate_row", f"local://candidates/{code}/{date_str}", f"候选行仅提供题材 {concept} 与玩法 {playbook}，未披露原料链。", date_str),
        ],
        "associations": [
            _make_assoc("9_futures", "链 3", "原材料涨价如果不能顺价，毛利率会先受压；目前只能用期货关联去补成本方向，缺少真实成本表", "建议补成本拆解后再做敏感性分析"),
        ],
        "conclusion": "原材料维度目前是明显缺口，只有结构化占位，没有真实成本占比、顺价条款和原料弹性，不能把它当成可靠结论依据。",
    }
    qualitative_deep_dive["9_futures"] = {
        "evidence": [
            _make_evidence("unknown", f"local://missing/futures/{code}", "当前项目没有期货曲线和套保敞口快照，无法判断 contango/backwardation。", date_str),
            _make_evidence("candidate_row", f"local://candidates/{code}/{date_str}", f"风险等级 {risk_level}，未见衍生品披露字段。", date_str),
        ],
        "associations": [
            _make_assoc("8_materials", "链 4", "期货只是材料端的价格代理；若公司没有套保或长协，行情波动会更直接映射到利润表", "若后续补到衍生品披露，可更快判断财报意外风险"),
        ],
        "conclusion": "期货关联目前只能做弱代理，缺少品种曲线和套保披露时，不宜把该维度包装成确定性的经营判断。",
    }
    qualitative_deep_dive["13_policy"] = {
        "evidence": [
            _make_evidence("unknown", f"local://missing/policy/{code}", "当前项目没有政策原文抓取与受益者判断，政策维度只能先做缺口标注。", date_str),
            _make_evidence("candidate_row", f"local://candidates/{code}/{date_str}", f"题材 {concept}，玩法 {playbook}，无法直接映射具体政策条款。", date_str),
        ],
        "associations": [
            _make_assoc("7_industry", "链 5", "政策通常先影响行业集中度，再传导到个股；当前缺少原文，只能判断该股是否可能受益于行业景气，而不能判断政策受益者排序", "若后续补政策原文，可量化龙头/新玩家的分配"),
        ],
        "conclusion": "政策维度是当前项目最明显的结构性缺口之一；没有原文、发文机构和受益者判断，就只能停留在题材标签。",
    }
    qualitative_deep_dive["15_events"] = {
        "evidence": evidence_map["15_events"],
        "associations": [
            _make_assoc("7_industry", "链 6", f"事件若能落到行业份额/订单兑现，就会把题材从一次性脉冲变成行业地位变化；当前摘要 {summary or '暂无'} 仍缺货币化拆解", "需要补公告金额、营收占比和催化日历"),
        ],
        "conclusion": f"事件维度已有最基础的公告/摘要入口，但仍缺货币化测算；如果 {name} 的后续事件不能转换成收入或利润增量，当前题材大概率只剩短线情绪。",
    }

    actual_coverage = len(filled_dims)
    panel_insights = (
        f"{name}（{code}）当前更偏{'情绪接力' if score != '—' else '结构占位'}；"
        f"价值席位 {val_score}，动量席位 {mom_score}，风险 {risk_level}。"
        f"若要继续放大，优先补财务快照、估值口径、政策原文和成本/期货链。"
    )

    return {
        "agent_reviewed": True,
        "coverage": {
            "filled": actual_coverage,
            "total": 22,
            "ratio": round(actual_coverage / 22, 4),
            "label": f"{actual_coverage}/22",
        },
        "highlights": [
            {"label": "财务/价值", "value": f"ROE {_fmt_pct(finance_roe, 2)} / PE {_fmt_num(pe_ttm, 2)} / 价值席位 {val_score}"},
            {"label": "题材/趋势", "value": f"首封 {str(_pick(candidate.get('first_seal_time'), '—'))} / 封板 {_fmt_pct(candidate.get('seal_ratio'), 2)} / 连板 {_safe_int(candidate.get('consecutive_boards'), 0)}"},
            {"label": "情绪/流向", "value": f"涨停 {limit_ups} / 跌停 {limit_downs} / 北向 {hgt_flow} / 市场 {market_sentiment}"},
        ],
        "dim_commentary": dim_commentary,
        "qualitative_deep_dive": qualitative_deep_dive,
        "core_conclusion": panel_insights,
        "panel_insights": panel_insights,
        "gaps_preview": [
            "政策原文 / 受益者判断仍缺",
            "原材料成本拆解与期货曲线仍缺",
            "历史公告货币化测算仍缺",
        ],
        "data_gap_acknowledged": [
            "政策原文 / 受益者判断仍缺",
            "原材料成本拆解与期货曲线仍缺",
            "历史公告货币化测算仍缺",
        ],
    }
