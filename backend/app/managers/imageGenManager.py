from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Awaitable, Callable

from app.functions.imageGen import (
    ImageGenerationRequest,
    ImageWorkflow,
    generate_image,
)
from app.managers.aiManager import AIGeneratorManager


class ImageKind(StrEnum):
    PORTRAIT = "portrait"
    FULL_BODY = "full_body"
    BACKGROUND = "background"
    ICON = "icon"


@dataclass(slots=True, frozen=True)
class ImagePrompts:
    portrait_prefix: str = (
        "portrait, anime style, full color, clean lineart, soft shading, "
        "looking at viewer, simple background, white background,"
    )
    full_body_prefix: str = (
        "full body, standing, anime style, full color, clean lineart, "
        "soft shading, looking at viewer, simple background, white background,"
    )
    icon_prefix: str = (
        "(((no humans))), simple background, white background,"
    )


@dataclass(slots=True, frozen=True)
class FullBodySizing:
    """Full-body canvas policy.

    Your plan lists 2048x784 for tall characters and 1552x784 for children.
    This implementation interprets that as 784 wide and 1552-2048 tall,
    because these are explicitly tall/full-body assets.

    `height_factor` is normalized 0..1:
      0.0 -> child_height
      1.0 -> adult_height
    """

    width: int = 784
    child_height: int = 1552
    adult_height: int = 2048

    def size(self, height_factor: float) -> tuple[int, int]:
        factor = min(1.0, max(0.0, float(height_factor)))
        height = round(
            self.child_height
            + ((self.adult_height - self.child_height) * factor)
        )
        # Keep dimensions divisible by 8 for common latent image pipelines.
        height = max(64, int(round(height / 8) * 8))
        return self.width, height


@dataclass(slots=True, frozen=True)
class ImageProfile:
    kind: ImageKind
    width: int
    height: int
    transparent: bool
    prefix: str = ""


@dataclass(slots=True, frozen=True)
class ManagedImageRequest:
    kind: ImageKind
    prompt: str
    negative_prompt: str = ""
    full_body_height_factor: float = 1.0
    seed: int | None = None
    steps: int | None = None
    guidance: float | None = None
    checkpoint: str | None = None


ProgressCallback = Callable[[dict], Awaitable[None]]


class ImageManager:
    """Translates StoryStudio image concepts into generic image requests."""

    def __init__(
        self,
        ai_manager: AIGeneratorManager,
        *,
        prompts: ImagePrompts | None = None,
        full_body_sizing: FullBodySizing | None = None,
    ) -> None:
        self.ai_manager = ai_manager
        self.prompts = prompts or ImagePrompts()
        self.full_body_sizing = full_body_sizing or FullBodySizing()

    @staticmethod
    def _join_prompt(prefix: str, prompt: str) -> str:
        prefix = prefix.strip()
        prompt = prompt.strip()
        if not prefix:
            return prompt
        if not prompt:
            return prefix
        return f"{prefix} {prompt}"

    def profile_for(
        self,
        kind: ImageKind,
        *,
        full_body_height_factor: float = 1.0,
    ) -> ImageProfile:
        if kind == ImageKind.PORTRAIT:
            return ImageProfile(
                kind=kind,
                width=512,
                height=512,
                transparent=True,
                prefix=self.prompts.portrait_prefix,
            )
        if kind == ImageKind.FULL_BODY:
            width, height = self.full_body_sizing.size(
                full_body_height_factor
            )
            return ImageProfile(
                kind=kind,
                width=width,
                height=height,
                transparent=True,
                prefix=self.prompts.full_body_prefix,
            )
        if kind == ImageKind.BACKGROUND:
            return ImageProfile(
                kind=kind,
                width=1920,
                height=1080,
                transparent=False,
            )
        if kind == ImageKind.ICON:
            return ImageProfile(
                kind=kind,
                width=512,
                height=512,
                transparent=True,
                prefix=self.prompts.icon_prefix,
            )
        raise ValueError(f"Unsupported image kind: {kind}")

    def build_request(
        self,
        request: ManagedImageRequest,
    ) -> ImageGenerationRequest:
        profile = self.profile_for(
            request.kind,
            full_body_height_factor=request.full_body_height_factor,
        )
        return ImageGenerationRequest(
            positive_prompt=self._join_prompt(
                profile.prefix,
                request.prompt,
            ),
            negative_prompt=request.negative_prompt,
            width=profile.width,
            height=profile.height,
            make_transparent=profile.transparent,
            seed=request.seed,
            steps=request.steps,
            guidance=request.guidance,
            checkpoint=request.checkpoint,
        )

    async def generate(
        self,
        workflow: ImageWorkflow,
        request: ManagedImageRequest,
        *,
        cancel_event: asyncio.Event | None = None,
        progress: ProgressCallback | None = None,
        filename_prefix: str | None = None,
    ) -> list[tuple[bytes, str]]:
        generic = self.build_request(request)
        return await generate_image(
            self.ai_manager,
            workflow,
            generic,
            cancel_event=cancel_event,
            progress=progress,
            filename_prefix=filename_prefix,
        )

    async def generate_generic(
        self,
        workflow: ImageWorkflow,
        request: ImageGenerationRequest,
        *,
        cancel_event: asyncio.Event | None = None,
        progress: ProgressCallback | None = None,
        filename_prefix: str | None = None,
    ) -> list[tuple[bytes, str]]:
        """Run an already-resolved request under ImageManager ownership.

        Job payload resolution is compatibility-sensitive. This adapter keeps
        legacy generic requests unchanged while preventing job handlers from
        bypassing the semantic manager.
        """
        return await generate_image(
            self.ai_manager,
            workflow,
            request,
            cancel_event=cancel_event,
            progress=progress,
            filename_prefix=filename_prefix,
        )
