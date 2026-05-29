# 06 — 执行实例走读：Research SubGraph 全链路

> **日期**: 2026-05-14 | **Sprint**: 2 | **作者**: Wu Gang + Claude

---

## 涉及源文件

| 文件 | 角色 |
|------|------|
| [`backend/packages/harness/deerflow/collaboration/nodes/research_nodes.py`](../backend/packages/harness/deerflow/collaboration/nodes/research_nodes.py) | 6 个节点实现 |
| [`backend/packages/harness/deerflow/collaboration/prompts/research_prompts.py`](../backend/packages/harness/deerflow/collaboration/prompts/research_prompts.py) | 4 个角色提示词 |
| [`backend/packages/harness/deerflow/collaboration/protocols/messages.py`](../backend/packages/harness/deerflow/collaboration/protocols/messages.py) | Challenge/Rebuttal/Ruling 数据结构 |
| [`backend/packages/harness/deerflow/collaboration/protocols/debate.py`](../backend/packages/harness/deerflow/collaboration/protocols/debate.py) | DebateState 状态机 |
| [`backend/packages/harness/deerflow/collaboration/subgraphs/research_subgraph.py`](../backend/packages/harness/deerflow/collaboration/subgraphs/research_subgraph.py) | 图结构（边与路由） |

---

## 场景：用户请求竞品对比分析

用户输入：**"帮我对比分析 iPhone 17 和华为 Mate 70 Pro 的竞争力"**

Parent Graph 启动，`state_in: map_parent_to_research()` 将工作流配置投影到 ResearchSubGraphState，然后：

---

### Step 1: `pi_agent_node` — 规划研究任务

**进入时的 State**：
```python
ResearchSubGraphState:
  messages: [HumanMessage("帮我对比分析 iPhone 17 和华为 Mate 70 Pro 的竞争力")]
  # 其他字段全部为空
```

**节点做什么**：
1. 创建 `SubagentConfig(name="pi_agent", system_prompt=PI_AGENT_PROMPT, tools=["read_file"], ...)`
2. `get_available_tools()` 加载工具
3. `SubagentExecutor(config, tools).execute(task)` — 任务描述包含用户请求
4. PI Agent（LLM）读取 prompt："你是研究主管，规划任务、分发 Scouts..."
5. LLM 输出 JSON，被 `_extract_json()` 解析

**LLM 输出的 JSON**：
```json
{
  "topic": "iPhone 17 vs 华为 Mate 70 Pro 竞争力对比",
  "sub_tasks": [
    {"id": "t1", "query": "iPhone 17 最新规格、价格、销量", "target_sources": ["apple.com", "IDC"], "method": "web_search+web_fetch"},
    {"id": "t2", "query": "华为 Mate 70 Pro 最新规格、价格、销量", "target_sources": ["consumer.huawei.com", "IDC"], "method": "web_search+web_fetch"},
    {"id": "t3", "query": "2026Q1 全球高端智能手机市场份额", "target_sources": ["Counterpoint", "Canalys"], "method": "web_search+python"}
  ],
  "num_scouts": 3
}
```

**返回的 dict**：
```python
{"research_plan": {...如上 JSON...}}
```

**State 变化**：
```python
ResearchSubGraphState:
  research_plan: {"topic": "...", "sub_tasks": [...], "num_scouts": 3}
```

---

### Step 2: `data_scout_node` — 并行采集数据（首次采集模式）

> LangGraph 的 Send API 并行启动 3 个 Data Scout，每个独立执行

**进入时的 State**（以 Scout A 为例）：
```python
ResearchSubGraphState:
  research_plan: {"sub_tasks": [..., ...]}
  # scout_results 为空 → 判定为首次采集模式
```

**Data Scout 的 prompt（来自 `DATA_SCOUT_PROMPT`）** 告诉 LLM：
> "你是数据采集员。不能质疑别人，不能做裁决。输出 JSON：{source, content, data_points, methods}"

**LLM 执行过程**（SubagentExecutor 内部 ReAct 循环）：
```
Think: 我需要搜索 iPhone 17 规格
Tool: web_search("iPhone 17 specs price 2026")
Observe: 搜索结果返回 apple.com 链接
Tool: web_fetch("https://apple.com/iphone17/specs")
Observe: 页面内容含价格 $6999, A19 芯片...
Tool: python("import pandas; ...") ← 数据清洗
Observe: 清洗完成
Think: 数据采集完毕，输出 JSON
```

