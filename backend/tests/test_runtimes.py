from __future__ import annotations

import httpx
import pytest

from app.services.runtimes import LlamaClient, ProcessSupervisor, RuntimeFailure


@pytest.mark.asyncio
async def test_raw_planning_endpoints_apply_template_stream_and_report_context() -> None:
    requests: list[tuple[str, str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = __import__("json").loads(request.content) if request.content else {}
        requests.append((request.method, request.url.path, payload))
        if request.url.path == "/apply-template":
            return httpx.Response(200, json={"prompt": "<chat>JSON:"})
        if request.url.path == "/props":
            return httpx.Response(200, json={
                "default_generation_settings": {"n_ctx": 32768}, "total_slots": 1, "build_info": "test",
            })
        if request.url.path == "/completion":
            body = (
                'data: {"prompt_progress":{"total":12,"cache":8,"processed":4,"time_ms":1}}\n\n'
                'data: {"content":"{\\"ok\\":true}","stop":false}\n\n'
                'data: {"content":"","stop":true,"stop_type":"eos","truncated":false,'
                '"tokens_cached":8,"tokens_evaluated":4,"timings":{"predicted_n":5},'
                '"generation_settings":{"n_ctx":32768}}\n\n'
            )
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        raise AssertionError(request.url.path)

    client = LlamaClient("http://llama.test", "story-model", transport=httpx.MockTransport(handler))
    prompt = await client.apply_template([{"role": "user", "content": "JSON only"}])
    result = await client.raw_complete_stream(prompt, n_predict=100, cache_prompt=True, id_slot=0)
    properties = await client.runtime_properties()

    assert prompt == "<chat>JSON:"
    assert result["content"] == '{"ok":true}'
    assert result["stop_type"] == "eos" and result["tokens_cached"] == 8
    assert result["tokens_predicted"] == 5 and result["n_ctx"] == 32768
    assert properties and properties["effective_context_tokens"] == 32768
    completion_payload = next(payload for _, path, payload in requests if path == "/completion")
    assert completion_payload["cache_prompt"] is True and completion_payload["id_slot"] == 0


@pytest.mark.asyncio
async def test_managed_llama_context_change_restarts_only_llama(monkeypatch, tmp_path) -> None:
    supervisor = ProcessSupervisor()
    original_comfy = object()
    supervisor.llama_process = type("Process", (), {"returncode": None})()
    supervisor.comfy_process = original_comfy  # type: ignore[assignment]
    supervisor.active_llama_context_tokens = 8192
    calls: list[tuple[str, int | None]] = []

    async def shutdown_llama() -> None:
        calls.append(("stop", supervisor.active_llama_context_tokens))
        supervisor.llama_process = None
        supervisor.active_llama_context_tokens = None

    async def start_llama(settings, context_tokens=None) -> None:
        calls.append(("start", context_tokens))
        supervisor.llama_process = type("Process", (), {"returncode": None})()
        supervisor.active_llama_context_tokens = context_tokens

    async def wait_until(check, name) -> None: return None

    monkeypatch.setattr(supervisor, "shutdown_llama", shutdown_llama)
    monkeypatch.setattr(supervisor, "_start_llama", start_llama)
    monkeypatch.setattr(supervisor, "_wait_until", wait_until)
    settings = {
        "storyteller_model_id": "story-model", "storyteller_model_path": str(tmp_path / "model.gguf"),
        "llama_url": "http://llama.test", "context_tokens": 8192, "llama_extra_args": [],
    }

    await supervisor.restart_llama(settings, 32768)

    assert calls == [("stop", 8192), ("start", 32768)]
    assert supervisor.comfy_process is original_comfy


@pytest.mark.asyncio
async def test_complete_sends_optional_temperature_for_one_request() -> None:
    payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(__import__("json").loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "direction"}}]})

    client = LlamaClient("http://llama.test", "story-model", transport=httpx.MockTransport(handler))
    assert await client.complete([{"role": "user", "content": "invent"}], temperature=1.25) == "direction"
    assert payloads[0]["temperature"] == 1.25


@pytest.mark.asyncio
async def test_load_is_noop_when_model_is_already_loaded() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"data": [{"id": "story-model", "status": {"value": "loaded"}}]},
        )

    client = LlamaClient("http://llama.test", "story-model", transport=httpx.MockTransport(handler))
    await client.load()

    assert [(request.method, request.url.path) for request in requests] == [("GET", "/models")]


@pytest.mark.asyncio
async def test_load_accepts_already_running_race() -> None:
    statuses = iter(["unloaded", "loaded"])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                json={"data": [{"id": "story-model", "status": {"value": next(statuses)}}]},
            )
        return httpx.Response(
            400,
            json={"error": {"code": 400, "message": "model is already running", "type": "invalid_request_error"}},
        )

    client = LlamaClient("http://llama.test", "story-model", transport=httpx.MockTransport(handler))
    await client.load()


@pytest.mark.asyncio
async def test_load_still_reports_real_router_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"data": []})
        return httpx.Response(404, json={"error": {"message": "File Not Found"}})

    client = LlamaClient("http://llama.test", "missing", transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeFailure, match="File Not Found"):
        await client.load()
