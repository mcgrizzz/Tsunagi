"""
A website asking for access (6.26): Anki shows the same prompt as AnkiConnect's
requestPermission, and an allowed website is added to Allowed websites. Reachable
without a key and from a website not yet allowed (http/middleware.py).
"""
from fastapi import APIRouter, Request

from ...adapters.settings import settings
from ...shared.permissions import PUBLIC, requires
from ...shared.schemas.capabilities import PermissionRequestResult
from ..compat.ankiconnect import request_permission
from ..middleware import is_local_request

router = APIRouter()


@router.post(
    "/v1/permissions:request",
    openapi_extra=requires(PUBLIC),
    response_model=PermissionRequestResult,
    summary="Ask for access from a website",
    description=(
        "For a website (a request with an Origin header) that isn't in Allowed websites yet. "
        "Anki asks you whether to allow it, and the answer comes back when you choose, or as "
        "denied after two minutes. An allowed website is answered at once, without asking; "
        "so is a request with no Origin (not a website). A website you asked Anki to ignore "
        "is denied without asking. Needs no key and no permission; `key_required` says "
        "whether the website's other requests will need an app's key."
    ),
    tags=["Collection"],
    operation_id="requestPermission",
)
def request_access(request: Request) -> PermissionRequestResult:
    # Blocking on purpose (FastAPI runs it in a worker thread): the answer is the prompt's.
    local = is_local_request(request.scope)
    answer = request_permission(request.headers.get("origin"), settings, None, local=local)
    return PermissionRequestResult(
        permission=answer["permission"],
        key_required=not settings.resolve_caller(None, local).grants)
