# Configuration Guide

## Configuration modes

Select the source with `CI_AGENT_CONFIG_MODE`:

| Mode | Source | Use case |
| --- | --- | --- |
| `db` (default) | SQLite `user_settings`, managed in Settings | Production and multi-user isolation |
| `file` | Root `config.yaml` + `.env` | Debugging, demos, and no-account runs |

Debug example:

```bash
cp .env.example .env
cp config.example.yaml config.yaml
CI_AGENT_CONFIG_MODE=file make dev
```

DB mode does not require `.env` or `config.yaml`. In File mode, secrets live in `.env`; model routing, groups, search, and Feishu switches live in `config.yaml`. Both files are ignored by Git.

## Models and search

`config.yaml` has providers and groups. A provider defines an environment variable for its key and an OpenAI-compatible `api_base`; a group defines its default provider/model, search backends, and per-Agent overrides. Agents may override provider, model, temperature, timeout, and max turns.

Provider-native search, Tavily, DuckDuckGo, and Jina can be enabled independently. Missing optional keys skip that backend; with all backends disabled the workflow uses a bounded no-search fallback.

## `.env` secrets

Copy `.env.example` and fill only the services you use:

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

Never commit `.env`, `config.yaml`, databases, models, or source documents.

## Monitoring and task runtime

| Variable | Default | Description |
| --- | --- | --- |
| `CI_AGENT_OBSERVATION_SCHEDULER_ENABLED` | `true` | Start the scheduler with FastAPI |
| `CI_AGENT_OBSERVATION_POLL_SECONDS` | `30` | Due-task scan interval, minimum 5 seconds at runtime |
| `CI_AGENT_NOTIFICATION_WEBHOOK` | empty | Optional alert webhook |

Run only one scheduler in a multi-process deployment, or run the standalone Worker with `python -m app.task_worker`.

## RAG parameters

Common variables include `CI_AGENT_KNOWLEDGE_ROOT`, `CI_AGENT_RAG_EMBEDDING_PATH`, `CI_AGENT_RAG_RERANKER_PATH`, `CI_AGENT_RAG_QDRANT_PATH`, `CI_AGENT_RAG_QDRANT_URL`, `CI_AGENT_RAG_QDRANT_API_KEY`, `CI_AGENT_OBJECT_STORE`, `CI_AGENT_OBJECT_STORE_BUCKET`, `CI_AGENT_RAG_MAX_UPLOAD_BYTES`, `CI_AGENT_RAG_MIN_SCORE`, `CI_AGENT_RAG_QUERY_EXPANSION`, and `CI_AGENT_RAG_LEXICAL_FALLBACK`. See [RAG documentation](rag_en.md) and `.env.example` for defaults.

Prepare local models once:

```bash
uv run --project backend --locked python scripts/setup-rag-models.py
```

Install optional S3/MinIO/R2 support:

```bash
uv sync --extra rag-remote --project backend
```

## Feishu

Create a Feishu enterprise app, enable the bot, and request `im:message:send_as_bot`, `docx:document`, and `drive:drive`. Enable features in Settings for DB mode or in the group's `feishu` section for File mode with `notify_enabled`, `doc_auto_export`, and `doc_manual_export`.

## Configuration sync

```bash
uv run --project backend --locked --no-dev --no-sync python scripts/sync-user-config.py push <user_email>
uv run --project backend --locked --no-dev --no-sync python scripts/sync-user-config.py pull <user_email>
uv run --project backend --locked --no-dev --no-sync python scripts/sync-user-config.py push <user_email> --dry-run
```

Confirm the target user and mode before syncing. The script must not print or copy secrets into logs.
