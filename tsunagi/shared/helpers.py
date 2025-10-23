"""
Helper functions for data validation and mapping.
"""
from typing import Any, Dict, List, Sequence


def validate_required_keys(data: Dict[str, Any], keys: Sequence[str]) -> None:
    """
    Validate that required keys are present and not None in data dictionary.

    Args:
        data: The input data dictionary
        keys: List of required key names

    Raises:
        ValueError: If any required key is missing or None

    Example:
        validate_required_keys(data, ["name", "flds", "tmpls"])
    """
    for key in keys:
        if key not in data or data[key] is None:
            raise ValueError(f"'{key}' is required")


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
        ValueError: If key is missing, not a list, or empty

    Example:
        flds = validate_nonempty_list(data, "flds", "field")
    """
    value = data.get(key, [])
    if not value or not isinstance(value, list) or len(value) == 0:
        raise ValueError(f"At least one {item_name} is required in '{key}'")
    return value
