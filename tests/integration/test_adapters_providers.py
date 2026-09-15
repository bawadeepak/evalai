"""Native OpenAI, Anthropic and local OpenAI-compatible adapters, verified end to end through
the execution engine with mocked HTTP (both SDKs run on httpx2, so a MockTransport is injected).
No request leaves the machine and no paid provider is called."""

import asyncio
import json
import uuid

import httpx2
import pytest
from sqlalchemy import select

from eval_triage.adapters import transport
from eval_triage.adapters.anthropic_adapter import AnthropicAdapter
from eval_triage.adapters.base import RunContext, TargetConfig, TargetRequest
from eval_triage.db.models import Attempt, Run, Trial
from eval_triage.db.repositories import DefinitionError, create_target_config
from tests.conftest import SENTINEL_SECRET
from tests.integration.helpers import import_fixture, make_project, outcomes, run_all, start_run


class FakeProvider:
    def __init__(self):
        self.requests: list[httpx2.Request] = []
        self.queue: dict[str, list[tuple[int, dict]]] = {}

    def add(self, path: str, body: dict, status: int = 200) -> None:
        self.queue.setdefault(path, []).append((status, body))

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        queue = self.queue[request.url.path]
        status, body = queue.pop(0) if len(queue) > 1 else queue[0]
        return httpx2.Response(status, json=body, headers={"request-id": "req_test", "x-request-id": "req_test"})

    def bodies(self, path: str) -> list[dict]:
        return [json.loads(r.content) for r in self.requests if r.url.path == path]


@pytest.fixture
def provider(monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr(transport, "HTTP_CLIENT_FACTORY",
                        lambda sdk: sdk.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(fake.handler)))
    return fake


def responses_body(text=None, calls=(), status="completed"):
    output = []
    if text is not None:
        output.append({"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
                       "content": [{"type": "output_text", "text": text, "annotations": []}]})
    for i, (name, args) in enumerate(calls):
        output.append({"type": "function_call", "id": f"fc_{i}", "call_id": f"call_{i}", "name": name,
                       "arguments": json.dumps(args), "status": "completed"})
    return {"id": "resp_1", "object": "response", "created_at": 1, "model": "example-model-2026-09-01",
            "status": status, "output": output, "parallel_tool_calls": True, "tool_choice": "auto", "tools": [],
            "incomplete_details": {"reason": "max_output_tokens"} if status == "incomplete" else None,
            "usage": {"input_tokens": 30, "output_tokens": 6, "total_tokens": 36,
                      "input_tokens_details": {"cached_tokens": 2}, "output_tokens_details": {"reasoning_tokens": 0}}}


def chat_body(text=None, calls=(), finish="stop"):
    message = {"role": "assistant", "content": text}
    if calls:
        message["tool_calls"] = [{"id": f"call_{i}", "type": "function",
                                  "function": {"name": name, "arguments": json.dumps(args)}}
                                 for i, (name, args) in enumerate(calls)]
    return {"id": "chatcmpl-1", "object": "chat.completion", "created": 1, "model": "example-local-model",
            "choices": [{"index": 0, "finish_reason": finish, "message": message, "logprobs": None}],
            "usage": {"prompt_tokens": 25, "completion_tokens": 7, "total_tokens": 32}}


def claude_body(text=None, tool=None, stop="end_turn", stop_details=None):
    content = []
    if text is not None:
        content.append({"type": "text", "text": text})
    if tool:
        content.append({"type": "tool_use", "id": "toolu_1", "name": tool[0], "input": tool[1]})
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5", "content": content,
            "stop_reason": stop, "stop_sequence": None, "stop_details": stop_details,
            "usage": {"input_tokens": 20, "output_tokens": 8, "cache_read_input_tokens": 4,
                      "cache_creation_input_tokens": 0}}


def _config(ctx, project, **fields):
    with ctx.db.write() as session:
        return create_target_config(session, project, **{"name": fields.pop("name", "t"), **fields}).id


