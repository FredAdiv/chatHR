"""Safe HTTP fetch for document ingestion.

Limits:
- Max response size: 20 MB (documented)
- Max redirects: 5, followed manually with URL re-validation (SSRF protection)
- Timeout: 30 seconds
- No credentials sent
- Each redirect target is validated against URL safety rules before following,
  preventing SSRF via open redirect from a public URL to a private/internal address.
"""
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx

from app.services.ingestion.url_utils import validate_url

MAX_BYTES = 20 * 1024 * 1024  # 20 MB — documented ingestion limit
_MAX_REDIRECTS = 5
_TIMEOUT = 30.0

# Standard browser-like headers that reduce 403s from gov.il servers.
# These identify the tool honestly — no impersonation of real browsers.
# SSRF protections and redirect validation remain fully intact.
_DEFAULT_HEADERS = {
    "User-Agent": "ChatHR-MVP-LocalIndexer/0.1 (local dev tool; not a commercial crawler)",
    "Accept": "text/html,application/pdf,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.7,en;q=0.6",
}


@dataclass
class FetchResult:
    url: str
    status_code: int | None
    content_type: str | None
    etag: str | None
    last_modified: str | None
    content: bytes | None
    error: str | None


async def fetch_url(url: str) -> FetchResult:
    """
    Fetch a URL and return a FetchResult.
    - Redirects are followed manually: each redirect target is validated with validate_url()
      before following, preventing SSRF via open redirect to private/internal addresses.
    - Response body is buffered up to MAX_BYTES (20 MB); larger responses return an error.
    - Up to _MAX_REDIRECTS redirects are followed.
    - No credentials or auth headers are sent.
    - Caller must validate the initial URL before calling this function.
    """
    try:
        async with httpx.AsyncClient(
            follow_redirects=False,
            timeout=_TIMEOUT,
            headers=_DEFAULT_HEADERS,
        ) as client:
            current_url = url
            hops = 0

            while True:
                response = await client.get(current_url)

                if response.is_redirect:
                    if hops >= _MAX_REDIRECTS:
                        return FetchResult(
                            url=url,
                            status_code=response.status_code,
                            content_type=None,
                            etag=None,
                            last_modified=None,
                            content=None,
                            error=f"Too many redirects (max {_MAX_REDIRECTS})",
                        )
                    hops += 1
                    location = response.headers.get("location", "")
                    next_url = urljoin(current_url, location)
                    try:
                        validate_url(next_url)
                    except ValueError as exc:
                        return FetchResult(
                            url=url,
                            status_code=response.status_code,
                            content_type=None,
                            etag=None,
                            last_modified=None,
                            content=None,
                            error=f"Redirect to blocked target: {exc}",
                        )
                    current_url = next_url
                    continue

                # Final (non-redirect) response — buffer body with size check
                content = response.content
                if len(content) > MAX_BYTES:
                    return FetchResult(
                        url=url,
                        status_code=response.status_code,
                        content_type=response.headers.get("content-type"),
                        etag=response.headers.get("etag"),
                        last_modified=response.headers.get("last-modified"),
                        content=None,
                        error=f"Response exceeded maximum allowed size of {MAX_BYTES} bytes",
                    )
                return FetchResult(
                    url=url,
                    status_code=response.status_code,
                    content_type=response.headers.get("content-type"),
                    etag=response.headers.get("etag"),
                    last_modified=response.headers.get("last-modified"),
                    content=content,
                    error=None,
                )

    except Exception as exc:
        return FetchResult(
            url=url,
            status_code=None,
            content_type=None,
            etag=None,
            last_modified=None,
            content=None,
            error=str(exc),
        )
