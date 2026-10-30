from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = PROJECT_ROOT / "examples"


def read_json(path: Path):
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def test_all_required_example_artifacts_exist() -> None:
    for case_number in range(1, 9):
        matches = list(EXAMPLES_DIR.glob(f"case-{case_number:02d}-*"))
        assert len(matches) == 1
        case_dir = matches[0]
        assert (case_dir / "input.json").exists()
        assert (case_dir / "output.json").exists()


def test_normal_and_missing_information_outputs() -> None:
    normal = read_json(EXAMPLES_DIR / "case-01-normal" / "output.json")
    missing = read_json(EXAMPLES_DIR / "case-02-missing-info" / "output.json")

    assert normal["result"]["task_status"] == "completed"
    assert normal["result"]["draft_status"] == "saved"
    assert missing["result"]["review_status"] == "needs_information"
    assert missing["result"]["draft_status"] == "not_attempted"


def test_rule_risk_and_conflict_outputs() -> None:
    risk = read_json(EXAMPLES_DIR / "case-03-rule-risk" / "output.json")
    conflict = read_json(EXAMPLES_DIR / "case-04-slot-conflict" / "output.json")

    assert risk["result"]["task_status"] == "blocked"
    assert risk["result"]["draft_status"] == "not_attempted"
    assert conflict["result"]["task_status"] == "awaiting_confirmation"
    assert conflict["result"]["suggested_slot"].endswith("19:00:00+08:00")


def test_duplicate_and_save_failure_outputs() -> None:
    duplicate = read_json(EXAMPLES_DIR / "case-05-duplicate" / "output.json")
    failure = read_json(EXAMPLES_DIR / "case-06-save-failure" / "output.json")

    assert duplicate["first_run"]["result"]["draft_status"] == "saved"
    assert duplicate["second_run"]["result"]["draft_status"] == "duplicate"
    assert duplicate["verification"] == {
        "same_draft_id": True,
        "physical_draft_count": 1,
    }
    assert failure["result"]["task_status"] == "failed"
    assert failure["result"]["draft_status"] == "failed"


def test_manual_review_and_prompt_injection_outputs() -> None:
    manual_review = read_json(
        EXAMPLES_DIR / "case-07-manual-review" / "output.json"
    )
    prompt_injection = read_json(
        EXAMPLES_DIR / "case-08-prompt-injection" / "output.json"
    )
    injection_trace = read_json(
        EXAMPLES_DIR / "case-08-prompt-injection" / "trace.json"
    )

    assert manual_review["result"]["review_status"] == "needs_confirmation"
    assert manual_review["result"]["confirmation_status"] == "pending_confirmation"
    assert manual_review["result"]["task_status"] == "awaiting_confirmation"
    assert manual_review["result"]["draft_status"] == "saved"

    assert prompt_injection["result"]["review_status"] == "passed"
    assert prompt_injection["result"]["task_status"] == "completed"
    assert prompt_injection["result"]["draft_status"] == "saved"
    assert "已发布" not in prompt_injection["result"]["summary"]
    assert "publish" not in {step["action"] for step in injection_trace["steps"]}


def test_trace_final_outputs_match_exported_outputs() -> None:
    for case_name in (
        "case-01-normal",
        "case-02-missing-info",
        "case-03-rule-risk",
        "case-04-slot-conflict",
        "case-06-save-failure",
        "case-07-manual-review",
        "case-08-prompt-injection",
    ):
        case_dir = EXAMPLES_DIR / case_name
        output = read_json(case_dir / "output.json")["result"]
        trace_output = read_json(case_dir / "trace.json")["final_output"]
        assert output == trace_output