def _attempts(ctx, run_id):
    with ctx.db.read() as session:
        return session.scalars(select(Attempt).join(Trial).where(Trial.run_id == run_id)
                               .order_by(Attempt.started_at, Attempt.attempt_index)).all()


def test_openai_responses_request_shape_evidence_and_no_secret(ctx, client, provider):
    project = make_project(ctx)
    suite = import_fixture(ctx, project, "packs/exact_classification/scenario.yaml", include=["C01"])
    target = _config(ctx, project, adapter="openai", model="example-model", credential_ref="EVALAI_TEST_SECRET")
    provider.add("/v1/responses", responses_body('{"label": "billing"}'))
    run_id = start_run(ctx, project, suite, {"baseline": target}, repeats=1)
    run_all(ctx)
    assert outcomes(ctx, run_id) == {("C01", "baseline"): ["pass"]}
    [body] = provider.bodies("/v1/responses")
    assert body["model"] == "example-model" and body["store"] is False
    assert "Route each support message" in body["instructions"]
    assert body["input"][0]["role"] == "user" and "seed" not in body and "temperature" not in body
    assert provider.requests[0].headers["authorization"] == f"Bearer {SENTINEL_SECRET}"  # server-side only
    [attempt] = _attempts(ctx, run_id)
    assert attempt.status == "success" and attempt.request_id == "req_test"
    assert attempt.actual_model == "example-model-2026-09-01"
    assert attempt.usage["cached_input_tokens"] == 2 and attempt.cost["amount"] is None  # no pricing: unknown
    for artifact in (attempt.request_artifact, attempt.response_artifact):
        text = client.get(f"/api/v1/artifacts/{artifact}").text
        assert SENTINEL_SECRET not in text
    with ctx.db.read() as session:
        assert session.get(Run, run_id).usage["cost_unknown_calls"] == 1


def test_openai_rate_limit_is_retried_with_every_attempt_kept(ctx, provider):
    project = make_project(ctx)
    suite = import_fixture(ctx, project, "packs/exact_classification/scenario.yaml", include=["C01"])
    target = _config(ctx, project, adapter="openai", model="example-model", credential_ref="EVALAI_TEST_SECRET")
    provider.add("/v1/responses", {"error": {"message": "slow down", "type": "rate_limit"}}, status=429)
    provider.add("/v1/responses", responses_body('{"label": "billing"}'))
    run_id = start_run(ctx, project, suite, {"baseline": target}, repeats=1)
    run_all(ctx)
    attempts = _attempts(ctx, run_id)
    assert [a.status for a in attempts] == ["provider_error", "success"]
    assert attempts[0].error["code"] == "rate_limited" and attempts[0].error["retryable"] is True
    assert attempts[1].retry_reason.startswith("transport retry 1")
    assert outcomes(ctx, run_id) == {("C01", "baseline"): ["pass"]}


def test_openai_bad_request_is_not_retried(ctx, provider):
    project = make_project(ctx)
    suite = import_fixture(ctx, project, "packs/exact_classification/scenario.yaml", include=["C01"])
    target = _config(ctx, project, adapter="openai", model="example-model", credential_ref="EVALAI_TEST_SECRET")
    provider.add("/v1/responses", {"error": {"message": "bad model", "type": "invalid_request_error"}}, status=400)
    run_id = start_run(ctx, project, suite, {"baseline": target}, repeats=1)
    run_all(ctx)
    [attempt] = _attempts(ctx, run_id)
    assert attempt.status == "provider_error" and attempt.error["code"] == "bad_request"
    with ctx.db.read() as session:
        assert session.get(Run, run_id).status == "completed_with_errors"
    assert outcomes(ctx, run_id) == {("C01", "baseline"): ["unresolved"]}


