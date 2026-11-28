"""Render an already validated, standard query page without rewalking its schema."""
import json
from typing import Any

import orjson
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

_PASSTHROUGH = (orjson.OPT_PASSTHROUGH_SUBCLASS | orjson.OPT_PASSTHROUGH_DATACLASS
                | orjson.OPT_PASSTHROUGH_DATETIME)


class _NeedsFrameworkEncoder(Exception):
    pass


def _unsupported(value: Any) -> Any:
    raise _NeedsFrameworkEncoder


def render_query_page(page: Any, floatless: bool = False) -> bytes:
    # Called only for the standard Paginated[ModelRow] envelope. Its rows were
    # validated and projected by the query engine; field names are already final.
    # Most pages contain only JSON values, which the C encoder renders exactly as
    # JSONResponse would after FastAPI's conversion; it calls _unsupported for
    # anything else, and rejects keys it cannot convert.
    # `total` is only sent when it was asked for (include=total).
    body = page.__dict__ if page.__dict__.get("total") is not None else {
        k: v for k, v in page.__dict__.items() if k != "total"}
    if floatless and not page.__config__.json_encoders:
        # orjson (Anki's own dependency) first: on a large page it is five
        # times faster than json, with the same bytes (backlog 6.157). What it
        # would render differently goes on to the encoders below: str, int,
        # dict and list subclasses, dataclasses and datetimes by passthrough,
        # non-string keys, ints beyond 64 bits and sets by refusing them. It
        # would write NaN and infinity as null where json refuses them, so it
        # is used only for rows that hold no floats (`floatless`).
        try:
            data = orjson.dumps(body, default=_unsupported, option=_PASSTHROUGH)
        except (_NeedsFrameworkEncoder, TypeError):
            pass
        else:
            if b'"_sa' not in data:
                return data
    if not page.__config__.json_encoders:
        try:
            text = json.dumps(body, ensure_ascii=False, allow_nan=False,
                              separators=(",", ":"), default=_unsupported)
        except (_NeedsFrameworkEncoder, TypeError):
            pass
        else:
            # jsonable_encoder drops dict keys starting with "_sa" (SQLAlchemy
            # state). Such text is rare; let the framework decide those pages.
            if '"_sa' not in text:
                return text.encode("utf-8")
    # Fall back for the entire page, not just the special value. Pydantic's
    # recursive dict conversion affects nested model aliases and encoders, so
    # encoding those models individually could change the response.
    return JSONResponse(jsonable_encoder(page, by_alias=True,
                                        exclude=None if "total" in body else {"total"})).body
