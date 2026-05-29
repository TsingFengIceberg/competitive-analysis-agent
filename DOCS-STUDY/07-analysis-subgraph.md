# 07 — Analysis SubGraph：节点流转与分析 Prompt

> **日期**: 2026-05-14 | **Sprint**: 3 | **作者**: Wu Gang + Claude

---

## 涉及源文件

| 文件 | 角色 |
|------|------|
| [`backend/packages/harness/deerflow/collaboration/prompts/analysis_prompts.py`](../backend/packages/harness/deerflow/collaboration/prompts/analysis_prompts.py) | Analyst Lead / Synthesizer / Internal Reviewer / Report Composer 提示词 |
| [`backend/packages/harness/deerflow/collaboration/nodes/analysis_nodes.py`](../backend/packages/harness/deerflow/collaboration/nodes/analysis_nodes.py) | 4 个 Analysis 相关节点实现 |
| [`backend/packages/harness/deerflow/collaboration/subgraphs/analysis_subgraph.py`](../backend/packages/harness/deerflow/collaboration/subgraphs/analysis_subgraph.py) | Analysis SubGraph 图结构 |

---

## Q1: Analysis 四个 Prompt 各自讲了什么？ `📄 analysis_prompts.py`

**A:** 与 Research 阶段的"对抗式批判"不同，Analysis 阶段的 prompt 编码的是**分析流水线**逻辑——确定性更强，分支更少。

| 角色 | 核心指令 | 权限底线 | 输出要求 |
|------|---------|---------|---------|
| **Analyst Lead** | 接收 validated_brief，规划分析维度、选择 Skills、决定可视化 | 不能改研究数据，不能跳过内审 | `{dimensions, skills_to_use, comparison_framework, visualizations}` |
| **Synthesizer** | 执行多维分析：Python 计算 + Skill 调用 + matplotlib/plotly 图表 | 不能采集新数据，每个数字必须溯源到 validated_brief 的数据点 | `synthesis_report`：comparison_matrix + swot + trends + recommendations |
| **Internal Reviewer** | QA 内审：数据溯源检查、逻辑一致性、图表完整性、建议质量 | 不能直接修改报告，不能采集数据 | `{passed, issues[], trace_rate, recommendation_quality}` |
| **Report Composer** | 把 synthesis_report 转成 Markdown 格式写入 `/mnt/user-data/outputs/` | 不能修改分析结论，不能添加报告里没有的新数据 | `analysis_report.md`（通过 present_files 展示给用户）|

**与 Research Prompt 的关键差异**：

| | Research Prompt | Analysis Prompt |
|---|---|---|
| 交互模式 | 对抗式（角色互怼） | 协作式（顺序流水线） |
| 权限约束 | 严格（四权分立） | 较松（只管不改） |
| 工具需求 | 采集为主（web_search/fetch） | 计算为主（Python/Skills） |
| 输出目标 | 数据质量保证 | 洞察生成 |

---

## Q2: Analysis 节点怎么流转？走一个例子 `📄 analysis_nodes.py`

**A:** 以继续"iPhone 17 vs 华为 Mate 70 Pro"为例。Research SubGraph 已产出 `validated_brief`：

```python
validated_brief = {
    "topic": "iPhone 17 vs 华为 Mate 70 Pro 竞争力对比",
    "verified_data_points": [
        {"data": "iPhone 17 起售价 $6999", "source": "apple.com", "confidence": 0.95},
        {"data": "华为 Mate 70 Pro 折合 $780", "source": "huawei.com + 汇率换算", "confidence": 0.90},
        {"data": "iPhone Q1 份额 23%", "source": "IDC 2026Q1", "confidence": 0.85},
        {"data": "华为 Q1 份额 18%", "source": "IDC 2026Q1", "confidence": 0.85}
    ],
    "quality_score": 0.70,
    "unresolved": ["QoQ 趋势数据缺失"]
}
```

---

### Step 1: `analyst_lead_node` — 规划分析维度

**State 进入**：
```python
AnalysisSubGraphState:
  validated_brief: {...如上...}
  research_quality_score: 0.70
  # 其他字段全部为空
```

