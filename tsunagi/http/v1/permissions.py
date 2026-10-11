"""
Access requests (6.26, 6.124): a website or a program asks, Anki shows you
who it is, you choose a role, and if you allow it, it becomes an app in Apps &
keys and gets its key in the answer. Reachable without a key and from a
website not yet allowed (http/middleware.py). AnkiConnect's requestPermission
is separate: it never gives a key (http/compat/ankiconnect.py).
"""
from typing import Optional

from fastapi import APIRouter, Body, Request

from ...adapters.access_requests import AccessAsk, AccessDecision, request_access
from ...adapters.settings import settings
from ...shared.permissions import PUBLIC, requires
from ...shared.schemas.capabilities import AccessRequest, PermissionRequestResult
from ..middleware import is_local_request

router = APIRouter()


def _ask(request: AccessAsk) -> AccessDecision:
    from ...adapters.dialogs import ask_access_dialog
    return ask_access_dialog(request)


@router.post(
    "/v1/permissions:request",
    openapi_extra=requires(PUBLIC),
    response_model=PermissionRequestResult,
    summary="Ask for access",
    description=(
        "For a website or a program that has no key yet. Anki asks you whether to allow it and "
        "which role it gets; the answer comes when you choose, or as denied after two minutes. "
        "Allowed, it becomes an app in Apps & keys and the answer carries its key, this once: "
        "send it as X-Api-Key from then on. A website is told apart by its Origin, a program by "
        "the `name` it sends (Anki shows that it can't be checked). Asking again always asks "
        "you, and allowing gives the app a new key; the old one stops working. A website or "
        "program you asked Anki to ignore is denied without asking. Needs no key and no "
        "permission. AnkiConnect's requestPermission gives no key."
    ),
    tags=["Collection"],
    operation_id="requestPermission",
)
def request_access_route(request: Request,
                         body: Optional[AccessRequest] = Body(None)) -> PermissionRequestResult:
    # Blocking on purpose (FastAPI runs it in a worker thread): the answer is the prompt's.
    body = body or AccessRequest()
    local = is_local_request(request.scope)
    answer = request_access(settings, _ask, origin=request.headers.get("origin"), local=local,
                            address=request.client.host if request.client else None,
                            name=body.name, role=body.role)
    return PermissionRequestResult(**answer,
                                   key_required=not settings.resolve_caller(None, local).grants)
