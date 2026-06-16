"""Unit tests for ingestion helper modules: url_utils, hash_utils, document_type, downloader."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api"))

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── URL validation ─────────────────────────────────────────────────────────────

from app.services.ingestion.url_utils import validate_url


def test_url_valid_https_gov():
    assert validate_url("https://www.gov.il/he/departments") == "https://www.gov.il/he/departments"


def test_url_valid_http():
    assert validate_url("http://example.gov.il/page") == "http://example.gov.il/page"


def test_url_strips_whitespace():
    assert validate_url("  https://example.gov.il  ") == "https://example.gov.il"


def test_url_rejects_file_scheme():
    with pytest.raises(ValueError, match="not allowed"):
        validate_url("file:///etc/passwd")


def test_url_rejects_javascript_scheme():
    with pytest.raises(ValueError, match="not allowed"):
        validate_url("javascript:alert(1)")


def test_url_rejects_ftp_scheme():
    with pytest.raises(ValueError, match="not allowed"):
        validate_url("ftp://example.com/file.txt")


def test_url_rejects_data_scheme():
    with pytest.raises(ValueError, match="not allowed"):
        validate_url("data:text/html,<h1>hi</h1>")


def test_url_rejects_localhost():
    with pytest.raises(ValueError, match="not allowed"):
        validate_url("http://localhost/admin")


def test_url_rejects_127():
    with pytest.raises(ValueError, match="not allowed"):
        validate_url("http://127.0.0.1:8080/data")


def test_url_rejects_10_dot():
    with pytest.raises(ValueError, match="not allowed"):
        validate_url("http://10.0.0.1/internal")


def test_url_rejects_192_168():
    with pytest.raises(ValueError, match="not allowed"):
        validate_url("http://192.168.1.1/router")


def test_url_rejects_172_16():
    with pytest.raises(ValueError, match="not allowed"):
        validate_url("http://172.16.0.1/private")


def test_url_rejects_empty():
    with pytest.raises(ValueError):
        validate_url("")


# ── Content hashing ───────────────────────────────────────────────────────────

from app.services.ingestion.hash_utils import sha256_hex


def test_hash_is_deterministic():
    data = b"hello world"
    assert sha256_hex(data) == sha256_hex(data)


def test_hash_correct_length():
    assert len(sha256_hex(b"test")) == 64


def test_hash_differs_for_different_content():
    assert sha256_hex(b"aaa") != sha256_hex(b"bbb")


def test_hash_known_value():
    # sha256("") == e3b0c44298fc1c149afb...
    result = sha256_hex(b"")
    assert result == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


# ── Document type detection ───────────────────────────────────────────────────

from app.services.ingestion.document_type import detect_document_type


def test_detect_html_by_content_type():
    assert detect_document_type("https://example.gov.il/page", "text/html; charset=utf-8") == "html"


def test_detect_pdf_by_content_type():
    assert detect_document_type("https://example.gov.il/doc", "application/pdf") == "pdf"


def test_detect_docx_by_content_type():
    ct = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert detect_document_type("https://example.gov.il/doc", ct) == "docx"


def test_detect_xlsx_by_content_type():
    ct = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert detect_document_type("https://example.gov.il/doc", ct) == "xlsx"


def test_detect_pdf_by_url_extension():
    assert detect_document_type("https://example.gov.il/document.pdf") == "pdf"


def test_detect_html_by_url_extension():
    assert detect_document_type("https://example.gov.il/index.html") == "html"


def test_detect_docx_by_url_extension():
    assert detect_document_type("https://example.gov.il/file.docx") == "docx"


def test_detect_unknown_for_unrecognized():
    assert detect_document_type("https://example.gov.il/file.csv") == "unknown"


def test_content_type_takes_precedence_over_extension():
    # URL says .pdf but content-type says html
    assert detect_document_type("https://example.gov.il/file.pdf", "text/html") == "html"


# ── Downloader ────────────────────────────────────────────────────────────────

from app.services.ingestion.downloader import fetch_url, MAX_BYTES


@pytest.mark.asyncio
async def test_fetch_url_success():
    import httpx
    content = b"<html>hello</html>"

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "text/html", "etag": '"abc"', "last-modified": "Mon, 16 Jun 2026 00:00:00 GMT"}

    async def _aiter_bytes(chunk_size=None):
        yield content

    mock_response.aiter_bytes = _aiter_bytes
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_client = MagicMock()
    mock_client.stream.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.ingestion.downloader.httpx.AsyncClient", return_value=mock_client):
        result = await fetch_url("https://example.gov.il/page")

    assert result.error is None
    assert result.status_code == 200
    assert result.content == content
    assert result.content_type == "text/html"
    assert result.etag == '"abc"'


@pytest.mark.asyncio
async def test_fetch_url_network_error():
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(side_effect=Exception("connection refused"))
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.ingestion.downloader.httpx.AsyncClient", return_value=mock_client):
        result = await fetch_url("https://example.gov.il/page")

    assert result.error is not None
    assert result.content is None
    assert result.status_code is None


@pytest.mark.asyncio
async def test_fetch_url_max_size_exceeded():
    import httpx

    large_chunk = b"x" * (MAX_BYTES + 1)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {}

    async def _aiter_bytes(chunk_size=None):
        yield large_chunk

    mock_response.aiter_bytes = _aiter_bytes
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_client = MagicMock()
    mock_client.stream.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.ingestion.downloader.httpx.AsyncClient", return_value=mock_client):
        result = await fetch_url("https://example.gov.il/huge")

    assert result.content is None
    assert result.error is not None
    assert "exceeded" in result.error.lower() or "size" in result.error.lower()
