"""
AnkiConnect compatibility handlers for model (note type) actions.

Wire shapes and error strings mirror AnkiConnect exactly (clients
string-match); full models are serialized with by_alias=True so keys match
Anki's schema11 names (flds, tmpls, sortf, ...).
"""
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from ....adapters.anki.models import (
    create_field,
    create_model,
    create_template,
    delete_field,
    delete_template,
    find_and_replace_in_models,
    get_model_names_and_ids,
    get_models_by_names,
    get_raw_models,
    patch_field,
    patch_model,
    patch_template,
    reorder_fields,
    reorder_templates,
)
from ..errors import (
    CREATE_MODEL_NO_FIELDS,
    CREATE_MODEL_NO_TEMPLATES,
    DESCRIPTION_NOT_STRING,
    FIELD_NOT_FOUND,
    FONT_NOT_STRING,
    FONT_SIZE_NOT_INT,
    MODEL_NAME_EXISTS,
    MODEL_NOT_FOUND,
    TEMPLATE_NOT_FOUND,
)
from ..registry import registry


class ModelFieldNamesParams(BaseModel):
    modelName: str


class FindModelsByNameParams(BaseModel):
    modelNames: List[str]


class FindModelsByIdParams(BaseModel):
    modelIds: List[int]


class ModelIdParams(BaseModel):
    modelId: int


class CreateModelParams(BaseModel):
    modelName: str
    inOrderFields: List[str]
    cardTemplates: List[Dict[str, str]]
    css: Optional[str] = None
    isCloze: bool = False


class FindAndReplaceParams(BaseModel):
    modelName: Optional[str] = None
    findText: str
    replaceText: str
    front: bool = True
    back: bool = True
    css: bool = True


class TemplateRenameParams(BaseModel):
    modelName: str
    oldTemplateName: str
    newTemplateName: str


class TemplateRepositionParams(BaseModel):
    modelName: str
    templateName: str
    index: int


class TemplateAddParams(BaseModel):
    modelName: str
    template: Dict[str, str]


class TemplateNameParams(BaseModel):
    modelName: str
    templateName: str


class FieldRenameParams(BaseModel):
    modelName: str
    oldFieldName: str
    newFieldName: str


class FieldRepositionParams(BaseModel):
    modelName: str
    fieldName: str
    index: int


class FieldAddParams(BaseModel):
    modelName: str
    fieldName: str
    index: Optional[int] = None


class FieldNameParams(BaseModel):
    modelName: str
    fieldName: str


class FieldSetFontParams(FieldNameParams):
    font: Any


class FieldSetFontSizeParams(FieldNameParams):
    fontSize: Any


class FieldSetDescriptionParams(FieldNameParams):
    description: Any


class UpdateModelTemplatesParams(BaseModel):
    model: Dict[str, Any]


class UpdateModelStylingParams(BaseModel):
    model: Dict[str, Any]


# --- shared lookups -----------------------------------------------------
# The native adapters raise their own 404-shaped errors; canonical's strings
# are different and clients match on them, so resolve here and raise those.

def _raw_model(name: str) -> Dict[str, Any]:
    model = get_raw_models(names=[name]).get(name)
    if model is None:
        raise ValueError(MODEL_NOT_FOUND.format(name))
    return model


def _require_field(model: Dict[str, Any], field_name: str) -> Dict[str, Any]:
    for field in model["flds"]:
        if field["name"] == field_name:
            return field
    raise ValueError(FIELD_NOT_FOUND.format(model["name"], field_name))


def _require_template(model: Dict[str, Any], template_name: str) -> Dict[str, Any]:
    for template in model["tmpls"]:
        if template["name"] == template_name:
            return template
    raise ValueError(TEMPLATE_NOT_FOUND.format(model["name"], template_name))


def _moved(names: List[str], name: str, index: int) -> List[str]:
    """`names` with `name` moved to `index` - the full order reorder_* wants."""
    rest = [n for n in names if n != name]
    return rest[:index] + [name] + rest[index:]


