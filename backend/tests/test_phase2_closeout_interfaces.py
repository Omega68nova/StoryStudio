from __future__ import annotations

from app.functions.imageGen import ImageGenerationRequest
from app.managers.imageGenManager import ImageKind, ImageManager, ManagedImageRequest


def test_generic_image_dimensions_are_optional() -> None:
    request = ImageGenerationRequest(positive_prompt="test")
    assert request.width is None
    assert request.height is None


def test_typed_image_manager_still_supplies_profile_dimensions() -> None:
    manager = ImageManager.__new__(ImageManager)
    # Test only profile logic without requiring an AI manager.
    from app.managers.imageGenManager import ImagePrompts, FullBodySizing
    manager.prompts = ImagePrompts()
    manager.full_body_sizing = FullBodySizing()

    profile = manager.profile_for(ImageKind.PORTRAIT)
    assert profile.width == 512
    assert profile.height == 512
    assert profile.transparent is True
