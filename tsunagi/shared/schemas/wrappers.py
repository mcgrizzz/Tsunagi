from typing import Dict, Generic, List, Literal, Optional, Sequence, TypeVar, Union

from pydantic import BaseModel, Field
from pydantic.generics import GenericModel

# Scalars we may return when shape=scalar
Scalar = Union[str, int, float, bool, None]

# Every request body: a key the body doesn't have is a 422 naming it, not
# quietly dropped (accept only what takes effect, 6.84).
class RequestBody(BaseModel):
    class Config:
        extra = "forbid"

# Schema extras for row fields (6.101), passed as Field(..., **extra): what a
# coded field's numbers mean (short names a client can name its values by;
# the prose goes in the description), and that a present field can be null.
def coded(values: Dict[int, str]) -> dict:
    return {"x-values": {str(code): name for code, name in values.items()}}

NULLABLE = {"x-nullable": True}

# A row field built from other resources (a card's deck_name): a change there
# changes it (6.105), so a client keeping the field current follows them too.
def derived(*resources: str) -> dict:
    return {"x-from": list(resources)}

# Every error answer (6.105): the description's `default` response. 422s
# also carry `errors` (HTTPValidationError).
class ErrorBody(BaseModel):
    detail: str = Field(description="What went wrong, for the app to show; it can quote note content. Never parse it")
    reason: Optional[Literal["busy", "closed", "syncing"]] = Field(None, description=(
        "On a 503, why Anki can't answer now: busy (it didn't answer in time), closed (no collection "
        "is open, e.g. during a full sync) or syncing; null otherwise"), **NULLABLE)

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
    # Only with include=total; left out of the response otherwise.
    total: Optional[int] = Field(None, description="With include=total: every row the query matches, "
                                                   "across all pages")

class MutationResult(GenericModel, Generic[T]):
    result: T
    stats: dict

class DeletionResult(BaseModel):
    success: bool
    affected_ids: List[int]
    stats: dict

# Wrapper for POST queries, for more complicated and/or structured
class QueryRequest(RequestBody):
    select: Optional[str] = None
    where: Optional[List[str]] = None
    search: Optional[str] = None   # Anki search string (search-backed resources)
    shape: Literal["object", "scalar"] = "object"
    order: Optional[str] = None     # e.g. "due:desc"; see the GET parameter
    distinct_on: Optional[str] = None   # one row per value of this field; see the GET parameter
    include: Optional[str] = None   # extra parts, comma-separated; see the GET parameter
    limit: Optional[int] = Field(default=None, ge=0, description="Maximum results in this response; 0 for none (with include=total, the count alone). Omit to return all matches; no fixed upper cap.")
    cursor: Optional[str] = None
