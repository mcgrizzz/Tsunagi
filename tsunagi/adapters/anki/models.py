from typing import Any, Dict, List, Mapping, Sequence

from anki.collection import Collection

from ...shared.errors import ResourceNotFoundError, ValidationError
from ...shared.helpers import (
    copy_if_present,
    find_in_subresource,
    normalize_field_names,
    validate_nonempty_list,
    validate_required_keys,
    validate_subresource_order,
)
from ...shared.schemas.models import (
    FieldCreate,
    FieldPatch,
    ModelCreate,
    ModelInfo,
    ModelPatch,
    TemplateCreate,
    TemplatePatch,
)
from ..ops import as_collection_op, as_query_op


@as_query_op # Read, off the UI thread
def list_models(col: Collection) -> List[ModelInfo]:
    return [ModelInfo.parse_obj(m) for m in col.models.all()] # 1 query + 3*each notetype This is worst case since it runs on all notetypes

@as_query_op
def get_models_by_ids(col: Collection, ids: Sequence[int], wants=None) -> List[ModelInfo]: #3*each notetype
    # `wants` (requested top-level fields) is accepted for the fetcher
    # contract; a model has no field expensive enough to skip.
    mm = col.models
    out: List[ModelInfo] = []
    for mid in ids:
        m = mm.get(mid)
        if m:
            out.append(ModelInfo.parse_obj(m))
    return out

@as_query_op
def get_models_by_names(col: Collection, names: Sequence[str], wants=None) -> List[ModelInfo]: #1 + #3*each notetype
    mm = col.models
    name_to_id: Dict[str, int] = {}
    for nt in mm.all_names_and_ids():
        name_to_id[nt.name] = int(nt.id)

    out: List[ModelInfo] = []
    for name in names:
        if name in name_to_id:
            m = mm.get(name_to_id[name]) # type: ignore
            if m:
                out.append(ModelInfo.parse_obj(m))
    return out

@as_query_op
def get_raw_models(col: Collection, ids: Sequence[int] = (),
                   names: Sequence[str] = ()) -> Dict[Any, Dict[str, Any]]:
    """
    Raw schema11 notetype dicts, keyed by whichever lookup was used.

    The compat findModelsBy* actions must return Anki's dict verbatim;
    routing them through ModelInfo would silently drop any schema11 key the
    schema doesn't model.
    """
    mm = col.models
    out: Dict[Any, Dict[str, Any]] = {}
    for mid in ids:
        m = mm.get(int(mid))
        if m:
            out[int(mid)] = m
    for name in names:
        m = mm.by_name(name)
        if m:
            out[name] = m
    return out

@as_query_op
def get_model_names_and_ids(col: Collection) -> List[Mapping[str, Any]]: #1 query
    res: List[Mapping[str, Any]] = []
    for nt in col.models.all_names_and_ids():
        # nt.id is NotetypeId -> int() is fine
        res.append({"id": int(nt.id), "name": nt.name})
    return res


# requires: name, flds (need a name), tmpls
# optional: field properties, template properties, type, css
@as_collection_op #Undoable, background thread
def create_model(col: Collection, data: Dict[str, Any]) -> ModelInfo:
    mm = col.models

    # Normalize field names (accepts both "fields"/"flds", "templates"/"tmpls", etc.)
    data = normalize_field_names(data, ModelCreate)

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
        # Normalize field data (accepts both "plain_text"/"plainText", etc.)
        fld_data = normalize_field_names(fld_data, FieldCreate)

        validate_required_keys(fld_data, ["name"])
        fm = mm.new_field(fld_data["name"])

        # Copy optional field properties (using Anki's names after normalization)
        copy_if_present(fld_data, fm, [
            "sticky", "rtl", "font", "size", "description",
            "plainText", "collapsed", "excludeFromSearch", "preventDeletion"
        ])

        mm.add_field(m, fm)

    # Add templates
    for idx, tmpl_data in enumerate(tmpls, start=1):
        # Normalize template data
        tmpl_data = normalize_field_names(tmpl_data, TemplateCreate)

        # Default to "Card #" if no name provided
        template_name = tmpl_data.get("name", f"Card {idx}")
        t = mm.new_template(template_name)

        # Copy optional template properties
        copy_if_present(tmpl_data, t, ["qfmt", "afmt", "bqfmt", "bafmt"])

        mm.add_template(m, t)

    # Save the model to collection
    mm.add(m)

    return ModelInfo.parse_obj(m)