def test_chat_completions_tool_loop_with_sandbox(ctx, provider):
    project = make_project(ctx)
    suite = import_fixture(ctx, project, "packs/tool_agent/scenario.yaml", include=["A02"])
    target = _config(ctx, project, adapter="openai", model="example-model", endpoint_type="chat_completions",
                     credential_ref="EVALAI_TEST_SECRET")
    provider.add("/v1/chat/completions", chat_body(calls=[("lookup_order", {"order_id": "1002"})], finish="tool_calls"))
    provider.add("/v1/chat/completions", chat_body("Your order 1002 is in transit."))
    run_id = start_run(ctx, project, suite, {"baseline": target}, repeats=1)
    run_all(ctx)
    assert outcomes(ctx, run_id) == {("A02", "baseline"): ["pass"]}
    second = provider.bodies("/v1/chat/completions")[1]
    tool_message = next(m for m in second["messages"] if m["role"] == "tool")
    assert tool_message["tool_call_id"] == "call_0" and "in_transit" in tool_message["content"]
    assert second["tools"][0]["function"]["name"] == "lookup_order"
    stages = [a.stage for a in _attempts(ctx, run_id)]
    assert stages.count("turn:1") == 1 and stages.count("turn:2") == 1 and "execution" in stages
    with ctx.db.read() as session:
        trial = session.scalars(select(Trial).where(Trial.run_id == run_id)).one()
        assert trial.output["tool_calls"][0]["result"] == {"status": "in_transit", "total": 19.99}


def test_anthropic_structured_output_usage_and_request_shape(ctx, provider):
    project = make_project(ctx)
    suite = import_fixture(ctx, project, "packs/structured_extraction/scenario.yaml", include=["E01"])
    target = _config(ctx, project, adapter="anthropic", model="claude-opus-5", credential_ref="EVALAI_TEST_SECRET")
    facts = {"facts": [{"subject": "maria", "relation": "lives_in", "object": "Lisbon"},
                       {"subject": "maria", "relation": "works_at", "object": "Nova Bank"}]}
    provider.add("/v1/messages", claude_body(json.dumps(facts)))
    run_id = start_run(ctx, project, suite, {"baseline": target}, repeats=1)
    run_all(ctx)
    assert outcomes(ctx, run_id) == {("E01", "baseline"): ["pass"]}
    [body] = provider.bodies("/v1/messages")
    assert body["model"] == "claude-opus-5" and body["max_tokens"] == 16000 and body["system"]
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert not {"temperature", "top_p", "seed"} & set(body)
    assert provider.requests[0].headers["x-api-key"] == SENTINEL_SECRET
    [attempt] = _attempts(ctx, run_id)
    assert attempt.usage == {"input_tokens": 20, "output_tokens": 8, "cache_read_input_tokens": 4,
                             "cache_creation_input_tokens": 0}


def _direct(adapter, config, request):
    context = RunContext(run_id="r", trial_id=str(uuid.uuid4()), candidate_key="c", repeat_index=0,
                         case_external_id="x", attempt_index=0, data_dir=None)

    async def go():
        session = await adapter.prepare(config, context)
        try:
            return await adapter.execute(request, session)
        finally:
            await adapter.close(session)

    return asyncio.run(go())


CLAUDE = TargetConfig(id="c", name="claude", adapter="anthropic", adapter_version="anthropic-1", model="claude-opus-5",
                      credential_ref="EVALAI_TEST_SECRET")


