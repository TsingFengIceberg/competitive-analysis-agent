# CI-Agent 竞赛要求 TODO

> 逐条提取自飞书文档「[【CIS】AI 全栈项目挑战赛开题材料](https://bytedance.larkoffice.com/wiki/Y7Qkw7TvYiwRDzkKxgycJhFOnuc)」和「[智能纪要：【CIS】AI挑战赛开题讲解 2026年5月20日](https://bytedance.larkoffice.com/docx/EesXdi4C4oM400xK91zcFtsWnvh)」。
> 编码时每条完成后打 ✅。

---

## 一、课题介绍 — 5 项核心功能（开题材料 §2）

### 1.1 角色 Agent

- [x] **采集 Agent**：多源数据抓取 + 问卷设计 + 问卷调研 + 用户访谈
  → [PLAN §3.3 Collector 双轨采集](../COMPETITION_PLAN.md#33-4-个-agent-角色定义)
  → [PLAN §4.4 VoC Aggregator](../COMPETITION_PLAN.md#44-用户声音聚合器-voice-of-customer-aggregator-竞赛要求-r2)

- [x] **分析师 Agent**：结构化整理、多维对比 + 预测推演
  → [PLAN §3.3 Analyst](../COMPETITION_PLAN.md#33-4-个-agent-角色定义)
  → [PLAN §3.5 Analyst 分析规范（7 子节）](../COMPETITION_PLAN.md#35-analyst-分析规范)
  → [PLAN §3.5.7 What-if 预测推演](../COMPETITION_PLAN.md#357-竞品分析的三个时间维度)

- [x] **报告撰写 Agent**：ReportData 交互报告 + 双视角 + 溯源 + 导出
  → [PLAN §3.3 Writer](../COMPETITION_PLAN.md#33-4-个-agent-角色定义)
  → [PLAN §3.7 Writer 报告规范（6 子节）](../COMPETITION_PLAN.md#37-writer-报告规范)

- [x] **质检 Agent**：事实校验
  → [PLAN §3.3 Reviewer](../COMPETITION_PLAN.md#33-4-个-agent-角色定义)
  → [PLAN §3.6 Reviewer 审阅清单（8 种判定规则）](../COMPETITION_PLAN.md#36-reviewer-审阅清单与判定规则-竞赛要求-r5)

- [x] **职责边界明确无重叠**（判标 §4 35%）
  → [PLAN §3.3 角色定义表](../COMPETITION_PLAN.md#33-4-个-agent-角色定义)

### 1.2 知识结构化

- [x] **功能树 Schema 定义 + 强制校验**
  → [PLAN §3.10 FeatureTree](../COMPETITION_PLAN.md#310-竞品知识-schemapydantic-强制校验)
  → [PLAN §3.11 Schema 强制校验链](../COMPETITION_PLAN.md#311-schema-强制校验链竞赛要求-r3-r8)

- [x] **定价模型 Schema 定义 + 强制校验**
  → [PLAN §3.8 PricingModel](../COMPETITION_PLAN.md#310-竞品知识-schemapydantic-强制校验)

- [x] **用户画像 Schema 定义 + 强制校验**
  → [PLAN §3.8 UserPersona](../COMPETITION_PLAN.md#310-竞品知识-schemapydantic-强制校验)

- [x] **输出严格符合 Schema，字段完整格式一致**（判标 §4 35%）
  → [PLAN §3.9 model_validate() + 重试 + 降级](../COMPETITION_PLAN.md#311-schema-强制校验链竞赛要求-r3-r8)

### 1.3 协作与反馈闭环

- [x] **Agent 间结构化消息传递（function calling / Schema），非纯自然语言**（判标 §4 35%）
  → [PLAN §3.13 CollectedDataPoint / ReviewGap](../COMPETITION_PLAN.md#313-agent-间结构化通信协议-竞赛要求-r4)

- [x] **质检 Agent 可将不足打回采集 Agent，DAG 式任务流转**
  → [PLAN §3.8 DAG 工作流](../COMPETITION_PLAN.md#38-dag-工作流)
  → [PLAN §3.14 route_after_reviewer](../COMPETITION_PLAN.md#312-路由逻辑普通模式--深度模式流水线)

- [x] **反馈闭环真实可触发，重做后输出有改善（非伪闭环）**（判标 §4 35%）
  → [PLAN §3.14.1 改善度量](../COMPETITION_PLAN.md#3121-反馈闭环改善追踪竞赛要求-r5-r6)

- [x] **DAG 任务流转可视化、可追溯**（判标 §4 35%）
  → [PLAN §7.2 DAG 执行图](../COMPETITION_PLAN.md#72-dag-执行图核心展示位)

- [x] **编排框架（LangGraph）使用合理**
  → [PLAN §3.14 graph.py 构建](../COMPETITION_PLAN.md#312-路由逻辑普通模式--深度模式流水线)

### 1.4 信息溯源

- [x] **每条分析结论标注数据来源**
  → [PLAN §3.9 traceability_map](../COMPETITION_PLAN.md#39-competitionstate-设计)

- [x] **报告正文内联溯源标注 `[n]`**
  → [PLAN §3.3 Writer 描述](../COMPETITION_PLAN.md#33-4-个-agent-角色定义)

- [x] **支持一键跳转原始数据源**（判标 §4 35%）
  → [PLAN §7.5 溯源链视图](../COMPETITION_PLAN.md#75-溯源链视图traceability-viewer-竞赛要求-r7)

### 1.5 可观测

- [x] **每个 Agent 的 Prompt 可查**（判标 §4 25%）
  → [PLAN §7.3 Agent 详情面板](../COMPETITION_PLAN.md#73-agent-详情面板点击节点展开)

- [x] **每个 Agent 的输入/输出可查**（判标 §4 25%）
  → [PLAN §7.3 Agent 详情面板](../COMPETITION_PLAN.md#73-agent-详情面板点击节点展开)

- [x] **每个 Agent 的决策过程可追溯**（判标 §4 25%）
  → [PLAN §7.4 消息流日志](../COMPETITION_PLAN.md#74-结构化消息流日志-竞赛要求-r4)

- [x] **Token 消耗有日志可查**（判标 §4 25%）
  → [PLAN §7.7 Token 面板](../COMPETITION_PLAN.md#77-token-消耗与成本面板)

---

## 二、判断标准 — 技术深度与工程完整度（25%）

- [x] **端到端链路完整：数据采集 → Agent 编排 → 后端接口 → 前端交互，可现场演示**
  → [PLAN §3.5 全链路](../COMPETITION_PLAN.md#38-dag-工作流)
  → [PLAN §8 Week 1+2](../COMPETITION_PLAN.md#八3-周开发计划含答辩呈现)

- [x] **上下文管理有明确策略：超长上下文分片**
  → [PLAN §3.15.1 幻觉抑制](../COMPETITION_PLAN.md#3151-幻觉抑制三策略竞赛要求-r12)

- [x] **错误恢复有明确策略**
  → [PLAN §3.15.5 超时重试与降级](../COMPETITION_PLAN.md#3155-超时重试与降级-竞赛要求-r13)

- [x] **幻觉抑制有明确策略：自一致性校验**
  → [PLAN §3.15.1 幻觉抑制](../COMPETITION_PLAN.md#3151-幻觉抑制三策略竞赛要求-r12)

- [x] **幻觉抑制有明确策略：引用强制（每条声明必须有活跃 URL）**
  → [PLAN §3.13.1 引用强制](../COMPETITION_PLAN.md#3151-幻觉抑制三策略竞赛要求-r12)

- [x] **系统稳定性：异常处理**
  → [PLAN §3.14 error_handler 路由](../COMPETITION_PLAN.md#312-路由逻辑普通模式--深度模式流水线)

- [x] **系统稳定性：超时重试（指数退避，最多 3 次）**
  → [PLAN §3.15.5 超时重试](../COMPETITION_PLAN.md#3155-超时重试与降级-竞赛要求-r13)

- [x] **系统稳定性：降级机制（备选数据源、部分结果继续）**
  → [PLAN §3.15.5 降级策略](../COMPETITION_PLAN.md#3155-超时重试与降级-竞赛要求-r13)

- [x] **技术方案有独特或前瞻性思考**
  → [PLAN §6 差异化创新](../COMPETITION_PLAN.md#六核心差异化创新点总结-竞赛要求-r14)
  - [x] 来源可信度动态演化
  - [x] 字节生态深度集成
  - [x] 双视角报告

---

## 三、判断标准 — 业务价值与产品体验（20%）

- [x] **相比传统人工，效率可量化提升（系统耗时 vs 2-3 天人工）**
  → [PLAN §3.15.4 效率指标](../COMPETITION_PLAN.md#3154-业务指标可量化追踪竞赛要求-r15)

- [x] **覆盖度可量化提升**
  → [PLAN §3.15.4 覆盖率指标](../COMPETITION_PLAN.md#3154-业务指标可量化追踪竞赛要求-r15)

- [x] **一致性可量化提升（交叉验证率）**
  → [PLAN §3.15.4 交叉验证率](../COMPETITION_PLAN.md#3154-业务指标可量化追踪竞赛要求-r15)

- [x] **贴合企业竞品分析真实工作流**
  → [PLAN §5.7 交互式报告编辑](../COMPETITION_PLAN.md#57-人对报告的细粒度交互式编辑p0--答辩核心交互-竞赛要求-r16)

- [x] **具备可落地性与可扩展性（换行业/换竞品对象）**
  → [PLAN §3.2 双模架构](../COMPETITION_PLAN.md#32-双模定位对比)

- [x] **交互设计流畅：报告查看**
  → [PLAN §7.1 用户视角面板](../COMPETITION_PLAN.md#71-双面板布局)

- [x] **交互设计流畅：溯源跳转**
  → [PLAN §7.5 溯源链视图](../COMPETITION_PLAN.md#75-溯源链视图traceability-viewer-竞赛要求-r7)

- [x] **交互设计流畅：人工介入修正**
  → [PLAN §5.7 交互式编辑](../COMPETITION_PLAN.md#57-人对报告的细粒度交互式编辑p0--答辩核心交互-竞赛要求-r16)

- [x] **交互设计流畅：Agent 决策回放**
  → [PLAN §7.6 执行回放](../COMPETITION_PLAN.md#76-执行回放答辩亮点)

- [x] **业务闭环关键指标：准确率**
  → [PLAN §3.15.4 指标表](../COMPETITION_PLAN.md#3154-业务指标可量化追踪竞赛要求-r15)

- [x] **业务闭环关键指标：覆盖率**
  → [PLAN §3.15.4 信息覆盖率](../COMPETITION_PLAN.md#3154-业务指标可量化追踪竞赛要求-r15)

- [x] **业务闭环关键指标：人工修正率**
  → [PLAN §3.15.4 人工修正率](../COMPETITION_PLAN.md#3154-业务指标可量化追踪竞赛要求-r15)

---

## 四、判断标准 — 代码质量与文档（10%）

- [x] **代码风格规范、模块化清晰、注释充分**
  → CLAUDE.md §5 编码规范

- [x] **README 齐全**
  → 根目录 README.md

- [x] **架构图**
  → [PLAN §3.6 DAG 流程图](../COMPETITION_PLAN.md#38-dag-工作流)

- [x] **Agent 角色与协议文档**
  → [PLAN §3.3 角色定义](../COMPETITION_PLAN.md#33-4-个-agent-角色定义)
  → [PLAN §3.11 通信协议](../COMPETITION_PLAN.md#313-agent-间结构化通信协议-竞赛要求-r4)

- [x] **部署说明**
  → README.md 快速开始（编码完成后补充）

- [x] **Git 提交记录规范，分支管理清晰**
  → CLAUDE.md §6 提交规范

- [x] **TRAE 等 AI 编程工具使用痕迹清晰**
  → Git 提交记录体现

---

## 五、判断标准 — 合规、材料与答辩（10%）

- [x] **采集合规：遵守 robots.txt**
  → [PLAN §3.15.2 robots.txt 预检](../COMPETITION_PLAN.md#3152-采集合规竞赛要求-r17)

- [x] **采集合规：遵守服务条款，有明确授权或公开声明**
  → [PLAN §3.13.2 来源声明](../COMPETITION_PLAN.md#3152-采集合规竞赛要求-r17)

- [x] **数据脱敏：问卷/访谈数据脱敏，无敏感信息泄露**
  → [PLAN §3.15.3 数据脱敏](../COMPETITION_PLAN.md#3153-数据脱敏竞赛要求-r18)

- [x] **工具/模型/数据使用符合比赛规范**
  → 开源库 MIT 协议

- [x] **方案文档完整**
  → COMPETITION_PLAN.md

- [x] **演示视频/录屏**
  → [PLAN §8 Week 3](../COMPETITION_PLAN.md#八3-周开发计划含答辩呈现)

- [x] **代码库齐全规范**
  → GitHub CI-Agent 仓库

- [x] **答辩讲解清晰有条理**
  → [PLAN §7 答辩呈现设计](../COMPETITION_PLAN.md#七答辩呈现设计--内部工作流可视化-竞赛要求-r9-r10)

---

## 六、会议纪要补充（2026-05-20 答疑）

- [x] **细分方向可做，系统需具备扩展性**
  → [PLAN §3.2 双模 + config.yaml workflows](../COMPETITION_PLAN.md#32-双模定位对比)

- [x] **并发处理**（能做到更好，非强制）
  → [PLAN §3.5 Send API Fan-out](../COMPETITION_PLAN.md#38-dag-工作流)

- [x] **推荐前端展示页面，本地机器演示**
  → [PLAN §7 答辩呈现](../COMPETITION_PLAN.md#七答辩呈现设计--内部工作流可视化-竞赛要求-r9-r10)

- [x] **演示建议录屏，可单独展示采集能力**
  → [PLAN §9 决策 5](../COMPETITION_PLAN.md#九待确认决策)

- [x] **可用 LangSmith 收集 trace → 我们用 LangGraph 原生方案代替**
  → [PLAN §7.8 技术实现路径](../COMPETITION_PLAN.md#78-技术实现路径)

---

## 七、前端展示（开题材料 + 会议纪要）

> **选型已定**：嵌入 DF 现有 Next.js 前端，新增 `/competition` 路由。
> 后端数据提取层已就绪（`dag.py` / `observability.py`），前端只做 JSON→UI 渲染。
> DF 复用：构建链（next build）、SSE client、shadcn/ui 组件、nginx 部署。

### 核心（P0，7 项）

- [x] **DAG 执行图**（ReactFlow 节点 5 状态高亮 + 边动画 + 反馈回环虚线）
  → 后端：`dag.py::get_dag_state()`（✅ 已就绪，25 tests）
  → 前端：`competition/dag-graph.tsx`

- [x] **Agent 详情面板**（点击 DAG 节点 → 展开 Prompt/Input/Output/Tools）
  → 后端：`observability.py::get_agent_detail()`（✅ 已就绪，13 tests）
  → 前端：`competition/agent-detail-panel.tsx`

- [x] **结构化消息流日志**（6 边 JSON 时间线，反馈回环红色高亮）
  → 后端：`observability.py::get_message_flow()`（✅ 已就绪）
  → 前端：`competition/message-flow-timeline.tsx`

- [x] **溯源链视图**（hover 报告 `[n]` → 弹出 source card：URL/时间/置信度/验证状态）
  → 后端：`observability.py::get_traceability_chain()`（✅ 已就绪）
  → 前端：`competition/source-card.tsx`

- [x] **ReportData 交互报告渲染**（章节折叠 + What-if 输入框内嵌）
  → 后端：Writer 输出 `ReportData` JSON（✅ 已就绪）
  → 前端：`competition/report-renderer.tsx`

- [x] **HITL 审批卡片**（4 按钮 + 自由文本输入 + 超时倒计时）
  → 后端：`hitl_gate.py::build_approval_card()`（✅ 已就绪）
  → 前端：`competition/hitl-card.tsx`

- [x] **双视角切换**（PM / 创业者 一键切换，重调 Writer）
  → 前端：`competition/persona-switcher.tsx`

### 外围（P1/P2，3 项）

- [x] **执行回放**（基于 Checkpoint 的时间轴滑块，拖动回到任意时刻）
  → 前端：`competition/replay-slider.tsx`（P1）

- [x] **Token 消耗面板**（底部状态栏：per-Agent Token 统计）
  → 前端：`competition/token-panel.tsx`（P2）

- [x] **报告导出按钮**（Markdown / JSON 下载，前端按钮 + 后端 /export 端点；PDF/PPTX 留作答辩展望）
  → 前端：导出 API 调用（P2）

---

## 八、业务层持久化（PLAN §3.14）

- [x] **source_credibility 表**（来源可信度跨 run 动态演化）
  → [PLAN §3.14.2](../COMPETITION_PLAN.md#3142-sourcecredibility-表--来源可信度动态演化)

- [x] **product_baseline 表**（竞品变更检测基线）
  → [PLAN §3.14.3](../COMPETITION_PLAN.md#3143-productbaseline-表--竞品变更检测基线)

- [x] **analysis_history 表**（分析历史索引）
  → [PLAN §3.14.4](../COMPETITION_PLAN.md#3144-analysishistory-表--分析历史索引)

- [x] **competition/db.py**（SQLite 业务表读写工具函数）
  → [PLAN §3.14](../COMPETITION_PLAN.md#314-数据持久化架构)

---

## 九、分支树 (BranchTree) + CheckpointOps — Agent 工作流分支管理 `**[核心差异化 P0]**`

> **设计更新（2026-05-29）**：继承体系从"两层三级"修正为**单层两级**。Agent 执行分支（操作 LangGraph checkpoint tree）与用户交互分支（操作 BranchTree）是两个独立树结构，不应共享基类。新增 **CheckpointOps** 独立工具层——封装 LangGraph checkpoint 裸 API 为便捷原子操作，BranchTree 通过调用 CheckpointOps（而非直接调 LangGraph API）来获取/恢复 state。
> 
> 详见 [PLAN §3.8](../COMPETITION_PLAN.md#38-分支树-branchtree--agent-工作流的-git-核心差异化) 和 [PLAN §6.6](../COMPETITION_PLAN.md#66-分支树-branchtree--agent-工作流的-git-核心差异化)。

### 继承体系设计（单层两级）

- [x] **BranchTree 抽象基类设计**（`tree.py`）：snapshot / fork / restore / lineage / to_dict 树操作接口
  → PLAN §3.8.8 完整定义了单层两级继承模型
- [x] **BranchTree 实现**（`tree.py`）：纯树算法 + 依赖注入 CheckpointOps + MetadataStore (256 行)
- [x] **_serialize / _deserialize 抽象方法**：子类各自实现——DeliverableTree 存完整 CompetitionState JSON，ConversationTree 存 messages

### 子类

- [x] **DeliverableTree（报告/可交付物版本分支，P0）**：当前 `competition.py` + `page.tsx` 已实现的核心功能
  → state = report_data + analysis_result + collected_data + hitl_decision + metadata
- [x] **ConversationTree（对话分支，P1）**：state = LangGraph messages，用户编辑历史消息 → 新分支 (62 行)

### CheckpointOps — 独立工具层 `**[新增]**`

> 定位：独立的工具库（不是 BranchTree 子类，不是树）。封装 LangGraph checkpoint 裸 API 为应用层友好的原子操作。BranchTree 通过调用 CheckpointOps 来跟 LangGraph 交互，实现依赖倒置。

- [x] **需求调研**：确认 PyPI 7 个 langgraph-checkpoint-* 包全是存储后端，无操作封装层；DeerFlow 仅工厂函数；LangGraph JS SDK 有 getBranchSequence 但 Python 端无等价物 → **真正的生态空白**
- [x] **隐式 Fork 机制分析**：LangGraph pregel loop 在检测到时间旅行（`is_time_traveling=True`）且非 update/fork source 时自动创建 `source: "fork"` checkpoint — 不需要我们实现 fork，只需封装
- [x] **CheckpointOps 核心类**（`checkpoint_ops.py`）(313 行)：
  - 读: `get_state()` / `get_history()` / `latest()` / `build_tree()` / `lineage()` / `children()` / `is_fork_point()`
  - 写: `fork()` / `update_state()`
  - 管理: `tag()` / `list_tags()` / `restore_to_tag()`
- [x] **便捷度证明**：对比裸调 LangGraph API vs CheckpointOps 封装，写进设计文档

### Core 层（`deerflow/branchtree/`）

- [x] **BranchNode 数据结构**（`node.py`）：node_id / parent_id / checkpoint_id / metadata / children
  → 改为存 checkpoint_id 引用而非完整 state（完整 state 由 LangGraph 管理）
- [x] **BranchTree 核心类**（`tree.py`）：snapshot / fork / restore / lineage / to_dict — 依赖注入 CheckpointOps (256 行)
- [x] **节点 Diff**（`diff.py`, P2）：两个快照的 state 差异计算 + 报告变化高亮 (143 行)

### Adapter 层

- [x] **LangGraph State → Snapshot 转换**：`_reanalyze_sync` 中保存 checkpoint_id 引用到 history
- [x] **Snapshot → LangGraph State 恢复**：`submit_decision` 中 fork 逻辑恢复历史版本 state
- [x] **Fork parent 追踪**：`_fork_parent_version` 标记确保 fork 分支正确挂载在源节点下
- [x] **独立 adapter.py**：将当前内联在 `competition.py` 中的转换逻辑抽取为 `BranchTreeAdapter` (165 行)

### Persistence 层

- [x] **branch_snapshots 表**（SQLite）：version / thread_id / parent_version / checkpoint_id / action / is_approved / metadata_json
  → 改为只存 checkpoint_id 引用 + 业务 metadata，完整 state 由 LangGraph 管理（避免重复存储）(store.py 179 行)
- [x] **BranchTree.save() / .load()**：`store.py` 实现序列化/反序列化
- [x] **已批准快照持久化**：`_save_to_db` 将 approved 报告写入 `analysis_history` 表

### 前端可视化

- [x] **BranchTree React 组件**：Unicode tree-line 渲染（├ └ │ ○）+ 节点点击查看 + 操作图标
- [x] **历史版本 HITL 操作**：从任意历史节点打开 HITL 面板（紫色边框 + "🌿 从 vX 分支" 提示）
- [x] **分支 fork 提交**：`fork_version` 参数传递给后端，自动创建新分支
- [x] **树节点 hover 预览**：悬停节点 → 弹出报告摘要卡片（已实现：报告标题、产品、指标、时间戳）
- [x] **分支合并**：选择两个分支节点 → 调用 LLM 合并各自的优点生成新版本 (merge.py 169 行，P2 前瞻已提前实现)

### Agent Git 论文参考（P2 前瞻，不影响 BranchTree 继承体系）

> Agent Git 操作的是 LangGraph checkpoint 层，与 BranchTree（Data 粒度用户层）是不同层级。如需扩展 Agent 执行层分支探索，在 CheckpointOps 上加操作语义即可。

- [x] **论文分析**：三层架构（External/Internal Session / Session History）可映射到 thread_id / node / lineage
- [x] **CheckpointOps Agent 扩展（P2）**：在 CheckpointOps 上增加 Agent 执行层的操作语义（自动分支探索/A/B 测试/cherry-pick/auto_merge），AgentBranchOps 类已实现 (checkpoint_ops.py)

### 文档

- [x] **PLAN §3.8.3 双层树架构**：BranchTree + LangGraph Checkpoint Tree + CheckpointOps 协作关系图
- [x] **PLAN §3.8.8 继承体系**：单层两级（BranchTree → DeliverableTree / ConversationTree）+ 勘误说明
- [x] **PLAN §3.8.9 Agent Git 论文参考**：定位为 LangGraph checkpoint 层工具链，不影响 BranchTree 继承
- [x] **PLAN §3.8.10 CheckpointOps**：完整 API 设计 + 隐式 fork 机制讲解 + 便捷度对比表 + 生态空白论证
- [x] **PLAN §3.8.11 差异化亮点**：6 条更新（含双树架构 + CheckpointOps 生态空白 + 依赖倒置）
- [x] **PLAN §6.6 差异化创新**：BranchTree + CheckpointOps 列为最核心技术创新点
- [x] **CLAUDE.md 目录结构**：更新为 `deerflow/branchtree/` 模块 + CheckpointOps

---

## 十、增强展望（P2，答辩口头提）

- [x] **图算法扩展**（中心度/社区检测/路径分析/PageRank） — `graph_algorithms.py` 已实现：度中心度、介数中心度、接近中心度、PageRank、Louvain 社区检测、全对最短路径、hub 识别、from_collected_data 构建
  → [PLAN §6.9](../COMPETITION_PLAN.md#69-竞品分析的本质是图问题p2-扩展展望)

- [x] **交互性报告扩展**（Hover-to-source/版本Diff/语音批注/协作评论） — SourceCard hover 溯源卡片 + data-trace-id 属性 + VersionDiff 版本对比组件 已实现
  → [PLAN §6.10](../COMPETITION_PLAN.md#610-交互性报告扩展p2-展望)

---

## 十一、产品名称解析 v3 管道 + 前端优化（2026-06-03）

### 11.1 v3 语义提取管道

- [x] **LLM 语义提取优先**（唯一语义步骤）：`_llm_extract_products()` 多轮 LLM 提取竞品名
  → [competition.py](../backend/app/gateway/routers/competition.py#L141-L170)
- [x] **Search 搜索验证兜底**：`_verify_products_via_search()` 并行搜索 + LLM 语义裁决
  → [competition.py](../backend/app/gateway/routers/competition.py#L225-L317)
- [x] **LLM Judge 一次裁决所有候选**：`_llm_judge_and_correct()` 综合 query 上下文 + 搜索标题
  → [competition.py](../backend/app/gateway/routers/competition.py#L320-L463)
- [x] **删除别名表 + 所有硬编码规则**：C1/C2/C3, alias table, canonical name extraction, string matching
- [x] **双重搜索策略**：引号上下文搜索 + 无引号独立搜索（搜索引擎自动纠错 Noton→Notion）

### 11.2 性能优化

- [x] **并行搜索**：`ThreadPoolExecutor` 并发搜索所有候选，4 候选 ~80s→~20s
  → [competition.py](../backend/app/gateway/routers/competition.py#L225)
- [x] **ProductJudge 保持 thinking 模式**：尝试 `disable_thinking` 导致 Doubao 返回空内容，回退

### 11.3 前端体验优化

- [x] **竞品名自动提取**：前端输入框改为可选，LLM 从自然语言 query 提取
- [x] **后端立即响应**：`/analyze` 立即返回 thread_id，解析+运行在后台线程
- [x] **前端耗时计时器**：Header 显示实时已用时间（每秒刷新），读取 `created_at`

---

## 十二、竞品变更检测：字段级四步漏斗（2026-06-04）`[延后]`

> ⚠️ **暂缓实施**。答辩前优先补前瞻性技术方向和问卷/访谈能力。答辩后如有时间再启动。
> 设计原则：低成本、低误报、定向精准。不做全量重跑，做字段级对账。
> 详细设计见 [PLAN §5.3](../COMPETITION_PLAN.md#53-竞品变更检测--飞书通知p1)

### 12.1 `product_baseline` 表扩展

- [ ] **扩展基线条目字段**：`search_query`、`evidence_snippet`、`value_type`（numeric/semver/boolean/enum）、`etag`
  → 每个条目录入时自带可重放的精准搜索词
- [ ] **自动入库**：分析完成后从 `collected_data` 提取可定量追踪的事实写入 baseline

### 12.2 四步漏斗检测流程

- [ ] **Step 1 URL 存活检查**：HEAD `evidence_urls` → ETag/Last-Modified/Content-Length 对比 → 不变则跳过（0 token）
- [ ] **Step 2 定向字段提取**：用存储的 `search_query` 搜 5 条 → LLM 只提取目标字段（max_tokens=50，~200 token）
  → 提示词三选一：UNCHANGED / 新值 / UNKNOWN
- [ ] **Step 3 交叉验证**：换同义 search query 重查 → 两轮一致才确认（仅 Step 2 发现变化时触发，~300 token）
- [ ] **Step 4 持久性确认**：标记 pending，24h 后重检 → 仍一致才推送（过滤促销/A/B 测试临时变体）

### 12.3 通知 + 降本

- [ ] **飞书 Bot 推送**：变更摘要 + evidence_snippet 前后对比 + 一键重分析入口
- [ ] **批量检测**：15 个检测点一次 LLM 调用完成（~500 token vs. 15 次 × 200）
- [ ] **事件触发优先**：GitHub Release / Blog RSS 有新条目 → 立即触发（零成本，比定时盲扫精准）
- [ ] **夜间降频**：周末/夜间 1 次/天，工作日白天 2 次/天
- [ ] **URL 长缓存**：etag 不变 → 标记 stale → 检测间隔拉长到 3 天

### 12.4 成本基线

- [ ] **日成本 ~815 token**（3 竞品 × 5 属性 = 15 检测点，对比单次完整分析 115K token = 0.7%）
- [ ] **误报率目标 <5%**（四道防线：URL 未变 / 字段未改 / 单次搜索偶然性 / 临时变体）

---

## 十三、前瞻性技术方向（2026-06-04，源自开题材料评分维度二 25%）

> 开题材料原文：「技术方案有独特或前瞻性思考（如自适应任务拆分、Agent 自评估、动态 Schema 演化）」
> 三个方向我们目前均未覆盖，答辩前至少各落地一个可演示的最小版本。

### 13.1 自适应任务拆分

- [x] **Query 复杂度评估**：根据 query 中的竞品数量、关键词（深度/全面/预测/战略）、长度自动判定 quick/standard/deep
  → 位置：`competition.py:155` `_assess_complexity()` — 启发式评估，零额外 LLM 调用
  → 例："对比 Slack 和 飞书" → quick 模式；"分析全球 CRM 市场 Top 5" → deep 模式
- [x] **动态搜索预算分配**：Collector 根据 complexity 调整搜索词数、fetch 深度、结果数
  → quick: 2 类别(功能+定价) × 1 fetch, ~15K tokens
  → standard: 4 类别 × 2 fetch, ~30K tokens
  → deep: 4 类别 + 3 额外深度查询/产品 × 3 fetch, ~60K tokens
  → 位置：`collector.py:468` `COMPLEXITY_CONFIG` + `search.py:707` `build_search_queries(complexity=)`
- [ ] **增量 vs 全量判断**：如果 7 天内已有同产品分析 → 增量更新而非全量重跑（需要跨 session 历史查询，暂延后）

### 13.2 Agent 自评估

- [x] **Collector 自评估**：采集完成后自评覆盖率（每个产品 × 每个维度是否都有数据）
  → 输出 `collector_self_assessment: {coverage_score, gaps, per_product, avg_confidence}`
  → 位置：`collector.py:256` `_build_collector_self_assessment()`
- [ ] **Collector 自动补采**：coverage < 0.7 时自动触发补采（需要图级路由变更，暂延后）
- [x] **Analyst 自评估**：分析完成后自评一致性（交叉验证率 + 单源结论 + confidence breakdown）
  → 输出 `analyst_self_assessment: {cross_validated_ratio, single_source_claims, confidence_breakdown}`
  → 位置：`analyst.py:452` `_build_analyst_self_assessment()`
- [x] **Writer 自评估**：生成后自检章节完整性、Schema 合规性、来源标注率
  → 输出 `writer_self_assessment: {schema_compliance, section_completeness, source_annotation_rate, overall_score}`
  → 位置：`writer.py:398` `_build_writer_self_assessment()`
- [ ] **Writer 自动回退修正**：发现问题自动回退修正不等 Reviewer 触发（需要图级路由变更，暂延后）
- [x] **自评估结果可视化**：DAG 图中 Collector/Analyst/Writer 节点旁显示自评分数圆点（绿≥0.8/黄≥0.6/红<0.6）
  → 后端：`dag.py:272` `_get_self_assessment()` 提取分数和 tier
  → 前端：`dag-graph.tsx` 节点标签内嵌彩色圆点 + hover title 显示百分比

### 13.3 动态 Schema 演化

- [x] **领域自适应 Schema 扩展**：`AnalysisResult` + `ReportData` 增加 `extra_fields: dict[str, Any]`，Analyst LLM 根据行业自动识别特有维度
  → 位置：`schema.py` AnalysisResult/ReportData 新增字段；`analyst.py` prompt 引导 LLM 输出 SaaS/硬件/游戏等行业维度
  → `writer.py` 报告增加「附录 B: 行业特有维度」section
- [x] **Reviewer G9 校验**：extra_fields 每项必须有 source_data_point_ids，无引用标记为 minor gap
  → 位置：`reviewer.py:313` `_check_extra_fields_sources()`
- [x] **Schema 版本管理**：`FeatureTree` + `PricingModel` 增加 `schema_version: int = 1`，旧版报告兼容读取
  → 位置：`schema.py`
- [ ] **用户自定义 Schema**：前端 Schema 模板编辑器（P2，答辩口头提）

---

## 十四、Collector 问卷/访谈能力（2026-06-04，源自开题材料核心功能）

> 开题材料原文：「支持信息采集 Agent（包括问卷设计，问卷调研，用户访谈等）」
> 会议纪要未强调为硬性要求，但原文明确列入核心功能。至少做问卷生成 + 模板导出，访谈做设计文档即可。

### 14.1 问卷设计

- [ ] **LLM 自动生成问卷**：基于 query + 分析目标，自动生成结构化问卷（选择题 + 开放题 + 评分题）
  → 输出 `Questionnaire` Pydantic Schema：标题/说明/题目列表（类型/选项/是否必答）
- [ ] **问卷模板库**：预设 3-5 套行业模板（SaaS 产品满意度 / 功能优先级排序 / 用户画像调研）
- [ ] **问卷导出**：支持导出为飞书表单链接、Markdown 表格、Google Form CSV

### 14.2 问卷调研

- [ ] **飞书表单集成**：通过 lark-cli 在飞书创建表单并收集回复，自动拉取结果进入 collected_data
- [ ] **结果结构化解析**：LLM 将问卷自由文本回复提取为结构化数据点
- [ ] **样本质量评估**：自动检测无效问卷（全选同一选项/填写时间 <30s），标记排除

### 14.3 用户访谈

- [ ] **访谈提纲自动生成**：基于 query + knowledge_gaps 生成半结构化访谈问题列表
- [ ] **访谈纪要结构化**：上传访谈录音/文本 → LLM 提取关键结论 → 结构化存入 collected_data
- [ ] **访谈数据脱敏**：自动识别并替换人名/公司名/联系方式（已有 §3.15.3 数据脱敏基础）

---

## 十五、Orchestrator Agent — Query-Driven 动态 Pipeline 升级 `**[v4 核心架构重构 P0]**`

> **动机**（2026-06-05 讨论）：
> 1. 当前 `_assess_complexity()` 用关键词匹配判定复杂度，无法理解语义意图
> 2. 产品名解析（提取 + 搜索验证 + LLM 纠错）是 2-3 次分散的 LLM 调用
> 3. 未来 query 信号越来越多（单产品补全竞品、维度强调、Schema 裁剪、pipeline 变体路由）——如果各加 LLM 调用是灾难
> 4. **解决方案**：引入 **Orchestrator Agent**，单次 LLM 调用统一完成意图解析 + 产品名解析 + 复杂度判定 + 路由决策
>
> 详见 PLAN §3.18 和 [memory: query-driven-dynamic-pipeline](../.claude/projects/-root-Projects-deer-flow/memory/query-driven-dynamic-pipeline.md)

### 15.1 PLAN 文档修改（13 处）

- [x] **PLAN §3.1 架构图更新**：新增 Orchestrator 预处理阶段
  → 原：`Collector → Analyst → Reviewer → Writer → HITL`
  → 新：`Orchestrator → Collector → Analyst → Reviewer → Writer → HITL`（Orchestrator 输出 `OrchestrationResult` 注入 State）
- [x] **PLAN §3.3 角色定义更新**：新增第 5 个 Agent — Orchestrator
  → 职责：意图解析 / 产品名提取+纠错 / 竞品自动补全 / 复杂度判定 / 维度权重分配 / Schema 裁剪 / pipeline 变体路由
  → 与其他 4 Agent 的关系：Orchestrator 只做意图→结构化指令，不做数据操作
- [x] **PLAN §3.4 Collector 规范更新**：搜索维度、预算、类别不再从固定 `COMPLEXITY_CONFIG` 取
  → 改为从 `state["orchestration_result"].dimension_weights` 动态取
  → 保留 `COMPLEXITY_CONFIG` 作为 fallback（Orchestrator 失败时降级）
- [x] **PLAN §3.5 Analyst 规范更新**：强制对比维度不再硬编码 4-6 维
  → 改为从 `state["orchestration_result"].dimension_weights` 动态取
  → 保留默认维度集作为 fallback
- [x] **PLAN §3.7 Writer 报告规范更新**：`REQUIRED_SECTIONS` 不再硬编码
  → 改为从 `state["orchestration_result"].schema_profile` 动态生成
  → 保留默认 section 集作为 fallback
- [x] **PLAN §3.10 State 更新**：新增 `orchestration_result: OrchestrationResult | None` + `complexity: str` 字段
- [x] **PLAN §3.13 路由逻辑更新**：新增 `route_after_orchestrator()` 函数
  → Orchestrator 成功后固定进 Collector；失败则根据 `pipeline_variant` 做条件路由
- [x] **PLAN §3.14 通信协议更新**：新增 **边 0：Orchestrator → Collector（OrchestrationResult）**
  → 通信契约总览从"6 边"更新为"7 边"
  → OrchestrationResult 作为后续所有节点的路由指令来源
- [x] **PLAN §3.16.5 超时重试更新**：新增 Orchestrator 超时配置
  → 建议 60s（单次 LLM 调用，远短于 Collector 的 600s）
- [x] **PLAN §3.17.1 自适应任务拆分更新**：标注复杂度判定已升级
  → 原：关键词匹配 `_assess_complexity()` → 现：Orchestrator LLM 语义判定
  → 旧实现保留作为降级 fallback
- [x] **PLAN §7 答辩呈现更新**：新增 Orchestrator 详情面板描述
  → DAG 图第一个节点 → 展开显示意图解析结果 / 产品置信度 / 维度权重分布
- [x] **PLAN §8 开发计划更新**：新增 Orchestrator 相关 Week 分配
- [x] **PLAN §6 差异化创新更新**：新增 Query-Driven Dynamic Orchestration 差异化点
  → 核心论点：传统 Agent 系统 pipeline 固定，我们引入 Orchestrator 实现 query 语义→pipeline 动态塑形

### 15.2 新代码：Orchestrator Agent

- [ ] **`deerflow/competition/nodes/orchestrator.py`**：Orchestrator 节点实现
  → 函数签名：`def orchestrator_node(state: CompetitionState) -> dict`
  → 内部流程：
    1. 构造 Orchestrator system prompt（意图解析 + 产品名提取 + 竞品补全 + 维度权重 + Schema 裁剪）
    2. 调用 `execute_agent()` 单次 LLM
    3. 解析输出为 `OrchestrationResult` Pydantic
    4. 如果产品名低置信度 → 触发 search 验证（复用现有 `_verify_products_via_search`）
    5. 如果单产品 → 自动补全竞品（search + LLM sub-step）
    6. `model_validate()` 失败 → 降级为默认 pipeline
- [ ] **`deerflow/competition/schema.py`**：新增 `OrchestrationResult` Pydantic Schema
  ```python
  class DimensionWeight(BaseModel):
      dimension: str           # "features" | "pricing" | "users" | "market" | "technology"
      weight: float            # 0.0-1.0, 各维度权重总和不一定为 1（控制搜索预算分配）
      reason: str              # 为什么这个维度权重高/低

  class OrchestrationResult(BaseModel):
      products: list[str]                     # 最终确认的产品名列表
      product_confidence: dict[str, str]       # 每个产品的置信度 high/medium/low
      complexity: Literal["quick", "standard", "deep"]
      complexity_reason: str                  # 为什么判定这个复杂度
      dimension_weights: list[DimensionWeight] # 各维度分析权重
      schema_profile: Literal["full", "feature_only", "pricing_only", "no_swot", "minimal"]
      emphasized_aspects: list[str]           # 用户强调的分析方面
      pipeline_variant: Literal["full", "collect_write_only", "skip_reviewer"]
      auto_discovered_competitors: list[str]  # 自动发现的竞品（单产品场景）
      summary: str                            # 意图解析的一句话摘要
  ```
- [ ] **`deerflow/competition/prompts/orchestrator.md`**：Orchestrator system prompt
  → 角色定位 + 输出格式 + 决策规则 + 降级行为

### 15.3 修改现有代码（13 个文件）

- [ ] **`competition.py` 重构 `_resolve_and_run_graph()`**：
  → 删除分散的 `_llm_extract_products()` + `_verify_products_via_search()` + `_assess_complexity()` 调用
  → 改为：构建初始 State → Orchestrator 节点一次完成所有意图解析
  → 保留 `_llm_extract_products()` 和 `_llm_judge_and_correct()` 作为 Orchestrator 内部的 fallback 子步骤
  → 保留 `_assess_complexity()` 作为纯降级兜底（Orchestrator 失败时）
- [ ] **`competition.py` `AnalyzeRequest` 修改**：`target_products` 从 `list[str]` 改为 `Optional[list[str]]`
  → 允许用户留空，由 Orchestrator 从自然语言 query 自动提取
- [ ] **`competition.py` `_add_token_entry()` 修改**：记录 Orchestrator token 消耗
- [ ] **`graph.py` 修改**：
  → `SET_ENTRY_POINT` 从 `"collector"` 改为 `"orchestrator"`
  → 新增 `builder.add_node("orchestrator", orchestrator_node)` + 对应 deep mode 的 deep_orchestrator
  → `add_conditional_edges("orchestrator", route_after_orchestrator, ...)`
  → 根据 `pipeline_variant` 做条件边（如 `collect_write_only` → 跳过 Analyst+Reviewer，直接到 Writer）
- [ ] **`state.py` 修改**：
  → 新增 `orchestration_result: NotRequired[dict | None]` 字段
  → 新增 `complexity: NotRequired[str | None]` 字段（Orchestrator 失败时作为 fallback 值）
- [ ] **`router.py` 修改**：新增 `route_after_orchestrator()` 函数
  → 成功 → `"collector"`（默认）/ 或根据 `pipeline_variant` 跳过节点
  → 失败/error → `"error_handler"`
- [ ] **`collector.py` 修改**：
  → `_run_searches()` 优先从 `state["orchestration_result"].dimension_weights` 读取维度权重
  → 权重高的维度分配更多搜索词 + 更高 fetch_top_n
  → `COMPLEXITY_CONFIG` 作为 fallback
- [ ] **`analyst.py` 修改**：
  → `analyst_node()` 读取 `orchestration_result.dimension_weights` 注入 Analyst system prompt
  → emphasized_aspects 作为 prompt 重点标注
- [ ] **`writer.py` 修改**：
  → `writer_node()` 读取 `orchestration_result.schema_profile` 决定生成哪些 sections
  → 例如 `feature_only` → 只生成 sec-comparison-matrix + sec-sources，跳过 SWOT/trends
- [ ] **`reviewer.py` 修改**：
  → `reviewer_node()` 读取 `orchestration_result.dimension_weights` 调整 G4（维度覆盖）校验标准
  → 如果 schema_profile 裁剪了某 section，对应维度的 G4 检查应放宽或跳过
- [ ] **`dag.py` 修改（6 处）**：
  → `DAG_TOPOLOGY["nodes"]`：新增 Orchestrator 节点定义
  → `DAG_TOPOLOGY["edges"]`：新增 Orchestrator→Collector 边
  → `_NODE_ORDER`：插入 Orchestrator 为首节点
  → `_infer_current_node()`：新增 Orchestrator 状态推断（无 orchestration_result → active）
  → `_compute_node_status()`：新增 Orchestrator 状态逻辑
  → `_compute_node_annotation()` + `_get_self_assessment()`：新增 Orchestrator 映射
- [ ] **`observability.py` 修改（5 处）**：
  → `NODE_INPUT_FIELDS`：新增 Orchestrator 输入字段（user_request / target_products）
  → `NODE_OUTPUT_FIELDS`：新增 Orchestrator 输出字段（orchestration_result）
  → `get_all_agent_details()`：循环从 5 节点扩展为 6 节点
  → `_node_label()`：新增 Orchestrator label
  → `_infer_tools()`：新增 Orchestrator 工具列表
- [ ] **`config.py` 修改**：新增 `OrchestratorConfig(BaseModel)` 配置类
  → timeout_seconds: int = 60 / model: str = "doubao-seed-2-0-lite" / temperature: float = 0.0 / max_tokens: int = 800

### 15.4 前端（7 项）

- [ ] **Orchestrator 详情面板**：DAG 图中 Orchestrator 节点可展开
  → 显示：意图解析摘要 / 产品置信度 / 维度权重 / Schema 裁剪决策 / pipeline 变体
- [ ] **Orchestrator 自评估**：`_build_orchestrator_self_assessment()`
  → 指标：产品置信度均值 / 竞品自动补全率 / 意图解析确定性
- [ ] **DAG 图更新**：新增 Orchestrator 节点（5 节点 → 6 节点）
  → 节点颜色：紫色（区别于其他 4 个 Agent 的蓝色）
- [ ] **`page.tsx` 输入区域修改**：`target_products` 输入框标记为可选
  → placeholder 改为 "可选：逗号分隔，留空由 AI 自动识别（如 Cursor, Copilot, Windsurf）"
  → label 改为 "竞品名称（可选）"
- [ ] **`api-client.ts` 类型修改**：`AnalyzeRequest.target_products` → `string[] | undefined`
- [ ] **SSE 流处理**：新增 Orchestrator 节点事件处理（`node_start` / `node_end`）
- [ ] **query 输入框提示文案更新**：
  → placeholder: "例如：对比 Slack、飞书和钉钉的协作能力，重点分析定价策略（竞品名称可留空）"

### 15.5 测试（5 项）

- [ ] **`test_competition_orchestrator.py`**：Orchestrator 单元测试
  → 测试场景：正常多产品 / 单产品自动补全 / 维度强调 / 低置信度降级 / Schema 裁剪 / pipeline_variant 路由
- [ ] **现有测试回归**：`test_competition_nodes.py` / `test_competition_graph.py` / `test_competition_state.py` 确保向后兼容
- [ ] **`test_competition_dag.py` 扩展**：新增 Orchestrator 节点的 DAG 状态测试
  → 验证：无 orchestration_result → Orchestrator 为 active / 有 orchestration_result → done
- [ ] **`test_competition_observability.py` 扩展**：新增 Orchestrator 可观测性测试
  → 验证：`get_agent_detail(state, "orchestrator")` 返回正确的 input/output 摘要
- [ ] **`test_competition_router.py` 扩展**：新增 `route_after_orchestrator` 测试
  → 验证：成功 → collector / error → error_handler / collect_write_only → writer

### 15.6 降级与兼容（3 项）

- [ ] **Orchestrator 失败降级**：Orchestrator LLM 调用失败 / JSON parse 失败 / model_validate 失败
  → 降级为当前默认 pipeline（`complexity="standard"`, `schema_profile="full"`, `pipeline_variant="full"`）
  → 产品名解析降级为当前 `_llm_extract_products()` + `_verify_products_via_search()`
- [ ] **向后兼容**：`orchestration_result` 为 None 时，所有下游节点按当前默认行为运行
- [ ] **Token 成本控制**：Orchestrator 单次调用预期 ~500-800 tokens（对比当前分散调用总和 ~1000-1500 tokens，实际节省 30-50%）

### 15.7 后续清理（Orchestrator 稳定运行后）

- [ ] **降级 `_assess_complexity()`**：从主路径移除，保留为 Orchestrator 失败时的纯降级 fallback
  → 理由：关键词匹配虽粗糙但零成本，作为兜底优于直接报错
- [ ] **降级 `_llm_extract_products()`**：提取+纠错归入 Orchestrator 内部，旧函数保留为 Orchestrator 失败时的独立 fallback 路径
- [ ] **冻结 `COMPLEXITY_CONFIG` 搜索参数**：不再作为主路径配置源，保留 label/description 用于 fallback 模式


> **使用方式**：编码时对照此 TODO，每完成一项标记 `[x]`。每个条目后的链接指向 COMPETITION_PLAN.md 对应设计章节。
> 状态：`[ ]` 待完成 | `[x]` 已完成
