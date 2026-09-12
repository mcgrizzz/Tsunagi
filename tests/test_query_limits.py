"""Large explicit pages, bounded defaults, and consistent GET/POST discovery."""
import pytest


@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize("limit", [0, -1])
def test_query_limit_still_requires_positive_value(client, method, limit):
    response = (client.get("/v1/cards", params={"limit": limit}) if method == "GET" else
                client.post("/v1/cards/query", json={"limit": limit}))
    assert response.status_code == 422


def test_query_limit_discovery_keeps_default_without_maximum(client):
    schema = client.get("/openapi.json").json()
    limits = [schema["components"]["schemas"]["QueryRequest"]["properties"]["limit"]]
    for path in ("/v1/cards", "/v1/notes", "/v1/models", "/v1/decks", "/v1/reviews", "/v1/media"):
        limits.append(next(p["schema"] for p in schema["paths"][path]["get"]["parameters"]
                           if p["name"] == "limit"))
    for limit in limits:
        assert limit["default"] == 1000
        assert limit["minimum"] == 1
        assert "maximum" not in limit


def test_large_media_page_keeps_cursor_and_default(client, monkeypatch):
    from tsunagi.http.v1 import media
    files = [(f"file-{index:05}.png", 12, 0) for index in range(6002)]
    monkeypatch.setattr(media, "list_media", lambda: files)
    default = client.get("/v1/media").json()
    assert len(default["items"]) == 1000
    assert default["next_cursor"]

    response = client.get("/v1/media", params={"limit": 6001})
    assert response.status_code == 200
    page = response.json()
    assert [item["filename"] for item in page["items"]] == [f[0] for f in files[:6001]]
    last = client.get("/v1/media", params={"limit": 6001, "cursor": page["next_cursor"]}).json()
    assert [item["filename"] for item in last["items"]] == [files[-1][0]]
    assert last["next_cursor"] is None
