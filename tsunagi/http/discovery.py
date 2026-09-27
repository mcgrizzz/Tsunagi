"""Combine registered native routes with Anki support and the caller's permissions."""
from fastapi.routing import APIRoute

from ..shared.permissions import PUBLIC, current_denial, permitted
from ..shared.schemas.capabilities import CapabilityState, OperationCapability


def state(*, supported=True, enabled=True, setting=None,
          reason="Available but disabled in settings"):
    if not supported:
        return CapabilityState(status="unsupported", reason="Unsupported by this Anki version", setting=setting)
    if not enabled:
        return CapabilityState(status="disabled", reason=reason, setting=setting)
    return CapabilityState(setting=setting)


def permission_state(permission, **kwargs):
    """Disabled when the calling app's group lacks `permission`."""
    if permission == PUBLIC:
        return state(**kwargs)
    return state(enabled=permitted(permission), setting=f"permissions.{permission}",
                 reason=current_denial(permission), **kwargs)


def native_features(support):
    fsrs = support["fsrs"]
    return {"fsrs_scheduling": state(supported=fsrs["supported"], enabled=fsrs["enabled"],
                                    setting="anki.fsrs")}


def native_operations(routes, support):
    operations = {}
    for route in routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/v1/") or not route.include_in_schema:
            continue
        for method in sorted(route.methods):
            key = f"{method} {route.path_format}"
            status = permission_state((route.openapi_extra or {}).get("x-permission"))
            options = {}
            if method == "POST" and route.path.startswith("/v1/fsrs:"):
                name = route.path.split(":", 1)[1].replace("-", "_")
                feature = support["fsrs"]["operations"].get(name)
                if feature is not None:
                    if not feature["available"]:
                        status = state(supported=False)
                    options = {name: state(supported=False) for name in feature.get("unsupported_options", [])}
            if key == "POST /v1/cards:set-memory-state":
                options["cards[].decay"] = permission_state("memory_state",
                                                            supported=support["card_decay"])
            if key == "POST /v1/media":
                options["path"] = permission_state("local_files")
            if method in {"POST", "PATCH"} and route.path in {"/v1/decks", "/v1/decks/{id}"}:
                options["desired_retention"] = state(supported=support["deck_desired_retention"])
            if key in {"POST /v1/collection:import", "GET /v1/collection/import-options"}:
                if not support["import_available"]:
                    status = state(supported=False)
                options.update({name: state(supported=False) for name in support["unsupported_import_options"]})
            operations[key] = OperationCapability(operation_id=route.operation_id or route.unique_id,
                                                 options=options, **status.dict())
    return dict(sorted(operations.items()))
