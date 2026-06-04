"""BranchTree — Data 粒度的 Agent 工作流版本分支树。

核心组件：
- BranchNode: 节点数据结构
- BranchTree: 抽象基类（单层两级继承）
- CheckpointOps: LangGraph checkpoint 便捷操作工具层
- AgentBranchOps: Agent 执行层分支操作（自动探索/A/B测试/择优合并）
"""
