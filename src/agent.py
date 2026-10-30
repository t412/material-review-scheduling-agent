"""模型选择动作、执行工具、观察结果并继续决策的Agent循环。"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.exceptions import ModelError, ToolNotAllowedError, TraceWriteError
from src.models.base import ModelClient, ModelToolCall
from src.prompts import AGENT_SYSTEM_PROMPT
from src.schemas import (
    AgentResult,
    BEIJING_TZ,
    ConfirmationStatus,
    DraftStatus,
    ReviewStatus,
    SchedulingRequest,
    TaskStatus,
    ToolResult,
    ToolStatus,
)
from src.tools.registry import RegisteredTool, ToolRegistry, build_default_registry
from src.trace import TraceWriter


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_steps: int = Field(default=8, ge=1, le=50)
    max_tool_calls: int = Field(default=10, ge=1, le=100)
    max_identical_calls: int = Field(default=2, ge=1, le=10)
    max_final_corrections: int = Field(default=1, ge=0, le=3)


class AgentRuntime(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    materials_path: Path | None = None
    rules_path: Path | None = None
    schedules_path: Path | None = None
    drafts_path: Path | None = None
    trace_dir: Path | None = None
    inject_save_failure: bool = False


class AgentStepRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step: int
    call_id: str
    tool_name: str
    arguments: dict[str, Any]
    observation: ToolResult
    decision_basis: str


class AgentRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: AgentResult
    steps: list[AgentStepRecord]
    model_steps: int
    tool_calls: int
    completion_reason: str
    trace_error: str | None = None


class MaterialSchedulingAgent:
    def __init__(
        self,
        model: ModelClient,
        *,
        registry: ToolRegistry | None = None,
        config: AgentConfig | None = None,
        runtime: AgentRuntime | None = None,
        trace_writer: TraceWriter | None = None,
    ) -> None:
        self.model = model
        self.registry = registry or build_default_registry()
        self.config = config or AgentConfig()
        self.runtime = runtime or AgentRuntime()
        self.trace_writer = trace_writer or TraceWriter()

    @staticmethod
    def _canonical_call_key(call: ModelToolCall) -> str:
        arguments = json.dumps(
            call.arguments,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return f"{call.name}:{arguments}"

    def _runtime_kwargs(self, tool_name: str) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if tool_name == "get_material" and self.runtime.materials_path:
            kwargs["materials_path"] = self.runtime.materials_path
        elif tool_name == "check_material_rules":
            if self.runtime.materials_path:
                kwargs["materials_path"] = self.runtime.materials_path
            if self.runtime.rules_path:
                kwargs["rules_path"] = self.runtime.rules_path
        elif tool_name in {"query_slot", "find_alternative_slots"}:
            if self.runtime.schedules_path:
                kwargs["schedules_path"] = self.runtime.schedules_path
        elif tool_name == "save_schedule_draft":
            if self.runtime.drafts_path:
                kwargs["drafts_path"] = self.runtime.drafts_path
            kwargs["inject_failure"] = self.runtime.inject_save_failure
        return kwargs

    def _execute_registered_tool(
        self,
        tool: RegisteredTool,
        arguments: dict[str, Any],
    ) -> ToolResult:
        try:
            validated = tool.input_model.model_validate(arguments)
        except ValidationError as exc:
            return ToolResult(
                tool_name=tool.name,
                status=ToolStatus.INVALID_INPUT,
                summary="模型提供的工具参数未通过Schema校验。",
                error_code="TOOL_ARGUMENT_VALIDATION_ERROR",
                data={"validation_error": str(exc)},
            )

        kwargs = validated.model_dump(mode="python")
        kwargs.update(self._runtime_kwargs(tool.name))
        try:
            result = tool.handler(**kwargs)
        except Exception as exc:  # 防止单个工具异常击穿Agent运行循环。
            return ToolResult(
                tool_name=tool.name,
                status=ToolStatus.FAILURE,
                summary=f"工具发生未预期异常：{type(exc).__name__}",
                error_code="UNEXPECTED_TOOL_ERROR",
            )
        if not isinstance(result, ToolResult):
            return ToolResult(
                tool_name=tool.name,
                status=ToolStatus.FAILURE,
                summary="工具返回了非ToolResult结果。",
                error_code="INVALID_TOOL_RESULT",
            )
        return result

    def _execute_call(self, call: ModelToolCall) -> ToolResult:
        try:
            tool = self.registry.get(call.name)
        except ToolNotAllowedError:
            return ToolResult(
                tool_name=call.name,
                status=ToolStatus.FAILURE,
                summary=f"工具不在允许列表中：{call.name}",
                error_code="TOOL_NOT_ALLOWED",
            )
        return self._execute_registered_tool(tool, call.arguments)

    @staticmethod
    def _latest_observation(
        steps: list[AgentStepRecord],
        tool_name: str,
    ) -> ToolResult | None:
        for step in reversed(steps):
            if step.tool_name == tool_name:
                return step.observation
        return None

    def _validate_final_facts(
        self,
        result: AgentResult,
        request: SchedulingRequest,
        steps: list[AgentStepRecord],
    ) -> None:
        if result.request_id != request.request_id:
            raise ValueError("最终结果的request_id与输入不一致")
        if result.material_id != request.material_id:
            raise ValueError("最终结果的material_id与输入不一致")
        if result.requested_slot != request.requested_slot:
            raise ValueError("最终结果的requested_slot与输入不一致")

        forbidden_claims = ("已发布", "发布成功", "已经发布", "正式上线")
        if any(claim in result.summary for claim in forbidden_claims):
            raise ValueError("最终结果包含越权发布声明")

        review_observation = self._latest_observation(steps, "check_material_rules")
        if review_observation and review_observation.status == ToolStatus.SUCCESS:
            observed_review = review_observation.data.get("review_status")
            if observed_review and result.review_status.value != observed_review:
                raise ValueError("最终审核状态与规则工具观察不一致")
            observed_reasons = review_observation.data.get("risk_reasons", [])
            if set(result.risk_reasons) != set(observed_reasons):
                raise ValueError("最终风险原因与规则工具观察不一致")

        save_observation = self._latest_observation(steps, "save_schedule_draft")
        if result.draft_status in {DraftStatus.SAVED, DraftStatus.DUPLICATE}:
            if not save_observation or save_observation.status != ToolStatus.SUCCESS:
                raise ValueError("模型声称已保存草稿，但没有成功的保存工具观察")
            observed_status = save_observation.data.get("draft_status")
            observed_draft = save_observation.data.get("draft", {})
            if observed_status != result.draft_status.value:
                raise ValueError("最终草稿状态与保存工具观察不一致")
            if observed_draft.get("draft_id") != result.draft_id:
                raise ValueError("最终draft_id与保存工具观察不一致")
            if observed_draft.get("confirmation_status") != result.confirmation_status.value:
                raise ValueError("最终确认状态与保存工具观察不一致")
            if observed_draft.get("material_id") != request.material_id:
                raise ValueError("保存草稿的material_id与原始输入不一致")
            if observed_draft.get("requested_slot") != request.requested_slot.isoformat():
                raise ValueError("保存草稿的requested_slot与原始输入不一致")
            observed_suggestion = observed_draft.get("suggested_slot")
            result_suggestion = (
                result.suggested_slot.isoformat()
                if result.suggested_slot is not None
                else None
            )
            if observed_suggestion != result_suggestion:
                raise ValueError("最终建议时段与保存草稿不一致")
            if save_observation.data.get("published") is not False:
                raise ValueError("保存工具没有明确证明未执行真实发布")
        elif result.draft_status == DraftStatus.FAILED:
            if not save_observation or save_observation.status != ToolStatus.FAILURE:
                raise ValueError("模型声称保存失败，但没有失败的保存工具观察")
        elif save_observation and save_observation.status == ToolStatus.SUCCESS:
            raise ValueError("保存工具已成功，但模型声称未尝试保存")

        if (
            result.suggested_slot is not None
            and result.suggested_slot != request.requested_slot
        ):
            alternative_observation = self._latest_observation(
                steps, "find_alternative_slots"
            )
            if not alternative_observation or alternative_observation.status != ToolStatus.SUCCESS:
                raise ValueError("替代时段没有成功的查询工具观察支持")
            candidate_slots = {
                item.get("slot")
                for item in alternative_observation.data.get("candidates", [])
            }
            if result.suggested_slot.isoformat() not in candidate_slots:
                raise ValueError("建议时段不在工具返回的候选列表中")

    def _observed_review_status(self, steps: list[AgentStepRecord]) -> ReviewStatus:
        observation = self._latest_observation(steps, "check_material_rules")
        if observation and observation.status == ToolStatus.SUCCESS:
            raw_status = observation.data.get("review_status")
            try:
                return ReviewStatus(raw_status)
            except (ValueError, TypeError):
                pass
        material = self._latest_observation(steps, "get_material")
        if material and material.data.get("missing_fields"):
            return ReviewStatus.NEEDS_INFORMATION
        return ReviewStatus.NEEDS_INFORMATION

    def _terminal_result(
        self,
        request: SchedulingRequest,
        steps: list[AgentStepRecord],
        *,
        reason: str,
        task_status: TaskStatus,
    ) -> AgentResult:
        review_status = self._observed_review_status(steps)
        if review_status == ReviewStatus.BLOCKED:
            task_status = TaskStatus.BLOCKED

        review_observation = self._latest_observation(steps, "check_material_rules")
        risk_reasons = (
            review_observation.data.get("risk_reasons", [])
            if review_observation
            else []
        )
        save_observation = self._latest_observation(steps, "save_schedule_draft")

        draft_status = DraftStatus.NOT_ATTEMPTED
        draft_id = None
        suggested_slot = None
        confirmation_status = ConfirmationStatus.NOT_REQUIRED
        if save_observation:
            if save_observation.status == ToolStatus.SUCCESS:
                observed_status = save_observation.data.get("draft_status", "saved")
                draft_status = DraftStatus(observed_status)
                draft = save_observation.data.get("draft", {})
                draft_id = draft.get("draft_id")
                suggested_slot = draft.get("suggested_slot")
                confirmation_status = ConfirmationStatus(
                    draft.get("confirmation_status", "not_required")
                )
            elif save_observation.status == ToolStatus.FAILURE:
                draft_status = DraftStatus.FAILED

        if suggested_slot is None:
            alternative = self._latest_observation(steps, "find_alternative_slots")
            if alternative and alternative.status == ToolStatus.SUCCESS:
                candidates = alternative.data.get("candidates", [])
                if candidates:
                    suggested_slot = candidates[0].get("slot")
                    confirmation_status = ConfirmationStatus.PENDING_CONFIRMATION

        pending_items: list[str] = []
        if confirmation_status == ConfirmationStatus.PENDING_CONFIRMATION:
            pending_items.append("请确认候选时段或审核风险。")

        return AgentResult(
            request_id=request.request_id,
            material_id=request.material_id,
            review_status=review_status,
            risk_reasons=risk_reasons,
            requested_slot=request.requested_slot,
            suggested_slot=suggested_slot,
            confirmation_status=confirmation_status,
            pending_items=pending_items,
            draft_status=draft_status,
            draft_id=draft_id,
            task_status=task_status,
            summary=f"任务未正常完成：{reason}",
        )

    def _finalize_run(
        self,
        *,
        request: SchedulingRequest,
        result: AgentResult,
        steps: list[AgentStepRecord],
        model_steps: int,
        tool_calls: int,
        completion_reason: str,
        started_at: datetime,
    ) -> AgentRunResult:
        trace_error: str | None = None
        if self.runtime.trace_dir is not None:
            finished_at = datetime.now(BEIJING_TZ)
            try:
                trace_path = self.trace_writer.write(
                    trace_dir=self.runtime.trace_dir,
                    request=request.model_dump(mode="json"),
                    steps=[step.model_dump(mode="json") for step in steps],
                    final_output=result.model_dump(mode="json"),
                    completion_reason=completion_reason,
                    model_steps=model_steps,
                    tool_calls=tool_calls,
                    limits=self.config.model_dump(mode="json"),
                    started_at=started_at,
                    finished_at=finished_at,
                )
            except TraceWriteError as exc:
                trace_error = str(exc)
            else:
                result.trace_file = trace_path

        return AgentRunResult(
            result=result,
            steps=steps,
            model_steps=model_steps,
            tool_calls=tool_calls,
            completion_reason=completion_reason,
            trace_error=trace_error,
        )

    def run(self, request_data: SchedulingRequest | dict[str, Any]) -> AgentRunResult:
        started_at = datetime.now(BEIJING_TZ)
        request = (
            request_data
            if isinstance(request_data, SchedulingRequest)
            else SchedulingRequest.model_validate(request_data)
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": AGENT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    request.model_dump(mode="json"),
                    ensure_ascii=False,
                ),
            },
        ]
        steps: list[AgentStepRecord] = []
        call_counts: Counter[str] = Counter()
        tool_call_count = 0
        final_correction_count = 0

        for model_step in range(1, self.config.max_steps + 1):
            try:
                decision = self.model.decide(
                    messages,
                    self.registry.openai_tools(),
                )
            except ModelError as exc:
                result = self._terminal_result(
                    request,
                    steps,
                    reason=str(exc),
                    task_status=TaskStatus.FAILED,
                )
                return self._finalize_run(
                    request=request,
                    result=result,
                    steps=steps,
                    model_steps=model_step,
                    tool_calls=tool_call_count,
                    completion_reason="model_error",
                    started_at=started_at,
                )

            if decision.final_output is not None:
                try:
                    result = AgentResult.model_validate(decision.final_output)
                    self._validate_final_facts(result, request, steps)
                except (ValidationError, ValueError) as exc:
                    if (
                        final_correction_count < self.config.max_final_corrections
                        and model_step < self.config.max_steps
                    ):
                        final_correction_count += 1
                        messages.append(
                            {
                                "role": "assistant",
                                "content": decision.assistant_text
                                or json.dumps(
                                    decision.final_output,
                                    ensure_ascii=False,
                                ),
                            }
                        )
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "你刚才的最终JSON未通过结构或工具事实校验。"
                                    "请严格依据已有工具观察修正，只返回完整JSON对象，"
                                    "不要再次调用工具。校验错误摘要："
                                    f"{str(exc)[:1000]}"
                                ),
                            }
                        )
                        continue
                    result = self._terminal_result(
                        request,
                        steps,
                        reason="模型最终结果未通过结构或事实一致性校验",
                        task_status=TaskStatus.FAILED,
                    )
                    completion_reason = "invalid_final_output"
                else:
                    completion_reason = "model_finished"
                return self._finalize_run(
                    request=request,
                    result=result,
                    steps=steps,
                    model_steps=model_step,
                    tool_calls=tool_call_count,
                    completion_reason=completion_reason,
                    started_at=started_at,
                )

            if tool_call_count + len(decision.tool_calls) > self.config.max_tool_calls:
                result = self._terminal_result(
                    request,
                    steps,
                    reason="达到最大工具调用次数",
                    task_status=TaskStatus.INCOMPLETE,
                )
                return self._finalize_run(
                    request=request,
                    result=result,
                    steps=steps,
                    model_steps=model_step,
                    tool_calls=tool_call_count,
                    completion_reason="max_tool_calls",
                    started_at=started_at,
                )

            assistant_tool_calls = []
            for call in decision.tool_calls:
                assistant_tool_calls.append(
                    {
                        "id": call.call_id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(
                                call.arguments,
                                ensure_ascii=False,
                            ),
                        },
                    }
                )
            messages.append(
                {
                    "role": "assistant",
                    "content": decision.assistant_text,
                    "tool_calls": assistant_tool_calls,
                }
            )

            for call in decision.tool_calls:
                call_key = self._canonical_call_key(call)
                call_counts[call_key] += 1
                if call_counts[call_key] > self.config.max_identical_calls:
                    result = self._terminal_result(
                        request,
                        steps,
                        reason="重复工具调用超过上限",
                        task_status=TaskStatus.INCOMPLETE,
                    )
                    return self._finalize_run(
                        request=request,
                        result=result,
                        steps=steps,
                        model_steps=model_step,
                        tool_calls=tool_call_count,
                        completion_reason="repeated_tool_call",
                        started_at=started_at,
                    )

                observation = self._execute_call(call)
                tool_call_count += 1
                step_record = AgentStepRecord(
                    step=model_step,
                    call_id=call.call_id,
                    tool_name=call.name,
                    arguments=call.arguments,
                    observation=observation,
                    decision_basis=f"模型选择调用{call.name}以获取下一步所需事实。",
                )
                steps.append(step_record)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.call_id,
                        "name": call.name,
                        "content": json.dumps(
                            observation.model_dump(mode="json"),
                            ensure_ascii=False,
                        ),
                    }
                )

        result = self._terminal_result(
            request,
            steps,
            reason="达到最大决策步数",
            task_status=TaskStatus.INCOMPLETE,
        )
        return self._finalize_run(
            request=request,
            result=result,
            steps=steps,
            model_steps=self.config.max_steps,
            tool_calls=tool_call_count,
            completion_reason="max_steps",
            started_at=started_at,
        )

