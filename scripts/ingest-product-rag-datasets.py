#!/usr/bin/env python3
"""Ingest normalized product records through the production KnowledgeService.

The default source is the four small evaluation snapshots, which makes a
repeatable local index practical on CPU.  Pass ``--source corpus`` and an
optional ``--max-documents`` value when a larger offline index is desired.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from competition.knowledge_index import KnowledgeIndex
from competition.knowledge_service import KnowledgeService

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = PROJECT_ROOT / ".ci-agent/datasets/normalized/product-rag-v1"
DEFAULT_INDEX = PROJECT_ROOT / ".ci-agent/datasets/index-runs/product-rag-v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest normalized product RAG records")
    parser.add_argument("--normalized-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--index-root", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--source", choices=("evaluations", "corpus"), default="evaluations")
    parser.add_argument("--max-documents", type=int, default=0, help="0 means all records in the selected source")
    parser.add_argument("--user-id", default="product-rag-eval")
    parser.add_argument("--collection", default="product_rag_v1")
    parser.add_argument("--warmup", action="store_true")
    return parser.parse_args()


def _records(root: Path, source: str) -> list[dict[str, Any]]:
    paths = sorted((root / "corpus").glob("*.jsonl")) if source == "corpus" else sorted((root / "evaluations").glob("*.json"))
    records: dict[str, dict[str, Any]] = {}
    for path in paths:
        if path.suffix == ".jsonl":
            with path.open(encoding="utf-8") as handle:
                values = (json.loads(line) for line in handle if line.strip())
                for value in values:
                    if isinstance(value, dict) and value.get("id"):
                        records.setdefault(str(value["id"]), value)
        else:
            payload = json.loads(path.read_text(encoding="utf-8"))
            for value in payload.get("documents") or []:
                if isinstance(value, dict) and value.get("id"):
                    records.setdefault(str(value["id"]), value)
    return list(records.values())


def _metadata(record: dict[str, Any]) -> dict[str, Any]:
    value = dict(record.get("metadata") or {})
    value.update({
        "canonical_id": record.get("id"),
        "dataset": record.get("dataset"),
        "record_kind": record.get("kind"),
        "license": record.get("license"),
        "evaluation_only": True,
        "images_excluded": True,
        "original_source_uri": record.get("source_uri") or "",
    })
    return value


def _record_source_uri(record: dict[str, Any]) -> str:
    """Keep provenance while making shared dataset URLs unique per record."""
    base = str(record.get("source_uri") or "product-dataset://unknown")
    return f"{base}#record-{record.get('id', '')}"


def main() -> int:
    args = parse_args()
    records = _records(args.normalized_root, args.source)
    if args.max_documents > 0:
        records = records[: args.max_documents]
    if not records:
        raise SystemExit(f"No normalized records found below {args.normalized_root}")
    args.index_root.mkdir(parents=True, exist_ok=True)
    index = KnowledgeIndex(path=args.index_root / "qdrant", collection=args.collection)
    service = KnowledgeService(db_path=args.index_root / "competition.db", root=args.index_root / "knowledge", index=index)
    started = datetime.now(UTC)
    failures: list[dict[str, Any]] = []
    completed = unchanged = 0
    try:
        if args.warmup:
            warmup = service.warmup()
        else:
            warmup = {"status": "skipped"}
        for record in records:
            side = (record.get("metadata") or {}).get("side") or (record.get("metadata") or {}).get("table")
            registration = service.register_bytes(
                user_id=args.user_id,
                filename=f"{record['id']}.md",
                data=str(record["text"]).encode("utf-8"),
                title=str(record.get("title") or record["id"]),
                media_type="text/markdown",
                source_type="product_dataset",
                source_uri=_record_source_uri(record),
                product=str(side or record.get("brand") or record.get("category") or ""),
                # The isolated benchmark shares one index across datasets. Keep
                # dataset identity in the indexed filter field so each query
                # evaluates only against its declared corpus; the source
                # category remains in canonical metadata.
                dimension=str(record.get("dataset") or "product-rag-v1"),
                market_scope="Global / unspecified",
                authority_tier="third_party" if record.get("kind") == "review" else "structured_fact",
                metadata=_metadata(record),
                approval_status="approved",
            )
            if registration.get("unchanged"):
                unchanged += 1
                continue
            job = service.process_job(registration["job"]["job_id"])
            if job.get("status") != "completed":
                failures.append({"id": record.get("id"), "error": job.get("error") or "ingestion failed"})
            else:
                completed += 1
    finally:
        service.close()
    report = {
        "schema_version": "product-rag-ingest-report.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "started_at": started.isoformat(),
        "normalized_root": str(args.normalized_root),
        "index_root": str(args.index_root),
        "source": args.source,
        "collection": args.collection,
        "user_id": args.user_id,
        "requested_records": len(records),
        "indexed_records": completed,
        "unchanged_records": unchanged,
        "failed_records": len(failures),
        "failures": failures[:100],
        "warmup": warmup,
    }
    report_path = args.index_root / "ingest-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
