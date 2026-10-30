from __future__ import annotations

from src.schemas import SchedulingRequest
from src.storage.idempotency import build_idempotency_key


def request_data(request_id: str = "REQ-001") -> dict:
    return {
        "request_id": request_id,
        "material_id": "M01",
        "requested_slot": "2026-11-02T18:00:00+08:00",
        "slot_requirement": "hard",
        "user_confirmed_alternative": False,
        "constraints": {
            "allowed_date": "2026-11-02",
            "earliest_time": "17:00:00",
            "latest_time": "21:00:00",
        },
    }


def test_same_business_request_has_stable_key() -> None:
    first = SchedulingRequest.model_validate(request_data("REQ-001"))
    second = SchedulingRequest.model_validate(request_data("REQ-999"))

    assert build_idempotency_key(first) == build_idempotency_key(second)


def test_equivalent_timezone_representation_has_same_key() -> None:
    first_data = request_data()
    second_data = request_data()
    second_data["requested_slot"] = "2026-11-02T10:00:00Z"

    first = SchedulingRequest.model_validate(first_data)
    second = SchedulingRequest.model_validate(second_data)

    assert build_idempotency_key(first) == build_idempotency_key(second)


def test_different_slot_has_different_key() -> None:
    first_data = request_data()
    second_data = request_data()
    second_data["requested_slot"] = "2026-11-02T19:00:00+08:00"

    assert build_idempotency_key(
        SchedulingRequest.model_validate(first_data)
    ) != build_idempotency_key(SchedulingRequest.model_validate(second_data))