def test_anthropic_stop_reasons_tools_and_errors(settings, provider):
    request = TargetRequest(messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "q"},
                                      {"role": "assistant", "content": "", "tool_calls": [
                                          {"id": "toolu_0", "tool": "lookup_order", "arguments": {"order_id": "1"}}]},
                                      {"role": "tool", "tool_call_id": "toolu_0", "content": "{}"}],
                            tools=[{"name": "lookup_order", "input_schema": {"type": "object"}}])
    provider.add("/v1/messages", claude_body(tool=("lookup_order", {"order_id": "1002"}), stop="tool_use"))
    result = _direct(AnthropicAdapter(), CLAUDE, request)
    assert result.tool_calls == [{"id": "toolu_1", "tool": "lookup_order", "arguments": {"order_id": "1002"}}]
    sent = provider.bodies("/v1/messages")[0]
    assert sent["messages"][1]["content"][0]["type"] == "tool_use"
    assert sent["messages"][2] == {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_0",
                                                               "content": "{}"}]}
    provider.queue.clear()
    provider.add("/v1/messages", claude_body("", stop="refusal", stop_details={
        "type": "refusal", "category": "cyber", "explanation": "declined"}))
    refused = _direct(AnthropicAdapter(), CLAUDE, TargetRequest(messages=[{"role": "user", "content": "q"}]))
    assert refused.status == "success" and refused.refusal == "declined"
    provider.queue.clear()
    provider.add("/v1/messages", claude_body("partial", stop="max_tokens"))
    assert _direct(AnthropicAdapter(), CLAUDE, TargetRequest(messages=[{"role": "user", "content": "q"}])).truncated
    provider.queue.clear()
    provider.add("/v1/messages", {"type": "error", "error": {"type": "overloaded_error", "message": "busy"}}, 529)
    overloaded = _direct(AnthropicAdapter(), CLAUDE, TargetRequest(messages=[{"role": "user", "content": "q"}]))
    assert overloaded.status == "provider_error" and overloaded.retryable and overloaded.error["code"] == "overloaded"
    unsupported = _direct(AnthropicAdapter(), CLAUDE, TargetRequest(messages=[{"role": "user", "content": "q"}],
                                                                    parameters={"temperature": 0}))
    assert unsupported.status == "unsupported"


def test_capability_validation_and_credentials(ctx, client):
    project = make_project(ctx)
    suite = import_fixture(ctx, project, "packs/exact_classification/scenario.yaml", include=["C01"])

    def validate(target):
        return client.post("/api/v1/runs/validate", json={
            "project_id": project, "scenario_id": suite["scenario_id"], "dataset_id": suite["dataset_id"],
            "candidates": [{"key": "baseline", "target_config_id": target}], "execution": {"repeats": 1}})

    claude = _config(ctx, project, name="claude", adapter="anthropic", model="claude-opus-5",
                     credential_ref="EVALAI_TEST_SECRET", parameters={"temperature": 0})
    errors = validate(claude).json()["error"]["details"]["errors"]
    assert errors[0]["code"] == "capability_conflict" and "temperature" in errors[0]["field"]
    seeded = _config(ctx, project, name="gpt", adapter="openai", model="example-model",
                     credential_ref="EVALAI_TEST_SECRET", parameters={"seed": 1})
    assert validate(seeded).json()["error"]["details"]["errors"][0]["code"] == "capability_conflict"
    chat_seed = _config(ctx, project, name="chat", adapter="openai", model="example-model",
                        endpoint_type="chat_completions", credential_ref="EVALAI_TEST_SECRET", parameters={"seed": 1})
    assert validate(chat_seed).json()["error"]["details"]["errors"][0]["code"] == "capability_unknown"
    experimental = _config(ctx, project, name="chat-x", adapter="openai", model="example-model",
                           endpoint_type="chat_completions", credential_ref="EVALAI_TEST_SECRET",
                           parameters={"seed": 1}, experimental=True)
    ok = validate(experimental).json()["data"]
    assert any("experimental" in w for w in ok["warnings"]) and ok["manifest"]["warnings"]
    missing = _config(ctx, project, name="nokey", adapter="openai", model="example-model",
                      credential_ref="EVALAI_UNSET_TEST_KEY")
    assert validate(missing).json()["error"]["details"]["errors"][0]["code"] == "credential_missing"
    listed = {c["name"]: c for c in client.get("/api/v1/target-configs", params={"project_id": project}).json()["data"]}
    assert listed["nokey"]["credential_status"] == "missing" and listed["claude"]["credential_status"] == "set"
    assert SENTINEL_SECRET not in json.dumps(listed)
    with ctx.db.write() as session:
        for bad in ({"adapter": "openai", "model": ""}, {"adapter": "openai_compatible", "model": "m"}):
            with pytest.raises(DefinitionError):
                create_target_config(session, project, name="bad", **bad)


