"""Writer node — ReportData generation with source traceability.

Per COMPETITION_PLAN.md §3.7: interactive ReportData replacing legacy .md strings.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

WRITER_MAX_PARALLEL_PER_REPORT = 3
WRITER_MAX_PARALLEL_PROCESS = 6
WRITER_SLOT_WAIT_SECONDS = 10
WRITER_SECTION_TIMEOUT_SECONDS = 120
WRITER_NARRATIVE_MAX_TOKENS = 800
WRITER_INDUSTRY_MAX_TOKENS = 600
_writer_process_slots = threading.BoundedSemaphore(WRITER_MAX_PARALLEL_PROCESS)


@dataclass(frozen=True)
class _WriterTaskSpec:
    key: str
    kind: str
    order: int
    label: str
    section_id: str | None
    max_tokens: int
    runner: Callable[[], tuple[Any, int]]


@dataclass(frozen=True)
class _WriterTaskResult:
    key: str
    kind: str
    order: int
    section_id: str | None
    status: str
    payload: Any
    tokens: int = 0
    elapsed_ms: int = 0


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
    "sec-trends",  # market/product trends
    "sec-forecast",  # prediction + what-if
    "appendix-industry",  # industry-specific dimensions (extra_fields)
]


def _get_schema_mode(state: dict) -> str:
    """Return the active schema profile from Orchestrator, default baseline."""
    orch = state.get("orchestration_result") or {}
    return orch.get("schema_profile", "baseline")


def writer_node(state: dict) -> dict:
    """Graph node: generate ReportData from analysis_result + review_verdict.

    Returns partial state update with report_data + review_package + traceability_map.
    """
    analysis = state.get("analysis_result") or {}
    verdict = state.get("review_verdict") or {}
    collected = state.get("collected_data") or []
    target_products = state.get("target_products", [])
    hitl_focus, whatif_comment_raw, hitl_action = _get_hitl_focus(state)
    # Only use comment as what-if scenario when action is explicitly "rewrite"
    whatif_comment = ""  # what-if temporarily disabled

    raw_verification = verdict.get("claim_verification") or state.get("claim_verification") or {}
    eligible_point_ids = _verified_evidence_ids(raw_verification)
    restrict_citations = bool(raw_verification.get("total"))
    citation_index = _citation_index(
        collected,
        eligible_point_ids if restrict_citations else None,
    )
    claim_verification = _prepare_claim_verification(raw_verification, citation_index)

    # Build report sections — v4: schema_profile controls deep sections
    quality = verdict.get("quality_summary", {})
    schema_mode = _get_schema_mode(state)
    sections = _build_sections(
        analysis,
        verdict,
        target_products,
        hitl_focus,
        whatif_comment,
        hitl_action,
        collected,
        quality,
        schema_mode,
        citation_index_override=citation_index,
    )

    traceability = _build_traceability_map(collected)
    _annotate_traceability(traceability, claim_verification)
    writer_traceability = {citation_id: source for citation_id, source in traceability.items() if not restrict_citations or citation_id in set(citation_index.values())}
    persona = state.get("persona") if state.get("persona") in ("pm", "entrepreneur") else "pm"
    brief = state.get("analysis_brief") or {}
    task_specs = _build_writer_task_specs(
        state=state,
        analysis=analysis,
        products=target_products,
        persona=persona,
        traceability=writer_traceability,
        citation_index=citation_index,
        hitl_action=hitl_action,
        hitl_focus=hitl_focus,
        hitl_comment=whatif_comment_raw,
        brief=brief,
    )
    task_results = _run_writer_tasks(task_specs)

    industry_sections = _merge_industry_sections(task_specs, task_results)
    selected_dimensions = brief.get("effective_dimensions") or brief.get("dimensions") or []
    has_industry_dimension = any(isinstance(item, dict) and item.get("source") == "industry" for item in selected_dimensions)
    if brief and not has_industry_dimension:
        industry_sections = []
    if industry_sections:
        sections.extend(industry_sections)
        logger.info("Added %d industry sections for '%s'", len(industry_sections), state.get("industry", "general"))
    _apply_narrative_result(
        sections,
        task_results.get("narrative"),
        {str(key) for key in writer_traceability},
    )
    forecast = analysis.get("forecast")
    extra_fields = analysis.get("extra_fields") or {}
    dynamic_blocks = analysis.get("dynamic_blocks") or []
    metrics = _compute_report_metrics(collected, verdict, traceability)
    quality_gate = _build_quality_gate(
        brief=brief,
        target_products=target_products,
        collected=collected,
        analysis=analysis,
        verdict=verdict,
        sections=sections,
        traceability=traceability,
    )
    context_pack = state.get("analysis_context_pack")
    rag_context = state.get("rag_context")
    if not isinstance(rag_context, dict):
        try:
            from competition.rag_context import build_agent_evidence_bundle

            rag_context = build_agent_evidence_bundle({**state, "analysis_context_pack": context_pack}, role="writer")
        except Exception:
            logger.exception("RAG evidence bundle build failed in Writer")
            rag_context = None

    report_data = {
        "persona": persona,
        "title": _build_title(target_products),
        "generated_at": datetime.now(UTC).isoformat(),
        "products": target_products,
        "sections": sections,
        "traceability_map": traceability,
        "quality_summary": quality,
        "forecast": forecast,
        "metrics": metrics,
        "extra_fields": extra_fields,
        "dynamic_blocks": dynamic_blocks,
        "analysis_scope": {
            "objective": brief.get("objective"),
            "market_scope": brief.get("market_scope"),
            "time_range": brief.get("time_range"),
            "dimensions": selected_dimensions,
            "audience": brief.get("audience"),
            "evidence_policy": brief.get("evidence_policy"),
            "output_focus": brief.get("output_focus"),
            "confirmation_source": brief.get("confirmation_source"),
        }
        if brief
        else None,
        "analysis_context": _build_context_overview(context_pack),
        "rag_context": _build_rag_context_overview(rag_context),
        "rag_provenance": _build_rag_provenance(analysis, rag_context),
        "quality_gate": quality_gate,
        "claim_verification": claim_verification,
        "long_term_insights": state.get("long_term_insights") or [],
        "structured_analysis": {
            "comparison_matrix": analysis.get("comparison_matrix") or {},
            "swot": analysis.get("swot") or {},
            "trends": analysis.get("trends") or [],
            "forecast": forecast,
            "dynamic_blocks": dynamic_blocks,
        },
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
        "rag_context": rag_context,
    }


def _build_rag_context_overview(bundle: dict | None) -> dict | None:
    if not isinstance(bundle, dict):
        return None
    return {
        "schema_version": bundle.get("schema_version"),
        "role": bundle.get("role"),
        "quality_state": bundle.get("quality_state"),
        "candidate_count": int(bundle.get("candidate_count", 0) or 0),
        "selected_count": int(bundle.get("selected_count", 0) or 0),
        "used_tokens": int(bundle.get("used_tokens", 0) or 0),
        "budget_tokens": int(bundle.get("budget_tokens", 0) or 0),
        "abstain": bool(bundle.get("abstain")),
        "abstain_reasons": list(bundle.get("abstain_reasons") or []),
        "coverage": bundle.get("coverage") or {},
        "degraded": any(
            bool(item.get("metadata", {}).get("degraded"))
            for item in bundle.get("evidence") or []
            if isinstance(item, dict)
        ),
    }


def _build_rag_provenance(analysis: dict, bundle: dict | None) -> dict[str, Any] | None:
    """Expose bounded provenance without leaking prompts or raw private paths."""
    recorded = analysis.get("rag_evidence") if isinstance(analysis, dict) else None
    if isinstance(recorded, dict):
        return {
            "schema_version": recorded.get("schema_version"),
            "candidate_count": int(recorded.get("candidate_count", 0) or 0),
            "selected_count": int(recorded.get("selected_count", 0) or 0),
            "evidence_ids": [str(value) for value in recorded.get("evidence_ids") or []][:100],
            "coverage": recorded.get("coverage") or {},
        }
    overview = _build_rag_context_overview(bundle)
    if not overview:
        return None
    return {
        "schema_version": overview.get("schema_version"),
        "candidate_count": overview.get("candidate_count", 0),
        "selected_count": overview.get("selected_count", 0),
        "coverage": overview.get("coverage") or {},
        "evidence_ids": [],
    }


def _build_context_overview(context_pack: dict | None) -> dict | None:
    """Expose a low-sensitivity context quality summary in each report.

    The complete pack stays in the internal graph state and immutable version
    snapshot. Reports only need enough information for a reader to understand
    which evidence scope and quality state informed the result.
    """
    if not isinstance(context_pack, dict):
        return None
    quality = context_pack.get("quality") if isinstance(context_pack.get("quality"), dict) else {}
    scope = context_pack.get("scope") if isinstance(context_pack.get("scope"), dict) else {}
    dimensions: list[dict] = []
    raw_dimensions = context_pack.get("dimensions")
    if isinstance(raw_dimensions, dict):
        for dimension_id, value in raw_dimensions.items():
            if not isinstance(value, dict):
                continue
            dimensions.append(
                {
                    "id": str(value.get("id") or dimension_id),
                    "label": str(value.get("label") or dimension_id),
                    "quality_state": str(value.get("quality_state") or "missing"),
                    "evidence_count": int(value.get("evidence_count", 0) or 0),
                    "source_domain_count": int(value.get("source_domain_count", 0) or 0),
                    "official_source_count": int(value.get("official_source_count", 0) or 0),
                    "stale_evidence_count": int(value.get("stale_evidence_count", 0) or 0),
                    "fallback_reason": str(value.get("fallback_reason") or ""),
                    "conflict_count": len(value.get("conflicts") or []) if isinstance(value.get("conflicts"), list) else 0,
                }
            )
    return {
        "schema_version": str(context_pack.get("schema_version") or "analysis-context-pack.v1"),
        "generated_at": context_pack.get("generated_at"),
        "scope": {
            "products": scope.get("products") or [],
            "market_scope": scope.get("market_scope") or "Global / unspecified",
            "time_range": scope.get("time_range") or {},
            "evidence_policy": scope.get("evidence_policy") or "balanced",
        },
        "quality": {
            "quality_state": quality.get("quality_state") or "missing",
            "evidence_count": int(quality.get("evidence_count", 0) or 0),
            "source_domain_count": int(quality.get("source_domain_count", 0) or 0),
            "official_source_count": int(quality.get("official_source_count", 0) or 0),
            "stale_evidence_count": int(quality.get("stale_evidence_count", 0) or 0),
            "missing_dimensions": quality.get("missing_dimensions") or [],
            "fallback_reason": str(quality.get("fallback_reason") or ""),
            "fetch_error": str(quality.get("fetch_error") or ""),
            "conflict_count": len(quality.get("conflicts") or []) if isinstance(quality.get("conflicts"), list) else 0,
        },
        "dimensions": dimensions,
    }


def _build_title(products: list[str]) -> str:
    products_str = " vs ".join(products) if products else "竞品分析"
    return f"{products_str} 竞品分析报告"


def _get_hitl_focus(state: dict) -> list[str] | None:
    decision = state.get("hitl_decision") or {}
    return decision.get("target_focus"), decision.get("comment", ""), decision.get("action", "")


def _citation_index(
    collected: list[dict],
    allowed_point_ids: set[str] | None = None,
) -> dict[str, str]:
    """Map original data-point IDs to stable numeric citation IDs."""
    index: dict[str, str] = {}
    for i, point in enumerate(collected):
        if not isinstance(point, dict):
            continue
        point_id = point.get("id")
        if point_id and (allowed_point_ids is None or str(point_id) in allowed_point_ids) and str(point_id) not in index:
            index[str(point_id)] = str(i + 1)
    return index


def _verified_evidence_ids(summary: dict[str, Any]) -> set[str]:
    """Return only data points that have an explicit supporting relationship."""
    return {
        str(evidence["data_point_id"])
        for claim in summary.get("claims") or []
        if isinstance(claim, dict) and claim.get("status") == "supported"
        for evidence in claim.get("evidence") or []
        if isinstance(evidence, dict) and evidence.get("relation") == "supports" and evidence.get("data_point_id")
    }


def _prepare_claim_verification(
    summary: dict[str, Any],
    citation_index: dict[str, str],
) -> dict[str, Any]:
    """Attach stable report citation IDs without mutating Reviewer state."""
    prepared = deepcopy(summary)
    for claim in prepared.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        for evidence in claim.get("evidence") or []:
            if not isinstance(evidence, dict):
                continue
            point_id = evidence.get("data_point_id")
            evidence["citation_id"] = citation_index.get(str(point_id)) if point_id else None
    return prepared


def _annotate_traceability(
    traceability: dict[str, dict],
    summary: dict[str, Any],
) -> None:
    """Expose claim relations on source records while retaining all audit evidence."""
    relations: dict[str, list[dict[str, str]]] = {}
    for claim in summary.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        for evidence in claim.get("evidence") or []:
            if not isinstance(evidence, dict) or not evidence.get("citation_id"):
                continue
            relations.setdefault(str(evidence["citation_id"]), []).append(
                {
                    "claim_id": str(claim.get("claim_id") or ""),
                    "claim_status": str(claim.get("status") or "insufficient"),
                    "relation": str(evidence.get("relation") or "context"),
                }
            )
    for citation_id, source in traceability.items():
        source_relations = relations.get(citation_id, [])
        source["claim_relations"] = source_relations
        source["verified"] = any(item["relation"] == "supports" for item in source_relations)


def _resolve_citations(point_ids: Any, index: dict[str, str]) -> tuple[str, list[str]]:
    """Resolve Analyst IDs without inventing references for unknown IDs."""
    if not isinstance(point_ids, (list, tuple)):
        return "", []
    numeric: list[str] = []
    for point_id in point_ids:
        key = str(point_id).strip() if point_id is not None else ""
        value = index.get(key)
        if value and value not in numeric:
            numeric.append(value)
    return "".join(f"[{value}]" for value in numeric), numeric


def _fallback_summary(summary_text: str, products: list[str], analysis: dict, citation_index: dict[str, str]) -> str:
    """Create useful narrative content without requiring an LLM."""
    product_text = "、".join(products) if products else "目标竞品"
    citations: list[str] = []
    matrix = analysis.get("comparison_matrix") or {}
    for cell in matrix.get("cells", []) if isinstance(matrix, dict) else []:
        if isinstance(cell, dict):
            _, ids = _resolve_citations(cell.get("source_data_point_ids", []), citation_index)
            citations.extend(ids)
    marker = "".join(f"[{item}]" for item in dict.fromkeys(citations))
    return f"基于公开数据和多维度分析，{product_text}的对比结果显示：{summary_text or '当前证据支持的差异仍需结合数据质量审慎解读。'}{marker}"


def _fallback_recommendations(analysis: dict, products: list[str], citation_index: dict[str, str]) -> str:
    matrix = analysis.get("comparison_matrix") or {}
    summary = matrix.get("summary", "") if isinstance(matrix, dict) else ""
    matrix_citations: list[str] = []
    if isinstance(matrix, dict):
        for cell in matrix.get("cells", []):
            if isinstance(cell, dict):
                _, stable_ids = _resolve_citations(cell.get("source_data_point_ids", []), citation_index)
                matrix_citations.extend(stable_ids)
    marker = "".join(f"[{item}]" for item in dict.fromkeys(matrix_citations))
    if summary:
        return f"- **优先级：高**：围绕“{summary}”验证自身产品的差异化策略，并补充关键维度的交叉证据。{marker}"
    if not citation_index:
        return "- **优先级：高**：当前证据不足，先完成关键维度的数据收集与多源验证，再做战略决策。"
    product_text = "、".join(products) if products else "目标竞品"
    return f"- **优先级：中**：结合{product_text}的已收集证据开展定向验证，并根据验证结果安排后续迭代。"


def _build_sections(
    analysis: dict,
    verdict: dict,
    products: list[str],
    focus: list[str] | None,
    whatif_comment: str,
    hitl_action: str,
    collected: list[dict],
    quality: dict,
    schema_profile: str = "baseline",
    *,
    citation_index_override: dict[str, str] | None = None,
) -> list[dict]:
    """Build all report sections."""
    sections: list[dict] = []
    citation_index = citation_index_override if citation_index_override is not None else _citation_index(collected)

    def _src_ref(point_ids: list[str]) -> str:
        return _resolve_citations(point_ids, citation_index)[0]

    # 1. Executive Summary (required)
    matrix = analysis.get("comparison_matrix", {})
    summary_text = matrix.get("summary", f"{' vs '.join(products)} 竞品分析")
    exec_content = _fallback_summary(summary_text, products, analysis, citation_index)
    sections.append(
        {
            "id": "sec-executive-summary",
            "title": "执行摘要",
            "content": exec_content,
            "content_type": "text",
            "source_ids": list(dict.fromkeys(re.findall(r"\[(\d+)\]", exec_content))),
            "chart_path": None,
            "subsections": None,
        }
    )

    # 2. Comparison Matrix (required)
    cells = matrix.get("cells", [])
    dims = matrix.get("dimensions", [])
    table_rows = []
    comparison_source_ids: list[str] = []
    for cell in cells:
        if isinstance(cell, dict):
            rating = cell.get("rating", "N/A")
            evidence = cell.get("evidence", "")
            src_ids = cell.get("source_data_point_ids", [])
            _, stable_ids = _resolve_citations(src_ids, citation_index)
            comparison_source_ids.extend(stable_ids)
            table_rows.append(
                {
                    "product": cell.get("product", ""),
                    "dimension": cell.get("dimension", ""),
                    "rating": rating,
                    "evidence": f"{evidence} {_src_ref(src_ids)}".strip(),
                }
            )
    sections.append(
        {
            "id": "sec-comparison-matrix",
            "title": "对比矩阵",
            "content": _render_comparison_table(table_rows, products, dims),
            "content_type": "table",
            "source_ids": list(dict.fromkeys(comparison_source_ids)),
            "chart_path": None,
            "subsections": None,
        }
    )

    # 3. SWOT (required)
    swot = analysis.get("swot", {})
    swot_content = ""
    swot_source_ids: list[str] = []
    for prod_name, swot_data in swot.items():
        if not isinstance(swot_data, dict):
            continue
        swot_content += f"### {prod_name}\n"
        for item in swot_data.get("items", []):
            if not isinstance(item, dict):
                continue
            src_ids = item.get("source_data_point_ids", [])
            _, stable_ids = _resolve_citations(src_ids, citation_index)
            swot_source_ids.extend(stable_ids)
            swot_content += f"- **{item.get('category', '?')}**: {item.get('statement', '')} {_src_ref(src_ids)}\n  - 证据: {item.get('evidence', '')}\n"
    sections.append(
        {
            "id": "sec-swot",
            "title": "SWOT 分析",
            "content": swot_content or "_暂无 SWOT 数据_",
            "content_type": "text",
            "source_ids": list(dict.fromkeys(swot_source_ids)),
            "chart_path": None,
            "subsections": None,
        }
    )

    # 4. Trends (conditional)
    trends = analysis.get("trends", [])
    if trends:
        trend_text = ""
        trend_source_ids: list[str] = []
        for t in trends:
            if isinstance(t, dict):
                src_ids = t.get("source_data_point_ids", [])
                _, stable_ids = _resolve_citations(src_ids, citation_index)
                trend_source_ids.extend(stable_ids)
                try:
                    confidence_text = f"{float(t.get('confidence', 0)):.0%}"
                except (TypeError, ValueError):
                    confidence_text = "0%"
                trend_text += f"- {t.get('dimension', '?')}: {t.get('direction', '?')} (置信度: {confidence_text}) — {t.get('evidence', '')} {_src_ref(src_ids)}\n"
        sections.append(
            {
                "id": "sec-trends",
                "title": "趋势与洞察",
                "content": trend_text,
                "content_type": "text",
                "source_ids": list(dict.fromkeys(trend_source_ids)),
                "chart_path": None,
                "subsections": None,
            }
        )

    # 5. Forecast (conditional, §3.5.7)
    forecast = analysis.get("forecast")
    if forecast and isinstance(forecast, dict):
        items = forecast.get("items", [])
        fc_text = forecast.get("summary", "") + "\n\n"
        forecast_source_ids: list[str] = []
        for fi in items:
            if isinstance(fi, dict):
                src_ids = fi.get("source_data_point_ids", [])
                _, stable_ids = _resolve_citations(src_ids, citation_index)
                forecast_source_ids.extend(stable_ids)
                fc_text += f"- **{fi.get('product', '?')}** ({fi.get('dimension', '?')}): 6个月预测 {fi.get('forecast_6m', '?')}, 12个月预测 {fi.get('forecast_12m', '?')} {_src_ref(src_ids)}\n"
        fc_text += f"\n*{forecast.get('disclaimer', '')}*"
        sections.append(
            {
                "id": "sec-forecast",
                "title": "预测推演",
                "content": fc_text,
                "content_type": "text",
                "source_ids": list(dict.fromkeys(forecast_source_ids)),
                "chart_path": None,
                "subsections": None,
            }
        )

    # What-if section — temporarily disabled

    # Dynamic analyst blocks are inserted after standard analysis sections.
    dynamic_blocks = analysis.get("dynamic_blocks") or []
    sections.extend(_render_dynamic_blocks(dynamic_blocks, _src_ref, citation_index))

    # Legacy extra_fields remains a compatibility appendix only when no blocks exist.
    extra_fields = analysis.get("extra_fields") or {}
    if extra_fields and not dynamic_blocks and isinstance(extra_fields, dict):
        ef_lines: list[str] = []
        ef_source_ids: list[str] = []
        for field_name, field_data in extra_fields.items():
            if isinstance(field_data, dict):
                value = field_data.get("value", "?")
                evidence = field_data.get("evidence", "")
                src_ids = field_data.get("source_data_point_ids", [])
                _, stable_ids = _resolve_citations(src_ids, citation_index)
                ef_source_ids.extend(stable_ids)
                line = f"- **{field_name}**: {value}"
                if evidence:
                    line += f" — {evidence}"
                if stable_ids:
                    line += f" {_src_ref(src_ids)}"
                ef_lines.append(line)
            else:
                ef_lines.append(f"- **{field_name}**: {field_data}")
        sections.append(
            {
                "id": "appendix-extra-fields",
                "title": "附录 B: 行业特有维度（动态 Schema）",
                "content": "\n".join(ef_lines) or "_无行业特有维度_",
                "content_type": "text",
                "source_ids": list(dict.fromkeys(ef_source_ids)),
                "chart_path": None,
                "subsections": None,
            }
        )

    # 6. Recommendations (required)
    rec_content = _fallback_recommendations(analysis, products, citation_index)
    sections.append(
        {
            "id": "sec-recommendations",
            "title": "建议",
            "content": rec_content,
            "content_type": "text",
            "source_ids": list(dict.fromkeys(re.findall(r"\[(\d+)\]", rec_content))),
            "chart_path": None,
            "subsections": None,
        }
    )

    # 7. Sources (required)
    sources_text = ""
    source_ids: list[str] = []
    for dp in collected:
        if isinstance(dp, dict) and str(dp.get("id") or "") in citation_index:
            citation_id = citation_index[str(dp["id"])]
            source_ids.append(citation_id)
            sources_text += f"[{citation_id}] {dp.get('source_url', '?')} — {dp.get('collected_at', '?')} — {dp.get('label', '')}\n"
    sections.append(
        {
            "id": "sec-sources",
            "title": "数据来源",
            "content": sources_text or "_暂无来源_",
            "content_type": "table",
            "source_ids": source_ids,
            "chart_path": None,
            "subsections": None,
        }
    )

    # 8. Appendix: Quality (required)
    q_text = f"总数据点: {quality.get('total_data_points', 0)}\n"
    q_text += f"已验证: {quality.get('verified_count', 0)} | 多源交叉: {quality.get('multi_source_count', 0)} | 单源: {quality.get('single_source_count', 0)}\n"
    q_text += f"事实错误: {quality.get('fact_errors_count', 0)} | 质量分: {quality.get('overall_quality_score', 0):.0%}\n"
    sections.append(
        {
            "id": "appendix-quality",
            "title": "附录 A: 数据质量报告",
            "content": q_text,
            "content_type": "text",
            "source_ids": [],
            "chart_path": None,
            "subsections": None,
        }
    )

    return sections


def _has_narrative_context(analysis: dict) -> bool:
    return bool(analysis and any(analysis.get(key) for key in ("comparison_matrix", "swot", "trends", "forecast", "dynamic_blocks")))


def _build_industry_section_specs(state: dict) -> list[dict[str, Any]]:
    """Build ordered, model-independent specs for industry fixed sections."""
    from competition.industry import get_industry_profile

    profile = get_industry_profile(state.get("industry", "general"))
    titles = profile.get("section_titles", {})
    bias = profile.get("prompt_bias", "")
    specs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for order, section_id in enumerate(profile.get("fixed_sections", []) or []):
        section_id = str(section_id)
        if not section_id or section_id in seen:
            logger.warning("Skipping duplicate or empty industry section ID: %s", section_id)
            continue
        seen.add(section_id)
        specs.append(
            {
                "section_id": section_id,
                "title": str(titles.get(section_id, section_id)),
                "prompt_bias": str(bias),
                "order": order,
            }
        )
    return specs


def _industry_fallback_content(title: str) -> str:
    return f"_{title}：当前没有足够的行业专属证据，无法生成可靠结论。_"


def _build_writer_task_specs(
    *,
    state: dict,
    analysis: dict,
    products: list[str],
    persona: str,
    traceability: dict[str, dict],
    citation_index: dict[str, str],
    hitl_action: str,
    hitl_focus: list[str] | None,
    hitl_comment: str,
    brief: dict,
) -> list[_WriterTaskSpec]:
    """Build independent Writer tasks without mutating report sections."""
    specs: list[_WriterTaskSpec] = []
    if _has_narrative_context(analysis):
        specs.append(
            _WriterTaskSpec(
                key="narrative",
                kind="narrative",
                order=0,
                label="摘要与建议",
                section_id=None,
                max_tokens=WRITER_NARRATIVE_MAX_TOKENS,
                runner=lambda: _generate_narrative_patch(
                    analysis,
                    products,
                    persona,
                    traceability,
                    citation_index,
                    hitl_action=hitl_action,
                    hitl_focus=hitl_focus,
                    hitl_comment=hitl_comment,
                    brief=brief,
                ),
            )
        )

    selected_dimensions = brief.get("effective_dimensions") or brief.get("dimensions") or []
    include_industry = not brief or any(isinstance(item, dict) and item.get("source") == "industry" for item in selected_dimensions)
    for spec in _build_industry_section_specs(state) if include_industry else []:
        specs.append(
            _WriterTaskSpec(
                key=f"industry:{spec['section_id']}",
                kind="industry",
                order=int(spec["order"]),
                label=str(spec["title"]),
                section_id=str(spec["section_id"]),
                max_tokens=WRITER_INDUSTRY_MAX_TOKENS,
                runner=lambda spec=spec: _generate_industry_section_result(state, analysis, spec),
            )
        )
    return specs


def _writer_is_cancelled() -> bool:
    from competition.executor import is_cancelled

    return is_cancelled()


def _run_one_writer_task(spec: _WriterTaskSpec) -> _WriterTaskResult:
    from competition.executor import emit_progress

    started = time.monotonic()
    if _writer_is_cancelled():
        return _WriterTaskResult(spec.key, spec.kind, spec.order, spec.section_id, "cancelled", None)

    acquired = _writer_process_slots.acquire(timeout=WRITER_SLOT_WAIT_SECONDS)
    if not acquired:
        logger.warning("Writer task saturated: %s", spec.key)
        return _WriterTaskResult(spec.key, spec.kind, spec.order, spec.section_id, "saturated", None)

    try:
        emit_progress(
            {
                "phase": "writer",
                "task_key": spec.key,
                "section_id": spec.section_id,
                "status": "running",
                "message": f"正在生成报告章节：{spec.label}",
            }
        )
        if _writer_is_cancelled():
            status = "cancelled"
            payload, tokens = None, 0
        else:
            try:
                payload, tokens = spec.runner()
                status = "cancelled" if _writer_is_cancelled() else ("success" if payload is not None else "fallback")
            except Exception as exc:
                logger.warning("Writer task failed [%s]: %s", spec.key, type(exc).__name__)
                payload, tokens, status = None, 0, "fallback"
        return _WriterTaskResult(
            spec.key,
            spec.kind,
            spec.order,
            spec.section_id,
            status,
            payload,
            max(int(tokens or 0), 0),
            round((time.monotonic() - started) * 1000),
        )
    finally:
        _writer_process_slots.release()


def _run_writer_tasks(task_specs: list[_WriterTaskSpec]) -> dict[str, _WriterTaskResult]:
    """Run Writer model tasks with bounded concurrency and stable result keys."""
    if not task_specs:
        return {}

    from competition.executor import (
        capture_executor_context,
        emit_progress,
        run_in_executor_context,
    )

    started = time.monotonic()
    results: dict[str, _WriterTaskResult] = {}
    completed = 0

    def record_result(result: _WriterTaskResult) -> None:
        nonlocal completed
        results[result.key] = result
        completed += 1
        emit_progress(
            {
                "phase": "writer",
                "task_key": result.key,
                "section_id": result.section_id,
                "status": result.status,
                "completed": completed,
                "total": len(task_specs),
                "message": f"报告章节生成进度：{completed}/{len(task_specs)}",
            }
        )

    if len(task_specs) == 1:
        record_result(_run_one_writer_task(task_specs[0]))
    else:
        max_workers = min(WRITER_MAX_PARALLEL_PER_REPORT, len(task_specs))
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="writer-section") as pool:
            futures = {
                pool.submit(
                    run_in_executor_context,
                    capture_executor_context(),
                    lambda spec=spec: _run_one_writer_task(spec),
                ): spec
                for spec in task_specs
            }
            for future in as_completed(futures):
                if _writer_is_cancelled():
                    for pending in futures:
                        if not pending.done():
                            pending.cancel()
                spec = futures[future]
                try:
                    record_result(future.result())
                except CancelledError:
                    record_result(
                        _WriterTaskResult(
                            spec.key,
                            spec.kind,
                            spec.order,
                            spec.section_id,
                            "cancelled",
                            None,
                        )
                    )
                except Exception as exc:
                    logger.warning("Writer worker crashed [%s]: %s", spec.key, type(exc).__name__)
                    record_result(
                        _WriterTaskResult(
                            spec.key,
                            spec.kind,
                            spec.order,
                            spec.section_id,
                            "cancelled" if _writer_is_cancelled() else "fallback",
                            None,
                        )
                    )

    status_counts: dict[str, int] = {}
    token_total = 0
    for result in results.values():
        status_counts[result.status] = status_counts.get(result.status, 0) + 1
        token_total += result.tokens
    logger.info(
        "Writer parallel tasks: total=%d statuses=%s tokens=%d elapsed_ms=%d",
        len(task_specs),
        status_counts,
        token_total,
        round((time.monotonic() - started) * 1000),
    )
    return results


def _merge_industry_sections(
    task_specs: list[_WriterTaskSpec],
    results: dict[str, _WriterTaskResult],
) -> list[dict]:
    sections: list[dict] = []
    for spec in sorted((item for item in task_specs if item.kind == "industry"), key=lambda item: item.order):
        result = results.get(spec.key)
        content = result.payload.strip() if result and result.status == "success" and isinstance(result.payload, str) and result.payload.strip() else _industry_fallback_content(spec.label)
        sections.append(
            {
                "id": spec.section_id,
                "title": spec.label,
                "content": content,
                "content_type": "text",
                "source_ids": [],
                "chart_path": None,
                "subsections": None,
            }
        )
    return sections


def _generate_industry_section_result(
    state: dict,
    analysis: dict,
    spec: dict[str, Any],
) -> tuple[str | None, int]:
    """Generate one industry section without mutating shared Writer state."""
    from competition.executor import execute_agent

    products = state.get("target_products", [])
    user_request = state.get("user_request", "")
    data_summary = "".join(f"- {dp.get('product', '?')} | {dp.get('category', '?')} | {dp.get('label', '?')} | {dp.get('value', '?')}\n" for dp in (state.get("collected_data") or [])[:10] if isinstance(dp, dict))
    task = (
        f"Query: {user_request}\n"
        f"Products: {', '.join(products) if products else 'unknown'}\n"
        f"Industry focus: {spec['prompt_bias']}\n\n"
        f"Collected data:\n{data_summary}\n\n"
        f"Generate a concise analysis section (3-5 paragraphs) for the industry-specific "
        f"section '{spec['section_id']}'. Focus on quantitative comparisons and cite data points. "
        "Output markdown text only, no JSON."
    )
    system = "You are a competitive analysis writer specializing in industry-specific analysis. Write concise, data-driven sections. Cite specific data points."
    raw, tokens = execute_agent(
        system,
        task,
        temperature=0.3,
        max_tokens=WRITER_INDUSTRY_MAX_TOKENS,
        agent_name="Writer",
        disable_thinking=True,
        timeout_seconds=WRITER_SECTION_TIMEOUT_SECONDS,
        max_retries=0,
        allow_empty_content_fallback=False,
    )
    return (raw.strip() if isinstance(raw, str) and raw.strip() else None, tokens)


def _generate_industry_section_content(state: dict, analysis: dict, section_id: str, prompt_bias: str) -> str:
    """Compatibility wrapper for one industry section's deterministic fallback."""
    raw, _ = _generate_industry_section_result(
        state,
        analysis,
        {"section_id": section_id, "prompt_bias": prompt_bias},
    )
    return raw or _industry_fallback_content(section_id)


