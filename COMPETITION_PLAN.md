# PA-Agent-DF → AI 全栈挑战赛 适配方案

> **比赛**: AI 全栈项目挑战赛 — AI 驱动的竞品分析 Agent 协作系统
> **时间**: 2026-05-20 ~ 2026-06-10 (3周)
> **题目来源**: 字节跳动 CIS（集团信息系统部）
> **当前项目**: PA-Agent-DF（基于 DeerFlow 的泛商品协同分析系统）

---

## 一、比赛需求分析

### 1.1 核心要求（来源：[【CIS】AI 全栈项目挑战赛开题材料](https://bytedance.larkoffice.com/wiki/Y7Qkw7TvYiwRDzkKxgycJhFOnuc) §2 课题介绍）

| 维度 | 要求 | 来源 |
|------|------|------|
| Agent 数量 | 3-4 个（非固定，可有其他设计） | 开题材料 |
| 编排框架 | LangGraph / CrewAI 推荐，**可手搓，不限制** | 开题材料 |
| Agent 通信 | **结构化消息传递**（function calling / Schema），非纯自然语言 | **[竞赛要求]** 开题材料 §2 |
| 知识结构化 | 定义竞品知识 Schema（功能树、定价模型、用户画像），输出必须符合 | **[竞赛要求]** 开题材料 §2 |
| 反馈闭环 | 质检 Agent 可将不足打回采集 Agent，形成 DAG 式任务流转迭代闭环 | **[竞赛要求]** 开题材料 §2 |
| 信息溯源 | 每条分析结论标注数据来源，支持 traceability | **[竞赛要求]** 开题材料 §2 |
| 可观测 | 每个 Agent 决策过程与中间产物可追溯 | **[竞赛要求]** 开题材料 §2 |
| 问卷/访谈 | 采集 Agent 包含问卷设计、问卷调研、用户访谈（都行，能完全自动化更好） | **[竞赛要求]** 开题材料 §2 |
| 开源合规 | 只能使用 MIT / Apache 2.0 / BSD 协议的开源库 | 会议纪要 |
| 前端 | 推荐做前端展示页面，可现场演示 | 开题材料 + 会议纪要 |

### 1.2 评分权重（来源：开题材料 §4 判断标准）

| 维度 | 权重 | 考察要点（官方原文） |
|------|------|---------------------|
| **多 Agent 协作与输出可信度** | **35%** | ①角色划分清晰，职责边界明确无重叠 ②编排框架使用合理，DAG 任务流转可视化、可追溯 ③Agent 间采用结构化消息传递，非纯自然语言 ④反馈闭环真实可触发：质检 Agent 能识别问题并打回重做，且重做后输出有改善（非伪闭环） ⑤输出严格符合预定义竞品知识 Schema ⑥信息溯源完整：每条结论可定位到原始数据源，支持一键跳转 |
| **技术深度与工程完整度** | **25%** | ①端到端链路完整，可支持现场演示 ②可观测性达标：Prompt/输入/输出/决策过程/Token 消耗均有日志可查 ③上下文管理、错误恢复、幻觉抑制有明确策略（自一致性校验、引用强制、超长上下文分片） ④系统稳定性：异常处理、超时重试、降级机制完备 ⑤技术方案有独特或前瞻性思考（自适应任务拆分、Agent 自评估、动态 Schema 演化） |
| **业务价值与产品体验** | **20%** | ①相比传统人工竞品分析，在效率/覆盖度/一致性上有可量化的提升 ②贴合企业竞品分析真实工作流，具备可落地性与可扩展性 ③交互设计流畅：报告查看、溯源跳转、人工介入修正、Agent 决策回放易用直观 ④设计了清晰的业务闭环（含关键指标如准确率、覆盖率、人工修正率） |
| **代码质量与文档** | **10%** | ①代码风格规范、模块化清晰、注释充分 ②文档齐全：README、架构图、Agent 角色与协议文档、部署说明 ③Git 提交记录规范，分支管理清晰 ④TRAE 等 AI 编程工具的使用痕迹清晰，体现深度协作 |
| **合规、材料与答辩** | **10%** | ①信息采集合规：遵守 robots.txt 与服务条款 ②数据隐私与安全：用户访谈、问卷数据脱敏处理 ③工具/模型/数据使用符合比赛要求 ④提交材料完整：方案文档、演示视频、代码库齐全 ⑤答辩讲解清晰有条理 |

### 1.4 竞赛要求追溯矩阵

> 每条 `**[竞赛要求]**` 标记对应开题材料或会议纪要中的具体条款。评审可据此快速定位实现位置。

