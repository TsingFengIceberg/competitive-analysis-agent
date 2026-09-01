# 配置指南

## 配置模式

通过 `CI_AGENT_CONFIG_MODE` 选择配置来源：

| 模式 | 配置来源 | 适用场景 |
| --- | --- | --- |
| `db`（默认） | SQLite `user_settings`，通过设置页管理 | 正式用户和多用户隔离 |
| `file` | 根目录 `config.yaml` + `.env` | 调试、演示和无账号运行 |

调试运行示例：

```bash
cp .env.example .env
cp config.example.yaml config.yaml
CI_AGENT_CONFIG_MODE=file make dev
```

DB 模式不需要维护 `.env` 或 `config.yaml`；File 模式下密钥放 `.env`，模型路由、配置组、搜索和飞书开关放 `config.yaml`。两个文件都被 Git 忽略。

## 模型与搜索

`config.yaml` 使用 providers + groups 两层结构。provider 定义 `api_key_env` 和兼容 OpenAI 的 `api_base`；group 定义默认 provider/model、搜索后端和各 Agent 覆盖。Agent 可单独指定 provider、model、temperature、timeout 和 max turns，否则继承 group 默认值。

搜索后端可以分别启用 provider-native search、Tavily、DuckDuckGo 和 Jina。没有可选搜索密钥时会自动跳过对应后端；所有后端关闭时流程使用受限的无搜索降级。

## `.env` 密钥

从 `.env.example` 复制后按需填写：

```bash
DOUBAO_API_KEY=...
DEEPSEEK_API_KEY=...
QWEN_API_KEY=...
TAVILY_API_KEY=...
JINA_API_KEY=...
FEISHU_APP_ID=...
FEISHU_APP_SECRET=...
FEISHU_NOTIFY_OPEN_ID=...
FEISHU_TENANT=...
```

不要提交 `.env`、`config.yaml`、数据库、模型或知识原文。

## 观察与任务运行参数

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `CI_AGENT_OBSERVATION_SCHEDULER_ENABLED` | `true` | 是否随 FastAPI 启停观察调度器 |
| `CI_AGENT_OBSERVATION_POLL_SECONDS` | `30` | 到期任务扫描间隔，运行时不低于 5 秒 |
| `CI_AGENT_NOTIFICATION_WEBHOOK` | 空 | 可选告警 Webhook |

多进程部署只启用一个调度实例，或运行独立 Worker：`python -m app.task_worker`。

## RAG 参数

常用 RAG 变量如下，完整说明和默认值见 `.env.example` 与 [RAG 文档](rag.md)：

`CI_AGENT_KNOWLEDGE_ROOT`、`CI_AGENT_RAG_EMBEDDING_PATH`、`CI_AGENT_RAG_RERANKER_PATH`、`CI_AGENT_RAG_QDRANT_PATH`、`CI_AGENT_RAG_QDRANT_URL`、`CI_AGENT_RAG_QDRANT_API_KEY`、`CI_AGENT_OBJECT_STORE`、`CI_AGENT_OBJECT_STORE_BUCKET`、`CI_AGENT_RAG_MAX_UPLOAD_BYTES`、`CI_AGENT_RAG_MIN_SCORE`、`CI_AGENT_RAG_QUERY_EXPANSION`、`CI_AGENT_RAG_LEXICAL_FALLBACK`。

首次准备本地模型：

```bash
uv run --project backend --locked python scripts/setup-rag-models.py
```

使用 S3/MinIO/R2 安装可选依赖：

```bash
uv sync --extra rag-remote --project backend
```

## 飞书

在飞书开放平台创建企业自建应用，开启机器人并申请 `im:message:send_as_bot`、`docx:document` 和 `drive:drive` 权限。DB 模式在设置页开启，File 模式在 group 的 `feishu` 段设置 `notify_enabled`、`doc_auto_export` 和 `doc_manual_export`。

## 配置同步

```bash
uv run --project backend --locked --no-dev --no-sync python scripts/sync-user-config.py push <user_email>
uv run --project backend --locked --no-dev --no-sync python scripts/sync-user-config.py pull <user_email>
uv run --project backend --locked --no-dev --no-sync python scripts/sync-user-config.py push <user_email> --dry-run
```

同步脚本不会输出或复制密钥到日志；执行前确认目标用户和当前模式。
