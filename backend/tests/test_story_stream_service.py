from __future__ import annotations

import asyncio

from app.services.storyStreamService import (
    StoryStreamCallbacks,
    StoryStreamRequest,
    StoryStreamService,
)


class FakeLlama:
    def __init__(self, chunks):
        self.chunks = chunks

    async def _stream(self):
        for chunk in self.chunks:
            yield chunk

    def chat_stream(
        self,
        messages,
        max_tokens=None,
        cancel_event=None,
    ):
        return self._stream()


async def _noop(*args, **kwargs):
    return None


def test_stream_service_hides_inline_envelope() -> None:
    async def run():
        tokens = []

        async def on_token(text):
            tokens.append(text)

        async def on_inline(call):
            assert call["name"] == "suggestIllustration"
            return {
                "title": "Scene",
                "prompt": "prompt",
                "negative_prompt": "",
            }

        service = StoryStreamService(
            FakeLlama(
                [
                    "Visible ",
                    '<ss-tool>{"name":"suggestIllustration",',
                    '"arguments":{"prompt":"prompt"}}</ss-tool>',
                    " ending.",
                ]
            )
        )

        result = await service.stream(
            StoryStreamRequest(
                messages=[
                    {
                        "role": "user",
                        "content": "go",
                    }
                ],
                response_max_tokens=100,
                cancel_event=asyncio.Event(),
            ),
            StoryStreamCallbacks(
                on_phase=_noop,
                on_token=on_token,
                on_notice=_noop,
                on_tool=_noop,
                on_inline_action=on_inline,
                persist_partial=_noop,
                on_model_request=_noop,
                on_first_token=_noop,
            ),
        )

        assert result.content == "Visible  ending."
        assert result.inline_suggestion is not None
        assert "<ss-tool>" not in "".join(tokens)

    asyncio.run(run())


def test_stream_service_returns_checkpoint() -> None:
    async def run():
        async def on_inline(call):
            return {
                "_checkpoint": True,
                "invocation": {
                    "game_key": "flip_coin"
                },
            }

        service = StoryStreamService(
            FakeLlama(
                [
                    "Choose now. ",
                    '<ss-tool>{"name":"startMinigame",'
                    '"arguments":{"game_key":"flip_coin"}}</ss-tool>',
                ]
            )
        )

        result = await service.stream(
            StoryStreamRequest(
                messages=[
                    {
                        "role": "user",
                        "content": "flip",
                    }
                ],
                response_max_tokens=100,
                cancel_event=asyncio.Event(),
            ),
            StoryStreamCallbacks(
                on_phase=_noop,
                on_token=_noop,
                on_notice=_noop,
                on_tool=_noop,
                on_inline_action=on_inline,
                persist_partial=_noop,
                on_model_request=_noop,
                on_first_token=_noop,
            ),
        )

        assert result.checkpoint == {
            "game_key": "flip_coin"
        }

    asyncio.run(run())
