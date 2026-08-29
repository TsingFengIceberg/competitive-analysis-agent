"""Offline retrieval evaluation metrics and dataset runner."""

from __future__ import annotations

import math
import statistics
import time
from dataclasses import dataclass
from typing import Any

from competition.knowledge_types import RetrievalFilters


@dataclass(frozen=True)
class EvaluationThresholds:
    recall_at_k: float = 0.8
    mrr: float = 0.7
    ndcg_at_k: float = 0.75
    abstention_accuracy: float = 1.0
    traceability_rate: float = 1.0
    max_p95_latency_ms: float | None = None
    claim_status_accuracy: float = 0.8
    contradiction_recall: float = 0.8
    citation_precision: float = 0.8
    numeric_consistency_accuracy: float = 0.8
    groundedness: float = 0.4
    query_route_accuracy: float = 0.9
    decomposition_coverage: float = 0.8
    governance_accuracy: float = 0.9
    quarantine_recall: float = 1.0
    memory_recall_at_k: float = 0.8
    memory_isolation_rate: float = 1.0
    current_thread_exclusion_rate: float = 1.0
    graph_route_accuracy: float = 0.9
    relation_recall_at_k: float = 0.8
    relation_traceability_rate: float = 1.0
    temporal_relation_accuracy: float = 1.0
    unsupported_relation_rate: float = 0.0


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def compute_retrieval_metrics(cases: list[dict[str, Any]], *, k: int = 5) -> dict[str, Any]:
    """Compute deterministic ranking, abstention, traceability, and latency metrics."""
    answerable = [case for case in cases if case.get("relevant")]
    unanswerable = [case for case in cases if not case.get("relevant")]
    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    ndcgs: list[float] = []
    traceable = 0
    returned = 0
    latencies: list[float] = []
    for case in cases:
        relevant = set(case.get("relevant") or [])
        ranked = list(case.get("ranked") or [])[:k]
        latencies.append(float(case.get("latency_ms") or 0.0))
        returned += len(ranked)
        traceable += sum(bool(item.get("document_id") and item.get("chunk_id")) for item in ranked)
        if not relevant:
            continue
        relevant_ranks = [index + 1 for index, item in enumerate(ranked) if item.get("label") in relevant]
        recalls.append(len({item.get("label") for item in ranked}.intersection(relevant)) / len(relevant))
        reciprocal_ranks.append(1.0 / min(relevant_ranks) if relevant_ranks else 0.0)
        dcg = sum(1.0 / math.log2(rank + 1) for rank in relevant_ranks)
        ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(len(relevant), k) + 1))
        ndcgs.append(dcg / ideal if ideal else 0.0)
    abstained = sum(not case.get("ranked") for case in unanswerable)
    return {
        "case_count": len(cases),
        "answerable_count": len(answerable),
        "unanswerable_count": len(unanswerable),
        f"recall_at_{k}": round(statistics.fmean(recalls), 6) if recalls else 0.0,
        "mrr": round(statistics.fmean(reciprocal_ranks), 6) if reciprocal_ranks else 0.0,
        f"ndcg_at_{k}": round(statistics.fmean(ndcgs), 6) if ndcgs else 0.0,
        "abstention_accuracy": round(abstained / len(unanswerable), 6) if unanswerable else 1.0,
        "traceability_rate": round(traceable / returned, 6) if returned else 1.0,
        "latency_ms": {
            "mean": round(statistics.fmean(latencies), 3) if latencies else 0.0,
            "p50": round(_percentile(latencies, 0.50), 3),
            "p95": round(_percentile(latencies, 0.95), 3),
            "max": round(max(latencies), 3) if latencies else 0.0,
        },
    }


