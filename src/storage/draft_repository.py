"""支持幂等、锁和原子替换的JSON草稿仓库。"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

from src.exceptions import DataLockTimeoutError, DataRepositoryError, DataWriteError
from src.schemas import DraftRecord
from src.storage.json_repository import load_model_list


class FileLock:
    """使用O_EXCL锁文件协调同机多线程和多进程写入。"""

    def __init__(self, path: Path, timeout_seconds: float = 3.0) -> None:
        self.path = path
        self.timeout_seconds = timeout_seconds
        self._file_descriptor: int | None = None

    def __enter__(self) -> "FileLock":
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            try:
                self._file_descriptor = os.open(
                    self.path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
                os.write(self._file_descriptor, str(os.getpid()).encode("ascii"))
                return self
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise DataLockTimeoutError(f"获取草稿文件锁超时：{self.path}")
                time.sleep(0.02)
            except OSError as exc:
                raise DataWriteError(f"无法创建草稿文件锁：{self.path}") from exc

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self._file_descriptor is not None:
            os.close(self._file_descriptor)
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            # 写入已完成时，残留锁不应覆盖原始业务异常。
            pass


class DraftRepository:
    def __init__(self, path: Path, *, lock_timeout_seconds: float = 3.0) -> None:
        self.path = path
        self.lock_path = path.with_suffix(path.suffix + ".lock")
        self.lock_timeout_seconds = lock_timeout_seconds

    def _load_existing(self) -> list[DraftRecord]:
        if not self.path.exists():
            return []
        return load_model_list(self.path, DraftRecord)

    def _atomic_write(self, drafts: list[DraftRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                json.dump(
                    [item.model_dump(mode="json") for item in drafts],
                    temporary_file,
                    ensure_ascii=False,
                    indent=2,
                )
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, self.path)
        except OSError as exc:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise DataWriteError(f"草稿文件写入失败：{self.path}") from exc

    def save(self, draft: DraftRecord) -> tuple[DraftRecord, bool]:
        """保存草稿；返回记录以及是否命中已有幂等记录。"""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(self.lock_path, self.lock_timeout_seconds):
            drafts = self._load_existing()
            existing = next(
                (
                    item
                    for item in drafts
                    if item.idempotency_key == draft.idempotency_key
                ),
                None,
            )
            if existing is not None:
                return existing, True
            drafts.append(draft)
            self._atomic_write(drafts)
            return draft, False

