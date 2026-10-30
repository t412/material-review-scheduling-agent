from __future__ import annotations

import pytest

from src.exceptions import ToolNotAllowedError
from src.tools.registry import build_default_registry


def test_default_registry_contains_only_expected_tools() -> None:
    registry = build_default_registry()

    assert registry.names == {
        "get_material",
        "check_material_rules",
        "query_slot",
        "find_alternative_slots",
        "save_schedule_draft",
    }
    assert "publish" not in registry.names


def test_registry_rejects_unknown_or_publish_tool() -> None:
    registry = build_default_registry()

    with pytest.raises(ToolNotAllowedError):
        registry.get("publish")


def test_openai_tool_definitions_have_json_schema() -> None:
    definitions = build_default_registry().openai_tools()

    assert len(definitions) == 5
    assert all(item["type"] == "function" for item in definitions)
    assert all(item["function"]["parameters"]["type"] == "object" for item in definitions)