**节点做什么**：
1. `SubagentConfig(name="analyst_lead", system_prompt=ANALYST_LEAD_PROMPT, tools=["read_file"], model="claude-opus-4-7")`
2. `SubagentExecutor(config, tools).execute(task)` — 任务描述含 validated_brief
3. Analyst Lead（LLM）读 prompt："接收研究简报，规划分析维度，选择 Skills"
4. LLM 输出 JSON，被 `_extract_json()` 解析

**LLM 输出的 JSON**：
```json
{
  "dimensions": ["spec_comparison", "price_analysis", "market_position", "swot"],
  "skills_to_use": ["spec-comparator", "price-elasticity", "market-share-calc", "swot-generator"],
  "comparison_framework": {
    "categories": ["display", "chipset", "camera", "battery", "price"],
    "metrics": ["raw_value", "price_performance_ratio", "market_trend"],
    "weights": {"specs": 0.25, "price": 0.30, "market": 0.25, "swot": 0.20}
  },
  "visualizations": ["radar_chart", "price_bar_chart", "market_share_pie"],
  "priority_order": ["price_analysis", "spec_comparison", "market_position", "swot"]
}
```

**返回 dict**：
```python
{"analysis_plan": {...如上 JSON...}}
```

**State 变化**：新增 `analysis_plan` 字段。

---

### Step 2: `synthesizer_node` — 多维分析合成

**State 进入**：
```python
AnalysisSubGraphState:
  validated_brief: {...}
  analysis_plan: {dimensions: [...], skills_to_use: [...], ...}
```

**SubagentConfig** — 这是最重的子代理：
```python
SubagentConfig(
    name="synthesizer",
    system_prompt=SYNTHESIZER_PROMPT,
    tools=["read_file", "python", "write_file"],
    skills=["spec-comparator", "price-elasticity", "market-share-calc", "trend-detector"],
    model="claude-opus-4-7",
    max_turns=50,  # 分析任务重，允许 50 轮
)
```

**LLM 执行过程**（SubagentExecutor 内部 ReAct）：
```
1. "加载 spec-comparator Skill，对比两台手机的规格"
   → Skill 生成对比表 CSV → python 读取并生成雷达图 → write_file

2. "加载 price-elasticity Skill，分析价格弹性"
   → python: 计算 $6999 vs $780 → 价格段差异 → 生成柱状图

3. "加载 market-share-calc Skill"
   → python: 23% vs 18% → 饼图 → 计算 HHI 指数

4. "加载 swot-generator Skill"
   → 基于前面数据生成 SWOT 矩阵
```

**LLM 输出**：
```json
{
  "synthesis_report": {
    "comparison_matrix": {
      "display": {"iphone": "6.3\" OLED 120Hz", "huawei": "6.8\" OLED 120Hz"},
      "chipset": {"iphone": "A19 3nm", "huawei": "Kirin 9100 5nm"},
      "price": {"iphone": "$6999", "huawei": "$780"}
    },
    "swot_analysis": {
      "iphone": {"strengths": ["A19 性能领先", "iOS 生态"], "weaknesses": ["价格高 9x"], ...},
      "huawei": {"strengths": ["价格优势巨大", "中国市场品牌"], "weaknesses": ["芯片制程落后一代"], ...}
    },
    "trend_analysis": {"iphone_share_trend": "stable", "huawei_share_trend": "rising +2% QoQ"},
    "recommendations": [
      {"priority": 1, "action": "iPhone 需在价格段防御华为高端冲击", "urgency": "high"},
      {"priority": 2, "action": "华为应强调芯片性能进步以缩小认知差距", "urgency": "medium"}
    ]
  }
}
```

**返回 dict**：
```python
{
  "analysis_results": [{dimension: "combined", data: {...}, insight: "...", confidence: 0.8}],
  "synthesis_report": {...如上 JSON...}
}
```

**State 变化**：新增 `analysis_results` 和 `synthesis_report`。

---

### Step 3: `internal_reviewer_node` — 质量内审

**State 进入**：
```python
AnalysisSubGraphState:
  synthesis_report: {comparison_matrix: {...}, swot: {...}, ...}
  validated_brief: {...}  # 用于溯源检查
```

**SubagentConfig**：
```python
SubagentConfig(
    name="internal_reviewer",
    system_prompt=INTERNAL_REVIEWER_PROMPT,
    tools=["read_file", "python"],
    model="inherit",
    max_turns=15,
)
```

