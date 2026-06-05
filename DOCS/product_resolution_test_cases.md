# v3 Product Resolution Test Cases

## 一、纠错用例（20 个）

### 拼写错误（8 个）

| # | 输入 | 期望输出 | query 上下文 |
|---|------|----------|-------------|
| 1 | Noton | Notion | 对比 Noton 和 Obsidian 笔记工具 |
| 2 | MonngoDB | MongoDB | 对比 MonngoDB 和 MySQL 数据库 |
| 3 | Githbu | GitHub | 用 Githbu 还是 GitLab |
| 4 | Postgre | PostgreSQL | 对比 Postgre 和 MySQL |
| 5 | Doker | Docker | 对比 Doker 和 Podman 容器工具 |
| 6 | Kubernets | Kubernetes | 对比 Kubernets 和 Docker Swarm |
| 7 | Figam | Figma | 对比 Figam 和 Sketch 设计工具 |
| 8 | Obisidian | Obsidian | 对比 Obisidian 和 Notion |

### 缩写/部分名 + 上下文消歧（8 个）

| # | 输入 | 期望输出 | query 上下文 |
|---|------|----------|-------------|
| 9 | Power | Power BI | 对比 Power 和 Tableau 数据分析工具 |
| 10 | Tab | Tableau | 对比 Tab 和 Power BI 数据可视化 |
| 11 | SF | Salesforce | 对比 SF 和 HubSpot 哪个 CRM 好 |
| 12 | spot | HubSpot | 对比 spot 和 Salesforce CRM 系统 |
| 13 | DD | Datadog | 对比 DD 和 New Relic 监控工具 |
| 14 | GH | GitHub | 对比 GH 和 GitLab 代码托管 |
| 15 | sugar | SugarCRM | 对比 sugar 和 Salesforce CRM |
| 16 | pd | PagerDuty | 对比 pd 和 Opsgenie 告警工具 |

### 中文昵称/描述（4 个）

| # | 输入 | 期望输出 | query 上下文 |
|---|------|----------|-------------|
| 17 | 小破站 | Bilibili | 对比 小破站 和 YouTube 视频平台 |
| 18 | 微软那个AI编程工具 | GitHub Copilot | 对比 微软那个AI编程工具 和 Cursor |
| 19 | 字节飞书 | Feishu/Lark | 对比 字节飞书 和 钉钉 |
| 20 | 谷歌文档 | Google Docs | 对比 谷歌文档 和 Notion |

---

## 二、正确用例（20 个，不需纠错，直接确认）

| # | 输入 | 期望输出 | query 上下文 |
|---|------|----------|-------------|
| 1 | MongoDB | MongoDB | 对比 MongoDB 和 PostgreSQL |
| 2 | GitHub Copilot | GitHub Copilot | 对比 GitHub Copilot 和 Cursor |
| 3 | Figma | Figma | 对比 Figma 和 Sketch |
| 4 | Cursor | Cursor | 对比 Cursor 和 Windsurf AI 编辑器 |
| 5 | Notion | Notion | 对比 Notion 和 Obsidian |
| 6 | Datadog | Datadog | 对比 Datadog 和 Grafana 监控 |
| 7 | Kubernetes | Kubernetes | 对比 Kubernetes 和 Docker Swarm |
| 8 | PostgreSQL | PostgreSQL | 对比 PostgreSQL 和 MySQL |
| 9 | Redis | Redis | 对比 Redis 和 Memcached |
| 10 | Slack | Slack | 对比 Slack 和 飞书 |
| 11 | Linear | Linear | 对比 Linear 和 Jira |
| 12 | Vercel | Vercel | 对比 Vercel 和 Netlify |
| 13 | Docker | Docker | 对比 Docker 和 Podman |
| 14 | Tailwind CSS | Tailwind CSS | 对比 Tailwind CSS 和 Bootstrap |
| 15 | Next.js | Next.js | 对比 Next.js 和 Remix |
| 16 | Stripe | Stripe | 对比 Stripe 和 Paddle 支付 |
| 17 | Snowflake | Snowflake | 对比 Snowflake 和 BigQuery |
| 18 | Tableau | Tableau | 对比 Tableau 和 Power BI |
| 19 | Webflow | Webflow | 对比 Webflow 和 Framer |
| 20 | ClickHouse | ClickHouse | 对比 ClickHouse 和 Snowflake |

