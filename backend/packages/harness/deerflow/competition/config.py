"""Pydantic configuration models for the CI-Agent competition system.

Extends ``config.yaml`` → ``competition`` section.
Read via ``deerflow.config`` at startup, injected into graph nodes via State.
"""

from pydantic import BaseModel, Field


class AgentConfig(BaseModel):
    """Per-agent runtime configuration."""

    model: str = Field(
        default="doubao-seed-2-0-lite-260215",
        description="LLM model for this agent",
    )
    max_turns: int = Field(default=30, ge=1, description="Max SubagentExecutor turns")
    timeout_seconds: int = Field(default=600, ge=10, description="SubagentExecutor timeout")
    skills: list[str] = Field(default_factory=list, description="DF skill names to inject")
    tools: list[str] = Field(
        default_factory=lambda: ["web_search", "web_fetch", "python", "write_file", "read_file"],
        description="Tool names for this agent",
    )


class CollectorConfig(AgentConfig):
    """Collector-specific overrides — §3.4."""

    max_turns: int = 30
    timeout_seconds: int = 600
    soft_stop_min_points: int = Field(default=20, description="Soft stop: min data points (§3.4.3)")
    soft_stop_min_source_types: int = Field(default=3, description="Soft stop: min source diversity (§3.4.3)")
    empty_result_limit: int = Field(default=3, description="Consecutive empty results → hard stop")
    search_timeout_per_call: int = Field(default=30, description="Per-search-API timeout in seconds")
    skills: list[str] = Field(
        default_factory=lambda: ["deep-research", "github-deep-research", "data-normalizer"],
    )


class AnalystConfig(AgentConfig):
    """Analyst-specific overrides — §3.5."""

    max_turns: int = 20
    timeout_seconds: int = 300
    min_data_points_for_analysis: int = Field(default=5, description="Warn if fewer (§3.5.1)")
    skills: list[str] = Field(
        default_factory=lambda: [
            "spec-comparator", "market-share-calc", "sentiment-analyzer",
            "trend-detector", "data-analysis", "price-elasticity",
        ],
    )


class ReviewerConfig(AgentConfig):
    """Reviewer-specific overrides — §3.6."""

    max_turns: int = 15
    timeout_seconds: int = 300
    max_feedback_rounds: int = Field(default=2, description="Hard cap on Collector→Reviewer loops (§3.12)")
    head_request_timeout: int = Field(default=10, description="HEAD request timeout for G1 check (§3.6.1)")
    data_staleness_days: int = Field(default=180, description="G3: data older than this → outdated")
    skills: list[str] = Field(default_factory=lambda: ["source-credibility"])


class WriterConfig(AgentConfig):
    """Writer-specific overrides — §3.7."""

    max_turns: int = 20
    timeout_seconds: int = 180
    executive_summary_max_chars: int = Field(default=500, description="§3.7.3 exec summary cap")
    default_persona: str = Field(default="pm", description="Default persona if not specified")
    skills: list[str] = Field(
        default_factory=lambda: [
            "consulting-analysis", "swot-generator", "chart-visualization",
            "newsletter-generation", "ppt-generation",
        ],
    )


class HitlConfig(BaseModel):
    """HITL Gate configuration — §5.2."""

    approval_timeout_minutes: int = Field(default=30, description="Auto-approve after timeout (§5.2.5)")
    enable_feishu_approval: bool = Field(default=False, description="P1: push Feishu approval card")
    enable_frontend_approval: bool = Field(default=True, description="P0: embed approval UI in frontend")


class DataSourceRoutingConfig(BaseModel):
    """Data source priority configuration — §3.4.7."""

    cn_first: list[str] = Field(
        default_factory=lambda: ["volcengine_web_search", "zhihu", "weibo"],
        description="Chinese content source priority",
    )
    en_first: list[str] = Field(
        default_factory=lambda: ["tavily_search", "brave_search", "volcengine_web_search"],
        description="English content source priority",
    )
    official_first: list[str] = Field(
        default_factory=lambda: ["firecrawl", "jina_reader", "web_search"],
        description="Official info source priority",
    )
    review_first: list[str] = Field(
        default_factory=lambda: ["g2", "product_hunt", "reddit_api", "zhihu"],
        description="User review source priority",
    )
    tech_first: list[str] = Field(
        default_factory=lambda: ["github_api", "web_search"],
        description="Technical depth source priority",
    )


