"""时段查询和候选时段搜索工具。"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from pathlib import Path

from pydantic import ValidationError

from src.exceptions import DataRepositoryError
from src.schemas import (
    AlternativeSlotQuery,
    BEIJING_TZ,
    CandidateSlot,
    ScheduledItem,
    SlotAvailability,
    SlotQueryInput,
    ToolResult,
    ToolStatus,
)
from src.storage.json_repository import load_model_list


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEDULES_PATH = PROJECT_ROOT / "data" / "schedules.json"


def _load_schedules(path: Path) -> list[ScheduledItem]:
    return load_model_list(path, ScheduledItem)


def _same_instant(left: datetime, right: datetime) -> bool:
    return left.astimezone(BEIJING_TZ) == right.astimezone(BEIJING_TZ)


def query_slot(
    slot: str | datetime,
    *,
    schedules_path: Path = DEFAULT_SCHEDULES_PATH,
) -> ToolResult:
    """查询指定时段；占用属于正常业务结果，不是工具失败。"""

    try:
        query = SlotQueryInput.model_validate({"slot": slot})
    except ValidationError as exc:
        return ToolResult(
            tool_name="query_slot",
            status=ToolStatus.INVALID_INPUT,
            summary="时段格式无效或缺少时区。",
            error_code="INVALID_SLOT",
            data={"validation_error": str(exc)},
        )

    try:
        schedules = _load_schedules(schedules_path)
    except DataRepositoryError as exc:
        return ToolResult(
            tool_name="query_slot",
            status=ToolStatus.FAILURE,
            summary=str(exc),
            error_code=exc.error_code,
        )

    conflicts = [
        item
        for item in schedules
        if _same_instant(item.slot, query.slot)
    ]
    availability = (
        SlotAvailability.OCCUPIED if conflicts else SlotAvailability.AVAILABLE
    )
    local_slot = query.slot.astimezone(BEIJING_TZ)
    summary = (
        f"时段{local_slot.isoformat()}已占用，共{len(conflicts)}项冲突。"
        if conflicts
        else f"时段{local_slot.isoformat()}可用。"
    )
    return ToolResult(
        tool_name="query_slot",
        status=ToolStatus.SUCCESS,
        summary=summary,
        data={
            "slot": local_slot.isoformat(),
            "availability": availability.value,
            "conflicts": [item.model_dump(mode="json") for item in conflicts],
        },
    )


def _iter_window_slots(query: AlternativeSlotQuery):
    local_date = query.preferred_slot.astimezone(BEIJING_TZ).date()
    current = datetime.combine(local_date, query.earliest_time, tzinfo=BEIJING_TZ)
    end = datetime.combine(local_date, query.latest_time, tzinfo=BEIJING_TZ)
    step = timedelta(minutes=query.interval_minutes)
    while current <= end:
        yield current
        current += step


def find_alternative_slots(
    preferred_slot: str | datetime,
    *,
    earliest_time: str | time = "09:00:00",
    latest_time: str | time = "22:00:00",
    limit: int = 3,
    interval_minutes: int = 60,
    schedules_path: Path = DEFAULT_SCHEDULES_PATH,
) -> ToolResult:
    """查找同日候选时段；仅给建议，永不替用户确认。"""

    try:
        query = AlternativeSlotQuery.model_validate(
            {
                "preferred_slot": preferred_slot,
                "earliest_time": earliest_time,
                "latest_time": latest_time,
                "limit": limit,
                "interval_minutes": interval_minutes,
            }
        )
    except ValidationError as exc:
        return ToolResult(
            tool_name="find_alternative_slots",
            status=ToolStatus.INVALID_INPUT,
            summary="候选时段查询参数无效。",
            error_code="INVALID_ALTERNATIVE_QUERY",
            data={"validation_error": str(exc)},
        )

    try:
        schedules = _load_schedules(schedules_path)
    except DataRepositoryError as exc:
        return ToolResult(
            tool_name="find_alternative_slots",
            status=ToolStatus.FAILURE,
            summary=str(exc),
            error_code=exc.error_code,
        )

    occupied = {
        item.slot.astimezone(BEIJING_TZ)
        for item in schedules
    }
    preferred = query.preferred_slot.astimezone(BEIJING_TZ)
    available = [
        slot
        for slot in _iter_window_slots(query)
        if slot != preferred and slot not in occupied
    ]
    # 距离相同时优先推荐原时段之后的候选，例如18:00冲突时先给19:00。
    available.sort(
        key=lambda slot: (
            abs((slot - preferred).total_seconds()),
            0 if slot > preferred else 1,
            slot,
        )
    )
    candidates = [CandidateSlot(slot=slot) for slot in available[: query.limit]]

    summary = (
        f"找到{len(candidates)}个候选时段，均需用户确认。"
        if candidates
        else "指定范围内没有可用候选时段。"
    )
    return ToolResult(
        tool_name="find_alternative_slots",
        status=ToolStatus.SUCCESS,
        summary=summary,
        data={
            "preferred_slot": preferred.isoformat(),
            "candidates": [item.model_dump(mode="json") for item in candidates],
            "requires_confirmation": True,
        },
    )