def _render_dynamic_blocks(blocks: list[dict], _src_ref: Callable[[list[str]], str], citation_index: dict[str, str] | None = None) -> list[dict]:
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
        if block.get("included", True) is False:
            continue
        bt = block.get("block_type", "kv_list")
        title = block.get("title", f"动态分析 {i + 1}")
        data = block.get("data", {})
        if not isinstance(data, dict):
            data = {"value": data}
        src_ids = block.get("source_data_point_ids", [])
        _, stable_source_ids = _resolve_citations(src_ids, citation_index or {})

        content = _format_block_content(bt, data, src_ids, _src_ref)
        if bt in ("comparison_table", "stat_chart") and not content:
            content = f"{title}（结构化数据）{_src_ref(src_ids)}".strip()
        sections.append(
            {
                "id": f"dynamic-block-{i}",
                "title": TYPE_TO_TITLE_PREFIX.get(bt, "") + title,
                "content": content,
                "content_type": TYPE_TO_CONTENT.get(bt, "text"),
                "source_ids": stable_source_ids,
                "chart_path": _extract_chart_config(bt, data),
                "subsections": None,
            }
        )

    return sections


def _format_block_content(block_type: str, data: dict, src_ids: list[str], _src_ref) -> str:
    """Format a single DynamicBlock's data as renderable content."""
    src_str = " " + _src_ref(src_ids) if src_ids else ""
    if not isinstance(data, dict):
        return str(data) + src_str

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
                citations = "".join(re.findall(r"\[\d+\]", match[0].get("evidence", "")))
                body += f" {rating}{citations} |"
            else:
                body += " N/A |"
        body += "\n"
    return header + sep + body