def test_local_endpoint_unknown_features_and_known_pricing(ctx, client, provider):
    project = make_project(ctx)
    suite = import_fixture(ctx, project, "packs/exact_classification/scenario.yaml", include=["C01"])
    local = _config(ctx, project, name="local", adapter="openai_compatible", model="example-local-model",
                    base_url="http://127.0.0.1:11434/v1", credential_ref="")
    caps = client.get(f"/api/v1/target-configs/{local}/capabilities").json()["data"]["capabilities"]
    assert caps["structured_output"]["state"] == "unknown" and caps["tools"]["state"] == "unknown"
    client.put("/api/v1/settings/pricing", json={"as_of": "2026-09-15", "entries": [
        {"adapter": "openai_compatible", "model": "example-local-*", "currency": "USD", "input_per_million": 1000,
         "output_per_million": 2000}]})
    provider.add("/v1/chat/completions", chat_body('{"label": "billing"}'))
    run_id = start_run(ctx, project, suite, {"baseline": local}, repeats=1)
    run_all(ctx)
    [body] = provider.bodies("/v1/chat/completions")
    assert "response_format" not in body  # structured output support is unknown, so JSON is requested by prompt
    [attempt] = _attempts(ctx, run_id)
    assert attempt.cost["amount"] == pytest.approx((25 * 1000 + 7 * 2000) / 1_000_000)
    assert attempt.cost["source"] == "pricing table as of 2026-09-15"
    test = client.post(f"/api/v1/target-configs/{local}/connection-tests").json()["data"]
    run_all(ctx, seconds=20)
    result = client.get(f"/api/v1/connection-tests/{test['id']}").json()["data"]
    assert result["status"] == "success" and result["result"]["actual_model"] == "example-local-model"


def test_anthropic_as_model_judge(ctx, provider):
    project = make_project(ctx)
    with ctx.db.write() as session:
        judge = create_target_config(session, project, name="judge", adapter="anthropic", model="claude-opus-5",
                                     credential_ref="EVALAI_TEST_SECRET").id
    from eval_triage.db.models import Grade, GraderVersion
    from eval_triage.db.repositories import import_document
    from eval_triage.domain.fixtures import FIXTURES_DIR, load_source

    with ctx.db.write() as session:
        imported = import_document(session, project, load_source(
            FIXTURES_DIR / "packs" / "reference_answer" / "scenario.yaml", include_cases=["R01"]),
            judges={"judge": judge})
        suite = {"scenario_id": imported["scenario"].id, "dataset_id": imported["dataset"].id}
    answerer = _config(ctx, project, name="answers", adapter="demo", model="demo")
    provider.add("/v1/messages", claude_body(json.dumps({"verdict": "pass", "evidence": [
        {"source": "answer", "quote": "1969"}], "explanation": "Matches the reference."})))
    run_id = start_run(ctx, project, suite, {"baseline": answerer}, repeats=1)
    run_all(ctx)
    with ctx.db.read() as session:
        grade = session.scalars(select(Grade).join(GraderVersion, GraderVersion.id == Grade.grader_id)
                                .join(Trial, Trial.id == Grade.trial_id)
                                .where(GraderVersion.name == "reference-judge", Trial.run_id == run_id)).one()
        assert grade.verdict == "pass" and grade.judge_attempts[0]["model"] == "claude-opus-5"
        assert SENTINEL_SECRET not in json.dumps(grade.judge_attempts)
    judge_prompt = provider.bodies("/v1/messages")[0]["messages"][0]["content"]
    assert "<untrusted_output>" in judge_prompt
