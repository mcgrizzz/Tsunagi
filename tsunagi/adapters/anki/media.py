"""
Media folder access.

All of these use @as_query_op, never @as_collection_op: media changes are not
part of Anki's undo stack (add_file/write_data return a filename, not
OpChanges), so a CollectionOp would push a no-op undo entry and fire a
spurious UI refresh on every upload. Anki's own editor calls these the same
way. QueryOp still gives us the worker thread, the mw.col guard and the
operation timeout.
"""
import os
from typing import List, Optional, Tuple

from anki.collection import Collection

from ...shared.errors import ValidationError
from ...shared.schemas.media import sanitize_media_filename
from ..ops import as_query_op


def _contained_path(col: Collection, filename: str) -> str:
    """
    Resolve a validated filename inside the media dir, refusing anything that
    escapes it. The name rules can't catch a symlink *inside* the media
    folder pointing outside it, so this check is not redundant.
    """
    root = os.path.realpath(col.media.dir())
    full = os.path.realpath(os.path.join(root, filename))
    if os.path.commonpath([full, root]) != root:
        raise ValidationError("filename escapes the media folder")
    return full


@as_query_op
def media_dir_path(col: Collection) -> str:
    """Absolute path of the collection's media folder."""
    return col.media.dir()


@as_query_op
def list_media(col: Collection) -> List[Tuple[str, int, int]]:
    """(filename, size, mtime) for every file in the media folder."""
    root = col.media.dir()
    out: List[Tuple[str, int, int]] = []
    with os.scandir(root) as entries:
        for entry in entries:
            if not entry.is_file():
                continue
            stat = entry.stat()
            out.append((entry.name, int(stat.st_size), int(stat.st_mtime)))
    return out


@as_query_op
def resolve_media_path(col: Collection, filename: str) -> Optional[str]:
    """Absolute path of an existing media file, or None."""
    name = sanitize_media_filename(filename)
    path = _contained_path(col, name)
    return path if os.path.isfile(path) else None


@as_query_op
def store_media_bytes(col: Collection, filename: str, data: bytes) -> Tuple[str, bool]:
    """
    Write bytes to the media folder. Returns (actual_filename, renamed) -
    Anki renames on a name collision with different content, and the caller
    needs the real name to reference the file.
    """
    name = sanitize_media_filename(filename)
    _contained_path(col, name)
    stored = col.media.write_data(name, data)
    return stored, stored != name


@as_query_op
def delete_media_file(col: Collection, filename: str) -> bool:
    name = sanitize_media_filename(filename)
    path = _contained_path(col, name)
    if not os.path.isfile(path):
        return False
    col.media.trash_files([name])
    return True
