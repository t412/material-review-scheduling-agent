"""离线确定性Mock模型，仅用于流程和测试，不证明真实模型能力。"""

from __future__ import annotations

import json
from typing import Any

from src.models.base import ModelClient, ModelDecision, ModelToolCall


class OfflineMockModel(ModelClient):
    def __init__(self) -> None:
        self._call_sequence = 0

    def _tool_call(self, name: str, arguments: dict[str, Any]) -> ModelDecision:
        self._call_sequence += 1
        return ModelDecision(
            tool_calls=[
                ModelToolCall(
                    call_id=f"mock-call-{self._call_sequence}",
                    name=name,
                    arguments=arguments,
                )
            ]
        )

    @staticmethod
    def _parse_content(message: dict[str, Any]) -> dict[str, Any]:
        content = message.get("content", {})
        if isinstance(content, dict):
            return content
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _request(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        for message in messages:
            if message.get("role") == "user":
                return self._parse_content(message)
        return {}

    def _observations(self, messages: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        observations: dict[str, dict[str, Any]] = {}
        for message in messages:
            if message.get("role") == "tool" and message.get("name"):
                observations[str(message["name"])] = self._parse_content(message)
        return observations

    @staticmethod
    def _base_final(
        request: dict[str, Any],
        *,
        review_status: str,
        draft_status: str,
        task_status: str,
        summary: str,
    ) -> dict[str, Any]:
        return {
            "request_id": request.get("request_id", "UNKNOWN"),
            "material_id": request.get("material_id", "UNKNOWN"),
            "review_status": review_status,
            "risk_reasons": [],
            "requested_slot": request.get("requested_slot"),
            "suggested_slot": None,
            "confirmation_status": "not_required",
            "pending_items": [],
            "draft_status": draft_status,
            "draft_id": None,
            "task_status": task_status,
            "summary": summary,
        }

    def decide(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelDecision:
        del tools  # Mock遵循固定白名单，不读取外部工具描述。
        request = self._request(messages)
        observations = self._observations(messages)

        if "get_material" not in observations:
            return self._tool_call(
                "get_material",
                {"material_id": request.get("material_id", "")},
            )

        material_result = observations["get_material"]
        if material_result.get("status") != "success":
            return ModelDecision(
                final_output=self._base_final(
                    request,
                    review_status="needs_information",
                    draft_status="not_attempted",
                    task_status="incomplete",
                    summary="素材读取失败或素材不存在，需要补充信息。",
                )
            )
        missing_fields = material_result.get("data", {}).get("missing_fields", [])
        if missing_fields:
            final = self._base_final(
                request,
                review_status="needs_information",
                draft_status="not_attempted",
                task_status="incomplete",
                summary="素材信息不完整，需要补充后继续。",
            )
            final["risk_reasons"] = [f"缺少字段：{', '.join(missing_fields)}"]
            final["pending_items"] = [f"补充字段：{', '.join(missing_fields)}"]
            return ModelDecision(final_output=final)

        if "check_material_rules" not in observations:
            return self._tool_call(
                "check_material_rules",
                {"material_id": request.get("material_id", "")},
            )

        review_result = observations["check_material_rules"]
        review_data = review_result.get("data", {})
        review_status = review_data.get("review_status", "needs_information")
        if review_result.get("status") != "success":
            return ModelDecision(
                final_output=self._base_final(
                    request,
                    review_status="needs_information",
                    draft_status="not_attempted",
                    task_status="failed",
                    summary="审核工具失败，任务未完成。",
                )
            )
        if review_status == "blocked":
            final = self._base_final(
                request,
                review_status="blocked",
                draft_status="not_attempted",
                task_status="blocked",
                summary="素材命中阻断规则，未保存草稿。",
            )
            final["risk_reasons"] = review_data.get("risk_reasons", [])
            return ModelDecision(final_output=final)
        if review_status == "needs_information":
            return ModelDecision(
                final_output=self._base_final(
                    request,
                    review_status="needs_information",
                    draft_status="not_attempted",
                    task_status="incomplete",
                    summary="审核发现信息不足，需要补充后继续。",
                )
            )

        if "query_slot" not in observations:
            return self._tool_call(
                "query_slot",
                {"slot": request.get("requested_slot")},
            )

        slot_result = observations["query_slot"]
        if slot_result.get("status") != "success":
            return ModelDecision(
                final_output=self._base_final(
                    request,
                    review_status=review_status,
                    draft_status="not_attempted",
                    task_status="failed",
                    summary="时段查询工具失败，任务未完成。",
                )
            )
        occupied = slot_result.get("data", {}).get("availability") == "occupied"
        if occupied and "find_alternative_slots" not in observations:
            return self._tool_call(
                "find_alternative_slots",
                {
                    "preferred_slot": request.get("requested_slot"),
                    "earliest_time": request.get("constraints", {}).get(
                        "earliest_time", "09:00:00"
                    ),
                    "latest_time": request.get("constraints", {}).get(
                        "latest_time", "22:00:00"
                    ),
                    "limit": 3,
                    "interval_minutes": 60,
                },
            )

        suggested_slot = None
        confirmation_status = (
            "pending_confirmation"
            if review_status == "needs_confirmation"
            else "not_required"
        )
        if occupied:
            alternative_result = observations.get("find_alternative_slots", {})
            if alternative_result.get("status") != "success":
                return ModelDecision(
                    final_output=self._base_final(
                        request,
                        review_status=review_status,
                        draft_status="not_attempted",
                        task_status="failed",
                        summary="替代时段查询工具失败，任务未完成。",
                    )
                )
            candidates = alternative_result.get("data", {}).get("candidates", [])
            if not candidates:
                return ModelDecision(
                    final_output=self._base_final(
                        request,
                        review_status=review_status,
                        draft_status="not_attempted",
                        task_status="incomplete",
                        summary="没有可用替代时段，任务未完成。",
                    )
                )
            suggested_slot = candidates[0]["slot"]
            confirmation_status = "pending_confirmation"

        if "save_schedule_draft" not in observations:
            return self._tool_call(
                "save_schedule_draft",
                {
                    "request": request,
                    "review_status": review_status,
                    "suggested_slot": suggested_slot,
                    "confirmation_status": confirmation_status,
                },
            )

        save_result = observations["save_schedule_draft"]
        if save_result.get("status") != "success":
            return ModelDecision(
                final_output=self._base_final(
                    request,
                    review_status=review_status,
                    draft_status="failed",
                    task_status="failed",
                    summary="草稿保存失败，未执行真实发布。",
                )
            )

        saved_draft = save_result.get("data", {}).get("draft", {})
        pending = saved_draft.get("confirmation_status") == "pending_confirmation"
        final = self._base_final(
            request,
            review_status=review_status,
            draft_status=save_result.get("data", {}).get("draft_status", "saved"),
            task_status="awaiting_confirmation" if pending else "completed",
            summary=(
                "候选排期草稿已保存，等待用户确认；未执行真实发布。"
                if pending
                else "排期草稿已保存；未执行真实发布。"
            ),
        )
        final.update(
            {
                "suggested_slot": saved_draft.get("suggested_slot"),
                "confirmation_status": saved_draft.get(
                    "confirmation_status", "not_required"
                ),
                "pending_items": (
                    ["请确认候选时段或审核风险。"] if pending else []
                ),
                "draft_id": saved_draft.get("draft_id"),
                "risk_reasons": review_data.get("risk_reasons", []),
            }
        )
        return ModelDecision(final_output=final)