**LLM 审查过程**：
```
1. 溯源检查: synthesis_report 里的 4 条 claims 是否都能追溯到 validated_brief 的 data_points？
   → 4/4 可追溯, trace_rate = 1.0

2. 可视化检查: 预期 3 张图 (radar/bar/pie)，是否都已生成？
   → 3/3 ✅

3. 逻辑一致性: "华为价格优势巨大" 是否从 $6999 vs $780 合理推导？
   → ✅

4. 建议质量: 建议是否具体、可衡量、有时限？
   → "adequate" (第二条有点模糊)
```

**LLM 输出**：
```json
{
  "passed": true,
  "issues": [],
  "data_trace_check": {"total_claims": 4, "claims_with_source_trace": 4, "trace_rate": 1.0},
  "visualization_check": {"expected_count": 3, "generated_count": 3, "all_present": true},
  "recommendation_quality": "adequate",
  "suggestions": ["建议 #2 可增加具体 KPI 指标"]
}
```

**返回 dict**：
```python
{"internal_review_passed": True, "review_feedback": "{...如上 JSON...}"}
```

---

### Step 4: `route_after_reviewer` → END

```python
state.get("internal_review_passed") → True → return "__end__"
```

Analysis SubGraph 结束。`state_out: map_analysis_to_parent()` 把 `synthesis_report` 写入 Parent State。

---

### Step 5: Parent 层 — HITL Gate → Report Composer

```
Parent Graph:
  route_after_analysis → 无错误 → hitl_gate
    → 人类审批 approve
    → report_composer_node
      → SubagentConfig(REPORT_COMPOSER_PROMPT, tools=["write_file", "python", "bash"])
      → 生成 /mnt/user-data/outputs/analysis_report.md
      → present_files → 用户可见
```

---

## Analysis SubGraph 完整流转图

```
validated_brief (来自 Research)
        │
        ▼
┌──────────────────────────────────────────────┐
│ analyst_lead_node                             │
│   Prompt: ANALYST_LEAD_PROMPT                 │
│   输入: validated_brief                       │
│   输出: analysis_plan (JSON)                  │
│   工具: read_file                             │
│   轮次: 15                                    │
└──────────────────┬───────────────────────────┘
                   ▼
┌──────────────────────────────────────────────┐
│ synthesizer_node                              │
│   Prompt: SYNTHESIZER_PROMPT                  │
│   输入: validated_brief + analysis_plan        │
│   输出: synthesis_report (JSON)               │
│   工具: read_file, python, write_file          │
│   Skills: spec-comparator, price-elasticity,  │
│           market-share-calc, trend-detector    │
│   轮次: 50                                    │
└──────────────────┬───────────────────────────┘
                   ▼
┌──────────────────────────────────────────────┐
│ internal_reviewer_node                        │
│   Prompt: INTERNAL_REVIEWER_PROMPT            │
│   输入: synthesis_report + validated_brief     │
│   输出: {passed, issues, trace_rate, ...}     │
│   工具: read_file, python                     │
│   轮次: 15                                    │
└──────────────────┬───────────────────────────┘
                   ▼
         route_after_reviewer
         passed=True → __end__
         passed=False → error_handler
                   ▼
              state_out: map_analysis_to_parent
                   ▼
         Parent.synthesis_report 就绪
                   ▼
            HITL Gate (Sprint 4)
                   ▼
         report_composer_node → Markdown 报告
```

**与 Research SubGraph 的关键差异**：

| | Research | Analysis |
|---|---|---|
| 流程结构 | 循环（Critic ⇄ Scout） | 顺序（Lead → Synth → Reviewer） |
| 并行 | Send API 分发多个 Scout | 无并行（单线程流水线） |
| 状态机 | DebateState（轮次控制） | 无（顺序执行） |
| 异常处理 | error → state_out 上浮 | error → route_after_reviewer → error_handler |
| 输出 | validated_brief（数据） | synthesis_report（洞察） |

---

> **已完成文档**: [01](01-state-system.md) | [02](02-subgraph-design.md) | [03](03-graph-orchestration.md) | [04](04-testing-patterns.md) | [05](05-debate-protocol.md) | [06](06-execution-walkthrough.md)
