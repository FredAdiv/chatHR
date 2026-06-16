"""Unit tests for parsing helper modules: HTML, PDF, DOCX, XLSX, unknown, dispatcher."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api"))

import pytest
from app.services.parsing.base import MAX_TEXT_BYTES, CURRENT_PARSER_VERSION
from app.services.parsing.html_parser import parse_html
from app.services.parsing.unknown_parser import parse_unknown
from app.services.parsing.dispatcher import parse_document_bytes


# ── HTML parser ───────────────────────────────────────────────────────────────

def test_html_extracts_visible_text():
    content = b"<html><body><h1>Hello</h1><p>World</p></body></html>"
    result = parse_html(content)
    assert result.error is None
    assert "Hello" in result.text
    assert "World" in result.text


def test_html_removes_script_tags():
    content = b"<html><body><script>alert('xss')</script><p>Safe</p></body></html>"
    result = parse_html(content)
    assert result.error is None
    assert "alert" not in result.text
    assert "xss" not in result.text
    assert "Safe" in result.text


def test_html_removes_style_tags():
    content = b"<html><head><style>.x { color: red; }</style></head><body><p>Text</p></body></html>"
    result = parse_html(content)
    assert result.error is None
    assert "color" not in result.text
    assert "Text" in result.text


def test_html_parser_name_and_version():
    content = b"<html><body><p>test</p></body></html>"
    result = parse_html(content)
    assert result.parser_name == "html"
    assert result.parser_version == CURRENT_PARSER_VERSION


def test_html_does_not_log_full_content(caplog):
    content = b"<html><body><p>secret content here</p></body></html>"
    with caplog.at_level("DEBUG"):
        parse_html(content)
    assert "secret content here" not in caplog.text


def test_html_truncates_huge_content():
    huge = b"<html><body>" + b"<p>" + b"x" * MAX_TEXT_BYTES + b"</p></body></html>"
    result = parse_html(huge)
    assert result.error is None
    assert len(result.text.encode("utf-8")) <= MAX_TEXT_BYTES


# ── Unknown / text fallback parser ───────────────────────────────────────────

def test_unknown_utf8_text_decoded():
    content = "Hello government document".encode("utf-8")
    result = parse_unknown(content)
    assert result.error is None
    assert "Hello" in result.text
    assert result.parser_name == "unknown"


def test_unknown_binary_content_fails_safely():
    # Null bytes interspersed with other binary data
    binary = bytes(range(256)) * 10
    result = parse_unknown(binary)
    assert result.error is not None
    assert result.text == ""


def test_unknown_empty_bytes_returns_empty_text():
    result = parse_unknown(b"")
    # Empty string is valid UTF-8 text
    assert result.error is None
    assert result.text == ""


# ── Dispatcher ────────────────────────────────────────────────────────────────

def test_dispatcher_routes_html():
    content = b"<html><body><p>government policy</p></body></html>"
    result = parse_document_bytes(content, "html")
    assert result.parser_name == "html"
    assert result.error is None


def test_dispatcher_routes_unknown():
    content = b"plain text document"
    result = parse_document_bytes(content, "unknown")
    assert result.parser_name == "unknown"
    assert result.error is None


def test_dispatcher_unknown_type_falls_back_to_unknown_parser():
    content = b"some text"
    result = parse_document_bytes(content, "csv")
    assert result.parser_name == "unknown"


def test_dispatcher_pdf_returns_result():
    result = parse_document_bytes(b"%PDF-1.4 fake", "pdf")
    assert result.parser_name == "pdf"
    # May succeed or fail depending on content — must not raise


def test_dispatcher_docx_returns_result():
    result = parse_document_bytes(b"PK\x03\x04 fake zip", "docx")
    assert result.parser_name == "docx"


def test_dispatcher_xlsx_returns_result():
    result = parse_document_bytes(b"PK\x03\x04 fake xlsx", "xlsx")
    assert result.parser_name == "xlsx"
