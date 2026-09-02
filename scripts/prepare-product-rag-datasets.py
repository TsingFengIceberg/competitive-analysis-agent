#!/usr/bin/env python3
"""Normalize the downloaded public product datasets for offline RAG work.

The output is deliberately written below ``.ci-agent`` (which is ignored by
Git).  Raw source files are never modified and no images or reviewer identity
fields are copied into the indexable records.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from competition.product_dataset_adapter import (
    SCHEMA_VERSION,
    ProductRagRecord,
    deduplicate_records,
    iter_abo_products,
    iter_abt_buy_pairs,
    iter_abt_buy_products,
    iter_amazon_google_pairs,
    iter_amazon_google_products,
    iter_esci_judgments,
    iter_esci_products,
    iter_review_documents,
    write_jsonl,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = PROJECT_ROOT / ".ci-agent/datasets/processed"
DEFAULT_OUTPUT = PROJECT_ROOT / ".ci-agent/datasets/normalized/product-rag-v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize product RAG datasets")
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-esci-pairs", type=int, default=50_000)
    parser.add_argument("--max-review-records", type=int, default=25_000)
    parser.add_argument("--max-abo-records", type=int, default=20_000)
    parser.add_argument("--eval-cases", type=int, default=128)
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _record_map(records: list[ProductRagRecord]) -> dict[str, ProductRagRecord]:
    return {record.id: record for record in records}


def _dataset_payload(name: str, documents: list[ProductRagRecord], queries: list[dict[str, Any]], *, description: str) -> dict[str, Any]:
    return {
        "name": name,
        "schema_version": "product-rag-eval.v1",
        "description": description,
        "k": 5,
        "evaluation_policy": {"minimum_cases": max(1, len(queries)), "required_categories": sorted({str(item.get("category")) for item in queries})},
        "documents": [
            record.to_dict()
            | {
                "filename": f"{record.id}.md",
                "source_url": record.source_uri,
                "product": record.product_id or record.brand or record.title,
                "dimension": record.dataset,
                "authority_tier": "structured_fact" if record.kind == "product" else "third_party",
                "captured_at": datetime.now(UTC).isoformat(),
            }
            for record in documents
        ],
        "queries": queries,
        "curation": {"review_status": "generated_from_public_snapshot", "dataset_version": "v1", "license_review_required": True},
    }


def _retrieval_queries(records: list[ProductRagRecord], limit: int) -> list[dict[str, Any]]:
    queries: list[dict[str, Any]] = []
    for index, record in enumerate(records[:limit]):
        queries.append({
            "id": f"product-title-query-{index:04d}",
            "query": record.title,
            "relevant": [record.id],
            "category": "product_search",
            "difficulty": "easy",
            "split": "offline",
            "products": [],
            "dimensions": [record.dataset],
        })
    return queries


def _review_queries(records: list[ProductRagRecord], limit: int) -> list[dict[str, Any]]:
    return [
        {
            "id": f"review-query-{index:04d}",
            "query": f"customer feedback {record.title}",
            "relevant": [record.id],
            "category": "review_evidence",
            "difficulty": "medium",
            "split": "offline",
            "dimensions": [record.dataset],
        }
        for index, record in enumerate(records[:limit])
    ]


def _metadata_queries(records: list[ProductRagRecord], limit: int) -> list[dict[str, Any]]:
    return [
        {
            "id": f"metadata-query-{index:04d}",
            "query": f"product category and brand for {record.title}",
            "relevant": [record.id],
            "category": "product_metadata",
            "difficulty": "easy",
            "split": "offline",
            "dimensions": [record.dataset],
        }
        for index, record in enumerate(records[:limit])
    ]


def _matching_queries(pairs: list[dict[str, Any]], records: dict[str, ProductRagRecord], limit: int) -> list[dict[str, Any]]:
    queries: list[dict[str, Any]] = []
    for index, pair in enumerate(pairs[:limit]):
        left = records.get(str(pair["left_id"]))
        if left is None:
            continue
        label = int(pair.get("label") or 0)
        queries.append({
            "id": str(pair["id"]),
            "query": left.text,
            "relevant": [str(pair["right_id"])] if label else [],
            "candidate_id": str(pair["right_id"]),
            "candidate_product": "B" if str(pair["right_id"]).startswith("abt-buy-v1-b-") else "right",
            "pair_label": label,
            "category": "entity_matching",
            "difficulty": "medium",
            "split": "offline",
            "dimensions": [str(pair["dataset"])],
        })
    return queries


def _balanced_pairs(pairs: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Select a deterministic, class-balanced matching slice when available."""
    positive = [item for item in pairs if int(item.get("label") or 0) == 1]
    negative = [item for item in pairs if int(item.get("label") or 0) == 0]
    each = max(1, limit // 2)
    selected = positive[:each] + negative[:each]
    return sorted(selected, key=lambda item: str(item["id"]))[:limit]


def main() -> int:
    args = parse_args()
    source = args.input_root
    output = args.output_root
    output.mkdir(parents=True, exist_ok=True)
    esci_path = source / "esci-v1/examples.jsonl"
    esci_products, esci_stats = deduplicate_records(iter_esci_products(esci_path, max_pairs=args.max_esci_pairs))
    esci_judgments = iter_esci_judgments(esci_path, max_queries=args.eval_cases)
    abt_products, abt_stats = deduplicate_records(iter_abt_buy_products(source / "abt-buy-v1/tableA.csv", source / "abt-buy-v1/tableB.csv"))
    abt_pairs = _balanced_pairs(list(iter_abt_buy_pairs(source / "abt-buy-v1/train.csv")), args.eval_cases // 2)
    ag_paths = [source / "amazon-google-v1" / name for name in ("amz_goog_train.csv", "amz_goog_validation.csv", "amz_goog_test.csv")]
    ag_products, ag_stats = deduplicate_records(iter_amazon_google_products(ag_paths))
    ag_pairs = _balanced_pairs(list(iter_amazon_google_pairs(ag_paths[0])), args.eval_cases // 2)
    review_products: list[ProductRagRecord] = []
    review_stats: dict[str, int] = {}
    for name in ("All_Beauty.jsonl", "Gift_Cards.jsonl"):
        records, stats = deduplicate_records(iter_review_documents(source / "amazon-reviews-v1" / name, max_records=args.max_review_records))
        review_products.extend(records)
        review_stats[name] = len(records)
    abo_products, abo_stats = deduplicate_records(iter_abo_products(source / "abo-v1/listings.jsonl", max_records=args.max_abo_records))

    groups: dict[str, list[ProductRagRecord]] = {
        "esci": esci_products,
        "abt-buy": abt_products,
        "amazon-google": ag_products,
        "reviews": review_products,
        "abo": abo_products,
    }
    counts: dict[str, Any] = {}
    for name, records in groups.items():
        path = output / "corpus" / f"{name}.jsonl"
        counts[name] = {"records": write_jsonl(path, records), "path": str(path.relative_to(PROJECT_ROOT)), "sha256": _sha256(path)}

    esci_map = _record_map(esci_products)
    selected_esci_ids: list[str] = []
    for judgment in esci_judgments:
        candidate = next((item for item in judgment["relevant"] if item in esci_map), None)
        if candidate and candidate not in selected_esci_ids:
            selected_esci_ids.append(candidate)
        if len(selected_esci_ids) >= max(1, args.eval_cases):
            break
    esci_eval_docs = [esci_map[item] for item in selected_esci_ids]
    selected_set = set(selected_esci_ids)
    esci_eval_queries = []
    for judgment in esci_judgments:
        relevant = [item for item in judgment["relevant"] if item in selected_set]
        if not relevant:
            continue
        esci_eval_queries.append({**judgment, "relevant": relevant, "dimensions": ["esci-v1"]})
        if len(esci_eval_queries) >= max(1, args.eval_cases):
            break
    if not esci_eval_queries:
        esci_eval_queries = _retrieval_queries(esci_eval_docs, args.eval_cases)
    _write_json(output / "evaluations/product-retrieval-v1.json", _dataset_payload("product-retrieval-v1", esci_eval_docs, esci_eval_queries, description="Query-to-product retrieval over ESCI and a deterministic offline sample."))

    matching_map = _record_map(abt_products + ag_products)
    matching_pairs = abt_pairs + ag_pairs
    matching_eval_ids = {item for pair in matching_pairs for item in (pair["left_id"], pair["right_id"]) if item in matching_map}
    matching_eval_docs = [matching_map[item] for item in sorted(matching_eval_ids)]
    _write_json(output / "evaluations/product-matching-v1.json", _dataset_payload("product-matching-v1", matching_eval_docs, _matching_queries(matching_pairs, matching_map, args.eval_cases), description="Class-balanced entity-matching retrieval benchmark over Abt-Buy and Amazon-Google pairs; negative pairs must abstain."))

    review_eval = review_products[: max(1, args.eval_cases)]
    _write_json(output / "evaluations/product-review-analysis-v1.json", _dataset_payload("product-review-analysis-v1", review_eval, _review_queries(review_eval, args.eval_cases), description="Customer-review evidence retrieval sample with identity fields removed."))
    abo_eval = abo_products[: max(1, args.eval_cases)]
    _write_json(output / "evaluations/product-metadata-v1.json", _dataset_payload("product-metadata-v1", abo_eval, _metadata_queries(abo_eval, args.eval_cases), description="Product metadata retrieval sample based on ABO listing text."))

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "input_root": str(source),
        "output_root": str(output),
        "policy": {"images_excluded": True, "reviewer_identity_excluded": True, "text_max_chars": 12000, "evaluation_only": True, "license_review_required": True},
        "counts": counts,
        "deduplication": {"esci": esci_stats, "abt-buy": abt_stats, "amazon-google": ag_stats, "reviews": review_stats, "abo": abo_stats},
        "evaluations": ["product-retrieval-v1", "product-matching-v1", "product-review-analysis-v1", "product-metadata-v1"],
    }
    _write_json(output / "manifest.json", manifest)
    print(json.dumps({"output": str(output), "corpus": counts, "evaluations": manifest["evaluations"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
