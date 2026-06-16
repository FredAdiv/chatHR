"""Safe HTTP fetch skeleton for document ingestion.

Limits:
- Max response size: 20 MB (documented)
- Max redirects: 5
- Timeout: 30 seconds
- No credentials sent
- Does not fetch private/internal addresses (caller must validate URL first)
"""
from dataclasses import dataclass

import httpx

MAX_BYTES = 20 * 1024 * 1024  # 20 MB — documented ingestion limit
_MAX_REDIRECTS = 5
_TIMEOUT = 30.0


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
    - No credentials or auth headers are sent.
    - Response body is read up to MAX_BYTES (20 MB); larger responses return an error.
    - Up to 5 redirects are followed.
    - Caller must validate the URL (scheme and host) before calling this function.
    """
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            max_redirects=_MAX_REDIRECTS,
            timeout=_TIMEOUT,
        ) as client:
            async with client.stream("GET", url) as response:
                headers = response.headers
                content_type = headers.get("content-type")
                etag = headers.get("etag")
                last_modified = headers.get("last-modified")

                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes(chunk_size=65_536):
                    total += len(chunk)
                    if total > MAX_BYTES:
                        return FetchResult(
                            url=url,
                            status_code=response.status_code,
                            content_type=content_type,
                            etag=etag,
                            last_modified=last_modified,
                            content=None,
                            error=f"Response exceeded maximum allowed size of {MAX_BYTES} bytes",
                        )
                    chunks.append(chunk)

                return FetchResult(
                    url=url,
                    status_code=response.status_code,
                    content_type=content_type,
                    etag=etag,
                    last_modified=last_modified,
                    content=b"".join(chunks),
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
