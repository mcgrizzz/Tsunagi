"""Render an already validated, standard query page without rewalking its schema."""
import json
from typing import Any

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse


class _NeedsFrameworkEncoder(Exception):
    pass


def _unsupported(value: Any) -> Any:
    raise _NeedsFrameworkEncoder


def render_query_page(page: Any) -> bytes:
    # Called only for the standard Paginated[ModelRow] envelope. Its rows were
    # validated and projected by the query engine; field names are already final.
    # Most pages contain only JSON values, which the C encoder renders exactly as
    # JSONResponse would after FastAPI's conversion; it calls _unsupported for
    # anything else, and rejects keys it cannot convert.
    if not page.__config__.json_encoders:
        try:
            text = json.dumps(page.__dict__, ensure_ascii=False, allow_nan=False,
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
    return JSONResponse(jsonable_encoder(page, by_alias=True)).body
