from typing import Any, Generic, List, Optional, Sequence, TypeVar, Union, Mapping
from pydantic import BaseModel, ConfigDict
from pydantic.fields import Field

# Scalars we may return when shape=scalar or auto-flatten
Scalar = Union[str, int, float, bool, None]

# Free-form projected object (when select=... returns dicts)
class ProjectedObject(BaseModel):
    model_config = ConfigDict(extra="allow")

# Generic paginated envelope; covariant + Sequence fixes list invariance issues
T = TypeVar("T", covariant=True)

class Paginated(BaseModel, Generic[T]):
    items: Sequence[T]
    next_cursor: Optional[str] = None
    stats: dict

class MutationResult(BaseModel, Generic[T]):
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