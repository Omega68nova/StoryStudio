from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, Literal

from app.managers.aiManager import AIGeneratorManager


ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]
RuntimeMode = Literal["normal", "planning"]


async def generate_text(
    manager: AIGeneratorManager,
    messages: list[dict[str, str]],
    *,
    max_tokens: int = 1000,
    json_mode: bool = False,
    temperature: float | None = None,
    runtime_mode: RuntimeMode = "normal",
) -> str:
    """Generic non-streaming llama.cpp chat completion.

    This function deliberately knows nothing about StoryManager, planning,
    world context, NPCs, or database jobs.
    """
    async with manager.text_session(
        runtime_mode,
        reason=f"{runtime_mode} text completion requested",
    ) as llama:
        return await llama.complete(
            messages,
            json_mode=json_mode,
            max_tokens=max_tokens,
            temperature=temperature,
        )


async def generate_text_stream(
    manager: AIGeneratorManager,
    messages: list[dict[str, str]],
    *,
    max_tokens: int = 1400,
    cancel_event: asyncio.Event | None = None,
    runtime_mode: RuntimeMode = "normal",
) -> AsyncIterator[str]:
    """Generic streaming chat completion used by story prose."""
    async with manager.text_session(
        runtime_mode,
        reason=f"{runtime_mode} streaming text generation requested",
    ) as llama:
        async for chunk in llama.chat_stream(
            messages,
            max_tokens=max_tokens,
            cancel_event=cancel_event,
        ):
            yield chunk


async def generate_structured_text(
    manager: AIGeneratorManager,
    messages: list[dict[str, str]],
    *,
    max_tokens: int,
    cancel_event: asyncio.Event | None = None,
    temperature: float | None = None,
    progress: ProgressCallback | None = None,
    runtime_mode: RuntimeMode = "normal",
) -> str:
    """Streaming JSON-mode completion for structured generation."""
    async with manager.text_session(
        runtime_mode,
        reason=f"{runtime_mode} structured generation requested",
    ) as llama:
        complete_stream = getattr(llama, "complete_stream", None)
        if complete_stream:
            return await complete_stream(
                messages,
                max_tokens=max_tokens,
                json_mode=True,
                progress=progress,
                cancel_event=cancel_event,
                temperature=temperature,
            )
        return await llama.complete(
            messages,
            json_mode=True,
            max_tokens=max_tokens,
            temperature=temperature,
        )
