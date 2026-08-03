"""
Action registry for AnkiConnect compatibility layer.

Maps AnkiConnect action names to handler functions. Handlers either take the
raw params dict, or - when registered with a pydantic params model - the
validated model instance.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Tuple, Type

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

ActionHandler = Callable[[Any], Any]


class AnkiConnectRegistry:
    """
    Registry for AnkiConnect action handlers.

    Example usage:
        @registry.register("deckNames")
        def ac_deckNames(params: Dict[str, Any]) -> List[str]:
            ...

        class ModelFieldNamesParams(BaseModel):
            modelName: str

        @registry.register("modelFieldNames", params=ModelFieldNamesParams)
        def ac_modelFieldNames(p: ModelFieldNamesParams) -> List[str]:
            ...  # receives the validated model instance
    """

    def __init__(self):
        self._handlers: Dict[str, Tuple[ActionHandler, Optional[Type[BaseModel]]]] = {}

    def register(
        self,
        action_name: str,
        params: Optional[Type[BaseModel]] = None,
    ) -> Callable[[ActionHandler], ActionHandler]:
        """
        Decorator to register an action handler.

        Args:
            action_name: The AnkiConnect action name (e.g., "deckNames")
            params: Optional pydantic model; when given, incoming params are
                validated against it and the handler receives the instance.
                Validation failure surfaces as the action's error string.
        """
        def decorator(func: ActionHandler) -> ActionHandler:
            if action_name in self._handlers:
                raise ValueError(f"Action '{action_name}' is already registered")
            self._handlers[action_name] = (func, params)
            return func
        return decorator

    def handle(self, action_name: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """
        Execute a handler for the given action.

        Raises:
            ValueError: unknown action, or params failed validation
        """
        if action_name not in self._handlers:
            from .errors import UNSUPPORTED_ACTION
            raise ValueError(UNSUPPORTED_ACTION)

        handler, model = self._handlers[action_name]
        if model is not None:
            try:
                parsed = model.parse_obj(params or {})
            except PydanticValidationError as e:
                raise ValueError(str(e)) from e
            return handler(parsed)
        return handler(params or {})

    def is_registered(self, action_name: str) -> bool:
        """Check if an action is registered."""
        return action_name in self._handlers

    def list_actions(self) -> list[str]:
        """Get a list of all registered action names."""
        return sorted(self._handlers.keys())


# Global registry instance
registry = AnkiConnectRegistry()
