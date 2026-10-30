"""项目内部可预期异常。"""

from __future__ import annotations


class DataRepositoryError(Exception):
    """数据仓库错误基类，包含稳定的机器可读错误码。"""

    error_code = "DATA_REPOSITORY_ERROR"


class DataFileNotFoundError(DataRepositoryError):
    error_code = "DATA_FILE_NOT_FOUND"


class DataFileInvalidJsonError(DataRepositoryError):
    error_code = "DATA_FILE_INVALID_JSON"


class DataSchemaValidationError(DataRepositoryError):
    error_code = "DATA_SCHEMA_INVALID"


class DataWriteError(DataRepositoryError):
    error_code = "DATA_WRITE_ERROR"


class DataLockTimeoutError(DataRepositoryError):
    error_code = "DATA_LOCK_TIMEOUT"


class ModelError(Exception):
    """模型适配层错误基类。"""


class ModelConfigurationError(ModelError):
    """模型环境变量或初始化参数缺失。"""


class ModelInvocationError(ModelError):
    """模型服务调用失败。"""


class ModelResponseError(ModelError):
    """模型响应为空或格式不可解析。"""


class ToolNotAllowedError(Exception):
    """模型尝试调用白名单以外的工具。"""


class TraceWriteError(Exception):
    """Trace文件无法安全写入。"""

