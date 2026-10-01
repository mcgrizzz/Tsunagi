from typing import Generic, List, Literal, Optional, Sequence, TypeVar, Union

from pydantic import BaseModel, Field
from pydantic.generics import GenericModel

# Scalars we may return when shape=scalar
Scalar = Union[str, int, float, bool, None]

# Free-form projected object (when select=... returns dicts)
class ProjectedObject(BaseModel):
    class Config:
        extra = "allow"

# The answer to a `resource:verb` action on a set of rows (cards:suspend, notes:delete...).
class VerbResult(BaseModel):
    affected: int
    stats: dict

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
    search: Optional[str] = None   # Anki search string (search-backed resources)
    shape: Literal["object", "scalar"] = "object"
    order: Optional[str] = None     # e.g. "due:desc"; see the GET parameter
    limit: Optional[int] = Field(default=None, ge=1, description="Maximum results in this response. Omit to return all matches; no fixed upper cap.")
    cursor: Optional[str] = None
