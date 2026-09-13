"""Resolve sources on the request thread; store bounded chunks in one collection."""
import logging
from typing import Callable, List, Tuple

from anki.collection import Collection
from aqt import mw

from ...shared.errors import CollectionUnavailableError, ValidationError
from ...shared.schemas.creation import CreationFailure
from ...shared.schemas.media import MediaCreated, MediaCreateResponse, MediaUpload
from ..ops import query_op_call
from .media import store_media_bytes

# These bound pending decoded bytes and collection dispatch work, not request size.
UPLOAD_CHUNK_BYTES = 8 * 1024 * 1024
UPLOAD_CHUNK_FILES = 64


def _store_chunk(col: Collection, expected: Collection, items: List[Tuple[int, str, bytes]]) -> MediaCreateResponse:
    if col is not expected:
        raise CollectionUnavailableError()
    result = MediaCreateResponse()
    for index, requested, data in items:
        try:
            stored, renamed = store_media_bytes.__wrapped__(col, requested, data)
        except ValidationError as exc:
            result.failed.append(CreationFailure(index=index, code="invalid_media", message=str(exc)))
        except OSError:
            logging.getLogger(__name__).exception("Could not store media input %s", index)
            result.failed.append(CreationFailure(index=index, code="storage_error",
                                                 message="Could not store media file"))
        else:
            result.created.append(MediaCreated(index=index, filename=stored,
                                                requested_filename=requested,
                                                renamed=renamed, size=len(data)))
    return result


def create_media(candidates: List[MediaUpload], resolve: Callable[[MediaUpload], tuple]) -> MediaCreateResponse:
    # Keep identity across downloads and every storage chunk. A profile switch
    # must never redirect the remaining uploads to a different collection.
    collection = mw.col
    if collection is None:
        raise CollectionUnavailableError()
    result = MediaCreateResponse()
    pending = []
    pending_bytes = 0

    def flush():
        nonlocal pending_bytes
        if not pending:
            return
        stored = query_op_call(_store_chunk, collection, pending)
        result.created.extend(stored.created)
        result.failed.extend(stored.failed)
        pending.clear()
        pending_bytes = 0

    for index, body in enumerate(candidates):
        if mw.col is not collection:
            raise CollectionUnavailableError()
        external = body.path is not None or body.url is not None
        if external:
            # Preserve source ordering: a later local path/URL may read a file
            # stored by an earlier input. Never download on the collection thread.
            flush()
        try:
            requested, data = resolve(body)
        except ValidationError as exc:
            result.failed.append(CreationFailure(index=index, code="invalid_media", message=str(exc)))
            continue
        except OSError:
            logging.getLogger(__name__).exception("Could not read media input %s", index)
            result.failed.append(CreationFailure(index=index, code="source_error",
                                                 message="Could not read media source"))
            continue
        if pending_bytes + len(data) > UPLOAD_CHUNK_BYTES:
            flush()
        pending.append((index, requested, data))
        pending_bytes += len(data)
        if external or pending_bytes >= UPLOAD_CHUNK_BYTES or len(pending) >= UPLOAD_CHUNK_FILES:
            flush()
    flush()
    result.failed.sort(key=lambda failure: failure.index)
    return result
