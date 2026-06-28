# Dragon-Seeking-Formula 智能体工程规范

本文件是本仓库面向编码智能体的唯一权威工程规范。仓库中的
`CLAUDE.md` 必须服从本文件，不得定义冲突规则。

## 产品边界

Dragon-Seeking-Formula 是面向 A 股首板进二板场景的盘后与盘中决策支持
系统，包括确定性接力评分、晋级概率建模、数据质量闸门和 UZI 审计。

系统只能输出研究和交易建议，不得连接券商、自动下单，也不得把模型输出
表述为确定性投资收益。

修改领域行为前，按顺序阅读：

1. `CONTEXT.md`：领域语言和产品边界；
2. `docs/adr/`：已采纳的架构契约；
3. `/Users/angojay/30_Knowledge/Dragon-Seeking`：领域证据；
4. `.omx/plans/dragon-seeking-rule-gap-transformation.md`：当前规则改造方案。

知识库是决策证据，不是可直接执行的规格。遇到冲突时，必须先在仓库内形成
版本化、无歧义的规则契约，再进行实现。

## 仓库结构

- `src/recap_engine.py`：盘后编排和兼容路径；
- `src/scorer.py`：盘后与盘中共享的 0–150 接力指数；
- `src/data_adapters/`：行情和财务数据源边界；
- `src/data_pipeline/`：盘中采集、归一化、存储和告警；
- `src/recap_scheduler.py`：盘后调度；
- `data/recap.db`：与 TickFlow 面板共享的 SQLite 契约；
- `vendor/tickflow-stock-panel/`：已纳入根仓库的 TickFlow 源码区，不再作为独立 Git 仓库处理；其源码与根仓库统一追踪。

## 不可破坏的领域约束

- 保留 `candidates.score` 现有 0–150 接力指数语义；
- 全量首板观察样本必须与最终发布的 Top 5 分开保存；
- AI/UZI 可以解释确定性结果，但不能覆盖准入、排名、交易日、数据质量或
  风控结论；
- 数据缺失、过期或请求失败时，禁止填成看似有效的 0 后继续发布；
- 非交易日或关键输入无效时必须 fail closed；
- 盘中和盘后必须消费同一套规则函数，禁止复制实现；
- Formula 可以生成结构化操作建议，但不得连接券商或提交订单。

## 工作约定

- 编辑前检查 `git status` 和相关 diff。工作区可能包含大量用户改动，必须
  完整保留；
- 未经用户明确要求，禁止使用 `git reset --hard`、`git checkout --` 等
  丢弃修改的命令；
- 改动应小、可审查、可回滚；
- 优先删除和复用现有工具，不随意增加抽象层；
- 成熟开源组件确实能减少自建基础设施时，应优先复用；新增依赖必须记录
  用途、许可证、兼容性和运维成本；
- 手工编辑文件使用 `apply_patch`；
- A 股证券代码在领域边界始终使用 6 位字符串，不得转换成整数；
- 新字段名显式携带单位，如 `*_yuan`、`*_pct`、`*_seconds`，只在兼容层或
  展示层转换；
- 硬规则必须确定、版本化、可解释，并覆盖边界测试。

## 行为变更和测试

- 行为保持型清理必须先写清理计划；已有行为缺少保护时，先补回归测试；
- 功能和缺陷修复在可行时先写失败测试；
- 每个阈值必须覆盖低于、等于和高于三个边界；
- 历史特征和 ML 评估必须排除未来数据；
- 金样本必须本地、确定，不得依赖实时行情接口；
- 禁止为了让测试变绿而直接改金样本；任何语义变化都必须先解释并确认。

相关代码变更后至少执行：

```bash
python3 -m pytest -q
python3 -m ruff check src tests
```

按改动范围追加执行：

- 在现有数据库副本上演练 migration；
- migration 后执行 `PRAGMA integrity_check`；
- 修改共享 Schema 后运行 vendor API 契约测试；
- 修改依赖或部署后运行 Docker 构建和启动检查；
- 修改规则后运行 2026-06-19、2026-06-24、2026-06-25、2026-06-26
  金样本回归。

未读取并报告验证输出前，不得宣称完成。

## 数据和 SQLite 安全

- 把 `docs/adr/0002-recap-db-schema-contract.md` 视为兼容性契约；
- 首轮改造使用增量 migration，不删除旧表和旧列；
- migration 必须版本化，并在数据库副本上演练；
- 外部网络或 AI 调用必须位于 SQLite 写事务之外；
- 所有服务必须使用统一的 WAL、busy timeout、foreign keys 和事务时长策略；
- 禁止只复制正在使用的 WAL 数据库主文件；必须使用 SQLite backup API 或
  在确认服务停止后备份。

## 自动生成和本地文件

- 仅包含 `<claude-mem-context>` 的嵌套 `CLAUDE.md` 是自动活动记录，不是
  工程规范；不得编辑、依赖或提交；
- `.env`、数据库、缓存、生成报告和 vendor 本地修改可能包含机器或用户状态，
  不得意外覆盖或提交。

## 提交规范

除非用户明确要求，否则不要创建提交。需要提交时使用 Lore 格式：

```text
<意图：为什么要做，而不是机械描述改了什么>

<背景与方案理由>

Constraint: <外部约束，可选>
Rejected: <备选方案> | <拒绝理由，可选>
Confidence: <low|medium|high>
Scope-risk: <narrow|moderate|broad>
Directive: <给未来修改者的提醒，可选>
Tested: <已完成验证>
Not-tested: <已知未验证项>
```

首行必须说明意图，而不是复述 diff。

## 完成报告

最终实施报告必须包含：

- 修改文件和行为影响；
- 简化内容及复用的成熟组件；
- migration 和兼容性影响；
- 完整验证命令与结果；
- 已知风险、未验证路径、灰度开关和回滚方案。

