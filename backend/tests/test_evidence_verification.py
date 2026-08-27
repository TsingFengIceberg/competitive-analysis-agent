from competition.evidence_verification import (
    extract_claims,
    lexical_similarity,
    numeric_consistency,
    verification_gaps,
    verify_claims,
)


def _analysis(evidence: str, source_ids: list[str]) -> dict:
    return {
        "comparison_matrix": {
            "cells": [
                {
                    "product": "Cursor",
                    "dimension": "pricing",
                    "evidence": evidence,
                    "source_data_point_ids": source_ids,
                }
            ]
        }
    }


def _point(value: str) -> dict:
    return {
        "id": "dp-1",
        "product": "Cursor",
        "category": "pricing",
        "label": "Cursor Pro monthly price",
        "value": value,
        "source_url": "https://cursor.com/pricing",
        "source_type": "official",
        "source_authority": "primary",
        "collected_at": "2026-08-27T00:00:00+00:00",
    }


def test_extract_claims_covers_matrix_swot_trends_and_dynamic_insights():
    analysis = _analysis("Cursor Pro costs $20 monthly.", ["dp-1"])
    analysis.update(
        {
            "swot": {
                "Cursor": {
                    "items": [
                        {
                            "category": "strength",
                            "statement": "Cursor includes agent mode.",
                            "source_data_point_ids": ["dp-2"],
                        }
                    ]
                }
            },
            "trends": [
                {
                    "dimension": "pricing",
                    "evidence": "The monthly price remained stable.",
                    "source_data_point_ids": ["dp-1"],
                }
            ],
            "dynamic_blocks": [
                {
                    "block_type": "insight_text",
                    "title": "Enterprise adoption",
                    "data": {"text": "Enterprise controls expanded in 2026."},
                    "source_data_point_ids": ["dp-3"],
                }
            ],
        }
    )
    claims = extract_claims(analysis)
    assert [claim["origin"] for claim in claims] == [
        "comparison_matrix",
        "swot.strength",
        "trend",
        "dynamic_block.0.0",
    ]
    assert len({claim["claim_id"] for claim in claims}) == 4


def test_verify_claims_classifies_support_conflict_and_insufficient_evidence():
    supported = verify_claims(
        _analysis("Cursor Pro costs $20 monthly.", ["dp-1"]),
        [_point("Cursor Pro costs $20 monthly.")],
    )
    contradicted = verify_claims(
        _analysis("Cursor Pro costs $25 monthly.", ["dp-1"]),
        [_point("Cursor Pro costs $20 monthly.")],
    )
    insufficient = verify_claims(
        _analysis("Cursor provides an undocumented private deployment mode.", []),
        [],
    )

    assert supported["claims"][0]["status"] == "supported"
    assert supported["groundedness"] == 1.0
    assert supported["citation_precision"] == 1.0
    assert contradicted["claims"][0]["status"] == "contradicted"
    assert contradicted["numeric_consistency"] == 0.0
    assert insufficient["claims"][0]["status"] == "insufficient"


def test_verification_detects_negation_conflicts_and_builds_rework_gaps():
    summary = verify_claims(
        _analysis("Cursor does not support SSO.", ["dp-1"]),
        [_point("Cursor supports SSO for business plans.")],
    )
    assert summary["claims"][0]["status"] == "contradicted"
    gaps = verification_gaps(summary, 0)
    assert gaps[0]["type"] == "source_conflict"
    assert gaps[0]["severity"] == "critical"
    assert gaps[0]["check_method"] == "semantic_claim_verification"


def test_unrelated_source_disclaimer_does_not_flip_claim_polarity():
    summary = verify_claims(
        _analysis("Cursor Pro costs $20 monthly.", ["dp-1"]),
        [_point("Cursor Pro costs $20 monthly. This fixture is not a real product claim.")],
    )
    assert summary["claims"][0]["status"] == "supported"


def test_semantic_and_numeric_helpers_are_multilingual_and_deterministic():
    assert lexical_similarity("支持企业单点登录", "企业版支持单点登录 SSO") > 0
    assert numeric_consistency("月费为 20 美元", "官方价格是每月20美元") is True
    assert numeric_consistency("月费为 25 美元", "官方价格是每月20美元") is False
