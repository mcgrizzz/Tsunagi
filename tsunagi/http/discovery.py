"""Combine registered native routes with Anki support and current settings."""
from fastapi.routing import APIRoute

from ..adapters.settings import settings
from ..shared.schemas.capabilities import CapabilityState, OperationCapability


def state(*, supported=True, enabled=True, setting=None):
    if not supported:
        return CapabilityState(status="unsupported", reason="Unsupported by this Anki version", setting=setting)
    if not enabled:
        return CapabilityState(status="disabled", reason="Available but disabled in settings", setting=setting)
    return CapabilityState(setting=setting)


def native_features(support):
    fsrs = support["fsrs"]
    return {"fsrs_scheduling": state(supported=fsrs["supported"], enabled=fsrs["enabled"],
                                    setting="anki.fsrs")}


def native_operations(routes, support):
    operations = {}
    gates = dict(settings.get("gates") or {})
    for route in routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/v1/") or not route.include_in_schema:
            continue
        for method in sorted(route.methods):
            key = f"{method} {route.path_format}"
            status = state()
            options = {}
            if method == "POST" and route.path.startswith("/v1/fsrs:"):
                name = route.path.split(":", 1)[1].replace("-", "_")
                feature = support["fsrs"]["operations"].get(name)
                if feature is not None:
                    status = state(supported=feature["available"])
                    options = {name: state(supported=False) for name in feature.get("unsupported_options", [])}
            if key == "POST /v1/cards:set-memory-state":
                status = state(enabled=bool(gates.get("cards_set_memory_state")),
                               setting="gates.cards_set_memory_state")
                options["cards[].decay"] = state(supported=support["card_decay"],
                                                 enabled=bool(gates.get("cards_set_memory_state")),
                                                 setting="gates.cards_set_memory_state")
            if key == "POST /v1/media":
                options["path"] = state(enabled=bool(gates.get("media_allow_local_path")),
                                        setting="gates.media_allow_local_path")
            if method in {"POST", "PATCH"} and route.path in {"/v1/decks", "/v1/decks/{id}"}:
                options["desired_retention"] = state(supported=support["deck_desired_retention"])
            if key in {"POST /v1/collection:import", "GET /v1/collection/import-options"}:
                status = state(supported=support["import_available"])
                options.update({name: state(supported=False) for name in support["unsupported_import_options"]})
            operations[key] = OperationCapability(operation_id=route.operation_id or route.unique_id,
                                                 options=options, **status.dict())
    return dict(sorted(operations.items()))
