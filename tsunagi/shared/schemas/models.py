from __future__ import annotations

from typing import Any, List, Optional, Tuple

from pydantic import BaseModel, Field

from .wrappers import NULLABLE, RequestBody, coded

# ----------------- Models -----------------

class ModelField(BaseModel):
    class Config:
        extra = "ignore"
        anystr_strip_whitespace = True
        allow_population_by_field_name = True  # Accept both field names and aliases

    name: str = Field(description="Field name.")
    ord: int = Field(description="Field position, from 0.")
    sticky: bool = Field(False, description="Keep the field's last value when adding the next note.")
    rtl: bool = Field(False, description="Edit the field right to left.")

    # display info
    font: Optional[str] = Field(None, description="Font used for the field in the editor.")
    size: Optional[int] = Field(None, description="Font size used for the field in the editor.")

    # schema 11 extras
    description: str = Field("", description="Text shown inside the field in the editor while it is empty.")
    plain_text: bool = Field(False, alias="plainText", description="Open the field in the HTML editor by default.")
    collapsed: bool = Field(False, description="Collapse the field in the editor by default.")
    exclude_from_search: bool = Field(False, alias="excludeFromSearch", description=(
        "Leave the field out of searches that don't name a field."))
    prevent_deletion: bool = Field(False, alias="preventDeletion", description=(
        "The field can't be deleted (required by the note type, e.g. Image Occlusion)."))

    id: Optional[int] = Field(None, description=(
        "Stable field id Anki uses to merge note types on import; null on fields from older versions."),
        **NULLABLE)
    media: List[str] = Field(default_factory=list, description="Legacy key from older Anki versions; usually empty.")


class ModelTemplate(BaseModel):
    class Config:
        extra = "ignore"
        anystr_strip_whitespace = True
        allow_population_by_field_name = True  # Accept both field names and aliases

    name: str = Field(description="Template name.")
    ord: int = Field(description="Template position, from 0; cards record it as their ord.")

    # Keep Anki's template format naming as they're domain-specific
    qfmt: Optional[str] = Field(None, description="Front template.")
    afmt: Optional[str] = Field(None, description="Back template.")
    bqfmt: Optional[str] = Field(None, description=(
        'Front template for the browser\'s Question column; "" uses qfmt.'))
    bafmt: Optional[str] = Field(None, description='Back template for the browser\'s Answer column; "" uses afmt.')
    did: Optional[int] = Field(None, description=(
        "Deck that new cards from this template go to, overriding the chosen deck; null when none."),
        **NULLABLE)


# req entries are [template_ord, "none|all|any", [field_ords]]
ReqEntry = Tuple[int, str, List[int]]


# ----------------- Request Schemas -----------------
# These mirror the response models but are used for parsing request bodies
# They support both clean names and Anki's abbreviated names via aliasing

class FieldCreate(RequestBody):
    """Schema for creating a field in a model"""
    class Config:
        allow_population_by_field_name = True

    name: str
    ord: Optional[int] = None
    sticky: bool = False
    rtl: bool = False
    font: Optional[str] = None
    size: Optional[int] = Field(None, ge=0, le=65535)  # Anki stores a 16-bit size
    description: str = ""
    plain_text: bool = Field(alias="plainText", default=False)
    collapsed: bool = False
    exclude_from_search: bool = Field(alias="excludeFromSearch", default=False)
    prevent_deletion: bool = Field(alias="preventDeletion", default=False)


class FieldPatch(RequestBody):
    """Schema for patching a field - all fields optional"""
    class Config:
        allow_population_by_field_name = True

    name: Optional[str] = None
    sticky: Optional[bool] = None
    rtl: Optional[bool] = None
    font: Optional[str] = None
    size: Optional[int] = Field(None, ge=0, le=65535)  # Anki stores a 16-bit size
    description: Optional[str] = None
    plain_text: Optional[bool] = Field(alias="plainText", default=None)
    collapsed: Optional[bool] = None
    exclude_from_search: Optional[bool] = Field(alias="excludeFromSearch", default=None)
    prevent_deletion: Optional[bool] = Field(alias="preventDeletion", default=None)


