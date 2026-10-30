from __future__ import annotations

import json

from src.schemas import ToolStatus
from src.tools.schedule import find_alternative_slots, query_slot


def test_query_slot_returns_available() -> None:
    result = query_slot("2026-11-02T17:00:00+08:00")

    assert result.status == ToolStatus.SUCCESS
    assert result.data["availability"] == "available"
    assert result.data["conflicts"] == []


def test_query_slot_returns_conflict_summary() -> None:
    result = query_slot("2026-11-02T18:00:00+08:00")

    assert result.status == ToolStatus.SUCCESS
    assert result.data["availability"] == "occupied"
    assert result.data["conflicts"][0]["schedule_id"] == "SCH-001"


def test_query_slot_normalizes_equivalent_utc_instant() -> None:
    result = query_slot("2026-11-02T10:00:00Z")

    assert result.data["availability"] == "occupied"
    assert result.data["slot"] == "2026-11-02T18:00:00+08:00"


def test_query_slot_rejects_datetime_without_timezone() -> None:
    result = query_slot("2026-11-02T18:00:00")

    assert result.status == ToolStatus.INVALID_INPUT
    assert result.error_code == "INVALID_SLOT"


def test_query_slot_reports_schedule_data_failure(tmp_path) -> None:
    path = tmp_path / "schedules.json"
    path.write_text("broken", encoding="utf-8")

    result = query_slot(
        "2026-11-02T18:00:00+08:00",
        schedules_path=path,
    )

    assert result.status == ToolStatus.FAILURE
    assert result.error_code == "DATA_FILE_INVALID_JSON"


def test_find_alternative_prefers_19_after_18_conflict() -> None:
    result = find_alternative_slots(
        "2026-11-02T18:00:00+08:00",
        earliest_time="17:00:00",
        latest_time="21:00:00",
        limit=3,
    )

    candidates = result.data["candidates"]
    assert candidates[0]["slot"] == "2026-11-02T19:00:00+08:00"
    assert [item["slot"] for item in candidates] == [
        "2026-11-02T19:00:00+08:00",
        "2026-11-02T17:00:00+08:00",
        "2026-11-02T21:00:00+08:00",
    ]


def test_alternative_slots_never_include_occupied_or_preferred_slot() -> None:
    result = find_alternative_slots(
        "2026-11-02T18:00:00+08:00",
        earliest_time="17:00:00",
        latest_time="21:00:00",
        limit=10,
    )

    slots = {item["slot"] for item in result.data["candidates"]}
    assert "2026-11-02T18:00:00+08:00" not in slots
    assert "2026-11-02T20:00:00+08:00" not in slots


def test_alternative_slots_are_always_pending_confirmation() -> None:
    result = find_alternative_slots(
        "2026-11-02T18:00:00+08:00",
        earliest_time="17:00:00",
        latest_time="19:00:00",
    )

    assert result.data["requires_confirmation"] is True
    assert all(
        item["confirmation_status"] == "pending_confirmation"
        for item in result.data["candidates"]
    )


def test_find_alternative_returns_empty_when_day_is_full(tmp_path) -> None:
    path = tmp_path / "full-schedule.json"
    path.write_text(
        json.dumps(
            [
                {
                    "schedule_id": f"SCH-{hour}",
                    "material_id": f"M-{hour}",
                    "slot": f"2026-11-02T{hour:02d}:00:00+08:00",
                    "status": "confirmed",
                }
                for hour in range(17, 22)
            ]
        ),
        encoding="utf-8",
    )

    result = find_alternative_slots(
        "2026-11-02T18:00:00+08:00",
        earliest_time="17:00:00",
        latest_time="21:00:00",
        schedules_path=path,
    )

    assert result.status == ToolStatus.SUCCESS
    assert result.data["candidates"] == []
    assert "没有可用" in result.summary


def test_find_alternative_rejects_invalid_limit() -> None:
    result = find_alternative_slots(
        "2026-11-02T18:00:00+08:00",
        limit=0,
    )

    assert result.status == ToolStatus.INVALID_INPUT
    assert result.error_code == "INVALID_ALTERNATIVE_QUERY"


def test_find_alternative_rejects_reversed_window() -> None:
    result = find_alternative_slots(
        "2026-11-02T18:00:00+08:00",
        earliest_time="21:00:00",
        latest_time="17:00:00",
    )

    assert result.status == ToolStatus.INVALID_INPUT


def test_find_alternative_rejects_preferred_slot_outside_window() -> None:
    result = find_alternative_slots(
        "2026-11-02T18:00:00+08:00",
        earliest_time="19:00:00",
        latest_time="21:00:00",
    )

    assert result.status == ToolStatus.INVALID_INPUT

