"""项目核心数据结构与跨字段业务约束。"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


BEIJING_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


class StrEnum(str, Enum):
    """兼容 Python 3.10 的字符串枚举。"""


class SlotRequirement(StrEnum):
    HARD = "hard"
    FLEXIBLE = "flexible"


class ReviewStatus(StrEnum):
    PASSED = "passed"
    NEEDS_INFORMATION = "needs_information"
    NEEDS_CONFIRMATION = "needs_confirmation"
    BLOCKED = "blocked"


class ConfirmationStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING_CONFIRMATION = "pending_confirmation"
    CONFIRMED = "confirmed"


class DraftStatus(StrEnum):
    SAVED = "saved"
    DUPLICATE = "duplicate"
    NOT_ATTEMPTED = "not_attempted"
    FAILED = "failed"


class TaskStatus(StrEnum):
    COMPLETED = "completed"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    BLOCKED = "blocked"
    INCOMPLETE = "incomplete"
    FAILED = "failed"


class ToolStatus(StrEnum):
    SUCCESS = "success"
    NOT_FOUND = "not_found"
    INVALID_INPUT = "invalid_input"
    FAILURE = "failure"


class RuleAction(StrEnum):
    REQUEST_INFORMATION = "request_information"
    REQUEST_CONFIRMATION = "request_confirmation"
    BLOCK = "block"


class RuleOperator(StrEnum):
    REQUIRED_FIELDS = "required_fields"
    CONTAINS_ANY = "contains_any"
    EQUALS = "equals"
    IN = "in"


class ScheduleStatus(StrEnum):
    CONFIRMED = "confirmed"
    DRAFT = "draft"


class SlotAvailability(StrEnum):
    AVAILABLE = "available"
    OCCUPIED = "occupied"


class StrictModel(BaseModel):
    """拒绝未知字段，避免模型或调用方悄悄注入额外状态。"""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True,
        use_enum_values=False,
    )


def _require_beijing_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("时间必须包含时区")
    return value.astimezone(BEIJING_TZ)


class ScheduleConstraints(StrictModel):
    allowed_date: date | None = None
    earliest_time: time | None = None
    latest_time: time | None = None

    @model_validator(mode="after")
    def validate_time_range(self) -> "ScheduleConstraints":
        if (
            self.earliest_time is not None
            and self.latest_time is not None
            and self.earliest_time >= self.latest_time
        ):
            raise ValueError("earliest_time 必须早于 latest_time")
        return self


class SchedulingRequest(StrictModel):
    request_id: str = Field(min_length=1, max_length=100)
    material_id: str = Field(min_length=1, max_length=100)
    requested_slot: datetime
    slot_requirement: SlotRequirement = SlotRequirement.HARD
    user_confirmed_alternative: bool = False
    constraints: ScheduleConstraints | None = None

    _normalize_slot = field_validator("requested_slot")(
        _require_beijing_datetime
    )

    @model_validator(mode="after")
    def validate_constraints(self) -> "SchedulingRequest":
        if self.constraints is None:
            return self

        local_slot = self.requested_slot.astimezone(BEIJING_TZ)
        if (
            self.constraints.allowed_date is not None
            and local_slot.date() != self.constraints.allowed_date
        ):
            raise ValueError("requested_slot 不在 allowed_date 内")

        local_time = local_slot.time().replace(tzinfo=None)
        if (
            self.constraints.earliest_time is not None
            and local_time < self.constraints.earliest_time
        ):
            raise ValueError("requested_slot 早于 earliest_time")
        if (
            self.constraints.latest_time is not None
            and local_time > self.constraints.latest_time
        ):
            raise ValueError("requested_slot 晚于 latest_time")
        return self


class MaterialMetadata(StrictModel):
    material_id: str = Field(min_length=1, max_length=100)
    title: str | None = None
    media_type: str | None = None
    source: str | None = None
    copyright_owner: str | None = None
    content_summary: str | None = None
    category: str | None = None
    tags: list[str] = Field(default_factory=list)
    language: str = "zh-CN"


class ReviewRule(StrictModel):
    rule_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    description: str
    field: str
    operator: RuleOperator
    expected: Any
    action: RuleAction
    reason: str
    enabled: bool = True

    @model_validator(mode="after")
    def validate_rule_shape(self) -> "ReviewRule":
        list_operators = {
            RuleOperator.REQUIRED_FIELDS,
            RuleOperator.CONTAINS_ANY,
            RuleOperator.IN,
        }
        if self.operator in list_operators:
            if not isinstance(self.expected, list) or not self.expected:
                raise ValueError(f"{self.operator.value} 的 expected 必须是非空数组")

        if self.operator == RuleOperator.REQUIRED_FIELDS:
            unknown_fields = [
                str(item)
                for item in self.expected
                if str(item) not in MaterialMetadata.model_fields
            ]
            if unknown_fields:
                raise ValueError(f"必填字段规则包含未知字段：{unknown_fields}")
        elif self.field not in MaterialMetadata.model_fields:
            raise ValueError(f"规则字段不存在：{self.field}")
        return self


class ScheduledItem(StrictModel):
    schedule_id: str = Field(min_length=1, max_length=100)
    material_id: str = Field(min_length=1, max_length=100)
    slot: datetime
    status: ScheduleStatus = ScheduleStatus.CONFIRMED

    _normalize_slot = field_validator("slot")(_require_beijing_datetime)


class SlotQueryInput(StrictModel):
    slot: datetime

    _normalize_slot = field_validator("slot")(_require_beijing_datetime)


class AlternativeSlotQuery(StrictModel):
    preferred_slot: datetime
    earliest_time: time = time(9, 0)
    latest_time: time = time(22, 0)
    limit: int = Field(default=3, ge=1, le=10)
    interval_minutes: int = Field(default=60, ge=15, le=240)

    _normalize_slot = field_validator("preferred_slot")(
        _require_beijing_datetime
    )

    @model_validator(mode="after")
    def validate_search_window(self) -> "AlternativeSlotQuery":
        if self.earliest_time >= self.latest_time:
            raise ValueError("earliest_time 必须早于 latest_time")
        local_time = self.preferred_slot.time().replace(tzinfo=None)
        if not self.earliest_time <= local_time <= self.latest_time:
            raise ValueError("preferred_slot 不在候选搜索范围内")
        return self


class CandidateSlot(StrictModel):
    slot: datetime
    confirmation_status: ConfirmationStatus = (
        ConfirmationStatus.PENDING_CONFIRMATION
    )

    _normalize_slot = field_validator("slot")(_require_beijing_datetime)

    @model_validator(mode="after")
    def require_pending_confirmation(self) -> "CandidateSlot":
        if self.confirmation_status != ConfirmationStatus.PENDING_CONFIRMATION:
            raise ValueError("候选时段只能标记为 pending_confirmation")
        return self


class ToolResult(StrictModel):
    tool_name: str = Field(min_length=1, max_length=100)
    status: ToolStatus
    summary: str
    data: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None

    @model_validator(mode="after")
    def require_error_code_for_failure(self) -> "ToolResult":
        if self.status == ToolStatus.FAILURE and not self.error_code:
            raise ValueError("工具失败时必须提供 error_code")
        return self


class DraftRecord(StrictModel):
    draft_id: str = Field(min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=16, max_length=128)
    request_id: str = Field(min_length=1, max_length=100)
    material_id: str = Field(min_length=1, max_length=100)
    requested_slot: datetime
    suggested_slot: datetime | None = None
    confirmation_status: ConfirmationStatus
    created_at: datetime

    _normalize_requested_slot = field_validator("requested_slot")(
        _require_beijing_datetime
    )
    _normalize_suggested_slot = field_validator("suggested_slot")(
        lambda value: None if value is None else _require_beijing_datetime(value)
    )
    _normalize_created_at = field_validator("created_at")(
        _require_beijing_datetime
    )

    @model_validator(mode="after")
    def validate_confirmation_boundary(self) -> "DraftRecord":
        if (
            self.suggested_slot is not None
            and self.suggested_slot != self.requested_slot
            and self.confirmation_status == ConfirmationStatus.NOT_REQUIRED
        ):
            raise ValueError("替代时段必须待确认或已确认")
        return self


class DraftSaveInput(StrictModel):
    request: SchedulingRequest
    review_status: ReviewStatus
    suggested_slot: datetime | None = None
    confirmation_status: ConfirmationStatus

    _normalize_suggested_slot = field_validator("suggested_slot")(
        lambda value: None if value is None else _require_beijing_datetime(value)
    )

    @model_validator(mode="after")
    def validate_save_boundary(self) -> "DraftSaveInput":
        if self.review_status in {
            ReviewStatus.BLOCKED,
            ReviewStatus.NEEDS_INFORMATION,
        }:
            raise ValueError("审核阻断或信息不足时不能保存排期草稿")

        if (
            self.review_status == ReviewStatus.NEEDS_CONFIRMATION
            and self.confirmation_status == ConfirmationStatus.NOT_REQUIRED
        ):
            raise ValueError("需要人工审核的素材不能标记为无需确认")

        if (
            self.suggested_slot is not None
            and self.suggested_slot != self.request.requested_slot
        ):
            if self.confirmation_status == ConfirmationStatus.NOT_REQUIRED:
                raise ValueError("替代时段必须待确认或已确认")
            if (
                self.confirmation_status == ConfirmationStatus.CONFIRMED
                and not self.request.user_confirmed_alternative
            ):
                raise ValueError("未经用户同意不能确认替代时段")
        return self


class AgentResult(StrictModel):
    request_id: str = Field(min_length=1, max_length=100)
    material_id: str = Field(min_length=1, max_length=100)
    review_status: ReviewStatus
    risk_reasons: list[str] = Field(default_factory=list)
    requested_slot: datetime
    suggested_slot: datetime | None = None
    confirmation_status: ConfirmationStatus
    pending_items: list[str] = Field(default_factory=list)
    draft_status: DraftStatus
    draft_id: str | None = None
    task_status: TaskStatus
    summary: str
    trace_file: Path | None = None

    _normalize_requested_slot = field_validator("requested_slot")(
        _require_beijing_datetime
    )
    _normalize_suggested_slot = field_validator("suggested_slot")(
        lambda value: None if value is None else _require_beijing_datetime(value)
    )

    @model_validator(mode="after")
    def validate_result_consistency(self) -> "AgentResult":
        if self.draft_status in {DraftStatus.SAVED, DraftStatus.DUPLICATE}:
            if not self.draft_id:
                raise ValueError("草稿已保存或重复时必须提供 draft_id")
        elif self.draft_id is not None:
            raise ValueError("未保存草稿时不得提供 draft_id")

        if self.review_status == ReviewStatus.BLOCKED:
            if self.draft_status in {DraftStatus.SAVED, DraftStatus.DUPLICATE}:
                raise ValueError("被阻断的素材不能保存排期草稿")
            if self.task_status != TaskStatus.BLOCKED:
                raise ValueError("审核阻断时任务状态必须为 blocked")

        if (
            self.suggested_slot is not None
            and self.suggested_slot != self.requested_slot
            and self.confirmation_status == ConfirmationStatus.NOT_REQUIRED
        ):
            raise ValueError("替代时段必须待确认或已确认")

        if self.task_status == TaskStatus.AWAITING_CONFIRMATION:
            if self.confirmation_status != ConfirmationStatus.PENDING_CONFIRMATION:
                raise ValueError("等待确认时 confirmation_status 必须为 pending_confirmation")
            if not self.pending_items:
                raise ValueError("等待确认时必须说明待确认项")
            if self.draft_status not in {DraftStatus.SAVED, DraftStatus.DUPLICATE}:
                raise ValueError("等待确认时必须已有草稿")

        if self.task_status == TaskStatus.COMPLETED:
            if self.draft_status not in {DraftStatus.SAVED, DraftStatus.DUPLICATE}:
                raise ValueError("任务完成时必须已有草稿")
            if self.confirmation_status == ConfirmationStatus.PENDING_CONFIRMATION:
                raise ValueError("仍待确认时任务不能标记为 completed")
        return self