| # | 竞赛要求（原文关键词） | 来源 | 实现章节 | 实现方式 |
|---|---------------------|------|---------|---------|
| R1 | 角色 Agent：采集/分析/撰写/质检，职责边界明确 | 开题 §2 | [§3.3 角色定义](#33-4-个-agent-角色定义) + [§3.4 Collector规范](#34-collector-采集规范-竞赛要求-r1-r2) + [§3.5 Analyst规范](#35-analyst-分析规范) | 4 Agent 角色定义 + Collector 6 项采集规则 + Analyst 5 项分析规则 |
| R2 | 采集 Agent 含问卷设计/问卷调研/用户访谈 | 开题 §2 | [§4.4 VoC Aggregator](#44-用户声音聚合器-voice-of-customer-aggregator-竞赛要求-r2) + [§3.3 Collector双轨](#33-4-个-agent-角色定义) | VoC Aggregator（主）+ 问卷生成（辅）双轨 |
| R3 | 知识结构化：功能树/定价模型/用户画像 Schema | 开题 §2 | [§3.9 竞品知识 Schema](#39-竞品知识-schemapydantic-强制校验) + [§3.10 Schema强制校验链](#310-schema-强制校验链竞赛要求-r3-r8) | 3 个 Pydantic BaseModel + model_validate() 强制校验 |
| R4 | Agent 间结构化消息传递，非纯自然语言 | 开题 §2 | [§3.12 结构化通信协议](#312-agent-间结构化通信协议-竞赛要求-r4) | 6 边完整 Schema（AnalysisResult/ReviewVerdict/ReviewPackage/HitlDecision） |
| R5 | 质检 Agent 将不足打回采集 Agent，DAG 式迭代闭环 | 开题 §2 | [§3.6 Reviewer审阅清单](#36-reviewer-审阅清单与判定规则-竞赛要求-r5) + [§3.7 DAG工作流](#37-dag-工作流) + [§3.12 路由逻辑](#311-路由逻辑普通模式--深度模式流水线) | route_after_reviewer → collector，最多 2 轮，8 种 gap 判定规则 |
| R6 | 反馈闭环真实可触发，重做后输出有改善（非伪闭环） | 判标 §4 | [§3.11.1 改善追踪](#3111-反馈闭环改善追踪竞赛要求) | gap 覆盖率追踪 + 改善度量 |
| R7 | 每条分析结论标注数据来源，支持 traceability | 开题 §2 | [§3.8 CompetitionState](#38-competitionstate-设计) + [§3.3 Writer](#33-4-个-agent-角色定义) | traceability_map + 报告内联 `[n]` 标注 |
| R8 | 输出严格符合预定义 Schema，字段完整格式一致 | 判标 §4 | [§3.10 Schema强制校验链](#310-schema-强制校验链竞赛要求-r3-r8) | model_validate() + 自动重试 + 降级 |
| R9 | DAG 任务流转可视化、可追溯 | 判标 §4 | [§7.2](#72-dag-执行图核心展示位) | ReactFlow 节点高亮 + 边动画 |
| R10 | 可观测性：Prompt/输入/输出/决策过程/Token 可查 | 开题 §2 + 判标 §4 | [§7.1-7.7](#七答辩呈现设计--内部工作流可视化) | 双面板 + Agent 详情 + 消息流日志 |
| R11 | 端到端链路完整，可现场演示 | 判标 §4 | [§3.7 DAG工作流](#37-dag-工作流) + [§8](#八3-周开发计划含答辩呈现) | 普通模式全链路 + 前端 |
| R12 | 上下文管理、错误恢复、幻觉抑制有明确策略 | 判标 §4 | [§3.15.1 幻觉抑制](#3141-幻觉抑制三策略竞赛要求-r12) | 自一致性校验 + 引用强制 + 超长分片 |
| R13 | 超时重试、降级机制完备 | 判标 §4 | [§3.15.5 超时重试](#3145-超时重试与降级-竞赛要求-r13) | per-Agent 超时 + 指数退避 + 降级 |
| R14 | 技术方案有独特或前瞻性思考 | 判标 §4 | [§6](#六核心差异化创新点总结) | 来源可信度动态演化 + 字节生态深度集成 + 双视角报告 |
| R15 | 效率/覆盖度/一致性可量化提升 | 判标 §4 | [§3.15.4 业务指标](#3144-业务指标可量化追踪竞赛要求) | 准确率/覆盖率/人工修正率指标 |
| R16 | 交互设计流畅：报告查看、溯源跳转、人工介入修正 | 判标 §4 | [§5.7](#57-人对报告的细粒度交互式编辑p0--答辩核心交互) + [§7.5](#75-溯源链视图traceability-viewer) | 飞书文档交互 + 溯源链视图 |
| R17 | 信息采集合规：遵守 robots.txt 与服务条款 | 判标 §4 | [§3.15.2 采集合规](#3142-采集合规竞赛要求) | robots.txt 预检 + 来源声明 |
| R18 | 数据隐私与安全：问卷/访谈数据脱敏 | 判标 §4 + 会议纪要 | [§3.15.3 数据脱敏](#3143-数据脱敏竞赛要求) | PII 自动检测 + 匿名化 |
| R19 | TRAE 等 AI 编程工具使用痕迹清晰 | 判标 §4 | [§8](#八3-周开发计划含答辩呈现) | Git 提交记录 + TRAE IDE 工作流 |
| R20 | 项目文档齐全：README/架构图/角色协议/部署说明 | 判标 §4 | [§10](#十参考信息) + README + PA-AGENT-DOCS/ | 文档体系 |
| R21 | 前段展示页面，可现场演示 | 开题 + 会议纪要 | [§7](#七答辩呈现设计--内部工作流可视化) + [§8 Week 2](#week-2-527--63-前端--可观测--飞书集成) | Gradio/Next.js + DAG 可视化 |
| R22 | 细分方向可做，系统需具备扩展性 | 会议纪要 | [§3.2](#32-双模定位对比) + config.yaml workflows | 双模架构 + 可配置 workflow |

> **标记说明**：文档中 `**[竞赛要求]**` 标记表示该段落/设计直接对应上述某条竞赛要求。评审可搜索此标记快速验证覆盖率。

### 1.5 "竞品分析"的范围

- **非固定品类**：可以做 AI 产品、企业软件、消费电子等任意方向
- **导师建议**：从 6 类用户（产品经理/创业者/市场/销售/投资人/设计师）中选 2 类控制范围
- **推荐聚焦**：**产品经理 + 创业者/项目负责人**（导师明确推荐）
- **关键约束**："可以做细分方向，但系统需具备扩展性" `**[竞赛要求 R22]**`

### 1.6 提供的资源

- **LLM**: Doubao-Seed-2.0-lite（EP + API Key 已提供）
- **工具推荐**: TRAE IDE（也可使用其他，有 Coding 记录更好）
- **参考**: TRAE IDE 模型配置操作指南

---

## 二、现有 PA-Agent-DF 评估

### 2.1 项目现状

| 指标 | 数值 |
|------|------|
| 协作代码量 | ~3300 行 Python |
| 测试数量 | 180 个（全 mock SubagentExecutor） |
| 架构 | Nested SubGraph（Parent + Research + Analysis） |
| 角色数 | 8 个（PI / Scout / Critic / Judge / Analyst Lead / Synthesizer / Internal Reviewer / Report Composer） |
| 独特机制 | 对抗式批判（Critic + Judge 四权分立）、HITL Gate、State Mapping、来源可信度记忆 |

### 2.2 保留 vs 砍掉

#### 保留（直接复用/适配）

| PA-Agent-DF 组件 | 比赛中的角色 |
|------------------|------------|
| `collaboration/state.py` TypedDict State 设计 | 简化成单层 CompetitionState |
| `collaboration/graph.py` LangGraph StateGraph 编排模式 | 4 节点单图 + 条件路由反馈闭环 |
| `collaboration/router.py` 条件路由逻辑 | Collector → Analyst → Reviewer 闭环 |
| `collaboration/nodes/research_nodes.py` 节点实现模式 | Collector / Reviewer 节点 |
| `collaboration/nodes/analysis_nodes.py` | Analyst / Writer 节点 |
| `collaboration/protocols/messages.py` 结构化消息 | Agent 间 JSON Schema 通信 |
| `collaboration/memory/source_credibility.py` | 来源可信度评分（差异化亮点） |
| `collaboration/nodes/hitl_gate.py` HITL interrupt | 人类修正中途结果入口 |
| DeerFlow Sandbox（bash/python/ls/read/write） | Python 计算 + 可视化 |
| DeerFlow Community Tools（web_search/web_fetch） | 真实数据采集 |
| DeerFlow Checkpointer（SqliteSaver） | 状态持久化 |
| DeerFlow 中间件链 | 复用（Summarization/LoopDetection/TokenUsage） |

#### 砍掉

| PA-Agent-DF 组件 | 原因 |
|------------------|------|
| Nested SubGraph 三层结构 | 简化为单图，减少调试复杂度 |
| Critic Agent + Meta-Judge 独立分离 | 合并为一个 Reviewer 节点 |
| `permissions/role_definition.py` 四权分立 | 4 角色不需要复杂权限系统 |
| `protocols/debate.py` 辩论状态机 | 简化为单次交叉验证 |
| 8 个角色 Prompt 模板 | 精简为 4 个 |
| `subgraphs/state_mapping.py` | 单图不需要子图映射 |
| `context.py` 角色上下文 | 简化 |
| 硬编码 `SubagentConfig` 引用不存在模型名 | 替换为比赛提供的豆包模型 |

---

## 三、比赛项目架构设计

### 3.1 总体架构：普通模式 + 深度模式（流水线增强）

> **核心理念**：普通模式是比赛的主体（80-100 分），不阉割任何核心环节。
> 深度模式是可选增强，以普通模式输出为起点，进一步做更深入的调研和分析。

```
用户输入 (deep_mode: false | true)
         │
         ▼
┌────────────────────────────────────────────────────────────┐
│               📋 普通模式 (始终执行, 比赛基准)               │
│                                                            │
│  Collector ──→ Analyst ──→ Reviewer ──→ Writer ──→ HITL   │
│      ↑             ↑           │            │         │    │
│      │             │           │ ❌          │    approve │
│      └─────────────┴── gap ────┘            │   replan   │
│           (结构化 JSON, 最多 2 轮)           │ reanalyze  │
│                                              │  rewrite   │
│                                              │         │    │
│                                         普通报告输出       │
│                                         (前端展示)         │
└──────────────────────┬─────────────────────────────────────┘
                       │
                       │  普通报告 (report_data → 前端交互展示)
                       │
                       ▼
               deep_mode == true ?
                       │
              ┌────────┴────────┐
              │ NO              │ YES
              ▼                 ▼
            END    ┌──────────────────────────────────────────┐
                   │         🔬 深度模式 (可选增强)            │
                   │                                          │
                   │  以普通报告为种子，进一步:                   │
                   │  • 更多数据源 (视频/抖音/飞书文档)          │
                   │  • 更多轮验证 (无上限，直到收敛)             │
                   │  • 更精细分析 (细分市场/用户分群/财务预测)   │
                   │  • 更完整报告 (ReportData + 导出 + 飞书推送)      │
                   │  • 飞书文档自动创建 + Bot 通知              │
                   │                                          │
                   │  Deep Collector → Deep Analyst            │
                   │       ↑              │                    │
                   │       │         Deep Reviewer             │
                   │       │              │                    │
                   │       └── gap ──────┘ (轮数放宽)          │
                   │                     │                    │
                   │               Deep Writer                 │
                   │                     │                    │
                   │               Deep HITL (可选)             │
                   │                     │                    │
                   │              飞书文档交付 + Bot 通知       │
                   └──────────────────────────────────────────┘
```

### 3.2 双模定位对比

| 维度 | 📋 普通模式 | 🔬 深度模式 |
|------|-----------|-----------|
| **定位** | **比赛主体 (80-100 分)**，完整竞品分析系统 | **锦上添花**，以普通模式输出为起点的增强 |
| **触发** | 始终执行 | 用户显式开启 `deep_mode: true` |
| **输入** | 用户原始请求 | 普通模式的完整输出 (report_data + analysis_result) |
| **Collector** | 多源搜索 + 意图路由 + 中英文分流（§3.4） | 增量采集：基于知识缺口补充视频/抖音等深层源 |
| **Analyst** | 对比矩阵 + SWOT + 趋势 + 预测推演（§3.5） | 细分分析 + 用户分群 + 财务/市场预测 |
| **Reviewer** | ✅ 8 项计算验证 + 2 轮反馈（§3.6） | ✅ 更深验证，轮数放宽 |
| **HITL** | ✅ 前端审批 + 自由文本交互（§5.2） | ✅ 可选二次审批 + 飞书推送 |
| **Writer** | 双视角 ReportData 交互报告（§3.7） | ReportData + Markdown/PDF/PPTX 导出 + 飞书 Doc |
| **交付** | 前端交互报告 + 溯源查看 + What-if 推演 | 飞书文档 `docs +create` + Bot 通知 |
| **数据源** | **不定死** — 编码时实测后决定。如果全模态抓取速度可接受，普通模式也会加入 | 覆盖普通模式未使用的更深层源 |
| **目标耗时** | 不做硬性时间目标，编码实测后定 | 无时间上限 |

### 3.3 4 个 Agent 角色定义 `**[竞赛要求 R1]**`

> 每个 Agent 在普通模式中已具备完整能力。深度模式下行为增强但不替换。

| Agent | 普通模式职责 | 深度模式额外行为 |
|-------|------------|----------------|
| **Collector** | 多源并行采集、用户声音聚合、**问卷生成与访谈支持**、定向补采 | 增量采集：基于知识缺口补充视频/抖音/深层源 |
| **Analyst** | 多维对比、SWOT、趋势、可视化 | 细分分析（按用户群/地域/场景）、预测建模 |
| **Reviewer** | 交叉验证、Python 统计检验、gap 打回采集（≤2轮）、飞书审批推送 | 更多轮验证（无硬上限）、对深度新增内容专项验证 |
| **Writer** | 双视角 ReportData 交互报告 + 内联溯源 + 一键导出 | Markdown/PDF/PPTX 导出 + 飞书 Doc 推送 |

#### Collector 的双轨采集能力 `**[竞赛要求 R2]**`

竞赛明确要求采集 Agent 需覆盖"问卷设计、问卷调研、用户访谈"。我们的 Collector 采用双轨设计：

| 轨道 | 方式 | 覆盖场景 | 自动化程度 |
|------|------|---------|-----------|
| **轨 1（默认）** | VoC Aggregator：多平台评论自动聚合（G2/Reddit/GitHub/ProductHunt/App Store） | 用户真实反馈、痛点提取、情感分析 | 🤖 完全自动 |
| **轨 2（按需）** | 问卷 + 访谈生成：Collector 根据分析目标自动生成结构化问卷（Markdown/飞书表单），用户可分发回收 → Collector 解析回填至 State | 需要定向调研的深度问题、特定用户群访谈 | ✍️ 人协作 |

**问卷生成示例**：当用户请求"调研目标用户对 AI 编程工具的偏好"时，Collector 生成：

```markdown
## 自动生成的调研问卷：AI 编程工具用户偏好

### 基本信息
1. 您目前主要使用哪个 AI 编程工具？（Cursor / Copilot / Claude Code / Windsurf / 其他）
2. 您的角色是？（专业开发者 / 技术管理者 / 学生 / 创业者）

### 功能需求（1-5 分）
3. 代码补全准确性 [ ]
4. 上下文理解能力 [ ]
5. 多文件重构能力 [ ]

### 痛点
6. 当前工具最大的不足是什么？[开放回答]
```

**访谈支持**：Collector 可生成结构化访谈提纲 + 接收用户粘贴的访谈记录/上传的音频转录文本 → 自动提取关键观点 → 结构化为 `CollectedDataPoint` → 纳入 State。

### 3.4 Collector 采集规范 `**[竞赛要求 R1, R2]**`

> 采集是整个系统的感官，Collector 不是"无脑搜"，而是按以下固定规则执行——搜什么、怎么搜、何时停、去重逻辑。

#### 3.4.1 有效数据点最低门槛

**字段完整性（结构门槛，必须全部满足才能进入 State）：**

| 字段 | 要求 | 缺失时行为 |
|------|------|-----------|
| `id` | 非空，格式 `dp-{timestamp}-{seq}` | 系统自动生成，不会缺失 |
| `product` | 非空，必须匹配 target_products 之一 | LLM 未填 → 重试 1 次；仍缺失 → 丢弃，记日志 |
| `category` | 必须属于 features / pricing / users / market | 其他值 → LLM 重分类 1 次；无法分类 → 归入 market |
| `label` | 非空，一句话描述（如 "Cursor Pro 月费价格"） | 缺失 → 重试 1 次；仍缺失 → 丢弃 |
| `value` | str 或 float，非 None | 缺失 → 重试 1 次；仍缺失 → 丢弃 |
| `source_url` | 非空，必须是有效 URL 格式 | 缺失 → **拒绝入库**（引用强制 §3.11.1） |
| `source_type` | 必须属于 official / review / news / interview / social | 缺失 → LLM 推断 1 次；推断不出 → 标记 "unknown" |
| `collected_at` | ISO 8601 格式 | 缺失 → 系统自动填当前时间 |

**内容可信度信号（不阻止入库，影响后续 Reviewer 判定）：**

| 信号 | 阈值 | 处理 |
|------|------|------|
| `confidence` | LLM 自评或 API 返回 | < 0.5 → 标记 `low_confidence=True`，Reviewer G8 触发复核 |
| source_url 可达性 | 暂不校验（留给 Reviewer G1） | Collector 不做 HEAD 请求，避免拖慢采集 |
| value 内容长度 | < 3 字符 | 标记 "⚠ 可能截断" |

> **关键决策**：Collector 只管"有没有来源 URL"，不管"来源对不对"——后者是 Reviewer 的职责。分割依据：判标 §4 35% 要求"引用强制"（Collector 负责），"自一致性校验"（Reviewer 负责）。

#### 3.4.2 去重规则

**两条数据点判定重复的标准**：

```
product 相同 + category 相同 + label 语义等价（LLM 判定指向同一事实）
```

语义等价示例：
- ✅ 重复 → "Cursor Pro 月费" ≈ "Cursor Pro 订阅价格（月度）"
- ❌ 不重复 → "Cursor Pro 月费" ≠ "Cursor 团队版年费"

**合并 vs 保留**：

| 场景 | 处理 |
|------|------|
| 重复 + value 差异 < 5% | **合并**：保留最早采集的那条，source_url 追加第二个来源，confidence 取 max |
| 重复 + value 差异 ≥ 5% | **都不合并**：两条都保留，label 后加来源标识（如 "[官网]" vs "[G2]"），留给 Reviewer G2 判定 source_conflict |
| 重复 + 来自同一 source_url | **丢弃**最新的一条（同源重复 = 采集 bug） |

**实现**：Collector 写入 State 前，对本轮 `collected_data` 做 pandas `groupby(["product", "category", "label_norm"]) → agg` 风格过滤。

#### 3.4.3 停止条件

Collector 不能让 Agent 无限搜索。两层停止：

**硬停止（无视结果质量，强制终止）：**

| 条件 | 值 |
|------|-----|
| max_turns 耗尽 | SubagentConfig.max_turns=30 |
| timeout | timeout_seconds=600s |
| 连续空结果 | 连续 3 次工具调用返回 0 条结果 |

**软停止（结果足够好时提前结束）：**

| 条件 | 阈值 |
|------|------|
| 维度覆盖 | 每个 target_product 在每个 category 均有 ≥ 2 条数据 |
| 来源多样性 | ≥ 3 种 source_type |
| 数据点总量 | ≥ 20 条 |

软停止 3 个条件**同时满足** → Collector 主动结束，不等 max_turns。

> **设计理由**：不加软停止，Collector 每次跑到 max_turns=30 才停，浪费 2-3 分钟。加软停止后大多数场景 15-20 轮结束。答辩话术："系统知道什么时候搜够了，不会无限搜索。"

#### 3.4.4 搜索词生成规则

从用户自然语言输入生成精确搜索词。由 LLM 生成，受规则约束。

**输入**：`"帮我分析一下 Cursor vs Copilot vs Windsurf 的竞争力"`

**搜索词生成策略**：

| 搜索维度 | 模板 | 示例 |
|---------|------|------|
| 基础信息 | `{product} pricing 2026` | `Cursor AI editor pricing 2026` |
| | `{product} features` | `GitHub Copilot features list` |
| | `{product} vs` | `Cursor vs Copilot comparison 2026` |
| 用户口碑 | `{product} review reddit` | `Cursor AI editor review reddit 2026` |
| | `{product} g2 rating` | `Windsurf editor g2 rating` |
| 技术深度 | `{product} github` | `Cursor AI github repository stars` |
| | `{product} tech stack` | `GitHub Copilot technical architecture` |
| 商业信息 | `{product} funding` | `Windsurf AI funding round 2026` |
| | `{product} market share` | `AI code editor market share 2026` |
| 中文市场 | `{product中文名/英文名} 评测` | `Cursor 编辑器 评测 2026` |
| | `{product中文名} 定价` | `Copilot 中文 定价` |

**规则约束**：
- 每个 target_product × 每个 category（features/pricing/users/market）至少 1 条
- 搜索词总数下限 = `len(target_products) × 4 × 1.5`
- 中英文搜索词**各至少 1/3**
- 时间限定词（"2026"、"latest"、"最新"）默认附加

**实现**：Collector 的 system prompt 注入 `SEARCH_QUERY_TEMPLATE`，LLM 按模板填充。

#### 3.4.5 来源优先级与 Fallback 链

按**查询意图**分叉，不是平面列表：

```
Collector 搜索决策
  │
  ├─ 中文内容?
  │   ├─ 1st: 火山引擎联网搜索（中文原生 + 多模态）
  │   ├─ fallback: Tavily Search
  │   └─ last: Brave Search
  │
  ├─ 英文技术/产品信息?
  │   ├─ 1st: Tavily Search（英文优化）
  │   ├─ fallback: Brave Search
  │   └─ 补充: GitHub API（开源项目）
  │
  ├─ 用户评价/口碑?
  │   ├─ 1st: G2 / Product Hunt（web_fetch 专用页）
  │   ├─ fallback: Reddit API
  │   └─ 中文: 知乎 web_fetch
  │
  ├─ 官方信息（定价/功能/更新）?
  │   ├─ 1st: Firecrawl 抓官网文档站
  │   ├─ fallback: Jina AI Reader 抓具体页面
  │   └─ last: web_search 搜 "site:product.com pricing"
  │
  └─ 视频舆情（深度模式）?
      ├─ 1st: YouTube transcript API
      ├─ 中文: Bilibili API
      └─ 多模态: 火山引擎图搜/视频搜
```

**Fallback 触发条件**：
- 工具调用返回空结果
- 工具调用超时（30s）
- 返回结果与查询目标不相关（LLM 判定）
- 连续 2 次同源查询无有效结果

> **关键决策**：Fallback 不只是调用失败——"搜到了但 LLM 判定不相关"也触发。防止静默失败。

#### 3.4.6 Collector 产出摘要

Collector 产出不仅是 `list[CollectedDataPoint]`，附带摘要供可观测面板展示：

```python
{
    "collected_data": [...],           # Annotated[list, op_add] 自动累加
    "collection_summary": {            # 日志/可观测用，非 State 字段
        "total_data_points": 42,
        "products_covered": {"cursor": 15, "copilot": 14, "windsurf": 13},
        "categories_covered": {"features": 12, "pricing": 10, "users": 8, "market": 12},
        "source_types": {"official": 18, "review": 14, "news": 6, "social": 4},
        "languages": {"zh": 15, "en": 27},
        "stopped_by": "soft_stop",     # "soft_stop" | "max_turns" | "timeout"
        "search_rounds": 18,
        "avg_confidence": 0.87,
        "low_confidence_points": 3,
    }
}
```

答辩时直接展示在 Collector 详情面板——"42 条数据、3 产品全覆盖、18 轮后软停止"。

#### 3.4.7 数据源路由策略

> §3.4.5 定义了按意图的 Fallback 链，本节定义**如何判定意图**和**中英文路由**——Collector 不能靠"感觉"选源。

**意图判定规则**（一次轻量 LLM 调用，不是完整 SubagentExecutor）：

| 查询特征 | 判定为 | 首选用源 |
|---------|--------|---------|
| 含 "定价"/"价格"/"pricing"/"$/月" | 官方信息 | Firecrawl → Jina → web_search |
| 含 "评测"/"review"/"对比"/"vs" | 用户评价 | G2/Product Hunt → Reddit → 知乎 |
| 含 "github"/"star"/"commit" | 技术深度 | GitHub API → web_search |
| 含 "融资"/"funding"/"估值" | 商业信息 | Crunchbase → web_search → Brave |
| 含 "市场份额"/"market share" | 市场数据 | Tavily → Brave → web_search |
| 纯中文查询 | 中文内容 | 火山引擎联网搜索 → 知乎/微博 → Tavily |
| 纯英文查询 | 英文内容 | Tavily → Brave → 火山引擎 |
| 无明确特征 | 通用 | Tavily → Brave → 火山引擎 |

**中英文自动路由**：

每条搜索词独立判定语言 → 各自走对应的 API 链：

```
搜索词生成（§3.4.4）:

  "Cursor pricing 2026"          → 英文 → Tavily → Brave
  "Cursor 定价 2026"              → 中文 → 火山引擎联网搜索
  "Copilot user review reddit"   → 英文 → Reddit API → Tavily
  "Cursor 评测 2026"              → 中文 → 火山引擎 → 知乎
```

中文词走火山引擎（原生优势、中文内容覆盖好），英文词走 Tavily/Brave（英文搜索质量高）。两者不冲突——同一个产品的中文和英文信息互补。

**web_search vs web_fetch 的选择**：

| 场景 | 工具 | 理由 |
|------|------|------|
| 探索性搜索（"Cursor 有什么功能"） | web_search | 需要概览，不是精确页面 |
| 精确提取（"Cursor 定价页面具体价格"） | web_fetch | 需要页面原始内容，转 Markdown |
| 整站爬取（"Cursor 所有文档"） | Firecrawl | 结构化批量抓 |
| URL 已知（"查 cursor.com/pricing"） | Jina AI Reader | 单页 Markdown 转换，比 web_fetch 更干净 |

### 3.5 Analyst 分析规范

> Analyst 从 `collected_data` 生成 `AnalysisResult`。不是"LLM 想到什么分析什么"——按以下固定规则执行。

#### 3.5.1 强制对比维度

| 维度 | 子维度 | 必选？ | 需要的数据 |
|------|--------|-------|-----------|
| **功能** | 核心功能、差异化功能、缺失功能 | ✅ 必选 | category=features 的 DataPoint |
| **定价** | 各 tier 价格、免费版、计费方式 | ✅ 必选 | category=pricing 的 DataPoint |
| **用户** | 目标用户群、满意度、NPS/评分 | ✅ 必选 | category=users 的 DataPoint |
| **市场** | 市场份额、增长趋势、融资/估值 | ⚠ 有数据才做 | category=market 的 DataPoint |
| **技术** | 技术栈、架构、开源/闭源 | ⚠ 有数据才做 | GitHub API 等技术源 |
| **团队** | 创始人、团队规模、招聘动态 | ⚠ 有数据才做 | LinkedIn/Crunchbase 等 |

某必选维度数据量为 0 → 不生成该维度对比（不造假），标注 "⚠ 该维度未采集到足够数据"。

#### 3.5.2 评分规则

`comparison_matrix` 中的 `rating`（1-5）不是 LLM 自由裁量：

| 数据情况 | 评分依据 |
|---------|---------|
| 有定量数据（价格、评分、star 数） | 分位数映射到 1-5。价格低的得高分，延迟低的得高分 |
| 有定性数据（"功能完整"、"用户抱怨延迟"） | LLM 综合判断，必须引用 ≥1 条 `source_data_point_ids` |
| 该维度无数据 | `rating = None`，标注 "无数据" |

```python
def quantile_to_rating(value: float, all_values: list[float],
                       lower_is_better: bool = True) -> int:
    """定量数据 → 1-5 分，有计算依据，非 LLM 幻觉数字"""
    percentile = stats.percentileofscore(all_values, value)
    if lower_is_better:
        percentile = 100 - percentile
    return min(5, max(1, round(percentile / 20)))
```

Reviewer 可回查原始数据和分位数计算是否正确（G6 统计异常检查）。

#### 3.5.3 SWOT 生成约束

每条 SWOT 条目必须满足：

```python
class SWOTItem(BaseModel):
    category: Literal["strength", "weakness", "opportunity", "threat"]
    statement: str          # 一句话陈述
    evidence: str           # 支撑这个陈述的具体数据
    source_data_point_ids: list[str]  # 必须 ≥ 1 条
```

**证据强制规则**：

| SWOT 类型 | 必须引用什么数据 |
|----------|----------------|
| **S**trength | ≥1 条正面评分的 DataPoint |
| **W**eakness | ≥1 条负面评分/用户抱怨的 DataPoint |
| **O**pportunity | ≥1 条外部趋势/市场的 DataPoint |
| **T**hreat | ≥1 条竞品动态/市场变化的 DataPoint |

LLM 不能自由发挥"我觉得他们团队强"——必须说"GitHub star 32K（dp-xxx），社区活跃度 4.2/5（dp-yyy），因此团队对开源社区有强吸引力"。

#### 3.5.4 可视化触发规则

不是每次分析都画所有图。根据数据条件自动选择：

| 数据条件 | 触发的图表 | 用途 |
|---------|-----------|------|
| 所有产品 × 所有维度均有 rating | 雷达图 | 多产品多维对比 |
| 3+ 产品 × 5+ 功能的数据 | 功能热力图 | 功能覆盖矩阵 |
| 有定价 tiers 数据 | 分组柱状图 | 定价层级对比 |
| 有时间序列数据（GitHub star 历史等） | 折线图 | 增长趋势 |
| 有用户评价 + sentiment 字段 | 情感饼图 + 词云 | 用户口碑概览 |
| 有市场份额数据 | 堆叠柱状图 | 市场格局 |
| 有 ≥2 次分析的同一产品数据 | 变更对比图 | 产品演进（P2） |

没有对应数据 → 跳过该图表，不强行画。

#### 3.5.5 Analyst 自检清单

Analyst 完成后内部校验（与 Reviewer 职责不同——Analyst 自检保证"输出结构完整"，Reviewer 审阅保证"数据正确"）：

| # | 检查项 | 不通过时 |
|---|-------|---------|
| A1 | 每个 target_product 在 comparison_matrix 中有 ≥1 个 rating | 标注 "⚠ 某产品数据不足" |
| A2 | 每个 SWOT 条目都有 `source_data_point_ids` | 补引用；补不上 → 删除该条目 |
| A3 | 所有引用 DataPoint 的 source_url 非空 | 回查 DataPoint，写 "⚠ 来源缺失" |
| A4 | 定量评分标注了计算方式（分位数/直接值） | 在 evidence 字段补充 |
| A5 | comparison_matrix.summary 包含数据覆盖率说明 | 补充覆盖率百分比 |

#### 3.5.6 Analyst 与 Reviewer 的职责边界

| 检查 | 谁做 | 目的 | 发现问题的处理 |
|------|------|------|-------------|
| A1-A5 自检 | Analyst | 保证输出结构完整 | 内部修正后产出 |
| G1-G8 审阅（§3.6） | Reviewer | 验证数据正确性 | 生成 ReviewGap 打回 Collector |

#### 3.5.7 竞品分析的三个时间维度

竞品分析天然是"过去→现在→未来"的完整视角。Analyst 的 `AnalysisResult` 已经覆盖了过去（trends）和现在（comparison_matrix + SWOT），唯一缺的是**未来（预测推演）**。

| 时间维 | 做什么 | 数据来源 | Analyst 产出 |
|--------|-------|---------|------------|
| **过去** | 版本演进、历史定价、趋势变化 | Collector（历史数据） | `TrendFinding[]` |
| **现在** | 对比矩阵、SWOT、用户声音 | Collector（当前数据） | `ComparisonMatrix` + `SWOTAnalysis` |
| **未来** | 预测推演、What-if 假设分析 | **不需要 Collector**——在现有数据上做推理 | `ForecastResult`（新增） |

**ForecastResult Schema**：

```python
class ForecastItem(BaseModel):
    dimension: str              # "定价" | "市场份额" | "用户增长" | "功能演进"
    product: str
    current_state: str          # "Cursor Pro = $20/月，免费版有 200K 用户"
    trend_direction: Literal["up", "down", "stable", "uncertain"]
    trend_strength: float       # 0.0-1.0，趋势的确定程度
    forecast_6m: str            # 6 个月预测
    forecast_12m: str           # 12 个月预测
    rationale: str              # 为什么这样预测（基于什么数据）
    confidence: float           # 预测置信度
    source_data_point_ids: list[str]


class ForecastResult(BaseModel):
    """Analyst → Writer，写入 AnalysisResult.forecast"""
    items: list[ForecastItem]
    summary: str                # 预测总结
    disclaimer: str             # "以下预测基于公开数据趋势外推，不构成投资建议"
```

**Why 不走 Collector**：What-if 是"在现有数据上做推理"——数据不动，推理在动。用户说"如果 Cursor 降价到 $10，竞争格局怎么变？"时，系统不需要重新搜索任何东西，直接在已有 `comparison_matrix` 上做假设推演，30 秒出结论。

**What-if 的实际触发路径**：用户在报告交互界面的 What-if 输入框输入假设 → 轻量 LLM 调用生成假设条件 → Writer 将假设条件注入重新生成报告的相关章节。不需要新节点，不需要新 Graph 边。

### 3.6 Reviewer 审阅清单与判定规则 `**[竞赛要求 R5]**`

> 判标 §4 要求"质检 Agent 能识别问题并打回采集/分析 Agent 重做"。审阅不是 LLM 自由发挥——Reviewer 按以下固定清单逐项检查，每条判定必须附带计算依据或来源证据。

#### 3.6.1 四类 Gap 判定规则

| # | 检查项 | 判定方法 | 判定依据 | 触发条件 | Gap 类型 | Gap 生成内容 |
|---|-------|---------|---------|---------|---------|------------|
| G1 | **来源可达性** | 计算验证 | `requests.head(url, timeout=10)` → status ≥ 400 | URL 返回 4xx/5xx | `fact_error` | `{claim: "从 {url} 获取的数据", evidence: "HTTP {status}", correction: "寻找替代来源"}` |
| G2 | **多源一致性** | 计算验证 + LLM | pandas `groupby("label")` → `nunique("value") > 1` | 同一 label 在不同来源的值差异 > 5% | `source_conflict` | `{conflict: {label, values_by_source, max_diff}, suggested_remedy: "定向搜索权威来源裁决"}` |
| G3 | **时效性** | 计算验证 | `now - collected_at > 180 days` | 数据超过 180 天 | `outdated` | `{current_value, age_days, target_collect: "搜索 {label} 最新数据"}` |
| G4 | **维度覆盖** | 计算验证 | 检查 `comparison_matrix` 中每个维度是否有 ≥1 条数据 | 某维度 0 条数据 | `missing_data` | `{dimension, expected_products, target_collect: "搜索 {dimension} 相关数据"}` |
| G5 | **来源多样性** | 计算验证 | `groupby("source_type")` — 检查是否有 ≥2 种来源类型 | 所有数据来自同一 source_type | `missing_data` | `{current_type, suggested_types: ["review", "news"], target_collect: "补充用户评价/媒体报道来源"}` |
| G6 | **统计异常** | 计算验证 | `scipy.stats.zscore(values)` → |z| > 3 | 某数值偏离总体 3σ 以上 | `fact_error` | `{outlier: {value, zscore, compared_to}, action: "验证异常值是否为采集错误"}` |
| G7 | **语义矛盾** | LLM 推理 | 同一产品/维度的两条文字描述语义相反 | LLM 判定语义冲突 | `source_conflict` | `{conflicting_claims: [text_a, text_b, source_a, source_b], suggested_remedy: "搜索更多来源判决"}` |
| G8 | **置信度偏低** | 计算验证 | `confidence < 0.5` 的数据点 | LLM 或 API 返回的低置信度标记 | `missing_data` | `{low_confidence_points, target_collect: "重新搜索高置信度来源"}` |

#### 3.6.2 判定优先级

Gap 不是平级的——`fact_error` 最严重，需要立即修正：

| 优先级 | Gap 类型 | 处理策略 |
|-------|---------|---------|
| P0 | `fact_error` | 该数据点**不进入 Analyst**，立即打回 Collector 补采 |
| P1 | `source_conflict` | 该数据点标注 "⚠ 来源冲突" 进入 Analyst，同时打回补采裁决来源 |
| P1 | `outdated` | 保留旧数据但标注 "⚠ 数据可能过时（X天前）"，打回补采最新数据 |
| P2 | `missing_data` | 不阻塞，标注缺失维度，打回补采。≥2 轮仍缺失则写入 `unresolved_issues` |

#### 3.6.3 审阅输出结构

Reviewer 完成后输出到 State：

```python
{
    "review_verdict": {
        "passed": False,            # 无 P0 gap 且 review_round < 2
        "round": 1,
        "gaps": [...],
        "fact_errors": [...],
        "quality_summary": {...},
        "reviewer_notes": "..."
    },
    "review_round": 1,
    "gaps": [
        {
            "gap_id": "gap-001",
            "type": "source_conflict",     # G1-G8 之一
            "check_method": "multi_source_consistency",  # 判定方法
            "description": "Copilot Business 定价：官网 $19 vs G2 $24.67，差异 29.8%",
            "evidence": "HEAD github.com → 200 OK; HEAD g2.com → 200 OK; 两来源均可达",
            "target_collect_task": "搜索 Copilot 官方定价页面或第三方权威评测验证实际价格",
            "severity": "major",           # critical | major | minor
            "related_data_point_ids": ["dp-015", "dp-028"],
        }
    ],
    "fact_errors": [...],
    "gap_coverage_improvement": 0.0,  # 补采前无对比基线
}
```

#### 3.6.4 为什么不需要 Critic+Judge 分离

PA-Agent-DF 用 Critic（提出质疑）+ Meta-Judge（裁决）是因为当时依靠 LLM 辩论做验证，存在"自己质疑自己裁决"的结构问题。

但 CI-Agent 的 Reviewer **主要依赖计算验证**（G1-G6、G8 共 7 项是计算判定，只有 G7 是 LLM 推理），计算工具的输出是客观的——URL 400 就是 400，zscore > 3 就是 > 3。不需要另一个 LLM 来"裁决"计算工具的结果。

这与判标 §4 25% 的"上下文管理、错误恢复、幻觉抑制有明确策略（自一致性校验、引用强制）"**直接对应**——我们的"自一致性"不是 LLM 自我审查，而是 Python 计算工具的硬验证。

### 3.7 Writer 报告规范

> Writer 输出不再是 `.md` 文件字符串——而是 `ReportData` 结构化 JSON，前端原生渲染交互报告。Markdown/PDF/PPTX 只是导出格式。

#### 3.7.1 报告从静态文件 → 前端原生交互

```
Writer 产出 ReportData (结构化 JSON)
    │
    ├─→ 前端交互报告（P0 基准）
    │     • hover 来源 [n] → 弹出 source card
    │     • 选中段落 → 输入指令 → 局部重做
    │     • 切换 PM/创业者视角（同一份 ReportData，前端重渲染）
    │     • 内嵌 What-if 输入框 → 实时推演
    │     • DAG 面板旁边即为报告面板（§7.1 双面板布局）
    │
    ├─→ 导出 Markdown    （本地保存）
    ├─→ 导出 PDF         （打印/分享）
    ├─→ 导出 PPTX        （DF 已有 ppt-generation Skill）
    └─→ 飞书 Doc 推送    （P1，lark-cli docs +create）
```

#### 3.7.2 ReportData Schema

```python
class ReportSection(BaseModel):
    id: str                          # "sec-executive-summary" / "sec-comparison" / ...
    title: str
    content: str                     # Markdown 文本（前端渲染引擎解析）
    content_type: str                # "text" | "table" | "chart" | "what-if-form"
    source_ids: list[str]            # 本章节引用的 DataPoint ID
    chart_path: str | None           # content_type="chart" 时
    subsections: list["ReportSection"] | None


class ReportData(BaseModel):
    """Writer → State.report_data，替代原来的 final_report + pm_report + entrepreneur_report"""
    persona: str                     # "pm" | "entrepreneur"
    title: str
    generated_at: str
    products: list[str]
    sections: list[ReportSection]
    traceability_map: dict           # source_id → {url, timestamp, confidence_level}
    quality_summary: QualitySummary  # 来自 ReviewVerdict（§3.13.4）
    forecast: ForecastResult | None  # 来自 AnalysisResult（§3.5.7）
    metrics: dict                    # coverage / improvement_ratio / trace_completeness
```

#### 3.7.3 报告固定章节结构

| 章节 (section id) | 必选？ | content_type | 条件 |
|-------------------|-------|-------------|------|
| `sec-executive-summary` | ✅ | text | — |
| `sec-comparison-matrix` | ✅ | table | — |
| `sec-swot` | ✅ | text | — |
| `sec-trends` | ⚠ | text + chart | 有 TrendFinding |
| `sec-user-voice` | ⚠ | text + chart | 有 sentiment 数据 |
| `sec-forecast` | ⚠ | text + what-if-form | 有 ForecastResult |
| `sec-recommendations` | ✅ | text | — |
| `sec-sources` | ✅ | table | — |
| `appendix-quality` | ✅ | text | — |
| `appendix-charts` | ⚠ | chart | 有图表生成 |

#### 3.7.4 PM 视角 vs 创业者视角

同一份数据，两版报告的差异在**措辞、侧重点、建议类型**。Writer 的 system prompt 注入 `PERSONA_PROFILE`——不是两套 prompt，而是一套 prompt + 一个 persona 参数：

```
PERSONA = "pm":
  执行摘要第一句: "从产品功能角度看..."
  建议: 功能优先级排序、差异化方向
  对比矩阵侧重: 功能维度 > 定价维度

PERSONA = "entrepreneur":
  执行摘要第一句: "从市场机会角度看..."
  建议: 细分市场选择、商业模式、进入时机
  对比矩阵侧重: 定价维度 > 功能维度
```

| 维度 | PM 视角 | 创业者视角 |
|------|---------|-----------|
| **核心问题** | "该做什么功能？差异化在哪？" | "市场有机会吗？能活下去吗？" |
| **对比矩阵侧重** | 功能维度为主，体验/UX 细粒度对比 | 定价维度为主，商业模式/市场格局 |
| **SWOT 层级** | 产品级（功能/UX/定价/用户） | 战略级（市场/团队/资本/壁垒） |
| **建议类型** | 功能优先级排序、差异化方向 | 细分市场选择、商业模式建议、进入时机 |
| **What-if 侧重** | "如果竞品加了 X 功能，我们要跟进吗？" | "如果我选 Y 细分市场，竞争压力多大？" |
| **来源强调** | 用户评价、功能对比测评 | 市场份额、融资数据、财务信息 |

#### 3.7.5 来源标注格式

每条事实性结论后跟 `[n]` 上标，前端 hover 弹出 source card（URL、抓取时间、置信度、交叉验证状态）：

```markdown
Cursor 的 Tab 补全准确率在多个独立评测中被认为优于 Copilot[1][3]，
但在多文件重构场景下 Copilot 的上下文理解更完整[2]。
```

**质量信号 → 标注文案映射**：

| QualitySummary 字段 | 前端渲染 |
|-------------------|---------|
| multi_source ≥ 2 | ✅ 多源交叉验证 |
| single_source = 1 | ⚠ 单源，未经交叉验证 |
| fact_errors > 0 | ❌ 发现数据错误 |
| reviewer_round ≥ 2 | ⚠ 反馈 2 轮后仍未完全解决 |

#### 3.7.6 Writer 自检清单

| # | 检查项 | 不通过时 |
|---|-------|---------|
| W1 | 每个 target_product 在报告中至少出现一次 | 补充 |
| W2 | 每条事实性结论后都有 `[n]` 来源标号 | 补引用 |
| W3 | traceability_map 的 key 和报告中的 `[n]` 一一对应 | 对齐 |
| W4 | 来源表中每条标注对应正确的 quality 标签 | 修正标签 |
| W5 | 所选 persona 的侧重点正确 | 调整措辞 |

### 3.8 DAG 工作流

```
普通模式 (始终执行):
  Collector → Analyst → Reviewer → Writer → HITL Gate
      ↑          ↑          │            │
      │          │          │ ❌          ├─ approve → END (输出普通报告)
      └──────────┴── gap ───┘            ├─ reanalyze → Analyst
              (最多 2 轮)                 ├─ rewrite → Writer
                                          └─ replan → Collector

深度模式 (deep_mode=true 时, 紧随普通模式):
  普通报告 (state 中所有累积数据) → Deep Collector → Deep Analyst → Deep Reviewer
                                          ↑                │              │
                                          └── gap ─────────┘              │
                                               (轮数放宽)           Deep Writer
                                                                        │
                                                                   Deep HITL (可选)
                                                                        │
                                                                   Feishu 交付
```

### 3.9 CompetitionState 设计

```python
class CompetitionState(AgentState):
    # ── 用户输入 ──
    user_request: str
    target_products: list[str]          # 要对比的产品
    persona: str                        # "pm" | "entrepreneur" | "both"
    deep_mode: bool                     # False=仅普通模式, True=普通+深度

    # ── Collector 输出（普通模式累积，深度模式增量追加）──
    collected_data: Annotated[list[CollectedDataPoint], op_add]
    knowledge_gaps: list[ReviewGap]     # Reviewer 发现的知识缺口 → 深度模式 Collector 目标

    # ── Analyst 输出 ── `**[竞赛要求 R4]**`
    analysis_result: AnalysisResult | None  # comparison_matrix + swot + trends + visualization_paths

    # ── Reviewer 输出 ──
    review_verdict: ReviewVerdict | None    # passed + gaps + fact_errors + quality_summary
    review_round: int                       # 当前反馈轮次（路由判断用，保留顶层）
    gap_coverage_improvement: float | None  # 反馈闭环改善度量：本轮填补的 gap 比例

    # ── Writer 输出（普通模式）── `**[竞赛要求 R7]**`
    report_data: ReportData | None          # 前端原生交互报告（替代 final_report/pm_report/entrepreneur_report）
    traceability_map: dict                  # claim_id → {url, fetch_timestamp, confidence}
    review_package: ReviewPackage | None    # Writer → HITL 审批简报

    # ── 深度模式专用 ──
    deep_collected_data: Annotated[list[CollectedDataPoint], op_add]
    deep_review_round: int                  # 深度模式 Reviewer 轮数
    deep_report: str                        # 深度模式最终报告 (HTML)
    deep_feishu_url: str | None             # 飞书文档 URL

    # ── HITL ──
    hitl_decision: HitlDecision | None      # action + comment + target_focus + timestamp
    deep_hitl_decision: HitlDecision | None

    # ── 异常 ──
    error: str | None
```

### 3.10 竞品知识 Schema（Pydantic 强制校验）

**Schema 1 — 功能树**:
```python
class FeatureNode(BaseModel):
    name: str
    description: str
    supported: bool
    differentiation_score: int  # 1-5, 差异化程度

class FeatureCategory(BaseModel):
    category_name: str          # 如 "代码补全"、"协作功能"、"安全合规"
    features: list[FeatureNode]

class FeatureTree(BaseModel):
    product_name: str
    categories: list[FeatureCategory]
```

**Schema 2 — 定价模型**:
```python
class PricingTier(BaseModel):
    tier_name: str              # "免费版" / "专业版" / "企业版"
    price: float
    currency: str
    billing_cycle: str          # "monthly" | "yearly" | "one-time"
    features_included: list[str]
    target_segment: str         # "个人开发者" / "小团队" / "企业"

class PricingModel(BaseModel):
    product_name: str
    tiers: list[PricingTier]
    free_tier_available: bool
    pricing_strategy: str       # "freemium" / "subscription" / "usage-based"
```

**Schema 3 — 用户画像**:
```python
class UserSegment(BaseModel):
    segment_name: str           # "专业开发者" / "技术管理者" / "学生"
    primary_needs: list[str]
    pain_points: list[str]
    why_choose: list[str]       # 为什么选这个产品
    why_leave: list[str]        # 为什么离开/不选
    estimated_share: float      # 估计占比

class UserPersona(BaseModel):
    product_name: str
    primary_segments: list[UserSegment]
```

### 3.11 Schema 强制校验链 `**[竞赛要求 R3, R8]**`

> 评审明确要求"输出严格符合预定义 Schema，字段完整、格式一致"。我们不仅定义 Schema，更在每个 Agent 输出边界做强制校验。

**校验流程**：

```
Agent LLM 输出 (JSON string)
  │
  ├─ 1. json.loads() 解析
  │     └─ 失败 → 自动重试 (返回 ValidationError 详情，最多 2 次)
  │
  ├─ 2. Pydantic model_validate()
  │     └─ Collector 输出 → [CollectedDataPoint].model_validate()
  │     └─ Analyst 输出 → FeatureTree/PricingModel/UserPersona.model_validate()
  │     └─ Writer 输出 → 检查每条结论是否关联 traceability_map 条目
  │
  ├─ 3. 校验通过 → 写入 State，进入下一节点
  │
  └─ 4. 2 次重试仍失败 → 标记 error 字段
        → 路由到 error_handler
        → 该数据点标注 "⚠ Schema 校验失败，需人工确认"
```

**实现要点**：
- 校验逻辑封装在 `competition/schema.py` 的 `validate_agent_output()` 函数中
- 每次校验失败时记录日志（时间、Agent、Schema 类型、原始输出、校验错误）
- Schema 校验日志作为可观测面板的一部分展示

### 3.12 路由逻辑（普通模式 + 深度模式流水线）

```python
# competition/router.py

def route_after_collector(state: CompetitionState) -> str:
    if state.get("error"):
        return "error_handler"
    return "analyst"

def route_after_analyst(state: CompetitionState) -> str:
    """普通模式: 始终进入 Reviewer（不跳过）"""
    if state.get("error"):
        return "error_handler"
    return "reviewer"

def route_after_reviewer(state: CompetitionState) -> str:
    """校验通过 → Writer / 有 gap → 打回 Collector / 超轮 → 带着问题进 Writer。"""
    verdict: ReviewVerdict | None = state.get("review_verdict")
    if verdict and verdict.passed:
        return "writer"
    review_round = state.get("review_round", 0)
    if review_round >= 2:
        return "writer"           # 超过上限 → 标注不确定性后继续
    return "collector"            # 打回重新采集

def route_after_writer(state: CompetitionState) -> str:
    """普通报告完成 → 进入 HITL。"""
    if state.get("error"):
        return "error_handler"
    return "hitl_gate"

def route_after_hitl(state: CompetitionState) -> str:
    """HITL 决策路由（对应 §3.11.7 HitlDecision.action）。"""
    decision: HitlDecision | None = state.get("hitl_decision")
    if not decision:
        return "__end__"
    action = decision.action
    if action == "approve":
        return "deep_collector" if state.get("deep_mode") else "__end__"
    elif action == "replan":
        return "collector"
    elif action == "reanalyze":
        return "analyst"
    elif action == "rewrite":
        return "writer"
    return "__end__"

# ── 深度模式路由 ──

def route_after_deep_collector(state: CompetitionState) -> str:
    if state.get("error"):
        return "deep_error_handler"
    return "deep_analyst"

def route_after_deep_analyst(state: CompetitionState) -> str:
    if state.get("error"):
        return "deep_error_handler"
    return "deep_reviewer"

def route_after_deep_reviewer(state: CompetitionState) -> str:
    """深度模式 Review：轮数放宽，但仍需收敛。"""
    if state.get("deep_review_passed"):
        return "deep_writer"
    deep_round = state.get("deep_review_round", 0)
    if deep_round >= 5:          # 深度模式放宽到 5 轮
        return "deep_writer"     # 带着未解决问题继续
    return "deep_collector"       # 继续增量采集

def route_after_deep_writer(state: CompetitionState) -> str:
    """深度报告完成 → 可选二次 HITL。"""
    return "deep_hitl"  # 或直接 feishu_delivery
```

```python
# competition/graph.py — 普通+深度双段 LangGraph 图构建

def build_competition_graph(checkpointer=None) -> CompiledStateGraph:
    builder = StateGraph(CompetitionState)

    # ── 普通模式节点（始终运行）──
    builder.add_node("collector", collector_node)
    builder.add_node("analyst", analyst_node)
    builder.add_node("reviewer", reviewer_node)
    builder.add_node("writer", writer_node)
    builder.add_node("hitl_gate", hitl_gate_node)

    # ── 深度模式节点（仅 deep_mode=true 时触发）──
    builder.add_node("deep_collector", deep_collector_node)
    builder.add_node("deep_analyst", deep_analyst_node)
    builder.add_node("deep_reviewer", deep_reviewer_node)
    builder.add_node("deep_writer", deep_writer_node)
    builder.add_node("deep_hitl", deep_hitl_node)
    builder.add_node("feishu_delivery", feishu_delivery_node)

    # ── 错误处理 ──
    builder.add_node("error_handler", error_handler_node)
    builder.add_node("deep_error_handler", deep_error_handler_node)

    # ── 普通模式边 ──
    builder.set_entry_point("collector")
    builder.add_edge("collector", "analyst")
    builder.add_edge("analyst", "reviewer")
    builder.add_conditional_edges("reviewer", route_after_reviewer, {
        "writer": "writer",
        "collector": "collector",
        "error_handler": "error_handler",
    })
    builder.add_edge("writer", "hitl_gate")
    builder.add_conditional_edges("hitl_gate", route_after_hitl, {
        "__end__": END,
        "analyst": "analyst",
        "collector": "collector",
        "deep_collector": "deep_collector",   # ← 深度模式入口
    })

    # ── 深度模式边 ──
    builder.add_edge("deep_collector", "deep_analyst")
    builder.add_edge("deep_analyst", "deep_reviewer")
    builder.add_conditional_edges("deep_reviewer", route_after_deep_reviewer, {
        "deep_writer": "deep_writer",
        "deep_collector": "deep_collector",
        "deep_error_handler": "deep_error_handler",
    })
    builder.add_edge("deep_writer", "deep_hitl")
    builder.add_edge("deep_hitl", "feishu_delivery")
    builder.add_edge("feishu_delivery", END)
    builder.add_edge("error_handler", END)
    builder.add_edge("deep_error_handler", END)

    return builder.compile(checkpointer=checkpointer)
```

#### 3.12.PLACEHOLDER 反馈闭环改善追踪 `**[竞赛要求 R5, R6]**`

> 判标 §4 明确要求"反馈闭环真实可触发，重做后输出有改善（非伪闭环）"。我们不仅实现打回，更量化改善。

**改善度量机制**：

```python
# Reviewer 节点在打回前记录当前 gaps
gaps_before = state.get("gaps", [])

# Collector 补采后，Reviewer 再次校验时计算改善
def measure_improvement(gaps_before: list, gaps_after: list) -> dict:
    resolved = [g for g in gaps_before if g["gap_id"] not in {g2["gap_id"] for g2 in gaps_after}]
    partial = [g for g in gaps_after if g.get("severity") != "critical"]  # 降级视为部分改善
    return {
        "gaps_before_count": len(gaps_before),
        "gaps_after_count": len(gaps_after),
        "resolved_count": len(resolved),
        "improvement_ratio": len(resolved) / max(len(gaps_before), 1),
        "partial_improvements": len(partial),
    }
```

**答辩展示**：在 DAG 图上，反馈回环边标注改善数据，如 "🔁 Round 1 → 2 gaps → Round 2 → 0 gaps (改善率 100%)"。如果改善率为 0（伪闭环），可从日志看出 LLM 没有真正生成新搜索词。

### 3.13 Agent 间结构化通信协议 `**[竞赛要求 R4]**`

> 判标 §4 35% 明确要求"Agent 间采用结构化消息传递（function calling / 标准 Schema），非纯自然语言对话"。
> 以下 6 条边全部定义为 Pydantic 模型，每条消息可被日志捕获、可被前端渲染。

#### 3.13.1 通信契约总览

```
Collector ──①──→ Analyst ──②──→ Reviewer ──③──→ Writer ──④──→ HITL
    ↑                    ↑                                    │
    └──── ⑤ gap ────────┘                   ⑥ replan/reanalyze/rewrite
```

| 边 | 发送方 | 接收方 | Schema | State 字段 | 作用 |
|---|-------|-------|--------|-----------|------|
| ① | Collector | Analyst | `CollectedDataPoint` | `collected_data` | 结构化采集结果 |
| ② | Analyst | Reviewer | `AnalysisResult` | `analysis_result` | 可验证的分析输出 |
| ③ | Reviewer | Writer | `ReviewVerdict` | `review_verdict` | 数据质量报告 |
| ④ | Writer | HITL Gate | `ReviewPackage` | `review_package` | 审批简报 |
| ⑤ | Reviewer | Collector | `ReviewGap` | `gaps` | 定向补采指令 |
| ⑥ | HITL Gate | 目标节点 | `HitlDecision` | `hitl_decision` | 精准回退指令 |

#### 3.13.2 边 ①：Collector → Analyst

```python
class CollectedDataPoint(BaseModel):
    id: str
    product: str
    category: str               # "features" | "pricing" | "users" | "market"
    label: str
    value: str | float
    confidence: float           # 0.0-1.0
    source_url: str
    source_type: str            # "official" | "review" | "news" | "interview"
    collected_at: str           # ISO 8601
```

#### 3.13.3 边 ②：Analyst → Reviewer

每条分析结论必须带 `source_data_point_ids`，让 Reviewer 能从结论反向追溯到原始数据点。没有这个字段，Reviewer 无法做计算验证。

```python
class ComparisonCell(BaseModel):
    product: str
    dimension: str              # 如 "代码补全"、"定价"、"用户群"
    rating: Literal[1, 2, 3, 4, 5] | None  # None = 无数据
    evidence: str               # 支撑这个评分的具体事实
    source_data_point_ids: list[str]


class ComparisonMatrix(BaseModel):
    products: list[str]
    dimensions: list[str]
    cells: list[ComparisonCell]
    summary: str                # 一句话概述


class SWOTItem(BaseModel):
    category: Literal["strength", "weakness", "opportunity", "threat"]
    statement: str
    evidence: str
    source_data_point_ids: list[str]


class SWOTAnalysis(BaseModel):
    product: str
    items: list[SWOTItem]


class TrendFinding(BaseModel):
    dimension: str              # "市场份额" | "定价趋势" | "功能演进"
    direction: Literal["up", "down", "stable", "unclear"]
    confidence: float
    evidence: str
    source_data_point_ids: list[str]


class AnalysisResult(BaseModel):
    """Analyst → Reviewer，写入 State.analysis_result"""
    comparison_matrix: ComparisonMatrix
    swot: dict[str, SWOTAnalysis]       # key = product name
    trends: list[TrendFinding]
    forecast: ForecastResult | None     # §3.5.7 预测推演（有趋势数据才生成）
    visualization_paths: list[str]       # Sandbox 中图表文件路径
```

#### 3.13.4 边 ③：Reviewer → Writer

Writer 生成报告时，措辞应该反映数据质量。多源验证过的写"多方来源显示"，单源的写"据 X 来源称"——这些信息在 QualitySummary 里。

```python
class QualitySummary(BaseModel):
    """数据质量总览"""
    total_data_points: int
    verified_count: int             # 通过所有检查的数据点数
    multi_source_count: int         # 2+ 独立来源
    single_source_count: int        # 仅单源，标注 "⚠ 单源"
    fact_errors_count: int
    unresolved_gaps: list[str]      # 仍未解决的 gap 描述
    overall_quality_score: float    # 0.0-1.0
    improvement_ratio: float | None # 反馈改善率


class ReviewVerdict(BaseModel):
    """Reviewer → Writer，写入 State.review_verdict"""
    passed: bool
    round: int
    gaps: list[ReviewGap]
    fact_errors: list[dict]         # {claim, evidence, correction}
    quality_summary: QualitySummary
    reviewer_notes: str             # 给 Writer 的一句话
```

#### 3.13.5 边 ④：Writer → HITL Gate

驱动飞书审批卡片的内容渲染。卡片的 UI 就是 `ReviewPackage` 的可视化呈现。

```python
class DataStats(BaseModel):
    total_data_points: int
    products_covered: dict[str, int]    # {"cursor": 15, "copilot": 14}
    categories_covered: dict[str, int]  # {"features": 12, "pricing": 10}
    source_types: dict[str, int]        # {"official": 18, "review": 14}


class ReviewPackage(BaseModel):
    """Writer → HITL Gate，写入 State.review_package"""
    executive_summary: str              # 500 字以内
    key_findings: list[str]             # 3-5 条
    data_stats: DataStats
    quality_summary: QualitySummary     # 从 ReviewVerdict 透传
    unresolved_issues: list[str]
    recommendations: list[str]          # 给用户的建议（approve? / replan? / reanalyze? / rewrite?）
    pm_report_preview: str              # PM 视角报告前 500 字
    entrepreneur_report_preview: str    # 创业者视角报告前 500 字
```

#### 3.13.6 边 ⑤：Reviewer → Collector（打回）

```python
class ReviewGap(BaseModel):
    gap_id: str
    type: str                   # "missing_data" | "fact_error" | "source_conflict" | "outdated"
    target_collect_task: str    # 具体的补采任务描述
    severity: str               # "critical" | "major" | "minor"
    related_data_point_ids: list[str]
```

#### 3.13.7 边 ⑥：HITL Gate → 目标节点

用户说"重写 SWOT 部分"时，Writer 不应该全文重写。`target_focus` 让目标节点聚焦。

```python
class HitlDecision(BaseModel):
    """HITL Gate → 目标节点，写入 State.hitl_decision"""
    action: Literal["approve", "replan", "reanalyze", "rewrite"]
    comment: str | None             # 用户自然语言反馈
    target_focus: list[str] | None  # reanalyze: 关注的维度；rewrite: 修改的章节
    timestamp: str                  # ISO 8601
```

#### 3.13.8 CompetitionState 对应更新

新增 4 个强类型字段替代原有松散 dict：

```python
# §3.7 CompetitionState 中：
# 旧：comparison_matrix: dict, swot: dict, trends: list[dict]
# 新：
analysis_result: AnalysisResult | None       # 替代 comparison_matrix + swot + trends
review_verdict: ReviewVerdict | None         # 替代 review_passed + gaps 散落字段
review_package: ReviewPackage | None         # Writer → HITL
hitl_decision: HitlDecision | None           # HITL → 目标节点
```

---

### 3.14 数据持久化架构

> 以下分析"整个系统用了哪些存储层"以及每层的职责边界。核心原则：**DF 基座层处理 Agent 基础设施的持久化（零工作量），业务层只在跨 run 有增量价值的点建表（三张）。**

#### 3.14.1 全项目存储总览

```
┌─────────────────────────────────────────────────────────┐
│ DF 基座层（零工作量，import 即用）                         │
├─────────────────────────────────────────────────────────┤
│ SqliteSaver                                             │
│   ├─ checkpoints 表     LangGraph 每次节点执行后自动写入   │
│   │                     用途：崩溃恢复 / 中断续跑 / 执行回放│
│   └─ checkpoint_writes  用途：pending writes 追踪         │
│                                                         │
│ Sandbox 文件系统（per-thread 隔离目录）                    │
│   用途：图表 PNG / 报告 MD & HTML / 临时下载文件           │
│   生命周期：thread 结束后保留，通过路径引用                  │
│                                                         │
│ AgentState.messages（内存，SubagentExecutor 管理）         │
│   用途：每个 Agent 内部的 LLM 对话历史，上下文窗口内          │
│                                                         │
│ config.yaml + deerflow.config                            │
│   用途：模型配置 / workflow 定义 / 飞书 App ID / Token     │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ 业务层（三张表，扩展在 SqliteSaver 同一个 SQLite 文件中）    │
├─────────────────────────────────────────────────────────┤
│ source_credibility      跨 run 动态演化的来源可信度        │
│   读：Collector 启动时   写：Reviewer 验证后                │
│   SELECT score WHERE source_domain = ?                   │
│                                                         │
│ product_baseline        竞品数据基线（变更检测用）          │
│   读：Collector 启动时   写：Writer 完成后                  │
│   ⚠ 是"上次是 X，这次验证是否变了"，不是缓存在不搜索         │
│                                                         │
│ analysis_history        分析历史索引                      │
│   读：用户查历史时        写：HITL approve 后               │
│   一条 SQL 找到"我上个月分析 Cursor 的报告"                 │
└─────────────────────────────────────────────────────────┘
```

> **关键认知**：这三张表不是系统运行的必需品——去掉它们，Collector → Analyst → Reviewer → Writer → HITL 照样跑通，因为 State 在内存中流转，Checkpointer 在图画完后已持久化。三张表的价值是**跨 run 的增量智能**——越用越准的来源可信度、自动感知的变更检测、可回溯的分析历史。

#### 3.14.2 source_credibility 表 — 来源可信度动态演化

```sql
CREATE TABLE IF NOT EXISTS source_credibility (
    source_domain TEXT PRIMARY KEY,     -- "g2.com" / "cursor.com" / "reddit.com"
    score REAL NOT NULL DEFAULT 0.50,   -- 0.0-1.0，新来源默认 0.50（中性）
    verification_count INTEGER DEFAULT 0,
    last_verified_at TEXT,
    last_verdict TEXT                   -- "verified" | "conflict" | "error" | "outdated"
);
```

**演化算法**（Reviewer 每次验证后调用）：

```python
def update_credibility(domain: str, verdict: str) -> float:
    adjustments = {
        "verified": +0.05,    # 准确 → 涨
        "conflict": -0.05,    # 与其他源矛盾 → 扣
        "error":    -0.15,    # 数据错误 → 重扣
        "outdated": -0.02,    # 过时 → 轻扣
    }
    current = get_score(domain)  # 默认 0.50
    delta = adjustments.get(verdict, 0)
    return clamp(current + delta, 0.0, 1.0)
```

**Collector 如何使用**：在 §3.4.5 来源优先级之上加权——高可信源（>0.80）优先，低可信源（<0.30）降级或跳过。

**答辩价值**：演示中展示 `g2.com` 的分数从 0.50→0.70→0.92 的演化曲线——"系统不是每次从零开始判断来源，而是越用越准"。

#### 3.14.3 product_baseline 表 — 竞品变更检测基线

> ⚠ **不是缓存**。不是"上次搜过了这次跳过"——那会导致漏掉竞品的真实变更。而是"上次是 X，这次定向验证是否变成 Y"。

```sql
CREATE TABLE IF NOT EXISTS product_baseline (
    product_name TEXT,
    attribute TEXT,            -- "pricing_pro" / "latest_version" / "key_feature_xxx"
    value TEXT,                -- "$20" / "0.48" / "AI code completion"
    source_url TEXT,
    confidence REAL,
    recorded_at TEXT,          -- 首次记录时间
    updated_at TEXT,           -- 最后确认时间
    PRIMARY KEY (product_name, attribute)
);
```

**Collector 如何使用**：

```
第一次分析 Cursor（无 baseline）:
  → 8 轮搜索 → Cursor Pro = $20 → 入库 product_baseline

第二次分析 Cursor（3 天后，有 baseline）:
  → 读 baseline: "上次 Cursor Pro = $20 (3 天前，source: cursor.com/pricing)"
  → 不是跳过，而是定向 HEAD cursor.com/pricing → 发现文案变成了 "$30/月"
  → CollectedDataPoint 标注:
      "⚠ Cursor Pro: was $20 (May 23), now $30 (May 26) — 提价 50%，source: cursor.com/pricing"
  → Reviewer 看到 was/now → 触发变更标记
```

**答辩价值**："系统不仅知道 Cursor 卖 $30，还知道它上次分析时卖 $20，变化发生在过去 3 天内"——这是 §5.3 竞品变更检测的技术底座。

#### 3.14.4 analysis_history 表 — 分析历史索引

```sql
CREATE TABLE IF NOT EXISTS analysis_history (
    thread_id TEXT PRIMARY KEY,
    user_id TEXT DEFAULT "default",
    query TEXT,
    products TEXT,             -- JSON array: ["cursor", "copilot", "windsurf"]
    persona TEXT,
    deep_mode INTEGER DEFAULT 0,
    created_at TEXT,
    key_findings TEXT,         -- JSON: 3-5 条关键发现
    report_path TEXT,          -- Sandbox 中报告文件路径
    metrics TEXT               -- JSON: {coverage, cross_validation_rate, improvement_ratio, ...}
);
```

**使用场景**：
- 用户问"对比我 5 月 15 日的分析"→ `SELECT * FROM analysis_history WHERE created_at < ?` → 读 history report → diff
- §5.6 竞品分析历史对比功能的数据基础
- 答辩面板展示"历史分析时间线"

#### 3.14.5 不需要建表的部分（及原因）

| 候选 | 判断 | 原因 |
|------|------|------|
| user_preferences | ❌ | Demo 是单用户，config.yaml competition 段即可 |
| 竞品数据库 | ❌ | 产品名是用户输入的参数，不预置 |
| 报告全文存储 | ❌ | Sandbox 文件系统存文件，表里只存路径 |
| Agent 执行日志 | ❌ | DF Checkpointer + §7 可观测面板从 State 实时读 |
| 搜索缓存 | ❌ | 危险——缓存会漏掉真实变更，product_baseline 是基线不是缓存 |

#### 3.14.6 三张表的关系定位

```
source_credibility ──→ quality（质量维度）
    越用越准

product_baseline   ──→ freshness（时效维度）
    自动感知变更

analysis_history   ──→ reference（回溯维度）
    可比较可复盘
```

> **共同价值**：使系统从"每次独立的分析工具"升级为"越用越聪明的分析助手"。

---

### 3.15 工程质量保障机制 `**[竞赛要求 R12, R13, R17, R18, R15]**`

> 判标 §4（25% 技术深度与工程完整度 + 10% 合规）明确要求：幻觉抑制策略、超时重试/降级、采集合规、数据脱敏、可量化业务指标。本节逐项落实。

#### 3.15.1 幻觉抑制三策略 `**[竞赛要求 R12]**`

| 策略 | 实现 | 触发条件 |
|------|------|---------|
| **引用强制** | 每个 `CollectedDataPoint` 必须包含非空 `source_url` 字段；Reviewer 校验时检查每条声明是否有活跃 URL（HEAD 请求验证可达性）；无来源声明标记 `confidence=0.0`，不进入 Analyst | 所有 Agent 输出 |
| **自一致性校验** | 同一数据点从 ≥2 个独立来源交叉验证；来源矛盾时标记 `source_conflict`；单源数据点标注 `⚠ 单源，未经交叉验证` | Reviewer 节点 |
| **超长上下文分片** | 当搜索结果 >50 条时，Collector 分批处理（每批 20 条）；Analyst 分批分析后合并；State 中用 `Annotated[list, op_add]` 自动累加 | Collector + Analyst |

**垃圾引用检测**（额外防御）：Reviewer 检查 source_url 域名是否在已知低质量源列表中（如内容农场、SEO 垃圾站），命中则自动降级 confidence。

#### 3.15.2 采集合规 `**[竞赛要求 R17]**`

> 判标 §4 10% 明确要求"遵守目标站点 robots.txt 与服务条款，对外部数据来源有明确授权或公开声明"。

| 机制 | 实现 |
|------|------|
| **robots.txt 预检** | Collector 发起 `web_fetch` 前，先 `HEAD /robots.txt` 检查目标域名的爬虫规则；拒绝的路径记录到日志，不发起请求 |
| **来源声明** | 每条 `CollectedDataPoint` 的 `source_type` 字段区分：`"official"`（官方公开）/ `"review"`（用户评价）/ `"news"`（媒体报道）/ `"interview"`（用户访谈）— 所有来源均公开可追溯 |
| **速率控制** | 同一域名请求间隔 ≥1s，避免对目标站点造成压力 |
| **工具合规** | 所有采集工具（Tavily/Firecrawl/Jina/Brave）均在各自免费/商业授权范围内使用 |

#### 3.15.3 数据脱敏 `**[竞赛要求 R18]**`

> 会议纪要明确："报告中涉及用户访谈等数据需做脱敏处理，避免个人敏感信息露出"。

| 数据类型 | 脱敏方式 |
|---------|---------|
| **问卷/访谈中的姓名/ID** | 自动检测 → 替换为 "受访者A" / "用户B" |
| **邮箱/手机号** | 正则匹配 → `[已脱敏]` |
| **公司内部数据** | 飞书文档/群聊作为数据源时，仅提取公开事实，不保留内部讨论中的个人发言归属 |
| **用户评论截图** | 用户名/头像模糊处理（如有） |

实现：在 Writer 生成报告前，LLM prompt 中注入脱敏指令 + Python 正则后处理双重保障。

#### 3.15.4 业务指标可量化追踪 `**[竞赛要求 R15]**`

> 判标 §4 20% 要求"相比传统人工，在效率/覆盖度/一致性上有可量化的提升。设计清晰的业务闭环关键指标（准确率、覆盖率、人工修正率）"。

| 指标 | 定义 | 计算方式 | 答辩展示 |
|------|------|---------|---------|
| **信息覆盖率** | 采集到的数据点覆盖请求维度的比例 | `covered_dimensions / total_requested_dimensions` | 每次分析输出覆盖度仪表盘 |
| **交叉验证率** | 经 ≥2 个独立来源验证的数据点比例 | `multi_source_points / total_data_points` | Reviewer 节点输出 |
| **人工修正率** | HITL 中被人类打回的比例 | `(replan + reanalyze + rewrite) / total_hitl_decisions` | HITL Gate 统计 |
| **反馈改善率** | 打回后 gap 被填补的比例 | `resolved_gaps / total_gaps_identified` | 反馈回环边标注 |
| **溯源完整率** | 报告中带有效来源链接的结论比例 | `traced_claims / total_claims` | 溯源地图统计 |
| **效率倍数** | vs 传统人工同质量分析的耗时比 | 系统耗时 vs 估算人工耗时（2-3天） | 答辩话术："2分钟 vs 2天" |

**效率声明示例（答辩用）**：
```
💰 Token 消耗: ~50,000 tokens ≈ $0.05 (Doubao-Seed-2.0)
⏱️ 总耗时: 2分14秒
📊 覆盖率: 9/10 维度 (90%)
✅ 交叉验证率: 13/18 数据点 (72%)
🔁 反馈改善率: 2/2 gaps 填补 (100%)
📎 溯源完整率: 18/18 (100%)

传统人工竞品分析需要 2-3 天完成相同质量的工作。
效率提升: ~1,000x | 成本: < 0.5 元人民币
```

#### 3.15.5 超时重试与降级 `**[竞赛要求 R13]**`

| 机制 | 实现 |
|------|------|
| **per-Agent 超时** | Collector: 600s / Analyst: 300s / Reviewer: 300s / Writer: 180s（可配置） |
| **工具调用超时** | 每个 web_search/web_fetch 调用 30s 超时，超时自动重试（指数退避：1s → 2s → 4s，最多 3 次） |
| **LLM 调用重试** | API 错误自动重试（同指数退避），非 4xx 错误才重试 |
| **降级策略** | 某数据源不可用时 → 自动切换备选源（Tavily 不可用 → Brave Search）；某 Agent 超时 → 带上已有部分结果继续下一节点 |
| **看门狗** | DF 已有的 `loop_detection_middleware`（3 次警告/5 次强制停止）防止 Reviewer 无限打回 |

#### 3.15.6 错误处理决策树 `**[竞赛要求 R12, R13]**`

> 判标 §4 25% 要求"错误恢复有明确策略"、"系统稳定性：异常处理、超时重试、降级机制完备"。
> 分层原则：**DF 基座管"怎么重试"，我们管"重试失败后图往哪走"**。

##### 3.15.6.1 错误分类

| 类别 | 示例 | 严重级别 | 策略 | 谁处理 |
|------|------|---------|------|-------|
| **A. 瞬时故障** | API 超时、Rate Limit、网络抖动 | 可恢复 | DF 的 SubagentExecutor + Middleware 链自动指数退避重试（1s→2s→4s，最多 3 次）。**我们不需要写重试逻辑。** | **DF 基座** |
| **B. 数据质量** | Schema 校验失败、空搜索结果、LLM 返回非 JSON | 可降级 | 节点内重试 1-2 次后标注降级，不阻塞流程。保留部分结果继续 | 节点内部 |
| **C. 逻辑故障** | 反馈死循环（同一 gap 反复出现 3 次）、连续 2 轮改善率为 0 | 需干预 | 自动关闭回环（降级标注或强制进 Writer），不等待人工介入 | 节点 + 路由 |
| **D. 基础设施故障** | Sandbox 崩溃、LLM API 返回 5xx 且重试耗尽、Out of Memory | 致命 | 设 `error` 字段 → 路由到 `error_handler` → 保存 checkpoint → 优雅停止 | Graph 层 |

> **关键区分**：A 类不需要我们写代码——DF 的 SubagentExecutor 和 middleware 链已经处理了。我们的节点只需要判断 `result.status == "failed"` 并决定降级行为。

##### 3.15.6.2 逐节点 Fallback 行为

**Collector 节点**：

```
Collector 执行中
  │
  ├─ 单个搜索 API 超时/失败
  │   → DF 基座已重试。重试耗尽后：
  │   → 切换到 fallback 链下一级（火山引擎 → Tavily → Brave，见 §3.4.5）
  │
  ├─ 全部搜索 API 失败
  │   → 已有部分数据 → 继续，标注 stopped_by = "all_sources_failed"
  │   → 0 条数据 → 设 error = "COLLECTOR_NO_DATA"，路由到 error_handler
  │
  ├─ SubagentExecutor 返回 failed（600s 超时或重试耗尽）
  │   → 保留已采集的部分数据（SubagentExecutor 的 thread 级 checkpoint）
  │   → 补充一条 gap："采集超时，以下维度可能未覆盖"
  │   → 不设 error，继续进 Analyst
  │
  └─ LLM 返回格式错误（非 JSON）
      → 重试 1 次（prompt 附带解析错误提示）
      → 仍失败 → 丢弃该条，记日志，不阻塞
```

**Analyst 节点**：

```
Analyst 执行中
  │
  ├─ 输入数据量 < 5 条
  │   → 正常分析但标注 "⚠ 数据量不足，分析结论置信度较低"
  │
  ├─ Schema 校验失败（comparison_matrix 缺必要字段）
  │   → 重试 2 次（附带 ValidationError 详情）
  │   → 仍失败 → 保留 LLM 原始输出，标注 "⚠ Schema 校验失败，已保留原始输出"
  │   → 不阻塞，继续进 Reviewer
  │
  ├─ 可视化生成失败（matplotlib 异常）
  │   → 跳过该图表，报告中注明 "图表生成失败"
  │   → 不阻塞文本分析
  │
  └─ SubagentExecutor 返回 failed（300s 超时）
      → 保留已生成的部分（如 SWOT 已生成但趋势分析未完成）
      → 标注缺失维度，继续进 Reviewer
```

**Reviewer 节点**：

```
Reviewer 执行中
  │
  ├─ 单条数据 HEAD 请求超时（网络不可达）
  │   → 标记 "⚠ 无法验证（网络不可达）"，不生成 fact_error
  │   → 与 HTTP 4xx 区分：4xx = fact_error，timeout = 不确定
  │
  ├─ 同一 gap 第三次出现（反馈死循环）
  │   → 不再打回 Collector，该 gap 降级为 minor
  │   → 写入 unresolved_issues，ReviewVerdict.passed = True
  │
  ├─ 连续 2 轮改善率 improvement_ratio = 0
  │   → 停止打回，标注 "⚠ 无法通过重新采集改善"
  │   → ReviewVerdict.passed = True，进 Writer（带不确定性）
  │
  ├─ scipy 计算异常（数据量不够做 zscore）
  │   → 跳过该统计检查，标注 "因数据量不足未执行统计检验"
  │   → 不阻塞其他检查
  │
  └─ review_round >= 2
      → 强制进 Writer（已有路由逻辑 §3.10，不是错误处理）
```

**Writer 节点**：

```
Writer 执行中
  │
  ├─ traceability_map 有缺失（某条结论无 source_url）
  │   → 该结论标注 "[来源缺失]"，不从报告中删除
  │
  ├─ 图表文件无法嵌入 Markdown
  │   → 保留图片文件路径，报告中引用相对路径
  │
  └─ LLM 输出过长被截断
      → 优先保留执行摘要 + 对比矩阵（核心章节）
      → 附录/详细数据表可截断
```

**HITL Gate 节点**：

```
HITL Gate 执行中
  │
  ├─ 审批超时（30 分钟无响应）
  │   → 默认 = approve（避免无限阻塞）
  │   → 标注 "⚠ 用户未响应，自动批准"
  │
  ├─ 用户选择 replan/reanalyze/rewrite 但未提供具体意见
  │   → 正常路由（replan → Collector, reanalyze → Analyst, rewrite → Writer）
  │   → 目标节点的 system prompt 注入 "用户要求重做，但未指定具体修改方向，请重新生成"
  │
  └─ 审批卡片推送失败（飞书 API 异常）
      → 降级为默认 approve，日志记 warning
      → 不阻塞系统（HITL 是增强功能，不是必须条件）
```

##### 3.15.6.3 错误传播路径（Graph 层）

```
     ┌──────────┐
     │  任意节点  │
     └────┬─────┘
          │
     ┌────┴────┐
     │ error 字段被设置? │
     └────┬────┘
          │
     ┌────┴────┐
     │ NO      │ YES
     ▼         ▼
  正常路由  ┌─────────────┐
           │ error_handler │
           │ 节点           │
           └──────┬────────┘
                  │
           ┌──────┴──────┐
           │ D 类（致命）  │ C 类（逻辑故障）
           ▼              ▼
     保存 checkpoint   自动设 HitlDecision
     report_data =       (action = "replan")
       ReportData(       路由回 Collector
         title="分析失败",
         ...)
     HitlDecision
       (action = "approve")
     END
```

> **A/B 类错误不进入 error_handler**——各节点内部已降级处理。error_handler 只处理 D 类（致命）和 C 类（逻辑故障升级到致命）。

##### 3.15.6.4 error_handler 节点实现

```python
def error_handler_node(state: CompetitionState) -> dict:
    error = state.get("error", "")

    # 有部分结果 → 降级标注后尝试继续
    if state.get("collected_data") or state.get("analysis_result"):
        return {
            "error": None,  # 清除错误，继续流程
            "unresolved_issues": [{
                "type": "system_error",
                "description": f"系统在运行中遇到错误: {error}",
                "severity": "minor",
            }],
        }

    # 完全无结果 → 优雅停止
    return {
        "error": f"FATAL: {error}",
        "report_data": ReportData(
            title="分析失败",
            persona="pm",
            generated_at=datetime.now().isoformat(),
            products=[],
            sections=[ReportSection(
                id="sec-error",
                title="错误",
                content=f"系统在运行过程中遇到致命错误：\n\n> {error}\n\n请检查输入或稍后重试。",
                content_type="text",
                source_ids=[],
            )],
            traceability_map={},
            quality_summary=QualitySummary(...),
            metrics={},
        ),
        "review_decision": "approve",  # 跳过 HITL，直接结束
        "hitl_decision": HitlDecision(action="approve", comment="致命错误，自动批准", target_focus=None, timestamp=datetime.now().isoformat()),
    }
```

##### 3.15.6.5 DF 层 vs Graph 层职责总结

| 层 | 职责 | 我们需要写吗 |
|---|------|------------|
| **DF 工具调用层** | LLM API 重试（指数退避）、loop_detection（3 次警告/5 次停止）、高危命令拦截 | ❌ DF 自带 |
| **节点内部** | 收到 DF 失败结果后的降级行为、Schema 校验失败的重试 | ✅ 每个节点内判断 |
| **Graph 路由层** | 读到 error 字段 → 路由到 error_handler / 正常路由 | ✅ route_after_* 函数判断 |
| **error_handler 节点** | 致命错误的最终决策（优雅停止 vs 降级继续） | ✅ 一个节点 |
| **图级循环防护** | 防止反馈回环无限循环 | ❌ 不需要额外机制——review_round >= 2 硬上限 + Reviewer 同 gap 三次降级已足够 |

---

## 四、数据源矩阵 — Collector 信息采集体系

采集 Agent 是整个系统的"感官"，信息源的丰富度直接决定分析质量。以下按类型分级。

### 4.0 字节跳动生态 API（核心差异化优势）

> **战略价值**：这是字节内部 CIS 比赛，深度集成字节技术生态会让评审产生天然共鸣。
> Doubao API Key 通过火山方舟发放，同一账号体系下可扩展使用火山引擎全家桶。

#### 4.0.1 火山引擎联网搜索 API（对标并超越 Tavily）

**官方文档**：https://www.volcengine.com/docs/87772/2272949

这是字节跳动官方的联网搜索服务，能力远超通用搜索 API：

| 能力 | 火山引擎联网搜索 | Tavily（DF 默认） |
|------|-----------------|-------------------|
| 文本搜索 | ✅ 50 条结果/次 | ✅ 5 条结果/次 |
| **图片搜索** | ✅ 支持 | ❌ 不支持 |
| **视频搜索** | ✅ 支持 | ❌ 不支持 |
| 域名过滤 | ✅ 指定/屏蔽域名 | ❌ 不支持 |
| 时效筛选 | ✅ 按时间段 | ❌ 有限 |
| Rerank 评分 | ✅ 相关性打分 | ❌ 无 |
| 权威分级 | ✅ 官方/媒体/UGC | ❌ 无 |
| 深度搜索 | ✅ 自适应多步拆解 | ❌ 无 |
| 垂类如意 | ✅ 20+ 结构化信息 | ❌ 无 |
| P90 延迟 | 800ms | ~2-3s |
| 中文内容 | 🏆 原生优势 | 🌐 覆盖一般 |

**API 调用示例**：
```python
import requests

url = "https://api.volcengine.com/websearch/v1/query"
headers = {
    "Authorization": "Bearer YOUR_API_KEY",
    "Content-Type": "application/json"
}
payload = {
    "FunctionName": "webSearch",
    "Query": "Cursor AI editor pricing 2026",
    "Count": 20,
    "DisableImageSearch": False,       # 开启图搜
    "DisableVideoSearch": False,       # 开启视频搜
    "TimeRange": "past_month",         # 时效筛选
    "VisionConfig": {"Enable": True}   # 多模态
}
```

#### 4.0.2 火山方舟 Responses API 内置 web_search（最简单接入）

**官方文档**：https://www.volcengine.com/docs/82379/1756990

Doubao 模型本身就支持内置 web search tool，只需在 API 调用时声明即可，**无需额外 API Key**：

```python
response = client.responses.create(
    model="doubao-seed-2-0-lite-260215",  # 比赛提供的模型！
    input=[{"role": "user", "content": "Cursor 最新定价是多少？"}],
    tools=[{"type": "web_search", "limit": 10}],
    stream=True,
)
```

可搜索来源包括：**抖音百科、头条图文、墨迹天气**等字节系内容。

#### 4.0.3 抖音开放平台 API（独特的视频舆情源）

**官方文档**：https://developer.open-douyin.com/

核心接口 — 关键词搜索视频：

```python
GET https://open.douyin.com/dy_open_api/v2/search/video/
  ?keyword=Cursor编辑器
  &count=20
  &sort_type=0    # 0=综合 1=最多点赞 2=最新
  &publish_time=180  # 半年内
```

返回：视频标题、作者、点赞数、发布时间、视频链接。

**竞品分析场景**：
- 搜索 "Cursor vs Copilot" → 中文科技博主的对比评测视频
- 搜索 "AI编程工具推荐" → 用户真实使用反馈和偏好
- 搜索竞品关键词 → 抖音上的讨论热度和舆情趋势
- 结合 Doubao 多模态 → 从视频截图提取产品信息

**接入要求**：需在抖音开放平台申请「抖音视频垂搜」权限，使用 `client_token`（应用级授权，无需用户授权）。

#### 4.0.4 字节生态 API 总览

| API | 产品 | 数据类型 | 优势 | 接入难度 |
|-----|------|---------|------|---------|
| **联网搜索** | 火山引擎 | 网页/图片/视频 | 多模态、中文强、速度快 | 低（同一火山账号） |
| **web_search tool** | 火山方舟 | 网页文本 | 零配置、Doubao 内置 | 极低（已就绪） |
| **抖音视频搜索** | 抖音开放平台 | 短视频+统计数据 | 独家中文视频舆情 | 中（需申请权限） |
| **VikingDB 多模态检索** | 火山引擎 | 向量/图片/视频 | 以图搜图、以视频搜视频 | 中 |
| **头条图文搜索** | 火山方舟内置 | 头条文章 | 中文资讯深度 | 极低（已就绪） |
| **抖音百科** | 火山方舟内置 | 结构化知识 | 中文知识图谱 | 极低（已就绪） |
| **飞书生态** | 飞书开放平台 | 文档/群聊/审批 | 企业内部数据 | 低（lark-cli） |

### 4.1 文本搜索源（通用）

#### 4.1.1 通用 Web Search（DF 已有 + 可扩展）

| API | 状态 | 协议 | 说明 |
|-----|------|------|------|
| **Tavily Search** | ✅ DF 已集成 | 商业 | 专为 AI Agent 优化的搜索，返回结构化结果+摘要 |
| **Jina AI Reader** | ✅ DF 已集成 | 商业 | URL → 可读 Markdown，适合抓取具体页面 |
| **Firecrawl** | ✅ DF 已集成 | 商业 | 整站爬取 + LLM 提取，适合批量抓文档站 |
| **DuckDuckGo Image** | ✅ DF 已集成 | 免费 | 图片搜索 |
| **Brave Search** | 可扩展 | 免费额度 | 隐私友好的通用搜索，月免费 2000 次 |
| **Serper** | 可扩展 | 商业 | Google 搜索的结构化代理，速度快 |

#### 4.1.2 垂直平台搜索（针对性强，差异化大）

| 平台 | 数据类型 | 采集方式 | 价值 |
|------|---------|---------|------|
| **Product Hunt** | 产品发布、用户评论、投票 | 非官方 API / web_fetch | 新品发现、用户反馈、趋势 |
| **G2 / TrustRadius** | B2B 软件评测、对比 | web_fetch + 结构化提取 | 企业用户视角的竞品对比 |
| **GitHub** | 开源项目 star/fork/issue/PR | GitHub API（免费） | 开发者社区活跃度、功能迭代速度 |
| **Reddit** | 用户讨论、社区情绪 | Reddit API（免费） | 真实用户体验、痛点、对比讨论 |
| **Hacker News** | 技术社区讨论 | HN API（免费） | 技术圈对产品的评价 |
| **App Store / Google Play** | 用户评分、评论 | RSS / web_fetch | 移动端用户满意度 |
| **知乎 / 微博** | 中文用户讨论 | web_fetch | 中文市场的竞品舆论 |
| **ArXiv / Semantic Scholar** | 学术论文 | 免费 API | 前沿技术追踪（如 AI 模型对比） |
| **Crunchbase** | 融资、团队规模 | 非官方 API | 竞品公司实力评估 |

#### 4.1.3 官方源

| 来源 | 数据 | 方式 |
|------|------|------|
| 产品官网 | 定价、功能列表、更新日志 | web_fetch + 结构化提取 |
| 公司博客 RSS | 产品动态、技术分享 | RSS feed 抓取 |
| SEC 文件 (上市公司) | 财报、风险披露 | EDGAR API |
| 开发者文档 | API 能力、技术栈 | web_fetch + 文档解析 |

### 4.2 视频/多媒体源（Doubao 多模态）

比赛提供的 **Doubao-Seed-2.0-lite 支持视觉**，可以分析图像和视频帧。

| 源类型 | 具体来源 | 采集方式 | 分析方式 |
|--------|---------|---------|---------|
| **YouTube** | 产品评测视频、发布会、博主对比 | `youtube-transcript-api` (MIT) 提取字幕/章节 | 字幕文本 → LLM 提取观点 + 时间轴标注 |
| **Bilibili** | 中文科技评测、开箱视频 | `bilibili-api` (MIT) 提取视频信息+字幕 | 同上，覆盖中文市场 |
| **播客** | 科技播客讨论 | RSS + 转录 API | 音频 → Whisper 转文字 → 提取观点 |
| **产品截图** | 竞品 UI/UX 截图 | 手动上传 / web_fetch 图片 | Doubao 多模态：从截图提取功能、交互、布局信息 |
| **发布会视频帧** | 关键幻灯片、产品图 | yt-dlp 提取关键帧 | Doubao 多模态：分析幻灯片内容、规格表 |
| **信息图/图表** | 市场报告中的图表 | web_fetch 图片 | Doubao 多模态：提取图表数值、趋势 |

**视频源的差异化价值**：
- 大多数比赛队伍只会用文本搜索，**视频+多模态是 0→1 的差异**
- 科技博主评测往往比文字评测更详细、更及时
- "从视频提取竞品信息"本身就是一个可展示的技术点

### 4.3 飞书文档源（DF 已具备能力）

通过 DF 的飞书 Channel + lark-cli，可以直接读取飞书生态内的文档：

| 源 | 方式 | 场景 |
|------|------|------|
| 飞书 Docx / Wiki | `docs +fetch --api-version v2` | 团队内部的竞品调研文档、会议纪要 |
| 飞书 Sheets | `lark-sheets` 读取 | 已有的竞品对比表格 |
| 飞书 Base | `lark-base` 读取 | 结构化竞品数据库 |
| 飞书群聊记录 | `im +chat-messages-list` | 群里的竞品讨论、用户反馈 |

### 4.4 用户声音聚合器 (Voice of Customer Aggregator) `**[竞赛要求 R2]**`

> **替代传统的"问卷分发"为主方案，辅以问卷/访谈生成能力** — 更自动化、更客观、技术含量更高。竞赛明确要求采集 Agent "包括问卷设计、问卷调研、用户访谈等"。我们的方案：轨 1（VoC Aggregator，完全自动化）覆盖 80% 场景；轨 2（问卷/访谈生成，见 §3.3 Collector 双轨设计）覆盖需要定向调研的场景。

**流程**：
1. 根据 target_products，自动识别相关评论平台
2. 多平台并行抓取用户评价（Product Hunt / G2 / Reddit / GitHub Issues / App Store）
3. LLM 从评论中提取：功能诉求、痛点、竞品对比提及、满意度信号
4. pandas 统计：情绪分布、高频关键词、功能需求排序
5. 产出 "用户真正想要什么" 章节，带情绪分布图和需求优先级矩阵

**为什么比传统问卷好**：
- **完全自动化**：不需要等真人填问卷、不需要分发渠道
- **数据更客观**：非诱导性问题，用户自发表达真实想法
- **量更大**：一次可以处理成百上千条评价
- **天然溯源**：每条评价有原始链接
- **技术展示**：爬虫 → NLP → 统计 → 可视化，完整技术链路

---

## 五、外围亮点功能矩阵

### 5.1 飞书 Bot 全流程入口（P0 — DF 已具备，配置即用）

DF 的 `app/channels/feishu.py`（699 行）已实现完整飞书 Bot：

- WebSocket 长连接，无需公网 IP
- 支持文本/图片/文件/富文本消息接收
- **流式卡片回复**：先发 "Working on it..." → 实时 patch 更新进度 → 完成加 DONE ✅
- 图片/文件自动下载到 Sandbox

**比赛演示流程**：
```
用户在飞书群 @Bot: "分析一下 Claude Code vs Cursor vs Copilot"
  → Bot 回复 OK 👌 + 实时进度卡片:
     [████░░░░] Collector 正在采集... 
       ✓ GitHub API: Cursor 最近 30 天 127 commits
       ✓ YouTube: 3 条博主评测视频字幕已提取
       ✓ G2: 42 条用户评价已抓取
     [██████░░] Analyst 正在对比... 
       ✓ 功能矩阵已生成 (8 维度 × 3 产品)
       ✓ SWOT 分析中...
     [████████] Reviewer 校验中... 
       ✓ 15/15 数据点通过验证
       ⚠ 发现 1 个数据冲突（定价），已推送飞书审批
     [完成 ✅] 报告已生成 → analysis_report.md (附件)
```

**配置**：只需在 `config.yaml` 中添加飞书 App ID + Secret。

### 5.2 飞书审批 HITL Gate（P1 — 新增，比赛亮点） `**[竞赛要求 R5, R16]**`

> 判标 §4 35% 要求"反馈闭环真实可触发"，20% 要求"交互设计流畅：人工介入修正"。审批不仅是 4 个按钮，更支持自由文本交互——用户用自然语言描述修改意图，系统自动解析并路由。

#### 5.2.1 审批卡片信息结构

卡片内容由 `ReviewPackage`（§3.13.5）驱动，分三个区域设计。信息原则：**摘要让用户 10 秒判断"结果对不对"，关键发现让用户定位"哪里不对"，数据质量让用户评估"要不要信"**。

```
┌──────────────────────────────────────────┐
│ 📊 竞品分析报告 — 待审批                    │
│                                          │
│ 【执行摘要】                              │
│ Cursor 在功能完整度和社区活跃度上领先，      │
│ Copilot 在生态集成和企业定价上有优势，       │
│ Windsurf 在创新速度上突出但市场份额最小。     │
│                                          │
│ 【关键发现】                              │
│ • Cursor Pro $20/月 vs Copilot $19/月     │
│   → 价格接近，Cursor 免费版能力更强         │
│ • 用户满意度：Cursor 4.2 > Copilot 3.8    │
│   → 差距在"代码补全准确性"维度最明显         │
│ • ⚠ Windsurf 企业版定价数据缺失             │
│                                          │
│ 【数据质量】                              │
│ 总数据点: 42 | 交叉验证: 72% | 溯源: 100%  │
│ 反馈改善率: 100% (2 gaps → 0)              │
│                                          │
│ 【未解决问题】                            │
│ • Windsurf 企业版定价未找到                 │
│                                          │
│ 【建议操作】                              │
│ 建议批准发布 | 或要求重写为投资人视角         │
│                                          │
│ 💬 输入修改意见：                          │
│ ┌──────────────────────────────────────┐ │
│ │ "SWOT 太笼统，需要具体的 Tab 补全      │ │
│ │  准确率数据，最好有定量对比"            │ │
│ └──────────────────────────────────────┘ │
│                                          │
│ [✅ 批准] [🔄 重新搜索] [📊 重新分析] [✏️ 重写] │
└──────────────────────────────────────────┘
```

#### 5.2.2 四个按钮的场景与语义

| 按钮 | 何时选 | 系统行为 |
|------|--------|---------|
| **approve** ✅ | 结果没问题，可以直接用 | `HitlDecision(action="approve")` → END 或深度模式 |
| **replan** 🔄 | 关键维度缺数据、来源太少、数据过时 | `HitlDecision(action="replan")` → Collector 定向补采 |
| **reanalyze** 📊 | 数据没问题但结论偏了、SWOT 不准 | `HitlDecision(action="reanalyze")` → Analyst 重做分析 |
| **rewrite** ✏️ | 数据和结论都对，但表达风格/视角不合适 | `HitlDecision(action="rewrite")` → Writer 重写报告 |

`target_focus` 让目标节点只重做指定部分，不全文重跑：

```
replan    + target_focus = ["定价"]       → Collector 定向搜索定价
reanalyze + target_focus = ["SWOT"]       → Analyst 只重做 SWOT
rewrite   + target_focus = ["创业者视角"]  → Writer 只重写创业者视角报告
```

#### 5.2.3 自由文本交互与意图解析

> 按钮是快捷操作，但不是好的交互的全部。用户应该能用自然语言精确描述修改意图。

**交互规则**：

| 用户操作 | 系统行为 |
|---------|---------|
| 只输入文本，不点按钮 | LLM 解析意图 → 自动判断 action + target_focus → 执行 |
| 只点按钮，不输入文本 | 当前逻辑，`comment` 为空，`target_focus` 取按钮默认 |
| 输入文本 + 点按钮 | 按钮决定 action，文本解析为 target_focus + 补充上下文 |
| 什么都不做 | 30 分钟超时 → auto-approve |

**意图解析 Prompt**（一次轻量 LLM 调用，HITL Gate 节点内部）：

```
你是一个意图解析器。用户在审阅竞品分析报告后给出了反馈。
请判断用户的意图，输出 JSON。

用户反馈: "{user_comment}"

可选动作:
- "approve": 用户满意，可以发布
- "replan": 用户认为数据不够，需要重新搜索
- "reanalyze": 用户认为分析不对，需要重新分析
- "rewrite": 用户认为报告表达需要修改

输出格式:
{
    "action": "replan" | "reanalyze" | "rewrite" | "approve",
    "target_focus": ["维度1", "维度2"],
    "reasoning": "一句话"
}
```

**为什么架构不用变**：意图解析只是 HITL Gate 节点内部多了一步 LLM 调用，输出还是 `HitlDecision` → 路由到已有 4 条边。回环不变，Graph 不变。

#### 5.2.4 飞书审批卡片 vs 前端审批（双路径）

两种实现路径，共享同一个 `ReviewPackage` Schema，只是渲染层不同：

| 维度 | 前端审批界面 | 飞书审批推送 |
|------|------------|------------|
| 优先级 | **P0**（比赛基准） | P1（增强亮点） |
| 实现方式 | 在 Gradio/Next.js 中嵌入审批卡片组件 | `lark-cli approval` API 推送 |
| 优势 | 不依赖外部服务、和 DAG 面板同界面 | 字节生态共鸣、飞书 App 内体验 |
| 劣势 | 需要开发审批 UI | 依赖飞书 API、需处理回调 resume |

**比赛策略**：P0 做前端审批（和 §7 可观测面板同一界面），P1 加飞书审批推送。答辩时前端展示审批交互，提到"已预留飞书审批对接"。

#### 5.2.5 审批超时与默认行为

| 场景 | 默认行为 | 理由 |
|------|---------|------|
| 30 分钟无操作 | auto-approve，标注 "⚠ 用户未响应，自动批准" | 不阻塞流程 |
| 飞书审批推送失败 | auto-approve + warning 日志 | HITL 是增强，不是必须阻塞点 |
| 用户选 replan/reanalyze/rewrite 但未填 comment | 正常路由，目标节点 prompt 追加 "用户未指定具体修改方向，请重新生成" | 降低使用门槛 |

### 5.3 竞品变更检测 + 飞书通知（P1 — 新增）

对关键竞品页面做定期快照，检测到变更时主动推送：

**场景**：
- Cursor 更新了定价页 → 飞书通知 "Cursor Pro 从 $20 涨到 $30"
- Copilot 发布了新功能 → 飞书通知 + 变更摘要
- Windsurf 被收购 → 飞书通知 + 行业影响分析

**技术实现**：
- 对目标 URL 做 hash 快照（存 SQLite）
- 定时任务（或手动触发）对比当前页面
- 变更检测 → LLM 生成变更摘要 → 飞书 Bot 推送
- 报告中标注："数据采集于 5/21，Cursor 定价页在 5/25 检测到变更"

### 5.4 可视化增强（P0 — 报告差异化关键）

在 Sandbox 中用 matplotlib/seaborn 生成，嵌入 ReportData 报告的 chart section：

| 图表类型 | 用途 | 示例 |
|---------|------|------|
| **雷达图** | 多产品多维度对比 | 功能/价格/UX/生态/支持/安全性 |
| **热力图** | 功能覆盖矩阵 | 行=功能 × 列=产品 × 颜色=支持度 |
| **时间线** | 产品演进对比 | Claude Code 2024.3 → 2025.7 vs Cursor 2024.1 → 2025.8 |
| **堆叠柱状图** | 定价对比 | 各产品免费/Pro/Enterprise 价格 |
| **情绪饼图** | 用户评价分布 | 正面/中性/负面 |
| **气泡图** | 市场定位 | X=价格 Y=功能覆盖 大小=用户量 |
| **词云** | 用户高频反馈 | 从评论中提取关键词 |

### 5.5 一键 HTML 报告导出（P2）

生成自包含的 HTML 文件（图表内嵌 base64、带目录导航、响应式），可：
- 飞书发送为附件
- 浏览器直接打开演示
- 打印为 PDF

### 5.6 竞品分析历史对比（P2 — 复用 DF Memory）

利用 DeerFlow 的 Memory 系统存储每次分析的关键数据点：

> "对比你 5 月 15 日的分析，Cursor 新增了 Terminal Cursor 功能，Pro 价格上涨了 $5/月。Claude Code 的 GitHub star 数增长了 12%。"

### 5.7 人对报告的细粒度交互式编辑（P0 — 答辩核心交互） `**[竞赛要求 R16]**`

> **核心理念**：竞品分析不是"AI 生成 → 人看一眼"就完了。对标判标 §4 "交互设计流畅：报告查看、溯源跳转、人工介入修正"。

#### 5.7.1 交互模式设计

```
Writer 完成报告
  │
  ├─→ 📄 飞书 Doc 自动创建（报告载体）
  │      │
  │      ├─ ✍️ 用户直接编辑 Doc（飞书原生协作能力）
  │      │    人对 AI 生成的任何段落都能手动修改
  │      │
  │      ├─ 💬 用户选中段落 + 添加局部评论:
  │      │    "@bot 深度调研这个数据点，补充更多来源"
  │      │    "@bot 这段重写为投资人视角"
  │      │    "@bot 验证这个市场份额数据的准确性"
  │      │    "@bot 展开这个要点为详细分析"
  │      │
  │      ├─ 📩 用户飞书 DM 给 Bot 发全局指令:
  │      │    "/report deep-dive 第三章"     → 对该章节深度调研
  │      │    "/report rewrite SWOT --style=investor" → 重写 SWOT
  │      │    "/report verify 全部数据"      → 全局交叉验证
  │      │    "/report expand 竞争优势分析"   → 展开某个要点
  │      │
  │      └─ 🤖 Bot 自动处理:
  │           1. 读取评论/DM 中的指令 + 上下文 block 内容
  │           2. 判断动作类型 → 触发对应 Agent
  │           3. Agent 执行（增量采集/深度分析/交叉验证/重写）
  │           4. docs +update --command block_replace 精准更新目标段落
  │           5. 回复评论/DM 确认变更
  │
  └─→ 🌐 前端同步展示（普通模式报告同样支持交互）
```

#### 5.7.2 支持的操作类型

| 操作 | 触发方式 | Agent 动作 | Feishu API |
|------|---------|-----------|-----------|
| ✍️ **手动编辑** | 用户直接在 Doc 中修改文字 | 无（飞书原生） | 飞书文档协作 |
| 🔍 **深度调研** | 评论 "@bot deep-dive" 或 DM | 选中段落的结论 → Collector 增量搜索 → 新数据回填 | `block_replace` 精准更新 |
| ✅ **交叉验证** | 评论 "@bot verify" 或 DM | 选中段落的声明 → Reviewer 重新校验 → 标记可信度 | `block_replace` + 注释 |
| ✏️ **重写段落** | 评论 "@bot rewrite --style=X" | Writer 以指定风格重写该段 | `block_replace` |
| 📊 **补充溯源** | 评论 "@bot add-sources" | 查找该段声明对应的原始来源 → 追加脚注链接 | `block_insert_after` |
| 📖 **展开详情** | 评论 "@bot expand" | 摘要→详细分析，保留原有要点 | `block_replace` |
| 🗑️ **删除段落** | 评论 "@bot remove" | 需用户二次确认 → 删除 | `block_delete` |
| 🔄 **全局重跑** | DM "/report rerun" | 整个分析流程从头重跑 | `overwrite` 文档 |

#### 5.7.3 技术实现关键点

**飞书 API 能力链**（全部已验证可行）：

```
┌──────────────────────────────────────────────────┐
│  飞书 Doc 创建                                    │
│  lark-cli docs +create --api-version v2          │
│  → 生成报告 Doc，获得 doc_token                    │
├──────────────────────────────────────────────────┤
│  飞书 Doc 精准读取                                 │
│  lark-cli docs +fetch --api-version v2            │
│    --scope range --start-block-id <id>            │
│  → 读取被评论的段落内容 + 上下文                     │
├──────────────────────────────────────────────────┤
│  飞书 Doc Block 精准更新                           │
│  lark-cli docs +update --api-version v2            │
│    --command block_replace --block-id <id>         │
│    --content '<p>新内容...</p>'                    │
│  → 只更新目标段落，不动其他内容                       │
├──────────────────────────────────────────────────┤
│  飞书局部评论                                      │
│  lark-cli drive +add-comment                       │
│    --block-id <block_id>                           │
│    --content '[...]'                              │
│  → 在具体段落上添加局部评论                          │
├──────────────────────────────────────────────────┤
│  飞书评论监控                                      │
│  lark-cli drive file.comments list                 │
│  → 定期轮询检测新评论，提取指令                      │
└──────────────────────────────────────────────────┘
```

**评论监控**：由于飞书 Bot 本身已通过 DF 的 `FeishuChannel` 与用户联通，Bot 可以：
- 监听用户 DM 消息（DF 已有 `_on_message` 回调）
- 解析指令关键词（`deep-dive`、`verify`、`rewrite`、`expand` 等）
- 如果评论含 `@bot`，读取评论对应 block 的上下文
- 触发对应 Agent → 更新 Doc

#### 5.7.4 为什么这是答辩杀手锏

其他参赛队伍大概率是"输入 → 等待 → 拿到报告"的线性体验。我们可以展示：

1. **"报告不是终点，是对话起点"** — 生成报告只是第一步，人可以对任何段落继续追问
2. **"人机协作的完整闭环"** — AI 生成 → 人 review → 人指定改进方向 → AI 精准修改 → 人最终定稿
3. **"飞书原生的企业工作流"** — 所有操作都在飞书文档内完成，和团队日常协作方式一致
4. **"块级精度"** — 不是"全文重跑"，而是精准定位到某一个段落做增量改进

---

## 六、核心差异化创新点（总结） `**[竞赛要求 R14]**`

> 判标 §4 25% 要求"技术方案有独特或前瞻性思考"。

### 6.0 深度集成字节跳动技术生态（独特护城河）

> 这是其他参赛队伍几乎不可能完全复制的优势

| 层级 | 字节技术 | 在项目中的应用 |
|------|---------|-------------|
| **模型层** | Doubao-Seed-2.0-lite (火山方舟) | 全部 Agent 的推理引擎 |
| **搜索层** | 火山引擎联网搜索 API | Collector 主力搜索引擎（中文原生优势+多模态） |
| **搜索层** | 抖音开放平台 API | 中文短视频舆情分析（独家数据源） |
| **搜索层** | 火山方舟内置 web_search tool | Doubao 原生联网，零配置启用 |
| **内容层** | 头条图文 + 抖音百科 | 中文资讯深度 + 结构化知识 |
| **协作层** | 飞书开放平台 (Bot + 审批 + 文档) | 全流程交互入口 + HITL 审批 |
| **开发工具** | TRAE IDE | AI 编程辅助（比赛推荐） |

**答辩话术**："我们的系统不仅用了字节的模型，还深度集成了火山引擎联网搜索的多模态能力、抖音开放平台的视频舆情数据、飞书的协作审批流程——形成了一个端到端的字节技术栈驱动的竞品分析系统。"

### 6.1 多模态视频信息提取

结合 Doubao 视觉能力 + YouTube/Bilibili 字幕提取：
- 从科技博主评测视频中提取产品对比观点
- 从发布会视频中提取产品规格
- 从教程视频中分析功能完整度
- 每条观点标注视频时间轴（可溯源到具体帧）

### 6.2 双角色报告

| 维度 | PM 视角 | 创业者视角 |
|------|---------|-----------|
| 核心问题 | 该做什么功能？差异化在哪？ | 市场有机会吗？能活下去吗？ |
| 报告重点 | 功能对比矩阵、用户体验、定价对比 | 竞争格局、市场规模、进入壁垒 |
| SWOT 维度 | 产品级（功能/UX/定价） | 战略级（市场/团队/资本） |
| 建议类型 | 功能优先级、差异化方向 | 商业模式、细分市场选择 |

### 6.3 来源可信度评分

每次 Reviewer 校验后，根据数据是否被证伪，自动更新数据源的信任分数。

```python
class SourceCredibility:
    scores: dict[str, float]   # source_domain → credibility_score (0.0-1.0)
    verification_history: list[dict]  # [{source, claim, verified, timestamp}]
```

### 6.4 计算验证落地

Analyst 和 Reviewer 使用 Sandbox Python 做真实计算：
- `scipy.stats` 检验数据一致性
- `pandas` 交叉验证多个来源的数据
- 输出**可复现**的计算摘要（非 LLM 幻觉数字）

### 6.5 可观测 Dashboard

前端实时展示：
- **Agent 状态**：当前哪个 Agent 在工作，DAG 图节点高亮
- **Prompt 快照**：每个 Agent 收到的完整 Prompt 和结构化输出
- **Token 消耗**：每个 Agent + 总计
- **溯源链路**：每条结论 → 追溯到原始 URL 或视频时间轴

### 6.6 外部项目灵感注入

调研了 2025-2026 年 GitHub 上 star 最高的 Agent 项目，提炼出可直接借鉴的外围功能：

| 灵感来源 | 项目 (Stars) | 可借鉴功能 | 移植难度 |
|---------|-------------|-----------|---------|
| **Hermes Agent** | 140K ⭐ | **自主 Skill 创建**：每次分析后自动反思 → 提取可复用分析模式 → 写入 SKILL.md，下次自动加载 | 中 |
| **Hermes Agent** | 同上 | **渐进式 Skill 加载**：上下文只存 20 token/条的 skill 索引，用到时才加载完整 SKILL.md，解决大量分析模板撑爆上下文的问题 | 低 |
| **TradingAgents** | 71K ⭐ | **事后复盘**：分析结论跟踪 → 实际结果对比 → LLM 反思"为什么对/错" → 注入下次分析 | 中 |
| **TradingAgents** | 同上 | **双模型调度**："Deep Think"做推理和报告，"Quick Think"做数据检索，成本优化 | 低 |
| **OpenClaw** | 345K ⭐ | **Cron 定时监控**：定时检查竞品变更 → 自动触发分析 → 推送报告，变"一次性分析"为"持续监控" | 低（DF 已有 cron 基础设施） |
| **Competitor Hunter** | 500 ⭐ | **MCP 原生架构 + Playwright 反检测**：随机 UA、智能滚动、自动截图，适合抓反爬严格的竞品网站 | 中 |
| **MarketMind AI** | 新 | **置信度评分**：报告中每条结论带置信度，如"Cursor 定价 $20/月（置信度 0.95）"vs"用户满意度高于 Copilot（置信度 0.62，单源未交叉验证）" | 低 |
| **Paperclip** | 50K ⭐ | **按 Agent 预算管控**：每个 Agent 设 token/成本上限，80% 软警告，100% 硬暂停，防止复杂分析烧太多钱 | 低 |
| **AGNO** | 40K ⭐ | **原生 OpenTelemetry 追踪**：无需外部服务，自动捕获每个 Agent 的执行、模型调用、Token 用量 | 中 |
| **Mastra** | 22K ⭐ | **Agent 版本管理**：分析配置每次变更自动版本化，支持 diff 对比和回滚，追踪"哪个配置产出哪个质量" | 中 |

### 6.7 DF 基座已有但未充分利用的外围功能

DF 基座远超"LangGraph + Sandbox"。以下能力当前未在比赛计划中利用，但可以直接发挥：

| 功能 | 位置 | 比赛中的用法 |
|------|------|------------|
| **31 个公共 Skills** | `skills/public/` | `market-share-calc`、`spec-comparator`、`swot-generator`、`sentiment-analyzer`、`trend-detector`、`source-credibility`、`data-normalizer`、`deep-research`、`consulting-analysis`、`newsletter-generation`、`systematic-literature-review` — 绝大多数**直接对应竞品分析需求**，不需要从零开发 |
| **7 个 Channel 集成** | `app/channels/` | 除飞书外还有 Slack、Telegram、DingTalk、Discord、WeChat、WeCom — 报告可以多渠道推送 |
| **Guardrails 系统** | `deerflow/guardrails/` | 预工具调用授权，可限制 Collector 不会误删文件、Reviewer 不会执行高危命令 |
| **Sandbox Audit** | `sandbox_audit_middleware.py` | 16 种高危命令拦截（rm -rf、curl\|sh 等），答辩时展示安全审计日志 |
| **Loop Detection** | `loop_detection_middleware.py` | 检测 Agent 重复工具调用循环（3 次警告，5 次强制停止），防止 Reviewer 无限打回 |
| **ACP Agent 调用** | `invoke_acp_agent_tool.py` | 可链式调用外部 ACP 兼容 Agent，扩展数据源或分析能力 |
| **Tool Search** | `tool_search` (config 可开启) | MCP 工具延迟发现，减少上下文 Token 消耗 |
| **Token Usage 追踪** | `token_usage_middleware.py` (config 可开启) | 答辩时展示每个 Agent 的精确 Token 消耗 |
| **Skill Evolution** | `skill_evolution` (config 可开启) | LLM 驱动的 Skill 自我改进，积累多次分析的最佳实践 |
| **Cron/Heartbeat** | DF 基础设施 | 定时触发竞品监控，变被动分析为主动推送 |

### 6.8 DF 公共 Skills 应用与增强计划

> **核心策略**：在 DF 基座 16 个可用 Skill 上做二次增强，而非从零开发——既体现复用 DF 生态的能力，又展示我们自己的改进和创新。

#### 6.8.1 现有 Skill → Agent 映射

| Agent | DF 基座 Skill | 技能描述 |
|-------|-------------|---------|
| **Collector** | `deep-research` | 系统化多角度 Web 调研，迭代搜索精炼 |
| | `github-deep-research` | GitHub 仓库 Star/Commit/Contributor 深度分析 |
| | `systematic-literature-review` | 学术文献系统综述（arXiv → 并行提取 → 主题合成） |
| | `data-normalizer` | 异构数据标准化（Web/PDF/CSV/JSON → 统一表格） |
| **Analyst** | `spec-comparator` | 多源规格归一化 → 差距分析 → 优势百分比 → 排序 |
| | `market-share-calc` | 市场份额 + HHI/CR4/CR8 集中度指标 |
| | `price-elasticity` | 价格弹性（点/弧/交叉） + 需求曲线拟合 + 最优定价 |
| | `sentiment-analyzer` | 评论/新闻/社媒 → 极性 + 方面级 + 主题提取 + 时序趋势 |
| | `trend-detector` | 移动平均/季节分解/CAGR/Mann-Kendall/拐点检测 |
| | `data-analysis` | DuckDB SQL 即席分析（多文件 Join/透视/导出） |
| **Reviewer** | `source-credibility` | 五维度（权威/准确/时效/客观/方法）加权评分 + 矛盾检测 |
| **Writer** | `consulting-analysis` | Phase1: 框架+数据需求; Phase2: McKinsey/BCG 风格报告 |
| | `swot-generator` | 证据锚定 SWOT + TOWS 战略建议矩阵 |
| | `chart-visualization` | 26 种图表（雷达图/热力图/桑基图/词云等） |
| | `newsletter-generation` | 多源策展简报（日报/周报/深度/行业格式） |
| | `ppt-generation` | 8 种视觉风格 → PPTX |

#### 6.8.2 每个 Skill 的增强方案（我们的工作量与创新）

**Collector 层增强**：

| Skill | 基座能力 | 我们的增强 | 创新点 |
|-------|---------|-----------|--------|
| `deep-research` | 通用 Web 多轮搜索 | ➕ 接入火山引擎联网搜索 API（多模态：文+图+视频）<br>➕ 接入抖音开放平台 API（视频舆情搜索）<br>➕ 支持飞书文档作为搜索源 | 🔥 字节技术栈深度集成<br>🔥 多模态搜索超越纯文本 |
| `github-deep-research` | GitHub API 分析 | ➕ 竞品对比模式：同时分析多个 repo 并生成差异报告<br>➕ 关联开发者社区活跃度到产品健康度评分 | 自动化横评对比 |
| `systematic-literature-review` | arXiv 搜索+提取 | ➕ 扩展数据源到 Semantic Scholar、Google Scholar<br>➕ 自动提取竞品相关的技术路线图 | 多源学术检索 |
| `data-normalizer` | 异构→统一表格 | ➕ 添加视频字幕文本归一化（YouTube/Bilibili → 结构化数据）<br>➕ 添加用户评论归一化（多平台评价 → 统一情感+特征表） | 🔥 多模态数据归一化 |

**Analyst 层增强**：

| Skill | 基座能力 | 我们的增强 | 创新点 |
|-------|---------|-----------|--------|
| `spec-comparator` | 规格对比矩阵 | ➕ Doubao 多模态：从产品截图提取 UI/UX 信息纳入对比<br>➕ 自动计算每个产品的差异化优势分 | 🔥 视觉信息提取+量化 |
| `sentiment-analyzer` | 文本情感分析 | ➕ 跨平台情感对比（同一产品在 Reddit vs G2 vs 知乎 的口碑差异）<br>➕ 情感趋势与产品更新事件关联 | 跨平台对比分析 |
| `trend-detector` | 时间序列趋势 | ➕ 自动标注趋势拐点与竞品事件（新功能发布/定价变更）的因果关系<br>➕ 多产品趋势叠加对比 | 因果关联+对比可视化 |
| `market-share-calc` | 份额+集中度 | ➕ 从公开财务数据/新闻自动估算非上市公司的市场份额<br>➕ 生成市场份额预测区间（非单一数值） | 🔥 非上市公司估算 |
| `price-elasticity` | 价格弹性计算 | ➕ 从用户评论提取"价格敏感"信号补充定量分析<br>➕ 模拟"如果竞品降价 X%，我们的需求会变动 Y%" | 定性+定量混合 |
| `data-analysis` | DuckDB SQL | ➕ 预置竞品分析常用查询模板（市场份额、价格对比、功能覆盖）<br>➕ 自动生成分析摘要 | 领域模板 |

**Reviewer 层增强**：

| Skill | 基座能力 | 我们的增强 | 创新点 |
|-------|---------|-----------|--------|
| `source-credibility` | 五维度评分 | ➕ 跨分析 run 记忆：同一来源多次验证后的动态可信度演化<br>➕ 来源矛盾时自动触发飞书审批 HITL（而非仅标记）<br>➕ 分数可视化（雷达图展示五维度得分） | 🔥 动态可信度+审批联动 |

**Writer 层增强**：

| Skill | 基座能力 | 我们的增强 | 创新点 |
|-------|---------|-----------|--------|
| `consulting-analysis` | 咨询报告框架 | ➕ **双视角报告**：同一份数据 → PM 视角 + 创业者视角<br>➕ 报告章节可配置（用户自定义需要哪些分析维度） | 🔥 双角色视角 |
| `swot-generator` | SWOT + TOWS | ➕ 每个 SWOT 条目强制附带溯源链接（一键跳转原始来源）<br>➕ SWOT 对比模式：多个竞品 SWOT 并列展示 | 溯源+并列对比 |
| `chart-visualization` | 26 种图表 | ➕ 竞品专用图表模板（雷达对比图、功能热力图、价格阶梯图）<br>➕ 交互式图表（HTML 报告中可 hover/缩放） | 🔥 竞品专用可视化 |
| `newsletter-generation` | 多格式简报 | ➕ 竞品简报专用模板（竞品动态周报、行业趋势月报）<br>➕ 飞书/邮件自动推送 | 领域模板+自动分发 |
| `ppt-generation` | 8 风格 PPTX | ➕ 竞品分析专用幻灯片模板（含对比矩阵页、SWOT 页、建议页）<br>➕ 自动嵌入生成的图表 | 领域模板 |

#### 6.8.3 增强工作量估算

| 层级 | 增强项数 | 预计额外代码量 | 创新度 |
|------|---------|-------------|--------|
| Collector | 4 项 | ~500 行 Python（API 接入 + 数据适配） | 🔥 高 |
| Analyst | 6 项 | ~600 行 Python（分析逻辑 + 模板） | 🔥 高 |
| Reviewer | 1 项 | ~200 行 Python（动态评分 + HITL 联动） | 中 |
| Writer | 5 项 | ~400 行 Python + ~300 行前端 | 🔥 高 |
| **总计** | **16 项增强** | **~2000 行 Python + 前端** | **显著** |

### 6.9 竞品分析的本质是图问题（P2 扩展展望）

> 当前 comparison_matrix 已经用结构化表格编码了图的关系。如果时间充裕，以下图算法方向可以作为长期扩展。

**竞品分析中天然存在的图关系**：

```
Cursor ──[competes_with]──→ Copilot ──[competes_with]──→ Windsurf
  │                            │                            │
  │                            │                            │
[has_feature]              [has_feature]              [has_feature]
  │                            │                            │
  ▼                            ▼                            ▼
Tab补全(4.5)              Tab补全(3.8)              Tab补全(4.1)
  │                            │                            │
  │                            │                            │
[sourced_from]             [sourced_from]             [sourced_from]
  │                            │                            │
  ▼                            ▼                            ▼
cursor.com                 github.com                 windsuf.com
```

我们的 `ComparisonCell`（product → dimension，带 rating）就是图的邻接矩阵表示，`CollectedDataPoint` 就是叶节点（带 source），`ReviewVerdict` 就是边的置信度权重。

**值得加入的真图算法**：

| 图算法 | 竞品分析场景 | 时机 |
|--------|------------|------|
| **中心度** (Centrality) | 在 AI 编程工具生态中，OpenAI 的 GPT 模型是所有竞品的共同依赖 → 中心节点即"行业关键瓶颈" | P2 |
| **社区检测** (Community Detection) | 市场上自然形成"开源派 vs 闭源派"、"云原生 vs 本地"的阵营 | P2 |
| **路径分析** (Path Analysis) | 从产品 A 到产品 B 的功能迁移路径 → "如果你从 Cursor 迁移到 Copilot，需要适应的 5 个功能差异" | P2 |
| **PageRank 变体** | 哪家竞品在技术生态中被引用最多 → "行业影响力排名" | P2 |

**为什么当前阶段不着急**：comparison_matrix + SWOT + trends 已经覆盖比赛所需的对比分析。以上图算法在准确性上依赖大量数据，在可解释性上不如结构化对比表直观。

**答辩话术**："竞品分析本质上是异构图问题。当前我们用结构化 Schema（comparison_matrix）编码了图的节点和边，Reviewer 通过交叉验证给每条边赋置信度权重。如果未来升级到图数据库（Neo4j）+ GraphRAG，就可以用中心度算法自动发现行业关键节点，用社区检测自动识别市场阵营。"

### 6.10 交互性报告扩展（P2 展望）

> §3.7 Writer 已将报告从静态文件升级为前端交互式 ReportData。以下是时间充裕时可进一步扩展的交互能力。

| 功能 | 交互方式 | 体验价值 | 时机 |
|------|---------|---------|------|
| **Hover-to-source** | 鼠标悬停 `[3]` → 弹出小卡片：URL、抓取时间、置信度、交叉验证状态 | 不用跳转到报告末尾看来源 | P2 |
| **What-if 推演** | 报告内嵌输入框，用户输入假设 → 不走 Collector，直接在现有数据上推理 → 30 秒更新报告 | 从"过去发生了什么"升级为"如果我做 X，市场会怎么反应" | **已纳入 §3.5.7 P0** |
| **版本 Diff** | 对比两次分析报告 → 高亮变化行 → 结合 `product_baseline` 表自动标注"这 8 天发生了什么" | 持续监控场景的核心交互 | P2 |
| **一键导出幻灯片** | ReportData → PPTX（DF 已有 `ppt-generation` Skill），每章节一页，图表自动嵌入 | PM 拿着报告去汇报，PPT 是硬通货 | P2 |
| **语音批注** | 飞书 App 长按段落 → 语音输入 → 自动转文字 → 解析为 HITL 指令 | 移动端场景 | P2 |
| **协作评论线程** | 多人对同一段报告评论、讨论、决议 | 企业真实协作场景 | P2 |

---

## 七、答辩呈现设计 — 内部工作流可视化 `**[竞赛要求 R9, R10]**`

> 答辩不只是展示"用户看到了什么"，更要展示"系统内部发生了什么"。
> 评分标准 35%（多Agent协作与输出可信度）明确要求"DAG任务流转可视化、可追溯"；25%（技术深度）要求"每个Agent的Prompt/输入/输出/决策过程/Token消耗均有日志可查"。

### 7.1 双面板布局

```
┌──────────────────────────────────────────────────────────────┐
│                    答辩展示界面 (全屏)                         │
├──────────────────────────┬───────────────────────────────────┤
│                          │                                   │
│    👤 用户视角 (左 50%)   │    🔧 系统内部 (右 50%)            │
│                          │                                   │
│  ┌────────────────────┐  │  ┌─────────────────────────────┐  │
│  │ 输入区域            │  │  │  🗺 DAG 执行图 (实时高亮)     │  │
│  │ "帮我分析 Cursor    │  │  │                             │  │
│  │  vs Copilot..."    │  │  │   [Collector] ← 当前活跃     │  │
│  └────────────────────┘  │  │      ↓ 绿色流动边             │  │
│                          │  │   [Analyst]   ← 等待中       │  │
│  ┌────────────────────┐  │  │      ↓                       │  │
│  │ 进度条 + 状态文本    │  │  │   [Reviewer]  ← 等待中       │  │
│  │ "Analyst 正在生成   │  │  │      ↓                       │  │
│  │  SWOT 分析..."      │  │  │   [Writer]    ← 等待中       │  │
│  └────────────────────┘  │  └─────────────────────────────┘  │
│                          │                                   │
│  ┌────────────────────┐  │  ┌─────────────────────────────┐  │
│  │ 📊 报告输出          │  │  │ 📋 Agent 详情面板             │  │
│  │ (Markdown 渲染)     │  │  │ (点击 DAG 节点展开)           │  │
│  │                     │  │  │                             │  │
│  │ ## 执行摘要          │  │  │ ▸ System Prompt (可折叠)     │  │
│  │ ...                 │  │  │ ▸ 结构化输入 JSON             │  │
│  │                     │  │  │ ▸ 结构化输出 JSON             │  │
│  │                     │  │  │ ▸ Token: 12,450             │  │
│  │                     │  │  │ ▸ 耗时: 34.2s               │  │
│  └────────────────────┘  │  └─────────────────────────────┘  │
│                          │                                   │
├──────────────────────────┴───────────────────────────────────┤
│  📎 底部状态栏: 总 Token: 48,230 | 总耗时: 2:14 | 反馈轮次: 1/2 │
└──────────────────────────────────────────────────────────────┘
```

### 7.2 DAG 执行图（核心展示位）

DAG 图是评审第一眼看到系统内部的地方，需要做到：

**节点状态**：
- ⚪ 灰色 = 等待中
- 🟢 绿色 + 脉冲动画 = 正在执行
- ✅ 绿色实心 = 已完成（标注数据量）
- 🔴 红色 = 出错
- 🟡 黄色 = 等待 HITL 人工决策
- 🔄 蓝色虚线 = 反馈回环（Reviewer → Collector）

**边上标注**：
- 数据流向 + 数据量（如 "42 data points"、"2 gaps"）
- 反馈回环用虚线和回环箭头

**交互**：
- 点击任意节点 → 右侧面板展开该 Agent 的完整 Prompt/Input/Output
- 鼠标悬停边上 → 显示传递的结构化消息预览

### 7.3 Agent 详情面板（点击节点展开）

评审点击 DAG 上任意节点后，右侧展示：

```
┌───────────────────────────────────┐
│  Agent: Collector  ✅ 已完成       │
│  耗时: 38.5s | Token: 15,230      │
├───────────────────────────────────┤
│  📥 结构化输入 (来自 State)        │
│  ┌─────────────────────────────┐  │
│  │ {                           │  │
│  │   "task": "搜索 Cursor 的   │  │
│  │     功能特点和定价信息",      │  │
│  │   "query": "Cursor AI       │  │
│  │     editor features pricing"│  │
│  │ }                           │  │
│  └─────────────────────────────┘  │
│                                   │
│  📤 结构化输出                     │
│  ┌─────────────────────────────┐  │
│  │ {                           │  │
│  │   "data_points": [...],     │  │
│  │   "sources": ["cursor.com", │  │
│  │     "github.com/..."],      │  │
│  │   "confidence": 0.92        │  │
│  │ }                           │  │
│  └─────────────────────────────┘  │
│                                   │
│  🔧 使用的工具:                    │
│  • web_search × 3 (Tavily)        │
│  • web_fetch × 2 (Jina AI)        │
│                                   │
│  📎 溯源链接:                      │
│  • cursor.com/pricing → ✓         │
│  • github.com/getcursor/cursor → ✓│
└───────────────────────────────────┘
```

### 7.4 结构化消息流日志 `**[竞赛要求 R4]**`

Agent 间的通信必须是**结构化 JSON**（比赛明确要求），在界面上展示：

```
┌─────────────────────────────────────────────────┐
│  📨 Agent 间消息流                               │
├─────────────────────────────────────────────────┤
│                                                  │
│  Collector ──→ Analyst                           │
│  {"type": "collected_data", "data_points": 42,   │
│   "coverage": {"features": 0.9, "pricing": 1.0,  │
│   "users": 0.7}}                                 │
│                                                  │
│  Analyst ──→ Reviewer                            │
│  {"type": "analysis_result",                     │
│   "comparison_matrix": {...}, "swot": {...}}      │
│                                                  │
│  Reviewer ──→ Collector  🔄 反馈回环 #1           │
│  {"type": "gap_report", "gaps": [{               │
│    "type": "missing_data",                       │
│    "target": "Cursor enterprise pricing",        │
│    "severity": "critical"}]}                     │
│                                                  │
│  Collector ──→ Analyst  (第2轮)                   │
│  {"type": "re_collected_data", "data_points": 3,  │
│   "addresses_gaps": ["gap-001"]}                  │
│                                                  │
└─────────────────────────────────────────────────┘
```

这个日志直接对评价分标准里的"Agent 间采用结构化消息传递，非纯自然语言对话"。

### 7.5 溯源链视图（Traceability Viewer） `**[竞赛要求 R7]**`

报告中每条结论都可以点击，高亮显示其数据来源链：

```
报告中的结论:                                  溯源链:
┌──────────────────────────┐     ┌──────────────────────────┐
│ "Cursor Pro 定价 $20/月， │     │ cursor.com/pricing       │
│  提供免费 Hobby 版，      │ ←── │ ↓ 抓取时间: 2026-05-21   │
│  企业版 $40/用户/月"      │     │ ↓ Collector → Analyst    │
│                          │     │ ↓ Reviewer: ✅ 已验证     │
│ "Copilot Business $19/月"│ ←── │ github.com/features/...  │
│                          │     │ ↓ 抓取时间: 2026-05-21   │
│                          │     │ ↓ Collector → Analyst    │
│ "用户评价: Cursor 的 Tab  │     │ ↓ Reviewer: ✅ 已验证     │
│  补全比 Copilot 更准确"   │ ←── │ reddit.com/r/programming │
│                          │     │ ↓ 用户投票: 238↑          │
│                          │     │ ↓ Reviewer: ⚠ 单源未交叉  │
└──────────────────────────┘     └──────────────────────────┘
```

### 7.6 执行回放（答辩亮点）

整个执行过程可以**回放**——不是录屏，而是基于 LangGraph checkpoint 数据做一个时间轴滑块：

```
├──────●────────────●──────────●────────●────────●──────┤
0s    38s          1:12       1:45     2:08     2:14
      Collector    Analyst    Reviewer Writer   HITL
      完成         完成       发现2个   完成     approve
                             gap,打回
```

- 拖动滑块到任意时刻 → 系统内部状态回到那一刻
- 可以看到**反馈闭环真的发生了**（这是评审核心关注点）
- 不需要外部录屏工具，系统自带

### 7.7 Token 消耗与成本面板

底部状态栏旁边展示：

```
💰 Token 消耗:
  Collector: 15,230 in + 2,100 out = 17,330
  Analyst:   12,450 in + 3,800 out = 16,250
  Reviewer:   8,120 in + 1,500 out =  9,620
  Writer:     4,100 in + 2,400 out =  6,500
  ─────────────────────────────────────────
  总计: 49,700 tokens ≈ $0.05 (Doubao-Seed-2.0)
```

**答辩话术**："一次完整的竞品分析，成本不到 5 分钱，2 分钟完成。传统人工做同样的事情需要 2-3 天。"

### 7.8 技术实现路径

| 组件 | 实现方案 | 依赖 |
|------|---------|------|
| DAG 图渲染 | React + D3.js / ReactFlow | 轻量，MIT 协议 |
| 实时节点状态 | LangGraph `stream_mode=["values","updates","custom"]` + SSE | DF 已有 StreamBridge |
| Agent 详情 | React 组件 + JSON syntax highlight | 纯前端 |
| 消息流日志 | 从 State 中提取结构化 JSON，时间线展示 | 纯前端 |
| 溯源链 | `traceability_map` (state 字段) → 前端渲染 | 纯前端 |
| 执行回放 | LangGraph Checkpointer (SqliteSaver) → 读取 checkpoint 历史 | DF 已有 |

> **注意**：不用引入外部服务如 LangSmith。所有可观测数据利用 LangGraph 自带的 stream + checkpointer 即可，零额外依赖，比赛合规。

---

## 八、3 周开发计划（含答辩呈现）

### Week 1 (5/21 - 5/27): 普通模式完整链路 + 核心节点

| 任务 | 产出 | 优先级 |
|------|------|--------|
| 创建 CompetitionState（单层 TypedDict，含深度模式字段） | `competition/state.py` | P0 |
| 定义竞品知识 Schema（Pydantic: 功能树/定价/用户画像/来源） | `competition/schema.py` | P0 |
| 构建普通模式 StateGraph + 条件路由（含反馈闭环 + HITL） | `competition/graph.py`, `router.py` | P0 |
| 实现 Collector 节点 (多源搜索, 具体源编码时实测决定) | `competition/nodes/collector.py` | P0 |
| 实现用户声音聚合器 (G2/Reddit/GitHub 评论抓取+NLP) | `competition/nodes/collector.py` (voc 子模块) | P0 |
| 实现视频字幕提取工具 (YouTube/Bilibili → LLM 观点提取) | `competition/tools/video_source.py` | P1 |
| 实现 Analyst 节点 (多维对比+SWOT+趋势+可视化) | `competition/nodes/analyst.py` | P0 |
| 实现 Reviewer 节点 (交叉验证+scipy.stats+gap打回+飞书审批) | `competition/nodes/reviewer.py` | P0 |
| 实现 Writer 节点 (双视角MD+溯源地图) | `competition/nodes/writer.py` | P0 |
| 实现 HITL Gate 节点 (飞书审批卡片生成+interrupt/resume) | `competition/nodes/hitl_gate.py` | P0 |
| 4 个 Prompt 模板 | `competition/prompts/` | P0 |
| 可视化引擎 (雷达图/热力图/时间线/情绪图) | `competition/visualization.py` | P0 |
| 单元测试（图可编译 + 路由正确性 + 反馈闭环） | `tests/test_competition_graph.py` | P0 |

### Week 1.5 (5/27 - 5/30): 深度模式 + 飞书集成

| 任务 | 产出 | 优先级 |
|------|------|--------|
| 实现深度模式图段 (deep_* 5 个节点) | `competition/graph.py` (深度段) | P1 |
| 深度 Collector: 基于 knowledge_gaps 增量采集 | `competition/nodes/deep_collector.py` | P1 |
| 深度 Reviewer: 放宽轮数，更深验证 | `competition/nodes/deep_reviewer.py` | P1 |
| 实现 feishu_delivery 节点 (docs +create + Bot 通知) | `competition/nodes/feishu_delivery.py` | P1 |
| 飞书 Bot 配置 + 联通测试 (DF 已有通道) | `config.yaml` channels.feishu | P1 |
| 飞书审批 HITL 集成测试 | 集成测试 | P1 |

### Week 2 (5/27 - 6/3): 前端 + 可观测 + 飞书集成

| 任务 | 产出 | 优先级 |
|------|------|--------|
| 前端 UI 框架搭建 (Gradio 或 Next.js) | `frontend/` 或 `app/` | P0 |
| 双面板布局 (左=用户视角, 右=系统内部) | 前端组件 | P0 |
| DAG 执行图 (ReactFlow/D3.js, 节点高亮+边动画) | 前端组件 | P0 |
| Agent 详情面板 (Prompt/Input/Output/Token 展示) | 前端组件 | P0 |
| 结构化消息流日志 (JSON 时间线) | 前端组件 | P0 |
| 溯源链视图 (点击报告结论 → 展示来源链) | 前端组件 | P0 |
| 执行回放控件 (基于 Checkpoint 的时间轴滑块) | 前端组件 | P1 |
| 报告查看页面（双视角切换 + Markdown 渲染） | 前端组件 | P0 |
| SSE 实时流消费 (LangGraph stream → 前端状态更新) | Gateway + 前端 | P0 |
| 飞书 Bot 配置 + 联通测试 (DF 已有通道) | `config.yaml` channels.feishu | P1 |
| 飞书审批 HITL Gate (审批卡生成+回调resume) | `competition/nodes/hitl_gate.py` | P1 |
| Gateway API (POST /analyze, WS /stream, GET /report) | `app/gateway/routers/competition.py` | P0 |
| 集成测试 | `tests/test_competition_e2e.py` | P0 |

### Week 3 (6/3 - 6/10): 打磨 + 答辩准备

| 任务 | 产出 | 优先级 |
|------|------|--------|
| 双角色报告模板完善 | PM 报告 + 创业者报告 | P0 |
| 错误恢复 + 降级机制完善 | 异常处理全覆盖 | P0 |
| 数据脱敏处理 | 用户数据脱敏 | P0 |
| 演示场景录制 (AI 编程工具竞品分析) | Demo 录屏 | P0 |
| README + 架构图 + 部署说明 | 项目文档 | P0 |
| 答辩 PPT + 演示流程设计 | 答辩材料 | P0 |
| (可选) 竞品分析历史对比 (DF Memory) | `competition/memory/` | P2 |

---

## 九、待确认决策

1. **演示场景**：建议选"AI 编程工具竞品分析"（Cursor vs Copilot vs Windsurf vs Claude Code）——数据好找、维度清晰、评审有体感。是否同意？

2. **数据源优先级**：编码时按实际速度和质量决定哪些源进普通模式、哪些源进深度模式。不提前定死。原则是"普通模式不阉割，深度模式不加限制"。

3. **前端选型**：Gradio（快速出活）vs Next.js（复用项目现有前端经验）。倾向哪个？

4. **Agent 实现方式**：复用 DeerFlow 的 `SubagentExecutor`（每个 Agent 作为独立子代理运行，可观测性+错误隔离更好），还是直接在节点函数内用 LangChain `create_agent`（更简单）？

5. **演示形式**（会议纪要建议）：推荐**录屏**演示，可单独展示采集能力。需提前准备 Demo 录制方案。

6. **现场演示**（会议纪要）：可在自己机器上现场演示，解决网站部署资源问题。建议准备本地运行 + 录屏双保险。

---

## 十、参考信息

### 飞书文档

- 开题材料: [【CIS】AI 全栈项目挑战赛开题材料](https://bytedance.larkoffice.com/wiki/Y7Qkw7TvYiwRDzkKxgycJhFOnuc)
- 会议纪要: [智能纪要：【CIS】AI挑战赛开题讲解 2026年5月20日](https://bytedance.larkoffice.com/docx/EesXdi4C4oM400xK91zcFtsWnvh)

### 群聊补充信息

- 开源库只能用 MIT / Apache 2.0 / BSD 协议
- Agent 数量非定死，可以用主 Agent + tool/skill/subagent 形式
- 框架不限制，可以手搓
- 用户群体建议聚焦：产品经理 + 创业者/项目负责人
- 问卷/访谈：从生成问卷到完全自动化找真实用户都可以

### 会议纪要关键补充（2026-05-20 答疑环节）

| 要点 | 原文/摘要 | 我们的应对 |
|------|---------|-----------|
| 提交材料 | 会提供具体说明和评分细则文档 | 等待后续通知 |
| 现场演示 | 建议录屏，可单独展示采集能力 | §8 已加入演示准备 |
| 可用 LangSmith | 收集 agent trace → 多 agent 执行过程可查 | 我们不用外部服务，用 LangGraph 自带 stream + checkpointer（更可控、零额外依赖、比赛合规） |
| 细分方向 | 可以做，但系统需具备扩展性 | 双模架构 + config.yaml workflows 切换（§3.2） |
| 数据脱敏 | 访谈数据需脱敏 | §3.10.3 已完整设计 |
| 并发 | 能做到更好，非强制 | Send API Fan-out 并行采集（§3.4） |
| 前端展示 | 推荐做前端，本地机器演示 | §7 双面板 DAG 可视化 |

### 关键 API Key

- Doubao-Seed-2.0-lite: EP `ep-20260514111325-xjmj7` / APIKEY: 已提供
