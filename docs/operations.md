# 运行与排障

## 本地启动

环境要求：Python 3.12+、uv、Node.js 22+、pnpm 10+。

```bash
make install
make dev
```

访问 `http://localhost:2026/competition`。常用命令：

```bash
make stop
make restart
make watch
make start
make test
make lint
make build
```

没有 pnpm 时可使用 `frontend/node_modules/.bin/next`、`tsc`、`eslint` 和 `prettier` 的已安装二进制完成检查。修改端口：`BACKEND_PORT=8002 FRONTEND_PORT=2027 make dev`。

## 分别启动

```bash
cd backend
uv run --locked --no-dev --no-sync uvicorn app.main:app --host 0.0.0.0 --port 8001
cd frontend
pnpm start --hostname 0.0.0.0 --port 2026
```

生产或共享服务器建议使用 `make dev`/`make start`，避免不必要的文件监听；`make watch` 仅用于需要热更新时。

## 测试与构建

```bash
make test
make lint
make rag-eval
cd backend
uv run --locked pytest tests/test_a2a_provider.py
```

前端检查可运行 `frontend/node_modules/.bin/tsc --noEmit`、`frontend/node_modules/.bin/eslint .` 和 `frontend/node_modules/.bin/prettier --check .`。`make rag-eval` 的结果写入 `.ci-agent/evaluations/`，不会污染业务知识库。

## 后台任务与恢复

知识导入、来源同步和观察执行都进入持久化任务队列。多进程环境中只运行一个观察调度器，或者单独启动：

```bash
cd backend
python -m app.task_worker
```

SQLite 租约、任务状态和 A2A Task 事件会持久化。进程重启后，仍处于 `submitted`/`working` 的任务可恢复；已完成、失败、取消或等待输入的任务不会重复执行。后台任务迟到结果不能覆盖取消状态。

## 日志排查顺序

1. 查看 FastAPI 启动日志和 `/api/competition/knowledge/status`。
2. 确认当前配置模式、模型 Provider、Base URL 和搜索开关。
3. 对失败的分析查看 `/api/competition/report/{thread_id}/trace`。
4. 对知识任务查看 `/api/competition/knowledge/jobs/{job_id}` 和来源健康接口。
5. 对观察任务查看 `/api/competition/observation/runtime`、运行历史和变化详情。
6. 若发生降级，检查检索日志中的 `degraded` 标记，不要把降级结果误判为语义模型结果。

## SSH 隧道

远程服务器只开放 SSH 时，在本机执行：

```bash
ssh -p 2002 -N -L 2026:127.0.0.1:2026 -L 8001:127.0.0.1:8001 wugang@47.99.117.47
```

若本机端口被占用，换成本地端口，例如：

```bash
ssh -p 2002 -N -L 3026:127.0.0.1:2026 -L 18001:127.0.0.1:8001 wugang@47.99.117.47
```

浏览器访问 `http://127.0.0.1:3026/competition`。

## 常见问题

- 首次 RAG 检索很慢：等待后台模型预热，或确认本地模型目录已经准备。
- 没有搜索结果：检查 provider-native search、Tavily/Jina 密钥和配置组开关。
- 观察提示“another observation is already running”：任务租约仍有效，先查看运行历史，避免重复点击立即执行。
- 报告链接打不开：确认前端端口和后端端口都建立了隧道，且浏览器使用的是同一个本地端口。
- A2A 返回未认证：生产环境需要 Bearer Token；调试环境才使用 `CI_AGENT_A2A_AUTH_REQUIRED=false`。
