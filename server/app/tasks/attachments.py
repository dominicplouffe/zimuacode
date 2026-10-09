"""Images pasted into a task's chat, kept in <task>/attachments/ next to the workspace
(not inside it, so an agent can't commit them by accident)."""

import base64
import binascii
import re
import uuid
from pathlib import Path

MAX_IMAGES = 5
# The Claude API rejects images over 5 MB.
MAX_IMAGE_BYTES = 5 * 1024 * 1024

NAME = re.compile(r"^[0-9a-f]{32}\.(png|jpg|gif|webp)$")
MEDIA_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
}


class AttachmentError(ValueError):
    pass


def sniff(data: bytes) -> str | None:
    """The file extension for an image's bytes, judged by its signature."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def decode(images: list[str]) -> list[tuple[bytes, str]]:
    """Validates base64 images, returning (bytes, extension) for each."""
    if len(images) > MAX_IMAGES:
        raise AttachmentError(f"At most {MAX_IMAGES} images per message")
    decoded = []
    for item in images:
        try:
            data = base64.b64decode(item, validate=True)
        except binascii.Error as e:
            raise AttachmentError("An image isn't valid base64") from e
        if len(data) > MAX_IMAGE_BYTES:
            raise AttachmentError(f"Images can be at most {MAX_IMAGE_BYTES // 1024 // 1024} MB")
        ext = sniff(data)
        if ext is None:
            raise AttachmentError("Only PNG, JPEG, GIF and WebP images are supported")
        decoded.append((data, ext))
    return decoded


def save(directory: Path, decoded: list[tuple[bytes, str]]) -> list[str]:
    """Writes validated images to `directory` and returns their file names."""
    directory.mkdir(parents=True, exist_ok=True)
    names = []
    for data, ext in decoded:
        name = f"{uuid.uuid4().hex}.{ext}"
        (directory / name).write_bytes(data)
        names.append(name)
    return names
