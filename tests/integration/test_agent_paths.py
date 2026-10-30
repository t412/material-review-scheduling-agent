from __future__ import annotations

from src.agent import AgentRuntime, MaterialSchedulingAgent
from src.models.mock_model import OfflineMockModel


def request_data(material_id: str, hour: int, request_id: str = "REQ-001") -> dict:
    return {
        "request_id": request_id,
        "material_id": material_id,
        "requested_slot": f"2026-11-02T{hour:02d}:00:00+08:00",
        "slot_requirement": "hard",
        "user_confirmed_alternative": False,
        "constraints": {
            "allowed_date": "2026-11-02",
            "earliest_time": "17:00:00",
            "latest_time": "21:00:00",
        },
    }


def build_agent(tmp_path, *, save_failure: bool = False):
    return MaterialSchedulingAgent(
        OfflineMockModel(),
        runtime=AgentRuntime(
            drafts_path=tmp_path / "drafts.json",
            inject_save_failure=save_failure,
        ),
    )


def test_normal_available_slot_path_saves_draft(tmp_path) -> None:
    run = build_agent(tmp_path).run(request_data("M01", 17))

    assert run.result.task_status.value == "completed"
    assert run.result.draft_status.value == "saved"
    assert run.result.draft_id is not None
    assert run.result.suggested_slot is None
    assert [step.tool_name for step in run.steps] == [
        "get_material",
        "check_material_rules",
        "query_slot",
        "save_schedule_draft",
    ]


def test_occupied_slot_path_queries_alternative_and_waits_confirmation(tmp_path) -> None:
    run = build_agent(tmp_path).run(request_data("M01", 18))

    assert run.result.task_status.value == "awaiting_confirmation"
    assert run.result.suggested_slot.hour == 19
    assert run.result.confirmation_status.value == "pending_confirmation"
    assert [step.tool_name for step in run.steps] == [
        "get_material",
        "check_material_rules",
        "query_slot",
        "find_alternative_slots",
        "save_schedule_draft",
    ]


def test_missing_material_information_stops_before_scheduling(tmp_path) -> None:
    run = build_agent(tmp_path).run(request_data("M02", 17))

    assert run.result.review_status.value == "needs_information"
    assert run.result.draft_status.value == "not_attempted"
    assert [step.tool_name for step in run.steps] == ["get_material"]
    assert not (tmp_path / "drafts.json").exists()


def test_blocking_rule_stops_before_slot_query(tmp_path) -> None:
    run = build_agent(tmp_path).run(request_data("M03", 17))

    assert run.result.task_status.value == "blocked"
    assert run.result.draft_status.value == "not_attempted"
    assert [step.tool_name for step in run.steps] == [
        "get_material",
        "check_material_rules",
    ]


def test_review_risk_saves_pending_draft_and_requests_confirmation(tmp_path) -> None:
    run = build_agent(tmp_path).run(request_data("M04", 17))

    assert run.result.review_status.value == "needs_confirmation"
    assert run.result.task_status.value == "awaiting_confirmation"
    assert run.result.confirmation_status.value == "pending_confirmation"
    assert run.result.draft_status.value == "saved"
    assert run.result.risk_reasons == ["健康或医疗类内容需要人工复核。"]


def test_save_failure_is_reported_truthfully(tmp_path) -> None:
    run = build_agent(tmp_path, save_failure=True).run(request_data("M01", 17))

    assert run.result.task_status.value == "failed"
    assert run.result.draft_status.value == "failed"
    assert run.result.draft_id is None
    assert "保存失败" in run.result.summary
    assert not (tmp_path / "drafts.json").exists()


def test_same_request_second_run_returns_duplicate(tmp_path) -> None:
    agent = build_agent(tmp_path)
    first = agent.run(request_data("M01", 17, "REQ-001"))
    second = agent.run(request_data("M01", 17, "REQ-002"))

    assert first.result.draft_status.value == "saved"
    assert second.result.draft_status.value == "duplicate"
    assert second.result.draft_id == first.result.draft_id

