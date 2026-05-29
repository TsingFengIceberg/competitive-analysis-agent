# 双树架构：Agent 工作流状态分支管理

> CI-Agent 核心设计亮点 | 2026-05-29
> 详见 [COMPETITION_PLAN.md §3.8](../COMPETITION_PLAN.md#38-分支树-branchtree--agent-工作流的-git-核心差异化)

---

## 1. 问题：Agent 工作流为什么需要分支？

当前主流 AI Agent 框架的状态管理都**不支持分支语义**：

| 方案 | 做了什么 | 局限 |
|------|---------|------|
| **线性 checkpoint**（LangGraph） | 沿单条时间轴保存状态快照 | 只能前进或回退，无法分叉 |
| **无内置版本管理**（CrewAI、AutoGen） | 状态是临时的 | 根本回不到过去的决策 |

但人类专家做竞品分析的工作模式是**分支式**的：

```
分析师看 v1 报告 → 从 PM 视角重写 → v2
分析师看 v1 报告 → 换关键词重新搜索 → v3
分析师看 v2 报告 → 在 v2 基础上继续深化 → v4
```

这与 Git 的分支模型完全一致。但 Agent 领域没有等价物。**这就是我们要解决的问题。**

---

## 2. 核心洞察：存在两棵独立的树

Agent 工作流实际涉及**两棵粒度完全不同的树**。

### 树 1：LangGraph Checkpoint Tree（Agent 粒度）

**管理者**：LangGraph 内置（SqliteSaver / PostgresSaver）
**一个节点**：一次 Agent 执行步骤（collector / analyst / reviewer / writer）
**何时分叉**：用非最新 `checkpoint_id` 调用 `update_state()` 或 `stream()` 时，LangGraph 自动创建 `source: "fork"` checkpoint

```
ck001(输入) → ck002(collector) → ck003(analyst) → ck004(reviewer) → ck005(writer) → ck006(HITL中断)
                                                                                         ↘ ck007(fork) → ck008(新collector) → ...
```

每个 checkpoint 存储完整的 `channel_values`（LangGraph State）。`parent_checkpoint_id` 天然构成树结构。LangGraph 的**隐式 fork 机制**：pregel loop 检测到 `is_time_traveling=True`（不是从中断恢复，而是主动回到历史 checkpoint），且 checkpoint source 不是 `"update"` 或 `"fork"` 时，自动创建 `source: "fork"` 的新 checkpoint。旧分支不受影响——fork 是 INSERT 新行，不 UPDATE 旧行。

### 树 2：BranchTree（Data 粒度）

**管理者**：我们自己（`deerflow/branchtree/`）
**一个节点**：一次完整分析的产出快照（report_data + analysis_result + collected_data）
**何时分叉**：用户 HITL 决策（重写 / 重分析 / 重搜索 / 批准）

```
v1 (初始分析)
├── v2 (从PM视角重写)
│   └── v3 (在v2基础上深化)
└── v4 (换关键词重新搜索) ← 从v1分叉，不是v3
```

每个节点存储 `checkpoint_id` 引用（指向 LangGraph checkpoint）和业务元数据（版本号 / 操作类型 / 是否批准）。完整 state 由 LangGraph 管理，我们不重复存储。

### 为什么必须分开

| 维度 | LangGraph Checkpoint Tree | BranchTree |
|------|--------------------------|------------|
| 一个节点 = | 一次 Agent 执行步骤 | 一次完整分析的产出 |
| 粒度 | Agent 级 | Run 级 |
| 受众 | 框架/开发者 | 用户（PM/创业者） |
| 分叉触发 | `update_state(非最新checkpoint)` — 自动 | HITL 决策 — 用户主动 |
| 存什么 | 完整 `channel_values` | `checkpoint_id` 引用 + 业务 metadata |

**它们不应该共享基类**——早期设计把 AgentExecutionTree 和 UserInteractionTree 放在同一继承体系下，这是一个架构错误，已修正。

---

## 3. 缺失层：CheckpointOps

### 3.1 为什么需要它

LangGraph 的 checkpoint API 是给**框架内部**（pregel loop）用的，不是给应用层调用的。每个用 LangGraph 的团队都在写同样的样板代码：

```python
# 今天每个 LangGraph 用户都得这么写:
config = {"configurable": {"thread_id": tid, "checkpoint_id": ck_id}}
checkpoint = saver.get(config)
state = checkpoint["channel_values"]  # 从内部 dict 结构手动挖数据
```

我们调研了整个生态：

| 来源 | 结论 |
|------|------|
| **PyPI**（7 个 `langgraph-checkpoint-*` 包） | 全是存储后端（LMDB / Neo4j / CosmosDB / S3 / Typesense），没有操作封装层 |
| **DeerFlow**（`runtime/checkpointer/`） | 只有工厂函数（`get_checkpointer` / `make_checkpointer`），无操作封装 |
| **LangGraph JS SDK** | 有 `getBranchSequence` / `getBranchView` / `getBranchContext` — 但 **Python 端没有等价物** |

**这是真正的生态空白。** CheckpointOps 填补了它。

### 3.2 API 设计与实现

> 所有方法统一接收 `thread_id` 参数——使缓存可以按 thread 分区，避免全局扫描。

```python
class CheckpointOps:
    """LangGraph checkpoint 便捷操作工具。不是一棵树——是一个工具库。"""

    def __init__(self, checkpointer: BaseCheckpointSaver,
                 graph: CompiledStateGraph | None = None):
        # 内存缓存：按 thread 分区，写操作时失效
        self._tree_cache: dict[str, dict[str | None, list[str]]] = {}  # thread_id → {parent_id: [child_ids]}
        self._ck_count: dict[str, int] = {}  # thread_id → checkpoint 数量（版本号，用于增量）

    # ── 读操作 ──

    def get_state(self, thread_id: str,
                  checkpoint_id: str | None = None) -> StateSnapshot:
        ...

    def get_history(self, thread_id: str,
                    limit: int | None = None) -> list[StateSnapshot]:
        ...

    def latest(self, thread_id: str) -> StateSnapshot:
        ...

    def children(self, thread_id: str,
                 checkpoint_id: str) -> list[str]:
        ...

    def is_fork_point(self, thread_id: str,
                      checkpoint_id: str) -> bool:
        ...

    def build_tree(self, thread_id: str
                   ) -> dict[str | None, list[str]]:
        ...

    def lineage(self, thread_id: str,
                checkpoint_id: str) -> list[str]:
        ...

    # ── 写操作（触发缓存失效）──

    def fork(self, thread_id: str, from_checkpoint: str,
             state_update: dict) -> str:
        ...

    def update_state(self, thread_id: str, values: dict,
                     as_node: str | None = None) -> str:
        ...

    # ── 标签管理 ──

    def tag(self, thread_id: str, checkpoint_id: str,
            label: str) -> None:
        ...

    def list_tags(self, thread_id: str) -> dict[str, str]:
        ...

    def restore_to_tag(self, thread_id: str,
                       label: str) -> StateSnapshot:
        ...
```

---

### 3.3 逐 API 设计与性能考量

#### 读操作

**`get_state(thread_id, checkpoint_id=None)`**

```python
def get_state(self, thread_id, checkpoint_id=None):
    config = {"configurable": {"thread_id": thread_id}}
    if checkpoint_id:
        config["configurable"]["checkpoint_id"] = checkpoint_id
    return self._graph.get_state(config) if self._graph \
      else self._checkpointer.get(config)
```

- 底层：SQLite 主键查询 `WHERE thread_id=? AND checkpoint_id=?`
- 复杂度：**O(1)**，有联合索引
- 不传 `checkpoint_id` 返回最新——LangGraph 内部走 `ORDER BY checkpoint_id DESC LIMIT 1`

---

**`get_history(thread_id, limit=None)`**

```python
def get_history(self, thread_id, limit=None):
    return list(self._graph.get_state_history(
        {"configurable": {"thread_id": thread_id}}, limit=limit
    ))
```

- 底层：索引扫描，`limit` 直接下推到 SQL
- 复杂度：**O(k)**，k = limit
- 调用方按需分页，不做全量预加载

---

**`latest(thread_id)`**

```python
def latest(self, thread_id):
    return self.get_state(thread_id)  # 等价，语义更明确
```

---

**`children(thread_id, checkpoint_id)`** — 🔥 核心优化点

```python
def children(self, thread_id, checkpoint_id):
    self._ensure_cache(thread_id)
    return self._tree_cache[thread_id].get(checkpoint_id, [])
```

- 缓存命中：**O(1)** dict 查找
- 无需全表扫描
- 500 条消息的会话、前端每秒轮询渲染树——同样 O(1)

---

**`is_fork_point(thread_id, checkpoint_id)`**

```python
def is_fork_point(self, thread_id, checkpoint_id):
    return len(self.children(thread_id, checkpoint_id)) > 1
```

- 继承 `children()` 的 O(1)
- 渲染树时为每个节点判断是否显示分叉图标——不额外查询

---

**`build_tree(thread_id)`** — 🔥 核心优化点

```python
def build_tree(self, thread_id):
    self._ensure_cache(thread_id)
    return self._tree_cache[thread_id]  # 直接返回缓存，零计算
```

- 缓存命中：**O(1)**
- 裸调 LangGraph 的等价操作需要全量扫描 + 手工建树，这里是最大收益项

---

**`lineage(thread_id, checkpoint_id)`**

```python
def lineage(self, thread_id, checkpoint_id):
    self._ensure_cache(thread_id)
    # 从缓存回溯 parent 链（缓存里已有 parent → children 映射）
    # 构建反向索引 parent_of[child] = parent，一次遍历
    chain = []
    cur = checkpoint_id
    parent_of = self._build_parent_index(thread_id)  # O(节点数)，只算一次
    while cur:
        chain.append(cur)
        cur = parent_of.get(cur)
    return chain
```

- 缓存预热后：**O(深度)**，纯内存遍历，零 DB 查询
- 对比裸调：200 步深度 = 200 次 SQLite 查询 → 1 次内存遍历

---

#### 写操作（均触发缓存失效）

**`fork(thread_id, from_checkpoint, state_update)`**

```python
def fork(self, thread_id, from_checkpoint, state_update):
    config = {"configurable": {
        "thread_id": thread_id, "checkpoint_id": from_checkpoint
    }}
    # 非最新 checkpoint_id → LangGraph 内部检测 time-travel
    # → 自动创建 source:"fork" checkpoint
    new_config = self._graph.update_state(config, state_update)
    new_ck_id = new_config["configurable"]["checkpoint_id"]

    # 写操作 → 清除该 thread 的缓存，下次读取时重新加载
    self._tree_cache.pop(thread_id, None)
    self._ck_count.pop(thread_id, None)
    return new_ck_id
```

- 缓存失效策略：**按 thread 粒度**，不影响其他 thread
- 不立即重建——下次 `_ensure_cache` 时惰性加载

---

**`update_state(thread_id, values, as_node=None)`**

```python
def update_state(self, thread_id, values, as_node=None):
    config = {"configurable": {"thread_id": thread_id}}
    new_config = self._graph.update_state(config, values, as_node=as_node)
    self._tree_cache.pop(thread_id, None)
    self._ck_count.pop(thread_id, None)
    return new_config["configurable"]["checkpoint_id"]
```

---

#### 标签管理

**`tag(thread_id, checkpoint_id, label)` / `list_tags(thread_id)` / `restore_to_tag(thread_id, label)`**

```python
# 标签存储在 LangGraph checkpoint metadata.extra 中，不引入新表
def tag(self, thread_id, checkpoint_id, label):
    cp = self._checkpointer.get(
        {"configurable": {"thread_id": thread_id, "checkpoint_id": checkpoint_id}}
    )
    tags = cp.get("metadata", {}).get("extra", {}).get("tags", [])
    tags.append(label)
    # 通过 put 写回更新的 metadata
    self._checkpointer.put(
        {"configurable": {"thread_id": thread_id, "checkpoint_id": checkpoint_id}},
        cp, {"extra": {"tags": tags}}, ...
    )
```

---

### 3.4 缓存策略

```
┌──────────────────────────────────────────────────┐
│               _ensure_cache(thread_id)             │
│                                                    │
│  1. 查 _ck_count[thread_id]                        │
│     │ 缓存中存的数量 vs 数据库实际数量              │
│     │                                              │
│     ├─ 相等 → 直接 return（缓存命中，零DB查询）      │
│     │                                              │
│     └─ 不等 → 增量加载                              │
│         │                                          │
│         ├─ 首次加载: checkpointer.list(thread)      │
│         │   全量扫描建树                             │
│         │                                          │
│         └─ 增量更新: checkpointer.list(             │
│               thread,                               │
│               limit=DB_count - cache_count           │
│             )                                      │
│             只加载新增的 checkpoint                  │
│             插入已有树结构                           │
│                                                    │
│  2. 更新 _ck_count[thread_id] = DB_count            │
└──────────────────────────────────────────────────┘

缓存失效时机:
  fork() → pop(thread_id)
  update_state() → pop(thread_id)
  （LangGraph 自己的 stream/invoke 也写 checkpoint，
    但那是内部行为 —— 外部调用方完成一次 run 后
    手动调 invalidate_cache(thread_id)）
```

**为什么不用物化表**：LangGraph 的 SqliteSaver 已管理 checkpoint 持久化。再加一张 children 索引表意味着跨表事务和一致性问题。内存缓存在单进程场景下（当前部署架构）零额外复杂度。

### 3.5 便捷度证明

| 操作 | 裸调 LangGraph API | 用 CheckpointOps |
|------|-------------------|-----------------|
| 获取某版本状态 | 手动拼 `RunnableConfig` → `saver.get(config)` → 从 `channel_values` 挖数据 | `ck.get_state(thread_id, checkpoint_id)` → 返回结构体 |
| 从历史版本 fork | 拼 config + `graph.update_state()` + 理解隐式 fork 机制 | `ck.fork(thread_id, from_checkpoint, state_update)` |
| 构建 checkpoint 树 | 遍历 `list()` 结果 → 手动按 `parent_checkpoint_id` 建树 | `ck.build_tree(thread_id)` → O(1) 返回缓存 dict |
| 查子节点 | 在完整 list 中按 `parent_config.checkpoint_id` 过滤 | `ck.children(thread_id, checkpoint_id)` → O(1) |
| 追溯祖先链 | 手动 parent 循环 N 次 DB 查询 | `ck.lineage(thread_id, checkpoint_id)` → O(深度) 纯内存 |

### 3.6 性能对比

| 场景 | 裸调 LangGraph | CheckpointOps（缓存命中） |
|------|---------------|-------------------------|
| 渲染 500 条消息的树 | 500 行扫描 + 手工建树，每次渲染都跑 | **O(1)** 返回缓存 dict |
| 判断节点是否分叉点 | 全量扫描 | **O(1)** dict 查 children 数量 |
| 追溯 200 步祖先链 | 200 次 SQLite 查询 | 1 次内存遍历 |
| 新增 1 条消息后刷新 | 全量 501 行重建 | 增量加载 1 行 + 插入缓存 |

每个操作从 3-5 行样板代码 + 隐式机制理解 → **一行函数调用**。

### 3.7 测试策略

> 测试文件：`backend/tests/test_checkpoint_ops.py`
> 全部使用 mock `BaseCheckpointSaver`，不依赖真实 LLM 或 LangGraph graph。纯单元测试。

**Mock 策略**：构造一个内存 `InMemorySaver`，预填充若干 checkpoint（含父子关系），模拟多分支场景：

```python
# 预置测试数据：一棵有分叉的 checkpoint 树
# ck001 → ck002 → ck003 → ck004 (主线)
#               ↘ ck005 → ck006 (分叉)
@pytest.fixture
def ops():
    saver = InMemorySaver()
    # 按序 put 6 个 checkpoint...
    return CheckpointOps(saver)
```

**每个 API 的测试清单**：

| API | 测试点 | 关键断言 |
|-----|--------|---------|
| `get_state` | 不传 checkpoint_id → 返回最新 | `snapshot.values["messages"]` 等于最后写入的值 |
| | 传历史 checkpoint_id → 返回当时状态 | 值等于历史时刻的值，不是最新的 |
| | 不存在的 thread_id → 明确抛错 | `ValueError` 或返回 None，不静默 |
| `get_history` | 不传 limit → 返回全部 | `len(result)` 等于预填充总数 |
| | limit=3 → 只返回 3 条 | 且是最新的 3 条（倒序） |
| `latest` | 返回最新 snapshot | `latest.values == get_state()` |
| `children` | 分叉点 → 返回 2 个子节点 | `ck003` 的 children = `[ck004, ck005]` |
| | 叶子节点 → 返回空列表 | `len(children(ck006)) == 0` |
| | **缓存命中**：调两次不触发两次 DB 扫描 | mock 计数验证 `list()` 只被调用一次 |
| `is_fork_point` | children > 1 → True | `ck003` → True |
| | children ≤ 1 → False | `ck006` → False |
| `build_tree` | 返回完整树结构 | `tree[None]` = 根节点 `[ck001]`，`tree[ck003]` = `[ck004, ck005]` |
| | **缓存命中** | 调两次只扫描一次 DB |
| `lineage` | 从叶子回溯到根 | `lineage(ck006)` = `[ck001, ck003, ck005, ck006]` |
| | 根节点 → 只有自己 | `lineage(ck001)` = `[ck001]` |
| | **纯内存**：不触发任何 `saver.get()` / `saver.list()` | mock 验证 |
| `fork` | 返回新 checkpoint_id | 不等于 from_checkpoint |
| | **缓存失效**：fork 后 children 应包含新 fork 节点 | 调 `fork()` 后再 `children()` 触发重新扫描 |
| | LangGraph 自动创建 source:"fork" | 新 checkpoint 的 metadata.source == "fork" |
| `update_state` | 返回新 checkpoint_id | | 
| | **缓存失效** | 同 fork |
| `tag` / `list_tags` / `restore_to_tag` | tag → list_tags 能查到 | `list_tags()[checkpoint_id]` 包含打的标签 |
| | restore_to_tag → 返回对应的 StateSnapshot | 值与 `get_state(checkpoint_id)` 一致 |
| | 同名标签覆盖 → 取最新 | 或者抛错——取决于设计决策 |

**重点测试项**（对应缓存逻辑）：

```
□ 缓存命中：children/build_tree/is_fork_point 首次调触发全量扫描，二次调不触发
□ 缓存失效：fork/update_state 后自动清除缓存，下次读触发重新扫描
□ 增量加载：已有缓存 + DB 新增 1 checkpoint → 只加载新增那 1 条
□ 跨 thread 隔离：thread_A 的缓存操作不影响 thread_B 的数据
□ 并发安全：多线程同时 fork + 同时读（如果用了 threading.Lock）
□ 空 thread：0 个 checkpoint 时不崩，返回空树/空列表
```

**运行方式**：
```bash
cd backend && PYTHONPATH=packages/harness uv run pytest tests/test_checkpoint_ops.py -v
```

---

## 4. 三者的协作关系

```
                        ┌──────────────────────────┐
                        │     BranchTree（我们）      │
                        │  Data 粒度 · 用户可见       │
                        │  ───────────────────────  │
                        │  节点 = 完整分析快照        │
                        │  分叉 = HITL 决策          │
                        │  存: checkpoint_id 引用    │
                        │      + 版本号              │
                        │      + 操作类型             │
                        │      + 批准状态             │
                        └───────────┬──────────────┘
                                    │ 调用（依赖倒置）
                        ┌───────────▼──────────────┐
                        │   CheckpointOps（我们）    │
                        │   工具层 · 无业务语义       │
                        │  ───────────────────────  │
                        │  get_state / fork         │
                        │  build_tree / lineage     │
                        │  封装 LangGraph 裸 API     │
                        └───────────┬──────────────┘
                                    │ 封装
                        ┌───────────▼──────────────┐
                        │ LangGraph Checkpoint Tree │
                        │ Agent 粒度 · 框架管理       │
                        │ ────────────────────────  │
                        │ 节点 = Agent 执行步骤       │
                        │ 分叉 = 隐式（source:       │
                        │        "fork" checkpoint） │
                        │ 存: 完整 channel_values    │
                        └───────────────────────────┘
```

**关键设计决策**：BranchTree 不直接调用 LangGraph checkpoint API。它调用 CheckpointOps。如果未来换编排框架，只需换 CheckpointOps 的实现，BranchTree 不受影响。这是经典的依赖倒置。

---

## 5. 继承模型

```
BranchTree（抽象基类）
├── snapshot / fork / restore / lineage / to_dict
├── 依赖注入: CheckpointOps + MetadataStore
└── 不关心节点存什么，只定义树操作
        │
    ┌───┴───┐
    │       │
DeliverableTree   ConversationTree
（报告版本分支）     （对话消息分支）
P0 — 已实现         P1 — 计划中
```

**勘误说明**：早期设计将 AgentExecutionTree 作为 UserInteractionTree 的兄弟放在同一 BaseVersionTree 下。我们认识到 Agent 执行分支操作的是 **LangGraph 自己的 checkpoint tree**——由不同系统管理的不同树，不应继承 BranchTree。如果未来需要 Agent 执行层的分支探索，在 CheckpointOps（工具层）上扩展即可，不需要往 BranchTree 继承体系里加新子类。

---

## 6. 存储策略

| 存什么 | 存在哪 | 由谁管理 |
|--------|--------|---------|
| 完整 state（channel_values） | LangGraph `checkpoints` 表 | SqliteSaver |
| 版本号 / 父版本 / 操作类型 / 批准状态 | `branch_snapshots` 表 | BranchTree MetadataStore |
| checkpoint_id 引用 | `branch_snapshots.checkpoint_id` | 关联两张表 |

查看历史版本的 state 流程：
1. 查 `branch_snapshots` → 拿到 `checkpoint_id`
2. `CheckpointOps.get_state(checkpoint_id)` → LangGraph 返回完整 state
3. state 数据零重复存储

---

## 7. 架构决策日志

| 日期 | 决策 | 理由 |
|------|------|------|
| 2026-05-28 | 初始设计：两层三级继承（BaseVersionTree → AgentExecutionTree / UserInteractionTree → ConversationTree / DeliverableTree） | 假设 Agent 执行分支和用户交互分支共享足够的树语义，值得统一基类 |
| 2026-05-29 | **修正**：将 AgentExecutionTree 从继承体系中移除；简化为单层两级（BranchTree → DeliverableTree / ConversationTree） | Agent 执行分支操作的是 LangGraph 自己的 checkpoint tree——不同粒度、不同系统管理的不同树，不应与用户级 BranchTree 共享基类 |
| 2026-05-29 | 新增 CheckpointOps 作为独立工具层 | 生态调研确认 Python 端没有 LangGraph checkpoint 操作封装库。BranchTree 需要一个干净的接口来与 LangGraph 交互——CheckpointOps 以依赖倒置方式提供 |
| 2026-05-29 | 存储策略从"完整 state JSON"改为"checkpoint_id 引用 + 业务 metadata" | 避免与 LangGraph 已有持久化重复。state 数据单一来源 |
