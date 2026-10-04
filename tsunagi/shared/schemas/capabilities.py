"""Native discovery with effective operation and option status."""
from typing import Dict, Literal, Optional

from pydantic import BaseModel, Field

from ..version import ADDON_VERSION, API_VERSION
from .wrappers import NULLABLE


class Versions(BaseModel):
    api: str = Field(API_VERSION, description="Native API contract identifier")
    addon: str = Field(ADDON_VERSION, description="Tsunagi release version")
    anki: str = Field(description="Running Anki version")


class CapabilityState(BaseModel):
    status: Literal["available", "disabled", "unsupported"] = Field(
        "available", description="Effective support after checking the running Anki and settings; request validation still applies")
    reason: Optional[str] = Field(None, description="Why it is disabled or unsupported, or what limits it; null when nothing does", **NULLABLE)
    setting: Optional[str] = Field(None, description="Setting controlling this capability; null when none does", **NULLABLE)


class OperationCapability(CapabilityState):
    operation_id: str
    options: Dict[str, CapabilityState] = Field(
        default_factory=dict, description="Options with settings or version restrictions; other inputs follow the operation schema")


class CallerInfo(BaseModel):
    """Who a request counts as: the same in health and capabilities (6.86)."""
    name: str = Field(description=(
        "The app the request's key belongs to, or the No key row it counts as (no key, or "
        "a key that matches no app)"))
    role: str = Field(description="The role that applies, by its display name")
    enabled: bool = Field(description="False for an app turned off in settings: it is granted nothing")
    key: Literal["valid", "unknown", "none"] = Field(description=(
        "valid: the key belongs to `name`. unknown: a key was sent but matches no app, so it "
        "counts as no key. none: no key was sent"))
    this_computer: bool = Field(description="Counted as this computer: loopback peer and loopback Host")
    host: str = Field(description="The Host header as Tsunagi received it (useful behind a proxy)")

    @classmethod
    def of(cls, who, sent_key, host: str) -> "CallerInfo":
        """From the resolved caller and the key the request carried, if any."""
        return cls(name=who.name, role=who.role_name, enabled=who.enabled,
                   key="none" if not sent_key else "valid" if who.key is not None else "unknown",
                   this_computer=who.local, host=host)


class Capabilities(BaseModel):
    versions: Versions
    caller: CallerInfo = Field(description="Who Tsunagi took this request to be; statuses below are for this caller")
    operations: Dict[str, OperationCapability] = Field(description="All native operations, keyed by METHOD /path")
    features: Dict[str, CapabilityState] = Field(description="Collection features that are not individual HTTP operations")
    stats: Dict[str, float] = Field(default_factory=dict)


def runtime_versions() -> Versions:
    from anki.buildinfo import version

    return Versions(anki=version)