**LLM 输出**：
```json
{
  "source": "apple.com/iphone17/specs",
  "content": "iPhone 17 起售价 $6999，A19 芯片，6.3英寸 OLED...",
  "data_points": [
    {"label": "起售价", "value": "$6999", "confidence": 0.95},
    {"label": "芯片", "value": "A19", "confidence": 0.95},
    {"label": "屏幕", "value": "6.3英寸 OLED", "confidence": 0.90}
  ],
  "methods": ["web_search", "web_fetch", "python"]
}
```

**返回的 dict**：
```python
{"scout_results": [{...如上 JSON...}]}  # Annotated[list, add] 累加
```

3 个 Scout 并行完成后，State 中 `scout_results` 有 3 条记录。

---

### Step 3: `critic_agent_node` — 对抗式审查

**进入时的 State**：
```python
ResearchSubGraphState:
  scout_results: [
    {"source": "apple.com", "data_points": [{"label": "起售价", "value": "$6999"}]},
    {"source": "huawei.com", "data_points": [{"label": "起售价", "value": "¥5499"}]},
    {"source": "IDC 2026Q1", "data_points": [{"label": "iPhone 份额", "value": "23%"}, {"label": "华为份额", "value": "18%"}]}
  ]
  debate_round: 0
```

**Critic 的 prompt（来自 `CRITIC_AGENT_PROMPT`）** 告诉 LLM：
> "你是审查官。找一切矛盾、漏洞、偏见。每条质疑必须引用证据。不能自己采数据。"

**LLM 审查过程**：
```
审查 Scout A (apple.com): 价格 $6999 — 来源权威，但需要确认是税前/税后
审查 Scout B (huawei.com): 价格 ¥5499 — 币种不同，无法直接对比
审查 Scout C (IDC): iPhone 23% vs 华为 18% — 有效，但缺少 QoQ 变化
交叉验证: Scout A 价格 vs Scout C 给出的 ASP 不一致
```

**LLM 输出**：
```json
[
  {
    "challenge_id": "ch-001",
    "claim": "iPhone 和华为价格币种不同，无法直接比较",
    "evidence": [{"type": "methodology_gap", "source": "apple.com+huawei.com", "data": "$6999 vs ¥5499", "vs": "需要统一为同币种"}],
    "severity": "major",
    "suggested_remedy": "统一换算为 USD，使用当日汇率，含税/不含税标注"
  },
  {
    "challenge_id": "ch-002",
    "claim": "IDC 市场份额数据缺少季度环比变化",
    "evidence": [{"type": "methodology_gap", "source": "IDC 2026Q1", "data": "23%/18% 快照", "vs": "需要 QoQ 趋势"}],
    "severity": "minor",
    "suggested_remedy": "补充 IDC 2025Q4 数据做对比"
  }
]
```

**节点内部**：
```python
# 1. 解析 LLM 输出
challenges = _extract_json(result)  # → 上面的 JSON 列表

# 2. 推进 DebateState
debate_state = DebateState(current_round=0)
debate_state.advance_to_critique(challenges)  # current_round → 1, phase → CRITIQUING
```

**返回的 dict**：
```python
{
  "challenges": [ch_001_dict, ch_002_dict],  # Annotated[list, add]
  "debate_round": 1
}
```

---

### Step 4: `route_after_critic` — 条件路由

```python
def route_after_critic(state):
    challenges = state.get("challenges", [])
    debate_round = state.get("debate_round", 0)
    
    if challenges and debate_round < 2:
        return "data_scout"    # ← 有质疑且未满2轮 → 补采
    return "meta_judge"
```

此时：`challenges = [ch-001, ch-002]`, `debate_round = 1 < 2` → 返回 `"data_scout"`

图跳转到 `data_scout_node`，进入补采模式。

---

### Step 5: `data_scout_node`（补采模式）— 定向数据补采

**进入时的 State**：
```python
scout_results: [3条采集结果]
challenges: [ch-001, ch-002]
rebuttals: []  # 还没有补采过
```

