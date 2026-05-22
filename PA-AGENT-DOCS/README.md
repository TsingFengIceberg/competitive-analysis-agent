# PA-Agent-DF

基于 [ByteDance DeerFlow](https://github.com/bytedance/deer-flow) 二次开发的泛商品协同分析 AI 多智能体系统。

## 定位

PA-Agent-DF 表现为一个"数字调研小组"——多个专门化 AI Agent 以结构化协作协议完成数据采集、交叉验证、多维度分析和报告生成。

## 架构概览

- **基座**: DeerFlow (LangGraph Agent 框架)
- **参考架构**: ClawdLab 对抗式批判验证、Nested SubGraph 等
- **角色体系**: 8 个专门化 Agent (PI / Data Scout / Critic / Meta-Judge / Analyst Lead / Synthesizer / Internal Reviewer / Report Composer)
- **核心机制**: 四权分立 (质疑权/执行权/裁决权/监督权)、HITL 人类审批门

详细架构与功能文档见 [PA-Agent-DF-architecture.md](./PA-Agent-DF-architecture.md)。

## 上游文档

DeerFlow 原始 README、构建说明及多语言文档已移至 [UPSTREAM-DOCS/](./UPSTREAM-DOCS/) 目录。
