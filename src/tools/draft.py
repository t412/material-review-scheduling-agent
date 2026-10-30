"""排期草稿保存工具。此模块不提供真实发布能力。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from src.exceptions import DataRepositoryError
from src.schemas import (
    BEIJING_TZ,
    DraftRecord,
    DraftSaveInput,
    DraftStatus,
    ToolResult,
    ToolStatus,
)
from src.storage.draft_repository import DraftRepository
from src.storage.idempotency import build_idempotency_key


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DRAFTS_PATH = PROJECT_ROOT / "runtime" / "drafts" / "drafts.json"


def save_schedule_draft(
    request: dict[str, Any],
    *,
    review_status: str,
    suggested_slot: str | datetime | None,
    confirmation_status: str,
    drafts_path: Path = DEFAULT_DRAFTS_PATH,
    inject_failure: bool = False,
) -> ToolResult:
    """验证业务边界后幂等保存草稿，永不执行真实发布。"""

    try:
        save_input = DraftSaveInput.model_validate(
            {
                "request": request,
                "review_status": review_status,
                "suggested_slot": suggested_slot,
                "confirmation_status": confirmation_status,
            }
        )
    except ValidationError as exc:
        return ToolResult(
            tool_name="save_schedule_draft",
            status=ToolStatus.INVALID_INPUT,
            summary="草稿保存参数或业务状态无效。",
            error_code="INVALID_DRAFT_INPUT",
            data={"validation_error": str(exc), "draft_status": DraftStatus.NOT_ATTEMPTED.value},
        )

    if inject_failure:
        return ToolResult(
            tool_name="save_schedule_draft",
            status=ToolStatus.FAILURE,
            summary="已注入草稿存储失败；草稿未保存。",
            error_code="DRAFT_SAVE_INJECTED_FAILURE",
            data={"draft_status": DraftStatus.FAILED.value},
        )

    idempotency_key = build_idempotency_key(save_input.request)
    draft = DraftRecord(
        draft_id=f"DRAFT-{idempotency_key[:12].upper()}",
        idempotency_key=idempotency_key,
        request_id=save_input.request.request_id,
        material_id=save_input.request.material_id,
        requested_slot=save_input.request.requested_slot,
        suggested_slot=save_input.suggested_slot,
        confirmation_status=save_input.confirmation_status,
        created_at=datetime.now(BEIJING_TZ),
    )

    try:
        saved_draft, duplicate = DraftRepository(drafts_path).save(draft)
    except DataRepositoryError as exc:
        return ToolResult(
            tool_name="save_schedule_draft",
            status=ToolStatus.FAILURE,
            summary=f"草稿保存失败：{exc}",
            error_code=exc.error_code,
            data={"draft_status": DraftStatus.FAILED.value},
        )

    draft_status = DraftStatus.DUPLICATE if duplicate else DraftStatus.SAVED
    summary = (
        f"检测到重复请求，返回已有草稿{saved_draft.draft_id}。"
        if duplicate
        else f"草稿{saved_draft.draft_id}已保存，未执行真实发布。"
    )
    return ToolResult(
        tool_name="save_schedule_draft",
        status=ToolStatus.SUCCESS,
        summary=summary,
        data={
            "draft_status": draft_status.value,
            "draft": saved_draft.model_dump(mode="json"),
            "published": False,
        },
    )