---

## 使用方式

把"输入"列作为 candidate name，搭配对应的 query 上下文发给 `_llm_judge_and_correct`，检查 returned mapping 里 `resolved` 是否等于"期望输出"。

模拟 search_titles 时：纠错用例的 search 标题应该包含期望输出对应的产品名（模拟搜索引擎自动纠错）；正确用例的标题自然就包含正确名称。

---

## 四、v4 Orchestrator — 复杂度判定（6 个）

> 测试 `_build_analyst_task` prompt 中的 complexity 判定逻辑 + `route_after_reviewer` 的轮次上限。
> 注意：此测试不涉及真实 LLM 调用，只测试路由和参数选择。

| # | Query | 产品数 | 期望复杂度 | 期望 Review 轮次 | 期望搜索预算 | 判定依据 |
|---|-------|--------|-----------|-----------------|-------------|---------|
| 1 | 对比 Slack 和飞书的定价 | 2 | quick | 1 | 12 | 2产品+简单对比 |
| 2 | 分析 Slack、飞书、钉钉的竞争力 | 3 | standard | 2 | 20 | 3产品+分析意图 |
| 3 | 深度分析全球协作工具 Top5 的竞争格局与未来趋势 | 5 | deep | 3 | 30 | 5产品+深度/战略/趋势关键词 |
| 4 | 对比 Notion 和 Confluence，重点分析定价策略和企业版功能差异 | 2 | standard | 2 | 20 | 2产品但含"分析"+"策略" → standard |
| 5 | Cursor 有哪些竞争对手 | 1→4 | standard | 2 | 20 | ProductResolver 自动补全 3 竞品 |
| 6 | Slack 和 Teams 在 SaaS 集成能力、API 开放程度、SLA 保障方面的对比 | 2 | quick | 1 | 12 | 2产品+具体维度对比 → quick |

### 复杂度决策树

```
产品数 ≥5 或 deep关键词 ≥2 或 query长度 >200  →  deep
产品数 ≥3 或 query长度 >80                       →  standard
产品 ≤2 且 有对比关键词                           →  quick
其他情况                                          →  standard（兜底）
```

---

## 五、v4 Orchestrator — 维度权重与策略输出（6 个）

> 测试 `OrchestrationResult` Schema 的字段完整性 + `orchestrator_node` 降级路径。

| # | 场景 | 输入 | 期望输出 |
|---|------|------|---------|
| 1 | 空 query 降级 | `user_request=""` | `complexity=standard, schema_profile=baseline, dimension_weights=4项` |
| 2 | 空产品降级 | `user_request="test", target_products=[]` | 立即返回降级，不调用 LLM |
| 3 | 完整 valid 输入 | `complexity=deep, schema_profile=deep, 2 dim_weights, 2 emphasized` | model_validate 通过 |
| 4 | 非法 complexity | `complexity="invalid"` | Pydantic ValidationError |
| 5 | 非法 schema_profile | `schema_profile="feature_only"`（已删除的旧值） | Pydantic ValidationError |
| 6 | JSON parse 失败 | LLM 返回 `"not json"` | `_parse_orchestrator_output()` → None → 降级 |

---

## 六、v4 Pipeline 路由 — 固定结构 + 轮次上限（8 个）

> 测试 `route_after_*` 全部 7 个函数的正确性。
> 核心原则：**Pipeline 节点图固定（O→C→A→R→W→H），复杂度只控制执行深度。**

| # | 场景 | 测试内容 | 期望 |
|---|------|---------|------|
| 1 | O→C 永远不变 | quick/standard/deep/无orch → `route_after_orchestrator` | 全部返回 `"collector"` |
| 2 | O→error | `state["error"]` 非空 | 返回 `"error_handler"` |
| 3 | C→A 永远不变 | 任意 state | 返回 `"analyst"` |
| 4 | C→error | 0 条 collected_data | 返回 `"error_handler"` |
| 5 | A→R 永远不变 | 任意 state | 返回 `"reviewer"` |
| 6 | Review 轮次 quick | quick + review_round=1 | 返回 `"writer"`（达上限） |
| 7 | Review 轮次 deep | deep + review_round=2 | 返回 `"collector"`（还可以继续） |
| 8 | Review 轮次 deep 上限 | deep + review_round=3 | 返回 `"writer"`（达上限） |