@registry.register("modelNames")
def ac_modelNames(params: Dict[str, Any]) -> List[str]:
    return [d["name"] for d in get_model_names_and_ids()]


@registry.register("modelNamesAndIds")
def ac_modelNamesAndIds(params: Dict[str, Any]) -> Dict[str, int]:
    return {d["name"]: d["id"] for d in get_model_names_and_ids()}


@registry.register("modelFieldNames", params=ModelFieldNamesParams)
def ac_modelFieldNames(p: ModelFieldNamesParams) -> List[str]:
    models = get_models_by_names([p.modelName])
    if not models:
        raise ValueError(MODEL_NOT_FOUND.format(p.modelName))
    return [f.name for f in models[0].fields]


# findModelsBy* return Anki's raw schema11 dict, exactly as AnkiConnect does.
# Routing them through ModelInfo would silently drop any schema11 key our
# schema doesn't model - the v1 API is where the curated shape belongs.

@registry.register("findModelsByName", params=FindModelsByNameParams)
def ac_findModelsByName(p: FindModelsByNameParams) -> List[Dict[str, Any]]:
    found = get_raw_models(names=p.modelNames)
    out: List[Dict[str, Any]] = []
    for name in p.modelNames:  # input order; raise at FIRST missing (as AnkiConnect)
        m = found.get(name)
        if m is None:
            raise ValueError(MODEL_NOT_FOUND.format(name))
        out.append(m)
    return out


@registry.register("findModelsById", params=FindModelsByIdParams)
def ac_findModelsById(p: FindModelsByIdParams) -> List[Dict[str, Any]]:
    found = get_raw_models(ids=[int(i) for i in p.modelIds])
    out: List[Dict[str, Any]] = []
    for mid in p.modelIds:
        m = found.get(int(mid))
        if m is None:
            raise ValueError(MODEL_NOT_FOUND.format(mid))
        out.append(m)
    return out


# --- raw schema11 reads -------------------------------------------------
# These go through get_raw_models rather than ModelInfo for the same reason
# findModelsBy* does: ModelField.font/size are Optional, so a curated shape
# would turn "Anki always sets this" into a lying null.

@registry.register("modelNameFromId", params=ModelIdParams)
def ac_modelNameFromId(p: ModelIdParams) -> str:
    model = get_raw_models(ids=[p.modelId]).get(p.modelId)
    if model is None:
        raise ValueError(MODEL_NOT_FOUND.format(p.modelId))
    return model["name"]


@registry.register("modelFieldDescriptions", params=ModelFieldNamesParams)
def ac_modelFieldDescriptions(p: ModelFieldNamesParams) -> List[str]:
    flds = _raw_model(p.modelName)["flds"]
    try:
        return [f["description"] for f in flds]
    except KeyError:
        # Anki older than field descriptions
        return ["" for _ in flds]


@registry.register("modelFieldFonts", params=ModelFieldNamesParams)
def ac_modelFieldFonts(p: ModelFieldNamesParams) -> Dict[str, Dict[str, Any]]:
    return {f["name"]: {"font": f["font"], "size": f["size"]}
            for f in _raw_model(p.modelName)["flds"]}


@registry.register("modelFieldsOnTemplates", params=ModelFieldNamesParams)
def ac_modelFieldsOnTemplates(p: ModelFieldNamesParams) -> Dict[str, List[List[str]]]:
    """{templateName: [[question fields], [answer fields]]} - canonical's parse."""
    out: Dict[str, List[List[str]]] = {}
    for template in _raw_model(p.modelName)["tmpls"]:
        sides: List[List[str]] = []
        for side in ("qfmt", "afmt"):
            names: List[str] = []
            for match in re.findall("{{[^#/}]+?}}", template[side]):
                name = re.sub(r"[{}]", "", match).split(":")[-1]
                # FrontSide is a directive, and the answer side doesn't repeat
                # what the question already showed.
                if name == "FrontSide" or (side == "afmt" and name in sides[0]):
                    continue
                names.append(name)
            sides.append(names)
        out[template["name"]] = sides
    return out