# ====================
# Top-Level Mutations
# ====================

@as_collection_op
def patch_model(col: Collection, model_id: int, updates: Dict[str, Any]) -> ModelInfo:
    """
    Update top-level model properties (name, css, sort_field/sortf).

    PATCH /v1/models/{id}
    """
    mm = col.models
    m = mm.get(model_id)
    if not m:
        raise ResourceNotFoundError("Model", model_id)

    # Normalize field names (accepts both "sort_field"/"sortf", etc.)
    updates = normalize_field_names(updates, ModelPatch)

    # Apply updates to allowed top-level properties. Note: a notetype's "type"
    # (standard vs cloze) is fixed at creation and intentionally not patchable.
    copy_if_present(updates, m, ["name", "css", "sortf"])
    mm.update_dict(m)
    return ModelInfo.parse_obj(m)


@as_collection_op
def delete_model(col: Collection, model_id: int) -> bool:
    """
    Delete a model/notetype.

    DELETE /v1/models/{id}
    """
    mm = col.models
    m = mm.get(model_id)
    if not m:
        raise ResourceNotFoundError("Model", model_id)

    mm.remove(model_id)
    return True


# ====================
# Field Subresource Mutations
# ====================

@as_collection_op
def create_field(col: Collection, model_id: int, field_data: Dict[str, Any]) -> ModelInfo:
    """
    Add a new field to a model.

    POST /v1/models/{id}/fields
    """
    mm = col.models
    m = mm.get(model_id)
    if not m:
        raise ResourceNotFoundError("Model", model_id)

    # Normalize field names (accepts both "plain_text"/"plainText", etc.)
    field_data = normalize_field_names(field_data, FieldCreate)

    validate_required_keys(field_data, ["name"])
    field = mm.new_field(field_data["name"])

    # Apply optional field properties (using Anki's names after normalization)
    copy_if_present(field_data, field, [
        "font", "size", "sticky", "rtl", "description",
        "plainText", "collapsed", "excludeFromSearch", "preventDeletion"
    ])

    mm.add_field(m, field)
    mm.update_dict(m)
    return ModelInfo.parse_obj(m)


@as_collection_op
def patch_field(col: Collection, model_id: int, field_name: str, updates: Dict[str, Any]) -> ModelInfo:
    """
    Update a field's properties.

    PATCH /v1/models/{id}/fields/{name}
    """
    mm = col.models
    m = mm.get(model_id)
    if not m:
        raise ResourceNotFoundError("Model", model_id)

    # Normalize field names (accepts both "plain_text"/"plainText", etc.)
    updates = normalize_field_names(updates, FieldPatch)

    field = find_in_subresource(m, "flds", field_name, "name")

    # Special handling for rename
    if "name" in updates:
        mm.rename_field(m, field, updates["name"])

    # Direct property updates (using Anki's names after normalization)
    copy_if_present(updates, field, [
        "font", "size", "sticky", "rtl", "description",
        "plainText", "collapsed", "excludeFromSearch", "preventDeletion"
    ])

    mm.update_dict(m)
    return ModelInfo.parse_obj(m)


@as_collection_op
def delete_field(col: Collection, model_id: int, field_name: str) -> ModelInfo:
    """
    Remove a field from a model.

    DELETE /v1/models/{id}/fields/{name}
    """
    mm = col.models
    m = mm.get(model_id)
    if not m:
        raise ResourceNotFoundError("Model", model_id)

    if len(m["flds"]) <= 1:
        raise ValidationError("Cannot delete last field. Model must have at least one field.")

    field = find_in_subresource(m, "flds", field_name, "name")
    mm.remove_field(m, field)
    mm.update_dict(m)
    return ModelInfo.parse_obj(m)


