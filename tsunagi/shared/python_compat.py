"""Compatibility with the oldest supported Python runtime (3.9)."""

import sys

# Python 3.9's dataclass decorator does not accept the slots keyword at all.
# Keep compact query nodes on newer runtimes without changing their fields.
DATACLASS_SLOTS = {"slots": True} if sys.version_info >= (3, 10) else {}
