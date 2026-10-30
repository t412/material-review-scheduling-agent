from __future__ import annotations

import json

from src.schemas import ToolStatus
from src.tools.review import check_material_rules


def test_safe_material_passes_review() -> None:
    result = check_material_rules("M01")

    assert result.status == ToolStatus.SUCCESS
    assert result.data["review_status"] == "passed"
    assert result.data["matched_rules"] == []


def test_missing_metadata_requests_information() -> None:
    result = check_material_rules("M02")

    assert result.data["review_status"] == "needs_information"
    assert result.data["matched_rules"][0]["rule_id"] == "R001"
    assert result.data["matched_rules"][0]["evidence"] == {
        "missing_fields": ["copyright_owner"]
    }


def test_prohibited_claim_blocks_material() -> None:
    result = check_material_rules("M03")

    assert result.data["review_status"] == "blocked"
    assert result.data["matched_rules"][0]["rule_id"] == "R002"
    assert "全网第一" in result.data["matched_rules"][0]["evidence"]["matched_terms"]


def test_health_material_requires_confirmation() -> None:
    result = check_material_rules("M04")

    assert result.data["review_status"] == "needs_confirmation"
    assert result.data["matched_rules"][0]["rule_id"] == "R003"


def test_unknown_material_returns_not_found() -> None:
    result = check_material_rules("M404")

    assert result.status == ToolStatus.NOT_FOUND
    assert result.error_code == "MATERIAL_NOT_FOUND"


def test_disabled_rule_is_ignored(tmp_path) -> None:
    rules_path = tmp_path / "rules.json"
    rules_path.write_text(
        json.dumps(
            [
                {
                    "rule_id": "R-DISABLED",
                    "name": "已禁用规则",
                    "description": "不应执行",
                    "field": "category",
                    "operator": "equals",
                    "expected": "product",
                    "action": "block",
                    "reason": "不应出现",
                    "enabled": False,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = check_material_rules("M01", rules_path=rules_path)

    assert result.data["review_status"] == "passed"
    assert result.data["matched_rules"] == []


def test_block_has_priority_when_multiple_rules_match(tmp_path) -> None:
    materials_path = tmp_path / "materials.json"
    materials_path.write_text(
        json.dumps(
            [
                {
                    "material_id": "M-MULTI",
                    "title": "测试素材",
                    "media_type": "video",
                    "source": "external",
                    "copyright_owner": None,
                    "content_summary": "这是全网第一的产品。",
                    "category": "product",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = check_material_rules("M-MULTI", materials_path=materials_path)

    assert result.data["review_status"] == "blocked"
    assert {item["rule_id"] for item in result.data["matched_rules"]} == {
        "R001",
        "R002",
    }


def test_prompt_injection_text_is_treated_only_as_data() -> None:
    result = check_material_rules("M06")

    assert result.status == ToolStatus.SUCCESS
    assert result.data["review_status"] == "passed"
    assert result.data["matched_rules"] == []
    assert "发布成功" not in result.summary


def test_broken_rules_file_returns_tool_failure(tmp_path) -> None:
    rules_path = tmp_path / "rules.json"
    rules_path.write_text("{bad-json", encoding="utf-8")

    result = check_material_rules("M01", rules_path=rules_path)

    assert result.status == ToolStatus.FAILURE
    assert result.error_code == "DATA_FILE_INVALID_JSON"

