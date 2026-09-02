#!/usr/bin/env python3
"""Run the configured RAG ablation matrix on an isolated temporary store.

This runner deliberately keeps experiment data out of the application
knowledge base.  It exercises the same KnowledgeService retrieval contract as
production while changing only the explicitly declared strategy switches.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

os.environ.setdefault("ORT_DISABLE_TELEMETRY", "true")

from qdrant_client import QdrantClient

from competition.knowledge_eval import (
    EvaluationThresholds,
    aggregate_query_metrics,
    bootstrap_metric_intervals,
    check_thresholds,
    compare_metric_sets,
    compute_answer_quality_metrics,
    compute_dataset_drift,
    compute_dataset_quality_metrics,
    compute_governance_metrics,
    compute_graph_metrics,
    compute_memory_metrics,
    compute_planning_metrics,
    compute_retrieval_metrics,
    compute_runtime_metrics,
    compute_robustness_metrics,
    compute_verification_metrics,
    evaluate_governance_cases,
    evaluate_graph_cases,
    evaluate_memory_cases,
    evaluate_queries,
    evaluate_verification_cases,
    evaluation_coverage,
)
from competition.knowledge_index import KnowledgeIndex
from competition.knowledge_service import KnowledgeService

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "evals/rag/experiments-v1.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run reproducible RAG retrieval experiments")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--strict", action="store_true", help="Fail when the candidate quality gate fails")
    return parser.parse_args()


def _thresholds(dataset: dict[str, Any]) -> EvaluationThresholds:
    configured = dataset.get("thresholds") or {}
    fields = EvaluationThresholds.__dataclass_fields__
    values = {key: configured[key] for key in fields if key in configured}
    return EvaluationThresholds(**values)


def validate_experiment_config(config: dict[str, Any], path: Path) -> None:
    if config.get("schema_version") != "rag-experiments.v1":
        raise ValueError(f"{path}: unsupported experiment schema")
    experiments = config.get("experiments") or []
    ids = [str(item.get("id") or "") for item in experiments]
    if not ids or any(not item for item in ids) or len(ids) != len(set(ids)):
        raise ValueError(f"{path}: experiments must have unique non-empty IDs")
    if config.get("baseline") not in ids:
        raise ValueError(f"{path}: baseline must reference an experiment ID")
    if config.get("drift_baseline_dataset") and not isinstance(config["drift_baseline_dataset"], str):
        raise ValueError(f"{path}: drift_baseline_dataset must be a relative path")
    drift_policy = config.get("drift_policy") or {}
    if "max_category_shift" in drift_policy and not 0 <= float(drift_policy["max_category_shift"]) <= 1:
        raise ValueError(f"{path}: drift_policy.max_category_shift must be between 0 and 1")
    for item in experiments:
        mode = item.get("retrieval_mode")
        if mode not in {"none", "dense", "sparse", "hybrid", "auto"}:
            raise ValueError(f"{path}: {item.get('id')} has invalid retrieval_mode")
        if not isinstance(item.get("rerank", False), bool) or not isinstance(item.get("graph", False), bool):
            raise ValueError(f"{path}: {item.get('id')} rerank/graph must be booleans")


def validate_dataset(dataset: dict[str, Any], path: Path) -> None:
    documents = dataset.get("documents") or []
    ids = [str(item.get("id") or "") for item in documents]
    if not ids or any(not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError(f"{path}: documents must have unique non-empty IDs")
    known = set(ids) | {
        str(item.get("id") or "") for item in dataset.get("graph_documents") or [] if item.get("id")
    }
    queries = list(dataset.get("queries") or [])
    robustness_queries = list(dataset.get("robustness_queries") or [])
    query_ids = [str(item.get("id") or "") for item in queries]
    if not query_ids or any(not value for value in query_ids) or len(query_ids) != len(set(query_ids)):
        raise ValueError(f"{path}: queries must have unique non-empty IDs")
    allowed_categories = {"fact", "comparison", "temporal", "multi_hop", "no_answer"}
    if str(dataset.get("name", "")).endswith("-v2"):
        for query in queries:
            if query.get("category") not in allowed_categories:
                raise ValueError(f"{path}: query {query.get('id')} has invalid or missing category")
            if not query.get("difficulty") or not query.get("split"):
                raise ValueError(f"{path}: query {query.get('id')} is missing difficulty or split")
    for query in queries:
        unknown = set(query.get("relevant") or []) - known
        if unknown:
            raise ValueError(f"{path}: query {query.get('id')} references unknown documents: {sorted(unknown)}")
    robustness_ids = [str(item.get("id") or "") for item in robustness_queries]
    if len(robustness_ids) != len(set(robustness_ids)) or any(not value for value in robustness_ids):
        raise ValueError(f"{path}: robustness_queries must have unique non-empty IDs")
    for query in robustness_queries:
        if not query.get("robustness_group"):
            raise ValueError(f"{path}: robustness query {query.get('id')} is missing robustness_group")
        if not all(query.get(field) for field in ("query", "category", "difficulty", "split")):
            raise ValueError(f"{path}: robustness query {query.get('id')} is missing metadata")
        unknown = set(query.get("relevant") or []) - known
        if unknown:
            raise ValueError(f"{path}: robustness query {query.get('id')} references unknown documents: {sorted(unknown)}")
    policy = dataset.get("evaluation_policy") or {}
    required = set(policy.get("required_categories") or [])
    present = {query.get("category") for query in queries}
    if required - present:
        raise ValueError(f"{path}: required categories missing: {sorted(required - present)}")


def _ingest_dataset(dataset: dict[str, Any], root: Path) -> tuple[KnowledgeService, dict[str, str], dict[str, str]]:
    index = KnowledgeIndex(
        client=QdrantClient(location=":memory:"),
        collection="competition_knowledge_experiment",
    )
    service = KnowledgeService(db_path=root / "evaluation.db", root=root / "knowledge", index=index)
    user_id = "rag-experiment"
    document_labels: dict[str, str] = {}
    document_ids: dict[str, str] = {}
    for document in dataset.get("documents", []):
        registration = service.register_bytes(
            user_id=user_id,
            filename=document["filename"],
            data=document["text"].encode("utf-8"),
            title=document.get("title", ""),
            product=document.get("product", ""),
            dimension=document.get("dimension", ""),
            authority_tier=document.get("authority_tier", "third_party"),
            published_at=document.get("published_at"),
            observed_at=document.get("captured_at"),
            source_uri=document.get("source_url", ""),
            metadata={"evaluation_id": document["id"]},
        )
        job = service.process_job(registration["job"]["job_id"])
        if job["status"] != "completed":
            raise RuntimeError(f"Failed to index evaluation document {document['id']}: {job.get('error')}")
        document_labels[registration["document"]["document_id"]] = document["id"]
        document_ids[document["id"]] = registration["document"]["document_id"]
    memory_labels: dict[str, str] = {}
    for report in dataset.get("memory_documents") or []:
        registration = service.register_report_snapshot(
            user_id=user_id,
            thread_id=report["thread_id"],
            version=int(report.get("version") or 1),
            report_data=report["report_data"],
            analysis_brief=report.get("analysis_brief") or {},
            generation_id=report.get("generation_id"),
        )
        job = service.process_job(registration["job"]["job_id"])
        if job["status"] != "completed":
            raise RuntimeError(f"Failed to index evaluation report {report['id']}: {job.get('error')}")
        memory_labels[registration["document"]["document_id"]] = report["id"]
    for graph_document in dataset.get("graph_documents") or []:
        for version in graph_document.get("versions") or []:
            registration = service.register_bytes(
                user_id=user_id,
                filename=graph_document["filename"],
                data=str(version["text"]).encode("utf-8"),
                title=graph_document.get("title") or graph_document["filename"],
                source_type=graph_document.get("source_type") or "upload",
                source_uri=graph_document["source_url"],
                product=graph_document["product"],
                dimension=graph_document["dimension"],
                authority_tier=graph_document.get("authority_tier") or "primary",
                published_at=version.get("published_at"),
                observed_at=version.get("observed_at"),
                metadata={"evaluation_id": graph_document["id"]},
            )
            job = service.process_job(registration["job"]["job_id"])
            if job["status"] != "completed":
                raise RuntimeError(f"Failed to index graph document {graph_document['id']}: {job.get('error')}")
            graph_document_id = registration["document"]["document_id"]
            document_labels[graph_document_id] = graph_document["id"]
            document_ids[graph_document["id"]] = graph_document_id
    return service, document_labels, document_ids | {"__memory_labels__": memory_labels}


def _no_rag_cases(queries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": item.get("id"),
            "query": item.get("query", ""),
            "relevant": list(item.get("relevant") or []),
            "ranked": [],
            "latency_ms": 0.0,
            "expected_route": item.get("expected_route"),
            "actual_route": None,
            "required_step_purposes": list(item.get("required_step_purposes") or []),
            "actual_step_purposes": [],
            "actual_step_count": 0,
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
        for item in queries
    ]


def _run_strategy(
    service: KnowledgeService,
    dataset: dict[str, Any],
    strategy: dict[str, Any],
    *,
    labels: dict[str, str],
    document_ids: dict[str, str],
    prior_log_count: int = 0,
) -> dict[str, Any]:
    user_id = "rag-experiment"
    if strategy["retrieval_mode"] == "none":
        cases = _no_rag_cases(dataset.get("queries", []))
    else:
        cases = evaluate_queries(
            service,
            dataset.get("queries", []),
            user_id=user_id,
            k=int(dataset.get("k", 5)),
            document_labels=labels,
            retrieval_mode=strategy["retrieval_mode"],
            rerank=bool(strategy.get("rerank", False)),
        )
    k = int(dataset.get("k", 5))
    if strategy["retrieval_mode"] != "none":
        all_logs = service.retrieval_logs(user_id, limit=500)
        retrieval_logs = all_logs[: max(0, len(all_logs) - prior_log_count)]
    else:
        retrieval_logs = []
    metrics: dict[str, Any] = {
        "retrieval": compute_retrieval_metrics(cases, k=k),
        "confidence_intervals": bootstrap_metric_intervals(cases, k=k),
        "planning": compute_planning_metrics(cases),
        "by_group": aggregate_query_metrics(cases, k=k),
        "runtime": compute_runtime_metrics(cases, retrieval_logs),
    }
    robustness_definitions = list(dataset.get("robustness_queries") or [])
    if strategy["retrieval_mode"] == "none":
        robustness_cases = _no_rag_cases(robustness_definitions)
    else:
        robustness_cases = evaluate_queries(
            service,
            robustness_definitions,
            user_id=user_id,
            k=k,
            document_labels=labels,
            retrieval_mode=strategy["retrieval_mode"],
            rerank=bool(strategy.get("rerank", False)),
        )
    metrics["robustness"] = compute_robustness_metrics(robustness_cases, k=k)
    verification_cases = evaluate_verification_cases(
        service, dataset.get("verification_cases", []), user_id=user_id, document_ids=document_ids
    )
    metrics["verification"] = compute_verification_metrics(verification_cases)
    governance_cases = evaluate_governance_cases(dataset.get("governance_cases", []))
    metrics["governance"] = compute_governance_metrics(governance_cases)
    memory_cases = evaluate_memory_cases(
        service,
        dataset.get("memory_cases", []),
        user_id=user_id,
        document_labels=document_ids.get("__memory_labels__", {}),
    )
    metrics["memory"] = compute_memory_metrics(memory_cases, k=k)
    if strategy.get("graph"):
        graph_cases = evaluate_graph_cases(service, dataset.get("graph_cases", []), user_id=user_id)
        metrics["graph"] = compute_graph_metrics(graph_cases, k=k)
    else:
        metrics["graph"] = {"skipped": True, "reason": "graph disabled for this ablation"}
    answer_quality_cases = list(dataset.get("answer_quality_cases") or [])
    if answer_quality_cases:
        metrics["answer_quality"] = compute_answer_quality_metrics(answer_quality_cases)
    coverage = evaluation_coverage(
        cases,
        minimum_cases=int((dataset.get("evaluation_policy") or {}).get("minimum_cases", 0)),
        required_categories=tuple((dataset.get("evaluation_policy") or {}).get("required_categories") or ()),
    )
    thresholds = _thresholds(dataset)
    gate_metrics = {
        **metrics["retrieval"],
        "planning": metrics["planning"],
        "verification": metrics["verification"],
        "governance": metrics["governance"],
        "memory": metrics["memory"],
        "runtime": metrics["runtime"],
    }
    if metrics["robustness"].get("invariance_rate") is not None:
        gate_metrics["robustness"] = metrics["robustness"]
    if "graph" in metrics and not metrics["graph"].get("skipped"):
        gate_metrics["graph"] = metrics["graph"]
    failures = check_thresholds(gate_metrics, thresholds, k=k)
    failures.extend(f"coverage.{warning}" for warning in coverage["warnings"])
    return {
        "strategy": strategy,
        "metrics": metrics,
        "coverage": coverage,
        "threshold_failures": failures,
        "status": "passed" if not failures else "failed",
        "cases": cases,
        "robustness_cases": robustness_cases,
        "verification_cases": verification_cases,
    }


def run_experiments(
    config: dict[str, Any],
    dataset: dict[str, Any],
    *,
    dataset_path: Path,
    baseline_dataset: dict[str, Any] | None = None,
) -> dict[str, Any]:
    strategies = config["experiments"]
    baseline_id = config["baseline"]
    with tempfile.TemporaryDirectory(prefix="ci-agent-rag-experiments-") as temporary:
        results: list[dict[str, Any]] = []
        for strategy in strategies:
            strategy_root = Path(temporary) / str(strategy["id"])
            service, labels, raw_ids = _ingest_dataset(dataset, strategy_root)
            document_ids = {key: value for key, value in raw_ids.items() if key != "__memory_labels__"}
            try:
                prior_log_count = len(service.retrieval_logs("rag-experiment", limit=500))
                results.append(
                    _run_strategy(
                        service,
                        dataset,
                        strategy,
                        labels=labels,
                        document_ids={**document_ids, "__memory_labels__": raw_ids.get("__memory_labels__", {})},
                        prior_log_count=prior_log_count,
                    )
                )
            finally:
                service.close()
    baseline = next(item for item in results if item["strategy"]["id"] == baseline_id)
    comparisons: dict[str, Any] = {}
    for result in results:
        if result["strategy"]["id"] == baseline_id:
            continue
        comparisons[result["strategy"]["id"]] = compare_metric_sets(
            baseline["metrics"]["retrieval"], result["metrics"]["retrieval"]
        )
    return {
        "schema_version": "rag-experiment-report.v1",
        "experiment_config": config,
        "dataset": {
            "name": dataset.get("name"),
            "path": str(dataset_path),
            "schema_version": dataset.get("schema_version"),
            "case_count": len(dataset.get("queries") or []),
            "curation": dataset.get("curation") or {},
            "quality": compute_dataset_quality_metrics(dataset),
            "drift_baseline_path": config.get("drift_baseline_dataset"),
            "drift": compute_dataset_drift(
                dataset,
                baseline_dataset,
                max_category_shift=float((config.get("drift_policy") or {}).get("max_category_shift", 0.25)),
            ),
        },
        "metadata": {
            "generated_at": datetime.now(UTC).isoformat(),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "embedding_model": os.getenv("CI_AGENT_EMBEDDING_MODEL", "configured-local-model"),
            "reranker_model": os.getenv("CI_AGENT_RERANKER_MODEL", "configured-local-model"),
            "concurrency": 1,
            "isolation": "temporary-qdrant-and-sqlite",
        },
        "results": results,
        "comparisons_to_baseline": comparisons,
        "warnings": [
            "Retrieval hit rate is not answer correctness or groundedness.",
            "Relative changes are undefined when the baseline metric is zero.",
        ],
    }


def main() -> int:
    args = parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    validate_experiment_config(config, args.config)
    dataset_path = (PROJECT_ROOT / config["dataset"]).resolve()
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    validate_dataset(dataset, dataset_path)
    baseline_dataset = None
    baseline_path_value = config.get("drift_baseline_dataset")
    if baseline_path_value:
        baseline_path = (PROJECT_ROOT / baseline_path_value).resolve()
        if not baseline_path.exists():
            raise ValueError(f"{args.config}: drift baseline dataset does not exist: {baseline_path_value}")
        baseline_dataset = json.loads(baseline_path.read_text(encoding="utf-8"))
        validate_dataset(baseline_dataset, baseline_path)
    report = run_experiments(config, dataset, dataset_path=dataset_path, baseline_dataset=baseline_dataset)
    output = args.output or PROJECT_ROOT / ".ci-agent/evaluations" / f"rag-experiments-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"dataset": report["dataset"], "results": [{"id": item["strategy"]["id"], "status": item["status"], "retrieval": item["metrics"]["retrieval"]} for item in report["results"]]}, ensure_ascii=False, indent=2))
    print(f"Experiment report: {output}")
    full = next((item for item in report["results"] if item["strategy"]["id"] == "full"), None)
    return 1 if args.strict and full and full["status"] != "passed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
