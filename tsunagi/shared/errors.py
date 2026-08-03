"""
Custom error classes and utilities for API operations.
"""
from __future__ import annotations

import time
import traceback
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable, Dict, Iterator, TypeVar

from fastapi import HTTPException


class ResourceNotFoundError(Exception):
    """Raised when a parent resource doesn't exist"""
    def __init__(self, resource_type: str, resource_id: int):
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.status_code = 404
        super().__init__(f"{resource_type} {resource_id} not found")


class SubresourceNotFoundError(Exception):
    """Raised when a subresource item doesn't exist"""
    def __init__(self, parent_type: str, parent_id: int, subres_type: str, subres_id: str):
        self.parent_type = parent_type
        self.parent_id = parent_id
        self.subres_type = subres_type
        self.subres_id = subres_id
        self.status_code = 404
        super().__init__(
            f"{subres_type} '{subres_id}' not found in {parent_type} {parent_id}"
        )


class ValidationError(Exception):
    """Raised when request data is invalid"""
    def __init__(self, message: str):
        self.status_code = 400
        super().__init__(message)


class DuplicateNoteError(Exception):
    """Raised when adding a note that duplicates an existing one"""
    def __init__(self, note_ids: list):
        self.note_ids = note_ids
        self.status_code = 409
        super().__init__(f"Note duplicates existing note(s): {note_ids}")


class AnkiBusyError(Exception):
    """Raised when a cross-thread operation times out (Anki busy/blocked)"""
    def __init__(self, message: str = "Anki is busy; operation timed out"):
        self.status_code = 503
        super().__init__(message)


class CollectionUnavailableError(Exception):
    """Raised when the collection is not open (profile closed/switching)"""
    def __init__(self, message: str = "Collection is not available"):
        self.status_code = 503
        super().__init__(message)


def register_exception_handlers(app: Any) -> None:
    """
    Map availability errors raised outside handle_mutation_errors (e.g. from
    query fetchers) to 503 responses, matching HTTPException's body shape.
    """
    from fastapi.responses import JSONResponse

    def _unavailable(request: Any, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    app.add_exception_handler(AnkiBusyError, _unavailable)
    app.add_exception_handler(CollectionUnavailableError, _unavailable)


T = TypeVar('T')


@contextmanager
def track_operation(operation_name: str) -> Iterator[Dict[str, Any]]:
    """
    Context manager to track operation timing and metadata.

    Yields a stats dictionary that will be populated with timing information.
    The duration_ms will be automatically calculated when the context exits.

    Usage:
        with track_operation("create") as stats:
            result = perform_operation()
            # stats dict is updated with duration_ms when exiting

        # stats now contains {"duration_ms": 12.345, "operation": "create"}
    """
    stats: Dict[str, Any] = {"operation": operation_name}
    start = time.perf_counter()
    try:
        yield stats
    finally:
        stats["duration_ms"] = round((time.perf_counter() - start) * 1000, 3)


def handle_mutation_errors(operation_name: str = "operation") -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator to standardize mutation error handling.

    Maps custom exceptions to appropriate HTTP responses:
    - ResourceNotFoundError, SubresourceNotFoundError -> 404
    - ValidationError -> 400
    - ValueError -> 400
    - Other exceptions -> 500

    Args:
        operation_name: Name of the operation for error messages (e.g., "create", "update")

    Usage:
        @handle_mutation_errors("create")
        def create_model(data: Dict[str, Any]) -> ModelInfo:
            # ...
    """
    def to_http_exception(exc: Exception) -> HTTPException:
        if isinstance(exc, (ResourceNotFoundError, SubresourceNotFoundError, ValidationError,
                            DuplicateNoteError, AnkiBusyError, CollectionUnavailableError)):
            return HTTPException(status_code=exc.status_code, detail=str(exc))
        if isinstance(exc, ValueError):
            return HTTPException(status_code=400, detail=str(exc))
        if isinstance(exc, HTTPException):
            # Pass through existing HTTPExceptions without wrapping
            return exc
        # Log the real error server-side; don't leak internals to clients.
        print(f"[tsunagi] {operation_name} failed:\n" + traceback.format_exc())
        return HTTPException(
            status_code=500,
            detail=f"{operation_name.capitalize()} failed"
        )

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                raise to_http_exception(e) from e
        return wrapper
    return decorator
