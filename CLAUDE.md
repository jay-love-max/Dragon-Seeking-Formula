# Claude Code 仓库规范入口

`AGENTS.md` 是本仓库唯一权威工程规范。TickFlow 源码已纳入根仓库统一追踪；在规划、编辑、评审或执行数据库
migration 前，必须完整阅读并遵守它。

实施依据的优先顺序：

1. 用户当前请求；
2. `AGENTS.md`；
3. `docs/adr/` 中已采纳的架构记录；
4. `CONTEXT.md`；
5. 与当前任务对应的 `.omx/plans/` 实施方案。

仅包含 `<claude-mem-context>` 的嵌套 `CLAUDE.md` 是自动生成的活动桩文件，
不是工程规范，不得覆盖 `AGENTS.md`。
