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
