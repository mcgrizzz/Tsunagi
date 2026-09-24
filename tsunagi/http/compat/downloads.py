"""AnkiConnect download status/errors, with Tsunagi's configured resource limits."""

from ...adapters.settings import settings
from .errors import MEDIA_DOWNLOAD_FAILED


def download_media(url: str) -> bytes:
    from anki.httpclient import HttpClient

    client = HttpClient()
    client.timeout = float(settings.get("media_fetch_timeout_seconds", 30))
    limit = int(settings.get("media_max_bytes", 67108864))
    try:
        response = client.get(url)
        try:
            # Upstream accepts only 200, including after redirects. Other 2xx
            # replies must fail before the caller deletes or writes any media.
            if response.status_code != 200:
                raise ValueError(MEDIA_DOWNLOAD_FAILED.format(url, response.status_code))
            declared = response.headers.get("Content-Length")
            if declared and int(declared) > limit:
                raise ValueError(f"file exceeds media_max_bytes ({limit})")
            chunks, total = [], 0
            for chunk in response.iter_content(chunk_size=65536):
                total += len(chunk)
                if total > limit:
                    raise ValueError(f"file exceeds media_max_bytes ({limit})")
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            response.close()
    except Exception as exc:
        # Requests' transport diagnostics belong in the RPC envelope (or the
        # note's escaped media error), not the dispatcher's generic failure.
        raise ValueError(str(exc)) from exc
