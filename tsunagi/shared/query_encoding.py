"""Encode an already validated, standard query page without rewalking its schema."""
from typing import Any

from fastapi.encoders import jsonable_encoder


class _NeedsFrameworkEncoder(Exception):
    pass


def _json_values(value: Any) -> Any:
    kind = type(value)
    if value is None or kind in (str, int, float, bool):
        return value
    if kind is list:
        return [_json_values(item) for item in value]
    if kind is dict:
        result = {}
        for key, item in value.items():
            if type(key) is not str:
                raise _NeedsFrameworkEncoder
            # Match jsonable_encoder's default SQLAlchemy attribute exclusion.
            if not key.startswith("_sa"):
                result[key] = _json_values(item)
        return result
    raise _NeedsFrameworkEncoder


def encode_query_page(page: Any) -> dict:
    # Called only for the standard Paginated[ModelRow] envelope. Its rows were
    # validated and projected by the query engine; field names are already final.
    # Most pages contain only JSON values. Avoid another recursive page.dict()
    # followed by FastAPI's general-purpose conversion of every scalar.
    if not page.__config__.json_encoders:
        try:
            return _json_values(page.__dict__)
        except _NeedsFrameworkEncoder:
            pass
    # Fall back for the entire page, not just the special value. Pydantic's
    # recursive dict conversion affects nested model aliases and encoders, so
    # encoding those models individually could change the response.
    return jsonable_encoder(page, by_alias=True)
