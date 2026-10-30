"""项目命令行入口。"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from src import __version__
from src.agent import AgentConfig, AgentRuntime, MaterialSchedulingAgent
from src.exceptions import DataRepositoryError, ModelConfigurationError
from src.models.mock_model import OfflineMockModel
from src.models.openai_compatible import OpenAICompatibleModel
from src.schemas import DraftRecord, MaterialMetadata, ScheduledItem, SchedulingRequest
from src.storage.json_repository import load_model_list


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_RUNTIME_DIR = PROJECT_ROOT / "runtime"

EXIT_SUCCESS = 0
EXIT_INPUT_ERROR = 2
EXIT_BLOCKED = 3
EXIT_FAILED = 4
EXIT_INCOMPLETE = 5


class CLIInputError(Exception):
    pass


def _add_runtime_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--runtime-dir",
        type=Path,
        default=DEFAULT_RUNTIME_DIR,
        help="草稿和Trace运行目录",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="material-agent",
        description="素材审核与发布排期 Agent",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="查看项目实现状态")

    run_parser = subparsers.add_parser("run", help="运行一次素材排期任务")
    run_parser.add_argument("--mode", choices=["mock", "live"], default="mock")
    run_parser.add_argument("--input", type=Path, help="包含请求JSON对象的输入文件")
    run_parser.add_argument("--request-id", default="REQ-CLI-001")
    run_parser.add_argument("--material-id")
    run_parser.add_argument("--requested-slot")
    run_parser.add_argument(
        "--slot-requirement",
        choices=["hard", "flexible"],
        default="hard",
    )
    run_parser.add_argument("--confirmed-alternative", action="store_true")
    run_parser.add_argument("--allowed-date")
    run_parser.add_argument("--earliest-time")
    run_parser.add_argument("--latest-time")
    run_parser.add_argument("--max-steps", type=int, default=8)
    run_parser.add_argument("--max-tool-calls", type=int, default=10)
    run_parser.add_argument("--max-identical-calls", type=int, default=2)
    run_parser.add_argument("--inject-save-failure", action="store_true")
    run_parser.add_argument("--output", type=Path, help="另存精简运行结果JSON")
    _add_runtime_argument(run_parser)

    materials_parser = subparsers.add_parser("list-materials", help="列出合成素材")
    materials_parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)

    schedule_parser = subparsers.add_parser("list-schedule", help="列出已有排期")
    schedule_parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)

    drafts_parser = subparsers.add_parser("show-drafts", help="查看运行期草稿")
    _add_runtime_argument(drafts_parser)
    return parser


def _read_json_file(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError as exc:
        raise CLIInputError(f"输入文件不存在：{path}") from exc
    except (JSONDecodeError, UnicodeDecodeError) as exc:
        raise CLIInputError(f"输入文件不是有效的UTF-8 JSON：{path}") from exc
    except OSError as exc:
        raise CLIInputError(f"无法读取输入文件：{path}") from exc


def _request_from_args(args: argparse.Namespace) -> SchedulingRequest:
    if args.input is not None:
        explicit_fields = (
            args.material_id,
            args.requested_slot,
            args.allowed_date,
            args.earliest_time,
            args.latest_time,
        )
        if any(value is not None for value in explicit_fields):
            raise CLIInputError("--input不能与请求字段参数同时使用")
        payload = _read_json_file(args.input)
        if isinstance(payload, dict) and isinstance(payload.get("request"), dict):
            payload = payload["request"]
        if not isinstance(payload, dict):
            raise CLIInputError("输入JSON顶层必须是请求对象")
    else:
        if not args.material_id or not args.requested_slot:
            raise CLIInputError("未使用--input时必须提供--material-id和--requested-slot")
        constraints = {
            key: value
            for key, value in {
                "allowed_date": args.allowed_date,
                "earliest_time": args.earliest_time,
                "latest_time": args.latest_time,
            }.items()
            if value is not None
        }
        payload = {
            "request_id": args.request_id,
            "material_id": args.material_id,
            "requested_slot": args.requested_slot,
            "slot_requirement": args.slot_requirement,
            "user_confirmed_alternative": args.confirmed_alternative,
            "constraints": constraints or None,
        }

    try:
        return SchedulingRequest.model_validate(payload)
    except ValidationError as exc:
        raise CLIInputError(f"请求参数校验失败：{exc}") from exc


def _build_model(mode: str):
    if mode == "mock":
        return OfflineMockModel()
    return OpenAICompatibleModel()


def _compact_run_output(run) -> dict[str, Any]:
    return {
        "result": run.result.model_dump(mode="json"),
        "completion_reason": run.completion_reason,
        "model_steps": run.model_steps,
        "tool_calls": run.tool_calls,
        "trace_error": run.trace_error,
    }


def _print_json(payload: Any, *, stream=None) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2), file=stream or sys.stdout)


def _write_output(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        raise CLIInputError(f"无法写入输出文件：{path}") from exc


def _exit_code(task_status: str) -> int:
    if task_status in {"completed", "awaiting_confirmation"}:
        return EXIT_SUCCESS
    if task_status == "blocked":
        return EXIT_BLOCKED
    if task_status == "incomplete":
        return EXIT_INCOMPLETE
    return EXIT_FAILED


def _run_command(args: argparse.Namespace) -> int:
    request = _request_from_args(args)
    try:
        model = _build_model(args.mode)
        config = AgentConfig(
            max_steps=args.max_steps,
            max_tool_calls=args.max_tool_calls,
            max_identical_calls=args.max_identical_calls,
        )
    except (ModelConfigurationError, ValidationError) as exc:
        raise CLIInputError(str(exc)) from exc

    runtime_dir: Path = args.runtime_dir.resolve()
    runtime = AgentRuntime(
        drafts_path=runtime_dir / "drafts" / "drafts.json",
        trace_dir=runtime_dir / "traces",
        inject_save_failure=args.inject_save_failure,
    )
    run = MaterialSchedulingAgent(model, config=config, runtime=runtime).run(request)
    payload = _compact_run_output(run)
    if args.output is not None:
        _write_output(args.output, payload)
    _print_json(payload)
    return _exit_code(run.result.task_status.value)


def _list_models(path: Path, model_type) -> int:
    try:
        records = load_model_list(path, model_type)
    except DataRepositoryError as exc:
        raise CLIInputError(str(exc)) from exc
    _print_json([record.model_dump(mode="json") for record in records])
    return EXIT_SUCCESS


def _show_drafts(runtime_dir: Path) -> int:
    path = runtime_dir.resolve() / "drafts" / "drafts.json"
    if not path.exists():
        _print_json([])
        return EXIT_SUCCESS
    return _list_models(path, DraftRecord)


def _configure_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
            except OSError:
                pass


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_output()
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "status":
            _print_json(
                {
                    "version": __version__,
                    "implementation": "core_complete",
                    "completed_stages": 8,
                    "next_stage": "验收案例与文档",
                    "publishing_enabled": False,
                }
            )
            return EXIT_SUCCESS
        if args.command == "run":
            return _run_command(args)
        if args.command == "list-materials":
            return _list_models(args.data_dir / "materials.json", MaterialMetadata)
        if args.command == "list-schedule":
            return _list_models(args.data_dir / "schedules.json", ScheduledItem)
        if args.command == "show-drafts":
            return _show_drafts(args.runtime_dir)
    except CLIInputError as exc:
        _print_json(
            {"error": "input_or_configuration_error", "message": str(exc)},
            stream=sys.stderr,
        )
        return EXIT_INPUT_ERROR

    parser.error(f"未知命令：{args.command}")
    return EXIT_INPUT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())