---

## 七、v4 DynamicBlock — 4 种动态块类型（12 个）

> 测试 `DynamicBlock` Pydantic Schema + Writer `_render_dynamic_blocks` + Reviewer `_check_dynamic_blocks`。

### 7.1 Schema 校验（5 个）

| # | 块类型 | 测试内容 | 期望 |
|---|--------|---------|------|
| 1 | kv_list | 2 个指标 + 2 个 source_ids | model_validate 通过 |
| 2 | comparison_table | 4 列表头 × 3 行数据 | model_validate 通过 |
| 3 | stat_chart | radar 图 5 标签 × 2 系列 | model_validate 通过 |
| 4 | insight_text | markdown 文本内容 | model_validate 通过 |
| 5 | 非法 block_type | `"invalid_type"` | Pydantic ValidationError |

### 7.2 Writer 渲染（4 个）

| # | 块类型 | 期望 content_type | 期望 chart_path |
|---|--------|-----------------|----------------|
| 1 | kv_list | `"text"` | None |
| 2 | comparison_table | `"table"` | `{headers, rows}` |
| 3 | stat_chart | `"chart"` | `{chart, labels, series}` |
| 4 | insight_text | `"text"` | None |

### 7.3 Reviewer G9 校验（3 个）

| # | 场景 | 期望 gaps |
|---|------|----------|
| 1 | 块无 source_data_point_ids | 1 gap（minor） |
| 2 | comparison_table row 列数不匹配 header | 1 gap（minor） |
| 3 | stat_chart series 值数与 labels 不匹配 | 1 gap（minor） |

---

## 八、v4 Schema 深度 — baseline vs deep（4 个）

| # | 场景 | schema_profile | 期望 section 数 | 说明 |
|---|------|---------------|----------------|------|
| 1 | 简单对比 | baseline | 6 | 执行摘要+矩阵+SWOT+建议+来源+质量 |
| 2 | 深度战略 | deep | 9 | baseline + 趋势+预测+行业附录 |
| 3 | 默认（无 orch） | baseline（默认） | 6 | 降级行为 |
| 4 | 无 orch → _get_schema_mode | baseline | 6 | `state.get("orchestration_result") or {}` |

---

## 九、集成测试 — 6 种代表性 Query Flow

| # | Query | 产品 | 复杂度 | Schema | 路径 | Review轮次 | 关键验证点 |
|---|-------|------|--------|--------|------|-----------|-----------|
| 1 | 对比 Slack 和飞书的定价 | [Slack, 飞书] | quick | baseline | O→C→A→R→W→H | 1 | 2产品简单对比，搜索预算 12 |
| 2 | 分析 Slack、飞书、钉钉的竞争力 | [Slack, 飞书, 钉钉] | standard | baseline | O→C→A→R→W→H | 2 | 3产品分析，搜索预算 20 |
| 3 | 深度分析全球协作工具 Top5 的竞争格局与未来趋势 | [Slack, Teams, 飞书, 钉钉, Discord] | deep | deep | O→C→A→R→W→H | 3 | 5产品+战略，搜索预算 30，9 sections |
| 4 | Cursor 有哪些竞争对手 | [Cursor, Copilot, Windsurf, Codeium] | standard | baseline | O→C→A→R→W→H | 2 | ProductResolver 自动补全 3 竞品 |
| 5 | 对比 Notion 和 Confluence，重点分析定价策略和企业版功能差异 | [Notion, Confluence] | standard | baseline | O→C→A→R→W→H | 2 | pricing weight=0.95，emphasized_aspects 注入 Analyst |
| 6 | Slack 和 Teams 在 SaaS 集成能力、API 开放程度、SLA 保障方面的对比 | [Slack, Teams] | quick | baseline | O→C→A→R→W→H | 1 | SaaS 特有维度 → DynamicBlock kv_list |

---

## 十、测试运行方式

```bash
# 综合测试（49 个断言，无 LLM 依赖）
cd backend && PYTHONPATH=packages/harness:. uv run python /tmp/test_v4_comprehensive.py

# 回归测试
cd backend && PYTHONPATH=packages/harness:. uv run pytest tests/test_competition_*.py -v
```