@registry.register("modelTemplates", params=ModelFieldNamesParams)
def ac_modelTemplates(p: ModelFieldNamesParams) -> Dict[str, Dict[str, str]]:
    return {t["name"]: {"Front": t["qfmt"], "Back": t["afmt"]}
            for t in _raw_model(p.modelName)["tmpls"]}


@registry.register("modelStyling", params=ModelFieldNamesParams)
def ac_modelStyling(p: ModelFieldNamesParams) -> Dict[str, str]:
    return {"css": _raw_model(p.modelName)["css"]}


# --- creation and bulk edits --------------------------------------------

@registry.register("createModel", params=CreateModelParams)
def ac_createModel(p: CreateModelParams) -> Dict[str, Any]:
    if not p.inOrderFields:
        raise ValueError(CREATE_MODEL_NO_FIELDS)
    if not p.cardTemplates:
        raise ValueError(CREATE_MODEL_NO_TEMPLATES)
    # Pre-check so the bare canonical string wins over the native one, which
    # names the model.
    if get_raw_models(names=[p.modelName]).get(p.modelName) is not None:
        raise ValueError(MODEL_NAME_EXISTS)

    templates = []
    for index, card in enumerate(p.cardTemplates, start=1):
        templates.append({
            "name": card.get("Name", f"Card {index}"),
            "qfmt": card.get("Front", ""),
            "afmt": card.get("Back", ""),
        })

    data: Dict[str, Any] = {
        "name": p.modelName,
        "flds": [{"name": name} for name in p.inOrderFields],
        "tmpls": templates,
    }
    if p.isCloze:
        data["type"] = 1
    if p.css is not None:
        data["css"] = p.css

    create_model(data)
    # Canonical returns Anki's raw notetype dict, not a curated shape.
    return get_raw_models(names=[p.modelName])[p.modelName]


@registry.register("findAndReplaceInModels", params=FindAndReplaceParams)
def ac_findAndReplaceInModels(p: FindAndReplaceParams) -> int:
    if p.modelName:
        _raw_model(p.modelName)          # canonical's model-not-found string
    return find_and_replace_in_models(
        p.findText, p.replaceText, p.modelName or None, p.front, p.back, p.css)


@registry.register("updateModelTemplates", params=UpdateModelTemplatesParams)
def ac_updateModelTemplates(p: UpdateModelTemplatesParams) -> None:
    model = _raw_model(p.model["name"])
    incoming = p.model.get("templates") or {}
    for template in model["tmpls"]:
        supplied = incoming.get(template["name"])
        if not supplied:
            continue                      # unknown names are silently ignored
        updates = {}
        # Only truthy values overwrite - canonical treats "" as "leave alone".
        if supplied.get("Front"):
            updates["qfmt"] = supplied["Front"]
        if supplied.get("Back"):
            updates["afmt"] = supplied["Back"]
        if updates:
            patch_template(model["id"], template["name"], updates)


@registry.register("updateModelStyling", params=UpdateModelStylingParams)
def ac_updateModelStyling(p: UpdateModelStylingParams) -> None:
    model = _raw_model(p.model["name"])
    patch_model(model["id"], {"css": p.model["css"]})


# --- template edits -----------------------------------------------------

@registry.register("modelTemplateRename", params=TemplateRenameParams)
def ac_modelTemplateRename(p: TemplateRenameParams) -> None:
    model = _raw_model(p.modelName)
    _require_template(model, p.oldTemplateName)
    patch_template(model["id"], p.oldTemplateName, {"name": p.newTemplateName})


@registry.register("modelTemplateReposition", params=TemplateRepositionParams)
def ac_modelTemplateReposition(p: TemplateRepositionParams) -> None:
    model = _raw_model(p.modelName)
    _require_template(model, p.templateName)
    names = [t["name"] for t in model["tmpls"]]
    reorder_templates(model["id"], _moved(names, p.templateName, p.index))


