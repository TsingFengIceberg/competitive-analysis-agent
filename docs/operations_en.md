# Operations and Troubleshooting

## Local startup

Requirements: Python 3.12+, uv, Node.js 22+, and pnpm 10+.

```bash
make install
make dev
```

Open `http://localhost:2026/competition`. Common commands:

```bash
make stop
make restart
make watch
make start
make test
make lint
make build
```

When pnpm is unavailable, use the installed binaries under `frontend/node_modules/.bin` for Next, TypeScript, ESLint, and Prettier. Override ports with `BACKEND_PORT=8002 FRONTEND_PORT=2027 make dev`.

## Separate processes

```bash
cd backend
uv run --locked --no-dev --no-sync uvicorn app.main:app --host 0.0.0.0 --port 8001
cd frontend
pnpm start --hostname 0.0.0.0 --port 2026
```

Use `make dev` or `make start` on shared servers to avoid unnecessary file watching. Use `make watch` only when hot reload is needed.

## Tests and builds

```bash
make test
make lint
make rag-eval
cd backend
uv run --locked pytest tests/test_a2a_provider.py
```

Frontend checks can use `frontend/node_modules/.bin/tsc --noEmit`, `frontend/node_modules/.bin/eslint .`, and `frontend/node_modules/.bin/prettier --check .`. RAG evaluation reports are written under ignored `.ci-agent/evaluations/` and do not enter the business knowledge base.

## Background tasks and recovery

Knowledge ingestion, source sync, and observation runs use the durable task queue. Run one observation scheduler in a multi-process deployment, or start the standalone Worker:

```bash
cd backend
python -m app.task_worker
```

SQLite leases, task states, and A2A events are persisted. After a restart, `submitted`/`working` tasks can resume; completed, failed, canceled, and input-required tasks are not duplicated. Late background results cannot overwrite a canceled task.

## Log triage

1. Check FastAPI startup logs and `/api/competition/knowledge/status`.
2. Confirm configuration mode, model Provider, Base URL, and search switches.
3. Inspect `/api/competition/report/{thread_id}/trace` for analysis failures.
4. Inspect `/api/competition/knowledge/jobs/{job_id}` and source health for ingestion failures.
5. Inspect `/api/competition/observation/runtime`, run history, and change details for monitoring failures.
6. A `degraded` retrieval marker means fallback mode; do not treat it as a semantic-model result.

## SSH tunneling

When the remote server exposes only SSH, run locally:

```bash
ssh -p 2002 -N -L 2026:127.0.0.1:2026 -L 8001:127.0.0.1:8001 wugang@47.99.117.47
```

If a local port is occupied, use another pair:

```bash
ssh -p 2002 -N -L 3026:127.0.0.1:2026 -L 18001:127.0.0.1:8001 wugang@47.99.117.47
```

Open `http://127.0.0.1:3026/competition`.

## Common issues

- First RAG retrieval is slow: wait for background model warm-up or verify local model assets.
- No search results: check provider-native search, Tavily/Jina keys, and group switches.
- “another observation is already running”: a lease is still active; inspect history before clicking Run now again.
- A report link does not load: ensure both frontend and backend ports are tunneled and use the same local frontend port.
- A2A returns unauthenticated: production requires a Bearer token; only explicit local debugging may set `CI_AGENT_A2A_AUTH_REQUIRED=false`.
