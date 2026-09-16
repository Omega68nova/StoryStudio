from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse
from uuid import uuid4

import httpx
import websockets


class RuntimeFailure(RuntimeError):
    pass


ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]


class LlamaClient:
    _READY_STATES = {"loaded", "running"}

    def __init__(
        self,
        base_url: str,
        model_id: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        transition_timeout: float = 300,
        poll_interval: float = 0.5,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_id = model_id
        self._transport = transport
        self._transition_timeout = transition_timeout
        self._poll_interval = poll_interval

    def _client(self, timeout: float | None) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout, transport=self._transport)

    async def health(self) -> bool:
        try:
            async with self._client(2) as client:
                response = await client.get(f"{self.base_url}/health")
            return response.status_code in {200, 503}
        except httpx.HTTPError:
            return False

    async def model_status(self) -> str | None:
        """Return llama.cpp router state for this model when the endpoint is available."""
        try:
            async with self._client(5) as client:
                response = await client.get(f"{self.base_url}/models")
            if response.is_error:
                return None
            models = response.json().get("data", [])
        except (httpx.HTTPError, TypeError, ValueError):
            return None
        for model in models:
            aliases = model.get("aliases") or []
            if model.get("id") != self.model_id and self.model_id not in aliases:
                continue
            status = model.get("status")
            if isinstance(status, dict):
                status = status.get("value")
            return str(status).lower() if status else None
        return None

    async def _wait_for_model(self, desired: set[str], operation: str) -> None:
        deadline = asyncio.get_running_loop().time() + self._transition_timeout
        while True:
            status = await self.model_status()
            # Older llama.cpp servers may implement load/unload without exposing
            # router status. In that case the successful command is authoritative.
            if status is None or status in desired:
                return
            if asyncio.get_running_loop().time() >= deadline:
                raise RuntimeFailure(
                    f"llama-server timed out {operation} '{self.model_id}' (current state: {status})"
                )
            await asyncio.sleep(self._poll_interval)

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            body = response.json()
            error = body.get("error", body)
            return str(error.get("message", "")) if isinstance(error, dict) else ""
        except ValueError:
            return ""

    async def load(self) -> None:
        status = await self.model_status()
        if status in self._READY_STATES:
            return
        if status == "loading":
            await self._wait_for_model(self._READY_STATES, "loading")
            return

        async with self._client(300) as client:
            response = await client.post(f"{self.base_url}/models/load", json={"model": self.model_id})
        if response.is_error:
            # Two callers can observe an unloaded model and race to load it. The
            # llama.cpp router reports that harmless race as HTTP 400.
            if self._error_message(response).strip().lower() == "model is already running":
                await self._wait_for_model(self._READY_STATES, "loading")
                return
            raise RuntimeFailure(f"llama-server could not load '{self.model_id}': {response.text}")
        await self._wait_for_model(self._READY_STATES, "loading")

    async def unload(self) -> None:
        status = await self.model_status()
        if status == "unloaded":
            return
        async with self._client(120) as client:
            response = await client.post(f"{self.base_url}/models/unload", json={"model": self.model_id})
        if response.status_code not in {200, 404}:
            raise RuntimeFailure(f"llama-server model unload failed: {response.text}")
        await self._wait_for_model({"unloaded"}, "unloading")

    async def chat_stream(self, messages: list[dict[str, str]], *, max_tokens: int = 1400, cancel_event: asyncio.Event | None = None) -> AsyncIterator[str]:
        payload = {"model": self.model_id, "messages": messages, "stream": True, "max_tokens": max_tokens}
        async with self._client(None) as client:
            async with client.stream("POST", f"{self.base_url}/v1/chat/completions", json=payload) as response:
                if response.is_error:
                    body = await response.aread()
                    raise RuntimeFailure(f"Story generation failed: {body.decode(errors='replace')}")
                iterator = response.aiter_lines().__aiter__()
                while True:
                    next_line = asyncio.create_task(iterator.__anext__())
                    cancelled = asyncio.create_task(cancel_event.wait()) if cancel_event else None
                    waiting = {next_line, cancelled} if cancelled else {next_line}
                    done, _ = await asyncio.wait(waiting, return_when=asyncio.FIRST_COMPLETED)
                    if cancelled and cancelled in done and cancel_event and cancel_event.is_set():
                        next_line.cancel()
                        try:
                            await next_line
                        except (asyncio.CancelledError, StopAsyncIteration):
                            pass
                        raise asyncio.CancelledError
                    if cancelled:
                        cancelled.cancel()
                    try:
                        line = next_line.result()
                    except StopAsyncIteration:
                        return
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        return
                    try:
                        chunk = json.loads(data)
                        text = chunk["choices"][0]["delta"].get("content")
                    except (KeyError, IndexError, json.JSONDecodeError):
                        continue
                    if text:
                        yield text

    async def complete(self, messages: list[dict[str, str]], *, json_mode: bool = False, max_tokens: int = 1000) -> str:
        payload: dict[str, Any] = {"model": self.model_id, "messages": messages, "stream": False, "max_tokens": max_tokens}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        async with self._client(300) as client:
            response = await client.post(f"{self.base_url}/v1/chat/completions", json=payload)
        if response.is_error:
            raise RuntimeFailure(f"Storyteller auxiliary request failed: {response.text}")
        return response.json()["choices"][0]["message"]["content"]

    async def complete_stream(
        self, messages: list[dict[str, str]], *, max_tokens: int, json_mode: bool = False,
        progress: ProgressCallback | None = None, cancel_event: asyncio.Event | None = None,
    ) -> str:
        payload: dict[str, Any] = {"model": self.model_id, "messages": messages, "stream": True, "max_tokens": max_tokens}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        chunks: list[str] = []
        predicted = 0
        output_chars = 0
        async with self._client(None) as client:
            async with client.stream("POST", f"{self.base_url}/v1/chat/completions", json=payload) as response:
                if response.is_error:
                    body = await response.aread()
                    raise RuntimeFailure(f"Storyteller auxiliary request failed: {body.decode(errors='replace')}")
                async for line in response.aiter_lines():
                    if cancel_event and cancel_event.is_set():
                        raise asyncio.CancelledError
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        text = chunk["choices"][0]["delta"].get("content") or ""
                    except (KeyError, IndexError, json.JSONDecodeError):
                        continue
                    if text:
                        chunks.append(text)
                        output_chars += len(text)
                        estimated_tokens = max(1, output_chars // 4)
                        if progress and estimated_tokens >= predicted + 8:
                            predicted = estimated_tokens
                            await progress({"stage": "generating", "value": min(predicted, max_tokens), "max": max_tokens})
        return "".join(chunks)

    async def count_tokens(self, messages: list[dict[str, str]]) -> int:
        content = "\n".join(f"{message.get('role', 'user')}: {message.get('content', '')}" for message in messages)
        try:
            async with self._client(30) as client:
                response = await client.post(f"{self.base_url}/tokenize", json={"content": content, "add_special": True})
            if response.is_error:
                raise RuntimeFailure(response.text)
            payload = response.json()
            tokens = payload.get("tokens", [])
            return len(tokens) if isinstance(tokens, list) else int(payload.get("count", 0))
        except (httpx.HTTPError, ValueError, TypeError, RuntimeFailure):
            # Old llama.cpp builds may not expose /tokenize. This conservative
            # fallback is only for compatibility; current builds use the exact count.
            return max(1, len(content) // 3)

    async def tool_step(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], *, max_tokens: int = 320) -> dict[str, Any]:
        payload = {"model": self.model_id, "messages": messages, "stream": False, "tools": tools, "tool_choice": "auto", "max_tokens": max_tokens}
        async with self._client(300) as client:
            response = await client.post(f"{self.base_url}/v1/chat/completions", json=payload)
        if response.is_error:
            raise RuntimeFailure(f"Native tool request failed: {response.text}")
        message = response.json()["choices"][0]["message"]
        return {"content": message.get("content") or "", "tool_calls": message.get("tool_calls") or []}


class ComfyClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                response = await client.get(f"{self.base_url}/system_stats")
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def object_info(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(f"{self.base_url}/object_info")
        if response.is_error:
            raise RuntimeFailure(f"Unable to inspect ComfyUI nodes: {response.text}")
        return response.json()

    async def free(self) -> None:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{self.base_url}/free", json={"unload_models": True, "free_memory": True}
            )
        if response.is_error:
            raise RuntimeFailure(f"ComfyUI memory release failed: {response.text}")

    async def interrupt(self) -> None:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(f"{self.base_url}/interrupt")

    async def run_workflow(
        self,
        graph: dict[str, Any],
        output_node_id: str,
        progress: ProgressCallback,
        cancel_event: asyncio.Event,
    ) -> list[tuple[bytes, str]]:
        client_id = str(uuid4())
        ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        async with websockets.connect(f"{ws_url}/ws?clientId={client_id}", max_size=8 * 1024 * 1024) as socket:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    f"{self.base_url}/prompt", json={"prompt": graph, "client_id": client_id}
                )
            if response.is_error:
                raise RuntimeFailure(f"ComfyUI rejected the workflow: {response.text}")
            prompt_id = response.json()["prompt_id"]
            await progress({"stage": "queued", "prompt_id": prompt_id})
            while True:
                if cancel_event.is_set():
                    await self.interrupt()
                    raise asyncio.CancelledError
                try:
                    message = await asyncio.wait_for(socket.recv(), timeout=1)
                except TimeoutError:
                    continue
                if not isinstance(message, str):
                    continue
                event = json.loads(message)
                data = event.get("data", {})
                if data.get("prompt_id") not in {None, prompt_id}:
                    continue
                if event.get("type") == "progress":
                    await progress({"stage": "running", "node": data.get("node"), "value": data.get("value"), "max": data.get("max")})
                elif event.get("type") == "execution_error":
                    raise RuntimeFailure(data.get("exception_message", "ComfyUI workflow failed"))
                elif event.get("type") == "executing" and data.get("node") is None:
                    break
        return await self._download_outputs(prompt_id, output_node_id)

    async def _download_outputs(self, prompt_id: str, output_node_id: str) -> list[tuple[bytes, str]]:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(f"{self.base_url}/history/{prompt_id}")
            if response.is_error:
                raise RuntimeFailure(f"Unable to read ComfyUI output history: {response.text}")
            history = response.json().get(prompt_id, {})
            output = history.get("outputs", {}).get(output_node_id, {})
            images = output.get("images", [])
            downloaded: list[tuple[bytes, str]] = []
            for image in images:
                query = urlencode(
                    {
                        "filename": image["filename"],
                        "subfolder": image.get("subfolder", ""),
                        "type": image.get("type", "output"),
                    }
                )
                image_response = await client.get(f"{self.base_url}/view?{query}")
                image_response.raise_for_status()
                downloaded.append((image_response.content, Path(image["filename"]).suffix or ".png"))
        if not downloaded:
            raise RuntimeFailure(f"Mapped output node '{output_node_id}' produced no images")
        return downloaded


