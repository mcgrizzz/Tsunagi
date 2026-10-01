"""Combine registered native routes with Anki support and the caller's permissions."""
from fastapi.routing import APIRoute

from ..adapters import addon_actions
from ..shared.permissions import ADDON, PUBLIC, current_denial, permitted
from ..shared.schemas.capabilities import CapabilityState, OperationCapability


def state(*, supported=True, enabled=True, setting=None,
          reason="Available but disabled in settings"):
    if not supported:
        return CapabilityState(status="unsupported", reason="Unsupported by this Anki version", setting=setting)
    if not enabled:
        return CapabilityState(status="disabled", reason=reason, setting=setting)
    return CapabilityState(setting=setting)


def permission_state(permission, **kwargs):
    """Disabled when the calling app's role lacks `permission`."""
    if permission == PUBLIC:
        return state(**kwargs)
    return state(enabled=permitted(permission), setting=f"permissions.{permission}",
                 reason=current_denial(permission), **kwargs)


def native_features(support):
    """Features that would tell an app what it may not read (whether FSRS is
    on, which add-ons are installed) show as disabled for one without the
    permission, naming it (backlog 6.62)."""
    fsrs = support["fsrs"]
    if permitted("read:collection"):
        fsrs_state = state(supported=fsrs["supported"], enabled=fsrs["enabled"], setting="anki.fsrs")
    else:
        fsrs_state = permission_state("read:collection")
    features = {"fsrs_scheduling": fsrs_state}
    # Each bundled add-on provider; its items' own statuses are in
    # GET /v1/addons/{provider}/actions.
    for provider in addon_actions.PROVIDERS.values():
        reason = addon_actions.unavailable(provider)
        if not permitted("read:addons"):
            features[f"addon_actions.{provider.id}"] = permission_state("read:addons")
        else:
            features[f"addon_actions.{provider.id}"] = (
                CapabilityState(status="unsupported", reason=reason) if reason else state())
    return features


def native_operations(routes, support):
    operations = {}
    for route in routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/v1/") or not route.include_in_schema:
            continue
        for method in sorted(route.methods):
            key = f"{method} {route.path_format}"
            permission = (route.openapi_extra or {}).get("x-permission")
            # Add-on items are allowed one by one; the actions list has each status.
            status = state() if permission == ADDON else permission_state(permission)
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
