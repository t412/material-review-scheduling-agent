from __future__ import annotations

import json

from src.agent import AgentRuntime, MaterialSchedulingAgent
from src.exceptions import TraceWriteError
from src.models.base import ModelClient, ModelDecision
from src.models.mock_model import OfflineMockModel
from src.trace import TraceWriter


def request_data(hour: int = 18) -> dict:
    return {
        "request_id": "REQ-TRACE",
        "material_id": "M01",
        "requested_slot": f"2026-11-02T{hour:02d}:00:00+08:00",
        "slot_requirement": "hard",
        "user_confirmed_alternative": False,
        "constraints": {
            "allowed_date": "2026-11-02",
            "earliest_time": "17:00:00",
            "latest_time": "21:00:00",
        },
    }


def build_agent(tmp_path, *, save_failure=False, trace_writer=None):
    return MaterialSchedulingAgent(
        OfflineMockModel(),
        runtime=AgentRuntime(
            drafts_path=tmp_path / "drafts.json",
            trace_dir=tmp_path / "traces",
            inject_save_failure=save_failure,
        ),
        trace_writer=trace_writer,
    )


def test_conflict_path_writes_complete_auditable_trace(tmp_path) -> None:
    run = build_agent(tmp_path).run(request_data(18))

    assert run.trace_error is None
    assert run.result.trace_file is not None
    assert run.result.trace_file.exists()
    payload = json.loads(run.result.trace_file.read_text(encoding="utf-8"))

    assert [step["action"] for step in payload["steps"]] == [
        "get_material",
        "check_material_rules",
        "query_slot",
        "find_alternative_slots",
        "save_schedule_draft",
    ]
    assert payload["steps"][2]["observation"]["data"]["availability"] == "occupied"
    assert payload["steps"][2]["next_action"] == "find_alternative_slots"
    assert payload["steps"][3]["observation"]["data"]["candidates"][0]["slot"].endswith("19:00:00+08:00")
    assert payload["final_output"]["suggested_slot"].endswith("19:00:00+08:00")
    assert payload["final_output"]["trace_file"] == str(run.result.trace_file)
    assert payload["notes"].startswith("仅记录可审计动作依据")


def test_tool_failure_is_preserved_in_trace(tmp_path) -> None:
    run = build_agent(tmp_path, save_failure=True).run(request_data(17))

    payload = json.loads(run.result.trace_file.read_text(encoding="utf-8"))
    save_step = payload["steps"][-1]
    assert save_step["action"] == "save_schedule_draft"
    assert save_step["observation"]["status"] == "failure"
    assert save_step["observation"]["error_code"] == "DRAFT_SAVE_INJECTED_FAILURE"
    assert payload["final_output"]["draft_status"] == "failed"


class FailingTraceWriter(TraceWriter):
    def write(self, **kwargs):
        raise TraceWriteError("模拟Trace存储失败")


def test_trace_failure_does_not_rewrite_business_truth(tmp_path) -> None:
    run = build_agent(tmp_path, trace_writer=FailingTraceWriter()).run(request_data(17))

    assert run.result.draft_status.value == "saved"
    assert run.result.draft_id is not None
    assert run.result.trace_file is None
    assert run.trace_error == "模拟Trace存储失败"


class TamperedRiskModel(ModelClient):
    def __init__(self) -> None:
        self.delegate = OfflineMockModel()

    def decide(self, messages, tools) -> ModelDecision:
        decision = self.delegate.decide(messages, tools)
        if decision.final_output is not None:
            output = dict(decision.final_output)
            output["risk_reasons"] = ["模型编造的风险原因"]
            return ModelDecision(final_output=output)
        return decision


def test_fabricated_risk_reason_is_rejected(tmp_path) -> None:
    agent = MaterialSchedulingAgent(
        TamperedRiskModel(),
        runtime=AgentRuntime(
            drafts_path=tmp_path / "drafts.json",
            trace_dir=tmp_path / "traces",
        ),
    )

    run = agent.run(request_data(17))

    assert run.completion_reason == "invalid_final_output"
    assert run.result.task_status.value == "failed"
    assert run.result.risk_reasons == []


class CorrectingRiskModel(ModelClient):
    def __init__(self) -> None:
        self.delegate = OfflineMockModel()
        self.tampered_once = False

    def decide(self, messages, tools) -> ModelDecision:
        decision = self.delegate.decide(messages, tools)
        if decision.final_output is not None and not self.tampered_once:
            self.tampered_once = True
            output = dict(decision.final_output)
            output["risk_reasons"] = ["首次错误的风险原因"]
            return ModelDecision(final_output=output)
        return decision


def test_invalid_final_output_can_be_corrected_once(tmp_path) -> None:
    model = CorrectingRiskModel()
    agent = MaterialSchedulingAgent(
        model,
        runtime=AgentRuntime(
            drafts_path=tmp_path / "drafts.json",
            trace_dir=tmp_path / "traces",
        ),
    )

    run = agent.run(request_data(17))

    assert model.tampered_once is True
    assert run.completion_reason == "model_finished"
    assert run.result.task_status.value == "completed"
    assert run.result.risk_reasons == []

