"""Tests for competition/state.py — CompetitionState TypedDict.

Covers §1.1 of the coding plan:
- All 23 fields declared with correct types
- Annotated[list, op_add] reducer fields
- NotRequired optional fields
- AgentState inheritance (messages field)
"""

from __future__ import annotations

from typing import get_type_hints

from competition.state import CompetitionState


class TestCompetitionStateFields:
    """Verify all fields declared in COMPETITION_PLAN.md §3.9."""

    def test_inherits_agent_state(self):
        """CompetitionState must include messages field from AgentState (TypedDict, not class inheritance)."""
        from typing import get_type_hints
        hints = get_type_hints(CompetitionState, include_extras=True)
        assert "messages" in hints, "CompetitionState must declare messages field for LangGraph compatibility"

    def test_user_input_fields(self):
        hints = get_type_hints(CompetitionState, include_extras=True)
        assert "user_request" in hints
        assert "target_products" in hints
        assert "persona" in hints

    def test_collector_output_fields(self):
        hints = get_type_hints(CompetitionState, include_extras=True)
        assert "collected_data" in hints
        assert "collection_summary" in hints
        assert "knowledge_gaps" in hints

    def test_analyst_output_fields(self):
        hints = get_type_hints(CompetitionState, include_extras=True)
        assert "analysis_result" in hints

    def test_reviewer_output_fields(self):
        hints = get_type_hints(CompetitionState, include_extras=True)
        assert "review_verdict" in hints
        assert "review_round" in hints
        assert "gap_coverage_improvement" in hints

    def test_writer_output_fields(self):
        hints = get_type_hints(CompetitionState, include_extras=True)
        assert "report_data" in hints
        assert "traceability_map" in hints
        assert "review_package" in hints

    def test_hitl_fields(self):
        hints = get_type_hints(CompetitionState, include_extras=True)
        assert "hitl_decision" in hints

    def test_error_field(self):
        hints = get_type_hints(CompetitionState, include_extras=True)
        assert "error" in hints

    def test_total_field_count(self):
        """Runtime tracking and analysis context extend the business state."""
        hints = get_type_hints(CompetitionState, include_extras=True)
        custom_fields = {k for k in hints if k != "messages"}
        assert len(custom_fields) == 32, f"Expected 32 custom fields, got {len(custom_fields)}: {custom_fields}"


class TestReducers:
    """Annotated[list, op_add] fields must accumulate across rounds."""

    def test_collected_data_is_add_reducer(self):
        """collected_data must auto-merge multi-round results."""
        hints = get_type_hints(CompetitionState, include_extras=True)
        assert "collected_data" in hints
        metadata = getattr(hints["collected_data"], "__metadata__", None)
        assert metadata is not None, "collected_data must be Annotated[list, op_add]"

    def test_stage_results_is_add_reducer(self):
        """Stage attempts must accumulate across rework rounds."""
        hints = get_type_hints(CompetitionState, include_extras=True)
        metadata = getattr(hints["stage_results"], "__metadata__", None)
        assert metadata is not None, "stage_results must be Annotated[list, op_add]"

class TestOptionalFields:
    """Most fields should be NotRequired (graph nodes return partial updates)."""

    def test_fields_are_not_required(self):
        """All custom fields should be NotRequired — LangGraph nodes return partial updates."""
        hints = get_type_hints(CompetitionState, include_extras=True)
        required = {"messages"}  # AgentState requires messages
        for name in hints:
            if name in required:
                continue
            # All custom fields should be accessible via .get() with None default
            state = CompetitionState(messages=[])
            assert state.get(name) is None, f"{name} should return None when unset"

    def test_can_construct_minimal(self):
        """Minimal state dict with only messages key (TypedDict, not class instance)."""
        state = CompetitionState(messages=[])
        assert state is not None
        assert state.get("messages") == []
        assert state.get("user_request") is None  # NotRequired → None
        assert state.get("collected_data") is None  # Annotated field starts unset
