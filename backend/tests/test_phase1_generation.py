from __future__ import annotations

from app.managers.imageGenManager import (
    FullBodySizing,
    ImageKind,
    ImageManager,
    ImagePrompts,
)


class DummyAIManager:
    pass


def test_portrait_profile() -> None:
    manager = ImageManager(DummyAIManager())  # type: ignore[arg-type]
    profile = manager.profile_for(ImageKind.PORTRAIT)
    assert (profile.width, profile.height) == (512, 512)
    assert profile.transparent is True


def test_background_profile() -> None:
    manager = ImageManager(DummyAIManager())  # type: ignore[arg-type]
    profile = manager.profile_for(ImageKind.BACKGROUND)
    assert (profile.width, profile.height) == (1920, 1080)
    assert profile.transparent is False


def test_full_body_sizing_interpolates() -> None:
    sizing = FullBodySizing()
    assert sizing.size(0.0) == (784, 1552)
    assert sizing.size(1.0) == (784, 2048)
    width, height = sizing.size(0.5)
    assert width == 784
    assert 1552 < height < 2048
    assert height % 8 == 0


def test_icon_prefix_is_applied() -> None:
    manager = ImageManager(
        DummyAIManager(),  # type: ignore[arg-type]
        prompts=ImagePrompts(icon_prefix="NO PEOPLE,"),
    )
    request = manager.build_request(
        __import__(
            "app.managers.imageGenManager",
            fromlist=["ManagedImageRequest"],
        ).ManagedImageRequest(
            kind=ImageKind.ICON,
            prompt="golden compass",
        )
    )
    assert request.positive_prompt.startswith("NO PEOPLE,")
    assert request.make_transparent is True