def compute_verification_metrics(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Score claim labels, contradictions, citations, numbers, and grounding."""
    if not cases:
        return {
            "case_count": 0,
            "claim_status_accuracy": 1.0,
            "contradiction_recall": 1.0,
            "citation_precision": 1.0,
            "numeric_consistency_accuracy": 1.0,
            "groundedness": 0.0,
        }
    status_correct = sum(case.get("actual_status") == case.get("expected_status") for case in cases)
    contradictions = [case for case in cases if case.get("expected_status") == "contradicted"]
    contradiction_hits = sum(case.get("actual_status") == "contradicted" for case in contradictions)
    predicted_supports = 0
    correct_supports = 0
    numeric_cases = [case for case in cases if case.get("expected_numeric_consistency") is not None]
    numeric_correct = sum(case.get("actual_numeric_consistency") == case.get("expected_numeric_consistency") for case in numeric_cases)
    for case in cases:
        expected = set(case.get("expected_supporting") or [])
        actual = list(case.get("actual_supporting") or [])
        predicted_supports += len(actual)
        correct_supports += sum(label in expected for label in actual)
    supported = sum(case.get("actual_status") == "supported" for case in cases)
    return {
        "case_count": len(cases),
        "claim_status_accuracy": round(status_correct / len(cases), 6),
        "contradiction_recall": round(contradiction_hits / len(contradictions), 6) if contradictions else 1.0,
        "citation_precision": round(correct_supports / predicted_supports, 6) if predicted_supports else 1.0,
        "numeric_consistency_accuracy": round(numeric_correct / len(numeric_cases), 6) if numeric_cases else 1.0,
        "groundedness": round(supported / len(cases), 6),
    }


def compute_planning_metrics(cases: list[dict[str, Any]]) -> dict[str, Any]:
    planned = [case for case in cases if case.get("expected_route")]
    if not planned:
        return {
            "case_count": 0,
            "query_route_accuracy": 1.0,
            "decomposition_coverage": 1.0,
            "average_steps": 1.0,
        }
    correct_routes = sum(case.get("actual_route") == case.get("expected_route") for case in planned)
    decomposition_scores: list[float] = []
    step_counts: list[int] = []
    for case in planned:
        expected = set(case.get("required_step_purposes") or [])
        actual = set(case.get("actual_step_purposes") or [])
        if expected:
            decomposition_scores.append(len(expected & actual) / len(expected))
        step_counts.append(int(case.get("actual_step_count") or 0))
    return {
        "case_count": len(planned),
        "query_route_accuracy": round(correct_routes / len(planned), 6),
        "decomposition_coverage": round(statistics.fmean(decomposition_scores), 6) if decomposition_scores else 1.0,
        "average_steps": round(statistics.fmean(step_counts), 3) if step_counts else 0.0,
    }


def evaluate_governance_cases(definitions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run deterministic admission examples through production governance policy."""
    from competition.knowledge_governance import assess_intelligence_item, assess_report

    cases: list[dict[str, Any]] = []
    for item in definitions:
        kind = str(item.get("kind") or "intelligence")
        if kind == "report":
            result = assess_report(dict(item.get("payload") or {}))
        else:
            result = assess_intelligence_item(
                dict(item.get("payload") or {}),
                source_credibility=float(item.get("source_credibility", 0.5)),
            )
        cases.append(
            {
                "id": item.get("id"),
                "kind": kind,
                "expected_status": item.get("expected_status"),
                "actual_status": result.get("approval_status"),
                "expected_quarantined": item.get("expected_status") == "pending",
                "actual_quarantined": bool(result.get("quarantined")),
                "result": result,
            }
        )
    return cases


def compute_governance_metrics(cases: list[dict[str, Any]]) -> dict[str, Any]:
    if not cases:
        return {"case_count": 0, "governance_accuracy": 1.0, "quarantine_recall": 1.0}
    correct = sum(case.get("actual_status") == case.get("expected_status") for case in cases)
    expected_quarantine = [case for case in cases if case.get("expected_quarantined")]
    quarantine_hits = sum(case.get("actual_quarantined") for case in expected_quarantine)
    return {
        "case_count": len(cases),
        "governance_accuracy": round(correct / len(cases), 6),
        "quarantine_recall": round(quarantine_hits / len(expected_quarantine), 6) if expected_quarantine else 1.0,
    }


def evaluate_memory_cases(
    service: Any,
    definitions: list[dict[str, Any]],
    *,
    user_id: str,
    document_labels: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Measure report-memory recall while proving reports never enter citable evidence."""
    labels = document_labels or {}
    cases: list[dict[str, Any]] = []
    for item in definitions:
        state = {
            "user_id": user_id,
            "user_request": item["query"],
            "target_products": list(item.get("products") or []),
            "thread_id": item.get("current_thread_id") or "",
            "analysis_brief": {
                "objective": item["query"],
                "target_products": list(item.get("products") or []),
                "effective_dimensions": [{"id": value} for value in item.get("dimensions") or ["features"]],
            },
        }
        memory = service.retrieve_analysis_memory(state, limit=int(item.get("k") or 5))
        evidence = service.retrieve_for_analysis(state, limit=12)
        ranked = [labels.get(str(entry.get("knowledge_document_id") or ""), str(entry.get("knowledge_document_id") or "")) for entry in memory]
        forbidden = set(item.get("forbidden") or [])
        returned_threads = {str(entry.get("report_thread_id") or "") for entry in memory}
        cases.append(
            {
                "id": item.get("id"),
                "relevant": list(item.get("relevant") or []),
                "ranked": ranked,
                "memory_count": len(memory),
                "citation_leak_count": sum(bool(entry.get("citation_eligible")) for entry in memory),
                "evidence_report_leak_count": sum(entry.get("source_authority") == "report" for entry in evidence),
                "forbidden_returned": sorted(forbidden.intersection(returned_threads)),
            }
        )
    return cases


def compute_memory_metrics(cases: list[dict[str, Any]], *, k: int = 5) -> dict[str, Any]:
    if not cases:
        return {
            "case_count": 0,
            f"memory_recall_at_{k}": 1.0,
            "memory_isolation_rate": 1.0,
            "current_thread_exclusion_rate": 1.0,
        }
    recalls: list[float] = []
    isolated = 0
    excluded = 0
    for case in cases:
        relevant = set(case.get("relevant") or [])
        ranked = set((case.get("ranked") or [])[:k])
        recalls.append(len(relevant.intersection(ranked)) / len(relevant) if relevant else 1.0)
        isolated += int(not case.get("citation_leak_count") and not case.get("evidence_report_leak_count"))
        excluded += int(not case.get("forbidden_returned"))
    return {
        "case_count": len(cases),
        f"memory_recall_at_{k}": round(statistics.fmean(recalls), 6),
        "memory_isolation_rate": round(isolated / len(cases), 6),
        "current_thread_exclusion_rate": round(excluded / len(cases), 6),
    }


def _relation_label(item: dict[str, Any]) -> str:
    source = item.get("source_entity") or item.get("source_name") or ""
    target = item.get("target_entity") or item.get("target_name") or ""
    return f"{source}|{item.get('relation_type') or ''}|{target}"


def evaluate_graph_cases(
    service: Any,
    definitions: list[dict[str, Any]],
    *,
    user_id: str,
) -> list[dict[str, Any]]:
    """Exercise production GraphRAG routing, paths, evidence, and time filters."""
    cases: list[dict[str, Any]] = []
    for item in definitions:
        state = {
            "user_id": user_id,
            "thread_id": item.get("current_thread_id") or "eval-graph-current",
            "user_request": item["query"],
            "target_products": list(item.get("products") or []),
            "analysis_brief": {
                "objective": item["query"],
                "target_products": list(item.get("products") or []),
                "effective_dimensions": [{"id": value} for value in item.get("dimensions") or ["features"]],
            },
        }
        evidence = service.retrieve_for_analysis(state, limit=20)
        context, plan = service.retrieve_relationship_context(state, evidence, limit=int(item.get("k") or 5))
        snapshot = service.graph(user_id, temporal_mode="all", limit=2000)
        current = service.graph(user_id, temporal_mode="current", limit=2000)
        historical = service.graph(user_id, temporal_mode="historical", limit=2000)
        expected_current = set(item.get("expected_current") or [])
        expected_historical = set(item.get("expected_historical") or [])
        current_labels = {_relation_label(value) for value in current["relations"]}
        historical_labels = {_relation_label(value) for value in historical["relations"]}
        cases.append(
            {
                "id": item.get("id"),
                "expected_route": item.get("expected_route"),
                "actual_route": plan.get("route"),
                "relevant": list(item.get("relevant") or []),
                "ranked": [_relation_label(value) for value in context],
                "returned_count": len(context),
                "traceable_count": sum(bool(value.get("source_data_point_ids")) for value in context if value.get("citation_eligible")),
                "citable_count": sum(bool(value.get("citation_eligible")) for value in context),
                "unsupported_relation_count": sum(not value.get("evidence") for value in snapshot["relations"]),
                "persisted_relation_count": len(snapshot["relations"]),
                "temporal_correct": (
                    expected_current <= current_labels
                    and expected_historical <= historical_labels
                    and all(not value.get("valid_to") or not value.get("valid_from") or str(value["valid_from"]) <= str(value["valid_to"]) for value in snapshot["relations"])
                ),
            }
        )
    return cases


def compute_graph_metrics(cases: list[dict[str, Any]], *, k: int = 5) -> dict[str, Any]:
    if not cases:
        return {
            "case_count": 0,
            "graph_route_accuracy": 1.0,
            f"relation_recall_at_{k}": 1.0,
            "relation_traceability_rate": 1.0,
            "temporal_relation_accuracy": 1.0,
            "unsupported_relation_rate": 0.0,
        }
    recalls: list[float] = []
    citable = 0
    traceable = 0
    unsupported = 0
    persisted = 0
    for case in cases:
        relevant = set(case.get("relevant") or [])
        ranked = set((case.get("ranked") or [])[:k])
        recalls.append(len(relevant.intersection(ranked)) / len(relevant) if relevant else 1.0)
        citable += int(case.get("citable_count") or 0)
        traceable += int(case.get("traceable_count") or 0)
        unsupported += int(case.get("unsupported_relation_count") or 0)
        persisted += int(case.get("persisted_relation_count") or 0)
    return {
        "case_count": len(cases),
        "graph_route_accuracy": round(
            sum(case.get("actual_route") == case.get("expected_route") for case in cases) / len(cases),
            6,
        ),
        f"relation_recall_at_{k}": round(statistics.fmean(recalls), 6),
        "relation_traceability_rate": round(traceable / citable if citable else 1.0, 6),
        "temporal_relation_accuracy": round(
            sum(bool(case.get("temporal_correct")) for case in cases) / len(cases),
            6,
        ),
        "unsupported_relation_rate": round(unsupported / persisted if persisted else 0.0, 6),
    }


def check_thresholds(metrics: dict[str, Any], thresholds: EvaluationThresholds, *, k: int = 5) -> list[str]:
    failures: list[str] = []
    checks = {
        f"recall_at_{k}": thresholds.recall_at_k,
        "mrr": thresholds.mrr,
        f"ndcg_at_{k}": thresholds.ndcg_at_k,
        "abstention_accuracy": thresholds.abstention_accuracy,
        "traceability_rate": thresholds.traceability_rate,
    }
    for name, minimum in checks.items():
        actual = float(metrics.get(name) or 0.0)
        if actual < minimum:
            failures.append(f"{name}={actual:.4f} is below {minimum:.4f}")
    if thresholds.max_p95_latency_ms is not None:
        actual_p95 = float((metrics.get("latency_ms") or {}).get("p95") or 0.0)
        if actual_p95 > thresholds.max_p95_latency_ms:
            failures.append(f"latency_ms.p95={actual_p95:.1f} exceeds {thresholds.max_p95_latency_ms:.1f}")
    verification = metrics.get("verification") or {}
    if verification:
        verification_checks = {
            "claim_status_accuracy": thresholds.claim_status_accuracy,
            "contradiction_recall": thresholds.contradiction_recall,
            "citation_precision": thresholds.citation_precision,
            "numeric_consistency_accuracy": thresholds.numeric_consistency_accuracy,
            "groundedness": thresholds.groundedness,
        }
        for name, minimum in verification_checks.items():
            actual = float(verification.get(name) or 0.0)
            if actual < minimum:
                failures.append(f"verification.{name}={actual:.4f} is below {minimum:.4f}")
    planning = metrics.get("planning") or {}
    if planning:
        for name, minimum in {
            "query_route_accuracy": thresholds.query_route_accuracy,
            "decomposition_coverage": thresholds.decomposition_coverage,
        }.items():
            actual = float(planning.get(name) or 0.0)
            if actual < minimum:
                failures.append(f"planning.{name}={actual:.4f} is below {minimum:.4f}")
    governance = metrics.get("governance") or {}
    if governance:
        for name, minimum in {
            "governance_accuracy": thresholds.governance_accuracy,
            "quarantine_recall": thresholds.quarantine_recall,
        }.items():
            actual = float(governance.get(name) or 0.0)
            if actual < minimum:
                failures.append(f"governance.{name}={actual:.4f} is below {minimum:.4f}")
    memory = metrics.get("memory") or {}
    if memory:
        for name, minimum in {
            f"memory_recall_at_{k}": thresholds.memory_recall_at_k,
            "memory_isolation_rate": thresholds.memory_isolation_rate,
            "current_thread_exclusion_rate": thresholds.current_thread_exclusion_rate,
        }.items():
            actual = float(memory.get(name) or 0.0)
            if actual < minimum:
                failures.append(f"memory.{name}={actual:.4f} is below {minimum:.4f}")
    graph = metrics.get("graph") or {}
    if graph:
        for name, minimum in {
            "graph_route_accuracy": thresholds.graph_route_accuracy,
            f"relation_recall_at_{k}": thresholds.relation_recall_at_k,
            "relation_traceability_rate": thresholds.relation_traceability_rate,
            "temporal_relation_accuracy": thresholds.temporal_relation_accuracy,
        }.items():
            actual = float(graph.get(name) or 0.0)
            if actual < minimum:
                failures.append(f"graph.{name}={actual:.4f} is below {minimum:.4f}")
        unsupported = float(graph.get("unsupported_relation_rate") or 0.0)
        if unsupported > thresholds.unsupported_relation_rate:
            failures.append(f"graph.unsupported_relation_rate={unsupported:.4f} exceeds {thresholds.unsupported_relation_rate:.4f}")
    return failures


def evaluate_queries(
    service: Any,
    queries: list[dict[str, Any]],
    *,
    user_id: str,
    k: int = 5,
    document_labels: dict[str, str] | None = None,
    query_expansion: bool | None = None,
) -> list[dict[str, Any]]:
    labels = document_labels or {}
    cases: list[dict[str, Any]] = []
    for item in queries:
        filters = RetrievalFilters(
            products=tuple(item.get("products") or ()),
            dimensions=tuple(item.get("dimensions") or ()),
            market_scope=str(item.get("market_scope") or ""),
            authority_tiers=tuple(item.get("authority_tiers") or ()),
            published_after=item.get("published_after"),
            published_before=item.get("published_before"),
            include_reports=bool(item.get("include_reports", False)),
        )
        started = time.perf_counter()
        plan = None
        if item.get("expected_route") or query_expansion is not None:
            hits, plan = service.search_planned(
                str(item["query"]), user_id=user_id, filters=filters, limit=k,
                query_expansion=query_expansion,
            )
        else:
            hits = service.search(str(item["query"]), user_id=user_id, filters=filters, limit=k)
        elapsed_ms = (time.perf_counter() - started) * 1000
        ranked = [
            {
                "label": labels.get(hit.document_id, hit.document_id),
                "document_id": hit.document_id,
                "chunk_id": hit.chunk_id,
                "score": hit.score,
            }
            for hit in hits
        ]
        cases.append(
            {
                "id": item.get("id"),
                "query": item["query"],
                "relevant": list(item.get("relevant") or []),
                "ranked": ranked,
                "latency_ms": round(elapsed_ms, 3),
                "expected_route": item.get("expected_route"),
                "actual_route": plan.route if plan else None,
                "required_step_purposes": list(item.get("required_step_purposes") or []),
                "actual_step_purposes": [step.purpose for step in plan.steps] if plan else [],
                "actual_step_count": len(plan.steps) if plan else 0,
            }
        )
    return cases


def evaluate_query_expansion(
    service: Any,
    queries: list[dict[str, Any]],
    *,
    user_id: str,
    k: int = 5,
    document_labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Compare retrieval quality with the bounded expansion switch off/on."""
    baseline_cases = evaluate_queries(
        service, queries, user_id=user_id, k=k, document_labels=document_labels,
        query_expansion=False,
    )
    invalidate = getattr(service, "_invalidate_result_cache", None)
    if callable(invalidate):
        invalidate(user_id)
    expanded_cases = evaluate_queries(
        service, queries, user_id=user_id, k=k, document_labels=document_labels,
        query_expansion=True,
    )
    baseline = compute_retrieval_metrics(baseline_cases, k=k)
    expanded = compute_retrieval_metrics(expanded_cases, k=k)
    return {
        "baseline": baseline,
        "expanded": expanded,
        "delta": {
            f"recall_at_{k}": round(expanded[f"recall_at_{k}"] - baseline[f"recall_at_{k}"], 6),
            "mrr": round(expanded["mrr"] - baseline["mrr"], 6),
            f"ndcg_at_{k}": round(expanded[f"ndcg_at_{k}"] - baseline[f"ndcg_at_{k}"], 6),
            "p95_latency_ms": round(
                expanded["latency_ms"]["p95"] - baseline["latency_ms"]["p95"], 3,
            ),
        },
        "case_count": len(queries),
    }


def evaluate_verification_cases(
    service: Any,
    definitions: list[dict[str, Any]],
    *,
    user_id: str,
    document_ids: dict[str, str],
) -> list[dict[str, Any]]:
    """Run golden claims through production verification and retain audit details."""
    from competition.evidence_verification import verify_claims

    cases: list[dict[str, Any]] = []
    for item in definitions:
        collected: list[dict[str, Any]] = []
        for label in item.get("cited_documents") or []:
            document_id = document_ids.get(label)
            detail = service.document_detail(document_id, user_id) if document_id else None
            if not detail or not detail.get("chunks"):
                continue
            chunk = detail["chunks"][0]
            collected.append(
                {
                    "id": label,
                    "product": detail.get("product") or "",
                    "category": detail.get("dimension") or "",
                    "label": detail.get("title") or label,
                    "value": chunk.get("text") or "",
                    "source_url": detail.get("source_uri") or f"knowledge://{document_id}/{chunk['chunk_id']}",
                    "source_type": "docs",
                    "source_authority": detail.get("authority_tier") or "third_party",
                    "collected_at": detail.get("observed_at"),
                    "published_at": detail.get("published_at"),
                    "knowledge_document_id": document_id,
                    "knowledge_chunk_id": chunk["chunk_id"],
                    "retrieval_score": 1.0,
                }
            )
        analysis = {
            "comparison_matrix": {
                "cells": [
                    {
                        "product": item.get("product") or "",
                        "dimension": item.get("dimension") or "",
                        "evidence": item["claim"],
                        "source_data_point_ids": list(item.get("cited_documents") or []),
                    }
                ]
            }
        }
        started = time.perf_counter()
        summary = verify_claims(
            analysis,
            collected,
            user_id=user_id,
            search_many=lambda requests, owner: service.search_many(requests, user_id=owner),
            semantic_scorer=service.index.rerank_many,
        )
        claim = summary["claims"][0]
        supporting = []
        contradicting = []
        for evidence in claim.get("evidence") or []:
            document_id = evidence.get("document_id")
            label = next((key for key, value in document_ids.items() if value == document_id), document_id)
            if evidence.get("relation") == "supports" and label and label not in supporting:
                supporting.append(label)
            if evidence.get("relation") == "contradicts" and label and label not in contradicting:
                contradicting.append(label)
        cases.append(
            {
                "id": item.get("id"),
                "claim": item["claim"],
                "expected_status": item["expected_status"],
                "actual_status": claim["status"],
                "expected_supporting": list(item.get("expected_supporting") or []),
                "actual_supporting": supporting,
                "expected_contradicting": list(item.get("expected_contradicting") or []),
                "actual_contradicting": contradicting,
                "expected_numeric_consistency": item.get("expected_numeric_consistency"),
                "actual_numeric_consistency": claim.get("numeric_consistency"),
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                "verification": summary,
            }
        )
    return cases
