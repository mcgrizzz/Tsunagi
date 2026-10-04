"""
The API description names fields as answers and docs do (backlog 6.72): each
list documents its row fields, and no schema shows an alias (`cardIds`,
`ivl`) in place of a field name.
"""
import pytest
from pydantic import BaseModel

from tsunagi.shared.schemas.cards import CardInfo
from tsunagi.shared.schemas.decks import DeckConfigRow, DeckInfo
from tsunagi.shared.schemas.media import MediaRow
from tsunagi.shared.schemas.models import ModelInfo
from tsunagi.shared.schemas.notes import NoteInfo
from tsunagi.shared.schemas.reviews import ReviewInfo
from tsunagi.shared.schemas.tags import TagRow

LISTS = {"/v1/cards": CardInfo, "/v1/notes": NoteInfo, "/v1/decks": DeckInfo,
         "/v1/models": ModelInfo, "/v1/reviews": ReviewInfo, "/v1/deck-configs": DeckConfigRow,
         "/v1/media": MediaRow, "/v1/tags": TagRow}


@pytest.fixture()
def spec(client):
    return client.get("/openapi.json").json()


def resolve(spec, schema):
    return spec["components"]["schemas"][schema["$ref"].rsplit("/", 1)[1]]


@pytest.mark.parametrize("path", LISTS)
@pytest.mark.parametrize("method,suffix", [("get", ""), ("post", "/query")])
def test_each_list_documents_its_row_fields(spec, path, method, suffix):
    response = spec["paths"][path + suffix][method]["responses"]["200"]
    page = resolve(spec, response["content"]["application/json"]["schema"])
    row = resolve(spec, page["properties"]["items"]["items"])
    assert set(row["properties"]) == set(LISTS[path].__fields__)
    assert "required" not in row  # select keeps only the fields it names


# Fields whose numbers stand for something (6.101): each lists its values.
CODED = {"CardRow": {"type", "queue", "flag"}, "ReviewRow": {"ease", "type"},
         "ModelRow": {"type", "original_stock_kind"}, "DeckRow": {"dynamic"}}


def test_every_row_field_is_described_and_coded_fields_list_their_values(spec):
    schemas = spec["components"]["schemas"]
    rows, seen = [], set()
    for path in [*LISTS, "/v1/addons"]:
        page = resolve(spec, spec["paths"][path]["get"]["responses"]["200"]["content"]["application/json"]["schema"])
        rows.append(page["properties"]["items"]["items"]["$ref"].rsplit("/", 1)[1])
    while rows:  # the rows and the objects inside them
        name = rows.pop()
        if name in seen:
            continue
        seen.add(name)
        for field, node in schemas[name]["properties"].items():
            assert node.get("description"), f"{name}.{field} has no description"
            assert ("x-values" in node) == (field in CODED.get(name, ())), f"{name}.{field} x-values"
            inner = node.get("items", node)
            rows += [ref["$ref"].rsplit("/", 1)[1] for ref in [inner, *inner.get("allOf", [])] if "$ref" in ref]
    assert {"FsrsMemoryState", "NoteField", "ModelField", "ModelTemplate"} <= seen


def test_review_rows_and_inserts_use_the_row_names(spec):
    names = {"card_id", "interval", "last_interval", "time_ms"}
    assert names <= set(spec["components"]["schemas"]["ReviewInfo"]["properties"])
    assert not {"cid", "ivl", "lastIvl", "time"} & set(spec["components"]["schemas"]["ReviewInfo"]["properties"])


def test_no_schema_shows_an_alias(spec):
    aliases = {f.alias for m in _models(BaseModel) if m.__module__.startswith("tsunagi.")
               for f in m.__fields__.values() if f.alias != f.name}
    fields = {f.name for m in _models(BaseModel) if m.__module__.startswith("tsunagi.")
              for f in m.__fields__.values()}
    shown = {(name, key) for name, s in spec["components"]["schemas"].items()
             for key in s.get("properties", {}) if key in aliases - fields}
    assert not shown


def _models(cls):
    for sub in cls.__subclasses__():
        yield sub
        yield from _models(sub)


# 6.103: what the API description didn't say, found by the TypeScript client.
@pytest.mark.parametrize("path", [*LISTS, "/v1/reviews"])
def test_search_is_documented_exactly_where_it_works(spec, client, path):
    documented = any(p["name"] == "search" for p in spec["paths"][path]["get"]["parameters"])
    answer = client.get(path, params={"search": "x"})
    assert (answer.status_code == 400) == (not documented), answer.text


def test_every_write_documents_its_idempotency_key(spec):
    missing = [f"{method.upper()} {path}" for path, item in spec["paths"].items() for method, operation in item.items()
               if method in {"post", "put", "patch", "delete"} and not path.endswith("/query")
               and not any(p["name"] == "Idempotency-Key" for p in operation.get("parameters", []))]
    assert not missing


# The answers a client decodes: a field that can be null says so, and coded
# strings list their values.
MESSAGES = ["NoteCreated", "NoteCreateFailure", "NoteUpsertFailure", "NoteUpdated", "NoteCheckResult",
            "AttachmentRef", "MediaCreated", "MediaCreateFailure", "CapabilityState", "OperationCapability",
            "CollectionHealth", "CallerInfo", "Versions", "SyncResult", "VerbResult", "JobInfo", "JobSubmitted"]
CODED_STRINGS = {"NoteCreateFailure": "code", "NoteUpsertFailure": "code", "MediaCreateFailure": "code",
         "NoteCheckResult": "state", "CollectionHealth": "state", "CapabilityState": "status", "CallerInfo": "key",
                 "JobInfo": "status", "JobSubmitted": "status"}


@pytest.mark.parametrize("name", MESSAGES)
def test_answers_say_what_can_be_null_and_list_coded_values(spec, name):
    model = next(m for m in _models(BaseModel) if m.__name__ == name and m.__module__.startswith("tsunagi."))
    properties = spec["components"]["schemas"][name]["properties"]
    for field in model.__fields__.values():
        assert properties[field.name].get("x-nullable", False) == field.allow_none, f"{name}.{field.name}"
    if name in CODED_STRINGS:
        assert properties[CODED_STRINGS[name]].get("enum"), f"{name}.{CODED_STRINGS[name]}"
