"""模型可见工具白名单及其JSON Schema。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

from src.exceptions import ToolNotAllowedError
from src.schemas import (
    AlternativeSlotQuery,
    DraftSaveInput,
    SlotQueryInput,
)
from src.tools.draft import save_schedule_draft
from src.tools.material import get_material
from src.tools.review import check_material_rules
from src.tools.schedule import find_alternative_slots, query_slot


class MaterialIdInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    material_id: str = Field(min_length=1, max_length=100)


@dataclass(frozen=True)
class RegisteredTool:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: Callable[..., Any]

    def as_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_model.model_json_schema(),
            },
        }


class ToolRegistry:
    def __init__(self, tools: list[RegisteredTool]) -> None:
        self._tools = {tool.name: tool for tool in tools}
        if len(self._tools) != len(tools):
            raise ValueError("工具名称不能重复")

    @property
    def names(self) -> set[str]:
        return set(self._tools)

    def get(self, name: str) -> RegisteredTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolNotAllowedError(f"工具不在白名单中：{name}") from exc

    def openai_tools(self) -> list[dict[str, Any]]:
        return [tool.as_openai_tool() for tool in self._tools.values()]


def build_default_registry() -> ToolRegistry:
    return ToolRegistry(
        [
            RegisteredTool(
                name="get_material",
                description="按素材ID读取元数据并报告缺失字段。",
                input_model=MaterialIdInput,
                handler=get_material,
            ),
            RegisteredTool(
                name="check_material_rules",
                description="依据审核规则检查素材并返回风险证据。",
                input_model=MaterialIdInput,
                handler=check_material_rules,
            ),
            RegisteredTool(
                name="query_slot",
                description="查询一个带时区的发布时间是否可用。",
                input_model=SlotQueryInput,
                handler=query_slot,
            ),
            RegisteredTool(
                name="find_alternative_slots",
                description="查询同一天范围内的可用候选时段，候选均需确认。",
                input_model=AlternativeSlotQuery,
                handler=find_alternative_slots,
            ),
            RegisteredTool(
                name="save_schedule_draft",
                description="幂等保存排期草稿；只保存草稿，不执行真实发布。",
                input_model=DraftSaveInput,
                handler=save_schedule_draft,
            ),
        ]
    )