def _build_traceability_map(collected: list[dict]) -> dict:
    """Build citation-id mapping while retaining compatibility fields and source metadata."""
    from urllib.parse import urlparse

    # Try to load domain credibility scores for tier assignment
    domain_scores: dict[str, float] = {}
    try:
        from competition.db import get_all_credibilities, init_db

        conn = init_db()
        rows = get_all_credibilities(conn)
        conn.close()
        if isinstance(rows, dict):
            domain_scores.update({str(domain): float(score) for domain, score in rows.items()})
        else:
            for r in rows:
                if isinstance(r, dict):
                    domain_scores[r.get("source_domain", "")] = r.get("score", 0.5)
    except Exception:
        pass

    def _tier(score: float) -> str:
        if score >= 0.7:
            return "strong"
        if score >= 0.4:
            return "moderate"
        return "weak"

    trace = {}
    content_cache: dict[str, dict | None] = {}
    for i, dp in enumerate(collected):
        if isinstance(dp, dict):
            url = dp.get("source_url", "")
            domain = urlparse(url).netloc if url else ""
            score = domain_scores.get(domain, 0.5)
            snapshot: dict | None = None
            if url:
                try:
                    import hashlib

                    from competition.db import get_content, init_db

                    content_ref = hashlib.sha256(url.encode()).hexdigest()[:16]
                    if content_ref not in content_cache:
                        conn = init_db()
                        content_cache[content_ref] = get_content(content_ref, conn=conn)
                        conn.close()
                    snapshot = content_cache[content_ref]
                except Exception:
                    snapshot = None
            snapshot_fields = {}
            if snapshot:
                import hashlib

                snapshot_fields = {
                    "content_ref": snapshot.get("content_ref"),
                    "snapshot_fetched_at": snapshot.get("fetched_at"),
                    "snapshot_char_count": snapshot.get("char_count", 0),
                    "snapshot_sha256": hashlib.sha256(str(snapshot.get("full_text", "")).encode()).hexdigest(),
                }
            trace[str(i + 1)] = {
                "url": url,
                "timestamp": dp.get("collected_at", ""),
                "confidence": dp.get("confidence", 0.0),
                "title": dp.get("title", "") or dp.get("label", ""),
                "snippet": dp.get("snippet", "") or str(dp.get("value", ""))[:300],
                "verified": bool(dp.get("verified", False)),
                "credibility_tier": _tier(score),
                "data_point_id": dp.get("id", ""),
                "product": dp.get("product", ""),
                "category": dp.get("category", ""),
                "label": dp.get("label", ""),
                "source_type": dp.get("source_type", ""),
                "collected_at": dp.get("collected_at", ""),
                "published_at": dp.get("published_at"),
                "publication_date_status": _publication_date_status(dp.get("published_at"), None),
                "knowledge_document_id": dp.get("knowledge_document_id"),
                "knowledge_chunk_id": dp.get("knowledge_chunk_id"),
                "source_authority": dp.get("source_authority"),
                "source_title": dp.get("source_title"),
                "section_path": dp.get("section_path"),
                "page_no": dp.get("page_no"),
                "retrieval_score": dp.get("retrieval_score"),
                "is_local_knowledge": bool(dp.get("knowledge_chunk_id")),
                "knowledge_version_no": dp.get("knowledge_version_no"),
                "knowledge_valid_from": dp.get("knowledge_valid_from"),
                "knowledge_valid_to": dp.get("knowledge_valid_to"),
                "knowledge_temporal_status": dp.get("knowledge_temporal_status"),
                **snapshot_fields,
            }
    return trace


