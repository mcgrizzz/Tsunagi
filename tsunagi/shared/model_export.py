"""Export validated query rows, retaining Pydantic for richer export behavior."""
from typing import Any

from pydantic import BaseModel

_DEFAULT = object()
_MODEL_DICT = BaseModel.dict
_MODEL_ITER = BaseModel._iter
_MODEL_GET_VALUE = BaseModel._get_value.__func__
_MODEL_CALCULATE_KEYS = BaseModel._calculate_keys


class _NeedsPydantic(Exception):
    pass


def _model_values(row: BaseModel, include: Any = None) -> dict:
    # Custom exporters and schema-level field masks must keep Pydantic's rules.
    if (getattr(row.dict, "__func__", None) is not _MODEL_DICT
            or getattr(row._iter, "__func__", None) is not _MODEL_ITER
            or getattr(row._get_value, "__func__", None) is not _MODEL_GET_VALUE
            or getattr(row._calculate_keys, "__func__", None) is not _MODEL_CALCULATE_KEYS
            or row.__custom_root_type__ or "__root__" in row.__dict__
            or row.__include_fields__ or row.__exclude_fields__):
        raise _NeedsPydantic
    # With no schema masks, a flat include only selects top-level keys. Avoid
    # asking Pydantic to recursively process an include mask for every value.
    return {key: _plain_values(value) for key, value in row._iter(to_dict=False)
            if include is None or key in include}


def _plain_values(value: Any) -> Any:
    kind = type(value)
    if value is None or kind in (str, int, float, bool):
        return value
    if kind is list:
        return [_plain_values(item) for item in value]
    if kind is dict:
        if any(type(key) is not str for key in value):
            raise _NeedsPydantic
        # Keep all keys here, including _sa: filters/projections run before the
        # HTTP encoder applies its exclusions.
        return {key: _plain_values(item) for key, item in value.items()}
    if isinstance(value, BaseModel):
        return _model_values(value)
    raise _NeedsPydantic


def model_row_dict(row: BaseModel, include: Any = _DEFAULT) -> dict:
    """Match row.dict() for ordinary JSON rows and flat field selections.

    Validation has already run. Every call reads this row again and creates
    fresh containers; no row values or model metadata are cached.
    """
    mask = None if include is _DEFAULT else include
    try:
        if mask is not None and type(mask) is not set:
            if type(mask) is not dict or any(value is not True for value in mask.values()):
                raise _NeedsPydantic
        return _model_values(row, mask)
    except _NeedsPydantic:
        # Fall back for the whole row so nested aliases, roots, custom methods,
        # non-JSON values and include/exclude rules retain their interactions.
        return row.dict() if include is _DEFAULT else row.dict(include=include)
