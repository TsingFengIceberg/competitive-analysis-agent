"""Focused tests for bounded parallel Writer section generation."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import competition.executor as executor_module
from competition.nodes.writer import (
    WRITER_MAX_PARALLEL_PER_REPORT,
    _build_writer_task_specs,
    _merge_industry_sections,
    _run_writer_tasks,
    _WriterTaskSpec,
)


def _state(industry: str = "ai") -> dict:
    return {
        "industry": industry,
        "target_products": ["A", "B"],
        "user_request": "比较 A 和 B",
        "collected_data": [],
        "analysis_result": {
            "comparison_matrix": {
                "summary": "A 和 B 存在差异",
                "cells": [],
            },
        },
    }


def test_non_general_task_specs_keep_existing_call_and_token_envelope():
    specs = _build_writer_task_specs(
        state=_state(),
        analysis=_state()["analysis_result"],
        products=["A", "B"],
        persona="pm",
        traceability={},
        citation_index={},
        hitl_action="",
        hitl_focus=None,
        hitl_comment="",
        brief={},
    )

    assert [spec.key for spec in specs] == [
        "narrative",
        "industry:sec-industry-benchmark",
        "industry:sec-industry-pricing",
    ]
    assert [spec.max_tokens for spec in specs] == [800, 600, 600]
    assert len(specs) == 3


def test_general_report_keeps_single_inline_task():
    state = _state("general")
    specs = _build_writer_task_specs(
        state=state,
        analysis=state["analysis_result"],
        products=["A", "B"],
        persona="pm",
        traceability={},
        citation_index={},
        hitl_action="",
        hitl_focus=None,
        hitl_comment="",
        brief={},
    )

    assert [spec.key for spec in specs] == ["narrative"]


def test_tasks_overlap_and_do_not_exceed_per_report_limit():
    barrier = threading.Barrier(WRITER_MAX_PARALLEL_PER_REPORT)
    active = 0
    maximum = 0
    lock = threading.Lock()

    def make_runner(index: int):
        def runner():
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            barrier.wait(timeout=3)
            with lock:
                active -= 1
            return f"result-{index}", index + 1
        return runner

    specs = [
        _WriterTaskSpec(f"task-{index}", "industry", index, f"S{index}", f"s-{index}", 600, make_runner(index))
        for index in range(WRITER_MAX_PARALLEL_PER_REPORT)
    ]
    results = _run_writer_tasks(specs)

    assert set(results) == {"task-0", "task-1", "task-2"}
    assert maximum == WRITER_MAX_PARALLEL_PER_REPORT
    assert sum(item.tokens for item in results.values()) == 6


def test_results_merge_in_profile_order_even_when_completion_order_differs():
    specs = [
        _WriterTaskSpec("industry:first", "industry", 0, "First", "first", 600, lambda: (None, 0)),
        _WriterTaskSpec("industry:second", "industry", 1, "Second", "second", 600, lambda: (None, 0)),
    ]
    # Construct through the Writer module so this test remains focused on merge semantics.
    from competition.nodes import writer as writer_module

    results = {
        "industry:second": writer_module._WriterTaskResult("industry:second", "industry", 1, "second", "success", "second content"),
        "industry:first": writer_module._WriterTaskResult("industry:first", "industry", 0, "first", "success", "first content"),
    }
    merged = _merge_industry_sections(specs, results)

    assert [section["id"] for section in merged] == ["first", "second"]
    assert [section["content"] for section in merged] == ["first content", "second content"]


def test_failed_task_only_uses_its_own_fallback():
    specs = [
        _WriterTaskSpec("industry:ok", "industry", 0, "OK", "ok", 600, lambda: ("usable", 4)),
        _WriterTaskSpec("industry:bad", "industry", 1, "Bad", "bad", 600, lambda: (None, 0)),
    ]
    results = _run_writer_tasks(specs)
    merged = _merge_industry_sections(specs, results)

    assert merged[0]["content"] == "usable"
    assert "没有足够的行业专属证据" in merged[1]["content"]


def test_cancelled_context_skips_model_tasks():
    calls: list[str] = []
    executor_module.set_cancel_checker(lambda: True)
    try:
        specs = [
            _WriterTaskSpec("task", "industry", 0, "Task", "task", 600, lambda: (calls.append("called") or "bad", 1)),
        ]
        results = _run_writer_tasks(specs)
    finally:
        executor_module.clear_cancel_checker()

    assert calls == []
    assert results["task"].status == "cancelled"


def test_multiple_reports_share_process_cap_without_exceeding_six_workers():
    active = 0
    maximum = 0
    lock = threading.Lock()
    barrier = threading.Barrier(6)

    def make_runner():
        def runner():
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            barrier.wait(timeout=3)
            with lock:
                active -= 1
            return "ok", 1
        return runner

    def run_report(prefix: str):
        specs = [
            _WriterTaskSpec(f"{prefix}-{index}", "industry", index, f"S{index}", f"s-{index}", 600, make_runner())
            for index in range(3)
        ]
        return _run_writer_tasks(specs)

    with ThreadPoolExecutor(max_workers=2) as pool:
        reports = list(pool.map(run_report, ["a", "b"]))

    assert all(len(report) == 3 for report in reports)
    assert maximum == 6
