"""提交前检查目录、验收材料、潜在密钥和自动化测试。"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_PATHS = (
    "README.md",
    "DELIVERY.md",
    "pyproject.toml",
    ".env.example",
    "src/agent.py",
    "src/cli.py",
    "src/schemas.py",
    "tests/unit",
    "tests/integration",
    "tests/e2e",
    "data/materials.json",
    "data/review_rules.json",
    "data/schedules.json",
    "docs/01-requirements.md",
    "docs/02-solution.md",
    "docs/03-evaluation.md",
    "docs/04-ai-usage.md",
    "docs/05-retrospective.md",
    "examples/test-results.txt",
)
CASE_NAMES = (
    "case-01-normal",
    "case-02-missing-info",
    "case-03-rule-risk",
    "case-04-slot-conflict",
    "case-05-duplicate",
    "case-06-save-failure",
    "case-07-manual-review",
    "case-08-prompt-injection",
)
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{24,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{20,}", re.IGNORECASE),
)
IGNORED_PARTS = {".git", ".venv", "__pycache__", ".pytest_cache", "runtime"}
TEXT_SUFFIXES = {".py", ".md", ".json", ".toml", ".txt", ".ps1", ".example"}


def inspect_files() -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    for relative_path in REQUIRED_PATHS:
        if not (PROJECT_ROOT / relative_path).exists():
            errors.append(f"缺少规定路径：{relative_path}")

    for case_name in CASE_NAMES:
        case_dir = PROJECT_ROOT / "examples" / case_name
        for file_name in ("input.json", "output.json"):
            if not (case_dir / file_name).exists():
                errors.append(f"缺少案例文件：examples/{case_name}/{file_name}")
        traces = list(case_dir.glob("trace*.json"))
        if not traces:
            errors.append(f"案例缺少Trace：examples/{case_name}")

    if (PROJECT_ROOT / ".env").exists():
        errors.append("仓库根目录存在.env，请确认其中无密钥并移出提交")

    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file() or any(part in IGNORED_PARTS for part in path.parts):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(content):
                errors.append(f"疑似真实密钥：{path.relative_to(PROJECT_ROOT)}")
                break

    live_dir = PROJECT_ROOT / "examples" / "live-model"
    live_traces = list(live_dir.glob("**/trace*.json")) if live_dir.exists() else []
    if len(live_traces) < 2:
        warnings.append("真实模型Trace少于2条；Mock不能证明真实模型决策效果")
    elif live_dir.exists():
        metadata_path = live_dir / "metadata.json"
        if not metadata_path.exists():
            errors.append("真实模型目录缺少metadata.json")
        else:
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                errors.append("真实模型metadata.json无法读取或不是有效JSON")
            else:
                if metadata.get("validation") != "passed":
                    errors.append("真实模型metadata验证状态不是passed")
                if metadata.get("failures"):
                    errors.append("真实模型metadata包含失败项")

        for case_dir in sorted(path for path in live_dir.iterdir() if path.is_dir()):
            output_path = case_dir / "output.json"
            trace_path = case_dir / "trace.json"
            if not output_path.exists() or not trace_path.exists():
                errors.append(f"Live案例文件不完整：{case_dir.name}")
                continue
            try:
                output = json.loads(output_path.read_text(encoding="utf-8"))
                trace = json.loads(trace_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                errors.append(f"Live案例JSON无法读取：{case_dir.name}")
                continue
            if output.get("completion_reason") != "model_finished":
                errors.append(
                    f"Live案例未由模型正常完成：{case_dir.name} "
                    f"({output.get('completion_reason')})"
                )
            if trace.get("completion_reason") != "model_finished":
                errors.append(
                    f"Live Trace结束原因异常：{case_dir.name} "
                    f"({trace.get('completion_reason')})"
                )
            if output.get("trace_error") is not None:
                errors.append(f"Live案例Trace写入失败：{case_dir.name}")
    return errors, warnings


def run_tests() -> tuple[bool, str]:
    completed = subprocess.run(
        [sys.executable, "-m", "pytest"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    summary = completed.stdout.strip().splitlines()
    last_line = summary[-1] if summary else "pytest无输出"
    return completed.returncode == 0, last_line


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument(
        "--require-live",
        action="store_true",
        help="真实模型Trace不足2条时检查失败",
    )
    args = parser.parse_args()

    errors, warnings = inspect_files()
    if args.require_live and any("真实模型Trace" in item for item in warnings):
        errors.append("启用--require-live，但真实模型Trace不足2条")

    test_summary = "skipped"
    if not args.skip_tests:
        tests_ok, test_summary = run_tests()
        if not tests_ok:
            errors.append(f"pytest失败：{test_summary}")

    report = {
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "warnings": warnings,
        "pytest": test_summary,
        "publishing_enabled": False,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())

