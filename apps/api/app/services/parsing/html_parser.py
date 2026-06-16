"""HTML parser: extracts visible text, removes script/style tags."""
from app.services.parsing.base import MAX_TEXT_BYTES, CURRENT_PARSER_VERSION, ParserResult

PARSER_NAME = "html"


def parse_html(content: bytes) -> ParserResult:
    try:
        from bs4 import BeautifulSoup  # type: ignore[import-untyped]
    except ImportError:
        return ParserResult(
            text="", parser_name=PARSER_NAME, parser_version=CURRENT_PARSER_VERSION,
            error="beautifulsoup4 not installed",
        )

    try:
        soup = BeautifulSoup(content, "html.parser")

        for tag in soup(["script", "style", "noscript", "head"]):
            tag.decompose()

        text = soup.get_text(separator="\n", strip=True)

        if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
            text = text.encode("utf-8")[:MAX_TEXT_BYTES].decode("utf-8", errors="ignore")

        return ParserResult(
            text=text,
            parser_name=PARSER_NAME,
            parser_version=CURRENT_PARSER_VERSION,
            metadata_json={"source": "html"},
        )
    except Exception as exc:
        return ParserResult(
            text="", parser_name=PARSER_NAME, parser_version=CURRENT_PARSER_VERSION,
            error=f"HTML parse error: {str(exc)[:500]}",
        )
