from __future__ import annotations

import httpx
import pytest

from app.services.runtimes import LlamaClient, RuntimeFailure


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
