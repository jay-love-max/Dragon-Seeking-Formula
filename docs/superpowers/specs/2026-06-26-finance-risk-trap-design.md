# 寻龙诀 · 财务排雷指标补全设计方案

* **日期**：2026-06-26
* **版本**：1.0
* **作者**：Antigravity (Oh My Pi Coding Agent)
* **状态**：设计中（待评审）
* **结论**：在现有 `AStockDataAdapter.get_finance_data()` 与 `recap_engine` 审计链路上，补齐商誉、应收、负债率等财务排雷字段，并把它们固化为可测试、可解释的 `risk_level` 判定。

---

## 1. 背景与目标

当前项目已经能从本地 Parquet 财务快照读取净利润、净资产、营收、总股本等字段，并在复盘审计里生成 `risk_level` 与三席位摘要。但排雷维度仍然偏弱：

1. **字段覆盖不完整**：现有逻辑主要依赖 `jinglirun / jingzichan / zongguben / liudongfuzhai / changqifuzhai / zongzichan`，但对商誉、应收账款、应收占比等排雷字段没有统一口径。
2. **风险表达偏粗**：`risk_level` 目前更多是“是否明显 ST”或“是否有基础财务结构问题”的粗分，难以稳定表达“危险”与“极度危险”的边界。
3. **提示文案有过度断言风险**：现有摘要里会写“未检测到高风险商誉与应收账款积压”，但在字段缺失时这句话容易给出过强结论。

本次设计目标：

1. **补全排雷字段**：优先从本地财务 Parquet 中读取商誉、应收账款、总资产、净资产、流动负债、非流动负债等字段，并做多列名归一。
2. **固化排雷规则**：把 ST、资产负债率、商誉占比、应收占比转成明确的 `risk_level` 判定与风险原因列表。
3. **保留现有数据链路**：不改变 `uzi_audit` 表结构，不引入新子进程，不破坏当前 UZI 审计与复盘输出。

---

## 2. 设计范围

### 2.1 涉及模块

- `src/data_adapters/a_stock_adapter.py`
- `src/recap_engine.py`
- `tests/test_recap_pipeline.py`

### 2.2 不在范围内

- 新增外部数据源接入
- 改写前端看板主题或布局
- 新增数据库表
- 引入新的模型服务或子进程管线

---

## 3. 数据层设计

### 3.1 读取优先级

沿用当前策略：

1. **本地 Parquet 优先**：读取 `DATA_DIR/financials/*/part.parquet`
2. **本地无数据时回退**：继续使用现有 `mootdx` 财务接口作为兜底
3. **接口失败时保持空字典**：由上层审计逻辑决定降级文案，不在适配层伪造数据

### 3.2 财务字段归一

在 `get_finance_data()` 中，除现有字段外，新增以下统一字段：

- `goodwill`：商誉
- `accounts_receivable`：应收账款
- `receivable_ratio`：应收账款 / 总资产
- `goodwill_ratio`：商誉 / 净资产
- `asset_liability_ratio`：负债 / 总资产
- `st_flag`：是否存在 ST / *ST 风险标记
- `risk_flags`：结构化红线列表，例如 `['st', 'high_liability']`

### 3.3 多列名映射

本地 Parquet 的列名允许不统一，但需要在适配层归一成固定字段。设计上采用“候选列名顺序匹配”：

- 商誉：`goodwill` -> `商誉` -> `goodwill_value`
- 应收账款：`accounts_receivable` -> `应收账款` -> `ar` -> `receivable`
- 总资产：`zongzichan` -> `total_assets` -> `总资产`
- 净资产：`jingzichan` -> `total_equity` -> `净资产`
- 流动负债：`liudongfuzhai` -> `current_liability` -> `流动负债`
- 非流动负债：`changqifuzhai` -> `noncurrent_liability` -> `非流动负债`

若某项关键字段缺失，则不补默认值，只返回已确认的字段。

---

## 4. 排雷规则设计

### 4.1 风险等级仍保持三档

当前项目和测试约束都围绕三档输出：

- `安全`
- `危险`
- `极度危险`

不新增第四档，避免打断现有审计接口。

### 4.2 判定规则

