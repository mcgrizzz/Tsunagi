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
