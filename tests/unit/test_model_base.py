from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.base import ModelDecision, ModelToolCall


def test_model_decision_accepts_tool_calls() -> None:
    decision = ModelDecision(
        tool_calls=[ModelToolCall(call_id="c1", name="get_material", arguments={})]
    )
    assert decision.final_output is None


def test_model_decision_accepts_final_output() -> None:
    decision = ModelDecision(final_output={"task_status": "completed"})
    assert decision.tool_calls == []


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {
            "tool_calls": [
                {"call_id": "c1", "name": "get_material", "arguments": {}}
            ],
            "final_output": {"task_status": "completed"},
        },
    ],
)
def test_model_decision_rejects_ambiguous_mode(payload) -> None:
    with pytest.raises(ValidationError):
        ModelDecision.model_validate(payload)

