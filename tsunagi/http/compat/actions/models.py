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
    find_and_replace_in_models,
    get_model_names_and_ids,
    get_models_by_names,
    get_raw_models,
    patch_model,
)
from ..errors import (
    FIELD_NOT_FOUND,
    MODEL_NOT_FOUND,
    TEMPLATE_NOT_FOUND,
)
from ..registry import registry

_FIELD_REF = re.compile("{{[^#/}]+?}}")
_BRACES = re.compile(r"[{}]")


class ModelFieldNamesParams(BaseModel):
    modelName: str


class FindModelsByNameParams(BaseModel):
    modelNames: List[str]


class FindModelsByIdParams(BaseModel):
    modelIds: List[int]


class ModelIdParams(BaseModel):
    modelId: int


class CreateModelParams(BaseModel):
    modelName: Any = ...
    inOrderFields: Any = ...
    cardTemplates: Any = ...
    css: Any = None
    isCloze: Any = False


class FindAndReplaceParams(BaseModel):
    modelName: Optional[str] = None
    findText: str
    replaceText: str
    front: bool = True
    back: bool = True
    css: bool = True


class TemplateRenameParams(BaseModel):
    modelName: Any = ...
    oldTemplateName: Any = ...
    newTemplateName: Any = ...


class TemplateRepositionParams(BaseModel):
    modelName: Any = ...
    templateName: Any = ...
    index: Any = ...


class TemplateAddParams(BaseModel):
    modelName: Any = ...
    template: Any = ...


class TemplateNameParams(BaseModel):
    modelName: Any = ...
    templateName: Any = ...


class FieldRenameParams(BaseModel):
    modelName: Any = ...
    oldFieldName: Any = ...
    newFieldName: Any = ...


class FieldRepositionParams(BaseModel):
    modelName: Any = ...
    fieldName: Any = ...
    index: Any = ...


class FieldAddParams(BaseModel):
    modelName: Any = ...
    fieldName: Any = ...
    index: Any = None


class FieldNameParams(BaseModel):
    modelName: Any = ...
    fieldName: Any = ...


class FieldSetFontParams(FieldNameParams):
    font: Any


class FieldSetFontSizeParams(FieldNameParams):
    fontSize: Any


class FieldSetDescriptionParams(FieldNameParams):
    description: Any


class UpdateModelTemplatesParams(BaseModel):
    model: Any = ...


class UpdateModelStylingParams(BaseModel):
    model: Any = ...


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
            for match in _FIELD_REF.findall(template[side]):
                name = _BRACES.sub("", match).split(":")[-1]
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
    from ....adapters.anki.compat import create_model_raw

    return create_model_raw(p.modelName, p.inOrderFields, p.cardTemplates, p.css, p.isCloze)


@registry.register("findAndReplaceInModels", params=FindAndReplaceParams)
def ac_findAndReplaceInModels(p: FindAndReplaceParams) -> int:
    from anki.errors import CardTypeError, InvalidInput

    try:
        models = (
            [_raw_model(p.modelName)] if p.modelName
            else get_raw_models(ids=[m["id"] for m in get_model_names_and_ids()]).values()
        )
        updated = 0
        for model in models:
            count = find_and_replace_in_models(
                p.findText, p.replaceText, model["name"], p.front, p.back, p.css)
            if not count:
                # The extra save is an AnkiConnect side effect, owned here.
                patch_model(model["id"], {})
            updated += count
        return updated
    except (CardTypeError, InvalidInput) as exc:
        raise ValueError(str(exc)) from exc


@registry.register("updateModelTemplates", params=UpdateModelTemplatesParams)
def ac_updateModelTemplates(p: UpdateModelTemplatesParams) -> None:
    from ....adapters.anki.compat import update_model_raw

    update_model_raw(p.model, templates=True)


@registry.register("updateModelStyling", params=UpdateModelStylingParams)
def ac_updateModelStyling(p: UpdateModelStylingParams) -> None:
    from ....adapters.anki.compat import update_model_raw

    update_model_raw(p.model, templates=False)


# --- template edits -----------------------------------------------------

@registry.register("modelTemplateRename", params=TemplateRenameParams)
def ac_modelTemplateRename(p: TemplateRenameParams) -> None:
    return _template_change(p, "rename", name=p.oldTemplateName, value=p.newTemplateName)


@registry.register("modelTemplateReposition", params=TemplateRepositionParams)
def ac_modelTemplateReposition(p: TemplateRepositionParams) -> None:
    return _template_change(p, "reposition", name=p.templateName, index=p.index)


@registry.register("modelTemplateAdd", params=TemplateAddParams)
def ac_modelTemplateAdd(p: TemplateAddParams) -> None:
    return _template_change(p, "add", spec=p.template)


@registry.register("modelTemplateRemove", params=TemplateNameParams)
def ac_modelTemplateRemove(p: TemplateNameParams) -> None:
    return _template_change(p, "remove", name=p.templateName)


@registry.register("modelFieldRename", params=FieldRenameParams)
def ac_modelFieldRename(p: FieldRenameParams) -> None:
    return _field_change(p, "rename", p.oldFieldName, value=p.newFieldName)


@registry.register("modelFieldReposition", params=FieldRepositionParams)
def ac_modelFieldReposition(p: FieldRepositionParams) -> None:
    return _field_change(p, "reposition", p.fieldName, index=p.index)


@registry.register("modelFieldAdd", params=FieldAddParams)
def ac_modelFieldAdd(p: FieldAddParams) -> None:
    return _field_change(p, "add", p.fieldName, index=p.index)


@registry.register("modelFieldRemove", params=FieldNameParams)
def ac_modelFieldRemove(p: FieldNameParams) -> None:
    return _field_change(p, "remove", p.fieldName)


@registry.register("modelFieldSetFont", params=FieldSetFontParams)
def ac_modelFieldSetFont(p: FieldSetFontParams) -> None:
    return _field_change(p, "font", p.fieldName, value=p.font)


@registry.register("modelFieldSetFontSize", params=FieldSetFontSizeParams)
def ac_modelFieldSetFontSize(p: FieldSetFontSizeParams) -> None:
    return _field_change(p, "size", p.fieldName, value=p.fontSize)


@registry.register("modelFieldSetDescription", params=FieldSetDescriptionParams)
def ac_modelFieldSetDescription(p: FieldSetDescriptionParams) -> bool:
    return _field_change(p, "description", p.fieldName, value=p.description)


def _field_change(p, action, name, **kwargs):
    from ....adapters.anki.compat import mutate_model_field_raw

    result, error = mutate_model_field_raw(p.modelName, action, name, **kwargs)
    if error is not None:
        raise ValueError(error)
    return result


def _template_change(p, action, **kwargs):
    from ....adapters.anki.compat import mutate_model_template_raw

    result, error = mutate_model_template_raw(p.modelName, action, **kwargs)
    if error is not None:
        raise ValueError(error)
    return result
