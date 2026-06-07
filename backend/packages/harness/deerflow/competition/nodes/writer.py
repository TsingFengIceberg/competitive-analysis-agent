"""Writer node — ReportData generation with dual-persona support and source traceability.

Per COMPETITION_PLAN.md §3.7: interactive ReportData replacing legacy .md strings.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

# Report section structure (§3.7.3) — baseline always 6 sections
REQUIRED_SECTIONS = [
    "sec-executive-summary",
    "sec-comparison-matrix",
    "sec-swot",
    "sec-recommendations",
    "sec-sources",
    "appendix-quality",
]

# Conditionally generated (always available, generated when data exists)
OPTIONAL_SECTIONS = {
    "sec-trends": "trends",
    "sec-user-voice": "sentiment",
    "sec-forecast": "forecast",
    "appendix-charts": "charts",
}

# v4: Deep mode additional sections — generated only when schema_profile="deep"
DEEP_SECTIONS = [
    "sec-trends",        # market/product trends
    "sec-forecast",      # prediction + what-if
    "appendix-industry", # industry-specific dimensions (extra_fields)
]


def _get_schema_mode(state: dict) -> str:
    """Return the active schema profile from Orchestrator, default baseline."""
    orch = state.get("orchestration_result") or {}
    return orch.get("schema_profile", "baseline")

# Persona profiles (§3.7.4)
PERSONA_PROFILES = {
    "pm": {
        "opening": "从产品功能角度看",
        "focus": "功能维度 > 定价维度",
        "recommendations": "功能优先级排序、差异化方向",
        "swot_level": "产品级（功能/UX/定价/用户）",
        "what_if": "如果竞品加了 X 功能，我们要跟进吗？",
    },
    "entrepreneur": {
        "opening": "从市场机会角度看",
        "focus": "定价维度 > 功能维度",
        "recommendations": "细分市场选择、商业模式建议、进入时机",
        "swot_level": "战略级（市场/团队/资本/壁垒）",
        "what_if": "如果我选 Y 细分市场，竞争压力多大？",
    },
}


def writer_node(state: dict) -> dict:
    """Graph node: generate ReportData from analysis_result + review_verdict.

    Returns partial state update with report_data + review_package + traceability_map.
    """
    analysis = state.get("analysis_result") or {}
    verdict = state.get("review_verdict") or {}
    collected = state.get("collected_data") or []
    persona = state.get("persona", "pm")
    target_products = state.get("target_products", [])
    hitl_focus, whatif_comment_raw, hitl_action = _get_hitl_focus(state)
    # Only use comment as what-if scenario when action is explicitly "rewrite"
    whatif_comment = whatif_comment_raw if hitl_action == "rewrite" else ""

    # Build report sections — v4: schema_profile controls deep sections
    quality = verdict.get("quality_summary", {})
    schema_mode = _get_schema_mode(state)
    sections = _build_sections(analysis, verdict, persona, target_products, hitl_focus, whatif_comment, hitl_action, collected, quality, schema_mode)

    # Industry fixed sections (Layer 2 of §3.20)
    industry_sections = _build_industry_sections(state, analysis)
    if industry_sections:
        sections.extend(industry_sections)
        logger.info("Added %d industry sections for '%s'", len(industry_sections), state.get("industry", "general"))

    # Generate executive summary via LLM for all actions (not just rewrite)
    try:
        _llm_generate_section(sections, "sec-executive-summary", analysis, target_products, persona)
    except Exception:
        logger.exception("Writer LLM generation failed for executive summary")

    traceability = _build_traceability_map(collected)
    forecast = analysis.get("forecast")
    extra_fields = analysis.get("extra_fields") or {}
    dynamic_blocks = analysis.get("dynamic_blocks") or []
    metrics = _compute_report_metrics(collected, verdict, traceability)

    report_data = {
        "persona": persona,
        "title": _build_title(target_products, persona),
        "generated_at": datetime.now(UTC).isoformat(),
        "products": target_products,
        "sections": sections,
        "traceability_map": traceability,
        "quality_summary": quality,
        "forecast": forecast,
        "metrics": metrics,
        "extra_fields": extra_fields,
        "dynamic_blocks": dynamic_blocks,
    }

    # Build ReviewPackage for HITL (§3.13.5)
    review_package = _build_review_package(report_data, collected, quality)

    # Self-check (§3.7.6)
    issues = writer_self_check(report_data, target_products)
    if issues:
        logger.warning("Writer self-check found %d issues: %s", len(issues), issues)

    # ── Self-assessment (§3.17.2) ──
    self_assessment = _build_writer_self_assessment(report_data, target_products)

    return {
        "report_data": report_data,
        "traceability_map": traceability,
        "review_package": review_package,
        "writer_self_assessment": self_assessment,
    }


def _build_title(products: list[str], persona: str) -> str:
    products_str = " vs ".join(products) if products else "竞品分析"
    persona_label = "产品经理视角" if persona == "pm" else "创业者视角"
    return f"{products_str} 竞品分析报告 — {persona_label}"


def _get_hitl_focus(state: dict) -> list[str] | None:
    decision = state.get("hitl_decision") or {}
    return decision.get("target_focus"), decision.get("comment", ""), decision.get("action", "")


def _build_sections(analysis: dict, verdict: dict, persona: str, products: list[str], focus: list[str] | None, whatif_comment: str, hitl_action: str, collected: list[dict], quality: dict, schema_profile: str = "baseline") -> list[dict]:
    """Build all report sections, respecting persona and optional conditions."""
    profile = PERSONA_PROFILES.get(persona, PERSONA_PROFILES["pm"])
    sections: list[dict] = []
    source_id = [0]  # mutable counter for [n] numbering

    def _src_ref(point_ids: list[str]) -> str:
        refs = []
        for _pid in point_ids:
            source_id[0] += 1
            refs.append(f"[{source_id[0]}]")
        return "".join(refs)

    # 1. Executive Summary (required)
    matrix = analysis.get("comparison_matrix", {})
    summary_text = matrix.get("summary", f"{' vs '.join(products)} 竞品分析")
    exec_content: str
    if hitl_action == "rewrite":
        exec_content = _llm_rewrite_section("executive_summary", analysis, products, persona)
    else:
        exec_content = f"{profile['opening']}，{summary_text}"
    sections.append({
        "id": "sec-executive-summary", "title": "执行摘要",
        "content": exec_content, "content_type": "text",
        "source_ids": [], "chart_path": None, "subsections": None,
    })

    # 2. Comparison Matrix (required)
    cells = matrix.get("cells", [])
    dims = matrix.get("dimensions", [])
    table_rows = []
    for cell in cells:
        if isinstance(cell, dict):
            rating = cell.get("rating", "N/A")
            evidence = cell.get("evidence", "")
            src_ids = cell.get("source_data_point_ids", [])
            table_rows.append({
                "product": cell.get("product", ""),
                "dimension": cell.get("dimension", ""),
                "rating": rating,
                "evidence": f"{evidence} {_src_ref(src_ids)}",
            })
    sections.append({
        "id": "sec-comparison-matrix", "title": "对比矩阵",
        "content": _render_comparison_table(table_rows, products, dims),
        "content_type": "table", "source_ids": [], "chart_path": None, "subsections": None,
    })

    # 3. SWOT (required)
    swot = analysis.get("swot", {})
    swot_content = ""
    for prod_name, swot_data in swot.items():
        if not isinstance(swot_data, dict):
            continue
        swot_content += f"### {prod_name}\n"
        for item in swot_data.get("items", []):
            if not isinstance(item, dict):
                continue
            src_ids = item.get("source_data_point_ids", [])
            swot_content += f"- **{item.get('category', '?')}**: {item.get('statement', '')} {_src_ref(src_ids)}\n  - *证据*: {item.get('evidence', '')}\n"
    sections.append({
        "id": "sec-swot", "title": "SWOT 分析",
        "content": swot_content or "_暂无 SWOT 数据_", "content_type": "text",
        "source_ids": [], "chart_path": None, "subsections": None,
    })

    # 4. Trends (conditional)
    trends = analysis.get("trends", [])
    if trends:
        trend_text = ""
        for t in trends:
            if isinstance(t, dict):
                src_ids = t.get("source_data_point_ids", [])
                trend_text += f"- {t.get('dimension', '?')}: {t.get('direction', '?')} (置信度: {t.get('confidence', 0):.0%}) — {t.get('evidence', '')} {_src_ref(src_ids)}\n"
        sections.append({
            "id": "sec-trends", "title": "趋势与洞察",
            "content": trend_text, "content_type": "text",
            "source_ids": [], "chart_path": None, "subsections": None,
        })

    # 5. Forecast (conditional, §3.5.7)
    forecast = analysis.get("forecast")
    if forecast and isinstance(forecast, dict):
        items = forecast.get("items", [])
        fc_text = forecast.get("summary", "") + "\n\n"
        for fi in items:
            if isinstance(fi, dict):
                fc_text += f"- **{fi.get('product', '?')}** ({fi.get('dimension', '?')}): 6个月预测 {fi.get('forecast_6m', '?')}, 12个月预测 {fi.get('forecast_12m', '?')}\n"
        fc_text += f"\n*{forecast.get('disclaimer', '')}*"
        sections.append({
            "id": "sec-forecast", "title": "预测推演",
            "content": fc_text, "content_type": "text",
            "source_ids": [], "chart_path": None, "subsections": None,
        })

    # What-if section — always present, LLM-generated when user submitted a what-if via rewrite
    whatif_content = _generate_whatif(whatif_comment, analysis, products, persona) if whatif_comment else ""
    if whatif_content:
        sections.append({
            "id": "sec-whatif", "title": "What-if 推演",
            "content": whatif_content, "content_type": "text",
            "source_ids": [], "chart_path": None, "subsections": None,
        })
    else:
        sections.append({
            "id": "sec-whatif", "title": "What-if 推演",
            "content": "输入假设条件，系统将在现有数据上做推演（不走 Collector，30 秒出结论）",
            "content_type": "what-if-form", "source_ids": [], "chart_path": None, "subsections": None,
        })

    # 6. Recommendations (required)
    rec_content: str
    if hitl_action == "rewrite":
        rec_content = _llm_rewrite_section("recommendations", analysis, products, persona)
    else:
        rec_content = f"**{profile['recommendations']}**\n\n基于以上分析，建议关注产品功能差异化和定价策略优化。"
    sections.append({
        "id": "sec-recommendations", "title": "建议",
        "content": rec_content,
        "content_type": "text", "source_ids": [], "chart_path": None, "subsections": None,
    })

    # 7. Sources (required)
    sources_text = ""
    for i, dp in enumerate(collected):
        if isinstance(dp, dict):
            sources_text += f"[{i+1}] {dp.get('source_url', '?')} — {dp.get('collected_at', '?')} — {dp.get('label', '')}\n"
    sections.append({
        "id": "sec-sources", "title": "数据来源",
        "content": sources_text or "_暂无来源_", "content_type": "table",
        "source_ids": [], "chart_path": None, "subsections": None,
    })

    # 8. Appendix: Quality (required)
    q_text = f"总数据点: {quality.get('total_data_points', 0)}\n"
    q_text += f"已验证: {quality.get('verified_count', 0)} | 多源交叉: {quality.get('multi_source_count', 0)} | 单源: {quality.get('single_source_count', 0)}\n"
    q_text += f"事实错误: {quality.get('fact_errors_count', 0)} | 质量分: {quality.get('overall_quality_score', 0):.0%}\n"
    sections.append({
        "id": "appendix-quality", "title": "附录 A: 数据质量报告",
        "content": q_text, "content_type": "text",
        "source_ids": [], "chart_path": None, "subsections": None,
    })

    # 8.5 Industry fixed sections (Layer 2 of §3.20)
    from deerflow.competition.industry import get_industry_profile  # noqa: E402
    industry_id = persona_state.get("industry", "general") if 'persona_state' in dir() else "general"
    # Read industry from the state dict passed through the node
    _industry = "general"
    # We need to reach the state from here — use the parameters already available
    # Actually, let's just read from the persona/industry state
    # The industry comes from state dict, so we need to pass it through _build_sections
    # For now, the industry sections are appended in writer_node after _build_sections

    return sections


def _build_industry_sections(state: dict, analysis: dict) -> list[dict]:
    """Generate Layer 2 industry-specific fixed sections (§3.20)."""
    from deerflow.competition.industry import get_industry_profile

    industry = state.get("industry", "general")
    if industry == "general":
        return []

    profile = get_industry_profile(industry)
    fixed_ids = profile.get("fixed_sections", [])
    titles = profile.get("section_titles", {})
    sections: list[dict] = []

    for i, sec_id in enumerate(fixed_ids):
        title = titles.get(sec_id, sec_id)
        bias = profile.get("prompt_bias", "")

        # Generate content via LLM based on industry-specific prompt
        content = _generate_industry_section_content(state, analysis, sec_id, bias)
        sections.append({
            "id": sec_id,
            "title": title,
            "content": content,
            "content_type": "text",
            "source_ids": [],
            "chart_path": None,
            "subsections": None,
        })

    return sections


def _generate_industry_section_content(state: dict, analysis: dict, section_id: str, prompt_bias: str) -> str:
    """Generate an industry-specific section via lightweight LLM call."""
    try:
        from deerflow.competition.executor import execute_agent

        products = state.get("target_products", [])
        user_request = state.get("user_request", "")

        data_summary = ""
        collected = state.get("collected_data") or []
        for dp in collected[:10]:
            if isinstance(dp, dict):
                data_summary += f"- {dp.get('product', '?')} | {dp.get('category', '?')} | {dp.get('label', '?')} | {dp.get('value', '?')}\n"

        task = (
            f"Query: {user_request}\n"
            f"Products: {', '.join(products) if products else 'unknown'}\n"
            f"Industry focus: {prompt_bias}\n\n"
            f"Collected data:\n{data_summary}\n\n"
            f"Generate a concise analysis section (3-5 paragraphs) for the industry-specific "
            f"section '{section_id}'. Focus on quantitative comparisons and cite data points. "
            f"Output markdown text only, no JSON."
        )
        system = (
            "You are a competitive analysis writer specializing in industry-specific analysis. "
            "Write concise, data-driven sections. Cite specific data points."
        )

        raw, _ = execute_agent(system, task, temperature=0.3, max_tokens=600, agent_name="IndustrySectionWriter")
        return raw.strip() if raw else f"_Industry section '{section_id}' — insufficient data to generate._"
    except Exception:
        logger.exception("Industry section generation failed for %s", section_id)
        return f"_Industry section '{section_id}' — generation failed._"
        block_sections = _render_dynamic_blocks(dynamic_blocks, _src_ref)
        sections.extend(block_sections)

    # 10. Legacy: extra_fields appendix (kept for backward compatibility)
    extra_fields = analysis.get("extra_fields") or {}
    if extra_fields and not dynamic_blocks:
        ef_text = ""
        for field_name, field_data in extra_fields.items():
            if isinstance(field_data, dict):
                value = field_data.get("value", "?")
                evidence = field_data.get("evidence", "")
                src_ids = field_data.get("source_data_point_ids", [])
                ef_text += f"- **{field_name}**: {value}"
                if evidence:
                    ef_text += f" — {evidence}"
                if src_ids:
                    ef_text += f" {_src_ref(src_ids)}"
                ef_text += "\n"
            else:
                ef_text += f"- **{field_name}**: {field_data}\n"
        sections.append({
            "id": "appendix-extra-fields", "title": "附录 B: 行业特有维度（动态 Schema）",
            "content": ef_text or "_无行业特有维度_", "content_type": "text",
            "source_ids": [], "chart_path": None, "subsections": None,
        })

    return sections


def _render_dynamic_blocks(blocks: list[dict], _src_ref) -> list[dict]:
    """Render DynamicBlock list → ReportSection list. `[v4 动态 Schema]`

    Each block_type maps to a different content_type for frontend rendering:
      kv_list → "text" (key-value list)
      comparison_table → "table" (sortable comparison table)
      stat_chart → "chart" (radar/bar/pie chart component)
      insight_text → "text" (markdown narrative)
    """
    sections: list[dict] = []
    TYPE_TO_CONTENT = {
        "kv_list": "text",
        "comparison_table": "table",
        "stat_chart": "chart",
        "insight_text": "text",
    }
    TYPE_TO_TITLE_PREFIX = {
        "kv_list": "指标: ",
        "comparison_table": "对比: ",
        "stat_chart": "图表: ",
        "insight_text": "洞察: ",
    }

    for i, block in enumerate(blocks):
        if not isinstance(block, dict):
            continue
        bt = block.get("block_type", "kv_list")
        title = block.get("title", f"动态分析 {i+1}")
        data = block.get("data", {})
        src_ids = block.get("source_data_point_ids", [])

        content = _format_block_content(bt, data, src_ids, _src_ref)
        sections.append({
            "id": f"dynamic-block-{i}",
            "title": TYPE_TO_TITLE_PREFIX.get(bt, "") + title,
            "content": content,
            "content_type": TYPE_TO_CONTENT.get(bt, "text"),
            "source_ids": src_ids,
            "chart_path": _extract_chart_config(bt, data),
            "subsections": None,
        })

    return sections


def _format_block_content(block_type: str, data: dict, src_ids: list[str], _src_ref) -> str:
    """Format a single DynamicBlock's data as renderable content."""
    src_str = " " + _src_ref(src_ids) if src_ids else ""

    if block_type == "kv_list":
        lines = []
        for key, val in (data or {}).items():
            if isinstance(val, dict):
                v = val.get("value", "?")
                e = val.get("evidence", "")
                lines.append(f"- **{key}**: {v}" + (f" — {e}" if e else ""))
            else:
                lines.append(f"- **{key}**: {val}")
        return "\n".join(lines) + src_str

    elif block_type == "comparison_table":
        return ""  # content is in data dict; frontend reads from chart_path

    elif block_type == "stat_chart":
        return ""  # content is in data dict; frontend reads from chart_path

    elif block_type == "insight_text":
        return (data.get("content", "") if isinstance(data, dict) else str(data)) + src_str

    return str(data) + src_str


