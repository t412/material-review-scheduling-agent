"""实际运行八组离线案例并导出输入、输出、Trace和测试结果。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agent import AgentRuntime, MaterialSchedulingAgent  # noqa: E402
from src.models.mock_model import OfflineMockModel  # noqa: E402


EXAMPLES_DIR = PROJECT_ROOT / "examples"
GENERATED_RUNTIME_ROOT = PROJECT_ROOT / "runtime" / "example-generation"
SINGLE_CASES = (
    "case-01-normal",
    "case-02-missing-info",
    "case-03-rule-risk",
    "case-04-slot-conflict",
    "case-06-save-failure",
    "case-07-manual-review",
    "case-08-prompt-injection",
)


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def compact_output(run, trace_name: str) -> dict[str, Any]:
    result = run.result.model_dump(mode="json")
    result["trace_file"] = trace_name
    return {
        "result": result,
        "completion_reason": run.completion_reason,
        "model_steps": run.model_steps,
        "tool_calls": run.tool_calls,
        "trace_error": run.trace_error,
    }


def export_trace(run, target: Path, trace_name: str) -> None:
    if run.result.trace_file is None:
        raise RuntimeError("案例未生成Trace")
    payload = read_json(run.result.trace_file)
    payload["final_output"]["trace_file"] = trace_name
    write_json(target, payload)


def run_once(request: dict[str, Any], runtime_dir: Path, *, save_failure=False):
    agent = MaterialSchedulingAgent(
        OfflineMockModel(),
        runtime=AgentRuntime(
            drafts_path=runtime_dir / "drafts" / "drafts.json",
            trace_dir=runtime_dir / "traces",
            inject_save_failure=save_failure,
        ),
    )
    return agent.run(request)


def generate_single_case(case_name: str, runtime_root: Path) -> None:
    case_dir = EXAMPLES_DIR / case_name
    request = read_json(case_dir / "input.json")
    run = run_once(
        request,
        runtime_root / case_name,
        save_failure=case_name == "case-06-save-failure",
    )
    export_trace(run, case_dir / "trace.json", "trace.json")
    write_json(case_dir / "output.json", compact_output(run, "trace.json"))


def generate_duplicate_case(runtime_root: Path) -> None:
    case_dir = EXAMPLES_DIR / "case-05-duplicate"
    requests = read_json(case_dir / "input.json")["runs"]
    runtime_dir = runtime_root / "case-05-duplicate"
    first = run_once(requests[0], runtime_dir)
    second = run_once(requests[1], runtime_dir)

    export_trace(first, case_dir / "trace-first.json", "trace-first.json")
    export_trace(second, case_dir / "trace-second.json", "trace-second.json")
    physical_drafts = read_json(runtime_dir / "drafts" / "drafts.json")
    write_json(
        case_dir / "output.json",
        {
            "first_run": compact_output(first, "trace-first.json"),
            "second_run": compact_output(second, "trace-second.json"),
            "verification": {
                "same_draft_id": first.result.draft_id == second.result.draft_id,
                "physical_draft_count": len(physical_drafts),
            },
        },
    )


def run_tests() -> int:
    completed = subprocess.run(
        [sys.executable, "-m", "pytest"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    report = (
        "Command: python -m pytest\n"
        f"Exit code: {completed.returncode}\n\n"
        "STDOUT:\n"
        f"{completed.stdout}\n"
        "STDERR:\n"
        f"{completed.stderr}"
    )
    (EXAMPLES_DIR / "test-results.txt").write_text(report, encoding="utf-8")
    return completed.returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args()

    GENERATED_RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="run-",
        dir=GENERATED_RUNTIME_ROOT,
    ) as temporary_directory:
        runtime_root = Path(temporary_directory)
        for case_name in SINGLE_CASES:
            generate_single_case(case_name, runtime_root)
        generate_duplicate_case(runtime_root)

    if not args.skip_tests:
        return run_tests()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

