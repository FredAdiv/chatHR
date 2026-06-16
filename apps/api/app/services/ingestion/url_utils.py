"""URL validation and normalization for ingestion."""
import re
from urllib.parse import urlparse

# RFC 1918 / loopback patterns — never ingest private/internal addresses
_PRIVATE_HOST_PATTERNS = [
    re.compile(r"^localhost$", re.IGNORECASE),
    re.compile(r"^127\."),
    re.compile(r"^10\."),
    re.compile(r"^172\.(1[6-9]|2[0-9]|3[01])\."),
    re.compile(r"^192\.168\."),
    re.compile(r"^::1$"),
    re.compile(r"^0\.0\.0\.0$"),
]

_ALLOWED_SCHEMES = {"http", "https"}


def validate_url(url: str) -> str:
    """
    Validate and normalize a URL for safe ingestion.
    Returns normalized URL or raises ValueError.
    Rejects: non-http/https schemes, private/localhost addresses, empty URLs.
    """
    url = url.strip()
    if not url:
        raise ValueError("URL must not be empty")

    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ValueError(
            f"URL scheme '{parsed.scheme}' is not allowed. Only http and https are permitted."
        )

    host = parsed.hostname or ""
    if not host:
        raise ValueError("URL must include a hostname")

    for pattern in _PRIVATE_HOST_PATTERNS:
        if pattern.match(host):
            raise ValueError(
                f"Private or localhost addresses are not allowed for ingestion: '{host}'"
            )

    return url
