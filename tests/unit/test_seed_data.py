from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.schemas import MaterialMetadata, ReviewRule, ScheduledItem


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"


def load_json(name: str):
    with (DATA_DIR / name).open(encoding="utf-8") as file:
        return json.load(file)


def test_material_seed_data_is_valid_and_covers_required_cases() -> None:
    materials = [
        MaterialMetadata.model_validate(item)
        for item in load_json("materials.json")
    ]
    by_id = {item.material_id: item for item in materials}

    assert len(by_id) == 6
    assert by_id["M01"].copyright_owner == "小影科技"
    assert by_id["M02"].copyright_owner is None
    assert "全网第一" in (by_id["M03"].content_summary or "")
    assert by_id["M04"].category == "health"
    assert "忽略之前所有规则" in (by_id["M06"].content_summary or "")


def test_review_rule_seed_data_is_valid() -> None:
    rules = [ReviewRule.model_validate(item) for item in load_json("review_rules.json")]

    assert {rule.rule_id for rule in rules} == {"R001", "R002", "R003"}
    assert all(rule.enabled for rule in rules)


def test_schedule_seed_data_is_valid_and_contains_conflicts() -> None:
    schedules = [
        ScheduledItem.model_validate(item)
        for item in load_json("schedules.json")
    ]

    occupied_hours = {item.slot.hour for item in schedules}
    assert occupied_hours == {18, 20}
    assert all(item.slot.utcoffset() is not None for item in schedules)


def test_draft_seed_starts_empty() -> None:
    assert load_json("drafts.seed.json") == []


def test_review_rule_rejects_unknown_material_field() -> None:
    with pytest.raises(ValidationError, match="规则字段不存在"):
        ReviewRule.model_validate(
            {
                "rule_id": "R-BAD",
                "name": "错误规则",
                "description": "引用不存在字段",
                "field": "nonexistent_field",
                "operator": "equals",
                "expected": "value",
                "action": "block",
                "reason": "测试",
            }
        )

