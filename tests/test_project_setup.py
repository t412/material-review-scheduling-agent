from __future__ import annotations

import subprocess
import sys
import json
from pathlib import Path

from src import __version__
from src.cli import main


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_version_is_defined() -> None:
    assert __version__ == "0.1.0"


def test_status_command(capsys) -> None:
    exit_code = main(["status"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["implementation"] == "core_complete"
    assert payload["publishing_enabled"] is False


def test_module_entrypoint_runs() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "src.cli", "status"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout)["completed_stages"] == 8

