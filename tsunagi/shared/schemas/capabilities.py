"""Native discovery with effective operation and option status."""
from typing import Dict, Literal, Optional

from pydantic import BaseModel, Field

from ..version import ADDON_VERSION, API_VERSION


class Versions(BaseModel):
    api: str = Field(API_VERSION, description="Native API contract identifier")
    addon: str = Field(ADDON_VERSION, description="Tsunagi release version")
    anki: str = Field(description="Running Anki version")


class CapabilityState(BaseModel):
    status: Literal["available", "disabled", "unsupported"] = Field(
        "available", description="Effective support after checking the running Anki and settings; request validation still applies")
    reason: Optional[str] = None
    setting: Optional[str] = Field(None, description="Setting controlling this capability, when applicable")


class OperationCapability(CapabilityState):
    operation_id: str
    options: Dict[str, CapabilityState] = Field(
        default_factory=dict, description="Options with settings or version restrictions; other inputs follow the operation schema")


class CallerInfo(BaseModel):
    name: str = Field(description="The app the key belongs to, or the No key row the request fell in")
    role: str = Field(description="The role's display name")
    this_computer: bool = Field(description="Counted as this computer: loopback peer and loopback Host")
    host: str = Field(description="The Host header as Tsunagi received it (useful behind a proxy)")


class Capabilities(BaseModel):
    versions: Versions
    caller: CallerInfo = Field(description="Who Tsunagi took this request to be; statuses below are for this caller")
    operations: Dict[str, OperationCapability] = Field(description="All native operations, keyed by METHOD /path")
    features: Dict[str, CapabilityState] = Field(description="Collection features that are not individual HTTP operations")
    stats: Dict[str, float] = Field(default_factory=dict)


def runtime_versions() -> Versions:
    from anki.buildinfo import version

    return Versions(anki=version)
