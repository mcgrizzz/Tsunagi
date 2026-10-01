"""
Media router - hand-written because media is a flat, name-keyed, binary
namespace: no integer id, nothing for the query planner to plan.
"""
import base64
import binascii
import contextvars
import mimetypes
import os
import threading
import time
import urllib.request
from typing import List, Optional, Union

from fastapi import Body, Header, Path
from fastapi.responses import FileResponse, JSONResponse

from ...adapters import idempotency
from ...adapters.anki.media import (
    delete_media_file,
    list_media,
    resolve_media_path,
)
from ...adapters.anki.media_batches import create_media
from ...adapters.ops import FOREVER
from ...adapters.settings import settings
from ...shared.errors import (
    ResourceNotFoundError,
    ValidationError,
    handle_mutation_errors,
)
from ...shared.permissions import current_denial, permitted, requires
from ...shared.planning import SourceCaps
from ...shared.route_factory import ModelRow, create_resource_routes
from ...shared.schemas.creation import IDEMPOTENCY_HELP
from ...shared.schemas.media import (
    MediaCreateResponse,
    MediaDeletionResult,
    MediaUpload,
)
from ...shared.schemas.wrappers import Paginated
from ...shared.version import ADDON_VERSION

# Query: GET /v1/media, POST /v1/media/query, with the parameters every list
# takes (backlog 6.71); rows keyed by filename. Uploads and files are below.
router = create_resource_routes(
    path="/v1/media",
    caps=SourceCaps(fetch_all=lambda wants=None: [{"filename": n, "size": s, "mtime": m}
                                                  for n, s, m in list_media()], key_type=str),
    response_model=Paginated[ModelRow],
    id_getter=lambda row: row["filename"],
    resource_name="media file",
    resource_plural="media",
    permission_resource="media",
    tag="Media",
    description="Every file in the media folder: filename, size and mtime (where=filename$=\".mp3\").",
)

_UA = f"Mozilla/5.0 (compatible; Tsunagi/{ADDON_VERSION}; +https://github.com/mcgrizzz/Tsunagi)"


def _stats(start: float) -> dict:
    return {"duration_ms": round((time.perf_counter() - start) * 1000, 3)}


def _max_bytes() -> int:
    return int(settings.get("media_max_bytes", 67108864))


class _HttpOnlyRedirects(urllib.request.HTTPRedirectHandler):
    # urllib also follows redirects to ftp://; keep the http(s) rule below.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.lower().startswith(("http://", "https://")):
            raise ValidationError("url redirected to a non-http(s) address")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_HttpOnlyRedirects)


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
        with _OPENER.open(req, timeout=timeout) as resp:  # scheme checked above and on redirect
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


def resolve_upload(body: MediaUpload) -> tuple:
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
        if not permitted("local_files"):
            raise ValidationError("local 'path' uploads are disabled; "
                                  + current_denial("local_files"))
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
    "/v1/media/{filename:path}",
    openapi_extra=requires("read:media"),
    response_class=FileResponse,
    summary="Download a media file",
    description="Streams the raw bytes with a guessed Content-Type. Note: when a request needs a key this URL cannot be used directly in <img src> - browsers can't attach the header; fetch() it and use createObjectURL.",
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
    openapi_extra=requires("write:media"),
    response_model=MediaCreateResponse,
    summary="Store one or more media files",
    description=("Accepts one upload object or an array. Each input provides exactly one of base64 'data', "
                 "a server-local 'path' (disabled by default), or a 'url'. Always returns created and "
                 "failed arrays with zero-based input indexes. Successful files stay stored when another "
                 "is rejected. Anki renames on collision; use the returned filename. "
                 "The configured upload-size limit applies per file. Media storage is not undoable."),
    tags=["Media"],
    operation_id="storeMedia",
)
@handle_mutation_errors("store_media")
def store_media(
    body: Union[List[MediaUpload], MediaUpload] = Body(..., description="One upload or an array of uploads"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key", description=IDEMPOTENCY_HELP),
) -> Union[MediaCreateResponse, JSONResponse]:
    candidates = body if isinstance(body, list) else [body]
    if not idempotency_key:
        return create_media(candidates, resolve_upload)

    def start(done, fail):
        # The whole upload runs on its own thread, with no deadline per chunk,
        # so it is recorded when it ends even after this request's 503. It
        # keeps the request's context: permissions such as local_files.
        context = contextvars.copy_context()

        def work():
            try:
                done(create_media(candidates, resolve_upload, timeout=FOREVER).dict())
            except BaseException as exc:
                fail(exc)
        threading.Thread(target=context.run, args=(work,), daemon=True).start()
    response, replayed = idempotency.run(
        idempotency.scope("POST /v1/media", idempotency_key),
        idempotency.fingerprint([c.dict() for c in candidates]), start)
    return JSONResponse(response, headers={"Idempotent-Replayed": "true"} if replayed else None)



@router.delete(
    "/v1/media/{filename:path}",
    openapi_extra=requires("write:media"),
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
