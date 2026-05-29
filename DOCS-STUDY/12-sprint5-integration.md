# 12 — Sprint 5 集成层：中间件注册 + 配置热加载 + HITL API

> **日期**: 2026-05-15 | **Sprint**: 5 | **作者**: Wu Gang + Claude

---

## 涉及源文件

| 文件 | 角色 |
|------|------|
| [`backend/packages/harness/deerflow/collaboration/context.py`](../backend/packages/harness/deerflow/collaboration/context.py) | agent_role ContextVar + current_role() 上下文管理器 |
| [`backend/packages/harness/deerflow/agents/middlewares/collaboration_middleware.py`](../backend/packages/harness/deerflow/agents/middlewares/collaboration_middleware.py) | 包装 PermissionGuard 的框架层中间件 |
| [`backend/packages/harness/deerflow/config/collaboration_config.py`](../backend/packages/harness/deerflow/config/collaboration_config.py) | Pydantic 配置模型 + 热加载 |
| [`backend/app/gateway/routers/collaboration.py`](../backend/app/gateway/routers/collaboration.py) | HITL resume API（App 层唯一新增） |
| [`backend/packages/harness/deerflow/agents/lead_agent/agent.py`](../backend/packages/harness/deerflow/agents/lead_agent/agent.py) | 注册 CollaborationMiddleware |
| [`backend/packages/harness/deerflow/config/app_config.py`](../backend/packages/harness/deerflow/config/app_config.py) | 新增 collaboration 字段 + 热加载钩子 |

---

## Q1: collaboration_middleware.py 和 permission_guard.py 都是中间件，关系是什么？为什么多一层？ `📄 collaboration_middleware.py`

**A:** 职责分层——一个干活，一个做适配。

```
agent.py (_build_middlewares)
    │
    └── CollaborationMiddleware    ← agents/middlewares/  （框架适配层）
              │
              └── PermissionGuardMiddleware  ← collaboration/permissions/  （业务逻辑层）
                        │
                        ├── role.can(action)
                        ├── role.requires_evidence(action)
                        └── role.requires_audit(action)
```

| | CollaborationMiddleware | PermissionGuardMiddleware |
|---|---|---|
| **位置** | `agents/middlewares/` | `collaboration/permissions/` |
| **职责** | 适配 DF 的 import 约定 | 所有权权限检查逻辑 |
| **代码量** | ~20 行（纯转发） | ~170 行 |
| **before_tool_call** | 调 `self._guard.before_tool_call(...)` | 真正做权限/证据/审计检查 |

**为什么要多这一层？** 因为导入路径。

DF 的 `agent.py` 按约定从 `agents/middlewares/` 注册中间件：

```python
# agent.py — 框架层
from deerflow.agents.middlewares.collaboration_middleware import CollaborationMiddleware
middlewares.append(CollaborationMiddleware())
```

但权限逻辑属于协作业务，应放在 `collaboration/permissions/`。如果 agent.py 直接 import `collaboration.permissions.permission_guard`，就是把业务路径泄漏到框架层。

`CollaborationMiddleware` 就是一个 thin wrapper——让框架层只看到框架路径，不知道里面是个 `PermissionGuardMiddleware`。

**如果 DF 没有"中间件放 agents/middlewares/"这个约定，完全可以删掉它，直接注册 PermissionGuardMiddleware。**

---

## Q2: collaboration_config.py 在整个系统中扮演什么角色？ `📄 collaboration_config.py`

**A:** 把 CLAUDE.md 中的协作配置表编码为可热加载的 Pydantic 模型。

包含 5 个子配置：

| 配置 | 类 | 关键字段 |
|------|-----|---------|
| 角色 | `RolesConfig` / `RoleConfig` | model, thinking_enabled, max_turns, tools, skills, max_instances |
| Skills | `CollabSkillsConfig` | enabled, load_path |
| Memory | `CollabMemoryConfig` | source_credibility, product_knowledge |
| HITL | `HITLConfig` | enabled, gates, stale_timeout_minutes, require_audit_log |
| Workflows | `WorkflowsConfig` / `WorkflowPreset` | scouts, phases, skip_validation |

**热加载机制**：遵循 DF 的 pattern——

```python
# app_config.py — from_file() 中：
load_collaboration_config_from_dict(config.collaboration.model_dump())

# collaboration_config.py：
def load_collaboration_config_from_dict(config_dict):
    global _collaboration_config
    _collaboration_config = CollaborationAppConfig(**config_dict)
```

当 `config.yaml` mtime 变化时，`get_app_config()` 自动重载，然后调用 `load_collaboration_config_from_dict` 更新单例。无需重启进程。

**agent.py 中的使用**：
```python
if resolved_app_config.collaboration and resolved_app_config.collaboration.enabled:
    middlewares.append(CollaborationMiddleware())
```

---

## Q3: HITL resume API 的 stale 检查是怎么实现的？ `📄 collaboration.py`

**A:** "冷检查"模式——不是在后台跑定时器，而是在恢复时做时间减法。

```python
# collaboration.py
STALE_TIMEOUT_SECONDS = 30 * 60  # 必须和 hitl_gate.py 一致

def _check_stale(interrupt_payload: dict) -> tuple[bool, int]:
    stale_check = interrupt_payload.get("_stale_check", {})
    generated_at = stale_check.get("generated_at", 0)
    stale_after = stale_check.get("stale_after", STALE_TIMEOUT_SECONDS)

    elapsed = int(time.time() - generated_at)
    return elapsed > stale_after, elapsed
```

**完整流程**：

```
① hitl_gate_node: interrupt(payload) 时在 payload 里夹带 _stale_check
   {"generated_at": 1715800000.0, "stale_after": 1800}

② 图暂停，checkpoint 持久化到 Postgres

③ 人类点击按钮 → POST /api/threads/{id}/runs/{rid}/resume
   body: {"resume": "approve"}

④ resume_hitl() 端点：
   ├─ 从 checkpointer 读取 checkpoint → 提取 interrupt payload
   ├─ _check_stale(payload) → (is_stale, elapsed)
   ├─ is_stale=True → 返回 {"status": "stale", "message": "审批已过期..."}
   └─ is_stale=False → Command(resume=decision) → graph.ainvoke(Command, config)
```

**关键**：`_stale_check` 是在暂停时贴的"保质期标签"，在恢复时检查。没有后台线程，没有定时器——只是两个时间戳相减。这就是 [09-hitl-gate.md](09-hitl-gate.md) 中提到的"冷检查"机制在 App 层的具体实现位置。
