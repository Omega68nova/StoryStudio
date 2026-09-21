from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.handlers.storyInlineActions import INLINE_TOOL_NAMES
from app.services.inline_tools import InlineToolParser


AsyncPhaseCallback = Callable[[str, str], Awaitable[None]]
AsyncTokenCallback = Callable[[str], Awaitable[None]]
AsyncNoticeCallback = Callable[[str], Awaitable[None]]
AsyncToolCallback = Callable[
    [str, str, dict[str, Any] | None],
    Awaitable[None],
]
AsyncInlineActionCallback = Callable[
    [dict[str, Any]],
    Awaitable[dict[str, Any] | None],
]
AsyncPartialCallback = Callable[[str], Awaitable[None]]
AsyncVoidCallback = Callable[[], Awaitable[None]]
AsyncFirstTokenCallback = Callable[[float], Awaitable[None]]


@dataclass(slots=True)
class StoryStreamCallbacks:
    on_phase: AsyncPhaseCallback
    on_token: AsyncTokenCallback
    on_notice: AsyncNoticeCallback
    on_tool: AsyncToolCallback
    on_inline_action: AsyncInlineActionCallback
    persist_partial: AsyncPartialCallback
    on_model_request: AsyncVoidCallback
    on_first_token: AsyncFirstTokenCallback


@dataclass(slots=True)
class StoryStreamRequest:
    messages: list[dict[str, str]]
    response_max_tokens: int
    cancel_event: asyncio.Event
    initial_content: str = ""
    initial_suggestion: dict[str, str] | None = None
    max_repairs: int = 2
    partial_checkpoint_chars: int = 256


@dataclass(slots=True)
class StoryStreamResult:
    content: str
    inline_suggestion: dict[str, str] | None
    checkpoint: dict[str, Any] | None
    stop_requested: bool
    repairs: int


class StoryStreamService:
    """Owns live storyteller streaming mechanics.

    This service intentionally does not know about:
      * generation_jobs
      * EventHub
      * WorldEngine
      * minigame session persistence
      * story commit/finalization

    Callbacks adapt those concerns at the handler boundary.
    """

    def __init__(
        self,
        llama: Any,
    ) -> None:
        self.llama = llama

    async def stream(
        self,
        request: StoryStreamRequest,
        callbacks: StoryStreamCallbacks,
    ) -> StoryStreamResult:
        messages = list(request.messages)
        chunks: list[str] = (
            [request.initial_content]
            if request.initial_content
            else []
        )
        persisted_chars = len(
            request.initial_content
        )
        inline_suggestion = (
            request.initial_suggestion
        )
        repairs = 0
        checkpoint: dict[str, Any] | None = None
        stop_requested = False
        first_token_seen = False
        started = time.monotonic()

        await callbacks.on_phase(
            "streaming_prose",
            "Streaming story",
        )

        while True:
            parser = InlineToolParser()
            invalid: dict[str, Any] | None = None

            if repairs:
                await callbacks.on_phase(
                    "streaming_prose",
                    "Streaming corrected continuation",
                )

            await callbacks.on_model_request()

            try:
                stream = self.llama.chat_stream(
                    messages,
                    max_tokens=request.response_max_tokens,
                    cancel_event=request.cancel_event,
                )
            except TypeError:
                # Preserve compatibility with older llama client wrappers.
                stream = self.llama.chat_stream(
                    messages,
                    cancel_event=request.cancel_event,
                )

            try:
                async for token in stream:
                    visible, calls, parser_errors = parser.feed(
                        token
                    )

                    if visible:
                        if not first_token_seen:
                            first_token_seen = True
                            await callbacks.on_first_token(
                                (
                                    time.monotonic()
                                    - started
                                )
                                * 1000
                            )

                        chunks.append(visible)
                        await callbacks.on_token(
                            visible
                        )

                        current_chars = sum(
                            len(part)
                            for part in chunks
                        )
                        if (
                            current_chars
                            - persisted_chars
                            >= request.partial_checkpoint_chars
                        ):
                            await callbacks.persist_partial(
                                "".join(chunks)
                            )
                            persisted_chars = (
                                current_chars
                            )

                    for parser_error in parser_errors:
                        invalid = parser_error.payload()
                        break

                    if invalid:
                        break

                    for call in calls:
                        try:
                            await callbacks.on_phase(
                                "validating_action",
                                f"Validating {call['name']}",
                            )

                            result = (
                                await callbacks.on_inline_action(
                                    call
                                )
                            )

                            if (
                                result
                                and result.get(
                                    "_checkpoint"
                                )
                            ):
                                checkpoint = result[
                                    "invocation"
                                ]
                            elif result:
                                inline_suggestion = (
                                    result
                                )

                            await callbacks.on_tool(
                                call["name"],
                                "accepted",
                                None,
                            )

                            await callbacks.on_phase(
                                "streaming_prose",
                                "Streaming story",
                            )

                        except Exception as exc:
                            # WorldValidationError is intentionally not imported
                            # here. The handler/domain adapter decides what counts
                            # as a valid inline-action exception and provides a
                            # normalized payload through the exception attribute.
                            payload = getattr(
                                exc,
                                "story_stream_error",
                                None,
                            )
                            if payload is None:
                                raise

                            invalid = payload
                            await callbacks.on_tool(
                                call["name"],
                                "rejected",
                                invalid,
                            )
                            break

                        if checkpoint:
                            break

                    if invalid or checkpoint:
                        break

            except asyncio.CancelledError:
                if not request.cancel_event.is_set():
                    raise
                stop_requested = True

            if stop_requested:
                break

            tail, tail_errors = parser.finish()
            if tail:
                chunks.append(tail)
                await callbacks.on_token(tail)

            if (
                not invalid
                and tail_errors
            ):
                invalid = (
                    tail_errors[0].payload()
                )

            if checkpoint:
                await callbacks.persist_partial(
                    "".join(chunks).strip()
                )
                break

            if (
                not invalid
                or repairs >= request.max_repairs
            ):
                if invalid:
                    await callbacks.on_notice(
                        "An invalid world action was omitted "
                        f"after {request.max_repairs} repair attempts."
                    )
                break

            repairs += 1

            await callbacks.on_phase(
                "repairing_action",
                (
                    "Repairing invalid action "
                    f"({repairs}/{request.max_repairs})"
                ),
            )
            await callbacks.on_notice(
                invalid["explanation"]
                + " The storyteller is continuing "
                "with a correction."
            )

            messages = [
                *messages,
                {
                    "role": "assistant",
                    "content": "".join(chunks),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "instruction": (
                                "Continue exactly where the partial prose "
                                "ends. Retry the rejected action safely or "
                                "omit it. Do not repeat prose."
                            ),
                            "validation_error": invalid,
                            "allowed_inline_tools": INLINE_TOOL_NAMES,
                        }
                    ),
                },
            ]

        return StoryStreamResult(
            content="".join(chunks).strip(),
            inline_suggestion=inline_suggestion,
            checkpoint=checkpoint,
            stop_requested=stop_requested,
            repairs=repairs,
        )
