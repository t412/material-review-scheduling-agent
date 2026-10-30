"""只读JSON数据仓库。运行期草稿写入将在后续阶段单独实现。"""

from __future__ import annotations

import json
from json import JSONDecodeError
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from src.exceptions import (
    DataFileInvalidJsonError,
    DataFileNotFoundError,
    DataSchemaValidationError,
)


ModelT = TypeVar("ModelT", bound=BaseModel)


def load_model_list(path: Path, model_type: type[ModelT]) -> list[ModelT]:
    """读取JSON数组并逐项执行Pydantic校验。"""

    try:
        with path.open(encoding="utf-8") as file:
            payload = json.load(file)
    except FileNotFoundError as exc:
        raise DataFileNotFoundError(f"数据文件不存在：{path}") from exc
    except (JSONDecodeError, UnicodeDecodeError) as exc:
        raise DataFileInvalidJsonError(f"数据文件不是有效的UTF-8 JSON：{path}") from exc
    except OSError as exc:
        raise DataFileNotFoundError(f"无法读取数据文件：{path}") from exc

    if not isinstance(payload, list):
        raise DataSchemaValidationError(f"数据文件顶层必须是数组：{path}")

    try:
        return [model_type.model_validate(item) for item in payload]
    except ValidationError as exc:
        raise DataSchemaValidationError(f"数据结构校验失败：{path}；{exc}") from exc

