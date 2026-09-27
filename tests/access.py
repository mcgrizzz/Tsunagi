"""Config fragments for tests of apps and groups (backlog 6.5a)."""


def key_required(key, group="default", name="Test app"):
    """One app with `key`; keyless requests from this computer get No access."""
    return {"apps": [{"name": name, "key": key, "group": group}],
            "no_key_local_group": "none"}
