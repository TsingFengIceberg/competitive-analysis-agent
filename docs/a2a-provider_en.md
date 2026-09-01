# A2A Provider

The project ships an independent Provider based on `a2a-sdk==1.1.2` and A2A protocol `1.0`. The pinned version keeps AgentCard, JSON-RPC, Task, Artifact, and SSE serialization reproducible. The Provider does not depend on a particular Hub, database, Task ID, callback, or authentication implementation.

## Endpoints

| Capability | Address |
| --- | --- |
| AgentCard | `GET /.well-known/agent-card.json` |
| JSON-RPC | `POST /a2a` |
| REST bindings | `/a2a/message:send`, `/a2a/message:stream`, `/a2a/tasks/{id}`, `/a2a/tasks/{id}:cancel` |

The AgentCard declares capabilities, protocol version, media types, streaming/push support, and authentication. External A2A Task IDs are persisted separately from internal `thread_id` values.

## Call flow

1. Discover the AgentCard.
2. Submit text or a DataPart with standard JSON-RPC `SendMessage`; the service returns a Task promptly.
3. Poll with `GetTask` or subscribe using `SendStreamingMessage` and standard SSE.
4. When the task is `TASK_STATE_INPUT_REQUIRED`, send the next Message with the same `taskId` and `contextId`.
5. Read the completed `application/json` Artifact containing the report, matrix, SWOT, trends, sources, and quality metrics.
6. Cancel a running task with `CancelTask`.

Example:

```bash
curl http://localhost:8001/.well-known/agent-card.json
curl -X POST http://localhost:8001/a2a -H 'Content-Type: application/json' -H 'A2A-Version: 1.0' -H 'Authorization: Bearer <key>' -d '{"jsonrpc":"2.0","id":"1","method":"SendMessage","params":{"message":{"messageId":"m-1","role":"ROLE_USER","parts":[{"text":"Compare Cursor and GitHub Copilot, focusing on team adoption cost"}]}}}'
```

Task lookup, streaming, and cancellation use the same JSON-RPC endpoint. Method names and fields follow the pinned SDK. SSE events have stable IDs; clients can recover after disconnect with `GetTask` or a new subscription using `Last-Event-ID`.

## Authentication and limits

Do not expose anonymous access in production. Set `CI_AGENT_A2A_API_KEY` and send a Bearer token. `X-A2A-Client-ID` and `X-A2A-Tenant` can identify callers and tenants. Set `CI_AGENT_A2A_AUTH_REQUIRED=false` only for explicit local debugging.

`CI_AGENT_A2A_ENABLED` controls the Provider. `CI_AGENT_A2A_MAX_CONCURRENCY`, `CI_AGENT_A2A_RATE_LIMIT_PER_MINUTE`, `CI_AGENT_A2A_MAX_REQUEST_BYTES`, `CI_AGENT_A2A_TASK_TIMEOUT_SECONDS`, `CI_AGENT_A2A_MAX_ATTEMPTS`, and `CI_AGENT_A2A_LEASE_SECONDS` constrain resources and lifecycle. Errors do not expose prompts, paths, credentials, or internal stacks.

## Tests

```bash
cd backend
uv run --locked pytest tests/test_a2a_provider.py
```

Coverage includes AgentCard, JSON-RPC, Task mapping, input-required continuation, Artifacts, cancellation, auth, and SSE recovery. The official A2A Inspector/TCK or another compatible client can provide additional interoperability checks.