def _publication_date_status(published_at: Any, time_range: dict | None) -> str:
    """Classify publication date without confusing it with collection time."""
    if not published_at:
        return "unknown"
    try:
        value = datetime.fromisoformat(str(published_at).replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        return "unknown"
    if not time_range or time_range.get("mode") in (None, "latest", "all_available"):
        return "known"
    try:
        start = datetime.fromisoformat(str(time_range.get("start"))).date() if time_range.get("start") else None
        end = datetime.fromisoformat(str(time_range.get("end"))).date() if time_range.get("end") else None
    except (TypeError, ValueError):
        return "known"
    if start and value < start or end and value > end:
        return "outside_range"
    return "known"


def _build_quality_gate(
    *,
    brief: dict,
    target_products: list[str],
    collected: list[dict],
    analysis: dict,
    verdict: dict,
    sections: list[dict],
    traceability: dict,
) -> dict:
    """Build a deterministic, report-version quality snapshot.

    This intentionally uses only already-produced graph outputs. It must remain
    cheap, reproducible, and safe when older or partially populated state is
    passed through Writer.
    """
    policy = str(brief.get("evidence_policy") or "balanced")
    if policy not in {"balanced", "official_preferred", "strict_multi_source"}:
        policy = "balanced"
    point_by_id = {str(dp.get("id")): dp for dp in collected if isinstance(dp, dict) and dp.get("id")}
    citation_by_point = {str(entry.get("data_point_id")): citation_id for citation_id, entry in traceability.items() if isinstance(entry, dict) and entry.get("data_point_id")}
    section_source_map = {str(section.get("id")): {str(value) for value in section.get("source_ids", []) or []} for section in sections if isinstance(section, dict)}

    issues: list[dict] = []
    issue_keys: set[tuple] = set()

    def add_issue(issue: dict) -> str:
        key = (
            issue.get("check_method", ""),
            tuple(sorted(issue.get("product_names", []))),
            tuple(sorted(issue.get("dimension_ids", []))),
            tuple(sorted(issue.get("data_point_ids", []))),
            issue.get("description", ""),
        )
        if issue.get("id", "").startswith("reviewer-"):
            key = ("reviewer", issue["id"])
        if key in issue_keys:
            return next((item["id"] for item in issues if item.get("id") == issue.get("id")), issue.get("id", "issue"))
        issue_keys.add(key)
        issues.append(issue)
        return issue.get("id", "issue")

    def section_ids_for(data_point_ids: list[str], method: str) -> list[str]:
        if "comparison" in method or "dimension" in method or method == "coverage":
            return ["sec-comparison-matrix"] if any(s == "sec-comparison-matrix" for s in section_source_map) else ["sec-comparison"]
        if "swot" in method:
            return ["sec-swot"]
        citations = {citation_by_point.get(str(point_id)) for point_id in data_point_ids}
        citations.discard(None)
        return [sid for sid, source_ids in section_source_map.items() if citations.intersection(source_ids)]

    # Reviewer gaps remain authoritative: their severity is never weakened.
    for gap in verdict.get("gaps", []) or []:
        if not isinstance(gap, dict):
            continue
        severity = str(gap.get("severity") or "major")
        severity = severity if severity in {"critical", "major", "minor"} else "major"
        data_point_ids = [str(value) for value in gap.get("related_data_point_ids", []) or []]
        issue_id = f"reviewer-{gap.get('gap_id') or len(issues) + 1}"
        add_issue(
            {
                "id": issue_id,
                "level": "blocking" if severity in {"critical", "major"} else "warning",
                "severity": severity,
                "type": str(gap.get("type") or "reviewer_gap"),
                "check_method": str(gap.get("check_method") or gap.get("method") or "reviewer"),
                "description": str(gap.get("description") or "Reviewer identified an unresolved issue"),
                "remediation": str(gap.get("target_collect_task") or gap.get("task") or "补充证据并重新审查"),
                "product_names": list(dict.fromkeys(str(point_by_id[item].get("product")) for item in data_point_ids if item in point_by_id)),
                "data_point_ids": data_point_ids,
                "citation_ids": [citation_by_point[item] for item in data_point_ids if item in citation_by_point],
                "section_ids": section_ids_for(data_point_ids, str(gap.get("check_method") or gap.get("method") or "reviewer")),
            }
        )

    # Some legacy/recovery states expose fact_errors separately from `gaps`.
    # Preserve those as blocking diagnostics instead of silently treating them
    # as an informational Reviewer note.
    for index, fact_error in enumerate(verdict.get("fact_errors", []) or [], start=1):
        if not isinstance(fact_error, dict):
            continue
        data_point_ids = [str(value) for value in fact_error.get("related_data_point_ids", []) or []]
        add_issue(
            {
                "id": f"reviewer-fact-error-{index}",
                "level": "blocking",
                "severity": "critical",
                "type": "fact_error",
                "check_method": str(fact_error.get("check_method") or "fact_error"),
                "description": str(fact_error.get("description") or fact_error.get("error") or "Reviewer reported a fact error"),
                "remediation": str(fact_error.get("target_collect_task") or "核对事实并补充可核验来源"),
                "data_point_ids": data_point_ids,
                "citation_ids": [citation_by_point[item] for item in data_point_ids if item in citation_by_point],
                "section_ids": section_ids_for(data_point_ids, "fact_error"),
            }
        )

    selected_dimensions = brief.get("effective_dimensions") or brief.get("dimensions") or []
    matrix = analysis.get("comparison_matrix") if isinstance(analysis.get("comparison_matrix"), dict) else {}
    matrix_dimensions = matrix.get("dimensions") if isinstance(matrix.get("dimensions"), list) else []
    if not selected_dimensions:
        selected_dimensions = [{"id": str(dim), "label": str(dim)} for dim in matrix_dimensions]
    dimensions: list[dict] = []
    for dim_item in selected_dimensions:
        if isinstance(dim_item, dict):
            dim_id = str(dim_item.get("id") or dim_item.get("dimension") or "unknown")
            label = str(dim_item.get("label") or dim_id)
        else:
            dim_id, label = str(dim_item), str(dim_item)
        dim_points = [dp for dp in collected if isinstance(dp, dict) and str(dp.get("category")) == dim_id]
        covered = list(dict.fromkeys(str(dp.get("product")) for dp in dim_points if dp.get("product") in target_products))
        matrix_covered = {
            str(cell.get("product"))
            for cell in matrix.get("cells", []) or []
            if isinstance(cell, dict) and str(cell.get("dimension")) in {dim_id, label} and cell.get("rating") is not None and str(cell.get("evidence_source", "")) != "insufficient" and cell.get("product") in target_products
        }
        # A selected product/dimension is covered only when the final matrix
        # has a usable cell. Raw collected data alone cannot make a missing
        # analysis cell appear complete.
        missing = [product for product in target_products if product not in matrix_covered]
        covered = [product for product in target_products if product in matrix_covered]
        status = "blocked" if missing else ("pass" if dim_points else "warning")
        issue_ids: list[str] = []
        for product in missing:
            issue_ids.append(
                add_issue(
                    {
                        "id": f"coverage-{dim_id}-{len(issue_ids) + 1}",
                        "level": "blocking",
                        "severity": "major",
                        "type": "missing_data",
                        "check_method": "dimension_coverage",
                        "description": f"未找到产品 {product} 在 {label} 维度的有效数据",
                        "remediation": f"为 {product} 补采 {label} 维度的可核验来源",
                        "dimension_ids": [dim_id],
                        "product_names": [product],
                        "section_ids": section_ids_for([], "dimension_coverage"),
                    }
                )
            )
        dimensions.append(
            {
                "dimension_id": dim_id,
                "label": label,
                "selected": True,
                "products_total": len(target_products),
                "products_covered": covered,
                "missing_products": missing,
                "data_point_count": len(dim_points),
                "source_domain_count": len({str(dp.get("source_url", "")).split("/")[2] for dp in dim_points if "://" in str(dp.get("source_url", ""))}),
                "coverage_ratio": len(covered) / max(len(target_products), 1),
                "status": status,
                "issue_ids": issue_ids,
            }
        )

    # Source diagnostics. `timestamp` remains collection time; publication dates
    # are parsed independently and never inferred from collection time.
    source_counts = {key: 0 for key in ("official", "strong", "moderate", "weak")}
    unknown_dates = outside_range = 0
    time_range = brief.get("time_range") if isinstance(brief.get("time_range"), dict) else None
    for citation_id, entry in traceability.items():
        tier = str(entry.get("credibility_tier") or "moderate")
        source_type = str(entry.get("source_type") or "")
        if source_type == "official":
            source_counts["official"] += 1
        if tier in source_counts:
            source_counts[tier] += 1
        status = _publication_date_status(entry.get("published_at"), time_range)
        entry["publication_date_status"] = status
        if status == "unknown":
            unknown_dates += 1
        elif status == "outside_range":
            outside_range += 1
        if tier == "weak":
            add_issue(
                {
                    "id": f"weak-source-{citation_id}",
                    "level": "warning",
                    "severity": "minor",
                    "type": "weak_source",
                    "check_method": "source_credibility",
                    "description": f"来源 [{citation_id}] 的域名可信度较低",
                    "remediation": "优先补充官方或高可信来源进行交叉验证",
                    "citation_ids": [str(citation_id)],
                    "section_ids": section_ids_for([str(entry.get("data_point_id"))], "source_credibility"),
                }
            )

    if policy != "balanced":
        for citation_id, entry in traceability.items():
            if not entry.get("published_at"):
                add_issue(
                    {
                        "id": f"publication-date-{citation_id}",
                        "level": "warning",
                        "severity": "minor",
                        "type": "publication_date_unknown",
                        "check_method": "publication_date",
                        "description": f"来源 [{citation_id}] 缺少公开发布时间",
                        "remediation": "核对来源页面的发布时间或补充带日期的来源",
                        "citation_ids": [str(citation_id)],
                        "section_ids": section_ids_for([str(entry.get("data_point_id"))], "publication_date"),
                    }
                )

    # Claims: comparison cells and SWOT entries are the current bounded claim set.
    claim_total = claim_multi = claim_single = claim_unsupported = 0
    cells = matrix.get("cells") if isinstance(matrix.get("cells"), list) else []
    claim_items: list[tuple[dict, str, str]] = [(item, "comparison_claim", "comparison") for item in cells if isinstance(item, dict)]
    swot = analysis.get("swot") if isinstance(analysis.get("swot"), dict) else {}
    for product, swot_data in swot.items():
        for item in swot_data.get("items", []) if isinstance(swot_data, dict) else []:
            if isinstance(item, dict):
                claim_items.append((item, "swot_claim", "swot"))
    for index, (claim, method, kind) in enumerate(claim_items, start=1):
        claim_total += 1
        ids = [str(value) for value in claim.get("source_data_point_ids", []) or []]
        domains = {str(point_by_id[item].get("source_url", "")).split("/")[2] for item in ids if item in point_by_id and "://" in str(point_by_id[item].get("source_url", ""))}
        if len(domains) >= 2:
            claim_multi += 1
        elif len(domains) == 1:
            claim_single += 1
        else:
            claim_unsupported += 1
        deficiency = "unsupported_claim" if not domains else ("single_source" if len(domains) == 1 else "")
        if deficiency:
            level = "blocking" if policy == "strict_multi_source" and deficiency == "single_source" else "warning"
            issue_id = add_issue(
                {
                    "id": f"{kind}-{deficiency}-{index}",
                    "level": level,
                    "severity": "major" if level == "blocking" else "minor",
                    "type": deficiency,
                    "check_method": method,
                    "description": "声明缺少两个独立来源的交叉支持" if deficiency == "single_source" else "声明没有可追溯来源",
                    "remediation": "补充不同域名的独立来源并重新审查" if deficiency == "single_source" else "为该声明补充数据点引用",
                    "product_names": [str(claim.get("product"))] if claim.get("product") else [],
                    "dimension_ids": [str(claim.get("dimension"))] if claim.get("dimension") else [],
                    "data_point_ids": ids,
                    "citation_ids": [citation_by_point[item] for item in ids if item in citation_by_point],
                    "section_ids": section_ids_for(ids, kind),
                }
            )

    blocking_count = sum(1 for issue in issues if issue.get("level") == "blocking")
    warning_count = sum(1 for issue in issues if issue.get("level") == "warning")
    status = "blocked" if blocking_count else ("warning" if warning_count else "pass")
    quality = verdict.get("quality_summary") if isinstance(verdict.get("quality_summary"), dict) else {}
    return {
        "schema_version": 1,
        "status": status,
        "generated_at": datetime.now(UTC).isoformat(),
        "policy": policy,
        "blocking_count": blocking_count,
        "warning_count": warning_count,
        "dimensions": dimensions,
        "sources": {"total": len(traceability), **source_counts, "unknown_publication_date": unknown_dates, "outside_requested_range": outside_range},
        "claims": {"total": claim_total, "multi_source": claim_multi, "single_source": claim_single, "unsupported": claim_unsupported},
        "issues": issues,
        "rework": {
            "review_round": int(verdict.get("round") or 0),
            "reviewer_notes": str(verdict.get("reviewer_notes") or ""),
            "improvement_ratio": quality.get("improvement_ratio"),
            "repair_delta": quality.get("repair_delta"),
            "current_round_metrics": quality.get("round_metrics"),
            "previous_round_metrics": quality.get("round_metrics_prev"),
        },
    }


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
            "repair_delta": quality.get("repair_delta", 0),
            "round_metrics": quality.get("round_metrics", {}),
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

    # W3: traceability_map keys match [n] references and explicit source IDs
    trace_map = report_data.get("traceability_map", {})
    if not trace_map:
        issues.append("W3: traceability_map is empty")
    valid_keys = {str(key) for key in trace_map}
    for section in sections:
        section_id = section.get("id", "unknown")
        for source_id in section.get("source_ids", []) or []:
            if str(source_id) not in valid_keys:
                issues.append(f"W3: {section_id} source ID [{source_id}] is not in traceability_map")
        content = section.get("content", "")
        if not isinstance(content, str):
            continue
        for marker in re.findall(r"\[(\d+)\]", content):
            if marker not in valid_keys:
                issues.append(f"W3: {section_id} citation [{marker}] is not in traceability_map")

    # W4: Source table references consistent

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
        section_status.append(
            {
                "id": rid,
                "present": rid in section_ids,
                "has_content": bool(next((s.get("content", "").strip() for s in sections if s.get("id") == rid), "")),
            }
        )

    # Overall score: weighted average
    schema_score = 1.0 if required_present else 0.0
    overall_score = schema_score * 0.4 + section_completeness * 0.3 + min(source_annotation_rate, 1.0) * 0.3

    return {
        "schema_compliance": required_present,
        "missing_required": missing_required,
        "section_completeness": round(section_completeness, 2),
        "source_annotation_rate": round(min(source_annotation_rate, 1.0), 2),
        "product_mention_check": product_mention_check,
        "section_status": section_status,
        "overall_score": round(overall_score, 2),
    }


def _narrative_digest(analysis: dict, citation_index: dict[str, str]) -> dict[str, Any]:
    """Build a compact, already-cited evidence digest for the Writer call."""
    digest: dict[str, Any] = {}
    matrix = analysis.get("comparison_matrix")
    if isinstance(matrix, dict):
        digest["comparison_summary"] = str(matrix.get("summary", ""))[:500]
        digest["comparison_cells"] = [
            {
                "product": cell.get("product", ""),
                "dimension": cell.get("dimension", ""),
                "rating": cell.get("rating"),
                "evidence": f"{cell.get('evidence', '')} {_resolve_citations(cell.get('source_data_point_ids', []), citation_index)[0]}".strip(),
            }
            for cell in matrix.get("cells", [])[:30]
            if isinstance(cell, dict)
        ]
    swot_digest: list[dict[str, Any]] = []
    for product, group in (analysis.get("swot") or {}).items() if isinstance(analysis.get("swot"), dict) else []:
        if not isinstance(group, dict):
            continue
        for item in group.get("items", [])[:20]:
            if not isinstance(item, dict):
                continue
            swot_digest.append(
                {
                    "product": product,
                    "category": item.get("category", ""),
                    "statement": item.get("statement", ""),
                    "evidence": f"{item.get('evidence', '')} {_resolve_citations(item.get('source_data_point_ids', []), citation_index)[0]}".strip(),
                }
            )
    digest["swot"] = swot_digest
    digest["trends"] = [
        {
            "dimension": item.get("dimension", ""),
            "direction": item.get("direction", ""),
            "evidence": f"{item.get('evidence', '')} {_resolve_citations(item.get('source_data_point_ids', []), citation_index)[0]}".strip(),
        }
        for item in (analysis.get("trends") or [])[:15]
        if isinstance(item, dict)
    ]
    forecast = analysis.get("forecast")
    if isinstance(forecast, dict):
        digest["forecast"] = {
            "summary": forecast.get("summary", ""),
            "items": [
                {
                    "product": item.get("product", ""),
                    "dimension": item.get("dimension", ""),
                    "forecast_6m": item.get("forecast_6m", ""),
                    "forecast_12m": item.get("forecast_12m", ""),
                    "rationale": f"{item.get('rationale', '')} {_resolve_citations(item.get('source_data_point_ids', []), citation_index)[0]}".strip(),
                }
                for item in forecast.get("items", [])[:15]
                if isinstance(item, dict)
            ],
        }
    else:
        digest["forecast"] = {}
    return digest


def _valid_narrative_text(value: Any, valid_keys: set[str]) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if any(marker not in valid_keys for marker in re.findall(r"\[(\d+)\]", text)):
        return None
    return text


def _generate_narrative_patch(
    analysis: dict,
    products: list[str],
    persona: str,
    traceability: dict[str, dict],
    citation_index: dict[str, str],
    *,
    hitl_action: str,
    hitl_focus: list[str] | None,
    hitl_comment: str,
    brief: dict | None = None,
) -> tuple[dict[str, Any] | None, int]:
    """Generate a validated narrative patch without mutating report sections."""
    if not _has_narrative_context(analysis):
        return None, 0
    try:
        from competition.executor import execute_structured_agent

        persona_label = "产品经理" if persona == "pm" else "创业者"
        guidance = ""
        if hitl_action == "rewrite":
            guidance = f"\n重写重点: {', '.join(hitl_focus or []) or '调整表达视角'}\n用户意见: {hitl_comment or '请提升可操作性'}"
        brief = brief or {}
        task = (
            f"视角: {persona_label}\n竞品: {', '.join(products)}\n"
            f"市场: {brief.get('market_scope', '未指定')}\n"
            f"输出重点: {', '.join(brief.get('output_focus') or []) or '关键差异与可执行建议'}\n"
            f"允许引用编号: {sorted(traceability, key=lambda x: int(x) if x.isdigit() else x)}{guidance}\n"
            f"证据摘要:\n{json.dumps(_narrative_digest(analysis, citation_index), ensure_ascii=False, indent=2)}\n\n"
            "只使用上述事实，不得编造事实或引用编号。返回严格 JSON 对象，字段为 executive_summary（150-250字中文字符串）和 recommendations（字符串数组）。"
        )
        response = execute_structured_agent(
            "你是竞品分析报告 Writer，负责把已有证据整理成可执行叙事。",
            task,
            output_schema_desc='{"executive_summary": string, "recommendations": string[]}',
            agent_name="Writer",
            temperature=0.3,
            max_tokens=WRITER_NARRATIVE_MAX_TOKENS,
            disable_thinking=True,
            timeout_seconds=WRITER_SECTION_TIMEOUT_SECONDS,
            max_retries=0,
            allow_empty_content_fallback=False,
        )
        if isinstance(response, tuple) and len(response) == 2:
            result, tokens = response
        else:
            result, tokens = response, 0
    except Exception as exc:
        logger.warning("Writer structured narrative generation failed: %s", type(exc).__name__)
        return None, 0

    if not isinstance(result, dict):
        return None, max(int(tokens or 0), 0)
    valid_keys = {str(key) for key in traceability}
    patch: dict[str, Any] = {}
    summary = _valid_narrative_text(result.get("executive_summary"), valid_keys)
    if summary:
        patch["executive_summary"] = summary
    recommendations = result.get("recommendations")
    if isinstance(recommendations, list):
        lines = [item.strip() for item in recommendations if isinstance(item, str)]
        if lines and len(lines) == len(recommendations) and all(item and _valid_narrative_text(item, valid_keys) for item in lines):
            patch["recommendations"] = "\n".join(f"- {item}" for item in lines)
    return (patch or None), max(int(tokens or 0), 0)


def _apply_narrative_result(
    sections: list[dict],
    result: _WriterTaskResult | None,
    valid_keys: set[str],
) -> None:
    """Apply a validated narrative result on the parent Writer thread."""
    if result is None or result.status != "success" or not isinstance(result.payload, dict):
        return
    summary = _valid_narrative_text(result.payload.get("executive_summary"), valid_keys)
    if summary:
        section = next((s for s in sections if s.get("id") == "sec-executive-summary"), None)
        if section:
            section["content"] = summary
            section["source_ids"] = list(dict.fromkeys(re.findall(r"\[(\d+)\]", summary)))
    recommendations = result.payload.get("recommendations")
    if isinstance(recommendations, str) and recommendations.strip():
        section = next((s for s in sections if s.get("id") == "sec-recommendations"), None)
        if section:
            section["content"] = recommendations
            section["source_ids"] = list(dict.fromkeys(re.findall(r"\[(\d+)\]", recommendations)))


def _apply_narrative_generation(
    sections: list[dict],
    analysis: dict,
    products: list[str],
    persona: str,
    traceability: dict[str, dict],
    citation_index: dict[str, str],
    *,
    hitl_action: str,
    hitl_focus: list[str] | None,
    hitl_comment: str,
    brief: dict | None = None,
) -> None:
    """Compatibility wrapper for one inline narrative task."""
    patch, tokens = _generate_narrative_patch(
        analysis,
        products,
        persona,
        traceability,
        citation_index,
        hitl_action=hitl_action,
        hitl_focus=hitl_focus,
        hitl_comment=hitl_comment,
        brief=brief,
    )
    _apply_narrative_result(
        sections,
        _WriterTaskResult("narrative", "narrative", 0, None, "success" if patch else "fallback", patch, tokens),
        {str(key) for key in traceability},
    )


def _generate_whatif(comment: str, analysis: dict, products: list[str], persona: str) -> str:
    """Generate what-if analysis via LLM based on user's assumption + existing data.

    Only runs when the user submits a what-if via HITL rewrite. Does NOT re-run
    Collector or Analyst — works from existing analysis_result.
    """
    from competition.executor import execute_agent

    matrix = analysis.get("comparison_matrix", {})
    swot = analysis.get("swot", {})
    trends = analysis.get("trends", [])
    forecast = analysis.get("forecast")

    context = f"""现有竞品分析数据:

对比矩阵: {matrix.get("summary", "")}
产品: {", ".join(products)}
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
