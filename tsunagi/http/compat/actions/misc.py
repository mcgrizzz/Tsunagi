"""
AnkiConnect compatibility handlers: miscellaneous actions.
"""
from typing import Any, Dict

from ..registry import registry


@registry.register("version")
def ac_version(params: Dict[str, Any]) -> int:
    return 6
