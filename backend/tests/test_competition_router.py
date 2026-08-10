"""Tests for competition/router.py conditional routing functions.

Covers §2.1 of the coding plan.
All router functions are pure (dict → str), trivially testable.
"""

from __future__ import annotations

from competition.router import (
    route_after_analyst,
    route_after_collector,
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

    def test_legacy_deep_flag_does_not_start_a_second_pipeline(self):
        assert route_after_hitl({
            "hitl_decision": {"action": "approve"},
            "deep_mode": True,
        }) == "__end__"

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
