from competition.budget import limits_for_stage, resolve_policy, summarize, used_tokens


def test_budget_policy_reads_run_and_stage_limits():
    state = {
        "budget_policy": {"enabled": True, "total_tokens": 100, "stage_tokens": {"analyst": 60}},
        "stage_results": [
            {"stage": "orchestrator", "token_usage": {"total_tokens": 20}},
            {"stage": "analyst", "token_usage": {"total_tokens": 10}},
        ],
    }
    assert resolve_policy(state).enabled is True
    assert limits_for_stage(state, "analyst")["effective_remaining"] == 50
    assert used_tokens(state["stage_results"]) == (30, {"orchestrator": 20, "analyst": 10})


def test_budget_summary_marks_exhaustion_without_affecting_unconfigured_runs():
    state = {
        "budget_policy": {"total_tokens": 25},
        "stage_results": [{"stage": "collector", "token_usage": {"total_tokens": 25}}],
    }
    summary = summarize(state, stage="analyst")
    assert summary["effective_remaining"] == 0
    assert summary["exhausted"] is True
    assert limits_for_stage({"stage_results": []}, "analyst")["effective_remaining"] is None
