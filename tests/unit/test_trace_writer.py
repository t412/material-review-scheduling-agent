from __future__ import annotations

import json
from datetime import datetime

from src.schemas import BEIJING_TZ
from src.trace import TraceWriter, redact_sensitive_data


def test_recursive_redaction_hides_common_credential_fields() -> None:
    source = {
        "OPENAI_API_KEY": "sk-secret",
        "nested": {
            "authorization": "Bearer token",
            "password": "123456",
            "safe": "visible",
        },
    }

    redacted = redact_sensitive_data(source)

    assert redacted["OPENAI_API_KEY"] == "[REDACTED]"
    assert redacted["nested"]["authorization"] == "[REDACTED]"
    assert redacted["nested"]["password"] == "[REDACTED]"
    assert redacted["nested"]["safe"] == "visible"
    assert source["OPENAI_API_KEY"] == "sk-secret"


def test_trace_writer_redacts_payload_and_records_no_internal_reasoning(tmp_path) -> None:
    now = datetime.now(BEIJING_TZ)
    path = TraceWriter().write(
        trace_dir=tmp_path,
        request={"request_id": "REQ/unsafe", "api_key": "secret"},
        steps=[
            {
                "step": 1,
                "call_id": "call-1",
                "tool_name": "get_material",
                "arguments": {"material_id": "M01", "access_token": "token"},
                "observation": {
                    "status": "success",
                    "summary": "ok",
                    "data": {},
                    "error_code": None,
                },
                "decision_basis": "读取素材以获得审核事实。",
            }
        ],
        final_output={"task_status": "completed"},
        completion_reason="model_finished",
        model_steps=2,
        tool_calls=1,
        limits={"max_steps": 8},
        started_at=now,
        finished_at=now,
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload["input"]["api_key"] == "[REDACTED]"
    assert payload["steps"][0]["arguments"]["access_token"] == "[REDACTED]"
    assert "secret" not in serialized
    assert "Bearer" not in serialized
    assert "chain_of_thought" not in serialized
    assert "/" not in path.name

