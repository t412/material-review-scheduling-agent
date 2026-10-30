"""可审计、脱敏且原子写入的Agent Trace。"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.exceptions import TraceWriteError


SENSITIVE_KEY_MARKERS = (
    "api_key",
    "apikey",
    "authorization",
    "access_token",
    "refresh_token",
    "password",
    "secret",
)


def redact_sensitive_data(value: Any) -> Any:
    """递归脱敏常见凭据字段，不修改原始对象。"""

    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key).lower()
            if any(marker in normalized_key for marker in SENSITIVE_KEY_MARKERS):
                redacted[str(key)] = "[REDACTED]"
            else:
                redacted[str(key)] = redact_sensitive_data(item)
        return redacted
    if isinstance(value, list):
        return [redact_sensitive_data(item) for item in value]
    if isinstance(value, tuple):
        return [redact_sensitive_data(item) for item in value]
    return value


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    return safe[:80] or "request"


class TraceWriter:
    def write(
        self,
        *,
        trace_dir: Path,
        request: dict[str, Any],
        steps: list[dict[str, Any]],
        final_output: dict[str, Any],
        completion_reason: str,
        model_steps: int,
        tool_calls: int,
        limits: dict[str, Any],
        started_at: datetime,
        finished_at: datetime,
    ) -> Path:
        request_id = str(request.get("request_id", "request"))
        timestamp = finished_at.strftime("%Y%m%dT%H%M%S%f")
        run_id = f"{_safe_name(request_id)}-{timestamp}-{uuid4().hex[:8]}"
        trace_path = trace_dir / f"{run_id}.json"

        trace_steps: list[dict[str, Any]] = []
        for index, step in enumerate(steps):
            observation = step.get("observation", {})
            next_action = (
                steps[index + 1].get("tool_name", "unknown")
                if index + 1 < len(steps)
                else f"结束：{final_output.get('task_status', 'unknown')}"
            )
            trace_steps.append(
                {
                    "step": step.get("step"),
                    "call_id": step.get("call_id"),
                    "action": step.get("tool_name"),
                    "arguments": step.get("arguments", {}),
                    "observation": {
                        "status": observation.get("status"),
                        "summary": observation.get("summary"),
                        "error_code": observation.get("error_code"),
                        "data": observation.get("data", {}),
                    },
                    "next_action": next_action,
                    "decision_basis": step.get("decision_basis"),
                }
            )

        output_with_trace = dict(final_output)
        output_with_trace["trace_file"] = str(trace_path)
        payload = redact_sensitive_data(
            {
                "schema_version": "1.0",
                "run_id": run_id,
                "started_at": started_at.isoformat(),
                "finished_at": finished_at.isoformat(),
                "input": request,
                "limits": limits,
                "model_steps": model_steps,
                "tool_calls": tool_calls,
                "steps": trace_steps,
                "completion_reason": completion_reason,
                "final_output": output_with_trace,
                "notes": "仅记录可审计动作依据，不包含模型内部思维过程。",
            }
        )

        temporary_path: Path | None = None
        try:
            trace_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=trace_dir,
                prefix=f".{run_id}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                json.dump(payload, temporary_file, ensure_ascii=False, indent=2)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, trace_path)
        except OSError as exc:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise TraceWriteError(f"Trace写入失败：{type(exc).__name__}") from exc
        return trace_path

