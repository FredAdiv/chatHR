"""Fallback parser: attempts UTF-8 text decode for unknown document types."""
from app.services.parsing.base import MAX_TEXT_BYTES, CURRENT_PARSER_VERSION, ParserResult

PARSER_NAME = "unknown"


def parse_unknown(content: bytes) -> ParserResult:
    # Null bytes are a reliable signal of binary content (rare in real text documents)
    if b"\x00" in content:
        return ParserResult(
            text="", parser_name=PARSER_NAME, parser_version=CURRENT_PARSER_VERSION,
            error="Content appears to be binary (contains null bytes) — text extraction not supported",
        )

    try:
        text = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        try:
            text = content.decode("latin-1", errors="replace")
            # Heuristic: high proportion of non-printable control chars → binary
            non_printable = sum(1 for c in text if ord(c) < 32 and c not in "\n\r\t")
            if non_printable > len(text) * 0.1:
                return ParserResult(
                    text="", parser_name=PARSER_NAME, parser_version=CURRENT_PARSER_VERSION,
                    error="Content appears to be binary — text extraction not supported",
                )
        except Exception as exc:
            return ParserResult(
                text="", parser_name=PARSER_NAME, parser_version=CURRENT_PARSER_VERSION,
                error=f"Text decode failed: {str(exc)[:500]}",
            )

    if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
        text = text.encode("utf-8")[:MAX_TEXT_BYTES].decode("utf-8", errors="ignore")

    return ParserResult(
        text=text,
        parser_name=PARSER_NAME,
        parser_version=CURRENT_PARSER_VERSION,
        metadata_json={"encoding": "utf-8"},
    )
