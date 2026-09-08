"""Runtime discovery; backend support is separate from collection settings."""
from typing import Dict, List

from pydantic import BaseModel, Field

from ..version import ADDON_VERSION, API_VERSION


class Versions(BaseModel):
    api: str = Field(API_VERSION, description="Native API contract identifier")
    addon: str = Field(ADDON_VERSION, description="Tsunagi release version")
    anki: str = Field(description="Running Anki version")


class OperationCapability(BaseModel):
    available: bool = Field(description="The backend supports this operation; inputs still require validation")
    unsupported_options: List[str] = Field(default_factory=list)


class FsrsCapabilities(BaseModel):
    supported: bool = Field(description="The backend exposes FSRS computations")
    enabled: bool = Field(description="The open collection has FSRS scheduling enabled")
    operations: Dict[str, OperationCapability]


class Capabilities(BaseModel):
    versions: Versions
    fsrs: FsrsCapabilities
    stats: Dict[str, float] = Field(default_factory=dict)


def runtime_versions() -> Versions:
    from anki.buildinfo import version

    return Versions(anki=version)
