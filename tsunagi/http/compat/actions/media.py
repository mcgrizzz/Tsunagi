"""
AnkiConnect compatibility handlers for media actions.

Thin translations over the same adapters the native /v1/media routes use;
the only compat-specific work is base64 and AnkiConnect's return quirks
(null for a skipHash match, false for a missing file).
"""
import base64
import hashlib
import os
import unicodedata
from typing import Any, List, Optional

from pydantic import BaseModel

from ....adapters.anki.media import (
    delete_media_file,
    list_media,
    media_dir_path,
    resolve_media_path,
    store_media_bytes,
)
from ....adapters.settings import settings
from ..errors import MEDIA_NO_SOURCE
from ..registry import registry

# Anki's legacy media.stripIllegal character class, which AnkiConnect applies
# to retrieveMediaFile filenames.
_ILLEGAL = set('[]><:"/?*^\\|\0\r\n')


class StoreMediaFileParams(BaseModel):
    filename: str
    data: Optional[str] = None
    path: Optional[str] = None
    url: Optional[str] = None
    skipHash: Optional[str] = None
    # Upstream uses Python truthiness, including nonempty strings and containers.
    deleteExisting: Any = True


class FilenameParams(BaseModel):
    filename: str


class PatternParams(BaseModel):
    pattern: str = "*"


@registry.register("storeMediaFile", params=StoreMediaFileParams)
def ac_storeMediaFile(p: StoreMediaFileParams) -> Optional[str]:
    if not (p.data or p.path or p.url):
        raise ValueError(MEDIA_NO_SOURCE)

    if p.data:
        data = base64.b64decode(p.data)
    elif p.path:
        if not settings.gate_enabled("media_allow_local_path"):
            raise ValueError(
                "local 'path' uploads are disabled; enable gates.media_allow_local_path in the Tsunagi config"
            )
        with open(p.path, "rb") as fh:
            data = fh.read()
    else:
        from ..downloads import download_media
        data = download_media(p.url)

    # skipHash: the caller already has this content, so store nothing.
    if p.skipHash is not None and hashlib.md5(data).hexdigest() == p.skipHash:
        return None

    if p.deleteExisting:
        delete_media_file(p.filename)
    stored, _renamed = store_media_bytes(p.filename, data)
    return stored


@registry.register("retrieveMediaFile", params=FilenameParams)
def ac_retrieveMediaFile(p: FilenameParams) -> Any:
    # AnkiConnect normalizes rather than rejecting, and answers `false`
    # (not null) when the file is absent.
    name = os.path.basename(p.filename)
    name = unicodedata.normalize("NFC", name)
    name = "".join(c for c in name if c not in _ILLEGAL)
    if not name:
        return False
    path = resolve_media_path(name)
    if path is None:
        return False
    with open(path, "rb") as fh:
        return base64.b64encode(fh.read()).decode("ascii")


@registry.register("getMediaFilesNames", params=PatternParams)
def ac_getMediaFilesNames(p: PatternParams) -> List[str]:
    import fnmatch
    return sorted(name for name, _size, _mtime in list_media()
                  if fnmatch.fnmatch(name, p.pattern))


@registry.register("deleteMediaFile", params=FilenameParams)
def ac_deleteMediaFile(p: FilenameParams) -> None:
    delete_media_file(p.filename)
    return None


@registry.register("getMediaDirPath")
def ac_getMediaDirPath(params: Any) -> str:
    return media_dir_path()
