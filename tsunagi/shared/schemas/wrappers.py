from typing import Any, Generic, Optional, Sequence, TypeVar, Union, Mapping
from pydantic import BaseModel, ConfigDict

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
    stats: dict | None = None
