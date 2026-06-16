"""Document type detection by URL extension and/or HTTP Content-Type."""
import os
from urllib.parse import urlparse

_EXT_MAP: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".doc": "docx",
    ".xlsx": "xlsx",
    ".xls": "xlsx",
    ".htm": "html",
    ".html": "html",
}

_CONTENT_TYPE_MAP: dict[str, str] = {
    "text/html": "html",
    "application/xhtml+xml": "html",
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/msword": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.ms-excel": "xlsx",
}


def detect_document_type(url: str, content_type: str | None = None) -> str:
    """
    Return document type: 'html', 'pdf', 'docx', 'xlsx', or 'unknown'.
    Content-Type header takes precedence over URL extension.
    """
    if content_type:
        ct = content_type.split(";")[0].strip().lower()
        if ct in _CONTENT_TYPE_MAP:
            return _CONTENT_TYPE_MAP[ct]

    path = urlparse(url).path
    ext = os.path.splitext(path)[1].lower()
    return _EXT_MAP.get(ext, "unknown")
