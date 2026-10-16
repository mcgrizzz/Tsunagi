"""Catalog entries first sent by LinguaCafe (https://github.com/simjanos-dev/LinguaCafe at c1ea298):
its requests that no other entry covers (tests/clients/linguacafe/client.py)."""


from dataclasses import replace

from clients.support import case, named

EVERYTHING = ("",)

def create_model(language):
    """AnkiApiService.php createAnkiDeckAndModel L54-69."""
    name = f"LinguaCafe{language}"
    return case(f"createModel {name}", "createModel", {
        "css": ".card {display: block;margin-left: auto;margin-right: auto;font-family: arial;"
               "font-size: 20px;text-align: center;color: black;max-width: 600px;border: 1px solid;"
               "border-radius: 8px;padding: 16px;}",
        "modelName": name,
        "inOrderFields": ["word", "reading", "translation", "example_sentence"],
        "cardTemplates": [{
            "Name": name,
            "Front": "<ruby>{{word}}<rt>{{reading}}</rt></ruby><hr>{{example_sentence}}",
            "Back": "<ruby>{{word}}<rt>{{reading}}</rt></ruby><hr>{{example_sentence}}<hr>{{translation}}",
        }]}, reads=EVERYTHING)

def create_deck(language):
    """L71-77."""
    return case(f"createDeck LinguaCafe::{language}", "createDeck", {"deck": f"LinguaCafe::{language}"},
                reads=EVERYTHING)

def insert(language, word, reading, translation, sentence):
    """insertNote L113-137: no tags."""
    deck = f"LinguaCafe::{language}"
    return case("addNote", "addNote", {"note": {
        "deckName": deck, "modelName": f"LinguaCafe{language}",
        "fields": {"word": word, "reading": reading, "translation": translation, "example_sentence": sentence},
        "options": {"allowDuplicate": False, "duplicateScope": "deck",
                    "duplicateScopeOptions": {"deckName": deck, "checkChildren": False, "checkAllModels": False}},
    }}, reads=EVERYTHING)

JA = ("Japanese", "猫", "ねこ", "cat", "猫がいる。")

DE = ("German", "hund", "", "dog", "Der Hund schläft.")

def entry(name, first, *then):
    """addWord's requests in order, the collection's changes compared."""
    return replace(first, name=name, effects=True, then=then)


ENTRIES = named("LinguaCafe", [
    # addWord L22-48: the first word of a language: no note type, then it and the deck are made.
    entry("addWord, first word of a language", insert(*JA), create_model("Japanese"),
          create_deck("Japanese"), insert(*JA)),
    # The note type is there, its deck isn't: 'Model name already exists' is let through.
    entry("addWord, deck missing", create_model("German"), insert(*DE), create_model("German"),
          create_deck("German"), insert(*DE)),
    # A word added again (L151-159, updateNote L179-241): the note found and its other fields updated.
    entry("addWord again, update", create_model("German"), create_deck("German"), insert(*DE),
          insert("German", "hund", "", "dog, hound", "Der Hund bellt."),
          case("findNotes", "findNotes", {"query": "deck:LinguaCafe::German word:hund"}, reads=EVERYTHING),
          case("updateNoteFields", "updateNoteFields", lambda c: {"note": {
              "id": c["answer"]["result"][0],
              "fields": {"reading": "", "translation": "dog, hound", "example_sentence": "Der Hund bellt."}}},
              reads=EVERYTHING)),
])
