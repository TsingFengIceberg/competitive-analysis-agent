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

- [ ] **执行回放**（基于 Checkpoint 的时间轴滑块，拖动回到任意时刻）
  → 前端：`competition/replay-slider.tsx`（P1）

- [ ] **Token 消耗面板**（底部状态栏：per-Agent Token 统计）
  → 前端：`competition/token-panel.tsx`（P2）

- [ ] **报告导出按钮**（Markdown / PDF / PPTX 下载）
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

## 九、增强展望（P2，答辩口头提）

- [ ] **图算法扩展**（中心度/社区检测/路径分析/PageRank）
  → [PLAN §6.9](../COMPETITION_PLAN.md#69-竞品分析的本质是图问题p2-扩展展望)

- [ ] **交互性报告扩展**（Hover-to-source/版本Diff/语音批注/协作评论）
  → [PLAN §6.10](../COMPETITION_PLAN.md#610-交互性报告扩展p2-展望)

---

> **使用方式**：编码时对照此 TODO，每完成一项标记 `[x]`。每个条目后的链接指向 COMPETITION_PLAN.md 对应设计章节。
> 状态：`[ ]` 待完成 | `[x]` 已完成
