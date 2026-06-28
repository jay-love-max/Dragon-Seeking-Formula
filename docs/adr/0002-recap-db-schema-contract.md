# 0002 — recap.db 跨仓库 Schema 契约

* **日期**:2026-06-26
* **状态**:已采纳
* **背景**:复盘引擎(`src/recap_engine.py`,写端)与 vendored 面板(`vendor/tickflow-stock-panel/backend/app/api/recap.py`,读端)通过 `data/recap.db` 隐式耦合,此前无显式契约。本 ADR 固化契约面,降低跨仓库改坏的回归风险。

## 结论

### 表级契约(必须存在,否则 `GET /api/recap/all` 返回 500)
- `market_recap`(PK `date`)
- `candidates`(PK `date, code`)
- `uzi_audit`(PK `date, code`)
- `limit_ups_archive`(PK `date, code`)—— 软依赖:缺失仅使校准区为空,不崩溃(读端用 `sqlite_master` 探测)。

### 列级硬依赖(改名/删列会让面板前端运行时崩溃)

`market_recap`:`promotion_rate`、`total_turnover`、`hgt_flow`、`sgt_flow`(前端 `.toFixed()` 无空值守卫)、`sector_ranking`(JSON 字符串,读端 `json.loads` 失败兜底 `[]`)。

`candidates`:`first_seal_time`(读端直取,缺列即 `KeyError`)、`price`、`turnover`、`float_mcap`、`seal_funds`、`score`(读端 `ORDER BY score DESC` + 校准分桶,0–150 语义必须保留)。

`uzi_audit`:`average_score`(`.toFixed(1)`,条件硬:仅当记录命中选中日 + top5 时渲染)。

### 列级软依赖(缺失仅空显示/NaN,不崩溃)
`candidates.pred_prob`(前端显式空值守卫;允许 NULL)、`concept`、`blown_count`、`seal_ratio`、`playbook`、`name`、`code`;`uzi_audit.val_vote / mom_vote / risk_level / summary / report_path / sector`;`market_recap.sentiment / limit_ups / limit_downs / sh/sz/cy_*`。

### `analysis_json` 内部结构:面板不可见
面板类型声明 `UziAuditRecord.analysis_json: string?`,但前端**从不 `JSON.parse`、从不渲染**它。其内部键(`coverage / dim_commentary / core_conclusion / highlights / evidence_map / qualitative_deep_dive / data_gap_acknowledged` 等)对面板**零依赖**。

→ **写端可自由演进 `analysis_json` 内部结构**,无需同步面板。面板实际展示的是扁平 `summary` 字符串字段。

### `pred_prob` 数值来源可变
`candidates.pred_prob REAL` 列契约仅要求:列存在、可为 NULL、为 `[0,1]` 概率。其数值来源(规则/ML/任意模型)可自由替换,不影响面板。

## 影响
- 写端改 `candidates.score` 列名/语义 → 必须同步面板(`recap.py:159` ORDER BY + `:80-99` 分桶)。这是唯一需要跨仓库协调的字段演进。
- 写端重构 `analysis_json` 内部结构(如本仓库 Phase 1/2 拆 UZI payload)→ **无需**改面板,前端零影响。
- 引入新列 → 读端 `SELECT *` 透传,无害。

## 验证
读端契约验证见 `vendor/tickflow-stock-panel/backend/app/api/recap.py`(`get_all_recap_data` + `get_recap_db_path` + `_build_uzi_analysis_payload`)。前端契约类型见 `vendor/.../frontend/src/api.ts:608-677`。
