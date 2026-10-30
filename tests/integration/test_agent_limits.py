from __future__ import annotations

from typing import Any

from src.agent import AgentConfig, AgentRuntime, MaterialSchedulingAgent
from src.models.base import ModelClient, ModelDecision, ModelToolCall
from src.models.mock_model import OfflineMockModel


REQUEST = {
    "request_id": "REQ-LIMIT",
    "material_id": "M01",
    "requested_slot": "2026-11-02T17:00:00+08:00",
    "slot_requirement": "hard",
    "user_confirmed_alternative": False,
}


class RepeatingModel(ModelClient):
    def __init__(self, tool_name: str = "get_material") -> None:
        self.tool_name = tool_name
        self.counter = 0

    def decide(self, messages, tools) -> ModelDecision:
        self.counter += 1
        return ModelDecision(
            tool_calls=[
                ModelToolCall(
                    call_id=f"repeat-{self.counter}",
                    name=self.tool_name,
                    arguments={"material_id": "M01"},
                )
            ]
        )


class ForgedFinalModel(ModelClient):
    def decide(self, messages, tools) -> ModelDecision:
        return ModelDecision(
            final_output={
                "request_id": "REQ-LIMIT",
                "material_id": "M01",
                "review_status": "passed",
                "risk_reasons": [],
                "requested_slot": "2026-11-02T17:00:00+08:00",
                "suggested_slot": None,
                "confirmation_status": "not_required",
                "pending_items": [],
                "draft_status": "saved",
                "draft_id": "DRAFT-FAKE",
                "task_status": "completed",
                "summary": "草稿已保存。",
            }
        )


def test_max_steps_returns_explicit_incomplete(tmp_path) -> None:
    agent = MaterialSchedulingAgent(
        OfflineMockModel(),
        config=AgentConfig(max_steps=2, max_tool_calls=10),
        runtime=AgentRuntime(drafts_path=tmp_path / "drafts.json"),
    )

    run = agent.run(REQUEST)

    assert run.completion_reason == "max_steps"
    assert run.result.task_status.value == "incomplete"
    assert "最大决策步数" in run.result.summary


def test_max_tool_calls_returns_explicit_incomplete(tmp_path) -> None:
    agent = MaterialSchedulingAgent(
        OfflineMockModel(),
        config=AgentConfig(max_steps=8, max_tool_calls=1),
        runtime=AgentRuntime(drafts_path=tmp_path / "drafts.json"),
    )

    run = agent.run(REQUEST)

    assert run.completion_reason == "max_tool_calls"
    assert run.result.task_status.value == "incomplete"
    assert run.tool_calls == 1


def test_repeated_identical_call_is_stopped(tmp_path) -> None:
    agent = MaterialSchedulingAgent(
        RepeatingModel(),
        config=AgentConfig(max_steps=8, max_tool_calls=8, max_identical_calls=1),
        runtime=AgentRuntime(drafts_path=tmp_path / "drafts.json"),
    )

    run = agent.run(REQUEST)

    assert run.completion_reason == "repeated_tool_call"
    assert run.result.task_status.value == "incomplete"
    assert run.tool_calls == 1


def test_unknown_publish_tool_is_never_executed(tmp_path) -> None:
    agent = MaterialSchedulingAgent(
        RepeatingModel("publish"),
        config=AgentConfig(max_steps=1),
        runtime=AgentRuntime(drafts_path=tmp_path / "drafts.json"),
    )

    run = agent.run(REQUEST)

    assert run.steps[0].observation.error_code == "TOOL_NOT_ALLOWED"
    assert not (tmp_path / "drafts.json").exists()


def test_forged_saved_result_is_rejected(tmp_path) -> None:
    agent = MaterialSchedulingAgent(
        ForgedFinalModel(),
        runtime=AgentRuntime(drafts_path=tmp_path / "drafts.json"),
    )

    run = agent.run(REQUEST)

    assert run.completion_reason == "invalid_final_output"
    assert run.result.task_status.value == "failed"
    assert run.result.draft_status.value == "not_attempted"
    assert run.result.draft_id is None

