#!/usr/bin/env python3
"""Evaluate an isolated product RAG index with a small ablation matrix."""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from competition.knowledge_eval import (
    bootstrap_metric_intervals,
    compare_metric_sets,
    compute_dataset_quality_metrics,
    compute_retrieval_metrics,
    evaluate_queries,
)
from competition.knowledge_index import KnowledgeIndex
from competition.knowledge_repo import KnowledgeRepository
from competition.knowledge_service import KnowledgeService
from competition.knowledge_types import RetrievalFilters

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = PROJECT_ROOT / ".ci-agent/datasets/normalized/product-rag-v1"
DEFAULT_INDEX = PROJECT_ROOT / ".ci-agent/datasets/index-runs/product-rag-v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate product RAG retrieval and ablations")
    parser.add_argument("--normalized-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--index-root", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--dataset", type=Path, help="Evaluation JSON; defaults to product-retrieval-v1")
    parser.add_argument("--all-datasets", action="store_true", help="Evaluate all four generated evaluation snapshots")
    parser.add_argument("--user-id", default="product-rag-eval")
    parser.add_argument("--collection", default="product_rag_v1")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--strategies", default="none,sparse,hybrid,hybrid-rerank")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def _no_rag(queries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": item.get("id"), "query": item.get("query", ""), "relevant": list(item.get("relevant") or []),
            "ranked": [], "latency_ms": 0.0, "category": item.get("category", "uncategorized"),
            "difficulty": item.get("difficulty", "unspecified"), "split": item.get("split", "offline"),
            "answerable": bool(item.get("relevant")), "abstention_expected": bool(item.get("abstention_expected", not item.get("relevant"))),
        }
        for item in queries
    ]


def _labels(db_path: Path, user_id: str) -> dict[str, str]:
    labels: dict[str, str] = {}
    with KnowledgeRepository(db_path=db_path) as repository:
        offset = 0
        while True:
            documents = repository.list_documents(user_id, limit=500, offset=offset)
            for document in documents:
                canonical = (document.get("metadata") or {}).get("canonical_id")
                if canonical:
                    labels[str(document["document_id"])] = str(canonical)
            if len(documents) < 500:
                break
            offset += len(documents)
    return labels