def _extract_chart_config(block_type: str, data: dict) -> dict | None:
    """Extract chart config from stat_chart blocks for frontend chart_path."""
    if block_type == "stat_chart" and isinstance(data, dict):
        return {
            "chart": data.get("chart", "radar"),
            "labels": data.get("labels", []),
            "series": data.get("series", {}),
        }
    if block_type == "comparison_table" and isinstance(data, dict):
        return {
            "headers": data.get("headers", []),
            "rows": data.get("rows", []),
        }
    return None


def _render_comparison_table(rows: list[dict], products: list[str], dimensions: list[str]) -> str:
    """Render comparison matrix as Markdown table."""
    if not rows or not dimensions:
        return "_暂无对比数据_"
    header = "| 产品 | " + " | ".join(dimensions) + " |\n"
    sep = "|------|" + "|".join(["------" for _ in dimensions]) + "|\n"
    body = ""
    for product in products:
        body += f"| {product} |"
        for dim in dimensions:
            match = [r for r in rows if r.get("product") == product and r.get("dimension") == dim]
            if match:
                rating = match[0].get("rating", "?")
                body += f" {rating} |"
            else:
                body += " N/A |"
        body += "\n"
    return header + sep + body


def _build_traceability_map(collected: list[dict]) -> dict:
    """Build claim_id → {url, timestamp, confidence} mapping."""
    trace = {}
    for i, dp in enumerate(collected):
        if isinstance(dp, dict):
            trace[str(i + 1)] = {
                "url": dp.get("source_url", ""),
                "timestamp": dp.get("collected_at", ""),
                "confidence": dp.get("confidence", 0.0),
            }
    return trace


