"""使用真实工具调用模型生成三条Live输出与Trace。"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agent import AgentRuntime, MaterialSchedulingAgent  # noqa: E402
from src.models.openai_compatible import OpenAICompatibleModel  # noqa: E402


OUTPUT_ROOT = PROJECT_ROOT / "examples" / "live-model"
TEMP_ROOT = PROJECT_ROOT / "runtime" / "example-generation"
CASES = (
    (
        "live-01-normal",
        {
            "request_id": "LIVE-01-NORMAL",
            "material_id": "M01",
            "requested_slot": "2026-11-02T17:00:00+08:00",
            "slot_requirement": "hard",
            "user_confirmed_alternative": False,
            "constraints": {
                "allowed_date": "2026-11-02",
                "earliest_time": "17:00:00",
                "latest_time": "21:00:00",
            },
        },
        "completed",
        {"get_material", "check_material_rules", "query_slot", "save_schedule_draft"},
        set(),
    ),
    (
        "live-02-slot-conflict",
        {
            "request_id": "LIVE-02-CONFLICT",
            "material_id": "M01",
            "requested_slot": "2026-11-02T18:00:00+08:00",
            "slot_requirement": "hard",
            "user_confirmed_alternative": False,
            "constraints": {
                "allowed_date": "2026-11-02",
                "earliest_time": "17:00:00",
                "latest_time": "21:00:00",
            },
        },
        "awaiting_confirmation",
        {
            "get_material",
            "check_material_rules",
            "query_slot",
            "find_alternative_slots",
            "save_schedule_draft",
        },
        set(),
    ),
    (
        "live-03-rule-risk",
        {
            "request_id": "LIVE-03-RULE-RISK",
            "material_id": "M03",
            "requested_slot": "2026-11-02T17:00:00+08:00",
            "slot_requirement": "hard",
            "user_confirmed_alternative": False,
            "constraints": {
                "allowed_date": "2026-11-02",
                "earliest_time": "17:00:00",
                "latest_time": "21:00:00",
            },
        },
        "blocked",
        {"get_material", "check_material_rules"},
        {"query_slot", "find_alternative_slots", "save_schedule_draft"},
    ),
)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def export_run(case_dir: Path, request: dict[str, Any], run) -> None:
    if run.result.trace_file is None:
        raise RuntimeError("Live运行没有生成Trace")
    trace = read_json(run.result.trace_file)
    trace["final_output"]["trace_file"] = "trace.json"
    output_result = run.result.model_dump(mode="json")
    output_result["trace_file"] = "trace.json"

    write_json(case_dir / "input.json", request)
    write_json(case_dir / "trace.json", trace)
    write_json(
        case_dir / "output.json",
        {
            "result": output_result,
            "completion_reason": run.completion_reason,
            "model_steps": run.model_steps,
            "tool_calls": run.tool_calls,
            "trace_error": run.trace_error,
        },
    )


def main() -> int:
    model_name = os.getenv("OPENAI_MODEL", "").strip()
    if not os.getenv("OPENAI_API_KEY", "").strip() or not model_name:
        print("缺少OPENAI_API_KEY或OPENAI_MODEL。", file=sys.stderr)
        return 2

    TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="live-", dir=TEMP_ROOT) as temporary:
        temporary_root = Path(temporary)
        staging_root = temporary_root / "validated-output"
        for (
            case_name,
            request,
            expected_status,
            required_tools,
            forbidden_tools,
        ) in CASES:
            runtime_dir = temporary_root / case_name
            agent = MaterialSchedulingAgent(
                OpenAICompatibleModel(),
                runtime=AgentRuntime(
                    drafts_path=runtime_dir / "drafts" / "drafts.json",
                    trace_dir=runtime_dir / "traces",
                ),
            )
            run = agent.run(request)
            case_dir = staging_root / case_name
            export_run(case_dir, request, run)

            called_tools = {step.tool_name for step in run.steps}
            if run.completion_reason != "model_finished":
                failures.append(
                    f"{case_name}: 结束原因应为model_finished，"
                    f"实际{run.completion_reason}"
                )
                failures.append(f"{case_name}: {run.result.summary}")
            if run.trace_error is not None:
                failures.append(f"{case_name}: Trace写入失败：{run.trace_error}")
            if run.result.task_status.value != expected_status:
                failures.append(
                    f"{case_name}: 期望{expected_status}，实际{run.result.task_status.value}"
                )
            missing_tools = required_tools - called_tools
            if missing_tools:
                failures.append(f"{case_name}: 缺少工具调用{sorted(missing_tools)}")
            unexpected_tools = forbidden_tools & called_tools
            if unexpected_tools:
                failures.append(
                    f"{case_name}: 出现不应调用的工具{sorted(unexpected_tools)}"
                )
            if run.completion_reason == "model_error":
                failures.append("模型服务首个请求失败，已停止后续Live案例以避免重复请求。")
                break

        if not failures:
            OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
            for case_name, *_ in CASES:
                shutil.copytree(
                    staging_root / case_name,
                    OUTPUT_ROOT / case_name,
                    dirs_exist_ok=True,
                )

    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    write_json(
        OUTPUT_ROOT / "metadata.json",
        {
            "model": model_name,
            "base_url_configured": bool(os.getenv("OPENAI_BASE_URL", "").strip()),
            "case_count": len(CASES),
            "validation": "passed",
            "failures": [],
            "note": "未记录API密钥。Trace仅包含可审计动作，不包含内部思维过程。",
        },
    )
    print(f"已生成{len(CASES)}条真实模型Live Trace：{OUTPUT_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

