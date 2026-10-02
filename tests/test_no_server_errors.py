"""
A client's mistake is never a 500 (backlog 6.70). Sends every /v1 write a
plausible body built from its OpenAPI schema, then one bad value at a time in
each field, nested one level: null, 0, -1, numbers beyond 64 bits, NaN, empty
and odd strings, empty and repeated lists. Path ids get 0, -1, huge and
unknown values. Whatever the answer, it must not be a 500.

Not probed here: actions on Anki's windows and check database need the real
Qt main window (the stub has none; checked offscreen with real Anki), and
sync, profile switch and exit reach outside the test collection.
"""
import json
import re

import pytest

SKIPPED = re.compile(r"^/v1/(gui:|collection:check-database$|collection:sync$|profiles:load$)")


def resolve(spec, schema):
    while "$ref" in schema:
        schema = spec["components"]["schemas"][schema["$ref"].rsplit("/", 1)[1]]
    if len(schema.get("allOf", [])) == 1:
        return resolve(spec, schema["allOf"][0])
    if "anyOf" in schema:
        options = [o for o in schema["anyOf"] if o.get("type") != "null"]
        return resolve(spec, options[0]) if options else {"type": "null"}
    return schema


def plausible(spec, schema, name, ids):
    """A value that passes validation, using real ids where the name says which."""
    schema = resolve(spec, schema)
    if "enum" in schema:
        return schema["enum"][0]
    if schema.get("default") is not None:
        return schema["default"]
    kind, name = schema.get("type"), name.lower()
    if kind == "integer":
        return next((v for k, v in ids.items() if k in name), max(1, schema.get("minimum", 1)))
    if kind == "number":
        return max(1.0, schema.get("minimum", 1.0))
    if kind == "boolean":
        return False
    if kind == "string":
        return {"deck": "Default", "model": "Basic", "search": "deck:*",
                "path": "probe.apkg"}.get(next((k for k in ("deck", "model", "search", "path")
                                                if k in name), ""), "x")
    if kind == "array":
        return [plausible(spec, schema.get("items", {}), name, ids)]
    if kind == "object" or "properties" in schema:
        return {k: plausible(spec, v, k, ids) for k, v in schema.get("properties", {}).items()}
    return "x"


def bad_values(spec, schema, name, ids):
    schema = resolve(spec, schema)
    kind = schema.get("type")
    values = [None]
    if kind == "integer":
        values += [0, -1, 2 ** 63, 2 ** 64, 999999999999]
    elif kind == "number":
        values += [0.0, -1.0, 1e308, float("nan"), float("inf")]
    elif kind == "string":
        values += ["", " ", "\u0000", "nonexistent", "::", "../x", "deck:\"", "(", "x" * 5000]
    elif kind == "array":
        item = plausible(spec, schema.get("items", {}), name, ids)
        values += [[], [item, item]]
        values += [[bad] for bad in bad_values(spec, schema.get("items", {}), name, ids)[1:]]
    elif kind == "object" or "properties" in schema:
        values.append({})
    if "enum" in schema:
        values.append("not-a-choice")
    return values


def bodies(spec, schema, ids):
    """The plausible body, an empty one, then one bad value per field."""
    schema = resolve(spec, schema)
    body = plausible(spec, schema, "", ids)
    yield body
    yield {}
    for key, field in schema.get("properties", {}).items():
        for bad in bad_values(spec, field, key, ids):
            yield {**body, key: bad}
        inner = resolve(spec, field)
        listed = inner.get("type") == "array"
        inner = resolve(spec, inner.get("items", {})) if listed else inner
        for sub_key, sub_field in inner.get("properties", {}).items():
            item = plausible(spec, inner, key, ids)
            for bad in bad_values(spec, sub_field, sub_key, ids):
                value = {**item, sub_key: bad}
                yield {**body, key: [value] if listed else value}


def urls(path, ids):
    """The path with real ids, then with bad ones in each parameter."""
    params = re.findall(r"\{(\w+)(?::path)?\}", path)
    real = {p: str(next((v for k, v in ids.items() if k in p), "nonexistent")) for p in params}
    variants = [real]
    for p in params:
        bad = (["0", "-1", str(2 ** 63), "999999999999", "abc"] if "id" in p
               else ["nonexistent", "x" * 300, "%00"])
        variants += [{**real, p: b} for b in bad]
    for values in variants:
        yield re.sub(r"\{(\w+)(?::path)?\}", lambda m, values=values: values[m.group(1)], path)


@pytest.fixture()
def unraised_client(col, reset_settings, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from tsunagi.app import app

    reset_settings.update(no_key_local_role="everything")
    monkeypatch.chdir(tmp_path)  # exports with relative paths land here
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000),
                    raise_server_exceptions=False) as client:
        yield client


def test_no_write_answers_500(unraised_client, col):
    note = col.new_note(col.models.by_name("Basic"))
    note["Front"] = "probe"
    col.add_note(note, 1)
    ids = {"note": note.id, "card": note.cards()[0].id, "model": note.mid, "deck": 1}
    spec = unraised_client.get("/openapi.json").json()
    failures, sent = [], 0
    for path, operations in spec["paths"].items():
        if not path.startswith("/v1/") or SKIPPED.match(path):
            continue
        for method, operation in operations.items():
            if method == "get":
                continue
            schema = (operation.get("requestBody", {}).get("content", {})
                      .get("application/json", {}).get("schema"))
            requests = [(url, plausible(spec, schema, "", ids) if schema else None)
                        for url in urls(path, ids)]
            if schema:
                requests += [(next(urls(path, ids)), body) for body in bodies(spec, schema, ids)]
            for url, body in requests:
                sent += 1
                resp = unraised_client.request(
                    method.upper(), url, content=None if body is None else json.dumps(body),
                    headers={"content-type": "application/json"})
                if resp.status_code == 500:
                    failures.append(f"{method.upper()} {url} {json.dumps(body)[:200]}: {resp.text}")
    assert sent > 1000
    assert not failures, "\n".join(failures)
