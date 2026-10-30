"""排期草稿幂等键生成。"""

from __future__ import annotations

import hashlib
import json

from src.schemas import BEIJING_TZ, SchedulingRequest


def build_idempotency_key(request: SchedulingRequest) -> str:
    """根据规范化业务请求生成稳定SHA-256键，不依赖request_id。"""

    payload = {
        "material_id": request.material_id,
        "requested_slot": request.requested_slot.astimezone(BEIJING_TZ).isoformat(),
        "slot_requirement": request.slot_requirement.value,
        "user_confirmed_alternative": request.user_confirmed_alternative,
        "constraints": (
            request.constraints.model_dump(mode="json", exclude_none=True)
            if request.constraints is not None
            else None
        ),
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