**节点判断逻辑**：
```python
rebutted_ids = {}  # 还没有任何 rebuttal
pending_challenges = [ch-001, ch-002]  # 两个都需要补采
→ 取第一个 ch-001 进行补采
```

**Scout 的 prompt 中包含**：
> "You are responding to a Critic challenge. Challenge ID: ch-001. Claim: 价格币种不同. Suggested Remedy: 统一换算 USD..."

**LLM 执行**：
```
Tool: web_search("USD CNY exchange rate May 2026")
Tool: python("prices = {'iphone_usd': 6999, 'huawei_cny': 5499, 'rate': 7.05}; huawei_usd = 5499/7.05; ...")
```

**LLM 输出**：
```json
{
  "challenge_id": "ch-001",
  "new_data": [
    {"label": "iPhone 17 USD", "value": "$6999"},
    {"label": "华为 Mate 70 Pro USD", "value": "$780 (¥5499 ÷ 7.05)"},
    {"label": "汇率日期", "value": "2026-05-14, 1 USD = 7.05 CNY"}
  ],
  "addresses_concern": true,
  "note": "华为价格基于中国官网，未含出口关税",
  "methods": ["web_search", "python"]
}
```

**返回的 dict**：
```python
{
  "rebuttals": [{...rebuttal for ch-001...}],      # Annotated[list, add]
  "scout_results": [{...new_data...}]                # Annotated[list, add]，附带新数据
}
```

---

### Step 6: 回到 `critic_agent_node`（第 2 轮审查）

图沿 `data_scout → critic_agent` 回到 Critic。

**进入时的 State**：
```python
scout_results: [原始3条 + 汇率数据1条]
challenges: [ch-001, ch-002]
rebuttals: [rb-for-ch-001]  # ch-001 已回应
debate_round: 1
```

Critic 重新审查：ch-001 的汇率问题已解决（`addresses_concern: true`），ch-002（minor）仍存在但只是小问题。

**LLM 输出**：
```json
[]  // 无新质疑
```

**返回的 dict**：
```python
{"challenges": [], "debate_round": 2}
```

---

### Step 7: `route_after_critic`（再次）

```python
challenges = []  # 无新质疑
debate_round = 2
→ challenges 为空 → 返回 "meta_judge"
```

---

### Step 8: `meta_judge_node` — 独立裁决

**进入时的 State**：
```python
scout_results: [4条]
challenges: [ch-001, ch-002]
rebuttals: [rb-for-ch-001]
```

**Judge 的 prompt（来自 `META_JUDGE_PROMPT`）**：
> "你是独立裁决官。只看证据不看身份。裁决前至少跑一次 Python 检验。计算 quality_score。"

**LLM 执行过程**：
```
1. 审查 ch-001: Critic 说币种不同 → Scout 补充了汇率换算 → 已验证一致 → RESOLVED
2. 审查 ch-002: Critic 说缺少 QoQ → Scout 未回应(是 minor) → 不阻塞

3. 运行 Python 计算 quality_score:
   - 数据覆盖率: 8/10 expected data points = 0.8
   - 交叉验证率: 6/8 被至少2源确认 = 0.75
   - 冲突率: 1/2 challenges resolved = 0.5
   - weighted = 0.4*0.8 + 0.3*0.75 + 0.3*0.5 = 0.695
```

**LLM 输出**：
```json
{
  "ruling_id": "rul-20260514-001",
  "resolved": ["ch-001"],
  "unresolved": [{"challenge_id": "ch-002", "issue": "缺少 QoQ 数据", "reason": "minor 级别不阻塞，但建议最终报告标注"}],
  "dismissed": [],
  "quality_score": 0.70,
  "computation_summary": "数据覆盖率 0.80, 交叉验证率 0.75 (Pearson's r=0.92 between sources), 冲突解决率 0.50"
}
```

**返回的 dict**：
```python
{
  "ruling": {...如上 JSON...},
  "research_quality_score": 0.70
}
```

---

### Step 9: `pi_review_node` — PI 审核裁决书

**进入时的 State**：
```python
ruling: {"quality_score": 0.70, "resolved": ["ch-001"], "unresolved": [...]}
```

