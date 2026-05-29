# 04 — 测试模式与断言

> **日期**: 2026-05-14 | **Sprint**: 1 | **作者**: Wu Gang + Claude

---

## 涉及源文件

| 文件 | 角色 |
|------|------|
| [`backend/tests/test_collaboration_subgraphs.py`](../backend/tests/test_collaboration_subgraphs.py) | State Schema + SubGraph 编译 + State Mapping 单元测试 |
| [`backend/tests/test_collaboration_graph.py`](../backend/tests/test_collaboration_graph.py) | Parent Graph 编译 + 条件路由单元测试 |

---

## Q1: `assert` 语句是干嘛的？ `📄 test_collaboration_subgraphs.py` `📄 test_collaboration_graph.py`

**A:** `assert` 是 Python 内置的断言语句，语法只有一种：

```python
assert 条件, "失败时显示的消息（可选）"
```

- 条件为 `True` → 无事发生，继续执行
- 条件为 `False` → 抛出 `AssertionError`，pytest 捕获它，标记该测试为 **FAILED**

**我们测试文件中出现的 5 种 assert 模式**：

**① 验证成员存在** — "这个字段必须在 State 里"

```python
assert "validated_brief" in CollaborationState.__annotations__
assert "messages" in annotations  # 继承自 AgentState 的字段
```

**② 验证值相等** — "State Mapping 产出的数据必须正确"

```python
assert result["validated_brief"]["key_finding"] == "test"
assert result["research_quality_score"] == 0.85
```

**③ 验证成员不存在** — "Research 内部字段绝不能泄露到 Parent"

```python
assert "challenges" not in result       # Research 私有字段
assert "rebuttals" not in result        # Research 私有字段
assert "debate_round" not in result     # Research 私有字段
```

**④ 验证布尔条件** — "SubGraph 编译产物应有特定能力"

```python
assert hasattr(research, "get_graph")   # CompiledStateGraph 的标志方法
assert graph is not None                # 编译不能返回 None
```

**⑤ 验证集合/结构** — "节点集合必须包含所有注册节点"

```python
nodes = graph.get_graph().nodes
assert "pi_agent" in nodes
assert "critic_agent" in nodes
assert "error_handler" in nodes
```

**pytest 的执行模型**：

```
pytest 扫描 tests/ 目录
  → 找到所有 test_ 开头的函数
  → 逐个执行
  → 所有 assert 通过 → . （绿点，PASSED）
  → 任何一个 assert 失败 → F （红字，FAILED + 行号和变量值）
```

**为什么不用 `if/raise` 而用 `assert`**：

```python
# ❌ 手写: 啰嗦
if "validated_brief" not in annotations:
    raise ValueError("validated_brief missing")

# ✅ assert: 一行，pytest 自动显示失败时的变量值
assert "validated_brief" in annotations
```

pytest 在 assert 失败时会自动展开表达式，显示出左右两边的实际值——这叫 assertion introspection。

---

## Q2: 测试是怎么组织的？ `📄 test_collaboration_subgraphs.py`

**A:** pytest 按 **类 + 方法** 两级组织测试：

```python
class TestStateSchema:              # ← 测试类：测试 State Schema 相关
    def test_collaboration_state_fields(self):    # ← 测试方法：验证字段存在
        ...

class TestSubGraphCompilation:      # ← 测试类：测试编译相关
    def test_research_subgraph_compiles(self):    # ← 测试方法：验证 Research 编译
        ...

class TestStateMappingEmptyValues:  # ← 测试类：测试空值处理
    def test_none_values_not_written(self):       # ← 测试方法：验证 None 不写入
        ...
```

**分类原则**：一个类 = 一个被测模块/概念。类名描述"测什么"，方法名描述"测哪种情况"。

**辅助函数放在文件末尾**：

```python
def _make_parent_state(**overrides) -> CollaborationState:
    """创建测试用的 Parent State，避免每个测试重复构造。"""
    base: dict = {"messages": []}
    base.update(overrides)
    return base
```

**参数化测试（减少重复）**：

```python
@pytest.mark.parametrize("decision,expected", [
    ("approve", "report_composer"),
    ("modify", "analysis_subgraph"),
    ("replan", "research_subgraph"),
])
def test_hitl_decisions(self, decision, expected):
    """一个测试函数覆盖三种审批结果。"""
    state = _make_state(review_decision=decision)
    assert route_after_hitl(state) == expected
```

pytest 会把 `parametrize` 里的每组数据作为一个独立测试用例运行——3 组数据 = 3 个 PASSED。

---

## Q3: 纯函数为什么好测？ `📄 test_collaboration_subgraphs.py`

**A:** State Mapping 四个函数是纯函数——只读输入、只返回 dict、不修改输入、不读外部状态。测试它们只需要：

```python
# 准备输入
child = {"messages": [], "validated_brief": {"data": "test"}}
parent = {"messages": []}

# 调用
result = map_research_to_parent(child, parent)

# 验证输出
assert result["validated_brief"]["data"] == "test"
# 验证无副作用
assert "validated_brief" not in parent  # parent 没被修改
```

不需要 mock LLM、不需要启动沙箱、不需要网络——纯数据进，纯数据出。对比测试一个有 LLM 调用的节点，需要 mock `SubagentExecutor`、准备假响应、处理异步。

**这也是为什么架构设计时强调 State Mapping 必须是纯函数**——不仅是为了隔离，也是为了可测试性。如果 State Mapping 里有副作用（如读文件、调 API），每个测试都要准备外部环境。

---

> **已完成文档**: [01 — State 体系](01-state-system.md) | [02 — SubGraph 构建](02-subgraph-design.md) | [03 — Parent Graph](03-graph-orchestration.md)
