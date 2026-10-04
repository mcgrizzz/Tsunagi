"""The sorts the API description lists are the ones this Anki has (6.101).

CI runs this on the newest Anki and the oldest supported one, so a release that
adds or drops a Browser sort fails here before clients are told the wrong list."""
from tsunagi.adapters.anki import sorting


def test_the_documented_sorts_are_this_ankis(col):
    assert sorted(sorting._sorts(col, False)) == sorted(sorting.CARD_SORTS)
    assert sorted(sorting._sorts(col, True)) == sorted(sorting.NOTE_SORTS)


def test_the_api_description_lists_them(client):
    paths = client.get("/openapi.json").json()["paths"]
    def sorts(path):
        order = next(p for p in paths[path]["get"]["parameters"] if p.get("name") == "order")
        return order["schema"]["x-sorts"]
    assert sorts("/v1/cards") == list(sorting.CARD_SORTS)
    assert sorts("/v1/notes") == list(sorting.NOTE_SORTS)
    assert "time_ms" in sorts("/v1/reviews") and "name" in sorts("/v1/decks")
