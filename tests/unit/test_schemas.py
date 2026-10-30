from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.schemas import (
    AgentResult,
    ConfirmationStatus,
    DraftStatus,
    ReviewStatus,
    ScheduleConstraints,
    SchedulingRequest,
    TaskStatus,
    ToolResult,
)


def valid_request_data() -> dict:
    return {
        "request_id": "REQ-001",
        "material_id": "M01",
        "requested_slot": "2026-11-02T18:00:00+08:00",
        "slot_requirement": "hard",
        "user_confirmed_alternative": False,
        "constraints": {
            "allowed_date": "2026-11-02",
            "earliest_time": "17:00:00",
            "latest_time": "21:00:00",
        },
    }


def test_valid_request_is_parsed_and_normalized_to_beijing_time() -> None:
    data = valid_request_data()
    data["requested_slot"] = "2026-11-02T10:00:00Z"

    request = SchedulingRequest.model_validate(data)

    assert request.requested_slot.hour == 18
    assert request.requested_slot.utcoffset() == timedelta(hours=8)
    assert request.material_id == "M01"


@pytest.mark.parametrize("missing_field", ["request_id", "material_id", "requested_slot"])
def test_request_rejects_missing_required_fields(missing_field: str) -> None:
    data = valid_request_data()
    data.pop(missing_field)

    with pytest.raises(ValidationError):
        SchedulingRequest.model_validate(data)


def test_request_rejects_datetime_without_timezone() -> None:
    data = valid_request_data()
    data["requested_slot"] = "2026-11-02T18:00:00"

    with pytest.raises(ValidationError, match="必须包含时区"):
        SchedulingRequest.model_validate(data)


def test_request_rejects_unknown_status() -> None:
    data = valid_request_data()
    data["slot_requirement"] = "automatic_publish"

    with pytest.raises(ValidationError):
        SchedulingRequest.model_validate(data)


def test_request_rejects_extra_fields() -> None:
    data = valid_request_data()
    data["publish_immediately"] = True

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SchedulingRequest.model_validate(data)


def test_constraints_reject_reversed_time_range() -> None:
    with pytest.raises(ValidationError, match="earliest_time 必须早于 latest_time"):
        ScheduleConstraints.model_validate(
            {"earliest_time": "21:00:00", "latest_time": "17:00:00"}
        )


def test_request_rejects_slot_outside_constraints() -> None:
    data = valid_request_data()
    data["requested_slot"] = "2026-11-02T22:00:00+08:00"

    with pytest.raises(ValidationError, match="晚于 latest_time"):
        SchedulingRequest.model_validate(data)


def test_tool_failure_requires_error_code() -> None:
    with pytest.raises(ValidationError, match="必须提供 error_code"):
        ToolResult.model_validate(
            {
                "tool_name": "save_schedule_draft",
                "status": "failure",
                "summary": "存储不可用",
            }
        )


def base_result_data() -> dict:
    return {
        "request_id": "REQ-001",
        "material_id": "M01",
        "review_status": "passed",
        "risk_reasons": [],
        "requested_slot": "2026-11-02T18:00:00+08:00",
        "suggested_slot": None,
        "confirmation_status": "not_required",
        "pending_items": [],
        "draft_status": "saved",
        "draft_id": "DRAFT-001",
        "task_status": "completed",
        "summary": "草稿已保存。",
        "trace_file": "runtime/traces/REQ-001.json",
    }


def test_valid_agent_result() -> None:
    result = AgentResult.model_validate(base_result_data())

    assert result.review_status == ReviewStatus.PASSED
    assert result.draft_status == DraftStatus.SAVED
    assert result.task_status == TaskStatus.COMPLETED
    assert result.trace_file == Path("runtime/traces/REQ-001.json")


def test_saved_result_requires_draft_id() -> None:
    data = base_result_data()
    data["draft_id"] = None

    with pytest.raises(ValidationError, match="必须提供 draft_id"):
        AgentResult.model_validate(data)


def test_blocked_material_cannot_have_saved_draft() -> None:
    data = base_result_data()
    data["review_status"] = "blocked"
    data["task_status"] = "blocked"

    with pytest.raises(ValidationError, match="不能保存排期草稿"):
        AgentResult.model_validate(data)


def test_alternative_slot_requires_confirmation() -> None:
    data = base_result_data()
    data["suggested_slot"] = "2026-11-02T19:00:00+08:00"

    with pytest.raises(ValidationError, match="替代时段必须待确认或已确认"):
        AgentResult.model_validate(data)


def test_awaiting_confirmation_requires_pending_item() -> None:
    data = base_result_data()
    data.update(
        {
            "suggested_slot": "2026-11-02T19:00:00+08:00",
            "confirmation_status": ConfirmationStatus.PENDING_CONFIRMATION,
            "task_status": "awaiting_confirmation",
            "pending_items": [],
        }
    )

    with pytest.raises(ValidationError, match="必须说明待确认项"):
        AgentResult.model_validate(data)


def test_unknown_review_status_is_rejected() -> None:
    data = base_result_data()
    data["review_status"] = "published"

    with pytest.raises(ValidationError):
        AgentResult.model_validate(data)


def test_failed_draft_cannot_keep_draft_id() -> None:
    data = base_result_data()
    data.update({"draft_status": "failed", "task_status": "failed"})

    with pytest.raises(ValidationError, match="不得提供 draft_id"):
        AgentResult.model_validate(data)

