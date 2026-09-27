"""Config fragments for tests of apps and roles (backlog 6.5a)."""


def key_required(key, role="default", name="Test app"):
    """One app with `key`; keyless requests from this computer get No access."""
    return {"apps": [{"name": name, "key": key, "role": role}],
            "no_key_local_role": "none"}