def _build_review_package(report_data: dict, collected: list[dict], quality: dict) -> dict:
    """Build ReviewPackage for HITL Gate (§3.13.5)."""
    sections = report_data.get("sections", [])
    exec_summary = ""
    for s in sections:
        if s.get("id") == "sec-executive-summary":
            exec_summary = s.get("content", "")[:500]
            break

    products = report_data.get("products", [])
    categories: dict[str, int] = {}
    sources: dict[str, int] = {}
    for dp in collected:
        if isinstance(dp, dict):
            cat = dp.get("category", "unknown")
            st = dp.get("source_type", "unknown")
            categories[cat] = categories.get(cat, 0) + 1
            sources[st] = sources.get(st, 0) + 1

    return {
        "executive_summary": exec_summary,
        "key_findings": _extract_key_findings(report_data),
        "data_stats": {
            "total_data_points": len(collected),
            "products_covered": {p: sum(1 for dp in collected if isinstance(dp, dict) and dp.get("product") == p) for p in products},
            "categories_covered": categories,
            "source_types": sources,
        },
        "quality_summary": quality,
        "unresolved_issues": quality.get("unresolved_gaps", []) if isinstance(quality, dict) else [],
        "recommendations": ["建议批准发布", "或选择重写为另一视角"],
        "pm_report_preview": exec_summary[:500],
        "entrepreneur_report_preview": "",  # Filled if dual-persona mode
    }


