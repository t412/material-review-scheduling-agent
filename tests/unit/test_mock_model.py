from __future__ import annotations

import json

from src.models.mock_model import OfflineMockModel


REQUEST = {
    "request_id": "REQ-001",
    "material_id": "M01",
    "requested_slot": "2026-11-02T18:00:00+08:00",
    "slot_requirement": "hard",
    "user_confirmed_alternative": False,
    "constraints": {"earliest_time": "17:00:00", "latest_time": "21:00:00"},
}


def tool_message(name: str, payload: dict) -> dict:
    return {
        "role": "tool",
        "name": name,
        "tool_call_id": f"call-{name}",
        "content": json.dumps(payload),
    }


def base_messages() -> list[dict]:
    return [{"role": "user", "content": json.dumps(REQUEST)}]


def complete_material_observation() -> dict:
    return tool_message(
        "get_material",
        {"status": "success", "data": {"missing_fields": []}},
    )


def passed_review_observation() -> dict:
    return tool_message(
        "check_material_rules",
        {
            "status": "success",
            "data": {"review_status": "passed", "risk_reasons": []},
        },
    )


def test_mock_starts_by_reading_material() -> None:
    decision = OfflineMockModel().decide(base_messages(), [])

    assert decision.tool_calls[0].name == "get_material"


def test_mock_stops_when_material_information_is_missing() -> None:
    messages = base_messages() + [
        tool_message(
            "get_material",
            {
                "status": "success",
                "data": {"missing_fields": ["copyright_owner"]},
            },
        )
    ]

    decision = OfflineMockModel().decide(messages, [])

    assert decision.final_output["review_status"] == "needs_information"
    assert decision.final_output["draft_status"] == "not_attempted"


def test_mock_stops_on_blocking_rule() -> None:
    messages = base_messages() + [
        complete_material_observation(),
        tool_message(
            "check_material_rules",
            {
                "status": "success",
                "data": {
                    "review_status": "blocked",
                    "risk_reasons": ["命中禁止词"],
                },
            },
        ),
    ]

    decision = OfflineMockModel().decide(messages, [])

    assert decision.final_output["task_status"] == "blocked"
    assert decision.final_output["draft_status"] == "not_attempted"


def test_mock_queries_alternatives_after_occupied_observation() -> None:
    messages = base_messages() + [
        complete_material_observation(),
        passed_review_observation(),
        tool_message(
            "query_slot",
            {"status": "success", "data": {"availability": "occupied"}},
        ),
    ]

    decision = OfflineMockModel().decide(messages, [])

    assert decision.tool_calls[0].name == "find_alternative_slots"


def test_mock_saves_directly_after_available_observation() -> None:
    messages = base_messages() + [
        complete_material_observation(),
        passed_review_observation(),
        tool_message(
            "query_slot",
            {"status": "success", "data": {"availability": "available"}},
        ),
    ]

    decision = OfflineMockModel().decide(messages, [])

    assert decision.tool_calls[0].name == "save_schedule_draft"
    assert decision.tool_calls[0].arguments["suggested_slot"] is None


def test_mock_reports_alternative_query_failure() -> None:
    messages = base_messages() + [
        complete_material_observation(),
        passed_review_observation(),
        tool_message(
            "query_slot",
            {"status": "success", "data": {"availability": "occupied"}},
        ),
        tool_message(
            "find_alternative_slots",
            {"status": "failure", "data": {}},
        ),
    ]

    decision = OfflineMockModel().decide(messages, [])

    assert decision.final_output["task_status"] == "failed"
    assert "查询工具失败" in decision.final_output["summary"]


def test_mock_reports_save_failure_truthfully() -> None:
    messages = base_messages() + [
        complete_material_observation(),
        passed_review_observation(),
        tool_message(
            "query_slot",
            {"status": "success", "data": {"availability": "available"}},
        ),
        tool_message(
            "save_schedule_draft",
            {"status": "failure", "data": {"draft_status": "failed"}},
        ),
    ]

    decision = OfflineMockModel().decide(messages, [])

    assert decision.final_output["draft_status"] == "failed"
    assert decision.final_output["task_status"] == "failed"
    assert "保存失败" in decision.final_output["summary"]

