# CI-Agent

AI 驱动的竞品分析 Agent 协作系统 — 基于 [ByteDance DeerFlow](https://github.com/bytedance/deer-flow) 构建的多智能体竞争情报平台。

> 字节跳动 CIS「AI 全栈项目挑战赛」参赛项目 | 2026-05-20 ~ 2026-06-10

## 定位

CI-Agent 表现为一个"数字竞争情报小组"——4 个专门化 AI Agent（Collector / Analyst / Reviewer / Writer）以结构化协作协议完成竞品数据采集、交叉验证、多维对比分析和交互式报告生成，全程可溯源、可干预、可交互。

## 架构概览

- **基座**: DeerFlow (LangGraph Agent 框架 + Sandbox + Skills + Tools)
- **编排**: LangGraph StateGraph 单图 + 反馈闭环
- **角色体系**: 4 Agent — Collector（采集）/ Analyst（分析）/ Reviewer（质检）/ Writer（报告）
- **核心竞争力**: 对抗式交叉验证、DAG 反馈闭环、飞书生态深度集成、交互式报告编辑

## 文档

- [竞赛适配方案](./COMPETITION_PLAN.md) — 完整技术方案与开发计划
- [上游 PA-Agent-DF 文档](./DOCS-PA-AGENT/) — 原架构参考、开发指令、架构规约

## 开源协议

基于 DeerFlow (MIT) 二次开发，本仓库代码遵循 [MIT License](./LICENSE)。
