from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError


IMAGE_FORMATS = {"PNG": ("image/png", ".png"), "JPEG": ("image/jpeg", ".jpg"), "WEBP": ("image/webp", ".webp")}
AUDIO_TYPES = {".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".wav": "audio/wav", ".m4a": "audio/mp4"}


class MediaValidationError(ValueError):
    pass


def validate_image(data: bytes) -> tuple[str, str, int, int]:
    if not data or len(data) > 20 * 1024 * 1024:
        raise MediaValidationError("Images must be between 1 byte and 20 MB")
    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()
        with Image.open(BytesIO(data)) as image:
            if image.format not in IMAGE_FORMATS:
                raise MediaValidationError("Only PNG, JPEG, and WebP images are supported")
            width, height = image.size
            if width < 16 or height < 16 or width > 16384 or height > 16384:
                raise MediaValidationError("Image dimensions must be between 16 and 16384 pixels")
            mime, suffix = IMAGE_FORMATS[image.format]
            return mime, suffix, width, height
    except (UnidentifiedImageError, OSError) as exc:
        raise MediaValidationError("The uploaded file is not a valid supported image") from exc


def validate_audio(data: bytes, original_name: str) -> tuple[str, str]:
    if not data or len(data) > 200 * 1024 * 1024:
        raise MediaValidationError("Audio files must be between 1 byte and 200 MB")
    suffix = Path(original_name).suffix.casefold()
    valid = (
        suffix == ".mp3" and (data.startswith(b"ID3") or data[:2] in {b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"})
        or suffix == ".ogg" and data.startswith(b"OggS")
        or suffix == ".wav" and data.startswith(b"RIFF") and data[8:12] == b"WAVE"
        or suffix == ".m4a" and len(data) > 12 and data[4:8] == b"ftyp"
    )
    if not valid or suffix not in AUDIO_TYPES:
        raise MediaValidationError("Only valid MP3, OGG, WAV, and M4A files are supported")
    return AUDIO_TYPES[suffix], suffix


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def store_media(data_dir: Path, relative_dir: str, file_id: str, suffix: str, data: bytes) -> str:
    directory = (data_dir / relative_dir).resolve()
    if data_dir.resolve() not in directory.parents:
        raise MediaValidationError("Invalid managed media destination")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{file_id}{suffix}"
    path.write_bytes(data)
    return str(path.relative_to(data_dir)).replace("\\", "/")
