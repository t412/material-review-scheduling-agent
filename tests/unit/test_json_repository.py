from __future__ import annotations

import json

import pytest

from src.exceptions import (
    DataFileInvalidJsonError,
    DataFileNotFoundError,
    DataSchemaValidationError,
)
from src.schemas import MaterialMetadata
from src.storage.json_repository import load_model_list


def test_load_model_list_reads_valid_utf8_json(tmp_path) -> None:
    path = tmp_path / "materials.json"
    path.write_text(
        json.dumps([{"material_id": "M01", "title": "中文标题"}], ensure_ascii=False),
        encoding="utf-8",
    )

    records = load_model_list(path, MaterialMetadata)

    assert records[0].title == "中文标题"


def test_load_model_list_reports_missing_file(tmp_path) -> None:
    with pytest.raises(DataFileNotFoundError):
        load_model_list(tmp_path / "missing.json", MaterialMetadata)


def test_load_model_list_reports_invalid_json(tmp_path) -> None:
    path = tmp_path / "invalid.json"
    path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(DataFileInvalidJsonError):
        load_model_list(path, MaterialMetadata)


def test_load_model_list_requires_top_level_array(tmp_path) -> None:
    path = tmp_path / "object.json"
    path.write_text('{"material_id": "M01"}', encoding="utf-8")

    with pytest.raises(DataSchemaValidationError):
        load_model_list(path, MaterialMetadata)


def test_load_model_list_reports_schema_error(tmp_path) -> None:
    path = tmp_path / "invalid-schema.json"
    path.write_text('[{"material_id": ""}]', encoding="utf-8")

    with pytest.raises(DataSchemaValidationError):
        load_model_list(path, MaterialMetadata)

