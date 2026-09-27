"""Add-on action providers shipped with Tsunagi (backlog 2b-P), registered on
import through the same `provide` other add-ons use."""
from ..addon_actions import Registry
from . import fsrs_helper

fsrs_helper.provide(Registry(bundled=True))
