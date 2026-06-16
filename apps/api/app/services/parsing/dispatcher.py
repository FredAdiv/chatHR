"""Parser dispatcher: routes document bytes to the appropriate parser by document_type."""
from app.services.parsing.base import CURRENT_PARSER_VERSION, ParserResult
from app.services.parsing.docx_parser import parse_docx
from app.services.parsing.html_parser import parse_html
from app.services.parsing.pdf_parser import parse_pdf
from app.services.parsing.unknown_parser import parse_unknown
from app.services.parsing.xlsx_parser import parse_xlsx


def parse_document_bytes(
    content: bytes,
    document_type: str,
    content_type: str | None = None,
) -> ParserResult:
    """
    Parse document bytes according to document_type.

    Supported types: html, pdf, docx, xlsx, unknown.
    Never executes document content. Does not fetch external resources.
    Does not perform OCR. Raw bytes are not stored in DB or logs.
    """
    dtype = (document_type or "unknown").lower()

    if dtype == "html":
        return parse_html(content)
    elif dtype == "pdf":
        return parse_pdf(content)
    elif dtype == "docx":
        return parse_docx(content)
    elif dtype == "xlsx":
        return parse_xlsx(content)
    else:
        return parse_unknown(content)