**PI 的 prompt**：
> "审核裁决书。默认批准。推翻只允许在发现明显逻辑错误时。"

**LLM 审查裁决书**：质量分 0.70 合理，ch-001 验证逻辑正确，ch-002 不阻塞。批准。

**LLM 输出**：
```json
{
  "validated_brief": {
    "topic": "iPhone 17 vs 华为 Mate 70 Pro 竞争力对比",
    "verified_data_points": [
      {"data": "iPhone 17 起售价 $6999", "source": "apple.com", "confidence": 0.95},
      {"data": "华为 Mate 70 Pro 折合 $780", "source": "huawei.com + 汇率换算", "confidence": 0.90},
      {"data": "iPhone Q1 份额 23%", "source": "IDC 2026Q1", "confidence": 0.85},
      {"data": "华为 Q1 份额 18%", "source": "IDC 2026Q1", "confidence": 0.85}
    ],
    "rejected_claims": [],
    "quality_score": 0.70,
    "unresolved": ["QoQ 趋势数据缺失（minor，不阻塞分析）"]
  }
}
```

**返回的 dict**：
```python
{"validated_brief": {...如上 JSON...}}
```

---

### Step 10: `route_after_pi_review` → END

```python
state.get("error") → None → 返回 "__end__"
```

Research SubGraph 结束。`state_out: map_research_to_parent()` 将 `validated_brief` 和 `quality_score` 写入 Parent State。

---

## 五类节点 + 三类协议 + 四个 Prompt 的协作全景

```
用户输入: "对比 iPhone 17 和华为 Mate 70 Pro"
  │
  ▼
┌─────────────────────────────────────────────────────────────┐
│ pi_agent_node                                               │
│   Prompt: PI_AGENT_PROMPT ("你是研究主管，规划+分发")         │
│   输出: research_plan (JSON)                                 │
│   协议: 无                                                   │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ data_scout_node (采集模式 ×3, Send API 并行)                 │
│   Prompt: DATA_SCOUT_PROMPT ("你是采集员，不能质疑")          │
│   输出: scout_results (JSON ×3)                              │
│   协议: 无（首次采集）                                         │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ critic_agent_node                                           │
│   Prompt: CRITIC_AGENT_PROMPT ("你是审查官，找漏洞，附证据")   │
│   输出: challenges (JSON list)                               │
│   协议: Challenge 数据结构, DebateState.advance_to_critique() │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
                route_after_critic (条件路由)
              needs_rebuttal? → Yes → data_scout
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ data_scout_node (补采模式)                                   │
│   Prompt: DATA_SCOUT_PROMPT ("回应 Critic 质疑，带新数据")    │
│   输出: rebuttals + scout_results                            │
│   协议: Rebuttal 数据结构, DebateState.advance_to_rebuttal()  │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
                critic_agent_node (第2轮) → route_after_critic
                challenges=[] → No → meta_judge
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ meta_judge_node                                             │
│   Prompt: META_JUDGE_PROMPT ("独立裁决，用 Python 计算")      │
│   输出: ruling + quality_score                               │
│   协议: Ruling 数据结构, DebateState.advance_to_adjudication()│
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ pi_review_node                                              │
│   Prompt: PI_AGENT_PROMPT ("审核裁决，默认批准")              │
│   输出: validated_brief                                      │
│   协议: DebateState.complete()                               │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
                     Research SubGraph 结束
                     state_out → Parent.validated_brief
```

**Prompt 只在 SubagentExecutor 内部生效**——每个节点通过 `SubagentConfig(system_prompt=XXX_PROMPT)` 把角色约束注入子 Agent。

**Protocol 数据在节点函数中创建和使用**——`_extract_json()` 从 LLM 文本提取结构化数据，`DebateState` 的方法推进辩论阶段。

**Node 的职责是"翻译"**——把 State 字段翻译成 SubagentExecutor 能理解的任务描述，再把 LLM 输出翻译回 State dict。

---

> **已完成文档**: [01](01-state-system.md) | [02](02-subgraph-design.md) | [03](03-graph-orchestration.md) | [04](04-testing-patterns.md) | [05](05-debate-protocol.md)
