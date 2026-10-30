"""基于确定性规则的素材审核工具。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.exceptions import DataRepositoryError
from src.schemas import (
    MaterialMetadata,
    ReviewRule,
    ReviewStatus,
    RuleAction,
    RuleOperator,
    ToolResult,
    ToolStatus,
)
from src.storage.json_repository import load_model_list
from src.tools.material import DEFAULT_MATERIALS_PATH


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RULES_PATH = PROJECT_ROOT / "data" / "review_rules.json"


def _material_field(material: MaterialMetadata, field_name: str) -> Any:
    if field_name not in MaterialMetadata.model_fields:
        return None
    return getattr(material, field_name)


def _match_rule(material: MaterialMetadata, rule: ReviewRule) -> dict[str, Any] | None:
    if not rule.enabled:
        return None

    if rule.operator == RuleOperator.REQUIRED_FIELDS:
        expected_fields = [str(item) for item in rule.expected]
        missing_fields = []
        for field_name in expected_fields:
            value = _material_field(material, field_name)
            if value is None or (isinstance(value, str) and not value.strip()):
                missing_fields.append(field_name)
        if not missing_fields:
            return None
        evidence: Any = {"missing_fields": missing_fields}
    elif rule.operator == RuleOperator.CONTAINS_ANY:
        value = _material_field(material, rule.field)
        if not isinstance(value, str):
            return None
        matched_terms = [str(item) for item in rule.expected if str(item) in value]
        if not matched_terms:
            return None
        evidence = {"field": rule.field, "matched_terms": matched_terms}
    elif rule.operator == RuleOperator.EQUALS:
        value = _material_field(material, rule.field)
        if value != rule.expected:
            return None
        evidence = {"field": rule.field, "value": value}
    elif rule.operator == RuleOperator.IN:
        value = _material_field(material, rule.field)
        if value not in rule.expected:
            return None
        evidence = {"field": rule.field, "value": value}
    else:  # 枚举校验后理论上不可达，保留防御性分支。
        return None

    return {
        "rule_id": rule.rule_id,
        "rule_name": rule.name,
        "action": rule.action.value,
        "reason": rule.reason,
        "evidence": evidence,
    }


def _aggregate_review_status(matches: list[dict[str, Any]]) -> ReviewStatus:
    actions = {item["action"] for item in matches}
    if RuleAction.BLOCK.value in actions:
        return ReviewStatus.BLOCKED
    if RuleAction.REQUEST_INFORMATION.value in actions:
        return ReviewStatus.NEEDS_INFORMATION
    if RuleAction.REQUEST_CONFIRMATION.value in actions:
        return ReviewStatus.NEEDS_CONFIRMATION
    return ReviewStatus.PASSED


def check_material_rules(
    material_id: str,
    *,
    materials_path: Path = DEFAULT_MATERIALS_PATH,
    rules_path: Path = DEFAULT_RULES_PATH,
) -> ToolResult:
    """检查素材规则并返回命中规则、事实证据和汇总状态。"""

    normalized_id = material_id.strip()
    if not normalized_id:
        return ToolResult(
            tool_name="check_material_rules",
            status=ToolStatus.INVALID_INPUT,
            summary="material_id不能为空。",
            error_code="EMPTY_MATERIAL_ID",
        )

    try:
        materials = load_model_list(materials_path, MaterialMetadata)
        rules = load_model_list(rules_path, ReviewRule)
    except DataRepositoryError as exc:
        return ToolResult(
            tool_name="check_material_rules",
            status=ToolStatus.FAILURE,
            summary=str(exc),
            error_code=exc.error_code,
        )

    material = next(
        (item for item in materials if item.material_id == normalized_id),
        None,
    )
    if material is None:
        return ToolResult(
            tool_name="check_material_rules",
            status=ToolStatus.NOT_FOUND,
            summary=f"未找到素材：{normalized_id}",
            error_code="MATERIAL_NOT_FOUND",
            data={"material_id": normalized_id},
        )

    matches = [
        match
        for rule in rules
        if (match := _match_rule(material, rule)) is not None
    ]
    review_status = _aggregate_review_status(matches)
    risk_reasons = list(dict.fromkeys(item["reason"] for item in matches))

    return ToolResult(
        tool_name="check_material_rules",
        status=ToolStatus.SUCCESS,
        summary=(
            f"素材{normalized_id}审核结果：{review_status.value}；"
            f"命中{len(matches)}条规则。"
        ),
        data={
            "material_id": normalized_id,
            "review_status": review_status.value,
            "matched_rules": matches,
            "risk_reasons": risk_reasons,
        },
    )