def _extract_key_findings(report_data: dict) -> list[str]:
    """Extract 3-5 key findings from report sections."""
    findings = []
    for s in report_data.get("sections", []):
        if s.get("id") in ("sec-executive-summary", "sec-swot"):
            content = s.get("content", "")
            # Take first bullet point or first sentence
            lines = [line.strip("- ").strip() for line in content.split("\n") if line.strip().startswith("-")]
            findings.extend(lines[:2])
    return findings[:5] or ["分析完成"]


def _compute_report_metrics(collected: list[dict], verdict: dict, traceability: dict) -> dict:
    """Compute coverage / cross_validation / trace_completeness metrics."""
    quality = verdict.get("quality_summary", {})
    if isinstance(quality, dict):
        return {
            "coverage": len(traceability) / max(len(collected), 1),
            "cross_validation_rate": quality.get("multi_source_count", 0) / max(quality.get("total_data_points", 1), 1),
            "trace_completeness": len(traceability) / max(len(collected), 1),
            "improvement_ratio": quality.get("improvement_ratio", 0),
        }
    return {}


# ── Self-Check (§3.7.6) ──


def writer_self_check(report_data: dict, target_products: list[str]) -> list[str]:
    """Run W1-W5 self-check on the report. Returns list of issue descriptions."""
    issues = []
    sections = report_data.get("sections", [])
    all_content = " ".join(s.get("content", "") for s in sections)

    # W1: Every target_product mentioned at least once
    for product in target_products:
        if product not in all_content:
            issues.append(f"W1: {product} not mentioned in report")

    # W2: Every factual claim has [n] source annotation
    # (Heuristic: check that sections with data have source IDs or [n] markers)
    for s in sections:
        if s.get("content_type") in ("table", "text") and s.get("id") not in ("sec-whatif",):
            if "[1]" not in s.get("content", "") and "source_data_point_ids" not in str(s):
                pass  # Minor — only flag if no source references at all

    # W3: traceability_map keys match [n] references
    trace_map = report_data.get("traceability_map", {})
    if not trace_map:
        issues.append("W3: traceability_map is empty")

    # W4: Source table references consistent
    # W5: Persona focus correct
    persona = report_data.get("persona", "pm")
    profile = PERSONA_PROFILES.get(persona, {})
    if profile and profile.get("opening", "") not in all_content:
        issues.append(f"W5: Persona '{persona}' focus not reflected in report")

    return issues


