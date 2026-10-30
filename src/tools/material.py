"""素材读取工具。"""

from __future__ import annotations

from pathlib import Path

from src.exceptions import DataRepositoryError
from src.schemas import MaterialMetadata, ToolResult, ToolStatus
from src.storage.json_repository import load_model_list


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MATERIALS_PATH = PROJECT_ROOT / "data" / "materials.json"
REQUIRED_MATERIAL_FIELDS = (
    "title",
    "media_type",
    "source",
    "copyright_owner",
    "content_summary",
)


def find_missing_fields(material: MaterialMetadata) -> list[str]:
    """返回缺少或空白的必填元数据字段。"""

    missing: list[str] = []
    for field_name in REQUIRED_MATERIAL_FIELDS:
        value = getattr(material, field_name)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(field_name)
    return missing


def get_material(
    material_id: str,
    *,
    materials_path: Path = DEFAULT_MATERIALS_PATH,
) -> ToolResult:
    """按ID读取素材，并报告元数据完整性。"""

    normalized_id = material_id.strip()
    if not normalized_id:
        return ToolResult(
            tool_name="get_material",
            status=ToolStatus.INVALID_INPUT,
            summary="material_id不能为空。",
            error_code="EMPTY_MATERIAL_ID",
        )

    try:
        materials = load_model_list(materials_path, MaterialMetadata)
    except DataRepositoryError as exc:
        return ToolResult(
            tool_name="get_material",
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
            tool_name="get_material",
            status=ToolStatus.NOT_FOUND,
            summary=f"未找到素材：{normalized_id}",
            error_code="MATERIAL_NOT_FOUND",
            data={"material_id": normalized_id},
        )

    missing_fields = find_missing_fields(material)
    completeness = "信息完整" if not missing_fields else "存在缺失字段"
    return ToolResult(
        tool_name="get_material",
        status=ToolStatus.SUCCESS,
        summary=f"已读取素材{normalized_id}，{completeness}。",
        data={
            "material": material.model_dump(mode="json"),
            "missing_fields": missing_fields,
        },
    )

