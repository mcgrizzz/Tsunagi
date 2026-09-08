"""The pinned AnkiConnect HTTP request schema; native routes do not use it."""

from pprint import pformat
from textwrap import indent
from typing import Any, Optional

REQUEST_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "minLength": 1},
        "version": {"type": "integer"},
        "params": {"type": "object"},
    },
    "required": ["action"],
}


def _error(message: str, validator: str, value: Any, field: Optional[str] = None) -> str:
    schema = REQUEST_SCHEMA if field is None else REQUEST_SCHEMA["properties"][field]
    schema_path = "" if field is None else f"['properties'][{field!r}]"
    instance_path = "" if field is None else f"[{field!r}]"
    schema_text = indent(pformat(schema, width=72, sort_dicts=False), "    ")
    instance_text = indent(pformat(value, width=72, sort_dicts=False), "    ")
    return (
        f"{message}\n\nFailed validating {validator!r} in schema{schema_path}:\n"
        f"{schema_text}\n\nOn instance{instance_path}:\n{instance_text}"
    )


def request_error(body: Any) -> Optional[str]:
    """Validate this fixed shallow schema, with jsonschema 4.23 diagnostics.

    Upstream validates only the outer HTTP request. Its multi entries bypass this
    schema. Keep the rules explicit here rather than adding a general validator
    and its dependencies to the installed addon.
    """
    if not isinstance(body, dict):
        return _error(f"{body!r} is not of type 'object'", "type", body)
    if "action" not in body:
        return _error("'action' is a required property", "required", body)
    # jsonschema's best_match prefers root errors, then the last property path
    # alphabetically when multiple properties at the same depth are invalid.
    for field in ("version", "params", "action"):
        if field not in body:
            continue
        value = body[field]
        expected = REQUEST_SCHEMA["properties"][field]["type"]
        valid = {
            "object": isinstance(value, dict),
            "string": isinstance(value, str),
            "integer": (isinstance(value, int) and not isinstance(value, bool))
            or (isinstance(value, float) and value.is_integer()),
        }[expected]
        if not valid:
            return _error(f"{value!r} is not of type {expected!r}", "type", value, field)
        if field == "action" and not value:
            return _error("'' should be non-empty", "minLength", value, field)
    return None
