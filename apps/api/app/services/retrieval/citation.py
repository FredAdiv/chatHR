"""Citation metadata builder for retrieved chunks.

Used by retrieval results and future RAG answers.
No LLM calls, no external services.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CitationMetadata:
    """Citation-ready fields for a retrieved chunk."""
    source_url: str | None
    source_title: str | None
    knowledge_source_id: str
    knowledge_source_name: str
    authority_level: int
    section_title: str | None
    page_number: int | None
    chunk_index: int
    document_type: str | None


def build_citation_metadata(
    *,
    chunk_index: int,
    section_title: str | None,
    page_number: int | None,
    source_url: str | None,
    source_title: str | None,
    document_type: str | None,
    knowledge_source_id: str,
    knowledge_source_name: str,
    authority_level: int,
) -> CitationMetadata:
    """Build citation metadata from retrieval row fields.

    All field values come from the DB join — no text generation, no LLM calls.
    """
    return CitationMetadata(
        source_url=source_url,
        source_title=source_title,
        knowledge_source_id=knowledge_source_id,
        knowledge_source_name=knowledge_source_name,
        authority_level=authority_level,
        section_title=section_title,
        page_number=page_number,
        chunk_index=chunk_index,
        document_type=document_type,
    )
