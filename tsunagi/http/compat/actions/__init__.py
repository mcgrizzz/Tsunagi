# Explicit side-effect imports: each module registers its handlers on the
# shared registry at import time. Add new action modules here.
from . import decks, gui, media, misc, models, notes  # noqa: F401
