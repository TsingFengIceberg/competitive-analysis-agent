"""Tests for competition/router.py — 10 conditional routing functions.

Covers §2.1 of the coding plan.
All router functions are pure (dict → str), trivially testable.
"""

from __future__ import annotations

from competition.router import (
    route_after_analyst,
    route_after_collector,
    route_after_deep_analyst,
    route_after_deep_collector,
    route_after_deep_hitl,
    route_after_deep_reviewer,
    route_after_deep_writer,
    route_after_hitl,
    route_after_reviewer,
    route_after_writer,
)

# ═══════════════════════════════════════════════════════════════════
# Normal Mode Routing
# ═══════════════════════════════════════════════════════════════════


class TestRouteAfterCollector:
    def test_normal_flow_to_analyst(self):
        assert route_after_collector({"collected_data": [{"id": "dp-1"}]}) == "analyst"

    def test_empty_results_to_error_handler(self):
        """§3.7 empty-result guard: 0 data → error_handler."""
        assert route_after_collector({"collected_data": []}) == "error_handler"

    def test_error_to_error_handler(self):
        assert route_after_collector({"error": "collector crashed"}) == "error_handler"


class TestRouteAfterAnalyst:
    def test_normal_flow_to_reviewer(self):
        assert route_after_analyst({}) == "reviewer"

    def test_error_to_error_handler(self):
        assert route_after_analyst({"error": "analyst crashed"}) == "error_handler"


class TestRouteAfterReviewer:
    def test_passed_to_writer(self):
        assert route_after_reviewer({"review_verdict": {"passed": True}}) == "writer"

    def test_gap_round_0_to_collector(self):
        """§3.12: gap + round < 2 → re-collect."""
        assert route_after_reviewer({
            "review_verdict": {"passed": False},
            "review_round": 0,
        }) == "collector"

    def test_gap_round_1_to_collector(self):
        assert route_after_reviewer({
            "review_verdict": {"passed": False},
            "review_round": 1,
        }) == "collector"

    def test_gap_round_2_forced_to_writer(self):
        """§3.12: round >= 2 hard cap → writer with uncertainty."""
        assert route_after_reviewer({
            "review_verdict": {"passed": False},
            "review_round": 2,
        }) == "writer"

    def test_gap_round_3_forced_to_writer(self):
        assert route_after_reviewer({
            "review_verdict": {"passed": False},
            "review_round": 3,
        }) == "writer"

    def test_error_to_error_handler(self):
        assert route_after_reviewer({"error": "reviewer crashed"}) == "error_handler"


class TestRouteAfterWriter:
    def test_normal_flow_to_hitl(self):
        assert route_after_writer({}) == "hitl_gate"

    def test_error_to_error_handler(self):
        assert route_after_writer({"error": "writer crashed"}) == "error_handler"


class TestRouteAfterHitl:
    def test_approve_no_deep(self):
        assert route_after_hitl({"hitl_decision": {"action": "approve"}}) == "__end__"

    def test_approve_with_deep(self):
        """§3.12: approve + deep_mode → bridge to deep Collector."""
        assert route_after_hitl({
            "hitl_decision": {"action": "approve"},
            "deep_mode": True,
        }) == "deep_collector"

    def test_replan_to_collector(self):
        assert route_after_hitl({"hitl_decision": {"action": "replan"}}) == "collector"

    def test_reanalyze_to_analyst(self):
        assert route_after_hitl({"hitl_decision": {"action": "reanalyze"}}) == "analyst"

    def test_rewrite_to_writer(self):
        assert route_after_hitl({"hitl_decision": {"action": "rewrite"}}) == "writer"

    def test_missing_decision_defaults_approve(self):
        assert route_after_hitl({}) == "__end__"

    def test_none_decision_defaults_approve(self):
        assert route_after_hitl({"hitl_decision": None}) == "__end__"


# ═══════════════════════════════════════════════════════════════════
# Deep Mode Routing (P1)
# ═══════════════════════════════════════════════════════════════════


class TestRouteAfterDeepCollector:
    def test_normal_flow(self):
        assert route_after_deep_collector({}) == "deep_analyst"

    def test_error(self):
        assert route_after_deep_collector({"error": "x"}) == "deep_error_handler"


class TestRouteAfterDeepAnalyst:
    def test_normal_flow(self):
        assert route_after_deep_analyst({}) == "deep_reviewer"

    def test_error(self):
        assert route_after_deep_analyst({"error": "x"}) == "deep_error_handler"


class TestRouteAfterDeepReviewer:
    def test_passed_to_deep_writer(self):
        assert route_after_deep_reviewer({"review_verdict": {"passed": True}}) == "deep_writer"

    def test_gap_round_0_to_deep_collector(self):
        assert route_after_deep_reviewer({
            "review_verdict": {"passed": False},
            "deep_review_round": 0,
        }) == "deep_collector"

    def test_gap_round_4_to_deep_collector(self):
        """Deep mode: round 4 still allows re-collect."""
        assert route_after_deep_reviewer({
            "review_verdict": {"passed": False},
            "deep_review_round": 4,
        }) == "deep_collector"

    def test_gap_round_5_forced_to_deep_writer(self):
        """§3.12: deep mode hard cap at 5 rounds."""
        assert route_after_deep_reviewer({
            "review_verdict": {"passed": False},
            "deep_review_round": 5,
        }) == "deep_writer"


class TestRouteAfterDeepWriter:
    def test_normal_flow(self):
        assert route_after_deep_writer({}) == "deep_hitl"

    def test_error(self):
        assert route_after_deep_writer({"error": "x"}) == "deep_error_handler"


class TestRouteAfterDeepHitl:
    def test_approve_to_feishu(self):
        assert route_after_deep_hitl({"deep_hitl_decision": {"action": "approve"}}) == "feishu_delivery"

    def test_replan_to_deep_collector(self):
        assert route_after_deep_hitl({"deep_hitl_decision": {"action": "replan"}}) == "deep_collector"

    def test_reanalyze_to_deep_analyst(self):
        assert route_after_deep_hitl({"deep_hitl_decision": {"action": "reanalyze"}}) == "deep_analyst"

    def test_rewrite_to_deep_writer(self):
        assert route_after_deep_hitl({"deep_hitl_decision": {"action": "rewrite"}}) == "deep_writer"

    def test_default_approve(self):
        assert route_after_deep_hitl({}) == "feishu_delivery"
