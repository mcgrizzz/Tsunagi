"""Native discovery with effective operation and option status."""
from typing import Dict, Literal, Optional

from pydantic import BaseModel, Field

from ..version import ADDON_VERSION, API_VERSION
from .wrappers import NULLABLE, RequestBody


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


class AccessRequest(RequestBody):
    """What a website or program may suggest when it asks for access (6.124); you decide."""
    name: Optional[str] = Field(None, description=(
        "The name for its app in Apps & keys. A website's default is its host; a program's is "
        "shown as the name it gives itself, which Tsunagi can't check."))
    role: Optional[str] = Field(None, description=(
        "The role to preselect in the prompt, by id or name (`read_only`, `Read-only`); "
        "Default otherwise."))


class PermissionRequestResult(BaseModel):
    """The answer to an access request (6.26, 6.124)."""
    permission: Literal["granted", "denied"] = Field(description=(
        "granted: you allowed it; denied: you didn't, it's on a list to ignore, or no one "
        "answered in two minutes."))
    key: Optional[str] = Field(None, description=(
        "Its app's key, sent this once: keep it and send it as X-Api-Key. Null when denied."),
        **NULLABLE)
    app: Optional[str] = Field(None, description="Its app's name in Apps & keys. Null when denied.",
                               **NULLABLE)
    role: Optional[str] = Field(None, description="The role you gave it, by name. Null when denied.",
                                **NULLABLE)
    key_required: bool = Field(description=(
        "Whether a request without a key has No access here (the \"No key, this computer\" row)."))
