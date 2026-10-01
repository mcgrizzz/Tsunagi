"""
Custom error classes and utilities for API operations.
"""
from __future__ import annotations

import logging
import time
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


class ConflictError(Exception):
    """The request is valid but clashes with the collection's state: a name or
    id that's taken. 400 is for a request that is wrong in itself."""
    def __init__(self, message: str):
        self.status_code = 409
        super().__init__(message)


class DuplicateNoteError(Exception):
    """Raised when adding a note that duplicates an existing one"""
    def __init__(self, note_ids: list):
        self.note_ids = note_ids
        self.status_code = 409
        super().__init__(f"Note duplicates existing note(s): {note_ids}")


class AnkiBusyError(Exception):
    """Raised when a cross-thread operation times out (Anki busy/blocked)"""
    reason = "busy"

    def __init__(self, message: str = "Anki is busy; operation timed out"):
        self.status_code = 503
        super().__init__(message)


class CollectionUnavailableError(Exception):
    """Raised when the collection is not open (profile closed/switching)"""
    reason = "closed"

    def __init__(self, message: str = "Collection is not available"):
        self.status_code = 503
        super().__init__(message)


class UnsupportedAnkiVersionError(Exception):
    """Raised when the running Anki lacks an API a route depends on"""
    def __init__(self, feature: str, minimum: str = ""):
        self.status_code = 501
        detail = f" (requires Anki {minimum}+)" if minimum else ""
        super().__init__(
            f"{feature} is not supported by this Anki version{detail}"
        )


class SyncConflictError(Exception):
    """The collection needs a full sync, which Anki must do with the user."""
    def __init__(self, message: str):
        self.status_code = 409
        super().__init__(message)


class SyncFailedError(Exception):
    """AnkiWeb or the network refused the sync; the message says why."""
    def __init__(self, message: str):
        self.status_code = 502
        super().__init__(message)


class JobConflictError(Exception):
    """Raised when a job request conflicts with the job's or store's state"""
    def __init__(self, message: str):
        self.status_code = 409
        super().__init__(message)


def register_exception_handlers(app: Any, syncing: Callable[[], bool] = lambda: False) -> None:
    """
    Map availability errors to 503 responses: HTTPException's body shape plus
    a `reason` (busy, closed or syncing) a client can show the user.
    """
    from fastapi.responses import JSONResponse

    def _unavailable(request: Any, exc: Exception) -> JSONResponse:
        reason = "syncing" if syncing() else getattr(exc, "reason", "busy")
        return JSONResponse(status_code=503, content={"detail": str(exc), "reason": reason})

    app.add_exception_handler(AnkiBusyError, _unavailable)
    app.add_exception_handler(CollectionUnavailableError, _unavailable)

    from fastapi.exceptions import RequestValidationError

    def _invalid(request: Any, exc: RequestValidationError) -> JSONResponse:
        # `detail` is a string in every error response; FastAPI's own 422
        # puts its list there, so the list moves to `errors`.
        errors = exc.errors()
        parts = [f"{'.'.join(str(p) for p in e.get('loc', ()))}: {e.get('msg', '')}" for e in errors[:3]]
        more = f" (and {len(errors) - 3} more)" if len(errors) > 3 else ""
        return JSONResponse(status_code=422, content={
            "detail": "Invalid request: " + "; ".join(parts) + more,
            "errors": jsonable_errors(errors)})

    app.add_exception_handler(RequestValidationError, _invalid)


def jsonable_errors(errors: list) -> list:
    """Validation errors as JSON: their context can hold exceptions or other objects."""
    from fastapi.encoders import jsonable_encoder
    return jsonable_encoder(errors)


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


# Anki errors that mean "the client sent something invalid", not "we broke".
# Matched by name rather than by class so this module stays importable without
# anki - the same idiom the adapters already use. Anything not listed here is
# a genuine fault and still becomes a 500.
ANKI_CLIENT_ERRORS = frozenset({
    "CardTypeError",     # template has no field replacement, or names a missing field
    "TemplateError",
    "InvalidInput",
    "SearchError",
    "DeckRenameError",
    "FilteredDeckError",
    "ExistsError",
})

# Anki wraps interpolated names in Unicode directional isolates for RTL
# rendering. They are invisible noise in a JSON error message.
_ISOLATES = str.maketrans("", "", "⁦⁧⁨⁩")


def anki_error_detail(exc: Exception) -> str:
    return str(exc).translate(_ISOLATES)


def handle_mutation_errors(operation_name: str = "operation") -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator to standardize mutation error handling.

    Maps custom exceptions to appropriate HTTP responses:
    - ResourceNotFoundError, SubresourceNotFoundError -> 404
    - ValidationError -> 400
    - ConflictError, DuplicateNoteError, JobConflictError, SyncConflictError -> 409
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
                            ConflictError, DuplicateNoteError, UnsupportedAnkiVersionError, JobConflictError,
                            SyncConflictError, SyncFailedError)):
            return HTTPException(status_code=exc.status_code, detail=str(exc))
        if type(exc).__name__ in ANKI_CLIENT_ERRORS:
            # Anki's own message explains the problem far better than we could
            # ("Expected to find a field replacement on the front of the card").
            return HTTPException(status_code=400, detail=anki_error_detail(exc))
        if isinstance(exc, ValueError):
            return HTTPException(status_code=400, detail=str(exc))
        if isinstance(exc, HTTPException):
            # Pass through existing HTTPExceptions without wrapping
            return exc
        # Log the real error server-side; don't leak internals to clients.
        logging.getLogger(__name__).exception("%s failed", operation_name.capitalize())
        return HTTPException(
            status_code=500,
            detail=f"{operation_name.capitalize()} failed"
        )

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            try:
                return func(*args, **kwargs)
            except (AnkiBusyError, CollectionUnavailableError):
                raise  # register_exception_handlers adds the 503 reason
            except Exception as e:
                raise to_http_exception(e) from e
        return wrapper
    return decorator
