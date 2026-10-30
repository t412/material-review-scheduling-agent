"""模型适配器统一接口与决策结构。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ModelToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: dict[str, Any]


class ModelDecision(BaseModel):
    """一次模型决策：调用一个或多个工具，或返回最终结构化结果。"""

    model_config = ConfigDict(extra="forbid")

    tool_calls: list[ModelToolCall] = Field(default_factory=list)
    final_output: dict[str, Any] | None = None
    assistant_text: str | None = None

    @model_validator(mode="after")
    def require_exactly_one_decision_mode(self) -> "ModelDecision":
        has_tools = bool(self.tool_calls)
        has_final = self.final_output is not None
        if has_tools == has_final:
            raise ValueError("模型必须在工具调用和最终输出之间二选一")
        return self


class ModelClient(ABC):
    @abstractmethod
    def decide(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelDecision:
        """根据对话与工具定义返回下一步动作。"""

