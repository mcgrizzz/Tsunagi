"""
Canonical AnkiConnect error strings. Clients string-match on these - never
reword them. Verified against AnkiConnect's source.
"""

API_KEY_ERROR = "valid api key must be provided"
UNSUPPORTED_ACTION = "unsupported action"
MODEL_NOT_FOUND = "model was not found: {}"
DECK_NOT_FOUND = "deck was not found: {}"
FIELD_NOT_FOUND = "field was not found in {}: {}"
TEMPLATE_NOT_FOUND = "template was not found in {}: {}"

# createModel. Note ours differs from the native /v1 message, which names the
# model - canonical's is bare and clients may match on it.
MODEL_NAME_EXISTS = "Model name already exists"
CREATE_MODEL_NO_FIELDS = "Must provide at least one field for inOrderFields"
CREATE_MODEL_NO_TEMPLATES = "Must provide at least one card for cardTemplates"

# Model field setters reject wrong types rather than coercing
FONT_NOT_STRING = "font should be a string: {}"
FONT_SIZE_NOT_INT = "fontSize should be an integer: {}"
DESCRIPTION_NOT_STRING = "description should be a string: {}"

# updateNote / updateNoteTags
NOTE_UPDATE_NO_INPUT = 'Must provide a "fields" or "tags" property.'
TAGS_MUST_BE_LIST = "Must provide tags as a list of strings"
NOTE_NOT_FOUND = "Note was not found: {}"
CARD_NOT_FOUND = "Card was not found: {}"

# deleteDecks refuses without cardsToo - the wording is canonical's
DECKS_NEED_CARDS_TOO = ("Since Anki 2.1.28 it's not possible "
                        "to delete decks without deleting cards as well")

# createNote outcomes
NOTE_EMPTY = "cannot create note because it is empty"
# Yomitan's "already added" badge substring-matches this exact string
NOTE_DUPLICATE = "cannot create note because it is a duplicate"
NOTE_UNKNOWN_REASON = "cannot create note for unknown reason"
EMPTY_QUESTION = "The field values you have provided would make an empty question on all cards."

# Note option validation (canonical rejects non-bools rather than coercing)
OPTION_ALLOW_DUPLICATE_BOOL = 'option parameter "allowDuplicate" must be boolean'
OPTION_CHECK_CHILDREN_BOOL = 'option parameter "duplicateScopeOptions.checkChildren" must be boolean'
OPTION_CHECK_ALL_MODELS_BOOL = 'option parameter "duplicateScopeOptions.checkAllModels" must be boolean'

# notesInfo
NOTES_INFO_NO_INPUT = 'Must provide either "notes" or a "query"'

# media
MEDIA_NO_SOURCE = 'You must provide a "data", "path", or "url" field.'
MEDIA_DOWNLOAD_FAILED = "{} download failed with return code {}"

# Our safe generic for unexpected exceptions. Deliberate divergence:
# AnkiConnect returns str(e) (leaking internals); we log server-side instead.
ACTION_FAILED = "Action failed"