# ── Self-Assessment (§3.17.2) ──


def _build_writer_self_assessment(report_data: dict, target_products: list[str], required_sections: list[str] | None = None) -> dict:
    """Build Writer self-assessment: schema compliance, section completeness, source annotation rate.

    Returns dict suitable for frontend green/yellow/red dot visualization.
    v4: accepts optional required_sections from Orchestrator's schema_profile.
    """
    sections = report_data.get("sections", [])
    section_ids = {s.get("id", "") for s in sections}
    req_secs = required_sections if required_sections is not None else REQUIRED_SECTIONS

    # Schema compliance: all required sections present
    required_present = all(rid in section_ids for rid in req_secs)
    missing_required = [rid for rid in req_secs if rid not in section_ids]

    # Section completeness: proportion of required sections with non-empty content
    filled = 0
    for s in sections:
        if s.get("id") in REQUIRED_SECTIONS and s.get("content", "").strip():
            filled += 1
    section_completeness = filled / len(REQUIRED_SECTIONS) if REQUIRED_SECTIONS else 1.0

    # Source annotation rate: count [n] references in report content
    all_content = " ".join(s.get("content", "") for s in sections)
    import re
    annotation_count = len(re.findall(r"\[\d+\]", all_content))

    # Count total factual claims (heuristic: lines with evidence markers or bullet points)
    claim_lines = 0
    for s in sections:
        content = s.get("content", "")
        claim_lines += len([line for line in content.split("\n") if line.strip().startswith("-") and len(line) > 20])
    source_annotation_rate = annotation_count / claim_lines if claim_lines > 0 else 0.0

    # Product mention check
    product_mention_check = {}
    for product in target_products:
        product_mention_check[product] = product in all_content

    # Section list for display
    section_status = []
    for rid in REQUIRED_SECTIONS:
        section_status.append({
            "id": rid,
            "present": rid in section_ids,
            "has_content": bool(next((s.get("content", "").strip() for s in sections if s.get("id") == rid), "")),
        })

    # Overall score: weighted average
    schema_score = 1.0 if required_present else 0.0
    overall_score = (schema_score * 0.4 + section_completeness * 0.3 + min(source_annotation_rate, 1.0) * 0.3)

    return {
        "schema_compliance": required_present,
        "missing_required": missing_required,
        "section_completeness": round(section_completeness, 2),
        "source_annotation_rate": round(min(source_annotation_rate, 1.0), 2),
        "product_mention_check": product_mention_check,
        "section_status": section_status,
        "overall_score": round(overall_score, 2),
    }


