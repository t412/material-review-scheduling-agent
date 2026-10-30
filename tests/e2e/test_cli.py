from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def run_cli(*arguments: str, env=None):
    return subprocess.run(
        [sys.executable, "-m", "src.cli", *arguments],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env=env,
    )


def parse_stdout(result):
    return json.loads(result.stdout)


def common_run_args(runtime_dir: Path, *, hour: int = 17, request_id="REQ-E2E"):
    return (
        "run",
        "--mode",
        "mock",
        "--request-id",
        request_id,
        "--material-id",
        "M01",
        "--requested-slot",
        f"2026-11-02T{hour:02d}:00:00+08:00",
        "--earliest-time",
        "17:00:00",
        "--latest-time",
        "21:00:00",
        "--runtime-dir",
        str(runtime_dir),
    )


def test_cli_normal_run_produces_output_draft_and_trace(tmp_path) -> None:
    result = run_cli(*common_run_args(tmp_path))

    assert result.returncode == 0, result.stderr
    payload = parse_stdout(result)
    assert payload["result"]["task_status"] == "completed"
    assert payload["result"]["draft_status"] == "saved"
    assert Path(payload["result"]["trace_file"]).exists()
    assert (tmp_path / "drafts" / "drafts.json").exists()


def test_cli_conflict_run_suggests_19_and_waits_confirmation(tmp_path) -> None:
    result = run_cli(*common_run_args(tmp_path, hour=18))

    assert result.returncode == 0, result.stderr
    payload = parse_stdout(result)
    assert payload["result"]["task_status"] == "awaiting_confirmation"
    assert payload["result"]["suggested_slot"].endswith("19:00:00+08:00")


def test_cli_accepts_json_input_and_writes_output_file(tmp_path) -> None:
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.json"
    input_path.write_text(
        json.dumps(
            {
                "request_id": "REQ-FILE",
                "material_id": "M01",
                "requested_slot": "2026-11-02T17:00:00+08:00",
                "slot_requirement": "hard",
            }
        ),
        encoding="utf-8",
    )

    result = run_cli(
        "run",
        "--input",
        str(input_path),
        "--runtime-dir",
        str(tmp_path / "runtime"),
        "--output",
        str(output_path),
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(output_path.read_text(encoding="utf-8")) == parse_stdout(result)


def test_cli_save_failure_returns_failure_exit_code(tmp_path) -> None:
    result = run_cli(*common_run_args(tmp_path), "--inject-save-failure")

    assert result.returncode == 4
    assert parse_stdout(result)["result"]["draft_status"] == "failed"


def test_cli_duplicate_execution_returns_original_draft(tmp_path) -> None:
    first = run_cli(*common_run_args(tmp_path, request_id="REQ-ONE"))
    second = run_cli(*common_run_args(tmp_path, request_id="REQ-TWO"))

    first_payload = parse_stdout(first)
    second_payload = parse_stdout(second)
    assert first_payload["result"]["draft_status"] == "saved"
    assert second_payload["result"]["draft_status"] == "duplicate"
    assert second_payload["result"]["draft_id"] == first_payload["result"]["draft_id"]


def test_cli_rejects_invalid_datetime(tmp_path) -> None:
    result = run_cli(
        "run",
        "--material-id",
        "M01",
        "--requested-slot",
        "not-a-datetime",
        "--runtime-dir",
        str(tmp_path),
    )

    assert result.returncode == 2
    assert json.loads(result.stderr)["error"] == "input_or_configuration_error"


def test_cli_live_mode_requires_model_configuration(tmp_path) -> None:
    env = dict(os.environ)
    env.pop("OPENAI_MODEL", None)
    env.pop("OPENAI_API_KEY", None)
    result = run_cli(
        "run",
        "--mode",
        "live",
        "--material-id",
        "M01",
        "--requested-slot",
        "2026-11-02T17:00:00+08:00",
        "--runtime-dir",
        str(tmp_path),
        env=env,
    )

    assert result.returncode == 2
    assert "OPENAI_MODEL" in json.loads(result.stderr)["message"]


def test_cli_max_steps_returns_incomplete_exit_code(tmp_path) -> None:
    result = run_cli(*common_run_args(tmp_path), "--max-steps", "1")

    assert result.returncode == 5
    assert parse_stdout(result)["completion_reason"] == "max_steps"


def test_cli_list_and_status_commands(tmp_path) -> None:
    status = run_cli("status")
    materials = run_cli("list-materials")
    schedules = run_cli("list-schedule")
    drafts = run_cli("show-drafts", "--runtime-dir", str(tmp_path))

    assert parse_stdout(status)["publishing_enabled"] is False
    assert len(parse_stdout(materials)) == 6
    assert len(parse_stdout(schedules)) == 2
    assert parse_stdout(drafts) == []

