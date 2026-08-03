"""
Canonical AnkiConnect error strings. Clients string-match on these - never
reword them. Verified against AnkiConnect's source.
"""

API_KEY_ERROR = "valid api key must be provided"
UNSUPPORTED_ACTION = "unsupported action"
MODEL_NOT_FOUND = "model was not found: {}"

# Our safe generic for unexpected exceptions. Deliberate divergence:
# AnkiConnect returns str(e) (leaking internals); we log server-side instead.
ACTION_FAILED = "Action failed"
