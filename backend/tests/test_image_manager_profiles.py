from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.handlers.imageJobHandler import ImageJobHandler
from app.managers.imageGenManager import (
    FullBodySizing,
    ImageKind,
    ImageManager,
    ImagePrompts,
    ManagedImageRequest,
)


def manager(prompts: ImagePrompts | None = None) -> ImageManager:
    # build_request/profile_for do not touch the runtime manager.
    return ImageManager(object(), prompts=prompts)  # type: ignore[arg-type]


def test_portrait_profile_is_square_transparent_and_prefixed() -> None:
    request = manager().build_request(
        ManagedImageRequest(
            kind=ImageKind.PORTRAIT,
            prompt="silver-haired courier",
        )
    )
    assert (request.width, request.height) == (512, 512)
    assert request.make_transparent is True
    assert request.positive_prompt.startswith(
        "portrait, anime style, full color, clean lineart, soft shading, "
        "looking at viewer, simple background, white background,"
    )
    assert request.positive_prompt.endswith("silver-haired courier")


def test_full_body_profile_interpolates_character_height() -> None:
    image_manager = manager()

    child = image_manager.build_request(
        ManagedImageRequest(
            kind=ImageKind.FULL_BODY,
            prompt="child courier",
            full_body_height_factor=0.0,
        )
    )
    midpoint = image_manager.build_request(
        ManagedImageRequest(
            kind=ImageKind.FULL_BODY,
            prompt="average-height courier",
            full_body_height_factor=0.5,
        )
    )
    tall = image_manager.build_request(
        ManagedImageRequest(
            kind=ImageKind.FULL_BODY,
            prompt="very tall courier",
            full_body_height_factor=1.0,
        )
    )

    assert (child.width, child.height) == (784, 1552)
    assert (midpoint.width, midpoint.height) == (784, 1800)
    assert (tall.width, tall.height) == (784, 2048)
    assert child.make_transparent is True
    assert midpoint.make_transparent is True
    assert tall.make_transparent is True
    assert tall.positive_prompt.startswith(
        "full body, standing, anime style, full color, clean lineart, "
        "soft shading, looking at viewer, simple background, white background,"
    )


def test_background_profile_uses_normal_output_and_hd_size() -> None:
    request = manager().build_request(
        ManagedImageRequest(
            kind=ImageKind.BACKGROUND,
            prompt="mountain village at dusk",
        )
    )
    assert (request.width, request.height) == (1920, 1080)
    assert request.make_transparent is False
    assert request.positive_prompt == "mountain village at dusk"


def test_icon_profile_is_square_transparent_and_blocks_human_bias() -> None:
    request = manager().build_request(
        ManagedImageRequest(
            kind=ImageKind.ICON,
            prompt="ancient brass key",
        )
    )
    assert (request.width, request.height) == (512, 512)
    assert request.make_transparent is True
    assert request.positive_prompt.startswith(
        "(((no humans))),simple background, white background,"
    )


def test_image_prefixes_are_configurable() -> None:
    prompts = ImagePrompts(
        portrait_prefix="CUSTOM PORTRAIT,",
        full_body_prefix="CUSTOM FULL BODY,",
        icon_prefix="CUSTOM ICON,",
    )
    image_manager = manager(prompts)

    assert image_manager.build_request(
        ManagedImageRequest(kind=ImageKind.PORTRAIT, prompt="subject")
    ).positive_prompt == "CUSTOM PORTRAIT, subject"
    assert image_manager.build_request(
        ManagedImageRequest(kind=ImageKind.FULL_BODY, prompt="subject")
    ).positive_prompt == "CUSTOM FULL BODY, subject"
    assert image_manager.build_request(
        ManagedImageRequest(kind=ImageKind.ICON, prompt="subject")
    ).positive_prompt == "CUSTOM ICON, subject"


@pytest.mark.parametrize(
    ("payload", "media_kind", "expected"),
    [
        ({}, "portrait", ImageKind.PORTRAIT),
        ({}, "full_body", ImageKind.FULL_BODY),
        ({}, "location", ImageKind.BACKGROUND),
        ({"image_kind": "icon"}, None, ImageKind.ICON),
        ({"environment_background_id": "background"}, None, ImageKind.BACKGROUND),
        ({}, None, None),
    ],
)
def test_job_handler_resolves_semantic_image_kind(
    payload: dict,
    media_kind: str | None,
    expected: ImageKind | None,
) -> None:
    context = SimpleNamespace(payload=payload)
    assert ImageJobHandler._semantic_kind(context, media_kind) == expected


def test_full_body_sizing_clamps_factor() -> None:
    sizing = FullBodySizing()
    assert sizing.size(-10) == (784, 1552)
    assert sizing.size(10) == (784, 2048)
