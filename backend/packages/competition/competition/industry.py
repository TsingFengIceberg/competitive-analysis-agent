"""Industry profiles — Layer 2 of the three-layer Schema model (§3.20).

Each industry defines search keywords, analyst dimensions, fixed sections,
and prompt bias that augment the baseline pipeline without replacing it.
Industry="general" (default) applies no bias — identical to current behavior.
"""

INDUSTRY_PROFILES: dict[str, dict] = {
    "saas": {
        "label": "SaaS / 企业软件",
        "search_keywords": ["pricing tiers", "SLA", "integration", "API", "enterprise", "compliance"],
        "analyst_dimensions": ["集成生态", "API开放度", "SLA保障", "安全合规"],
        "fixed_sections": ["sec-industry-integration", "sec-industry-compliance"],
        "section_titles": {
            "sec-industry-integration": "集成生态与 API 开放度",
            "sec-industry-compliance": "安全合规与 SLA 保障",
        },
        "prompt_bias": "重点关注 API 开放程度、SLA 保障条款、企业级安全合规认证、定价层级结构",
    },
    "devtools": {
        "label": "开发者工具 / DevOps",
        "search_keywords": ["GitHub stars", "API docs", "community", "plugins", "open source", "performance"],
        "analyst_dimensions": ["社区活跃度", "API文档质量", "插件生态", "开源协议"],
        "fixed_sections": ["sec-industry-community", "sec-industry-api"],
        "section_titles": {
            "sec-industry-community": "社区活跃度与生态",
            "sec-industry-api": "API 质量与文档完善度",
        },
        "prompt_bias": "重点关注 GitHub Stars/Issues/PR 数据、API 设计质量、插件/扩展生态、文档完善度",
    },
    "ai": {
        "label": "AI / 大模型",
        "search_keywords": ["benchmark", "API pricing", "context window", "multimodal", "tokens per second", "fine-tuning"],
        "analyst_dimensions": ["模型能力Benchmark", "API定价(per-token)", "上下文窗口", "多模态支持"],
        "fixed_sections": ["sec-industry-benchmark", "sec-industry-pricing"],
        "section_titles": {
            "sec-industry-benchmark": "模型能力 Benchmark 对比",
            "sec-industry-pricing": "API 定价与 Token 成本分析",
        },
        "prompt_bias": "重点关注模型 benchmark 评分、API 调用定价(per-token)、上下文窗口大小、多模态能力、微调支持",
    },
    "database": {
        "label": "数据库 / 基础设施",
        "search_keywords": ["TPS", "latency", "scalability", "consistency", "deployment", "benchmark"],
        "analyst_dimensions": ["TPS/延迟", "扩展性", "一致性模型", "部署复杂度"],
        "fixed_sections": ["sec-industry-performance", "sec-industry-architecture"],
        "section_titles": {
            "sec-industry-performance": "性能指标对比 (TPS/延迟/扩展性)",
            "sec-industry-architecture": "架构与部署复杂度",
        },
        "prompt_bias": "重点关注 TPS/延迟基准测试、水平扩展能力、一致性模型（CP/AP）、部署运维复杂度",
    },
    "hardware": {
        "label": "硬件 / 消费电子",
        "search_keywords": ["specs", "chip", "battery", "benchmark", "price", "weight"],
        "analyst_dimensions": ["芯片型号", "功耗散热", "尺寸重量", "性能跑分"],
        "fixed_sections": ["sec-industry-specs", "sec-industry-benchmark"],
        "section_titles": {
            "sec-industry-specs": "硬件规格对比",
            "sec-industry-benchmark": "性能跑分与实测数据",
        },
        "prompt_bias": "重点关注芯片型号、性能跑分（Geekbench/AnTuTu）、功耗散热、尺寸重量、物料成本",
    },
    "gaming": {
        "label": "游戏",
        "search_keywords": ["engine", "platforms", "monetization", "DAU", "MAU", "revenue"],
        "analyst_dimensions": ["引擎", "平台覆盖", "付费模式", "用户规模"],
        "fixed_sections": ["sec-industry-tech", "sec-industry-monetization"],
        "section_titles": {
            "sec-industry-tech": "技术架构与引擎对比",
            "sec-industry-monetization": "付费模式与营收分析",
        },
        "prompt_bias": "重点关注游戏引擎、平台覆盖（PC/主机/移动）、付费模式（买断/内购/订阅）、DAU/MAU 数据",
    },
    "general": {
        "label": "通用（默认）",
        "search_keywords": [],
        "analyst_dimensions": [],
        "fixed_sections": [],
        "section_titles": {},
        "prompt_bias": "",
    },
}

_VALID_INDUSTRIES = frozenset(INDUSTRY_PROFILES.keys())


def get_industry_dimension_specs(industry: str) -> list[dict[str, str]]:
    """Return stable, editable Layer-2 dimension candidates for an industry.

    The existing profile labels remain the source of truth for compatibility;
    IDs are generated from the stable profile order and therefore remain safe
    for Collector categories and persisted Briefs.
    """
    profile = get_industry_profile(industry)
    labels = profile.get("analyst_dimensions", []) or []
    keywords = profile.get("search_keywords", []) or []
    return [
        {
            "id": f"industry:{industry}:{index + 1}",
            "label": str(label),
            "description": f"{profile.get('label', industry)}场景下的专项分析维度",
            "search_hint": " ".join(
                part for part in (str(label), str(keywords[index]) if index < len(keywords) else "") if part
            ),
            "source": "industry",
        }
        for index, label in enumerate(labels)
        if str(label).strip()
    ]


def get_industry_profile(industry: str) -> dict:
    """Return the profile for a given industry, defaulting to 'general'."""
    return INDUSTRY_PROFILES.get(industry, INDUSTRY_PROFILES["general"])


def validate_industry(industry: str) -> str:
    """Validate and normalize industry selection. Returns 'general' for unknown values."""
    if industry in _VALID_INDUSTRIES:
        return industry
    return "general"