class TemplateCreate(RequestBody):
    """Schema for creating a template in a model"""
    class Config:
        allow_population_by_field_name = True

    name: str
    ord: Optional[int] = None
    qfmt: Optional[str] = None
    afmt: Optional[str] = None
    bqfmt: Optional[str] = None
    bafmt: Optional[str] = None


class TemplatePatch(RequestBody):
    """Schema for patching a template - all fields optional"""
    class Config:
        allow_population_by_field_name = True

    name: Optional[str] = None
    qfmt: Optional[str] = None
    afmt: Optional[str] = None
    bqfmt: Optional[str] = None
    bafmt: Optional[str] = None


class ModelCreate(RequestBody):
    """Schema for creating a model"""
    class Config:
        allow_population_by_field_name = True

    name: str
    fields: List[FieldCreate] = Field(alias="flds")
    templates: List[TemplateCreate] = Field(alias="tmpls")
    css: Optional[str] = None
    sort_field: Optional[int] = Field(alias="sortf", default=0)
    # 0 standard, 1 cloze. Fixed at creation - ModelPatch deliberately can't
    # change it. Without this key, normalize_field_names dropped it and cloze
    # note types were impossible to create.
    type: Optional[int] = None


class FindReplaceRequest(RequestBody):
    """Literal (non-regex) replace across template sides and styling."""
    class Config:
        allow_population_by_field_name = True

    find: str
    replace: str
    # Omit to sweep every model.
    model_name: Optional[str] = Field(alias="modelName", default=None)
    front: bool = True
    back: bool = True
    css: bool = True


class FindReplaceResult(BaseModel):
    """`affected` counts models that actually contained the text."""
    affected: int
    stats: dict


class ModelPatch(RequestBody):
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

    id: int = Field(description="Note type id.")
    name: str = Field(description="Note type name.")

    note_count: Optional[int] = Field(
        default=None,
        description="How many notes use this note type. "
                    "Computed by native model queries; may be null in mutation replies.",
    )

    type: int = Field(0, description="Standard or cloze.", **coded({0: "standard", 1: "cloze"}))
    mod: int = Field(0, description="Last modified, Unix seconds.")
    usn: int = Field(0, description="Update sequence number for syncing; -1 means changed since the last sync.")
    sort_field: int = Field(0, alias="sortf", description="Position (from 0) of the field the browser shows and sorts by.")
    did: Optional[int] = Field(None, description=(
        "Legacy last-used deck id. Current Anki stores that elsewhere; null when unset."), **NULLABLE)

    templates: List[ModelTemplate] = Field(alias="tmpls", description="The note type's card templates, in order.")
    fields: List[ModelField] = Field(alias="flds", description="The note type's fields, in order.")

    css: str = Field("", description="Styling shared by all the note type's cards.")
    latex_pre: str = Field("", alias="latexPre", description="LaTeX header added before each LaTeX snippet.")
    latex_post: str = Field("", alias="latexPost", description="LaTeX footer added after each LaTeX snippet.")
    latex_svg: bool = Field(False, alias="latexsvg", description="Whether LaTeX is rendered as SVG instead of PNG.")

    req: List[ReqEntry] = Field(default_factory=list, description=(
        'Fields each template needs: [template ord, "any"|"all"|"none", [field ords]].'))
    tags: List[str] = Field(default_factory=list, description="Legacy key from older Anki versions; usually empty.")
    vers: List[Any] = Field(default_factory=list, description="Legacy key from older Anki versions; usually empty.")

    original_stock_kind: Optional[int] = Field(None, alias="originalStockKind", description=(
        "The built-in type this note type was made from; null when unknown or before Anki 2.1.62."),
        **coded({1: "basic", 2: "basic_and_reversed", 3: "basic_optional_reversed", 4: "basic_typing",
                 5: "cloze", 6: "image_occlusion"}), **NULLABLE)
    original_id: Optional[int] = Field(None, alias="originalId", description=(
        "For an imported note type, its id in the collection it came from; null otherwise."), **NULLABLE)
