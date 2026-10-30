from __future__ import annotations

from src.schemas import ToolStatus
from src.tools.material import get_material


def test_get_material_returns_complete_material() -> None:
    result = get_material("M01")

    assert result.status == ToolStatus.SUCCESS
    assert result.data["material"]["material_id"] == "M01"
    assert result.data["missing_fields"] == []


def test_get_material_reports_missing_metadata() -> None:
    result = get_material("M02")

    assert result.status == ToolStatus.SUCCESS
    assert result.data["missing_fields"] == ["copyright_owner"]


def test_get_material_returns_not_found() -> None:
    result = get_material("M404")

    assert result.status == ToolStatus.NOT_FOUND
    assert result.error_code == "MATERIAL_NOT_FOUND"


def test_get_material_rejects_empty_id() -> None:
    result = get_material("   ")

    assert result.status == ToolStatus.INVALID_INPUT
    assert result.error_code == "EMPTY_MATERIAL_ID"


def test_get_material_reports_broken_data_file(tmp_path) -> None:
    path = tmp_path / "materials.json"
    path.write_text("not-json", encoding="utf-8")

    result = get_material("M01", materials_path=path)

    assert result.status == ToolStatus.FAILURE
    assert result.error_code == "DATA_FILE_INVALID_JSON"

