"""Tests for competition/config.py — Pydantic configuration models.

Covers §1.5 of the coding plan:
- All 7 config models with default values
- load_competition_config_from_dict() partial/empty/full loading
- Per-agent skill/tool defaults
"""

from __future__ import annotations

from competition.config import (
    AgentConfig,
    AnalystConfig,
    CollectorConfig,
    CompetitionConfig,
    DataSourceRoutingConfig,
    DeepModeConfig,
    HitlConfig,
    ReviewerConfig,
    WriterConfig,
    load_competition_config_from_dict,
)


class TestAgentConfig:
    def test_defaults(self):
        cfg = AgentConfig()
        assert cfg.model == "doubao-seed-2-0-lite-260215"
        assert cfg.max_turns == 30
        assert cfg.timeout_seconds == 600
        assert "web_search" in cfg.tools

    def test_custom(self):
        cfg = AgentConfig(model="custom-model", max_turns=10, timeout_seconds=120, skills=["s1"])
        assert cfg.model == "custom-model"
        assert cfg.max_turns == 10
        assert cfg.skills == ["s1"]


class TestCollectorConfig:
    def test_defaults(self):
        cfg = CollectorConfig()
        assert cfg.max_turns == 30
        assert cfg.timeout_seconds == 600
        assert cfg.soft_stop_min_points == 20
        assert cfg.soft_stop_min_source_types == 3
        assert cfg.empty_result_limit == 3
        assert "deep-research" in cfg.skills
        assert "data-normalizer" in cfg.skills

    def test_override(self):
        cfg = CollectorConfig(soft_stop_min_points=15, empty_result_limit=5)
        assert cfg.soft_stop_min_points == 15
        assert cfg.empty_result_limit == 5


class TestAnalystConfig:
    def test_defaults(self):
        cfg = AnalystConfig()
        assert cfg.max_turns == 20
        assert cfg.timeout_seconds == 300
        assert cfg.min_data_points_for_analysis == 5
        assert "spec-comparator" in cfg.skills
        assert "swot-generator" not in cfg.skills  # Writer skill

    def test_has_six_skills(self):
        cfg = AnalystConfig()
        assert len(cfg.skills) == 6


class TestReviewerConfig:
    def test_defaults(self):
        cfg = ReviewerConfig()
        assert cfg.max_turns == 15
        assert cfg.timeout_seconds == 300
        assert cfg.max_feedback_rounds == 2
        assert cfg.head_request_timeout == 10
        assert cfg.data_staleness_days == 180
        assert "source-credibility" in cfg.skills

    def test_feedback_rounds_bounded(self):
        cfg = ReviewerConfig(max_feedback_rounds=5)
        assert cfg.max_feedback_rounds == 5


class TestWriterConfig:
    def test_defaults(self):
        cfg = WriterConfig()
        assert cfg.max_turns == 20
        assert cfg.timeout_seconds == 180
        assert cfg.executive_summary_max_chars == 500
        assert "consulting-analysis" in cfg.skills
        assert "ppt-generation" in cfg.skills

    def test_has_five_skills(self):
        cfg = WriterConfig()
        assert len(cfg.skills) == 5


class TestHitlConfig:
    def test_defaults(self):
        cfg = HitlConfig()
        assert cfg.approval_timeout_minutes == 30
        assert cfg.enable_feishu_approval is False
        assert cfg.enable_frontend_approval is True


class TestDataSourceRoutingConfig:
    def test_defaults(self):
        cfg = DataSourceRoutingConfig()
        assert "volcengine_web_search" in cfg.cn_first
        assert "tavily_search" in cfg.en_first
        assert "firecrawl" in cfg.official_first
        assert "g2" in cfg.review_first
        assert "github_api" in cfg.tech_first


class TestDeepModeConfig:
    def test_defaults(self):
        cfg = DeepModeConfig()
        assert cfg.enabled is True
        assert cfg.max_review_rounds == 5
        assert "youtube_transcript" in cfg.extra_sources


class TestCompetitionConfig:
    def test_default_root(self):
        cfg = CompetitionConfig()
        assert cfg.default_model == "doubao-seed-2-0-lite-260215"
        assert cfg.schema_validation_retries == 2
        assert isinstance(cfg.collector, CollectorConfig)
        assert isinstance(cfg.analyst, AnalystConfig)
        assert isinstance(cfg.reviewer, ReviewerConfig)
        assert isinstance(cfg.writer, WriterConfig)
        assert isinstance(cfg.hitl, HitlConfig)
        assert isinstance(cfg.data_sources, DataSourceRoutingConfig)
        assert isinstance(cfg.deep_mode, DeepModeConfig)

    def test_nested_override(self):
        cfg = CompetitionConfig.model_validate({
            "collector": {"soft_stop_min_points": 10},
            "reviewer": {"max_feedback_rounds": 3},
        })
        assert cfg.collector.soft_stop_min_points == 10
        assert cfg.reviewer.max_feedback_rounds == 3
        # Unspecified sub-configs should still have defaults
        assert cfg.analyst.max_turns == 20


class TestLoadConfigFromDict:
    def test_none_returns_default(self):
        cfg = load_competition_config_from_dict(None)
        assert cfg.default_model == "doubao-seed-2-0-lite-260215"

    def test_empty_returns_default(self):
        cfg = load_competition_config_from_dict({})
        assert cfg.schema_validation_retries == 2

    def test_partial_merge(self):
        cfg = load_competition_config_from_dict({
            "hitl": {"approval_timeout_minutes": 15},
        })
        assert cfg.hitl.approval_timeout_minutes == 15
        assert cfg.collector.max_turns == 30  # default preserved

    def test_unknown_field_ignored(self):
        """Pydantic v2 silently ignores extra fields (forward-compatible config)."""
        cfg = load_competition_config_from_dict({"nonexistent_field": 42})
        assert cfg.schema_validation_retries == 2  # unknown key doesn't break loading