class ProcessSupervisor:
    def __init__(self) -> None:
        self.llama_process: asyncio.subprocess.Process | None = None
        self.comfy_process: asyncio.subprocess.Process | None = None
        self._log_tasks: list[asyncio.Task[None]] = []
        self.log_tail: dict[str, list[str]] = {"llama-server": [], "ComfyUI": []}

    async def ensure_started(self, settings: dict[str, Any]) -> tuple[LlamaClient, ComfyClient]:
        llama = await self.ensure_llama(settings)
        comfy = await self.ensure_comfy(settings)
        return llama, comfy

    async def ensure_llama(self, settings: dict[str, Any]) -> LlamaClient:
        model_id = settings["storyteller_model_id"] or Path(settings["storyteller_model_path"]).stem
        llama = LlamaClient(settings["llama_url"], model_id)
        if not await llama.health():
            await self._start_llama(settings)
            await self._wait_until(llama.health, "llama-server")
        return llama

    async def ensure_comfy(self, settings: dict[str, Any]) -> ComfyClient:
        comfy = ComfyClient(settings["comfy_url"])
        if not await comfy.health():
            await self._start_comfy(settings)
            await self._wait_until(comfy.health, "ComfyUI")
        return comfy

    async def _start_llama(self, settings: dict[str, Any]) -> None:
        executable = Path(settings["llama_executable"])
        model_path = Path(settings["storyteller_model_path"])
        if not executable.is_file():
            raise RuntimeFailure("Configure an existing llama-server executable in Settings")
        if not model_path.is_file():
            raise RuntimeFailure("Configure an existing GGUF storyteller model in Settings")
        parsed = urlparse(settings["llama_url"])
        args = [
            str(executable),
            "--models-dir",
            str(model_path.parent),
            "--host",
            "127.0.0.1",
            "--port",
            str(parsed.port or 8080),
            "--parallel",
            "1",
            "--ctx-size",
            str(settings.get("context_tokens", 8192)),
            *settings["llama_extra_args"],
        ]
        self.llama_process = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        self._log_tasks.append(asyncio.create_task(self._drain(self.llama_process, "llama-server")))

    async def _start_comfy(self, settings: dict[str, Any]) -> None:
        command = list(settings["comfy_command"])
        workdir = Path(settings["comfy_workdir"])
        if not command:
            raise RuntimeFailure("Configure the ComfyUI launch command in Settings")
        executable = shutil.which(command[0]) or (command[0] if Path(command[0]).is_file() else None)
        if executable is None:
            raise RuntimeFailure(f"ComfyUI command was not found: {command[0]}")
        if not workdir.is_dir():
            raise RuntimeFailure("Configure an existing ComfyUI working directory in Settings")
        listen_arguments = [argument for argument in command if argument.startswith("--listen=")]
        if "--listen" in command:
            index = command.index("--listen")
            listen_host = command[index + 1] if index + 1 < len(command) and not command[index + 1].startswith("--") else "127.0.0.1"
            if listen_host not in {"127.0.0.1", "localhost", "::1"}:
                raise RuntimeFailure("ComfyUI must listen on a loopback address")
        elif listen_arguments:
            if listen_arguments[-1].split("=", 1)[1] not in {"127.0.0.1", "localhost", "::1"}:
                raise RuntimeFailure("ComfyUI must listen on a loopback address")
        else:
            command.extend(["--listen", "127.0.0.1"])
        self.comfy_process = await asyncio.create_subprocess_exec(
            executable,
            *command[1:],
            cwd=workdir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        self._log_tasks.append(asyncio.create_task(self._drain(self.comfy_process, "ComfyUI")))

    async def _drain(self, process: asyncio.subprocess.Process, name: str) -> None:
        if process.stdout is None:
            return
        async for raw in process.stdout:
            lines = self.log_tail[name]
            lines.append(raw.decode(errors="replace").rstrip())
            del lines[:-100]

    async def _wait_until(self, check: Callable[[], Awaitable[bool]], name: str) -> None:
        for _ in range(120):
            if await check():
                return
            await asyncio.sleep(0.5)
        raise RuntimeFailure(f"{name} did not become ready within 60 seconds")

    async def shutdown(self) -> None:
        for process in (self.llama_process, self.comfy_process):
            if process is not None and process.returncode is None:
                process.terminate()
        for process in (self.llama_process, self.comfy_process):
            if process is not None and process.returncode is None:
                try:
                    await asyncio.wait_for(process.wait(), timeout=10)
                except TimeoutError:
                    process.kill()
        for task in self._log_tasks:
            if not task.done():
                task.cancel()
        self._log_tasks.clear()
        self.llama_process = None
        self.comfy_process = None
