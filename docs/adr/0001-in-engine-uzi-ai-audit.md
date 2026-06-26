# 将 UZI 智能大模型审计逻辑内置于复盘引擎

为了消除由于外部子进程调用和多 Git 仓库克隆造成的臃肿管道与 Docker 容器化构建障碍，我们将 UZI 智能审计逻辑（Prompt 模板、API 结构化数据请求）直接内置在 `src/recap_engine.py` 内部，通过共享的 OpenAI 兼容网关进行调用并持久化至本地 SQLite，实现单容器部署。