@registry.register("modelTemplateAdd", params=TemplateAddParams)
def ac_modelTemplateAdd(p: TemplateAddParams) -> None:
    model = _raw_model(p.modelName)
    name = p.template["Name"]
    updates = {"qfmt": p.template["Front"], "afmt": p.template["Back"]}

    for existing in model["tmpls"]:
        if existing["name"] == name:
            # DEVIATION: canonical mutates its working copy and returns without
            # saving, so the update is silently discarded. Ours persists it.
            patch_template(model["id"], name, updates)
            return
    create_template(model["id"], {"name": name, **updates})


@registry.register("modelTemplateRemove", params=TemplateNameParams)
def ac_modelTemplateRemove(p: TemplateNameParams) -> None:
    model = _raw_model(p.modelName)
    _require_template(model, p.templateName)
    delete_template(model["id"], p.templateName)


# --- field edits --------------------------------------------------------

@registry.register("modelFieldRename", params=FieldRenameParams)
def ac_modelFieldRename(p: FieldRenameParams) -> None:
    model = _raw_model(p.modelName)
    _require_field(model, p.oldFieldName)
    patch_field(model["id"], p.oldFieldName, {"name": p.newFieldName})


@registry.register("modelFieldReposition", params=FieldRepositionParams)
def ac_modelFieldReposition(p: FieldRepositionParams) -> None:
    model = _raw_model(p.modelName)
    _require_field(model, p.fieldName)
    names = [f["name"] for f in model["flds"]]
    reorder_fields(model["id"], _moved(names, p.fieldName, p.index))


@registry.register("modelFieldAdd", params=FieldAddParams)
def ac_modelFieldAdd(p: FieldAddParams) -> None:
    model = _raw_model(p.modelName)
    names = [f["name"] for f in model["flds"]]
    if p.fieldName not in names:
        create_field(model["id"], {"name": p.fieldName})
        names.append(p.fieldName)
    # Repositions even when the field already existed.
    if p.index is not None:
        reorder_fields(model["id"], _moved(names, p.fieldName, p.index))


@registry.register("modelFieldRemove", params=FieldNameParams)
def ac_modelFieldRemove(p: FieldNameParams) -> None:
    model = _raw_model(p.modelName)
    _require_field(model, p.fieldName)
    delete_field(model["id"], p.fieldName)


@registry.register("modelFieldSetFont", params=FieldSetFontParams)
def ac_modelFieldSetFont(p: FieldSetFontParams) -> None:
    if not isinstance(p.font, str):
        raise ValueError(FONT_NOT_STRING.format(p.font))
    model = _raw_model(p.modelName)
    _require_field(model, p.fieldName)
    patch_field(model["id"], p.fieldName, {"font": p.font})


@registry.register("modelFieldSetFontSize", params=FieldSetFontSizeParams)
def ac_modelFieldSetFontSize(p: FieldSetFontSizeParams) -> None:
    # bool is an int subclass, and a bool here is a client bug, not a size.
    if not isinstance(p.fontSize, int) or isinstance(p.fontSize, bool):
        raise ValueError(FONT_SIZE_NOT_INT.format(p.fontSize))
    model = _raw_model(p.modelName)
    _require_field(model, p.fieldName)
    patch_field(model["id"], p.fieldName, {"size": p.fontSize})


@registry.register("modelFieldSetDescription", params=FieldSetDescriptionParams)
def ac_modelFieldSetDescription(p: FieldSetDescriptionParams) -> bool:
    if not isinstance(p.description, str):
        raise ValueError(DESCRIPTION_NOT_STRING.format(p.description))
    model = _raw_model(p.modelName)
    _require_field(model, p.fieldName)
    patch_field(model["id"], p.fieldName, {"description": p.description})
    # Canonical returns False only on Anki too old to have the key at all.
    return True
