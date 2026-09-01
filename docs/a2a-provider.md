# A2A Provider

项目提供基于 `a2a-sdk==1.1.2`、A2A 协议 `1.0` 的独立 Provider。固定版本是为了让 AgentCard、JSON-RPC、Task、Artifact 和 SSE 序列化可复现。Provider 不依赖任何特定 Hub、数据库、Task ID 或回调实现。

## 端点

| 能力 | 地址 |
| --- | --- |
| AgentCard | `GET /.well-known/agent-card.json` |
| JSON-RPC | `POST /a2a` |
| REST 绑定 | `/a2a/message:send`、`/a2a/message:stream`、`/a2a/tasks/{id}`、`/a2a/tasks/{id}:cancel` |

AgentCard 真实声明能力、协议版本、媒体类型、streaming/push 支持和认证要求。外部 A2A Task ID 与内部 `thread_id` 分离并持久化映射。

## 调用流程

1. 客户端读取 AgentCard。
2. 使用标准 JSON-RPC `SendMessage` 提交文本或 DataPart，服务立即返回 Task。
3. 使用 `GetTask` 查询，或使用 `SendStreamingMessage` 订阅标准 SSE。
4. 如果状态为 `TASK_STATE_INPUT_REQUIRED`，带同一个 `taskId`/`contextId` 发送下一条 Message。
5. 完成后从 `application/json` Artifact 读取报告、矩阵、SWOT、趋势、来源和质量指标。
6. 使用 `CancelTask` 取消仍在运行的任务。

示例：

```bash
curl http://localhost:8001/.well-known/agent-card.json
curl -X POST http://localhost:8001/a2a -H 'Content-Type: application/json' -H 'A2A-Version: 1.0' -H 'Authorization: Bearer <key>' -d '{"jsonrpc":"2.0","id":"1","method":"SendMessage","params":{"message":{"messageId":"m-1","role":"ROLE_USER","parts":[{"text":"比较 Cursor 和 GitHub Copilot，重点关注团队采用成本"}]}}}'
```

任务查询、流式订阅和取消使用同一 JSON-RPC endpoint；方法名和字段以锁定 SDK 版本为准。SSE 事件带稳定 ID，客户端断线后可用 `GetTask` 或重新订阅恢复，支持 `Last-Event-ID` 增量回放。

## 认证与限制

生产环境不要匿名开放。设置 `CI_AGENT_A2A_API_KEY` 后使用 Bearer Token，并可通过 `X-A2A-Client-ID`、`X-A2A-Tenant` 做调用方和租户隔离。仅本地调试时显式设置 `CI_AGENT_A2A_AUTH_REQUIRED=false`。

`CI_AGENT_A2A_ENABLED` 控制开关；`CI_AGENT_A2A_MAX_CONCURRENCY`、`CI_AGENT_A2A_RATE_LIMIT_PER_MINUTE`、`CI_AGENT_A2A_MAX_REQUEST_BYTES`、`CI_AGENT_A2A_TASK_TIMEOUT_SECONDS`、`CI_AGENT_A2A_MAX_ATTEMPTS` 和 `CI_AGENT_A2A_LEASE_SECONDS` 控制资源和生命周期。错误响应不会泄露 Prompt、路径、凭据或内部堆栈。

## 测试

```bash
cd backend
uv run --locked pytest tests/test_a2a_provider.py
```

测试覆盖 AgentCard、JSON-RPC、Task 映射、input-required 续接、Artifact、取消、鉴权和 SSE 恢复。可使用官方 A2A Inspector/TCK 或兼容客户端进行额外互操作测试。
