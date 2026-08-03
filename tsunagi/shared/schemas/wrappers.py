from typing import Generic, List, Optional, Sequence, TypeVar, Union

from pydantic import BaseModel, Field
from pydantic.generics import GenericModel

# Scalars we may return when shape=scalar or auto-flatten
Scalar = Union[str, int, float, bool, None]

# Free-form projected object (when select=... returns dicts)
class ProjectedObject(BaseModel):
    class Config:
        extra = "allow"

# Generic paginated envelope; covariant + Sequence fixes list invariance issues.
# Must be GenericModel (not BaseModel + Generic): parametrizing a plain
# BaseModel leaks typing's __orig_class__ into __dict__/.dict() output.
T = TypeVar("T", covariant=True)

class Paginated(GenericModel, Generic[T]):
    items: Sequence[T]
    next_cursor: Optional[str] = None
    stats: dict

class MutationResult(GenericModel, Generic[T]):
    result: T
    stats: dict

class DeletionResult(BaseModel):
    success: bool
    affected_ids: List[int]
    stats: dict

# Wrapper for POST queries, for more complicated and/or structured
class QueryRequest(BaseModel):
    select: Optional[str] = None
    where: Optional[List[str]] = None
    shape: Optional[str] = "auto"
    limit: int = Field(default=1000, ge=1, le=5000)
    cursor: Optional[str] = None