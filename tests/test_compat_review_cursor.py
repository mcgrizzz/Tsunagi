"""cardReviews binds raw cutoffs while native review reads keep integer inputs."""
import pytest


@pytest.fixture()
def review_rows(col):
    note = col.new_note(col.models.by_name('Basic'))
    note['Front'] = 'review cutoff'
    col.add_note(note, col.decks.id('Default'))
    cid = note.cards()[0].id
    rows = [[rid, cid, -1, 3, 1, 0, 2500, 1000, 1] for rid in (100, 101, 102)]
    col.db.executemany('insert into revlog values (?,?,?,?,?,?,?,?,?)', rows)
    return rows


def rpc(client, **params):
    return client.post('/', json={'action': 'cardReviews', 'version': 6, 'params': params}).json()


@pytest.mark.parametrize('cutoff,ids', [
    (None, []), ('100', [101, 102]), ('1e2', [101, 102]),
    ('not numeric', []), ('0 OR 1=1', []), (100.5, [101, 102]),
    ([], []),
])
def test_card_reviews_binds_cutoff_without_coercion(client, review_rows, cutoff, ids):
    response = rpc(client, deck='Default', startID=cutoff)
    assert response['error'] is None
    assert [row[0] for row in response['result']] == ids


@pytest.mark.parametrize('cutoff', [False, True, {}, 2**100])
def test_card_reviews_preserves_binding_error_after_deck_lookup(client, col, cutoff):
    with pytest.raises(Exception) as expected:
        col.db.all('select id from revlog where id > ?', cutoff)
    response = rpc(client, deck='Cutoff-created deck', startID=cutoff)
    assert response == {'result': None, 'error': str(expected.value)}
    assert col.decks.by_name('Cutoff-created deck') is not None


def test_card_reviews_requires_cutoff(client):
    response = rpc(client, deck='Default')
    assert response['result'] is None
    assert 'startID' in response['error']


def test_native_review_reader_keeps_integer_conversion(review_rows):
    from tsunagi.adapters.anki.reviews import reviews_of_deck
    assert [row[0] for row in reviews_of_deck('Default', '100')] == [101, 102]
    with pytest.raises(ValueError):
        reviews_of_deck('Default', '1e2')
