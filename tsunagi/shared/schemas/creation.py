"""The same per-input result contract for single and bulk creation."""
from typing import Generic, List, TypeVar

from pydantic import BaseModel, Field
from pydantic.generics import GenericModel


class CreationFailure(BaseModel):
    index: int = Field(description="Zero-based position in the submitted array; 0 for one object.")
    code: str
    message: str


Created = TypeVar("Created")


class CreationResult(GenericModel, Generic[Created]):
    created: List[Created] = Field(default_factory=list)
    failed: List[CreationFailure] = Field(default_factory=list)


IDEMPOTENCY_HELP = (
    "Optional. Send a new unique value (for example a UUID) with each request you "
    "may retry. A retry with the same key returns the first attempt's response "
    "(header Idempotent-Replayed: true) instead of creating again, including after "
    "a 503 whose write completed later. Keys are per app and kept ten minutes.")
