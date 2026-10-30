"""OpenAI兼容Chat Completions工具调用适配器。"""

from __future__ import annotations

import json
import os
import re
from json import JSONDecodeError
from typing import Any

from openai import OpenAI

from src.exceptions import (
    ModelConfigurationError,
    ModelInvocationError,
    ModelResponseError,
)
from src.models.base import ModelClient, ModelDecision, ModelToolCall


class OpenAICompatibleModel(ModelClient):
    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.model = (model or os.getenv("OPENAI_MODEL", "")).strip()
        if not self.model:
            raise ModelConfigurationError("缺少OPENAI_MODEL或model参数")

        self.base_url = (base_url or os.getenv("OPENAI_BASE_URL", "")).strip()
        self.request_options: dict[str, Any] = {}
        if "api.deepseek.com" in self.base_url.lower():
            # DeepSeek思考模式的多轮工具调用需要回传reasoning_content。
            # 当前统一消息协议不保留供应商私有字段，因此按官方示例关闭思考模式。
            self.request_options["extra_body"] = {
                "thinking": {"type": "disabled"}
            }
            self.request_options["response_format"] = {"type": "json_object"}

        if client is not None:
            self.client = client
            return

        resolved_key = (api_key or os.getenv("OPENAI_API_KEY", "")).strip()
        if not resolved_key:
            raise ModelConfigurationError("缺少OPENAI_API_KEY或api_key参数")
        client_kwargs: dict[str, Any] = {"api_key": resolved_key}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url
        self.client = OpenAI(**client_kwargs)

    @staticmethod
    def _safe_invocation_error(exc: Exception) -> str:
        details = [type(exc).__name__]
        status_code = getattr(exc, "status_code", None)
        if isinstance(status_code, int):
            details.append(f"HTTP {status_code}")
        error_code = getattr(exc, "code", None)
        if isinstance(error_code, str) and re.fullmatch(
            r"[A-Za-z0-9_.-]{1,80}", error_code
        ):
            details.append(f"code={error_code}")
        return "，".join(details)

    @staticmethod
    def _parse_tool_arguments(raw_arguments: Any, tool_name: str) -> dict[str, Any]:
        if isinstance(raw_arguments, dict):
            arguments = raw_arguments
        else:
            try:
                arguments = json.loads(raw_arguments or "{}")
            except (JSONDecodeError, TypeError) as exc:
                raise ModelResponseError(
                    f"工具{tool_name}的参数不是有效JSON"
                ) from exc
        if not isinstance(arguments, dict):
            raise ModelResponseError(f"工具{tool_name}的参数必须是JSON对象")
        return arguments

    @staticmethod
    def _parse_final_output(content: Any) -> dict[str, Any]:
        if not isinstance(content, str) or not content.strip():
            raise ModelResponseError("模型既未调用工具，也未返回最终内容")
        normalized = content.strip()
        if normalized.startswith("```") and normalized.endswith("```"):
            first_newline = normalized.find("\n")
            if first_newline != -1:
                normalized = normalized[first_newline + 1 : -3].strip()
        try:
            parsed = json.loads(normalized)
        except JSONDecodeError as exc:
            raise ModelResponseError("模型最终输出不是有效JSON对象") from exc
        if not isinstance(parsed, dict):
            raise ModelResponseError("模型最终输出必须是JSON对象")
        return parsed

    def decide(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelDecision:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                **self.request_options,
            )
        except Exception as exc:
            safe_error = self._safe_invocation_error(exc)
            raise ModelInvocationError(f"模型服务调用失败：{safe_error}") from exc

        if not getattr(response, "choices", None):
            raise ModelResponseError("模型响应不包含choices")
        message = getattr(response.choices[0], "message", None)
        if message is None:
            raise ModelResponseError("模型响应不包含message")

        raw_tool_calls = getattr(message, "tool_calls", None) or []
        if raw_tool_calls:
            parsed_calls: list[ModelToolCall] = []
            for raw_call in raw_tool_calls:
                function = getattr(raw_call, "function", None)
                name = getattr(function, "name", "") if function else ""
                if not name:
                    raise ModelResponseError("模型工具调用缺少工具名称")
                parsed_calls.append(
                    ModelToolCall(
                        call_id=getattr(raw_call, "id", "") or f"call-{len(parsed_calls) + 1}",
                        name=name,
                        arguments=self._parse_tool_arguments(
                            getattr(function, "arguments", "{}"),
                            name,
                        ),
                    )
                )
            return ModelDecision(
                tool_calls=parsed_calls,
                assistant_text=getattr(message, "content", None),
            )

        content = getattr(message, "content", None)
        return ModelDecision(
            final_output=self._parse_final_output(content),
            assistant_text=content,
        )

