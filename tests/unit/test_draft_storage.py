from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.schemas import ToolStatus
from src.tools.draft import save_schedule_draft


def request_data(request_id: str = "REQ-001", material_id: str = "M01") -> dict:
    return {
        "request_id": request_id,
        "material_id": material_id,
        "requested_slot": "2026-11-02T18:00:00+08:00",
        "slot_requirement": "hard",
        "user_confirmed_alternative": False,
        "constraints": {
            "allowed_date": "2026-11-02",
            "earliest_time": "17:00:00",
            "latest_time": "21:00:00",
        },
    }


def save(drafts_path, *, request=None, inject_failure=False, **overrides):
    parameters = {
        "request": request or request_data(),
        "review_status": "passed",
        "suggested_slot": "2026-11-02T19:00:00+08:00",
        "confirmation_status": "pending_confirmation",
        "drafts_path": drafts_path,
        "inject_failure": inject_failure,
    }
    parameters.update(overrides)
    return save_schedule_draft(**parameters)


def test_first_save_creates_candidate_draft(tmp_path) -> None:
    path = tmp_path / "drafts.json"

    result = save(path)

    assert result.status == ToolStatus.SUCCESS
    assert result.data["draft_status"] == "saved"
    assert result.data["published"] is False
    assert result.data["draft"]["confirmation_status"] == "pending_confirmation"
    assert len(json.loads(path.read_text(encoding="utf-8"))) == 1


def test_duplicate_request_returns_existing_draft(tmp_path) -> None:
    path = tmp_path / "drafts.json"
    first = save(path, request=request_data("REQ-001"))
    second = save(path, request=request_data("REQ-999"))

    assert first.data["draft_status"] == "saved"
    assert second.data["draft_status"] == "duplicate"
    assert second.data["draft"]["draft_id"] == first.data["draft"]["draft_id"]
    assert len(json.loads(path.read_text(encoding="utf-8"))) == 1


def test_different_business_request_creates_second_draft(tmp_path) -> None:
    path = tmp_path / "drafts.json"
    first_request = request_data("REQ-001", "M01")
    second_request = request_data("REQ-002", "M05")

    first = save(path, request=first_request)
    second = save(path, request=second_request)

    assert first.data["draft_status"] == "saved"
    assert second.data["draft_status"] == "saved"
    assert len(json.loads(path.read_text(encoding="utf-8"))) == 2


def test_injected_failure_does_not_create_file(tmp_path) -> None:
    path = tmp_path / "drafts.json"

    result = save(path, inject_failure=True)

    assert result.status == ToolStatus.FAILURE
    assert result.data["draft_status"] == "failed"
    assert result.error_code == "DRAFT_SAVE_INJECTED_FAILURE"
    assert not path.exists()


def test_corrupted_draft_file_returns_failure(tmp_path) -> None:
    path = tmp_path / "drafts.json"
    path.write_text("not-json", encoding="utf-8")

    result = save(path)

    assert result.status == ToolStatus.FAILURE
    assert result.error_code == "DATA_FILE_INVALID_JSON"
    assert path.read_text(encoding="utf-8") == "not-json"


def test_atomic_write_failure_preserves_existing_file(tmp_path, monkeypatch) -> None:
    path = tmp_path / "drafts.json"
    first = save(path, request=request_data("REQ-001", "M01"))
    original_content = path.read_text(encoding="utf-8")

    def fail_replace(source, destination):
        raise OSError("simulated replace failure")

    monkeypatch.setattr("src.storage.draft_repository.os.replace", fail_replace)
    second = save(path, request=request_data("REQ-002", "M05"))

    assert first.data["draft_status"] == "saved"
    assert second.status == ToolStatus.FAILURE
    assert second.error_code == "DATA_WRITE_ERROR"
    assert path.read_text(encoding="utf-8") == original_content
    assert list(tmp_path.glob("*.tmp")) == []


def test_concurrent_duplicate_saves_create_one_record(tmp_path) -> None:
    path = tmp_path / "drafts.json"

    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(lambda _: save(path), range(5)))

    statuses = [result.data["draft_status"] for result in results]
    assert statuses.count("saved") == 1
    assert statuses.count("duplicate") == 4
    assert len(json.loads(path.read_text(encoding="utf-8"))) == 1


@pytest.mark.parametrize("review_status", ["blocked", "needs_information"])
def test_blocked_or_incomplete_review_cannot_be_saved(tmp_path, review_status) -> None:
    path = tmp_path / "drafts.json"

    result = save(path, review_status=review_status)

    assert result.status == ToolStatus.INVALID_INPUT
    assert result.data["draft_status"] == "not_attempted"
    assert not path.exists()


def test_unconfirmed_alternative_cannot_be_marked_confirmed(tmp_path) -> None:
    path = tmp_path / "drafts.json"

    result = save(path, confirmation_status="confirmed")

    assert result.status == ToolStatus.INVALID_INPUT
    assert result.error_code == "INVALID_DRAFT_INPUT"
    assert not path.exists()


def test_project_exposes_no_publish_function() -> None:
    import src.tools.draft as draft_module

    assert not hasattr(draft_module, "publish")
    assert not hasattr(draft_module, "publish_material")

