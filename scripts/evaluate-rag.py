#!/usr/bin/env python3
"""Run the versioned local RAG golden-set evaluation without touching runtime data."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

os.environ.setdefault("ORT_DISABLE_TELEMETRY", "true")

from qdrant_client import QdrantClient

from competition.knowledge_eval import (
    EvaluationThresholds,
    check_thresholds,
    compute_governance_metrics,
    compute_memory_metrics,
    compute_planning_metrics,
    compute_retrieval_metrics,
    compute_verification_metrics,
    evaluate_governance_cases,
    evaluate_memory_cases,
    evaluate_queries,
    evaluate_verification_cases,
)
from competition.knowledge_index import KnowledgeIndex
from competition.knowledge_service import KnowledgeService

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = PROJECT_ROOT / "evals/rag/real-v1.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate local hybrid RAG retrieval on a golden dataset")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when quality thresholds fail",
    )
    return parser.parse_args()


def validate_dataset(dataset: dict, path: Path) -> None:
    documents = dataset.get("documents") or []
    document_ids = [str(item.get("id") or "") for item in documents]
    if not documents or any(not value for value in document_ids) or len(document_ids) != len(set(document_ids)):
        raise ValueError(f"{path}: documents must have unique non-empty IDs")
    known = set(document_ids)
    governance_cases = dataset.get("governance_cases") or []
    governance_ids = [str(item.get("id") or "") for item in governance_cases]
    if any(not value for value in governance_ids) or len(governance_ids) != len(set(governance_ids)):
        raise ValueError(f"{path}: governance cases must have unique non-empty IDs")
    invalid_statuses = {str(item.get("expected_status") or "") for item in governance_cases} - {"approved", "pending"}
    if invalid_statuses:
        raise ValueError(f"{path}: governance cases use invalid expected statuses: {sorted(invalid_statuses)}")
    memory_documents = dataset.get("memory_documents") or []
    memory_id_values = [str(item.get("id") or "") for item in memory_documents]
    if any(not value for value in memory_id_values) or len(memory_id_values) != len(set(memory_id_values)):
        raise ValueError(f"{path}: memory documents must have unique non-empty IDs")
    memory_thread_values = [str(item.get("thread_id") or "") for item in memory_documents]
    if any(not value for value in memory_thread_values) or len(memory_thread_values) != len(set(memory_thread_values)):
        raise ValueError(f"{path}: memory documents must have unique non-empty thread IDs")
    memory_ids = set(memory_id_values)
    memory_threads = set(memory_thread_values)
    for query in dataset.get("queries") or []:
        unknown = set(query.get("relevant") or []) - known
        if unknown:
            raise ValueError(f"{path}: query {query.get('id')} references unknown documents: {sorted(unknown)}")
    for case in dataset.get("verification_cases") or []:
        referenced = {
            *case.get("cited_documents", []),
            *case.get("expected_supporting", []),
            *case.get("expected_contradicting", []),
        }
        unknown = referenced - known
        if unknown:
            raise ValueError(f"{path}: verification case {case.get('id')} references unknown documents: {sorted(unknown)}")
    for case in dataset.get("memory_cases") or []:
        unknown = set(case.get("relevant") or []) - memory_ids
        if unknown:
            raise ValueError(f"{path}: memory case {case.get('id')} references unknown reports: {sorted(unknown)}")
        unknown_threads = set(case.get("forbidden") or []) - memory_threads
        if unknown_threads:
            raise ValueError(f"{path}: memory case {case.get('id')} references unknown forbidden threads: {sorted(unknown_threads)}")
        current_thread = str(case.get("current_thread_id") or "")
        if not current_thread or current_thread not in set(case.get("forbidden") or []):
            raise ValueError(f"{path}: memory case {case.get('id')} must forbid its non-empty current_thread_id")
    if (dataset.get("curation") or {}).get("review_status") == "human_curated":
        for document in documents:
            if not str(document.get("source_url") or "").startswith(("http://", "https://")):
                raise ValueError(f"{path}: curated document {document['id']} is missing a public source URL")
            if not document.get("captured_at"):
                raise ValueError(f"{path}: curated document {document['id']} is missing captured_at")


def main() -> int:
    args = parse_args()
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    validate_dataset(dataset, args.dataset)
    k = int(dataset.get("k", 5))
    user_id = "rag-evaluation"
    with tempfile.TemporaryDirectory(prefix="ci-agent-rag-eval-") as temporary:
        root = Path(temporary)
        index = KnowledgeIndex(
            client=QdrantClient(location=":memory:"),
            collection="competition_knowledge_evaluation",
        )
        service = KnowledgeService(db_path=root / "evaluation.db", root=root / "knowledge", index=index)
        warmup = service.warmup()
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
        cases = evaluate_queries(
            service,
            dataset.get("queries", []),
            user_id=user_id,
            k=k,
            document_labels=document_labels,
        )
        verification_cases = evaluate_verification_cases(
            service,
            dataset.get("verification_cases", []),
            user_id=user_id,
            document_ids=document_ids,
        )
        governance_cases = evaluate_governance_cases(dataset.get("governance_cases", []))
        memory_cases = evaluate_memory_cases(
            service,
            dataset.get("memory_cases", []),
            user_id=user_id,
            document_labels=memory_labels,
        )
        metrics = compute_retrieval_metrics(cases, k=k)
        metrics["planning"] = compute_planning_metrics(cases)
        metrics["verification"] = compute_verification_metrics(verification_cases)
        metrics["governance"] = compute_governance_metrics(governance_cases)
        metrics["memory"] = compute_memory_metrics(memory_cases, k=k)
        configured = dataset.get("thresholds") or {}
        thresholds = EvaluationThresholds(
            recall_at_k=float(configured.get("recall_at_k", 0.8)),
            mrr=float(configured.get("mrr", 0.7)),
            ndcg_at_k=float(configured.get("ndcg_at_k", 0.75)),
            abstention_accuracy=float(configured.get("abstention_accuracy", 1.0)),
            traceability_rate=float(configured.get("traceability_rate", 1.0)),
            max_p95_latency_ms=configured.get("max_p95_latency_ms"),
            claim_status_accuracy=float(configured.get("claim_status_accuracy", 0.8)),
            contradiction_recall=float(configured.get("contradiction_recall", 0.8)),
            citation_precision=float(configured.get("citation_precision", 0.8)),
            numeric_consistency_accuracy=float(configured.get("numeric_consistency_accuracy", 0.8)),
            groundedness=float(configured.get("groundedness", 0.4)),
            query_route_accuracy=float(configured.get("query_route_accuracy", 0.9)),
            decomposition_coverage=float(configured.get("decomposition_coverage", 0.8)),
            governance_accuracy=float(configured.get("governance_accuracy", 0.9)),
            quarantine_recall=float(configured.get("quarantine_recall", 1.0)),
            memory_recall_at_k=float(configured.get("memory_recall_at_k", 0.8)),
            memory_isolation_rate=float(configured.get("memory_isolation_rate", 1.0)),
            current_thread_exclusion_rate=float(configured.get("current_thread_exclusion_rate", 1.0)),
        )
        failures = check_thresholds(metrics, thresholds, k=k)
        report = {
            "dataset": dataset.get("name", args.dataset.stem),
            "dataset_path": str(args.dataset),
            "generated_at": datetime.now(UTC).isoformat(),
            "warmup": warmup,
            "metrics": metrics,
            "threshold_failures": failures,
            "cases": cases,
            "verification_cases": verification_cases,
            "governance_cases": governance_cases,
            "memory_cases": memory_cases,
        }
        output = args.output or (PROJECT_ROOT / ".ci-agent/evaluations" / f"rag-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        service.close()
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(f"Evaluation report: {output}")
    if failures:
        print("Threshold failures:")
        for failure in failures:
            print(f"- {failure}")
    return 1 if args.strict and failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
