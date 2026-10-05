from __future__ import annotations

import ntpath
import os
import unicodedata
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from ..errors import ValidationError
from .creation import CreationFailure, CreationResult
from .wrappers import NULLABLE, RequestBody

# Windows reserved device names (a file named CON.png is unopenable there)
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {
    f"LPT{i}" for i in range(1, 10)
}


def sanitize_media_filename(name: object) -> str:
    """
    Return the NFC-normalized bare filename, or raise ValidationError (400).

    This is user-controlled input that becomes a filesystem path, so the
    rules are deliberately strict and rejecting rather than rewriting: a
    silently "cleaned" name would not match what the caller stored.
    """
    if not isinstance(name, str) or not name.strip():
        raise ValidationError("filename is required")
    if name != name.strip():
        # Windows silently strips trailing dots/spaces, so the stored name
        # would differ from the requested one.
        raise ValidationError("filename must not have leading/trailing whitespace")
    if any(ord(c) < 32 or ord(c) == 127 for c in name):
        # NUL truncation, newline header injection
        raise ValidationError("filename must not contain control characters")
    if "/" in name or "\\" in name:
        raise ValidationError("filename must not contain path separators")
    if ":" in name:
        # Windows drive letters and NTFS alternate data streams (x.png:evil)
        raise ValidationError("filename must not contain ':'")
    if ".." in name:
        raise ValidationError("filename must not contain '..'")
    if os.path.isabs(name) or ntpath.splitdrive(name)[0]:
        raise ValidationError("filename must be relative")
    if os.path.splitext(name)[0].upper() in _RESERVED:
        raise ValidationError(f"'{name}' is a reserved device name")
    if len(name.encode("utf-8")) > 255:
        raise ValidationError("filename is too long (max 255 bytes)")
    # Normalize rather than reject: macOS hands out NFD, Anki stores NFC.
    return unicodedata.normalize("NFC", name)


# ----------------- Schemas -----------------


class MediaRow(BaseModel):
    """A row of GET /v1/media: one file in the media folder."""
    filename: str = Field(description="File name in the media folder.")
    size: int = Field(..., description="File size in bytes.")
    modified: int = Field(..., description="Last modified, Unix seconds.")


class MediaUpload(RequestBody):
    filename: Optional[str] = None
    data: Optional[str] = None   # base64
    path: Optional[str] = None   # server-local file (local_files permission)
    url: Optional[str] = None


class MediaStored(BaseModel):
    filename: str                        # the name Anki actually stored
    requested_filename: Optional[str] = Field(None, description="The filename sent; null when none was.", **NULLABLE)
    renamed: bool = False
    size: int


class MediaDeletionResult(BaseModel):
    success: bool
    filename: str
    stats: dict


class MediaCreated(MediaStored):
    index: int


class MediaCreateFailure(CreationFailure):
    code: Literal["invalid_media", "storage_error", "source_error"] = Field(description=(
        "invalid_media: the file can't be stored as sent, such as a bad filename or base64 (see "
        "message). storage_error: Anki couldn't write it. source_error: its url or path couldn't be read."))


class MediaCreateResponse(CreationResult[MediaCreated]):
    failed: List[MediaCreateFailure] = Field(default_factory=list)