优先级从高到低：

1. **ST / *ST 直接命中**
   - `risk_level = 极度危险`
2. **多项硬红线同时命中**
   - 若以下红线命中 2 项及以上：
     - 资产负债率 `>= 75%`
     - 商誉占净资产比 `>= 30%`
     - 应收账款占总资产比 `>= 50%`
   - 则 `risk_level = 极度危险`
3. **单项硬红线命中**
   - 任一单项命中则 `risk_level = 危险`
4. **无红线**
   - `risk_level = 安全`

### 4.3 解释输出

上层审计摘要不再使用“未检测到高风险商誉与应收账款积压”这种绝对句式，而是改成可解释、可降级的描述：

- 有红线：列出具体命中的项目和阈值
- 无红线：写“当前财务排雷未命中明确红线”
- 字段缺失：写“部分排雷字段缺失，当前仅能基于已知财务快照判断”

这样避免把“没查到”误写成“没问题”。

---

## 5. 审计链路设计

### 5.1 `recap_engine` 中的消费方式

`run_recap()` 里在读取 `finance_dict` 后，继续计算现有的价值分与动量分，同时新增一个小的排雷判定块：

- 先从 `finance_dict` 读取 `jinglirun / jingzichan / zongguben / liudongfuzhai / changqifuzhai / zongzichan / goodwill / accounts_receivable`
- 计算：
  - `asset_liability_ratio`
  - `goodwill_ratio`
  - `receivable_ratio`
- 生成：
  - `risk_flags`
  - `risk_level`
  - `risk_notes`

### 5.2 `_build_uzi_analysis_payload()` 里的表现

审计 payload 保持现有结构，不大改 schema，只增强以下内容：

- `dim_commentary["1_financials"]`：增加商誉、应收、负债率的摘要
- `dim_commentary["18_trap"]`：明确写出命中的红线或“无明确红线”
- `evidence_map["18_trap"]`：优先写真实数值证据，不再只写空洞占位语

### 5.3 摘要文案

本地规则模拟器输出的 `summary` 维持三席位结构，但排雷席位改成：

- 命中风险时：写出具体红线和等级
- 无命中时：写“当前财务快照未触发明确排雷红线”
- 缺字段时：写“字段缺失，排雷结论置信度下降”

---

## 6. 测试设计

### 6.1 现有测试保留

保留并继续通过以下行为：

- 数据库初始化
- `time_to_seconds()`
- 本地财务 parquet 读取
- 无 API Key 时的本地规则模拟
- 共享 AI 审计的 JSON 持久化

### 6.2 新增测试点

`tests/test_recap_pipeline.py` 需要增加：

1. **排雷字段读取测试**
   - 在临时 Parquet 中写入商誉、应收账款、总资产、净资产、负债字段
   - 验证 `get_finance_data()` 能返回归一后的字段和比例字段
2. **风险等级判定测试**
   - `ST / *ST` 样例必须返回 `极度危险`
   - 高负债 / 高商誉 / 高应收 样例分别命中 `危险` 或 `极度危险`
   - 正常样例返回 `安全`
3. **摘要文案测试**
   - 摘要里必须包含“排雷席位”字样
   - 风险命中时必须包含对应红线关键词
   - 不再断言“未检测到高风险商誉与应收账款积压”这种绝对措辞

---

## 7. 风险与回退

1. **字段缺失风险**
   - 回退策略：仅使用已确认字段，风险结论降为“基于部分数据判断”，不伪造数值
2. **外部财务源不可用**
   - 回退策略：继续使用现有本地 Parquet / API 兜底，不改变调用链
3. **历史测试脆弱**
   - 回退策略：将断言从固定长句调整为关键词和结构断言，减少文案细节耦合

---

## 8. 交付标准

满足以下条件即可认为本设计完成：

- `get_finance_data()` 能返回商誉、应收、资产负债率等排雷相关字段
- `run_recap()` 能基于这些字段稳定判定 `risk_level`
- `uzi_audit` 与 `analysis_json` 保持兼容
- 单元测试覆盖字段读取、风险判定、摘要输出三部分
- 字段缺失不会被误写成“安全”或“未检测到风险”
