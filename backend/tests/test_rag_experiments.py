"""Contract tests for the isolated RAG experiment runner."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts/run-rag-experiments.py"


@pytest.fixture(scope="module")
def experiment_runner():
    spec = importlib.util.spec_from_file_location("rag_experiment_runner", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v2_dataset_and_strategy_matrix_contracts(experiment_runner):
    config_path = PROJECT_ROOT / "evals/rag/experiments-v1.json"
    dataset_path = PROJECT_ROOT / "evals/rag/real-v2.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    experiment_runner.validate_experiment_config(config, config_path)
    experiment_runner.validate_dataset(dataset, dataset_path)
    assert len(dataset["queries"]) >= 50
    assert {item["id"] for item in config["experiments"]} == {
        "no-rag", "dense-only", "hybrid", "hybrid-rerank", "full", "adaptive"
    }
    assert {item["category"] for item in dataset["queries"]} == {
        "fact", "comparison", "temporal", "multi_hop", "no_answer"
    }
    assert len(dataset["robustness_queries"]) >= 3
    assert config["drift_baseline_dataset"] == "evals/rag/real-v1.json"


def test_no_rag_cases_preserve_answerability_metadata(experiment_runner):
    cases = experiment_runner._no_rag_cases(
        [
            {"id": "known", "query": "price", "relevant": ["doc"], "category": "fact"},
            {"id": "unknown", "query": "unknown", "relevant": [], "category": "no_answer", "abstention_expected": False},
        ]
    )
    assert cases[0]["answerable"] is True
    assert cases[0]["abstention_expected"] is False
    assert cases[1]["abstention_expected"] is False