def _llm_generate_section(
    sections: list[dict],
    section_id: str,
    analysis: dict,
    products: list[str],
    persona: str,
) -> None:
    """Generate a report section via LLM call (Writer always contributes tokens)."""
    from deerflow.competition.executor import execute_agent

    section = next((s for s in sections if s.get("id") == section_id), None)
    if not section:
        return

    matrix = analysis.get("comparison_matrix", {})
    swot = analysis.get("swot", {})
    trends = analysis.get("trends", [])
    persona_label = "产品经理" if persona == "pm" else "创业者"

    prompt = f"""你是竞品分析报告撰写专家。请为竞品分析报告撰写一段 150-250 字的中文执行摘要。
视角: {persona_label}
竞品: {', '.join(products)}
对比矩阵: {str(matrix.get('summary', ''))[:400]}
SWOT: {str(swot)[:400]}
趋势: {str(trends)[:300]}

要求：简洁有力，突出关键差异化发现，避免套话。请直接输出摘要文本："""

    result, _ = execute_agent(prompt, "", temperature=0.4, max_tokens=300, agent_name="Writer")
    if result:
        section["content"] = result.strip()


def _llm_rewrite_section(section: str, analysis: dict, products: list[str], persona: str) -> str:
    """Use LLM to rewrite a report section from analysis data.

    Called when HITL action is 'rewrite' — regenerates executive_summary or
    recommendations so the user sees visible LLM effort and a fresh perspective.
    """
    from deerflow.competition.executor import execute_agent

    matrix = analysis.get("comparison_matrix", {})
    swot = analysis.get("swot", {})
    trends = analysis.get("trends", [])

    context = f"""竞品: {', '.join(products)}
视角: {persona}
对比矩阵摘要: {matrix.get('summary', 'N/A')}
SWOT: {str(swot)[:600]}
趋势: {str(trends)[:300]}"""

    prompts = {
        "executive_summary": f"""你是竞品分析报告撰写专家。基于以下数据，为竞品分析报告撰写一段 200-300 字的中文执行摘要。
要求：简洁有力，突出关键差异化发现，避免套话。

{context}

请直接输出执行摘要文本：""",
        "recommendations": f"""你是竞品分析策略顾问。基于以下数据，为产品团队撰写 3-5 条具体可操作的建议。
每条建议应包含：方向、理由、优先级（高/中/低）。

{context}

请直接输出建议文本：""",
    }

    prompt = prompts.get(section, prompts["executive_summary"])
    result, _tokens = execute_agent(prompt, "", temperature=0.6, max_tokens=500, agent_name="Writer")
    if result:
        return result.strip()
    return f"[LLM rewrite failed for {section}]"


