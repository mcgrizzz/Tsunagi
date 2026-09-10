"""Reviewer compatibility regressions using disposable cards and a fake UI."""
from types import SimpleNamespace

import pytest


def rpc(client, action, **params):
    return client.post('/', json={'action': action, 'version': 6, 'params': params}).json()


@pytest.fixture()
def reviewer(monkeypatch, col):
    import aqt

    note = col.new_note(col.models.by_name('Basic'))
    note['Front'], note['Back'] = 'question', 'answer'
    col.add_note(note, col.decks.id('Default'))
    card = note.cards()[0]
    events = []
    review = SimpleNamespace(
        card=card, state='answer', mw=aqt.mw,
        _answerButtonList=lambda: [(1, 'Again'), (3, 'Good')],
        _answerCard=lambda ease: events.append(('answer', ease)),
        _showQuestion=lambda: events.append('question'),
        _showAnswer=lambda: events.append('show_answer'),
        replayAudio=lambda: events.append('audio'),
    )
    monkeypatch.setattr(aqt.mw, 'reviewer', review, raising=False)
    monkeypatch.setattr(aqt.mw, 'state', 'review', raising=False)
    review.events = events
    return review


def test_current_card_intervals_follow_reviewer_buttons(client, col, reviewer, monkeypatch):
    calls = []
    def interval(card, ease, short):
        calls.append((card, ease, short))
        return f'button {ease}'
    monkeypatch.setattr(col.sched, 'nextIvlStr', interval)
    reply = rpc(client, 'guiCurrentCard')
    assert reply['error'] is None
    assert reply['result']['buttons'] == [1, 3]
    assert reply['result']['nextReviews'] == ['button 1', 'button 3']
    assert calls == [(reviewer.card, 1, True), (reviewer.card, 3, True)]
    assert reply['result']['fields']['Front']['value'] == 'question'
    assert reply['result']['question'] == reviewer.card.question()
    assert reply['result']['answer'] == reviewer.card.answer()


def test_current_card_keeps_interval_error(client, col, reviewer, monkeypatch):
    def fail(*args):
        raise RuntimeError('interval lookup failed')
    monkeypatch.setattr(col.sched, 'nextIvlStr', fail)
    assert rpc(client, 'guiCurrentCard') == {'result': None, 'error': 'interval lookup failed'}


@pytest.mark.parametrize('ease', ['3', None, [], 1.5, True])
@pytest.mark.parametrize('state', ['inactive', 'question'])
def test_answer_checks_review_state_before_rating(client, reviewer, monkeypatch, ease, state):
    import aqt
    if state == 'inactive':
        monkeypatch.setattr(aqt.mw, 'state', 'deckBrowser')
    else:
        reviewer.state = 'question'
    assert rpc(client, 'guiAnswerCard', ease=ease) == {'result': False, 'error': None}
    assert reviewer.events == []


@pytest.mark.parametrize('ease', ['3', None, []])
def test_answer_preserves_rating_type_error(client, reviewer, ease):
    with pytest.raises(TypeError) as expected:
        _ = ease <= 0
    assert rpc(client, 'guiAnswerCard', ease=ease) == {'result': None, 'error': str(expected.value)}
    assert reviewer.events == []


@pytest.mark.parametrize('ease', [1.5, True])
def test_answer_passes_raw_rating_to_reviewer(client, reviewer, ease):
    assert rpc(client, 'guiAnswerCard', ease=ease) == {'result': True, 'error': None}
    assert reviewer.events == [('answer', ease)]
    assert type(reviewer.events[0][1]) is type(ease)


@pytest.mark.parametrize('action,method,params', [
    ('guiShowQuestion', '_showQuestion', {}),
    ('guiShowAnswer', '_showAnswer', {}),
    ('guiPlayAudio', 'replayAudio', {}),
    ('guiAnswerCard', '_answerCard', {'ease': 3}),
])
def test_reviewer_callback_error_is_preserved(client, reviewer, monkeypatch, action, method, params):
    def fail(*args):
        raise RuntimeError('reviewer callback failed')
    monkeypatch.setattr(reviewer, method, fail)
    assert rpc(client, action, **params) == {'result': None, 'error': 'reviewer callback failed'}


def test_native_current_card_keeps_backend_interval_source(col, reviewer, monkeypatch):
    from tsunagi.adapters.anki import cards, gui
    monkeypatch.setattr(cards, '_next_reviews', lambda collection, cid: ['native intervals'])
    assert gui.current_card()['nextReviews'] == ['native intervals']
