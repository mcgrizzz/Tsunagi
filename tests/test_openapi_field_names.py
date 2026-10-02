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
