"""
Action registry for AnkiConnect compatibility layer.

This module provides a registry pattern for mapping AnkiConnect action names
to handler functions. Handlers receive AnkiConnect parameters and return
results in AnkiConnect format.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

ActionHandler = Callable[[Dict[str, Any]], Any]


class AnkiConnectRegistry:
    """
    Registry for AnkiConnect action handlers.

    Example usage:
        registry = AnkiConnectRegistry()

        @registry.register("findModelsById")
        def find_models_by_id(params: Dict[str, Any]) -> List[Optional[Dict[str, Any]]]:
            model_ids = params.get("modelIds", [])
            # ... implementation
            return results

        # Later, handle a request:
        result = registry.handle("findModelsById", {"modelIds": [123, 456]})
    """

    def __init__(self):
        self._handlers: Dict[str, ActionHandler] = {}

    def register(self, action_name: str) -> Callable[[ActionHandler], ActionHandler]:
        """
        Decorator to register an action handler.

        Args:
            action_name: The AnkiConnect action name (e.g., "findModelsById")

        Returns:
            Decorator function

        Example:
            @registry.register("createModel")
            def create_model(params: Dict[str, Any]) -> int:
                # ...
                return model_id
        """
        def decorator(func: ActionHandler) -> ActionHandler:
            if action_name in self._handlers:
                raise ValueError(f"Action '{action_name}' is already registered")
            self._handlers[action_name] = func
            return func
        return decorator

    def handle(self, action_name: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """
        Execute a handler for the given action.

        Args:
            action_name: The AnkiConnect action name
            params: Parameters for the action (optional)

        Returns:
            Result from the handler

        Raises:
            ValueError: If action is not registered
        """
        if action_name not in self._handlers:
            available = ", ".join(sorted(self._handlers.keys()))
            raise ValueError(
                f"Unknown action: '{action_name}'. "
                f"Available actions: {available if available else 'none'}"
            )

        handler = self._handlers[action_name]
        return handler(params or {})

    def is_registered(self, action_name: str) -> bool:
        """Check if an action is registered."""
        return action_name in self._handlers

    def list_actions(self) -> list[str]:
        """Get a list of all registered action names."""
        return sorted(self._handlers.keys())


# Global registry instance
registry = AnkiConnectRegistry()
