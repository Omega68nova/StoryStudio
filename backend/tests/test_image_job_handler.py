from __future__ import annotations

from app.handlers.imageJobHandler import ImageJobHandler


def test_mime_types() -> None:
    handler = ImageJobHandler()
    assert handler._mime_type("a.png") == "image/png"
    assert handler._mime_type("a.jpg") == "image/jpeg"
    assert handler._mime_type("a.jpeg") == "image/jpeg"
    assert handler._mime_type("a.webp") == "image/webp"


def test_optional_values() -> None:
    handler = ImageJobHandler()
    assert handler._optional_int(None) is None
    assert handler._optional_int("12") == 12
    assert handler._optional_float("7.5") == 7.5
    assert handler._optional_str("") is None