@as_collection_op
def reorder_fields(col: Collection, model_id: int, order: List[str]) -> ModelInfo:
    """
    Reorder fields in a model.

    PUT /v1/models/{id}/fields:order
    Body: {"order": ["field1", "field2", ...]}
    """
    mm = col.models
    m = mm.get(model_id)
    if not m:
        raise ResourceNotFoundError("Model", model_id)

    validate_subresource_order(m, "flds", order, "name")

    # Reposition each field to its new index
    for new_idx, field_name in enumerate(order):
        field = find_in_subresource(m, "flds", field_name, "name")
        mm.reposition_field(m, field, new_idx)

    mm.update_dict(m)
    return ModelInfo.parse_obj(m)


# ====================
# Template Subresource Mutations
# ====================

@as_collection_op
def create_template(col: Collection, model_id: int, template_data: Dict[str, Any]) -> ModelInfo:
    """
    Add a new template to a model.

    POST /v1/models/{id}/templates
    """
    mm = col.models
    m = mm.get(model_id)
    if not m:
        raise ResourceNotFoundError("Model", model_id)

    # Normalize template data
    template_data = normalize_field_names(template_data, TemplateCreate)

    # Default name if not provided
    name = template_data.get("name", f"Card {len(m['tmpls']) + 1}")
    template = mm.new_template(name)

    # Apply optional template properties
    copy_if_present(template_data, template, ["qfmt", "afmt", "bqfmt", "bafmt"])

    mm.add_template(m, template)
    mm.update_dict(m)
    return ModelInfo.parse_obj(m)


@as_collection_op
def patch_template(col: Collection, model_id: int, template_name: str, updates: Dict[str, Any]) -> ModelInfo:
    """
    Update a template's properties.

    PATCH /v1/models/{id}/templates/{name}
    """
    mm = col.models
    m = mm.get(model_id)
    if not m:
        raise ResourceNotFoundError("Model", model_id)

    # Normalize template data
    updates = normalize_field_names(updates, TemplatePatch)

    template = find_in_subresource(m, "tmpls", template_name, "name")

    # Apply property updates
    copy_if_present(updates, template, ["name", "qfmt", "afmt", "bqfmt", "bafmt"])

    mm.update_dict(m)
    return ModelInfo.parse_obj(m)


@as_collection_op
def delete_template(col: Collection, model_id: int, template_name: str) -> ModelInfo:
    """
    Remove a template from a model.

    DELETE /v1/models/{id}/templates/{name}
    """
    mm = col.models
    m = mm.get(model_id)
    if not m:
        raise ResourceNotFoundError("Model", model_id)

    if len(m["tmpls"]) <= 1:
        raise ValidationError("Cannot delete last template. Model must have at least one template.")

    template = find_in_subresource(m, "tmpls", template_name, "name")
    mm.remove_template(m, template)
    mm.update_dict(m)
    return ModelInfo.parse_obj(m)


@as_collection_op
def reorder_templates(col: Collection, model_id: int, order: List[str]) -> ModelInfo:
    """
    Reorder templates in a model.

    PUT /v1/models/{id}/templates:order
    Body: {"order": ["template1", "template2", ...]}
    """
    mm = col.models
    m = mm.get(model_id)
    if not m:
        raise ResourceNotFoundError("Model", model_id)

    validate_subresource_order(m, "tmpls", order, "name")

    # Reposition each template to its new index
    for new_idx, template_name in enumerate(order):
        template = find_in_subresource(m, "tmpls", template_name, "name")
        mm.reposition_template(m, template, new_idx)

    mm.update_dict(m)
    return ModelInfo.parse_obj(m)
