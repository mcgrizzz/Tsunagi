"""
Helper functions for data validation and mapping.
"""
from typing import Any, Dict, List, Sequence, Type, TypeVar

from pydantic import BaseModel

from .errors import ValidationError as TsunagiValidationError

T = TypeVar('T', bound=BaseModel)


def normalize_field_names(data: Dict[str, Any], schema: Type[T]) -> Dict[str, Any]:
    """
    Normalize field names in a dictionary using a Pydantic schema's aliases.

    Accepts both clean field names (fields, templates, sort_field) and
    Anki's abbreviated names (flds, tmpls, sortf), then returns a dictionary
    with Anki's field names for use with Anki's API.

    Args:
        data: Input dictionary with either clean or abbreviated field names
        schema: Pydantic schema class with field aliases

    Returns:
        Dictionary with Anki's abbreviated field names

    Example:
        >>> from tsunagi.shared.schemas.models import ModelPatch
        >>> normalize_field_names({"sort_field": 1, "name": "Basic"}, ModelPatch)
        {"sortf": 1, "name": "Basic"}

        >>> normalize_field_names({"sortf": 1, "name": "Basic"}, ModelPatch)
        {"sortf": 1, "name": "Basic"}
    """
    # Validate and parse using the schema (accepts both names due to allow_population_by_field_name=True)
    validated = schema.parse_obj(data)

    # Serialize using aliases (Anki's abbreviated names)
    # by_alias=True means use the alias (flds, tmpls, sortf)
    # exclude_none=True means don't include fields that are None
    return validated.dict(by_alias=True, exclude_none=True)


def validate_required_keys(data: Dict[str, Any], keys: Sequence[str]) -> None:
    """
    Validate that required keys are present and not None in data dictionary.

    Args:
        data: The input data dictionary
        keys: List of required key names

    Raises:
        TsunagiValidationError: If any required key is missing or None

    Example:
        validate_required_keys(data, ["name", "flds", "tmpls"])
    """
    for key in keys:
        if key not in data or data[key] is None:
            raise TsunagiValidationError(f"'{key}' is required")


def copy_if_present(
    source: Dict[str, Any],
    target: Dict[str, Any],
    keys: Sequence[str]
) -> None:
    """
    Copy keys from source dict to target dict only if they exist in source.

    Args:
        source: Source dictionary to copy from
        target: Target dictionary to copy to
        keys: List of key names to copy if present

    Example:
        copy_if_present(input_data, model_dict, ["css", "type", "did"])
    """
    for key in keys:
        if key in source:
            target[key] = source[key]


def validate_nonempty_list(data: Dict[str, Any], key: str, item_name: str = "item") -> List[Any]:
    """
    Validate that a key contains a non-empty list.

    Args:
        data: The input data dictionary
        key: The key name to validate
        item_name: Human-readable name for items (for error messages)

    Returns:
        The list value

    Raises:
        TsunagiValidationError: If key is missing, not a list, or empty

    Example:
        flds = validate_nonempty_list(data, "flds", "field")
    """
    value = data.get(key, [])
    if not value or not isinstance(value, list) or len(value) == 0:
        raise TsunagiValidationError(f"At least one {item_name} is required in '{key}'")
    return value


def find_in_subresource(
    parent: Dict[str, Any],
    json_key: str,
    identifier_value: Any,
    identifier_field: str = "name",
) -> Dict[str, Any]:
    """
    Find item in parent's subresource array by identifier.

    Args:
        parent: Parent resource dict (e.g., model dict)
        json_key: Array key in parent (e.g., "flds", "tmpls")
        identifier_value: Value to match (e.g., "Front", 0)
        identifier_field: Field to match against (e.g., "name", "ord")

    Returns:
        The matching item dict

    Raises:
        TsunagiValidationError: If item not found

    Example:
        field = find_in_subresource(model, "flds", "Front", "name")
    """
    items = parent.get(json_key, [])

    for item in items:
        if item.get(identifier_field) == identifier_value:
            return item

    available = [item.get(identifier_field) for item in items]
    raise TsunagiValidationError(
        f"Item with {identifier_field}='{identifier_value}' not found in {json_key}. "
        f"Available: {', '.join(str(v) for v in available)}"
    )


def validate_subresource_order(
    parent: Dict[str, Any],
    json_key: str,
    order: List[Any],
    identifier_field: str = "name",
) -> None:
    """
    Validate that order array matches existing items in subresource.

    Checks that:
    - All existing items are in order array
    - No extra items in order array
    - No duplicates in order array

    Args:
        parent: Parent resource dict
        json_key: Array key in parent (e.g., "flds", "tmpls")
        order: Proposed new order (list of identifiers)
        identifier_field: Field to use as identifier

    Raises:
        TsunagiValidationError: If validation fails

    Example:
        validate_subresource_order(model, "flds", ["Front", "Back"], "name")
    """
    items = parent.get(json_key, [])
    existing = {item[identifier_field] for item in items}
    order_set = set(order)

    if len(order_set) != len(order):
        raise TsunagiValidationError("Duplicate items in order array")

    missing = existing - order_set
    extra = order_set - existing

    if missing or extra:
        errors = []
        if missing:
            errors.append(f"Missing from order: {missing}")
        if extra:
            errors.append(f"Not in {json_key}: {extra}")
        raise TsunagiValidationError(". ".join(errors))
