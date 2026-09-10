"""Native pagination rejects invalid tokens consistently across query plans."""
import pytest

from tsunagi.shared.pagination import encode_cursor

BAD_CURSORS = ['', '!!!bad-base64!!!', encode_cursor({'last_key': '42'})]


def query_path(client, resource):
    operation = 'query' + resource.title()
    paths = client.get('/openapi.json').json()['paths']
    return next(path for path, methods in paths.items()
                if methods.get('post', {}).get('operationId') == operation)


@pytest.mark.parametrize('resource', ['notes', 'cards', 'reviews', 'models', 'decks'])
@pytest.mark.parametrize('cursor', BAD_CURSORS)
@pytest.mark.parametrize('method', ['get', 'post'])
def test_invalid_native_cursor_returns_400(client, resource, cursor, method):
    params = {'cursor': cursor, 'limit': 1}
    if method == 'get':
        response = client.get(f'/v1/{resource}', params=params)
    else:
        response = client.post(query_path(client, resource), json=params)
    assert response.status_code == 400, response.text
    assert response.json()['detail'].startswith('Invalid pagination cursor.')


@pytest.mark.parametrize('cursor', ['', 'garbage', encode_cursor({}), encode_cursor({'last_key': 1})])
def test_invalid_media_cursor_returns_400(client, cursor):
    response = client.get('/v1/media', params={'cursor': cursor})
    assert response.status_code == 400, response.text
    assert response.json()['detail'].startswith('Invalid pagination cursor.')


def test_returned_cursor_walks_between_get_and_post(client, col):
    for index in range(3):
        note = col.new_note(col.models.by_name('Basic'))
        note['Front'] = f'cursor contract {index}'
        col.add_note(note, col.decks.id('Default'))
    params = {'limit': 1, 'search': '"cursor contract"', 'select': 'id', 'shape': 'scalar'}
    first = client.get('/v1/notes', params=params).json()
    path = query_path(client, 'notes')
    second_response = client.post(path, json={**params, 'cursor': first['next_cursor']})
    assert second_response.status_code == 200, second_response.text
    second = second_response.json()
    third = client.get('/v1/notes', params={**params, 'cursor': second['next_cursor']}).json()
    assert len(set(first['items'] + second['items'] + third['items'])) == 3
    assert third['next_cursor'] is None
    restarted = client.post(path, json={**params, 'cursor': None}).json()
    assert restarted['items'] == first['items']


def test_media_cursor_round_trip_with_unicode(client, col):
    for name in ('cursor-かな.txt', 'cursor-日本語.txt'):
        col.media.write_data(name, b'cursor fixture')
    first = client.get('/v1/media', params={'prefix': 'cursor-', 'limit': 1}).json()
    assert first['next_cursor'] is not None
    second_response = client.get('/v1/media', params={
        'prefix': 'cursor-', 'limit': 1, 'cursor': first['next_cursor']})
    assert second_response.status_code == 200, second_response.text
    second = second_response.json()
    assert {row['filename'] for row in first['items'] + second['items']} == {'cursor-かな.txt', 'cursor-日本語.txt'}
    assert second['next_cursor'] is None
