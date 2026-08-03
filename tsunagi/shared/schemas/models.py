from __future__ import annotations

from typing import Any, List, Optional, Tuple

from pydantic import BaseModel, Field

# ----------------- Models -----------------

class ModelField(BaseModel):
    class Config:
        extra = "ignore"
        anystr_strip_whitespace = True
        allow_population_by_field_name = True  # Accept both field names and aliases

    name: str
    ord: int
    sticky: bool = False
    rtl: bool = False

    # display info
    font: Optional[str] = None
    size: Optional[int] = None

    # schema 11 extras
    description: str = ""
    plain_text: bool = Field(alias="plainText", default=False)
    collapsed: bool = False
    exclude_from_search: bool = Field(alias="excludeFromSearch", default=False)
    prevent_deletion: bool = Field(alias="preventDeletion", default=False)

    id: Optional[int] = None
    media: List[str] = Field(default_factory=list)  


class ModelTemplate(BaseModel):
    class Config:
        extra = "ignore"
        anystr_strip_whitespace = True
        allow_population_by_field_name = True  # Accept both field names and aliases

    name: str
    ord: int

    # Keep Anki's template format naming as they're domain-specific
    qfmt: Optional[str] = None
    afmt: Optional[str] = None
    bqfmt: Optional[str] = None
    bafmt: Optional[str] = None
    did: Optional[int] = None


# req entries are [template_ord, "none|all|any", [field_ords]]
ReqEntry = Tuple[int, str, List[int]]


# ----------------- Request Schemas -----------------
# These mirror the response models but are used for parsing request bodies
# They support both clean names and Anki's abbreviated names via aliasing

class FieldCreate(BaseModel):
    """Schema for creating a field in a model"""
    class Config:
        allow_population_by_field_name = True

    name: str
    ord: Optional[int] = None
    sticky: bool = False
    rtl: bool = False
    font: Optional[str] = None
    size: Optional[int] = None
    description: str = ""
    plain_text: bool = Field(alias="plainText", default=False)
    collapsed: bool = False
    exclude_from_search: bool = Field(alias="excludeFromSearch", default=False)
    prevent_deletion: bool = Field(alias="preventDeletion", default=False)


class FieldPatch(BaseModel):
    """Schema for patching a field - all fields optional"""
    class Config:
        allow_population_by_field_name = True

    name: Optional[str] = None
    sticky: Optional[bool] = None
    rtl: Optional[bool] = None
    font: Optional[str] = None
    size: Optional[int] = None
    description: Optional[str] = None
    plain_text: Optional[bool] = Field(alias="plainText", default=None)
    collapsed: Optional[bool] = None
    exclude_from_search: Optional[bool] = Field(alias="excludeFromSearch", default=None)
    prevent_deletion: Optional[bool] = Field(alias="preventDeletion", default=None)


class TemplateCreate(BaseModel):
    """Schema for creating a template in a model"""
    class Config:
        allow_population_by_field_name = True

    name: str
    ord: Optional[int] = None
    qfmt: Optional[str] = None
    afmt: Optional[str] = None
    bqfmt: Optional[str] = None
    bafmt: Optional[str] = None


class TemplatePatch(BaseModel):
    """Schema for patching a template - all fields optional"""
    class Config:
        allow_population_by_field_name = True

    name: Optional[str] = None
    qfmt: Optional[str] = None
    afmt: Optional[str] = None
    bqfmt: Optional[str] = None
    bafmt: Optional[str] = None


class ModelCreate(BaseModel):
    """Schema for creating a model"""
    class Config:
        allow_population_by_field_name = True

    name: str
    fields: List[FieldCreate] = Field(alias="flds")
    templates: List[TemplateCreate] = Field(alias="tmpls")
    css: Optional[str] = None
    sort_field: Optional[int] = Field(alias="sortf", default=0)


class ModelPatch(BaseModel):
    """Schema for patching a model - all fields optional"""
    class Config:
        allow_population_by_field_name = True

    name: Optional[str] = None
    css: Optional[str] = None
    sort_field: Optional[int] = Field(alias="sortf", default=None)
    type: Optional[int] = None


# ----------------- Response Schemas -----------------

class ModelInfo(BaseModel):
    class Config:
        extra = "ignore"
        anystr_strip_whitespace = True
        allow_population_by_field_name = True  # Accept both field names and aliases

    id: int
    name: str

    # keep as plain ints (no enums)
    type: int = 0
    mod: int = 0
    usn: int = 0
    sort_field: int = Field(alias="sortf", default=0)
    did: Optional[int] = None

    templates: List[ModelTemplate] = Field(alias="tmpls")
    fields: List[ModelField] = Field(alias="flds")

    css: str = ""
    latex_pre: str = Field(alias="latexPre", default="")
    latex_post: str = Field(alias="latexPost", default="")
    latex_svg: bool = Field(alias="latexsvg", default=False)

    req: List[ReqEntry] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    vers: List[Any] = Field(default_factory=list)

    # stock metadata as plain ints
    original_stock_kind: Optional[int] = Field(alias="originalStockKind", default=None)
    original_id: Optional[int] = Field(alias="originalId", default=None)