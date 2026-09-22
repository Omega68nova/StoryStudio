from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable

from app.services.planning import random_direction_messages
from app.services.runtimes import RuntimeFailure


ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]


def planning_json_error(raw: str) -> json.JSONDecodeError | None:
    text = raw.strip()
    if text.startswith("```"):
        first_break = text.find("\n")
        text = text[first_break + 1:] if first_break >= 0 else text[3:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    try:
        json.loads(text)
    except json.JSONDecodeError as exc:
        return exc
    return None


def open_json_containers(text: str) -> tuple[list[tuple[str, int]], bool]:
    stack: list[tuple[str, int]] = []
    in_string = False
    escaped = False
    for position, character in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
        elif character == '"':
            in_string = True
        elif character in "[{":
            stack.append((character, position))
        elif character in "]}":
            if stack:
                stack.pop()
    return stack, in_string


def looks_like_token_truncation(
    raw: str,
    error: json.JSONDecodeError,
) -> bool:
    text = raw.rstrip()
    near_end = error.pos >= max(0, len(text) - 48)
    stack, in_string = open_json_containers(text)
    return (
        "Unterminated string" in error.msg
        or (near_end and (in_string or bool(stack)))
    )


class PlanningGenerationCore:
    """Reusable structured-generation primitives.

    This is now the sole owner of raw structured-planning generation primitives.
    """

    async def random_direction(
        self,
        context: Any,
        theme: str,
    ) -> str:
        llama = await context.ai.ensure_text_ready(
            "planning",
            reason="random planning direction requested",
        )
        messages = random_direction_messages(theme)
        complete_stream = getattr(llama, "complete_stream", None)
        if complete_stream:
            raw = await complete_stream(
                messages,
                max_tokens=600,
                temperature=1.25,
                cancel_event=context.cancel_event,
            )
        else:
            raw = await llama.complete(
                messages,
                max_tokens=600,
                temperature=1.25,
            )
        direction = str(raw or "").strip()
        if not direction:
            raise RuntimeFailure(
                "The storyteller returned an empty random direction"
            )
        return direction

    async def raw_complete_json(
        self,
        context: Any,
        llama: Any,
        messages: list[dict[str, str]],
        context_tokens: int,
        stage_label: str,
        progress: ProgressCallback | None,
    ) -> tuple[str, str | None, int, int]:
        apply_template = getattr(llama, "apply_template", None)
        raw_complete = getattr(llama, "raw_complete_stream", None)
        if not apply_template or not raw_complete:
            raise RuntimeFailure(
                "The configured llama.cpp runtime does not support raw "
                "planning autocomplete."
            )

        formatted_prompt = await apply_template(messages)
        count_prompt = getattr(llama, "count_prompt_tokens", None)
        prompt_tokens = (
            int(await count_prompt(formatted_prompt))
            if count_prompt
            else max(1, len(formatted_prompt) // 3)
        )
        combined = ""
        last_allowance = 0

        for attempt in range(4):
            if context.cancel_event.is_set():
                raise asyncio.CancelledError

            full_prompt = formatted_prompt + combined
            used_tokens = (
                int(await count_prompt(full_prompt))
                if count_prompt
                else max(1, len(full_prompt) // 3)
            )
            allowance = context_tokens - used_tokens - 128
            last_allowance = max(0, allowance)
            if allowance < 64:
                context.db.update_job_partial_output(
                    context.job_id,
                    combined,
                )
                return (
                    combined,
                    (
                        f"{stage_label} exhausted its "
                        f"{context_tokens:,}-token planning context while "
                        "autocomplete was still incomplete."
                    ),
                    prompt_tokens,
                    last_allowance,
                )

            result = await raw_complete(
                full_prompt,
                n_predict=allowance,
                cache_prompt=True,
                id_slot=0,
                temperature=0.0 if attempt else None,
                cancel_event=context.cancel_event,
                progress=progress,
                stop_when=lambda suffix: (
                    planning_json_error(combined + suffix) is None
                ),
            )
            suffix = str(result.get("content") or "")
            if not suffix:
                result = await raw_complete(
                    full_prompt,
                    n_predict=allowance,
                    cache_prompt=False,
                    id_slot=0,
                    temperature=0.0 if attempt else None,
                    cancel_event=context.cancel_event,
                    progress=progress,
                    stop_when=lambda retry_suffix: (
                        planning_json_error(
                            combined + retry_suffix
                        ) is None
                    ),
                )
                suffix = str(result.get("content") or "")
                if not suffix:
                    details = ", ".join(
                        f"{key}={result.get(key)!r}"
                        for key in (
                            "stop_type",
                            "truncated",
                            "tokens_cached",
                            "tokens_evaluated",
                            "tokens_predicted",
                            "n_ctx",
                        )
                    )
                    raise RuntimeFailure(
                        f"{stage_label} returned no raw completion "
                        f"after a cache-free retry ({details})"
                    )

            combined += suffix
            context.db.update_job_partial_output(
                context.job_id,
                combined,
            )
            error = planning_json_error(combined)
            if error is None:
                return combined, None, prompt_tokens, last_allowance

            stopped_for_limit = (
                bool(result.get("truncated"))
                or result.get("stop_type") == "limit"
            )
            if (
                not stopped_for_limit
                and not looks_like_token_truncation(
                    combined,
                    error,
                )
            ):
                return combined, None, prompt_tokens, last_allowance

        return (
            combined,
            (
                f"{stage_label} remained incomplete after three raw "
                "autocomplete attempts."
            ),
            prompt_tokens,
            last_allowance,
        )


# Compatibility import names for migrated structured-generation tests.
_planning_json_error = planning_json_error
_looks_like_token_truncation = looks_like_token_truncation
