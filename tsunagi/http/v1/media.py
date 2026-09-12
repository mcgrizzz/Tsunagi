"""
Media router - hand-written because media is a flat, name-keyed, binary
namespace: no integer id, nothing for the query planner to plan.
"""
import base64
import binascii
import mimetypes
import os
import time
import urllib.request
from typing import Optional

from fastapi import APIRouter, Body, Path, Query
from fastapi.responses import FileResponse

from ...adapters.anki.media import (
    delete_media_file,
    list_media,
    resolve_media_path,
    store_media_bytes,
)
from ...adapters.settings import settings
from ...shared.errors import (
    ResourceNotFoundError,
    ValidationError,
    handle_mutation_errors,
)
from ...shared.pagination import decode_cursor, encode_cursor
from ...shared.schemas.media import (
    MediaDeletionResult,
    MediaFile,
    MediaList,
    MediaStored,
    MediaUpload,
)
from ...shared.version import ADDON_VERSION

router = APIRouter()

_UA = f"Mozilla/5.0 (compatible; Tsunagi/{ADDON_VERSION}; +https://github.com/mcgrizzz/Tsunagi)"


def _stats(start: float) -> dict:
    return {"duration_ms": round((time.perf_counter() - start) * 1000, 3)}


def _max_bytes() -> int:
    return int(settings.get("media_max_bytes", 67108864))


def _fetch_url(url: str) -> bytes:
    """
    Download media. Runs on the request thread, deliberately OUTSIDE any Anki
    op: a slow download inside a query op would trip the operation timeout
    and return a spurious 503 while the worker kept downloading.
    """
    if not url.lower().startswith(("http://", "https://")):
        # urllib would happily open file:///etc/passwd
        raise ValidationError("url must be http or https")

    limit = _max_bytes()
    timeout = float(settings.get("media_fetch_timeout_seconds", 30))
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (scheme checked above)
            declared = resp.headers.get("Content-Length")
            if declared and int(declared) > limit:
                raise ValidationError(f"file exceeds media_max_bytes ({limit})")
            chunks, total = [], 0
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                # Content-Length may be absent or lying
                if total > limit:
                    raise ValidationError(f"file exceeds media_max_bytes ({limit})")
                chunks.append(chunk)
    except ValidationError:
        raise
    except Exception as e:
        raise ValidationError(f"download failed: {e}") from e
    return b"".join(chunks)


def _resolve_upload(body: MediaUpload) -> tuple:
    """(filename, data) from exactly one of data/path/url."""
    sources = [s for s in (body.data, body.path, body.url) if s is not None]
    if len(sources) != 1:
        raise ValidationError("provide exactly one of 'data', 'path' or 'url'")

    limit = _max_bytes()
    if body.data is not None:
        if not body.filename:
            raise ValidationError("'filename' is required with 'data'")
        try:
            data = base64.b64decode(body.data, validate=True)
        except (binascii.Error, ValueError) as e:
            raise ValidationError("'data' is not valid base64") from e
        name = body.filename
    elif body.path is not None:
        if not settings.gate_enabled("media_allow_local_path"):
            raise ValidationError(
                "local 'path' uploads are disabled; enable gates.media_allow_local_path in the config"
            )
        if not os.path.isfile(body.path):
            raise ValidationError(f"no such file: {body.path}")
        if os.path.getsize(body.path) > limit:
            raise ValidationError(f"file exceeds media_max_bytes ({limit})")
        with open(body.path, "rb") as fh:
            data = fh.read()
        name = body.filename or os.path.basename(body.path)
    else:
        data = _fetch_url(body.url)
        name = body.filename or os.path.basename(body.url.split("?", 1)[0])

    if len(data) > limit:
        raise ValidationError(f"file exceeds media_max_bytes ({limit})")
    return name, data


@router.get(
    "/v1/media",
    response_model=MediaList,
    summary="List media files",
    description="Media is a flat file namespace, not a queryable resource - filter with prefix/suffix rather than the select/where DSL.",
    tags=["Media"],
    operation_id="listMedia",
)
@handle_mutation_errors("list_media")
def list_media_files(
    prefix: Optional[str] = Query(default=None, description="Only names starting with this"),
    suffix: Optional[str] = Query(default=None, description="Only names ending with this (e.g. '.mp3')"),
    limit: int = Query(default=1000, ge=1, description="Maximum results in this response; no fixed upper cap"),
    cursor: Optional[str] = Query(default=None, description="Opaque next_cursor from the previous response. Omit to start at page one; malformed or empty cursors return 400."),
) -> MediaList:
    start = time.perf_counter()
    last = decode_cursor(cursor, key_type=str).get("last_key")
    files = sorted(list_media(), key=lambda f: f[0])
    if prefix:
        files = [f for f in files if f[0].startswith(prefix)]
    if suffix:
        files = [f for f in files if f[0].endswith(suffix)]

    # Keyset on the filename (a string key, so paginate_keyset - which is
    # int-only - doesn't apply).
    if last is not None:
        files = [f for f in files if f[0] > last]
    page, more = files[:limit], len(files) > limit
    next_cursor = encode_cursor({"last_key": page[-1][0]}) if more and page else None

    return MediaList(
        items=[MediaFile(filename=n, size=s, mtime=m) for n, s, m in page],
        next_cursor=next_cursor,
        stats=_stats(start),
    )


@router.get(
    "/v1/media/{filename:path}",
    response_class=FileResponse,
    summary="Download a media file",
    description="Streams the raw bytes with a guessed Content-Type. Note: when an API key is configured this URL cannot be used directly in <img src> - browsers can't attach the header; fetch() it and use createObjectURL.",
    tags=["Media"],
    operation_id="getMediaFile",
)
@handle_mutation_errors("get_media")
def get_media_file(filename: str = Path(..., description="Media filename")) -> FileResponse:
    path = resolve_media_path(filename)
    if path is None:
        raise ResourceNotFoundError("Media file", filename)
    media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, filename=filename,
                        content_disposition_type="inline")


@router.post(
    "/v1/media",
    response_model=MediaStored,
    status_code=201,
    summary="Store a media file",
    description="Provide exactly one of base64 'data', a server-local 'path' (disabled by default), or a 'url'. Anki renames on collision, so the response reports the name actually stored.",
    tags=["Media"],
    operation_id="storeMedia",
)
@handle_mutation_errors("store_media")
def store_media(body: MediaUpload = Body(..., description="File source")) -> MediaStored:
    requested, data = _resolve_upload(body)
    stored, renamed = store_media_bytes(requested, data)
    return MediaStored(
        filename=stored,
        requested_filename=requested,
        renamed=renamed,
        size=len(data),
    )


@router.delete(
    "/v1/media/{filename:path}",
    response_model=MediaDeletionResult,
    summary="Delete a media file",
    description="Moves the file to Anki's media trash.",
    tags=["Media"],
    operation_id="deleteMediaFile",
)
@handle_mutation_errors("delete_media")
def delete_media(filename: str = Path(..., description="Media filename")) -> MediaDeletionResult:
    start = time.perf_counter()
    if not delete_media_file(filename):
        raise ResourceNotFoundError("Media file", filename)
    return MediaDeletionResult(success=True, filename=filename, stats=_stats(start))
