from __future__ import annotations

from typing import Any, List, Optional, Tuple
from pydantic import BaseModel, ConfigDict
from pydantic.fields import Field

# ----------------- Models -----------------

class ModelField(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    name: str
    ord: int
    sticky: bool = False
    rtl: bool = False

    # display info
    font: Optional[str] = None
    size: Optional[int] = None

    # schema 11 extras
    description: str = ""                  
    plainText: bool = False
    collapsed: bool = False
    excludeFromSearch: bool = False
    preventDeletion: bool = False

    id: Optional[int] = None
    media: List[str] = Field(default_factory=list)  


class ModelTemplate(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    name: str
    ord: int

    qfmt: Optional[str] = None
    afmt: Optional[str] = None
    bqfmt: Optional[str] = None
    bafmt: Optional[str] = None
    did: Optional[int] = None


# req entries are [template_ord, "none|all|any", [field_ords]]
ReqEntry = Tuple[int, str, List[int]]

class ModelInfo(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    id: int
    name: str

    # keep as plain ints (no enums)
    type: int = 0
    mod: int = 0
    usn: int = 0
    sortf: int = 0
    did: Optional[int] = None

    tmpls: List[ModelTemplate]
    flds: List[ModelField]

    css: str = ""
    latexPre: str = ""
    latexPost: str = ""
    latexsvg: bool = False

    req: List[ReqEntry] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    vers: List[Any] = Field(default_factory=list)

    # stock metadata as plain ints
    originalStockKind: Optional[int] = None
    originalId: Optional[int] = None