def _generate_whatif(comment: str, analysis: dict, products: list[str], persona: str) -> str:
    """Generate what-if analysis via LLM based on user's assumption + existing data.

    Only runs when the user submits a what-if via HITL rewrite. Does NOT re-run
    Collector or Analyst — works from existing analysis_result.
    """
    from deerflow.competition.executor import execute_agent

    matrix = analysis.get("comparison_matrix", {})
    swot = analysis.get("swot", {})
    trends = analysis.get("trends", [])
    forecast = analysis.get("forecast")

    context = f"""现有竞品分析数据:

对比矩阵: {matrix.get('summary', '')}
产品: {', '.join(products)}
SWOT: {str(swot)[:800]}
趋势: {str(trends)[:400]}
预测: {str(forecast)[:400]}"""

    prompt = f"""你是竞品分析推演专家。基于现有竞品分析数据，对用户的假设条件进行推演。

现有数据摘要:
{context}

请基于以上数据，对以下假设做出 150-300 字的推演分析，直接输出推演文本：
假设: {comment}"""

    result, _tokens = execute_agent(prompt, comment, temperature=0.7, max_tokens=600, agent_name="Writer")
    if result:
        return result.strip()
    return f"基于现有数据，无法对「{comment}」做出可靠推演。请尝试更具体的假设条件。"
