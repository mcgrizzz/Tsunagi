from typing import Any, Dict, List, Mapping, Sequence
from aqt import mw
from anki.collection import Collection, OpChanges

from ..ops import as_collection_op, on_main
from ...shared.schemas.models import ModelInfo
from ...shared.helpers import validate_required_keys, copy_if_present, validate_nonempty_list

@on_main
def list_models() -> List[ModelInfo]:
    return [ModelInfo.model_validate(m) for m in mw.col.models.all()] # 1 query + 3*each notetype This is worst case since it runs on all notetypes

@on_main
def get_models_by_ids(ids: Sequence[int]) -> List[ModelInfo]: #3*each notetype
    mm = mw.col.models
    out: List[ModelInfo] = []
    for mid in ids:
        m = mm.get(mid)
        if m:
            out.append(ModelInfo.model_validate(m))
    return out

@on_main
def get_models_by_names(names: Sequence[str]) -> List[ModelInfo]: #1 + #3*each notetype
    mm = mw.col.models
    name_to_id: Dict[str, int] = {}
    for nt in mm.all_names_and_ids():
        name_to_id[nt.name] = int(nt.id)

    out: List[ModelInfo] = []
    for name in names:
        if name in name_to_id:
            m = mm.get(name_to_id[name]) # type: ignore
            if m:
                out.append(ModelInfo.model_validate(m))
    return out

@on_main
def get_model_names_and_ids() -> List[Mapping[str, Any]]: #1 query
    res: List[Mapping[str, Any]] = []
    for nt in mw.col.models.all_names_and_ids():
        # nt.id is NotetypeId -> int() is fine
        res.append({"id": int(nt.id), "name": nt.name})
    return res


# requires: name, flds (need a name), tmpls
# optional: field properties, template properties, type, css
@as_collection_op #Undoable, background thread
def create_model(col: Collection, data: Dict[str, Any]) -> ModelInfo:
    mm = col.models

    # Validate required fields
    validate_required_keys(data, ["name"])
    name = data["name"]
    flds = validate_nonempty_list(data, "flds", "field")
    tmpls = validate_nonempty_list(data, "tmpls", "template")

    # Check name doesn't already exist
    if name in [n.name for n in mm.all_names_and_ids()]:
        raise ValueError(f"Model name '{name}' already exists")

    # Create new model (defaults to standard type)
    m = mm.new(name)

    # Set to cloze type if explicitly requested
    if data.get("type") in [1, "cloze"]:
        m["type"] = 1

    # Copy optional model-level properties
    copy_if_present(data, m, ["css"])

    # Add fields
    for fld_data in flds:
        validate_required_keys(fld_data, ["name"])
        fm = mm.new_field(fld_data["name"])

        # Copy optional field properties
        copy_if_present(fld_data, fm, [
            "sticky", "rtl", "font", "size", "description",
            "plainText", "collapsed", "excludeFromSearch", "preventDeletion"
        ])

        mm.addField(m, fm)

    # Add templates
    for idx, tmpl_data in enumerate(tmpls, start=1):
        # Default to "Card #" if no name provided
        template_name = tmpl_data.get("name", f"Card {idx}")
        t = mm.new_template(template_name)

        # Copy optional template properties
        copy_if_present(tmpl_data, t, ["qfmt", "afmt", "bqfmt", "bafmt"])

        mm.addTemplate(m, t)

    # Save the model to collection
    mm.add(m)

    return ModelInfo.model_validate(m)
    