class DeepModeConfig(BaseModel):
    """Deep mode pipeline configuration — §3.1 (P1)."""

    enabled: bool = Field(default=True, description="Allow deep_mode=true in requests")
    max_review_rounds: int = Field(default=5, description="Relaxed round cap for deep Reviewer")
    extra_sources: list[str] = Field(
        default_factory=lambda: ["youtube_transcript", "bilibili_api", "douyin_api", "feishu_docs"],
        description="Additional data sources for deep Collector",
    )


class SearchBackendConfig(BaseModel):
    """Real web search backend toggles — controls which APIs Collector actually calls.

    Flip a backend to false to disable it without removing its API key from .env.
    At least one backend must be enabled; falls back to DDG if all are off.
    """

    tavily: bool = Field(default=True, description="Tavily AI search (needs TAVILY_API_KEY)")
    ddg: bool = Field(default=True, description="DuckDuckGo free search (no key needed)")
    jina: bool = Field(default=False, description="Jina AI reader for page extraction (needs JINA_API_KEY)")
    fetch_timeout: int = Field(default=15, description="Per-fetch timeout in seconds")
    fetch_top_n: int = Field(default=3, description="How many search results to deep-fetch per query batch")


class BranchExplorationConfig(BaseModel):
    """Agent branch exploration configuration — AgentBranchOps toggle.

    **IMPORTANT**: AgentBranchOps itself performs ZERO LLM calls.
    All operations (explore/fork/cherry-pick/compare/merge) are pure
    checkpoint data manipulation. Token consumption comes from RUNNING
    the graph on each branch, which is triggered by the CALLER, not by
    AgentBranchOps.

    This toggle controls whether the Agent is ALLOWED to use multi-branch
    strategies at all. When disabled, the Agent is limited to a single
    linear execution path.
    """

    enabled: bool = Field(
        default=False,
        description="Allow Agent to use multi-branch strategies (A/B test, explore, auto-merge)",
    )
    max_branches: int = Field(
        default=3, ge=1, le=8,
        description="Hard cap on number of concurrent branches to prevent runaway cost",
    )
    strategy: str = Field(
        default="manual",
        description="Branch strategy: 'manual' (user triggers) / 'auto-explore' (Agent auto-explores N variants) / 'a-b' (Agent A/B tests conflicting strategies)",
    )


class CompetitionConfig(BaseModel):
    """Root configuration for the competition module.

    Mounted under ``config.yaml`` → ``competition`` section.
    Read at graph startup, injected into CompetitionState.config.
    """

    collector: CollectorConfig = Field(default_factory=CollectorConfig)
    analyst: AnalystConfig = Field(default_factory=AnalystConfig)
    reviewer: ReviewerConfig = Field(default_factory=ReviewerConfig)
    writer: WriterConfig = Field(default_factory=WriterConfig)
    hitl: HitlConfig = Field(default_factory=HitlConfig)
    data_sources: DataSourceRoutingConfig = Field(default_factory=DataSourceRoutingConfig)
    deep_mode: DeepModeConfig = Field(default_factory=DeepModeConfig)
    search: SearchBackendConfig = Field(default_factory=SearchBackendConfig)
    branch_exploration: BranchExplorationConfig = Field(default_factory=BranchExplorationConfig)

    # Top-level defaults
    default_model: str = Field(default="doubao-seed-2-0-lite-260215")
    default_persona: str = Field(default="both", description="pm / entrepreneur / both")
    schema_validation_retries: int = Field(default=2, description="Max retries for validate_agent_output()")
    log_level: str = Field(default="INFO")


def load_competition_config_from_dict(raw: dict | None) -> CompetitionConfig:
    """Parse competition config from a raw YAML dict (called by deerflow.config)."""
    if raw is None:
        return CompetitionConfig()
    return CompetitionConfig.model_validate(raw)
