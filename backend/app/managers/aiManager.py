from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable, Literal

from app.services.runtimes import ComfyClient, LlamaClient, ProcessSupervisor, RuntimeFailure


RuntimeKind = Literal["text", "image"]
RuntimeMode = Literal["normal", "planning"]
StateCallback = Callable[[str, str | None], Awaitable[None]]
SettingsLoader = Callable[[], dict[str, Any]]


@dataclass(slots=True, frozen=True)
class AIManagerSnapshot:
    owner: RuntimeKind | None
    transition_reason: str | None
    llama_runtime_mode: str
    requested_context_tokens: int | None
    load_count: int
    unload_count: int


class AIGeneratorManager:
    """Owns inference-runtime lifecycle and exclusive GPU ownership.

    This is intentionally *not* a story or image service. It only answers:
      - Which inference runtime should currently own the GPU?
      - Is llama.cpp/ComfyUI alive?
      - Does llama.cpp have the requested context?
      - How do we transition safely between text and image generation?

    Job persistence, EventHub messages and StoryStudio domain behavior stay
    outside this class during Phase 1.
    """

    def __init__(
        self,
        settings_loader: SettingsLoader,
        supervisor: ProcessSupervisor,
        *,
        state_callback: StateCallback | None = None,
    ) -> None:
        self._settings_loader = settings_loader
        self.supervisor = supervisor
        self._state_callback = state_callback

        self.llama: LlamaClient | None = None
        self.comfy: ComfyClient | None = None

        self.gpu_owner: RuntimeKind | None = None
        self.transition_reason: str | None = None
        self.llama_runtime_mode: str = "normal"
        self.llama_requested_context_tokens: int | None = None

        self.load_count = 0
        self.unload_count = 0

        # All ownership-changing operations go through one lock. This prevents
        # two jobs from racing a llama unload against a ComfyUI acquisition.
        self._runtime_lock = asyncio.Lock()

    def snapshot(self) -> AIManagerSnapshot:
        return AIManagerSnapshot(
            owner=self.gpu_owner,
            transition_reason=self.transition_reason,
            llama_runtime_mode=self.llama_runtime_mode,
            requested_context_tokens=self.llama_requested_context_tokens,
            load_count=self.load_count,
            unload_count=self.unload_count,
        )

    async def _state(self, state: str, detail: str | None = None) -> None:
        if self._state_callback is not None:
            await self._state_callback(state, detail)

    def _settings(self) -> dict[str, Any]:
        return dict(self._settings_loader())

    async def ensure_llama_runtime(self, runtime_mode: RuntimeMode = "normal") -> LlamaClient:
        async with self._runtime_lock:
            return await self._ensure_llama_runtime_unlocked(runtime_mode)

    async def _ensure_llama_runtime_unlocked(
        self, runtime_mode: RuntimeMode = "normal"
    ) -> LlamaClient:
        settings = self._settings()
        requested_context = int(
            settings.get(
                "planning_context_tokens",
                settings.get("context_tokens", 8192),
            )
            if runtime_mode == "planning"
            else settings.get("context_tokens", 8192)
        )

        if hasattr(self.supervisor, "ensure_llama"):
            self.llama = await self.supervisor.ensure_llama(
                settings, requested_context
            )
        elif self.llama and await self.llama.health():
            pass
        else:
            self.llama, discovered_comfy = await self.supervisor.ensure_started(
                settings
            )
            self.comfy = self.comfy or discovered_comfy

        properties = (
            await self.llama.runtime_properties(autoload=True)
            if hasattr(self.llama, "runtime_properties")
            else None
        )
        effective_context = (properties or {}).get("effective_context_tokens")
        if (
            effective_context is not None
            and int(effective_context) < requested_context
        ):
            ownership = (
                "StoryStudio-managed"
                if getattr(self.supervisor, "manages_llama", False)
                else "external"
            )
            raise RuntimeFailure(
                f"The {ownership} llama.cpp server provides "
                f"{int(effective_context):,} context tokens, but "
                f"{runtime_mode} generation requests {requested_context:,}. "
                "Increase the server context or lower the corresponding "
                "Runtime Settings value."
            )

        ownership_known = hasattr(self.supervisor, "manages_llama")
        if (
            runtime_mode == "planning"
            and ownership_known
            and not self.supervisor.manages_llama
            and effective_context is None
        ):
            raise RuntimeFailure(
                "The external llama.cpp server did not report its effective "
                "context through /props. Update llama.cpp before using raw "
                "planning autocomplete."
            )

        self.llama_runtime_mode = runtime_mode
        self.llama_requested_context_tokens = requested_context
        return self.llama

    async def ensure_comfy_runtime(self) -> ComfyClient:
        async with self._runtime_lock:
            return await self._ensure_comfy_runtime_unlocked()

    async def _ensure_comfy_runtime_unlocked(self) -> ComfyClient:
        if self.comfy and await self.comfy.health():
            return self.comfy

        settings = self._settings()
        if hasattr(self.supervisor, "ensure_comfy"):
            self.comfy = await self.supervisor.ensure_comfy(settings)
        else:
            discovered_llama, self.comfy = await self.supervisor.ensure_started(
                settings
            )
            self.llama = self.llama or discovered_llama
        return self.comfy

    async def ensure_text_ready(
        self,
        runtime_mode: RuntimeMode = "normal",
        *,
        reason: str = "text generation requested",
    ) -> LlamaClient:
        async with self._runtime_lock:
            llama = await self._ensure_llama_runtime_unlocked(runtime_mode)
            status = (
                await llama.model_status()
                if hasattr(llama, "model_status")
                else None
            )
            ready = status in {"loaded", "running", "ready"}
            should_load = not ready if status is not None else self.gpu_owner != "text"

            if should_load:
                await self._state("loading_storyteller", reason)
                self.transition_reason = reason
                await llama.load()
                self.load_count += 1

            self.gpu_owner = "text"
            return llama

    @asynccontextmanager
    async def text_session(
        self,
        runtime_mode: RuntimeMode = "normal",
        *,
        reason: str = "text generation requested",
    ) -> AsyncIterator[LlamaClient]:
        """Acquire the text model without unloading it when the call ends."""
        llama = await self.ensure_text_ready(runtime_mode, reason=reason)
        yield llama

    @asynccontextmanager
    async def image_session(
        self,
        *,
        reason: str = "image generation requested",
        restore_text: bool = True,
        restore_runtime_mode: RuntimeMode | None = None,
    ) -> AsyncIterator[ComfyClient]:
        """Give ComfyUI exclusive GPU ownership, then restore active text.

        The ownership lock is held for the entire image operation. That mirrors
        the scheduler's current single-GPU assumption and prevents a second
        generation path from reloading llama.cpp halfway through a workflow.
        An image-first session does not start llama.cpp merely to unload it.
        """
        async with self._runtime_lock:
            restore_loaded_text = restore_text and self.gpu_owner == "text"
            comfy = await self._ensure_comfy_runtime_unlocked()
            llama: LlamaClient | None = None
            if restore_loaded_text:
                llama = await self._ensure_llama_runtime_unlocked(
                    restore_runtime_mode or self.llama_runtime_mode
                )

            await self._state("switching_to_image", reason)
            self.transition_reason = reason

            if llama is not None:
                status = (
                    await llama.model_status()
                    if hasattr(llama, "model_status")
                    else None
                )
                if status != "unloaded":
                    await llama.unload()
                    self.unload_count += 1

            self.gpu_owner = "image"
            try:
                yield comfy
            finally:
                if restore_loaded_text and llama is not None:
                    await self._state(
                        "restoring_storyteller",
                        "image generation finished; restoring text model",
                    )
                    try:
                        await comfy.free()
                    finally:
                        await llama.load()
                        self.load_count += 1
                        self.gpu_owner = "text"
                        self.transition_reason = (
                            "image generation finished; storyteller restored"
                        )
                else:
                    # Even when the caller deliberately leaves text unloaded,
                    # release ComfyUI's loaded models so ownership is explicit.
                    await comfy.free()
                    self.gpu_owner = None

    async def interrupt_image(self) -> None:
        if self.comfy is not None:
            await self.comfy.interrupt()

    async def shutdown(self) -> None:
        await self.supervisor.shutdown()
        self.llama = None
        self.comfy = None
        self.gpu_owner = None