def _evaluate_dataset(service: KnowledgeService, dataset: dict[str, Any], labels: dict[str, str], *, user_id: str, k: int, strategies: list[str]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for strategy in strategies:
        started = time.perf_counter()
        try:
            if dataset.get("name") == "product-matching-v1":
                cases = _matching_cases(service, dataset.get("queries") or [], labels, user_id=user_id, k=k, strategy=strategy)
                metrics = {"matching": _matching_metrics(cases, k=k)}
            elif strategy == "none":
                cases = _no_rag(dataset.get("queries") or [])
                metrics = compute_retrieval_metrics(cases, k=k)
                metrics["confidence_intervals"] = bootstrap_metric_intervals(cases, k=k, iterations=100)
            else:
                mode = "hybrid" if strategy in {"hybrid", "hybrid-rerank"} else strategy
                cases = evaluate_queries(service, dataset.get("queries") or [], user_id=user_id, k=k, document_labels=labels, retrieval_mode=mode, rerank=strategy == "hybrid-rerank")
                metrics = compute_retrieval_metrics(cases, k=k)
                metrics["confidence_intervals"] = bootstrap_metric_intervals(cases, k=k, iterations=100)
            results.append({"id": strategy, "status": "passed", "duration_ms": round((time.perf_counter() - started) * 1000, 3), "metrics": metrics, "cases": cases})
        except Exception as exc:
            results.append({"id": strategy, "status": "failed", "duration_ms": round((time.perf_counter() - started) * 1000, 3), "error": str(exc)[:1000], "metrics": {}})
    baseline = next((item for item in results if item["id"] == "none" and item["status"] == "passed"), None)
    comparisons = {}
    if baseline:
        for item in results:
            if item is baseline or item["status"] != "passed":
                continue
            comparisons[item["id"]] = compare_metric_sets(baseline["metrics"], item["metrics"])
    return {"dataset": dataset.get("name"), "quality": compute_dataset_quality_metrics(dataset), "results": results, "comparisons_to_no_rag": comparisons}


def _matching_cases(service: KnowledgeService, queries: list[dict[str, Any]], labels: dict[str, str], *, user_id: str, k: int, strategy: str) -> list[dict[str, Any]]:
    """Rank the declared candidate side of each labeled entity-matching pair."""
    cases: list[dict[str, Any]] = []
    for item in queries:
        started = time.perf_counter()
        if strategy == "none":
            hits = []
        else:
            mode = "hybrid" if strategy in {"hybrid", "hybrid-rerank"} else strategy
            hits = service.search(
                str(item["query"]), user_id=user_id,
                filters=RetrievalFilters(
                    products=(str(item.get("candidate_product") or ""),),
                    dimensions=tuple(item.get("dimensions") or ()),
                ),
                limit=k, retrieval_mode=mode, rerank=strategy == "hybrid-rerank",
            )
        ranked = [labels.get(hit.document_id, hit.document_id) for hit in hits]
        candidate = str(item.get("candidate_id") or "")
        rank = ranked.index(candidate) + 1 if candidate in ranked else None
        cases.append({
            "id": item.get("id"), "pair_label": int(item.get("pair_label") or 0), "candidate_id": candidate,
            "rank": rank, "ranked": ranked, "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        })
    return cases


def _matching_metrics(cases: list[dict[str, Any]], *, k: int) -> dict[str, Any]:
    positive = [case for case in cases if case["pair_label"] == 1]
    negative = [case for case in cases if case["pair_label"] == 0]
    positive_ranks = [int(case["rank"]) for case in positive if case.get("rank")]
    negative_ranks = [int(case["rank"]) for case in negative if case.get("rank")]
    return {
        "case_count": len(cases),
        "positive_pair_count": len(positive),
        "negative_pair_count": len(negative),
        f"positive_candidate_recall_at_{k}": round(len(positive_ranks) / len(positive), 6) if positive else None,
        "positive_candidate_mrr": round(sum(1.0 / rank for rank in positive_ranks) / len(positive), 6) if positive else None,
        f"negative_candidate_top_{k}_rate": round(sum(rank <= k for rank in negative_ranks) / len(negative), 6) if negative else None,
        "negative_candidate_mrr": round(sum(1.0 / rank for rank in negative_ranks) / len(negative), 6) if negative else None,
        "latency_ms": {"mean": round(sum(float(case["latency_ms"]) for case in cases) / len(cases), 3) if cases else 0.0},
        "interpretation": "Higher positive recall/MRR is better; lower negative candidate top-k rate/MRR is better. This is candidate ranking, not an abstention test.",
    }


def main() -> int:
    args = parse_args()
    if args.all_datasets:
        datasets = sorted((args.normalized_root / "evaluations").glob("*.json"))
    else:
        datasets = [args.dataset or args.normalized_root / "evaluations/product-retrieval-v1.json"]
    payloads = [(path, json.loads(path.read_text(encoding="utf-8"))) for path in datasets]
    index = KnowledgeIndex(path=args.index_root / "qdrant", collection=args.collection)
    service = KnowledgeService(db_path=args.index_root / "competition.db", root=args.index_root / "knowledge", index=index)
    try:
        labels = _labels(args.index_root / "competition.db", args.user_id)
        strategy_ids = [item.strip() for item in args.strategies.split(",") if item.strip()]
        reports = [_evaluate_dataset(service, dataset, labels, user_id=args.user_id, k=max(1, args.k), strategies=strategy_ids) for _, dataset in payloads]
    finally:
        service.close()
    report = {
        "schema_version": "product-rag-evaluation-report.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "index_root": str(args.index_root),
        "datasets": reports,
        "metadata": {"strategies": strategy_ids, "k": max(1, args.k), "offline_public_snapshots": True, "not_a_production_quality_claim": True},
    }
    output = args.output or args.index_root / "evaluation-report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "datasets": [{"name": item["dataset"], "results": [{"id": result["id"], "status": result["status"], "metrics": result.get("metrics", {})} for result in item["results"]]} for item in reports]}, ensure_ascii=False, indent=2))
    failed = any(result["status"] == "failed" for item in reports for result in item["results"])
    return 1 if args.strict and failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
