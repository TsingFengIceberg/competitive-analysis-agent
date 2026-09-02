"""Offline retrieval evaluation metrics and dataset runner."""

from __future__ import annotations

import math
import random
import statistics
import time
from collections import Counter
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
    max_failure_rate: float | None = None
    max_degraded_rate: float | None = None
    max_p99_latency_ms: float | None = None
    max_cost_usd_per_case: float | None = None
    robustness_invariance_rate: float | None = None


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
    abstention_cases = [case for case in unanswerable if case.get("abstention_expected", True)]
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
    abstained = sum(not case.get("ranked") for case in abstention_cases)
    return {
        "case_count": len(cases),
        "answerable_count": len(answerable),
        "unanswerable_count": len(unanswerable),
        f"recall_at_{k}": round(statistics.fmean(recalls), 6) if recalls else 0.0,
        "mrr": round(statistics.fmean(reciprocal_ranks), 6) if reciprocal_ranks else 0.0,
        f"ndcg_at_{k}": round(statistics.fmean(ndcgs), 6) if ndcgs else 0.0,
        "abstention_case_count": len(abstention_cases),
        "abstention_accuracy": round(abstained / len(abstention_cases), 6) if abstention_cases else 1.0,
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


_ANSWER_QUALITY_DIMENSIONS = (
    "factuality",
    "groundedness",
    "citation_completeness",
    "decision_usefulness",
    "comparison_fairness",
)


def compute_answer_quality_metrics(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate human or judge scores without pretending they are retrieval metrics.

    Each case may provide a ``scores`` mapping with values in ``[0, 1]``. The
    function intentionally ignores missing dimensions and reports coverage so
    an incomplete manual review cannot look like a complete benchmark.
    """
    score_values: dict[str, list[float]] = {dimension: [] for dimension in _ANSWER_QUALITY_DIMENSIONS}
    invalid = 0
    for case in cases:
        scores = case.get("scores") or case.get("actual_scores") or {}
        if not isinstance(scores, dict):
            invalid += 1
            continue
        for dimension in _ANSWER_QUALITY_DIMENSIONS:
            value = scores.get(dimension)
            if value is None:
                continue
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                invalid += 1
                continue
            if not 0.0 <= numeric <= 1.0:
                invalid += 1
                continue
            score_values[dimension].append(numeric)
    dimension_metrics = {
        dimension: {
            "sample_count": len(values),
            "mean": round(statistics.fmean(values), 6) if values else None,
        }
        for dimension, values in score_values.items()
    }
    means = [item["mean"] for item in dimension_metrics.values() if item["mean"] is not None]
    return {
        "case_count": len(cases),
        "scored_case_count": sum(bool(case.get("scores") or case.get("actual_scores")) for case in cases),
        "invalid_score_count": invalid,
        "coverage": round(sum(bool(values) for values in score_values.values()) / len(score_values), 6),
        "overall_mean": round(statistics.fmean(means), 6) if means else None,
        "dimensions": dimension_metrics,
        "method": "human_or_judge_scores",
    }


def bootstrap_metric_intervals(
    cases: list[dict[str, Any]],
    *,
    k: int = 5,
    iterations: int = 1000,
    confidence: float = 0.95,
    seed: int = 17,
) -> dict[str, Any]:
    """Estimate uncertainty for retrieval metrics with deterministic bootstrap sampling."""
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be between 0 and 1")
    if iterations < 100:
        raise ValueError("iterations must be at least 100")
    point = compute_retrieval_metrics(cases, k=k)
    metric_names = (f"recall_at_{k}", "mrr", f"ndcg_at_{k}", "abstention_accuracy", "traceability_rate")
    if len(cases) < 2:
        return {
            "method": "nonparametric_bootstrap",
            "confidence": confidence,
            "iterations": iterations,
            "seed": seed,
            "sample_count": len(cases),
            "intervals": {},
            "warnings": ["at least two cases are required for a confidence interval"],
        }
    rng = random.Random(seed)
    samples: dict[str, list[float]] = {name: [] for name in metric_names}
    for _ in range(iterations):
        resampled = [cases[rng.randrange(len(cases))] for _ in cases]
        metrics = compute_retrieval_metrics(resampled, k=k)
        for name in metric_names:
            samples[name].append(float(metrics.get(name) or 0.0))
    tail = (1.0 - confidence) / 2.0
    return {
        "method": "nonparametric_bootstrap",
        "confidence": confidence,
        "iterations": iterations,
        "seed": seed,
        "sample_count": len(cases),
        "intervals": {
            name: {
                "estimate": point.get(name),
                "lower": round(_percentile(values, tail), 6),
                "upper": round(_percentile(values, 1.0 - tail), 6),
            }
            for name, values in samples.items()
        },
        "warnings": [],
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
    retrieval_fields = {f"recall_at_{k}", "mrr", f"ndcg_at_{k}", "abstention_accuracy", "traceability_rate"}
    if retrieval_fields.intersection(metrics):
        checks = {
            f"recall_at_{k}": thresholds.recall_at_k,
            "mrr": thresholds.mrr,
            f"ndcg_at_{k}": thresholds.ndcg_at_k,
            "abstention_accuracy": thresholds.abstention_accuracy,
            "traceability_rate": thresholds.traceability_rate,
        }
        for name, minimum in checks.items():
            if name not in metrics:
                continue
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
    runtime = metrics.get("runtime") or {}
    if thresholds.max_failure_rate is not None and float(runtime.get("failure_rate") or 0.0) > thresholds.max_failure_rate:
        failures.append(f"runtime.failure_rate={float(runtime.get('failure_rate') or 0.0):.4f} exceeds {thresholds.max_failure_rate:.4f}")
    if thresholds.max_degraded_rate is not None and float(runtime.get("degraded_rate") or 0.0) > thresholds.max_degraded_rate:
        failures.append(f"runtime.degraded_rate={float(runtime.get('degraded_rate') or 0.0):.4f} exceeds {thresholds.max_degraded_rate:.4f}")
    if thresholds.max_p99_latency_ms is not None:
        p99 = float((runtime.get("latency_ms") or {}).get("p99") or 0.0)
        if p99 > thresholds.max_p99_latency_ms:
            failures.append(f"runtime.latency_ms.p99={p99:.1f} exceeds {thresholds.max_p99_latency_ms:.1f}")
    if thresholds.max_cost_usd_per_case is not None:
        cost = runtime.get("cost") or {}
        observed_cost = cost.get("observed_cost_usd")
        cost_case_count = int(cost.get("case_count") or 0)
        if observed_cost is not None and cost_case_count:
            cost_per_case = float(observed_cost) / cost_case_count
            if cost_per_case > thresholds.max_cost_usd_per_case:
                failures.append(f"runtime.cost.usd_per_case={cost_per_case:.6f} exceeds {thresholds.max_cost_usd_per_case:.6f}")
    robustness = metrics.get("robustness") or {}
    if thresholds.robustness_invariance_rate is not None and robustness.get("invariance_rate") is not None:
        actual_invariance = float(robustness.get("invariance_rate") or 0.0)
        if actual_invariance < thresholds.robustness_invariance_rate:
            failures.append(
                f"robustness.invariance_rate={actual_invariance:.4f} is below {thresholds.robustness_invariance_rate:.4f}"
            )
    return failures


def evaluate_queries(
    service: Any,
    queries: list[dict[str, Any]],
    *,
    user_id: str,
    k: int = 5,
    document_labels: dict[str, str] | None = None,
    query_expansion: bool | None = None,
    retrieval_mode: str = "hybrid",
    rerank: bool = True,
    ranking_profile: str = "balanced",
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
            try:
                hits, plan = service.search_planned(
                    str(item["query"]), user_id=user_id, filters=filters, limit=k,
                    query_expansion=query_expansion,
                    retrieval_mode=retrieval_mode,
                    rerank=rerank,
                    ranking_profile=ranking_profile,
                )
            except TypeError as exc:
                # Keep lightweight test doubles and third-party adapters that
                # implement the pre-strategy contract usable in evaluations.
                if not any(name in str(exc) for name in ("retrieval_mode", "rerank", "ranking_profile")):
                    raise
                hits, plan = service.search_planned(
                    str(item["query"]), user_id=user_id, filters=filters, limit=k,
                    query_expansion=query_expansion,
                )
        else:
            try:
                hits = service.search(
                    str(item["query"]),
                    user_id=user_id,
                    filters=filters,
                    limit=k,
                    retrieval_mode=retrieval_mode,
                    rerank=rerank,
                    ranking_profile=ranking_profile,
                )
            except TypeError as exc:
                if not any(name in str(exc) for name in ("retrieval_mode", "rerank", "ranking_profile")):
                    raise
                hits = service.search(str(item["query"]), user_id=user_id, filters=filters, limit=k)
        elapsed_ms = (time.perf_counter() - started) * 1000
        ranked = [
            {
                "label": labels.get(hit.document_id, hit.document_id),
                "document_id": hit.document_id,
                "chunk_id": hit.chunk_id,
                "score": hit.score,
                "token_estimate": max(1, round(len(hit.contextual_text or hit.text) / 4)),
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
                "category": item.get("category", "uncategorized"),
                "difficulty": item.get("difficulty", "unspecified"),
                "split": item.get("split", "eval"),
                "answerable": bool(item.get("relevant")),
                "abstention_expected": bool(item.get("abstention_expected", not item.get("relevant"))),
                "products": list(item.get("products") or []),
                "robustness_group": item.get("robustness_group"),
                "variant_type": item.get("variant_type"),
                "expected_invariant": bool(item.get("expected_invariant", True)),
            }
        )
    return cases


_LOWER_IS_BETTER = ("latency", "error", "unsupported", "cost", "failure", "abstention_loss")


def metric_direction(path: str) -> str:
    """Return whether increasing a metric is an improvement."""
    lowered = str(path).casefold()
    return "lower" if any(token in lowered for token in _LOWER_IS_BETTER) else "higher"


def _flatten_numeric(prefix: str, value: Any) -> dict[str, float]:
    if isinstance(value, dict):
        flattened: dict[str, float] = {}
        for key, child in value.items():
            flattened.update(_flatten_numeric(f"{prefix}.{key}" if prefix else str(key), child))
        return flattened
    leaf = prefix.rsplit(".", 1)[-1]
    if leaf == "case_count" or leaf.endswith("_count"):
        return {}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return {prefix: float(value)}
    return {}


def compare_metric_sets(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Compare scalar metrics with direction-aware relative changes.

    A zero baseline is retained as an explicit undefined relative change so
    reports cannot accidentally present an infinite or fabricated percentage.
    """
    old = _flatten_numeric("", baseline)
    new = _flatten_numeric("", candidate)
    absolute: dict[str, float] = {}
    relative: dict[str, float | None] = {}
    directions: dict[str, str] = {}
    undefined: dict[str, str] = {}
    for key in sorted(set(old).intersection(new)):
        delta = new[key] - old[key]
        direction = metric_direction(key)
        if direction == "lower":
            delta = old[key] - new[key]
        absolute[key] = round(delta, 6)
        directions[key] = direction
        if old[key] == 0:
            relative[key] = None
            undefined[key] = "baseline_is_zero"
        else:
            relative[key] = round(delta / abs(old[key]), 6)
    return {
        "absolute_delta": absolute,
        "relative_change": relative,
        "directions": directions,
        "undefined": undefined,
    }


def aggregate_query_metrics(
    cases: list[dict[str, Any]],
    *,
    k: int = 5,
    dimensions: tuple[str, ...] = ("category", "difficulty", "split", "answerability", "product"),
) -> dict[str, Any]:
    """Compute retrieval metrics for each declared query classification."""
    groups: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for case in cases:
        for dimension in dimensions:
            if dimension == "answerability":
                values = ["answerable" if case.get("relevant") else "unanswerable"]
            elif dimension == "product":
                values = [str(value) for value in case.get("products") or []] or ["shared/unspecified"]
            else:
                values = [str(case.get(dimension) or "unspecified")]
            for value in values:
                groups.setdefault(dimension, {}).setdefault(value, []).append(case)
    return {
        dimension: {
            value: {"sample_count": len(group), "metrics": compute_retrieval_metrics(group, k=k)}
            for value, group in values.items()
        }
        for dimension, values in groups.items()
    }


def evaluation_coverage(
    cases: list[dict[str, Any]],
    *,
    minimum_cases: int = 0,
    required_categories: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Report sample-size and category coverage warnings for quality gates."""
    present = {str(case.get("category") or "uncategorized") for case in cases}
    missing = sorted(set(required_categories) - present)
    warnings: list[str] = []
    if minimum_cases and len(cases) < minimum_cases:
        warnings.append(f"case_count={len(cases)} is below minimum {minimum_cases}")
    if missing:
        warnings.append(f"missing_categories={','.join(missing)}")
    return {
        "case_count": len(cases),
        "minimum_cases": minimum_cases,
        "required_categories": list(required_categories),
        "present_categories": sorted(present),
        "missing_categories": missing,
        "warnings": warnings,
    }


def compute_runtime_metrics(
    cases: list[dict[str, Any]],
    logs: list[dict[str, Any]] | None = None,
    *,
    pricing: dict[str, dict[str, float]] | None = None,
    wall_time_ms: float | None = None,
    concurrency: int = 1,
) -> dict[str, Any]:
    """Summarize observable retrieval cost and reliability without guessing.

    Token counts are reported only when the caller supplied them. Retrieval
    logs provide authoritative search/cache/failure counts when available.
    """
    logs = logs or []
    durations = [float(case.get("latency_ms") or 0.0) for case in cases]
    statuses = [str(item.get("status") or "completed") for item in logs]
    filters = [item.get("filters") if isinstance(item.get("filters"), dict) else {} for item in logs]
    token_values = [float(case["token_count"]) for case in cases if case.get("token_count") is not None]
    if not token_values:
        token_values = [
            float(sum(item.get("token_estimate") or 0 for item in case.get("ranked") or []))
            for case in cases
            if case.get("ranked")
        ]
    retry_count = sum(int(case.get("retry_count") or 0) for case in cases)
    retry_count += sum(int(item.get("retry_count") or 0) for item in logs)
    timeout_count = sum(status == "timeout" for status in statuses)
    cancelled_count = sum(status in {"cancelled", "canceled"} for status in statuses)
    failure_count = sum(status not in {"completed", "degraded"} for status in statuses) if logs else 0
    degraded_count = sum(status == "degraded" for status in statuses) if logs else 0
    retry_success_count = sum(
        int(item.get("retry_count") or 0) > 0 and str(item.get("status") or "") in {"completed", "degraded"}
        for item in logs
    )
    retry_exhausted_count = sum(
        int(item.get("retry_count") or 0) > 0 and str(item.get("status") or "") in {"failed", "timeout", "cancelled", "canceled"}
        for item in logs
    )
    cost = compute_cost_metrics(cases, pricing=pricing)
    load = compute_load_metrics(cases, wall_time_ms=wall_time_ms, concurrency=concurrency)
    return {
        "query_count": len(cases),
        "search_count": len(logs) if logs else None,
        "cache_hit_count": sum(bool(item.get("cache_hit")) for item in filters) if logs else None,
        "cache_hit_rate": round(sum(bool(item.get("cache_hit")) for item in filters) / len(filters), 6) if filters else None,
        "failure_count": failure_count,
        "failure_rate": round(failure_count / len(statuses), 6) if statuses else 0.0,
        "degraded_count": degraded_count,
        "degraded_rate": round(degraded_count / len(statuses), 6) if statuses else 0.0,
        "timeout_count": timeout_count,
        "cancelled_count": cancelled_count,
        "retry_count": retry_count,
        "retry_success_count": retry_success_count,
        "retry_exhausted_count": retry_exhausted_count,
        "retrieved_token_estimate": round(sum(token_values), 3) if token_values else None,
        "cost": cost,
        "load": load,
        "latency_ms": {
            "mean": round(statistics.fmean(durations), 3) if durations else 0.0,
            "p50": round(_percentile(durations, 0.50), 3),
            "p95": round(_percentile(durations, 0.95), 3),
            "p99": round(_percentile(durations, 0.99), 3),
        },
        "notes": [
            "search/cache counts require retrieval logs",
            "token estimate is null when token instrumentation is unavailable",
            "cost is null until model usage and pricing are supplied",
        ],
    }


def compute_load_metrics(
    cases: list[dict[str, Any]],
    *,
    wall_time_ms: float | None = None,
    concurrency: int = 1,
) -> dict[str, Any]:
    """Summarize throughput and error behavior for serial or externally timed loads."""
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    durations = [float(case.get("latency_ms") or 0.0) for case in cases]
    measured_wall_time = float(wall_time_ms) if wall_time_ms is not None else sum(durations)
    if measured_wall_time < 0:
        raise ValueError("wall_time_ms must be non-negative")
    statuses = [str(case.get("status") or "completed") for case in cases]
    failed = sum(status not in {"completed", "degraded"} for status in statuses)
    return {
        "query_count": len(cases),
        "concurrency": concurrency,
        "wall_time_ms": round(measured_wall_time, 3),
        "wall_time_source": "supplied" if wall_time_ms is not None else "sum_case_latency",
        "throughput_qps": round(len(cases) / (measured_wall_time / 1000), 6) if measured_wall_time > 0 else None,
        "failed_count": failed,
        "error_rate": round(failed / len(cases), 6) if cases else 0.0,
        "p95_latency_ms": round(_percentile(durations, 0.95), 3),
        "p99_latency_ms": round(_percentile(durations, 0.99), 3),
    }


_USAGE_FIELDS = ("input_tokens", "output_tokens", "total_tokens", "cost_usd")


def _usage_value(case: dict[str, Any], field: str) -> float | None:
    usage = case.get("usage") if isinstance(case.get("usage"), dict) else {}
    value = usage.get(field)
    if value is None:
        value = case.get(field)
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) and numeric >= 0 else None


def compute_cost_metrics(
    cases: list[dict[str, Any]],
    *,
    pricing: dict[str, dict[str, float]] | None = None,
) -> dict[str, Any]:
    """Aggregate observed model usage and optionally estimate its monetary cost.

    ``pricing`` maps a model name (or ``default``) to ``input_usd_per_1k`` and
    ``output_usd_per_1k``. No price or model usage means cost remains ``None``;
    retrieval character estimates are intentionally not treated as LLM usage.
    """
    pricing = pricing or {}
    input_tokens = 0.0
    output_tokens = 0.0
    total_tokens = 0.0
    observed_cost = 0.0
    observed_cost_count = 0
    instrumented = 0
    estimated_cost = 0.0
    estimated_count = 0
    models: set[str] = set()
    for case in cases:
        usage = case.get("usage") if isinstance(case.get("usage"), dict) else {}
        model = str(usage.get("model") or case.get("model") or "")
        if model:
            models.add(model)
        values = {field: _usage_value(case, field) for field in _USAGE_FIELDS}
        has_usage = any(values[field] is not None for field in ("input_tokens", "output_tokens", "total_tokens"))
        if has_usage:
            instrumented += 1
            input_tokens += values["input_tokens"] or 0.0
            output_tokens += values["output_tokens"] or 0.0
            total_tokens += values["total_tokens"] if values["total_tokens"] is not None else (values["input_tokens"] or 0.0) + (values["output_tokens"] or 0.0)
        if values["cost_usd"] is not None:
            observed_cost += values["cost_usd"] or 0.0
            observed_cost_count += 1
        price = pricing.get(model) or pricing.get("default")
        if has_usage and price:
            input_price = float(price.get("input_usd_per_1k") or 0.0)
            output_price = float(price.get("output_usd_per_1k") or 0.0)
            estimated_cost += ((values["input_tokens"] or 0.0) / 1000) * input_price
            estimated_cost += ((values["output_tokens"] or 0.0) / 1000) * output_price
            estimated_count += 1
    warnings: list[str] = []
    if not instrumented:
        warnings.append("model usage is not instrumented")
    elif estimated_count and estimated_count < instrumented:
        warnings.append("pricing is missing for some instrumented models")
    return {
        "case_count": len(cases),
        "instrumented_case_count": instrumented,
        "coverage": round(instrumented / len(cases), 6) if cases else 0.0,
        "input_tokens": round(input_tokens, 3) if instrumented else None,
        "output_tokens": round(output_tokens, 3) if instrumented else None,
        "total_tokens": round(total_tokens, 3) if instrumented else None,
        "observed_cost_usd": round(observed_cost, 6) if observed_cost_count else None,
        "estimated_cost_usd": round(estimated_cost, 6) if estimated_count else None,
        "cost_coverage": round(observed_cost_count / len(cases), 6) if cases else 0.0,
        "pricing_coverage": round(estimated_count / instrumented, 6) if instrumented else 0.0,
        "models": sorted(models),
        "warnings": warnings,
    }


def compute_dataset_quality_metrics(dataset: dict[str, Any]) -> dict[str, Any]:
    """Check benchmark metadata completeness, duplicates, distractors, and balance."""
    documents = list(dataset.get("documents") or [])
    queries = list(dataset.get("queries") or [])
    robustness_queries = list(dataset.get("robustness_queries") or [])
    required_document_fields = ("id", "filename", "text", "source_url", "product", "dimension", "authority_tier", "captured_at")
    missing_document_fields = sum(
        1 for document in documents if any(not str(document.get(field) or "").strip() for field in required_document_fields)
    )
    duplicate_texts = len(documents) - len({str(document.get("text") or "").strip() for document in documents})
    referenced = {str(label) for query in queries for label in query.get("relevant") or []}
    known_ids = {str(document.get("id") or "") for document in documents}
    orphan_documents = len((known_ids - referenced) - {""})
    categories = Counter(str(query.get("category") or "uncategorized") for query in queries)
    answerable = sum(bool(query.get("relevant")) for query in queries)
    metadata_complete = sum(
        all(str(query.get(field) or "").strip() for field in ("id", "query", "category", "difficulty", "split"))
        for query in queries
    )
    warnings: list[str] = []
    if missing_document_fields:
        warnings.append(f"documents_missing_metadata={missing_document_fields}")
    if duplicate_texts:
        warnings.append(f"duplicate_document_texts={duplicate_texts}")
    if not documents:
        warnings.append("no_documents")
    if not queries:
        warnings.append("no_queries")
    return {
        "document_count": len(documents),
        "query_count": len(queries),
        "robustness_query_count": len(robustness_queries),
        "total_query_count": len(queries) + len(robustness_queries),
        "answerable_count": answerable,
        "answerable_rate": round(answerable / len(queries), 6) if queries else 0.0,
        "document_metadata_completeness": round((len(documents) - missing_document_fields) / len(documents), 6) if documents else 0.0,
        "query_metadata_completeness": round(metadata_complete / len(queries), 6) if queries else 0.0,
        "duplicate_document_text_count": duplicate_texts,
        "distractor_document_count": orphan_documents,
        "distractor_document_ratio": round(orphan_documents / len(documents), 6) if documents else 0.0,
        "category_counts": dict(sorted(categories.items())),
        "warnings": warnings,
    }


def compute_dataset_drift(
    current: dict[str, Any],
    baseline: dict[str, Any] | None,
    *,
    max_category_shift: float = 0.25,
) -> dict[str, Any]:
    """Compare benchmark versions and flag distribution changes before scoring."""
    if not baseline:
        return {"status": "unavailable", "warnings": ["no baseline dataset configured"]}
    current_quality = compute_dataset_quality_metrics(current)
    baseline_quality = compute_dataset_quality_metrics(baseline)
    current_categories = Counter(current_quality["category_counts"])
    baseline_categories = Counter(baseline_quality["category_counts"])
    has_usable_category_baseline = bool(baseline_categories) and set(baseline_categories) != {"uncategorized"}
    category_shift: float | None = None
    if has_usable_category_baseline:
        current_total = max(1, sum(current_categories.values()))
        baseline_total = max(1, sum(baseline_categories.values()))
        category_shift = 0.5 * sum(
            abs(current_categories.get(category, 0) / current_total - baseline_categories.get(category, 0) / baseline_total)
            for category in set(current_categories) | set(baseline_categories)
        )
    current_ids = {str(item.get("id") or "") for item in current.get("documents") or []}
    baseline_ids = {str(item.get("id") or "") for item in baseline.get("documents") or []}
    warnings = []
    if category_shift is None:
        warnings.append("baseline_category_metadata_unavailable")
    elif category_shift > max_category_shift:
        warnings.append(f"category_distribution_shift={category_shift:.4f} exceeds {max_category_shift:.4f}")
    return {
        "status": "partial" if category_shift is None else ("drifted" if warnings else "stable"),
        "max_category_shift": max_category_shift,
        "category_distribution_shift": round(category_shift, 6) if category_shift is not None else None,
        "query_count_delta": current_quality["query_count"] - baseline_quality["query_count"],
        "document_count_delta": current_quality["document_count"] - baseline_quality["document_count"],
        "answerable_rate_delta": round(current_quality["answerable_rate"] - baseline_quality["answerable_rate"], 6),
        "added_document_ids": sorted(current_ids - baseline_ids),
        "removed_document_ids": sorted(baseline_ids - current_ids),
        "warnings": warnings,
    }


def compute_robustness_metrics(cases: list[dict[str, Any]], *, k: int = 5, tolerance: float = 0.1) -> dict[str, Any]:
    """Measure retrieval stability across explicitly paired query perturbations."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for case in cases:
        group = str(case.get("robustness_group") or "")
        if group:
            groups.setdefault(group, []).append(case)
    if not groups:
        return {
            "case_count": len(cases),
            "group_count": 0,
            "invariance_rate": None,
            "mean_recall_delta": None,
            "mean_top_k_overlap": None,
            "degradation_rate": None,
            "warnings": ["no paired robustness cases supplied"],
        }
    deltas: list[float] = []
    overlaps: list[float] = []
    invariant_passes = 0
    invariant_total = 0
    degradations = 0
    for group_cases in groups.values():
        baseline = next((case for case in group_cases if case.get("variant_type") == "baseline"), group_cases[0])
        baseline_metrics = compute_retrieval_metrics([baseline], k=k)
        baseline_recall = float(baseline_metrics.get(f"recall_at_{k}") or 0.0)
        baseline_labels = {str(item.get("label")) for item in (baseline.get("ranked") or [])[:k]}
        for variant in group_cases:
            if variant is baseline:
                continue
            variant_metrics = compute_retrieval_metrics([variant], k=k)
            variant_recall = float(variant_metrics.get(f"recall_at_{k}") or 0.0)
            variant_labels = {str(item.get("label")) for item in (variant.get("ranked") or [])[:k]}
            union = baseline_labels | variant_labels
            overlap = len(baseline_labels & variant_labels) / len(union) if union else 1.0
            delta = variant_recall - baseline_recall
            deltas.append(delta)
            overlaps.append(overlap)
            if delta < -tolerance:
                degradations += 1
            if variant.get("expected_invariant", True):
                invariant_total += 1
                invariant_passes += int(delta >= -tolerance)
    return {
        "case_count": len(cases),
        "group_count": len(groups),
        "invariance_rate": round(invariant_passes / invariant_total, 6) if invariant_total else None,
        "mean_recall_delta": round(statistics.fmean(deltas), 6) if deltas else 0.0,
        "mean_top_k_overlap": round(statistics.fmean(overlaps), 6) if overlaps else 1.0,
        "degradation_rate": round(degradations / len(deltas), 6) if deltas else 0.0,
        "tolerance": tolerance,
        "warnings": [],
    }


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
