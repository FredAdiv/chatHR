"""PDF parser: extracts text using pypdf. No OCR, no binary data in DB."""
from app.services.parsing.base import MAX_TEXT_BYTES, CURRENT_PARSER_VERSION, ParserResult

PARSER_NAME = "pdf"


def parse_pdf(content: bytes) -> ParserResult:
    try:
        import io
        from pypdf import PdfReader  # type: ignore[import-untyped]
    except ImportError:
        return ParserResult(
            text="", parser_name=PARSER_NAME, parser_version=CURRENT_PARSER_VERSION,
            error="pypdf not installed — PDF parsing is not available",
        )

    try:
        reader = PdfReader(io.BytesIO(content))
        pages_text = []
        for page in reader.pages:
            page_text = page.extract_text() or ""
            pages_text.append(page_text)

        text = "\n".join(pages_text)

        if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
            text = text.encode("utf-8")[:MAX_TEXT_BYTES].decode("utf-8", errors="ignore")

        return ParserResult(
            text=text,
            parser_name=PARSER_NAME,
            parser_version=CURRENT_PARSER_VERSION,
            metadata_json={"page_count": len(reader.pages)},
        )
    except Exception as exc:
        return ParserResult(
            text="", parser_name=PARSER_NAME, parser_version=CURRENT_PARSER_VERSION,
            error=f"PDF parse error: {str(exc)[:500]}",
        )
