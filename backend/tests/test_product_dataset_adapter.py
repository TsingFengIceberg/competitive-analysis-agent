"""Tests for deterministic public product dataset normalization."""

from __future__ import annotations

import json
from pathlib import Path

from competition.product_dataset_adapter import (
    deduplicate_records,
    iter_abo_products,
    iter_abt_buy_pairs,
    iter_abt_buy_products,
    iter_amazon_google_pairs,
    iter_amazon_google_products,
    iter_esci_judgments,
    iter_esci_products,
    iter_review_documents,
    normalize_record,
    timestamp_iso,
)


def test_normalize_record_cleans_empty_and_limits_text():
    assert normalize_record(record_id="x", dataset="d", kind="product", title="", text=" \x00 ") is None
    item = normalize_record(record_id="x", dataset="d", kind="product", title=" A  title ", text=" A\n\nbody ", metadata={"evaluation_only": True})
    assert item is not None
    assert item.title == "A title"
    assert item.text == "A body"
    assert item.metadata["evaluation_only"] is True
    assert "schema_version" in item.to_dict()


def test_esci_products_are_deduplicated_and_judgments_are_graded(tmp_path: Path):
    path = tmp_path / "esci.jsonl"
    path.write_text(
        "\n".join([
            json.dumps({"query": "lawn", "product_id": "p1", "product_title": "Mower", "esci_label": "E"}),
            json.dumps({"query": "lawn", "product_id": "p1", "product_title": "Mower", "esci_label": "E"}),
            json.dumps({"query": "lawn", "product_id": "p2", "product_title": "Wheel", "esci_label": "I"}),
        ]) + "\n",
        encoding="utf-8",
    )
    products = list(iter_esci_products(path))
    assert [item.id for item in products] == ["esci-v1-product-p1", "esci-v1-product-p2"]
    judgments = iter_esci_judgments(path)
    assert judgments[0]["relevant"] == ["esci-v1-product-p1"]
    assert judgments[0]["relevance"]["esci-v1-product-p1"] == 3


def test_matching_and_review_adapters_drop_private_identity_fields(tmp_path: Path):
    table_a = tmp_path / "tableA.csv"
    table_b = tmp_path / "tableB.csv"
    table_a.write_text("id,name,description,price\n1,Phone,Good phone,10\n", encoding="utf-8")
    table_b.write_text("id,name,description,price\n2,Phone,Good phone,10\n", encoding="utf-8")
    assert next(iter_abt_buy_products(table_a, table_b)).metadata["table"] == "A"
    pairs = tmp_path / "train.csv"
    pairs.write_text("ltable_id,rtable_id,label\n1,2,1\n", encoding="utf-8")
    pair = next(iter_abt_buy_pairs(pairs))
    assert pair["left_id"] == "abt-buy-v1-a-1"

    review = tmp_path / "Beauty.jsonl"
    review.write_text(json.dumps({"asin": "a", "title": "Nice", "text": "works", "user_id": "secret", "rating": 5, "timestamp": 1_700_000_000_000}) + "\n", encoding="utf-8")
    item = next(iter_review_documents(review))
    assert "secret" not in item.text
    assert "user_id" not in item.metadata
    assert item.metadata["timestamp"].startswith("2023-")


def test_amazon_google_and_abo_adapters_are_stable(tmp_path: Path):
    pair_file = tmp_path / "pairs.csv"
    pair_file.write_text("id,label,left_id,left_title,left_manufacturer,left_price,right_id,right_title,right_manufacturer,right_price\n1,1,l,Alpha,Acme,1,r,Beta,Acme,2\n", encoding="utf-8")
    products = list(iter_amazon_google_products([pair_file]))
    assert {item.id for item in products} == {"amazon-google-v1-left-l", "amazon-google-v1-right-r"}
    assert next(iter_amazon_google_pairs(pair_file))["label"] == 1

    abo = tmp_path / "listings.jsonl"
    abo.write_text(json.dumps({"item_id": "a", "title": "Lamp", "brand": "Brand", "product_type_readable": "lighting", "hierarchy_path": "Home > lighting", "images": ["ignored"]}) + "\n", encoding="utf-8")
    item = next(iter_abo_products(abo))
    assert item.id == "abo-v1-product-a"
    assert item.metadata["images_excluded"] is True


def test_deduplication_reports_duplicate_ids_and_text():
    first = normalize_record(record_id="one", dataset="d", kind="product", title="A", text="same")
    second = normalize_record(record_id="one", dataset="d", kind="product", title="B", text="other")
    third = normalize_record(record_id="three", dataset="d", kind="product", title="C", text="same")
    records, stats = deduplicate_records([first, second, third])
    assert [item.id for item in records if item] == ["one"]
    assert stats == {"duplicate_id_count": 1, "duplicate_text_count": 1}
    assert timestamp_iso("bad") is None
