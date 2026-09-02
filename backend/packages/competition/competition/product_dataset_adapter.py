"""Adapters for public product-analysis datasets.

The adapters intentionally produce a small, stable interchange schema before
anything is sent to the knowledge service.  Dataset-specific fields stay in
``metadata`` while the indexable text and provenance fields have one contract.
This module has no database, model, or Qdrant dependency and is safe to use in
offline preparation jobs and unit tests.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "product-rag-record.v1"
_WHITESPACE = re.compile(r"\s+")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MAX_TEXT_CHARS = 12000


def clean_text(value: Any, *, max_chars: int = _MAX_TEXT_CHARS) -> str:
    """Normalize arbitrary dataset text without inventing content."""
    if value is None:
        return ""
    text = _CONTROL.sub(" ", str(value).replace("\r", "\n"))
    text = _WHITESPACE.sub(" ", text).strip()
    return text[:max(1, int(max_chars))]


def stable_id(*parts: Any) -> str:
    """Create a deterministic, source-independent suffix for a record."""
    payload = "|".join(clean_text(part).casefold() for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def timestamp_iso(value: Any) -> str | None:
    """Convert an Amazon millisecond timestamp to an ISO-8601 value."""
    if value in (None, ""):
        return None
    try:
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000
        return datetime.fromtimestamp(number, tz=UTC).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


@dataclass(frozen=True)
class ProductRagRecord:
    """Canonical document or evaluation record produced by an adapter."""

    id: str
    dataset: str
    kind: str
    title: str
    text: str
    product_id: str = ""
    query: str = ""
    label: int | str | None = None
    brand: str = ""
    category: str = ""
    source_uri: str = ""
    license: str = "review-needed"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["schema_version"] = SCHEMA_VERSION
        return value


def normalize_record(
    *,
    record_id: str,
    dataset: str,
    kind: str,
    title: Any,
    text: Any,
    product_id: Any = "",
    query: Any = "",
    label: int | str | None = None,
    brand: Any = "",
    category: Any = "",
    source_uri: Any = "",
    license: Any = "review-needed",
    metadata: dict[str, Any] | None = None,
) -> ProductRagRecord | None:
    """Apply common validation and cleaning to one source record."""
    if kind not in {"product", "review", "matching_pair", "query_judgment"}:
        raise ValueError(f"Unsupported product RAG record kind: {kind}")
    clean_title = clean_text(title, max_chars=1000)
    clean_body = clean_text(text)
    if not clean_body:
        return None
    if not clean_title:
        clean_title = clean_body[:160]
    return ProductRagRecord(
        id=clean_text(record_id, max_chars=180),
        dataset=clean_text(dataset, max_chars=100),
        kind=kind,
        title=clean_title,
        text=clean_body,
        product_id=clean_text(product_id, max_chars=180),
        query=clean_text(query, max_chars=2000),
        label=label,
        brand=clean_text(brand, max_chars=300),
        category=clean_text(category, max_chars=300),
        source_uri=clean_text(source_uri, max_chars=1000),
        license=clean_text(license, max_chars=300) or "review-needed",
        metadata=dict(metadata or {}),
    )


def _read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
            if isinstance(value, dict):
                yield value


def _read_csv(path: Path) -> Iterator[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        yield from csv.DictReader(handle)


def _limit(values: Iterable[ProductRagRecord], limit: int | None) -> Iterator[ProductRagRecord]:
    count = 0
    for value in values:
        if limit is not None and limit > 0 and count >= limit:
            break
        yield value
        count += 1


def iter_esci_products(path: str | Path, *, max_pairs: int | None = None) -> Iterator[ProductRagRecord]:
    """Convert ESCI query/product rows to deduplicated product documents."""
    seen: set[str] = set()
    for row in _limit((_esci_row(item) for item in _read_jsonl(Path(path))), max_pairs):
        if row is None or row.id in seen:
            continue
        seen.add(row.id)
        yield row


def _esci_row(row: dict[str, Any]) -> ProductRagRecord | None:
    product_id = clean_text(row.get("product_id"))
    title = clean_text(row.get("product_title"))
    if not product_id or not title:
        return None
    return normalize_record(
        record_id=f"esci-v1-product-{product_id}",
        dataset="esci-v1",
        kind="product",
        title=title,
        text=f"Product title: {title}",
        product_id=product_id,
        category="search product",
        source_uri="https://github.com/amazon-science/esci-data",
        license="ESCI research dataset; verify upstream terms",
        metadata={"split": row.get("split", ""), "esci_label": row.get("esci_label", "")},
    )


def iter_esci_judgments(path: str | Path, *, max_queries: int | None = 128) -> list[dict[str, Any]]:
    """Build deterministic graded relevance judgments from ESCI rows."""
    grouped: dict[str, dict[str, int]] = {}
    for row in _read_jsonl(Path(path)):
        query = clean_text(row.get("query"), max_chars=2000)
        product_id = clean_text(row.get("product_id"))
        if not query or not product_id:
            continue
        label = clean_text(row.get("esci_label"))
        grade = {"E": 3, "S": 2, "C": 1, "I": 0}.get(label, _safe_int(row.get("relevance_label")))
        grouped.setdefault(query, {})[f"esci-v1-product-{product_id}"] = grade
    output: list[dict[str, Any]] = []
    for index, (query, labels) in enumerate(sorted(grouped.items())):
        relevant = [item for item, grade in sorted(labels.items()) if grade > 0]
        if not relevant:
            continue
        output.append({
            "id": f"esci-query-{index:05d}",
            "query": query,
            "relevant": relevant,
            "relevance": labels,
            "category": "product_search",
            "difficulty": "medium",
            "split": "offline",
            "dataset": "esci-v1",
        })
        if max_queries and len(output) >= max_queries:
            break
    return output


def iter_abt_buy_products(table_a: str | Path, table_b: str | Path) -> Iterator[ProductRagRecord]:
    for side, path in (("A", Path(table_a)), ("B", Path(table_b))):
        for row in _read_csv(path):
            item_id = clean_text(row.get("id"))
            title = clean_text(row.get("name"))
            description = clean_text(row.get("description"))
            body = "\n".join(part for part in (f"Product name: {title}", f"Description: {description}", f"Price: {clean_text(row.get('price'))}") if part.split(": ", 1)[-1])
            record = normalize_record(
                record_id=f"abt-buy-v1-{side.lower()}-{item_id}", dataset="abt-buy-v1", kind="product",
                title=title, text=body, product_id=item_id, category="entity matching",
                source_uri="https://github.com/anhaidgroup/deepmatcher/blob/master/Datasets/Structured/Abt-Buy",
                license="Abt-Buy research dataset; verify upstream terms", metadata={"table": side},
            )
            if record:
                yield record


def iter_abt_buy_pairs(path: str | Path, *, max_pairs: int | None = None) -> Iterator[dict[str, Any]]:
    for index, row in enumerate(_limit(_read_csv(Path(path)), max_pairs)):
        left, right = clean_text(row.get("ltable_id")), clean_text(row.get("rtable_id"))
        if not left or not right:
            continue
        yield {"id": f"abt-pair-{Path(path).stem}-{index:05d}", "left_id": f"abt-buy-v1-a-{left}", "right_id": f"abt-buy-v1-b-{right}", "label": _safe_int(row.get("label")), "dataset": "abt-buy-v1"}


def iter_amazon_google_products(paths: Iterable[str | Path]) -> Iterator[ProductRagRecord]:
    seen: set[str] = set()
    for path_value in paths:
        for row in _read_csv(Path(path_value)):
            for side in ("left", "right"):
                item_id = clean_text(row.get(f"{side}_id"))
                title = clean_text(row.get(f"{side}_title"))
                if not item_id or not title:
                    continue
                record_id = f"amazon-google-v1-{side}-{item_id}"
                if record_id in seen:
                    continue
                seen.add(record_id)
                manufacturer = clean_text(row.get(f"{side}_manufacturer"))
                price = clean_text(row.get(f"{side}_price"))
                body = "\n".join(part for part in (f"Product title: {title}", f"Manufacturer: {manufacturer}", f"Price: {price}") if part.split(": ", 1)[-1])
                record = normalize_record(
                    record_id=record_id, dataset="amazon-google-v1", kind="product", title=title, text=body,
                    product_id=item_id, brand=manufacturer, category="entity matching",
                    source_uri="https://github.com/anhaidgroup/deepmatcher/blob/master/Datasets/Structured/Amazon-Google",
                    license="Amazon-Google research dataset; verify upstream terms", metadata={"side": side},
                )
                if record:
                    yield record


def iter_amazon_google_pairs(path: str | Path, *, max_pairs: int | None = None) -> Iterator[dict[str, Any]]:
    for index, row in enumerate(_limit(_read_csv(Path(path)), max_pairs)):
        left, right = clean_text(row.get("left_id")), clean_text(row.get("right_id"))
        if not left or not right:
            continue
        yield {"id": f"amazon-google-pair-{Path(path).stem}-{index:05d}", "left_id": f"amazon-google-v1-left-{left}", "right_id": f"amazon-google-v1-right-{right}", "label": _safe_int(row.get("label")), "dataset": "amazon-google-v1"}


def iter_review_documents(path: str | Path, *, max_records: int | None = None) -> Iterator[ProductRagRecord]:
    dataset_category = Path(path).stem
    for index, row in enumerate(_limit(_read_jsonl(Path(path)), max_records)):
        asin = clean_text(row.get("parent_asin") or row.get("asin"))
        title = clean_text(row.get("title")) or "Customer review"
        review = clean_text(row.get("text"))
        if not review:
            continue
        body = f"Review title: {title}\nReview: {review}\nRating: {row.get('rating', '')}"
        record = normalize_record(
            record_id=f"amazon-reviews-v1-{dataset_category.casefold()}-{stable_id(asin, title, review, index)}",
            dataset="amazon-reviews-v1", kind="review", title=title, text=body, product_id=asin,
            category=dataset_category, source_uri="https://amazon-reviews-2023.github.io/",
            license="Amazon Reviews 2023 research dataset; verify upstream terms",
            metadata={"rating": row.get("rating"), "verified_purchase": bool(row.get("verified_purchase")), "helpful_vote": _safe_int(row.get("helpful_vote")), "timestamp": timestamp_iso(row.get("timestamp"))},
        )
        if record:
            yield record


def iter_abo_products(path: str | Path, *, max_records: int | None = None) -> Iterator[ProductRagRecord]:
    for row in _limit(_read_jsonl(Path(path)), max_records):
        item_id = clean_text(row.get("item_id"))
        title = clean_text(row.get("title"))
        if not item_id or not title:
            continue
        product_type = clean_text(row.get("product_type_readable") or row.get("product_type"))
        hierarchy = clean_text(row.get("hierarchy_path"))
        body = "\n".join(part for part in (f"Product title: {title}", f"Brand: {clean_text(row.get('brand'))}", f"Product type: {product_type}", f"Category path: {hierarchy}") if part.split(": ", 1)[-1])
        record = normalize_record(
            record_id=f"abo-v1-product-{item_id}", dataset="abo-v1", kind="product", title=title, text=body,
            product_id=item_id, brand=row.get("brand"), category=product_type,
            source_uri="https://amazon-berkeley-objects.s3.amazonaws.com/", license="ABO research dataset; verify upstream terms",
            metadata={"country": clean_text(row.get("country")), "marketplace": clean_text(row.get("marketplace")), "domain_name": clean_text(row.get("domain_name")), "images_excluded": True},
        )
        if record:
            yield record


def deduplicate_records(records: Iterable[ProductRagRecord]) -> tuple[list[ProductRagRecord], dict[str, int]]:
    """Remove duplicate IDs and texts while retaining deterministic order."""
    seen_ids: set[str] = set()
    seen_text: set[str] = set()
    output: list[ProductRagRecord] = []
    duplicate_ids = duplicate_texts = 0
    for record in records:
        if not record.id or record.id in seen_ids:
            duplicate_ids += 1
            continue
        text_key = record.text.casefold()
        if text_key in seen_text:
            duplicate_texts += 1
            continue
        seen_ids.add(record.id)
        seen_text.add(text_key)
        output.append(record)
    return output, {"duplicate_id_count": duplicate_ids, "duplicate_text_count": duplicate_texts}


def write_jsonl(path: str | Path, records: Iterable[ProductRagRecord | dict[str, Any]]) -> int:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with destination.open("w", encoding="utf-8") as handle:
        for record in records:
            value = record.to_dict() if isinstance(record, ProductRagRecord) else dict(record)
            handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count
